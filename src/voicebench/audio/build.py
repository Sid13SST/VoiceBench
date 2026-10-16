"""Turn scenarios into WAV files, recording exactly how each was made."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from voicebench.audio.noise import make_noise
from voicebench.audio.signal import SAMPLE_RATE, mix_at_snr, overlay, peak_normalise, snr_db, write_wav
from voicebench.audio.tts import EspeakTTS
from voicebench.schema import Condition, InterruptionKind, Scenario

PAD_MS = 250  # silence before and after the caller, like a real call turn
BABBLE_TALKERS = 4
# Level of the agent prompt relative to the caller in barge-in clips. The
# agent's own prompt leaking back (echo) is usually quieter than the caller.
AGENT_GAIN_DB = -6.0


@dataclass
class AudioRecord:
    id: str
    path: str
    sha256: str
    duration_s: float
    condition: str
    language: str
    caller_voice: str
    target_snr_db: Optional[float] = None
    measured_snr_db: Optional[float] = None
    noise_type: Optional[str] = None
    noise_seed: Optional[int] = None
    babble_talkers: list[str] = field(default_factory=list)
    agent_voice: Optional[str] = None
    agent_gain_db: Optional[float] = None
    caller_onset_ms: Optional[int] = None
    overlap_ms: Optional[int] = None


def scenario_seed(scenario_id: str) -> int:
    """Stable per-scenario seed (does not depend on Python's hash randomisation)."""
    return int.from_bytes(hashlib.sha256(scenario_id.encode()).digest()[:4], "big")


def _ms(n_samples: int) -> int:
    return round(1000 * n_samples / SAMPLE_RATE)


def pad(audio: np.ndarray, ms: int = PAD_MS) -> np.ndarray:
    z = np.zeros(int(SAMPLE_RATE * ms / 1000), dtype=np.float32)
    return np.concatenate([z, audio, z])


def babble_sources(scenario: Scenario, pool: list[Scenario], k: int = BABBLE_TALKERS) -> list[Scenario]:
    """Pick ``k`` other clean scenarios as babble talkers, deterministically."""
    candidates = sorted(
        (s for s in pool if s.condition is Condition.CLEAN and s.id != scenario.id),
        key=lambda s: hashlib.sha256(f"{scenario.id}:{s.id}".encode()).hexdigest(),
    )
    if len(candidates) < k:
        raise ValueError(f"need {k} clean scenarios for babble, found {len(candidates)}")
    return candidates[:k]


class ScenarioAudioBuilder:
    def __init__(self, tts: EspeakTTS, pool: list[Scenario]):
        self.tts = tts
        self.pool = pool
        self._cache: dict[tuple[str, str], np.ndarray] = {}

    def _speak(self, text: str, voice: str) -> np.ndarray:
        key = (text, voice)
        if key not in self._cache:
            self._cache[key] = peak_normalise(self.tts.synthesize(text, voice))
        return self._cache[key]

    def build(self, s: Scenario) -> tuple[np.ndarray, AudioRecord]:
        voice = self.tts.voice_for(s.language.value)
        caller = self._speak(s.reference, voice)
        rec = AudioRecord(
            id=s.id, path="", sha256="", duration_s=0.0,
            condition=s.condition.value, language=s.language.value, caller_voice=voice,
        )

        if s.condition is Condition.NOISE:
            clean = pad(caller)
            seed = scenario_seed(s.id)
            talkers = []
            if s.noise_type.value == "babble":
                sources = babble_sources(s, self.pool)
                talkers = [self._speak(t.reference, self.tts.voice_for(t.language.value)) for t in sources]
                rec.babble_talkers = [t.id for t in sources]
            noise = make_noise(s.noise_type.value, len(clean), seed, talkers)
            audio, scaled = mix_at_snr(clean, noise, s.snr_db)
            rec.target_snr_db = float(s.snr_db)
            rec.measured_snr_db = round(snr_db(clean, scaled), 3)
            rec.noise_type = s.noise_type.value
            rec.noise_seed = seed

        elif s.condition is Condition.INTERRUPTION and s.interruption.kind is InterruptionKind.BARGE_IN:
            agent_voice = self.tts.voice_for(s.language.value, agent=True)
            agent = self._speak(s.interruption.agent_prompt, agent_voice)
            onset = int(SAMPLE_RATE * s.interruption.caller_onset_ms / 1000)
            if onset >= len(agent):
                raise ValueError(f"{s.id}: caller_onset_ms is after the agent prompt ends")
            # Simplest model of a system with no barge-in detection: the agent
            # prompt plays to the end while the caller talks over it.
            audio = pad(overlay(agent * (10 ** (AGENT_GAIN_DB / 20)), caller, onset))
            rec.agent_voice = agent_voice
            rec.agent_gain_db = AGENT_GAIN_DB
            rec.caller_onset_ms = s.interruption.caller_onset_ms
            rec.overlap_ms = _ms(min(len(agent) - onset, len(caller)))

        else:
            # clean, and self-correction (the correction is in the words).
            audio = pad(caller)

        audio = peak_normalise(audio)
        rec.duration_s = round(len(audio) / SAMPLE_RATE, 3)
        return audio, rec


def build_all(
    scenarios: list[Scenario],
    out_dir: str | Path,
    tts: EspeakTTS | None = None,
    scenarios_file: str | None = None,
    scenarios_sha256: str | None = None,
    command: str | None = None,
) -> dict:
    """Write one WAV per scenario plus ``manifest.json`` into ``out_dir``."""
    tts = tts or EspeakTTS()
    out_dir = Path(out_dir)
    builder = ScenarioAudioBuilder(tts, scenarios)
    records = []
    for s in scenarios:
        audio, rec = builder.build(s)
        path = out_dir / f"{s.id}.wav"
        write_wav(path, audio)
        rec.path = path.name
        rec.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append(asdict(rec))
    manifest = {
        "synthetic": True,
        "tts_engine": tts.version(),
        "tts_words_per_minute": tts.words_per_minute,
        "sample_rate": SAMPLE_RATE,
        "pad_ms": PAD_MS,
        "agent_gain_db": AGENT_GAIN_DB,
        "scenarios_file": scenarios_file,
        "scenarios_sha256": scenarios_sha256,
        "command": command,
        "files": records,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest
