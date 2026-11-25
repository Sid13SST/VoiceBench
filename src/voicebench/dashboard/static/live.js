// Live test console. Audio is decoded and transcribed in this browser (asr-worker.js) and never
// uploaded. Only the text transcript (and an optional reference sentence) is POSTed to /api/analyze.
// Transcripts, references and API answers are untrusted text: they are only ever set with
// textContent, never as HTML.

const $ = (id) => document.getElementById(id);
const consoleEl = $("console");
if (consoleEl) init();

function init() {
  const MODELS = JSON.parse(consoleEl.dataset.models);
  const TJS = consoleEl.dataset.tjs;
  const MAX_CHARS = Number(consoleEl.dataset.maxChars) || 2000;
  const MAX_SECONDS = 30;
  const MAX_BYTES = 10 * 1024 * 1024;
  const SAMPLE_RATE = 16000;
  const CACHE_NAME = "transformers-cache";
  const FILE_TYPES = ["wav", "mp3", "m4a", "webm", "ogg"];

  const st = {
    model: MODELS.find((m) => m.key === "base") || MODELS[0],
    worker: null, loaded: null, loading: null, busy: false,
    audio: null, clips: [], baselineRuns: {}, pendingRun: false, runId: 0, recorder: null,
  };

  // ---------------------------------------------------------------- helpers
  const el = (tag, props = {}, text) => {
    const n = document.createElement(tag);
    Object.assign(n, props);
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const fmtMs = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`);
  const mb = (b) => `${(b / 1e6).toFixed(1)} MB`;
  const setStatus = (node, text, spin = false) => {
    node.replaceChildren();
    if (spin) node.append(el("span", { className: "spin" }));
    if (text) node.append(el("span", {}, text));
  };
  const fileUrl = (m, file) => `https://huggingface.co/${m.repo}/resolve/${m.revision}/${file}`;

  function showError(title, detail, retry) {
    $("error-title").textContent = title;
    $("error-detail").textContent = detail || "";
    $("error-detail").hidden = !detail;
    $("error").hidden = false;
    const btn = $("retry-btn");
    btn.hidden = !retry;
    btn.onclick = () => { hideError(); retry && retry(); };
  }
  const hideError = () => { $("error").hidden = true; };

  // ---------------------------------------------------------------- model picker
  async function cachedState(m) {
    try {
      if (!("caches" in self)) return null;
      const c = await caches.open(CACHE_NAME);
      const files = ["onnx/encoder_model_quantized.onnx", "onnx/decoder_model_merged_quantized.onnx"];
      const hits = await Promise.all(files.map((f) => c.match(fileUrl(m, f))));
      return hits.every(Boolean);
    } catch (_) {
      return null;
    }
  }

  async function renderModelMeta() {
    const m = st.model;
    const box = $("model-meta");
    box.replaceChildren();
    const repoLink = el("a", { href: `https://huggingface.co/${m.repo}/tree/${m.revision}`, target: "_blank", rel: "noopener" }, m.repo);
    const rev = el("code", {}, m.revision.slice(0, 12));
    box.append(repoLink, " @ ", rev, ` · q8 encoder + merged decoder ≈ ${m.mb} MB download`);
    box.append(el("br"));
    const up = el("a", { href: `https://huggingface.co/${m.upstream}/tree/${m.upstream_revision}`, target: "_blank", rel: "noopener" }, m.upstream);
    if (m.card_license) box.append(`Model card licence: ${m.card_license}. Converted from `, up, " (Apache-2.0).");
    else box.append("The ONNX model card declares no licence. Converted from ", up, ", whose card says Apache-2.0.");
    const cached = await cachedState(m);
    if (m !== st.model) return;
    box.append(el("br"), cached === true ? "Cached in this browser: loading will not download it again." :
      cached === false ? "Not cached yet: the first load downloads it from Hugging Face." : "");
  }

  document.querySelectorAll("#model-seg [data-model]").forEach((b) => {
    b.addEventListener("click", () => {
      if (st.loading) return;
      document.querySelectorAll("#model-seg [data-model]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      st.model = MODELS.find((m) => m.key === b.dataset.model);
      renderModelMeta();
      updateLoadedLabel();
    });
  });
  $("backend").addEventListener("change", updateLoadedLabel);

  function updateLoadedLabel() {
    const want = `${st.model.key}/${$("backend").value}`;
    if (st.loaded && st.loaded.key === want) {
      setStatus($("load-status"), `whisper-${st.model.key} is loaded (${st.loaded.device}).`);
      $("load-btn").textContent = "Reload model";
    } else {
      $("load-btn").textContent = st.loaded ? `Load whisper-${st.model.key}` : "Load model";
      if (!st.loading) setStatus($("load-status"), st.loaded ? `Loaded: ${st.loaded.key.replace("/", " on ")}. Pick Load to switch.` : "");
    }
    refreshRunButton();
  }

  $("clear-cache-btn").addEventListener("click", async () => {
    try {
      const names = await caches.keys();
      await Promise.all(names.filter((n) => n.startsWith("transformers")).map((n) => caches.delete(n)));
      setStatus($("load-status"), "Deleted the cached model files from this browser.");
    } catch (e) {
      showError("Could not clear the cache", String(e && e.message || e));
    }
    renderModelMeta();
  });

  // ---------------------------------------------------------------- worker
  function newWorker() {
    if (st.worker) st.worker.terminate();
    st.worker = new Worker("/static/asr-worker.js", { type: "module" });
    st.worker.onmessage = onWorkerMessage;
    st.worker.onerror = (e) => {
      const msg = e.message || "the worker failed to start";
      finishLoading();
      endRun();
      showError("The speech model stopped with an error", msg, () => loadModel());
    };
    st.loaded = null;
    return st.worker;
  }

  function loadModel() {
    hideError();
    const m = st.model;
    const backend = $("backend").value;
    st.loading = { key: `${m.key}/${backend}`, files: new Map(), t0: performance.now() };
    newWorker().postMessage({ type: "load", tjs: TJS, repo: m.repo, revision: m.revision, backend });
    $("load-progress").hidden = false;
    $("load-progress").firstElementChild.style.width = "0%";
    setStatus($("load-status"), `Loading whisper-${m.key}…`, true);
    $("load-btn").disabled = true;
    $("cancel-btn").hidden = false;
    document.querySelectorAll("#model-seg button").forEach((b) => (b.disabled = true));
    refreshRunButton();
  }
  $("load-btn").addEventListener("click", loadModel);

  function finishLoading() {
    st.loading = null;
    $("load-btn").disabled = false;
    $("load-progress").hidden = true;
    document.querySelectorAll("#model-seg button").forEach((b) => (b.disabled = false));
    if (!st.busy) $("cancel-btn").hidden = true;
  }

  function onWorkerMessage({ data }) {
    if (data.type === "progress" && st.loading) {
      if (data.file && data.total) st.loading.files.set(data.file, { loaded: data.loaded || 0, total: data.total });
      let loaded = 0, total = 0;
      for (const f of st.loading.files.values()) { loaded += f.loaded; total += f.total; }
      if (total) {
        $("load-progress").firstElementChild.style.width = `${Math.min(100, (100 * loaded) / total).toFixed(1)}%`;
        setStatus($("load-status"), `Downloading or reading cache: ${mb(loaded)} of ${mb(total)}`, true);
      }
    } else if (data.type === "notice") {
      st.notice = data.message;
    } else if (data.type === "ready") {
      const key = st.loading ? st.loading.key : `${st.model.key}/${$("backend").value}`;
      st.loaded = { key, device: data.device, repo: data.repo, revision: data.revision, loadMs: data.loadMs };
      finishLoading();
      setStatus($("load-status"), `whisper-${key.split("/")[0]} ready on ${data.device === "webgpu" ? "WebGPU" : "WASM (CPU)"} in ${fmtMs(data.loadMs)} (download or cache read, plus session start).${st.notice ? ` ${st.notice}` : ""}`);
      st.notice = null;
      $("load-btn").textContent = "Reload model";
      renderModelMeta();
      refreshRunButton();
      if (st.pendingRun) { st.pendingRun = false; runTranscription(); }
    } else if (data.type === "result") {
      if (data.id !== st.runId) return;
      onTranscript(data);
    } else if (data.type === "error") {
      const wasLoading = data.stage === "load";
      finishLoading();
      endRun();
      st.pendingRun = false;
      if (wasLoading) {
        st.loaded = null;
        showError(`Could not load whisper-${st.model.key}`, data.message, () => loadModel());
      } else {
        showError("Transcription failed", data.message, () => runTranscription());
      }
    }
  }

  $("cancel-btn").addEventListener("click", () => {
    const what = st.loading ? "Model loading" : "Transcription";
    if (st.worker) st.worker.terminate();
    st.worker = null;
    st.loaded = null;
    st.pendingRun = false;
    finishLoading();
    endRun();
    $("cancel-btn").hidden = true;
    setStatus($("load-status"), "");
    showError(`${what} cancelled`, "The model was unloaded. Files that finished downloading stay cached.", () => loadModel());
    updateLoadedLabel();
  });

  // ---------------------------------------------------------------- audio input
  async function decodeToMono16k(arrayBuffer) {
    const Ctx = self.AudioContext || self.webkitAudioContext;
    if (!Ctx) throw new Error("This browser has no Web Audio API, so it cannot decode audio.");
    const ctx = new Ctx();
    let decoded;
    try {
      decoded = await ctx.decodeAudioData(arrayBuffer);
    } finally {
      ctx.close();
    }
    if (decoded.duration > MAX_SECONDS + 0.05) {
      const e = new Error(`The audio is ${decoded.duration.toFixed(1)} s long; the limit is ${MAX_SECONDS} s.`);
      e.limit = true;
      throw e;
    }
    if (decoded.duration < 0.1) throw new Error("The audio is shorter than 0.1 s.");
    const frames = Math.ceil(decoded.duration * SAMPLE_RATE);
    const off = new OfflineAudioContext(1, frames, SAMPLE_RATE);
    const src = off.createBufferSource();
    src.buffer = decoded;
    src.connect(off.destination);
    src.start();
    const out = await off.startRendering();
    return { samples: out.getChannelData(0), duration: decoded.duration };
  }

  function drawScope(samples) {
    const c = $("scope");
    const g = c.getContext("2d");
    const w = (c.width = c.clientWidth * (devicePixelRatio || 1));
    const h = (c.height = 64 * (devicePixelRatio || 1));
    g.clearRect(0, 0, w, h);
    if (!samples) return;
    const step = Math.max(1, Math.floor(samples.length / w));
    let peak = 0;
    for (let i = 0; i < samples.length; i += 4) peak = Math.max(peak, Math.abs(samples[i]));
    peak = peak || 1;
    g.fillStyle = "#2ec4b6";
    for (let x = 0; x < w; x++) {
      let m = 0;
      for (let i = x * step, e = Math.min(samples.length, i + step); i < e; i++) m = Math.max(m, Math.abs(samples[i]));
      const bh = Math.max(1, (m / peak) * (h - 6));
      g.fillRect(x, (h - bh) / 2, 1, bh);
    }
  }

  async function setAudio(blob, source, name, clip = null) {
    hideError();
    clearResult();
    setStatus($("audio-info"), "Decoding audio in your browser…", true);
    try {
      const { samples, duration } = await decodeToMono16k(await blob.arrayBuffer());
      st.audio = { samples, duration, source, name, clip };
      drawScope(samples);
      const prev = $("audio-preview");
      if (prev.src) URL.revokeObjectURL(prev.src);
      prev.src = URL.createObjectURL(blob);
      prev.hidden = false;
      setStatus($("audio-info"), `${name} · ${duration.toFixed(2)} s · resampled to 16 kHz mono in your browser`);
      refreshRunButton();
      return true;
    } catch (e) {
      st.audio = null;
      drawScope(null);
      $("audio-preview").hidden = true;
      setStatus($("audio-info"), "");
      const msg = e && e.message ? e.message : String(e);
      if (e && e.limit) showError("Audio over the limit", msg);
      else showError("This audio could not be decoded",
        `${msg}\nBrowsers decode different formats: WAV and MP3 work everywhere; m4a (AAC) is missing from some builds, e.g. Chromium without proprietary codecs. Try WAV or MP3.`);
      refreshRunButton();
      return false;
    }
  }

  $("file-input").addEventListener("change", async (ev) => {
    const f = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (!f) return;
    const ext = (f.name.split(".").pop() || "").toLowerCase();
    if (!FILE_TYPES.includes(ext)) {
      showError("Unsupported file type", `"${f.name}" is not one of: ${FILE_TYPES.join(", ")}.`);
      return;
    }
    if (f.size > MAX_BYTES) {
      showError("File over the limit", `"${f.name}" is ${mb(f.size)}; the limit is 10 MB.`);
      return;
    }
    $("compare").hidden = true;
    if (await setAudio(f, "file", f.name)) maybeAutoDomain(null);
  });

  // Microphone
  $("rec-btn").addEventListener("click", async () => {
    if (st.recorder) { st.recorder.stop(); return; }
    hideError();
    let stream;
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw Object.assign(new Error("This browser does not expose a microphone API (it needs HTTPS)."), { name: "NotSupportedError" });
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: false } });
    } catch (e) {
      const denied = e && (e.name === "NotAllowedError" || e.name === "SecurityError");
      const none = e && (e.name === "NotFoundError" || e.name === "OverconstrainedError");
      showError(denied ? "Microphone permission denied" : none ? "No microphone found" : "Could not open the microphone",
        denied ? "Allow microphone access for this site in the browser's address bar, then retry." : String(e && e.message || e),
        () => $("rec-btn").click());
      return;
    }
    if (typeof MediaRecorder === "undefined") {
      stream.getTracks().forEach((t) => t.stop());
      showError("Recording is not supported", "This browser has no MediaRecorder. Upload a file instead.");
      return;
    }
    const chunks = [];
    const rec = new MediaRecorder(stream);
    const ctx = new (self.AudioContext || self.webkitAudioContext)();
    const an = ctx.createAnalyser();
    an.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Float32Array(an.fftSize);
    const t0 = performance.now();
    let raf = 0;
    const tick = () => {
      an.getFloatTimeDomainData(buf);
      let s = 0;
      for (const v of buf) s += v * v;
      const rms = Math.sqrt(s / buf.length);
      $("rec-level").style.width = `${Math.min(100, rms * 400).toFixed(0)}%`;
      const secs = (performance.now() - t0) / 1000;
      $("rec-timer").textContent = `${secs.toFixed(1)} s / ${MAX_SECONDS} s`;
      if (secs >= MAX_SECONDS - 0.2 && rec.state === "recording") rec.stop();
      raf = requestAnimationFrame(tick);
    };
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = async () => {
      cancelAnimationFrame(raf);
      stream.getTracks().forEach((t) => t.stop());
      ctx.close();
      st.recorder = null;
      $("rec-btn").classList.remove("recording");
      $("rec-btn").lastElementChild.textContent = "Record";
      $("rec-level").style.width = "0%";
      $("compare").hidden = true;
      const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
      if (await setAudio(blob, "mic", "microphone recording")) maybeAutoDomain(null);
    };
    st.recorder = rec;
    rec.start();
    $("rec-btn").classList.add("recording");
    $("rec-btn").lastElementChild.textContent = "Stop";
    tick();
  });

  // Benchmark clips
  async function loadClips() {
    const sel = $("clip-select");
    try {
      const r = await fetch("/api/clips");
      if (!r.ok) throw new Error(`/api/clips answered ${r.status}`);
      const data = await r.json();
      st.clips = data.clips;
      st.baselineRuns = data.baseline;
      sel.replaceChildren();
      for (const c of st.clips) {
        if (!c.audio) continue;
        const ref = c.reference.length > 48 ? `${c.reference.slice(0, 47)}…` : c.reference;
        sel.append(el("option", { value: c.id }, `${c.id} · ${c.language} · ${c.condition} · ${ref}`));
      }
      if (!sel.options.length) sel.append(el("option", { value: "" }, "no benchmark audio on this deployment"));
    } catch (e) {
      sel.replaceChildren(el("option", { value: "" }, "could not load the clip list"));
    }
  }
  $("clip-btn").addEventListener("click", async () => {
    const c = st.clips.find((x) => x.id === $("clip-select").value);
    if (!c) return;
    hideError();
    setStatus($("audio-info"), `Fetching ${c.id}.wav from this site…`, true);
    let blob;
    try {
      const r = await fetch(c.audio);
      if (!r.ok) throw new Error(`${c.audio} answered ${r.status}`);
      blob = await r.blob();
    } catch (e) {
      setStatus($("audio-info"), "");
      showError("Could not fetch the benchmark clip", String(e && e.message || e), () => $("clip-btn").click());
      return;
    }
    if (!(await setAudio(blob, "clip", `benchmark clip ${c.id} (${c.language}, ${c.condition})`, c))) return;
    $("reference").value = c.reference;
    maybeAutoDomain(c);
    runTranscription();
  });

  function maybeAutoDomain(clip) {
    if (clip) $("domain").value = clip.domain;
    $("domain").disabled = !!clip;
    $("domain").title = clip ? "Set by the benchmark scenario" : "";
  }

  // ---------------------------------------------------------------- run
  function refreshRunButton() {
    $("run-btn").disabled = !st.audio || st.busy || !!st.loading;
  }

  function endRun() {
    st.busy = false;
    if (!st.loading) $("cancel-btn").hidden = true;
    refreshRunButton();
  }

  function clearResult() {
    $("out-transcript").textContent = "No result yet. Nothing is pre-filled: this box only shows a transcript your browser produced.";
    $("out-transcript").classList.add("empty");
    for (const id of ["f-lang", "f-latency", "f-rtf", "f-intent", "f-slots", "f-wer"]) $(id).textContent = "-";
    $("result-tags").replaceChildren();
    $("compare").hidden = true;
    $("result-note").textContent = "";
  }

  function runTranscription() {
    if (!st.audio) return;
    hideError();
    const want = `${st.model.key}/${$("backend").value}`;
    if (!st.loaded || st.loaded.key !== want) {
      st.pendingRun = true;
      if (!st.loading) loadModel();
      setStatus($("run-status"), "Loading the model first…", true);
      return;
    }
    clearResult();
    st.busy = true;
    st.runId += 1;
    $("cancel-btn").hidden = false;
    refreshRunButton();
    setStatus($("run-status"), `Transcribing ${st.audio.duration.toFixed(1)} s of audio on your device…`, true);
    const copy = st.audio.samples.slice();
    st.worker.postMessage({ type: "transcribe", id: st.runId, audio: copy, language: $("lang").value }, [copy.buffer]);
  }
  $("run-btn").addEventListener("click", runTranscription);

  async function onTranscript(r) {
    const a = st.audio;
    let text = r.text || "";
    let truncated = false;
    if (text.length > MAX_CHARS) { text = text.slice(0, MAX_CHARS); truncated = true; }
    const box = $("out-transcript");
    box.classList.toggle("empty", !text);
    box.textContent = text || "(empty transcript)";
    const langLabel = r.languageMode === "auto" ? `${r.language}${r.languageProb != null ? ` (p ${r.languageProb.toFixed(2)})` : ""}` : `${r.language} (hint)`;
    $("f-lang").textContent = langLabel;
    $("f-latency").textContent = fmtMs(r.totalMs);
    $("f-rtf").textContent = a ? (r.totalMs / 1000 / a.duration).toFixed(2) : "-";
    const tags = $("result-tags");
    tags.replaceChildren(
      el("span", { className: "pill accent" }, `whisper-${st.model.key} · q8 · ${r.device === "webgpu" ? "WebGPU" : "WASM"}`),
      el("span", { className: "pill" }, "fresh live run"),
    );
    $("result-note").textContent =
      `Timing on this device: audio features ${fmtMs(r.featureMs)}, encoder + decoding ${fmtMs(r.generateMs)}${r.languageMode === "auto" ? " (language detected in the same pass)" : ""}. Real-time factor = total ÷ audio length; below 1 is faster than real time. Model ${r.repo} @ ${String(r.revision).slice(0, 12)}.` +
      (truncated ? ` The transcript was cut to ${MAX_CHARS} characters before analysis.` : "");
    setStatus($("run-status"), "Scoring the text with the project's matcher…", true);

    const body = { transcript: text, domain: $("domain").value };
    const ref = $("reference").value.trim().slice(0, MAX_CHARS);
    if (ref) body.reference = ref;
    if (a && a.clip) body.scenario_id = a.clip.id;
    try {
      const resp = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const out = await resp.json().catch(() => null);
      if (!resp.ok) {
        const detail = out && out.detail ? (Array.isArray(out.detail) ? out.detail.map((d) => `${d.field}: ${d.error}`).join("\n") : String(out.detail)) : `HTTP ${resp.status}`;
        throw new Error(detail);
      }
      showAnalysis(out, r, text);
      setStatus($("run-status"), "Done.");
    } catch (e) {
      setStatus($("run-status"), "");
      showError("/api/analyze failed", String(e && e.message || e), () => onTranscript(r));
    } finally {
      endRun();
    }
  }

  function showAnalysis(out, r, text) {
    $("f-intent").textContent = out.intent || "none";
    const slots = Object.entries(out.slots || {});
    $("f-slots").textContent = slots.length ? slots.map(([k, v]) => `${k}=${v}`).join(", ") : "none";
    $("f-wer").textContent = out.wer != null ? out.wer.toFixed(2) : out.wer_note ? "n/a" : "no reference";
    const tags = $("result-tags");
    tags.append(el("span", { className: "pill" }, `domain ${out.domain}`), el("span", { className: "pill" }, `script ${out.transcript_script}`));
    if (out.scenario) {
      tags.append(el("span", { className: `pill ${out.scenario.task_success ? "good" : "bad"}` }, out.scenario.task_success ? "task success (live)" : "task failed (live)"));
    }
    const a = st.audio;
    if (!a || !a.clip) return;
    const policy = $("lang").value === "auto" ? "auto" : "hint";
    const base = a.clip.baseline[policy] || a.clip.baseline.auto;
    const run = st.baselineRuns[policy] || st.baselineRuns.auto;
    if (!base) return;
    $("compare").hidden = false;
    $("cmp-base-run").textContent = run ? `(${run.asr_model}, ${policy}, stored run)` : "";
    $("cmp-base").textContent = base.error ? `pipeline error: ${base.error}` : (base.transcript || "(empty)");
    const bslots = Object.entries(base.predicted_slots || {}).map(([k, v]) => `${k}=${v}`).join(", ") || "none";
    $("cmp-base-facts").textContent = `${base.task_success ? "task success" : "task failed"} · intent ${base.predicted_intent || "none"} · slots ${bslots} · WER ${base.wer != null ? base.wer.toFixed(2) : "-"} · detected ${base.detected_language || "-"}${base.latency_ms != null ? ` · ${Math.round(base.latency_ms)} ms on the benchmark CPU` : ""}`;
    $("cmp-live").textContent = text || "(empty)";
    const s = out.scenario;
    $("cmp-live-facts").textContent = `${s.task_success ? "task success" : "task failed"} · intent ${out.intent || "none"} (expected ${s.expected_intent}) · WER ${out.wer != null ? out.wer.toFixed(2) : "-"} · detected ${r.language} · ${fmtMs(r.totalMs)} on your device`;
  }

  // ---------------------------------------------------------------- start
  renderModelMeta();
  loadClips();
  drawScope(null);
  addEventListener("resize", () => st.audio && drawScope(st.audio.samples));
}
