"""Small, dependency-light signal helpers. All audio is mono float32 in [-1, 1]."""

from __future__ import annotations

from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SAMPLE_RATE = 16_000  # what Whisper-family models expect


def read_wav(path: str | Path, target_sr: int = SAMPLE_RATE) -> np.ndarray:
    audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)  # downmix to mono
    return resample(audio, sr, target_sr)


def write_wav(path: str | Path, audio: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(audio, -1.0, 1.0), sr, subtype="PCM_16")


def resample(audio: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return audio.astype(np.float32, copy=False)
    g = gcd(sr_in, sr_out)
    return resample_poly(audio, sr_out // g, sr_in // g).astype(np.float32)


def power(audio: np.ndarray) -> float:
    """Mean signal power."""
    return float(np.mean(np.square(audio, dtype=np.float64)))


def snr_db(signal: np.ndarray, noise: np.ndarray) -> float:
    return 10.0 * np.log10(power(signal) / power(noise))


def mix_at_snr(signal: np.ndarray, noise: np.ndarray, target_snr_db: float) -> tuple[np.ndarray, np.ndarray]:
    """Add ``noise`` to ``signal`` so that 10*log10(P_signal / P_noise) == target.

    Power is measured over the whole clip, including the short silences that
    TTS leaves at either end. The noise is tiled or cropped to the signal
    length. Returns ``(mixture, scaled_noise)``; the mixture is *not*
    normalised so that the SNR stays exact (callers peak-normalise after).
    """
    if power(signal) == 0:
        raise ValueError("signal is silent")
    if power(noise) == 0:
        raise ValueError("noise is silent")
    noise = fit_length(noise, len(signal))
    gain = np.sqrt(power(signal) / (power(noise) * 10 ** (target_snr_db / 10)))
    scaled = (noise * gain).astype(np.float32)
    return (signal + scaled).astype(np.float32), scaled


def fit_length(audio: np.ndarray, n: int) -> np.ndarray:
    if len(audio) >= n:
        return audio[:n]
    reps = int(np.ceil(n / len(audio)))
    return np.tile(audio, reps)[:n]


def peak_normalise(audio: np.ndarray, peak: float = 0.9) -> np.ndarray:
    """Scale so the loudest sample is ``peak``. Does not change any SNR."""
    m = float(np.max(np.abs(audio)))
    return audio if m == 0 else (audio * (peak / m)).astype(np.float32)


def overlay(base: np.ndarray, top: np.ndarray, offset: int, top_gain_db: float = 0.0) -> np.ndarray:
    """Place ``top`` on ``base`` starting at sample ``offset``, extending if needed."""
    if offset < 0:
        raise ValueError("offset must be >= 0")
    n = max(len(base), offset + len(top))
    out = np.zeros(n, dtype=np.float32)
    out[: len(base)] += base
    out[offset : offset + len(top)] += top * (10 ** (top_gain_db / 20))
    return out


def max_sample_diff(a: str | Path, b: str | Path) -> int:
    """Largest absolute difference between two 16-bit WAVs, in integer steps."""
    x, sr_x = sf.read(str(a), dtype="int16")
    y, sr_y = sf.read(str(b), dtype="int16")
    if sr_x != sr_y or x.shape != y.shape:
        raise ValueError(f"different length or sample rate ({x.shape}@{sr_x} vs {y.shape}@{sr_y})")
    return int(np.max(np.abs(x.astype(np.int32) - y.astype(np.int32)), initial=0))
