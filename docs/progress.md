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
