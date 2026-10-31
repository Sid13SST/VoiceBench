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
    RealSpeechStore,
    RunStore,
    RunUnusable,
    case_rows,
    matrix,
    run_overview,
)
from voicebench.dashboard.data import word_diff
from voicebench.realspeech import clip_category, summarise_realspeech, word_error_breakdown
from voicebench.understanding import BUILTIN

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
SCENARIO_ID_RE = re.compile(r"^v\d+-\d{3}$")


def create_app(results_dir: str | Path = "results", audio_dir: str | Path = "audio/v1",
               repo_root: str | Path | None = None, realspeech_dir: str | Path | None = None) -> FastAPI:
    store = RunStore(results_dir, repo_root)
    # Real-speech runs (external human audio) have their own directory and pages.
    real = RealSpeechStore(realspeech_dir if realspeech_dir is not None else Path(results_dir) / "realspeech")
    audio_dir = Path(audio_dir)
    app = FastAPI(title="VoiceBench", docs_url="/api/docs", redoc_url=None)

    def _entry(run_id: str):
        entry = store.get(run_id)
        if entry is None:
            raise HTTPException(404, f"no run {run_id!r}")
        return entry

    def _overview(entry):
        try:
            return run_overview(entry, store)
        except RunUnusable as e:
            raise HTTPException(422, f"run {entry.run_id!r} ({entry.path.name}) cannot be shown: {e}") from None

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        rows, unusable = [], []
        for e in store.runs():
            try:
                ov = run_overview(e, store)
            except RunUnusable as err:
                unusable.append({"file": e.path.name, "reason": str(err)})
                continue
            rows.append({"entry": e, "overall": ov["summary"]["overall"], "hash_ok": ov["hash_ok"]})
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"rows": rows, "invalid": store.invalid, "unusable": unusable, "results_dir": str(store.results_dir),
             "real_rows": [{"run": r, "s": summarise_realspeech(r)} for r in real.runs()],
             "real_invalid": real.invalid, "real_dir": str(real.directory)},
        )

    @app.get("/realspeech/{run_id}", response_class=HTMLResponse)
    def realspeech_page(request: Request, run_id: str, sort: str = Query("wer")):
        run = real.get(run_id)
        if run is None:
            raise HTTPException(404, f"no real-speech run {run_id!r}")
        clips = list(run.results)
        if sort == "wer":
            clips.sort(key=lambda r: (r.wer is None, -(r.wer or 0)))
        return TEMPLATES.TemplateResponse(
            request, "realspeech.html",
            {"m": run, "s": summarise_realspeech(run), "b": word_error_breakdown(run),
             "clips": [{"r": r, "category": clip_category(r, run.language_policy),
                        "diff": word_diff(r.reference, r.transcript or "") if r.error is None else []}
                       for r in clips],
             "sort": "wer" if sort == "wer" else "id"},
        )

    @app.get("/api/realspeech")
    def api_realspeech():
        return [summarise_realspeech(r) for r in real.runs()]

    @app.get("/api/realspeech/{run_id}")
    def api_realspeech_run(run_id: str):
        run = real.get(run_id)
        if run is None:
            raise HTTPException(404, f"no real-speech run {run_id!r}")
        return {"summary": summarise_realspeech(run), "run": run}

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
        try:
            ov = run_overview(entry, store)
        except RunUnusable as e:
            return TEMPLATES.TemplateResponse(
                request, "unusable.html", {"m": entry.manifest, "file": entry.path.name, "reason": str(e)},
                status_code=422,
            )
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
             "rescored_from": e.manifest.rescored_from, "file": e.path.name,
             "understander": e.manifest.understander or BUILTIN}
            for e in store.runs()
        ]

    @app.get("/api/runs/{run_id}")
    def api_run(run_id: str):
        entry = _entry(run_id)
        ov = _overview(entry)
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
