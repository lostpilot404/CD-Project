/**
 * Unit tests for the frontend's pure modules: DOM helpers (escaping), finding
 * filters, graph layout and the SVG renderer's edge selection.
 *
 * Run with `node --test frontend/tests/` or `npm test` inside `frontend/`.
 * These tests need no engine and no browser: they import the same ES modules
 * the page loads.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { installDocument } from './dom.js';
import { el, render, clear, append, code } from '../js/lib/dom.js';
import {
  CERTAINTY_ORDER,
  SEVERITY_ORDER,
  countBySeverity,
  describeComparison,
  facet,
  filterFindings,
  matchesSearch,
  sortFindings,
} from '../js/lib/filter.js';
import { computeLayers, layoutGraph, selectEdges, shortenLabel } from '../js/lib/layout.js';
import { EDGE_LEGEND, renderGraph, renderLegend } from '../js/graph.js';

const { document } = installDocument('<html><body></body></html>');
globalThis.document = document;
globalThis.Node = document.createElement('div').constructor;

test('lib/dom.js inserts text, never markup', () => {
  const hostile = '<img src=x onerror="alert(1)">';
  const node = el('p', { text: hostile });
  assert.equal(node.textContent, hostile);
  assert.equal(node.children.length, 0, 'no element may be created from analysed source');

  const parent = el('div', {}, ['a <b> c', el('span', { text: '</span>' })]);
  assert.equal(parent.textContent, 'a <b> c</span>');
  assert.equal(parent.children.length, 1);
});

test('lib/dom.js sets attributes, classes, datasets and listeners', () => {
  let clicks = 0;
  const button = el('button', {
    class: 'button',
    type: 'button',
    dataset: { sid: 12, role: 'finding' },
    on: { click: () => { clicks += 1; } },
    'aria-label': 'select finding',
  }, 'click me');
  assert.equal(button.getAttribute('class'), 'button');
  assert.equal(button.getAttribute('type'), 'button');
  assert.equal(button.getAttribute('aria-label'), 'select finding');
  assert.equal(button.dataset.sid, '12');
  assert.equal(button.getAttribute('data-role'), 'finding');
  assert.equal(button.textContent, 'click me');
  button.click();
  button.click();
  assert.equal(clicks, 2);
});

test('lib/dom.js render replaces children and skips empty values', () => {
  const host = el('div', {}, ['old']);
  render(host, [null, undefined, false, '', 'new']);
  assert.equal(host.textContent, 'new');
  append(host, [' more', [el('span', { text: '!' })]]);
  assert.equal(host.textContent, 'new more!');
  clear(host);
  assert.equal(host.textContent, '');
  assert.equal(host.children.length, 0);
  assert.equal(code('x = 1;').textContent, 'x = 1;');
});

test('lib/filter.js facets, search and filters', () => {
  const findings = [
    finding({ id: 'F1', severity: 'HIGH', category: 'command-injection', rule: 'RULE001', certainty: 'confirmed', line: 9 }),
    finding({ id: 'F2', severity: 'MEDIUM', category: 'format-string', rule: 'RULE005', certainty: 'approximate', line: 4, function_name: 'printf', statement_text: 'printf(fmt);' }),
    finding({ id: 'F3', severity: 'LOW', category: 'format-string', rule: 'RULE005', certainty: 'unproven', line: 12, function_name: 'printf', statement_text: 'printf(fmt);' }),
  ];
  assert.deepEqual(facet(findings, (item) => item.severity), ['HIGH', 'LOW', 'MEDIUM']);
  assert.deepEqual(facet(findings, (item) => item.category), ['command-injection', 'format-string']);
  assert.equal(filterFindings(findings, {}).length, 3);
  assert.deepEqual(filterFindings(findings, { severity: 'LOW' }).map((f) => f.id), ['F3']);
  assert.deepEqual(filterFindings(findings, { category: 'format-string' }).map((f) => f.id), ['F2', 'F3']);
  assert.deepEqual(filterFindings(findings, { rule: 'RULE001' }).map((f) => f.id), ['F1']);
  assert.deepEqual(filterFindings(findings, { certainty: 'unproven' }).map((f) => f.id), ['F3']);
  assert.deepEqual(filterFindings(findings, { search: 'printf' }).map((f) => f.id), ['F2', 'F3']);
  assert.deepEqual(filterFindings(findings, { search: 'system' }).map((f) => f.id), ['F1']);
  assert.deepEqual(filterFindings(findings, { search: 'rule005' }).map((f) => f.id), ['F2', 'F3']);
  assert.equal(matchesSearch(findings[0], ''), true);

  const resolved = new Set(['F2']);
  assert.deepEqual(filterFindings(findings, { status: 'open' }, { resolvedIds: resolved }).map((f) => f.id), ['F1', 'F3']);
  assert.deepEqual(filterFindings(findings, { status: 'fixed' }, { resolvedIds: resolved }).map((f) => f.id), ['F2']);
  assert.deepEqual(filterFindings(findings, { file: 'helper' }).map((f) => f.id), ['F2']);
});

test('lib/filter.js sorts deterministically and counts severities', () => {
  const findings = [
    finding({ id: 'F3', severity: 'LOW', line: 12 }),
    finding({ id: 'F1', severity: 'HIGH', certainty: 'approximate', line: 9 }),
    finding({ id: 'F0', severity: 'HIGH', certainty: 'confirmed', line: 20 }),
    finding({ id: 'F2', severity: 'MEDIUM', line: 4 }),
  ];
  assert.deepEqual(sortFindings(findings).map((f) => f.id), ['F0', 'F1', 'F2', 'F3']);
  assert.deepEqual(sortFindings(findings, 'line').map((f) => f.id), ['F2', 'F1', 'F3', 'F0']);
  // confirmed first (by line: F2 4, F3 12, F0 20), then approximate (F1).
  assert.deepEqual(sortFindings(findings, 'certainty').map((f) => f.id), ['F2', 'F3', 'F0', 'F1']);
  // Sorting must not mutate the caller's array.
  assert.equal(findings[0].id, 'F3');
  assert.deepEqual(countBySeverity(findings), {
    CRITICAL: 0, HIGH: 2, MEDIUM: 1, LOW: 1, INFO: 0,
  });
  assert.equal(SEVERITY_ORDER.CRITICAL, 0);
  assert.equal(CERTAINTY_ORDER.confirmed, 0);
  assert.equal(describeComparison(null).length, 0);
  assert.deepEqual(
    describeComparison({ summary: { new: 1, resolved: 2, persistent: 3, moved: 4 } }).map((entry) => entry.value),
    [1, 2, 3, 4],
  );
});

test('lib/layout.js layers follow edges and are stable', () => {
  const nodes = ['entry', 'a', 'b', 'c'].map((id) => ({ id }));
  const edges = [
    { from: 'entry', to: 'a' },
    { from: 'entry', to: 'b' },
    { from: 'a', to: 'c' },
    { from: 'b', to: 'c' },
  ];
  const first = computeLayers(nodes, edges);
  const second = computeLayers(nodes, edges);
  assert.deepEqual(first.layers, [['entry'], ['a', 'b'], ['c']]);
  assert.deepEqual([...first.layerOf], [...second.layerOf]);
  const layout = layoutGraph(nodes, edges);
  assert.equal(layout.positions.size, 4);
  // Nodes in the same layer share an x coordinate; deeper layers move right.
  assert.equal(layout.positions.get('a').x, layout.positions.get('b').x);
  assert.ok(layout.positions.get('c').x > layout.positions.get('a').x);
  assert.notEqual(layout.positions.get('a').y, layout.positions.get('b').y);
  assert.ok(layout.width > 0 && layout.height > 0);
});

test('lib/layout.js breaks cycles instead of looping forever', () => {
  // A plain cycle has no root; every node is still placed exactly once.
  const cyclic = computeLayers(
    [{ id: 'h' }, { id: 'b' }],
    [
      { from: 'h', to: 'b' },
      { from: 'b', to: 'h' },
    ],
  );
  assert.deepEqual(cyclic.layers.flat().sort(), ['b', 'h']);
  assert.equal(cyclic.layers.length, 1);

  // A loop reachable from a root: the back edge must not move its target, so
  // layering terminates and the loop is drawn as a back edge.
  const loop = computeLayers(
    [{ id: 'entry' }, { id: 'header' }, { id: 'body' }],
    [
      { from: 'entry', to: 'header' },
      { from: 'header', to: 'body' },
      { from: 'body', to: 'header' },
    ],
  );
  assert.deepEqual(loop.layers, [['entry'], ['header'], ['body']]);
  assert.ok(loop.layers.length < 4);
});

test('lib/layout.js edge selection filters by kind and reports drops', () => {
  const edges = [
    { from: 's0', to: 's1', kind: 'data', family: 'data' },
    { from: 's0', to: 's1', kind: 'data', family: 'data' }, // duplicate
    { from: 's1', to: 's2', kind: 'control', family: 'control' },
    { from: 's2', to: 's3', kind: 'taint', family: 'data' },
  ];
  assert.equal(selectEdges(edges).edges.length, 3);
  assert.deepEqual(selectEdges(edges, { kinds: ['control'] }).edges.map((edge) => edge.kind), ['control']);
  // `taint` is a member of the `data` family, so filtering by family keeps it.
  assert.deepEqual(
    selectEdges(edges, { kinds: ['data'] }).edges.map((edge) => edge.kind),
    ['data', 'taint'],
  );
  const capped = selectEdges(edges, { limit: 1 });
  assert.equal(capped.edges.length, 1);
  assert.equal(capped.dropped, 2);
  assert.equal(shortenLabel('  a   very\nlong label  ', 10), 'a very lo…');
  assert.equal(shortenLabel('short', 10), 'short');
  assert.equal(shortenLabel(null), '');
});

test('graph.js renders an SVG with one group per node and one path per edge', () => {
  const graph = {
    nodes: [
      { id: 's0', kind: 'statement', label: 'int a = 1;', line: 2, symbol: 'a' },
      { id: 's1', kind: 'statement', label: 'return a;', line: 3, symbol: null },
    ],
    edges: [{ from: 's0', to: 's1', kind: 'data', reason: 'definition of a reaches the read' }],
  };
  const container = renderGraph(graph, { onSelect: () => {} });
  const svg = container.querySelector('svg');
  assert.ok(svg, 'an svg element is rendered');
  assert.equal(svg.getAttribute('viewBox').startsWith('0 0 '), true);
  assert.equal(container.querySelectorAll('g').length, 2);
  assert.equal(container.querySelectorAll('path').length, 2, 'one edge path plus the arrow marker');
  const labels = container.querySelectorAll('text').map((node) => node.textContent);
  assert.ok(labels.includes('int a = 1;'));
  assert.ok(labels.includes('line 3'));
});

test('graph.js states when a graph is empty or too large', () => {
  const empty = renderGraph({ nodes: [], edges: [] }, {});
  assert.match(empty.textContent, /No graph data/);
  const emptyCustom = renderGraph({ nodes: [], edges: [] }, { emptyMessage: 'nothing here' });
  assert.match(emptyCustom.textContent, /nothing here/);

  const many = {
    nodes: Array.from({ length: 5 }, (_value, index) => ({ id: `s${index}`, kind: 'statement', label: 'x', line: index + 1 })),
    edges: [],
  };
  const big = renderGraph(many, { maxNodes: 3 });
  assert.match(big.textContent, /This graph has 5 nodes/);
  const button = big.querySelector('button');
  assert.ok(button, 'a button offers to draw it anyway');
  button.click();
  assert.ok(big.querySelector('svg'), 'clicking the button draws the graph');
});

test('graph.js legend describes every drawn edge kind', () => {
  const legend = renderLegend();
  const text = legend.textContent;
  for (const kind of ['data', 'taint', 'control', 'call', 'return', 'sanitize', 'define']) {
    assert.ok(text.includes(kind), `legend mentions ${kind}`);
  }
  assert.equal(EDGE_LEGEND.length, 7);
});

test('renderGraph handles missing node positions without throwing', () => {
  const container = renderGraph(
    {
      nodes: [{ id: 's0', kind: 'statement', label: 'a', line: 1 }],
      edges: [{ from: 's0', to: 's99', kind: 'data', reason: 'dangling' }],
    },
    {},
  );
  assert.equal(container.querySelectorAll('g').length, 1);
});

function finding({
  id,
  severity = 'HIGH',
  category = 'command-injection',
  rule = 'RULE001',
  certainty = 'confirmed',
  line = 1,
  function_name = 'system',
  statement_text = 'system(cmd);',
}) {
  return {
    id,
    rule_id: rule,
    category,
    severity,
    certainty,
    confidence: 'high',
    explanation: 'potential command-injection flow detected',
    explanation: `potential ${category} flow detected`,
    source: { rule: 'input', function: 'input', line: 3, statement_text: 'string cmd = input();' },
    sink: {
      function: function_name,
      line,
      statement_text: statement_text,
      enclosing_function: line === 4 ? 'helper' : 'main',
    },
  };
}
