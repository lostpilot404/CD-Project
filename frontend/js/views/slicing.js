/**
 * Program Slicing view.
 *
 * A slice is computed by the engine by traversing the dependency graph; this
 * view selects a criterion (a statement id or a finding), asks for the slice and
 * shows the statements, the reasons each one is included, the induced subgraph
 * and the conservatism note.
 */
import { el, render } from '../lib/dom.js';
import { api } from '../api.js';
import { renderGraph } from '../graph.js';

export function renderSlicing(container, { state, onCriterion, onDirection, onSelectStatement }) {
  const toolbar = container.querySelector('#slicing-toolbar');
  const body = container.querySelector('#slicing-body');
  const run = state.run;

  if (!run) {
    render(toolbar, []);
    render(body, el('p', { class: 'empty-state', text: 'No analysis has run yet. Use “Analyze Code” first.' }));
    return;
  }

  const sids = Object.keys(state.statementsById || {}).sort((a, b) => Number(a) - Number(b));
  if (!sids.length) {
    render(toolbar, []);
    render(body, el('p', {
      class: 'empty-state',
      text: 'This run has no statements, so there is no slice to compute.',
    }));
    return container;
  }
  render(toolbar, el('div', { class: 'row row--wrap' }, [
    el('label', { class: 'field' }, [
      el('span', { text: 'Criterion statement' }),
      el('select', { on: { change: (event) => onCriterion(Number(event.target.value)) } },
        sids.map((sid) => el('option', {
          value: sid,
          selected: Number(sid) === Number(state.slicing.sid),
          text: `${sid}: ${(state.statementsById[sid] || '').slice(0, 46)}`,
        }))),
    ]),
    el('label', { class: 'field' }, [
      el('span', { text: 'Direction' }),
      el('select', { on: { change: (event) => onDirection(event.target.value) } }, [
        el('option', { value: 'backward', selected: state.slicing.direction === 'backward', text: 'backward (what influences it)' }),
        el('option', { value: 'forward', selected: state.slicing.direction === 'forward', text: 'forward (what it influences)' }),
      ]),
    ]),
    el('p', { class: 'hint', text: 'A security slice for a finding is available from the Findings page.' }),
  ]));

  const slice = state.slicing.data;
  if (!slice) {
    render(body, el('p', {}, [el('span', { class: 'spinner' }), ' computing the slice…']));
    return;
  }

  const rows = (slice.statements_detail || []).map((statement) =>
    el('tr', {}, [
      el('td', {}, el('button', { type: 'button', class: 'button button--small', text: String(statement.sid), on: { click: () => onSelectStatement(statement.sid) } })),
      el('td', { class: 'mono', text: `${statement.line}:${statement.col}` }),
      el('td', { text: statement.function }),
      el('td', { class: 'mono', text: statement.text }),
      el('td', { text: (slice.reasons[String(statement.sid)] || []).join(' · ') }),
    ]));

  render(body, [
    el('h2', { text: `${slice.kind} slice (${slice.statements.length} statement(s))` }),
    el('dl', { class: 'kv' }, [
      el('dt', { text: 'criterion' }),
      el('dd', { text: slice.criterion.text ? `line ${slice.criterion.line}: ${slice.criterion.text}` : JSON.stringify(slice.criterion) }),
      el('dt', { text: 'finding' }), slice.finding_id ? el('dd', { class: 'mono', text: slice.finding_id }) : null,
      el('dt', { text: 'truncated' }), el('dd', { text: slice.truncated ? 'yes — the statement limit was reached' : 'no' }),
      el('dt', { text: 'note' }), el('dd', { text: slice.note }),
    ]),
    el('h3', { text: 'Statements in the slice' }),
    el('table', { class: 'data' }, [
      el('thead', {}, el('tr', {}, ['sid', 'line:col', 'function', 'statement', 'why it is included'].map((h) => el('th', { text: h })))),
      el('tbody', {}, rows),
    ]),
    el('h3', { text: 'Dependency subgraph of the slice' }),
    renderGraph(slice.subgraph || { nodes: [], edges: [] }, {
      kinds: null,
      onSelect: (node) => { if (node.sid >= 0) onSelectStatement(node.sid); },
      emptyMessage: 'This slice has no dependencies between its statements.',
    }),
  ]);
  return container;
}

export async function loadSlice(state, sid) {
  const run = state.run;
  return api.slice(run.run_id, sid, state.slicing.direction);
}

export async function loadFindingSlice(state, findingId) {
  const run = state.run;
  return api.findingSlice(run.run_id, findingId);
}
