# Adapters: plugging in your own transcriber or understander

VoiceBench has two places where you can swap in your own code:

- the **transcriber** (speech to text), a Python object passed to
  `runner.run()`;
- the **understander** (text to intent and slots), a function that replaces
  the built-in rule-based matcher.

Both are small hooks for experiments. They are not a plugin system, and
the limits below matter.

> **Security.** `--understander package.module:function` **imports and runs
> a Python module** in the benchmark process, with all the rights of that
> process. Use it only with trusted local code that you have read. Never
> point it at untrusted code or code downloaded from somewhere you don't
> control.

## The understander contract

```python
def understand(transcript: str, domain: str) -> dict:
    return {"intent": "transfer_money", "slots": {"amount": "5000", "recipient": "rahul"}}
```

- `transcript` is the ASR output for one scenario (or the reference text
  with `--asr oracle`).
- `domain` is the scenario's domain as a string: `"banking"`, `"food"`,
  `"travel"` or `"support"`.
- The return value must be a `dict` with **exactly** the keys `"intent"`
  and `"slots"`:
  - `"intent"`: a `str`, or `None` for "no intent recognised";
  - `"slots"`: a `dict` mapping `str` to `str` (may be empty).

The output is checked for every scenario. If the function raises, or
returns anything else (not a dict, missing or extra keys, a non-string
intent, a non-string slot value...), that scenario is recorded with an
`error` such as `UnderstanderError: RuntimeError: ...` or
`UnderstanderError: expected keys ['intent', 'slots'], got ['intent']`, and
counts as a task failure, exactly like a transcription error. The other
scenarios still run. There is **no fallback** to the built-in matcher.

Scoring is the same as for the built-in matcher: the intent must equal the
scenario's `expected_intent`, and every expected slot must be present with
exactly the expected value (extra slots are ignored). Values must therefore
use the scenarios' canonical forms, e.g. `"amount": "5000"`, not
`"five thousand"` or `"₹5,000"`. See `scenarios/README.md` and the
`INTENTS` table in `src/voicebench/schema.py` for the intents and slot names.

### Running with an understander

The module has to be importable by the Python that runs VoiceBench:
installed in the venv, or on `PYTHONPATH`.

```bash
PYTHONPATH=. .venv/bin/voicebench run --understander my_nlu:understand
```

`--understander` works with every other `run` option (`--asr oracle`,
`--language-policy hint`, ...). From Python, pass the callable instead:

```python
from voicebench.runner import run
manifest = run(scenarios, "audio/v1", transcriber, "scenarios/v1.jsonl", "my command",
               understand=my_nlu.understand, understander="my_nlu:understand")
```

`scoring.score(..., understand=...)` takes the same argument for a single
transcript.

### What the run file records

Every new run file has an `understander` field: `"builtin"` for the
built-in matcher, or the `package.module:function` given on the command
line (from Python: the `understander` argument, else the callable's
`module:qualname`). `voicebench report` prints it in the header when it
is not `builtin`. Run files written before this field existed have no
`understander` and are treated as `builtin`.

### Compare and the dashboard

`voicebench compare A B` prints the understander of both runs
(`builtin` for a run file without the field). When they differ it says
so explicitly, for example:

```
understander: A=builtin B=my_nlu:understand
understanders differ: A=builtin B=my_nlu:understand - this compares two systems, not a reproducibility check
```

It does not refuse: comparing two systems on the same scenarios is
legitimate, and the exit status is the same as for any other comparison.
From Python, `compare.compare_runs()` returns the two values as
`understander_a` and `understander_b`, and `understanders_differ` as a
boolean, next to its other fields.

The dashboard shows the understander for every run in the run list and in
the run page header: plain `builtin` for the built-in matcher, an
**external** tag followed by the recorded name otherwise; an external
run's page also has a banner saying it was not scored by the built-in
matcher. `/api/runs` includes an `understander` key for each run. The name
is read from the run file, so it is treated as untrusted text and always
HTML-escaped.

