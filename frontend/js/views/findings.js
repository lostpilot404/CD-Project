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
    select('Sort by', ['severity', 'line', 'rule', 'category', 'certainty'], state.sort, onSort, 'severity'),
    el('label', { class: 'field' }, [
      el('span', { text: 'Search' }),
      el('input', {
        type: 'search',
        id: 'findings-search',
        value: filters.search,
        placeholder: 'rule, function, text…',
        on: { input: (event) => onFilter({ search: event.target.value }) },
      }),
    ]),
  ]));
}

function findingCard(finding, selected, onSelect) {
  return el('li', { class: 'finding-card', 'aria-selected': String(selected) }, [
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

export function renderFindingDetail(container, { finding, detail, source, onShowSlice, onSelectStatement }) {
  if (!finding) {
    render(container, el('p', { class: 'empty-state', text: 'Select a finding to see its evidence, the data-flow path and the remediation hint.' }));
    return;
  }
  const record = detail || finding;
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
    renderSource(source, {
      highlightLines: pathLines,
      selectedLine: record.sink.line,
      severityByLine: severityByLine([record]),
      onLineClick: onSelectStatement,
      maxLines: 2000,
    }),
    el('div', { class: 'row' }, [
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

  // Typing in the search box filters on every keystroke, and filtering
  // re-renders this toolbar — which replaces the search input itself.  In a
  // browser that drops focus (and the caret) after the first character, so
  // remember them here and restore them once the new toolbar is in place.
  const previousSearch = toolbar.querySelector('#findings-search');
  const searchHadFocus = Boolean(
    previousSearch && typeof document !== 'undefined' && document.activeElement === previousSearch,
  );
  const searchCaret = searchHadFocus && typeof previousSearch.selectionStart === 'number'
    ? previousSearch.selectionStart
    : null;

  if (!run) {
    render(toolbar, []);
    render(listNode, el('p', { class: 'empty-state', text: 'No analysis has run yet. Use “Analyze Code” first.' }));
    render(detailNode, []);
    return;
  }

  const resolvedIds = new Set(
    (state.comparison && (state.comparison.resolved_ids
      || (state.comparison.resolved || []).map((finding) => finding.id))) || [],
  );
  const filtered = sortFindings(filterFindings(run.findings, state.filters, { resolvedIds }), state.sort);
  render(toolbar, [
    el('div', { class: 'row row--between' }, [
      el('strong', { text: `${filtered.length} of ${run.findings.length} finding(s)` }),
      el('span', { class: 'hint', text: 'Findings are ordered and filtered here; the analysis itself is not recomputed.' }),
    ]),
  ]);
  const controls = el('div');
  renderToolbar(controls, { state, onFilter, onSort, findings: run.findings });
  toolbar.appendChild(controls);

  if (!run.findings.length) {
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

  renderFindingDetail(detailNode, {
    finding: filtered.find((f) => f.id === state.selectedFinding) || null,
    detail: state.selectedFindingDetail,
    source: state.source,
    onShowSlice,
    onSelectStatement,
  });

  if (searchHadFocus) {
    const nextSearch = toolbar.querySelector('#findings-search');
    if (nextSearch && typeof nextSearch.focus === 'function') {
      nextSearch.focus();
      if (searchCaret !== null && typeof nextSearch.setSelectionRange === 'function') {
        try { nextSearch.setSelectionRange(searchCaret, searchCaret); } catch (error) { /* caret is best-effort */ }
      }
    }
  }
  return container;
}

/** Fetch and store the full record of one finding. */
export async function loadFindingDetail(runId, findingId) {
  return api.finding(runId, findingId);
}
