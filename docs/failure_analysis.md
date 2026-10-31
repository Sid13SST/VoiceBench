# Failure analysis: Whisper `small` on VoiceBench v1

Sections 1 to 4 are written from the day 5 run files only (the real-speech
section at the end uses its own run files):

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

- **Lucky pass:** `v1-044` (barge-in) passes although the transcript is mostly
  the agent prompt. The only scoring keyword hit is "human", which comes from
  the caller's words; the leaked prompt text contains neither "agent" nor
  "human". The analysis flags it as `agent_prompt_leak` even though it passes.
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

## Real speech (FLEURS Hindi)

Added on day 8. Whisper `small`, same revision and decoding settings as
above, on 150 clips of human Hindi read speech from the Google FLEURS
`hi_in` test split (CC BY 4.0, seed 20261031; see `DATA_NOTES.md`). Run
files:

- `results/realspeech/20261031T200244Z-faster-whisper-small-realspeech-fleurs-hi_in-auto.json` (auto-detect)
- `results/realspeech/20261031T202136Z-faster-whisper-small-realspeech-fleurs-hi_in-hint.json` (language hint `hi`)
- the same two `…-rescored-9336d77.json`: identical transcripts, with the
  per-clip number fields added. The figures below come from these.
- the same two `…-rescored-08a104e.json` (day 9): identical transcripts
  and WER, numbers recovered with the day 9 number parser (section 3).

Every figure is printed by `voicebench realspeech report <rescored file>`
or `voicebench realspeech compare <auto> <hint>`. There are no intents in
FLEURS, so the categories that need them (agent prompt leak, no intent,
wrong intent, slot error) don't apply. The ones that do are used in the
same order (pipeline error → wrong language → repetition loop), and any
other clip with WER above 0 is `recognition_error`.

| | auto-detect | language hint |
|---|---|---|
| corpus WER (3708 reference words) | 0.631 | 0.593 |
| wrong language detected | 19 | n/a |
| repetition loop | 8 | 11 |
| recognition error | 123 | 139 |
| pipeline error | 0 | 0 |
| clips with WER 0 | 0 | 0 |

**Against the synthetic baseline.** Synthetic Hindi (17 clips) has corpus
WER 3.02 (auto) and 1.12 (hint), and auto-detect labelled none of the 17
as Hindi. On human Hindi the same model labels 131 of 150 as Hindi and
WER is 0.63 / 0.59. So the synthetic numbers overstate how badly Whisper
`small` handles Hindi, and language ID especially. The text also differs
(Wikipedia sentences of about 25 words vs short caller turns), so the gap
is not a pure TTS-vs-human measurement.

### 1. Language ID: Urdu is the main confusion

With auto-detect, 19 clips were labelled as another language: `ur` 15,
`ne` 2, `jw` 1, `id` 1. The Urdu ones are written in Arabic script, so
every word counts as an error even when the words are right (Hindi and
Urdu are one spoken language). The `jw` and `id` ones are in Latin script,
romanised Hindi or garble.

`voicebench realspeech compare` shows that for the other 131 clips the
auto and hint transcripts are **identical**. The whole auto-vs-hint
difference is these 19 clips: their WER is 1.08 with auto-detect and 0.74
with the hint. That is Whisper's language ID, not something this repo can
fix; giving the language (the hint policy) is the remedy.

### 2. Recognition errors dominate, and they are Whisper's

No clip is perfect. Of the edits, substitutions are most (1912 auto, 1711
hint), then deletions (249 / 269) and insertions (177 / 217). The report
names a few mechanical kinds of substitution:

| substitution kind | auto | hint | example |
|---|---|---|---|
| aspiration lost or added | 77 | 84 | "गंभीर" → "गंबीर", "था" → "ता" |
| short / long vowel | 42 | 46 | "पानी" → "पानि" |
| nukta / chandrabindu only | 29 | 37 | "बड़ी" → "बडी", "वीज़ा" → "वीजा" |
| a digit on either side | 43 | 39 | "1889" → "उन्नासी" |
| Devanagari vs Latin | 45 | 6 | the Latin-script auto transcripts |
| anything else | 1676 | 1499 | |

