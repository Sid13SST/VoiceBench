"""Compare two runs scenario by scenario (reproducibility checks)."""

from __future__ import annotations

from typing import Any

from voicebench.schema import RunManifest
from voicebench.understanding import BUILTIN


def compare_runs(a: RunManifest, b: RunManifest) -> dict[str, Any]:
    if a.scenarios_sha256 != b.scenarios_sha256:
        raise ValueError("runs used different scenario files")
    rb = {r.scenario_id: r for r in b.results}
    transcript_diffs, outcome_diffs = [], []
    for ra in a.results:
        other = rb.get(ra.scenario_id)
        if other is None:
            continue
        if ra.transcript != other.transcript:
            transcript_diffs.append(ra.scenario_id)
        if ra.task_success != other.task_success:
            outcome_diffs.append((ra.scenario_id, ra.task_success, other.task_success))
    return {
        "a": a.run_id,
        "b": b.run_id,
        "compared": sum(1 for r in a.results if r.scenario_id in rb),
        "same_hardware": a.hardware == b.hardware and bool(a.hardware),
        "same_model": a.asr_config.get("model_revision") == b.asr_config.get("model_revision")
        and a.asr_config.get("model_revision") is not None,
        "transcripts_differ": transcript_diffs,
        "task_outcome_differs": outcome_diffs,
        # A run file without the field was scored by the built-in matcher.
        "understander_a": a.understander or BUILTIN,
        "understander_b": b.understander or BUILTIN,
        "understanders_differ": (a.understander or BUILTIN) != (b.understander or BUILTIN),
    }
