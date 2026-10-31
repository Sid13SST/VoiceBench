"""Real-speech lane tests. Clips and transcripts here are fixtures; no FLEURS audio is downloaded."""

import hashlib
import io
import json
import tarfile
from pathlib import Path

import numpy as np
import pytest

from voicebench import realspeech as rs
from voicebench.asr import Transcript
from voicebench.audio.signal import write_wav
from voicebench.cli import main
from voicebench.runner import save

ROOT = Path(__file__).resolve().parents[1]


def tsv_row(sid, file, raw, n=16000, gender="MALE"):
    return "\t".join([str(sid), file, raw, raw, "x", str(n), gender])


TSV = "\n".join([
    tsv_row(1, "300.wav", "पहला वाक्य है।"),
    tsv_row(1, "100.wav", "पहला वाक्य है।", gender="FEMALE"),
    tsv_row(2, "200.wav", "53 साल के कुओमो ने"),
    tsv_row(3, "400.wav", "चौथा वाक्य"),
]) + "\n"


def test_parse_fleurs_tsv():
    rows = rs.parse_fleurs_tsv(TSV)
    assert [r["id"] for r in rows] == ["300", "100", "200", "400"]
    assert rows[2] == {"id": "200", "file": "200.wav", "sentence_id": 2, "reference": "53 साल के कुओमो ने",
                       "reference_fleurs_normalised": "53 साल के कुओमो ने", "num_samples": 16000, "gender": "MALE"}
    with pytest.raises(ValueError, match="7 columns"):
        rs.parse_fleurs_tsv("1\ta.wav\tonly three\n")


def test_selection_is_seeded_sorted_and_independent_of_row_order():
    rows = rs.parse_fleurs_tsv(TSV)
    a = rs.select_clips(rows, 2, seed=7)
    assert a == rs.select_clips(list(reversed(rows)), 2, seed=7)
    assert [c["file"] for c in a] == sorted(c["file"] for c in a)
    assert len({c["file"] for c in rs.select_clips(rows, 4, seed=1)}) == 4
    with pytest.raises(ValueError):
        rs.select_clips(rows, 5, seed=1)


