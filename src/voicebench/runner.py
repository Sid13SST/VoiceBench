"""Run every scenario through ASR and scoring, and save a run file."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from voicebench.asr import WHISPER_LANGUAGE_HINT, ASRUnavailable, Transcript
from voicebench.loader import file_sha256
from voicebench.schema import ResultSource, RunManifest, Scenario
from voicebench.scoring import failed, score

LANGUAGE_POLICIES = ("auto", "hint")


class ReferenceTranscriber:
    """Returns the reference text as the 'transcript'.

    Not an ASR model: it checks the pipeline end to end and shows what the
    matcher does with perfect text. Its runs are recorded with
    asr_model="oracle-reference".
    """

    name = "oracle-reference"

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "backend": "none"}

    def transcribe_scenario(self, scenario: Scenario) -> Transcript:
        return Transcript(
            text=scenario.reference, model=self.name, detected_language=None,
            language_probability=None, requested_language=None, latency_ms=0.0, audio_duration_s=0.0,
        )


def hardware_info() -> dict[str, Any]:
    cpu = platform.processor() or None
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    try:
        ram_gb = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 1)
    except (ValueError, OSError, AttributeError):
        ram_gb = None
    return {
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "ram_gb": ram_gb,
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "python": platform.python_version(),
    }


def git_commit(repo: Path) -> Optional[str]:
    try:
        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{sha}-dirty" if dirty else sha


def run(
    scenarios: list[Scenario],
    audio_dir: str | Path,
    transcriber: Any,
    scenarios_file: str,
    command: str,
    source: ResultSource = ResultSource.MEASURED,
    language_policy: str = "auto",
    progress: Optional[Callable[[str], None]] = None,
) -> RunManifest:
    if language_policy not in LANGUAGE_POLICIES:
        raise ValueError(f"language_policy must be one of {LANGUAGE_POLICIES}")
    audio_dir = Path(audio_dir)
    audio_manifest_path = audio_dir / "manifest.json"
    audio_manifest = json.loads(audio_manifest_path.read_text(encoding="utf-8")) if audio_manifest_path.exists() else {}

    # One untimed call so model loading and first-call setup don't land in
    # the first scenario's latency.
    warmup_runs = 0
    if not hasattr(transcriber, "transcribe_scenario"):
        first = next((audio_dir / f"{s.id}.wav" for s in scenarios if (audio_dir / f"{s.id}.wav").exists()), None)
        if first is not None:
            try:
                transcriber.transcribe_file(first, language=None)
                warmup_runs = 1
            except ASRUnavailable:
                raise
            except Exception:
                pass  # the timed call for that file will record the error

    cost_fn = getattr(transcriber, "cost_usd", None)
    results = []
    start = time.perf_counter()
    for s in scenarios:
        wav = audio_dir / f"{s.id}.wav"
        language = WHISPER_LANGUAGE_HINT[s.language.value] if language_policy == "hint" else None
        try:
            if hasattr(transcriber, "transcribe_scenario"):
                t = transcriber.transcribe_scenario(s)
            else:
                if not wav.exists():
                    raise FileNotFoundError(f"missing audio {wav}")
                t = transcriber.transcribe_file(wav, language=language)
        except ASRUnavailable:
            raise  # the whole run is impossible; don't write 50 identical failures
        except Exception as exc:  # one bad file should not sink the run
            results.append(failed(s, source, f"{type(exc).__name__}: {exc}"))
        else:
            results.append(
                score(
                    s, t.text, source,
                    latency_ms=t.latency_ms if t.audio_duration_s else None,
                    audio_duration_s=t.audio_duration_s or None,
                    detected_language=t.detected_language or t.requested_language,
                    cost_usd=cost_fn(t.audio_duration_s) if cost_fn else None,
                )
            )
        if progress:
            r = results[-1]
            progress(f"{s.id} {'PASS' if r.task_success else 'FAIL'} {r.transcript or r.error or ''}")

    wall_time_s = round(time.perf_counter() - start, 2)

    desc = transcriber.describe()
    created = datetime.now(timezone.utc)
    return RunManifest(
        run_id=f"{created:%Y%m%dT%H%M%SZ}-{desc['name'].replace('/', '-')}-{language_policy}",
        created_at=created,
        source=source,
        command=command,
        git_commit=git_commit(Path(scenarios_file).resolve().parent),
        scenarios_file=scenarios_file,
        scenarios_sha256=file_sha256(scenarios_file),
        asr_model=desc["name"],
        asr_model_version=desc.get("backend_version"),
        asr_config=desc,
        language_policy=language_policy,
        device=desc.get("device"),
        tts_engine=audio_manifest.get("tts_engine"),
        hardware=hardware_info(),
        warmup_runs=warmup_runs,
        wall_time_s=wall_time_s,
        cost_note=getattr(transcriber, "cost_note", None),
        results=results,
    )


def rescore(previous: RunManifest, scenarios: list[Scenario], command: str) -> RunManifest:
    """Score the transcripts of ``previous`` again with the current code.

    No audio is decoded: transcripts, latency and detected language are
    copied unchanged, so any difference comes from scoring/matching changes
    alone. Scenarios that errored before stay errored.
    """
    by_id = {s.id: s for s in scenarios}
    results = []
    for old in previous.results:
        s = by_id[old.scenario_id]
        if old.error is not None or old.transcript is None:
            results.append(old)
            continue
        results.append(
            score(
                s, old.transcript, previous.source,
                latency_ms=old.latency_ms, audio_duration_s=old.audio_duration_s,
                detected_language=old.detected_language, cost_usd=old.cost_usd,
            )
        )
    commit = git_commit(Path(previous.scenarios_file).resolve().parent)
    return previous.model_copy(
        update={
            "run_id": f"{previous.run_id}-rescored-{(commit or 'nogit')[:7]}",
            "created_at": datetime.now(timezone.utc),
            "command": command,
            "git_commit": commit,
            "rescored_from": previous.run_id,
            "results": results,
        }
    )


def save(manifest: RunManifest, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{manifest.run_id}.json"
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def load_run(path: str | Path) -> RunManifest:
    return RunManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))