The first two are recognition errors and are counted as such. A further
32 / 35 words (the report's `split_or_join`) are a word of one side
written as two adjacent words of the other ("इस में" vs "इसमें"). These are also left as errors: which spelling is right is a
judgement call, and folding them would hide differences rather than fix
anything.

### 3. Numbers: Whisper writes them as misspelled words

34 numbers are written in digits in the references (28 clips; ordinals
such as "11वीं", units such as "35mm", and times are left out). The report
checks whether the matcher's number parser (`nlu/numbers.py`) finds each
value in the transcript. It found **6 of 34** (auto) and **7 of 34**
(hint) at `9336d77`, and finds **9 of 34** and **10 of 34** after the
parser change below (rescores at `08a104e`).

Method. The 150 clips are split into a dev half and a held-out half
(`data/realspeech/fleurs_hi_in_test_150_split.json`, seed 20261101, 75
clips each). The split is by FLEURS sentence, because 15 sentences are
read by two speakers and would otherwise be in both halves. Dev has 15
reference numbers in 12 clips; held-out has 19 in 16. The misses were
classified and the parser changed using dev only; held-out was scored once,
after the rules were committed. No transcript was regenerated: the run
files' saved transcripts were rescored.

Cause of each reference number the parser did not find, before the change
(primary cause; auto / hint):

| cause | dev (15) | held-out (19) | all (34) |
|---|---|---|---|
| found already | 1 / 1 | 5 / 6 | 6 / 7 |
| Whisper: number word misspelled or garbled | 7 / 9 | 7 / 7 | 14 / 16 |
| Whisper: number missing (left out, or a repetition loop) | 3 / 3 | 2 / 4 | 5 / 7 |
| Whisper: transcript in Urdu script | 2 / 0 | 3 / 0 | 5 / 0 |
| parser: unit and hundred as one word, or "सो" after a number (fixed) | 1 / 1 | 2 / 2 | 3 / 3 |
| parser: "सो" for "सौ" on its own (not fixed) | 1 / 1 | 0 / 0 | 1 / 1 |

Examples of the misspellings: "उन्निस्स्सो तर्सट" for 1963 (उन्नीस सौ
तिरसठ), "सथटर" and "सक्तर" for सत्तर (70), "चालिच हजार" for 40,000,
"ती साजार" for तीस हज़ार, "बारासो" for बारह सौ (1200), "10 अजार" for
10,000, "चोथ तिस" for चौंतीस (34). "अटारा सो उन्नासी" for 1889 would be
1879 even read correctly: the last word is 79, not 89. No transcript
contains Devanagari digits. Of the categories one might expect, fractions
(ढाई, साढ़े, सवा) do not occur in these references, ordinals ("11वीं") are
left out of the count on purpose, and no miss was a formatting problem
(digit grouping "800,000" is handled).

So the large majority of the gap is Whisper's transcript, not the matcher:
with auto-detect, 24 of the 28 misses (hint 23 of 27) have no
correctly spelled number to find.

The parser fix (`nlu/numbers.py`), from the dev misses:

- The lexicon had only 1-20 and the round tens, so the dev references'
  31, 53, 63 and 89 (as in 1963 and 1889) could not be read even when
  spelled correctly. All standard words for 21-99 are now listed, with
  the -नबे / -नवे endings of 91-99 and the other dictionary variants.
  No dev transcript had one of these words spelled correctly, so this
  adds nothing to the counts here; a test pins the full 0-99 coverage.
- Whisper wrote 400 as "चार्सो": a unit and its hundred as one word, with
  or without a virama, and "सो" for "सौ". Such a fused word is now read,
  and "सो" counts as a hundred right after a number. "सो" alone is not
  read, because it is also "so" and "sleep"; that leaves one miss ("सो
  साल" for 100 years) unread.
- Misspellings are not guessed at. A fuzzy match would also read "साथ"
  (with) as "साठ" (60); tests pin the dev misspellings that stay unread.

Numbers recovered, before (`9336d77`) and after (`08a104e`), auto / hint:

| half | before | after |
|---|---|---|
| dev (15) | 1 / 1 | 2 / 2 |
| held-out (19) | 5 / 6 | 7 / 8 |
| all (34) | 6 / 7 | 9 / 10 |

The held-out gain is one clip, "एक सो पचास और दोसो" for "150 और 200",
which the two dev-derived rules read, and no number was lost. Numbers
the parser reads that are not among the reference's digits go from 21
to 21 (dev, auto; hint 25 to 25) and from 20 to 18 (held-out, auto;
hint 22 to 20): "एक" and "पचास" were read as 1 and 50 before. Headline
WER is unchanged (0.631 / 0.593): only `numbers_recovered` differs in the
rescored files, on two clips per run.

Not fixed, and why:

- The Whisper misspellings (14 / 16 of 34) and the missing or Urdu-script
  numbers (10 / 7). These need a better recogniser, not a better parser.
- Held-out shows a pattern dev did not: Whisper dropping "ह" ("बारासो"
  for बारह सौ, "10 अजार" for 10 हज़ार). On dev the same habit only
  appears in words that stay unreadable anyway ("अटारा", "जार",
  "साजार"), so a rule for it had no dev evidence, and adding one now
  would be tuning on held-out. It needs a fresh held-out set to test.
- Synthetic benchmark: rescoring the day 5 and 2026-10-29 runs changes
  no intent, slot, task outcome or WER. The parser finds the expected
  number in 0 of 6 (auto) and 0 of 7 (hint) Hindi transcripts both before
  and after, and 4 / 5 and 3 / 5 for Hindi-English, also unchanged. The
  synthetic Hindi transcripts are garbled ("पंच पंच नोशुन" for पाँच पाँच
  नौ शून्य), so no number in them is readable.

Correction to day 8: it said no miss was a correctly spelled number word
the parser lacked. True for these transcripts, but the parser also lacked
the correct words for most reference numbers below 100, and it treated
"चार्सो" as unreadable when it is a regular joined spelling.

### 4. Nukta and chandrabindu: one matcher fix

When Whisper got a word with a nukta otherwise right, it **dropped the
nukta 27 times and kept it 5 times** (auto; hint 35 vs 7). Chandrabindu
was written as anusvara: the 29 / 37 "nukta / chandrabindu only"
substitutions include both. The matcher's lexicon handled this with hand-added variants
(हज़ार/हजार, पाँच/पांच, कहाँ/कहां), but not everywhere: "पिज्जा" did not
match the menu item "पिज़्ज़ा".

Fix (`textnorm.fold_spelling_variants`, used by `nlu/matcher.py` and
`nlu/numbers.py`): the matcher drops the nukta and writes chandrabindu as
anusvara on both the transcript and every lexicon form. Regression tests:
`test_nukta_and_chandrabindu_spellings_match` (the "पिज्जा" case failed
before the change) and `test_folded_number_words_keep_their_value`.

Before and after:

- **Real-speech lane**: unchanged. WER keeps both marks (`normalise` is
  not changed), and numbers recovered stayed 6 / 34 and 7 / 34, because
  every number word the parser knows was already listed with and without
  the marks. Corpus WER with the two marks folded, reported as a
  diagnostic, is 0.622 (auto) and 0.582 (hint); about 0.01 of WER is
  these spellings.
- **Synthetic benchmark**: rescoring every committed run with the change
  alters no intent, slot or task outcome (checked by
  `test_default_rescore_of_every_committed_run_is_unchanged`).
- So the fix is backed by what Whisper does with real Hindi, but its
  measured effect is on matcher keywords, not on any number in these
  runs.

### 5. Repetition loops

8 clips loop with auto-detect and 11 with the hint; the 8 are among the
11. The existing rule catches all of them, at word level ("ॐ ॐ ॐ …",
"आपने आपने …") and at character level ("च्च्च्…", "ँँँ…"). Loop clips
have a median latency of 12.3 s (auto) and 11.8 s (hint), against 7.3 s
and 6.3 s for other clips. The real clips are longer than the synthetic
ones (11.7 s on average against 4.0 s), so latencies are higher overall.

### 6. Other things found

- Three transcripts per run contain U+FFFD, a broken character, each time
  as the transcript's last character: decoding stopped in the middle of a
  multi-byte character (Whisper's tokens are bytes). `normalise` turns it into a space, so it doesn't add
  a word; it is a Whisper / faster-whisper artefact and is left as is.
- A real-speech run takes about 20 minutes, so a commit made during the
  run could be recorded as its code. `run_realspeech` now reads the commit
  before decoding. The two runs here were made at `6e3ddb7`, before that
  change, with no commit during the runs; `6e3ddb7` is what they record.

### What this does not show

- Phone audio, conversational or accented speech, noise, or
  interruptions: FLEURS is clean read speech.
- Hindi-English code-switching: no openly licensed real source could be
  verified (`DATA_NOTES.md`).
- Task success for real callers: there are no intents or slots here.
