/**
 * Test harness: a real engine plus a stub DOM.
 *
 * The frontend tests are integration tests.  Instead of hand-written mock
 * responses they start the actual CodeTrace server on a private port
 * (`python3 -m codetrace.api`, exactly the command the README documents) and
 * point the page's `fetch` at it, so every number a view displays comes from
 * the real analysis engine.  The only substitution is the DOM itself
 * (see `dom.js`).
 */

import { spawn } from 'node:child_process';
import { connect } from 'node:net';
import { readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { installDocument } from './dom.js';

export const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
export const FRONTEND_ROOT = join(REPO_ROOT, 'frontend');

function portFree(port) {
  return new Promise((resolve_) => {
    const socket = connect({ host: '127.0.0.1', port });
    socket.on('connect', () => {
      socket.destroy();
      resolve_(false);
    });
    socket.on('error', () => resolve_(true));
  });
}

async function pickPort() {
  for (let port = 8791; port < 8860; port += 1) {
    // eslint-disable-next-line no-await-in-loop
    if (await portFree(port)) return port;
  }
  throw new Error('no free port found for the test engine');
}

async function waitForHealth(baseUrl, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      // eslint-disable-next-line no-await-in-loop
      const response = await fetch(`${baseUrl}/api/health`);
      if (response.ok) return response.json();
    } catch (error) {
      lastError = error;
    }
    // eslint-disable-next-line no-await-in-loop
    await new Promise((done) => setTimeout(done, 120));
  }
  throw new Error(`engine did not become healthy: ${lastError ? lastError.message : 'timeout'}`);
}

/** Start `python3 -m codetrace.api` and wait until it answers `/api/health`. */
export async function startEngine() {
  const port = await pickPort();
  const child = spawn('python3', ['-m', 'codetrace.api', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: REPO_ROOT,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let log = '';
  child.stdout.on('data', (chunk) => {
    log += chunk.toString();
  });
  child.stderr.on('data', (chunk) => {
    log += chunk.toString();
  });
  const baseUrl = `http://127.0.0.1:${port}`;
  try {
    const health = await waitForHealth(baseUrl);
    return {
      baseUrl,
      health,
      log: () => log,
      async stop() {
        child.kill('SIGTERM');
        await new Promise((done) => {
          child.on('exit', done);
          setTimeout(() => {
            child.kill('SIGKILL');
            done();
          }, 3000);
        });
      },
    };
  } catch (error) {
    child.kill('SIGKILL');
    throw new Error(`${error.message}\nserver output:\n${log}`);
  }
}

/**
 * Load `index.html` into the stub DOM and route relative `fetch` calls (the
 * URLs the page actually uses, e.g. `api/health`) to the engine base URL.
 * Returns the document handles plus a restore function.
 */
export async function loadPage(baseUrl) {
  const html = await readFile(join(FRONTEND_ROOT, 'index.html'), 'utf8');
  const handles = installDocument(html);

  const realFetch = globalThis.fetch;
  globalThis.fetch = (input, init) => {
    if (typeof input === 'string' && !/^[a-z]+:\/\//i.test(input)) {
      return realFetch(`${baseUrl}/${input.replace(/^\/+/, '')}`, init);
    }
    return realFetch(input, init);
  };

  globalThis.document = handles.document;
  globalThis.window = handles.window;
  globalThis.Node = handles.root.constructor;
  globalThis.NodeStub = handles.root.constructor;

  return {
    ...handles,
    /**
     * Restore the real `fetch`.  The DOM globals are intentionally left in
     * place: the application has asynchronous work in flight (routing and
     * requests started by the last interaction), and pulling the globals out
     * from under it would only produce noise while the test process is about to
     * exit anyway.
     */
    restore() {
      globalThis.fetch = realFetch;
    },
  };
}

/** Wait until `predicate()` is truthy, or fail with `message`. */
export async function waitFor(predicate, message, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    // eslint-disable-next-line no-await-in-loop
    const value = await predicate();
    if (value) return value;
    // eslint-disable-next-line no-await-in-loop
    await new Promise((done) => setTimeout(done, 25));
  }
  throw new Error(`timed out waiting for ${message}`);
}

/** Give queued promise callbacks a chance to run. */
export function settle(ms = 40) {
  return new Promise((done) => setTimeout(done, ms));
}
