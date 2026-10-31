> **Status (2026-10-29, added after this report).** This report was written
> against commit `0f996db`, and its line numbers refer to that commit. Since
> then these findings were fixed on `main` (checked against
> `git log 0f996db..f4306752` and the commits in each pull request):
>
> - Pull request #1 ("Fix dashboard 500, digit quantities, decimal amounts;
>   correct docs"): H1 (`2cbe4fa`), H2 (`aa2f145`), M1 (`cd38a01`), and the
>   documentation errors D1, D2 and D3 (`3377680`, `99c521a`).
> - Pull request #2 ("Fix scoring abort, grouped digit ids, account numbers
>   read as amounts"): M3 (`3b941c6`), M2 (`b574a22`), M5 (`adc8d00`).
> - Pull request #3 ("Fix report/analyze scenario lookup and hash check,
>   run-file overwrite, "do" quantity, "card ending" amount"): M6
>   (`9b22011`), L8 (`3cff5d4`), M4 (`2610115`), and the "card ending" /
>   "account ending in" case of M5 (`f430675`). M5 is fixed mostly: by
>   design, a number a few words after an account word is still read as the
>   amount ("from my account send 5000" gives 5000, per `f430675`).
>
> Still open: L1, L2, L3, L4, L5, L6, L7 and L9, and the CI weak spots in
> section 4.4 (`.github/workflows/ci.yml` is unchanged since `0f996db`).
> For D4, `3377680` added a README note on the 2.80 GHz run.
>
> **Status (2026-10-31).** A later batch fixed: short order ids introduced by
> a marker word ("cancel order 2"), L3 (the source city is now the *last*
> marked mention, matching the self-correction rule), L4 ("august 15" parses;
> "5k" is read as 5000), L5 (`script_profile` now reports `other` for
> non-Latin/Devanagari scripts instead of hiding them in `none`; this is the
> one intended rescore difference, on `v1-018` and `v1-029`'s
> `transcript_script`), L7 (a single word must repeat 5+ times to count as a
> loop; no committed transcript's flag changes) and L1 (`report`, `analyze`,
> `compare` and `rescore` print a one-line error for a missing or malformed
> run file instead of a traceback). Re-verified: rescore of the committed
> runs changes no transcript and no task outcome. Left as documented design:
> L2 (ties go to the first-listed intent) and L6 (a hi-en clip detected as
> `en` counts as wrong language). L9 and the CI weak spots remain open.
>
> The summary says the transcript match with the day 3 runs "confirms the
> documented CPU dependence". Later runs show that the transcript
> differences are machine-dependent, but the cause is not isolated; see
> `docs/benchmark_current_main.md` and `docs/rerun_comparison.md`.
>
> The text below is unchanged from the original report.

# Verification report: VoiceBench v0.1.0

Date: 2026-10-29. All checks below ran in a single automated session in a
cloud container. Nothing here comes from a manual listening test or from a
person running the commands. Every number in this report was produced by a
command listed in section 1. Where something could not be checked, section 6
says so.

**Scope.** I made a fresh `git clone` of `main` at `0f996db`. That commit
differs from the v0.1.0 tag (`e8fab2c`) only in `docs/progress.md`, and
`origin/main` also pointed to `0f996db`. All runs used that clone, in a scratch
directory, so the committed `audio/` and `results/` were never touched. The only
file added to the repository is this report.

## Summary

- Everything documented that runs works: setup, tests, validation, audio
  generation, the audio check, both benchmark runs, `report`, `analyze`,
  `compare`, `rescore` and the dashboard. No step failed.
- **Task success reproduces exactly**: 18/50 (auto) and 15/50 (hint), with
  the same per-language counts and the same passing and failing scenarios.
- **WER, latency and several failure-category counts do not match the README.**
  This container had a different CPU (Xeon @ 2.80 GHz, not the documented
  2.10 GHz). My transcripts are **identical (0/50 differ)** to the committed
  day 3 runs, which were made on the 2.80 GHz CPU type, and differ from the day 5
  runs in exactly the 22 (auto) and 33 (hint) scenarios that
  `results/README.md` reports. This confirms the documented CPU dependence.
  It also means the README's WER and latency figures hold only on the
  2.10 GHz machine.
- **Bugs found**: the most serious are a dashboard index page that returns
  HTTP 500 when any one run file points to missing scenarios, and matcher
  bugs. In the matcher, a quantity written as a digit ("2 masala dosa") never
  fills the `quantity` slot, and "1.5 lakh" is read as 600000. None of these
  changes a committed result, but the tests don't cover them.
