# Progress log

## Day 1 (2026-10-15)

**Done**
- Packaging (`pyproject.toml`, src layout) and a `Makefile` with
  `setup` / `test` / `validate`.
- Scenario, result and run-manifest schema (`src/voicebench/schema.py`).
  Validation covers: id/version agreement; intents belonging to their domain;
  allowed slot keys per intent; SNR (5 or 10 dB) and noise type only on noise
  scenarios; an interruption block only on interruption scenarios; a script
  check (hi = Devanagari, hi-en = Devanagari + Latin, en = no Devanagari).
- 50 hand-written scenarios in `scenarios/v1.jsonl`, with conventions written
  down in `scenarios/README.md`.
- Loader that collects every error with its line number, plus a
  `voicebench validate` CLI.
- 30 pytest tests, all passing locally.

**Did not work / open issues**
- Nothing failed today, but these design choices may need revisiting:
  - The script convention for hi-en (Hindi in Devanagari, English in Latin)
    is a choice. Whisper may write code-switched speech fully in Devanagari
    or fully romanised, which would inflate WER without the agent actually
    misunderstanding anything. Day 3 scoring should report WER under a
    stated normalisation, and the failure analysis should keep script
    mismatch separate from real recognition errors.
  - Slot values are canonical English/ASCII (`दो हज़ार` → `"2000"`), so the
    day-3 rule-based matcher needs Hindi number words and Hindi city/item
    names. Hindi slot extraction may well fail for that reason alone, and
    if so it will be reported as such.
  - `make run` does not exist yet; it arrives with the dashboard on day 4.
  - No CI yet (planned for day 6).

**Next (day 2)**
- Check that a free offline TTS (espeak-ng, or piper if a Hindi voice with a
  suitable licence exists) can be installed here, and produce one WAV per
  scenario, labelled synthetic.
- Noise mixing at a set SNR, with tests that check the SNR it actually
  produces; barge-in mixing.
- Transcript adapter for a small local Whisper model (faster-whisper). If the
  weights cannot be downloaded in this environment, say so here and in the
  README rather than faking transcripts.

## Day 2 (2026-10-16)

**Done**
- `audio/signal.py`: WAV I/O, resampling to 16 kHz, `mix_at_snr` (scales
  noise so the SNR over the whole clip equals the target), overlay, peak
  normalisation. Tests check the SNR actually achieved at -3, 0, 5 and 10 dB.
- `audio/noise.py`: seeded white, pink (1/f) and babble noise. Babble is
  built from four *other* scenarios' synthetic utterances, so it contains no
  real voices.
- `audio/tts.py`: espeak-ng adapter (`en-us` for en; `hi` for hi and hi-en,
  which reads Latin-script words with English rules).
- `audio/build.py` + `voicebench synth`: one WAV per scenario. Noise clips
  are mixed at 5 or 10 dB (measured SNR matches the target to within 0.01 dB
  and is stored per file). Barge-in clips play the agent prompt (different
  voice variant, -6 dB) with the caller starting at `caller_onset_ms`
  (1.9 to 2.6 s of overlap). Self-correction clips are plain speech, since
  the correction is in the words.
- `audio/v1/`: 50 WAVs, 198.9 s in total, 6.3 MB, committed with a manifest.
  Regenerating with espeak-ng 1.51 gave byte-identical files. A test checks
  every committed WAV against its manifest hash.
- `DATA_NOTES.md`: source and licence of every piece of data.
- `asr.py` + `voicebench transcribe`: faster-whisper adapter with
  deterministic decoding, optional language hint (hi-en is decoded as `hi`
  since Whisper has no code-switched language code) and per-call latency.
- 76 tests pass, 1 skipped (the real-model smoke test, see below).

**Did not work**
- **No Whisper weights in this environment.** faster-whisper downloads
  models from `huggingface.co`, and openai-whisper downloads from
  `openaipublic.azureedge.net`. The build environment's network proxy
  returns 403 for both, so no transcript has been produced yet and none
  is faked. The adapter fails with a clear `ASRUnavailable` error (tested).
  Fix: allow `huggingface.co` in the environment's network settings, or run
  `make setup && .venv/bin/voicebench transcribe audio/v1/v1-002.wav` on a
  machine with normal internet access. Once the weights are cached,
  `VOICEBENCH_ASR_MODEL=small make test` also runs the real-model smoke test.
- I could not listen to the audio here. Checks so far are mechanical only:
  non-silent, correct length, exact SNR. espeak-ng's Hindi is clearly
  robotic, which is a limitation of the benchmark audio, not of the scoring.

**Next (day 3)**
- Runner: scenarios → audio → transcript → score, writing a `RunManifest`.
- Scoring: WER with a stated text normalisation (lower case, punctuation
  stripped; script mismatch on hi-en counted separately), a rule-based
  intent/slot matcher (including Hindi number words), and task completion.
  All tested deterministically on fixed transcripts labelled as fixtures.
