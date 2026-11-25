// Shared Playwright setup: real Chromium, Hugging Face downloads over the network, and jsDelivr
// served from the identical npm tarball files (for sandboxes where jsDelivr is blocked).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
// Unpacked npm tarballs: npm pack @huggingface/transformers@4.3.2 onnxruntime-web@1.31.0-dev.20260914-8d85527a0
const NPM = process.env.NPM_DIR || path.join(__dirname, '.npm');
const MAP = [
  ['https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.3.2/dist/', `${NPM}/tjs/package/dist/`],
  ['https://cdn.jsdelivr.net/npm/onnxruntime-web@1.31.0-dev.20260914-8d85527a0/dist/', `${NPM}/ort/package/dist/`],
];
const served = [];
async function launch(opts = {}) {
  const browser = await chromium.launch({ proxy: { server: process.env.HTTPS_PROXY, bypass: 'localhost,127.0.0.1' }, ...opts.launch });
  const context = await browser.newContext({ ...opts.context });
  await context.route('https://cdn.jsdelivr.net/**', async (route) => {
    const url = route.request().url();
    for (const [prefix, dir] of MAP) {
      if (url.startsWith(prefix)) {
        const file = path.join(dir, url.slice(prefix.length).split('?')[0]);
        served.push(url);
        const type = file.endsWith('.wasm') ? 'application/wasm' : 'text/javascript';
        return route.fulfill({ status: 200, body: fs.readFileSync(file), headers: { 'content-type': type, 'access-control-allow-origin': '*' } });
      }
    }
    return route.fulfill({ status: 404, body: 'not mapped: ' + url });
  });
  return { browser, context, served };
}
module.exports = { launch };
