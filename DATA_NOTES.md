# Data notes

Where every piece of data in this repo comes from, and under what terms.

## Scenario text: `scenarios/v1.jsonl`

- Written by hand for this project. Not taken from real calls, transcripts,
  or any dataset. All names (Rahul, Priya, Neha, ...), order numbers and PNRs
  are made up.
- Licence: same as the repo (MIT).

## Audio: `audio/v1/*.wav` (50 files, 16 kHz mono, 16-bit PCM)

- **Every file is synthetic.** No human voice was recorded and no real phone
  audio is used.
- **Speech**: generated with [eSpeak NG](https://github.com/espeak-ng/espeak-ng)
  1.51 (Ubuntu package `espeak-ng 1.51+dfsg-12build1`), a formant synthesiser.
  The program is GPL-3.0-or-later. Audio it produces is program output and is
  not covered by the GPL. We release it under the repo's MIT licence.
  - Voices: `en-us` for English callers, `hi` for Hindi and Hindi-English
    callers (espeak-ng reads Latin-script words in a Hindi line with English
    rules). Agent prompts in barge-in clips use the `+f3` variant of the same
    voice so the two speakers sound different. 160 words per minute.
  - The mbrola voices (`hindi-mbrola-*`) were **not** used: they need separately
    licensed mbrola databases.
- **Noise**: all synthetic and generated in code (`src/voicebench/audio/noise.py`),
  seeded per scenario:
  - `white`: Gaussian white noise.
  - `pink`: white noise shaped to a 1/f spectrum.
  - `babble`: four *other* clean scenarios' espeak-ng utterances, looped and
    summed. So babble is synthetic speech too, not recordings of people.
- **Mixing**: noise is scaled so that the SNR over the whole padded clip equals
  the target (5 or 10 dB). The measured value is stored per file in
  `audio/v1/manifest.json`. Barge-in clips place the caller over the agent
  prompt at `caller_onset_ms`, with the agent at -6 dB relative to the caller.
- **Reproduce**: `make audio` (or `voicebench synth scenarios/v1.jsonl --out audio/v1`).
  With the same espeak-ng version, regenerating gives byte-identical files
  (checked on 2026-10-16). A different espeak-ng version may give different
  audio, so the manifest stores each file's sha256.

## What this audio is *not*

espeak-ng sounds clearly robotic, and its Hindi is far from natural Indian
speech. Results on this audio measure how an ASR model copes with *this
synthetic speech*. They are not an estimate of accuracy on real callers. See
the limitations section of the README.
