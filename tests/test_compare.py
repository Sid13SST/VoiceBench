from datetime import datetime, timezone

import pytest

from voicebench.compare import compare_runs
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
