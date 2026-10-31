"""Read run files and shape them for the dashboard."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from voicebench.loader import file_sha256, load_scenarios
from voicebench.report import summarise
from voicebench.runner import load_run
from voicebench.schema import RunManifest, Scenario, ScenarioResult
from voicebench.textnorm import tokens

LANGUAGES = ("en", "hi", "hi-en")
CONDITIONS = ("clean", "noise", "interruption")


@dataclass
class RunEntry:
    run_id: str
    path: Path
    manifest: RunManifest


class RunUnusable(Exception):
    """A valid run file that cannot be scored: its scenarios file is missing or does not match it."""


class RunStore:
    """Loads every ``*.json`` run in ``results_dir``; reloads files that changed."""

    def __init__(self, results_dir: str | Path, repo_root: str | Path | None = None):
        self.results_dir = Path(results_dir)
        self.repo_root = Path(repo_root) if repo_root else self.results_dir.resolve().parent
        self._cache: dict[Path, tuple[float, Optional[RunEntry]]] = {}
        self.invalid: list[str] = []

    def runs(self) -> list[RunEntry]:
        out, self.invalid = [], []
        for path in sorted(self.results_dir.glob("*.json")):
            mtime = path.stat().st_mtime
            cached = self._cache.get(path)
            if cached is None or cached[0] != mtime:
                try:
                    m = load_run(path)
                    entry: Optional[RunEntry] = RunEntry(m.run_id, path, m)
                except (ValidationError, ValueError):
                    entry = None
                self._cache[path] = (mtime, entry)
            entry = self._cache[path][1]
            if entry is None:
                self.invalid.append(path.name)
            else:
                out.append(entry)
        return sorted(out, key=lambda e: e.manifest.created_at, reverse=True)

    def get(self, run_id: str) -> Optional[RunEntry]:
        return next((e for e in self.runs() if e.run_id == run_id), None)

    def scenarios_for(self, m: RunManifest) -> tuple[list[Scenario], bool]:
        """Scenarios the run was made against, and whether the file still matches its hash."""
        path = Path(m.scenarios_file)
        if not path.is_absolute():
            path = self.repo_root / path
        return load_scenarios(path), file_sha256(path) == m.scenarios_sha256


def word_diff(reference: str, hypothesis: str) -> list[dict[str, str]]:
    """Align normalised words: ops are equal / sub / del (ref only) / ins (hyp only)."""
    ref, hyp = tokens(reference), tokens(hypothesis)
    out: list[dict[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False).get_opcodes():
        if op == "equal":
            out += [{"op": "equal", "ref": w, "hyp": w} for w in ref[i1:i2]]
        elif op == "delete":
            out += [{"op": "del", "ref": w, "hyp": ""} for w in ref[i1:i2]]
        elif op == "insert":
            out += [{"op": "ins", "ref": "", "hyp": w} for w in hyp[j1:j2]]
        else:
            out.append({"op": "sub", "ref": " ".join(ref[i1:i2]), "hyp": " ".join(hyp[j1:j2])})
    return out


def _cell(pairs: list[tuple[Scenario, ScenarioResult]]) -> dict[str, Any]:
    n = len(pairs)
    ok = sum(bool(r.task_success) for _, r in pairs)
    return {"n": n, "ok": ok, "rate": ok / n if n else None}


def matrix(run: RunManifest, scenarios: list[Scenario]) -> dict[str, Any]:
    """Task success counts for each language x condition cell, plus row/column totals."""
    by_id = {s.id: s for s in scenarios}
    pairs = [(by_id[r.scenario_id], r) for r in run.results]
    rows = {}
    for lang in LANGUAGES:
        rows[lang] = {
            cond: _cell([(s, r) for s, r in pairs if s.language.value == lang and s.condition.value == cond])
            for cond in CONDITIONS
        }
        rows[lang]["all"] = _cell([(s, r) for s, r in pairs if s.language.value == lang])
    rows["all"] = {cond: _cell([(s, r) for s, r in pairs if s.condition.value == cond]) for cond in CONDITIONS}
    rows["all"]["all"] = _cell(pairs)
    return rows


def case_rows(
    run: RunManifest,
    scenarios: list[Scenario],
    language: str | None = None,
    condition: str | None = None,
    status: str = "fail",
) -> list[dict[str, Any]]:
    by_id = {s.id: s for s in scenarios}
    rows = []
    for r in run.results:
        s = by_id[r.scenario_id]
        if language and s.language.value != language:
            continue
        if condition and s.condition.value != condition:
            continue
        if status == "fail" and r.task_success:
            continue
        if status == "pass" and not r.task_success:
            continue
        rows.append({
            "scenario": s,
            "result": r,
            "diff": word_diff(s.reference, r.transcript or "") if r.error is None else [],
            "slot_errors": {
                k: (v, r.predicted_slots.get(k)) for k, v in s.expected_slots.items() if r.predicted_slots.get(k) != v
            },
        })
    return rows


def run_overview(entry: RunEntry, store: RunStore) -> dict[str, Any]:
    """Summary of a run. Raises RunUnusable if its scenarios cannot be loaded or do not cover its results."""
    try:
        scenarios, hash_ok = store.scenarios_for(entry.manifest)
        summary = summarise(entry.manifest, scenarios)
    except FileNotFoundError:
        raise RunUnusable(f"scenarios file not found: {entry.manifest.scenarios_file}") from None
    except ValueError as e:  # includes pydantic ValidationError from a malformed scenarios file
        raise RunUnusable(str(e)) from None
    return {"summary": summary, "hash_ok": hash_ok, "scenarios": scenarios}


class RealSpeechStore:
    """Loads real-speech run files (``voicebench.realspeech.RealSpeechRun``) from their own directory.

    They live apart from the synthetic runs (``results/realspeech/`` by
    default) and are never mixed into the synthetic run list.
    """

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.invalid: list[str] = []

    def runs(self) -> list[Any]:
        from voicebench.realspeech import load_realspeech_run

        out, self.invalid = [], []
        for path in sorted(self.directory.glob("*.json")) if self.directory.is_dir() else []:
            try:
                out.append(load_realspeech_run(path))
            except (ValidationError, ValueError):
                self.invalid.append(path.name)
        return sorted(out, key=lambda r: r.created_at, reverse=True)

    def get(self, run_id: str) -> Optional[Any]:
        return next((r for r in self.runs() if r.run_id == run_id), None)
