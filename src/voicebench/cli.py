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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voicebench")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="validate a scenario JSONL file")
    p_validate.add_argument("path")
    p_validate.set_defaults(func=_cmd_validate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
