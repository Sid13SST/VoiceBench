"""Real-speech validation lane: Whisper on human Hindi speech from Google FLEURS.

Separate from the 50-scenario synthetic benchmark. There are no intents or
slots here, only reference transcripts, so this lane measures recognition
alone: corpus and per-clip WER, the language auto-detect chose, repetition
loops and latency, with the same Whisper model and decoding settings as
``voicebench run``.

The subset of clips is fixed by a committed manifest (clip ids, reference
transcripts, a sha256 per WAV and the selection seed). The audio itself is
never committed: ``fetch`` downloads the FLEURS ``hi_in`` test archive from
the Hugging Face Hub at a pinned revision and extracts only the manifest's
clips into a git-ignored cache directory.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
import tarfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Optional

import jiwer
from pydantic import BaseModel, ConfigDict, Field

from voicebench.analysis import has_repetition_loop
from voicebench.asr import ASRUnavailable
from voicebench.loader import file_sha256
from voicebench.metrics import corpus_wer, percentile, wer
from voicebench.nlu.numbers import find_numbers
from voicebench.runner import git_commit, hardware_info
from voicebench.textnorm import fold_spelling_variants, normalise, script_profile, tokens

KIND = "real-speech-external"

FLEURS_REPO = "google/fleurs"
# Dataset revision the committed manifest was built from. Downloads are
# pinned to it so the archive (and every clip's sha256) cannot change.
FLEURS_REVISION = "70bb2e84b976b7e960aa89f1c648e09c59f894dd"
FLEURS_CONFIG = "hi_in"
FLEURS_SPLIT = "test"
FLEURS_TSV = f"data/{FLEURS_CONFIG}/{FLEURS_SPLIT}.tsv"
FLEURS_AUDIO = f"data/{FLEURS_CONFIG}/audio/{FLEURS_SPLIT}.tar.gz"
# As stated in the dataset card (README.md, "license: cc-by-4.0") at FLEURS_REVISION.
FLEURS_LICENSE = "CC-BY-4.0"

DEFAULT_MANIFEST = "data/realspeech/fleurs_hi_in_test_150.json"
DEFAULT_AUDIO_DIR = ".cache/realspeech/fleurs_hi_in_test"
DEFAULT_RESULTS_DIR = "results/realspeech"
DEFAULT_SEED = 20261031
DEFAULT_N = 150

# Whisper language code for the FLEURS config, used by the "hint" policy.
HINT_LANGUAGE = "hi"
LANGUAGE_POLICIES = ("auto", "hint")

# Failure categories from voicebench.analysis that apply without intents,
# in the same priority order. Clips with none of these but WER > 0 are
# "recognition_error".
CATEGORIES = ("pipeline_error", "wrong_language", "repetition_loop")


# ---------------------------------------------------------------- manifest


def parse_fleurs_tsv(text: str) -> list[dict[str, Any]]:
    """Rows of a FLEURS ``<split>.tsv`` (no header, 7 tab-separated columns)."""
    rows = []
    for line in csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE):
        if not line:
            continue
        if len(line) != 7:
            raise ValueError(f"expected 7 columns in a FLEURS tsv row, got {len(line)}: {line[:2]}")
        sentence_id, file, raw, norm, _chars, num_samples, gender = line
        rows.append({
            "id": Path(file).stem,
            "file": file,
            "sentence_id": int(sentence_id),
            "reference": raw,
            "reference_fleurs_normalised": norm,
            "num_samples": int(num_samples),
            "gender": gender,
        })
    return rows


def select_clips(rows: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    """``n`` rows chosen with ``random.Random(seed)`` from the rows sorted by file name.

    Sorting first makes the choice independent of the tsv's row order. The
    result is returned sorted by file name too.
    """
    pool = sorted(rows, key=lambda r: r["file"])
    if len({r["file"] for r in pool}) != len(pool):
        raise ValueError("duplicate file names in the tsv")
    if not 0 < n <= len(pool):
        raise ValueError(f"n must be between 1 and {len(pool)}")
    picked = random.Random(seed).sample(range(len(pool)), n)
    return [pool[i] for i in sorted(picked)]


def _tar_members(tar: tarfile.TarFile, wanted: set[str]):
    """Regular-file members whose base name is in ``wanted``; paths in the archive are never used."""
    for member in tar:
        name = Path(member.name).name
        if name in wanted and member.isfile():
            f = tar.extractfile(member)
            if f is not None:
                yield name, f.read()


def build_manifest(tsv_text: str, archive: str | Path, n: int, seed: int, command: str,
                   tsv_sha256: str, archive_sha256: str) -> dict[str, Any]:
    clips = select_clips(parse_fleurs_tsv(tsv_text), n, seed)
    wanted = {c["file"] for c in clips}
    hashes: dict[str, str] = {}
    with tarfile.open(archive, "r:gz") as tar:
        for name, data in _tar_members(tar, wanted):
            hashes[name] = hashlib.sha256(data).hexdigest()
    missing = sorted(wanted - hashes.keys())
    if missing:
        raise ValueError(f"{len(missing)} selected clips are not in the archive, e.g. {missing[0]}")
    return {
        "kind": KIND,
        "dataset": {
            "name": "FLEURS",
            "hf_repo": FLEURS_REPO,
            "revision": FLEURS_REVISION,
            "config": FLEURS_CONFIG,
            "split": FLEURS_SPLIT,
            "license": FLEURS_LICENSE,
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "citation": "Conneau et al., FLEURS: Few-shot Learning Evaluation of Universal "
                        "Representations of Speech, arXiv:2205.12446, 2022",
            "transcript_file": {"path": FLEURS_TSV, "sha256": tsv_sha256},
            "audio_archive": {"path": FLEURS_AUDIO, "sha256": archive_sha256},
        },
        "selection": {
            "seed": seed,
            "n": n,
            "population": len(parse_fleurs_tsv(tsv_text)),
            "method": "random.Random(seed).sample over the tsv rows sorted by file name",
        },
        "reference_field": "reference (FLEURS raw_transcription); WER uses voicebench.textnorm.normalise",
        "command": command,
        "clips": [{**c, "sha256": hashes[c["file"]]} for c in clips],
    }


def load_manifest(path: str | Path) -> dict[str, Any]:
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    if m.get("kind") != KIND:
        raise ValueError(f"{path}: not a real-speech manifest (kind={m.get('kind')!r})")
    ids = [c["id"] for c in m["clips"]]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate clip ids")
    return m


# ------------------------------------------------------------------- fetch


def hf_download(filename: str, local_files_only: bool = False) -> Path:
    """One file of the FLEURS dataset repo at the pinned revision, via the HF cache."""
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(FLEURS_REPO, filename, repo_type="dataset", revision=FLEURS_REVISION,
                                local_files_only=local_files_only))


def extract_clips(manifest: dict[str, Any], archive: str | Path, out_dir: str | Path) -> dict[str, int]:
    """Write the manifest's clips from ``archive`` into ``out_dir`` and check every sha256.

    Clips already present with the right hash are left alone. Raises
    ValueError if a clip is missing from the archive or has a different hash.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    want = {c["file"]: c["sha256"] for c in manifest["clips"]}
    todo = {f for f, h in want.items() if not (out_dir / f).is_file() or file_sha256(out_dir / f) != h}
    written = 0
    if todo:
        with tarfile.open(archive, "r:gz") as tar:
            for name, data in _tar_members(tar, todo):
                got = hashlib.sha256(data).hexdigest()
                if got != want[name]:
                    raise ValueError(f"{name}: sha256 {got} does not match the manifest ({want[name]})")
                (out_dir / name).write_bytes(data)
                written += 1
        missing = sorted(f for f in todo if not (out_dir / f).is_file())
        if missing:
            raise ValueError(f"{len(missing)} clips are not in the archive, e.g. {missing[0]}")
    return {"clips": len(want), "written": written, "already_present": len(want) - written}


