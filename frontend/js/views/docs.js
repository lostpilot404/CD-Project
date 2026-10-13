/**
 * Documentation view: the language subset, the diagnostic catalogue, the grammar
 * of the analysed language and the project documents.  Everything here is loaded
 * from the API or linked from the repository, so the documentation cannot drift
 * away from the implementation without the drift being visible.
 */
import { el, render } from '../lib/dom.js';

const DOCUMENTS = [
  ['README.md', 'project overview, quick start, repository layout'],
  ['docs/TECHNICAL_DESIGN.md', 'architecture, module responsibilities, data flow through the engine'],
  ['docs/COMPILER_THEORY.md', 'every compiler concept used, with equations, worked examples and test pointers'],
  ['docs/ALGORITHMS.md', 'pseudocode and complexity of each algorithm'],
  ['docs/LANGUAGE.md', 'the CT-C subset: grammar, types, statements, unsupported constructs'],
  ['docs/RULE_LANGUAGE.md', 'the declarative rule language and its grammar'],
  ['docs/API.md', 'HTTP endpoints, request and response schemas, limits'],
  ['docs/EVALUATION.md', 'how the labelled corpus was built and what the measured numbers mean'],
  ['docs/LIMITATIONS.md', 'what the tool does not do, and the threat model of the tool itself'],
  ['docs/USER_GUIDE.md', 'running the app, using the interface, reading findings'],
  ['docs/PRESENTATION.md', 'presentation outline and viva questions'],
];

export function renderDocs(container, { language, grammar }) {
  const sections = [];

  sections.push(el('div', { class: 'panel' }, [
    el('h2', { text: 'Documents in this repository' }),
    el('ul', {}, DOCUMENTS.map(([path, description]) =>
      el('li', {}, [el('span', { class: 'mono', text: path }), ` — ${description}`]))),
    el('p', { class: 'hint', text: 'The files are part of the repository; this list is the map, not a copy.' }),
  ]));

  if (language) {
    sections.push(el('div', { class: 'panel' }, [
      el('h2', { text: `Language subset (${language.mode})` }),
      el('h3', { text: 'Supported' }),
      el('dl', { class: 'kv' }, Object.entries(language.supported).map(([key, values]) =>
        [el('dt', { text: key }), el('dd', { text: (Array.isArray(values) ? values : [values]).join(', ') })])),
      el('h3', { text: 'Outside the subset (every one of these produces a diagnostic)' }),
      el('table', { class: 'data' }, [
        el('thead', {}, el('tr', {}, ['construct', 'why it is not analysed'].map((h) => el('th', { text: h })))),
        el('tbody', {}, Object.entries(language.unsupported).map(([keyword, reason]) =>
          el('tr', {}, [el('td', { class: 'mono', text: keyword }), el('td', { text: reason })]))),
      ]),
      el('h3', { text: 'Diagnostics' }),
      el('table', { class: 'data' }, [
        el('thead', {}, el('tr', {}, ['code', 'phase', 'meaning'].map((h) => el('th', { text: h })))),
        el('tbody', {}, language.diagnostics.map((entry) =>
          el('tr', {}, [el('td', { class: 'mono', text: entry.code }), el('td', { text: entry.phase }), el('td', { text: entry.meaning })]))),
      ]),
    ]));
  }

  if (grammar) {
    const automaton = grammar.automaton || {};
    sections.push(el('div', { class: 'panel' }, [
      el('h2', { text: `Grammar of the analysed language (${grammar.mode})` }),
      el('dl', { class: 'kv' }, [
        el('dt', { text: 'start symbol' }), el('dd', { class: 'mono', text: grammar.start_symbol }),
        el('dt', { text: 'productions' }), el('dd', { text: String(grammar.productions.length) }),
        el('dt', { text: 'terminals / non-terminals' }), el('dd', { text: `${grammar.terminals.length} / ${grammar.nonterminals.length}` }),
        el('dt', { text: 'nullable symbols' }), el('dd', { class: 'mono', text: grammar.nullable.join(', ') || 'none' }),
        el('dt', { text: 'LR(1) states before merging' }), el('dd', { text: String(automaton.lr1_states_before_merge ?? '—') }),
        el('dt', { text: 'states in this mode' }), el('dd', { text: `${automaton.states} (${automaton.transitions} transitions)` }),
        el('dt', { text: 'conflicts' }), el('dd', { text: grammar.table.conflicts.length ? `${grammar.table.conflicts.length} conflict(s)` : 'none — the grammar is conflict-free in this mode' }),
      ]),
      el('details', {}, [
        el('summary', { text: 'FIRST and FOLLOW sets' }),
        el('pre', { class: 'mono', text: Object.entries(grammar.first).map(([symbol, values]) => `FIRST(${symbol}) = { ${values.join(', ')} }`).join('\n') }),
        el('pre', { class: 'mono', text: Object.entries(grammar.follow).map(([symbol, values]) => `FOLLOW(${symbol}) = { ${values.join(', ')} }`).join('\n') }),
      ]),
      el('details', {}, [
        el('summary', { text: 'Productions' }),
        el('pre', { class: 'mono', text: grammar.productions.map((production) => `${production.index}: ${production.text || `${production.lhs} → ${(production.rhs || []).join(' ')}`}`).join('\n') }),
      ]),
    ]));
  }

  // The head of the section (its heading and the `#docs-body` mount point) is
  // part of `index.html` and must survive rendering; only the body is replaced.
  render(container.querySelector('#docs-body'), sections);
  return container;
}
