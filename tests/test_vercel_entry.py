"""The Vercel entry point (root app.py) serves the committed results from any working directory."""

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent


def _load_entry():
    spec = importlib.util.spec_from_file_location("vercel_entry", ROOT / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


def test_entry_point_serves_committed_results_from_another_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # paths must not depend on the working directory
    client = TestClient(_load_entry())
    assert client.get("/").status_code == 200
    runs = client.get("/api/runs").json()
    assert runs and client.get(f"/runs/{runs[0]['run_id']}").status_code == 200
    real = client.get("/api/realspeech").json()
    assert real and client.get(f"/realspeech/{real[0]['run_id']}").status_code == 200
    assert client.get("/api/gnani").json()
    audio = client.get("/audio/v1-001.wav")
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"


def test_deploy_requirements_leave_out_the_asr_stack():
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for heavy in ("faster-whisper", "torch", "ctranslate2"):
        assert heavy not in reqs
