# Scenarios

`v1.jsonl` holds 50 simulated caller turns, one JSON object per line, validated
by `voicebench.schema.Scenario` (`make validate`).

| condition    | count | detail                                                    |
|--------------|-------|-----------------------------------------------------------|
| clean        | 30    | 10 en, 10 hi, 10 hi-en                                    |
| noise        | 10    | 5 at 5 dB SNR, 5 at 10 dB SNR (white / pink / babble)     |
| interruption | 10    | 5 barge-in over an agent prompt, 5 caller self-correction |

Languages overall: en 17, hi 17, hi-en 16. Domains: banking 14, food 13,
travel 12, support 11.

All utterances were written by hand for this project. They are not taken
from real calls, and every name in them (Rahul, Priya, ...) is made up.

## Conventions

- **References are transcripts, not prose**: lower case, no punctuation, and
  numbers spelled out the way a caller would say them ("four eight two one").
- **Script**: Hindi words in Devanagari, English words in Latin script.
  Code-switched (`hi-en`) lines therefore contain both, and the validator
  enforces this. Pure `hi` lines write English loanwords in Devanagari
  (`कार्ड`, `ऑर्डर`), as a Hindi speaker would usually say them.
- **Slot values are canonical**: lower-case ASCII, whatever language the
  caller spoke. Numbers are digits (`"5000"`, `"4821"`), cities are their
  common English names (`"bengaluru"`), dates are kept as spoken (`"tomorrow"`,
  `"friday"`, `"12 november"`). So `दो हज़ार` → `amount: "2000"`.
- **Self-correction**: expected slots hold the caller's *final* value.
- **Barge-in**: `reference` is only the caller's speech. `agent_prompt` is the
  agent audio the caller talks over, and `caller_onset_ms` is when the caller
  starts relative to the start of the prompt.
- Intents and the slots each one allows are defined in
  `src/voicebench/schema.py` (`INTENTS`).

## Versioning

`v1.jsonl` is frozen once results are published against it. Any change to a
line (wording, labels, conditions) goes into a new file `v2.jsonl` with ids
`v2-NNN`, so results from different versions are never compared without
noticing. Every run records the sha256 of the scenario file it used.
