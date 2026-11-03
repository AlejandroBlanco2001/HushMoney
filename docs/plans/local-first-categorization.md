# HushMoney: local-first, retrieval-augmented categorization + agent

## Context

Today one cloud model (Nebius `Nemotron-Nano-30B-A3B`) does everything. We want to (a) move the
narrow, high-volume **merchant categorization** onto a small **local** model, (b) close the
accuracy gap on **long-tail local merchants** (tiny minimarkets, local eateries) that no model
knows from the name, and (c) make the **agent loop** runnable local-first with cloud fallback.

An eval over 47 labeled Colombian-merchant fixtures (`evals/model_selection/`) showed
**Gemma 4 E4B** (~4.5B eff, ~7 GB, fits a normal PC) is the right local categorizer — best
accuracy-per-latency, strongest on `needs_clarification`. The remaining gap is **local-brand
knowledge, not model size**, so the fix is **retrieval + cache**, not a bigger model.

**Key constraint:** there is *no corpus of how merchants actually appear in real SMS vs email
across banks* — fixtures cover only Bancolombia. So a hand-authored gazetteer is out. Instead:
**normalize the raw string → online lookup → learn the result into the `merchants` cache**, which
becomes the gazetteer over time. Normalization can only be tuned against real samples, so a **data
workstream** is a first-class phase.

Done already (this effort): taxonomy extended (`restaurants`/`groceries`/`delivery` + hypermarket→
`needs_clarification`) in `config/schema.sql` and `skills/categorizer/scripts/categorize_merchant.py`;
eval harness gained local/Ollama support, labeled golden set, auto-scoring, parallelism, JSON-mode
config (`evals/lib/*`, `evals/model_selection/*`, `Makefile`).

Existing machinery to build on:
- Categorizer pipeline (`skills/categorizer/SKILL.md`): `lookup_cached_category.py` → LLM
  `categorize_merchant.py` / keyword `get_categories.py` → `save_merchant.py`; `gateway_server.py`
  auto-categorizes from the cache.
- Parsing/learning (`forwarder/src/forwarder/`): `sanitizer/models.py` yields the clean `merchant`
  field; `learning/{fingerprint,unmatched,inbox,store,lifecycle}.py` detect unmatched messages and
  queue patterns to the pattern-inbox. Merchant is PII-sanitized before it leaves the sanitizer
  (`docs/rules/security.md`).

---

## Phase 0 — Local model infrastructure (Ollama in the stack)  ← IN PROGRESS

**Goal:** make it possible to run the categorizer against a local model, agent stays cloud.

- Add an opt-in `ollama` service to `docker-compose.yml` under a `local-llm` profile (mirrors the
  `telemetry` profile for openobserve) + an `ollama-models` volume; localhost `11434` exposed so
  host-side evals can reuse it.
