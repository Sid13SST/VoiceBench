"""Gnani Voice QA lane: Gnani.ai's Prisma STT and Timbre TTS, run as external APIs.

Separate from the local benchmark. Every run made here calls a remote, paid
service; its run files say so (``asr_config.external_api``), are written to
``results/gnani/`` and are never merged with, averaged with or ranked against
the local Whisper runs. See docs/GNANI_QA.md.

This module imports nothing beyond the standard library, so the report,
compare and dashboard code can use :func:`external_provider` without
needing httpx.
"""

from __future__ import annotations

from typing import Any, Optional

PROVIDER = "gnani.ai"
MAX_CLIP_S = 30.0  # REST STT limit per request
COMPARABILITY = "external API run: not comparable with, and never to be averaged with, local Whisper runs"
COST_NOTE = ("external API (gnani.ai): credit per request is not published and not reported by the API, "
             "so cost_usd is not recorded; read the credit used on the app.gnani.ai Usage page")


def external_provider(asr_config: Any) -> Optional[str]:
    """The provider named in a run's ``asr_config.external_api``, or None for a local run."""
    if not isinstance(asr_config, dict):
        return None
    ext = asr_config.get("external_api")
    if not isinstance(ext, dict):
        return None
    return str(ext.get("provider") or "external")
