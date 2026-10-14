// Render a DOCX with docx-preview inside headless Chromium and print it to PDF
// (Letter, 1 in margins, Times-metric "Tinos" standing in for Times New Roman)
// so that the pagination of the report can be measured without Microsoft Word.
//
// Usage:  node render_check.mjs <input.docx> <output.pdf>
// Requires (installed with npm in $SHOT_DIR, default /home/user/.cache/shot):
//   @sparticuz/chromium puppeteer-core docx-preview jszip @fontsource/tinos
// and the chromium binary + al2023 libraries inflated to /tmp (see setup notes
// in build_bcse307p_report.py).
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const SHOT = process.env.SHOT_DIR || '/home/user/.cache/shot';
const require = createRequire(path.join(SHOT, 'package.json'));
const chromium = (await import(require.resolve('@sparticuz/chromium'))).default;
const { setupLambdaEnvironment } = await import(require.resolve('@sparticuz/chromium'));
const puppeteer = (await import(require.resolve('puppeteer-core'))).default;

setupLambdaEnvironment('/tmp/al2023/lib');
process.env.LD_LIBRARY_PATH = '/tmp/al2023/lib:' + (process.env.LD_LIBRARY_PATH || '');

const DOCX = path.resolve(process.argv[2]);
const PDF = path.resolve(process.argv[3]);
const FONTS = path.join(SHOT, 'node_modules/@fontsource/tinos/files');
const html = `<!doctype html><html><head><meta charset="utf-8">
<style>
@font-face{font-family:"Times New Roman";font-weight:400;font-style:normal;src:url("file://${FONTS}/tinos-latin-400-normal.woff2") format("woff2");}
@font-face{font-family:"Times New Roman";font-weight:700;font-style:normal;src:url("file://${FONTS}/tinos-latin-700-normal.woff2") format("woff2");}
@font-face{font-family:"Times New Roman";font-weight:400;font-style:italic;src:url("file://${FONTS}/tinos-latin-400-italic.woff2") format("woff2");}
@font-face{font-family:"Times New Roman";font-weight:700;font-style:italic;src:url("file://${FONTS}/tinos-latin-700-italic.woff2") format("woff2");}
@font-face{font-family:"Consolas";src:local("DejaVu Sans Mono");}
@page{size:8.5in 11in;margin:1in;}
.docx-wrapper>section.docx:last-child{break-after:auto;page-break-after:auto;}
html,body{margin:0;padding:0;background:#fff;}
.docx-wrapper{background:none !important;padding:0 !important;display:block !important;}
.docx-wrapper>section.docx{break-after:page;page-break-after:always;padding:0 !important;min-height:0 !important;width:6.5in !important;box-shadow:none !important;margin:0 !important;box-sizing:content-box;}
</style>
<script src="file://${SHOT}/node_modules/jszip/dist/jszip.min.js"></script>
<script src="file://${SHOT}/node_modules/docx-preview/dist/docx-preview.min.js"></script>
</head><body><div id="c"></div></body></html>`;
fs.mkdirSync(path.join(SHOT, 'render'), { recursive: true });
const htmlPath = path.join(SHOT, 'render', 'harness.html');
fs.writeFileSync(htmlPath, html);

const exe = await chromium.executablePath();
const browser = await puppeteer.launch({
  executablePath: exe,
  args: [...chromium.args, '--no-sandbox', '--disable-gpu', '--allow-file-access-from-files'],
  headless: 'shell',
  defaultViewport: { width: 1000, height: 1200 },
});
const page = await browser.newPage();
const errors = [];
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errors.push(m.text()); });
page.on('pageerror', (e) => errors.push(String(e)));
await page.goto('file://' + htmlPath);
const b64 = fs.readFileSync(DOCX).toString('base64');
await page.evaluate(async (b64) => {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  await window.docx.renderAsync(bytes.buffer, document.getElementById('c'), null, {
    breakPages: true, ignoreLastRenderedPageBreak: true, renderHeaders: false, renderFooters: false,
    ignoreHeight: true, ignoreWidth: false, inWrapper: true, useBase64URL: true, experimental: true,
  });
}, b64);
await page.evaluate(() => document.fonts.ready);
await new Promise((r) => setTimeout(r, 1500));
const info = await page.evaluate(() => ({
  sections: document.querySelectorAll('section.docx').length,
  images: document.images.length,
  fonts: [...document.fonts].map((f) => `${f.family}:${f.weight}:${f.style}:${f.status}`),
}));
console.log(JSON.stringify(info));
await page.pdf({ path: PDF, preferCSSPageSize: true, printBackground: true });
console.log('pdf written', PDF, 'console errors:', errors.length, errors.slice(0, 5));
await browser.close();
