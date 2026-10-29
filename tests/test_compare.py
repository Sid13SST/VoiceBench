import json
from datetime import datetime, timezone

import pytest

from voicebench.cli import main
from voicebench.compare import compare_runs
from voicebench.runner import load_run
from voicebench.schema import RunManifest


def manifest(run_id, transcripts, outcomes, hardware=None, rev="m@1", sha="0" * 64):
    return RunManifest(
        run_id=run_id, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), source="fixture", command="t",
        scenarios_file="s", scenarios_sha256=sha, asr_model="x", asr_config={"model_revision": rev},
        hardware=hardware or {"cpu": "a"},
        results=[{"scenario_id": f"v1-00{i}", "scenario_version": "v1", "source": "fixture",
                  "transcript": t, "task_success": o} for i, (t, o) in enumerate(zip(transcripts, outcomes), 1)],
    )


def test_compare_identical_and_different():
    a = manifest("a", ["x", "y", "z"], [True, False, False])
    same = compare_runs(a, manifest("b", ["x", "y", "z"], [True, False, False]))
    assert same["transcripts_differ"] == [] and same["task_outcome_differs"] == []
    assert same["same_hardware"] and same["same_model"] and same["compared"] == 3
    diff = compare_runs(a, manifest("c", ["x", "Y", "z"], [True, True, False], hardware={"cpu": "b"}))
    assert diff["transcripts_differ"] == ["v1-002"]
    assert diff["task_outcome_differs"] == [("v1-002", False, True)]
    assert not diff["same_hardware"]


def test_compare_refuses_different_scenario_files():
    with pytest.raises(ValueError):
        compare_runs(manifest("a", ["x"], [True]), manifest("b", ["x"], [True], sha="1" * 64))


def _write(tmp_path, m, drop_understander=False):
    data = json.loads(m.model_dump_json())
    if drop_understander:
        del data["understander"]  # a run file from before the field existed
    path = tmp_path / f"{m.run_id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_compare_reports_matching_understanders():
    a = manifest("a", ["x"], [True]).model_copy(update={"understander": "my_nlu:understand"})
    b = manifest("b", ["x"], [True]).model_copy(update={"understander": "my_nlu:understand"})
    c = compare_runs(a, b)
    assert c["understander_a"] == c["understander_b"] == "my_nlu:understand"
    assert c["understanders_differ"] is False
    assert c["compared"] == 1 and c["task_outcome_differs"] == []


def test_compare_reports_mismatching_understanders():
    a = manifest("a", ["x"], [True]).model_copy(update={"understander": "builtin"})
    b = manifest("b", ["x"], [False]).model_copy(update={"understander": "my_nlu:understand"})
    c = compare_runs(a, b)
    assert (c["understander_a"], c["understander_b"]) == ("builtin", "my_nlu:understand")
    assert c["understanders_differ"] is True
    assert c["task_outcome_differs"] == [("v1-001", True, False)]


def test_compare_treats_a_run_without_the_field_as_builtin(tmp_path):
    old = load_run(_write(tmp_path, manifest("old", ["x"], [True]), drop_understander=True))
    assert old.understander is None
    c = compare_runs(old, manifest("new", ["x"], [True]).model_copy(update={"understander": "builtin"}))
    assert c["understander_a"] == "builtin" and c["understanders_differ"] is False
    assert compare_runs(old, manifest("ext", ["x"], [True]).model_copy(
        update={"understander": "my_nlu:understand"}))["understanders_differ"] is True


def test_cli_compare_prints_understanders(tmp_path, capsys):
    old = _write(tmp_path, manifest("old", ["x"], [True]), drop_understander=True)
    same = _write(tmp_path, manifest("same", ["x"], [True]).model_copy(update={"understander": "builtin"}))
    ext = _write(tmp_path, manifest("ext", ["x"], [False]).model_copy(update={"understander": "my_nlu:understand"}))

    assert main(["compare", old, same]) == 0
    out = capsys.readouterr().out
    assert "understander: A=builtin B=builtin" in out
    assert "understanders differ" not in out

    assert main(["compare", old, ext]) == 0  # two systems is a legitimate comparison, not an error
    out = capsys.readouterr().out
    assert "understander: A=builtin B=my_nlu:understand" in out
    assert ("understanders differ: A=builtin B=my_nlu:understand - "
            "this compares two systems, not a reproducibility check") in out
    assert "task outcome differs: 1 v1-001(True->False)" in out
