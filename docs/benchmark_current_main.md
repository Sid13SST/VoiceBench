# Benchmark re-run on current main (f4306752)

Two real benchmark runs (Whisper `small`, language policy `auto` and
`hint`) on commit `f4306752dcd2e3c7cf19e4c80c4cd345afc1897b`. They are
compared with the committed 2026-10-18 baseline and with the two re-runs at
commit `0f996db` described in `docs/rerun_comparison.md`. No source file was
changed.

New run files:

- `results/20261029T072645Z-faster-whisper-small-auto.json`
- `results/20261029T073031Z-faster-whisper-small-hint.json`

## Method

- **Automated run in a cloud container** (Claude Code remote session), on
  2026-10-29.
- **Preflight.** After `git fetch origin`, `origin/main` and
  `git ls-remote origin refs/heads/main` both returned
  `f4306752dcd2e3c7cf19e4c80c4cd345afc1897b`, the expected commit. The work
  branch was created from `origin/main`. `git rev-parse HEAD` returned that
  SHA and `git status` was clean before the runs. Both run files record
  `git_commit` = `f4306752dcd2e3c7cf19e4c80c4cd345afc1897b`, with no `-dirty`
  suffix.
- **Install.** `make setup` (`pip install -e ".[dev,asr]"` in `.venv`, as in
  the README and CI). `espeak-ng` was not installed, so it was added with
  `apt-get install espeak-ng` (1.51+dfsg-12build1).
- **Checks** (run at f4306752, before the benchmark):
  - `voicebench validate scenarios/v1.jsonl`: 50 valid scenarios, sha256
    `75fed5e1…a1aa1b`. By language: en=17, hi=17, hi-en=16. By condition:
    clean=30, interruption=10, noise=10.
  - `python -m pytest`: **271 passed, 1 skipped**. The README says
    "205 tests pass", which does not match this commit.
  - `make audio-check` (`synth … --check`, no tolerance flag): "all 50
    files are byte-identical to audio/v1/manifest.json".
- **Runs.** These are the commands `make bench` and `make bench POLICY=hint`
  execute, except that `--out` points to a fresh directory instead of
  `results/`:
  - `voicebench run --model small --language-policy auto --out /tmp/rerun-main`
  - `voicebench run --model small --language-policy hint --out /tmp/rerun-main`

  The two runs used the same container and commit and ran one after the
  other: auto from 07:22:19 to 07:26:45 UTC, hint from 07:26:52 to
  07:30:32 UTC. The weights were downloaded from huggingface.co (reachable,
  HTTP 200) at revision `Systran/faster-whisper-small@536b0662742c02347bc0e980a01041f333bce120`,
  the same revision as all the runs compared here. The two run files were
  then copied into `results/` under their generated names. No file of that
  name existed there before.
- **Metrics.** Aggregates come from `voicebench.report.summarise`. The
  per-scenario lists come from `voicebench.compare.compare_runs` plus direct
  field comparison. The `0f996db` run files were read with `git show` and
  were not copied into the branch this document was written on; they are
  now in `results/` under the names listed below.

### Environment

| item | value |
|---|---|
| CPU (`hardware.cpu`) | Intel(R) Xeon(R) Processor @ 2.10GHz, 4 logical CPUs (1 thread per core, 1 socket) |
| RAM | 15.7 GB (manifest); 16091 MB total from `free -m`, no swap |
| kernel | Linux 6.18.44-fc-v185 x86_64 |
| python | 3.13.17 |
| pip | 26.2.2 |
| espeak-ng | 1.51+dfsg-12build1 (installed with apt for this run) |
| huggingface.co | reachable |

### Installed vs locked package versions

`requirements-lock.txt` lists the environment of the day 5 runs. It says
Python 3.13.16. Here, `make setup` installed the latest allowed versions
instead of the locked ones. 13 packages differ (`pip freeze` vs lock):

