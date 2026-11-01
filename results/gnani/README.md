# Gnani lane results (external API)

Run files of the Gnani Voice QA lane ([docs/GNANI_QA.md](../../docs/GNANI_QA.md)):
Gnani.ai's Prisma STT and Timbre TTS, called as **remote, paid APIs**. They
are not part of the local benchmark in `results/`, are not comparable with
its Whisper runs, and must never be averaged or ranked with them.

| directory | kind | read with |
|-----------|------|-----------|
| `synthetic/` | standard run files (Prisma on `audio/v1`) | `voicebench report` |
| `realspeech/` | real-speech run files (Prisma on FLEURS dev clips) and `manifests/` with each run's clip subset | `voicebench realspeech report` |
| `roundtrip/` | standard run files (Timbre -> Prisma round trip) and `audio-manifests/` with the sha256 of each synthesized WAV | `voicebench report` |

Audio is never committed here: synthesized WAVs stay in the git-ignored
`.cache/gnani/`.

## Committed runs

Four live runs, all made on 1 Nov 2026 (UTC) by `--live` requests to the
Gnani API. The credit column is the cumulative Usage-page reading for the
day: the Usage page does not split credit use per run, so per-run splits are
unavailable. The STT billing (7.51 credits, for the STT requests of all four
runs) showed up first;
the TTS billing for the roundtrip run (2.72 credits) showed up after it.

| file | command | date (UTC) | requests / HTTP attempts | audio s sent | credit before -> after (Usage page) | operator |
|------|---------|------------|--------------------------|--------------|-------------------------------------|----------|
| `synthetic/20261101T044219Z-gnani-prisma-v3.0-auto.json` | `voicebench gnani run --lane synthetic --max-requests 2 --live` | 2026-11-01 04:42:19 | 2 / 2 (2 STT) | 7.493 | 5000.00 -> 4992.49 after all STT runs; 4989.77 after TTS billing landed (per-run split unavailable) | Siddhant |
| `synthetic/20261101T044342Z-gnani-prisma-v3.0-auto.json` | `voicebench gnani run --lane synthetic --max-requests 51 --live` | 2026-11-01 04:43:42 | 51 / 51 (51 STT) | 202.679 | as above (per-run split unavailable) | Siddhant |
| `realspeech/20261101T044527Z-gnani-prisma-v3.0-realspeech-fleurs-hi_in-auto.json` | `voicebench gnani run --lane realspeech --max-requests 76 --live` | 2026-11-01 04:45:27 | 75 / 75 (75 STT) | 852.24 | as above (per-run split unavailable) | Siddhant |
| `roundtrip/20261101T044548Z-gnani-roundtrip-timbre-v2.5-prisma-v3.0-hint.json` | `voicebench gnani roundtrip --max-requests 20 --live` | 2026-11-01 04:45:48 | 20 / 20 (10 TTS + 10 STT, 390 TTS characters) | 23.52 | as above; its TTS share is the 2.72 credits that landed last | Siddhant |

The request counts are in each run file under `asr_config.external_api`.
The credit columns can only come from the app.gnani.ai Usage page: the API
does not report credit use, and nothing here estimates it.

## Runs so far

The first live runs, made on 1 Nov 2026 (UTC). They are external-API runs
made with the operator's own Gnani key and paid from the challenge's free
credit grant ("Base Credit"): 7.51 + 2.72 credits consumed, as read on the
app.gnani.ai Usage page. They are not comparable with local Whisper runs.

| date (UTC) | lane | file | items | headline metric |
|------------|------|------|-------|-----------------|
| 2026-11-01 04:42 | synthetic (probe) | `synthetic/20261101T044219Z-gnani-prisma-v3.0-auto.json` | 2 requests (1 scenario) | connectivity probe only |
| 2026-11-01 04:43 | synthetic | `synthetic/20261101T044342Z-gnani-prisma-v3.0-auto.json` | 50 scenarios | task success 10/50, corpus WER 0.78 |
| 2026-11-01 04:45 | realspeech | `realspeech/20261101T044527Z-gnani-prisma-v3.0-realspeech-fleurs-hi_in-auto.json` | 74 FLEURS dev clips | corpus WER 0.110 |
| 2026-11-01 04:45 | roundtrip | `roundtrip/20261101T044548Z-gnani-roundtrip-timbre-v2.5-prisma-v3.0-hint.json` | 10 scenarios | task success 9/10, corpus WER 0.18 |
