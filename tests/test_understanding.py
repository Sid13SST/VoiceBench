"""The understander seam: an external callable in place of the built-in matcher."""

import json
from pathlib import Path

import numpy as np
import pytest

from conftest import make_scenario
from voicebench.asr import Transcript
from voicebench.audio.signal import write_wav
from voicebench.cli import main
from voicebench.nlu.matcher import match
from voicebench.runner import ReferenceTranscriber, UnderstanderMismatch, load_run, rescore, run, save
from voicebench.schema import ResultSource, Scenario
from voicebench.scoring import score
from voicebench.understanding import (
    BUILTIN,
    UnderstanderError,
    check_understanding,
    load_understander,
    understander_id,
)

FIX = ResultSource.FIXTURE
ROOT = Path(__file__).resolve().parents[1]
SPEC = "test_understanding:stub_understand"


def stub_understand(transcript, domain):
    """Knows two phrases; used directly and through --understander."""
    if "boom" in transcript:
        raise RuntimeError("stub exploded")
    if "card" in transcript:
        return {"intent": "block_card", "slots": {"card_type": "credit"}}
    return {"intent": None, "slots": {}}


class Recorder:
    def __init__(self, out):
        self.out, self.calls = out, []

    def __call__(self, transcript, domain):
        self.calls.append((transcript, domain))
        return self.out


@pytest.fixture
def transfer():
    return Scenario.model_validate(make_scenario())


def test_stub_is_called_with_transcript_and_domain_and_scored(transfer):
    u = Recorder({"intent": "transfer_money", "slots": {"amount": "5000", "recipient": "rahul"}})
    r = score(transfer, "anything at all", FIX, understand=u)
    assert u.calls == [("anything at all", "banking")]
    assert type(u.calls[0][1]) is str
    assert r.predicted_intent == "transfer_money" and r.task_success is True
    wrong = score(transfer, "x", FIX, understand=Recorder({"intent": "transfer_money", "slots": {"amount": "4000"}}))
    assert wrong.intent_correct is True and wrong.slots_correct is False and wrong.task_success is False


@pytest.mark.parametrize("out, msg", [
    (None, "expected a dict"),
    (("transfer_money", {}), "expected a dict"),
    ({"intent": "transfer_money"}, "expected keys"),
    ({"intent": "transfer_money", "slots": {}, "confidence": 0.9}, "expected keys"),
    ({"intent": 3, "slots": {}}, "intent must be"),
    ({"intent": None, "slots": [("amount", "5000")]}, "slots must be a dict"),
    ({"intent": None, "slots": {"amount": 5000}}, "slots must map str to str"),
    ({"intent": None, "slots": {1: "x"}}, "slots must map str to str"),
])
def test_bad_return_shape_is_rejected(transfer, out, msg):
    with pytest.raises(UnderstanderError, match=msg):
        check_understanding(out)
    with pytest.raises(UnderstanderError, match=msg):
        score(transfer, "x", FIX, understand=Recorder(out))


def test_no_fallback_to_the_builtin_matcher(transfer):
    # The built-in matcher would get this transcript right; a broken
    # understander must still fail it.
    with pytest.raises(UnderstanderError, match="RuntimeError: stub exploded"):
        score(transfer, "send five thousand to rahul boom", FIX, understand=stub_understand)


@pytest.fixture
def setup(tmp_path):
    rows = [
        make_scenario(id="v1-001"),
        make_scenario(id="v1-002", reference="please block my credit card", expected_intent="block_card",
                      expected_slots={"card_type": "credit"}),
        make_scenario(id="v1-003", reference="block my credit card boom", expected_intent="block_card",
                      expected_slots={"card_type": "credit"}),
    ]
    sfile = tmp_path / "v1.jsonl"
    sfile.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    audio = tmp_path / "audio"
    for r in rows:
        write_wav(audio / f"{r['id']}.wav", np.zeros(1600, np.float32))
    return [Scenario.model_validate(r) for r in rows], sfile, audio


def test_run_records_errors_per_scenario_and_the_understander(setup):
    scenarios, sfile, audio = setup

    def understand(transcript, domain):
        if transcript.endswith("boom"):
            return {"intent": "block_card"}  # bad shape
        return stub_understand(transcript, domain)

    m = run(scenarios, audio, ReferenceTranscriber(), str(sfile), "t", source=FIX,
            understand=understand, understander="mine:understand")
    assert m.understander == "mine:understand"
    a, b, c = m.results
    assert a.error is None and a.task_success is False and a.predicted_intent is None
    assert b.error is None and b.task_success is True
    assert c.error.startswith("UnderstanderError: expected keys") and c.task_success is False

    m = run(scenarios, audio, ReferenceTranscriber(), str(sfile), "t", source=FIX, understand=stub_understand)
    assert m.understander == "test_understanding:stub_understand"
    assert m.results[2].error == "UnderstanderError: RuntimeError: stub exploded"
    assert m.results[2].task_success is False


def test_default_path_is_the_builtin_matcher(setup):
    scenarios, sfile, audio = setup
    m = run(scenarios, audio, ReferenceTranscriber(), str(sfile), "t", source=FIX)
    assert m.understander == BUILTIN
    for s, r in zip(scenarios, m.results):
        pred = match(s.reference, s.domain)
        assert (r.predicted_intent, r.predicted_slots) == (pred.intent, pred.slots)
        assert r == score(s, s.reference, FIX)


