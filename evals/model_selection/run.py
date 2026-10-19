#!/usr/bin/env python3
"""
Model selection experiment for Hermes categorizer.

Sends each fixture's clean payload to three NVIDIA Nemotron tiers on Nebius,
records the predicted category, latency, and token usage, then writes results.json.

You manually fill in `correct_category` in results.json, then run --score to get
the full accuracy / latency / cost comparison.

The labeled results.json doubles as the seed for skills/categorizer/evals/golden.jsonl.

Usage:
    # Add NEBIUS_API_KEY to .env at the repo root (copy from .env.example)
    python evals/model_selection/run.py              # run experiment → results.json
    python evals/model_selection/run.py --score      # score labeled results.json
    python evals/model_selection/run.py --dry-run    # verify fixture discovery, no API calls
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    # create_default_context() sets OpenSSL search paths but doesn't explicitly
    # load the cert file — do it manually so verification actually works
    for candidate in [
        os.environ.get("NIX_SSL_CERT_FILE", ""),
        os.environ.get("SSL_CERT_FILE", ""),
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/ssl/certs/ca-bundle.crt",
    ]:
        if candidate and Path(candidate).exists():
            ctx.load_verify_locations(cafile=candidate)
            break
    return ctx


# ── Config ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent.parent
RESULTS_FILE = Path(__file__).parent / "results.json"
API_BASE = "https://api.studio.nebius.com/v1"

MODELS: list[dict[str, Any]] = [
    {
        "key": "nano",
        "id": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        "label": "Nano  (30B / 3B active)",
        "input_per_m": 0.06,
        "output_per_m": 0.24,
    },
    {
        "key": "super",
        "id": "nvidia/nemotron-3-super-120b-a12b",
        "label": "Super (120B / 12B active)",
        "input_per_m": 0.30,
        "output_per_m": 0.90,
    },
    {
        "key": "ultra",
        "id": "nvidia/Nemotron-3-Ultra-550b-a55b",
        "label": "Ultra (550B / 55B active)",
        "input_per_m": 1.00,
        "output_per_m": 3.00,
    },
]

# Default category set shipped with the app — user can add/remove via Telegram.
# In production the categorizer skill reads this list from SQLite at call time.
STARTER_CATEGORIES = [
    "dining",
    "groceries",
    "food_delivery",
    "transport",
    "fuel",
    "shopping",
    "entertainment",
    "subscriptions",
    "utilities",
    "health",
    "fitness",
    "travel",
    "accommodation",
    "transfer",
    "cash",
    "services",
    "other",
]


def make_system_prompt(categories: list[str]) -> str:
    cats = ", ".join(categories)
    return f"""You are a transaction categorizer for a personal finance app.

Given a clean transaction payload as JSON, respond with ONLY a JSON object.

Confident case:
{{"category": "<one of the valid categories>"}}

Uncertain case — merchant is a payment gateway or processor where the actual
purchase purpose cannot be determined from the name alone (e.g. PayU, Stripe,
Adyen, or any generic capital/financial services company):
{{"category": "needs_clarification", "reason": "payment_gateway"}}

Valid categories: {cats}

Rules:
- transaction_type "transfer_out" or "transfer_in" → always "transfer"
- transaction_type "cash" → always "cash"
- Ride-hailing apps → "transport"
- Food delivery platforms → "food_delivery"
- Streaming, gaming, cinema → "entertainment" or "subscriptions"
- Pharmacies, clinics → "health"
- Utility and telecom providers → "utilities"
- No merchant field → infer from transaction_type

