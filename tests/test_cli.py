"""CLI tests for commands that read a saved run. The real runs in results/ are only read."""

import json
from pathlib import Path

import pytest

from voicebench.cli import main

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results" / "20261018T132344Z-faster-whisper-small-auto.json"


@pytest.fixture
def copied_repo(tmp_path):
    """A copy of scenarios/v1.jsonl and one committed run, laid out like the repo."""
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "v1.jsonl").write_bytes((ROOT / "scenarios" / "v1.jsonl").read_bytes())
    (tmp_path / "results").mkdir()
    run = tmp_path / "results" / RUN.name
    run.write_bytes(RUN.read_bytes())
    return tmp_path, run


@pytest.mark.parametrize("command", ["report", "analyze"])
def test_reads_scenarios_relative_to_the_run_from_another_directory(command, tmp_path, monkeypatch, capsys):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert main([command, str(RUN)]) == 0
    assert capsys.readouterr().out.strip()


@pytest.mark.parametrize("command", ["report", "analyze"])
def test_matching_hash_still_works(command, copied_repo, monkeypatch, capsys):
    root, run = copied_repo
    monkeypatch.chdir(root)
    assert main([command, str(run)]) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("command", ["report", "analyze", "rescore"])
def test_missing_run_file_is_a_clean_error(command, tmp_path, capsys):
    missing = tmp_path / "nope.json"
    assert main([command, str(missing)]) == 1
    out = capsys.readouterr()
    assert out.out == "" and "no such file" in out.err and "Traceback" not in out.err


@pytest.mark.parametrize("command", ["report", "analyze", "rescore", "compare"])
def test_malformed_run_file_is_a_clean_error(command, tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"broken": true', encoding="utf-8")
    argv = [command, str(bad)] + ([str(bad)] if command == "compare" else [])
    assert main(argv) == 1
    out = capsys.readouterr()
    assert out.out == "" and "not a valid run file" in out.err and "Traceback" not in out.err


def test_analyze_unknown_scenario_is_a_clean_error(copied_repo, monkeypatch, capsys):
    root, run = copied_repo
    data = json.loads(run.read_text(encoding="utf-8"))
    data["results"][0]["scenario_id"] = "v1-999"
    run.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.chdir(root)
    assert main(["analyze", str(run)]) == 1
    out = capsys.readouterr()
    assert "v1-999" in out.err and "Traceback" not in out.err


@pytest.mark.parametrize("command", ["report", "analyze"])
def test_mismatching_hash_is_refused(command, copied_repo, monkeypatch, capsys):
    root, run = copied_repo
    data = json.loads(run.read_text(encoding="utf-8"))
    data["scenarios_sha256"] = "0" * 64
    run.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.chdir(root)
    assert main([command, str(run)]) == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.count("\n") == 1
    assert "scenario file changed since this run" in out.err and f"refusing to {command}" in out.err
