/**
 * Selected-statement panel, shared by the graph, data-flow and slicing views.
 *
 * Every value shown here comes from the engine's statement endpoint
 * (`/api/runs/{id}/statements/{sid}`): reaching definitions, live variables,
 * taint and control dependencies.  One renderer keeps the three pages
 * consistent — and keeps statement clicks meaningful everywhere, instead of
 * fetching results only one page displays.
 */
import { el } from '../lib/dom.js';

/** @param {object|null} statement the statement endpoint payload, if loaded */
export function renderStatementDetail(statement) {
  if (!statement) {
    return el('p', { class: 'empty-state', text: 'Select a statement to see its analysis results.' });
  }
  return el('div', {}, [
    el('dl', { class: 'kv' }, [
      el('dt', { text: 'id' }), el('dd', { class: 'mono', text: String(statement.sid) }),
      el('dt', { text: 'line:col' }), el('dd', { class: 'mono', text: `${statement.line}:${statement.col}` }),
      el('dt', { text: 'function / block' }), el('dd', { text: `${statement.function} / ${statement.block}` }),
      el('dt', { text: 'kind' }), el('dd', { text: statement.kind }),
    ]),
    el('pre', { class: 'mono', text: statement.text || '' }),
    el('h3', { text: 'Reaching definitions' }),
    (statement.reaching_definitions || []).length
      ? el('ul', {}, statement.reaching_definitions.map((item) =>
          el('li', { text: `${item.symbol} defined at line ${item.line} (${item.kind})` })))
      : el('p', { class: 'hint', text: 'No definition reaches a read in this statement.' }),
    el('h3', { text: 'Live variables' }),
    el('p', { class: 'hint', text: `IN: ${(statement.live_variables?.in || []).join(', ') || '—'} · OUT: ${(statement.live_variables?.out || []).join(', ') || '—'}` }),
    el('h3', { text: 'Taint before this statement' }),
    (statement.taint || []).length
      ? el('ul', {}, statement.taint.map((item) => el('li', { class: 'mono', text: `${item.symbol}: ${(item.atoms || []).join(', ')}` })))
      : el('p', { class: 'hint', text: 'No taint reaches this statement.' }),
    el('h3', { text: 'Control dependencies' }),
    (statement.control_dependencies || []).length
      ? el('ul', {}, statement.control_dependencies.map((item) =>
          el('li', { text: `${item.kind} condition '${item.condition}' at line ${item.line}` })))
      : el('p', { class: 'hint', text: 'Not guarded by any condition.' }),
  ]);
}
