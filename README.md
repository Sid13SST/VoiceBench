# VoiceBench

[![CI](https://github.com/Sid13SST/VoiceBench/actions/workflows/ci.yml/badge.svg)](https://github.com/Sid13SST/VoiceBench/actions/workflows/ci.yml)

A small evaluation harness for voice agents that serve Hindi, English and
Hindi-English (code-switched) callers, including calls with background noise
and interruptions.

> **Status: day 6 of 7.** Full baseline runs with latency and cost are below
> and can be browsed in a local dashboard (`make run`). CI, reproducibility
> notes and limitations are in place. The failure analysis (day 7) is still to come.

## Baseline (Whisper `small`, synthetic espeak-ng audio)

Task success means the matcher got the right intent *and* every expected
slot from the transcript. WER is corpus-level after lower-casing and removing
punctuation. It can go above 1.0 when the model adds words, for example when
it gets stuck repeating a phrase. Numbers come from the day 5 runs in
[`results/`](results/README.md) (`make bench` and `make bench POLICY=hint`,
commit `20939304`).

| language | n | task success, auto-detect | task success, language hint | WER auto | WER hint |
|----------|---|---------------------------|-----------------------------|----------|----------|
| en       | 17 | 14/17 | 14/17 | 0.39 | 0.39 |
| hi       | 17 | 0/17  | 1/17  | 3.02 | 1.12 |
| hi-en    | 16 | 4/16  | 0/16  | 1.50 | 1.42 |
| **all**  | 50 | 18/50 | 15/50 | 1.63 | 0.97 |

**Latency and cost** (CPU only: 4 vCPU Xeon @ 2.10 GHz, int8, after one
warm-up call; 50 clips, 198.9 s of audio):

| run | p50 latency | p95 latency | real-time factor p50 / p95 | wall time | cost |
|-----|-------------|-------------|----------------------------|-----------|------|
| auto-detect   | 2886 ms | 11707 ms | 0.78 / 2.45 | 183 s | 0 USD |
| language hint | 2749 ms | 10968 ms | 0.79 / 2.08 | 177 s | 0 USD |

Cost is 0 USD because inference is local, with no per-call charge.
Electricity and hardware are not counted. p95 is driven by the few clips
where Whisper got stuck repeating itself: everything else stays near p50.
With 50 clips, p95 is roughly the third-slowest clip. Latency only
compares between runs on the same hardware.

What these numbers do and don't say:

- **The audio is espeak-ng's robotic synthetic speech, not real callers.**
  The Hindi failures may come mostly from espeak-ng's Hindi being hard to
  understand rather than from Whisper's Hindi. This benchmark can't yet tell
  those apart. Natural, properly licensed Hindi speech would be needed.
- With auto-detect, Whisper didn't identify a single Hindi or Hindi-English
  clip as Hindi. It guessed `en`, `hu`, `la`, `ro`, `de` and `ja`, and
  wrote every transcript in Latin script.
- With the language hint, Hindi WER drops from 3.02 to 1.12, but task
  success barely moves (0 → 1 of 17). The words are recognised too poorly
  for the matcher. On hi-en the hint *hurts*: Whisper writes the English
  words in Devanagari, often misspelled ("क्रेदिट"), so the matcher misses them.
- On the same machine, re-running gives identical transcripts. On a
  different CPU (the day 3 runs), 22 to 33 of 50 transcripts changed, almost
  all of them already-garbled Hindi output, while no scenario changed between
  pass and fail. Hindi WER is therefore not a stable number across machines.
  See [`results/README.md`](results/README.md).
- n is 16 or 17 per language, and as small as 3 per language × condition
  cell. Treat differences of one or two scenarios as noise.
- Some passes are lucky. In the barge-in clip `v1-044` the transcript is
  mostly the agent's own prompt, yet it contains "agent", so the intent
  matches.

## Limitations

Read every number above with these in mind.

**The audio**
- **All speech is synthetic espeak-ng output**: one formant-synthesised
  (robotic-sounding) voice per language, with no accents, ages, genders or
  speaking styles. Nobody has listened to the clips to judge how
  intelligible the Hindi is. The benchmark can't yet tell "Whisper is bad
  at Hindi" apart from "espeak-ng Hindi is hard to recognise".
- **Not telephone audio.** Clips are clean 16 kHz wideband. Real calls are
  usually 8 kHz narrowband with codec artefacts and packet loss; none of that
  is simulated.
- **Noise is synthetic** (white, pink, babble made from other synthetic
  utterances). It isn't recorded street, café or vehicle noise. SNR is
  measured over the whole clip, including 250 ms of silence at each end.
- **Barge-in is simplified**: the agent prompt and the caller are mixed into
  one channel, the prompt keeps playing (no barge-in detection), and there is
  no echo cancellation. Self-correction is only in the words.

**The measurement**
- **Small n**: 50 scenarios, 16 or 17 per language, as few as 3 per language ×
  condition cell. One scenario moves a cell's rate by up to 33 points. No
  confidence intervals are reported, and with these counts they would be wide.
- **The matcher's lexicon was written alongside the scenarios.** It reads
  all 50 reference texts correctly by design. Task success therefore
  measures how much ASR errors break a matcher that understands the clean
  text, not how well a real agent would understand new callers.
- **The matcher is told the domain** (bank, restaurant, travel, support),
  which makes intent detection easier than in an open-ended agent.
- **WER doesn't normalise numbers or script**: "5000" vs "five thousand" and
  English words written in Devanagari count as errors. Each transcript's
  script is recorded so script mismatches can be counted separately.
- **Transcripts vary across CPUs.** On one machine, runs are identical. On
  another CPU, 22 to 33 of 50 transcripts changed (no pass/fail changed),
  so Hindi WER isn't a stable number across machines
  ([details](docs/REPRODUCING.md)).
- **Latency** is CPU-only, from one 4-vCPU cloud machine. It times only the
  `transcribe` call (not audio I/O, the matcher or any network). It doesn't
  represent GPU or streaming deployments.
- **Cost 0 USD** means no per-call charge for local inference. Electricity,
  hardware and engineering time are not counted.
- **One ASR model** (Whisper `small`) and one decoding setup. Larger Whisper
  models or Indian-language ASR models may do much better on Hindi; they
  haven't been tried.

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
- `src/voicebench/dashboard/`: FastAPI dashboard over `results/`. It shows
  task success by language × condition, WER and intent accuracy per group,
  and a case browser filterable by status, language and condition. Each case
  has a word-level diff of reference vs transcript, intent and slot errors,
  and the audio clip. Read-only. Also serves JSON at `/api/runs` and
  `/api/runs/{id}`.
- `tests/`: unit tests for the schema and loader, plus tests that pin the
  makeup of `v1.jsonl`.

## Quick start

Requires Python 3.10+.

```bash
make setup      # creates .venv and installs the package with dev extras
make setup-locked   # same, with the exact versions used for the committed runs
make test       # runs pytest
make validate   # validates scenarios/v1.jsonl and prints its makeup
make audio      # regenerates audio/v1 (needs espeak-ng: apt-get install espeak-ng)
make audio-check    # regenerate in a temp dir and compare with the committed audio

make run        # dashboard at http://127.0.0.1:8000 (PORT=... to change)
make bench      # full run: Whisper "small", language auto-detect -> results/
make bench POLICY=hint MODEL=/path/to/ct2-whisper   # pass the language, use local weights
.venv/bin/voicebench report results/<run>.json
.venv/bin/voicebench rescore results/<run>.json   # re-score saved transcripts with current code
.venv/bin/voicebench compare results/<a>.json results/<b>.json   # which transcripts/outcomes differ

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
| 2 | synthetic audio via an offline TTS, noise mixing at a set SNR, local Whisper transcript adapter ✅ |
| 3 | runner and scoring: WER, rule-based intent/slot matching, task completion ✅ |
| 4 | FastAPI dashboard: pass/fail by language and condition, failing cases ✅ |
| 5 | latency p50/p95, cost per run, full run saved under `results/` ✅ |
| 6 | CI, reproducibility, data notes, limitations ✅ |
| 7 | final README, failure analysis from real results, v0.1.0 tag |

Progress notes, including what did not work, are in
[`docs/progress.md`](docs/progress.md). How to reproduce every committed
number: [`docs/REPRODUCING.md`](docs/REPRODUCING.md). Data sources and
licences: [`DATA_NOTES.md`](DATA_NOTES.md).

## Licence

MIT, see [LICENSE](LICENSE).
