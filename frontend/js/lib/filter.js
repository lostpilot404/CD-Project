/**
 * Filtering, searching and sorting of findings.
 *
 * These functions are pure: they take the finding objects the API returns and
 * return new arrays.  Keeping them out of the views makes them testable without
 * a browser (see frontend/tests/) and keeps the taint/dependency reasoning in
 * the engine where it belongs -- nothing here recomputes analysis results, it
 * only selects and orders what the engine reported.
 */

export const SEVERITY_ORDER = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3, INFO: 4 };
export const CERTAINTY_ORDER = { confirmed: 0, approximate: 1, unproven: 2 };
export const CONFIDENCE_ORDER = { high: 0, medium: 1, low: 2 };

/** Unique sorted values of one field across the findings. */
export function facet(findings, pick) {
  const values = new Set();
  for (const finding of findings) {
    const value = pick(finding);
    if (value !== null && value !== undefined && value !== '') values.add(String(value));
  }
  return [...values].sort();
}

/** Free-text search across the fields a reviewer would look at. */
export function matchesSearch(finding, needle) {
  if (!needle) return true;
  const haystack = [
    finding.id,
    finding.rule_id,
    finding.category,
    finding.severity,
    finding.certainty,
    finding.sink && finding.sink.function,
    finding.sink && finding.sink.statement_text,
    finding.source && finding.source.rule,
    finding.source && finding.source.function,
    finding.explanation,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return haystack.includes(needle.toLowerCase());
}

/**
 * Apply the toolbar filters.
 *
 * `filters` fields: severity, category, file, rule, certainty, status, search.
 * `status` is `open` / `fixed` / `all` as delivered by a run comparison: a
 * finding is `open` unless the comparison says it was resolved.
 */
export function filterFindings(findings, filters = {}, context = {}) {
  const resolved = context.resolvedIds instanceof Set ? context.resolvedIds : new Set(context.resolvedIds || []);
  return findings.filter((finding) => {
    if (filters.severity && finding.severity !== filters.severity) return false;
    if (filters.category && finding.category !== filters.category) return false;
    if (filters.rule && finding.rule_id !== filters.rule) return false;
    if (filters.certainty && finding.certainty !== filters.certainty) return false;
    if (filters.file && String(finding.sink && finding.sink.enclosing_function) !== filters.file) return false;
    if (filters.status === 'fixed' && !resolved.has(finding.id)) return false;
    if (filters.status === 'open' && resolved.has(finding.id)) return false;
    if (filters.search && !matchesSearch(finding, filters.search)) return false;
    return true;
  });
}

/** Sort findings by severity, then certainty, then line. */
export function sortFindings(findings, key = 'severity') {
  const byLine = (finding) => Number((finding.sink && finding.sink.line) || 0);
  const comparators = {
    severity: (a, b) =>
      (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9) ||
      (CERTAINTY_ORDER[a.certainty] ?? 9) - (CERTAINTY_ORDER[b.certainty] ?? 9) ||
      byLine(a) - byLine(b) ||
      String(a.id).localeCompare(String(b.id)),
    line: (a, b) => byLine(a) - byLine(b) || String(a.id).localeCompare(String(b.id)),
    rule: (a, b) => String(a.rule_id).localeCompare(String(b.rule_id)) || byLine(a) - byLine(b),
    category: (a, b) => String(a.category).localeCompare(String(b.category)) || byLine(a) - byLine(b),
    certainty: (a, b) =>
      (CERTAINTY_ORDER[a.certainty] ?? 9) - (CERTAINTY_ORDER[b.certainty] ?? 9) || byLine(a) - byLine(b),
  };
  const compare = comparators[key] || comparators.severity;
  return [...findings].sort(compare);
}

/** Severity counters used by the summary strip. */
export function countBySeverity(findings) {
  const counts = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0, INFO: 0 };
  for (const finding of findings) {
    counts[finding.severity] = (counts[finding.severity] || 0) + 1;
  }
  return counts;
}

/** Compare two runs by finding identity (never by line number). */
export function describeComparison(diff) {
  if (!diff || !diff.summary) return [];
  const { new: added = 0, resolved = 0, persistent = 0, moved = 0 } = diff.summary;
  return [
    { label: 'new', value: added, hint: 'not reported by the earlier run' },
    { label: 'resolved', value: resolved, hint: 'reported earlier, absent now' },
    { label: 'persistent', value: persistent, hint: 'reported by both runs' },
    { label: 'moved', value: moved, hint: 'same finding identity, different location' },
  ];
}
