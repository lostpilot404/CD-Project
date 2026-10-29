/**
 * Program Graph view: the dependency graph, a single CFG, or the subgraph of a
 * finding / slice.  Selecting a node fetches that statement's analysis results
 * (reaching definitions, live variables, taint, control dependencies) from the
 * API, so the panel always shows engine output.
 */
import { el, render } from '../lib/dom.js';
import { api } from '../api.js';
import { renderGraph, renderLegend } from '../graph.js';
import { renderStatementDetail } from './statement.js';

const KINDS = [
  ['data', 'data'],
  ['taint', 'taint only'],
  ['control', 'control'],
  ['call', 'call'],
  ['return', 'return'],
  ['define', 'definition'],
  ['sanitize', 'sanitization'],
  ['source-to-sink', 'source-to-sink'],
];

const CFG_EDGE_KINDS = [
  ['sequential', 'straight-line flow from one block to the next'],
  ['true', 'branch taken (the condition holds)'],
  ['false', 'branch not taken'],
  ['loop-back', 'end of a loop body, back to its header'],
  ['return', 'a return statement leaves the function'],
  ['break', 'a break leaves the loop'],
  ['continue', 'a continue jumps to the loop header'],
  ['exit', 'end of the function'],
];

/**
 * Convert one function's CFG (as returned by `/api/runs/{id}/cfg`) into the
 * node/edge shape the SVG renderer draws.  One block becomes one node; the
 * node's `sid` is the block's first statement, so clicking a block selects the
 * statement the block starts with.
 */
export function cfgToGraph(cfg, statementsById = {}) {
  const nodes = (cfg.blocks || []).map((block) => {
    const sids = block.statement_ids || [];
    const firstText = sids.length && statementsById[sids[0]] ? `: ${statementsById[sids[0]]}` : '';
    const firstLine = (block.statements || []).reduce(
      (lowest, statement) => (lowest === null || statement.line < lowest ? statement.line : lowest),
      null,
    );
    return {
      id: `b${block.id}`,
      kind: 'block',
      label: `B${block.id} · ${block.kind}${firstText}`,
      line: firstLine || 0,
      symbol: null,
      sid: sids.length ? sids[0] : -1,
      sids,
    };
  });
  const edges = [];
  for (const block of cfg.blocks || []) {
    for (const successor of block.successors || []) {
      edges.push({
        from: `b${successor.from}`,
        to: `b${successor.to}`,
        kind: successor.kind,
        family: successor.kind,
        reason: successor.condition || successor.label || successor.kind,
      });
    }
  }
  return {
    function: cfg.function,
    nodes,
    edges,
    truncated: false,
    limit: edges.length,
  };
}

function renderCfgLegend() {
  return el('ul', { class: 'legend' }, CFG_EDGE_KINDS.map(([kind, description]) =>
    el('li', {}, [
      el('span', { class: `legend__swatch legend__swatch--cfg-${kind}` }),
      el('span', {}, [el('span', { class: 'mono', text: kind }), ` — ${description}`]),
    ])));
}

