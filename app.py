"""Vercel entry point for the read-only results dashboard.

Vercel's Python runtime looks for a FastAPI instance named ``app`` in a
root-level ``app.py``. Every path is resolved from this file, not from the
working directory, so the committed run files and audio are found wherever
the function runs. Locally, ``voicebench dashboard`` / ``make run`` are
unchanged; ``uvicorn app:app`` also serves this same app.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# The package lives in src/ and is not necessarily pip-installed on Vercel.
_SRC = str(ROOT / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from voicebench.dashboard.app import create_app  # noqa: E402

app = create_app(
    results_dir=ROOT / "results",
    audio_dir=ROOT / "audio" / "v1",
    repo_root=ROOT,
    realspeech_dir=ROOT / "results" / "realspeech",
    gnani_dir=ROOT / "results" / "gnani",
)
