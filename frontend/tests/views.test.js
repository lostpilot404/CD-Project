/**
 * Interface integration tests.
 *
 * These tests load the real `index.html` into the stub DOM, import the real
 * `js/app.js` and talk to a real engine started with `python3 -m codetrace.api`.
 * Nothing is mocked except the DOM: every number, finding, graph, slice and
 * report the views display is produced by the analysis engine over HTTP, which
 * is exactly the path a browser takes.
 *
 * Run with `node --test frontend/tests/` (or `npm test` inside `frontend/`).
 */

import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';

import { loadPage, settle, startEngine, waitFor } from './harness.js';

const PROGRAM = `// A program with two flows: one command injection, one format string.
string build_command(string value) {
  return "ls " + value;
}

int main() {
  string name = input();
  string cmd = build_command(name);
  system(cmd);
  string safe = "ls /tmp";
  system(safe);
  printf(name);
  return 0;
}
`;

const ROUTES = ['overview', 'analyze', 'findings', 'graph', 'dataflow', 'slicing', 'rules', 'reports', 'documentation'];

let engine;
let page;

function viewText(route) {
  return page.document.getElementById(`view-${route}`).textContent;
}

function go(route) {
  page.window.location.hash = `#/${route}`;
  page.window.dispatchEvent({ type: 'hashchange' });
  return settle(30);
}

before(async () => {
  engine = await startEngine();
  page = await loadPage(engine.baseUrl);
  await import('../js/app.js'); // boots the interface (routing, status, first render)
  await waitFor(
    () => page.document.getElementById('engine-status').textContent.includes('engine '),
    'the engine status badge',
  );
});

after(async () => {
  if (page) page.restore();
  if (engine) await engine.stop();
});

test('the page boots, reports the engine version and the grammar facts', () => {
  const status = page.document.getElementById('engine-status').textContent;
  assert.match(status, new RegExp(engine.health.engine_version.replace(/\./g, '\\.')));
  // Regression: the badge once read grammar.states (absent from the API) and
  // showed "undefined states"; the old pattern matched that by accident.
  assert.match(status, /(^|\s)\d+ states \/ \d+ conflicts/);
  assert.doesNotMatch(status, /undefined|NaN|null/);
  assert.equal(page.document.getElementById('global-error').hidden, true);
  assert.ok(viewText('overview').length > 80, 'the overview is not an empty page');
});

test('every navigation destination renders content (no empty pages)', async () => {
  for (const route of ROUTES) {
    // eslint-disable-next-line no-await-in-loop
    await go(route);
    const view = page.document.getElementById(`view-${route}`);
    assert.equal(view.hidden, false, `${route} is shown`);
    assert.ok(viewText(route).trim().length > 40, `${route} has content`);
    for (const other of ROUTES) {
      if (other !== route) assert.equal(page.document.getElementById(`view-${other}`).hidden, true);
    }
    const navCurrent = page.document
      .querySelectorAll('#nav-list a')
      .filter((link) => link.getAttribute('aria-current') === 'page');
    assert.equal(navCurrent.length, 1, `${route} is marked as current in the navigation`);
    assert.equal(navCurrent[0].dataset.route, route);
  }
});

test('the navigation is complete: every route has a link and every link a route', () => {
  const links = page.document.querySelectorAll('#nav-list a').map((link) => link.dataset.route);
  assert.deepEqual([...links].sort(), [...ROUTES].sort());
  for (const link of page.document.querySelectorAll('#nav-list a')) {
    assert.ok(link.getAttribute('href').startsWith('#/'), 'links are hash routes');
    assert.ok(link.textContent.trim().length > 2);
  }
});

