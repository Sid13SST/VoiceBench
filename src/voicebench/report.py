"""Aggregate a run by language, condition and both."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from voicebench.metrics import corpus_wer
from voicebench.schema import RunManifest, Scenario, ScenarioResult


def _group_stats(pairs: list[tuple[Scenario, ScenarioResult]]) -> dict[str, Any]:
    n = len(pairs)
    scored = [(s, r) for s, r in pairs if r.error is None]
    return {
        "n": n,
        "task_success": sum(bool(r.task_success) for _, r in pairs),
        "task_success_rate": sum(bool(r.task_success) for _, r in pairs) / n if n else None,
        "intent_accuracy": sum(bool(r.intent_correct) for _, r in pairs) / n if n else None,
        "corpus_wer": corpus_wer((s.reference, r.transcript or "") for s, r in scored) if scored else None,
        "errors": n - len(scored),
    }


def summarise(run: RunManifest, scenarios: list[Scenario]) -> dict[str, Any]:
    by_id = {s.id: s for s in scenarios}
    missing = [r.scenario_id for r in run.results if r.scenario_id not in by_id]
    if missing:
        raise ValueError(f"results for unknown scenarios: {missing}")
    pairs = [(by_id[r.scenario_id], r) for r in run.results]

    def group(key: Callable[[Scenario], str]) -> dict[str, Any]:
        buckets: dict[str, list] = defaultdict(list)
        for s, r in pairs:
            buckets[key(s)].append((s, r))
        return {k: _group_stats(v) for k, v in sorted(buckets.items())}

    return {
        "run_id": run.run_id,
        "source": run.source.value,
        "asr_model": run.asr_model,
        "overall": _group_stats(pairs),
        "by_language": group(lambda s: s.language.value),
        "by_condition": group(lambda s: s.condition.value),
        "by_language_condition": group(lambda s: f"{s.language.value}/{s.condition.value}"),
        "by_domain": group(lambda s: s.domain.value),
    }


def format_table(summary: dict[str, Any]) -> str:
    lines = [f"run {summary['run_id']}  [{summary['source']}]  asr={summary['asr_model']}", ""]
    header = f"{'group':<22}{'n':>4}{'task ok':>10}{'intent':>9}{'WER':>8}{'errors':>8}"
    for title in ("overall", "by_language", "by_condition", "by_language_condition"):
        groups = {"all": summary["overall"]} if title == "overall" else summary[title]
        lines += [title, header]
        for name, g in groups.items():
            w = "-" if g["corpus_wer"] is None else f"{g['corpus_wer']:.2f}"
            lines.append(
                f"{name:<22}{g['n']:>4}{g['task_success']:>5}/{g['n']:<4}"
                f"{g['intent_accuracy']:>9.0%}{w:>8}{g['errors']:>8}"
            )
        lines.append("")
    return "\n".join(lines)
