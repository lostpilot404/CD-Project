/**
 * Source viewer.
 *
 * Renders the analysed file line by line with line numbers.  Every character of
 * the file is inserted as text, so source that contains markup is displayed as
 * markup, never interpreted.  Lines can be highlighted (a finding's path) or
 * marked with the severity of the findings that sit on them, which is what makes
 * "read the code next to the finding" work without leaving the page.
 */

import { el, render } from './lib/dom.js';

function splitLines(source) {
  const lines = String(source ?? '').split('\n');
  if (lines.length && lines[lines.length - 1] === '') lines.pop();
  return lines;
}

/**
 * @param {string} source
 * @param {object} options `{highlightLines, selectedLine, severityByLine, onLineClick, maxLines}`
 */
export function renderSource(source, options = {}) {
  const lines = splitLines(source);
  const highlight = new Set(options.highlightLines || []);
  const severityByLine = options.severityByLine || {};
  const maxLines = options.maxLines || 4000;

  if (!lines.length) {
    return el('p', { class: 'empty-state', text: 'No source text is loaded. Run an analysis first.' });
  }
  if (lines.length > maxLines) {
    return el('p', {
      class: 'empty-state',
      text: `The file has ${lines.length} lines; the viewer shows at most ${maxLines}. Use the finding list to navigate.`,
    });
  }

  const body = el('ul', { class: 'source__lines' });
  lines.forEach((text, index) => {
    const lineNumber = index + 1;
    const row = el('li', { class: 'source__row' }, [
      el('span', { class: 'source__gutter', text: String(lineNumber) }),
      el('span', { class: 'source__code', text: text === '' ? ' ' : text }),
    ]);
    row.dataset.highlight = highlight.has(lineNumber) ? 'true' : 'false';
    row.dataset.selected = options.selectedLine === lineNumber ? 'true' : 'false';
    const severity = severityByLine[lineNumber];
    if (severity) row.dataset.severity = severity;
    if (options.onLineClick) {
      row.style.cursor = 'pointer';
      row.addEventListener('click', () => options.onLineClick(lineNumber));
    }
    body.appendChild(row);
  });

  // The pane scrolls; without a tab stop a keyboard user cannot reach the
  // content inside it (axe: scrollable-region-focusable).
  return el('div', {
    class: 'source',
    tabindex: '0',
    role: 'group',
    'aria-label': 'Source of the analysed file',
  }, body);
}

/** Map of line number -> highest severity, for the gutter markers. */
export function severityByLine(findings) {
  const order = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1, INFO: 0 };
  const result = {};
  for (const finding of findings || []) {
    const line = Number(finding.sink && finding.sink.line);
    if (!line) continue;
    const current = result[line];
    if (!current || order[finding.severity] > order[current]) result[line] = finding.severity;
  }
  return result;
}

/** Replace a container's content with a fresh source view. */
export function mountSource(container, source, options = {}) {
  return render(container, renderSource(source, options));
}
