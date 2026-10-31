# Gnani Voice QA lane (external API)

An optional lane that runs Gnani.ai's **Prisma** speech-to-text and
**Timbre** text-to-speech REST APIs on small subsets of VoiceBench's existing
audio and scenarios. It adds to the benchmark; it does not change it.

## Scope

- **External, paid, remote.** Every request goes to `api.vachana.ai` and
  uses credit on your Gnani account. This is unlike the rest of VoiceBench,
  which runs locally with no keys.
- **Separate from the local benchmark.** Gnani runs are written to
  `results/gnani/`. They are labelled as external-API runs in the run file
  (`asr_config.external_api`, `notes`, an `asr_model` starting `gnani-`), in
  `voicebench report` / `realspeech report` output (an `EXTERNAL API RUN`
  line), in `voicebench compare` output, and on the dashboard, where they get
  their own section and a banner on each run page.
- **Not comparable with the local Whisper numbers.** Gnani runs cover a
  handful of items, not all 50 scenarios or 150 clips. Their latency includes
  the network. The remote service can change without notice. Never average
  Gnani numbers with the Whisper ones, put them in the same table, or rank
  the two against each other on these runs.
- **The Whisper numbers are unchanged.** Nothing in this lane touches
  `scenarios/v1.jsonl`, the committed audio, the committed runs, the
  real-speech lane or the scoring.

## What each lane measures

| lane | command | input | measures | run file |
|------|---------|-------|----------|----------|
| synthetic | `voicebench gnani run --lane synthetic` | committed espeak-ng audio (`audio/v1`) | Prisma recognition, then intent/slots with the **built-in matcher** (so `understander` is `builtin`) | standard run file (`voicebench report`) |
| realspeech | `voicebench gnani run --lane realspeech` | FLEURS Hindi clips from the **dev** half of `data/realspeech/fleurs_hi_in_test_150_split.json` | Prisma recognition on human speech: WER, detected language, numbers | real-speech run file (`voicebench realspeech report`) |
| roundtrip | `voicebench gnani roundtrip` | scenario reference texts | Timbre speaks the reference, Prisma transcribes it, the transcript is scored against the reference | standard run file + audio manifest |

The recognition lanes go through `runner.run()` and
`realspeech.run_realspeech()` unchanged, through the transcriber hook in
[ADAPTERS.md](ADAPTERS.md) (`voicebench.gnani.transcriber.GnaniPrismaTranscriber`).

The **round trip measures both services at once.** A word lost may be
Timbre's mispronunciation or Prisma's misrecognition; the run cannot tell
which. It is a consistency check of the two together, not a score for
either one. Its audio is synthetic speech from Timbre, not human speech.

## Setup

