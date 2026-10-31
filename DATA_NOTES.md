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

## Real speech: Google FLEURS, Hindi (`hi_in` config, `test` split)

Used only by the real-speech validation lane (`voicebench realspeech …`,
`make realspeech-fetch` / `make realspeech`). It is separate from the
50-scenario synthetic benchmark, which is unchanged.

- **What it is**: FLEURS, read speech. Native speakers read sentences
  from the FLoRes-101 benchmark (Wikipedia-derived text), 16 kHz. It is
  human speech, but read aloud and recorded wideband: not phone calls,
  not conversational, and not code-switched.
- **Source**: [huggingface.co/datasets/google/fleurs](https://huggingface.co/datasets/google/fleurs),
  pinned to revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`. Two files
  of the `hi_in` config are used: `data/hi_in/test.tsv` (transcripts,
  sha256
  `889e82e2875490f9533ff59ab67326fcfa01cf828fc4412758aaaa1f442a729f`) and
  `data/hi_in/audio/test.tar.gz` (audio, sha256
  `47c238b9cf7016ba596639bb3038b0c89dc6e85759f16d09c4f58c6dfa25c65f`).
  Not gated; downloaded without an account through `huggingface_hub`.
- **Licence**: **CC BY 4.0**, as the dataset card states at that revision
  (`license: cc-by-4.0` in its metadata, and "All datasets are licensed
  under the Creative Commons license (CC-BY)"). The brief for this work
  described FLEURS as CC-BY-SA-4.0; the card at the pinned revision says
  CC BY 4.0, so that is what is recorded here. The attribution below meets
  the attribution terms of either licence.
- **Attribution** (required by the licence; reproduce it with any copy of
  the manifest or of transcripts taken from it):

  > Real-speech audio and reference transcripts: FLEURS, Hindi (`hi_in`),
  > test split. A. Conneau, M. Ma, S. Khanuja, Y. Zhang, V. Axelrod,
  > S. Dalmia, J. Riesa, C. Rivera and A. Bapna, "FLEURS: Few-shot Learning
  > Evaluation of Universal Representations of Speech", arXiv:2205.12446,
  > 2022. Published by Google at
  > https://huggingface.co/datasets/google/fleurs (revision `70bb2e84`),
  > licensed under CC BY 4.0, https://creativecommons.org/licenses/by/4.0/.
  > Changes: a 150-clip subset was selected and its transcripts copied
  > unchanged into `data/realspeech/fleurs_hi_in_test_150.json`; the audio
  > is not redistributed.

- **Subset manifest (committed)**: [`data/realspeech/fleurs_hi_in_test_150.json`](data/realspeech/fleurs_hi_in_test_150.json).
  For each of the 150 clips: the FLEURS file id, sentence id, raw and
  FLEURS-normalised transcription, number of samples, the speaker gender
  label FLEURS gives, and the sha256 of the WAV. It also records the
  dataset revision, licence, the sha256 of both source files and the
  selection seed.
- **Selection**: seed **20261031**. `random.Random(20261031).sample` picks
  150 of the 418 rows of `test.tsv`, sorted by file name first so the
  choice does not depend on row order (`voicebench.realspeech.select_clips`).
  Rebuild with `voicebench realspeech manifest` (defaults `--n 150 --seed 20261031`).
  The subset has 1753 s (29.2 min) of audio, 76 clips labelled male and 74
  female, and 135 distinct sentences: FLEURS records some sentences with
  more than one speaker, and 15 sentences appear twice.
- **Reference text**: WER is computed against the raw transcription (the
  `reference` field) after `voicebench.textnorm.normalise`, the same
  normalisation as the synthetic benchmark. The FLEURS-normalised
  transcription is kept in the manifest for reference only.
- **Audio is never committed.** `make realspeech-fetch` downloads the
  archive into the Hugging Face cache and extracts only the 150 manifest
  clips into `.cache/realspeech/fleurs_hi_in_test/` (git-ignored). Every
  clip's sha256 is checked against the manifest, archive member paths are
  never used as file paths, and links are not followed.
- **People**: the speakers are FLEURS's recorded volunteers. The
  transcripts are encyclopaedic sentences with no personal data about the
  speakers.

### Hindi-English (Hinglish): not added

The optional second source, MUCS 2021 Hindi-English code-switched speech,
was **skipped**. Copies exist on the Hugging Face Hub, but only as
re-uploads by individuals, and they do not agree on the licence:
`dianavdavidson/MUCS-Hinglish` is tagged CC BY 4.0, while
`Trelis/vistaar-hi-mucs-test` (the Hindi, not code-switched, MUCS test set)
states that the original OpenSLR-104 release is CC BY-SA 4.0. The original
(openslr.org, and the challenge site) is not reachable from this
environment, so the licence could not be checked at its source. That is
not a clear licence to record, so no code-switched real speech is used.
The Hindi-English numbers in this repo remain synthetic only.

## Model weights (not in the repo)

- **Whisper `small`** (OpenAI), MIT licence, in the CTranslate2 conversion
  `Systran/faster-whisper-small` (MIT), revision
  `536b0662742c02347bc0e980a01041f333bce120`. Downloaded from Hugging Face
  at run time into the local cache. Never committed or redistributed here.
- Software used to run it: faster-whisper (MIT) and CTranslate2 (MIT).

## Results: `results/*.json`

- Transcripts in `results/*.json` are Whisper's output on the synthetic
  audio above. They contain no personal data: all input text is invented.
- `results/realspeech/*.json` are real-speech run files: Whisper's output on
  the FLEURS clips, with the FLEURS reference transcript of each clip
  (CC BY 4.0, attribution above).
- Run files are written by `voicebench run` / `rescore` and never edited by
  hand. Their exact provenance is in [`results/README.md`](results/README.md).

## What is *not* in this repo

- No recordings of real people are committed, no real phone calls, no
  scraped audio or text.
- No third-party audio is committed. The real-speech lane downloads FLEURS
  Hindi audio at run time (above); only its clip list and transcripts are
  in the repo.

## What this audio is *not*

espeak-ng is a formant synthesiser and is generally described as robotic.
Its output is very different from natural Indian speech. The clips have
been checked mechanically (length, level, SNR, hashes), but nobody has
listened to them to rate intelligibility. Results on this audio measure how an ASR model copes with *this
synthetic speech*. They are not an estimate of accuracy on real callers. See
the limitations section of the README.
