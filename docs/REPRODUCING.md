# Reproducing the results

Everything here runs on a laptop CPU with free, local tools. Nothing needs
an API key or costs money.

## 1. Environment

| what | version used for the committed runs |
|------|-------------------------------------|
| OS | Ubuntu 24.04 (cloud container) |
| Python | 3.13.16 (CI also tests 3.10 and 3.12) |
| espeak-ng | 1.51 (`espeak-ng 1.51+dfsg-12build1` from Ubuntu) |
| faster-whisper / CTranslate2 | 1.2.1 / 4.8.3 |
| Whisper weights | `Systran/faster-whisper-small@536b0662742c02347bc0e980a01041f333bce120` |
| other packages | `requirements-lock.txt` |

```bash
sudo apt-get install espeak-ng      # only needed to (re)generate audio
make setup-locked                   # exact versions (Python 3.11+); or `make setup` for any 3.10+
make test                           # with espeak-ng installed: 336 pass, 1 skipped (real-model test); without it 331 pass, 6 skipped (5 need espeak-ng); no model download
```

## 2. Scenarios → audio

```bash
make validate       # scenarios/v1.jsonl: 50 valid, prints sha256 and makeup
make audio-check    # regenerate audio in a temp dir and compare with audio/v1/manifest.json
make audio          # (re)write audio/v1 for real
```

What to expect:

- With espeak-ng 1.51 and the locked packages, all 50 files are
  **byte-identical** to the committed ones.
- With other numpy/scipy versions, a sample can be rounded differently. With
  numpy 2.2.6 / scipy 1.15.3 (Python 3.10), one sample of `v1-038` differed
  by 1 step out of 65,536. `--check` prints such differences, and
  `--tolerance-lsb 1` (used in CI) accepts them.
- A different espeak-ng version will likely give different audio. Results
  are then not comparable to the committed ones.

## 3. Audio → results

Preflight before a benchmark run, so the run measures the commit you mean
to measure (a stale checkout once produced runs of an older `main`):

```bash
git fetch origin
git rev-parse HEAD                  # must equal the commit you mean to measure
```

After the run, check that the run file's `git_commit` equals that same
commit (with no `-dirty` suffix):

```bash
python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['git_commit'])" results/<run>.json
```

```bash
make bench                 # Whisper small, language auto-detect   (~3-7 min on 4 CPUs)
make bench POLICY=hint     # scenario language passed to Whisper
.venv/bin/voicebench report results/<run>.json
make run                   # dashboard at http://127.0.0.1:8000
```

On first use, `make bench` downloads the Whisper weights (~480 MB) from
Hugging Face. That needs `huggingface.co` and its file hosts
(`*.hf.co`, e.g. `cas-server.xethub.hf.co`). To use weights you already
have: `make bench MODEL=/path/to/ctranslate2-whisper-small`.

Each run file records the command, git commit (with `-dirty` if the tree
had changes), scenario sha256, model revision, decoding settings, hardware,
warm-up count and wall time.

## 3b. Real-speech lane (FLEURS Hindi)

```bash
make realspeech-fetch       # FLEURS hi_in test archive (~250 MB) from huggingface.co at revision 70bb2e84,
                            # 150 manifest clips extracted to .cache/realspeech/ (git-ignored), sha256-checked
make realspeech             # auto-detect -> results/realspeech/   (~20 min on 4 CPUs)
make realspeech POLICY=hint # Whisper told the language is hi
.venv/bin/voicebench realspeech report results/realspeech/<run>.json
.venv/bin/voicebench realspeech compare results/realspeech/<auto>.json results/realspeech/<hint>.json
```

The download needs `huggingface.co` and its file hosts (`*.hf.co`), as
for the weights. `voicebench realspeech manifest` rebuilds
`data/realspeech/fleurs_hi_in_test_150.json` from the same revision and
seed. Rebuilt with the default `--out` it is byte-identical (checked on
day 8); with another `--out`, only the recorded command line differs. A rebuilt run on another CPU will
likely differ in some transcripts, as the benchmark's do (section 4); that
has not been measured for this lane.

## 4. What is and isn't reproducible

| | same machine | different CPU |
|---|---|---|
| audio (espeak-ng 1.51) | identical | identical with numpy 2.5 on three CPUs (Xeon 2.80 GHz where it was made, Xeon 2.10 GHz, AMD EPYC in CI); with numpy 2.2 (Python 3.10, locally and in CI), one sample of `v1-038` differs by 1 LSB |
| transcripts | **identical** (0/50 differ on re-run) | **differ**: 22/50 (auto) and 33/50 (hint) between the day 3 and day 5 machines |
| pass/fail per scenario | identical | identical in the one comparison made (0 changes) |
| WER | identical | Hindi corpus WER moved from 4.30 to 3.02 (auto) |
| latency | similar (timing noise) | not comparable |

Decoding uses temperature 0 and no sampling, so it's deterministic on one
machine. Across CPUs, CTranslate2's int8 kernels can produce different
results. This shows mostly on clips where Whisper is already producing
garbled output (the espeak-ng Hindi). It's an observed effect from two
machines, not a general guarantee. Check your own runs with:

```bash
.venv/bin/voicebench compare results/<committed run>.json results/<your run>.json
```

## 5. Changing the scorer without re-running ASR

```bash
.venv/bin/voicebench rescore results/<run>.json
```

This re-scores the saved transcripts with the current code and writes a new
run file with `rescored_from` set. It was used once: for the
hyphenated-digit fix on day 4 (see `results/README.md`).

A run made with `--understander` (see [`ADAPTERS.md`](ADAPTERS.md)) is
only rescored with the same `--understander`; `rescore` refuses anything
else. Runs without an `understander` field, including all committed ones,
count as the built-in matcher.
