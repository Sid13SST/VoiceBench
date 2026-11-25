"""usage: python analyse.py <dir with meas-<model>.json> <model>...

Score browser-Whisper measurements with the project's own WER code; compare with the stored run on the same clips."""
import json, statistics, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from voicebench.analysis import has_repetition_loop
from voicebench.metrics import corpus_wer, percentile

S = sys.argv[1]
stored = json.load(open(REPO / "results/realspeech/20261031T200244Z-faster-whisper-small-realspeech-fleurs-hi_in-auto-rescored-9336d77.json"))
by_id = {r["clip_id"]: r for r in stored["results"]}
rows = []
for m in sys.argv[2:]:
    d = json.load(open(f"{S}/meas-{m}.json"))
    clips = d["clips"]
    ok = [c for c in clips if c["error"] is None]
    ms = [c["total_ms"] for c in ok]
    rtf = [c["total_ms"] / 1000 / c["audio_s"] for c in ok]
    ids = [c["clip_id"] for c in clips]
    rows.append({
        "system": f"{d['model']} q8, browser WASM ({d['browser']['cores']} cores, isolated={d['browser']['coi']})",
        "n": len(clips), "errors": len(clips) - len(ok),
        "corpus_wer": round(corpus_wer((c["reference"], c["transcript"] or "") for c in clips), 3),
        "detected_hi": sum(c["language"] == "hi" for c in ok),
        "loops": sum(has_repetition_loop(c["transcript"] or "") for c in ok),
        "p50_ms": round(percentile(ms, 50)), "p95_ms": round(percentile(ms, 95)),
        "rtf_p50": round(percentile(rtf, 50), 2), "rtf_p95": round(percentile(rtf, 95), 2),
        "load_ms": round(d["load_ms"]),
    })
base = [by_id[i] for i in ids]
rows.append({
    "system": f"stored run {stored['run_id']} ({stored['asr_model']}, CTranslate2 int8, server CPU)",
    "n": len(base), "errors": sum(r["error"] is not None for r in base),
    "corpus_wer": round(corpus_wer((r["reference"], r["transcript"] or "") for r in base), 3),
    "detected_hi": sum(r["detected_language"] == "hi" for r in base),
    "loops": sum(has_repetition_loop(r["transcript"] or "") for r in base),
    "p50_ms": round(percentile([r["latency_ms"] for r in base], 50)), "p95_ms": round(percentile([r["latency_ms"] for r in base], 95)),
    "rtf_p50": None, "rtf_p95": None, "load_ms": None,
})
print(json.dumps({"clips": ids, "rows": rows}, indent=1, ensure_ascii=False))
