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

None yet. The lane was built and tested offline against a mock of the API;
no live request has been made from this repository, so there are no
measured Gnani numbers.

When a live run is committed, add a row here:

| file | command | date (UTC) | requests / HTTP attempts | audio s sent | credit before -> after (Usage page) | operator |
|------|---------|------------|--------------------------|--------------|-------------------------------------|----------|

The request counts are in each run file under `asr_config.external_api`.
The credit columns can only come from the app.gnani.ai Usage page: the API
does not report credit use, and nothing here estimates it.
