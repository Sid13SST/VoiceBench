"""Command line entry point: ``python -m voicebench <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from voicebench.loader import ScenarioFileError, file_sha256, load_scenarios, summarize


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        scenarios = load_scenarios(args.path)
    except ScenarioFileError as exc:
        print(exc, file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"{args.path}: no such file", file=sys.stderr)
        return 1
    print(f"{args.path}: {len(scenarios)} valid scenarios (version {scenarios[0].version})")
    print(f"sha256: {file_sha256(args.path)}")
    for dimension, counts in summarize(scenarios).items():
        if counts:
            parts = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            print(f"  {dimension}: {parts}")
    return 0


def _load_scenarios(path: str):
    """Load a scenario file, printing a clean error instead of a traceback."""
    try:
        return load_scenarios(path)
    except ScenarioFileError as exc:
        print(exc, file=sys.stderr)
    except FileNotFoundError:
        print(f"{path}: no such file", file=sys.stderr)
    return None


def _cmd_synth(args: argparse.Namespace) -> int:
    import json
    import tempfile

    from voicebench.audio.build import build_all
    from voicebench.audio.tts import EspeakTTS, TTSUnavailable

    scenarios = _load_scenarios(args.path)
    if scenarios is None:
        return 1
    command = f"voicebench synth {args.path} --out {args.out}"
    tmp = tempfile.TemporaryDirectory() if args.check else None
    out = tmp.name if tmp else args.out
    try:
        manifest = build_all(
            scenarios, out, EspeakTTS(),
            scenarios_file=args.path, scenarios_sha256=file_sha256(args.path), command=command,
        )
    except TTSUnavailable as exc:
        print(exc, file=sys.stderr)
        return 1
    if not args.check:
        total = sum(f["duration_s"] for f in manifest["files"])
        print(f"wrote {len(manifest['files'])} files ({total:.1f} s of audio) to {args.out} with {manifest['tts_engine']}")
        return 0

    from voicebench.audio.signal import max_sample_diff

    committed = json.loads((Path(args.out) / "manifest.json").read_text(encoding="utf-8"))
    want = {f["id"]: f["sha256"] for f in committed["files"]}
    got = {f["id"]: f["sha256"] for f in manifest["files"]}
    mismatched = sorted(i for i in want.keys() | got.keys() if want.get(i) != got.get(i))
    print(f"regenerated with {manifest['tts_engine']} (committed: {committed['tts_engine']})")
    worst = 0
    for i in mismatched:
        try:
            diff = max_sample_diff(Path(args.out) / f"{i}.wav", Path(out) / f"{i}.wav")
        except (FileNotFoundError, ValueError) as exc:
            print(f"  {i}: {exc}")
            diff = None
        else:
            print(f"  {i}: differs, max sample difference {diff} LSB (16-bit)")
        worst = max(worst, diff if diff is not None else 10**9)
    tmp.cleanup()
    if not mismatched:
        print(f"all {len(want)} files are byte-identical to {args.out}/manifest.json")
        return 0
    if worst <= args.tolerance_lsb:
        print(f"{len(mismatched)}/{len(want)} files differ, all within {args.tolerance_lsb} LSB: accepted")
        return 0
    print(f"{len(mismatched)}/{len(want)} files differ from {args.out}/manifest.json")
    return 1


def _cmd_transcribe(args: argparse.Namespace) -> int:
    from voicebench.asr import ASRUnavailable, FasterWhisperTranscriber

    asr = FasterWhisperTranscriber(args.model, local_files_only=args.offline)
    try:
        for path in args.wav:
            t = asr.transcribe_file(path, language=args.language)
            print(f"{path}\t[{t.detected_language}, {t.latency_ms:.0f} ms]\t{t.text}")
    except ASRUnavailable as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def _load_understander(spec):
    """None for the built-in matcher, the imported callable, or False after printing why not."""
    if spec is None:
        return None
    from voicebench.understanding import load_understander

    try:
        return load_understander(spec)
    except Exception as exc:  # bad spec, import error, or an error raised by the module itself
        print(f"could not load understander {spec!r}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False


def _cmd_run(args: argparse.Namespace) -> int:
    from voicebench.asr import ASRUnavailable, FasterWhisperTranscriber
    from voicebench.report import format_table, summarise
    from voicebench.runner import ReferenceTranscriber, run, save

    understand = _load_understander(args.understander)
    if understand is False:
        return 2
    scenarios = _load_scenarios(args.scenarios)
    if scenarios is None:
        return 1
    if args.asr == "oracle":
        transcriber = ReferenceTranscriber()
    else:
        transcriber = FasterWhisperTranscriber(args.model, local_files_only=args.offline)
    command = " ".join(["voicebench", *sys.argv[1:]]) if args.command is None else args.command
    try:
        manifest = run(
            scenarios, args.audio, transcriber, args.scenarios, command,
            language_policy=args.language_policy,
            progress=(lambda m: print(m, file=sys.stderr)) if args.verbose else None,
            understand=understand, understander=args.understander,
        )
    except ASRUnavailable as exc:
        print(exc, file=sys.stderr)
        return 2
    path = save(manifest, args.out)
    print(format_table(summarise(manifest, scenarios)))
    print(f"saved {path}")
    return 0


def _load_run(path: str):
    """Load a saved run file, printing a clean error instead of a traceback."""
    from pydantic import ValidationError

    from voicebench.runner import load_run

    try:
        return load_run(path)
    except FileNotFoundError:
        print(f"{path}: no such file", file=sys.stderr)
    except (ValidationError, ValueError) as exc:
        print(f"{path}: not a valid run file: {str(exc).splitlines()[0]}", file=sys.stderr)
    return None


def _cmd_rescore(args: argparse.Namespace) -> int:
    from voicebench.report import format_table, summarise
    from voicebench.runner import UnderstanderMismatch, rescore, save

    understand = _load_understander(args.understander)
    if understand is False:
        return 2
    previous = _load_run(args.run)
    if previous is None:
        return 1
    scenarios = _scenarios_of_run(previous, args.run, "rescore")
    if scenarios is None:
        return 1
    try:
        manifest = rescore(previous, scenarios, " ".join(["voicebench", *sys.argv[1:]]),
                           understand=understand, understander=args.understander)
    except UnderstanderMismatch as exc:
        print(f"{exc}. Pass the same --understander the run used (none for builtin).", file=sys.stderr)
        return 1
    path = save(manifest, args.out)
    print(format_table(summarise(manifest, scenarios)))
    print(f"saved {path}")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    from voicebench.compare import compare_runs

    a = _load_run(args.a)
    b = _load_run(args.b)
    if a is None or b is None:
        return 1
    try:
        c = compare_runs(a, b)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{c['a']}\n  vs {c['b']}")
    print(f"scenarios compared: {c['compared']}; same hardware: {c['same_hardware']}; "
          f"same model revision: {c['same_model']}")
    print(f"understander: A={c['understander_a']} B={c['understander_b']}")
    if c["understanders_differ"]:
        print(f"understanders differ: A={c['understander_a']} B={c['understander_b']} - "
              "this compares two systems, not a reproducibility check")
    print(f"transcripts differ: {len(c['transcripts_differ'])} {' '.join(c['transcripts_differ'])}")
    print(f"task outcome differs: {len(c['task_outcome_differs'])} "
          + " ".join(f"{i}({x}->{y})" for i, x, y in c["task_outcome_differs"]))
    return 0


def _scenarios_of_run(run, run_path: str, action: str):
    """Load the scenarios a saved run was scored against, or print why not and return None.

    A relative ``scenarios_file`` is looked up from the current directory, as
    ``rescore`` does, then from the run file's repository root (the parent of
    its results directory), as the dashboard does. A file whose sha256 does
    not match the run is refused, as ``rescore`` refuses it.
    """
    path = Path(run.scenarios_file)
    if not path.is_absolute() and not path.exists():
        path = Path(run_path).resolve().parent.parent / path
    if not path.exists():
        print(f"scenarios file not found: {run.scenarios_file}", file=sys.stderr)
        return None
    if file_sha256(path) != run.scenarios_sha256:
        print(f"scenario file changed since this run ({path}); refusing to {action}", file=sys.stderr)
        return None
    return load_scenarios(path)


def _cmd_analyze(args: argparse.Namespace) -> int:
    from voicebench.analysis import analyse_run, format_analysis

    run = _load_run(args.run)
    if run is None:
        return 1
    scenarios = _scenarios_of_run(run, args.run, "analyze")
    if scenarios is None:
        return 1
    try:
        analysis = analyse_run(run, scenarios)
    except KeyError as exc:
        print(f"run names scenario {exc} which is not in the scenario file", file=sys.stderr)
        return 1
    print(format_analysis(analysis))
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from voicebench.report import format_table, summarise

    run = _load_run(args.run)
    if run is None:
        return 1
    scenarios = _scenarios_of_run(run, args.run, "report")
    if scenarios is None:
        return 1
    print(format_table(summarise(run, scenarios)))
    return 0


def _cmd_realspeech_manifest(args: argparse.Namespace) -> int:
    import json

    from voicebench import realspeech as rs

    try:
        tsv = rs.hf_download(rs.FLEURS_TSV, local_files_only=args.offline)
        archive = rs.hf_download(rs.FLEURS_AUDIO, local_files_only=args.offline)
    except Exception as exc:
        print(f"could not download FLEURS {rs.FLEURS_CONFIG}/{rs.FLEURS_SPLIT}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2
    command = f"voicebench realspeech manifest --n {args.n} --seed {args.seed} --out {args.out}"
    manifest = rs.build_manifest(tsv.read_text(encoding="utf-8"), archive, args.n, args.seed, command,
                                 file_sha256(tsv), file_sha256(archive))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}: {len(manifest['clips'])} of {manifest['selection']['population']} clips, seed {args.seed}")
    return 0


def _cmd_realspeech_fetch(args: argparse.Namespace) -> int:
    from voicebench import realspeech as rs

    manifest = rs.load_manifest(args.manifest)
    if manifest["dataset"]["revision"] != rs.FLEURS_REVISION:
        print(f"{args.manifest} was built from revision {manifest['dataset']['revision']}, "
              f"this code downloads {rs.FLEURS_REVISION}", file=sys.stderr)
        return 1
    try:
        archive = rs.hf_download(rs.FLEURS_AUDIO, local_files_only=args.offline)
    except Exception as exc:
        print(f"could not download {rs.FLEURS_AUDIO}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    want = manifest["dataset"]["audio_archive"]["sha256"]
    if file_sha256(archive) != want:
        print(f"{archive}: sha256 does not match the manifest ({want})", file=sys.stderr)
        return 1
    try:
        n = rs.extract_clips(manifest, archive, args.audio)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{n['clips']} clips in {args.audio} ({n['written']} written, {n['already_present']} already there), "
          "all sha256 match the manifest")
    return 0


def _cmd_realspeech_run(args: argparse.Namespace) -> int:
    from voicebench import realspeech as rs
    from voicebench.asr import ASRUnavailable, FasterWhisperTranscriber
    from voicebench.runner import save

    manifest = rs.load_manifest(args.manifest)
    transcriber = FasterWhisperTranscriber(args.model, local_files_only=args.offline)
    command = " ".join(["voicebench", *sys.argv[1:]]) if args.command is None else args.command
    try:
        run = rs.run_realspeech(manifest, args.manifest, args.audio, transcriber, command,
                                language_policy=args.language_policy,
                                progress=(lambda m: print(m, file=sys.stderr)) if args.verbose else None)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    except ASRUnavailable as exc:
        print(exc, file=sys.stderr)
        return 2
    path = save(run, args.out)
    print(rs.format_realspeech(rs.summarise_realspeech(run)))
    print(f"saved {path}")
    return 0


def _load_realspeech_run(path: str):
    from pydantic import ValidationError

    from voicebench.realspeech import load_realspeech_run

    try:
        return load_realspeech_run(path)
    except FileNotFoundError:
        print(f"{path}: no such file", file=sys.stderr)
    except (ValidationError, ValueError) as exc:
        print(f"{path}: not a valid real-speech run file: {str(exc).splitlines()[0]}", file=sys.stderr)
    return None


def _cmd_realspeech_rescore(args: argparse.Namespace) -> int:
    from voicebench import realspeech as rs
    from voicebench.runner import save

    previous = _load_realspeech_run(args.run)
    if previous is None:
        return 1
    run = rs.rescore_realspeech(previous, " ".join(["voicebench", *sys.argv[1:]]))
    path = save(run, args.out)
    print(rs.format_realspeech(rs.summarise_realspeech(run)))
    print(f"saved {path}")
    return 0


def _cmd_realspeech_compare(args: argparse.Namespace) -> int:
    from voicebench import realspeech as rs

    a, b = _load_realspeech_run(args.a), _load_realspeech_run(args.b)
    if a is None or b is None:
        return 1
    try:
        c = rs.compare_realspeech(a, b)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    f = lambda x: "-" if x is None else f"{x:.3f}"  # noqa: E731
    print(f"{c['a']}\n  vs {c['b']}  (real speech, {c['compared']} clips)")
    print(f"identical transcripts: {c['identical_transcripts']}; of the {c['detected_hi_in_a']} clips A detected "
          f"as hi: {c['identical_where_a_detected_hi']}")
    print(f"clips A detected as another language: {c['misdetected_in_a']}, corpus WER "
          f"A {f(c['misdetected_wer_a'])} / B {f(c['misdetected_wer_b'])}")
    print(f"repetition loops: A {c['loops_a']}, B {c['loops_b']}, both {c['loops_both']}")
    return 0


def _cmd_realspeech_report(args: argparse.Namespace) -> int:
    from voicebench import realspeech as rs

    run = _load_realspeech_run(args.run)
    if run is None:
        return 1
    print(rs.format_realspeech(rs.summarise_realspeech(run), rs.word_error_breakdown(run)))
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    import uvicorn

    from voicebench.dashboard.app import create_app

    print(f"VoiceBench dashboard on http://{args.host}:{args.port}  (results: {args.results})")
    uvicorn.run(create_app(args.results, args.audio), host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voicebench")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="validate a scenario JSONL file")
    p_validate.add_argument("path")
    p_validate.set_defaults(func=_cmd_validate)

    p_synth = sub.add_parser("synth", help="generate synthetic audio for every scenario")
    p_synth.add_argument("path")
    p_synth.add_argument("--out", required=True)
    p_synth.add_argument("--check", action="store_true",
                         help="regenerate into a temp dir and compare hashes with OUT/manifest.json; writes nothing")
    p_synth.add_argument("--tolerance-lsb", type=int, default=0,
                         help="with --check: accept files whose samples differ by at most this many 16-bit steps")
    p_synth.set_defaults(func=_cmd_synth)

    p_tr = sub.add_parser("transcribe", help="transcribe WAV files with a local Whisper model")
    p_tr.add_argument("wav", nargs="+")
    p_tr.add_argument("--model", default="small", help="model name or local CTranslate2 directory")
    p_tr.add_argument("--language", default=None, help="Whisper language code; default auto-detect")
    p_tr.add_argument("--offline", action="store_true", help="never try to download weights")
    p_tr.set_defaults(func=_cmd_transcribe)

    p_run = sub.add_parser("run", help="run all scenarios through ASR + scoring and save results")
    p_run.add_argument("--scenarios", default="scenarios/v1.jsonl")
    p_run.add_argument("--audio", default="audio/v1")
    p_run.add_argument("--asr", choices=["faster-whisper", "oracle"], default="faster-whisper")
    p_run.add_argument("--model", default="small", help="Whisper model name or local CTranslate2 dir")
    p_run.add_argument("--language-policy", choices=["auto", "hint"], default="auto")
    p_run.add_argument("--offline", action="store_true", help="never try to download weights")
    p_run.add_argument("--out", default="results")
    p_run.add_argument("--understander", default=None, metavar="package.module:function",
                       help="replace the built-in matcher with this callable (docs/ADAPTERS.md); "
                            "imports and runs a TRUSTED local Python module; never point it at untrusted code")
    p_run.add_argument("--command", default=None, help=argparse.SUPPRESS)
    p_run.add_argument("-v", "--verbose", action="store_true")
    p_run.set_defaults(func=_cmd_run)

    p_res = sub.add_parser("rescore", help="re-score a saved run's transcripts with the current code")
    p_res.add_argument("run")
    p_res.add_argument("--out", default="results")
    p_res.add_argument("--understander", default=None, metavar="package.module:function",
                       help="must be the understander the run recorded; "
                            "imports and runs a TRUSTED local Python module; never point it at untrusted code")
    p_res.set_defaults(func=_cmd_rescore)

    p_cmp = sub.add_parser("compare", help="compare transcripts and outcomes of two runs")
    p_cmp.add_argument("a")
    p_cmp.add_argument("b")
    p_cmp.set_defaults(func=_cmd_compare)

    p_an = sub.add_parser("analyze", help="categorise the failures of a saved run")
    p_an.add_argument("run")
    p_an.set_defaults(func=_cmd_analyze)

    p_rep = sub.add_parser("report", help="print the breakdown of a saved run")
    p_rep.add_argument("run")
    p_rep.set_defaults(func=_cmd_report)

    p_real = sub.add_parser("realspeech", help="real-speech validation lane (FLEURS Hindi, external audio)")
    rsub = p_real.add_subparsers(dest="realspeech_command", required=True)
    from voicebench import realspeech as _rs

    p_rm = rsub.add_parser("manifest", help="(re)build the committed clip manifest; downloads from huggingface.co")
    p_rm.add_argument("--n", type=int, default=_rs.DEFAULT_N)
    p_rm.add_argument("--seed", type=int, default=_rs.DEFAULT_SEED)
    p_rm.add_argument("--out", default=_rs.DEFAULT_MANIFEST)
    p_rm.add_argument("--offline", action="store_true", help="use the Hugging Face cache only")
    p_rm.set_defaults(func=_cmd_realspeech_manifest)

    p_rf = rsub.add_parser("fetch", help="download the FLEURS archive and extract the manifest's clips (git-ignored)")
    p_rf.add_argument("--manifest", default=_rs.DEFAULT_MANIFEST)
    p_rf.add_argument("--audio", default=_rs.DEFAULT_AUDIO_DIR)
    p_rf.add_argument("--offline", action="store_true", help="use the Hugging Face cache only")
    p_rf.set_defaults(func=_cmd_realspeech_fetch)

    p_rr = rsub.add_parser("run", help="transcribe the manifest's clips with Whisper and save a real-speech run")
    p_rr.add_argument("--manifest", default=_rs.DEFAULT_MANIFEST)
    p_rr.add_argument("--audio", default=_rs.DEFAULT_AUDIO_DIR)
    p_rr.add_argument("--model", default="small", help="Whisper model name or local CTranslate2 dir")
    p_rr.add_argument("--language-policy", choices=list(_rs.LANGUAGE_POLICIES), default="auto",
                      help="auto: Whisper detects the language; hint: Whisper is told 'hi'")
    p_rr.add_argument("--offline", action="store_true", help="never try to download weights")
    p_rr.add_argument("--out", default=_rs.DEFAULT_RESULTS_DIR)
    p_rr.add_argument("--command", default=None, help=argparse.SUPPRESS)
    p_rr.add_argument("-v", "--verbose", action="store_true")
    p_rr.set_defaults(func=_cmd_realspeech_run)

    p_rs = rsub.add_parser("rescore", help="re-score a saved real-speech run's transcripts with the current code")
    p_rs.add_argument("run")
    p_rs.add_argument("--out", default=_rs.DEFAULT_RESULTS_DIR)
    p_rs.set_defaults(func=_cmd_realspeech_rescore)

    p_rc = rsub.add_parser("compare", help="compare two real-speech runs clip by clip (e.g. auto vs hint)")
    p_rc.add_argument("a")
    p_rc.add_argument("b")
    p_rc.set_defaults(func=_cmd_realspeech_compare)

    p_rp = rsub.add_parser("report", help="print WER, language, loop, latency and word-edit breakdown of a real-speech run")
    p_rp.add_argument("run")
    p_rp.set_defaults(func=_cmd_realspeech_report)

    p_dash = sub.add_parser("dashboard", help="serve the results dashboard")
    p_dash.add_argument("--results", default="results")
    p_dash.add_argument("--audio", default="audio/v1")
    p_dash.add_argument("--host", default="127.0.0.1")
    p_dash.add_argument("--port", type=int, default=8000)
    p_dash.set_defaults(func=_cmd_dashboard)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
