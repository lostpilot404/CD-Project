// Drives the real CodeTrace interface in a headless Chromium and saves
// screenshots of what the engine actually returned.  Nothing is mocked: every
// value on screen comes from the running server.
//
//   CODETRACE_URL=http://127.0.0.1:8000 CHROME_PATH=/path/to/chrome \
//     node submission/tools/ui_capture.mjs submission/screenshots submission/evidence
//
// Requires puppeteer-core (npm install puppeteer-core) and a Chromium binary.
// When CHROME_PATH is not set, the tool falls back to the Chromium bundled in
// the npm package @sparticuz/chromium (npm install @sparticuz/chromium), which
// needs no system browser.  Fonts: that bundle ships Open Sans only, which has
// no glyphs for ∪ ⋃ → ∅; put DejaVu Sans / DejaVu Sans Mono (or any font with
// those glyphs) in a fontconfig directory and point FONTCONFIG_PATH at it so
// the data-flow equations render.
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.CODETRACE_URL || 'http://127.0.0.1:8000';
const SHOTS = process.argv[2] || 'submission/screenshots';
const EVIDENCE = process.argv[3] || 'submission/evidence';
fs.mkdirSync(SHOTS, { recursive: true });
fs.mkdirSync(EVIDENCE, { recursive: true });

// 1680 × 1000 is a common desktop size and wider than the interface's own
// layout cap (110rem), so every page is shown at the width it was designed for.
const VIEWPORT = { width: 1680, height: 1000, deviceScaleFactor: 1 };

let executablePath = process.env.CHROME_PATH;
let launchArgs = (process.env.CHROME_ARGS || '--no-sandbox,--disable-gpu,--disable-dev-shm-usage').split(',');
if (!executablePath) {
  const { default: chromium } = await import('@sparticuz/chromium');
  executablePath = await chromium.executablePath();
  launchArgs = chromium.args;
}

const browser = await puppeteer.launch({ executablePath, headless: true, args: launchArgs, defaultViewport: VIEWPORT });
const page = await browser.newPage();
const consoleErrors = [];
const pageErrors = [];
page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
page.on('pageerror', (err) => pageErrors.push(String(err)));

