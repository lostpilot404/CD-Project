/**
 * CodeTrace interface: routing, state wiring and view updates.
 *
 * The interface is a thin client: it submits source, asks for the analysis
 * artefacts it wants to show and renders them.  It does not compute taint,
 * dependencies, data-flow states or slices -- those come from the engine, which
 * is the single source of truth for every analysis result.
 */

import { el, render } from './lib/dom.js';
import { api, ApiError } from './api.js';
import { state, subscribe, update, resetRun } from './state.js';
import { renderOverview } from './views/overview.js';
import { renderAnalyze, openExamplePicker, runAnalysis, diagnosticTable } from './views/analyze.js';
import { renderFindings, loadFindingDetail } from './views/findings.js';
import { renderGraphView, loadGraph } from './views/graph.js';
import { renderDataflow, loadDataflow } from './views/dataflow.js';
import { renderSlicing, loadSlice, loadFindingSlice } from './views/slicing.js';
import { renderRules, validateRules } from './views/rules.js';
import { renderReports } from './views/reports.js';
import { renderDocs } from './views/docs.js';

const ROUTES = ['overview', 'analyze', 'findings', 'graph', 'dataflow', 'slicing', 'rules', 'reports', 'documentation'];
const STATIC_CONTEXT = { health: null, language: null, grammar: null };

