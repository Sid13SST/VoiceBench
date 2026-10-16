import json

import numpy as np
import pytest

from conftest import make_scenario
from voicebench.audio.build import (
    AGENT_GAIN_DB,
    ScenarioAudioBuilder,
    babble_sources,
    build_all,
    scenario_seed,
)
from voicebench.audio.signal import SAMPLE_RATE, read_wav
from voicebench.schema import Scenario

SR = SAMPLE_RATE


class FakeTTS:
    """Deterministic stand-in: a tone whose length grows with the text."""

    words_per_minute = 160

    def voice_for(self, language, agent=False):
        return f"{language}{'+agent' if agent else ''}"

    def version(self):
        return "fake-tts 0"

    def synthesize(self, text, voice):
        n = int(SR * 0.1 * len(text.split()))
        freq = 300 + 10 * (sum(map(ord, voice)) % 30)
        return (0.5 * np.sin(2 * np.pi * freq * np.arange(n) / SR)).astype(np.float32)


def scenario(**kw):
    return Scenario.model_validate(make_scenario(**kw))


@pytest.fixture
def pool():
    return [scenario(id=f"v1-{i:03d}", reference=f"clean utterance number {i} with words") for i in range(1, 7)]


def test_seed_is_stable():
    assert scenario_seed("v1-031") == scenario_seed("v1-031")
    assert scenario_seed("v1-031") != scenario_seed("v1-032")


def test_clean_is_padded_caller(pool):
    audio, rec = ScenarioAudioBuilder(FakeTTS(), pool).build(pool[0])
    pad = int(0.25 * SR)
    assert np.all(audio[:pad] == 0) and np.all(audio[-pad:] == 0)
    assert rec.condition == "clean" and rec.target_snr_db is None


@pytest.mark.parametrize("noise_type", ["white", "pink", "babble"])
@pytest.mark.parametrize("snr", [5, 10])
def test_noise_measured_snr_matches_target(pool, noise_type, snr):
    s = scenario(id="v1-031", condition="noise", snr_db=snr, noise_type=noise_type)
    _, rec = ScenarioAudioBuilder(FakeTTS(), pool + [s]).build(s)
    assert rec.measured_snr_db == pytest.approx(snr, abs=0.01)
    assert rec.noise_seed == scenario_seed("v1-031")
    if noise_type == "babble":
        assert len(rec.babble_talkers) == 4 and "v1-031" not in rec.babble_talkers
    else:
        assert rec.babble_talkers == []


def test_babble_sources_are_deterministic_and_clean_only(pool):
    s = scenario(id="v1-031", condition="noise", snr_db=5, noise_type="babble")
    noisy = scenario(id="v1-032", condition="noise", snr_db=5, noise_type="white")
    a = babble_sources(s, pool + [s, noisy])
    assert [x.id for x in a] == [x.id for x in babble_sources(s, list(reversed(pool)) + [noisy, s])]
    assert all(x.condition.value == "clean" for x in a)
    with pytest.raises(ValueError):
        babble_sources(s, pool[:2])


def test_barge_in_overlap(pool):
    s = scenario(
        id="v1-041", condition="interruption", reference="transfer three thousand rupees",
        interruption={"kind": "barge_in", "agent_prompt": " ".join(["word"] * 20), "caller_onset_ms": 1000},
    )
    audio, rec = ScenarioAudioBuilder(FakeTTS(), pool).build(s)
    # agent prompt 2.0 s, caller 0.4 s starting at 1.0 s -> fully overlapped
    assert rec.overlap_ms == 400
    assert rec.agent_gain_db == AGENT_GAIN_DB
    assert rec.duration_s == pytest.approx(2.0 + 0.5, abs=0.01)


def test_barge_in_onset_after_prompt_is_rejected(pool):
    s = scenario(
        id="v1-041", condition="interruption",
        interruption={"kind": "barge_in", "agent_prompt": "hi there", "caller_onset_ms": 5000},
    )
    with pytest.raises(ValueError, match="after the agent prompt"):
        ScenarioAudioBuilder(FakeTTS(), pool).build(s)


def test_build_all_writes_wavs_and_manifest(tmp_path, pool):
    manifest = build_all(pool, tmp_path, FakeTTS(), scenarios_sha256="0" * 64)
    assert manifest["synthetic"] is True
    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert on_disk == manifest
    for rec in manifest["files"]:
        audio = read_wav(tmp_path / rec["path"])
        assert len(audio) / SR == pytest.approx(rec["duration_s"], abs=1e-3)
        assert np.max(np.abs(audio)) <= 1.0
