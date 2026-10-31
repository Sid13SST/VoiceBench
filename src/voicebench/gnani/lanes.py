"""The Gnani lanes: which items a run sends, the dry-run plan, and the run itself.

- ``synthetic``: Prisma on the committed espeak-ng audio (``audio/v1``),
  through ``runner.run()`` unchanged; a standard run file.
- ``realspeech``: Prisma on FLEURS Hindi clips from the dev half of the
  committed split, through ``realspeech.run_realspeech()`` unchanged; a
  real-speech run file.
- ``roundtrip``: Timbre speaks scenario references, Prisma transcribes them,
  through ``runner.run()``; a standard run file plus an audio manifest.

Each lane sends at most ``max_requests`` billable requests. The two
recognition lanes spend one of them on the untimed warm-up call that
``runner.run()`` and ``run_realspeech()`` always make, so they send
``max_requests - 1`` items; the round trip needs two requests per item and
has no warm-up.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Optional

from voicebench.gnani import COMPARABILITY, MAX_CLIP_S, PROVIDER
from voicebench.loader import file_sha256
from voicebench.schema import RunManifest, Scenario

LANES = ("synthetic", "realspeech")
RESULTS_DIR = "results/gnani"
DEFAULT_OUT = {
    "synthetic": f"{RESULTS_DIR}/synthetic",
    "realspeech": f"{RESULTS_DIR}/realspeech",
    "roundtrip": f"{RESULTS_DIR}/roundtrip",
}


def items_for(lane: str, max_requests: int) -> int:
    """How many scenarios or clips fit in ``max_requests``."""
    n = max_requests // 2 if lane == "roundtrip" else max_requests - 1
    if n < 1:
        raise ValueError(f"--max-requests {max_requests} leaves no room for a single item in the {lane} lane "
                         "(it needs at least 2)")
    return n


def pick_scenarios(scenarios: list[Scenario], n: int, ids: Optional[list[str]] = None) -> list[Scenario]:
    """``ids`` in file order, else ``n`` scenarios taken in turn from each language x condition cell.

    Cells are visited in a fixed order (en, hi, hi-en by clean, noise,
    interruption) and scenarios within a cell by id, so a small budget
    still spreads over the languages and conditions, and the same ``n``
    always gives the same subset.
    """
    if ids:
        known = {s.id for s in scenarios}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise ValueError(f"unknown scenario ids: {', '.join(unknown)}")
        picked = [s for s in scenarios if s.id in set(ids)]
        if len(picked) > n:
            raise ValueError(f"{len(picked)} scenarios asked for, but the request cap allows {n}")
        return picked
    cells: dict[tuple[str, str], list[Scenario]] = defaultdict(list)
    for s in sorted(scenarios, key=lambda s: s.id):
        cells[(s.language.value, s.condition.value)].append(s)
    order = [(lang, cond) for lang in ("en", "hi", "hi-en") for cond in ("clean", "noise", "interruption")]
    order += sorted(k for k in cells if k not in order)
    picked: list[Scenario] = []
    depth = 0
    while len(picked) < n and any(len(cells[k]) > depth for k in order):
        for k in order:
            if len(picked) < n and len(cells[k]) > depth:
                picked.append(cells[k][depth])
        depth += 1
    return sorted(picked, key=lambda s: s.id)


def audio_durations(audio_dir: str | Path) -> dict[str, float]:
    """Scenario id -> duration from the audio manifest (no audio is read)."""
    m = json.loads((Path(audio_dir) / "manifest.json").read_text(encoding="utf-8"))
    return {f["id"]: float(f["duration_s"]) for f in m["files"]}


def realspeech_subset(manifest: dict[str, Any], split: dict[str, list[str]], n: int,
                      manifest_file: str, ids: Optional[list[str]] = None) -> dict[str, Any]:
    """A real-speech manifest holding ``n`` dev clips (by id) of at most 30 s, or the clips ``ids``."""
    by_id = {c["id"]: c for c in manifest["clips"]}
    dev = set(split["dev"])
    if ids:
        unknown = [i for i in ids if i not in by_id]
        if unknown:
            raise ValueError(f"unknown clip ids: {', '.join(unknown)}")
        held = [i for i in ids if i not in dev]
        if held:
            raise ValueError(f"not dev clips (the held-out half is not used here): {', '.join(held)}")
        if len(ids) > n:
            raise ValueError(f"{len(ids)} clips asked for, but the request cap allows {n}")
        chosen = sorted(set(ids))
    else:
        chosen = [i for i in sorted(dev) if by_id[i]["num_samples"] / 16000 <= MAX_CLIP_S][:n]
    too_long = [i for i in chosen if by_id[i]["num_samples"] / 16000 > MAX_CLIP_S]
    if too_long:
        raise ValueError(f"over the {MAX_CLIP_S:.0f} s REST STT limit: {', '.join(too_long)}")
    return {
        **{k: v for k, v in manifest.items() if k != "clips"},
        "subset": {
            "of": manifest_file,
            "of_sha256": file_sha256(manifest_file),
            "split": "dev",
            "method": "the given clip ids" if ids else
                      f"the first {n} dev clip ids (sorted) of at most {MAX_CLIP_S:.0f} s",
            "n": len(chosen),
        },
        "clips": [by_id[i] for i in chosen],
    }


def subset_path(out_dir: str | Path, subset: dict[str, Any]) -> Path:
    """Content-addressed file name, so the same subset is written once and a different one never overwrites it."""
    body = json.dumps(subset, ensure_ascii=False, indent=1) + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    return Path(out_dir) / "manifests" / f"fleurs_{subset['dataset']['config']}_dev_{subset['subset']['n']}_{digest}.json"


def write_subset(out_dir: str | Path, subset: dict[str, Any]) -> Path:
    path = subset_path(out_dir, subset)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(subset, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def plan_text(lane: str, items: list[tuple[str, float]], requests: int, max_requests: int,
              extra: str = "") -> str:
    audio = sum(d for _, d in items)
    lines = [f"gnani {lane}: DRY RUN, nothing sent.",
             f"would send {requests} billable requests (cap {max_requests}) for {len(items)} items"
             + (f", {audio:.1f} s of audio" if audio else "") + f"{extra}:"]
    lines += [f"  {i}  {d:.1f} s" if d else f"  {i}" for i, d in items]
    lines.append("Run again with --live and GNANI_API_KEY set in the environment to call the API.")
    return "\n".join(lines)


def label_run(m: RunManifest, lane: str, total_scenarios: int) -> RunManifest:
    """Mark a standard run file as an external-API run in its ``notes``."""
    what = ("Gnani Timbre TTS + Prisma STT round trip (measures both services together)"
            if lane == "roundtrip" else "Gnani Prisma STT on the committed synthetic audio")
    note = (f"EXTERNAL API RUN ({PROVIDER}): {what}. {len(m.results)} of {total_scenarios} scenarios. "
            f"{COMPARABILITY}. Latency includes the network round trip. Results depend on a remote service "
            "and are not bit-reproducible.")
    return m.model_copy(update={"notes": note})


def run_synthetic(transcriber: Any, scenarios: list[Scenario], total: int, audio_dir: str, scenarios_file: str,
                  command: str, language_policy: str,
                  progress: Optional[Callable[[str], None]] = None) -> RunManifest:
    from voicebench.runner import run

    m = run(scenarios, audio_dir, transcriber, scenarios_file, command,
            language_policy=language_policy, progress=progress)
    return label_run(m, "synthetic", total)


def run_roundtrip(transcriber: Any, scenarios: list[Scenario], total: int, scenarios_file: str, command: str,
                  progress: Optional[Callable[[str], None]] = None) -> RunManifest:
    from voicebench.runner import run

    # transcribe_scenario is used, so no audio directory is read and there is no warm-up call.
    m = run(scenarios, transcriber.cache_dir, transcriber, scenarios_file, command,
            language_policy="hint", progress=progress)
    m = m.model_copy(update={"tts_engine": f"{PROVIDER} {transcriber.tts_model} (external API)"})
    return label_run(m, "roundtrip", total)


def save_roundtrip_audio_manifest(transcriber: Any, run_path: Path) -> Path:
    path = run_path.parent / "audio-manifests" / run_path.name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(transcriber.audio_manifest(run_path.stem), ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return path
