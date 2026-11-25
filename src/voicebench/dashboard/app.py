"""FastAPI app: run list, per-run pass/fail matrix and failing-case browser.

Start with ``make run`` (or ``voicebench dashboard``). Read-only: it never
writes to the results directory.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from voicebench.dashboard.data import (
    CONDITIONS,
    LANGUAGES,
    RealSpeechStore,
    RunStore,
    RunUnusable,
    case_rows,
    featured_runs,
    matrix,
    run_overview,
)
from voicebench.dashboard.live import MAX_BODY_BYTES, AnalyzeRequest, analyze
from voicebench.dashboard.data import word_diff
from voicebench.gnani import COMPARABILITY, external_provider
from voicebench.realspeech import clip_category, summarise_realspeech, word_error_breakdown
from voicebench.understanding import BUILTIN

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
SCENARIO_ID_RE = re.compile(r"^v\d+-\d{3}$")


def create_app(results_dir: str | Path = "results", audio_dir: str | Path = "audio/v1",
               repo_root: str | Path | None = None, realspeech_dir: str | Path | None = None,
               gnani_dir: str | Path | None = None) -> FastAPI:
    store = RunStore(results_dir, repo_root)
    # Real-speech runs (external human audio) have their own directory and pages.
    real = RealSpeechStore(realspeech_dir if realspeech_dir is not None else Path(results_dir) / "realspeech")
    # External-API runs (Gnani lane, docs/GNANI_QA.md): their own directories and their own
    # section of the run list, never mixed into the local runs above.
    gnani = Path(gnani_dir) if gnani_dir is not None else Path(results_dir) / "gnani"
    gnani_stores = {lane: RunStore(gnani / lane, store.repo_root) for lane in ("synthetic", "roundtrip")}
    gnani_real = RealSpeechStore(gnani / "realspeech")
    audio_dir = Path(audio_dir)
    app = FastAPI(title="VoiceBench", docs_url="/api/docs", redoc_url=None)
    def _find(run_id: str):
        """(entry, the store it is in, its Gnani lane or None)."""
        entry = store.get(run_id)
        if entry is not None:
            return entry, store, None
        for lane, s in gnani_stores.items():
            entry = s.get(run_id)
            if entry is not None:
                return entry, s, lane
        raise HTTPException(404, f"no run {run_id!r}")

    def _entry(run_id: str):
        return _find(run_id)[0]

    def _overview(entry):
        try:
            return run_overview(entry, _find(entry.run_id)[1])
        except RunUnusable as e:
            raise HTTPException(422, f"run {entry.run_id!r} ({entry.path.name}) cannot be shown: {e}") from None

    def _shown(path: Path) -> str:
        """A directory as shown on the page: relative to the repo root when it is inside it."""
        try:
            return str(Path(path).resolve().relative_to(store.repo_root.resolve()))
        except ValueError:
            return str(path)

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
        gnani_rows, gnani_invalid = [], []
        for lane, s in gnani_stores.items():
            for e in s.runs():
                try:
                    ov = run_overview(e, s)
                except RunUnusable as err:
                    gnani_invalid.append(f"{e.path.name}: {err}")
                    continue
                gnani_rows.append({"entry": e, "lane": lane, "overall": ov["summary"]["overall"]})
            gnani_invalid += s.invalid
        gnani_real_rows = [{"run": r, "s": summarise_realspeech(r)} for r in gnani_real.runs()]
        gnani_invalid += gnani_real.invalid
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"rows": rows, "invalid": store.invalid, "unusable": unusable, "results_dir": _shown(store.results_dir),
             "real_rows": [{"run": r, "s": summarise_realspeech(r)} for r in real.runs()],
             "real_invalid": real.invalid, "real_dir": _shown(real.directory),
             "gnani_rows": gnani_rows, "gnani_real_rows": gnani_real_rows, "gnani_invalid": gnani_invalid,
             "gnani_dir": _shown(gnani)},
        )

    @app.get("/api/clips")
    def api_clips():
        """The 50 benchmark scenarios with the stored baseline transcript of each, for the live console."""
        featured = featured_runs(store)
        if not featured:
            return {"baseline": {}, "clips": []}
        any_entry = featured.get("auto") or next(iter(featured.values()))
        scenarios, _ = store.scenarios_for(any_entry.manifest)
        baseline = {}
        for policy, e in featured.items():
            results = {r.scenario_id: r for r in e.manifest.results}
            baseline[policy] = {"run_id": e.run_id, "asr_model": e.manifest.asr_model,
                                "asr_model_version": e.manifest.asr_model_version, "results": results}
        clips = []
        for s in scenarios:
            item = {"id": s.id, "language": s.language.value, "domain": s.domain.value,
                    "condition": s.condition.value, "reference": s.reference,
                    "expected_intent": s.expected_intent, "expected_slots": s.expected_slots,
                    "audio": f"/audio/{s.id}.wav" if (audio_dir / f"{s.id}.wav").is_file() else None,
                    "baseline": {}}
            for policy, b in baseline.items():
                r = b["results"].get(s.id)
                if r is not None:
                    item["baseline"][policy] = {
                        "transcript": r.transcript, "detected_language": r.detected_language,
                        "predicted_intent": r.predicted_intent, "predicted_slots": r.predicted_slots,
                        "task_success": r.task_success, "wer": r.wer, "latency_ms": r.latency_ms,
                        "error": r.error}
            clips.append(item)
        return {"baseline": {p: {k: v for k, v in b.items() if k != "results"} for p, b in baseline.items()},
                "clips": clips}

    @app.post("/api/analyze")
    async def api_analyze(request: Request):
        """Text only: intent, slots and WER for a browser transcript. Nothing is stored or logged."""
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
            raise HTTPException(413, f"request body over {MAX_BODY_BYTES} bytes")
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, f"request body over {MAX_BODY_BYTES} bytes")
        try:
            req = AnalyzeRequest.model_validate_json(body)
        except ValidationError as e:
            # Report what was wrong, never echo the submitted text back.
            detail = [{"field": ".".join(str(x) for x in err["loc"]), "error": err["msg"]} for err in e.errors()]
            return JSONResponse({"detail": detail}, status_code=422, headers={"Cache-Control": "no-store"})
        scenario = None
        if req.scenario_id is not None:
            featured = featured_runs(store)
            if featured:
                scenarios, _ = store.scenarios_for(next(iter(featured.values())).manifest)
                scenario = next((s for s in scenarios if s.id == req.scenario_id), None)
            if scenario is None:
                raise HTTPException(404, f"no scenario {req.scenario_id!r}")
        return JSONResponse(analyze(req, scenario), headers={"Cache-Control": "no-store"})

    @app.get("/realspeech/{run_id}", response_class=HTMLResponse)
    def realspeech_page(request: Request, run_id: str, sort: str = Query("wer")):
        run = real.get(run_id) or gnani_real.get(run_id)
        if run is None:
            raise HTTPException(404, f"no real-speech run {run_id!r}")
        clips = list(run.results)
        if sort == "wer":
            clips.sort(key=lambda r: (r.wer is None, -(r.wer or 0)))
        return TEMPLATES.TemplateResponse(
            request, "realspeech.html",
            {"m": run, "s": summarise_realspeech(run), "b": word_error_breakdown(run),
             "external_api": external_provider(run.asr_config), "comparability": COMPARABILITY,
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
        entry, owner, gnani_lane = _find(run_id)
        language = language if language in LANGUAGES else None
        condition = condition if condition in CONDITIONS else None
        status = status if status in ("fail", "pass", "all") else "fail"
        try:
            ov = run_overview(entry, owner)
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
                # A round-trip run was not made from the committed audio, so it is not offered.
                "has_audio": audio_dir.is_dir() and gnani_lane != "roundtrip",
                "gnani_lane": gnani_lane,
                "external_api": external_provider(m.asr_config),
                "comparability": COMPARABILITY,
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

    @app.get("/api/gnani")
    def api_gnani():
        """External-API runs only (Gnani lane); /api/runs lists the local runs."""
        out = [{"run_id": e.run_id, "lane": lane, "created_at": e.manifest.created_at,
                "asr_model": e.manifest.asr_model, "language_policy": e.manifest.language_policy,
                "file": e.path.name, "external_api": external_provider(e.manifest.asr_config),
                "understander": e.manifest.understander or BUILTIN}
               for lane, s in gnani_stores.items() for e in s.runs()]
        out += [{"run_id": r.run_id, "lane": "realspeech", "created_at": r.created_at, "asr_model": r.asr_model,
                 "language_policy": r.language_policy, "external_api": external_provider(r.asr_config)}
                for r in gnani_real.runs()]
        return out

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