### Rescoring

`voicebench rescore` only re-scores with the understander the run
recorded:

- a `builtin` run (or an old run file without the field) is rescored with
  the built-in matcher; passing `--understander` is refused;
- a run made with `--understander my_nlu:understand` must be rescored with
  exactly `--understander my_nlu:understand`; without it, or with a
  different one, `rescore` exits with status 1 and writes nothing.

So a run scored by your code is never silently re-scored by the built-in
matcher, or the other way round.

### Example

A deliberately tiny understander (`my_nlu.py`). It only knows two banking
phrasings and uses no network and no secrets:

```python
import re

def understand(transcript: str, domain: str) -> dict:
    text = transcript.lower()
    if domain != "banking":
        return {"intent": None, "slots": {}}
    if "block" in text and "card" in text:
        card = next((c for c in ("credit", "debit") if c in text), None)
        return {"intent": "block_card", "slots": {"card_type": card} if card else {}}
    if "balance" in text:
        return {"intent": "check_balance", "slots": {}}
    m = re.search(r"send (\d+) (?:rupees )?to (\w+)", text)
    if m:
        return {"intent": "transfer_money", "slots": {"amount": m.group(1), "recipient": m.group(2)}}
    return {"intent": None, "slots": {}}
```

```bash
PYTHONPATH=. .venv/bin/voicebench run --asr oracle --understander my_nlu:understand --out /tmp/vb
```

It will fail most scenarios, which is the point: the numbers measure
whatever you plug in.

## The transcriber hook

There is no command-line option for a custom transcriber: `run --asr`
offers only `faster-whisper` and `oracle`. From Python, `runner.run()`
accepts any object with the following shape; this is how the hook works
today.

- `describe() -> dict` (required). `describe()["name"]` becomes the run's
  `asr_model` and part of its `run_id`; the whole dict is stored as
  `asr_config`, and its `backend_version` and `device` keys, if present,
  as `asr_model_version` and `device`.
- One of two ways to transcribe, returning a `voicebench.asr.Transcript`:
  - `transcribe_scenario(scenario)`: if the object has this method it is
    always used, gets the `Scenario`, and no audio file is read (this is
    how `--asr oracle` works);
  - otherwise `transcribe_file(path, language=None)`: called with
    `<audio_dir>/<scenario id>.wav`, and `language` is `None` with
    `--language-policy auto` or the Whisper code (`"en"` or `"hi"`) with
    `hint`. Before the timed loop it is called once, untimed, on the first
    available file (`warmup_runs: 1`); a missing file is that scenario's
    error.
- Optional `cost_usd(audio_duration_s) -> float` and a `cost_note` string,
  recorded per scenario and per run.

`Transcript.latency_ms` and `audio_duration_s` are recorded only when
`audio_duration_s` is non-zero. The recorded `detected_language` is
`Transcript.detected_language`, or `requested_language` when that is
empty. Raising `voicebench.asr.ASRUnavailable` aborts the whole run; any
other exception is recorded as that scenario's error.

## Limits

- **Fixed domains and intents.** Scenarios, domains (`banking`, `food`,
  `travel`, `support`) and their intents and slots are built in
  (`Domain` and `INTENTS` in `schema.py`). An understander can only be
  scored on these. A project with other domains or intents **cannot be
  scored yet**: there is no way to load them from a file.
- **No HTTP support.** VoiceBench does not call remote services for
  transcription or understanding, and has no built-in client, timeouts or
  retries for them.
- **The built-in matcher is unchanged.** Its open limitations (lexicon
  written alongside the scenarios, domain given to it, intent ties broken
  by list order; see the README's Limitations) still apply to every
  `builtin` run, including all committed results.
- An understander runs in the benchmark process, once per scenario, and
  its time is not part of the measured latency (only the `transcribe` call
  is timed).
- These hooks are new and lightly tested. They are not production-ready
  and may change.