test('running an analysis uses the real engine and reports findings', async () => {
  await go('analyze');
  const editor = page.document.getElementById('source-input');
  editor.value = PROGRAM;
  page.document.getElementById('filename-input').value = 'ui-fixture.ctc';
  page.document.getElementById('use-builtin').checked = true;
  page.document.getElementById('run-dependencies').checked = true;
  page.document.getElementById('analyze-button').click();

  await waitFor(
    () => page.document.getElementById('analyze-status').textContent.includes('run '),
    'the analysis to finish',
    30000,
  );
  const status = page.document.getElementById('analyze-status').textContent;
  assert.match(status, /ui-fixture\.ctc/);
  const summary = page.document.getElementById('analyze-summary').textContent;
  assert.match(summary, /findings\s*2/);
  assert.match(summary, /HIGH/);

  const { state } = await import('../js/state.js');
  assert.ok(state.run, 'the run is stored in the interface state');
  assert.equal(state.run.filename, 'ui-fixture.ctc');
  assert.equal(state.run.findings.length, 2, 'the engine reported both flows');
  assert.deepEqual(
    state.run.findings.map((finding) => finding.category).sort(),
    ['command-injection', 'format-string'],
  );
  assert.deepEqual([...state.run.summary.functions].sort(), ['build_command', 'main']);
  assert.equal(state.run.metrics.functions, 2, 'metrics.functions is the function count');
  assert.ok(state.run.run_id.length >= 12);
});

test('the findings view lists findings and opens the evidence for one', async () => {
  await go('findings');
  const list = page.document.getElementById('findings-list');
  const toolbar = page.document.getElementById('findings-toolbar');
  await waitFor(() => toolbar.textContent.includes('2 of 2 finding'), 'the findings list');
  assert.ok(list.querySelectorAll('.finding-card').length === 2, 'both findings are listed');
  const text = list.textContent;
  assert.match(text, /command-injection/);
  assert.match(text, /format-string/);
  assert.match(text, /HIGH/);

  const card = page.document.querySelectorAll('#findings-list .finding-card__select')[0];
  assert.ok(card, 'each finding is selectable');
  card.click();

  const detail = page.document.getElementById('finding-detail');
  await waitFor(
    () => detail.querySelectorAll('.evidence-path li').length >= 5,
    'the evidence path from the finding endpoint',
  );
  const detailText = detail.textContent;
  assert.match(detailText, /Evidence path/);
  assert.match(detailText, /Why this was reported/);
  assert.match(detailText, /potential .* flow detected/i);
  assert.match(detailText, /Remediation/);
  assert.match(detailText, /Limitations of this finding/);
  assert.match(detailText, /line 9/, 'the sink line is shown');
  assert.match(detailText, /Source context/);
});

test('filtering the findings does not recompute anything and can empty the list', async () => {
  await go('findings');
  const select = page.document.querySelectorAll('#findings-toolbar select')[0];
  assert.ok(select, 'the severity filter exists');
  select.value = 'CRITICAL';
  select.dispatchEvent({ type: 'change', target: select });
  await waitFor(
    () => page.document.getElementById('findings-list').textContent.includes('No finding matches the current filters'),
    'the filtered empty state',
  );
  const second = page.document.querySelectorAll('#findings-toolbar select')[0];
  second.value = 'HIGH';
  second.dispatchEvent({ type: 'change', target: second });
  await waitFor(
    () => page.document.getElementById('findings-toolbar').textContent.includes('1 of 2 finding'),
    'the HIGH-only list',
  );
  assert.equal(page.document.querySelectorAll('#findings-list .finding-card').length, 1);
  // Reset the filter for the tests that follow.
  const reset = page.document.querySelectorAll('#findings-toolbar select')[0];
  reset.value = '';
  reset.dispatchEvent({ type: 'change', target: reset });
  await waitFor(
    () => page.document.getElementById('findings-toolbar').textContent.includes('2 of 2 finding'),
    'the unfiltered list',
  );
});