- **Two documentation errors**: the explanation of the `v1-044` "lucky pass"
  is wrong, and `docs/REPRODUCING.md` gives an old test count.

## 1. Commands run and outcome

Environment: Python 3.13.17, Linux 6.18, 4 logical CPUs (Intel Xeon @ 2.80 GHz),
15.7 GB RAM, no GPU. espeak-ng was not preinstalled. `apt-get install espeak-ng`
installed `1.51+dfsg-12build1`, the version documented in REPRODUCING.md.

| # | command | result |
|---|---------|--------|
| 1 | `make setup` | pass. Resolved numpy 2.5.4, scipy 1.18.1, faster-whisper 1.2.1, **ctranslate2 4.8.4** (lock file: 4.8.3), fastapi 0.162.0, pydantic 2.14.1 |
| 2 | `make test` | pass: **189 passed, 1 skipped** (3.97 s) |
| 3 | `make validate` | pass: 50 valid, sha256 `75fed5e1…aa1b`, en=17 hi=17 hi-en=16, clean=30 noise=10 interruption=10, snr 5 dB=5 and 10 dB=5 |
| 4 | `make audio-check` | pass: "all 50 files are byte-identical to audio/v1/manifest.json" |
| 5 | `make audio` | pass: wrote 50 files, 198.9 s of audio. `git status` was clean afterwards, so the rewritten audio is byte-identical |
| 6 | `make bench` (auto) | pass, exit 0, 4 m 38 s. Whisper `small` downloaded from Hugging Face on first use with no error (464 MB cache); revision `536b0662…ce120`, the same as the committed runs |
| 7 | `make bench POLICY=hint` | pass, exit 0, 4 m 12 s |
| 8 | `voicebench run` (auto) again into a scratch dir, machine otherwise idle | pass, 4 m 20 s; 0/50 transcripts differ from run 6 |
| 9 | `make setup-locked VENV=.venv-locked`, then `make test`, `make audio-check` and an auto run in that env | pass: 189 passed, 1 skipped; audio byte-identical; 0/50 transcripts differ from run 6, so ctranslate2 4.8.3 and 4.8.4 give the same transcripts |
| 10 | `VOICEBENCH_ASR_MODEL=small pytest` (enables the skipped real-model test) | pass: **190 passed** |
| 11 | `voicebench transcribe audio/v1/v1-002.wav --offline` | pass: "Please send 5,000 rupees to Rahul." |
| 12 | `voicebench run --asr oracle` | pass: 50/50, WER 0.00 |
| 13 | `voicebench report`, `analyze`, `compare` on committed and new runs | pass (numbers in sections 2–3) |
| 14 | `voicebench rescore` on all four original committed runs | pass: day 3 originals → only `v1-006` flips fail→pass in each, as documented; day 5 → 0 changes |
| 15 | `make run PORT=8765`, then `curl` on every route | pass (section 4.3) |
| 16 | GitHub Actions history for `ci.yml` (read through the GitHub API) | 6/6 runs on `main` concluded `success`, including `0f996db` and `e8fab2c`. Tag `v0.1.0` → `e8fab2c` |

Caveat on latency: during run 6 I also ran light probes (Python edge-case
scripts, a dashboard server and test clients). Run 8 repeats run 6 with
nothing else running, and section 2 uses run 8's latency. Run 7 overlapped
only with file reads and GitHub API calls.

## 2. README numbers: documented vs reproduced

Documented values are from the day 5 runs (Xeon @ 2.10 GHz). Reproduced values
are from runs 6/8 (auto) and 7 (hint) on a Xeon @ 2.80 GHz.

### Task success (all match)

| language | auto, documented | auto, reproduced | hint, documented | hint, reproduced |
|---|---|---|---|---|
| en | 14/17 | 14/17 ✅ | 14/17 | 14/17 ✅ |
| hi | 0/17 | 0/17 ✅ | 1/17 | 1/17 ✅ |
| hi-en | 4/16 | 4/16 ✅ | 0/16 | 0/16 ✅ |
| all | 18/50 | 18/50 ✅ | 15/50 | 15/50 ✅ |

The same scenarios pass: en failures are `v1-008`, `v1-031`, `v1-041` in
both policies; the hi pass with the hint is `v1-019`; the hi-en passes with
auto are `v1-027`, `v1-028`, `v1-030`, `v1-040`.

