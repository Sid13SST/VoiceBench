"""Word error rate and run-level aggregates."""

from __future__ import annotations

import math
from typing import Iterable, Optional

import jiwer

from voicebench.textnorm import normalise


def wer(reference: str, hypothesis: str) -> float:
    """WER after :func:`voicebench.textnorm.normalise`. Can exceed 1.0."""
    ref = normalise(reference)
    if not ref:
        raise ValueError("reference is empty after normalisation")
    hyp = normalise(hypothesis)
    if not hyp:
        return 1.0  # every reference word deleted
    return float(jiwer.wer(ref, hyp))


def corpus_wer(pairs: Iterable[tuple[str, str]]) -> float:
    """Total edits / total reference words (not a mean of per-item WERs)."""
    refs, hyps = [], []
    for ref, hyp in pairs:
        refs.append(normalise(ref))
        # jiwer rejects empty hypotheses; a placeholder token that can never
        # match a reference word gives the same edit count (1 sub + n-1 del).
        hyps.append(normalise(hyp) or "<empty>")
    if not refs:
        raise ValueError("no pairs")
    return float(jiwer.wer(refs, hyps))


def percentile(values: Iterable[float], q: float) -> Optional[float]:
    """Nearest-rank percentile (q in [0, 100]); None for no values."""
    xs = sorted(values)
    if not xs:
        return None
    if not 0 <= q <= 100:
        raise ValueError("q must be in [0, 100]")
    rank = max(1, math.ceil(q / 100 * len(xs)))
    return xs[rank - 1]
