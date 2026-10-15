"""Load and validate versioned scenario files (JSON Lines)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from voicebench.schema import Scenario


@dataclass
class LineError:
    line: int
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


@dataclass
class ScenarioFileError(Exception):
    path: str
    errors: list[LineError] = field(default_factory=list)

    def __str__(self) -> str:
        details = "\n".join(f"  {e}" for e in self.errors)
        return f"{self.path}: {len(self.errors)} invalid line(s)\n{details}"


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_scenarios(path: str | Path, expected_version: str | None = None) -> list[Scenario]:
    """Parse every line of ``path`` and return the scenarios.

    Collects all problems (bad JSON, schema errors, duplicate ids, mixed
    versions) and raises a single :class:`ScenarioFileError` listing them, so a
    broken file can be fixed in one pass. Blank lines are ignored.
    """
    path = Path(path)
    errors: list[LineError] = []
    scenarios: list[Scenario] = []
    first_line: dict[str, int] = {}

    with path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(LineError(lineno, f"invalid JSON: {exc.msg}"))
                continue
            try:
                scenario = Scenario.model_validate(data)
            except ValidationError as exc:
                for err in exc.errors():
                    loc = ".".join(str(p) for p in err["loc"]) or "<scenario>"
                    errors.append(LineError(lineno, f"{loc}: {err['msg']}"))
                continue
            if scenario.id in first_line:
                errors.append(
                    LineError(lineno, f"duplicate id {scenario.id!r} (first on line {first_line[scenario.id]})")
                )
                continue
            first_line[scenario.id] = lineno
            scenarios.append(scenario)

    versions = {s.version for s in scenarios}
    if expected_version is not None and versions - {expected_version}:
        errors.append(LineError(0, f"expected only version {expected_version!r}, found {sorted(versions)}"))
    elif len(versions) > 1:
        errors.append(LineError(0, f"file mixes versions {sorted(versions)}"))

    if not scenarios and not errors:
        errors.append(LineError(0, "file contains no scenarios"))

    if errors:
        raise ScenarioFileError(str(path), errors)
    return scenarios


def summarize(scenarios: list[Scenario]) -> dict[str, dict[str, int]]:
    """Counts by language, domain, condition and noise SNR."""
    return {
        "language": dict(Counter(s.language.value for s in scenarios)),
        "domain": dict(Counter(s.domain.value for s in scenarios)),
        "condition": dict(Counter(s.condition.value for s in scenarios)),
        "snr_db": dict(Counter(str(s.snr_db) for s in scenarios if s.snr_db is not None)),
    }