Respond with only the JSON object, no explanation."""


# ── Fixtures ───────────────────────────────────────────────────────────────────


def discover_fixtures() -> list[dict[str, Any]]:
    root = REPO_ROOT / "tests" / "fixtures"
    cases: list[dict[str, Any]] = []

    for path in sorted(root.rglob("*.expected.json")):
        rel = path.relative_to(root)
        key = str(rel).replace(".expected.json", "")

        with path.open() as f:
            payload = json.load(f)

        cases.append(
            {
                "fixture": key,
                "input": payload,
                "correct_category": None,  # fill in manually after running
                "models": {},
            }
        )

    return cases


# ── API ────────────────────────────────────────────────────────────────────────


def _extract_result(text: str) -> dict[str, str]:
    """Pull category (and optional reason) from a model response.

    Returns {"category": ..., "reason": ...} — reason is empty string when absent.
    Handles reasoning models that prepend a monologue before the JSON.
    """
    import re

    def _parse(obj: dict[str, Any]) -> dict[str, str]:
        return {
            "category": str(obj.get("category", "unknown")).lower().strip(),
            "reason": str(obj.get("reason", "")),
        }

    # Happy path: entire response is valid JSON
    try:
        return _parse(json.loads(text))
    except (json.JSONDecodeError, AttributeError):
        pass

    # Reasoning model: find the last {...} block that contains "category"
    matches = re.findall(r'\{[^{}]*"category"\s*:[^{}]*\}', text)
    if matches:
        try:
            return _parse(json.loads(matches[-1]))
        except json.JSONDecodeError:
            cat_match = re.search(r'"category"\s*:\s*"([^"]+)"', matches[-1])
            if cat_match:
                return {"category": cat_match.group(1).lower().strip(), "reason": ""}

    # Last resort: scan for any known category word in the full text
    all_categories = STARTER_CATEGORIES + ["needs_clarification"]
    for cat in all_categories:
        if re.search(rf"\b{re.escape(cat)}\b", text, re.IGNORECASE):
            return {"category": cat, "reason": ""}

    return {"category": "unknown", "reason": ""}


def call_model(
    api_key: str,
    model_id: str,
    payload: dict[str, Any],
    categories: list[str] = STARTER_CATEGORIES,
) -> dict[str, Any]:
    body = json.dumps(
        {
            "model": model_id,
            "messages": [
                {"role": "system", "content": make_system_prompt(categories)},
                {"role": "user", "content": json.dumps(payload)},
            ],
            "temperature": 0,
            "max_tokens": 256,  # enough for reasoning models that prepend thought text
        }
    ).encode()

    req = urllib.request.Request(
        f"{API_BASE}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
        latency_ms = round((time.perf_counter() - t0) * 1000)
        data = json.loads(resp.read())

    message = data["choices"][0]["message"]
    # content can be None when the model uses a refusal field or reasoning_content
    content = message.get("content") or message.get("reasoning_content") or ""
    content = content.strip()
    usage = data.get("usage", {})

    result = _extract_result(content)

    return {
        "category": result["category"],
        "reason": result["reason"],
        "latency_ms": latency_ms,
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "error": None,
    }


# ── Run ────────────────────────────────────────────────────────────────────────


def run_experiment(dry_run: bool = False) -> None:
    if dry_run:
        print("[dry-run: fixture discovery only, no API calls]\n")
    else:
        _load_dotenv(REPO_ROOT / ".env")
        api_key = os.environ.get("NEBIUS_API_KEY", "")
        if not api_key:
            print("ERROR: NEBIUS_API_KEY not set", file=sys.stderr)
            sys.exit(1)

    cases = discover_fixtures()
    print(f"Found {len(cases)} fixtures\n")

    for case in cases:
        print(f"  {case['fixture']}")

        if dry_run:
            for model in MODELS:
                print(f"    [{model['key']:5}] (skipped)")
            print()
            continue

        for model in MODELS:
            try:
                result = call_model(api_key, model["id"], case["input"])  # type: ignore[possibly-undefined]
                case["models"][model["key"]] = result
                label = result["category"]
                if result.get("reason"):
                    label = f"{label} ({result['reason']})"
                print(
                    f"    [{model['key']:5}] {label:<30} "
                    f"{result['latency_ms']:>5}ms  "
                    f"{result['input_tokens']}+{result['output_tokens']} tok"
                )
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}: {e.reason}"
                case["models"][model["key"]] = {
                    "category": None,
                    "reason": "",
                    "latency_ms": None,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "error": err,
                }
                print(f"    [{model['key']:5}] ERROR: {err}")
            except Exception as e:
                case["models"][model["key"]] = {
                    "category": None,
                    "reason": "",
                    "latency_ms": None,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "error": str(e),
                }
                print(f"    [{model['key']:5}] ERROR: {e}")

            time.sleep(0.25)  # avoid hammering the endpoint between models

        print()

    if not dry_run:
        with RESULTS_FILE.open("w") as f:
            json.dump(cases, f, indent=2, ensure_ascii=False)

        print(f"Written to {RESULTS_FILE.relative_to(REPO_ROOT)}")
        print()
        print("Next steps:")
        print("  1. Open results.json")
        print('  2. Fill in "correct_category" for each fixture')
        print("  3. Run:  python evals/model_selection/run.py --score")
        print()
        print(
            "Tip: the labeled file is the seed for skills/categorizer/evals/golden.jsonl"
        )


# ── Score ──────────────────────────────────────────────────────────────────────


def score() -> None:
    if not RESULTS_FILE.exists():
        print("No results.json found — run the experiment first.", file=sys.stderr)
        sys.exit(1)

    with RESULTS_FILE.open() as f:
        cases: list[dict[str, Any]] = json.load(f)

    labeled = [c for c in cases if c.get("correct_category")]
    if not labeled:
        print(
            "No labeled cases yet — fill in 'correct_category' in results.json first."
        )
        sys.exit(0)

    print(f"\n{'=' * 76}")
    print(
        f"HERMES MODEL SELECTION  ({len(labeled)} labeled / {len(cases)} total fixtures)"
    )
    print(f"{'=' * 76}\n")

    print(
        f"  {'Model':<28} {'Acc':>5}  {'Avg latency':>11}  {'Tokens in/out':>14}  {'$/1K calls':>10}"
    )
    print(f"  {'-' * 74}")

    for model in MODELS:
        key = model["key"]
        model_cases = [
            c
            for c in labeled
            if key in c["models"] and not c["models"][key].get("error")
        ]

        if not model_cases:
            print(f"  {model['label']:<28}  no data")
            continue

        correct = sum(
            1
            for c in model_cases
            if c["models"][key]["category"] == c["correct_category"]
        )
        accuracy = correct / len(model_cases)

        latencies = [
            c["models"][key]["latency_ms"]
            for c in model_cases
            if c["models"][key]["latency_ms"]
        ]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0

        avg_in = sum(c["models"][key]["input_tokens"] for c in model_cases) / len(
            model_cases
        )
        avg_out = sum(c["models"][key]["output_tokens"] for c in model_cases) / len(
            model_cases
        )

        cost_per_call = (avg_in / 1_000_000) * model["input_per_m"] + (
            avg_out / 1_000_000
        ) * model["output_per_m"]

        print(
            f"  {model['label']:<28} {accuracy:>5.1%}  {avg_latency:>9.0f}ms  "
            f"{avg_in:>6.0f}/{avg_out:<7.0f}  ${cost_per_call * 1000:.4f}"
        )

    print()
    print("FIXTURE BREAKDOWN\n")
    for case in labeled:
        correct_cat = case["correct_category"]
        line = f"  {case['fixture']:<48} label={correct_cat:<18}"
        for model in MODELS:
            key = model["key"]
            got = case["models"].get(key, {}).get("category") or "err"
            mark = "✓" if got == correct_cat else "✗"
            line += f"  {mark}{key}={got}"
        print(line)

    print()


# ── Entry ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--score" in sys.argv:
        score()
    elif "--dry-run" in sys.argv:
        run_experiment(dry_run=True)
    else:
        run_experiment()
