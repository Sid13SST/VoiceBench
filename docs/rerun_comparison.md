# Re-run of the benchmark on current main (2026-10-29)

The full benchmark was re-run on `main` and compared with the committed day 5
baseline runs:

| policy | baseline (committed) | re-run (this document) |
|---|---|---|
| auto-detect | `results/20261018T132344Z-faster-whisper-small-auto.json` | `results/20261029T064826Z-faster-whisper-small-auto.json` |
| language hint | `results/20261018T132652Z-faster-whisper-small-hint.json` | `results/20261029T065314Z-faster-whisper-small-hint.json` |

**Summary.** Task success is unchanged: 18/50 auto, 15/50 hint, and no
scenario moved between pass and fail. Transcripts differ in 22/50 (auto) and
33/50 (hint) scenarios, so WER moved: all-clips WER 1.63 → 2.05 (auto) and
0.97 → 0.93 (hint). One hint scenario (`v1-017`) lost its intent (it still
fails). Latency was about 1.5× higher and wall time about 1.6× longer than
the baseline. The re-run's transcripts are identical, for all 50 scenarios
in both policies, to the day 3 runs, which were made on a Xeon @ 2.80 GHz,
the same CPU model as this container reports.

## Method

This was an automated run in a cloud container (claude.ai Claude Code
session), not on a developer's own machine. No source file was changed.

Steps, in order:

1. `apt-get install espeak-ng` (espeak-ng was not installed in the
   container). Installed `1.51+dfsg-12build1`.
2. `python3 -m venv .venv`, `pip install --upgrade pip`,
   `pip install -e ".[dev,asr]"` (the `make setup` / CI install, not the
   locked versions).
3. Checks: `voicebench validate scenarios/v1.jsonl`, `pytest`,
   `make audio-check`.
4. `python -m voicebench run --model small --language-policy auto --out /tmp/rerun`
   then the same with `--language-policy hint`. This is `make bench` and
   `make bench POLICY=hint` with `--out` pointed at a fresh directory, so no
   existing file in `results/` could be touched. The Whisper weights were
   downloaded from Hugging Face on first use (cache 464 MB). The two run
   files were then copied into `results/` unchanged, under the run ids the
   tool generated (neither name existed there). Their `command` field
   therefore says `--out /tmp/rerun`.
5. Comparison with `voicebench compare` and a small script that uses
   `voicebench.report.summarise` (the same aggregation as `voicebench
   report`) plus a field-by-field diff of every scenario result.

### Environment

| | baseline (day 5, from its run manifests) | re-run (this container) |
|---|---|---|
| code | `20939304ad73` | `0f996db4ca3d` (main) |
| CPU | Intel Xeon Processor @ 2.10 GHz, 4 logical CPUs | Intel Xeon Processor @ 2.80 GHz, 4 logical CPUs (1 thread per core; flags include avx2, avx512f/bw/dq/vl, avx512_vnni) |
| RAM | 15.7 GB | 15.7 GB, no swap |
| OS (kernel) | Linux 6.18.44-fc-v139 | Linux 6.18.44-fc-v185, Ubuntu 24.04.5 LTS |
| Python | 3.13.16 | 3.13.17 |
| espeak-ng | 1.51 | 1.51 (`1.51+dfsg-12build1`) |
| faster-whisper (`asr_model_version`) | 1.2.1 | 1.2.1 |
| model revision | `Systran/faster-whisper-small@536b0662742c02347bc0e980a01041f333bce120` | same |
| `asr_config` | cpu, int8, beam 5 | identical (field-by-field equal) |
| CTranslate2 | 4.8.3 (`requirements-lock.txt`; not in the manifest) | 4.8.4 (`pip freeze`; not in the manifest) |
| huggingface.co reachable | n/a | yes (HTTP 200 from the model API) |