const log = [];
const step = (name, note) => { log.push({ step: name, note, at: new Date().toISOString() }); console.log('•', name, note || ''); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// Park the pointer in the page margin before every capture so no button is
// drawn in its hover state.
const parkMouse = () => page.mouse.move(2, VIEWPORT.height - 2);
const shot = async (file, label) => {
  await parkMouse();
  await page.screenshot({ path: path.join(SHOTS, file), fullPage: true });
  step('screenshot', `${file} — ${label}`);
};
// A close-up of one element at 2× device pixels: readable when embedded in a
// report at figure width.  The element is clipped out of the whole document
// rather than scrolled into view, so the sticky top bar and toolbars stay where
// they belong instead of covering the element.  The viewport is restored
// afterwards; `width` lets a wide element (the graph canvas) keep its frame.
const closeup = async (selector, file, label, width = VIEWPORT.width) => {
  await parkMouse();
  await page.setViewport({ ...VIEWPORT, width, deviceScaleFactor: 2 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await sleep(250);
  const clip = await page.evaluate((sel) => {
    const node = document.querySelector(sel);
    if (!node) return null;
    const rect = node.getBoundingClientRect();
    return { x: rect.left + window.scrollX, y: rect.top + window.scrollY, width: rect.width, height: rect.height };
  }, selector);
  if (!clip) throw new Error(`close-up target ${selector} not found`);
  await page.screenshot({ path: path.join(SHOTS, file), clip, captureBeyondViewport: true });
  await page.setViewport(VIEWPORT);
  await sleep(200);
  step('screenshot', `${file} — ${label} (close-up of ${selector}, 2× pixels)`);
};
const waitText = (selector, pattern, timeout = 20000) =>
  page.waitForFunction((sel, pat) => {
    const node = document.querySelector(sel);
    return node && new RegExp(pat).test(node.textContent);
  }, { timeout }, selector, pattern);

async function openExample(name) {
  await page.evaluate(() => { location.hash = '#/analyze'; });
  await page.waitForSelector('#load-example-button');
  await page.click('#load-example-button');
  await page.waitForFunction(() => document.querySelectorAll('.modal .modal__list button').length > 0, { timeout: 20000 });
  const clicked = await page.evaluate((n) => {
    const btn = [...document.querySelectorAll('.modal .modal__list button')].find((b) => b.textContent.trim() === n);
    if (btn) btn.click();
    return !!btn;
  }, name);
  if (!clicked) throw new Error(`example ${name} not listed`);
  step('load example', name);
}

async function runAnalysis() {
  await page.click('#analyze-button');
  await waitText('#analyze-status', 'Analysed|could not|error|Error|rejected', 30000);
  await sleep(300);
}

// Select a <select> option the way a user would: set the value, fire `change`.
async function choose(selector, value) {
  const ok = await page.evaluate((sel, val) => {
    const select = document.querySelector(sel);
    if (!select || ![...select.options].some((o) => o.value === val)) return false;
    select.value = val;
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }, selector, value);
  if (!ok) throw new Error(`option ${value} not available in ${selector}`);
}

// Click the graph node whose accessible label matches `pattern`.
async function clickGraphNode(pattern) {
  const ok = await page.evaluate((pat) => {
    const node = [...document.querySelectorAll('#graph-canvas .node')].find((g) => new RegExp(pat).test(g.getAttribute('aria-label') || ''));
    if (node) node.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return !!node;
  }, pattern);
  if (!ok) throw new Error(`graph node ${pattern} not found`);
}

// 1. Overview
await page.goto(BASE + '/#/overview', { waitUntil: 'networkidle0' });
await waitText('#engine-status', 'ok|ready|online|LR|Engine|engine', 20000).catch(() => {});
await shot('01-overview.png', 'Overview: engine status and pipeline');

// 2. Analyze: primary vulnerable example — a completed analysis
await openExample('command_injection.ctc');
await runAnalysis();
await shot('02-analyze-vulnerable-run.png', 'Analyze Code after running command_injection.ctc: summary, diagnostics, run id');
const summaryText = await page.$eval('#analyze-summary', (n) => n.textContent);
fs.writeFileSync(path.join(EVIDENCE, 'ui_summary_command_injection.txt'), summaryText);

// 3. Findings with evidence path
await page.evaluate(() => { location.hash = '#/findings'; });
await page.waitForSelector('#findings-list');
await sleep(500);
// Select the finding (the list item is a button) so its detail and evidence path render.
await page.evaluate(() => {
  const item = [...document.querySelectorAll('#findings-list button')].find((b) => /system\(\)/.test(b.textContent));
  if (item) item.click();
});
await waitText('#finding-detail', 'Evidence path', 20000);
await sleep(400);
await shot('03-findings-list-and-detail.png', 'Findings list and detail (evidence path) for the command-injection finding');
await closeup('#finding-detail', '03b-finding-evidence-path-closeup.png', 'The finding record: source, sink, why it was reported and the 8-step evidence path');
const detailText = await page.$eval('#finding-detail', (n) => n.innerText);
fs.writeFileSync(path.join(EVIDENCE, 'ui_finding_detail_command_injection.txt'), detailText);

// 4. Program graph.  The sink statement is selected so the side panel shows the
// engine's per-statement results (reaching definitions, liveness, taint).
// The layered layout is drawn at natural size and the canvas scrolls; for a
// single frame the page is widened to Full HD and the layout width cap is
// lifted — a presentation setting only, the graph data is untouched.
await page.evaluate(() => { location.hash = '#/graph'; });
await page.waitForSelector('#graph-canvas .graph-svg', { timeout: 20000 });
await clickGraphNode('system\\(command\\)');
await waitText('#graph-side', 'Taint before this statement', 20000);
await sleep(400);
await page.setViewport({ ...VIEWPORT, width: 1920 });
const wideLayout = await page.addStyleTag({ content: '.layout { max-width: none; }' });
await sleep(300);
await shot('04-program-graph.png', 'Typed program dependency graph with the sink statement selected (Full-HD frame)');
await closeup('#graph-canvas', '04b-program-graph-closeup.png', 'The dependency graph alone: taint edges in red, call/return in blue, define edges in purple', 1920);
await wideLayout.evaluate((node) => node.remove());
await page.setViewport(VIEWPORT);
step('note', '04 and 04b were captured at 1920px with the 110rem layout cap lifted so the whole graph fits one frame; every other page uses 1680px and the stock stylesheet');

// 5. Data-flow: reaching definitions in main(), the function that holds the flow,
// with the sink statement selected.
await page.evaluate(() => { location.hash = '#/dataflow'; });
await page.waitForSelector('#dataflow-body');
await waitText('#dataflow-body', 'Basic blocks', 20000);
await choose('#dataflow-toolbar select', 'main');
await waitText('#dataflow-body', 'in main\\(\\)', 20000);
await waitText('#dataflow-body', 'Basic blocks', 20000);
await page.evaluate(() => {
  const btn = [...document.querySelectorAll('#dataflow-body table.data button')].find((b) => b.textContent.trim() === '3');
  if (btn) btn.click();
});
await waitText('#dataflow-body', 'Taint before this statement', 20000);
await sleep(400);
await shot('05-dataflow.png', 'Reaching definitions in main(): equations, worklist, block IN/OUT sets, per-statement states, selected statement');

// 6. Slicing
await page.evaluate(() => { location.hash = '#/slicing'; });
await page.waitForSelector('#slicing-body');
await sleep(800);
await shot('06-slicing.png', 'Program slicing view');

// 7. Reports
await page.evaluate(() => { location.hash = '#/reports'; });
await page.waitForSelector('#reports-body');
await sleep(300);
await shot('07-reports.png', 'Reports page with JSON and HTML export links');

// 8. Safe counterpart: zero-finding state
await openExample('constant_command.ctc');
await runAnalysis();
await page.evaluate(() => { location.hash = '#/findings'; });
await sleep(400);
await shot('08-safe-counterpart-zero-findings.png', 'Safe counterpart: zero findings, stated as such');
fs.writeFileSync(path.join(EVIDENCE, 'ui_findings_safe_counterpart.txt'), await page.$eval('#view-findings', (n) => n.innerText));

// 9. Syntax error
await openExample('missing_semicolon.ctc');
await runAnalysis();
await page.evaluate(() => { location.hash = '#/analyze'; });
await sleep(400);
await shot('09-syntax-error.png', 'Syntax error: located diagnostic, partial analysis');
fs.writeFileSync(path.join(EVIDENCE, 'ui_syntax_error_missing_semicolon.txt'), await page.$eval('#analyze-diagnostics', (n) => n.innerText));

// 10. Unsupported construct
await openExample('switch_statement.ctc');
await runAnalysis();
await page.evaluate(() => { location.hash = '#/analyze'; });
await sleep(400);
await shot('10-unsupported-switch.png', 'Unsupported construct: switch statement reported, run partial');
fs.writeFileSync(path.join(EVIDENCE, 'ui_unsupported_switch.txt'), await page.$eval('#analyze-diagnostics', (n) => n.innerText));

// 11–12. A loop: the control-flow graph with its loop-back edge, and the
// fixed-point iteration of reaching definitions over that loop.
await openExample('loop_carried.ctc');
await runAnalysis();
await page.evaluate(() => { location.hash = '#/graph'; });
await page.waitForSelector('#graph-toolbar select', { timeout: 20000 });
await choose('#graph-toolbar select', 'cfg');
await waitText('#graph-canvas', 'Control-flow graph of main\\(\\)', 20000);
// Select the loop body block: its statement is control-dependent on the loop condition.
await clickGraphNode('B4');
await waitText('#graph-side', 'Control dependencies', 20000);
await sleep(400);
await shot('11-cfg-loop-carried.png', 'Control-flow graph of main() in loop_carried.ctc: block kinds, true/false edges, loop-back edge, loop body selected');
await page.evaluate(() => { location.hash = '#/dataflow'; });
await page.waitForSelector('#dataflow-body');
await waitText('#dataflow-body', 'Basic blocks', 20000);
await choose('#dataflow-toolbar select', 'main');
await waitText('#dataflow-body', 'in main\\(\\)', 20000);
await waitText('#dataflow-body', 'Basic blocks', 20000);
await sleep(400);
await shot('12-dataflow-loop-carried.png', 'Reaching definitions over the loop: more than one worklist pass before the fixed point');

fs.writeFileSync(path.join(EVIDENCE, 'ui_capture_log.json'), JSON.stringify({
  base: BASE,
  browser: await browser.userAgent(),
  viewport: VIEWPORT,
  steps: log,
  console_errors: consoleErrors,
  page_errors: pageErrors,
}, null, 2));
console.log('console errors:', consoleErrors.length, 'page errors:', pageErrors.length);
await browser.close();
