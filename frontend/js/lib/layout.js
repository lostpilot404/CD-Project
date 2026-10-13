/**
 * Deterministic layered layout for program graphs.
 *
 * The layout is computed, not simulated: nodes are assigned to layers by a
 * breadth-first pass over the edges, nodes inside a layer are ordered by their
 * id, and an edge is dropped from the layering (never expanded again) when its
 * target has already been placed, so cyclic graphs terminate.  The result is
 * therefore stable for a given graph -- the same analysis always draws the same
 * picture, which matters when a reviewer compares two runs.
 */

export const DEFAULT_NODE_WIDTH = 168;
export const DEFAULT_NODE_HEIGHT = 34;
export const DEFAULT_GAP_X = 220;
export const DEFAULT_GAP_Y = 46;

/** Layers of node ids, in order of increasing distance from a root. */
export function computeLayers(nodes, edges) {
  const ids = nodes.map((node) => node.id);
  const idSet = new Set(ids);
  const outgoing = new Map(ids.map((id) => [id, []]));
  const incomingCount = new Map(ids.map((id) => [id, 0]));
  for (const edge of edges) {
    if (!idSet.has(edge.from) || !idSet.has(edge.to) || edge.from === edge.to) continue;
    outgoing.get(edge.from).push(edge.to);
    incomingCount.set(edge.to, incomingCount.get(edge.to) + 1);
  }
  for (const list of outgoing.values()) list.sort();
  const layer = new Map();
  const roots = ids.filter((id) => incomingCount.get(id) === 0).sort();
  // Breadth-first layering: a node is placed once, at one more than the layer
  // of the node that reached it first, and is never re-expanded.  An edge whose
  // target already has a layer cannot change it, so it is dropped from the
  // layering and drawn as it is -- that is how cycles (loop back edges, CFG
  // backedges, dependency edges that close a cycle) are broken.  Because every
  // node is placed at most once, the pass always terminates, which a
  // longest-path relaxation over a cyclic graph would not.
  const queue = [];
  for (const id of roots.length ? roots : ids.slice().sort()) {
    layer.set(id, 0);
    queue.push(id);
  }
  while (queue.length) {
    const id = queue.shift();
    const current = layer.get(id) || 0;
    for (const target of outgoing.get(id)) {
      if (layer.has(target)) continue;
      layer.set(target, current + 1);
      queue.push(target);
    }
  }
  for (const id of ids) if (!layer.has(id)) layer.set(id, 0);
  const maxLayer = Math.max(0, ...layer.values());
  const layers = [];
  for (let index = 0; index <= maxLayer; index += 1) layers.push([]);
  for (const id of ids.slice().sort()) layers[layer.get(id)].push(id);
  return { layers, layerOf: layer };
}

/** Positions for every node, plus the drawing size. */
export function layoutGraph(nodes, edges, options = {}) {
  const width = options.nodeWidth || DEFAULT_NODE_WIDTH;
  const height = options.nodeHeight || DEFAULT_NODE_HEIGHT;
  const gapX = options.gapX || DEFAULT_GAP_X;
  const gapY = options.gapY || DEFAULT_GAP_Y;
  const { layers, layerOf } = computeLayers(nodes, edges);
  const positions = new Map();
  let maxRows = 0;
  layers.forEach((ids, layerIndex) => {
    maxRows = Math.max(maxRows, ids.length);
    ids.forEach((id, rowIndex) => {
      positions.set(id, {
        x: 20 + layerIndex * gapX,
        y: 20 + rowIndex * gapY,
        width,
        height,
      });
    });
  });
  const totalWidth = 40 + Math.max(1, layers.length) * gapX;
  const totalHeight = 40 + Math.max(1, maxRows) * gapY;
  return { positions, layers, layerOf, width: totalWidth, height: totalHeight };
}

/** Trim a label to fit a node, keeping the informative prefix. */
export function shortenLabel(label, max = 24) {
  const text = String(label || '').replace(/\s+/g, ' ').trim();
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

/**
 * Choose the edges worth drawing.
 *
 * A program dependency graph can be large; drawing every edge of a big file
 * produces an unreadable picture, so the caller passes the kinds it cares about
 * and this function drops duplicates and self-loops of the `sanitize` kind that
 * carry no positional information.
 */
export function selectEdges(edges, { kinds = null, limit = 1500 } = {}) {
  const wanted = kinds && kinds.length ? new Set(kinds) : null;
  const kept = [];
  const seen = new Set();
  let dropped = 0;
  for (const edge of edges) {
    if (wanted && !wanted.has(edge.kind) && !wanted.has(edge.family)) continue;
    const key = `${edge.from}->${edge.to}:${edge.kind}`;
    if (seen.has(key)) continue;
    seen.add(key);
    if (kept.length >= limit) {
      dropped += 1;
      continue;
    }
    kept.push(edge);
  }
  return { edges: kept, dropped };
}
