/**
 * Findings: the list, the filters and the evidence for one finding.
 *
 * Filtering and sorting happen here on the findings the engine returned; no
 * property of a finding is recomputed in the browser.  Selecting a finding
 * fetches its full record (with the evidence path) and renders:
 * source → sink locations, the ordered path, branch conditions, sanitizers that
 * were seen, per-finding limitations and the remediation hint.
 */
import { el, render } from '../lib/dom.js';
import { api } from '../api.js';
import { filterFindings, sortFindings, facet } from '../lib/filter.js';
import { renderSource, severityByLine } from '../source.js';

function select(label, options, value, onChange, allLabel) {
  return el('label', { class: 'field' }, [
    el('span', { text: label }),
    el('select', {
      on: { change: (event) => onChange(event.target.value) },
    }, [
      el('option', { value: '', text: allLabel, selected: value === '' }),
      ...options.map((option) => el('option', { value: option, text: option, selected: option === value })),
    ]),
  ]);
}

function sortSelect(current, onSort) {
  const options = ['severity', 'line', 'rule', 'category', 'certainty'];
  return el('label', { class: 'field' }, [
    el('span', { text: 'Sort by' }),
    el('select', {
      on: { change: (event) => onSort(event.target.value) },
    }, options.map((option) => el('option', { value: option, text: option, selected: option === current }))),
  ]);
}

