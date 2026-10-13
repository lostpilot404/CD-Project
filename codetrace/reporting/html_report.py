"""Human-readable HTML report.

The report is a single self-contained file: no scripts, no external resources,
no network access.  The analysed source text is **escaped** before it is
embedded (``&``, ``<``, ``>``, ``"``, ``'``), because the analysed program is
untrusted input: emitting it verbatim would turn the report viewer into an
HTML/JavaScript injection sink.
"""

from __future__ import annotations

import html
from typing import Dict, List, Optional, Sequence

from ..analysis.pipeline import Program
from .json_report import STANDING_LIMITATIONS, build_report

STYLE = """
:root { --fg:#1b1f23; --muted:#57606a; --border:#d0d7de; --bg:#ffffff; --code:#f6f8fa;
        --crit:#a40e26; --high:#bc4c00; --med:#9a6700; --low:#0969da; --ok:#1a7f37; }
* { box-sizing: border-box; }
body { margin:0; padding:32px; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       color:var(--fg); background:var(--bg); line-height:1.5; }
h1 { font-size:22px; margin:0 0 4px; }
h2 { font-size:16px; margin:28px 0 8px; border-bottom:1px solid var(--border); padding-bottom:4px; }
h3 { font-size:14px; margin:18px 0 6px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:20px; }
table { border-collapse:collapse; width:100%; font-size:13px; margin:8px 0 16px; }
th,td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--border); vertical-align:top; }
th { color:var(--muted); font-weight:600; }
code, pre { font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace; font-size:12.5px; }
pre { background:var(--code); border:1px solid var(--border); border-radius:6px; padding:12px; overflow-x:auto; }
.kv { display:grid; grid-template-columns:220px 1fr; gap:2px 16px; font-size:13px; }
.kv div:nth-child(odd) { color:var(--muted); }
.badge { display:inline-block; padding:1px 7px; border-radius:10px; font-size:11px; font-weight:600;
         border:1px solid currentColor; }
.sev-CRITICAL { color:var(--crit); } .sev-HIGH { color:var(--high); }
.sev-MEDIUM { color:var(--med); } .sev-LOW { color:var(--low); } .sev-INFO { color:var(--muted); }
.finding { border:1px solid var(--border); border-radius:6px; padding:14px; margin:12px 0; }
.finding h3 { margin-top:0; }
.path { font-size:12.5px; }
.path li { margin-bottom:3px; }
.limits { font-size:13px; color:var(--muted); }
.src { font-size:12px; margin:0; }
.src .ln { color:var(--muted); display:inline-block; width:38px; text-align:right; margin-right:10px;
           user-select:none; }
.src .hit { background:#fff8c5; }
footer { margin-top:32px; color:var(--muted); font-size:12px; }
"""


