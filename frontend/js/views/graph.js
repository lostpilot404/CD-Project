/**
 * Program Graph view: the dependency graph, a single CFG, or the subgraph of a
 * finding / slice.  Selecting a node fetches that statement's analysis results
 * (reaching definitions, live variables, taint, control dependencies, AST
 * summary) from the API, so the panel always shows engine output.
 */
import { el, render } from '../lib/dom.js';
import { api } from '../api.js';
import { renderGraph, renderLegend } from '../graph.js';

const KINDS = [
  ['data', 'data'],
  ['taint', 'taint only'],
  ['control', 'control'],
  ['call', 'call'],
  ['return', 'return'],
  ['define', 'definition'],
  ['sanitize', 'sanitization'],
];

export function renderGraphView(container, { state, onSelectNode, onMode, onKinds }) {
  const toolbar = container.querySelector('#graph-toolbar');
  const canvas = container.querySelector('#graph-canvas');
  const side = container.querySelector('#graph-side');
  const run = state.run;

  if (!run) {
    render(toolbar, []);
    render(canvas, el('p', { class: 'empty-state', text: 'No analysis has run yet. Use “Analyze Code” first.' }));
    render(side, []);
    return;
  }

  const modes = [
    ['dependency', 'Program dependency graph'],
    ['cfg', 'Control-flow graph'],
    ['function', 'Function-level call view'],
  ];
  render(toolbar, el('div', { class: 'row row--wrap' }, [
    el('label', { class: 'field' }, [
      el('span', { text: 'Graph' }),
      el('select', { on: { change: (event) => onMode(event.target.value) } },
        modes.map(([value, label]) => el('option', { value, selected: value === state.graph.mode, text: label }))),
    ]),
    el('fieldset', { class: 'fieldset' }, [
      el('legend', { text: 'Edge kinds' }),
      el('div', { class: 'row row--wrap' }, KINDS.map(([kind, label]) =>
        el('label', { class: 'checkbox' }, [
          el('input', {
            type: 'checkbox',
            checked: state.graph.kinds.includes(kind),
            on: { change: (event) => onKinds(kind, event.target.checked) },
          }),
          el('span', { text: label }),
        ]))),
    ]),
  ]));

  const panel = el('div');
  render(panel, [
    state.graph.mode === 'cfg'
      ? el('p', { class: 'hint', text: 'The control-flow graph of one function is shown on the Data-Flow Analysis page, where its blocks are listed with the data-flow results that explain them.' })
      : null,
    state.graph.mode === 'function'
      ? el('p', { class: 'hint', text: 'Function-level view: every edge is a call or a return between the analysed functions.' })
      : null,
  ]);

  if (state.graph.mode === 'cfg') {
    render(canvas, el('p', { class: 'alert alert--info', text: 'Choose a function on the Data-Flow Analysis page to draw its control-flow graph.' }));
    render(side, [el('h2', { text: 'Legend' }), renderLegend()]);
    return;
  }

  const graph = state.graph.data;
  if (!graph) {
    render(canvas, el('p', { class: 'empty-state', text: 'Loading graph…' }));
  } else {
    render(canvas, renderGraph(graph, {
      kinds: state.graph.kinds,
      selectedId: state.selectedStatement !== null ? `s${state.selectedStatement}` : null,
      onSelect: onSelectNode,
      emptyMessage: 'No edges of the selected kinds exist in this graph. Enable more kinds to see the program structure.',
    }));
    panel.appendChild(el('p', { class: 'hint', text: `Graph: ${graph.nodes.length} node(s), ${graph.edges.length} edge(s) shown${graph.truncated ? ' (truncated by the API limit)' : ''}.` }));
  }
  canvas.appendChild(panel);

  const statement = state.statementDetail;
  render(side, [
    el('h2', { text: 'Legend' }),
    renderLegend(),
    el('h2', { text: 'Selected statement' }),
    statement
      ? el('div', {}, [
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
        ])
      : el('p', { class: 'empty-state', text: 'Select a node in the graph to see its analysis results.' }),
  ]);
  return container;
}

export async function loadGraph(state, api_) {
  const run = state.run;
  if (!run) return null;
  if (state.graph.mode === 'function') {
    return api_.graph(run.run_id, { kinds: ['call', 'return'] });
  }
  return api_.graph(run.run_id, { kinds: state.graph.kinds });
}
