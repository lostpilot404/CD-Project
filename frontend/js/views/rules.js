/**
 * Rule Editor.
 *
 * Rules are validated by the engine before they are used; the editor shows the
 * diagnostics with line and column, the active rule set and the grammar of the
 * rule language.  The editor never executes anything: submitting rules is a
 * POST to /api/rules/validate, and only a rule set that validates can be used.
 */
import { el, render } from '../lib/dom.js';
import { api } from '../api.js';
import { update } from '../state.js';

export function renderRules(container, { state, onStatus }) {
  const diagnostics = container.querySelector('#rules-diagnostics');
  const active = container.querySelector('#rules-active');
  const grammar = container.querySelector('#rules-grammar');
  const status = container.querySelector('#rules-status');

  if (state.rulesActive) {
    const ruleSet = state.rulesActive;
    render(active, [
      el('p', { class: 'hint', text: `version ${ruleSet.version} · ${JSON.stringify(ruleSet.stats)}` }),
      el('ul', {}, (ruleSet.rules || []).map((rule) =>
        el('li', {}, [
          el('span', { class: 'badge badge--muted', text: rule.kind }),
          ' ',
          el('span', { class: 'mono', text: rule.id }),
          ` — ${rule.function ? `${rule.function}() ` : ''}${rule.description || ''}`,
        ]))),
    ]);
  }
  if (state.ruleGrammar) {
    render(grammar, [
      el('p', { text: `The rule language is parsed by the same LR(1) machinery as the analysed language: ${state.ruleGrammar.productions} productions, ${state.ruleGrammar.states} states, ${state.ruleGrammar.conflicts} conflicts.` }),
      el('p', { class: 'hint', text: 'A conflict would be reported here rather than hidden; the grammar is documented in docs/RULE_LANGUAGE.md.' }),
    ]);
  }
  if (!state.rulesValidated) {
    render(diagnostics, []);
    return container;
  }
  render(diagnostics, [
    el('h2', { text: 'Validation result' }),
    el('p', { text: state.rulesValidated.valid ? 'The rule set is valid and can be used for an analysis.' : 'The rule set was rejected; it is not used for any analysis.' }),
    state.rulesValidated.diagnostics.length
      ? el('table', { class: 'data' }, [
          el('thead', {}, el('tr', {}, ['severity', 'code', 'line:col', 'message'].map((h) => el('th', { text: h })))),
          el('tbody', {}, state.rulesValidated.diagnostics.map((diagnostic) =>
            el('tr', {}, [
              el('td', {}, el('span', { class: `badge badge--${diagnostic.severity}`, text: diagnostic.severity })),
              el('td', { class: 'mono', text: diagnostic.code }),
              el('td', { class: 'mono', text: `${diagnostic.line}:${diagnostic.col}` }),
              el('td', {}, [diagnostic.message, diagnostic.detail ? el('div', { class: 'hint', text: diagnostic.detail }) : null]),
            ]))),
        ])
      : el('p', { class: 'hint', text: 'No diagnostics.' }),
    el('dl', { class: 'kv' }, [
      el('dt', { text: 'parsed tokens' }), el('dd', { text: String(state.rulesValidated.parse.tokens) }),
      el('dt', { text: 'accepted by the rule parser' }), el('dd', { text: state.rulesValidated.parse.accepted ? 'yes' : 'no' }),
      el('dt', { text: 'rule counts' }), el('dd', { text: JSON.stringify(state.rulesValidated.stats) }),
    ]),
  ]);
  return container;
}

export async function validateRules(text) {
  const result = await api.validateRules(text);
  update({ rulesValidated: result });
  return result;
}
