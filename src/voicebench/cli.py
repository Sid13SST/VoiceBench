"""Command line entry point: ``python -m voicebench <command>``."""

from __future__ import annotations

import argparse
import sys

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
    from voicebench.audio.build import build_all
    from voicebench.audio.tts import EspeakTTS, TTSUnavailable

    scenarios = load_scenarios(args.path)
    command = f"voicebench synth {args.path} --out {args.out}"
    try:
        manifest = build_all(
            scenarios, args.out, EspeakTTS(),
            scenarios_file=args.path, scenarios_sha256=file_sha256(args.path), command=command,
        )
    except TTSUnavailable as exc:
        print(exc, file=sys.stderr)
        return 1
    total = sum(f["duration_s"] for f in manifest["files"])
    print(f"wrote {len(manifest['files'])} files ({total:.1f} s of audio) to {args.out} with {manifest['tts_engine']}")
    return 0


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voicebench")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="validate a scenario JSONL file")
    p_validate.add_argument("path")
    p_validate.set_defaults(func=_cmd_validate)

    p_synth = sub.add_parser("synth", help="generate synthetic audio for every scenario")
    p_synth.add_argument("path")
    p_synth.add_argument("--out", required=True)
    p_synth.set_defaults(func=_cmd_synth)

    p_tr = sub.add_parser("transcribe", help="transcribe WAV files with a local Whisper model")
    p_tr.add_argument("wav", nargs="+")
    p_tr.add_argument("--model", default="small", help="model name or local CTranslate2 directory")
    p_tr.add_argument("--language", default=None, help="Whisper language code; default auto-detect")
    p_tr.add_argument("--offline", action="store_true", help="never try to download weights")
    p_tr.set_defaults(func=_cmd_transcribe)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