export function renderGraphView(container, { state, onSelectNode, onMode, onKinds, onCfgFunction }) {
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
  const functions = (run.summary && run.summary.functions) || [];
  const cfgFunction = state.graph.cfgFunction && functions.includes(state.graph.cfgFunction)
    ? state.graph.cfgFunction
    : functions[0] || null;
  const toolbarControls = [
    el('label', { class: 'field' }, [
      el('span', { text: 'Graph' }),
      el('select', { on: { change: (event) => onMode(event.target.value) } },
        modes.map(([value, label]) => el('option', { value, selected: value === state.graph.mode, text: label }))),
    ]),
  ];
  if (state.graph.mode === 'cfg') {
    toolbarControls.push(
      el('label', { class: 'field' }, [
        el('span', { text: 'Function' }),
        el('select', { on: { change: (event) => onCfgFunction(event.target.value) } },
          functions.map((name) => el('option', { value: name, selected: name === cfgFunction, text: `${name}()` }))),
      ]),
    );
  } else if (state.graph.mode === 'dependency') {
    // Only the dependency-graph mode filters by edge kind.  The function-level
    // view always asks the API for exactly the call and return edges; showing
    // the checkboxes there offered controls that changed nothing (and an
    // "enable more kinds" hint for a filter that mode does not have).
    toolbarControls.push(
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
    );
  }
  render(toolbar, el('div', { class: 'row row--wrap' }, toolbarControls));

  const panel = el('div');
  if (state.graph.mode === 'function') {
    render(panel, el('p', { class: 'hint', text: 'Function-level view: every edge is a call or a return between the analysed functions.' }));
  }

  if (state.graph.mode === 'cfg') {
    renderCfg(canvas, side, panel, { state, run, functions, cfgFunction, onSelectNode });
    return;
  }

  if (run.summary && run.summary.dependencies_built === false) {
    render(canvas, el('p', {
      class: 'empty-state',
      text: 'The dependency graph was not built for this run: the analysis ran with “Build the program dependency graph and slices” switched off. Run the analysis again with that option enabled to draw it.',
    }));
    render(side, [el('h2', { text: 'Legend' }), renderLegend()]);
    return;
  }

  const graph = state.graph.data;
  if (state.graph.mode === 'dependency' && !state.graph.kinds.length) {
    // Unchecking every kind sent no filter at all, and the engine's documented
    // default for an empty filter is *every* kind, so "no kinds" silently drew
    // all of them.  Say what is happening and offer the way back.  The
    // function-level view ignores the kind filter entirely, so the gate does
    // not apply there.
    render(canvas, el('div', {}, [
      el('p', { class: 'alert alert--info' },
        'No edge kinds are selected, so no edges are drawn. Select at least one kind, or use the button below.'),
      el('button', {
        type: 'button',
        class: 'button button--small',
        text: 'Select all edge kinds',
        on: {
          click: () => {
            for (const [kind] of KINDS) if (!state.graph.kinds.includes(kind)) onKinds(kind, true);
          },
        },
      }),
    ]));
    render(side, [el('h2', { text: 'Legend' }), renderLegend()]);
    return;
  }
  if (state.graph.loadError) {
    render(canvas, el('p', { class: 'alert alert--error', text: `Could not load the program graph: ${state.graph.loadError}` }));
  } else if (!graph) {
    render(canvas, el('p', { class: 'empty-state', text: 'Loading graph…' }));
  } else {
    // "Show in Program Graph" on the Findings page stores the finding's id as
    // the graph's focus; the sink statement's node is highlighted so the jump
    // lands somewhere the eye can follow.  Without this the focus value was
    // set and never rendered.
    const focused = state.graph.focus
      ? ((run.findings || []).find((finding) => finding.id === state.graph.focus) || null)
      : null;
    const focusIds = focused && focused.sink && focused.sink.sid !== null && focused.sink.sid !== undefined
      ? new Set([`s${focused.sink.sid}`])
      : null;
    const functionMode = state.graph.mode === 'function';
    render(canvas, renderGraph(graph, {
      // The function-level payload is already exactly the call/return edges;
      // filtering it again with the dependency mode's kind checkboxes hid
      // edges the mode promised to show.
      kinds: functionMode ? null : state.graph.kinds,
      selectedId: state.selectedStatement !== null ? `s${state.selectedStatement}` : null,
      focusIds,
      onSelect: onSelectNode,
      emptyMessage: functionMode
        ? 'This program has no calls or returns between analysed functions, so the function-level view is empty.'
        : 'No edges of the selected kinds exist in this graph. Enable more kinds to see the program structure.',
    }));
    if (focused) {
      panel.appendChild(el('p', {
        class: 'hint',
        text: `Focused finding ${focused.id} (${focused.rule_id}, ${focused.severity}): its sink statement is highlighted.`,
      }));
    }
    panel.appendChild(el('p', { class: 'hint', text: `Graph: ${graph.nodes.length} node(s), ${graph.edges.length} edge(s) shown${graph.truncated ? ' (truncated by the API limit)' : ''}.` }));
  }
  canvas.appendChild(panel);

  render(side, [
    el('h2', { text: 'Legend' }),
    renderLegend(),
    el('h2', { text: 'Selected statement' }),
    renderStatementDetail(state.statementDetail),
  ]);
  return container;
}

