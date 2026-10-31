"""``voicebench gnani``: dry runs by default, opt-in live runs (against a mock), exit codes, labels. Offline."""

import json
from pathlib import Path

import pytest

import voicebench.gnani.client as gclient
from gnani_mock import FAKE_KEY, MockGnani, fixture, wav_bytes
from voicebench.cli import main
from voicebench.gnani.client import API_KEY_ENV

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def mock_api(monkeypatch):
    """Route every GnaniClient the CLI builds to a mock transport; fail loudly on any real request."""
    mock = MockGnani()
    real = gclient.GnaniClient

    def factory(*args, **kwargs):
        kwargs["transport"] = mock.transport
        kwargs["sleep"] = lambda s: None
        return real(*args, **kwargs)

    monkeypatch.setattr(gclient, "GnaniClient", factory)
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    return mock


def test_dry_run_sends_nothing(mock_api, capsys):
    assert main(["gnani", "run", "--lane", "synthetic", "--max-requests", "4"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN, nothing sent" in out and "would send 4 billable requests" in out
    assert main(["gnani", "roundtrip", "--max-requests", "4"]) == 0
    assert "would send 4 billable requests (cap 4) for 2 items" in capsys.readouterr().out
    assert mock_api.requests == []


def test_dry_run_of_realspeech_uses_the_committed_dev_split(mock_api, capsys):
    assert main(["gnani", "run", "--lane", "realspeech", "--max-requests", "3"]) == 0
    out = capsys.readouterr().out
    split = json.loads((ROOT / "data" / "realspeech" / "fleurs_hi_in_test_150_split.json").read_text())
    listed = [line.split()[0] for line in out.splitlines() if line.startswith("  ")]
    assert len(listed) == 2 and set(listed) <= set(split["dev"])
    assert mock_api.requests == []


def test_live_without_key_is_refused(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    assert main(["gnani", "run", "--lane", "synthetic", "--live", "--out", str(tmp_path)]) == 2
    assert "GNANI_API_KEY is not set" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_live_synthetic_run_writes_a_labelled_run_file(mock_api, tmp_path, capsys):
    out = tmp_path / "gnani" / "synthetic"
    assert main(["gnani", "run", "--lane", "synthetic", "--max-requests", "3", "--live", "--out", str(out),
                 "--command", "voicebench gnani run --lane synthetic --max-requests 3 --live"]) == 0
    io = capsys.readouterr()
    assert mock_api.count("/stt/v3") == 3
    assert "EXTERNAL API RUN (gnani.ai)" in io.out
    assert "gnani: 3 of 3 allowed requests used" in io.err and "app.gnani.ai" in io.err
    (path,) = out.glob("*.json")
    run = json.loads(path.read_text(encoding="utf-8"))
    assert run["asr_model"] == "gnani-prisma-v3.0" and run["asr_config"]["external_api"]["provider"] == "gnani.ai"
    assert FAKE_KEY not in path.read_text(encoding="utf-8")
    # voicebench report reads it and labels it
    assert main(["report", str(path)]) == 0
    assert "EXTERNAL API RUN" in capsys.readouterr().out
    # comparing it with a local run says these are different systems
    local = ROOT / "results" / "20261018T132344Z-faster-whisper-small-auto.json"
    assert main(["compare", str(local), str(path)]) == 0
    assert "external API run: A=local B=gnani.ai" in capsys.readouterr().out


def test_402_stops_the_run_loudly_and_writes_nothing(mock_api, tmp_path, capsys):
    mock_api.routes["/stt/v3"] = [(200, fixture("stt_ok_v3.json")), (402, fixture("err_402_credit.json"))]
    assert main(["gnani", "run", "--lane", "synthetic", "--live", "--out", str(tmp_path)]) == 3
    err = capsys.readouterr().err
    assert "OUT OF CREDIT" in err and "gnani: 2 of 10 allowed requests used" in err
    assert mock_api.count("/stt/v3") == 2 and not list(tmp_path.glob("*.json"))


def test_401_stops_the_run(mock_api, tmp_path, capsys):
    mock_api.routes["/stt/v3"] = [(401, fixture("err_401_invalid_key.json"))]
    assert main(["gnani", "run", "--lane", "synthetic", "--live", "--out", str(tmp_path)]) == 2
    assert "INVALID_API_KEY" in capsys.readouterr().err and mock_api.count("/stt/v3") == 1


def test_live_roundtrip_writes_run_file_and_audio_manifest(mock_api, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "v1.jsonl").write_bytes((ROOT / "scenarios" / "v1.jsonl").read_bytes())
    mock_api.routes["/api/v1/tts/inference"] = [(200, wav_bytes(2.0))]
    assert main(["gnani", "roundtrip", "--max-requests", "4", "--live", "--ids", "v1-001,v1-011"]) == 0
    capsys.readouterr()
    (path,) = (tmp_path / "results" / "gnani" / "roundtrip").glob("*.json")
    manifest = json.loads((path.parent / "audio-manifests" / path.name).read_text(encoding="utf-8"))
    assert [f["scenario_id"] for f in manifest["files"]] == ["v1-001", "v1-011"]
    assert all(f["path"].startswith(".cache/gnani/roundtrip/") for f in manifest["files"])
    assert not list((tmp_path / "results").rglob("*.wav"))