### WER (only English matches)

| language | auto, documented | auto, reproduced | hint, documented | hint, reproduced |
|---|---|---|---|---|
| en | 0.39 | 0.39 ✅ | 0.39 | 0.39 ✅ |
| hi | 3.02 | **4.30** ❌ | 1.12 | **0.88** ❌ |
| hi-en | 1.50 | **1.48** ❌ | 1.42 | **1.54** ❌ |
| all | 1.63 | **2.05** ❌ | 0.97 | **0.93** ❌ |

The reproduced Hindi WER (4.30 auto, 0.88 hint) equals the day 3 values on
the 2.80 GHz CPU. The README's direction "the hint lowers Hindi WER" holds
here as well.

### Latency, wall time, cost

| | documented (2.10 GHz) | reproduced (2.80 GHz) |
|---|---|---|
| auto p50 | 2886 ms | **3641 ms** ❌ (run 6: 3708; locked env: 3742) |
| auto p95 | 11707 ms | **16914 ms** ❌ (run 6: 17857; locked: 17680) |
| auto RTF p50 / p95 | 0.78 / 2.45 | **0.99 / 3.74** ❌ |
| auto wall time | 183 s | **252 s** ❌ (run 6: 261 s) |
| hint p50 | 2749 ms | **3845 ms** ❌ |
| hint p95 | 10968 ms | **16575 ms** ❌ |
| hint RTF p50 / p95 | 0.79 / 2.08 | **1.11 / 3.12** ❌ |
| hint wall time | 177 s | **245 s** ❌ |
| cost | 0 USD | 0 USD ✅ |
| "a full run took 3 to 7 minutes" | | 4 m 12 s – 4 m 38 s ✅ |
| audio total | 198.9 s | 198.9 s ✅ |

The README says latency is only comparable on the same machine, so these
differences are expected, but they are large: on this CPU p95 is about 50% higher.
The day 3 runs (same CPU type) recorded p50 5691 / 5542 ms, which also
doesn't match these runs. Latency doesn't follow the CPU name alone.

Minor point: the committed hint run's p50 is 2748.5 ms. `voicebench report`
prints it as `2748` (Python rounds half to even), while README line 56 and
progress.md line 240 say `2749`.

### "What failed" claims in the README

| claim | reproduced |
|---|---|
| auto: none of 33 hi/hi-en clips detected as Hindi | 0/33 ✅ |
| detected as en, hu, ro, la, de or ja | same set ✅ (hi: en 10, hu 3, la 2, ro 1, de 1; hi-en: en 15, ja 1) |
| 30 of 33 transcripts in Latin script | **31/33** ❌ |
| hint: all 33 decoded as Hindi | 33/33 ✅ |
| hint: 1 of 17 Hindi clips passes | 1/17 (`v1-019`) ✅ |
| hint: 24 failures contain no recognisable intent | **26** (primary `no_intent`) ❌ |
| code-switching 4/16 → 0/16 | ✅ |
| 4 slowest clips are loops in both runs | ✅ (auto: the 5 slowest are loops; hint: the 4 slowest) |
| loop clips median latency about 11 s | **16.9 s (auto), 16.6 s (hint)** ❌ |
| every other clip finishes within 5.3 s | auto ✅ (max 4.9 s); **hint ❌: `v1-034`, not a loop, took 9.1 s** |
| English: same three failures | ✅ |
| `v1-044` passes "only by luck, from words in the leaked prompt" | the pass reproduces, but **the explanation is wrong**, see D1 |

Re-computed from the **committed** day 5 files, every one of these claims
and every number in the README results tables matches. The docs describe
their own run files correctly. Only reproduction on different hardware fails.

## 3. docs/failure_analysis.md: documented vs reproduced

| primary category | auto, documented | auto, reproduced | hint, documented | hint, reproduced |
|---|---|---|---|---|
| wrong language | 29 (hi 17, hi-en 12) | 29 (hi 17, hi-en 12) ✅ | n/a | n/a ✅ |
| repetition loop | 0 primary (5 flagged) | 0 primary (5 flagged) ✅ | 6 (hi 2, hi-en 4) | **5 (hi 1, hi-en 4)** ❌ |
| no intent | 0 primary (26 flagged) | 0 primary (26 flagged) ✅ | 24 (hi 12, hi-en 12) | **26 (hi 14, hi-en 12)** ❌ |
| slot error | 2 (en) | 2 (en) ✅ | 4 (en 2, hi 2) | **3 (en 2, hi 1)** ❌ |
| agent prompt leak | 1 (en) | 1 (en) ✅ | 1 (en) | 1 (en) ✅ |
| failures | 32 | 32 ✅ | 35 | 35 ✅ |

