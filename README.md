# VoiceBench

A small evaluation harness for voice agents that serve Hindi, English and
Hindi-English (code-switched) callers, including calls with background noise
and interruptions.

> **Status: day 3 of 7.** First baseline runs exist (below). The dashboard,
> latency/cost reporting and the failure analysis are still to come.

## First baseline (Whisper `small`, synthetic espeak-ng audio)

Task success means the matcher got the right intent *and* every expected
slot from the transcript. WER is corpus-level after lower-casing and removing
punctuation. It can go above 1.0 when the model adds words, for example when
it gets stuck repeating a phrase. Run files and the exact setup are in
[`results/`](results/README.md).

| language | n | task success, auto-detect | task success, language hint | WER auto | WER hint |
|----------|---|---------------------------|-----------------------------|----------|----------|
| en       | 17 | 13/17 | 13/17 | 0.39 | 0.39 |
| hi       | 17 | 0/17  | 1/17  | 4.30 | 0.88 |
| hi-en    | 16 | 4/16  | 0/16  | 1.48 | 1.54 |
| **all**  | 50 | 17/50 | 14/50 | 2.05 | 0.93 |

What these numbers do and don't say:

- **The audio is espeak-ng's robotic synthetic speech, not real callers.**
  The Hindi failures may come mostly from espeak-ng's Hindi being hard to
  understand rather than from Whisper's Hindi. This benchmark can't yet tell
  those apart. Natural, properly licensed Hindi speech would be needed.
- With auto-detect, Whisper didn't identify a single Hindi or Hindi-English
  clip as Hindi. It guessed `en`, `hu`, `la`, `ro`, `de` and `ja`, and
  wrote every transcript in Latin script.
- With the language hint, Hindi WER drops from 4.30 to 0.88, but task
  success barely moves (0 → 1 of 17). The words are recognised too poorly
  for the matcher. On hi-en the hint *hurts*: Whisper writes the English
  words in Devanagari, often misspelled ("क्रेदिट"), so the matcher misses them.
- n is 16 or 17 per language, and as small as 3 per language × condition
  cell. Treat differences of one or two scenarios as noise.
- Some passes are lucky. In the barge-in clip `v1-044` the transcript is
  mostly the agent's own prompt, yet it contains "agent", so the intent
  matches.

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
- `src/voicebench/textnorm.py`, `metrics.py`: normalisation (lower case,
  punctuation only; numbers and script are *not* rewritten) and WER via jiwer.
  Group WER is corpus-level (total edits / total reference words).
- `src/voicebench/nlu/`: a rule-based intent and slot matcher standing in for
  the agent's language understanding. It handles English, Devanagari and
  romanised Hindi, number words ("दो हज़ार" → 2000, "four eight two one" →
  4821) and self-corrections (the last mention wins). **Its lexicon was
  written alongside the v1 scenarios**, so v1 scores show how ASR errors
  break a matcher that reads the clean text perfectly. They don't show how
  the matcher would do on new phrasings.
- `src/voicebench/scoring.py`, `runner.py`, `report.py`: per-scenario WER,
  intent and slot correctness, and task success (right intent *and* every
  expected slot right). Runs are saved to `results/` with the command, git
  commit, scenario hash and ASR config, and broken down by language,
  condition and domain.
- `tests/`: unit tests for the schema and loader, plus tests that pin the
  makeup of `v1.jsonl`.

## Quick start

Requires Python 3.10+.

```bash
make setup      # creates .venv and installs the package with dev extras
make test       # runs pytest
make validate   # validates scenarios/v1.jsonl and prints its makeup
make audio      # regenerates audio/v1 (needs espeak-ng: apt-get install espeak-ng)

make bench      # full run: Whisper "small", language auto-detect -> results/
make bench POLICY=hint MODEL=/path/to/ct2-whisper   # pass the language, use local weights
.venv/bin/voicebench report results/<run>.json

# pipeline check without ASR (reference text as transcript; not an ASR result)
.venv/bin/voicebench run --asr oracle --out /tmp/oracle

# transcribe a clip (downloads Whisper "small" from huggingface.co on first use,
# or pass --model /path/to/ctranslate2-whisper-dir)
.venv/bin/voicebench transcribe audio/v1/v1-002.wav --model small
```

## Plan

| day | scope |
|-----|-------|
| 1 | scenario/result schema, 50 scenarios, loader, validation, tests ✅ |
| 2 | synthetic audio via an offline TTS, noise mixing at a set SNR, local Whisper transcript adapter ✅ (adapter not yet run on real weights) |
| 3 | runner and scoring: WER, rule-based intent/slot matching, task completion ✅ (no ASR run yet) |
| 4 | FastAPI dashboard: pass/fail by language and condition, failing cases |
| 5 | latency p50/p95, cost per run, full run saved under `results/` |
| 6 | CI, reproducibility, data notes, limitations |
| 7 | final README, failure analysis from real results, v0.1.0 tag |

Progress notes, including what did not work, are in
[`docs/progress.md`](docs/progress.md).

## Licence

MIT, see [LICENSE](LICENSE).
