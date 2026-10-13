"""Analysis report: the documented, stable JSON structure CodeTrace exports.

The report is the *complete* record of one analysis run: what was analysed,
with which rule set and engine version, what was found, the evidence for each
finding, everything that could not be analysed, and the measured performance.

Schema version
--------------
``schema_version`` is bumped whenever the structure changes incompatibly.  The
documented schema lives in ``docs/REPORT_SCHEMA.md``; the top-level keys are:

``schema_version``, ``tool``, ``run``, ``input``, ``language``, ``summary``,
``findings``, ``diagnostics``, ``unsupported``, ``analysis``, ``metrics``,
``evaluation``, ``limitations``
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..version import LANGUAGE_MODE
from ..analysis.pipeline import ENGINE_VERSION, Program

from ..version import SCHEMA_VERSION  # noqa: F401  (re-exported)

SUPPORTED_LANGUAGE_MODE = LANGUAGE_MODE + " (see docs/LANGUAGE.md)"

#: Statements about what the analysis does *not* guarantee, included verbatim
#: in every report so that a reader of the report cannot mistake it for a
#: proof of exploitability.
STANDING_LIMITATIONS: List[str] = [
    "Static analysis only: the analysed program is never executed. A reported flow means the "
    "analysis could not exclude it, not that it is exploitable.",
    "The supported language subset is documented in docs/LANGUAGE.md; constructs outside it are "
    "reported as unsupported and are not analysed.",
    "Interprocedural reasoning is context-insensitive: a parameter tainted at one call site is "
    "summarised as tainted for every call site.",
    "Pointers, aliasing, dynamic memory, structs, and the preprocessor are outside the supported "
    "subset and are never assumed safe.",
    "Array elements are not tracked individually; taint assigned to one element is attributed to "
    "the whole array.",
    "Sanitizers are only trusted where a rule declares them, and only for the declared context; "
    "unknown functions are never assumed to validate their arguments.",
    "Reports contain the results of the run they were produced from; re-running after editing the "
    "source or the rules produces a new, independent report.",
]


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_report(
    program: Program, evaluation: Optional[dict] = None, run_id: Optional[str] = None
) -> dict:
    """Build the report dictionary for a completed analysis run.

    ``run_id`` is the in-memory identifier the API assigned to the run; it is
    recorded so a saved report can be traced back to the run it describes, and is
    ``None`` for a report produced outside the server.
    """
    metrics = dict(program.metrics)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {
            "name": "CodeTrace",
            "version": ENGINE_VERSION,
            "description": "compiler-driven program dependency and vulnerability analysis",
        },
        "run": {
            "run_id": run_id,
            "timestamp": _timestamp(),
            "engine_version": ENGINE_VERSION,
            "rules_version": program.rules.version_label(),
            "rule_set": program.rules.stats(),
            "parser_mode": metrics.get("parser_mode"),
            "grammar": {
                "productions": metrics.get("grammar_productions"),
                "lalr_states": metrics.get("grammar_states"),
                "conflicts": metrics.get("grammar_conflicts"),
            },
        },
        "input": {
            "filename": program.filename,
            "lines": metrics.get("source_lines"),
            "bytes": metrics.get("source_bytes"),
            "sha256": _source_hash(program.source),
        },
        "language": {
            "mode": SUPPORTED_LANGUAGE_MODE,
            "dialect": "C-like subset parsed by a canonical LR(1) / LALR(1) parser",
        },
        "summary": {
            "findings": len(program.findings),
            "by_severity": _count(program.findings, lambda f: f.severity),
            "by_category": _count(program.findings, lambda f: f.category),
            "by_certainty": _count(program.findings, lambda f: f.certainty),
            "dispositions": dispositions(program),
            "errors": len([d for d in program.diagnostics if d.severity == "error"]),
            "warnings": len([d for d in program.diagnostics if d.severity == "warning"]),
            "unsupported_constructs": len(set(program.semantic.unsupported_offsets)),
            "analysis_complete": program.analysis_complete,
            "partial_reasons": list(program.partial_reasons),
            "analysis_converged": program.taint.converged,
        },
        "findings": [finding.to_json() for finding in program.findings],
        "diagnostics": [diagnostic.to_json() for diagnostic in program.diagnostics],
        "unsupported": {
            "offsets": sorted(set(program.semantic.unsupported_offsets)),
            "features": sorted(
                {
                    d.message
                    for d in program.diagnostics
                    if d.unsupported
                }
            ),
        },
        "unknown_values": program.semantic.unknowns[:200],
        "analysis": {
            "order": [
                "lexer",
                "canonical LR(1) parser (LALR(1) tables by default)",
                "abstract syntax tree",
                "semantic analysis and symbol tables",
                "control-flow graph",
                "reaching definitions",
                "liveness",
                "definite assignment",
                "taint propagation (sources, sinks, sanitizers, function summaries)",
                "program dependency graph",
                "program slicing",
                "finding generation",
            ],
            "functions": [
                {
                    **analysis.cfg.stats(),
                    "reaching_definitions_iterations": analysis.reaching_result.iterations,
                    "reaching_definitions_converged": analysis.reaching_result.converged,
                    "liveness_iterations": analysis.live_result.iterations,
                    "liveness_converged": analysis.live_result.converged,
                    "definite_assignment_converged": analysis.definite_result.converged,
                }
                for analysis in program.analyses.values()
            ],
            "taint": program.taint.to_json(),
            "dependency_graph": program.dependencies.stats() if program.dependencies else {},
        },
        "metrics": metrics,
        "evaluation": evaluation or {
            "available": False,
            "note": "no labelled expectation was supplied for this run",
        },
        "limitations": list(STANDING_LIMITATIONS) + list(program.limits_hit) + list(program.partial_reasons),
    }


def _source_hash(source: str) -> str:
    import hashlib

    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _count(findings, key) -> dict:
    counts: Dict[str, int] = {}
    for finding in findings:
        value = key(finding)
        counts[value] = counts.get(value, 0) + 1
    return counts


def dispositions(program: Program) -> dict:
    """Which source/sink candidates were *not* reported, and why.

    This is the honest counterpart of the findings list: it shows what the
    engine saw but deliberately did not report.
    """
    sink_calls = []
    for call in program.semantic.calls:
        rules = program.rules.sink_rules(call.name)
        if rules:
            sink_calls.append(call)
    reported_sids = {finding.sink.get("sid") for finding in program.findings}
    unreported = []
    pruned = {
        (entry["function"], entry["to"]) for entry in getattr(program.taint, "infeasible_edges", [])
    }
    for call in sink_calls:
        if call.sid in reported_sids:
            continue
        if any(call.line == finding.sink.get("line") for finding in program.findings):
            continue
        block = program.block_of_statement(call.sid, call.function)
        if block is not None and (call.function, block) in pruned:
            reason = (
                "the statement sits in a branch whose condition is a literal constant, so the "
                "branch cannot execute and the statement was not analysed as reachable"
            )
        else:
            reason = (
                "no taint of the required context reached this sink argument, or no enabled flow "
                "connects a known source to it"
            )
            if block is not None and any(
                entry["function"] == call.function for entry in getattr(program.taint, "infeasible_edges", [])
            ):
                reason += (
                    "; note that a branch in this function was statically pruned because its "
                    "condition is a literal constant, which can also explain a missing flow"
                )
        unreported.append(
            {
                "function": call.function,
                "sink_rule": next((r.id for r in program.rules.sink_rules(call.name)), None),
                "line": call.line,
                "col": call.col,
                    "reason": reason,
                }
            )
    return {
        "sink_calls_seen": len(sink_calls),
        "reported": len(program.findings),
        "unreported_sink_calls": unreported[:50],
        "unreported_count": len(unreported),
        "statically_pruned_branches": list(program.taint.infeasible_edges),
        "note": (
            "A sink call appears here when no enabled flow connects a configured source to it, "
            "when the required taint context was removed by a declared sanitizer, or when the "
            "statement sits in a branch whose literal condition makes it unreachable."
        ),
    }


def to_json_text(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=False, ensure_ascii=False)


def write_json_report(program: Program, path: str, evaluation: Optional[dict] = None) -> str:
    report = build_report(program, evaluation)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(to_json_text(report))
    return path
