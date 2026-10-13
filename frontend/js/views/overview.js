/**
 * Overview: what the tool is, what it just analysed, and how the pipeline fits
 * together.  Every number shown here comes from the engine's own metrics; the
 * overview never invents or estimates a value.
 */
import { el, render } from '../lib/dom.js';

const PIPELINE = [
  ['Lexer', 'tokens with offsets, line and column'],
  ['Canonical LR(1) parser', 'LALR(1) tables by default; conflicts are reported, never concealed'],
  ['AST + semantic analysis', 'scopes, symbol table, type checks, diagnostics'],
  ['Control-flow graph', 'basic blocks, branches, loops, return edges, reachability'],
  ['Data-flow analysis', 'reaching definitions, liveness, definite assignment'],
  ['Taint analysis', 'sources, sinks, sanitizers; conservative interprocedural summaries'],
  ['Dependency graph', 'typed edges, each with the analysis result that justifies it'],
  ['Slicing', 'backward, forward and security slices over that graph'],
  ['Findings and reports', 'stable ids, evidence paths, JSON and HTML export'],
];

function stat(value, label, hint = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat__value', text: value === null || value === undefined ? '—' : String(value) }),
    el('div', { class: 'stat__label', text: label }),
    hint ? el('div', { class: 'stat__hint', text: hint }) : null,
  ]);
}

export function renderOverview(container, { state, health, language }) {
  const run = state.run;
  const metrics = (run && run.metrics) || {};
  const summary = (run && run.summary) || null;

  const stats = el('div', { class: 'grid grid--stats' }, [
    stat(health ? health.engine_version : '—', 'engine version',
         health ? `API ${health.api_version}, schema ${health.schema_version}` : 'engine unreachable'),
    stat(health ? health.grammar.lalr_states : '—', 'LALR(1) states',
         health ? `${health.grammar.productions} productions, ${health.grammar.conflicts} conflicts` : ''),
    stat(health ? health.rules_version : '—', 'rule set', 'validated before it is used'),
    stat(run ? run.filename : '—', 'last analysed file',
         run ? `${summary.findings} finding(s)` : 'nothing analysed yet'),
  ]);

  const runPanel = el('div', { class: 'panel' });
  if (!run) {
    render(runPanel, [
      el('h2', { text: 'Current run' }),
      el('p', {
        class: 'empty-state',
        text: 'No analysis has run in this session yet. Open “Analyze Code”, paste a file (or load a bundled example) and run the analysis.',
      }),
    ]);
  } else {
    const bySeverity = Object.entries(summary.by_severity || {})
      .map(([key, value]) => `${key}: ${value}`)
      .join(', ') || 'none';
    render(runPanel, [
      el('h2', { text: 'Current run' }),
      el('dl', { class: 'kv' }, [
        el('dt', { text: 'run id' }), el('dd', { class: 'mono', text: run.run_id }),
        el('dt', { text: 'accepted by the parser' }),
        el('dd', { text: run.accepted ? 'yes' : 'no — the parser recovered from syntax errors' }),
        el('dt', { text: 'analysis complete' }),
        el('dd', {
          text: summary.analysis_complete === false
            ? `no — ${(summary.partial_reasons || []).join('; ')}`
            : 'yes',
        }),
        el('dt', { text: 'functions' }), el('dd', { text: (summary.functions || []).join(', ') || '—' }),
        el('dt', { text: 'statements' }), el('dd', { text: String(metrics.statements ?? '—') }),
        el('dt', { text: 'basic blocks / CFG edges' }),
        el('dd', { text: `${metrics.basic_blocks ?? '—'} / ${metrics.cfg_edges ?? '—'}` }),
        el('dt', { text: 'definitions' }), el('dd', { text: String(metrics.definitions ?? '—') }),
        el('dt', { text: 'dependency nodes / edges' }),
        el('dd', { text: `${metrics.dependency_nodes ?? '—'} / ${metrics.dependency_edges ?? '—'}` }),
        el('dt', { text: 'data-flow iterations' }), el('dd', { text: String(metrics.dataflow_iterations ?? '—') }),
        el('dt', { text: 'findings' }), el('dd', { text: `${summary.findings} (${bySeverity})` }),
        el('dt', { text: 'engine-side analysis time' }), el('dd', { text: `${run.total_analysis_seconds} s` }),
        el('dt', { text: 'errors / warnings' }),
        el('dd', { text: `${summary.errors} / ${summary.warnings}` }),
      ]),
      el('p', { class: 'hint', text: 'All values are measured by the engine for this run; none are estimated.' }),
    ]);
  }

  const pipeline = el('div', { class: 'panel' }, [
    el('h2', { text: 'Pipeline' }),
    el('ol', {}, PIPELINE.map(([name, description]) =>
      el('li', {}, [el('strong', { text: name }), ' — ', description]))),
    el('p', {
      class: 'hint',
      text: 'The front end is the project’s own lexer and canonical LR(1) parser generator. '
        + 'The tree is then analysed by the classical compiler algorithms and the results are '
        + 'turned into findings with evidence paths and honest limitations.',
    }),
    language
      ? el('p', { class: 'hint', text: `Language mode: ${language.mode}. ${language.diagnostics.length} diagnostic codes are defined; unsupported syntax always produces a diagnostic.` })
      : null,
  ]);

  // Render into the page's own mount points instead of replacing the section:
  // the heading (`aria-labelledby` on the section) and the mount points stay in
  // the document, so re-rendering never destroys part of the page structure.
  render(container.querySelector('#overview-stats'), stats);
  render(container.querySelector('#overview-run'), runPanel);
  render(container.querySelector('#overview-pipeline'), pipeline);
  return container;
}