test('the program graph view draws the dependency graph from the engine', async () => {
  await go('graph');
  const canvas = page.document.getElementById('graph-canvas');
  await waitFor(() => canvas.querySelector('svg'), 'the graph svg', 20000);
  const svg = canvas.querySelector('svg');
  const { state } = await import('../js/state.js');
  const nodes = canvas.querySelectorAll('g').filter((group) => group.getAttribute('aria-label'));
  assert.equal(nodes.length, state.graph.data.nodes.length, 'one group per returned node');
  assert.match(svg.getAttribute('viewBox'), /^0 0 \d+(\.\d+)? \d+(\.\d+)?$/);
  assert.match(svg.getAttribute('aria-label'), /Program graph with \d+ nodes/);
  assert.match(canvas.textContent, /Graph: \d+ node\(s\), \d+ edge\(s\) shown/);
  assert.ok(page.document.getElementById('graph-side').textContent.includes('Legend'));

  // Selecting a statement node loads that statement's results into the side panel.
  const statementNode = nodes.find((group) => group.getAttribute('aria-label').startsWith('statement '));
  assert.ok(statementNode, 'the graph contains statement nodes');
  statementNode.click();
  await waitFor(
    () => page.document.getElementById('graph-side').textContent.includes('Reaching definitions'),
    'the statement detail',
    20000,
  );
  assert.match(page.document.getElementById('graph-side').textContent, /Live variables/);
});

test('the data-flow view shows both equations and the block states', async () => {
  await go('dataflow');
  const body = page.document.getElementById('dataflow-body');
  await waitFor(() => body.textContent.includes('Reaching definitions'), 'the data-flow table', 20000);
  assert.match(body.textContent, /OUT = GEN ∪ \(IN − KILL\)/);
  assert.match(page.document.getElementById('dataflow-toolbar').textContent, /Function/);
  assert.ok(body.querySelectorAll('table').length >= 1, 'block states are tabulated');

  // Switching the analysis switches the equations and the direction.
  const selects = page.document.querySelectorAll('#dataflow-toolbar select');
  const analysis = selects[selects.length - 1];
  analysis.value = 'liveness';
  analysis.dispatchEvent({ type: 'change', target: analysis });
  await waitFor(
    () => page.document.getElementById('dataflow-body').textContent.includes('Live variables'),
    'the liveness table',
  );
  assert.match(
    page.document.getElementById('dataflow-body').textContent,
    /IN = USE ∪ \(OUT − DEF\)/,
  );
});

test('the slicing view defaults to the sink of the first finding and lists the slice', async () => {
  const { state } = await import('../js/state.js');
  await go('slicing');
  const body = page.document.getElementById('slicing-body');
  await waitFor(() => body.textContent.includes('slice ('), 'a computed slice', 20000);
  assert.match(body.textContent, /Statements in the slice/);
  assert.match(body.textContent, /why it is included/);
  assert.match(body.textContent, /line 9/, 'the default criterion is the reported sink');
  assert.equal(Number(state.slicing.sid), state.run.findings[0].sink.sid);

  // Changing the direction recomputes the slice through the engine.
  const direction = page.document.querySelectorAll('#slicing-toolbar select')[1];
  direction.value = 'forward';
  direction.dispatchEvent({ type: 'change', target: direction });
  await waitFor(
    () => page.document.getElementById('slicing-body').textContent.includes('forward slice'),
    'the forward slice',
  );
});

