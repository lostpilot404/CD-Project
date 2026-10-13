/**
 * Data-Flow Analysis view: the CFG of one function with the results of the
 * classical analyses, exactly as the engine computed them.
 *
 * For each basic block the view shows the equations' inputs and outputs
 * (reaching definitions, live variables or definite assignment) and the number
 * of worklist iterations it took to converge.  Per-statement states come from the
 * engine's own replay of the transfer function.
 */
import { el, render } from '../lib/dom.js';
import { api } from '../api.js';

const ANALYSES = [
  ['reaching', 'Reaching definitions', 'OUT = GEN ∪ (IN − KILL), IN = ∪ OUT[P]', 'forward'],
  ['liveness', 'Live variables', 'IN = USE ∪ (OUT − DEF), OUT = ∪ IN[S]', 'backward'],
  ['definite', 'Definite assignment', 'IN = ∩ OUT[P] (must analysis)', 'forward'],
];

export function renderDataflow(container, { state, onFunction, onAnalysis, onSelectStatement }) {
  const toolbar = container.querySelector('#dataflow-toolbar');
  const body = container.querySelector('#dataflow-body');
  const run = state.run;

  if (!run) {
    render(toolbar, []);
    render(body, el('p', { class: 'empty-state', text: 'No analysis has run yet. Use “Analyze Code” first.' }));
    return;
  }

  // Function names come from the run summary; `metrics.functions` is a count.
  const functions = (run.summary && run.summary.functions) || [];
  if (!functions.length) {
    render(toolbar, []);
    render(body, el('p', {
      class: 'empty-state',
      text: 'This run declares no function, so there is no control-flow graph to analyse.',
    }));
    return container;
  }
  const current = state.dataflow.function && functions.includes(state.dataflow.function)
    ? state.dataflow.function
    : functions[0];

  render(toolbar, el('div', { class: 'row row--wrap' }, [
    el('label', { class: 'field' }, [
      el('span', { text: 'Function' }),
      el('select', { on: { change: (event) => onFunction(event.target.value) } },
        functions.map((name) => el('option', { value: name, selected: name === current, text: name }))),
    ]),
    el('label', { class: 'field' }, [
      el('span', { text: 'Analysis' }),
      el('select', { on: { change: (event) => onAnalysis(event.target.value) } },
        ANALYSES.map(([value, label]) => el('option', { value, selected: value === state.dataflow.analysis, text: label }))),
    ]),
  ]));

  const [key, label, equations] = ANALYSES.find((entry) => entry[0] === state.dataflow.analysis) || ANALYSES[0];
  const data = state.dataflow.data;
  if (!data) {
    render(body, el('p', {}, [el('span', { class: 'spinner' }), ' running the analysis…']));
    return;
  }

  const blockRows = (data.blocks || []).map((block) =>
    el('tr', {}, [
      el('td', { class: 'mono', text: String(block.block) }),
      el('td', { text: block.reachable ? 'reachable' : 'unreachable' }),
      el('td', { class: 'num', text: String(block.in_size) }),
      el('td', { class: 'mono', text: (block.in || []).join(', ') || '∅' }),
      el('td', { class: 'num', text: String(block.out_size) }),
      el('td', { class: 'mono', text: (block.out || []).join(', ') || '∅' }),
    ]));

  const statementRows = Object.entries(data.statement_states || {}).map(([sid, states]) =>
    el('tr', {}, [
      el('td', {}, el('button', { type: 'button', class: 'button button--small', text: sid, on: { click: () => onSelectStatement(Number(sid)) } })),
      el('td', { class: 'mono', text: data.state_labels ? '[in]' : '[in]' }),
      el('td', { class: 'mono', text: Array.isArray(states.in) ? states.in.join(', ') || '∅' : String(states.in) }),
      el('td', { class: 'mono', text: Array.isArray(states.out) ? states.out.join(', ') || '∅' : String(states.out) }),
    ]));

  render(body, [
    el('h2', { text: `${label} in ${current}()` }),
    el('dl', { class: 'kv' }, [
      el('dt', { text: 'domain' }), el('dd', { text: `${data.domain} (${data.domain_size} elements)` }),
      el('dt', { text: 'direction' }), el('dd', { text: data.direction }),
      el('dt', { text: 'equations' }), el('dd', { class: 'mono', text: equations }),
      el('dt', { text: 'worklist' }), el('dd', { text: `${data.iterations} iteration(s), ${data.steps} step(s), converged: ${data.converged ? 'yes' : 'no — the iteration cap was reached'}` }),
      el('dt', { text: 'processing order' }), el('dd', { class: 'mono', text: (data.processed_order || []).join(' → ') }),
    ]),
    el('h3', { text: 'Basic blocks' }),
    el('table', { class: 'data' }, [
      el('thead', {}, el('tr', {}, ['block', 'state', '|IN|', 'IN', '|OUT|', 'OUT'].map((h) => el('th', { text: h })))),
      el('tbody', {}, blockRows),
    ]),
    el('h3', { text: 'Per-statement states' }),
    el('p', { class: 'hint', text: 'Values between statements, produced by replaying the transfer function inside each block after the fixed point was reached.' }),
    el('table', { class: 'data' }, [
      el('thead', {}, el('tr', {}, ['statement', '', 'IN', 'OUT'].map((h) => el('th', { text: h })))),
      el('tbody', {}, statementRows),
    ]),
    (data.uninitialised_reads || []).length
      ? el('div', {}, [
          el('h3', { text: 'Uses that may happen before assignment' }),
          el('ul', {}, data.uninitialised_reads.map((item) =>
            el('li', { text: `line ${item.line}: '${item.symbol}' is read but is not definitely assigned on every path` }))),
        ])
      : null,
  ]);
  return container;
}

export async function loadDataflow(state) {
  const run = state.run;
  const functions = (run.summary && run.summary.functions) || [];
  const fn = state.dataflow.function && functions.includes(state.dataflow.function)
    ? state.dataflow.function
    : functions[0];
  if (!fn) throw new Error('this run declares no function to analyse');
  return api.dataflow(run.run_id, fn, state.dataflow.analysis);
}
