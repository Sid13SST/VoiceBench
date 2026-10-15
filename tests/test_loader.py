import pytest

from conftest import make_scenario
from voicebench.cli import main
from voicebench.loader import ScenarioFileError, load_scenarios, summarize


def test_loads_valid_file(write_jsonl):
    path = write_jsonl([make_scenario(), "", make_scenario(id="v1-002")])
    scenarios = load_scenarios(path)
    assert [s.id for s in scenarios] == ["v1-001", "v1-002"]


def test_collects_all_errors_with_line_numbers(write_jsonl):
    path = write_jsonl(
        [
            make_scenario(),
            "{not json",
            make_scenario(id="v1-002", expected_intent="order_food"),
            make_scenario(),  # duplicate id
        ]
    )
    with pytest.raises(ScenarioFileError) as exc:
        load_scenarios(path)
    lines = [e.line for e in exc.value.errors]
    assert lines == [2, 3, 4]
    assert "duplicate id" in str(exc.value)


def test_rejects_mixed_versions(write_jsonl):
    path = write_jsonl([make_scenario(), make_scenario(id="v2-001", version="v2")])
    with pytest.raises(ScenarioFileError, match="mixes versions"):
        load_scenarios(path)


def test_expected_version_enforced(write_jsonl):
    path = write_jsonl([make_scenario()])
    with pytest.raises(ScenarioFileError, match="expected only version"):
        load_scenarios(path, expected_version="v2")


def test_empty_file_rejected(write_jsonl):
    with pytest.raises(ScenarioFileError, match="no scenarios"):
        load_scenarios(write_jsonl([""]))


def test_summarize_counts(write_jsonl):
    path = write_jsonl(
        [
            make_scenario(),
            make_scenario(id="v1-002", condition="noise", snr_db=5, noise_type="white"),
        ]
    )
    summary = summarize(load_scenarios(path))
    assert summary["condition"] == {"clean": 1, "noise": 1}
    assert summary["snr_db"] == {"5": 1}


def test_cli_validate_exit_codes(write_jsonl, capsys):
    good = write_jsonl([make_scenario()], name="good.jsonl")
    bad = write_jsonl(["{"], name="bad.jsonl")
    assert main(["validate", str(good)]) == 0
    assert "1 valid scenarios" in capsys.readouterr().out
    assert main(["validate", str(bad)]) == 1
    assert main(["validate", "does/not/exist.jsonl"]) == 1