def _archive(tmp_path, members):
    """A .tar.gz with the given {name: bytes}; a value of None adds a symlink of that name."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "test.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            if data is None:
                info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return path


def test_manifest_and_extract_verify_hashes_and_never_use_archive_paths(tmp_path):
    members = {f"test/{i}00.wav": f"wav{i}".encode() for i in range(1, 5)}
    archive = _archive(tmp_path, members)
    m = rs.build_manifest(TSV, archive, 4, 3, "pytest", "a" * 64, "b" * 64)
    assert m["kind"] == rs.KIND and m["selection"] == {**m["selection"], "seed": 3, "n": 4, "population": 4}
    assert {c["file"]: c["sha256"] for c in m["clips"]}["200.wav"] == hashlib.sha256(b"wav2").hexdigest()

    out = tmp_path / "out"
    assert rs.extract_clips(m, archive, out) == {"clips": 4, "written": 4, "already_present": 0}
    assert (out / "100.wav").read_bytes() == b"wav1"
    assert rs.extract_clips(m, archive, out)["already_present"] == 4

    # A member whose path climbs out of the archive is written by base name into out_dir only;
    # a symlink with a wanted name is never followed or written.
    evil = _archive(tmp_path / "e", {"../../100.wav": b"wav1", "200.wav": None,
                                     **{k: v for k, v in members.items() if "200" not in k}})
    out2 = tmp_path / "out2"
    with pytest.raises(ValueError, match="not in the archive"):
        rs.extract_clips(m, evil, out2)
    assert (out2 / "100.wav").read_bytes() == b"wav1"
    assert not (out2 / "200.wav").exists() and not (tmp_path / "100.wav").exists()

    tampered = _archive(tmp_path / "t", {**members, "test/300.wav": b"changed"})
    with pytest.raises(ValueError, match="does not match the manifest"):
        rs.extract_clips(m, tampered, tmp_path / "out3")


def test_committed_manifest():
    m = rs.load_manifest(ROOT / rs.DEFAULT_MANIFEST)
    assert m["dataset"]["revision"] == rs.FLEURS_REVISION
    assert (m["dataset"]["config"], m["dataset"]["split"], m["dataset"]["license"]) == ("hi_in", "test", "CC-BY-4.0")
    assert m["selection"]["seed"] == rs.DEFAULT_SEED and m["selection"]["n"] == len(m["clips"]) == 150
    assert [c["file"] for c in m["clips"]] == sorted(c["file"] for c in m["clips"])
    assert all(c["reference"].strip() and len(c["sha256"]) == 64 for c in m["clips"])


def test_no_real_speech_audio_is_committed():
    import subprocess

    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True).stdout.split()
    clips = {c["file"] for c in rs.load_manifest(ROOT / rs.DEFAULT_MANIFEST)["clips"]}
    assert not [f for f in tracked if Path(f).name in clips or f.startswith(".cache/")]


class Scripted:
    name = "scripted"

    def __init__(self, texts):
        self.texts, self.languages = texts, []

    def describe(self):
        return {"name": self.name, "backend": "fixture", "device": "none"}

    def transcribe_file(self, path, language=None):
        self.languages.append(language)
        text, lang = self.texts[Path(path).stem]
        if isinstance(text, Exception):
            raise text
        return Transcript(text, self.name, lang if language is None else language, 0.9, language,
                          latency_ms=500.0, audio_duration_s=1.0)


@pytest.fixture
def lane(tmp_path):
    clips = [{"id": "a", "file": "a.wav", "reference": "मैं घर जा रहा हूँ।"},
             {"id": "b", "file": "b.wav", "reference": "वह बाज़ार गई"},
             {"id": "c", "file": "c.wav", "reference": "पानी"}]
    manifest = {"kind": rs.KIND, "dataset": {"name": "FLEURS", "hf_repo": "x", "revision": "r", "config": "hi_in",
                                             "split": "test", "license": "CC-BY-4.0"}, "clips": clips}
    mfile = tmp_path / "manifest.json"
    mfile.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    for c in clips:
        write_wav(tmp_path / "audio" / c["file"], np.zeros(1600, np.float32))
    texts = {"a": ("मैं घर जा रहा हूँ", "hi"),
             "b": ("wo bazaar gayi", "ur"),
             "c": (RuntimeError("boom"), "hi")}
    return manifest, str(mfile), tmp_path / "audio", texts


def test_run_policies_and_summary(lane):
    manifest, mfile, audio, texts = lane
    asr = Scripted(texts)
    auto = rs.run_realspeech(manifest, mfile, audio, asr, "pytest", language_policy="auto")
    assert asr.languages == [None, None, None, None]  # first call is the untimed warm-up
    by = {r.clip_id: r for r in auto.results}
    assert by["a"].wer == 0 and by["b"].wer == 1.0 and by["c"].error == "RuntimeError: boom"
    s = rs.summarise_realspeech(auto)
    assert s["n"] == 3 and s["errors"] == 1 and s["detected_languages"] == {"hi": 1, "ur": 1}
    assert s["categories"] == {"wrong_language": 1, "pipeline_error": 1}
    assert s["corpus_wer"] == pytest.approx(3 / 8)  # 0 of 5 + 3 of 3 reference words
    assert s["corpus_wer_detected_hi"] == 0 and s["n_detected_hi"] == 1
    assert s["corpus_wer_spelling_folded"] == s["corpus_wer"]
    assert (s["latency_p50_loop_ms"], s["latency_p50_no_loop_ms"]) == (None, 500.0)
    assert "REAL SPEECH, external audio" in rs.format_realspeech(s)

    asr = Scripted(texts)
    hint = rs.rescore_realspeech(rs.run_realspeech(manifest, mfile, audio, asr, "pytest", language_policy="hint"),
                                 "pytest rescore")
    assert asr.languages == [None, "hi", "hi", "hi"]
    assert hint.rescored_from and hint.run_id.endswith(hint.run_id.split("-rescored-")[1])
    # with the hint every clip is "hi", so a wrong-script transcript is a recognition error, not wrong_language
    assert rs.summarise_realspeech(hint)["categories"] == {"recognition_error": 1, "pipeline_error": 1}


def test_run_refuses_missing_audio(lane, tmp_path):
    manifest, mfile, audio, texts = lane
    (audio / "b.wav").unlink()
    with pytest.raises(FileNotFoundError, match="realspeech fetch"):
        rs.run_realspeech(manifest, mfile, audio, Scripted(texts), "pytest")


def test_word_error_breakdown_kinds(lane):
    manifest, mfile, audio, _ = lane
    texts = {"a": ("मै घर जा रहा हूं", "hi"), "b": ("वह bazaar गई", "hi"), "c": ("२", "hi")}
    run = rs.run_realspeech(manifest, mfile, audio, Scripted(texts), "pytest", language_policy="hint")
    b = rs.word_error_breakdown(run)
    assert b["substitutions"] == {"other": 1, "spelling_variant": 1, "script": 1, "digits": 1}
    # Whisper errors seen on FLEURS: "गंभीर" -> "गंबीर" (aspiration), "पानी" -> "पानि" (vowel length)
    texts = {"a": ("मैं घर जा रहा हूँ", "hi"), "b": ("वह बाज़ार गयी", "hi"), "c": ("पानि", "hi")}
    run2 = rs.run_realspeech(manifest, mfile, audio, Scripted(texts), "pytest", language_policy="hint")
    assert rs.word_error_breakdown(run2)["substitutions"] == {"other": 1, "vowel_length": 1}
    run2.results[0].reference, run2.results[0].transcript = "गंभीर मौसम था", "गंबीर मौसम ता"
    assert rs.word_error_breakdown(run2)["substitutions"] == {"aspiration": 2, "other": 1, "vowel_length": 1}
    assert ("हूँ", "हूं", 1) in b["top_pairs"]["spelling_variant"]
    s = rs.summarise_realspeech(run)
    # "हूँ" -> "हूं" is an error in the headline WER only: 4 vs 3 errors over 9 reference words
    assert (s["corpus_wer"], s["corpus_wer_spelling_folded"]) == (pytest.approx(4 / 9), pytest.approx(3 / 9))


def test_cli_report_and_rescore(lane, tmp_path, capsys):
    manifest, mfile, audio, texts = lane
    run = rs.run_realspeech(manifest, mfile, audio, Scripted(texts), "pytest")
    path = save(run, tmp_path / "results")
    assert main(["realspeech", "report", str(path)]) == 0
    out = capsys.readouterr().out
    assert "REAL SPEECH" in out and "detected language          hi=1, ur=1" in out
    assert main(["realspeech", "rescore", str(path), "--out", str(tmp_path / "results")]) == 0
    assert len(list((tmp_path / "results").glob("*-rescored-*.json"))) == 1
    synthetic = ROOT / "results" / "20261018T132344Z-faster-whisper-small-auto.json"
    assert main(["realspeech", "report", str(synthetic)]) == 1
    assert "not a valid real-speech run file" in capsys.readouterr().err


def test_run_records_the_commit_from_before_decoding(lane, monkeypatch):
    manifest, mfile, audio, texts = lane
    calls = iter(["commit-at-start", "commit-at-end"])
    monkeypatch.setattr(rs, "git_commit", lambda repo: next(calls))
    run = rs.run_realspeech(manifest, mfile, audio, Scripted(texts), "pytest")
    assert run.git_commit == "commit-at-start"


def test_reference_numbers_take_whole_tokens_only():
    # From FLEURS references in the committed manifest.
    assert rs.reference_numbers("सोवियत की यूनियन रेड आर्मी के 800,000 से ज़्यादा सैनिकों ने") == ["800000"]
    assert rs.reference_numbers("11वीं, 12वीं और 13वीं सदी (1000-1300) में") == ["1000", "1300"]
    assert rs.reference_numbers("सुबह 10: 00-11: 00 बजे, 11:35 पर, 3:2 से") == []
    assert rs.reference_numbers("35mm है. यह 20% हिस्सा") == ["20"]


def test_numbers_recovered_uses_the_matcher_parser():
    ref = "उस समय करीब 10,000 लोग थे और 20 जहाज़"
    assert rs.numbers_recovered(ref, "उस समय करीब दस हज़ार लोग थे और बीस जहाज") == 2
    assert rs.numbers_recovered(ref, "उस समय करीब 10,000 लोग थे") == 1
    assert rs.numbers_recovered(ref, "उस समय करीब १०००० लोग थे") == 1  # Devanagari digits
    assert rs.numbers_recovered(ref, "") == 0
    clip = rs.score_clip({"id": "x", "reference": ref}, "दस हज़ार लोग")
    assert (clip.reference_numbers, clip.numbers_recovered) == (["10000", "20"], 1)


def test_compare_isolates_the_misdetected_clips(lane, tmp_path, capsys):
    manifest, mfile, audio, texts = lane
    auto = rs.run_realspeech(manifest, mfile, audio, Scripted(texts), "pytest", language_policy="auto")
    hint_texts = {**texts, "b": ("वह बाज़ार गई", "hi")}  # the clip auto labelled "ur" is right with the hint
    hint = rs.run_realspeech(manifest, mfile, audio, Scripted(hint_texts), "pytest", language_policy="hint")
    c = rs.compare_realspeech(auto, hint)
    assert (c["compared"], c["identical_transcripts"], c["detected_hi_in_a"], c["identical_where_a_detected_hi"]) == (2, 1, 1, 1)
    assert (c["misdetected_in_a"], c["misdetected_wer_a"], c["misdetected_wer_b"]) == (1, 1.0, 0.0)
    pa, pb = save(auto, tmp_path / "r"), save(hint, tmp_path / "r")
    assert main(["realspeech", "compare", str(pa), str(pb)]) == 0
    assert "clips A detected as another language: 1, corpus WER A 1.000 / B 0.000" in capsys.readouterr().out
    other = auto.model_copy(update={"manifest_sha256": "f" * 64})
    with pytest.raises(ValueError, match="different manifests"):
        rs.compare_realspeech(other, hint)