test('the rule editor validates a rule file with the engine and rejects a broken one', async () => {
  await go('rules');
  assert.ok(page.document.getElementById('rules-active').textContent.includes('source'), 'active rules are listed');
  assert.match(page.document.getElementById('rules-grammar').textContent, /\d+ productions, \d+ states, 0 conflicts/);

  // The example rule file is loaded through the interface (its own button and
  // the example endpoint), then validated by the engine's rule parser.
  const editor = page.document.getElementById('rule-editor');
  page.document.getElementById('load-rule-example-button').click();
  await waitFor(() => editor.value.includes('version 1'), 'the example rule file');
  assert.match(editor.value, /source request_body/, 'the example declares a source');
  page.document.getElementById('validate-rules-button').click();
  await waitFor(
    () => page.document.getElementById('rules-status').textContent.includes('Valid:'),
    'the validation result',
    20000,
  );
  assert.match(page.document.getElementById('rules-status').textContent, /1 source\(s\)/);

  editor.value = 'version 1\nsink\n';
  page.document.getElementById('validate-rules-button').click();
  const diagnostics = page.document.getElementById('rules-diagnostics');
  await waitFor(
    () => page.document.getElementById('rules-status').textContent.includes('Rejected'),
    'the rejection',
  );
  assert.match(diagnostics.textContent, /Validation result/);
  assert.match(diagnostics.textContent, /RULE\d+|SYN\d+/, 'a diagnostic code is shown');
  assert.match(diagnostics.textContent, /\d+:\d+/, 'the diagnostic carries line:col');
});

test('the reports view offers both exports and compares two runs by identity', async () => {
  await go('reports');
  const body = page.document.getElementById('reports-body');
  await waitFor(() => body.textContent.includes('Download JSON report'), 'the export links');
  const links = body.querySelectorAll('a').map((link) => link.getAttribute('href'));
  assert.ok(links.some((href) => href.includes('format=json')), 'json download link');
  assert.ok(links.some((href) => href.includes('format=html')), 'html report link');

  const { state } = await import('../js/state.js');
  const before = page.document.getElementById('compare-before');
  const after = page.document.getElementById('compare-after');
  before.value = state.run.run_id;
  after.value = state.run.run_id;
  page.document.getElementById('compare-button').click();
  await waitFor(() => page.document.getElementById('reports-body').textContent.includes('persistent'), 'the comparison', 20000);
  const text = page.document.getElementById('reports-body').textContent;
  assert.match(text, /new/);
  assert.match(text, /resolved/);
  assert.match(text, /moved/);
  assert.equal(state.comparison.summary.new, 0);
  assert.equal(state.comparison.summary.persistent, 2);
});

test('the status filter separates fixed from open findings after a comparison', async () => {
  await go('findings');
  const withStatus = () =>
    page.document.querySelectorAll('#findings-toolbar select')
      .find((select) => select.children.some((option) => option.getAttribute('value') === 'fixed'));
  const status = withStatus();
  assert.ok(status, 'the status filter appears once two runs have been compared');
  status.value = 'fixed';
  status.dispatchEvent({ type: 'change', target: status });
  await waitFor(
    () => page.document.getElementById('findings-list').textContent.includes('No finding matches the current filters'),
    'the fixed filter (the comparison resolved nothing, so no finding is fixed)',
  );
  const again = withStatus();
  again.value = 'open';
  again.dispatchEvent({ type: 'change', target: again });
  await waitFor(
    () => !page.document.getElementById('findings-list').textContent.includes('No finding matches the current filters'),
    'open findings are still listed',
  );
  const text = page.document.getElementById('findings-list').textContent;
  assert.match(text, /command-injection/, 'the open findings are the ones from this run');
});

test('the status filter explains itself before any comparison was made', async () => {
  await import('../js/state.js').then(({ update }) => update({ comparison: null }));
  await go('findings');
  const toolbar = page.document.getElementById('findings-toolbar');
  const status = toolbar.querySelectorAll('select')
    .find((select) => select.children.some((option) => option.getAttribute('value') === 'fixed'));
  assert.ok(!status, 'no inert status filter is offered before a comparison exists');
  assert.match(toolbar.textContent, /Reports page/, 'the interface says where the comparison happens');
  assert.equal(toolbar.querySelectorAll('select')[0].value === undefined, false,
    'the severity filter is still the first control');
});

test('the documentation view documents the language, diagnostics and limits', async () => {
  await go('documentation');
  const text = page.document.getElementById('docs-body').textContent;
  assert.match(text, /LEX001|LEX002/);
  assert.match(text, /SEM\d+/);
  assert.match(text, /DFA001|RULE\d+/);
  assert.ok(text.length > 500, 'the documentation page is substantive');
});