Other packages that differ from `requirements-lock.txt` in this install:
av 19.0.2 (lock 19.0.1), onnxruntime 1.31.1 (1.31.0), huggingface_hub 2.3.0
(2.2.0), hf-xet 1.7.1 (1.7.0), plus fastapi, starlette, httpx2, httpcore2,
filelock, certifi, pycparser and pytest, which the benchmark path does not
use for decoding. numpy 2.5.4, scipy 1.18.1 and tokenizers 0.23.3 match the
lock file.

### Checks

- `voicebench validate scenarios/v1.jsonl`: 50 valid scenarios (v1), sha256
  `75fed5e1…aa1b`; en=17, hi=17, hi-en=16; clean=30, interruption=10,
  noise=10.
- `pytest`: **189 passed, 1 skipped** (the real-model smoke test, skipped
  because `VOICEBENCH_ASR_MODEL` is not set). The README and
  `docs/REPRODUCING.md` say 205 pass; that number was not reproduced here.
- `make audio-check`: regenerated with espeak-ng 1.51, **all 50 files
  byte-identical** to `audio/v1/manifest.json`.

So the input audio for the re-run is the committed audio, and the scoring
code is the same: `git diff 20939304 0f996db -- src/` touches only
`__init__.py`, `analysis.py`, `audio/signal.py`, `cli.py` and `compare.py`,
none of which is used by ASR, the matcher or scoring in `voicebench run`.

## Numbers

Task success = right intent and every expected slot. "Slots ok" = scenarios
whose predicted slots match all expected slots. WER is corpus WER as in
`voicebench report`. Latency is per `transcribe` call, nearest-rank
percentiles.

### Auto-detect (`make bench`)

| group | task ok base | task ok new | intent base | intent new | slots ok base | slots ok new | WER base | WER new | p50 ms base | p50 ms new | p95 ms base | p95 ms new |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 18/50 | 18/50 | 46% | 46% | 21/50 | 21/50 | 1.63 | 2.05 | 2886 | 4294 | 11707 | 19152 |
| en | 14/17 | 14/17 | 94% | 94% | 14/17 | 14/17 | 0.39 | 0.39 | 2869 | 4258 | 3203 | 5222 |
| hi | 0/17 | 0/17 | 0% | 0% | 3/17 | 3/17 | 3.02 | 4.30 | 3074 | 4750 | 12257 | 20494 |
| hi-en | 4/16 | 4/16 | 44% | 44% | 4/16 | 4/16 | 1.50 | 1.48 | 2818 | 4095 | 11440 | 19152 |

Real-time factor p50 / p95: 0.78 / 2.45 → 1.18 / 4.22. Wall time (50 clips,
after one untimed warm-up): 183.1 s → 293.1 s. Scoring errors: 0 → 0.

### Language hint (`make bench POLICY=hint`)

| group | task ok base | task ok new | intent base | intent new | slots ok base | slots ok new | WER base | WER new | p50 ms base | p50 ms new | p95 ms base | p95 ms new |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 15/50 | 15/50 | 38% | 36% | 18/50 | 18/50 | 0.97 | 0.93 | 2748 | 4316 | 10968 | 18770 |
| en | 14/17 | 14/17 | 94% | 94% | 14/17 | 14/17 | 0.39 | 0.39 | 1806 | 2645 | 2106 | 3514 |
| hi | 1/17 | 1/17 | 18% | 12% | 3/17 | 3/17 | 1.12 | 0.88 | 2976 | 5364 | 10968 | 10683 |
| hi-en | 0/16 | 0/16 | 0% | 0% | 1/16 | 1/16 | 1.42 | 1.54 | 3583 | 5545 | 11156 | 19368 |

Real-time factor p50 / p95: 0.79 / 2.08 → 1.28 / 3.42. Wall time: 177.0 s →
279.7 s. Scoring errors: 0 → 0.

Cost is 0 USD in all four runs (local inference).

## Comparison with the day 3 runs