# ----------------------------------------------------------------- numbers

_TIME_OR_RATIO_RE = re.compile(r"\d+\s*:\s*\d+")  # 11:35, 3:2, "10: 00"
_REF_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")
_DIGIT_GROUP_COMMA_RE = re.compile(r"(?<=[0-9०-९]),(?=[0-9०-९])")


def reference_numbers(text: str) -> list[str]:
    """Numbers a reference writes in digits, as digit strings ("800,000" -> "800000").

    Only whole tokens count: ordinals and units glued to the digits
    ("11वीं", "35mm") and times or ratios ("11:35", "3:2") are left out,
    because what a correct transcript would contain for them is not one
    number. Ranges ("1000-1300") count as both numbers.
    """
    out = []
    for tok in _TIME_OR_RATIO_RE.sub(" ", text).split():
        tok = tok.strip("()[]\"'“”.,;!?%")
        for part in tok.split("-"):
            if _REF_NUMBER_RE.fullmatch(part):
                out.append(part.replace(",", ""))
    return out


def transcript_numbers(text: str) -> list[str]:
    """Values the built-in matcher's number parser reads in a transcript (digits or number words)."""
    return [n.value for n in find_numbers(tokens(_DIGIT_GROUP_COMMA_RE.sub("", text)))]


def numbers_recovered(reference: str, transcript: str) -> int:
    """How many of the reference's numbers the parser finds in the transcript (as a multiset)."""
    return sum((Counter(reference_numbers(reference)) & Counter(transcript_numbers(transcript))).values())


