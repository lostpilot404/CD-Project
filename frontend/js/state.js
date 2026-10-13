/**
 * Application state.
 *
 * One store holds the current run and the current selection.  Views subscribe
 * to it; nothing else keeps analysis results, so switching views never
 * re-runs or re-derives analysis -- it reads what the engine already computed.
 */

const listeners = new Set();

export const state = {
  /** Last engine metadata from /api/health. */
  health: null,
  /** Full response of the last /api/analyze call. */
  run: null,
  /** Source text of the analysed file (kept for the source viewer). */
  source: '',
  /** Currently selected finding id. */
  selectedFinding: null,
  /** Full finding object (with path) when fetched. */
  selectedFindingDetail: null,
  /** Currently selected statement id. */
  selectedStatement: null,
  /** Findings filters in the toolbar. */
  filters: { severity: '', category: '', rule: '', certainty: '', file: '', status: '', search: '' },
  /** Sort key for the finding list. */
  sort: 'severity',
  /** Graph view selection; `data` holds the graph the engine returned. */
  graph: { mode: 'dependency', kinds: ['data', 'control', 'call', 'return', 'taint', 'define', 'sanitize'], data: null },
  /** Data-flow view selection; `data` holds the solution the engine returned. */
  dataflow: { function: null, analysis: 'reaching', data: null },
  /** Slicing selection; `data` holds the slice the engine returned. */
  slicing: { sid: null, direction: 'backward', source: 'statement', data: null },
  /** Result of the last run comparison, if any. */
  comparison: null,
};

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Merge a patch into the state and notify subscribers. */
export function update(patch) {
  Object.assign(state, patch);
  for (const listener of [...listeners]) listener(state);
}

export function resetRun() {
  update({
    run: null,
    source: '',
    selectedFinding: null,
    selectedFindingDetail: null,
    selectedStatement: null,
    comparison: null,
    filters: { severity: '', category: '', rule: '', certainty: '', file: '', status: '', search: '' },
    dataflow: { function: null, analysis: 'reaching' },
    slicing: { sid: null, direction: 'backward', source: 'statement' },
  });
}
