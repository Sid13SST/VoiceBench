"""FastAPI app: run list, per-run pass/fail matrix and failing-case browser.

Start with ``make run`` (or ``voicebench dashboard``). Read-only: it never
writes to the results directory.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from voicebench.dashboard.data import (
    CONDITIONS,
    LANGUAGES,
    RunStore,
    case_rows,
    matrix,
    run_overview,
)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
SCENARIO_ID_RE = re.compile(r"^v\d+-\d{3}$")


def create_app(results_dir: str | Path = "results", audio_dir: str | Path = "audio/v1",
               repo_root: str | Path | None = None) -> FastAPI:
    store = RunStore(results_dir, repo_root)
    audio_dir = Path(audio_dir)
    app = FastAPI(title="VoiceBench", docs_url="/api/docs", redoc_url=None)

    def _entry(run_id: str):
        entry = store.get(run_id)
        if entry is None:
            raise HTTPException(404, f"no run {run_id!r}")
        return entry

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        rows = []
        for e in store.runs():
            ov = run_overview(e, store)
            rows.append({"entry": e, "overall": ov["summary"]["overall"], "hash_ok": ov["hash_ok"]})
        return TEMPLATES.TemplateResponse(
            request, "index.html", {"rows": rows, "invalid": store.invalid, "results_dir": str(store.results_dir)}
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_page(
        request: Request,
        run_id: str,
        language: Optional[str] = Query(None),
        condition: Optional[str] = Query(None),
        status: str = Query("fail"),
    ):
        entry = _entry(run_id)
        language = language if language in LANGUAGES else None
        condition = condition if condition in CONDITIONS else None
        status = status if status in ("fail", "pass", "all") else "fail"
        ov = run_overview(entry, store)
        m = entry.manifest
        return TEMPLATES.TemplateResponse(
            request,
            "run.html",
            {
                "m": m,
                "summary": ov["summary"],
                "hash_ok": ov["hash_ok"],
                "matrix": matrix(m, ov["scenarios"]),
                "cases": case_rows(m, ov["scenarios"], language, condition, status),
                "languages": LANGUAGES,
                "conditions": CONDITIONS,
                "f": {"language": language, "condition": condition, "status": status},
                "has_audio": audio_dir.is_dir(),
            },
        )

    @app.get("/api/runs")
    def api_runs():
        return [
            {"run_id": e.run_id, "created_at": e.manifest.created_at, "asr_model": e.manifest.asr_model,
             "language_policy": e.manifest.language_policy, "source": e.manifest.source.value,
             "rescored_from": e.manifest.rescored_from, "file": e.path.name}
            for e in store.runs()
        ]

    @app.get("/api/runs/{run_id}")
    def api_run(run_id: str):
        entry = _entry(run_id)
        ov = run_overview(entry, store)
        return {"summary": ov["summary"], "scenario_hash_matches": ov["hash_ok"], "run": entry.manifest}

    @app.get("/audio/{scenario_id}.wav")
    def audio(scenario_id: str):
        if not SCENARIO_ID_RE.match(scenario_id):
            raise HTTPException(404)
        path = audio_dir / f"{scenario_id}.wav"
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="audio/wav")

    return app