The day 3 runs (`results/20261016T080842Z-…-auto.json`,
`results/20261016T081450Z-…-hint.json`) were made on a Xeon @ 2.80 GHz
according to `results/README.md`; their manifests do not record hardware
or model revision. `voicebench compare` against the re-run:

| A | B | transcripts that differ | pass/fail that differ |
|---|---|---|---|
| day 3 auto | re-run auto | 0 / 50 | 1 (`v1-006` fail → pass) |
| day 3 auto, rescored at `75a9e5c` | re-run auto | 0 / 50 | 0 |
| day 3 hint | re-run hint | 0 / 50 | 1 (`v1-006` fail → pass) |
| day 3 hint, rescored at `75a9e5c` | re-run hint | 0 / 50 | 0 |
| day 5 auto | day 5 auto re-run (`results/reproducibility/`), same machine | 0 / 50 | 0 |

The `v1-006` change against the unrescored day 3 files is the
hyphenated-digit matcher fix already documented in `results/README.md`, not
an ASR difference. The re-run's WER (2.05 auto, 0.93 hint) and task success
(18/50, 15/50) are also the figures the README gives for "a later run on a
different machine (Xeon @ 2.80 GHz)".

## What the differences point to

What the manifests and measurements show:

- **Same model and library as recorded.** `asr_model_version` (1.2.1), the
  model revision (`536b066…`) and the whole `asr_config` are identical
  between baseline and re-run. Audio is byte-identical and the scoring code
  is unchanged.
- **Different CPU.** `hardware.cpu` is Xeon @ 2.10 GHz in the baseline and
  Xeon @ 2.80 GHz in the re-run.
- **Transcripts follow the CPU, not the date or the package set.** The
  re-run reproduces the day 3 transcripts exactly (0/50 differ in both
  policies), and day 3 also ran on a Xeon @ 2.80 GHz. That match holds even
  though this container has CTranslate2 4.8.4 and day 3 used 4.8.3 (per
  `results/README.md`), so on this CPU that patch-version change made no
  difference to any transcript.
- **Latency is higher on this machine**, by about 1.5× at p50 and 1.6× in
  wall time, although the clock speed reported is higher. The baseline and
  re-run differ in CPU model, so this can't be separated from host load or
  other container differences; latency comparisons across machines are not
  meaningful, as `docs/REPRODUCING.md` already says.

So the transcript and WER differences look like a **different CPU**, not a
different model or faster-whisper version. What can't be shown from these
runs:

- which CPU feature or kernel path causes the different decoding (the
  manifests record only the CPU brand string, not the microarchitecture or
  instruction sets used by CTranslate2);
- whether CTranslate2 4.8.3 vs 4.8.4 would matter on the 2.10 GHz machine:
  the CTranslate2 version is not recorded in any run manifest, and no run
  here was made with 4.8.3;
- the day 3 hardware: it is stated in `results/README.md`, not recorded in
  the day 3 manifests.

## Limits

- One run per policy in this container; it was not re-run here to confirm
  same-machine determinism (the day 5 same-machine re-run already showed
  0/50 differences on its machine).
- The install used `pip install -e ".[dev,asr]"`, so package versions
  differ from `requirements-lock.txt` (listed above). `make setup-locked`
  was not tried.
- Latency comes from a shared cloud container and depends on host load; it
  is one sample.
- The pytest count (189 + 1 skipped) does not match the 205 stated in the
  README; this was only observed, not investigated.
- All the limits of the benchmark itself (synthetic espeak-ng audio, n = 50,
  matcher written alongside the scenarios) apply unchanged; see the README.

## Per-scenario differences

Every scenario where the transcript, detected language, predicted intent,
predicted slots, intent/slot correctness or task outcome differs between
baseline and re-run. Transcripts longer than 160 characters (repetition
loops) are cut, with their full length given; the full text is in the run
files.

