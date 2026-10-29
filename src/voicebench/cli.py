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


def _cmd_synth(args: argparse.Namespace) -> int:
    import json
    import tempfile

    from voicebench.audio.build import build_all
    from voicebench.audio.tts import EspeakTTS, TTSUnavailable

    scenarios = load_scenarios(args.path)
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
    scenarios = load_scenarios(args.scenarios)
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


def _cmd_rescore(args: argparse.Namespace) -> int:
    from voicebench.report import format_table, summarise
    from voicebench.runner import UnderstanderMismatch, load_run, rescore, save

    understand = _load_understander(args.understander)
    if understand is False:
        return 2
    previous = load_run(args.run)
    scenarios = load_scenarios(previous.scenarios_file)
    if file_sha256(previous.scenarios_file) != previous.scenarios_sha256:
        print("scenario file changed since this run; refusing to rescore", file=sys.stderr)
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
    from voicebench.runner import load_run

    c = compare_runs(load_run(args.a), load_run(args.b))
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
    from voicebench.runner import load_run

    run = load_run(args.run)
    scenarios = _scenarios_of_run(run, args.run, "analyze")
    if scenarios is None:
        return 1
    print(format_analysis(analyse_run(run, scenarios)))
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from voicebench.report import format_table, summarise
    from voicebench.runner import load_run

    run = load_run(args.run)
    scenarios = _scenarios_of_run(run, args.run, "report")
    if scenarios is None:
        return 1
    print(format_table(summarise(run, scenarios)))
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