test('no view renders a placeholder leak', async () => {
  for (const route of ROUTES) {
    // eslint-disable-next-line no-await-in-loop
    await go(route);
    const text = viewText(route);
    assert.equal(text.includes('undefined'), false, `${route} has no "undefined"`);
    assert.equal(text.includes('[object Object]'), false, `${route} has no object leak`);
    assert.equal(text.includes('NaN'), false, `${route} has no NaN`);
    assert.equal(page.document.getElementById('global-error').hidden, true, `${route} shows no error banner`);
  }
});

test('a partial analysis says so in the interface instead of looking clean', async () => {
  // The engine marks a run partial when a construct outside the subset was
  // skipped; the interface must repeat that, so a short finding list is never
  // mistaken for a clean bill of health.  This test pins the payload keys the
  // views read (`summary.analysis_complete`, `summary.partial_reasons`).
  await go('analyze');
  page.document.getElementById('source-input').value =
    'int main() { switch (1) { case 1: return 0; } return 0; }\n';
  page.document.getElementById('filename-input').value = 'partial-fixture.ctc';
  page.document.getElementById('use-builtin').checked = true;
  page.document.getElementById('analyze-button').click();

  // Wait for *this* run, not for the previous test's status text: the old run's
  // "run <id>" line is still on the page until the new payload arrives.
  await waitFor(
    () => {
      const text = page.document.getElementById('analyze-status').textContent;
      return text.includes('partial-fixture.ctc') && text.includes('run ');
    },
    'the partial analysis to finish',
    30000,
  );

  const { state } = await import('../js/state.js');
  assert.equal(state.run.filename, 'partial-fixture.ctc');
  assert.equal(state.run.summary.analysis_complete, false, 'the engine reports the run as partial');
  assert.ok(state.run.summary.partial_reasons.length > 0, 'the reasons are named');
  assert.equal(state.run.findings.length, 0, 'no finding is claimed for a skipped region');

  const diagnostics = page.document.getElementById('analyze-diagnostics').textContent;
  assert.match(diagnostics, /This analysis is partial/);
  assert.match(diagnostics, /LEX100|LEX102|SYN100/, 'the unsupported construct is named');

  await go('findings');
  const findingsText = viewText('findings');
  assert.match(findingsText, /the analysis was partial/, 'the findings page repeats the warning');
});

