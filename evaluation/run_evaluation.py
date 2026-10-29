#!/usr/bin/env python3
"""Evaluate CodeTrace against the labelled corpus in ``evaluation/expectations.json``.

The corpus is authored by hand: each case states, before the analysis runs, what
the tool is expected to report.  This script runs the real engine over every
case and compares the outcome with those labels.  It measures:

* **finding level** -- true positives (expected and reported), false positives
  (reported but not expected), false negatives (expected but not reported);
* **file level** -- cases whose label is ``safe`` or ``sanitized`` and whose
  report is empty count as true negatives; a finding in such a case is a false
  positive at file level;
* **diagnostics** -- whether the expected diagnostic codes appear, which is how
  unsupported and malformed input is checked; a case may also *forbid* codes of
  any severity (``forbidden_diagnostics``, e.g. a false DFA001 that must never
  appear) and pin the engine's completeness verdict (``analysis_complete``);
* **precision / recall / F1** -- with explicit handling of the zero-denominator
  case (when nothing was predicted or nothing was expected, the metric is
  reported as ``null`` with a note rather than as 0 or 1).

What the numbers mean and do not mean: they describe **this corpus only**.  It
is a small, hand-written corpus built for a compiler-design project, so the
metrics are evidence that the pipeline behaves as intended on documented cases;
they are not an estimate of precision or recall on arbitrary real-world code.

Usage::

    python3 evaluation/run_evaluation.py            # human-readable table
    python3 evaluation/run_evaluation.py --json var/evaluation.json
    python3 evaluation/run_evaluation.py --quiet --json var/evaluation.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from codetrace.analysis.pipeline import ENGINE_VERSION, analyse_source  # noqa: E402
from codetrace.reporting.json_report import SCHEMA_VERSION  # noqa: E402
from codetrace.rules.rule_language import load_builtin_rules, parse_and_validate  # noqa: E402
from codetrace.rules.model import merge  # noqa: E402

EXAMPLES = os.path.join(ROOT, "examples")
EXPECTATIONS = os.path.join(ROOT, "evaluation", "expectations.json")


def normalise(text: str) -> str:
    """Whitespace-insensitive form used to compare sink statements."""
    return " ".join((text or "").split())


def finding_matches(finding, expectation: Dict[str, object]) -> bool:
    """Does a reported finding satisfy one expectation?"""
    if expectation.get("rule") and finding.rule_id != expectation["rule"]:
        return False
    if expectation.get("category") and finding.category != expectation["category"]:
        return False
    if expectation.get("severity") and finding.severity != expectation["severity"]:
        return False
    if expectation.get("certainty") and finding.certainty != expectation["certainty"]:
        return False
    if expectation.get("source_rule") and finding.source.get("rule") != expectation["source_rule"]:
        return False
    if expectation.get("sink_statement"):
        sink_text = normalise(str(finding.sink.get("statement_text", "")))
        if normalise(str(expectation["sink_statement"])) not in sink_text:
            # The sink expression is also acceptable: for `readfile(path)` the
            # statement text is the whole statement, the expression is the
            # argument list, and both identify the same sink.
            return False
    return True


def run_case(case: Dict[str, object]) -> dict:
    path = os.path.join(EXAMPLES, str(case["file"]))
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()

    rules = None
    rule_diagnostics: List[dict] = []
    if case.get("rules"):
        rule_path = os.path.join(EXAMPLES, str(case["rules"]))
        with open(rule_path, "r", encoding="utf-8") as handle:
            custom_text = handle.read()
        custom, custom_diags, _parsed = parse_and_validate(
            custom_text, os.path.basename(rule_path), origin="evaluation corpus"
        )
        errors = [d for d in custom_diags if d.severity == "error"]
        if errors:
            return {
                "file": case["file"],
                "error": "custom rule file failed validation: "
                + "; ".join(f"{d.code} line {d.line}: {d.message}" for d in errors),
            }
        builtin, builtin_diags = load_builtin_rules()
        rules = merge(builtin, custom)
        rule_diagnostics = [d.to_json() for d in builtin_diags + custom_diags]

    started = time.perf_counter()
    program = analyse_source(source, filename=str(case["file"]), rules=rules)
    seconds = time.perf_counter() - started

    expectations = list(case.get("expect") or [])
    matched_expectations: List[int] = []
    matched_findings: Dict[int, int] = {}
    for index, expectation in enumerate(expectations):
        for finding_index, finding in enumerate(program.findings):
            if finding_index in matched_findings:
                continue
            if finding_matches(finding, expectation):
                matched_expectations.append(index)
                matched_findings[finding_index] = index
                break

    diagnostics = [d for d in program.diagnostics]
    codes = sorted({d.code for d in diagnostics})
    expected_codes = list(case.get("expect_diagnostics") or [])
    missing_codes = [code for code in expected_codes if code not in codes]
    unexpected_errors = [
        d.code for d in diagnostics if d.severity == "error" and d.code not in expected_codes
    ]
    # A case may forbid codes of *any* severity: a warning that must never
    # appear (a false DFA001, say) would otherwise pass unnoticed, because
    # only error-severity codes are checked above.
    forbidden_codes = list(case.get("forbidden_diagnostics") or [])
    forbidden_present = sorted({code for code in forbidden_codes if code in codes})
    # And a case may pin the engine's own completeness verdict, so "the run
    # says the analysis was complete" becomes a checked claim, not a hope.
    expected_complete = case.get("analysis_complete")
    complete_mismatch = (
        expected_complete is not None
        and program.analysis_complete != bool(expected_complete)
    )
    min_syntax_errors = int(case.get("min_syntax_errors") or 0)
    syntax_errors = [d for d in diagnostics if d.code.startswith("SYN")]
    if len(syntax_errors) < min_syntax_errors:
        missing_codes.append(f"at least {min_syntax_errors} SYNxxx")

    true_positives = len(matched_expectations)
    false_negatives = len(expectations) - true_positives
    false_positives = len(program.findings) - len(matched_findings)
    label = str(case.get("label"))
    file_level_tn = label in ("safe", "sanitized") and not program.findings
    file_level_fp = label in ("safe", "sanitized") and bool(program.findings)

    # "analysis_ok" is the engine's own verdict on the file: false for a file
    # that was deliberately malformed or outside the subset.  "verdict" is what
    # the harness decides about the *expectation*: a case passes when every
    # documented finding is reported, nothing else is reported, and the expected
    # diagnostics appear.
    reasons: List[str] = []
    if false_negatives:
        reasons.append(f"{false_negatives} expected finding(s) were not reported")
    if false_positives:
        reasons.append(f"{false_positives} unexpected finding(s) were reported")
    if missing_codes:
        reasons.append(f"expected diagnostics missing: {', '.join(missing_codes)}")
    if unexpected_errors:
        reasons.append(f"unexpected error diagnostics: {', '.join(sorted(set(unexpected_errors)))}")
    if forbidden_present:
        reasons.append(f"forbidden diagnostics present: {', '.join(forbidden_present)}")
    if complete_mismatch:
        reasons.append(
            f"analysis_complete is {program.analysis_complete}, "
            f"expected {bool(expected_complete)}"
        )
    if file_level_fp:
        reasons.append("a finding was reported in a case labelled safe/sanitized")

    return {
        "file": case["file"],
        "label": label,
        "accepted": program.parse.accepted,
        "analysis_ok": program.ok,
        "verdict": "pass" if not reasons else "fail",
        "reasons": reasons,
        "findings": [f.to_json(include_path=False) for f in program.findings],
        "reported_rules": sorted({f.rule_id for f in program.findings}),
        "expectations": expectations,
        "missing_expectations": [
            expectations[i] for i in range(len(expectations)) if i not in matched_expectations
        ],
        "diagnostic_codes": codes,
        "expected_diagnostic_codes": expected_codes,
        "missing_diagnostic_codes": missing_codes,
        "unexpected_error_codes": unexpected_errors,
        "forbidden_diagnostic_codes": forbidden_codes,
        "forbidden_diagnostic_codes_present": forbidden_present,
        "analysis_complete": program.analysis_complete,
        "expected_analysis_complete": expected_complete,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "file_level_true_negative": file_level_tn,
        "file_level_false_positive": file_level_fp,
        "seconds": round(seconds, 6),
        "limits_hit": list(program.limits_hit),
        "rule_diagnostics": rule_diagnostics,
        "metrics": {
            "statements": len(program.statements),
            "cfg_blocks": sum(len(cfg.blocks) for cfg in program.cfgs.values()),
            "dependency_edges": program.dependencies.stats()["edges"] if program.dependencies else 0,
            "taint_iterations": program.taint.iterations,
            "taint_converged": program.taint.converged,
        },
    }


def ratio(numerator: int, denominator: int, wording: str) -> Tuple[Optional[float], str]:
    """A metric with honest zero-denominator handling."""
    if denominator == 0:
        return None, wording
    return round(numerator / denominator, 4), ""


def evaluate(verbose: bool = True) -> dict:
    with open(EXPECTATIONS, "r", encoding="utf-8") as handle:
        corpus = json.load(handle)

    results = [run_case(case) for case in corpus["cases"]]

    tp = sum(r.get("true_positives", 0) for r in results)
    fp = sum(r.get("false_positives", 0) for r in results)
    fn = sum(r.get("false_negatives", 0) for r in results)
    file_tn = sum(1 for r in results if r.get("file_level_true_negative"))
    file_fp = sum(1 for r in results if r.get("file_level_false_positive"))
    safe_files = sum(1 for r in results if r["label"] in ("safe", "sanitized"))

    precision, precision_note = ratio(tp, tp + fp, "no findings were reported in this corpus")
    recall, recall_note = ratio(tp, tp + fn, "the corpus expects no findings")
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1: Optional[float] = round(2 * precision * recall / (precision + recall), 4)
        f1_note = ""
    else:
        f1, f1_note = None, "F1 is undefined because precision or recall is undefined or both are zero"

    diagnostic_failures = [
        r["file"]
        for r in results
        if r.get("missing_diagnostic_codes") or r.get("unexpected_error_codes")
        or r.get("forbidden_diagnostic_codes_present")
    ]

    report = {
        "corpus_version": corpus["corpus_version"],
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor_count": os.cpu_count(),
        },
        "corpus": {
            "cases": len(results),
            "safe_or_sanitized_cases": safe_files,
            "files": [r["file"] for r in results],
        },
        "totals": {
            "cases_passed": sum(1 for r in results if r.get("verdict") == "pass"),
            "cases_failed": sum(1 for r in results if r.get("verdict") == "fail"),
            "expected_findings": tp + fn,
            "reported_findings": tp + fp,
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "file_level_true_negatives": file_tn,
            "file_level_false_positives": file_fp,
            "cases_with_diagnostic_mismatch": diagnostic_failures,
        },
        "metrics": {
            "precision": precision,
            "precision_note": precision_note,
            "recall": recall,
            "recall_note": recall_note,
            "f1": f1,
            "f1_note": f1_note,
        },
        "cases": results,
        "interpretation": (
            "These numbers describe the labelled corpus in this repository only. The corpus is "
            "small and hand-written, so the metrics are a regression signal for the analysis "
            "pipeline, not an estimate of real-world detection quality or of security."
        ),
    }

    if verbose:
        print(f"CodeTrace evaluation - engine {ENGINE_VERSION}, "
              f"corpus {corpus['corpus_version']} ({len(results)} cases)")
        print("-" * 108)
        print(f"{'case':44} {'label':14} {'exp':>3} {'rep':>3} {'TP':>3} {'FP':>3} {'FN':>3}  diag")
        print("-" * 108)
        for result in results:
            if "error" in result:
                print(f"{result['file']:44} HARNESS ERROR: {result['error']}")
                continue
            marker = "" if result.get("verdict") == "pass" else "  <-- check"
            print(
                f"{result['file']:44} {result['label']:14} {len(result['expectations']):3d} "
                f"{len(result['findings']):3d} {result['true_positives']:3d} "
                f"{result['false_positives']:3d} {result['false_negatives']:3d}  "
                f"{','.join(result['diagnostic_codes'][:3])}{marker}"
            )
        print("-" * 108)
        print(
            f"findings: TP={tp} FP={fp} FN={fn}   files: TN={file_tn} FP={file_fp} "
            f"({safe_files} safe/sanitized cases)"
        )
        print(
            f"precision={precision if precision is not None else 'undefined'} {precision_note} | "
            f"recall={recall if recall is not None else 'undefined'} {recall_note} | "
            f"F1={f1 if f1 is not None else 'undefined'} {f1_note}"
        )
        total_seconds = sum(r.get("seconds", 0) for r in results)
        print(f"analysis time: {total_seconds:.3f}s over {len(results)} files")
        if diagnostic_failures:
            print("diagnostic mismatches:")
            for file in diagnostic_failures:
                entry = next(r for r in results if r["file"] == file)
                print(f"  {file}: missing={entry['missing_diagnostic_codes']} "
                      f"unexpected={entry['unexpected_error_codes']}")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", metavar="PATH", help="write the full report as JSON")
    parser.add_argument("--quiet", action="store_true", help="only write the JSON report")
    args = parser.parse_args()

    report = evaluate(verbose=not args.quiet)
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        if not args.quiet:
            print(f"wrote {args.json}")

    failing = [case for case in report["cases"] if case.get("verdict") != "pass"]
    if failing and not args.quiet:
        for case in failing:
            print(f"case failed: {case['file']}: {'; '.join(case.get('reasons', []))}")
    return 0 if not failing else 1


if __name__ == "__main__":
    raise SystemExit(main())
