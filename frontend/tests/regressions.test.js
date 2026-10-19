/**
 * Regression tests for the interface defects confirmed by the hostile audit.
 *
 * Each test reproduces a failure that was observed in the running application
 * (headless Chromium + CDP) against the *previous* code, and asserts the
 * documented behaviour instead.  The harness is the same one the other
 * interface tests use: a real engine, the real `index.html`, the real modules.
 */

import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import { loadPage, settle, startEngine, waitFor } from './harness.js';

const PROGRAM = `int main() {
  string name = input();
  system(name);
  return 0;
}
`;

let engine;
let page;

function go(route) {
  page.window.location.hash = `#/${route}`;
  page.window.dispatchEvent({ type: 'hashchange' });
  return settle(60);
}

function text(route) {
  return page.document.getElementById(`view-${route}`).textContent;
}

function banner() {
  return page.document.getElementById('global-error');
}

async function analyse(source = PROGRAM, filename = 'regress.ctc') {
  await go('analyze');
  page.document.getElementById('source-input').value = source;
  page.document.getElementById('filename-input').value = filename;
  page.document.getElementById('analyze-button').click();
  await waitFor(
    () => page.document.getElementById('analyze-status').textContent.includes('Analysed'),
    'the analysis to finish',
    30000,
  );
  const { state } = await import('../js/state.js');
  return state.run;
}

before(async () => {
  engine = await startEngine();
  page = await loadPage(engine.baseUrl);
  await import('../js/app.js');
  await waitFor(
    () => page.document.getElementById('engine-status').textContent.includes('engine '),
    'the engine status badge',
  );
});

after(async () => {
  if (page) page.restore();
  if (engine) await engine.stop();
});

test('opening Program Graph with no run shows an empty state and no error banner', async () => {
  // Before: `state.run.summary` was read without checking `state.run`, the
  // throw was caught by the router, and the global banner claimed
  // "Cannot read properties of null (reading 'summary')" on every later route.
  const { resetRun } = await import('../js/state.js');
  resetRun();
  await go('graph');
  assert.equal(banner().hidden, true, 'no global error banner without a run');
  assert.match(text('graph'), /No analysis has run yet/);
});

test('a banner raised on one route does not survive the move to another', async () => {
  const { resetRun } = await import('../js/state.js');
  resetRun();
  await go('graph');            // previously raised the sticky banner
  await go('overview');
  assert.equal(banner().hidden, true, 'the banner must not be sticky across routes');
});

test('the security slice of a finding names its line instead of "undefined"', async () => {
  await analyse();
  await go('findings');
  await page.document.querySelector('.finding-card__select').click();
  await waitFor(
    () => page.document.getElementById('finding-detail').textContent.includes('Security slice'),
    'the finding detail',
  );
  const { state, update } = await import('../js/state.js');
  const finding = state.run.findings[0];
  update({ slicing: { ...state.slicing, source: 'finding', data: null, error: null } });
  await go('slicing');
  await waitFor(
    () => page.document.getElementById('slicing-body').textContent.includes('slice ('),
    'the security slice',
    20000,
  );
  const body = page.document.getElementById('slicing-body');
  assert.match(body.textContent, new RegExp(`line ${finding.sink.line}:`));
  assert.doesNotMatch(body.textContent, /undefined/);
  assert.equal(state.slicing.data.criterion.line, finding.sink.line);
});

test('the findings Source context shows the analysed text, not a later draft', async () => {
  await analyse();
  await go('findings');
  await page.document.querySelector('.finding-card__select').click();
  await waitFor(
    () => page.document.getElementById('finding-detail').textContent.includes('Source context'),
    'the finding detail',
  );
  const detail = page.document.getElementById('finding-detail');
  const analysedText = detail.textContent;
  // Edit the editor: the draft now differs from the analysed source.
  await go('analyze');
  const editor = page.document.getElementById('source-input');
  editor.value = '// something else entirely\nint main() { return 0; }\n';
  editor.dispatchEvent({ type: 'input', target: editor });
  await settle();
  await go('findings');
  await settle();
  assert.equal(
    page.document.getElementById('finding-detail').textContent.includes('something else entirely'),
    false,
    'the draft must not be shown as the finding context',
  );
  assert.ok(analysedText.includes('input()'));
  assert.match(
    page.document.getElementById('finding-detail').textContent,
    /The editor has changed since this run/,
  );
});