def _escape(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _source_block(program: Program, highlight_lines: Sequence[int]) -> str:
    lines = program.source.split("\n")
    rows: List[str] = []
    wanted = set(highlight_lines)
    for index, text in enumerate(lines, start=1):
        marker = " hit" if index in wanted else ""
        rows.append(
            f'<span class="ln">{index}</span><span class="{marker.strip()}">{_escape(text)}</span>'
        )
    return "\n".join(rows)


def render_html(
    program: Program, evaluation: Optional[dict] = None, run_id: Optional[str] = None
) -> str:
    report = build_report(program, evaluation, run_id=run_id)
    summary = report["summary"]
    findings = program.findings
    highlight = sorted(
        {
            int(line)
            for finding in findings
            for line in (
                [finding.sink.get("line")]
                + [step.get("line") for step in finding.path]
            )
            if line
        }
    )

    parts: List[str] = []
    parts.append("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>")
    parts.append(f"<title>CodeTrace report — {_escape(program.filename)}</title>")
    parts.append(f"<style>{STYLE}</style></head><body>")

    parts.append("<h1>CodeTrace analysis report</h1>")
    run_id_text = f" · run {_escape(run_id)}" if run_id else ""
    parts.append(
        f"<div class='sub'>{_escape(program.filename)} · generated {_escape(report['run']['timestamp'])}{run_id_text} · "
        f"CodeTrace {_escape(report['tool']['version'])} · rules {_escape(report['run']['rules_version'])} · "
        f"grammar {_escape(report['run']['grammar']['productions'])} productions, "
        f"{_escape(report['run']['grammar']['lalr_states'])} LALR states, "
        f"{_escape(report['run']['grammar']['conflicts'])} conflicts</div>")

    # -- summary ---------------------------------------------------------
    parts.append("<h2>Summary</h2><div class='kv'>")
    for key, value in (
        ("Findings", summary["findings"]),
        ("By severity", summary["by_severity"]),
        ("By category", summary["by_category"]),
        ("By certainty", summary["by_certainty"]),
        ("Errors / warnings", f"{summary['errors']} / {summary['warnings']}"),
        ("Unsupported constructs", summary["unsupported_constructs"]),
        ("Analysis converged", summary["analysis_converged"]),
        ("Parser mode", report["run"]["parser_mode"]),
        ("Language mode", report["language"]["mode"]),
    ):
        parts.append(f"<div>{_escape(key)}</div><div>{_escape(value)}</div>")
    parts.append("</div>")

    # -- findings --------------------------------------------------------
    parts.append(f"<h2>Findings ({len(findings)})</h2>")
    if not findings:
        parts.append(
            "<p>No flow from a configured source to a configured sink was reported for this file. "
            "This is a statement about the analysed subset and the active rule set only.</p>"
        )
    for finding in findings:
        parts.append("<div class='finding'>")
        parts.append(
            f"<h3><span class='badge sev-{_escape(finding.severity)}'>{_escape(finding.severity)}</span> "
            f"{_escape(finding.category)} — <code>{_escape(finding.id)}</code></h3>"
        )
        parts.append("<div class='kv'>")
        for key, value in (
            ("Rule", finding.rule_id),
            ("Sink", f"{finding.sink.get('function')}() at line {finding.sink.get('line')}:{finding.sink.get('col')}"),
            ("Sink statement", finding.sink.get("statement_text")),
            ("Source", f"{finding.source.get('rule')} ({finding.source.get('description')}) at line {finding.source.get('line')}"),
            ("Certainty", f"{finding.certainty} (confidence {finding.confidence}, "
                          f"{'interprocedural' if finding.interprocedural else 'intraprocedural'})"),
            ("Path feasibility", f"{finding.feasibility} — {finding.feasibility_note}"),
        ):
            parts.append(f"<div>{_escape(key)}</div><div>{_escape(value)}</div>")
        parts.append("</div>")
        parts.append(f"<p>{_escape(finding.explanation)}</p>")
        parts.append("<h3>Evidence path</h3><ol class='path'>")
        for step in finding.path:
            parts.append(
                f"<li><code>{_escape(step['kind'])}</code> line {_escape(step['line'])} "
                f"({_escape(step['function'])}): {_escape(step['label'])}"
                + (f" — atoms {_escape(', '.join(step['atoms']))}" if step.get("atoms") else "")
                + "</li>"
            )
        parts.append("</ol>")
        if finding.branch_conditions:
            parts.append("<h3>Conditions on the path</h3><ul class='path'>")
            for condition in finding.branch_conditions:
                parts.append(f"<li>line {_escape(condition['line'])}: {_escape(condition['condition'])}</li>")
            parts.append("</ul>")
        if finding.sanitizers_seen:
            parts.append("<h3>Sanitizers on the path</h3><ul class='path'>")
            for sanitizer in finding.sanitizers_seen:
                parts.append(
                    f"<li>{_escape(sanitizer.get('rule'))} "
                    f"(context {_escape(sanitizer.get('context'))}) at line "
                    f"{_escape(sanitizer.get('line'))}: {_escape(sanitizer.get('detail'))}</li>"
                )
            parts.append("</ul>")
        parts.append(f"<h3>Remediation</h3><p>{_escape(finding.remediation)}</p>")
        parts.append("<h3>Limitations affecting this finding</h3><ul class='limits'>")
        for limitation in finding.limitations:
            parts.append(f"<li>{_escape(limitation)}</li>")
        parts.append("</ul></div>")

    # -- diagnostics -----------------------------------------------------
    parts.append("<h2>Diagnostics</h2>")
    if program.diagnostics:
        parts.append("<table><tr><th>Severity</th><th>Code</th><th>Location</th><th>Message</th></tr>")
        for diagnostic in program.diagnostics[:400]:
            parts.append(
                f"<tr><td>{_escape(diagnostic.severity)}</td><td><code>{_escape(diagnostic.code)}</code></td>"
                f"<td>{_escape(diagnostic.line)}:{_escape(diagnostic.col)}</td>"
                f"<td>{_escape(diagnostic.message)}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append("<p>No diagnostics.</p>")

    # -- source ---------------------------------------------------------
    parts.append("<h2>Analysed source (highlighted lines take part in a finding)</h2>")
    parts.append(f"<pre class='src'>{_source_block(program, highlight)}</pre>")

    # -- metrics ---------------------------------------------------------
    metrics = report["metrics"]
    parts.append("<h2>Measured metrics</h2><div class='kv'>")
    for key in (
        "source_lines",
        "tokens",
        "ast_nodes",
        "statements",
        "functions",
        "symbols",
        "scopes",
        "basic_blocks",
        "cfg_edges",
        "definitions",
        "dependency_nodes",
        "dependency_edges",
        "unreachable_blocks",
        "dataflow_iterations",
        "taint_hits",
        "findings",
    ):
        if key in metrics:
            parts.append(f"<div>{_escape(key)}</div><div>{_escape(metrics[key])}</div>")
    timings = metrics.get("timings", {})
    for key, value in sorted(timings.items()):
        parts.append(f"<div>{_escape(key)}</div><div>{_escape(value)} s</div>")
    parts.append("</div>")

    # -- limitations -----------------------------------------------------
    parts.append("<h2>Analysis limitations</h2><ul class='limits'>")
    for limitation in report["limitations"]:
        parts.append(f"<li>{_escape(limitation)}</li>")
    parts.append("</ul>")

    parts.append(
        "<footer>Generated by CodeTrace. This report describes a static analysis run of the "
        "analysed file with the listed rule set; it is not a proof of exploitability and not a "
        "guarantee that the file is free of vulnerabilities.</footer>"
    )
    parts.append("</body></html>")
    return "".join(parts)


def write_html_report(
    program: Program, path: str, evaluation: Optional[dict] = None,
    run_id: Optional[str] = None,
) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(render_html(program, evaluation, run_id=run_id))
    return path
