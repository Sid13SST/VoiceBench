"""``voicebench gnani run|roundtrip``: the Gnani Voice QA lane on the command line.

Nothing is sent without ``--live``; without it each command prints what it
would send and exits 0. ``--live`` without ``GNANI_API_KEY`` exits 2.
A run stopped by 402 (out of credit) exits 3, by 401/403 or the request
cap 2; no run file is written for a stopped run. The request summary is
printed whenever a live run started, however it ended.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from voicebench.gnani import COMPARABILITY, lanes
from voicebench.gnani.budget import DEFAULT_MAX_REQUESTS


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _ids(value):
    return [i.strip() for i in value.split(",") if i.strip()] if value else None


def _command(args) -> str:
    return " ".join(["voicebench", *sys.argv[1:]]) if args.command is None else args.command


def _live_setup(args):
    """(client, budget), or an exit code after explaining why not."""
    from voicebench.gnani.budget import Budget, LiveRunRefused, require_live

    try:
        key = require_live(args.live)
    except LiveRunRefused as exc:
        _err(str(exc))
        return 2
    from voicebench.gnani.client import GnaniClient

    return GnaniClient(api_key=key, timeout_s=args.timeout), Budget(args.max_requests)


def _finish_live(client, budget, run_fn):
    """Run ``run_fn``; map aborts to exit codes; always print the request summary."""
    from voicebench.gnani.budget import BudgetExceeded, GnaniRunAborted
    from voicebench.gnani.client import GnaniError

    try:
        return run_fn()
    except GnaniRunAborted as exc:
        if exc.out_of_credit:
            _err("=" * 72 + "\nGNANI 402: OUT OF CREDIT. The run was stopped and no run file was written.\n"
                 f"{exc}\n" + "=" * 72)
            return 3
        _err(f"gnani: run stopped: {exc}")
        return 2
    except BudgetExceeded as exc:
        _err(f"gnani: run stopped: {exc}")
        return 2
    except GnaniError as exc:  # e.g. a 429 on the warm-up call of a real-speech run
        _err(f"gnani: run stopped: {type(exc).__name__}: {exc}")
        return 1
    except ValueError as exc:  # an option combination refused before any request
        _err(f"gnani: {exc}")
        return 1
    finally:
        print(budget.summary(client.http_attempts), file=sys.stderr)
        client.close()


def _cmd_run(args: argparse.Namespace) -> int:
    if args.lane == "synthetic":
        return _run_synthetic(args)
    return _run_realspeech(args)


def _transcriber(args, client, budget):
    from voicebench.gnani.transcriber import GnaniPrismaTranscriber

    return GnaniPrismaTranscriber(client, budget, model=args.model, format=args.format,
                                  auto_language_code=args.auto_language_code)


def _check_language(args) -> bool:
    from voicebench.gnani.transcriber import language_code_for

    if args.language_policy == "auto":
        try:
            language_code_for(None, args.model, args.auto_language_code)
        except ValueError as exc:
            _err(str(exc))
            return False
    return True


def _run_synthetic(args) -> int:
    from voicebench.cli import _load_scenarios
    from voicebench.report import format_table, summarise
    from voicebench.runner import save

    scenarios = _load_scenarios(args.scenarios)
    if scenarios is None or not _check_language(args):
        return 1
    try:
        picked = lanes.pick_scenarios(scenarios, lanes.items_for("synthetic", args.max_requests), _ids(args.ids))
        durations = lanes.audio_durations(args.audio)
    except (ValueError, OSError) as exc:
        _err(str(exc))
        return 1
    if not args.live:
        print(lanes.plan_text("synthetic", [(s.id, durations.get(s.id, 0.0)) for s in picked],
                              len(picked) + 1, args.max_requests, ", one of them the untimed warm-up call"))
        return 0
    setup = _live_setup(args)
    if isinstance(setup, int):
        return setup
    client, budget = setup

    def go() -> int:
        m = lanes.run_synthetic(_transcriber(args, client, budget), picked, len(scenarios), args.audio,
                                args.scenarios, _command(args), args.language_policy,
                                progress=(lambda s: _err(s)) if args.verbose else None)
        path = save(m, args.out)
        print(format_table(summarise(m, scenarios)))
        print(f"saved {path}  [{COMPARABILITY}]")
        return 0

    return _finish_live(client, budget, go)


def _run_realspeech(args) -> int:
    from voicebench import realspeech as rs
    from voicebench.runner import save

    if not _check_language(args):
        return 1
    try:
        manifest = rs.load_manifest(args.manifest)
        subset = lanes.realspeech_subset(manifest, rs.load_split(args.split),
                                         lanes.items_for("realspeech", args.max_requests),
                                         args.manifest, _ids(args.ids))
    except (ValueError, OSError, KeyError) as exc:
        _err(str(exc))
        return 1
    items = [(c["id"], c["num_samples"] / 16000) for c in subset["clips"]]
    if not args.live:
        print(lanes.plan_text("realspeech", items, len(items) + 1, args.max_requests,
                              ", one of them the untimed warm-up call"))
        return 0
    missing = [c["file"] for c in subset["clips"] if not (Path(args.audio) / c["file"]).is_file()]
    if missing:
        _err(f"{len(missing)} clips missing from {args.audio} (run `voicebench realspeech fetch`)")
        return 1
    setup = _live_setup(args)
    if isinstance(setup, int):
        return setup
    client, budget = setup

    def go() -> int:
        subset_file = lanes.write_subset(args.out, subset)
        run = rs.run_realspeech(subset, str(subset_file), args.audio, _transcriber(args, client, budget),
                                _command(args), language_policy=args.language_policy,
                                progress=(lambda s: _err(s)) if args.verbose else None)
        path = save(run, args.out)
        print(rs.format_realspeech(rs.summarise_realspeech(run)))
        print(f"saved {path} (clip subset {subset_file})  [{COMPARABILITY}]")
        return 0

    return _finish_live(client, budget, go)


def _cmd_roundtrip(args: argparse.Namespace) -> int:
    from voicebench.cli import _load_scenarios
    from voicebench.report import format_table, summarise
    from voicebench.runner import save

    scenarios = _load_scenarios(args.scenarios)
    if scenarios is None:
        return 1
    try:
        picked = lanes.pick_scenarios(scenarios, lanes.items_for("roundtrip", args.max_requests), _ids(args.ids))
    except ValueError as exc:
        _err(str(exc))
        return 1
    voices = {k: v for k, v in (("en", args.voice_en), ("hi", args.voice_hi), ("hi-en", args.voice_hi_en)) if v}
    if not args.live:
        chars = sum(len(s.reference) for s in picked)
        print(lanes.plan_text("roundtrip", [(s.id, 0.0) for s in picked], 2 * len(picked), args.max_requests,
                              f" to be synthesized ({chars} characters of text), one TTS and one STT request each"))
        return 0
    setup = _live_setup(args)
    if isinstance(setup, int):
        return setup
    client, budget = setup

    def go() -> int:
        from voicebench.gnani.roundtrip import GnaniRoundTripTranscriber

        cache = Path(args.cache) / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
        t = GnaniRoundTripTranscriber(client, budget, cache, tts_model=args.tts_model, voices=voices,
                                      speed=args.speed, stt_model=args.stt_model, stt_format=args.format)
        m = lanes.run_roundtrip(t, picked, len(scenarios), args.scenarios, _command(args),
                                progress=(lambda s: _err(s)) if args.verbose else None)
        path = save(m, args.out)
        audio_manifest = lanes.save_roundtrip_audio_manifest(t, path)
        print(format_table(summarise(m, scenarios)))
        print(f"saved {path} and {audio_manifest} (audio in {cache}, git-ignored)  [{COMPARABILITY}]")
        return 0

    return _finish_live(client, budget, go)


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS,
                   help=f"hard cap on billable requests for this run (default {DEFAULT_MAX_REQUESTS})")
    p.add_argument("--ids", default=None, metavar="ID,ID,...",
                   help="exactly these scenarios / clips instead of the default subset")
    p.add_argument("--live", action="store_true",
                   help="really call the Gnani API (uses credit; also needs GNANI_API_KEY). Without it: dry run")
    p.add_argument("--timeout", type=float, default=60.0, help="seconds per HTTP request")
    p.add_argument("--command", default=None, help=argparse.SUPPRESS)
    p.add_argument("-v", "--verbose", action="store_true")


def add_parser(sub) -> None:
    from voicebench import realspeech as rs

    p = sub.add_parser("gnani", help="Gnani Voice QA lane: Prisma STT / Timbre TTS as external APIs "
                                     "(separate from the local benchmark; docs/GNANI_QA.md)")
    gsub = p.add_subparsers(dest="gnani_command", required=True)

    p_run = gsub.add_parser("run", help="transcribe a small subset of the synthetic or FLEURS audio with Prisma")
    p_run.add_argument("--lane", choices=list(lanes.LANES), required=True)
    p_run.add_argument("--model", default="prisma-v3.0", choices=["prisma-v3.0", "prisma-v2.5"])
    p_run.add_argument("--format", default="verbatim", choices=["verbatim", "transcribe", "transliterate"])
    p_run.add_argument("--language-policy", choices=["auto", "hint"], default="auto",
                       help="auto: send --auto-language-code; hint: en-IN / hi-IN from the item's language")
    p_run.add_argument("--auto-language-code", default="hi-IN,en-IN",
                       help="language_code sent under --language-policy auto (prisma-v3.0: a list or indic-auto)")
    p_run.add_argument("--scenarios", default="scenarios/v1.jsonl")
    p_run.add_argument("--audio", default=None,
                       help=f"audio directory (default audio/v1, or {rs.DEFAULT_AUDIO_DIR} for realspeech)")
    p_run.add_argument("--manifest", default=rs.DEFAULT_MANIFEST)
    p_run.add_argument("--split", default=rs.DEFAULT_SPLIT)
    p_run.add_argument("--out", default=None, help="default results/gnani/<lane>")
    _common(p_run)
    p_run.set_defaults(func=_with_defaults(_cmd_run))

    p_rt = gsub.add_parser("roundtrip", help="synthesize scenario references with Timbre, transcribe with Prisma, "
                                             "score against the reference")
    p_rt.add_argument("--scenarios", default="scenarios/v1.jsonl")
    p_rt.add_argument("--tts-model", default="timbre-v2.5", choices=["timbre-v2.5", "timbre-v3.0"])
    p_rt.add_argument("--voice-en", default=None, help="default Kaveri (timbre-v2.5 catalog)")
    p_rt.add_argument("--voice-hi", default=None, help="default Nalini")
    p_rt.add_argument("--voice-hi-en", default=None, help="default Poorvi (Hinglish)")
    p_rt.add_argument("--speed", type=float, default=1.0)
    p_rt.add_argument("--stt-model", default="prisma-v3.0", choices=["prisma-v3.0", "prisma-v2.5"])
    p_rt.add_argument("--format", default="verbatim", choices=["verbatim", "transcribe", "transliterate"])
    p_rt.add_argument("--cache", default=".cache/gnani/roundtrip", help="where synthesized WAVs go (git-ignored)")
    p_rt.add_argument("--out", default=lanes.DEFAULT_OUT["roundtrip"])
    _common(p_rt)
    p_rt.set_defaults(func=_cmd_roundtrip)


def _with_defaults(fn):
    from voicebench import realspeech as rs

    def wrapped(args):
        if args.audio is None:
            args.audio = "audio/v1" if args.lane == "synthetic" else rs.DEFAULT_AUDIO_DIR
        if args.out is None:
            args.out = lanes.DEFAULT_OUT[args.lane]
        return fn(args)

    return wrapped