### Auto-detect: baseline `20261018T132344Z` vs re-run `20261029T064826Z`

scenarios with any difference: 22/50; transcript differs: 22; task outcome differs: 0

#### v1-008 (en, clean) - differs: transcript

- base: lang `en`, intent `check_pnr_status`, slots `{}`, task fail, WER 0.73, 3203 ms
  > Check the status on PNR45213786, I'm zero.
- new: lang `en`, intent `check_pnr_status`, slots `{}`, task fail, WER 0.67, 4556 ms
  > Check the status on PNR 45213786, I'm zero.

#### v1-011 (hi, clean) - differs: transcript

- base: lang `hu`, intent `None`, slots `{}`, task fail, WER 1.29, 3306 ms
  > Mert ezt én nincs kaptam egy két abelős hely.
- new: lang `hu`, intent `None`, slots `{}`, task fail, WER 1.00, 4507 ms
  > Mert ezt én nincs kaptam a kitabáleszhez.

#### v1-013 (hi, clean) - differs: transcript, detected_language

- base: lang `hu`, intent `None`, slots `{}`, task fail, WER 1.00, 4287 ms
  > Méréka tészed azt a marubjé, biába tájékat gájé hen volkát riké sikájött kali hely.
- new: lang `la`, intent `None`, slots `{}`, task fail, WER 1.56, 5368 ms
  > me re kha te se das tamar lu ye bi amat a ekat ga ekan bo kha re ki si kha yat ka li hai.

#### v1-014 (hi, clean) - differs: transcript

- base: lang `ro`, intent `None`, slots `{}`, task fail, WER 1.17, 3614 ms
  > Mucătine măsala d-o să mă-ndoarește.
- new: lang `ro`, intent `None`, slots `{}`, task fail, WER 1.17, 4460 ms
  > Mucătine măsă la dosamându-mă de hă.

#### v1-015 (hi, clean) - differs: transcript

- base: lang `hu`, intent `None`, slots `{}`, task fail, WER 1.09, 3784 ms
  > Megálljok a hát hát, hogy a nombor páncs, páncs, nossú nyugy hát.
- new: lang `hu`, intent `None`, slots `{}`, task fail, WER 1.00, 5626 ms
  > Megálljok a hátáját amúgy pancs, pancs, nossú nyutáj!

#### v1-016 (hi, clean) - differs: transcript

- base: lang `en`, intent `None`, slots `{}`, task fail, WER 1.40, 2714 ms
  > Maybe I'll just write a D.
- new: lang `en`, intent `None`, slots `{}`, task fail, WER 1.00, 3718 ms
  > May God bless you.

#### v1-018 (hi, clean) - differs: transcript

- base: lang `la`, intent `None`, slots `{}`, task fail, WER 1.00, 12257 ms
  > నినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినినిన
- new: lang `la`, intent `None`, slots `{}`, task fail, WER 2.50, 18922 ms
  > నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిని నిన

#### v1-020 (hi, clean) - differs: transcript

- base: lang `en`, intent `None`, slots `{}`, task fail, WER 1.56, 2776 ms
  > Maybe I'll just make a seat on it and eat a heechal raha.
- new: lang `en`, intent `None`, slots `{}`, task fail, WER 1.33, 3972 ms
  > May the router make a seat on it that he shall rest.

#### v1-023 (hi-en, clean) - differs: transcript

- base: lang `en`, intent `None`, slots `{}`, task fail, WER 0.92, 2988 ms
  > May the credit card to the Hoga-yahe please use a lock or two.
- new: lang `en`, intent `None`, slots `{}`, task fail, WER 1.08, 4823 ms
  > May the credit card show you who got a hat, please use a lock or two.

#### v1-024 (hi-en, clean) - differs: transcript, detected_language

- base: lang `hu`, intent `None`, slots `{}`, task fail, WER 1.00, 3085 ms
  > Ég panélba termes alarod a karáthely.
