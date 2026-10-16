# Results

Each `*.json` file is one complete run (`voicebench.schema.RunManifest`):
per-scenario transcript, WER, predicted intent and slots, and latency, plus
the command, git commit, scenario-file sha256 and ASR config. They are
written by `voicebench run` and never edited by hand. `voicebench report
<file>` prints the breakdown.

## Runs

| file | command | language policy |
|------|---------|-----------------|
| `20261016T080842Z-faster-whisper-small-auto.json` | `make bench` | auto-detect |
| `20261016T081450Z-faster-whisper-small-hint.json` | `make bench POLICY=hint` | scenario language passed to Whisper (hi-en → `hi`) |

Both runs share this setup:

- Code at commit `40523cf`, clean tree.
- `scenarios/v1.jsonl`, sha256 `75fed5e1…aa1b`.
- Audio: `audio/v1`, synthetic espeak-ng 1.51.
- ASR: faster-whisper 1.2.1 (CTranslate2 4.8.3), model `small`, resolved to
  `Systran/faster-whisper-small@536b0662742c02347bc0e980a01041f333bce120`
  from the Hugging Face cache. CPU, int8, beam 5, temperature 0. These run
  files don't store the revision; it was read from the local cache. Runs from
  later commits record it automatically.
- Machine: cloud container, 4 vCPU Intel Xeon @ 2.80 GHz, no GPU. Latency
  depends heavily on hardware, so compare latency only between runs on the
  same machine.

Results are deterministic up to CPU numerics: decoding uses temperature 0
and no sampling. Re-running on different hardware may change a few tokens.