function renderCfg(canvas, side, panel, { state, run, functions, cfgFunction, onSelectNode }) {
  if (!functions.length) {
    render(canvas, el('p', {
      class: 'empty-state',
      text: 'This run declares no function, so there is no control-flow graph to draw.',
    }));
    render(side, [el('h2', { text: 'Legend' }), renderCfgLegend()]);
    return;
  }
  const graph = state.graph.data;
  if (!state.graph.kinds.length) {
    // Unchecking every kind sent no filter at all, and the engine's documented
    // default for an empty filter is *every* kind, so "no kinds" silently drew
    // all of them.  Say what is happening and offer the way back.
    render(canvas, el('div', {}, [
      el('p', { class: 'alert alert--info' },
        'No edge kinds are selected, so no edges are drawn. Select at least one kind, or use the button below.'),
      el('button', {
        type: 'button',
        class: 'button button--small',
        text: 'Select all edge kinds',
        on: {
          click: () => {
            for (const [kind] of KINDS) if (!state.graph.kinds.includes(kind)) onKinds(kind, true);
          },
        },
      }),
    ]));
    render(side, [el('h2', { text: 'Legend' }), renderLegend()]);
    return;
  }
  if (state.graph.loadError) {
    render(canvas, el('p', { class: 'alert alert--error', text: `Could not load the control-flow graph: ${state.graph.loadError}` }));
  } else if (!graph || graph.function !== cfgFunction) {
    render(canvas, el('p', { class: 'empty-state' }, [el('span', { class: 'spinner' }), ` loading the control-flow graph of ${cfgFunction}()…`]));
  } else {
    const selectedId = state.selectedStatement !== null
      ? ((graph.nodes || []).find((node) => (node.sids || []).includes(state.selectedStatement)) || {}).id || null
      : null;
    render(canvas, renderGraph(graph, {
      kinds: null,
      selectedId,
      onSelect: onSelectNode,
      emptyMessage: `The control-flow graph of ${cfgFunction}() has no blocks.`,
    }));
    const kinds = [...new Set((graph.edges || []).map((edge) => edge.kind))].sort();
    panel.appendChild(el('p', {
      class: 'hint',
      text: `Control-flow graph of ${cfgFunction}(): ${graph.nodes.length} block(s), ${graph.edges.length} edge(s)`
        + (kinds.length ? ` (kinds: ${kinds.join(', ')})` : '') + '.',
    }));
  }
  canvas.appendChild(panel);

  render(side, [
    el('h2', { text: 'Legend' }),
    renderCfgLegend(),
    el('h2', { text: 'Selected statement' }),
    el('p', { class: 'hint', text: 'Clicking a block selects the statement the block starts with.' }),
    renderStatementDetail(state.statementDetail),
  ]);
}

export async function loadGraph(state, api_) {
  const run = state.run;
  if (!run) return null;
  if (state.graph.mode === 'cfg') {
    const functions = (run.summary && run.summary.functions) || [];
    const fn = state.graph.cfgFunction && functions.includes(state.graph.cfgFunction)
      ? state.graph.cfgFunction
      : functions[0];
    if (!fn) throw new Error('this run declares no function to draw');
    const cfg = await api_.cfg(run.run_id, fn);
    return cfgToGraph(cfg, state.statementsById || {});
  }
  if (state.graph.mode === 'function') {
    return api_.graph(run.run_id, { kinds: ['call', 'return'] });
  }
  return api_.graph(run.run_id, { kinds: state.graph.kinds });
}