test('an analysis uses the rules written in the Analyze page box, not another page\'s', async () => {
  const { api } = await import('../js/api.js');
  await go('analyze');

  // A broken rule file is left in the Rule Editor.  It must not be applied to an
  // analysis started here, where the custom-rules box is empty: the built-in
  // rules alone have to find the flow.
  page.document.getElementById('rule-editor').value = 'version 1\nsink\n';
  page.document.getElementById('rules-input').value = '';
  page.document.getElementById('source-input').value =
    'int main() {\n  string cmd = input();\n  system(cmd);\n  return 0;\n}\n';
  page.document.getElementById('filename-input').value = 'builtin-only.ctc';
  page.document.getElementById('analyze-button').click();

  const { state } = await import('../js/state.js');
  await waitFor(
    () => {
      const text = page.document.getElementById('analyze-status').textContent;
      return text.includes('builtin-only.ctc') && text.includes('run ');
    },
    'the analysis with the built-in rules',
    30000,
  );
  assert.equal(state.run.findings.length, 1, 'the built-in rule set reported the flow');
  assert.equal(state.run.rules.origin, 'built-in rules');

  // Now write the shipped custom rule file into the Analyze page box: it has to
  // be the rule set the engine uses, and it has to find the custom sink.
  const rules = await api.example('custom_rules/strict_rules.ctrule');
  const demo = await api.example('custom_rules/custom_rule_demo.ctc');
  page.document.getElementById('rules-input').value = rules.content;
  page.document.getElementById('source-input').value = demo.content;
  page.document.getElementById('filename-input').value = 'custom-demo.ctc';
  page.document.getElementById('analyze-button').click();

  await waitFor(
    () => {
      const text = page.document.getElementById('analyze-status').textContent;
      return text.includes('custom-demo.ctc') && text.includes('run ');
    },
    'the analysis with the custom rules',
    30000,
  );
  assert.equal(state.run.filename, 'custom-demo.ctc');
  assert.equal(state.run.rules.origin, 'built-in rules + submitted rules');
  assert.equal(state.run.rules.sources, 6, 'the submitted source rule was merged in');
  assert.equal(state.run.rules.sinks, 9, 'the submitted sink rule was merged in');
  assert.equal(state.run.findings.length, 1, 'the custom sink is reported once');
  assert.equal(state.run.findings[0].rule_id, 'audit_injection');
  assert.equal(state.run.findings[0].sink.function, 'audit_write');

  // The Rule Editor's own text is still the broken file: it never leaked.
  assert.match(page.document.getElementById('rule-editor').value, /^version 1\nsink/);

  // The hand-over button copies the editor's file into that box, visibly.
  await go('rules');
  page.document.getElementById('rule-editor').value = rules.content;
  page.document.getElementById('analyze-with-rules-button').click();
  await settle(20);
  assert.equal(page.window.location.hash, '#/analyze');
  assert.equal(page.document.getElementById('rules-input').value, rules.content);
  assert.match(
    page.document.getElementById('analyze-status').textContent,
    /now in the custom rules box/,
  );
});

test('a run whose only sink call was cleared by a validator says so, and names it', async () => {
  // The result a user is most likely to misread is "0 findings". Here the taint
  // does reach `system(name)`; what cleared it is the declared validator on the
  // guarding branch. The Analyze page must therefore carry the engine's own
  // account of the run rather than letting an empty finding list speak for it.
  const { state } = await import('../js/state.js');
  await go('analyze');
  page.document.getElementById('source-input').value =
    'int main() {\n  string name = input();\n  if (is_safe_command(name)) {\n'
    + '    system(name);\n  }\n  return 0;\n}\n';
  page.document.getElementById('filename-input').value = 'guarded-fixture.ctc';
  page.document.getElementById('use-builtin').checked = true;
  page.document.getElementById('analyze-button').click();
  await waitFor(
    () => {
      const text = page.document.getElementById('analyze-status').textContent;
      return text.includes('guarded-fixture.ctc') && text.includes('run ');
    },
    'the guarded analysis to finish',
    30000,
  );

  assert.equal(state.run.findings.length, 0, 'the guarded flow is not reported as a finding');

  const dispositions = state.run.summary.dispositions;
  assert.ok(dispositions, 'the run payload carries the dispositions');
  assert.equal(dispositions.sink_calls_seen, 1);
  assert.equal(dispositions.unreported_count, 1);
  assert.equal(dispositions.validator_guards.length, 1);
  assert.equal(dispositions.validator_guards[0].validator, 'validate_command');
  assert.match(dispositions.unreported_sink_calls[0].reason, /cleared/);
  assert.ok(state.run.notes.length > 0, 'the run notes are carried to the page');

  const panel = page.document.getElementById('analyze-dispositions').textContent;
  assert.match(panel, /What the engine saw but did not report/);
  assert.match(panel, /validate_command/, 'the validator that cleared the flow is named');
  assert.match(panel, /assumption/, 'it is presented as an assumption');
  assert.match(panel, /not analysed/, 'the report states the validator body is not analysed');
  assert.match(panel, /inspected and not reported/, 'the inspected sink call is counted');
  assert.match(panel, /Notes recorded for this run/);

  // And the Findings page must not let the empty list stand alone.
  await go('findings');
  const findingsText = viewText('findings');
  assert.match(findingsText, /not that the program is safe/);
  assert.match(findingsText, /inspected and not reported/);
});
