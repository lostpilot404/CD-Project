/**
 * Reports: export the JSON or HTML report of the current run, inspect the schema
 * and compare two runs (new / resolved / persistent / moved findings).
 */
import { el, render } from '../lib/dom.js';
import { api } from '../api.js';
import { describeComparison } from '../lib/filter.js';

export function renderReports(container, { state, onCompare }) {
  const body = container.querySelector('#reports-body');
  const run = state.run;
  if (!run) {
    render(body, el('p', { class: 'empty-state', text: 'No analysis has run yet. Use “Analyze Code” first.' }));
    return;
  }
  const comparison = state.comparison;

  render(body, [
    el('h2', { text: 'Export' }),
    el('p', { class: 'hint', text: 'The JSON report follows the documented schema (schema_version in the payload); the HTML report is self-contained and escapes all analysed source text.' }),
    el('div', { class: 'row row--wrap' }, [
      el('a', { class: 'button', href: api.reportUrl(run.run_id, 'json'), download: `${run.filename}.codetrace.json`, text: 'Download JSON report' }),
      el('a', { class: 'button', href: api.reportUrl(run.run_id, 'html'), target: '_blank', rel: 'noopener', text: 'Open HTML report' }),
    ]),
    el('h2', { text: 'Run comparison' }),
    el('p', { class: 'hint', text: 'Findings are matched by their stable identity (rule, sink operation, statement text), so inserting lines above a finding does not make it look new.' }),
    el('div', { class: 'row row--wrap' }, [
      el('label', { class: 'field' }, [
        el('span', { text: 'Earlier run id' }),
        el('input', { type: 'text', id: 'compare-before', placeholder: 'run id', value: state.compareBefore || '' }),
      ]),
      el('label', { class: 'field' }, [
        el('span', { text: 'Later run id' }),
        el('input', { type: 'text', id: 'compare-after', placeholder: 'run id', value: state.compareAfter || run.run_id }),
      ]),
      el('button', { type: 'button', class: 'button', id: 'compare-button', text: 'Compare', on: { click: () => onCompare() } }),
    ]),
    comparison
      ? el('div', {}, [
          el('div', { class: 'grid grid--stats' }, describeComparison(comparison).map((entry) =>
            el('div', { class: 'stat' }, [
              el('div', { class: 'stat__value', text: String(entry.value) }),
              el('div', { class: 'stat__label', text: entry.label }),
              el('div', { class: 'stat__hint', text: entry.hint }),
            ]))),
          el('p', { class: 'hint', text: comparison.summary.note || '' }),
        ])
      : null,
  ]);
  return container;
}
