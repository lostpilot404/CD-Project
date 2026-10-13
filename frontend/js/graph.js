/**
 * SVG renderer for the program dependency graph, the CFG and slice views.
 *
 * The renderer is deliberately small: a deterministic layered layout
 * (`lib/layout.js`), one `<g>` per node, one `<path>` per edge, keyboard
 * selection and a legend.  It never draws a node or an edge the API did not
 * return, and it says so when a graph was truncated because of its size.
 */

import { el, render } from './lib/dom.js';
import { layoutGraph, selectEdges, shortenLabel } from './lib/layout.js';

const SVG_NS = 'http://www.w3.org/2000/svg';

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined) continue;
    node.setAttribute(key, String(value));
  }
  return node;
}

export const EDGE_LEGEND = [
  { kind: 'data', label: 'data (a definition reaches a read)', className: '' },
  { kind: 'taint', label: 'taint (that data is untrusted)', className: 'legend__swatch--taint' },
  { kind: 'control', label: 'control (guarded by a condition)', className: 'legend__swatch--control' },
  { kind: 'call', label: 'call (statement → callee)', className: 'legend__swatch--call' },
  { kind: 'return', label: 'return (callee → call site)', className: 'legend__swatch--call' },
  { kind: 'sanitize', label: 'sanitize (a rule removes this taint)', className: 'legend__swatch--sanitize' },
  { kind: 'define', label: 'define (statement → its definition)', className: 'legend__swatch--define' },
];

export function renderLegend() {
  return el('ul', { class: 'legend' }, [
    el('li', {}, [el('span', { class: 'legend__swatch' }), 'data edge']),
    ...EDGE_LEGEND.slice(1).map((entry) =>
      el('li', {}, [el('span', { class: `legend__swatch ${entry.className}` }), entry.label]),
    ),
  ]);
}

/**
 * Render a graph.
 *
 * @param {object} graph  `{nodes, edges, truncated, limit}` as returned by the API
 * @param {object} options `{onSelect, selectedId, maxNodes, kinds, emptyMessage}`
 */
export function renderGraph(graph, options = {}) {
  const container = el('div');
  const nodes = (graph && graph.nodes) || [];
  const edges = (graph && graph.edges) || [];
  const maxNodes = options.maxNodes || 400;

  if (!nodes.length) {
    render(container, el('p', { class: 'empty-state', text: options.emptyMessage || 'No graph data for this selection.' }));
    return container;
  }
  if (nodes.length > maxNodes) {
    const button = el('button', {
      type: 'button',
      class: 'button button--small',
      text: `Draw anyway (${nodes.length} nodes)`,
      on: { click: () => render(container, buildSvg(nodes, edges, options)) },
    });
    render(container, [
      el('p', {
        class: 'alert alert--warn',
        text: `This graph has ${nodes.length} nodes. Rendering it is possible but the picture will be dense;`,
      }),
      button,
    ]);
    return container;
  }
  render(container, buildSvg(nodes, edges, options));
  return container;
}

function buildSvg(nodes, edges, options) {
  const { edges: drawn, dropped } = selectEdges(edges, { kinds: options.kinds || null, limit: options.edgeLimit || 2000 });
  const { positions, width, height } = layoutGraph(nodes, drawn, options.layout || {});
  const root = svg('svg', {
    class: 'graph-svg',
    viewBox: `0 0 ${width} ${height}`,
    // Natural size, not 100%: a layered graph scaled down to fit the canvas
    // becomes unreadable, so the canvas scrolls instead.  The height attribute
    // must match the viewBox height — capping it here used to shrink tall
    // graphs into an unreadable strip.
    width: width,
    height: Math.max(240, height),
    role: 'img',
    'aria-label': `Program graph with ${nodes.length} nodes and ${drawn.length} edges`,
  });
  const defs = svg('defs');
  const marker = svg('marker', {
    id: 'arrow', viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '6', markerHeight: '6', orient: 'auto-start-reverse',
  });
  marker.appendChild(svg('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: 'currentColor' }));
  defs.appendChild(marker);
  root.appendChild(defs);

  for (const edge of drawn) {
    const from = positions.get(edge.from);
    const to = positions.get(edge.to);
    if (!from || !to) continue;
    const x1 = from.x + from.width;
    const y1 = from.y + from.height / 2;
    const x2 = to.x;
    const y2 = to.y + to.height / 2;
    const control = Math.max(20, Math.abs(x2 - x1) / 2);
    const path = svg('path', {
      class: `edge edge--${edge.kind}`,
      d: `M ${x1} ${y1} C ${x1 + control} ${y1}, ${x2 - control} ${y2}, ${x2} ${y2}`,
      color: 'currentColor',
    });
    const title = svg('title');
    title.textContent = `${edge.kind}: ${edge.reason || 'dependency edge'}`;
    path.appendChild(title);
    root.appendChild(path);
  }

  for (const node of nodes) {
    const position = positions.get(node.id);
    if (!position) continue;
    const group = svg('g', {
      class: `node node--${node.kind}${options.selectedId === node.id ? ' node--selected' : ''}`,
      tabindex: '0',
      role: 'button',
      'aria-label': `${node.kind} ${node.label} (line ${node.line})`,
      transform: `translate(${position.x}, ${position.y})`,
    });
    group.appendChild(svg('rect', { width: position.width, height: position.height, rx: '6' }));
    const label = svg('text', { x: '8', y: '14' });
    label.textContent = shortenLabel(node.label, 26);
    group.appendChild(label);
    const sub = svg('text', { x: '8', y: '27', class: 'node__sub' });
    sub.textContent = `line ${node.line}${node.symbol ? ` · ${node.symbol}` : ''}`;
    group.appendChild(sub);
    const select = () => options.onSelect && options.onSelect(node);
    group.addEventListener('click', select);
    group.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        select();
      }
    });
    root.appendChild(group);
  }

  const wrapper = el('div');
  wrapper.appendChild(root);
  if (dropped) {
    wrapper.appendChild(
      el('p', {
        class: 'alert alert--warn',
        text: `${dropped} further edge(s) were not drawn: the graph is larger than the drawing limit. Use the filters to narrow it.`,
      }),
    );
  }
  return wrapper;
}
