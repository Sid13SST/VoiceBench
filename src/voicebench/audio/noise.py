"""Deterministic synthetic noise. No recorded noise is used anywhere."""

from __future__ import annotations

import numpy as np


def white_noise(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


def pink_noise(n: int, seed: int) -> np.ndarray:
    """1/f noise made by shaping white noise in the frequency domain."""
    rng = np.random.default_rng(seed)
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs = np.arange(len(spectrum), dtype=np.float64)
    freqs[0] = 1.0  # avoid dividing by zero at DC
    spectrum /= np.sqrt(freqs)
    spectrum[0] = 0.0
    pink = np.fft.irfft(spectrum, n)
    return (pink / np.std(pink)).astype(np.float32)


def babble_noise(talkers: list[np.ndarray], n: int, seed: int) -> np.ndarray:
    """Sum several speech clips, each looped and started at a random offset.

    ``talkers`` are synthetic TTS utterances of *other* scenarios, so the
    babble contains no real voices.
    """
    if len(talkers) < 2:
        raise ValueError("babble needs at least two talkers")
    rng = np.random.default_rng(seed)
    out = np.zeros(n, dtype=np.float64)
    for clip in talkers:
        clip = clip / (np.std(clip) or 1.0)
        start = int(rng.integers(0, len(clip)))
        looped = np.tile(np.roll(clip, -start), int(np.ceil(n / len(clip))) + 1)[:n]
        out += looped
    return (out / np.std(out)).astype(np.float32)


def make_noise(kind: str, n: int, seed: int, talkers: list[np.ndarray] | None = None) -> np.ndarray:
    if kind == "white":
        return white_noise(n, seed)
    if kind == "pink":
        return pink_noise(n, seed)
    if kind == "babble":
        return babble_noise(talkers or [], n, seed)
    raise ValueError(f"unknown noise type {kind!r}")
