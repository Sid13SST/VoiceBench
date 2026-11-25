// Run the dashboard's own static/asr-worker.js over FLEURS clips in headless Chromium and write
// per-clip JSON. Needs the dashboard running (uvicorn app:app --port 8765) and the clips fetched
// (make realspeech-fetch). Clips: the first N ids, sorted, of the committed dev split.
// usage: node measure.js <tiny|base|small> <n> <out.json> [language=auto] [cpuThrottle=1]
const { launch } = require('./harness');
const fs = require('fs');
const [model, n, outFile, language = 'auto', throttle = '1'] = process.argv.slice(2);
const MODELS = {
  tiny: ['onnx-community/whisper-tiny', 'ff4177021cc41f7db950912b73ea4fdf7d01d8e7'],
  base: ['onnx-community/whisper-base', '27a07b4b52b3a4c5886134bb4320e93e1a4bbc7c'],
  small: ['onnx-community/whisper-small', '36050c46d777d46dc4b5f43f6d90574fc38f8732'],
};
const path = require('path');
const REPO = path.resolve(__dirname, '..', '..');
const AUDIO = path.join(REPO, '.cache/realspeech/fleurs_hi_in_test');
const split = JSON.parse(fs.readFileSync(path.join(REPO, 'data/realspeech/fleurs_hi_in_test_150_split.json')));
const manifest = JSON.parse(fs.readFileSync(path.join(REPO, 'data/realspeech/fleurs_hi_in_test_150.json')));
const byId = Object.fromEntries(manifest.clips.map((c) => [c.id, c]));
const ids = [...split.dev].sort().slice(0, Number(n));
(async () => {
  const { browser, context } = await launch();
  await context.route('http://localhost:8765/__fleurs/**', (route) => {
    const id = route.request().url().split('/').pop();
    route.fulfill({ status: 200, body: fs.readFileSync(`${AUDIO}/${byId[id].file}`), headers: { 'content-type': 'audio/wav' } });
  });
  const page = await context.newPage();
  await page.goto('http://localhost:8765/');
  if (throttle !== '1') {
    const cdp = await context.newCDPSession(page);
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: Number(throttle) });
  }
  await page.evaluate(([repo, revision]) => new Promise((res, rej) => {
    window.__w = new Worker('/static/asr-worker.js', { type: 'module' });
    window.__w.onmessage = ({ data }) => { if (data.type === 'ready') { window.__ready = data; res(); } else if (data.type === 'error') rej(new Error(data.message)); };
    window.__w.postMessage({ type: 'load', tjs: 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.3.2/dist/transformers.min.js', repo, revision, backend: 'wasm' });
  }), MODELS[model]);
  const ready = await page.evaluate(() => window.__ready);
  const results = [];
  for (const id of ids) {
    const r = await page.evaluate(async ([id, language]) => {
      const buf = await (await fetch('/__fleurs/' + id)).arrayBuffer();
      const ctx = new AudioContext();
      const dec = await ctx.decodeAudioData(buf); ctx.close();
      const off = new OfflineAudioContext(1, Math.ceil(dec.duration * 16000), 16000);
      const s = off.createBufferSource(); s.buffer = dec; s.connect(off.destination); s.start();
      const audio = (await off.startRendering()).getChannelData(0);
      return await new Promise((res) => {
        window.__w.onmessage = ({ data }) => { if (data.type === 'result' || data.type === 'error') res({ ...data, duration: dec.duration }); };
        window.__w.postMessage({ type: 'transcribe', id: 1, audio, language });
      });
    }, [id, language]);
    results.push({ clip_id: id, reference: byId[id].reference, transcript: r.text ?? null, error: r.type === 'error' ? r.message : null,
      language: r.language ?? null, language_prob: r.languageProb ?? null, total_ms: r.totalMs ?? null, audio_s: r.duration });
    process.stderr.write(`${model} ${results.length}/${ids.length} ${Math.round(r.totalMs)} ms ${r.language}\n`);
  }
  const info = await page.evaluate(() => ({ ua: navigator.userAgent, cores: navigator.hardwareConcurrency, coi: self.crossOriginIsolated }));
  fs.writeFileSync(outFile, JSON.stringify({ model: MODELS[model][0], revision: MODELS[model][1], dtype: 'q8', device: ready.device, load_ms: ready.loadMs,
    language_mode: language, cpu_throttle: Number(throttle), browser: info, clips: results }, null, 1));
  await browser.close();
})();
