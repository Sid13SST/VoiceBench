"""Rule-based failure categories for a run, so the failure analysis is reproducible.

Each failed scenario gets exactly one *primary* category: the first rule
below that matches. Rules are applied in this order because earlier
problems explain later ones (a repetition loop usually also means no intent):

1. pipeline_error     the pipeline raised an error for this scenario
2. wrong_language     language auto-detect chose a language other than the
                      caller's (only checked when the run used auto-detect)
3. repetition_loop    the transcript repeats a word or phrase (up to 6 words) 4+ times
                      in a row, or a 1-3 character non-digit unit 10+ times
4. agent_prompt_leak  barge-in clip whose transcript contains at least 30%
                      of the agent prompt's words
5. no_intent          the matcher found no intent keyword at all
6. wrong_intent       the matcher picked a different intent
7. slot_error         intent right, at least one expected slot wrong/missing

Flags are not exclusive and are also computed for passing scenarios (for
example a pass whose transcript is mostly the leaked agent prompt).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from voicebench.asr import WHISPER_LANGUAGE_HINT
from voicebench.schema import InterruptionKind, RunManifest, Scenario, ScenarioResult
from voicebench.textnorm import tokens

CATEGORIES = (
    "pipeline_error",
    "wrong_language",
    "repetition_loop",
    "agent_prompt_leak",
    "no_intent",
    "wrong_intent",
    "slot_error",
)
LEAK_THRESHOLD = 0.3
_CHAR_RUN_RE = re.compile(r"([^\s\d]{1,3}?)\1{9,}")  # digits excluded: 1000000000 is not a loop


def has_repetition_loop(text: str, min_repeats: int = 4, max_ngram: int = 6) -> bool:
    if _CHAR_RUN_RE.search(text):
        return True
    toks = tokens(text)
    for n in range(1, max_ngram + 1):
        for i in range(len(toks) - n * min_repeats + 1):
            gram = toks[i : i + n]
            if all(toks[i + k * n : i + (k + 1) * n] == gram for k in range(1, min_repeats)):
                return True
    return False


def agent_prompt_recall(scenario: Scenario, transcript: str) -> Optional[float]:
    """Share of the agent prompt's distinct words that appear in the transcript (barge-in only)."""
    intr = scenario.interruption
    if intr is None or intr.kind is not InterruptionKind.BARGE_IN:
        return None
    prompt = set(tokens(intr.agent_prompt)) - set(tokens(scenario.reference))
    if not prompt:
        return None
    return len(prompt & set(tokens(transcript))) / len(prompt)


@dataclass
class CaseAnalysis:
    scenario_id: str
    language: str
    condition: str
    passed: bool
    primary: Optional[str]  # None for passes
    flags: list[str] = field(default_factory=list)
    wrong_slots: list[str] = field(default_factory=list)


def analyse_case(s: Scenario, r: ScenarioResult, language_policy: Optional[str]) -> CaseAnalysis:
    flags: list[str] = []
    transcript = r.transcript or ""
    if r.error is not None:
        flags.append("pipeline_error")
    else:
        expected_lang = WHISPER_LANGUAGE_HINT[s.language.value]
        if language_policy == "auto" and r.detected_language and r.detected_language != expected_lang:
            flags.append("wrong_language")
        if has_repetition_loop(transcript):
            flags.append("repetition_loop")
        recall = agent_prompt_recall(s, transcript)
        if recall is not None and recall >= LEAK_THRESHOLD:
            flags.append("agent_prompt_leak")
        if r.predicted_intent is None:
            flags.append("no_intent")
        elif not r.intent_correct:
            flags.append("wrong_intent")
        elif not r.slots_correct:
            flags.append("slot_error")
    wrong_slots = [k for k, v in s.expected_slots.items() if r.predicted_slots.get(k) != v]
    passed = bool(r.task_success)
    primary = None if passed else next((c for c in CATEGORIES if c in flags), "other")
    return CaseAnalysis(s.id, s.language.value, s.condition.value, passed, primary, flags, wrong_slots)


def analyse_run(run: RunManifest, scenarios: list[Scenario]) -> dict[str, Any]:
    by_id = {s.id: s for s in scenarios}
    cases = [analyse_case(by_id[r.scenario_id], r, run.language_policy) for r in run.results]
    failures = [c for c in cases if not c.passed]
    by_lang: dict[str, Counter] = defaultdict(Counter)
    by_cond: dict[str, Counter] = defaultdict(Counter)
    for c in failures:
        by_lang[c.language][c.primary] += 1
        by_cond[c.condition][c.primary] += 1
    flag_counts = Counter(f for c in cases for f in c.flags)
    return {
        "run_id": run.run_id,
        "language_policy": run.language_policy,
        "n": len(cases),
        "failures": len(failures),
        "primary": Counter(c.primary for c in failures),
        "primary_by_language": {k: dict(v) for k, v in sorted(by_lang.items())},
        "primary_by_condition": {k: dict(v) for k, v in sorted(by_cond.items())},
        "flags_all_cases": dict(flag_counts),
        "passes_with_flags": [(c.scenario_id, c.flags) for c in cases if c.passed and c.flags],
        "cases": cases,
    }


def format_analysis(a: dict[str, Any]) -> str:
    langs = ["en", "hi", "hi-en"]
    conds = ["clean", "noise", "interruption"]
    lines = [f"run {a['run_id']}  (language policy: {a['language_policy']})",
             f"{a['failures']} of {a['n']} scenarios failed", "",
             f"{'primary category':<20}{'all':>5}" + "".join(f"{x:>7}" for x in langs) + "".join(f"{x:>14}" for x in conds)]
    for cat in (*CATEGORIES, "other"):
        total = a["primary"].get(cat, 0)
        if not total:
            continue
        row = f"{cat:<20}{total:>5}"
        row += "".join(f"{a['primary_by_language'].get(x, {}).get(cat, 0):>7}" for x in langs)
        row += "".join(f"{a['primary_by_condition'].get(x, {}).get(cat, 0):>14}" for x in conds)
        lines.append(row)
    lines += ["", "flags over all scenarios (not exclusive): "
              + ", ".join(f"{k}={v}" for k, v in sorted(a["flags_all_cases"].items()))]
    if a["passes_with_flags"]:
        lines.append("passes that carry a flag: " + "; ".join(f"{i} {f}" for i, f in a["passes_with_flags"]))
    lines += ["", "failed scenarios:"]
    for c in a["cases"]:
        if not c.passed:
            extra = f" slots={','.join(c.wrong_slots)}" if c.primary == "slot_error" else ""
            lines.append(f"  {c.scenario_id} {c.language:<6}{c.condition:<13}{c.primary}{extra}  [{' '.join(c.flags)}]")
    return "\n".join(lines)