- new: lang `en`, intent `None`, slots `{}`, task fail, WER 1.29, 3627 ms
  > I can't wait to see you next time!

#### v1-025 (hi-en, clean) - differs: transcript

- base: lang `en`, intent `None`, slots `{}`, task fail, WER 0.92, 3061 ms
  > May the order be booked now. Here I order ID 6604.
- new: lang `en`, intent `None`, slots `{}`, task fail, WER 0.92, 3954 ms
  > May the order be booked now here I order ID 6604H

#### v1-026 (hi-en, clean) - differs: transcript

- base: lang `en`, intent `book_ticket`, slots `{"destination": "bengaluru", "date": "monday"}`, task fail, WER 0.60, 3146 ms
  > Monday, go Mumbai, see Bengaluru, keep light, book, honey, hey.
- new: lang `en`, intent `book_ticket`, slots `{"destination": "bengaluru", "date": "monday"}`, task fail, WER 0.60, 4516 ms
  > Monday, go Mumbai, see Bengaluru, keep light, book, honey, hey!

#### v1-028 (hi-en, clean) - differs: transcript

- base: lang `en`, intent `reset_password`, slots `{}`, task pass, WER 1.00, 2768 ms
  > May the password rule the year who reset Karate.
- new: lang `en`, intent `reset_password`, slots `{}`, task pass, WER 1.00, 3831 ms
  > May the password rule the earth who reset Karate.

#### v1-029 (hi-en, clean) - differs: transcript

- base: lang `ja`, intent `None`, slots `{}`, task fail, WER 1.00, 3003 ms
  > 目が立つチャージの皮膚が下
- new: lang `ja`, intent `None`, slots `{}`, task fail, WER 1.00, 3905 ms
  > 目が立つチャージの皮膚の下

#### v1-030 (hi-en, clean) - differs: transcript

- base: lang `en`, intent `cancel_order`, slots `{"order_id": "3127"}`, task pass, WER 0.67, 2727 ms
  > Order 3127 Cancel Cargo please.
- new: lang `en`, intent `cancel_order`, slots `{"order_id": "3127"}`, task pass, WER 0.67, 3594 ms
  > Order 3127 Cancel Cargo, please.

#### v1-034 (hi, noise) - differs: transcript

- base: lang `en`, intent `None`, slots `{}`, task fail, WER 1.00, 2805 ms
  > (empty transcript)
- new: lang `en`, intent `None`, slots `{}`, task fail, WER 13.64, 19067 ms
  > I mean, I think I'm not going to show you, I'm going to show you, I'm going to show you, I'm going to show you, I'm going to show you, I'm going to show you, I'… (732 chars in total)

#### v1-039 (hi, noise) - differs: transcript

- base: lang `en`, intent `None`, slots `{}`, task fail, WER 1.00, 2730 ms
  > Mugiwa-Pasama-Prize-Kama-Head
- new: lang `en`, intent `None`, slots `{}`, task fail, WER 1.00, 4618 ms
  > Mugiwa-Pasama-Risei-Kama-Head

#### v1-040 (hi-en, noise) - differs: transcript

- base: lang `en`, intent `cancel_booking`, slots `{"mode": "train", "date": "sunday"}`, task pass, WER 0.62, 2716 ms
  > Sunday Mali train people can cancel kaleehae.
- new: lang `en`, intent `cancel_booking`, slots `{"mode": "train", "date": "sunday"}`, task pass, WER 0.62, 4294 ms
  > Sunday Mali train people can cancel kaleehae

#### v1-041 (en, interruption) - differs: transcript

- base: lang `en`, intent `check_balance`, slots `{}`, task fail, WER 2.17, 3048 ms
  > Welcome to the bank for balance and trance 3,000 groupings to never transfer
- new: lang `en`, intent `check_balance`, slots `{}`, task fail, WER 2.50, 5006 ms
  > Welcome to the bank for balance and trance for three thousand through trance for eight trance sir

