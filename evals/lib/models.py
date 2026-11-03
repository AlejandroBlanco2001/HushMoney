"""Nebius model definitions and shared paths."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).parent.parent.parent
API_BASE = 'https://api.studio.nebius.com/v1'

# Local OpenAI-compatible endpoint (Ollama by default). Override with OLLAMA_BASE_URL.
OLLAMA_BASE = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434/v1')

# Cloud tiers served by Nebius. `base_url` omitted → api.chat_completion uses API_BASE.
MODELS: list[dict[str, Any]] = [
    {
        'key': 'nano',
        'id': 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
        'label': 'Nano  (30B / 3B active)',
        'input_per_m': 0.06,
        'output_per_m': 0.24,
        'local': False,
    },
    {
        'key': 'super',
        'id': 'nvidia/nemotron-3-super-120b-a12b',
        'label': 'Super (120B / 12B active)',
        'input_per_m': 0.30,
        'output_per_m': 0.90,
        'local': False,
    },
    {
        'key': 'ultra',
        'id': 'nvidia/Nemotron-3-Ultra-550b-a55b',
        'label': 'Ultra (550B / 55B active)',
        'input_per_m': 1.00,
        'output_per_m': 3.00,
        'local': False,
    },
]

# Local SLM candidates served via Ollama — the fit-on-a-normal-PC tier (8-16GB VRAM).
# Settled on the Gemma 4 family: E2B/E4B are edge models whose "E" sizes are *effective*
# active memory (Per-Layer Embeddings) built for ~8GB devices; 12B is the step up.
# VRAM figures are the default Ollama quant. Cost is $0 (runs on your box).
# Pull before running:  make ollama-pull   then: run.py --local
LOCAL_MODELS: list[dict[str, Any]] = [
    {
        'key': 'g4_e2b',
        'id': 'gemma4:e2b',
        'label': 'Gemma4-E2B   (2.3B eff ~5GB)',
        'input_per_m': 0.0,
        'output_per_m': 0.0,
        'local': True,
        'base_url': OLLAMA_BASE,
    },
    {
        'key': 'g4_e4b',
        'id': 'gemma4:e4b',
        'label': 'Gemma4-E4B   (4.5B eff ~7GB)',
        'input_per_m': 0.0,
        'output_per_m': 0.0,
        'local': True,
        'base_url': OLLAMA_BASE,
    },
    {
        'key': 'gemma4_12b',
        'id': 'gemma4:12b',
        'label': 'Gemma4-12B   (~7.7GB)',
        'input_per_m': 0.0,
        'output_per_m': 0.0,
        'local': True,
        'base_url': OLLAMA_BASE,
    },
]

# Tags pulled by `make ollama-pull` — keep in sync with the ids above.
LOCAL_MODEL_TAGS: list[str] = [m['id'] for m in LOCAL_MODELS]

MODELS_BY_KEY: dict[str, dict[str, Any]] = {m['key']: m for m in (*MODELS, *LOCAL_MODELS)}
