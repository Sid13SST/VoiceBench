# VoiceBench

A small evaluation harness for voice agents that serve Hindi, English and
Hindi-English (code-switched) callers, including calls with background noise
and interruptions.

> **Status: day 1 of 7. There are no results yet.** This repo has the
> scenario format, 50 scenarios, a loader/validator and tests. Audio, ASR,
> scoring and the dashboard come later. Any number in this README will come
> from a run committed in this repo that you can reproduce.

## What exists today

- `src/voicebench/schema.py`: pydantic models for a **scenario** (reference
  utterance, language, domain, acoustic condition, expected intent and slots)
  and for **results** and run manifests. Every result is marked `measured` or
  `fixture`, so test fixtures can never pass as real numbers.
- `scenarios/v1.jsonl`: 50 hand-written scenarios: 30 clean, 10 noisy (5 at
  5 dB and 5 at 10 dB SNR), 10 interruptions (barge-in and self-correction),
  across en / hi / hi-en and banking / food / travel / support. Conventions
  are in [`scenarios/README.md`](scenarios/README.md).
- `src/voicebench/loader.py`: loads a JSONL file and reports every problem
  with its line number (bad JSON, schema errors, duplicate ids, mixed versions).
- `tests/`: unit tests for the schema and loader, plus tests that pin the
  makeup of `v1.jsonl`.

## Quick start

Requires Python 3.10+.

```bash
make setup      # creates .venv and installs the package with dev extras
make test       # runs pytest
make validate   # validates scenarios/v1.jsonl and prints its makeup
```

## Plan

| day | scope |
|-----|-------|
| 1 | scenario/result schema, 50 scenarios, loader, validation, tests ✅ |
| 2 | synthetic audio via an offline TTS, noise mixing at a set SNR, local Whisper transcript adapter |
| 3 | runner and scoring: WER, rule-based intent/slot matching, task completion |
| 4 | FastAPI dashboard: pass/fail by language and condition, failing cases |
| 5 | latency p50/p95, cost per run, full run saved under `results/` |
| 6 | CI, reproducibility, data notes, limitations |
| 7 | final README, failure analysis from real results, v0.1.0 tag |

Progress notes, including what did not work, are in
[`docs/progress.md`](docs/progress.md).

## Licence

MIT, see [LICENSE](LICENSE).