#### v1-045 (hi-en, interruption) - differs: transcript

- base: lang `en`, intent `None`, slots `{}`, task fail, WER 2.30, 3443 ms
  > Namaste, I'm Kisami, and today I'm going to show you how to make an internet art art art art art art art.
- new: lang `en`, intent `None`, slots `{}`, task fail, WER 1.70, 4971 ms
  > Namaste, I'm Kisami, and today I'm going to show you how to use the internet.

#### v1-047 (hi, interruption) - differs: transcript

- base: lang `en`, intent `None`, slots `{}`, task fail, WER 8.77, 11898 ms
  > Billy said I put na-hee-na-hee-ah-bra-hee-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-… (247 chars in total)
- new: lang `en`, intent `None`, slots `{}`, task fail, WER 8.77, 20494 ms
  > Billy said I put na-hee-na-hee-ah-bra-kee-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-… (247 chars in total)

#### v1-050 (hi-en, interruption) - differs: transcript

- base: lang `en`, intent `cancel_booking`, slots `{}`, task fail, WER 1.00, 2676 ms
  > When they keep sorry to they keep a smoking cancel couple
- new: lang `en`, intent `cancel_booking`, slots `{}`, task fail, WER 1.00, 4095 ms
  > When they keep sorry to they keep a smoking cancel couple.


### Language hint: baseline `20261018T132652Z` vs re-run `20261029T065314Z`

scenarios with any difference: 33/50; transcript differs: 33; task outcome differs: 0

#### v1-008 (en, clean) - differs: transcript

- base: lang `en`, intent `check_pnr_status`, slots `{}`, task fail, WER 0.73, 1931 ms
  > Check the status on PNR45213786, I'm zero.
- new: lang `en`, intent `check_pnr_status`, slots `{}`, task fail, WER 0.67, 2972 ms
  > Check the status on PNR 45213786, I'm zero.

#### v1-011 (hi, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.71, 2924 ms
  > मेरे से मीगष्खाते में किता बलेज़े
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.71, 4018 ms
  > मेरे से मीग्ष्काती में किता बलेजे

#### v1-012 (hi, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 2932 ms
  > प्रियाको तो तो सारुब ये बेज्दी ये
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 4073 ms
  > प्रिया को तो तो सा रुग ये बेज्दी ये

#### v1-013 (hi, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.75, 5220 ms
  > मेरे खादे से ज़स्धना रुप्ये ब्यामबा एक अट्गा एक हैं वो खाद्री की शिखायत करनी हैं
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.75, 7963 ms
  > मेरे खादे से ज़स्धना रुप्ये भी आमबा एक अट्गा एक हैं वो खाद्री की शिखायत करनी हैं

#### v1-015 (hi, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 3031 ms
  > में बाजो चवाजा दंबर पंच पंच नोशुन योगे
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 5500 ms
  > में बाजो च़ाखे आजो दंबर पंच पंच नोशुन योगे

#### v1-016 (hi, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 2002 ms
  > मेगा अखो रड़ का लिए
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.80, 3548 ms
  > मेरा अग़ो रड़ का दिये

#### v1-017 (hi, clean) - differs: transcript, predicted_intent, intent_correct

- base: lang `hi`, intent `book_ticket`, slots `{}`, task fail, WER 0.92, 3673 ms
  > शुप्रे मार्खोल अख्नुसे कान पुर्की बस्काडिकोट बुक कराहें
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 6977 ms
  > शुप्रे मार्खोल अख्नुसे कान पुर्की बस्काटिको तुक्कर आखें

#### v1-018 (hi, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.70, 3081 ms
  > बाड़ा रंबर की मेरी प्लाइत की बुकीं कैसल कर्वो
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.70, 5374 ms
  > बाड़़ा बंबर की मेरी प्लाइत की बुकीं कैसल कर्वो

