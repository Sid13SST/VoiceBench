"""Dashboard tests. Runs built here are fixtures; the real runs in results/ are only read."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_scenario
from voicebench.dashboard.app import TEMPLATES, create_app
from voicebench.dashboard.data import case_rows, matrix, word_diff
from voicebench.loader import file_sha256
from voicebench.schema import RunManifest, Scenario

ROOT = Path(__file__).resolve().parents[1]


def test_word_diff_ops():
    d = word_diff("send five thousand to rahul", "Send 5000 to Rahul please")
    assert [x["op"] for x in d] == ["equal", "sub", "equal", "equal", "ins"]
    assert d[1] == {"op": "sub", "ref": "five thousand", "hyp": "5000"}
    assert [x["op"] for x in word_diff("a b c", "a c")] == ["equal", "del", "equal"]
    assert word_diff("a b", "") == [{"op": "del", "ref": "a", "hyp": ""}, {"op": "del", "ref": "b", "hyp": ""}]


@pytest.fixture
def fixture_repo(tmp_path):
    rows = [
        make_scenario(id="v1-001"),
        make_scenario(id="v1-002", language="hi", reference="राहुल को पाँच हज़ार रुपये भेजो",
                      condition="noise", snr_db=5, noise_type="white"),
        make_scenario(id="v1-003", language="hi-en", reference="rahul को five thousand rupees भेजो",
                      condition="interruption", interruption={"kind": "self_correction"}),
    ]
    (tmp_path / "scenarios").mkdir()
    sfile = tmp_path / "scenarios" / "v1.jsonl"
    sfile.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    base = {"scenario_version": "v1", "source": "fixture"}
    manifest = RunManifest(
        run_id="fixture-run",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source="fixture",
        command="pytest",
        scenarios_file="scenarios/v1.jsonl",
        scenarios_sha256=file_sha256(sfile),
        asr_model="scripted",
        results=[
            {**base, "scenario_id": "v1-001", "transcript": "please send five thousand rupees to rahul", "wer": 0.0,
             "predicted_intent": "transfer_money", "predicted_slots": {"amount": "5000", "recipient": "rahul"},
             "intent_correct": True, "slots_correct": True, "task_success": True},
            {**base, "scenario_id": "v1-002", "transcript": "rahul ko paise", "wer": 1.0,
             "predicted_intent": None, "intent_correct": False, "slots_correct": False, "task_success": False},
            {**base, "scenario_id": "v1-003", "error": "RuntimeError: boom", "task_success": False},
        ],
    )
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "fixture-run.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    (tmp_path / "results" / "notes.json").write_text('{"not": "a run"}', encoding="utf-8")
    scenarios = [Scenario.model_validate(r) for r in rows]
    client = TestClient(create_app(tmp_path / "results", tmp_path / "audio", repo_root=tmp_path))
    return client, manifest, scenarios, sfile


def test_matrix_and_case_filters(fixture_repo):
    _, m, scenarios, _ = fixture_repo
    mx = matrix(m, scenarios)
    assert mx["en"]["clean"] == {"n": 1, "ok": 1, "rate": 1.0}
    assert mx["hi"]["noise"] == {"n": 1, "ok": 0, "rate": 0.0}
    assert mx["hi"]["clean"]["n"] == 0 and mx["hi"]["clean"]["rate"] is None
    assert mx["all"]["all"]["ok"] == 1 and mx["all"]["all"]["n"] == 3
    assert [c["scenario"].id for c in case_rows(m, scenarios)] == ["v1-002", "v1-003"]
    assert [c["scenario"].id for c in case_rows(m, scenarios, status="pass")] == ["v1-001"]
    assert [c["scenario"].id for c in case_rows(m, scenarios, language="hi", status="all")] == ["v1-002"]
    assert case_rows(m, scenarios, status="all")[0]["slot_errors"] == {}
    assert case_rows(m, scenarios)[0]["slot_errors"] == {"amount": ("5000", None), "recipient": ("rahul", None)}


def test_index_lists_runs_and_skips_invalid_files(fixture_repo):
    client = fixture_repo[0]
    r = client.get("/")
    assert r.status_code == 200
    assert "fixture-run" in r.text and "1/3" in r.text
    assert "notes.json" in r.text  # reported as skipped, not crashed on
    assert "<b>fixture</b>" in r.text


def test_run_page_shows_banner_matrix_and_failures(fixture_repo):
    client = fixture_repo[0]
    r = client.get("/runs/fixture-run")
    assert r.status_code == 200
    assert "Fixture data." in r.text
    assert "No timed transcriptions" in r.text and "Hardware not recorded" in r.text
    assert r.text.count('class="case"') == 2  # default filter: failures only
    assert "Pipeline error: RuntimeError: boom" in r.text
    assert "राहुल" in r.text  # Devanagari reference rendered
    assert client.get("/runs/fixture-run?status=all").text.count('class="case"') == 3
    assert client.get("/runs/fixture-run?language=hi").text.count('class="case"') == 1
    # unknown filter values are ignored, not errors
    assert client.get("/runs/fixture-run?language=fr&status=bogus").status_code == 200


def test_changed_scenario_file_is_flagged(fixture_repo):
    client, _, _, sfile = fixture_repo
    sfile.write_text(sfile.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert "has changed since this run" in client.get("/runs/fixture-run").text


def test_html_is_escaped(fixture_repo, tmp_path):
    client, m, _, _ = fixture_repo
    evil = m.model_copy(update={"results": [m.results[0].model_copy(update={"transcript": "<script>x</script>"}),
                                            *m.results[1:]]})
    (tmp_path / "results" / "fixture-run.json").write_text(evil.model_dump_json(), encoding="utf-8")
    text = client.get("/runs/fixture-run?status=all").text
    assert "<script>x</script>" not in text and "&lt;script&gt;" in text


def test_api_and_404s(fixture_repo):
    client = fixture_repo[0]
    runs = client.get("/api/runs").json()
    assert [r["run_id"] for r in runs] == ["fixture-run"] and runs[0]["source"] == "fixture"
    detail = client.get("/api/runs/fixture-run").json()
    assert detail["summary"]["overall"]["task_success"] == 1 and detail["scenario_hash_matches"] is True
    assert client.get("/runs/nope").status_code == 404
    assert client.get("/api/runs/nope").status_code == 404


def test_audio_route_only_serves_scenario_wavs():
    client = TestClient(create_app(ROOT / "results", ROOT / "audio" / "v1", repo_root=ROOT))
    r = client.get("/audio/v1-001.wav")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert client.get("/audio/v1-999.wav").status_code == 404
    assert client.get("/audio/manifest.wav").status_code == 404
    assert client.get("/audio/..%2F..%2Fpyproject.wav").status_code == 404


@pytest.mark.skipif(not list((ROOT / "results").glob("*.json")), reason="no committed runs")
def test_committed_runs_render():
    client = TestClient(create_app(ROOT / "results", ROOT / "audio" / "v1", repo_root=ROOT))
    runs = client.get("/api/runs").json()
    assert runs
    for run in runs:
        assert client.get(f"/runs/{run['run_id']}?status=all").status_code == 200


def _write_broken_runs(tmp_path, m):
    missing = m.model_copy(update={"run_id": "missing-scenarios", "scenarios_file": "scenarios/gone.jsonl"})
    unknown = m.model_copy(update={"run_id": "unknown-scenario",
                                   "results": [m.results[0].model_copy(update={"scenario_id": "v1-999"}),
                                               *m.results[1:]]})
    for run in (missing, unknown):
        (tmp_path / "results" / f"{run.run_id}.json").write_text(run.model_dump_json(), encoding="utf-8")


def test_index_survives_runs_that_cannot_be_scored(fixture_repo, tmp_path):
    client, m, _, _ = fixture_repo
    _write_broken_runs(tmp_path, m)
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/runs/fixture-run"' in r.text and "1/3" in r.text
    assert 'href="/runs/missing-scenarios"' not in r.text
    assert "missing-scenarios.json" in r.text and "scenarios file not found: scenarios/gone.jsonl" in r.text
    assert "unknown-scenario.json" in r.text and "v1-999" in r.text


def test_run_pages_for_unscorable_runs_are_4xx(fixture_repo, tmp_path):
    client, m, _, _ = fixture_repo
    _write_broken_runs(tmp_path, m)
    for run_id, reason in (("missing-scenarios", "scenarios file not found"), ("unknown-scenario", "v1-999")):
        r = client.get(f"/runs/{run_id}")
        assert r.status_code == 422 and reason in r.text
        api = client.get(f"/api/runs/{run_id}")
        assert api.status_code == 422 and reason in api.json()["detail"]
    assert client.get("/runs/fixture-run").status_code == 200


EXTERNAL = "my_nlu:understand"
HOSTILE = "<script>alert(1)</script>"


def _write_run(tmp_path, m, drop_understander=False):
    data = json.loads(m.model_dump_json())
    if drop_understander:
        del data["understander"]  # a run file from before the field existed
    (tmp_path / "results" / f"{m.run_id}.json").write_text(json.dumps(data), encoding="utf-8")


def _understander_cell(html, run_id):
    """The understander cell of one row of the run list."""
    row = html.split(f'href="/runs/{run_id}"', 1)[1].split("</tr>", 1)[0]
    return row.split("</td>")[1]


def test_api_runs_includes_the_understander(fixture_repo, tmp_path):
    client, m, _, _ = fixture_repo
    _write_run(tmp_path, m, drop_understander=True)
    _write_run(tmp_path, m.model_copy(update={"run_id": "external-run", "understander": EXTERNAL}))
    runs = {r["run_id"]: r for r in client.get("/api/runs").json()}
    assert runs["fixture-run"]["understander"] == "builtin"
    assert runs["external-run"]["understander"] == EXTERNAL
    for r in runs.values():  # existing keys kept
        assert {"run_id", "created_at", "asr_model", "language_policy", "source", "rescored_from", "file"} <= r.keys()


def test_run_list_labels_builtin_and_external_understanders(fixture_repo, tmp_path):
    client, m, _, _ = fixture_repo
    _write_run(tmp_path, m, drop_understander=True)
    _write_run(tmp_path, m.model_copy(update={"run_id": "external-run", "understander": EXTERNAL}))
    html = client.get("/").text
    assert "<th>understander</th>" in html
    builtin = _understander_cell(html, "fixture-run")
    assert "builtin" in builtin and 'class="tag"' not in builtin
    external = _understander_cell(html, "external-run")
    assert 'class="tag"' in external and ">external<" in external and EXTERNAL in external


def test_run_page_header_shows_the_understander(fixture_repo, tmp_path):
    client, m, _, _ = fixture_repo
    builtin = client.get("/runs/fixture-run").text
    assert "understander builtin" in builtin and "External understander." not in builtin
    _write_run(tmp_path, m.model_copy(update={"run_id": "external-run", "understander": EXTERNAL}))
    external = client.get("/runs/external-run").text
    assert 'understander <span class="tag"' in external and EXTERNAL in external
    assert "External understander." in external


def test_hostile_understander_name_is_escaped(fixture_repo, tmp_path):
    for name in ("index.html", "run.html", "macros.html"):
        assert TEMPLATES.env.autoescape(name) is True
    client, m, _, _ = fixture_repo
    _write_run(tmp_path, m.model_copy(update={"run_id": "hostile-run", "understander": HOSTILE}))
    escaped = "&lt;script&gt;alert(1)&lt;/script&gt;"
    for page in (client.get("/").text, client.get("/runs/hostile-run").text):
        assert HOSTILE not in page and "<script" not in page
        assert escaped in page
    assert {r["run_id"]: r for r in client.get("/api/runs").json()}["hostile-run"]["understander"] == HOSTILE