test('a slow finding-detail response cannot replace a newer selection', async () => {
  const run = await analyse(
    `int main() {\n  string a = input();\n  system(a);\n  string b = input();\n  printf(b);\n  return 0;\n}\n`,
    'race.ctc',
  );
  assert.ok(run.findings.length >= 2, 'the program needs two findings');
  await go('findings');
  const { state } = await import('../js/state.js');

  // Delay the *first* detail request so it resolves after the second one.
  const realFetch = globalThis.fetch;
  let delayed = 0;
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    if (/\/findings\/[A-Z0-9]+$/.test(url) && delayed === 0) {
      delayed += 1;
      await new Promise((done) => setTimeout(done, 400));
    }
    return realFetch(input, init);
  };
  try {
    const buttons = [...page.document.querySelectorAll('.finding-card__select')];
    assert.ok(buttons.length >= 2);
    const first = run.findings[0].id;
    const second = run.findings[1].id;
    buttons[0].click();
    await settle(30);
    buttons[1].click();
    await waitFor(
      () => state.selectedFindingDetail && state.selectedFindingDetail.id === second,
      'the second finding detail',
      10000,
    );
    await settle(500);                       // let the delayed response land
    assert.equal(state.selectedFinding, second);
    assert.equal(
      state.selectedFindingDetail.id,
      second,
      'the delayed response for the first finding must not be painted',
    );
  } finally {
    globalThis.fetch = realFetch;
  }
});

test('text typed during an analysis is kept and the mismatch is stated', async () => {
  const { state } = await import('../js/state.js');
  await go('analyze');
  const editor = page.document.getElementById('source-input');
  editor.value = PROGRAM;
  page.document.getElementById('filename-input').value = 'dirty.ctc';

  const realFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    if (String(input).includes('api/analyze')) {
      await new Promise((done) => setTimeout(done, 300));
    }
    return realFetch(input, init);
  };
  try {
    page.document.getElementById('analyze-button').click();
    await settle(60);                        // the request is in flight now
    editor.value = '// typed while the analysis was running\nint main() { return 0; }\n';
    editor.dispatchEvent({ type: 'input', target: editor });
    await waitFor(
      () => page.document.getElementById('analyze-status').textContent.includes('submitted'),
      'the mismatch notice',
      20000,
    );
    assert.equal(state.editorDirty, true);
    await go('analyze');
    assert.equal(
      page.document.getElementById('source-input').value,
      '// typed while the analysis was running\nint main() { return 0; }\n',
      'the draft must survive the response',
    );
    assert.equal(state.analysedSource, PROGRAM, 'the run records the analysed text');
  } finally {
    globalThis.fetch = realFetch;
  }
});

test('a validation result does not stand for text that was never validated', async () => {
  await go('rules');
  const editor = page.document.getElementById('rule-editor');
  page.document.getElementById('load-rule-example-button').click();
  await waitFor(() => editor.value.length > 20, 'the example rule file');
  page.document.getElementById('validate-rules-button').click();
  await waitFor(
    () => page.document.getElementById('rules-diagnostics').textContent.includes('Validation result'),
    'the validation result',
    20000,
  );
  editor.value = 'this is not a rule file';
  editor.dispatchEvent({ type: 'input', target: editor });
  await settle(60);
  assert.match(
    page.document.getElementById('rules-diagnostics').textContent,
    /The editor has changed since this validation/,
  );
});

test('the theme control switches light/dark/system and is remembered', async () => {
  // The stub DOM has no storage; give it one so the persistence path is real.
  const store = new Map();
  if (!page.window.localStorage) {
    page.window.localStorage = {
      getItem: (key) => (store.has(key) ? store.get(key) : null),
      setItem: (key, value) => store.set(key, String(value)),
      removeItem: (key) => store.delete(key),
    };
  }
  await go('overview');
  const toggle = page.document.getElementById('theme-toggle');
  assert.match(toggle.textContent, /Theme: (light|dark|system)/);
  const seen = new Set();
  for (let i = 0; i < 4; i += 1) {
    const label = toggle.textContent.replace('Theme: ', '').trim();
    seen.add(label);
    if (label === 'dark') {
      assert.equal(page.document.body.classList.contains('dark'), true, 'dark applies the dark palette');
    }
    toggle.click();
    await settle(20);
  }
  assert.deepEqual([...seen].sort(), ['dark', 'light', 'system']);
  assert.equal(store.get('codetrace.theme'), toggle.textContent.replace('Theme: ', '').trim());
});

test('the high-contrast switch still works and is a separate control', async () => {
  await go('overview');
  const contrast = page.document.getElementById('contrast-toggle');
  assert.ok(contrast, 'the high-contrast control still exists');
  const before = page.document.body.classList.contains('contrast');
  contrast.click();
  await settle(20);
  assert.equal(page.document.body.classList.contains('contrast'), !before);
});

