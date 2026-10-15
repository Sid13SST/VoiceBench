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