| package | locked | installed |
|---|---|---|
| av | 19.0.1 | 19.0.2 |
| certifi | 2026.7.22 | 2026.10.23 |
| ctranslate2 | 4.8.3 | **4.8.4** |
| fastapi | 0.144.0 | 0.162.0 |
| filelock | 4.2.2 | 4.2.4 |
| hf-xet | 1.7.0 | 1.7.1 |
| httpcore2 | 2.13.1 | 2.16.0 |
| httpx2 | 2.13.1 | 2.16.0 |
| huggingface_hub | 2.2.0 | 2.3.0 |
| onnxruntime | 1.31.0 | 1.31.1 |
| pycparser | 3.11 | 3.12 |
| pytest | 9.1.1 | 9.2.0 |
| starlette | 1.8.0 | 1.10.0 |

**faster-whisper** is 1.2.1 in both. numpy (2.5.4), scipy, tokenizers,
soundfile and all other locked packages match exactly. No package is
missing from either list.

## Results

The new runs are compared with two sets of earlier runs:

- **baseline**: `20261018T132344Z-…-auto` and `20261018T132652Z-…-hint`,
  commit 2093930.
- **0f996db**: `20261029T064826Z-…-auto` and `20261029T065314Z-…-hint`
  (`results/20261029T064826Z-faster-whisper-small-auto.json`,
  `results/20261029T065314Z-faster-whisper-small-hint.json`), described in
  `docs/rerun_comparison.md`.

"Corpus WER" is the repo's own definition (`metrics.corpus_wer`): one WER
over all clips in the group, after lower-casing and removing punctuation.
It can exceed 1. Slots is the number of scenarios with `slots_correct`
true, counted from the run files. `summarise` does not report slots.

### Language policy: auto

| run | commit | task success | intent acc. | slots ok | corpus WER all | en | hi | hi-en | p50 ms | p95 ms | RTF p50/p95 | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline 2026-10-18 | 2093930 | 18/50 | 0.46 | 21 | 1.6272 | 0.3871 | 3.0197 | 1.4966 | 2886 | 11707 | 0.78 / 2.45 | 183.1 |
| re-run 0f996db | 0f996db | 18/50 | 0.46 | 21 | 2.0504 | 0.3935 | 4.2961 | 1.4832 | 4294 | 19152 | 1.18 / 4.22 | 293.1 |
| **this run** | f430675 | **18/50** | **0.46** | **21** | **1.6272** | 0.3871 | 3.0197 | 1.4966 | 3818 | 14852 | 1.00 / 3.59 | 242.2 |

Task success by language for all three runs: en 14/17, hi 0/17,
hi-en 4/16. No scenario errored.

### Language policy: hint

| run | commit | task success | intent acc. | slots ok | corpus WER all | en | hi | hi-en | p50 ms | p95 ms | RTF p50/p95 | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline 2026-10-18 | 2093930 | 15/50 | 0.38 | 18 | 0.9671 | 0.3871 | 1.1184 | 1.4161 | 2748 | 10968 | 0.79 / 2.08 | 177.0 |
| re-run 0f996db | 0f996db | 15/50 | 0.36 | 18 | 0.9298 | 0.3935 | 0.8816 | 1.5369 | 4316 | 18770 | 1.28 / 3.42 | 279.7 |
| **this run** | f430675 | **15/50** | **0.38** | **18** | **0.9671** | 0.3871 | 1.1184 | 1.4161 | 3283 | 12927 | 0.94 / 2.52 | 213.1 |

Task success by language for all three runs: en 14/17, hi 1/17,
hi-en 0/16. No scenario errored.

Cost is 0.00 USD in every run (local inference).

## Per-scenario differences

### This run vs the 2026-10-18 baseline

| policy | transcript differs | task outcome differs | other fields differing |
|---|---|---|---|
| auto | **none (0/50)** | **none** | `latency_ms` only (all 50). `predicted_intent`, `predicted_slots`, `intent_correct`, `slots_correct`, `detected_language` and per-clip `wer` are identical. |
| hint | **none (0/50)** | **none** | same as auto: `latency_ms` only. |

The baseline was scored at commit 2093930 and this run at f4306752. On these
identical transcripts, both commits give the same intents, slots and task
outcomes for all 100 scenario results.

### This run vs the 0f996db re-runs