export function renderToolbar(container, { state, onFilter, onSort, findings }) {
  const filters = state.filters;
  render(container, el('div', { class: 'row row--wrap' }, [
    select('Severity', ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'], filters.severity, (value) => onFilter({ severity: value }), 'all severities'),
    select('Category', facet(findings, (f) => f.category), filters.category, (value) => onFilter({ category: value }), 'all categories'),
    select('Rule', facet(findings, (f) => f.rule_id), filters.rule, (value) => onFilter({ rule: value }), 'all rules'),
    select('Certainty', ['confirmed', 'approximate', 'unproven'], filters.certainty, (value) => onFilter({ certainty: value }), 'any certainty'),
    select('Function', facet(findings, (f) => f.sink && f.sink.enclosing_function), filters.file, (value) => onFilter({ file: value }), 'all functions'),
    // The status filter only means something once two runs have been compared:
    // "fixed" is a finding the comparison says no longer exists.
    state.comparison
      ? select('Status', ['open', 'fixed'], filters.status, (value) => onFilter({ status: value }), 'all statuses')
      : el('span', {
          class: 'hint',
          text: 'Compare two runs on the Reports page to filter findings by fixed/open.',
        }),
    sortSelect(state.sort || 'severity', onSort),
    el('label', { class: 'field' }, [
      el('span', { text: 'Search' }),
      el('input', {
        type: 'search',
        value: filters.search,
        placeholder: 'rule, function, text…',
        on: { input: (event) => onFilter({ search: event.target.value }) },
      }),
    ]),
  ]));
}

function findingCard(finding, selected, onSelect) {
  // aria-selected is not allowed on a plain <li> (axe: aria-allowed-attr);
  // aria-current marks the selected item and is valid on any element.
  return el('li', { class: 'finding-card', 'aria-current': selected ? 'true' : null }, [
    el('button', {
      type: 'button',
      class: 'finding-card__select',
      on: { click: () => onSelect(finding.id) },
    }, [
      el('div', { class: 'row row--wrap' }, [
        el('span', { class: `badge badge--${finding.severity}`, text: finding.severity }),
        el('span', { class: 'badge badge--muted', text: finding.category }),
        el('span', { class: 'badge badge--muted', text: finding.certainty }),
        el('span', { class: 'spacer' }),
        el('span', { class: 'mono hint', text: finding.id }),
      ]),
      el('div', { text: `${finding.sink.function}() at line ${finding.sink.line}:${finding.sink.col}` }),
      el('div', { class: 'mono hint', text: finding.sink.statement_text || '(statement text unavailable)' }),
      el('div', { class: 'hint', text: `source: ${finding.source.rule} (${finding.source.function}) from line ${finding.source.line}` }),
    ]),
  ]);
}

function pathView(finding, { loading = false } = {}) {
  if (!finding.path || !finding.path.length) {
    // The list payload does not carry the path; it arrives with the full record.
    // Saying "no path was recorded" while that request is still in flight would
    // be a false statement about the analysis, so the two cases are distinct.
    return loading
      ? el('p', { class: 'empty-state' }, [el('span', { class: 'spinner' }), ' loading the evidence path…'])
      : el('p', { class: 'empty-state', text: 'No path was recorded for this finding.' });
  }
  return el('ol', { class: 'evidence-path' }, finding.path.map((step) =>
    el('li', {}, [
      el('div', { text: step.label }),
      el('span', { class: 'evidence-path__kind', text: `${step.kind} · line ${step.line}:${step.col}${step.function ? ` · ${step.function}()` : ''}` }),
      step.detail ? el('div', { class: 'hint', text: step.detail }) : null,
    ]),
  ));
}

export function renderFindingDetail(container, { finding, detail, source, draftSource, earlierRun, onShowSlice, onSelectStatement }) {
  if (!finding) {
    render(container, el('p', { class: 'empty-state', text: 'Select a finding to see its evidence, the data-flow path and the remediation hint.' }));
    return;
  }
  const record = detail || finding;
  const fromEarlierRun = Boolean(earlierRun);
  // The line numbers in `record` belong to the analysed text.  If the editor has
  // moved on, say so instead of printing the finding's lines next to other code.
  // A finding of the *earlier* run in a comparison belongs to a source this
  // page does not have at all.
  const sourceNote = fromEarlierRun
    ? el('p', {
        class: 'alert alert--info',
        text: `This finding was reported by the earlier run ${earlierRun} and is absent from the run on screen; its line numbers refer to that run's source, which is not displayed here.`,
      })
    : (draftSource !== undefined && draftSource !== source
        ? el('p', { class: 'hint', text: 'The editor has changed since this run: the context below is the text that was analysed, and the line numbers refer to it.' })
        : null);
  // The run summary lists findings without their evidence path, while the
  // findings list and the detail endpoint include it; the placeholder is only
  // shown when neither has produced a path yet.
  const pathLines = (record.path || []).map((step) => step.line).filter((line) => line > 0);
  const pathLoading = !detail && !(finding && (finding.path || []).length);
  render(container, [
    el('h2', { text: `${record.severity} ${record.category}` }),
    el('dl', { class: 'kv' }, [
      el('dt', { text: 'finding id' }), el('dd', { class: 'mono', text: record.id }),
      el('dt', { text: 'flow rule' }), el('dd', { text: record.flow_id }),
      el('dt', { text: 'confidence / certainty' }), el('dd', { text: `${record.confidence} / ${record.certainty}` }),
      el('dt', { text: 'reasoning' }), el('dd', { text: record.interprocedural ? 'interprocedural (a function boundary was crossed)' : 'intraprocedural' }),
      el('dt', { text: 'path feasibility' }), el('dd', { text: `${record.feasibility || 'unconditional'} — ${record.feasibility_note || ''}` }),
      el('dt', { text: 'sink' }), el('dd', { text: `${record.sink.function}() line ${record.sink.line}:${record.sink.col} in ${record.sink.enclosing_function}()` }),
      el('dt', { text: 'source' }), el('dd', { text: `${record.source.rule} (${record.source.function}) line ${record.source.line}` }),
    ]),
    el('h3', { text: 'Why this was reported' }),
    el('p', { text: record.explanation }),
    el('h3', { text: 'Evidence path' }),
    pathView(record, { loading: pathLoading }),
    (record.branch_conditions || []).length
      ? el('div', {}, [
          el('h3', { text: 'Branch conditions on this path' }),
          el('table', { class: 'data' }, [
            el('thead', {}, el('tr', {}, ['condition', 'line', 'kind', 'feasibility'].map((h) => el('th', { text: h })))),
            el('tbody', {}, record.branch_conditions.map((condition) =>
              el('tr', {}, [
                el('td', { class: 'mono', text: condition.condition }),
                el('td', { class: 'mono', text: String(condition.line) }),
                el('td', { text: condition.kind }),
                el('td', { text: condition.feasibility }),
              ]))),
          ]),
          el('p', { class: 'hint', text: 'Conditions are recorded from the control-flow graph; they are not proved or refuted at run time.' }),
        ])
      : null,
    (record.sanitizers_seen || []).length
      ? el('div', {}, [
          el('h3', { text: 'Sanitizers seen on this path' }),
          el('ul', {}, record.sanitizers_seen.map((sanitizer) =>
            el('li', { text: `${sanitizer.rule} (context ${sanitizer.context}) at line ${sanitizer.line} — ${sanitizer.detail || 'it did not remove the taint that reached this sink'}` }))),
        ])
      : null,
    el('h3', { text: 'Limitations of this finding' }),
    el('ul', {}, (record.limitations || []).map((item) => el('li', { text: item }))),
    el('h3', { text: 'Remediation' }),
    el('p', { text: record.remediation }),
    el('h3', { text: 'Source context' }),
    sourceNote,
    // Read-only here: a line number is not a statement id, so clicking a line
    // cannot select the statement behind it, and this page has no statement
    // panel to show it in.  (The handler once treated the line number as a
    // statement id and fetched the wrong statement, invisibly.)
    fromEarlierRun ? null : renderSource(source, {
      highlightLines: pathLines,
      selectedLine: record.sink.line,
      severityByLine: severityByLine([record]),
      maxLines: 2000,
    }),
    fromEarlierRun
      ? el('p', {
          class: 'hint',
          text: 'The Program Graph and slicing views show the run on screen, so they are not offered for a finding of the earlier run.',
        })
      : el('div', { class: 'row' }, [
          el('button', {
            type: 'button',
            class: 'button',
            text: 'Show in Program Graph',
            on: { click: () => onShowSlice('graph', record) },
          }),
          el('button', {
            type: 'button',
            class: 'button',
            text: 'Security slice of this finding',
            on: { click: () => onShowSlice('slice', record) },
          }),
        ]),
    el('details', {}, [
      el('summary', { text: 'Evidence record (what justified each hop)' }),
      el('pre', { class: 'mono', text: JSON.stringify(record.evidence, null, 2) }),
    ]),
  ]);
}

export async function renderFindings(container, { state, onFilter, onSort, onSelect, onShowSlice, onSelectStatement }) {
  const toolbar = container.querySelector('#findings-toolbar');
  const listNode = container.querySelector('#findings-list');
  const detailNode = container.querySelector('#finding-detail');
  const run = state.run;

  if (!run) {
    render(toolbar, []);
    toolbar.dataset.controlsKey = '';
    render(listNode, el('p', { class: 'empty-state', text: 'No analysis has run yet. Use “Analyze Code” first.' }));
    render(detailNode, []);
    return;
  }

  const resolvedIds = new Set(
    (state.comparison && (state.comparison.resolved_ids
      || (state.comparison.resolved || []).map((finding) => finding.id))) || [],
  );
  // "Fixed" means "reported by the earlier run, absent from the later one".
  // When the run on screen *is* the later run, none of its findings can be
  // fixed and filtering them by that status was always empty -- a dead
  // filter.  The comparison payload carries the resolved findings as full
  // records, so the fixed view lists those instead.
  const comparison = state.comparison;
  const fixedFromEarlierRun = Boolean(
    comparison
    && state.filters.status === 'fixed'
    && comparison.after && comparison.after.run_id === run.run_id
    && Array.isArray(comparison.resolved),
  );
  const listSource = fixedFromEarlierRun ? comparison.resolved : run.findings;
  const filtered = sortFindings(filterFindings(listSource, state.filters, { resolvedIds }), state.sort);
  // The count line is cheap to repaint, but the controls are not: rebuilding
  // them on every keystroke in the search box would destroy the focused input
  // and drop each second character.  The controls only depend on the run, on
  // whether a comparison exists and on which list is shown (the current run's
  // findings or the earlier run's resolved ones), so they are rebuilt only
  // when those change and the count line is repainted every time.
  const controlsKey = `${run.run_id}|${state.comparison ? 'compared' : 'single'}|${fixedFromEarlierRun ? 'fixed' : 'normal'}`;
  let count = toolbar.querySelector('.findings-count');
  if (!count) {
    render(toolbar, []);
    count = el('div', { class: 'row row--between findings-count' });
    toolbar.appendChild(count);
  }
  render(count, [
    el('strong', {
      text: fixedFromEarlierRun
        ? `${filtered.length} of ${listSource.length} resolved finding(s) from the earlier run ${comparison.before.run_id}`
        : `${filtered.length} of ${run.findings.length} finding(s)`,
    }),
    el('span', { class: 'hint', text: 'Findings are ordered and filtered here; the analysis itself is not recomputed.' }),
  ]);
  if (toolbar.dataset.controlsKey !== controlsKey) {
    const previous = toolbar.querySelector('.findings-controls');
    if (previous) toolbar.removeChild(previous);
    const controls = el('div', { class: 'findings-controls' });
    renderToolbar(controls, { state, onFilter, onSort, findings: listSource });
    toolbar.appendChild(controls);
    toolbar.dataset.controlsKey = controlsKey;
  }

  if (fixedFromEarlierRun && !listSource.length) {
    render(listNode, el('p', {
      class: 'empty-state',
      text: 'The comparison resolved no finding: everything the earlier run reported is still reported now.',
    }));
  } else if (!listSource.length) {
    render(listNode, el('p', {
      class: 'alert alert--info',
      text: run.summary.analysis_complete === false
        ? 'No findings, but the analysis was partial: see the diagnostics on the Analyze Code page before drawing conclusions.'
        : 'No findings for this file. That means no configured source-to-sink flow was detected — not that the program is safe. The Analyze Code page lists every sink call that was inspected and not reported, with the reason for each.',
    }));
  } else if (!filtered.length) {
    render(listNode, el('p', { class: 'empty-state', text: 'No finding matches the current filters.' }));
  } else {
    render(listNode, el('ul', { class: 'findings-list', role: 'list' },
      filtered.map((finding) => findingCard(finding, finding.id === state.selectedFinding, onSelect))));
  }

  const selectedFinding = filtered.find((f) => f.id === state.selectedFinding) || null;
  // A resolved finding belongs to the earlier run: its line numbers refer to
  // that run's source, which this page does not have, and the graph/slice
  // views show the current run -- so both are withheld with an explanation
  // rather than silently displaying another run's artefacts.
  const selectedFromEarlierRun = Boolean(
    selectedFinding && !(run.findings || []).some((f) => f.id === selectedFinding.id),
  );
  renderFindingDetail(detailNode, {
    finding: selectedFinding,
    detail: state.selectedFindingDetail,
    // The analysed text, not the live draft: the finding's line numbers belong
    // to it, and rendering them beside a newer draft misattributed the result.
    source: selectedFromEarlierRun ? '' : (state.analysedSource || state.source),
    draftSource: state.source,
    earlierRun: selectedFromEarlierRun && comparison && comparison.before
      ? comparison.before.run_id
      : null,
    onShowSlice,
    onSelectStatement,
  });
  return container;
}

/** Fetch and store the full record of one finding. */
export async function loadFindingDetail(runId, findingId) {
  return api.finding(runId, findingId);
}
