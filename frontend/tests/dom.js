/**
 * A deliberately small DOM implementation for the frontend tests.
 *
 * The interface code is plain ES modules that touch only a handful of DOM
 * methods (`createElement`, `createTextNode`, `appendChild`, `textContent`,
 * `querySelector`, events, attributes).  This file implements exactly that
 * surface, plus a tiny HTML parser good enough for `index.html`, so the tests
 * can exercise the *real* page structure and the *real* view code without a
 * browser and without a DOM library dependency.
 *
 * What it does NOT do is pretend to be a browser: no layout, no CSS, no
 * rendering.  Text is text; if a test asserts it, it asserts on the DOM tree.
 */

class DomNode {
  constructor(nodeName) {
    this.nodeName = nodeName;
    this.parentNode = null;
    this.childNodes = [];
    this.attributes = new Map();
    this.listenerIndex = new Map();
    // Form/visibility state.  Real elements have these as properties, and the
    // interface assigns to them, so they must exist on the stub too; the
    // initial value comes from the parsed attributes (see `syncFromAttributes`).
    this.value = '';
    this.checked = false;
    this.selected = false;
    this.hidden = false;
    this.disabled = false;
    // Views only ever touch inline styles for the cursor/highlight hints; a
    // plain object is enough for the assertions here.
    this.style = {};
  }

  /** Apply the values implied by this element's attributes. */
  syncFromAttributes() {
    if (this.hasAttribute('value')) this.value = this.getAttribute('value');
    this.checked = this.hasAttribute('checked');
    this.selected = this.hasAttribute('selected');
    this.hidden = this.hasAttribute('hidden');
    this.disabled = this.hasAttribute('disabled');
    return this;
  }

  get nodeType() {
    return 1;
  }

  get firstChild() {
    return this.childNodes.length ? this.childNodes[0] : null;
  }

  get lastChild() {
    return this.childNodes.length ? this.childNodes[this.childNodes.length - 1] : null;
  }

  /** Element children only, like the real `children` property. */
  get children() {
    return this.childNodes.filter((child) => child.nodeType === 1);
  }

  /** Concatenated text of the whole subtree. */
  get textContent() {
    return this.childNodes
      .map((child) => (child.nodeType === 3 ? child.data : child.textContent))
      .join('');
  }

  set textContent(value) {
    this.childNodes = [];
    if (value !== '' && value !== null && value !== undefined) {
      const text = new TextNode(String(value));
      text.parentNode = this;
      this.childNodes.push(text);
    }
  }

  get innerText() {
    return this.textContent;
  }

  set innerText(value) {
    this.textContent = value;
  }

  appendChild(child) {
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }

  removeChild(child) {
    const index = this.childNodes.indexOf(child);
    if (index >= 0) this.childNodes.splice(index, 1);
    child.parentNode = null;
    return child;
  }

  // -- attributes ------------------------------------------------------
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  hasAttribute(name) {
    return this.attributes.has(name);
  }

  get className() {
    return this.getAttribute('class') || '';
  }

  set className(value) {
    this.setAttribute('class', value);
  }

  get classList() {
    const node = this;
    const list = () => node.className.split(/\s+/).filter(Boolean);
    return {
      contains: (name) => list().includes(name),
      add: (name) => {
        if (!list().includes(name)) node.className = [...list(), name].join(' ');
      },
      remove: (name) => {
        node.className = list()
          .filter((entry) => entry !== name)
          .join(' ');
      },
      toggle: (name) => {
        const on = !list().includes(name);
        if (on) node.className = [...list(), name].join(' ');
        else node.className = list().filter((entry) => entry !== name).join(' ');
        return on;
      },
      get value() {
        return list();
      },
    };
  }

