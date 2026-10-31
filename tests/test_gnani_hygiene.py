"""Secrets and generated audio stay out of git; the Gnani lane stays out of the local results. Offline."""

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gnani_mock import FAKE_KEY, MockGnani, make_client
from voicebench.dashboard.app import create_app
from voicebench.gnani import lanes
from voicebench.gnani.budget import Budget
from voicebench.gnani.transcriber import GnaniPrismaTranscriber
from voicebench.loader import load_scenarios
from voicebench.runner import save

ROOT = Path(__file__).resolve().parents[1]
MUST_IGNORE = [".env", ".env.local", ".env.production", ".cache/gnani/roundtrip/x/v1-001.wav",
               "results/gnani/roundtrip/v1-001.wav"]


def test_gitignore_lists_the_patterns():
    lines = {line.strip() for line in (ROOT / ".gitignore").read_text().splitlines()}
    assert {".env", ".env.*", ".cache/gnani/"} <= lines


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="needs a git checkout")
@pytest.mark.parametrize("path", MUST_IGNORE)
def test_git_ignores(path):
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", path])
    assert r.returncode == 0, f"{path} is not git-ignored"


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="needs a git checkout")
def test_run_files_are_not_ignored():
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index",
                        "results/gnani/synthetic/20261101T000000Z-gnani-prisma-v3.0-auto.json"])
    assert r.returncode == 1


def test_no_key_like_values_in_the_lane_source():
    """The client only ever reads the key from the environment; nothing in the source assigns one."""
    for p in (ROOT / "src" / "voicebench" / "gnani").glob("*.py"):
        text = p.read_text(encoding="utf-8")
        assert "X-API-Key-ID\": \"" not in text and "GNANI_API_KEY=" not in text, p


def test_dashboard_lists_gnani_runs_separately(tmp_path):
    results = tmp_path / "results"
    for name in ("scenarios",):
        (tmp_path / name).mkdir()
    (tmp_path / "scenarios" / "v1.jsonl").write_bytes((ROOT / "scenarios" / "v1.jsonl").read_bytes())
    scenarios = load_scenarios(tmp_path / "scenarios" / "v1.jsonl")
    picked = lanes.pick_scenarios(scenarios, 2)
    t = GnaniPrismaTranscriber(make_client(MockGnani()), Budget(3))
    m = lanes.run_synthetic(t, picked, len(scenarios), str(ROOT / "audio" / "v1"), "scenarios/v1.jsonl",
                            "pytest", "auto")
    m = m.model_copy(update={"scenarios_file": "scenarios/v1.jsonl"})
    path = save(m, results / "gnani" / "synthetic")
    assert FAKE_KEY not in path.read_text(encoding="utf-8")

    client = TestClient(create_app(results, ROOT / "audio" / "v1", repo_root=tmp_path))
    assert client.get("/api/runs").json() == []  # never mixed into the local run list
    gn = client.get("/api/gnani").json()
    assert [r["run_id"] for r in gn] == [m.run_id] and gn[0]["external_api"] == "gnani.ai"
    index = client.get("/").text
    assert "External API runs (Gnani)" in index and f'href="/runs/{m.run_id}"' in index
    page = client.get(f"/runs/{m.run_id}?status=all")
    assert page.status_code == 200 and "External API run (gnani.ai)" in page.text
    assert "not comparable" in page.text


def test_committed_dashboard_still_renders_without_gnani_runs():
    client = TestClient(create_app(ROOT / "results", ROOT / "audio" / "v1", repo_root=ROOT))
    r = client.get("/")
    assert r.status_code == 200 and "External API runs (Gnani)" in r.text