Other figures:

| claim | documented | reproduced |
|---|---|---|
| hi auto-detect labels | en 10, hu 4, ro/la/de 1 each | **en 10, hu 3, la 2, ro 1, de 1** ❌ |
| hi-en auto-detect labels | en 14, hu 1, ja 1 | **en 15, ja 1** ❌ |
| loop clips | 5 (auto), 6 (hint), all hi or hi-en | **5 and 5** ❌ (all hi or hi-en ✅); the auto set has `v1-034` instead of `v1-045` |
| loop median latency | 11.7 s / 10.8 s | **16.9 s / 16.6 s** ❌ |
| non-loop median / max | 2.9 / 4.3 s (auto), 2.7 / 5.2 s (hint) | **3.6 / 4.9 s, 3.6 / 9.1 s** ❌ |
| max WER 20.67 on `v1-049` (auto) | 20.67, `v1-049` | 20.67, `v1-049` ✅ |
| Hindi WER 3.02 → 1.12 | | **4.30 → 0.88** ❌ |
| `v1-041` tie: balance 3, transfer 3 → `check_balance` | | ✅ same transcript and scores |
| `v1-041` overlap: onset 1.8 s, overlap 2.6 s | | ✅ (`audio/v1/manifest.json`: 1800 ms, 2626 ms) |
| quoted transcripts (`v1-008`, `v1-017`, `v1-019`, `v1-030`, `v1-031`, `v1-040`, `v1-041`, "कान्सल", "त्रान्स्फर", "संदे", "నిని…", "may god be with you", "तुम तुम तुम") | | all present in the committed day 5 files ✅. Several Hindi ones (e.g. `v1-017`) differ in my runs, as expected from the CPU difference |

Run `voicebench analyze` on the committed day 5 files and every count in the
failure analysis matches.

**Reproducibility table in `results/README.md`**: re-run with
`voicebench compare`. Every row reproduces: 0/50 same-machine, 22/50 auto
and 33/50 hint across CPUs, 0 outcome changes. The `rescore` claim
(only `v1-006` changes) also reproduces.

## 4. Code review: bugs and weak spots, by severity

Each item was confirmed by running it. Probe scripts were run against the
installed package and are not committed. Line numbers refer to `0f996db`.

### High