  /** `dataset` mirrors `data-*` attributes, as in the real DOM. */
  get dataset() {
    const node = this;
    return new Proxy(
      {},
      {
        get(_target, key) {
          const attribute = dataAttribute(String(key));
          return node.getAttribute(attribute);
        },
        set(_target, key, value) {
          node.setAttribute(dataAttribute(String(key)), String(value));
          return true;
        },
        has(_target, key) {
          return node.hasAttribute(dataAttribute(String(key)));
        },
        ownKeys() {
          return [...node.attributes.keys()]
            .filter((name) => name.startsWith('data-'))
            .map((name) => camelCase(name.slice(5)));
        },
        getOwnPropertyDescriptor(_target, key) {
          const attribute = dataAttribute(String(key));
          if (!node.hasAttribute(attribute)) return undefined;
          return { value: node.getAttribute(attribute), enumerable: true, configurable: true };
        },
      },
    );
  }

  // -- events ----------------------------------------------------------
  addEventListener(type, handler) {
    if (!handler) return;
    const handlers = this.listenerIndex.get(type) || [];
    handlers.push(handler);
    this.listenerIndex.set(type, handlers);
  }

  removeEventListener(type, handler) {
    const handlers = this.listenerIndex.get(type) || [];
    this.listenerIndex.set(
      type,
      handlers.filter((entry) => entry !== handler),
    );
  }

  dispatchEvent(event) {
    const detail = event || {};
    const type = detail.type;
    const payload = { target: this, currentTarget: this, type, preventDefault() {}, ...detail };
    for (const handler of [...(this.listenerIndex.get(type) || [])]) {
      handler(payload);
    }
    return true;
  }

  click() {
    this.dispatchEvent({ type: 'click', target: this });
  }

  change() {
    this.dispatchEvent({ type: 'change', target: this });
  }

  // -- selectors -------------------------------------------------------
  matches(selector) {
    return selector.split(',').some((part) => matchesSimple(this, part.trim()));
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    const found = [];
    for (const part of selector.split(',')) {
      const chain = part.trim().split(/\s+/).filter(Boolean);
      for (const child of this.children) collect(child, chain, found);
    }
    return found;
  }
}

class TextNode extends DomNode {
  constructor(data) {
    super('#text');
    this.data = String(data);
  }

  get nodeType() {
    return 3;
  }

  get textContent() {
    return this.data;
  }

  set textContent(value) {
    this.data = String(value);
  }
}

/** `Node` for `instanceof` checks in `lib/dom.js`. */
export class NodeStub extends DomNode {}

function dataAttribute(key) {
  return `data-${key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}`;
}

function camelCase(key) {
  return key.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
}

function matchesSimple(node, selector) {
  if (!selector) return false;
  if (selector.startsWith('#')) return node.getAttribute('id') === selector.slice(1);
  if (selector.startsWith('.')) return node.classList.contains(selector.slice(1));
  return node.nodeName.toLowerCase() === selector.toLowerCase();
}

function collect(node, chain, found) {
  if (!chain.length) return;
  const [head, ...rest] = chain;
  const matched = matchesSimple(node, head);
  if (matched && !rest.length) {
    found.push(node);
    return;
  }
  for (const child of node.children) {
    if (matched) collect(child, rest, found);
    else collect(child, chain, found);
  }
}

const VOID_TAGS = new Set(['meta', 'link', 'br', 'hr', 'img', 'input', 'source', 'area', 'base', 'col', 'embed', 'track', 'wbr']);
const RAW_TEXT_TAGS = new Set(['script', 'style', 'textarea', 'title']);