test('selecting no edge kind says so instead of drawing every edge', async () => {
  await analyse();
  await go('graph');
  const checkboxes = () => [...page.document.querySelectorAll('#graph-toolbar input')]
    .filter((node) => node.getAttribute('type') === 'checkbox');
  await waitFor(() => checkboxes().length > 0, 'the edge-kind checkboxes');
  const boxes = checkboxes();
  for (const box of boxes) {
    if (box.checked) {
      box.checked = false;
      box.dispatchEvent({ type: 'change', target: box });
      await settle(40);
    }
  }
  await settle(200);
  assert.match(text('graph'), /No edge kinds are selected/);
  const selectAll = [...page.document.querySelectorAll('#graph-canvas button')]
    .find((button) => /Select all edge kinds/.test(button.textContent));
  assert.ok(selectAll, 'the way back to a full graph is offered');
});

test('the finding card marks the selection with an allowed attribute', async () => {
  await analyse();
  await go('findings');
  await page.document.querySelector('.finding-card__select').click();
  await settle(80);
  const cards = [...page.document.querySelectorAll('.finding-card')];
  assert.ok(cards.length >= 1);
  for (const card of cards) {
    assert.equal(card.getAttribute('aria-selected'), null, 'aria-selected is not allowed on <li>');
  }
  assert.equal(cards[0].getAttribute('aria-current'), 'true');
});

test('the source pane is reachable with the keyboard', async () => {
  await analyse();
  await go('findings');
  await page.document.querySelector('.finding-card__select').click();
  await waitFor(
    () => page.document.getElementById('finding-detail').textContent.includes('Source context'),
    'the finding detail',
  );
  const pane = page.document.querySelector('.source');
  assert.ok(pane, 'the source pane renders');
  assert.equal(pane.getAttribute('tabindex'), '0');
});

test('a graph node draws text that appears in its accessible name', async () => {
  // WCAG 2.5.3 (Label in Name): the visible text must be included in the accessible
  // name.  The nodes used to carry the untruncated label plus "(line N)", so the text
  // actually drawn -- the shortened label followed by "line N" -- was not a substring
  // of the name and axe reported label-content-name-mismatch on every node button.
  await analyse();
  await go('graph');
  const canvas = page.document.getElementById('graph-canvas');
  // The earlier edge-kind test deliberately leaves every kind unchecked, and the graph
  // then states that instead of drawing.  Restore the selection through the documented
  // affordance so this test measures the nodes, not the empty-kind state.
  const selectAll = [...canvas.querySelectorAll('button')]
    .find((button) => /select all/i.test(button.textContent));
  if (selectAll) {
    selectAll.click();
    await settle(60);
  }
  // The test DOM shim does not implement attribute selectors, so the node groups are
  // found the same way views.test.js finds them: all <g> elements that carry a name.
  await waitFor(
    () => canvas.querySelectorAll('g').some((group) => group.getAttribute('aria-label')),
    'a graph node',
    20000,
  );
  const nodes = canvas.querySelectorAll('g').filter((group) => group.getAttribute('aria-label'));
  assert.ok(nodes.length >= 1, 'the graph drew node buttons');
  for (const node of nodes) {
    // Compared the way axe compares it: the drawn text has to appear in the
    // accessible name as written, not merely the same words in another order.
    const name = node.getAttribute('aria-label');
    const visible = node.textContent;
    assert.ok(visible.trim().length > 0, 'the node draws text');
    assert.ok(
      name.includes(visible),
      `the accessible name ${JSON.stringify(name)} does not contain ` +
      `the drawn text ${JSON.stringify(visible)}`,
    );
  }
});

test('a primary button keeps its accent background while hovered', async () => {
  // .button:hover (0,2,0) outranks .button--primary (0,1,0).  Without an explicit hover
  // background the pointer turned the primary button into white text on the page
  // background: axe measured a contrast of 1.12 on an enabled control.
  const stylesheet = await readFile(new URL('../css/app.css', import.meta.url), 'utf8');
  const primaryHover = stylesheet.match(/\.button--primary:hover\s*\{([^}]*)\}/);
  assert.ok(primaryHover, '.button--primary:hover is declared');
  assert.match(primaryHover[1], /background:\s*var\(--accent\)/,
    'the primary hover rule sets the accent background itself');
  assert.match(primaryHover[1], /brightness/, 'the hover affordance is kept');
});