**auto.** Task outcomes: **no differences**. Intent and slot results:
no differences.

Transcripts differ in 22 scenarios:

- en: v1-008, v1-041
- hi: v1-011, v1-013, v1-014, v1-015, v1-016, v1-018, v1-020, v1-034,
  v1-039, v1-047
- hi-en: v1-023, v1-024, v1-025, v1-026, v1-028, v1-029, v1-030, v1-040,
  v1-045, v1-050

`detected_language` differs for v1-013 and v1-024. Per-clip WER differs
for 12 scenarios.

**hint.** Task outcomes: **no differences**.

Intent differs in 1 scenario. In v1-017, 0f996db predicted no intent
(intent wrong) and this run predicted `book_ticket` (intent right). Slots
are wrong in both runs, so the task fails in both. This one scenario
accounts for the intent accuracy gap (0.36 vs 0.38).

Transcripts differ in 33 scenarios:

- en: v1-008, v1-041
- hi: v1-011, v1-012, v1-013, v1-015, v1-016, v1-017, v1-018, v1-019,
  v1-020, v1-032, v1-034, v1-037, v1-039, v1-042, v1-047, v1-049
- hi-en: v1-021, v1-022, v1-023, v1-024, v1-025, v1-026, v1-027, v1-028,
  v1-029, v1-030, v1-033, v1-038, v1-043, v1-045, v1-050

Per-clip WER differs for 18 scenarios.

## What differs between the environments

This comparison uses only what the run manifests record. The manifests do
not record package versions other than faster-whisper.

| field | baseline 2026-10-18 | 0f996db re-run | this run |
|---|---|---|---|
| `hardware.cpu` | Xeon @ 2.10GHz | Xeon @ **2.80GHz** | Xeon @ 2.10GHz |
| logical CPUs / RAM | 4 / 15.7 GB | 4 / 15.7 GB | 4 / 15.7 GB |
| kernel (`hardware.os`) | 6.18.44-fc-**v139** | 6.18.44-fc-v185 | 6.18.44-fc-v185 |
| python | **3.13.16** | 3.13.17 | 3.13.17 |
| faster-whisper (`backend_version`) | 1.2.1 | 1.2.1 | 1.2.1 |
| model revision | 536b066 | 536b066 | 536b066 |
| compute type / beam | int8 / 5 | int8 / 5 | int8 / 5 |
| tts_engine | espeak-ng 1.51 | espeak-ng 1.51 | espeak-ng 1.51 |
| scenarios sha256 | 75fed5e1… | 75fed5e1… | 75fed5e1… |
| other package versions | per `requirements-lock.txt` (documented, not in manifest) | not recorded | see table above (ctranslate2 4.8.4, etc.) |

Observed:

- **This run vs the baseline.** The CPU model string matches. The kernel
  build, Python patch version and installed package versions differ,
  including ctranslate2 4.8.4 here against 4.8.3 in the lock file. All 100
  transcripts are identical to the baseline.
- **This run vs 0f996db.** The kernel and Python match. The CPU model
  string differs (2.10 vs 2.80 GHz). 22 (auto) and 33 (hint) transcripts
  differ.
- **Latency and wall time** differ from both earlier runs. This run is
  slower than the baseline (p50 +32% auto, +19% hint) and faster than
  0f996db.

The cause of the transcript differences against 0f996db is **not
isolated**. The cause of the latency and wall-time differences is **not
isolated**. Only one run was made per setup. The installed package versions
of the 0f996db container are not in its manifest. Other things on the host
were not measured.

## Limits

- One run per policy per setup, so run-to-run variance on the same machine
  was not measured here. Latency figures from a single run on a shared
  cloud host can be affected by other load on that host, which was not
  observed.
- The environment was installed with `make setup`, not `make setup-locked`.
  13 packages are newer than the lock file. The effect of that alone was not
  tested.
- The same audio (`audio/v1`, byte-identical to its manifest) and the same
  model revision were used throughout. All limits in the README still
  apply: synthetic espeak-ng speech, 50 scenarios, no telephone audio.
- p95 over 50 clips is close to the maximum ("worst few clips").
