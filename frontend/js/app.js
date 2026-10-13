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
          // Load first, navigate second.  Navigating first raced the view's
          // own lazy loading (which would fetch the full graph / a default
          // statement slice into the same slot), the load's completion did
          // not itself trigger a re-render, and a failed load surfaced only
          // as an unhandled rejection in the console.
          try {
            if (target === 'graph') {
              update({ graph: { ...state.graph, mode: 'dependency' }, selectedFinding: finding.id });
              await loadStatementSubgraph(finding);
              window.location.hash = '#/graph';
            } else {
              update({ slicing: { ...state.slicing, source: 'finding' } });
              await loadSliceForFinding(finding.id);
              window.location.hash = '#/slicing';
            }
            showError('');
          } catch (error) {
            showError(`Could not load that view for the finding: ${error.message}`);
          }
        },
        onSelectStatement: selectStatement,
      });
    } else if (route === 'graph') {
      const view = document.getElementById('view-graph');
      const options = {
        state,
        onSelectNode: (node) => { if (node.sid >= 0) selectStatement(node.sid); },
        onMode: async (mode) => { update({ graph: { ...state.graph, mode } }); await loadGraphData(); refresh('graph'); },
        onKinds: async (kind, checked) => {
          const kinds = checked
            ? [...new Set([...state.graph.kinds, kind])]
            : state.graph.kinds.filter((entry) => entry !== kind);
          update({ graph: { ...state.graph, kinds } });
          await loadGraphData();
          refresh('graph');
        },
      };
      renderGraphView(view, options);
      // Reaching this page after a run must show the graph, not a placeholder:
      // fetch it the first time the page is opened and paint again.
      if (state.run && state.graph.mode !== 'cfg' && !state.graph.data) {
        try {
          await loadGraphData();
        } catch (error) {
          showError('Could not load the program graph.', error.message);
        }
        renderGraphView(view, options);
      }
    } else if (route === 'dataflow') {
      const view = document.getElementById('view-dataflow');
      const options = {
        state,
        onFunction: async (fn) => { update({ dataflow: { ...state.dataflow, function: fn } }); await loadDataflowData(); refresh('dataflow'); },
        onAnalysis: async (analysis) => { update({ dataflow: { ...state.dataflow, analysis } }); await loadDataflowData(); refresh('dataflow'); },
        onSelectStatement: selectStatement,
      };
      renderDataflow(view, options);
      const hasFunctions = Boolean(state.run && state.run.summary && (state.run.summary.functions || []).length);
      if (state.run && hasFunctions && !state.dataflow.data) {
        try {
          await loadDataflowData();
        } catch (error) {
          showError('Could not load the data-flow results.', error.message);
        }
        renderDataflow(view, options);
      }
    } else if (route === 'slicing') {
      state.statementsById = statementIndex(state.run || {});
      const view = document.getElementById('view-slicing');
      const options = {
        state,
        onCriterion: async (sid) => {
          update({ slicing: { ...state.slicing, sid, source: 'statement', data: null } });
          await loadSliceData(sid);
          refresh('slicing');
        },
        onDirection: async (direction) => {
          update({ slicing: { ...state.slicing, direction, data: null } });
          // A finding (security) slice has no statement criterion and no
          // direction: recompute that slice instead of asking the statement
          // endpoint for `sid=null`.
          if (state.slicing.source === 'finding' && state.selectedFinding) {
            await loadSliceForFinding(state.selectedFinding);
          } else {
            await loadSliceData(state.slicing.sid);
          }
          refresh('slicing');
        },
        onSelectStatement: selectStatement,
      };
      renderSlicing(view, options);
      if (state.run && !state.slicing.data) {
        const criterion = defaultCriterion(state);
        if (criterion !== null) {
          update({ slicing: { ...state.slicing, sid: criterion, source: 'statement' } });
          try {
            await loadSliceData(criterion);
          } catch (error) {
            showError('Could not compute the slice.', error.message);
          }
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

async function loadGraphData() {
  if (!state.run || state.graph.mode === 'cfg') return;
  const graph = await loadGraph(state, api);
  update({ graph: { ...state.graph, data: graph } });
}

async function loadStatementSubgraph(finding) {
  const graph = await api.graph(state.run.run_id, { kinds: state.graph.kinds });
  const statementNodes = new Set((finding.statement_ids || []).map((sid) => `s${sid}`));
  const nodes = graph.nodes.filter((node) => statementNodes.has(node.id) || node.kind === 'function');
  const kept = new Set(nodes.map((node) => node.id));
  // Both endpoints must survive: an edge pointing at a dropped node cannot
  // be drawn, but it would still be counted in the "edges shown" total.
  const edges = graph.edges.filter((edge) => kept.has(edge.from) && kept.has(edge.to));
  update({ graph: { ...state.graph, data: { ...graph, nodes, edges }, focus: finding.id } });
}

async function loadDataflowData() {
  const data = await loadDataflow(state);
  update({ dataflow: { ...state.dataflow, data } });
}

async function loadSliceData(sid) {
  const slice = await loadSlice(state, sid);
  update({ slicing: { ...state.slicing, data: slice } });
}

async function loadSliceForFinding(findingId) {
  const slice = await loadFindingSlice(state, findingId);
  update({ slicing: { ...state.slicing, data: slice } });
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
  try {
    const comparison = await api.compare(before, after);
    update({ comparison, compareBefore: before, compareAfter: after });
    showError('');
    refresh('reports');
  } catch (error) {
    showError(`Comparison failed: ${error.message}`);
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
      update({ statementsById: statementIndex(run), selectedFinding: null, selectedFindingDetail: null });
      refresh('analyze');
    }
  });

  view.querySelector('#clear-button').addEventListener('click', () => {
    resetRun();
    editor.value = '';
    // The filename counts as untouched again, so the next run's name is
    // shown instead of the cleared run's name lingering as "user input".
    filename.dataset.touched = '';
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
