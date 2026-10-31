# Results

Each `*.json` file is one complete run (`voicebench.schema.RunManifest`):
per-scenario transcript, WER, predicted intent and slots, and latency, plus
the command, git commit, scenario-file sha256 and ASR config. They are
written by `voicebench run` and never edited by hand. `voicebench report
<file>` prints the breakdown.

The 2026-10-29 runs (`20261029T*`: re-runs at `0f996db` with rescores at `f430675`, and runs at `f4306752`) are described in [`docs/rerun_comparison.md`](../docs/rerun_comparison.md) and [`docs/benchmark_current_main.md`](../docs/benchmark_current_main.md).

## Real-speech runs

`results/realspeech/` holds run files of a different kind
(`voicebench.realspeech.RealSpeechRun`, `"kind": "real-speech-external"`):
Whisper on 150 human Hindi clips from Google FLEURS (`hi_in` test, CC BY
4.0, manifest `data/realspeech/fleurs_hi_in_test_150.json`). They are not
synthetic benchmark runs: no scenarios, intents or task success. The
synthetic tools (`report`, `analyze`, `compare`, `rescore`) do not read
them; use `voicebench realspeech report|compare|rescore`. The dashboard
lists them in a separate section.

| file | command |
|------|---------|
| `20261031T200244Z-faster-whisper-small-realspeech-fleurs-hi_in-auto.json` | `make realspeech` (see note) |
| `20261031T202136Z-faster-whisper-small-realspeech-fleurs-hi_in-hint.json` | `make realspeech POLICY=hint` (see note) |
| `…-auto-rescored-9336d77.json` | `voicebench realspeech rescore results/realspeech/20261031T200244Z-…-auto.json` |
| `…-hint-rescored-9336d77.json` | `voicebench realspeech rescore results/realspeech/20261031T202136Z-…-hint.json` |
| `…-auto-rescored-08a104e.json` | same command, at `08a104e` (day 9 number parser) |
| `…-hint-rescored-08a104e.json` | same command, at `08a104e` (day 9 number parser) |

- The two runs were started as
  `voicebench realspeech run --model small --language-policy {auto,hint} -v --command "make realspeech POLICY={auto,hint}"`:
  the command those make targets run, plus `-v` for progress output. The
  hidden `--command` flag only sets the recorded command string.
- Code at `6e3ddb7`, clean tree (recorded in each file); the audio came
  from `make realspeech-fetch`, all 150 sha256 matching the manifest.
  Model `Systran/faster-whisper-small@536b0662742c02347bc0e980a01041f333bce120`,
  faster-whisper 1.2.1, CPU int8, beam 5, temperature 0: the benchmark's
  settings. One untimed warm-up call each.
- Machine: Intel Xeon @ 2.10 GHz, 4 logical CPUs, the same CPU model as
  the day 5 and 2026-10-29 runs, but a different container.
- The rescores at `9336d77` keep every transcript, latency and language
  unchanged and add the per-clip reference numbers and how many the
  matcher's parser reads back. Read the figures from them:
  `voicebench realspeech report <rescored file>`.
- The rescores at `08a104e` differ from those at `9336d77` only in
  `numbers_recovered` (two clips per run), after the day 9 number-parser
  change. Add `--split data/realspeech/fleurs_hi_in_test_150_split.json`
  to `realspeech report` for the dev / held-out counts.
- Cost 0 USD, as for the benchmark.

## Day 5 runs (current synthetic baseline)

| file | command |
|------|---------|
| `20261018T132344Z-faster-whisper-small-auto.json` | `make bench` |
| `20261018T132652Z-faster-whisper-small-hint.json` | `make bench POLICY=hint` |
| `reproducibility/20261018T133015Z-faster-whisper-small-auto.json` | `make bench` again, same machine (written to a scratch directory, then copied here) |

- Code at commit `20939304ad73`, clean tree. Model
  `Systran/faster-whisper-small@536b0662742c02347bc0e980a01041f333bce120`,
  recorded in each file. faster-whisper 1.2.1, CPU int8, beam 5,
  temperature 0.
- Machine (recorded in each file): Intel Xeon @ 2.10 GHz, 4 logical CPUs,
  15.7 GB RAM, Linux. This is **not** the machine the day 3 runs used
  (Xeon @ 2.80 GHz), because cloud containers change between sessions.
- One untimed warm-up transcription before timing. Latency is the wall
  time of each `transcribe` call; it doesn't include loading audio or scoring.
- Cost: 0 USD. Local inference has no per-call charge. Electricity and
  hardware are real costs and are not counted. The file states this in
  `cost_note`.

### Reproducibility checks (`voicebench compare A B`)

| A | B | transcripts that differ | pass/fail that differ |
|---|---|---|---|
| day 5 auto | day 5 auto re-run, same machine | 0 / 50 | 0 |
| day 3 auto (rescored) | day 5 auto, different CPU | 22 / 50 | 0 |
| day 3 hint (rescored) | day 5 hint, different CPU | 33 / 50 | 0 |

On one machine, decoding is deterministic. Across CPUs, many transcripts
change: almost all are clips where Whisper already produced wrong-language
or garbled output, and the int8 kernels differ between CPUs. No scenario
changed between pass and fail, but **WER on the Hindi clips is not stable
across machines**: Hindi corpus WER with auto-detect was 4.30 on day 3 and
3.02 on day 5. Treat WER above about 1 as "unusable output" rather than a
precise number.

## Day 3 runs

| file | command | language policy |
|------|---------|-----------------|
| `20261016T080842Z-faster-whisper-small-auto.json` | `make bench` | auto-detect |
| `20261016T081450Z-faster-whisper-small-hint.json` | `make bench POLICY=hint` | scenario language passed to Whisper (hi-en → `hi`) |
| `…-auto-rescored-75a9e5c.json` | `voicebench rescore results/20261016T080842Z-faster-whisper-small-auto.json` | as auto run |
| `…-hint-rescored-75a9e5c.json` | `voicebench rescore results/20261016T081450Z-faster-whisper-small-hint.json` | as hint run |

The two `rescored` files reuse the original transcripts unchanged and score
them again at commit `75a9e5c`. That commit includes the fix that joins
digits Whisper writes as `7-3-1-0`. Compared with the originals, exactly one
scenario changes in each run: `v1-006` goes from fail to pass. The
originals stay here unchanged, so the effect of that fix can be checked.

The two original day 3 runs share this setup:

- Code at commit `40523cf`, clean tree.
- `scenarios/v1.jsonl`, sha256 `75fed5e1…aa1b`.
- Audio: `audio/v1`, synthetic espeak-ng 1.51.
- ASR: faster-whisper 1.2.1 (CTranslate2 4.8.3), model `small`, resolved to
  `Systran/faster-whisper-small@536b0662742c02347bc0e980a01041f333bce120`
  from the Hugging Face cache. CPU, int8, beam 5, temperature 0. These run
  files don't store the revision; it was read from the local cache. Runs from
  later commits record it automatically.
- Machine: cloud container, 4 vCPU Intel Xeon @ 2.80 GHz, no GPU. Latency
  depends heavily on hardware, so compare latency only between runs on the
  same machine.

Results are deterministic up to CPU numerics: decoding uses temperature 0
and no sampling. Re-running on different hardware may change a few tokens.