def test_default_rescore_of_every_committed_run_is_unchanged():
    from voicebench.loader import load_scenarios

    runs = {r.run_id: r for r in map(load_run, sorted((ROOT / "results").rglob("*.json")))}
    assert len(runs) >= 13
    # The day 3 runs predate the day 4 matcher fix; their committed rescore
    # holds the current scoring.
    latest = {r.rescored_from: r for r in runs.values() if r.rescored_from}
    for old in runs.values():
        assert old.understander is None  # committed before the field existed
        new = rescore(old, load_scenarios(ROOT / old.scenarios_file), "pytest")
        assert new.understander == BUILTIN
        want = latest.get(old.run_id, old) if old.rescored_from is None else old
        if new.results == want.results:
            continue
        # The only allowed difference: script_profile gained an "other" label
        # for non-Latin/Devanagari scripts, so the Telugu transcripts of
        # v1-018 and v1-029 are no longer reported as "none". Intents, slots,
        # outcomes, WER and every other field must be identical.
        diffs = [
            (a.scenario_id, field, getattr(b, field), getattr(a, field))
            for a, b in zip(new.results, want.results)
            for field in type(a).model_fields
            if getattr(a, field) != getattr(b, field)
        ]
        assert diffs and all(
            d[0] in {"v1-018", "v1-029"} and d[1:] == ("transcript_script", "none", "other")
            for d in diffs
        ), (old.run_id, diffs)


def test_rescore_requires_the_recorded_understander(setup):
    scenarios, sfile, audio = setup
    ext = run(scenarios, audio, ReferenceTranscriber(), str(sfile), "t", source=FIX,
              understand=stub_understand, understander=SPEC)
    with pytest.raises(UnderstanderMismatch, match="'test_understanding:stub_understand'.*'builtin'"):
        rescore(ext, scenarios, "t")
    with pytest.raises(UnderstanderMismatch):
        rescore(ext, scenarios, "t", understand=stub_understand, understander="other:fn")
    again = rescore(ext, scenarios, "t", understand=stub_understand, understander=SPEC)
    assert again.understander == SPEC and again.results == ext.results

    builtin = run(scenarios, audio, ReferenceTranscriber(), str(sfile), "t", source=FIX)
    with pytest.raises(UnderstanderMismatch):
        rescore(builtin, scenarios, "t", understand=stub_understand, understander=SPEC)
    # A run file from before the field existed counts as builtin.
    old = builtin.model_copy(update={"understander": None})
    assert rescore(old, scenarios, "t").understander == BUILTIN
    with pytest.raises(UnderstanderMismatch):
        rescore(old, scenarios, "t", understand=stub_understand, understander=SPEC)


def test_old_run_file_without_the_field_loads(setup, tmp_path):
    scenarios, sfile, audio = setup
    m = run(scenarios, audio, ReferenceTranscriber(), str(sfile), "t", source=FIX)
    data = json.loads(m.model_dump_json())
    del data["understander"]
    path = tmp_path / "old.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_run(path).understander is None


def test_load_understander():
    assert load_understander(SPEC) is stub_understand
    assert load_understander("voicebench.nlu.matcher:match") is match
    for bad in ("test_understanding", ":stub_understand", "test_understanding:", "test_understanding:nope",
                "test_understanding:SPEC"):
        with pytest.raises(ValueError):
            load_understander(bad)
    with pytest.raises(ImportError):
        load_understander("no_such_module_xyz:fn")
    assert understander_id(None) == BUILTIN
    assert understander_id(stub_understand) == SPEC


def _write_run(setup, tmp_path, *args):
    scenarios, sfile, audio = setup
    out = tmp_path / "r"
    assert main(["run", "--asr", "oracle", "--scenarios", str(sfile), "--audio", str(audio),
                 "--out", str(out), "--command", "pytest", *args]) == 0
    (path,) = out.glob("*.json")
    return path


def test_cli_run_and_rescore_with_understander(setup, tmp_path, capsys):
    path = _write_run(setup, tmp_path, "--understander", SPEC)
    m = load_run(path)
    assert m.understander == SPEC
    assert [r.task_success for r in m.results] == [False, True, False]
    assert m.results[2].error == "UnderstanderError: RuntimeError: stub exploded"
    assert f"understander={SPEC}" in capsys.readouterr().out

    out = tmp_path / "rescored"
    assert main(["rescore", str(path), "--out", str(out)]) == 1
    assert "refusing to rescore" in capsys.readouterr().err and not out.exists()
    assert main(["rescore", str(path), "--out", str(out), "--understander", SPEC]) == 0
    (again,) = out.glob("*.json")
    assert load_run(again).understander == SPEC


def test_cli_builtin_run_refuses_rescore_with_understander(setup, tmp_path, capsys):
    path = _write_run(setup, tmp_path)
    assert load_run(path).understander == BUILTIN
    assert "understander=" not in capsys.readouterr().out
    out = tmp_path / "rescored"
    assert main(["rescore", str(path), "--out", str(out), "--understander", SPEC]) == 1
    assert "'builtin'" in capsys.readouterr().err and not out.exists()


def test_cli_bad_understander_spec(setup, tmp_path, capsys):
    scenarios, sfile, audio = setup
    code = main(["run", "--asr", "oracle", "--scenarios", str(sfile), "--audio", str(audio),
                 "--out", str(tmp_path / "r"), "--understander", "no_such_module_xyz:fn"])
    assert code == 2 and "could not load understander" in capsys.readouterr().err
    assert not (tmp_path / "r").exists()