#### v1-019 (hi, clean) - differs: transcript

- base: lang `hi`, intent `talk_to_agent`, slots `{}`, task pass, WER 0.43, 2187 ms
  > बुजे किसी सां से बात करनी हैं
- new: lang `hi`, intent `talk_to_agent`, slots `{}`, task pass, WER 0.29, 3967 ms
  > मुजे किसी सां से बात करनी है

#### v1-020 (hi, clean) - differs: transcript

- base: lang `hi`, intent `report_issue`, slots `{}`, task fail, WER 0.56, 2976 ms
  > मेदे राउ तो में कल से इटो लेज नहीं चल रहा
- new: lang `hi`, intent `report_issue`, slots `{}`, task fail, WER 0.44, 4762 ms
  > मेरे राउ तो में कल से इटो लेज नहीं चल रहा

#### v1-021 (hi-en, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.83, 2748 ms
  > मेरी करन्ट अखान्ट का आलन्स्मबाये
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.83, 4263 ms
  > मेरी करन्ट अखान्ट का आलन्स्मबाई

#### v1-022 (hi-en, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.88, 3304 ms
  > अमित को फिर्टीं हुँद रुपीज त्रान्स्फर्कऱ्ो।
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.88, 4972 ms
  > अमित को फिर्टिन रुपिस च्रान्स्पर कर्वोः

#### v1-023 (hi-en, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.83, 3638 ms
  > मेरा क्रेदिट काद चोभी होगाया है, प्लीस वुसे लोग कर्दो.
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.58, 5545 ms
  > मेरा क्रेदिट काद चोगी हो गाया है प्लीस वुसे लोग कर दो

#### v1-024 (hi-en, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.14, 2742 ms
  > एक पनी अब तर में साल रोड़ कर आफें
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.86, 4505 ms
  > एक पनिल्बाद़ में आलरोड़ कराफें

#### v1-025 (hi-en, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.92, 3742 ms
  > मेदा अड़ा भी भुखना ही अड़ा अड़ी 6604 है
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 3.00, 19237 ms
  > मेदा अड़ा भी भुखना ही अड़ा अड़ी चिक्स चिक्स लिए रो फोगे अड़ा मेदा अड़ा मेदा अड़ा मेदा अड़ा मेदा अड़ा मेदा अड़ा मेदा अड़ा मेदा अड़ा मेदा अड़ा मेदा अड़ा मेदा अड़ा… (187 chars in total)

#### v1-026 (hi-en, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 10404 ms
  > मुन्देखो मुँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँ�
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.70, 5812 ms
  > मुन्देखो मुम्बाय से बंगलो रुकी फ्लाट्बोग करनी है

#### v1-027 (hi-en, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 11156 ms
  > मिर्बा प्यन्र अड़ तेट वं तु लिएरो फाँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँ�
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 19368 ms
  > मिर्बा प्यन्र अड़ तेट वन तु लिएरो फूँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँँ

#### v1-028 (hi-en, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.88, 3175 ms
  > मेरा पास्वर्ड्वुल्गा आपुरिस्ट्खर्वे
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.88, 5285 ms
  > मेरा पास्वर्ड्वुल्गा आपुरिस्ट्खा आपे

#### v1-029 (hi-en, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.83, 2653 ms
  > में बाला जोग चाजन नहीं हो रखा
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.83, 3842 ms
  > में बाला तो चाजन नहीं हो रखा

#### v1-030 (hi-en, clean) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.78, 3898 ms
  > अदर 3, 1, 2, 7, कान्सल कर्वो प्लीज अदर 3, 1, 2, 7, कान्सल कर्वो प्लीज
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.78, 6289 ms
  > अदर 3, 1, 2, 7, कान्सल कर्दो प्लीज अदर 3, 1, 2, 7, कान्सल कर्दो प्लीज

