/**
 * Shared bootstrap for the CodeTrace frontend tests.
 *
 * The application itself has no dependencies and no build step; these tests
 * are development-only tooling.  They start the real Python API on an
 * ephemeral port, load the real `frontend/index.html` into jsdom, wire
 * `window.fetch` to the real server and import the real ES modules — the same
 * `app.js` the browser loads.  What they are NOT: a real browser.  Layout,
 * painting, focus rings and responsive behaviour need the manual pass in
 * `docs/MANUAL_BROWSER_VERIFICATION.md`.
 */

import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { JSDOM } from 'jsdom';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export const settle = (ms = 250) => new Promise((resolve) => setTimeout(resolve, ms));

export async function until(fn, { timeout = 20000, step = 150, label = 'condition' } = {}) {
  const deadline = Date.now() + timeout;
  for (;;) {
    const value = await fn();
    if (value) return value;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
    await settle(step);
  }
}

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once('error', reject);
    probe.listen(0, '127.0.0.1', () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

/** Start `python3 -m codetrace.api` (the documented command) on a free port. */
export async function startServer() {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const child = spawn('python3', ['-m', 'codetrace.api', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: ROOT,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let stderr = '';
  child.stderr.on('data', (chunk) => { stderr += chunk; });
  await until(async () => {
    if (child.exitCode !== null) throw new Error(`server exited (${child.exitCode}): ${stderr}`);
    try {
      const response = await fetch(`${base}/api/health`);
      return response.ok;
    } catch {
      return false;
    }
  }, { label: 'server health', timeout: 30000 });
  return { child, port, base };
}

/**
 * Load the real index.html + app.js into jsdom, wired to `base`.
 * Returns DOM helpers bound to this window.
 */
export async function buildApp(base) {
  const html = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    url: `${base}/`,
    pretendToBeVisual: true,
  });
  const { window } = dom;

  // Capture Node's fetch BEFORE anything overrides it (a self-recursive
  // wrapper here once deadlocked the suite).
  const nodeFetch = globalThis.fetch.bind(globalThis);
  const requests = [];
  const wrappedFetch = async (input, init) => {
    const url = typeof input === 'string' ? new URL(input, base).href : String(input);
    const parsed = new URL(url);
    requests.push(`${(init && init.method) || 'GET'} ${parsed.pathname}${parsed.search}`);
    return nodeFetch(url, init);
  };
  window.fetch = wrappedFetch;

  // Node 22 exposes a getter-only global `navigator`; app code and jsdom both
  // need the window's one, so redefine rather than assign.
  Object.defineProperty(globalThis, 'navigator', { value: window.navigator, configurable: true });
  for (const key of ['window', 'document', 'location', 'history', 'localStorage', 'sessionStorage',
    'HTMLElement', 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'MouseEvent',
    'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'matchMedia']) {
    if (window[key] !== undefined) {
      Object.defineProperty(globalThis, key, { value: window[key], configurable: true, writable: true });
    }
  }
  Object.defineProperty(globalThis, 'fetch', { value: wrappedFetch, configurable: true, writable: true });

  // jsdom does not execute <script type="module">; import the real entry
  // point directly, which is exactly what the browser would execute.
  await import(pathToFileURL(path.join(ROOT, 'frontend', 'js', 'app.js')).href);
  await until(() => {
    const status = window.document.getElementById('engine-status');
    return status && /rules|states/i.test(status.textContent);
  }, { label: 'engine status', timeout: 15000 });

  const document = window.document;
  const helpers = {
    dom,
    window,
    document,
    requests,
    q: (selector) => document.querySelector(selector),
    qa: (selector) => Array.from(document.querySelectorAll(selector)),
    text: (selector) => {
      const el = document.querySelector(selector);
      return el ? el.textContent : null;
    },
    visibleView: () => {
      const view = Array.from(document.querySelectorAll('.view')).find((v) => !v.hidden);
      return view ? view.id : null;
    },
    type(selector, value) {
      const el = document.querySelector(selector);
      el.value = value;
      el.dispatchEvent(new window.Event('input', { bubbles: true }));
    },
    click(selector) {
      const el = typeof selector === 'string' ? document.querySelector(selector) : selector;
      el.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
    },
    changeSelect(select, value) {
      select.value = value;
      select.dispatchEvent(new window.Event('change', { bubbles: true }));
    },
    async navigate(route) {
      window.location.hash = `#/${route}`;
      await settle(350);
    },
    async analyse(source, filename = 'example.ctc') {
      // Navigate first: completion refreshes the *visible* route, so the
      // status line the run id is read from only updates on the analyze view.
      await helpers.navigate('analyze');
      helpers.type('#source-input', source);
      if (filename) helpers.q('#filename-input').value = filename;
      helpers.click('#analyze-button');
      await until(() => /run [0-9a-f]{16}/.test(helpers.text('#analyze-status') || ''), {
        label: `analysis of ${filename}`,
      });
      const runId = helpers.text('#analyze-status').match(/run ([0-9a-f]{16})/)[1];
      await settle(300);
      return runId;
    },
  };
  return helpers;
}