/** Parse the subset of HTML that `index.html` uses. */
export function parseHTML(html) {
  const root = new DomNode('#document-fragment');
  const stack = [root];
  let index = 0;
  const top = () => stack[stack.length - 1];

  while (index < html.length) {
    const next = html.indexOf('<', index);
    if (next === -1) {
      appendText(top(), html.slice(index));
      break;
    }
    if (next > index) appendText(top(), html.slice(index, next));
    if (html.startsWith('<!--', next)) {
      const end = html.indexOf('-->', next);
      index = end === -1 ? html.length : end + 3;
      continue;
    }
    if (html.startsWith('<!', next)) {
      const end = html.indexOf('>', next);
      index = end === -1 ? html.length : end + 1;
      continue;
    }
    const close = html.indexOf('>', next);
    if (close === -1) break;
    const raw = html.slice(next + 1, close);
    index = close + 1;
    if (raw.startsWith('/')) {
      const name = raw.slice(1).trim().toLowerCase();
      for (let depth = stack.length - 1; depth > 0; depth -= 1) {
        if (stack[depth].nodeName === name) {
          stack.length = depth;
          break;
        }
      }
      continue;
    }
    const selfClosing = raw.endsWith('/');
    const body = selfClosing ? raw.slice(0, -1) : raw;
    const space = body.search(/\s/);
    const name = (space === -1 ? body : body.slice(0, space)).toLowerCase();
    const element = new DomNode(name);
    const attributes = space === -1 ? '' : body.slice(space + 1);
    for (const match of attributes.matchAll(/([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g)) {
      const value = match[3] ?? match[4] ?? match[5] ?? '';
      element.setAttribute(match[1], value);
    }
    element.syncFromAttributes();
    top().appendChild(element);
    if (VOID_TAGS.has(name) || selfClosing) continue;
    if (RAW_TEXT_TAGS.has(name)) {
      const end = html.toLowerCase().indexOf(`</${name}`, index);
      if (end === -1) {
        index = html.length;
      } else {
        appendText(element, html.slice(index, end));
        const afterClose = html.indexOf('>', end);
        index = afterClose === -1 ? html.length : afterClose + 1;
      }
      continue;
    }
    stack.push(element);
  }
  finaliseSelects(root);
  return root;
}

/** A `<select>` reports the value of its selected (or first) option. */
function finaliseSelects(root) {
  for (const option of root.querySelectorAll('option')) {
    if (!option.hasAttribute('value')) option.value = option.textContent.trim();
  }
  for (const select of root.querySelectorAll('select')) {
    const options = select.querySelectorAll('option');
    const chosen = options.find((option) => option.selected) || options[0];
    if (chosen) select.value = chosen.value;
  }
}

function appendText(parent, text) {
  if (!text) return;
  parent.appendChild(new TextNode(text));
}

/**
 * Install a global `document`/`window` built from `index.html` and return the
 * handles the tests need.
 */
export function installDocument(html) {
  const root = parseHTML(html);
  const documentElement = root.children.find((child) => child.nodeName === 'html') || root;
  const body = documentElement.querySelector('body') || documentElement;
  const head = documentElement.querySelector('head') || documentElement;

  const document = {
    nodeType: 9,
    documentElement,
    head,
    body,
    title: '',
    createElement: (tag) => new DomNode(String(tag).toLowerCase()),
    createElementNS: (_namespace, tag) => new DomNode(String(tag).toLowerCase()),
    createTextNode: (data) => new TextNode(data),
    getElementById: (id) => documentElement.querySelector(`#${id}`),
    querySelector: (selector) => documentElement.querySelector(selector),
    querySelectorAll: (selector) => documentElement.querySelectorAll(selector),
    addEventListener() {},
  };

  const windowListeners = new Map();
  const window = {
    location: { hash: '' },
    addEventListener(type, handler) {
      if (!handler) return;
      windowListeners.set(type, [...(windowListeners.get(type) || []), handler]);
    },
    removeEventListener(type, handler) {
      windowListeners.set(type, (windowListeners.get(type) || []).filter((entry) => entry !== handler));
    },
    dispatchEvent(event) {
      for (const handler of [...(windowListeners.get(event.type) || [])]) handler(event);
      return true;
    },
    setTimeout,
    clearTimeout,
  };

  return { document, window, root, documentElement, body, head };
}

export { DomNode, TextNode };