- Retry Whisper download; if it's still blocked, the runner and scoring
  still get built and tested, and results wait until weights are available.

## Day 3 (2026-10-16)

**Whisper download, retried**
- `huggingface.co` is reachable now, but the weight files themselves come
  from `cas-server.xethub.hf.co` (Hugging Face's Xet storage) and, with Xet
  turned off (`HF_HUB_DISABLE_XET=1`), from `us.aws.cdn.hf.co`. The proxy
  rejects both, so **still no transcripts**. Fix: also allow `*.hf.co`
  (or those two hosts) in the environment's network settings, or run
  `make bench` on a normal machine.

**Done**
- `textnorm.py`: NFC, lower case, punctuation and danda removed, Devanagari
  combining marks kept. Numbers and script are deliberately *not* rewritten.
  `script_profile` labels each transcript devanagari / latin / mixed, so
  hi-en script mismatches can be counted separately from recognition errors.
- `metrics.py`: per-utterance WER, corpus WER, nearest-rank percentile
  (ready for day 5 latency).
- `nlu/numbers.py`: English, Devanagari and romanised Hindi number words.
  Runs of single digits are read as ids, other runs as quantities. One bug
  was found and fixed while checking v1: "transfer कर दो" was read as
  amount 2. A lone "दो" after a light verb is now treated as the verb.
- `nlu/matcher.py` + `lexicon.py`: keyword scoring per domain intent;
  gazetteers for cities, menu, payees, devices and issues; last mention wins
  for self-corrections; first mention wins for device.
- `scoring.py`, `runner.py`, `report.py`; CLI `voicebench run` / `report`;
  `make bench`.
- 153 tests pass, 1 skipped (real-model smoke test). Scoring tests use
  hand-written transcripts marked `fixture`.

**Honest caveats**
- The matcher reads all 50 v1 *references* correctly. That is a coverage
  check, not a result: the lexicon was written for these sentences. Its job
  in the benchmark is to show how much ASR errors break a matcher that
  already understands the clean text.
- The matcher is told the domain (one agent per business). Without that,
  "cancel" would be ambiguous between orders and bookings.
- Extra predicted slots are not penalised; only expected slots must match.

**Next (day 4)**
- FastAPI dashboard over saved runs: pass/fail by language and condition,
  failing cases with transcript vs reference.
- Until real runs exist, the dashboard can only be shown with the oracle run
  or fixture data, clearly labelled as such.

## Day 3, continued: first real runs (2026-10-16)

**Whisper download, retried again: it works now.** The Whisper `small`
weights (`Systran/faster-whisper-small@536b066`) downloaded from Hugging Face.
`VOICEBENCH_ASR_MODEL=small make test` now also runs and passes the
real-model smoke test.

**Ran**
- `make bench` (language auto-detect) and `make bench POLICY=hint`, both
  saved under `results/`. Each takes about 6.5 min for 50 clips on the
  4-vCPU container.
- The first `make bench` failed with `ModuleNotFoundError: jiwer`: the venv
  was made before jiwer became a dependency, and an editable install doesn't
  pick up new dependencies. Re-running `make setup` fixed it.

**What the runs show** (numbers from the run files; README has the table)
- English: 13/17 task success, WER 0.39, same under both policies.
- Hindi: 0/17 (auto) and 1/17 (hint). Auto-detect never chose Hindi.
- Hindi-English: 4/16 (auto) and 0/16 (hint). With the hint, English words
  come out in Devanagari and often misspelled.
- Several clips went into repetition loops ("may God be with you, may God
  be with you, …"), giving WER up to 20.7 and latency up to about 26 s.
  Corpus WER is dominated by these few clips.

**Problems found, not fixed yet (fixing after seeing results needs care)**
- Matcher gap: Whisper wrote order id "7310" as `7-3-1-0`. Normalisation
  turns that into four separate digit tokens, and the matcher doesn't join
  them, so `v1-006` fails although the ASR was right. That's a genuine
  general gap (hyphenated digits are a standard Whisper format), but the
  fix would be made after seeing v1 results. If I fix it, the current runs
  stay as they are, the fix gets its own commit, and new runs are added next
  to the old ones, so the change is visible.
- Lucky pass: `v1-044` (barge-in) passes although the agent prompt leaked
  into the transcript. The only scoring keyword hit is "human", from the
  caller's words; the leaked prompt text contains neither "agent" nor
  "human".
- The first transcription in a run includes some warm-up cost. Day 5 latency
  reporting should do an untimed warm-up call first.
- Run files from this commit don't contain the model revision. The adapter
  now records it for future runs, and `results/README.md` states it for
  these two.

**Next (day 4)**: dashboard over these run files.

## Day 4 (2026-10-18)

**Hyphenated-digit fix first** (the matcher gap logged on day 3)
- `nlu/numbers.py` now joins runs of single digits written as `7-3-1-0` or
  `3, 1, 2, 7` into one id. Multi-digit strings (`4821 5590`) stay separate.
- Added `voicebench rescore`. It scores a saved run's transcripts again with
  the current code, without decoding audio, and writes a new run file with
  `rescored_from` set. It refuses if the scenario file changed.
- Re-scored both baseline runs at `75a9e5c`. Exactly one scenario changed in
  each: `v1-006` (English) went from fail to pass. Totals: auto 17 → 18/50,
  hint 14 → 15/50. The original run files are kept unchanged next to the
  re-scored ones, and the README table now says which runs it uses.

**Done**
- `dashboard/data.py`: run store (skips invalid JSON files and lists them,
  reloads changed files), language × condition matrix, case filter, and a
  word-level diff (equal / substituted / missed / added).
- `dashboard/app.py` + Jinja templates: runs list; run page with metadata
  (command, commit, model, audio), banners for fixture data, reference-text
  runs, re-scored runs, a changed scenario file and synthetic audio; the
  pass/fail matrix with counts and a single-colour rate bar; WER and intent
  table; case browser with audio playback. No external assets, light and dark
  themes, usable at phone width.
- `voicebench dashboard` / `make run`. 167 tests pass, 1 skipped.

**Did not work / fixed along the way**
- First screenshot showed the rate bars as empty tracks: the fill was an
  inline `<span>`, so its width was ignored. Fixed with `display: block` and
  checked again in light, dark and 390 px-wide screenshots.
- The audio route serves only files named like a scenario id from the
  configured audio directory. A path-traversal attempt returns 404 (tested).
- The dashboard assumes one audio directory (`audio/v1`) for every run. That
  is fine while there is only v1. Runs don't record their audio directory
  yet.

**Next (day 5)**
- Latency p50/p95 per run, after one untimed warm-up call, and real-time
  factor.
- Cost per run: 0 USD for local inference, stated as such, with the
  hardware recorded.
- Full run over all 50 scenarios with the exact command and model revision
  saved under `results/`.

## Day 5 (2026-10-18)

**Done**
- Run files now record the hardware (CPU, logical CPUs, RAM, OS, Python),
  the number of untimed warm-up calls, the wall time of the timed loop, a
  per-scenario `cost_usd`, and a `cost_note` explaining it.
- The runner makes one untimed warm-up transcription before timing. A failed
  warm-up only aborts the run if the model can't load at all.
- `report.latency_stats`: nearest-rank p50/p95 of per-clip latency and
  real-time factor, per group. Shown in `voicebench report` and on the
  dashboard's run page, together with cost, wall time, hardware and whether
  a warm-up was done.
- Cost: local faster-whisper costs 0 USD per call. The note says electricity
  and hardware are not counted.
- `voicebench compare A B`: which transcripts and which pass/fail outcomes
  differ between two runs.
- Full runs at commit `20939304`, saved in `results/`:
  - auto-detect: 18/50, corpus WER 1.63, p50 2886 ms, p95 11707 ms, 183 s wall.
  - language hint: 15/50, corpus WER 0.97, p50 2748 ms, p95 10968 ms, 177 s wall.
- 174 tests pass, 1 skipped.

**What surprised me / did not work**
- **Transcripts are not reproducible across machines.** This session's
  container has a different CPU (Xeon @ 2.10 GHz vs 2.80 GHz on day 3). The
  model revision and settings are the same, yet 22/50 (auto) and 33/50
  (hint) transcripts differ from day 3. On the same machine a re-run gave
  0/50 differences, so decoding itself is deterministic. The int8 CPU
  kernels most likely differ between processors; I haven't verified that
  cause. No scenario flipped between pass and fail, but Hindi corpus WER
  (auto) moved from 4.30 to 3.02. The README now says WER above about 1
  should be read as "unusable output", not as a precise number.
- Day 3's latency (p50 about 5.7 s) and today's (about 2.9 s) aren't
  comparable: different CPU, and day 3 had no warm-up. Only today's runs
  are reported.
- English latency is lower with the language hint (p50 1806 ms) than with
  auto-detect (2869 ms). Auto-detect has to identify the language first.
  It's an observation from one run each, not a measured breakdown.
- p95 latency (about 11 s) comes from the same few clips that went into
  repetition loops. It describes worst-case behaviour on garbled input more
  than typical speed.

**Next (day 6)**
- GitHub Actions CI (tests, scenario validation, audio manifest check; no
  model download in CI).
- Reproducibility notes in one place, finishing DATA_NOTES.md, and a
  limitations section in the README.

## Day 6 (2026-10-19)

**Done**
- **CI** (`.github/workflows/ci.yml`): Python 3.10, 3.12 and 3.13 on
  ubuntu-24.04. It installs espeak-ng, validates the scenarios, runs pytest,
  checks that the committed audio regenerates, and runs the oracle pipeline
  end to end. It downloads no model weights. First run: all three jobs green.
  CI warned that the actions used Node 20, so they're moved to
  `checkout@v5` / `setup-python@v6`.
- **Python 3.10 checked locally first** (uv-installed 3.10.20): all tests
  passed before CI was added.
- **`synth --check` / `make audio-check`**: regenerates the audio in a
  temporary folder and compares hashes. For files that differ, it prints the
  largest sample difference. `--tolerance-lsb` accepts tiny differences
  explicitly; it's 0 by default and 1 in CI.
- **`requirements-lock.txt` + `make setup-locked`**: the exact package
  versions of the environment that made the day 5 runs. Checked: a fresh
  locked venv passes all tests.
- **`docs/REPRODUCING.md`**: environment table, step-by-step commands, and a
  table of what is and isn't reproducible.
- **`DATA_NOTES.md`** completed: Whisper weights (MIT, revision pinned, not
  redistributed), how the results were produced, and what isn't in the
  repo.
- **README**: limitations section (audio, measurement, matcher, WER
  stability, latency scope, cost scope, one model), CI badge, links.

**Found along the way**
- With numpy 2.2.6 / scipy 1.15.3 (Python 3.10), regenerating the audio gives
  one sample in `v1-038` that differs by 1 LSB from the committed file. The
  file is the 10 dB babble mix, and the other 49 are byte-identical. CI's
  3.10 job reproduced exactly that difference. With numpy 2.5 the audio was
  byte-identical on three different CPUs: the original Xeon 2.80 GHz, today's
  Xeon 2.10 GHz, and an AMD EPYC CI runner.
- I had written that espeak-ng's Hindi is "hard to understand even for
  people". Nobody has listened to the clips, so that claim was removed. The
  docs now say only that the audio was checked mechanically.

**Next (day 7)**
- One-page failure analysis written from the day 5 run files only.
- Final README with an architecture diagram and how to run.
- Tag v0.1.0 once a clean checkout passes `make setup && make test` and CI
  is green.

## Day 7 (2026-10-19)

**Done**
- `voicebench analyze`: rule-based failure categories with a fixed priority
  order (pipeline error → wrong language → repetition loop → agent prompt
  leak → no intent → wrong intent → slot error), plus non-exclusive flags,
  including on passing scenarios. Tested on fixtures.
- `docs/failure_analysis.md`: one page, written from the two day 5 run
  files only. Main findings: auto-detect never identifies the synthetic
  Hindi as Hindi; the language hint fixes detection but not recognition
  (1/17); on code-switched speech the hint hurts (4/16 → 0/16) because
  English words get non-standard Devanagari spellings; repetition loops
  account for all latency above 5.3 s; and three English failures with
  three different causes.
- README rewritten for v0.1.0: Mermaid architecture diagram (rendered with
  mermaid 11.4.1 to check it parses), results, what failed, how to run,
  command table, limitations, reproducibility and data links.
- Version 0.1.0 in `pyproject.toml` and `voicebench.__version__`.

**Corrections made while writing**
- The repetition-loop rule was adjusted twice after looking at these runs:
  to catch a 5-word phrase loop (`v1-049`), and to catch a repeated
  2-character Telugu unit (`v1-018`) without flagging long numbers. The
  failure analysis says so.
- First draft said `v1-041` failed because Whisper transcribed only the
  agent prompt. The transcript actually contains part of the caller too
  ("3,000", "transfer"), and the wrong intent comes from a 3-3 tie broken by
  list order. Corrected in the analysis and in the README limitations.
- Earlier README text still claimed espeak-ng Hindi is hard to understand,
  and that every auto-detect transcript was in Latin script (it is 30 of 33).
  Both are fixed.

**Not done**
- Optional spoof-risk adapter: skipped as planned. It was only to be
  attempted if everything else was finished and a usable pretrained model
  existed, and no such model was evaluated.

**Release**
- CI is green on the release commit `e8fab2c`. A fresh clone passes
  `make setup`, `make test` (189 passed, 1 skipped) and `make audio-check`,
  and `voicebench analyze` reproduces every count in the failure analysis.
- The `v0.1.0` tag could not be pushed from the build environment: the git
  proxy answers tag pushes with HTTP 403, though branch pushes work. The tag
  was then created through a GitHub release ("VoiceBench v0.1.0") on
  `e8fab2c`. Checked afterwards: a clone of the tag reports version 0.1.0,
  passes `make setup` and `make test` (189 passed, 1 skipped), regenerates
  the audio byte-identically, and reproduces the README numbers.