# --------------------------------------------------------------- run files


class ClipResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: str
    reference: str
    transcript: Optional[str] = None
    wer: Optional[float] = Field(default=None, ge=0)
    reference_words: int = Field(ge=0)
    detected_language: Optional[str] = None
    language_probability: Optional[float] = None
    transcript_script: Optional[str] = None
    repetition_loop: Optional[bool] = None
    # Numbers the reference writes in digits, and how many of them the
    # matcher's number parser finds in the transcript. None in run files
    # written before this field existed; ``rescore`` fills it in.
    reference_numbers: list[str] = Field(default_factory=list)
    numbers_recovered: Optional[int] = Field(default=None, ge=0)
    latency_ms: Optional[float] = Field(default=None, ge=0)
    audio_duration_s: Optional[float] = Field(default=None, ge=0)
    error: Optional[str] = None


class RealSpeechRun(BaseModel):
    """One pass of an ASR model over the real-speech manifest. Never mixed with RunManifest files."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["real-speech-external"] = KIND
    run_id: str
    created_at: datetime
    command: str
    git_commit: Optional[str] = None
    manifest_file: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset: dict[str, Any]
    asr_model: str
    asr_model_version: Optional[str] = None
    asr_config: dict[str, Any] = Field(default_factory=dict)
    language_policy: str
    hardware: dict[str, Any] = Field(default_factory=dict)
    warmup_runs: int = Field(default=0, ge=0)
    wall_time_s: Optional[float] = Field(default=None, ge=0)
    cost_note: Optional[str] = None
    rescored_from: Optional[str] = None
    results: list[ClipResult]


def score_clip(clip: dict[str, Any], transcript: str, **timing: Any) -> ClipResult:
    return ClipResult(
        clip_id=clip["id"],
        reference=clip["reference"],
        transcript=transcript,
        wer=wer(clip["reference"], transcript),
        reference_words=len(tokens(clip["reference"])),
        transcript_script=script_profile(transcript),
        repetition_loop=has_repetition_loop(transcript),
        reference_numbers=reference_numbers(clip["reference"]),
        numbers_recovered=numbers_recovered(clip["reference"], transcript),
        **timing,
    )


def run_realspeech(
    manifest: dict[str, Any],
    manifest_file: str,
    audio_dir: str | Path,
    transcriber: Any,
    command: str,
    language_policy: str = "auto",
    progress: Optional[Callable[[str], None]] = None,
) -> RealSpeechRun:
    if language_policy not in LANGUAGE_POLICIES:
        raise ValueError(f"language_policy must be one of {LANGUAGE_POLICIES}")
    audio_dir = Path(audio_dir)
    language = HINT_LANGUAGE if language_policy == "hint" else None
    clips = manifest["clips"]
    missing = [c["file"] for c in clips if not (audio_dir / c["file"]).is_file()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} clips missing from {audio_dir} (run `voicebench realspeech fetch`)")

    # The commit is read before decoding, so a commit made while a long run
    # is in progress is not recorded as the code that produced it.
    commit = git_commit(Path(manifest_file).resolve().parent)

    # One untimed call, as in voicebench.runner.run, so model loading does
    # not land in the first clip's latency.
    transcriber.transcribe_file(audio_dir / clips[0]["file"], language=None)

    results = []
    start = time.perf_counter()
    for i, c in enumerate(clips, 1):
        try:
            t = transcriber.transcribe_file(audio_dir / c["file"], language=language)
            r = score_clip(c, t.text, detected_language=t.detected_language,
                           language_probability=t.language_probability,
                           latency_ms=t.latency_ms, audio_duration_s=t.audio_duration_s)
        except ASRUnavailable:
            raise
        except Exception as exc:  # one bad clip should not sink the run
            r = ClipResult(clip_id=c["id"], reference=c["reference"],
                           reference_words=len(tokens(c["reference"])), error=f"{type(exc).__name__}: {exc}")
        results.append(r)
        if progress:
            progress(f"[{i}/{len(clips)}] {c['id']} wer={r.wer if r.wer is None else round(r.wer, 2)} "
                     f"lang={r.detected_language} {r.transcript or r.error}")
    wall = round(time.perf_counter() - start, 2)

    desc = transcriber.describe()
    created = datetime.now(timezone.utc)
    ds = manifest["dataset"]
    return RealSpeechRun(
        run_id=f"{created:%Y%m%dT%H%M%SZ}-{desc['name'].replace('/', '-')}-realspeech-fleurs-{ds['config']}-{language_policy}",
        created_at=created,
        command=command,
        git_commit=commit,
        manifest_file=manifest_file,
        manifest_sha256=file_sha256(manifest_file),
        dataset={k: ds[k] for k in ("name", "hf_repo", "revision", "config", "split", "license")},
        asr_model=desc["name"],
        asr_model_version=desc.get("backend_version"),
        asr_config=desc,
        language_policy=language_policy,
        hardware=hardware_info(),
        warmup_runs=1,
        wall_time_s=wall,
        cost_note=getattr(transcriber, "cost_note", None),
        results=results,
    )


def rescore_realspeech(previous: RealSpeechRun, command: str) -> RealSpeechRun:
    """Recompute WER, script and loop flags of saved transcripts with the current code; no audio is decoded."""
    results = []
    for old in previous.results:
        if old.error is not None or old.transcript is None:
            results.append(old)
            continue
        clip = {"id": old.clip_id, "reference": old.reference}
        results.append(score_clip(clip, old.transcript, detected_language=old.detected_language,
                                  language_probability=old.language_probability,
                                  latency_ms=old.latency_ms, audio_duration_s=old.audio_duration_s))
    commit = git_commit(Path(previous.manifest_file).resolve().parent)
    return previous.model_copy(update={
        "run_id": f"{previous.run_id}-rescored-{(commit or 'nogit')[:7]}",
        "created_at": datetime.now(timezone.utc),
        "command": command,
        "git_commit": commit,
        "rescored_from": previous.run_id,
        "results": results,
    })


def load_realspeech_run(path: str | Path) -> RealSpeechRun:
    return RealSpeechRun.model_validate_json(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- analysis


def clip_category(r: ClipResult, language_policy: str) -> Optional[str]:
    """Primary category of a clip, using the applicable rules of voicebench.analysis in their order.

    None for a clip with WER 0; "recognition_error" for any other clip that
    none of the earlier rules explain.
    """
    if r.error is not None:
        return "pipeline_error"
    if language_policy == "auto" and r.detected_language and r.detected_language != HINT_LANGUAGE:
        return "wrong_language"
    if r.repetition_loop:
        return "repetition_loop"
    if r.wer:
        return "recognition_error"
    return None


def summarise_realspeech(run: RealSpeechRun) -> dict[str, Any]:
    ok = [r for r in run.results if r.error is None]
    timed = [r for r in ok if r.latency_ms is not None and r.audio_duration_s]
    lat = [r.latency_ms for r in timed]
    rtf = [r.latency_ms / 1000 / r.audio_duration_s for r in timed]
    wers = [r.wer for r in ok if r.wer is not None]
    on_hindi = [r for r in ok if r.detected_language == HINT_LANGUAGE]
    with_numbers = [r for r in ok if r.reference_numbers and r.numbers_recovered is not None]
    return {
        "run_id": run.run_id,
        "kind": run.kind,
        "dataset": run.dataset,
        "asr_model": run.asr_model,
        "language_policy": run.language_policy,
        "n": len(run.results),
        "errors": len(run.results) - len(ok),
        "reference_words": sum(r.reference_words for r in ok),
        "corpus_wer": corpus_wer((r.reference, r.transcript or "") for r in ok) if ok else None,
        # Clips auto-detect labelled Hindi only; with the hint this equals corpus_wer.
        "corpus_wer_detected_hi": corpus_wer((r.reference, r.transcript or "") for r in on_hindi) if on_hindi else None,
        "n_detected_hi": len(on_hindi),
        # Diagnostic only, not the headline: corpus WER when nukta and
        # chandrabindu spellings are folded on both sides (textnorm.fold_spelling_variants).
        "corpus_wer_spelling_folded": corpus_wer(
            (fold_spelling_variants(normalise(r.reference)), fold_spelling_variants(normalise(r.transcript or "")))
            for r in ok) if ok else None,
        "clip_wer_mean": sum(wers) / len(wers) if wers else None,
        "clip_wer_median": percentile(wers, 50),
        "clips_wer_zero": sum(1 for w in wers if w == 0),
        "clips_wer_over_1": sum(1 for w in wers if w > 1),
        "detected_languages": dict(Counter(r.detected_language for r in ok).most_common()),
        "transcript_scripts": dict(Counter(r.transcript_script for r in ok).most_common()),
        "repetition_loops": sum(1 for r in ok if r.repetition_loop),
        "transcripts_with_devanagari_digits": sum(1 for r in ok if re.search("[०-९]", r.transcript or "")),
        # U+FFFD: Whisper stopped in the middle of a multi-byte character.
        "transcripts_with_replacement_char": sum(1 for r in ok if "\ufffd" in (r.transcript or "")),
        "clips_with_numbers": len(with_numbers),
        "reference_numbers": sum(len(r.reference_numbers) for r in with_numbers),
        "numbers_recovered": sum(r.numbers_recovered for r in with_numbers) if with_numbers else None,
        "categories": dict(Counter(c for c in (clip_category(r, run.language_policy) for r in run.results)
                                   if c is not None).most_common()),
        "audio_s": sum(r.audio_duration_s or 0 for r in ok),
        "latency_p50_ms": percentile(lat, 50),
        "latency_p95_ms": percentile(lat, 95),
        "latency_p50_loop_ms": percentile([r.latency_ms for r in timed if r.repetition_loop], 50),
        "latency_p50_no_loop_ms": percentile([r.latency_ms for r in timed if not r.repetition_loop], 50),
        "rtf_p50": percentile(rtf, 50),
        "rtf_p95": percentile(rtf, 95),
        "wall_time_s": run.wall_time_s,
        "hardware": run.hardware,
    }


def compare_realspeech(a: RealSpeechRun, b: RealSpeechRun) -> dict[str, Any]:
    """Clip-by-clip comparison of two runs over the same manifest (e.g. auto-detect vs language hint).

    ``misdetected`` are the clips run A labelled with a language other than
    Hindi; their corpus WER is given under both runs, which shows how much
    of the difference between the runs those clips account for.
    """
    if a.manifest_sha256 != b.manifest_sha256:
        raise ValueError("runs used different manifests")
    bb = {r.clip_id: r for r in b.results if r.error is None}
    pairs = [(r, bb[r.clip_id]) for r in a.results if r.error is None and r.clip_id in bb]
    mis = [(x, y) for x, y in pairs if x.detected_language != HINT_LANGUAGE]
    rest = [(x, y) for x, y in pairs if x.detected_language == HINT_LANGUAGE]
    wer_of = lambda rs_: corpus_wer((r.reference, r.transcript or "") for r in rs_) if rs_ else None  # noqa: E731
    return {
        "a": a.run_id, "b": b.run_id, "compared": len(pairs),
        "identical_transcripts": sum(1 for x, y in pairs if x.transcript == y.transcript),
        "detected_hi_in_a": len(rest),
        "identical_where_a_detected_hi": sum(1 for x, y in rest if x.transcript == y.transcript),
        "misdetected_in_a": len(mis),
        "misdetected_wer_a": wer_of([x for x, _ in mis]),
        "misdetected_wer_b": wer_of([y for _, y in mis]),
        "loops_a": sum(1 for x, _ in pairs if x.repetition_loop),
        "loops_b": sum(1 for _, y in pairs if y.repetition_loop),
        "loops_both": sum(1 for x, y in pairs if x.repetition_loop and y.repetition_loop),
    }


def _variant_key(word: str) -> str:
    """A word with nasalisation and nukta marks folded, for spotting spelling-only differences."""
    return fold_spelling_variants(word)


_NUKTA = "\u093c"
_UNASPIRATE = str.maketrans("खघछझठढथधफभ", "कगचजटडतदपब")
_SHORTEN = str.maketrans("ीूईऊ", "िुइउ")


def word_error_breakdown(run: RealSpeechRun) -> dict[str, Any]:
    """Counts of word-level edits, with substitutions split by a small set of mechanical rules.

    The rules only look at the two words of a substitution:

    - ``digits``: either side contains a digit (ASCII or Devanagari).
    - ``script``: one side is Devanagari and the other Latin.
    - ``spelling_variant``: equal once chandrabindu/anusvara and nukta are folded.
    - ``aspiration``: then equal once aspirated consonants are written
      unaspirated (ख->क, घ->ग, छ->च, झ->ज, ठ->ट, ढ->ड, थ->त, ध->द, फ->प, भ->ब),
      e.g. "गंभीर" -> "गंबीर", "था" -> "ता".
    - ``vowel_length``: then equal once long i/u are written short (ी->ि, ू->ु, ई->इ, ऊ->उ).
    - ``other``: anything else.

    These are descriptions of the errors, not corrections: WER counts all of them.

    Insertions and deletions are counted as they are; ``split_or_join``
    counts reference words that the hypothesis wrote as two adjacent words,
    or two adjacent reference words written as one (each counted once).
    """
    subs: Counter = Counter()
    ins = dels = hits = split_join = nukta_kept = nukta_dropped = 0
    pairs: Counter = Counter()
    for r in run.results:
        if r.error is not None or not r.transcript:
            continue
        ref, hyp = tokens(r.reference), tokens(r.transcript)
        if not hyp:
            dels += len(ref)
            continue
        out = jiwer.process_words(" ".join(ref), " ".join(hyp))
        for chunk in out.alignments[0]:
            rw, hw = ref[chunk.ref_start_idx:chunk.ref_end_idx], hyp[chunk.hyp_start_idx:chunk.hyp_end_idx]
            if chunk.type == "equal":
                hits += len(rw)
                nukta_kept += sum(1 for w in rw if _NUKTA in w)
            elif chunk.type == "insert":
                ins += len(hw)
            elif chunk.type == "delete":
                dels += len(rw)
            else:
                for a, b in zip(rw, hw):
                    if any(ch.isdigit() for ch in a + b):
                        kind = "digits"
                    elif script_profile(a) != script_profile(b) and {script_profile(a), script_profile(b)} == {"devanagari", "latin"}:
                        kind = "script"
                    elif _variant_key(a) == _variant_key(b):
                        kind = "spelling_variant"
                        nukta_dropped += _NUKTA in a and _NUKTA not in b
                    elif _variant_key(a).translate(_UNASPIRATE) == _variant_key(b).translate(_UNASPIRATE):
                        kind = "aspiration"
                    elif _variant_key(a).translate(_SHORTEN) == _variant_key(b).translate(_SHORTEN):
                        kind = "vowel_length"
                    else:
                        kind = "other"
                    subs[kind] += 1
                    pairs[(kind, a, b)] += 1
        # split / join: "a b" in one side equals one word of the other side
        joined_hyp = {hyp[i] + hyp[i + 1] for i in range(len(hyp) - 1)}
        joined_ref = {ref[i] + ref[i + 1] for i in range(len(ref) - 1)}
        split_join += sum(1 for w in set(ref) - set(hyp) if w in joined_hyp)
        split_join += sum(1 for w in set(hyp) - set(ref) if w in joined_ref)
    return {
        "hits": hits,
        "substitutions": dict(subs.most_common()),
        "insertions": ins,
        "deletions": dels,
        "split_or_join": split_join,
        # Reference words with a nukta that the transcript got right with the
        # nukta, and right except for a missing nukta.
        "nukta_kept": nukta_kept,
        "nukta_dropped": nukta_dropped,
        "top_pairs": {k: [(a, b, n) for (kk, a, b), n in pairs.most_common() if kk == k][:10]
                      for k in subs},
    }


def format_realspeech(summary: dict[str, Any], breakdown: Optional[dict[str, Any]] = None) -> str:
    ds = summary["dataset"]
    f2 = lambda x: "-" if x is None else f"{x:.3f}"  # noqa: E731
    lines = [
        f"run {summary['run_id']}  [REAL SPEECH, external audio: {ds['name']} {ds['config']}/{ds['split']}, "
        f"{ds['license']}]",
        f"asr={summary['asr_model']}  language policy={summary['language_policy']}  "
        f"clips={summary['n']}  errors={summary['errors']}  reference words={summary['reference_words']}",
        "",
        f"corpus WER                 {f2(summary['corpus_wer'])}",
        f"corpus WER, detected hi    {f2(summary['corpus_wer_detected_hi'])}  ({summary['n_detected_hi']} clips)",
        f"corpus WER, nukta/chandrabindu folded (diagnostic) {f2(summary['corpus_wer_spelling_folded'])}",
        f"per-clip WER mean / median {f2(summary['clip_wer_mean'])} / {f2(summary['clip_wer_median'])}",
        f"clips with WER 0 / WER > 1 {summary['clips_wer_zero']} / {summary['clips_wer_over_1']}",
        f"detected language          " + ", ".join(f"{k}={v}" for k, v in summary["detected_languages"].items()),
        f"transcript script          " + ", ".join(f"{k}={v}" for k, v in summary["transcript_scripts"].items()),
        f"repetition loops           {summary['repetition_loops']}",
        f"transcripts with Devanagari digits / U+FFFD  {summary['transcripts_with_devanagari_digits']} / "
        f"{summary['transcripts_with_replacement_char']}",
        f"numbers recovered          "
        + ("-" if summary["numbers_recovered"] is None else
           f"{summary['numbers_recovered']} of {summary['reference_numbers']} reference numbers "
           f"({summary['clips_with_numbers']} clips), read by the matcher's number parser"),
        f"primary categories         " + ", ".join(f"{k}={v}" for k, v in summary["categories"].items()),
    ]
    if summary["latency_p50_ms"] is not None:
        lines.append(f"latency p50 / p95          {summary['latency_p50_ms']:.0f} / {summary['latency_p95_ms']:.0f} ms"
                     f"  (RTF {summary['rtf_p50']:.2f} / {summary['rtf_p95']:.2f}, {summary['audio_s']:.0f} s audio)")
    if summary["latency_p50_loop_ms"] is not None:
        lines.append(f"latency p50 loop / no loop {summary['latency_p50_loop_ms']:.0f} / "
                     f"{summary['latency_p50_no_loop_ms']:.0f} ms")
    if summary.get("wall_time_s") is not None:
        lines.append(f"wall time                  {summary['wall_time_s']:.0f} s")
    hw = summary.get("hardware") or {}
    if hw:
        lines.append(f"hardware                   {hw.get('cpu')}, {hw.get('logical_cpus')} logical CPUs")
    if breakdown:
        lines += ["", f"word edits: hits={breakdown['hits']} insertions={breakdown['insertions']} "
                      f"deletions={breakdown['deletions']} split_or_join={breakdown['split_or_join']}",
                  "substitutions: " + ", ".join(f"{k}={v}" for k, v in breakdown["substitutions"].items()),
                  f"nukta words otherwise right: nukta kept {breakdown['nukta_kept']}, "
                  f"dropped {breakdown['nukta_dropped']}"]
        for kind, rows in breakdown["top_pairs"].items():
            if kind == "other":
                continue
            lines.append(f"  {kind}: " + "; ".join(f"{a}->{b} x{n}" for a, b, n in rows))
    return "\n".join(lines)