**H1. One bad run file makes the dashboard index return 500.**
`src/voicebench/dashboard/app.py:45-46` calls `run_overview` for every run
with no error handling. `data.py:65` (`load_scenarios`) raises
`FileNotFoundError` when a run's `scenarios_file` is missing, and `data.py:93`
raises `KeyError` when a result names an unknown scenario. `RunStore.runs`
(`data.py:47`) only skips files that fail to *parse*, so a schema-valid run
file still causes these errors. Observed with a test client: a results dir
with one good run plus one run whose `scenarios_file` points to a missing
file → `/` = 500 and `/runs/<that id>` = 500. The good run's page stays 200,
but the index page no longer lists any run. Same result for a run containing
`scenario_id: "v1-999"`. Malformed JSON is handled correctly (200, "Skipped
files" banner).

**H2. A quantity written as a digit never fills `quantity`.**
`nlu/numbers.py:118-119` marks every all-digit run, including a single `"2"`,
as `digit_sequence=True`. `nlu/matcher.py:155` then drops digit sequences
when looking for a quantity. Result: `"i want 2 masala dosa"` (food) →
`{'item': 'masala dosa'}` with no quantity, so the task fails on a perfect
transcript. `"I want two masala dosa"` works. In the committed runs Whisper
wrote quantities as words (`v1-004`, `v1-035`, `v1-048`), so no reported
number is affected. Whisper often writes numerals in English, though. The tests
only cover the word form (`tests/test_nlu_matcher.py:24`).

### Medium

**M1. Decimal amounts are misread.** `textnorm.normalise` turns "." into a
space, `numbers.py:103-109` joins the single digits, and `_quantity` adds
them: `"send 1.5 lakh to rahul"` → amount `600000`; `"send 2.5 thousand"` →
`7000`. The wrong amount is reported with no warning.

**M2. Digit groups other than single digits are not joined into one id.**
`numbers.py:103-109`: `"PNR 452-137-8690"` → no `pnr`;
`"PNR 45 21 37 86 90"` → no `pnr`; `"cancel order 3 127"` → `order_id 127`;
`"31-27"` → no id. The day 4 fix covers only `7-3-1-0` / `7, 3, 1, 0`.

**M3. A scoring exception aborts the whole run.**
`runner.py:127-128` calls `score()` in the `else:` branch of the `try`, so
errors raised while scoring are not caught by the per-scenario handler. Two
inputs that trigger this:
- characters for which `str.isdigit()` is true but `int()` fails
  (`numbers.py:63`, `86`; `matcher.py:134`): `"send ² thousand to rahul"` →
  `ValueError: invalid literal for int()`; `"book a train to goa on ² may"`
  → same error;
- a scenario reference that normalises to nothing: `reference: "?!"` passes
  validation (`schema.py:117`, `127`), but `metrics.py:17` raises. Confirmed: an
  oracle run on such a file raises and writes no run file.

A real Whisper run would lose all ASR time already spent. Related: Arabic-Indic
digits pass `isdigit` but are not translated, so `"cancel order ٣١٢٧"` →
`order_id '٣١٢٧'`, and `①②③` becomes an order id.

**M4. The romanised "do" next to a number is added into the quantity.**
`numbers.py:47`/`112` skips ambiguous words only when they stand alone, so
`"can you do 3 plates of masala dosa"` → quantity `5` (2 + 3).

**M5. `amount` is the last number in the utterance, whatever kind it is.**
`matcher.py:145`: `"transfer five thousand to rahul from account 1234"` →
amount `1234`.

**M6. `report` and `analyze` skip the scenario-file hash check and depend on the
working directory.** `cli.py:157` and `cli.py:166` load `run.scenarios_file`
relative to the current directory and never compare its sha256. A run
whose recorded hash doesn't match is reported silently (exit 0, no warning),
while `rescore` refuses and the dashboard shows a banner. Running
`voicebench report <abs path>` from `/tmp` fails with
`FileNotFoundError: 'scenarios/v1.jsonl'`.

### Low

- **L1. CLI errors print raw tracebacks.** A malformed or empty run file
  gives a pydantic `ValidationError` traceback with exit 1, from
  `report`/`analyze`/`rescore`. `analyze` on a run with an unknown scenario id
  gives `KeyError` (`analysis.py:108`). `compare` on runs with different
  scenario hashes gives a `ValueError` traceback. The behaviour is correct,
  but the output is not a friendly message.
- **L2. Ties go to the first-listed intent** (`matcher.py:109`):
  `"transfer balance"` → `check_balance`. This is documented, and it decided
  `v1-041`.
- **L3. The source city is the first "from" mention**, against the stated
  "last mention wins" rule for self-corrections:
  `"from pune sorry from delhi to mumbai"` → source `pune`; delhi is dropped.
- **L4. Some dates and amounts are not parsed.** `"august 15"` gives no date
  (only `15 august` works), and `"5k"` gives no amount.
- **L5. `script_profile` ignores scripts other than Latin and Devanagari**
  (`textnorm.py:46-54`). Telugu or Japanese output counts as `none`, the
  same label as an empty transcript.
- **L6. hi-en clips detected as `en` count as `wrong_language`**
  (`analysis.py:87`, hi-en is mapped to `hi`). For code-switched speech this
  is debatable. It decides the primary category of all 12 auto hi-en
  failures, and it flags the 4 hi-en passes.
- **L7. The repetition-loop rule flags natural repetition.**
  `"no no no no I said four"` → loop. It only affects categorisation.
- **L8. Run ids use 1-second resolution**, and `save()` overwrites a file with
  the same name (`runner.py:145`, `203`). If two files share a `run_id`,
  the dashboard lists both but `/runs/{id}` shows only one.
- **L9. The dashboard always serves audio from one `--audio` dir**
  (`audio/v1`), whatever scenario version a run used.

### Checked and found correct

- Hyphenated, comma-separated and Devanagari digits: `3-1-2-7`,
  `3, 1, 2, 7`, `3,127`, `३१२७`, `ऑर्डर ३-१-२-७ कैंसल करो`, `तीन एक दो सात`
  and `four five two one three seven eight six nine zero` (10-digit PNR)
  all resolve correctly.
- Empty, whitespace-only and punctuation-only transcripts give no intent, a
  WER of 1.0 and a task failure, with no crash. Corpus WER with an empty
  hypothesis counts the right number of edits.
- An unknown domain raises a `ValueError`. Unknown scenario languages are
  rejected by the schema (enum).
- Scenario data: ids `v1-001…v1-050` are sequential. The audio manifest ids
  match, all 50 wav sha256 values match, and the manifest's scenario hash
  matches the file. Every noise clip's measured SNR equals its target
  (5.0 / 10.0). Cell sizes are 3–10, as the README says.
- Dashboard XSS: a `<script>` transcript is rendered escaped. The audio
  route rejects ids that are not scenario ids and path-traversal attempts
  (404).

## 4.3 Dashboard routes (live server via `make run PORT=8765`)

| route | status |
|---|---|
| `/` | 200 html, 6 runs listed |
| `/runs/<day5 auto>` (default failures) | 200, 32 failing cases shown (= 32 failures) |
| `?status=all`, `?status=pass&language=hi-en` | 200 |
| `?language=xx&condition=yy&status=zz` | 200 (invalid filters ignored) |
| `/runs/nope`, `/api/runs/nope` | 404 |
| `/api/runs` | 200, 6 entries |
| `/api/runs/<day5 auto>` | 200; overall 18 passes, WER 1.627, p50 2885.7, p95 11707.2 |
| `/audio/v1-001.wav` | 200 audio/wav |
| `/audio/v1-999.wav`, `/audio/manifest.wav`, `/audio/..%2Fmanifest.wav` | 404 |
| `/api/docs`, `/openapi.json` | 200 |

The fresh runs from this session also render (200; 18 and 15 passes).
`results/reproducibility/` is not listed, because `RunStore` reads only the
top level of `results/`. That may be intended.

## 4.4 CI configuration (`.github/workflows/ci.yml`)

It runs correctly: 6/6 green on `main`. Weak spots:

- It installs with `pip install -e ".[dev,asr]"` (unpinned), not
  `requirements-lock.txt`, so CI tests whatever is newest that day. Locally
  this already resolved ctranslate2 4.8.4 rather than the locked 4.8.3. That
  made no difference to transcripts here.
- The audio check uses `--tolerance-lsb 1`; the local default is 0.
- It never starts the dashboard server. Only `TestClient` tests cover it.
- It runs on pushes to `main` and on pull requests only. Pushes to other
  branches are not checked.
- By design it never runs the real-model test or a real benchmark, so CI
  can't catch an ASR regression.

## 5. Documentation errors

- **D1. Wrong explanation of the `v1-044` "lucky pass"** (README line 85-86,
  `docs/failure_analysis.md` line 90-91). The agent prompt is "your call is
  important to us please hold while we connect": it contains neither "agent"
  nor "human". The transcript "…because we are human agents." passes only
  through the keyword `human` (score 3), and "human" comes from the
  caller's own words ("get me a human agent"). `agents` does not match the
  exact-token keyword `agent`: without "human" the matcher finds no intent.
  So the pass is not "from words in the leaked prompt". The
  `agent_prompt_leak` flag on it is still correct (prompt recall ≥ 30%).
- **D2.** `docs/REPRODUCING.md` line 20 says `make test # 176 tests`. The
  real count is 189 passed, 1 skipped, as the README states.
- **D3.** The `2749` vs `2748` rounding noted in section 2.
- **D4.** The README results section gives the machine (Xeon @ 2.10 GHz), and
  the Limitations section says transcripts vary across CPUs. Still, a reader
  re-running `make bench` on a different CPU should expect WER and failure
  counts to differ from the tables (as in sections 2–3), not just latency.
  Only task success reproduced.

## 6. Not verified, and why

- **The documented WER and latency on the 2.10 GHz CPU.** This container had a
  2.80 GHz Xeon, and I couldn't choose the CPU. The day 5 files were
  checked for internal consistency only.
- **Python 3.10 and 3.12.** Only 3.13.17 was available locally. For those
  versions I only read the GitHub Actions results (green).
- **Audio quality and intelligibility.** No one listened to the clips in this
  session, and the claim that Hindi failures can't be attributed to TTS or
  ASR stays untested.
- **Real or telephone audio.** None exists in the repo (documented
  limitation).
- **Latency stability.** Two idle auto runs and one in the locked env gave
  p50 3641–3742 ms and p95 16914–17680 ms. That is enough to show the README
  figures are machine-specific, not enough for a variance estimate.
- **Model download hosts.** The download succeeded on the first try, so no
  host failure could be observed. Which Hugging Face hosts served the files
  was not logged.
