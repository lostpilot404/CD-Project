// Drives the real CodeTrace interface in a headless Chromium and saves
// screenshots of what the engine actually returned.  Nothing is mocked: every
// value on screen comes from the running server.
//
//   CODETRACE_URL=http://127.0.0.1:8000 CHROME_PATH=/path/to/chrome \
//     node submission/tools/ui_capture.mjs submission/screenshots submission/evidence
//
// Requires puppeteer-core (npm install puppeteer-core) and a Chromium binary.
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.CODETRACE_URL || 'http://127.0.0.1:8000';
const SHOTS = process.argv[2] || 'submission/screenshots';
const EVIDENCE = process.argv[3] || 'submission/evidence';
fs.mkdirSync(SHOTS, { recursive: true });
fs.mkdirSync(EVIDENCE, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH,
  headless: 'shell',
  args: (process.env.CHROME_ARGS || '--no-sandbox,--disable-gpu,--disable-dev-shm-usage').split(','),
  defaultViewport: { width: 1440, height: 1000 },
});
const page = await browser.newPage();
const consoleErrors = [];
const pageErrors = [];
page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
page.on('pageerror', (err) => pageErrors.push(String(err)));

const log = [];
const step = (name, note) => { log.push({ step: name, note, at: new Date().toISOString() }); console.log('•', name, note || ''); };
const shot = async (file, label) => {
  await page.screenshot({ path: path.join(SHOTS, file), fullPage: true });
  step('screenshot', `${file} — ${label}`);
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
  await new Promise((r) => setTimeout(r, 300));
}

// 1. Overview
await page.goto(BASE + '/#/overview', { waitUntil: 'networkidle0' });
await waitText('#engine-status', 'ok|ready|online|LR|Engine|engine', 20000).catch(() => {});
await shot('01-overview.png', 'Overview: engine status and pipeline');

// 2. Analyze: primary vulnerable example
await openExample('command_injection.ctc');
await runAnalysis();
await shot('02-analyze-vulnerable-run.png', 'Analyze Code after running command_injection.ctc');
const summaryText = await page.$eval('#analyze-summary', (n) => n.textContent);
fs.writeFileSync(path.join(EVIDENCE, 'ui_summary_command_injection.txt'), summaryText);

// 3. Findings with evidence path
await page.evaluate(() => { location.hash = '#/findings'; });
await page.waitForSelector('#findings-list');
await new Promise((r) => setTimeout(r, 500));
// Select the finding (the list item is a button) so its detail and evidence path render.
await page.evaluate(() => {
  const item = [...document.querySelectorAll('#findings-list button')].find((b) => /system\(\)/.test(b.textContent));
  if (item) item.click();
});
await new Promise((r) => setTimeout(r, 600));
await shot('03-findings-list-and-detail.png', 'Findings list and detail (evidence path) for the command-injection finding');
const detailText = await page.$eval('#finding-detail', (n) => n.innerText);
fs.writeFileSync(path.join(EVIDENCE, 'ui_finding_detail_command_injection.txt'), detailText);

// 4. Program graph
await page.evaluate(() => { location.hash = '#/graph'; });
await page.waitForSelector('#graph-canvas');
await new Promise((r) => setTimeout(r, 800));
await shot('04-program-graph.png', 'Typed program dependency graph for the finding');

// 5. Data-flow
await page.evaluate(() => { location.hash = '#/dataflow'; });
await page.waitForSelector('#dataflow-body');
await new Promise((r) => setTimeout(r, 500));
await shot('05-dataflow.png', 'Reaching definitions / liveness / definite assignment');

// 6. Slicing
await page.evaluate(() => { location.hash = '#/slicing'; });
await page.waitForSelector('#slicing-body');
await new Promise((r) => setTimeout(r, 500));
await shot('06-slicing.png', 'Program slicing view');

// 7. Reports
await page.evaluate(() => { location.hash = '#/reports'; });
await page.waitForSelector('#reports-body');
await new Promise((r) => setTimeout(r, 300));
await shot('07-reports.png', 'Reports page with JSON and HTML export links');

// 8. Safe counterpart: zero-finding state
await openExample('constant_command.ctc');
await runAnalysis();
await page.evaluate(() => { location.hash = '#/findings'; });
await new Promise((r) => setTimeout(r, 400));
await shot('08-safe-counterpart-zero-findings.png', 'Safe counterpart: zero findings, stated as such');
fs.writeFileSync(path.join(EVIDENCE, 'ui_findings_safe_counterpart.txt'), await page.$eval('#view-findings', (n) => n.innerText));

// 9. Syntax error
await openExample('missing_semicolon.ctc');
await runAnalysis();
await page.evaluate(() => { location.hash = '#/analyze'; });
await new Promise((r) => setTimeout(r, 400));
await shot('09-syntax-error.png', 'Syntax error: located diagnostic, partial analysis');
fs.writeFileSync(path.join(EVIDENCE, 'ui_syntax_error_missing_semicolon.txt'), await page.$eval('#analyze-diagnostics', (n) => n.innerText));

// 10. Unsupported construct
await openExample('switch_statement.ctc');
await runAnalysis();
await page.evaluate(() => { location.hash = '#/analyze'; });
await new Promise((r) => setTimeout(r, 400));
await shot('10-unsupported-switch.png', 'Unsupported construct: switch statement reported, run partial');
fs.writeFileSync(path.join(EVIDENCE, 'ui_unsupported_switch.txt'), await page.$eval('#analyze-diagnostics', (n) => n.innerText));

fs.writeFileSync(path.join(EVIDENCE, 'ui_capture_log.json'), JSON.stringify({ base: BASE, steps: log, console_errors: consoleErrors, page_errors: pageErrors }, null, 2));
console.log('console errors:', consoleErrors.length, 'page errors:', pageErrors.length);
await browser.close();
