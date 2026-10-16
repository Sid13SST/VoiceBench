"""The committed audio must match its manifest and the current scenario file."""

import hashlib
import json
from pathlib import Path

import pytest

from voicebench.loader import file_sha256, load_scenarios

ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / "audio" / "v1"

pytestmark = pytest.mark.skipif(not (AUDIO / "manifest.json").exists(), reason="audio/v1 not generated")


@pytest.fixture(scope="module")
def manifest():
    return json.loads((AUDIO / "manifest.json").read_text(encoding="utf-8"))


def test_manifest_matches_scenario_file(manifest):
    assert manifest["synthetic"] is True
    assert manifest["scenarios_sha256"] == file_sha256(ROOT / "scenarios" / "v1.jsonl")
    ids = [s.id for s in load_scenarios(ROOT / "scenarios" / "v1.jsonl")]
    assert [f["id"] for f in manifest["files"]] == ids


def test_every_wav_matches_its_hash(manifest):
    for f in manifest["files"]:
        data = (AUDIO / f["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == f["sha256"], f["id"]


def test_noise_files_hit_target_snr(manifest):
    for f in manifest["files"]:
        if f["condition"] == "noise":
            assert abs(f["measured_snr_db"] - f["target_snr_db"]) < 0.01, f["id"]