#### v1-032 (hi, noise) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.83, 2764 ms
  > मेदी माचुए खाछी का मेदी स्वोदाई
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 4316 ms
  > मेदी माचु खाछी का मेदी स्वो दाए।

#### v1-033 (hi-en, noise) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.75, 2689 ms
  > मेरे तों बड़ा लोग नहीं पोड़़ा
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.88, 4598 ms
  > मेरेदों पर आप लोगने लिए पोड़़ा

#### v1-034 (hi, noise) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 2.00, 10968 ms
  > बिज़़िदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आपिदे आ… (166 chars in total)
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.07, 10683 ms
  > बिज़ा बिदे आम्दम दोडों शुम्य शुम्य देशाँ साब चाड़ा बिच्ये सदोड़ा बिच्ये सदोड़ा बिच्ये सदोड़ा

#### v1-037 (hi, noise) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.80, 2802 ms
  > अगर नम्बनाशुन्ये एक भो खास्टेदस, या है
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.80, 5228 ms
  > अगर नम्बना शुन्ये एक भो खास्टेदस, या है।

#### v1-038 (hi-en, noise) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 4.75, 10626 ms
  > भी बादे में इस्वाद बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे बादे ब… (187 chars in total)
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 4.62, 18734 ms
  > भी बादे मिस्खार्द वादे लागे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वादे वा… (186 chars in total)

#### v1-039 (hi, noise) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 2780 ms
  > मुके अपा समः ब्रीज़ कर अपेज़।
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 5771 ms
  > मुँँँँँँँँँँँँँँँँँँँँँँँँँँ

#### v1-041 (en, interruption) - differs: transcript

- base: lang `en`, intent `check_balance`, slots `{}`, task fail, WER 2.17, 2106 ms
  > Welcome to the bank for balance and trance 3,000 groupings to never transfer
- new: lang `en`, intent `check_balance`, slots `{}`, task fail, WER 2.50, 3188 ms
  > Welcome to the bank for balance and trance for three thousand through trance for eight trance sir

#### v1-042 (hi, interruption) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 8.00, 6689 ms
  > तब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब आब.
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 2.50, 6266 ms
  > तो मैंगे रिस्वोईत में आप दास्माड़ुदि लाई चाडिए से सुने

#### v1-043 (hi-en, interruption) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 3.91, 11106 ms
  > वल्कुम तुम तुम त्रावल देलिची तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम… (179 chars in total)
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 3.91, 18770 ms
  > वेल्कुम तुम तुम त्रावल देलिची तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तुम तु… (180 chars in total)

#### v1-045 (hi-en, interruption) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.10, 3972 ms
  > नुमस्ती आपकी सावी बीटोग का लगी का रवा अंटनेच नगी आरवा
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 6235 ms
  > नुमस्ती आपकी सावी बीटो ता नजी कारवा अंटनेच नजी आरवा

#### v1-047 (hi, interruption) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.77, 4446 ms
  > बिल्ली से जाई पुन्धी नहीं अग्राखी त्रेंश निमार्खे लिए बुख्ख़ों
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.85, 7364 ms
  > बिल्ली से जाई पुन्नाखी नाखी ब्राखी त्रेंशा नि मार्खे लिए बुख ख़ूए।

#### v1-049 (hi, interruption) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.89, 3394 ms
  > मेरा वेविटकार मदलों क्रेविटकार ब्लोग कर्दीए
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 0.78, 5364 ms
  > मेरा देविट कार मदलों क्रेविट कार ब्लोग कर दीजे

#### v1-050 (hi-en, interruption) - differs: transcript

- base: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 3583 ms
  > मुन देखी सुरिटुज देखी बास्बूकिं कान्सुल कर्बूकु।
- new: lang `hi`, intent `None`, slots `{}`, task fail, WER 1.00, 5909 ms
  > मुन देखी सुरी तुज देखी बस्वूँकिं कान्सुल कर्ब।
