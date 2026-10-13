/**
 * Analyze Code: submit source to the engine and show what came back.
 *
 * The editor's content is sent as JSON to /api/analyze. It is never executed,
 * never written to disk by the API and never placed into the page as markup.
 */
import { el, render } from '../lib/dom.js';
import { api, ApiError } from '../api.js';
import { renderSource } from '../source.js';
import { resetForNewRun } from '../state.js';

const DIAGNOSTIC_ORDER = { error: 0, warning: 1, info: 2 };

export function diagnosticTable(diagnostics) {
  if (!diagnostics || !diagnostics.length) {
    return el('p', { class: 'empty-state', text: 'No diagnostics: the file parsed and passed the semantic checks that apply to this subset.' });
  }
  const rows = [...diagnostics]
    .sort((a, b) => (DIAGNOSTIC_ORDER[a.severity] ?? 9) - (DIAGNOSTIC_ORDER[b.severity] ?? 9) || a.line - b.line || a.col - b.col)
    .map((diagnostic) =>
      el('tr', {}, [
        el('td', {}, el('span', { class: `badge badge--${diagnostic.severity}`, text: diagnostic.severity })),
        el('td', { class: 'mono', text: diagnostic.code }),
        el('td', { class: 'mono', text: `${diagnostic.line}:${diagnostic.col}` }),
        el('td', { text: diagnostic.phase }),
        el('td', {}, [
          diagnostic.message,
          diagnostic.detail ? el('div', { class: 'hint', text: diagnostic.detail }) : null,
          diagnostic.unsupported ? el('div', { class: 'hint', text: 'Unsupported construct: the enclosing statement was skipped, not guessed at.' }) : null,
        ]),
      ]),
    );
  return el('table', { class: 'data' }, [
    el('caption', { class: 'hint', text: 'Diagnostics reported for this file' }),
    el('thead', {}, el('tr', {}, ['severity', 'code', 'line:col', 'phase', 'message'].map((header) => el('th', { text: header })))),
    el('tbody', {}, rows),
  ]);
}

/**
 * "What the engine saw but did not report".
 *
 * A short findings list is the most easily misread result the tool produces, so
 * the run's own account of it is shown next to the summary: the sink calls that
 * were inspected and not reported (with the reason for each), the branch guards
 * that cleared a flow, the branches pruned as unreachable and the run's notes
 * (interprocedural approximation, iteration limits, unsupported constructs).
 * Every value here comes from the engine payload; nothing is recomputed here.
 */
export function dispositionsPanel(run) {
  const summary = run.summary || {};
  const dispositions = summary.dispositions || null;
  const notes = run.notes || [];
  const guards = (dispositions && dispositions.validator_guards) || [];
  const unreported = (dispositions && dispositions.unreported_sink_calls) || [];
  const pruned = (dispositions && dispositions.statically_pruned_branches) || [];
  if (!dispositions && !notes.length) return null;

  const rows = [];
  if (dispositions) {
    rows.push(el('dt', { text: 'sink calls inspected' }), el('dd', { text: String(dispositions.sink_calls_seen ?? '—') }));
    rows.push(el('dt', { text: 'reported as findings' }), el('dd', { text: String(dispositions.reported ?? '—') }));
    rows.push(el('dt', { text: 'inspected but not reported' }), el('dd', { text: String(dispositions.unreported_count ?? unreported.length) }));
    rows.push(el('dt', { text: 'branches pruned as unreachable' }), el('dd', { text: String(pruned.length) }));
  }

  const children = [
    el('h2', { text: 'What the engine saw but did not report' }),
    rows.length ? el('dl', { class: 'kv' }, rows) : null,
  ];

  if (guards.length) {
    children.push(el('p', { class: 'alert alert--info', text:
      'A rule-declared validator guards part of this program: the flows through that guard were '
      + 'cleared, and the validator\u2019s implementation is not analysed. The result assumes it '
      + 'rejects every value that is unsafe for its context.' }));
    children.push(el('ul', {}, guards.map((guard) => el('li', {}, [
      el('span', { class: 'badge badge--muted', text: 'assumption' }),
      ' ',
      el('span', { class: 'mono', text: `${guard.validator}()` }),
      ` guards ${guard.symbol} for context “${guard.context}” at line ${guard.line}`
        + ` (${guard.removed_atoms.join(', ')} removed)`,
    ]))));
  }

  if (unreported.length) {
    children.push(el('details', {}, [
      el('summary', { text: `Sink calls that were inspected and not reported (${unreported.length})` }),
      el('ul', {}, unreported.map((entry) => el('li', {}, [
        el('span', { class: 'mono', text: `${entry.function}() line ${entry.line}` }),
        ` — ${entry.sink_rule || 'sink'}: `,
        el('span', { class: 'hint', text: entry.reason }),
      ]))),
    ]));
  }

  if (notes.length) {
    children.push(el('h3', { text: 'Notes recorded for this run' }));
    children.push(el('ul', {}, notes.map((note) => el('li', { class: 'hint', text: note }))));
  }

  if (dispositions && dispositions.note) {
    children.push(el('p', { class: 'hint', text: dispositions.note }));
  }
  return children;
}

