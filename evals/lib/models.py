"""Nebius model definitions and shared paths."""
from __future__ import annotations

from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent.parent
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

MODELS_BY_KEY: dict[str, dict[str, Any]] = {m["key"]: m for m in MODELS}
