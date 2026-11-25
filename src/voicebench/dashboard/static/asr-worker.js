// Whisper in a Web Worker with transformers.js (onnxruntime-web). Audio arrives as 16 kHz mono
// Float32 samples from the page and never leaves this browser: the worker makes no request other
// than fetching the library and the model files.
//
// Language: transformers.js 4.3.2 does not auto-detect; with no language it forces English. "auto"
// here lets the model choose the language token itself (see autoLanguageProcessor).

let T = null;          // the transformers.js module
let model = null;
let processor = null;
let device = null;
let langById = null;   // token id -> language code
let modelInfo = null;

const post = (msg) => self.postMessage(msg);
const errorMessage = (e) => (e && (e.message || String(e))) || "unknown error";

async function load({ tjs, repo, revision, backend }) {
  const t0 = performance.now();
  try {
    T = await import(tjs);
  } catch (e) {
    throw new Error(`Could not load transformers.js from ${tjs}: ${errorMessage(e)}`);
  }
  T.env.allowLocalModels = false;
  T.env.useBrowserCache = true;

  let gpu = false;
  if (backend === "auto") {
    try {
      gpu = !!(self.navigator.gpu && (await self.navigator.gpu.requestAdapter()));
    } catch (_) {
      gpu = false;
    }
    if (!gpu) post({ type: "notice", message: "WebGPU is not available in this browser, so the model runs on WASM (CPU)." });
  }

  const progress_callback = (p) => {
    if (p && (p.status === "progress" || p.status === "initiate" || p.status === "done" || p.status === "download")) {
      post({ type: "progress", status: p.status, file: p.file, loaded: p.loaded ?? null, total: p.total ?? null });
    }
  };
  const common = { revision, dtype: "q8", progress_callback };
  model = null;
  if (gpu) {
    try {
      model = await T.AutoModelForSpeechSeq2Seq.from_pretrained(repo, { ...common, device: "webgpu" });
      device = "webgpu";
    } catch (e) {
      post({ type: "notice", message: `WebGPU failed to start (${errorMessage(e)}); falling back to WASM (CPU).` });
      model = null;
    }
  }
  if (!model) {
    model = await T.AutoModelForSpeechSeq2Seq.from_pretrained(repo, { ...common, device: "wasm" });
    device = "wasm";
  }
  processor = await T.AutoProcessor.from_pretrained(repo, { revision, progress_callback });
  const l2i = model.generation_config.lang_to_id || {};
  langById = new Map(Object.entries(l2i).map(([tok, id]) => [Number(id), tok.replace(/^<\|/, "").replace(/\|>$/, "")]));
  modelInfo = { repo, revision, dtype: "q8", device };
  post({ type: "ready", ...modelInfo, loadMs: performance.now() - t0 });
}

// "auto": one generate() pass whose first step may only pick a language token (Whisper's
// detect_language rule, with the probability over language tokens recorded), and whose next two
// steps are forced to <|transcribe|><|notimestamps|>, exactly the prompt a language hint gives.
function autoLanguageProcessor(T, cfg, langIds, out) {
  const keep = new Set(langIds);
  const transcribe = cfg.task_to_id && cfg.task_to_id.transcribe;
  const noTs = cfg.no_timestamps_token_id;
  // With a hint, generate() suppresses these at the first text position; do the same here.
  const beginSuppress = (cfg.begin_suppress_tokens || []).map(Number);
  // Force one token. It must be set finite: Whisper's suppress_tokens already masks the task tokens.
  const force = (d, id) => { for (let j = 0; j < d.length; ++j) d[j] = j === id ? 0 : -Infinity; };
  return new (class extends T.LogitsProcessor {
    _call(input_ids, logits) {
      for (let i = 0; i < input_ids.length; ++i) {
        const d = logits[i].data;
        const step = input_ids[i].length;
        if (step === 1) {
          let best = -1, bestV = -Infinity;
          for (const id of keep) if (d[id] > bestV) { bestV = d[id]; best = id; }
          let sum = 0;
          for (const id of keep) sum += Math.exp(d[id] - bestV);
          out.id = best;
          out.prob = 1 / sum;
          force(d, best);
        } else if (step === 2 && transcribe != null) {
          force(d, Number(transcribe));
        } else if (step === 3 && noTs != null) {
          force(d, Number(noTs));
        } else if (step === 4) {
          for (const id of beginSuppress) d[id] = -Infinity;
        }
      }
      return logits;
    }
  })();
}

async function transcribe({ id, audio, language }) {
  if (!model) throw new Error("The model is not loaded.");
  const t0 = performance.now();
  const inputs = await processor(audio);
  const tFeat = performance.now();
  const hint = language === "hi" || language === "en" ? language : null;
  const cfg = model.generation_config;
  let seq;
  const found = {};
  if (hint) {
    seq = await model.generate({ ...inputs, language: hint, task: "transcribe", max_new_tokens: 440 });
  } else {
    const procs = new T.LogitsProcessorList();
    procs.push(autoLanguageProcessor(T, cfg, [...langById.keys()], found));
    seq = await model.generate({ ...inputs, decoder_input_ids: [cfg.decoder_start_token_id], max_new_tokens: 443, logits_processor: procs });
  }
  const genMs = performance.now() - tFeat;
  const ids = Array.from(seq.tolist()[0], Number);
  const lang = hint || langById.get(ids[1]) || null;
  if (!lang) throw new Error("Language detection returned no language token.");
  const text = processor.tokenizer.decode(ids, { skip_special_tokens: true }).trim();
  post({
    type: "result", id, text, language: lang, languageProb: hint ? null : found.prob ?? null, languageMode: language,
    featureMs: tFeat - t0, generateMs: genMs, totalMs: performance.now() - t0, ...modelInfo,
  });
}

self.onmessage = async ({ data }) => {
  try {
    if (data.type === "load") await load(data);
    else if (data.type === "transcribe") await transcribe(data);
  } catch (e) {
    post({ type: "error", stage: data.type, message: errorMessage(e), stack: e && e.stack ? String(e.stack).slice(0, 1200) : "" });
  }
};
