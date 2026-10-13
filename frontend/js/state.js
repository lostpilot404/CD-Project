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
  /** Run ids entered on the Reports page for a comparison. */
  compareBefore: '',
  compareAfter: '',
  /** Statement id -> source text of the current run. */
  statementsById: {},
  /** Full record of the currently selected statement, if fetched. */
  statementDetail: null,
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

/**
 * Drop every artefact derived from a run (graph, data-flow solution, slice,
 * statement/finding details, comparison).  Views fetch these lazily only when
 * their slot is empty, so anything left over from a previous run would be
 * shown as if it belonged to the current one: a new analysis — and Clear —
 * must invalidate them all, while keeping the user's view preferences
 * (graph mode/edge kinds, data-flow analysis, slice direction).
 */
export function invalidateRunArtifacts() {
  update({
    selectedFinding: null,
    selectedFindingDetail: null,
    selectedStatement: null,
    statementDetail: null,
    comparison: null,
    compareBefore: '',
    compareAfter: '',
    statementsById: {},
    graph: { ...state.graph, data: null, focus: null },
    dataflow: { function: null, analysis: state.dataflow.analysis, data: null },
    slicing: { sid: null, direction: state.slicing.direction, source: 'statement', data: null },
  });
}

export function resetRun() {
  update({
    run: null,
    source: '',
    filters: { severity: '', category: '', rule: '', certainty: '', file: '', status: '', search: '' },
  });
  invalidateRunArtifacts();
}
