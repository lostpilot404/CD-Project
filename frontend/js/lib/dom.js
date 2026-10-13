/**
 * Minimal DOM helpers.
 *
 * Everything that renders analysed source text goes through these helpers, and
 * text is always inserted with `document.createTextNode` or `textContent`,
 * never with `innerHTML`.  Analysed source is untrusted input: if it contained
 * markup it must be shown as characters, not interpreted.
 */

/** Create an element. `attrs` sets attributes/properties, `children` appends. */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'text') {
      node.textContent = String(value);
    } else if (key === 'class') {
      node.className = String(value);
    } else if (key === 'dataset') {
      for (const [dataKey, dataValue] of Object.entries(value)) {
        if (dataValue !== null && dataValue !== undefined) node.dataset[dataKey] = String(dataValue);
      }
    } else if (key === 'on') {
      for (const [eventName, handler] of Object.entries(value)) {
        node.addEventListener(eventName, handler);
      }
    } else if (key in node && typeof value !== 'string' && key !== 'list') {
      node[key] = value;
    } else {
      node.setAttribute(key, String(value));
    }
  }
  append(node, children);
  return node;
}

/** Append children, flattening arrays and skipping null/undefined/false. */
export function append(parent, children) {
  const list = Array.isArray(children) ? children : [children];
  for (const child of list) {
    if (child === null || child === undefined || child === false || child === '') continue;
    if (Array.isArray(child)) append(parent, child);
    else if (child instanceof Node) parent.appendChild(child);
    else parent.appendChild(document.createTextNode(String(child)));
  }
  return parent;
}

/** Remove every child of a node. */
export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

/** Replace the contents of a node with new children. */
export function render(node, children) {
  clear(node);
  append(node, children);
  return node;
}

/** A labelled `<code>` span. */
export function code(text) {
  return el('code', { text: String(text) });
}
