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
  `make audio-check` regenerates the audio in a temporary folder and compares
  it with the manifest. CI runs that check on every push. Details, including
  a 1-sample difference seen with older numpy, are in
  [`docs/REPRODUCING.md`](docs/REPRODUCING.md).

## Model weights (not in the repo)

- **Whisper `small`** (OpenAI), MIT licence, in the CTranslate2 conversion
  `Systran/faster-whisper-small` (MIT), revision
  `536b0662742c02347bc0e980a01041f333bce120`. Downloaded from Hugging Face
  at run time into the local cache. Never committed or redistributed here.
- Software used to run it: faster-whisper (MIT) and CTranslate2 (MIT).

## Results: `results/*.json`

- Transcripts in the run files are Whisper's output on the synthetic audio
  above. They contain no personal data: all input text is invented.
- Run files are written by `voicebench run` / `rescore` and never edited by
  hand. Their exact provenance is in [`results/README.md`](results/README.md).

## What is *not* in this repo

- No recordings of real people, no real phone calls, no scraped audio or text.
- No third-party speech datasets. Natural, licensed Hindi speech would make
  the benchmark much more meaningful (see the README limitations), but none
  has been added yet.

## What this audio is *not*

espeak-ng is a formant synthesiser and is generally described as robotic.
Its output is very different from natural Indian speech. The clips have
been checked mechanically (length, level, SNR, hashes), but nobody has
listened to them to rate intelligibility. Results on this audio measure how an ASR model copes with *this
synthetic speech*. They are not an estimate of accuracy on real callers. See
the limitations section of the README.
