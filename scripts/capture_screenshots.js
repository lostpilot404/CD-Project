#!/usr/bin/env node
/**
 * Capture the Review 3 screenshot set from a running CodeTrace server.
 *
 * The screenshots in `docs/review3_screenshots/` are produced by this script, against a
 * real engine over HTTP: every number that appears in them comes from an analysis of the
 * example files, not from a mock. The script drives the workbench the way a reviewer
 * would — load an example, run the analysis, open each view, select a finding, take a
 * slice — and screenshots the result.
 *
 * Usage
 * -----
 *   python3 -m codetrace.api --port 8000          # in one terminal
 *   cd scripts
 *   npm install puppeteer-core @sparticuz/chromium # build-time only, not a project dependency
 *   node capture_screenshots.js [--base http://127.0.0.1:8000] [--out ../docs/review3_screenshots]
 *
 * The two packages are resolved from `scripts/node_modules` (created by the `npm install`
 * above, which `.gitignore` keeps out of the tree) or from `NODE_PATH` if it is set.
 *
 * CHROME_PATH may point at a system Chrome/Chromium instead of the bundled build.
 */

const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2);
function arg(name, fallback) {
  const i = args.indexOf('--' + name);
  return i === -1 ? fallback : args[i + 1];
}

const BASE = arg('base', 'http://127.0.0.1:8000');
const OUT = path.resolve(arg('out', path.join(__dirname, '..', 'docs', 'review3_screenshots')));
const VIEWPORT = { width: 1440, height: 1000 };
const SCALE = 2;
const MAX_HEIGHT = 1500;   // CSS px; keeps one figure to a readable size in the report

const COMMAND_INJECTION = `// Untrusted standard input is concatenated into a shell command.
string build_command(string user_input) {
  return "ls " + user_input;
}

int main() {
  string name = input();
  string command = build_command(name);
  system(command);
  return 0;
}`;

const MISSING_SEMICOLON = `int main() {
  string name = input()
  system(name);
  return 0;
}`;

