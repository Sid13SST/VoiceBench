"""Aggregate a run by language, condition and both."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from voicebench.metrics import corpus_wer, percentile
from voicebench.schema import RunManifest, Scenario, ScenarioResult


def latency_stats(results: list[ScenarioResult]) -> dict[str, Any]:
    """p50/p95 of per-utterance latency and real-time factor (latency / audio length).

    Nearest-rank percentiles over the timed utterances only. With 50 or fewer
    utterances p95 is close to the maximum, so read it as "worst few".
    """
    timed = [r for r in results if r.latency_ms is not None and r.audio_duration_s]
    lat = [r.latency_ms for r in timed]
    rtf = [r.latency_ms / 1000 / r.audio_duration_s for r in timed]
    return {
        "n_timed": len(timed),
        "latency_p50_ms": percentile(lat, 50),
        "latency_p95_ms": percentile(lat, 95),
        "rtf_p50": percentile(rtf, 50),
        "rtf_p95": percentile(rtf, 95),
    }


def _group_stats(pairs: list[tuple[Scenario, ScenarioResult]]) -> dict[str, Any]:
    n = len(pairs)
    scored = [(s, r) for s, r in pairs if r.error is None]
    costs = [r.cost_usd for _, r in pairs if r.cost_usd is not None]
    return {
        **latency_stats([r for _, r in pairs]),
        "cost_usd": sum(costs) if costs else None,
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
        "hardware": run.hardware,
        "wall_time_s": run.wall_time_s,
        "warmup_runs": run.warmup_runs,
        "cost_note": run.cost_note,
        "overall": _group_stats(pairs),
        "by_language": group(lambda s: s.language.value),
        "by_condition": group(lambda s: s.condition.value),
        "by_language_condition": group(lambda s: f"{s.language.value}/{s.condition.value}"),
        "by_domain": group(lambda s: s.domain.value),
    }


def format_table(summary: dict[str, Any]) -> str:
    lines = [f"run {summary['run_id']}  [{summary['source']}]  asr={summary['asr_model']}", ""]
    header = f"{'group':<22}{'n':>4}{'task ok':>10}{'intent':>9}{'WER':>8}{'errors':>8}{'p50 ms':>9}{'p95 ms':>9}{'RTF p50':>9}"
    for title in ("overall", "by_language", "by_condition", "by_language_condition"):
        groups = {"all": summary["overall"]} if title == "overall" else summary[title]
        lines += [title, header]
        for name, g in groups.items():
            w = "-" if g["corpus_wer"] is None else f"{g['corpus_wer']:.2f}"
            p50 = "-" if g["latency_p50_ms"] is None else f"{g['latency_p50_ms']:.0f}"
            p95 = "-" if g["latency_p95_ms"] is None else f"{g['latency_p95_ms']:.0f}"
            rtf = "-" if g["rtf_p50"] is None else f"{g['rtf_p50']:.2f}"
            lines.append(
                f"{name:<22}{g['n']:>4}{g['task_success']:>5}/{g['n']:<4}"
                f"{g['intent_accuracy']:>9.0%}{w:>8}{g['errors']:>8}{p50:>9}{p95:>9}{rtf:>9}"
            )
        lines.append("")
    o = summary["overall"]
    if summary.get("wall_time_s") is not None:
        lines.append(f"wall time {summary['wall_time_s']:.1f} s (after {summary['warmup_runs']} untimed warm-up call)")
    if o["cost_usd"] is not None:
        lines.append(f"cost {o['cost_usd']:.2f} USD - {summary['cost_note'] or 'no cost note'}")
    hw = summary.get("hardware") or {}
    if hw:
        lines.append(f"hardware {hw.get('cpu')}, {hw.get('logical_cpus')} logical CPUs, {hw.get('ram_gb')} GB RAM")
    return "\n".join(lines)