export function renderAnalyze(container, { state, onRun, onStatus }) {
  const status = container.querySelector('#analyze-status');
  const summary = container.querySelector('#analyze-summary');
  const seen = container.querySelector('#analyze-dispositions');
  const diagnostics = container.querySelector('#analyze-diagnostics');
  const source = state.source || '';

  const editor = container.querySelector('#source-input');
  if (editor.value !== source) editor.value = source;

  const stored = container.querySelector('#filename-input');
  if (state.run && !stored.dataset.touched) stored.value = state.run.filename;

  if (!state.run) {
    render(status, []);
    render(summary, []);
    render(seen, []);
    render(diagnostics, []);
    return container;
  }

  const run = state.run;
  const metrics = run.metrics || {};
  render(status, el('span', { text: `Analysed ${run.filename} in ${run.total_analysis_seconds} s (run ${run.run_id}).` }));
  render(summary, [
    el('h2', { text: 'Summary' }),
    el('dl', { class: 'kv' }, [
      el('dt', { text: 'findings' }), el('dd', { text: String(run.summary.findings) }),
      el('dt', { text: 'by severity' }), el('dd', { text: Object.entries(run.summary.by_severity).map(([k, v]) => `${k}: ${v}`).join(', ') || 'none' }),
      el('dt', { text: 'by category' }), el('dd', { text: Object.entries(run.summary.by_category).map(([k, v]) => `${k}: ${v}`).join(', ') || 'none' }),
      el('dt', { text: 'statements / blocks' }), el('dd', { text: `${metrics.statements ?? '—'} / ${metrics.basic_blocks ?? '—'}` }),
      el('dt', { text: 'dependency edges' }), el('dd', { text: String(metrics.dependency_edges ?? '—') }),
      el('dt', { text: 'limits reached' }), el('dd', { text: (run.limits_hit || []).join('; ') || 'none' }),
    ]),
    el('p', { class: 'hint', text: 'Open Findings, Program Graph, Data-Flow Analysis or Program Slicing to inspect the result of this run.' }),
  ]);
  render(seen, dispositionsPanel(run) || []);

  const ruleDiagnostics = run.rule_diagnostics || [];
  render(diagnostics, [
    el('h2', { text: 'Diagnostics' }),
    diagnosticTable(run.diagnostics),
    run.summary.analysis_complete === false
      ? el('p', { class: 'alert alert--warn', text: `This analysis is partial: ${(run.summary.partial_reasons || []).join('; ')}` })
      : null,
    ruleDiagnostics.length
      ? el('div', {}, [
          el('h3', { text: 'Rule diagnostics' }),
          el('p', { class: 'hint', text: 'Reported by the rule loader for the rule set this run used. A rule file with errors is never used: the analysis is refused instead.' }),
          diagnosticTable(ruleDiagnostics),
        ])
      : null,
  ]);
  return container;
}

/** Example picker: a modal dialog listing the bundled corpus. */
export async function openExamplePicker({ onPick }) {
  const root = document.getElementById('modal-root');
  const list = el('div', {}, el('p', { class: 'spinner-wrapper' }, [el('span', { class: 'spinner' }), ' loading examples…']));
  const close = () => {
    if (typeof document.removeEventListener === 'function') document.removeEventListener('keydown', onKey);
    render(root, []);
  };
  const onKey = (event) => {
    if (event.key === 'Escape') close();
  };
  document.addEventListener('keydown', onKey);
  const closeButton = el('button', { type: 'button', class: 'button button--small', text: 'Close', on: { click: close } });
  const modal = el('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Load a bundled example' }, [
    el('div', { class: 'row row--between' }, [
      el('h2', { text: 'Bundled examples' }),
      closeButton,
    ]),
    list,
  ]);
  render(root, el('div', { class: 'modal-backdrop', on: { click: (event) => { if (event.target.classList.contains('modal-backdrop')) close(); } } }, modal));
  if (typeof closeButton.focus === 'function') closeButton.focus();
  try {
    const payload = await api.examples();
    const categories = [...new Set(payload.examples.map((entry) => entry.category))].sort();
    const body = el('div');
    for (const category of categories) {
      body.appendChild(el('p', { class: 'modal__category', text: category }));
      const items = payload.examples.filter((entry) => entry.category === category);
      body.appendChild(el('ul', { class: 'modal__list' }, items.map((entry) =>
        el('li', {}, el('button', {
          type: 'button',
          on: { click: async () => { close(); await onPick(entry); } },
          text: entry.name,
        })),
      )));
    }
    render(list, body);
  } catch (error) {
    render(list, el('p', { class: 'alert alert--error', text: `Could not load the example list: ${error.message}` }));
  }
}

/** Run the analysis for the current editor contents. */
export async function runAnalysis(container, { filename, source, parserMode, useBuiltin, customRules, runDependencies }) {
  const button = container.querySelector('#analyze-button');
  const status = container.querySelector('#analyze-status');
  button.disabled = true;
  render(status, [el('span', { class: 'spinner' }), ' analysing…']);
  try {
    // The options are sent exactly as shown: the built-in toggle, the parser
    // mode and the dependency-graph checkbox all reach the engine.  (The
    // checkbox once built a payload field nothing read, so unchecking it
    // silently analysed with the graph anyway.)
    const payload = {
      source,
      filename,
      parser_mode: parserMode,
      use_builtin_rules: Boolean(useBuiltin),
      run_dependencies: Boolean(runDependencies),
    };
    if (customRules && customRules.trim()) payload.rules = customRules;
    const run = await api.analyze(payload);
    resetForNewRun(run, source);
    render(status, el('span', { text: `Analysed ${run.filename} in ${run.total_analysis_seconds} s.` }));
    return run;
  } catch (error) {
    const detail = error instanceof ApiError && error.detail ? ` (${error.detail})` : '';
    render(status, el('span', { class: 'alert alert--error', text: `${error.message}${detail}` }));
    return null;
  } finally {
    button.disabled = false;
  }
}