function currentRoute() {
  const hash = window.location.hash.replace(/^#\/?/, '');
  return ROUTES.includes(hash) ? hash : 'overview';
}

function showError(message, detail = '') {
  const banner = document.getElementById('global-error');
  if (!message) {
    banner.hidden = true;
    render(banner, []);
    return;
  }
  banner.hidden = false;
  render(banner, [message, detail ? el('div', { class: 'hint', text: detail }) : null]);
}

function showRoute() {
  const route = currentRoute();
  for (const name of ROUTES) {
    document.getElementById(`view-${name}`).hidden = name !== route;
  }
  for (const link of document.querySelectorAll('#nav-list a')) {
    if (link.dataset.route === route) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  document.title = `CodeTrace — ${route}`;
  refresh(route);
}

function statementIndex(run) {
  const index = {};
  for (const statement of run.statements || []) {
    index[statement.sid] = statement.text;
  }
  return index;
}

async function refresh(route = currentRoute()) {
  const context = { ...STATIC_CONTEXT, state };
  try {
    if (route === 'overview') {
      renderOverview(document.getElementById('view-overview'), context);
    } else if (route === 'analyze') {
      renderAnalyze(document.getElementById('view-analyze'), context);
    } else if (route === 'findings') {
      await renderFindings(document.getElementById('view-findings'), {
        state,
        onFilter: (patch) => { update({ filters: { ...state.filters, ...patch } }); refresh('findings'); },
        onSort: (sortKey) => { update({ sort: sortKey }); refresh('findings'); },
        onSelect: selectFinding,
        onShowSlice: async (target, finding) => {
          // Fetch the finding-specific artefact first, then navigate to a page
          // that already has something to show.  Fetching after navigating
          // used to leave the page behind: the fetch ran without a second
          // paint, so the page kept showing whatever it showed before — a
          // stale graph, or a spinner that never stopped.
          if (target === 'graph') {
            update({ graph: { ...state.graph, mode: 'dependency', data: null, loadError: null }, selectedFinding: finding.id });
            try {
              await loadStatementSubgraph(finding);
            } catch (error) {
              update({ graph: { ...state.graph, loadError: error.message } });
            }
            window.location.hash = '#/graph';
            refresh('graph');
          } else {
            update({ slicing: { ...state.slicing, source: 'finding', data: null, error: null } });
            try {
              await loadSliceForFinding(finding.id);
            } catch (error) {
              update({ slicing: { ...state.slicing, error: error.message } });
            }
            window.location.hash = '#/slicing';
            refresh('slicing');
          }
        },
        onSelectStatement: selectStatement,
      });
    } else if (route === 'graph') {
      const view = document.getElementById('view-graph');
      const options = {
        state,
        onSelectNode: (node) => { if (node.sid >= 0) selectStatement(node.sid); },
        onMode: async (mode) => {
          update({ graph: { ...state.graph, mode, data: null, loadError: null, focus: null } });
          await reloadGraphData();
          refresh('graph');
        },
        onKinds: async (kind, checked) => {
          const kinds = checked
            ? [...new Set([...state.graph.kinds, kind])]
            : state.graph.kinds.filter((entry) => entry !== kind);
          update({ graph: { ...state.graph, kinds, loadError: null } });
          await reloadGraphData();
          refresh('graph');
        },
        onCfgFunction: async (fn) => {
          update({ graph: { ...state.graph, cfgFunction: fn, loadError: null } });
          await reloadGraphData();
          refresh('graph');
        },
      };
      renderGraphView(view, options);
      // Reaching this page after a run must show the graph, not a placeholder:
      // fetch it the first time the page is opened and paint again.  A failed
      // fetch is kept on the state (not only in the banner) so the canvas can
      // explain itself instead of spinning forever.
      const graphFunctions = (state.run.summary && state.run.summary.functions) || [];
      const needsFetch = state.run && !state.graph.data && !state.graph.loadError
        && (state.graph.mode === 'cfg'
          ? graphFunctions.length > 0
          : (state.run.summary && state.run.summary.dependencies_built !== false));
      if (needsFetch) {
        await reloadGraphData();
        renderGraphView(view, options);
      }
    } else if (route === 'dataflow') {
      const view = document.getElementById('view-dataflow');
      const options = {
        state,
        onFunction: async (fn) => {
          update({ dataflow: { ...state.dataflow, function: fn, data: null, error: null } });
          await reloadDataflowData();
          refresh('dataflow');
        },
        onAnalysis: async (analysis) => {
          update({ dataflow: { ...state.dataflow, analysis, data: null, error: null } });
          await reloadDataflowData();
          refresh('dataflow');
        },
        onSelectStatement: selectStatement,
      };
      renderDataflow(view, options);
      const hasFunctions = Boolean(state.run && state.run.summary && (state.run.summary.functions || []).length);
      if (state.run && hasFunctions && !state.dataflow.data && !state.dataflow.error) {
        await reloadDataflowData();
        renderDataflow(view, options);
      }
    } else if (route === 'slicing') {
      state.statementsById = statementIndex(state.run || {});
      const view = document.getElementById('view-slicing');
      const options = {
        state,
        onCriterion: async (sid) => {
          update({ slicing: { ...state.slicing, sid, source: 'statement', data: null, error: null } });
          await reloadSliceData(sid);
          refresh('slicing');
        },
        onDirection: async (direction) => {
          update({ slicing: { ...state.slicing, direction, data: null, error: null } });
          await reloadSliceData(state.slicing.sid);
          refresh('slicing');
        },
        onSelectStatement: selectStatement,
      };
      renderSlicing(view, options);
      const slicingAvailable = !state.run || !state.run.summary || state.run.summary.slicing_available !== false;
      if (state.run && state.slicing.source === 'finding' && !state.slicing.data && !state.slicing.error) {
        // A finding slice is loaded by the Findings page action; landing here
        // without one (a stale state) falls back to a statement slice rather
        // than spinning forever.
        update({ slicing: { ...state.slicing, source: 'statement' } });
      }
      if (state.run && slicingAvailable && !state.slicing.data && !state.slicing.error
          && state.slicing.source !== 'finding') {
        const criterion = defaultCriterion(state);
        if (criterion !== null) {
          update({ slicing: { ...state.slicing, sid: criterion, source: 'statement' } });
          await reloadSliceData(criterion);
          renderSlicing(view, options);
        }
      }
    } else if (route === 'rules') {
      renderRules(document.getElementById('view-rules'), { state });
    } else if (route === 'reports') {
      renderReports(document.getElementById('view-reports'), {
        state,
        onCompare: compareRuns,
      });
    } else if (route === 'documentation') {
      renderDocs(document.getElementById('view-documentation'), STATIC_CONTEXT);
    }
  } catch (error) {
    showError('Something went wrong while rendering this view.', error.message);
  }
}

/**
 * Which statement a slice is taken from when the user has not chosen one.
 *
 * The sink of the first finding is the most useful default: it is the point the
 * engine reported a flow into.  Without findings the last statement of the file
 * is used, so the page is never an empty destination.
 */
function defaultCriterion(state) {
  const findings = (state.run && state.run.findings) || [];
  const sinkSid = findings.length && findings[0].sink ? findings[0].sink.sid : null;
  if (sinkSid !== null && sinkSid !== undefined) return sinkSid;
  const sids = Object.keys(state.statementsById || {})
    .map(Number)
    .sort((left, right) => left - right);
  return sids.length ? sids[sids.length - 1] : null;
}

async function reloadGraphData() {
  if (!state.run) return;
  try {
    const graph = await loadGraph(state, api);
    update({ graph: { ...state.graph, data: graph, loadError: null, focus: null } });
  } catch (error) {
    // Kept on the state so the canvas explains the failure in place; a banner
    // alone would leave a spinner spinning underneath it.
    update({ graph: { ...state.graph, data: null, loadError: error.message } });
  }
}

async function loadStatementSubgraph(finding) {
  const graph = await api.graph(state.run.run_id, { kinds: state.graph.kinds });
  const statementNodes = new Set((finding.statement_ids || []).map((sid) => `s${sid}`));
  const nodes = graph.nodes.filter((node) => statementNodes.has(node.id) || node.kind === 'function');
  const kept = new Set(nodes.map((node) => node.id));
  // An edge is only drawable when both ends survived the filter; keeping
  // half-edges would inflate the edge count with lines the renderer skips.
  const edges = graph.edges.filter((edge) => kept.has(edge.from) && kept.has(edge.to));
  update({ graph: { ...state.graph, data: { ...graph, nodes, edges }, loadError: null, focus: finding.id } });
}

async function reloadDataflowData() {
  try {
    const data = await loadDataflow(state);
    update({ dataflow: { ...state.dataflow, data, error: null } });
  } catch (error) {
    update({ dataflow: { ...state.dataflow, data: null, error: error.message } });
  }
}

async function reloadSliceData(sid) {
  try {
    const slice = await loadSlice(state, sid);
    update({ slicing: { ...state.slicing, data: slice, error: null } });
  } catch (error) {
    update({ slicing: { ...state.slicing, data: null, error: error.message } });
  }
}

async function loadSliceForFinding(findingId) {
  const slice = await loadFindingSlice(state, findingId);
  update({ slicing: { ...state.slicing, source: 'finding', data: slice } });
}

async function selectFinding(findingId) {
  update({ selectedFinding: findingId, selectedFindingDetail: null, slicing: { ...state.slicing, source: 'finding' } });
  refresh('findings');
  try {
    const detail = await loadFindingDetail(state.run.run_id, findingId);
    update({ selectedFindingDetail: detail });
    refresh('findings');
  } catch (error) {
    showError(`Could not load the finding: ${error.message}`);
  }
}

async function selectStatement(sid) {
  if (!state.run) return;
  update({ selectedStatement: sid });
  try {
    const detail = await api.statement(state.run.run_id, sid);
    update({ statementDetail: detail, selectedStatement: sid });
  } catch (error) {
    showError(`Could not load statement ${sid}: ${error.message}`);
  }
  const route = currentRoute();
  if (route === 'graph' || route === 'dataflow' || route === 'slicing') refresh(route);
}

async function compareRuns() {
  const before = document.getElementById('compare-before').value.trim();
  const after = document.getElementById('compare-after').value.trim();
  if (!before || !after) {
    showError('Enter both run ids to compare two runs.');
    return;
  }
  const button = document.getElementById('compare-button');
  if (button) button.disabled = true;
  try {
    const comparison = await api.compare(before, after);
    update({ comparison, compareBefore: before, compareAfter: after });
    showError('');
    refresh('reports');
  } catch (error) {
    showError(`Comparison failed: ${error.message}`);
  } finally {
    if (button) button.disabled = false;
  }
}

function wireInputs() {
  const view = document.getElementById('view-analyze');
  const editor = view.querySelector('#source-input');
  const filename = view.querySelector('#filename-input');
  // The custom rules used by an analysis are the ones written in the Analyze
  // page's own box.  Reading the Rule Editor's textarea here would apply rules
  // that this page does not show, which is exactly the kind of silent mismatch
  // a security tool must not have.
  const customRules = view.querySelector('#rules-input');
  const rules = document.getElementById('rule-editor');

  editor.addEventListener('input', () => update({ source: editor.value }));
  filename.addEventListener('input', () => { filename.dataset.touched = 'true'; });

  view.querySelector('#analyze-button').addEventListener('click', async () => {
    const run = await runAnalysis(view, {
      filename: filename.value || 'example.ctc',
      source: editor.value,
      parserMode: view.querySelector('#parser-mode').value,
      useBuiltin: view.querySelector('#use-builtin').checked,
      customRules: customRules.value,
      runDependencies: view.querySelector('#run-dependencies').checked,
    });
    if (run) {
      // runAnalysis already stored the run and dropped the previous run's
      // artefacts; only the statement index (derived here) is still missing.
      update({ statementsById: statementIndex(run) });
      refresh('analyze');
    }
  });

  view.querySelector('#clear-button').addEventListener('click', () => {
    resetRun();
    editor.value = '';
    refresh('analyze');
  });

  view.querySelector('#load-example-button').addEventListener('click', () => {
    openExamplePicker({
      onPick: async (entry) => {
        const example = await api.example(entry.id);
        editor.value = example.content;
        filename.value = entry.name;
        filename.dataset.touched = 'true';
        update({ source: example.content });
        const status = view.querySelector('#analyze-status');
        render(status, [el('span', { text: `Loaded ${entry.id}${example.expectation ? ` — ${example.expectation}` : ''}` })]);
      },
    });
  });

  document.getElementById('validate-rules-button').addEventListener('click', async () => {
    const status = document.getElementById('rules-status');
    render(status, [el('span', { class: 'spinner' }), ' validating…']);
    try {
      const result = await validateRules(rules.value);
      render(status, el('span', {
        class: result.valid ? 'status' : 'alert alert--error',
        text: result.valid
          ? `Valid: ${result.stats.sources} source(s), ${result.stats.sinks} sink(s), ${result.stats.sanitizers} sanitizer(s), ${result.stats.flows} flow(s).`
          : 'Rejected: the rule set has errors and was not used.',
      }));
    } catch (error) {
      render(status, el('span', { class: 'alert alert--error', text: error.message }));
    }
    refresh('rules');
  });

  document.getElementById('load-rule-example-button').addEventListener('click', async () => {
    try {
      const example = await api.example('custom_rules/strict_rules.ctrule');
      rules.value = example.content;
      const status = document.getElementById('rules-status');
      render(status, [el('span', { text: 'Loaded the example rule file. Validate it, then use it from the Analyze Code page.' })]);
    } catch (error) {
      showError(`Could not load the example rule file: ${error.message}`);
    }
  });

  document.getElementById('analyze-with-rules-button').addEventListener('click', async () => {
    // Moving the rule file to the Analyze page is explicit: the same text is
    // placed in that page's own custom-rules box, so what the user reads there
    // is what the engine will be given.  Nothing is added to the source box.
    const view2 = document.getElementById('view-analyze');
    const customRules = view2.querySelector('#rules-input');
    customRules.value = rules.value;
    window.location.hash = '#/analyze';
    refresh('analyze');
    const status = view2.querySelector('#analyze-status');
    render(status, [el('span', {
      text: rules.value.trim()
        ? 'The rule file from the Rule Editor is now in the custom rules box; it is validated when the analysis runs.'
        : 'The Rule Editor is empty: write a rule file there, or load the example, before using this button.',
    })]);
  });

  document.getElementById('theme-toggle').addEventListener('click', (event) => {
    const on = document.body.classList.toggle('contrast');
    event.target.textContent = `High contrast: ${on ? 'on' : 'off'}`;
    event.target.setAttribute('aria-pressed', String(on));
  });
}

async function boot() {
  wireInputs();
  window.addEventListener('hashchange', showRoute);
  subscribe(() => { /* views re-render on demand; nothing global to do here */ });
  showRoute();
  try {
    const health = await api.health();
    STATIC_CONTEXT.health = health;
    const status = document.getElementById('engine-status');
    render(status, [
      el('span', { class: 'badge badge--ok', text: `engine ${health.engine_version}` }),
      ' ',
      el('span', { class: 'badge badge--muted', text: `rules ${health.rules_version}` }),
      ' ',
      el('span', { class: 'badge badge--muted', text: `${health.grammar.lalr_states} states / ${health.grammar.conflicts} conflicts` }),
    ]);
    update({ health });
    showError('');
  } catch (error) {
    const status = document.getElementById('engine-status');
    render(status, el('span', { class: 'badge badge--error', text: 'engine unreachable' }));
    showError('The analysis API is not reachable from this page.', error.message);
  }
  try {
    STATIC_CONTEXT.language = await api.language();
  } catch (error) { /* the documentation view degrades gracefully */ }
  try {
    const rules = await api.rules();
    update({ rulesActive: rules.active, ruleGrammar: rules.rule_language });
  } catch (error) { /* ditto */ }
  try {
    STATIC_CONTEXT.grammar = await api.grammar('lalr');
  } catch (error) { /* ditto */ }

  // A default program so the first visit is useful without typing.
  if (!state.source) {
    state.source = [
      '// A small program: untrusted input reaches a command sink through a helper.',
      'string build_command(string value) {',
      '  return "ls " + value;',
      '}',
      '',
      'int main() {',
      '  string name = input();',
      '  string command = build_command(name);',
      '  system(command);',
      '  return 0;',
      '}',
      '',
    ].join('\n');
  }
  refresh(currentRoute());
}

boot();