1. Get an API key from the Gnani dashboard at [app.gnani.ai](https://app.gnani.ai).
2. Install the extra: `pip install -e ".[gnani]"` (adds `httpx`; the `dev`
   extra already has it).
3. Put the key in the environment of the shell that runs VoiceBench, and
   nowhere else:

   ```bash
   read -rs GNANI_API_KEY && export GNANI_API_KEY
   ```

   The client reads only `GNANI_API_KEY`. There is no command-line option
   for the key, it is never written to a run file and it is removed from any
   error text. `.env` and `.env.*` are git-ignored in case you keep it in one;
   never commit it.

## Budget rules (free tier)

Credit costs per request are not published, so the lane counts what it can
and leaves cost to you:

- **Nothing is sent without `--live`.** Without it, every command prints the
  plan (items, requests, audio seconds) and exits 0. `--live` without
  `GNANI_API_KEY` exits 2.
- **`--max-requests N` is a hard cap** (default 10). Each STT transcription and
  each TTS synthesis counts as one request; a 429 retry of the same request
  does not count again (HTTP attempts are reported separately). The command
  picks a subset that fits: `N - 1` items for the recognition lanes (the
  runner always makes one untimed warm-up call first, and it is billed),
  `N / 2` scenarios for the round trip (one TTS and one STT each). If the cap
  is reached anyway the run stops and no run file is written.
- **402 (out of credit) stops the run at once**, prints `OUT OF CREDIT`,
  writes no run file and exits 3. 401 and 403 also stop the run (exit 2).
  429 is retried up to 3 attempts with exponential backoff and jitter (the
  API sends no `Retry-After`); if all fail, that item is recorded as an
  error and the run continues.
- **After every live run** the command prints the requests made, HTTP
  attempts, audio seconds sent and TTS characters, and reminds you to check
  the **Usage** page on app.gnani.ai. Note the balance before a run and read
  the delta after it.
- **No cost is invented.** `cost_usd` is never set. If a reply carries a
  header whose name mentions credit, usage, balance, billing, cost or quota,
  it is kept per item in `asr_config.external_api.credit_headers_by_item`;
  otherwise the run file says credit use was not reported.

Start with the smallest run, look at the Usage page, then decide:

```bash
voicebench gnani run --lane synthetic --max-requests 3            # dry run: what would be sent
voicebench gnani run --lane synthetic --max-requests 3 --live     # 2 scenarios + warm-up
```

## Running each lane

```bash
# Synthetic audio, 9 scenarios + warm-up (spread over languages and conditions).
voicebench gnani run --lane synthetic --max-requests 10 --live
# The same with the scenario language sent as a hint (en-IN / hi-IN).
voicebench gnani run --lane synthetic --language-policy hint --max-requests 10 --live
# Exactly these scenarios.
voicebench gnani run --lane synthetic --ids v1-002,v1-014,v1-027 --max-requests 4 --live

# FLEURS dev clips (fetch the audio first; it is git-ignored).
voicebench realspeech fetch
voicebench gnani run --lane realspeech --max-requests 10 --live

# TTS + STT round trip on 5 scenarios.
voicebench gnani roundtrip --max-requests 10 --live
voicebench gnani roundtrip --tts-model timbre-v2.5 --voice-hi Bhavna --ids v1-011,v1-012 --max-requests 4 --live

# Read the results.
voicebench report results/gnani/synthetic/<run>.json
voicebench realspeech report results/gnani/realspeech/<run>.json
voicebench report results/gnani/roundtrip/<run>.json
voicebench dashboard            # "External API runs (Gnani)" section
```

Other options: `--model prisma-v3.0|prisma-v2.5`,
`--format verbatim|transcribe|transliterate`, `--auto-language-code`,
`--timeout` (seconds per request), `--out`, `-v`. For the round trip:
`--tts-model timbre-v2.5|timbre-v3.0`, `--voice-en`, `--voice-hi`,
`--voice-hi-en`, `--speed`, `--stt-model`, `--cache`. The defaults are the
`timbre-v2.5` voices Kaveri (English), Nalini (Hindi) and Poorvi
(Hinglish); `timbre-v3.0` has a different voice catalog, so pass voices from
it with that model.

## Language mapping

Prisma needs a `language_code` on every request.

| VoiceBench | Prisma `language_code` |
|------------|------------------------|
| `en` | `en-IN` |
| `hi` | `hi-IN` |
| `hi-en` with `--language-policy hint` | `hi-IN` (the runner hands code-switched scenarios over as `hi`, as it does for Whisper) |
| any, `--language-policy auto` | `hi-IN,en-IN` with `prisma-v3.0` (a hint covering every language in the benchmark, not a lock); change with `--auto-language-code`, e.g. `indic-auto`. `prisma-v2.5` takes one code only, so `auto` with it needs a single `--auto-language-code` |
| round trip | the scenario's own language: `en-IN`, `hi-IN`, and `hi-IN,en-IN` for `hi-en` (prisma-v3.0) |

Timbre gets `en-IN` for English and `hi-IN` for Hindi and Hindi-English.
Scenario references already write numbers as words, as Timbre expects.

`detected_language` in the run file is Prisma's `detected_language_code`
(prisma-v3.0 only) cut to the language part (`hi-IN` -> `hi`), so it reads
like Whisper's codes; it is empty when the reply has none.

## Files

```
results/gnani/
  README.md                         provenance and budget of every committed run
  synthetic/<run_id>.json           standard run files
  realspeech/<run_id>.json          real-speech run files
  realspeech/manifests/*.json       the clip subset each run used (with sha256 per clip)
  roundtrip/<run_id>.json           standard run files
  roundtrip/audio-manifests/<run_id>.json   sha256, duration and voice of each synthesized WAV
.cache/gnani/roundtrip/<time>/*.wav synthesized audio (git-ignored, never committed)
```

Commit the JSON files and a line in `results/gnani/README.md` saying who
ran it, when, with what `--max-requests`, and the credit delta read from the
Usage page. Never commit audio.

## Limitations

- **30 s per request.** The REST STT endpoint takes clips of at most 30 s.
  Longer clips are not sent (recorded as `ClipTooLong`, no credit used).
- **Credit costs are not published**, and the documented replies do not
  report credit, so the lane cannot say what a run cost. Read it off the
  Usage page.
- **Not bit-reproducible.** Results depend on a remote service whose model,
  decoding and voices can change; the run file records the model name sent
  and any model name the reply reports, but no server-side version. Two runs
  of the same command may differ. Synthesized round-trip audio may differ
  between runs; the sha256 values identify what a given run used.
- **Small samples.** A 10-request budget gives 9 scenarios or 5 round trips:
  enough to see how the service behaves on this material, not to estimate
  an error rate with any precision.
- **Latency is client-side** and includes upload, network, queueing and any
  429 waits. It is not comparable with local Whisper latency.
- **Code written from the documentation, not from live traffic.** The
  request and reply fields follow Gnani's public API reference and its
  Python SDK (`transcript`, `detected_language_code`, `truncated`; TTS returns
  the WAV bytes). The tests replay hand-written replies. Field names of the
  error bodies (`error_code`/`code`/`error`, optionally under `detail`) are
  read defensively. Whether `language_code` accepts a comma-separated list
  directly was taken from the API reference; the SDK instead sends
  candidate languages as `multi_lang_codes` with `language_code=indic-auto`.
  If a live run rejects the list, use `--auto-language-code indic-auto` or
  `--language-policy hint`.
