/**
 * Reports: export the JSON or HTML report of the current run, inspect the schema
 * and compare two runs (new / resolved / persistent / moved findings).
 */
import { el, render } from '../lib/dom.js';
import { api } from '../api.js';
import { describeComparison } from '../lib/filter.js';

/**
 * The comparison's per-finding records.
 *
 * The counts above answer "did it get better?"; these lists answer "which
 * findings?".  The API returns the new and resolved findings as full records
 * and the moved/persistent ones with their before/after locations -- showing
 * only the counts discarded exactly the part a reviewer acts on.
 */
function comparisonRecords(comparison) {
  const findingList = (title, entries, emptyText) => el('details', {}, [
    el('summary', { text: `${title} (${entries.length})` }),
    entries.length
      ? el('ul', { class: 'compare-list' }, entries.map((finding) => el('li', {}, [
          el('span', { class: `badge badge--${finding.severity}`, text: finding.severity }),
          ' ',
          el('span', { class: 'mono hint', text: finding.id }),
          ` — ${finding.rule_id}: ${finding.sink.function}() line ${finding.sink.line}:${finding.sink.col}`,
          finding.sink.statement_text
            ? el('div', { class: 'mono hint', text: finding.sink.statement_text })
            : null,
        ])))
      : el('p', { class: 'hint', text: emptyText }),
  ]);
  const moved = comparison.moved || [];
  return el('div', { class: 'compare-records' }, [
    findingList('New findings — only the later run reports them', comparison.new || [],
      'No finding is new.'),
    findingList('Resolved findings — only the earlier run reported them', comparison.resolved || [],
      'Nothing was resolved between the two runs.'),
    el('details', {}, [
      el('summary', { text: `Moved findings — same identity, different location (${moved.length})` }),
      moved.length
        ? el('ul', { class: 'compare-list' }, moved.map((entry) => el('li', {}, [
            el('span', { class: 'mono hint', text: entry.id }),
            ` — line ${entry.before.line}:${entry.before.col} → ${entry.after.line}:${entry.after.col}`,
            entry.before.severity !== entry.after.severity
              ? `, severity ${entry.before.severity} → ${entry.after.severity}`
              : '',
          ])))
        : el('p', { class: 'hint', text: 'No finding changed its location.' }),
    ]),
    el('p', {
      class: 'hint',
      text: `Persistent findings: ${(comparison.persistent || []).length} finding(s) are reported by both runs at the same location.`,
    }),
    el('p', {
      class: 'hint',
      text: 'Set the Findings page status filter to “fixed” to read a resolved finding’s full record.',
    }),
  ]);
}

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
          comparisonRecords(comparison),
        ])
      : null,
  ]);
  return container;
}
