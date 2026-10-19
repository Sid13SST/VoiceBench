# Failure analysis: Whisper `small` on VoiceBench v1

Written from the day 5 run files only:

- `results/20261018T132344Z-faster-whisper-small-auto.json` (language auto-detect)
- `results/20261018T132652Z-faster-whisper-small-hint.json` (caller's language passed to Whisper)

Every count below can be regenerated with `voicebench analyze <run file>`
(rules in `src/voicebench/analysis.py`). Each failure gets one *primary*
category, assigned in a fixed order: wrong language → repetition loop →
agent prompt leak → no intent → wrong intent → slot error. I adjusted the
repetition-loop rule twice after looking at these runs: once to catch
5-word phrases ("may god be with you" ×N), and once to catch repeated
2-character units ("నిని…") while ignoring long numbers. Those were the
only changes.

**The audio is synthetic espeak-ng speech, 16 to 17 clips per language.**
Everything below describes this audio and this model, not real callers.

## Summary

| | en | hi | hi-en | all |
|---|---|---|---|---|
| task success, auto-detect | 14/17 | 0/17 | 4/16 | 18/50 |
| task success, language hint | 14/17 | 1/17 | 0/16 | 15/50 |

| primary failure category | auto-detect | language hint |
|---|---|---|
| wrong language detected | 29 (hi 17, hi-en 12) | n/a (language given) |
| repetition loop | 0 as primary (5 flagged) | 6 (hi 2, hi-en 4) |
| no intent found | 0 as primary (26 flagged) | 24 (hi 12, hi-en 12) |
| slot error | 2 (en) | 4 (en 2, hi 2) |
| agent prompt leak | 1 (en) | 1 (en) |
| **failures** | **32** | **35** |

## 1. Hindi: language ID fails first, recognition fails second

- **With auto-detect, none of the 33 Hindi or Hindi-English clips was
  detected as Hindi.** Hindi clips were labelled `en` 10 times, `hu` 4, and
  `ro`/`la`/`de` once each. Hindi-English clips were labelled `en` 14
  times, `hu` once and `ja` once. The transcripts are then text in the wrong
  language, e.g. `v1-017` → "Sok remárkod a knúsékán purkiba…".
- **Giving the language fixes detection but not recognition.** With the
  hint, all 33 are decoded as Hindi in Devanagari, yet only 1 of 17 Hindi
  clips passes (`v1-019`, "बुजे किसी सां से बात करनी हैं" → `talk_to_agent`).
  24 of the 35 failures have no recognisable intent keyword at all.
  Hindi WER improves from 3.02 to 1.12, still above one error per word.
- What this does **not** show: whether the cause is Whisper `small`'s
  Hindi or espeak-ng's Hindi audio. Nobody has listened to these clips.
  Natural Hindi speech is needed to separate the two.

## 2. Code-switching: the language hint makes things worse

Hindi-English goes from 4/16 (auto) to 0/16 (hint), the opposite of Hindi.

- **Auto-detect** mostly treats these clips as English and keeps the English
  content words in Latin script. That's enough for the matcher in 4 cases:
  `v1-030` "Order 3127 Cancel Cargo please." → `cancel_order`, order 3127;
  `v1-040` "Sunday Mali train people can cancel kaleehae." → `cancel_booking`.
  These passes come *with* a wrong language label. They are lucky, not robust.
- **With the hint**, the same English words are written in Devanagari, often
  with non-standard spellings the matcher doesn't know: "कान्सल" (lexicon:
  "कैंसल"), "त्रान्स्फर" ("ट्रांसफर"), "संदे" ("sunday"). This is partly a
  matcher limitation. A matcher that normalised transliteration variants
  might recover some of these. I haven't counted how many, because judging
  "close enough" spellings would be my own call, not a rule.

## 3. Repetition loops drive latency

- Whisper got stuck repeating itself in 5 clips (auto) and 6 (hint), all of
  them Hindi or Hindi-English: "may god be with you, may god be with you,
  …", "तुम तुम तुम …", and Telugu-script "నినినిని…" for a Hindi clip.
- **In both runs, the 4 slowest clips are loops.** Loop clips have a median
  latency of 11.7 s (auto) and 10.8 s (hint). All other clips: median 2.9 s
  / 2.7 s, maximum 4.3 s / 5.2 s. The p95 latency in the README (about 11 s)
  is a measure of these loops, not of typical speed.
- Loops also produce the extreme WERs (the maximum is 20.67, `v1-049` in
  the auto run), and these dominate corpus WER for Hindi.

## 4. English: three failures, each with a different cause

The same three English scenarios fail in both runs (14/17 pass):

| scenario | condition | what happened |
|---|---|---|
| `v1-008` | clean | PNR "four five two one three seven eight six nine zero" → "PNR45213786, I'm zero": the digit string has only 8 digits ("nine" is lost, "zero" becomes "I'm zero"), so no 10-digit `pnr` is found. A real ASR error on a long spoken digit string. |
| `v1-031` | noise, 5 dB babble | "from pune to mumbai" → "for people who don't want to": the city names are lost in babble, so `source` and `destination` are missing. Intent, mode and date survive. |
| `v1-041` | barge-in | "Welcome to the bank for balance and trance 3,000 groupings to never transfer": the agent prompt and part of the caller are mixed together ("3,000", "transfer", and "neha" heard as "never"). "balance" (prompt) and "transfer" (caller) both score 3, and the matcher breaks ties by list order, so it picks `check_balance`. That's an ASR failure (overlap) made worse by a matcher tie rule. The caller starts 1.8 s into the prompt, and the two overlap for 2.6 s. |

- **Lucky pass:** `v1-044` (barge-in) passes because the transcript is mostly
  the agent prompt and contains "agents". The analysis flags it as
  `agent_prompt_leak` even though it passes.
- **Self-correction works when ASR is right:** `v1-046` ("send 2000, no
  sorry, 4000…" → 4000) and `v1-048` ("two masala dosa wait make that
  three" → 3) both pass via the last-mention rule.
- Noise and interruption each have only 3 to 4 English clips, so this
  doesn't support any claim like "noise costs X%". Both failures are
  plausible mechanisms, not rates.

## What would change these conclusions

1. Natural, properly licensed Hindi and Hindi-English speech. It's the only
   way to separate the TTS problem from the ASR problem in sections 1 and 2.
2. Larger or India-focused ASR models. Only Whisper `small` was tried.
3. A matcher that handles transliteration variants. It should be judged on
   held-out phrasings, since this lexicon was written alongside v1.
4. More clips per condition before reading anything into the noise or
   interruption numbers.
