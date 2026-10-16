# VoiceBench

A small evaluation harness for voice agents that serve Hindi, English and
Hindi-English (code-switched) callers, including calls with background noise
and interruptions.

> **Status: day 2 of 7. There are no results yet.** This repo has the
> scenario format, 50 scenarios, synthetic audio for each one, and a local
> Whisper adapter. **The Whisper adapter has not been run on real weights
> yet:** this build environment's network policy blocks `huggingface.co`, where
> the weights are hosted (details in [`docs/progress.md`](docs/progress.md)).
> Scoring and the dashboard come later. Any number in this README will come
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
- `src/voicebench/audio/`: offline TTS through **espeak-ng**, deterministic
  white / pink / babble noise, mixing at an exact SNR, and barge-in overlay.
  `audio/v1/` holds the 50 generated WAVs (all synthetic) plus a manifest with
  each file's voice, measured SNR, noise seed and sha256. Sources and licences
  are in [`DATA_NOTES.md`](DATA_NOTES.md).
- `src/voicebench/asr.py`: transcript adapter for a small local Whisper model
  via faster-whisper. Decoding is deterministic (temperature 0) and it times
  each call. No paid or remote APIs.
- `tests/`: unit tests for the schema and loader, plus tests that pin the
  makeup of `v1.jsonl`.

## Quick start

Requires Python 3.10+.

```bash
make setup      # creates .venv and installs the package with dev extras
make test       # runs pytest
make validate   # validates scenarios/v1.jsonl and prints its makeup
make audio      # regenerates audio/v1 (needs espeak-ng: apt-get install espeak-ng)

# transcribe a clip (downloads Whisper "small" from huggingface.co on first use,
# or pass --model /path/to/ctranslate2-whisper-dir)
.venv/bin/voicebench transcribe audio/v1/v1-002.wav --model small
```

## Plan

| day | scope |
|-----|-------|
| 1 | scenario/result schema, 50 scenarios, loader, validation, tests ✅ |
| 2 | synthetic audio via an offline TTS, noise mixing at a set SNR, local Whisper transcript adapter ✅ (adapter not yet run on real weights) |
| 3 | runner and scoring: WER, rule-based intent/slot matching, task completion |
| 4 | FastAPI dashboard: pass/fail by language and condition, failing cases |
| 5 | latency p50/p95, cost per run, full run saved under `results/` |
| 6 | CI, reproducibility, data notes, limitations |
| 7 | final README, failure analysis from real results, v0.1.0 tag |

Progress notes, including what did not work, are in
[`docs/progress.md`](docs/progress.md).

## Licence

MIT, see [LICENSE](LICENSE).