- Categorizer-only model override: `CATEGORIZER_BASE_URL` / `CATEGORIZER_MODEL` (unset → fall back
  to the agent's `OPENAI_BASE_URL` / `HERMES_MODEL`), wired in `categorize_merchant.py` with
  keyless-local support and JSON-mode + higher token cap for local models. Default behavior (cloud)
  unchanged.
- Telemetry: local calls bypass `llm_proxy.py` (accepted gap; latency already measured in evals).
  Proxy no-body-logging invariant (ADR-0002) preserved.

**Files:** `docker-compose.yml`, `.env.example`, `skills/categorizer/scripts/categorize_merchant.py`,
`Makefile` (reuse `ollama-pull`).
**Verify:** `podman compose --profile local-llm up -d ollama`; pull `gemma4:e4b`; set
`CATEGORIZER_*`; `make smoke` and confirm categorization via the local model.

---

## Phase 1 — Data workstream: real merchant strings + normalization

**Goal:** learn how merchants actually appear across banks/channels; build the normalization
retrieval depends on.

- Gather real (redacted) SMS/email samples beyond Bancolombia using the existing unmatched pipeline
  (`learning/unmatched.py`, `learning/inbox.py`, pattern-inbox); extend `tests/fixtures/emails/`
  and `tests/fixtures/sms/` following the `*.eml`/`*.txt` + `*.expected.json` convention.
- Add one shared `normalize_merchant(raw) -> key` (strip location/store-number/ref noise, collapse
  whitespace, upper-case) — current cache key is only UPPER+whitespace. Place where both cache and
  online lookup import it (`skills/categorizer/scripts/_merchant.py`); reuse in
  `lookup_cached_category.py` + `save_merchant.py` for a consistent key.
- Tune normalization against the gathered fixtures (SMS/email variants → one key). Input is the
  sanitizer's PII-safe `merchant` field.

**Verify:** unit test that SMS/email variants normalize to one key; `make test`.

---

## Phase 2 — Retrieval layer (normalize → online lookup → cache learns)

**Goal:** resolve unknown/`needs_clarification` merchants via free online lookup; cache so each is
looked up once. No hand-authored list — the cache is the gazetteer.

- New `skills/categorizer/scripts/lookup_merchant_web.py`: normalize, query **OSM/Nominatim (free)**
  fuzzily, map shop/amenity tags → taxonomy slug (`get_categories.py`), return
  `{found, category, source}`. Respect Nominatim policy (User-Agent, ≤1 req/s, cache); degrade to
  `needs_clarification` on miss/offline.
- Wire into `SKILL.md` between name-inference and cache-write: SLM `needs_clarification`/low-conf →
  web lookup → confident hit `save_merchant.py` (next txn cache-served); miss → existing
  user-clarification flow (answer also cached). Lookup only fires on cache miss.

**Verify:** new real fixtures resolve via OSM on first encounter, cache-served on second (no
network); `make eval-local-models` shows no regression.

---

## Phase 3 — Agent-capability eval + local-first agent (cloud fallback)

**Goal:** decide on data whether the agent loop can run local; wire local-first + fallback.

- Eval first: new `evals/agent/` mirroring `model_selection/run.py` but scoring tool-call validity +
  task completion, using scenarios from `evals/{bank_learning,debt_tracker,summaries}`. Candidate
  local models: tool-tuned `qwen3:8b` / Hermes-family / `qwen3:30b-a3b` (NOT Gemma-edge). Reuse
  `evals/lib/{api,models}.py`, `ollama_config.json` JSON-mode pattern.
- Reliable tool-calls via structured output / strict schemas. Shrink the agent's job by offloading
  to specialized scripts (categorizer/retrieval). Point agent `OPENAI_BASE_URL` at Ollama with a
  fallback to cloud `Nemotron-Nano-30B-A3B` on validation failure / low-confidence / multi-step;
  keep forwarder proposal validation as the safety net; offline → defer/ask.

**Verify:** agent eval cloud vs local; `make run` + `make smoke` with agent local, confirm tool
calls execute and fallback triggers.

---

## Phase 4 — Fine-tune from confirmed local labels (optional, last)

**Goal:** specialize a small model to your schema/brands if a gap remains.

- Data source (security-critical): NOT proxy capture (`llm_proxy.py`/ADR-0002 forbid reading
  bodies). Build pairs from stored, user-confirmed local data: `merchants`, `learned_patterns`,
  `golden_co.jsonl`. New `evals/finetune/build_dataset.py` reuses `categorize_merchant.py`'s prompt
  builder. LoRA-tune E4B / `qwen3:4b` off-box; import adapter; adopt only if it beats base on the
  golden set.

---

## Sequencing & risks

1. **Phase 0 + Phase 1 together** (infra + the data/normalization retrieval depends on).
2. **Phase 2** once normalization holds on real samples — the accuracy mover.
3. **Phase 3** is largest, gated on the agent eval — never swap the prod agent before data.
4. **Phase 4** only if a gap remains.

**Risks:** normalization quality is bounded by how many real bank/channel samples Phase 1 gathers.
Nominatim coverage of tiny shops is patchy (true unknowns stay `needs_clarification` → user → cache).
Privacy: OSM lookups send the PII-sanitized merchant string externally — a conscious choice; never
send amounts. 12B is off the table locally (latency). Local calls currently bypass the telemetry
proxy (accepted gap).
