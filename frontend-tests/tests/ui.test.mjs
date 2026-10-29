/**
 * Scripted-DOM regression suite for the CodeTrace frontend.
 *
 * Pins the behaviours fixed in the 2026-10 audit (defects D3/D4/D5/D7/D8/D14
 * and the slice-truncation notice): real ES modules, real HTTP against the
 * real Python API — but jsdom, NOT a real browser.  Visual/layout/contrast
 * checks live in docs/MANUAL_BROWSER_VERIFICATION.md.
 *
 * Tests share one booted app instance and therefore run in file order.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { ROOT, buildApp, settle, startServer, until } from '../helpers.mjs';

const VULNERABLE = [
  '// untrusted input reaches a command sink',
  'int main() {',
  '  string name = input();',
  '  system(name);',
  '  return 0;',
  '}',
].join('\n');

const SANITIZED = [
  'int main() {',
  '  string name = input();',
  '  string safe = shell_escape(name);',
  '  system(safe);',
  '  return 0;',
  '}',
].join('\n');

let H;
let server;

test.before(async () => {
  server = await startServer();
  H = await buildApp(server.base);
});

test.after(() => {
  if (server) server.child.kill();
  if (H) H.dom.window.close();
});

test('boot: overview visible, engine status populated, nine views reachable', async () => {
  assert.equal(H.visibleView(), 'view-overview');
  assert.match(H.text('#engine-status'), /rules/);
  assert.match(H.text('#engine-status'), /states/);
  assert.equal(H.qa('#nav-list a[data-route]').length, 9);
});

test('analyze: vulnerable program reports a finding end to end', async () => {
  await H.navigate('analyze');
  const runId = await H.analyse(VULNERABLE, 'vuln.ctc');
  assert.match(runId, /^[0-9a-f]{16}$/);
  assert.match(H.text('#analyze-summary'), /findings/);
  await H.navigate('findings');
  await until(() => H.qa('.finding-card').length >= 1, { label: 'finding card' });
  assert.match(H.text('#findings-list'), /command-injection/);
});

test('findings filter: changing severity changes the list (not just the widget)', async () => {
  const severity = H.qa('#findings-toolbar select')
    .find((select) => Array.from(select.options).some((o) => o.value === 'LOW'));
  assert.ok(severity, 'severity select exists');
  H.changeSelect(severity, 'LOW');
  await until(() => /No finding matches/.test(H.text('#findings-list') || ''), { label: 'empty filter result' });
  H.changeSelect(severity, '');
  await until(() => H.qa('.finding-card').length >= 1, { label: 'cards restored' });
});

test('D14/D4: example picker lists only .ctc programs and its notice survives navigation', async () => {
  await H.navigate('analyze');
  H.click('#load-example-button');
  await until(() => H.q('#modal-root .modal'), { label: 'example modal' });
  // The list is fetched asynchronously; wait for it instead of counting the
  // spinner.  Buttons carry the example's *name* (basename); the picker must
  // offer programs only — the corpus's .ctrule file belongs to the Rule
  // Editor's own button (defect D14).
  await until(() => H.qa('#modal-root .modal__list button').length >= 30,
    { label: 'example list loaded' });
  const exampleButtons = H.qa('#modal-root .modal__list button');
  for (const button of exampleButtons) {
    assert.ok(button.textContent.trim().endsWith('.ctc'),
      `picker must not offer non-programs: ${button.textContent.trim()}`);
    assert.ok(!button.textContent.includes('.ctrule'));
  }
  assert.ok(!H.text('#modal-root').includes('.ctrule'), 'no rule file anywhere in the picker');
  const wanted = exampleButtons.find((b) => b.textContent.trim() === 'command_injection.ctc');
  assert.ok(wanted, 'command_injection.ctc is offered');
  H.click(wanted);
  await until(() => (H.q('#source-input').value || '').includes('system'), { label: 'editor filled' });
  // The repaint after the pick is asynchronous; wait for the notice itself.
  await until(() => /Loaded vulnerable\/command_injection\.ctc/.test(H.text('#analyze-status') || ''),
    { label: 'loaded notice' });
  assert.match(H.text('#analyze-status'), /1 finding/);
  // The notice is state-held: navigating away and back must not wipe it.
  await H.navigate('overview');
  await H.navigate('analyze');
  assert.match(H.text('#analyze-status'), /Loaded vulnerable\/command_injection\.ctc/);
  // Close the modal for the rest of the suite.
  H.window.document.dispatchEvent(new H.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await settle(200);
});

test('D4: rule-editor hand-off confirmation survives the hash change', async () => {
  await H.navigate('rules');
  const ruleText = 'version 1\nsink broken { function system arguments 0 context command }\n';
  H.type('#rule-editor', ruleText);
  H.click('#analyze-with-rules-button');
  await until(() => H.window.location.hash === '#/analyze', { label: 'hand-off navigation' });
  await settle(300);
  assert.match(H.text('#analyze-status'), /custom rules box/);
  assert.equal(H.q('#rules-input').value, ruleText);
  // Empty the custom-rules box again: later tests analyse with builtin rules.
  H.type('#rules-input', '');
});

test('D5: navigating away mid-analysis keeps the result', async () => {
  await H.navigate('analyze');
  H.type('#source-input', VULNERABLE);
  H.click('#analyze-button');
  await H.navigate('overview'); // while the request is in flight
  await until(() => !/No analysis has run/.test(H.text('#overview-run') || ''), {
    label: 'overview shows the landed run',
  });
  assert.match(H.text('#overview-run'), /command-injection|finding|run/i);
});

test('D3: "Show in Program Graph" focuses exactly the finding\'s node', async () => {
  await H.navigate('findings');
  await until(() => H.qa('.finding-card').length >= 1, { label: 'finding card' });
  H.click('.finding-card__select');
  await until(() => /Show in Program Graph/.test(H.text('#finding-detail') || ''), { label: 'detail actions' });
  const show = H.qa('#finding-detail button').find((b) => b.textContent.includes('Show in Program Graph'));
  H.click(show);
  await until(() => H.visibleView() === 'view-graph', { label: 'graph view' });
  await until(() => H.qa('.node--focus').length === 1, { label: 'exactly one focused node' });
  assert.match(H.window.document.body.textContent, /Focused finding/);
});

test('D7: function-level mode shows only its own controls and an honest empty state', async () => {
  const modeSelect = H.q('#graph-toolbar select');
  H.changeSelect(modeSelect, 'function');
  await until(() => /no calls or returns/.test(H.text('#graph-canvas') || ''), { label: 'function empty state' });
  assert.equal(H.qa('#graph-toolbar input[type="checkbox"]').length, 0,
    'kind checkboxes belong to dependency mode only');
  H.changeSelect(modeSelect, 'dependency');
  await until(() => H.qa('#graph-toolbar input[type="checkbox"]').length > 0, { label: 'kind checkboxes' });
});

test('D8: comparison renders records and the fixed filter routes to the earlier run', async () => {
  const runA = await H.analyse(VULNERABLE, 'before.ctc');
  const runB = await H.analyse(SANITIZED, 'after.ctc');
  await H.navigate('reports');
  await until(() => H.q('#compare-before'), { label: 'comparison controls' });
  H.changeSelect(H.q('#compare-before'), runA);
  H.changeSelect(H.q('#compare-after'), runB);
  H.click('#compare-button');
  await until(() => /Resolved findings/.test(H.text('#reports-body') || ''), { label: 'comparison records' });
  assert.match(H.text('#reports-body'), /New findings/);
  assert.ok(H.qa('#reports-body .compare-list li').length >= 1, 'resolved record rows are rendered');
  assert.match(H.text('#reports-body'), /command_execution/);

  await H.navigate('findings');
  const statusSelect = H.qa('#findings-toolbar select')
    .find((select) => Array.from(select.options).some((o) => o.value === 'fixed'));
  assert.ok(statusSelect, 'status filter exists once a comparison is loaded');
  H.changeSelect(statusSelect, 'fixed');
  await until(() => /resolved finding\(s\) from the earlier run/.test(
    H.text('#findings-toolbar .findings-count') || ''), { label: 'fixed count line' });
  assert.match(H.text('#findings-toolbar .findings-count'), new RegExp(runA));
  await until(() => H.qa('.finding-card').length >= 1, { label: 'resolved card' });
  const before = H.requests.length;
  H.click('.finding-card__select');
  await until(() => /earlier run/.test(H.text('#finding-detail') || ''), { label: 'earlier-run note' });
  assert.ok(
    H.requests.slice(before).some((r) => r.includes(`/api/runs/${runA}/findings/`)),
    `detail must be fetched from the earlier run: ${H.requests.slice(before).join(', ')}`);
  assert.ok(!H.qa('#finding-detail button').some((b) => b.textContent.includes('Show in Program Graph')),
    'graph/slice actions of the current run are withheld for an earlier-run finding');
  H.changeSelect(statusSelect, 'open');
  await settle(300);
});

test('slicing view discloses detail-table truncation (D23)', async () => {
  // View-level render check with an injected payload: the API-side flag is
  // pinned by tests/test_api_contract.py; this is the UI half of the contract.
  const { renderSlicing } = await import(pathToFileURL(path.join(ROOT, 'frontend', 'js', 'views', 'slicing.js')).href);
  const container = H.q('#view-slicing');
  const fakeState = {
    run: { run_id: 'aaaaaaaaaaaaaaaa' },
    statementsById: { 0: 'int a = 1;', 1: 'int b = a;', 2: 'int c = b;' },
    statementDetail: null,
    slicing: {
      sid: 1,
      direction: 'backward',
      source: 'statement',
      data: {
        kind: 'backward',
        statements: [0, 1, 2],
        statements_detail: [
          { sid: 0, line: 1, col: 1, function: 'main', text: 'int a = 1;' },
          { sid: 1, line: 2, col: 1, function: 'main', text: 'int b = a;' },
        ],
        statements_detail_truncated: true,
        reasons: {},
        criterion: { text: 'int c = b;', line: 3 },
        note: 'conservative',
        truncated: false,
        subgraph: { nodes: [], edges: [] },
      },
    },
  };
  renderSlicing(container, {
    state: fakeState,
    onCriterion: () => {},
    onDirection: () => {},
    onSelectStatement: () => {},
  });
  await settle(100);
  assert.match(container.textContent, /first 2 of 3 statements/);
});