const RULE_FILE = `# A reviewer's own rule file, parsed by CodeTrace's LR(1) rule parser.
version 1

source reviewer_input {
    description "one line read by the reviewer's harness"
    function input
    returns
    contexts command
}

sink reviewer_shell {
    description "the shell interpreter used by this demonstration"
    function system
    arguments 0
    context command
    category "command-injection"
    severity HIGH
}

flow reviewer_command {
    description "reviewer input reaches the shell interpreter"
    severity HIGH
    category "command-injection"
    sources reviewer_input
    sinks reviewer_shell
    enabled true
}`;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function main() {
  const puppeteer = require('puppeteer-core');
  let launch = { headless: 'shell' };
  if (process.env.CHROME_PATH) {
    launch.executablePath = process.env.CHROME_PATH;
    launch.args = ['--no-sandbox', '--disable-dev-shm-usage'];
  } else {
    const chromium = require('@sparticuz/chromium');
    launch.executablePath = await chromium.executablePath();
    launch.args = chromium.args;
  }

  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch(launch);
  const page = await browser.newPage();
  await page.setViewport({ ...VIEWPORT, deviceScaleFactor: SCALE });

  const problems = [];
  page.on('console', (message) => {
    if (message.type() === 'error') problems.push('console: ' + message.text());
  });
  page.on('pageerror', (error) => problems.push('pageerror: ' + error.message));
  page.on('requestfailed', (request) => problems.push('request failed: ' + request.url()));

  const go = async (route) => {
    await page.goto(`${BASE}/#/${route}`, { waitUntil: 'networkidle0' });
    await sleep(700);
  };

  const analyse = async (filename, source) => {
    await go('analyze');
    await page.evaluate((name, text) => {
      const nameInput = document.querySelector('#filename-input');
      const editor = document.querySelector('#source-input');
      nameInput.value = name;
      nameInput.dispatchEvent(new Event('input', { bubbles: true }));
      editor.value = text;
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    }, filename, source);
    await page.click('#analyze-button');
    await page.waitForFunction(
      () => !document.querySelector('#analyze-button').disabled, { timeout: 30000 });
    await sleep(900);
  };

  /** Screenshot the page from the top down to the bottom of its content. */
  const shot = async (name, options = {}) => {
    const box = await page.evaluate(() => {
      const main = document.querySelector('#main');
      const bottom = Math.max(main.getBoundingClientRect().bottom + window.scrollY,
        document.body.scrollHeight);
      return { bottom, width: document.documentElement.clientWidth };
    });
    const height = Math.min(Math.round(box.bottom), options.maxHeight || MAX_HEIGHT);
    const clip = { x: 0, y: 0, width: box.width, height };
    await page.screenshot({ path: path.join(OUT, name), clip });
    console.log('  ' + name + `  ${box.width}x${height}`);
  };

  /** Screenshot one element, with a little breathing room around it. */
  const shotOf = async (name, selector, pad = 8) => {
    const element = await page.$(selector);
    if (!element) throw new Error(`missing element ${selector}`);
    const box = await element.boundingBox();
    const clip = {
      x: Math.max(0, box.x - pad),
      y: Math.max(0, box.y - pad + await page.evaluate(() => window.scrollY)),
      width: Math.min(box.width + pad * 2, VIEWPORT.width),
      height: box.height + pad * 2,
    };
    await page.screenshot({ path: path.join(OUT, name), clip });
    console.log('  ' + name + `  ${Math.round(clip.width)}x${Math.round(clip.height)}`);
  };

  console.log('capture: overview');
  // the display name in the header card is short enough to stay on one line
  await analyse('injection.ctc', COMMAND_INJECTION);
  await go('overview');
  await shot('01_overview.png', { maxHeight: 1180 });

  console.log('capture: analyze workbench');
  await go('analyze');
  await shot('02_analyze_workbench.png', { maxHeight: 1120 });

  console.log('capture: editor state guard');
  await page.evaluate(() => {
    const editor = document.querySelector('#source-input');
    editor.value += '\n// edited after the run\n';
    editor.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await sleep(600);
  await page.evaluate(() => document.querySelector('#main').scrollIntoView());
  await shot('03_editor_state_guard.png', { maxHeight: 1120 });

  console.log('capture: located diagnostics');
  await analyse('missing_semicolon.ctc', MISSING_SEMICOLON);
  await shotOf('04_syntax_diagnostics.png', '#analyze-diagnostics', 10);
  await shot('04b_analysis_refused.png', { maxHeight: 1120 });

  console.log('capture: findings and evidence');
  await analyse('command_injection.ctc', COMMAND_INJECTION);
  await go('findings');
  const card = await page.$('.finding-card__select');
  if (card) {
    await card.click();
    await sleep(1200);
  }
  await shot('05_findings.png', { maxHeight: 1240 });
  if (await page.$('.evidence-path')) {
    await shotOf('05b_evidence_path.png', '.evidence-path', 10);
  }

  console.log('capture: program graph');
  await go('graph');
  await sleep(900);
  // select the sink statement, so the panel beside the canvas shows its analysis
  // results instead of the prompt that asks for a selection
  const selected = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll('#graph-canvas svg g[role="button"]')];
    const target = nodes.find((n) => /system\(command\)/.test(n.textContent));
    if (!target) return null;
    target.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return target.getAttribute('aria-label');
  });
  console.log('  selected graph node: ' + selected);
  await sleep(800);
  await shot('06_program_graph.png', { maxHeight: 1100 });

  console.log('capture: data flow');
  await go('dataflow');
  await page.evaluate(() => {
    const select = document.querySelector('#dataflow-toolbar select');
    if (select) {
      const option = [...select.options].find((o) => o.value === 'main');
      if (option) {
        select.value = option.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
  });
  await sleep(1200);
  await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#dataflow-body table.data tbody tr')];
    const row = rows.find((r) => /system\(command\)/.test(r.textContent)) || rows[rows.length - 1];
    const button = row && row.querySelector('button');
    if (button) button.click();
  });
  await sleep(1200);
  await shot('07_dataflow.png', { maxHeight: 1320 });

  console.log('capture: slicing');
  await go('slicing');
  await page.evaluate(() => {
    const selects = [...document.querySelectorAll('#slicing-toolbar select')];
    if (selects[0]) {
      const option = [...selects[0].options].find((o) => /system\(command\)/.test(o.textContent));
      if (option) {
        selects[0].value = option.value;
        selects[0].dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
  });
  await sleep(1500);
  await shot('08_slice.png', { maxHeight: 1180 });
  const subgraphHandle = await page.evaluateHandle(() => {
    const headings = [...document.querySelectorAll('#slicing-body h2, #slicing-body h3')];
    const target = headings.find((h) => /subgraph/i.test(h.textContent));
    if (!target) return null;
    return target.parentElement && target.parentElement.contains(target)
      ? (target.nextElementSibling || target.parentElement)
      : target;
  });
  const element = subgraphHandle.asElement();
  if (element) {
    await element.evaluate((node) => node.scrollIntoView({ block: 'center' }));
    await sleep(500);
    await element.screenshot({ path: path.join(OUT, '08b_slice_subgraph.png') });
    console.log('  08b_slice_subgraph.png (element capture)');
    await page.evaluate(() => window.scrollTo(0, 0));
  }

  console.log('capture: rule editor');
  await go('rules');
  await page.evaluate((text) => {
    const editor = document.querySelector('#rule-editor');
    editor.value = text;
    editor.dispatchEvent(new Event('input', { bubbles: true }));
  }, RULE_FILE);
  await page.click('#validate-rules-button');
  await sleep(1800);
  const rulesStatus = await page.$eval('#rules-status', (e) => e.innerText.trim());
  if (!/valid/i.test(rulesStatus) || /rejected|error/i.test(rulesStatus)) {
    console.log('  rule validation did not succeed: ' + rulesStatus);
    problems.push('rule editor screenshot would have shown a rejected rule set');
  }
  await shot('09_rule_editor.png', { maxHeight: 1180 });

  console.log('capture: rule validation result');
  await shotOf('09b_rule_validation.png', '#rules-diagnostics', 10);

  console.log('capture: reports');
  await analyse('command_injection.ctc', COMMAND_INJECTION.replace('input()', 'input()'));
  const runId = await page.evaluate(() => {
    const text = document.querySelector('#analyze-status').innerText;
    const match = text.match(/run ([0-9a-f]+)/);
    return match ? match[1] : '';
  });
  await analyse('command_injection_fixed.ctc',
    COMMAND_INJECTION.replace('  system(command);', '  system("ls");'));
  const fixedId = await page.evaluate(() => {
    const text = document.querySelector('#analyze-status').innerText;
    const match = text.match(/run ([0-9a-f]+)/);
    return match ? match[1] : '';
  });
  await go('reports');
  if (runId && fixedId) {
    const inputs = await page.$$('#reports-body input');
    if (inputs.length >= 2) {
      await inputs[0].click({ clickCount: 3 });
      await inputs[0].type(runId);
      await inputs[1].click({ clickCount: 3 });
      await inputs[1].type(fixedId);
      await page.evaluate(() => {
        const button = [...document.querySelectorAll('#reports-body button')]
          .find((b) => /compare/i.test(b.textContent));
        if (button) button.click();
      });
      await sleep(1800);
    }
  }
  await shot('10_reports.png', { maxHeight: 1100 });

  console.log('capture: documentation');
  await go('documentation');
  await shot('11_documentation.png', { maxHeight: 1120 });

  console.log('capture: dark theme');
  // re-analyse the vulnerable file so the dark capture shows a run with a finding
  await analyse('command_injection.ctc', COMMAND_INJECTION);
  await go('overview');
  await page.evaluate(() => {
    const toggle = document.querySelector('#theme-toggle');
    for (let i = 0; i < 3; i += 1) {
      if (/dark/i.test(toggle.textContent)) break;
      toggle.click();
    }
  });
  await sleep(900);
  await shot('12_dark_theme.png', { maxHeight: 1180 });

  await browser.close();
  if (problems.length) {
    console.log(`\n${problems.length} page problem(s):`);
    problems.slice(0, 10).forEach((problem) => console.log('  - ' + problem));
    process.exitCode = 1;
  } else {
    console.log('\nno console errors, no failed requests');
  }
}

main().catch((error) => {
  console.error('capture failed:', error.message);
  process.exit(1);
});
