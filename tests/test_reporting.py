"""Reporting tests: the JSON report and the self-contained HTML report.

A report is evidence, so the tests check what it must contain (the run identity,
the source hash, the analysis order, the dispositions, the limitations) as well
as what it must not (unescaped source text, absolute server paths, external
resources, claims of safety).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

from codetrace.reporting.html_report import write_html_report
from codetrace.reporting.json_report import build_report, to_json_text
from codetrace.version import ENGINE_VERSION, SCHEMA_VERSION
from tests.helpers import ROOT, analyse

VULNERABLE = 'int main() { string cmd = input(); system(cmd); return 0; }'
CLEAN = "int main() { int a = 1; return a; }"


class JsonReportTests(unittest.TestCase):
    def setUp(self):
        self.program = analyse(VULNERABLE, filename="report.ctc")
        self.report = build_report(self.program, run_id="run-abc")

    def test_report_identifies_the_run_and_the_engine(self):
        self.assertEqual(self.report["schema_version"], SCHEMA_VERSION)
        self.assertEqual(self.report["tool"]["name"], "CodeTrace")
        self.assertEqual(self.report["tool"]["version"], ENGINE_VERSION)
        self.assertEqual(self.report["run"]["run_id"], "run-abc")
        self.assertEqual(self.report["run"]["engine_version"], ENGINE_VERSION)
        self.assertTrue(self.report["run"]["rules_version"].startswith("builtin-"))
        self.assertEqual(self.report["run"]["grammar"]["conflicts"], 0)
        self.assertEqual(self.report["run"]["parser_mode"], "lalr")
        self.assertTrue(self.report["run"]["timestamp"].endswith("Z"))

    def test_report_records_the_input_fingerprint(self):
        payload = self.report["input"]
        self.assertEqual(payload["filename"], "report.ctc")
        self.assertEqual(payload["bytes"], len(self.program.source.encode("utf-8")))
        self.assertEqual(len(payload["sha256"]), 64)
        other = build_report(analyse(CLEAN, filename="report.ctc"))
        self.assertNotEqual(payload["sha256"], other["input"]["sha256"])

    def test_report_lists_the_pipeline_order_and_real_metrics(self):
        order = self.report["analysis"]["order"]
        for stage in ("lexer", "parser", "semantic analysis", "control-flow graph",
                      "reaching definitions", "liveness", "taint", "dependency graph", "slicing"):
            self.assertTrue(
                any(stage in entry for entry in order), f"{stage} is missing from the pipeline order"
            )
        metrics = self.report["metrics"]
        for key in ("grammar_states", "grammar_productions", "tokens", "ast_nodes", "statements",
                    "functions", "basic_blocks", "definitions", "dependency_edges", "taint_hits",
                    "findings", "timings"):
            self.assertIn(key, metrics)
        for phase in ("lex_seconds", "parse_seconds", "semantic_seconds", "cfg_seconds",
                      "dataflow_seconds", "taint_seconds", "findings_seconds"):
            self.assertIn(phase, metrics["timings"])
            self.assertLess(metrics["timings"][phase], 60, "phase timings are seconds, not cumulative")
        self.assertEqual(metrics["findings"], len(self.program.findings))
        self.assertEqual(metrics["grammar_conflicts"], 0)

    def test_report_contains_findings_with_evidence(self):
        findings = self.report["findings"]
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["rule_id"], "command_execution")
        self.assertTrue(finding["path"])
        self.assertTrue(finding["evidence"]["atoms"])
        self.assertTrue(finding["limitations"])
        self.assertTrue(finding["remediation"])
        self.assertTrue(finding["explanation"])

    def test_report_states_its_limits_and_never_claims_safety(self):
        limitations = " ".join(self.report["limitations"]).lower()
        self.assertIn("static analysis only", limitations)
        self.assertIn("never assumed safe", limitations)
        self.assertIn("context-insensitive", limitations)
        self.assertIn("unsupported", limitations)
        clean_report = build_report(analyse(CLEAN))
        limitations = " ".join(clean_report["limitations"]).lower()
        self.assertNotIn("the program is safe", limitations)
        self.assertIn("never assumed safe", limitations)

    def test_report_explains_a_sink_that_was_not_reported(self):
        run = analyse(
            """
int main() {
  string cmd = input();
  system(shell_escape(cmd));
  return 0;
}
"""
        )
        report = build_report(run)
        dispositions = report["summary"]["dispositions"]
        self.assertEqual(dispositions["reported"], 0)
        self.assertEqual(dispositions["sink_calls_seen"], 1)
        self.assertEqual(dispositions["unreported_count"], 1)
        entry = dispositions["unreported_sink_calls"][0]
        self.assertEqual(entry["sink_rule"], "command_system")
        self.assertEqual(entry["function"], "main", "the enclosing function is recorded")
        self.assertTrue(entry["reason"])

    def test_report_is_deterministic_apart_from_the_timestamp(self):
        again = build_report(analyse(VULNERABLE, filename="report.ctc"), run_id="run-abc")
        def stable(report):
            copy = dict(report)
            copy["run"] = {k: v for k, v in copy["run"].items() if k != "timestamp"}
            copy["metrics"] = {k: v for k, v in copy["metrics"].items() if k != "timings"}
            return copy

        self.assertEqual(stable(self.report), stable(again))
        self.assertEqual(
            to_json_text(stable(self.report)), to_json_text(stable(again)),
            "the serialised report is byte-identical for the same input",
        )

    def test_report_is_json_serialisable_without_custom_encoders(self):
        text = to_json_text(self.report)
        reparsed = json.loads(text)
        self.assertEqual(reparsed["summary"]["findings"], 1)
        self.assertIsInstance(text, str)
        self.assertIn("\n", text, "the report is pretty-printed for reading")

    def test_report_carries_the_labelled_evaluation_when_supplied(self):
        evaluation = {
            "case": "unit",
            "expected": ["command_execution"],
            "observed": ["command_execution"],
            "matched": True,
        }
        report = build_report(self.program, evaluation=evaluation)
        self.assertEqual(report["evaluation"]["case"], "unit")
        self.assertTrue(report["evaluation"]["matched"])
        plain = build_report(self.program)
        self.assertFalse(plain["evaluation"]["available"])


class HtmlReportTests(unittest.TestCase):
    def test_html_is_self_contained_and_escapes_the_source(self):
        hostile = (
            'int main() { string cmd = input(); system("<img src=x onerror=alert(1)>" + cmd);'
            " return 0; }"
        )
        program = analyse(hostile, filename="hostile.ctc")
        from codetrace.reporting.html_report import render_html

        html = render_html(program, run_id="run-html")
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertNotIn("<img src=x onerror=alert(1)>", html)
        self.assertIn("&lt;img", html)
        self.assertNotIn("<script", html, "the report needs no scripting to be read")
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("/home/", html, "no absolute server path leaks into the report")
        for section in ("Findings", "Evidence path", "Remediation", "Analysis limitations",
                        "Diagnostics"):
            self.assertIn(section, html)

    def test_html_escapes_a_hostile_filename(self):
        from codetrace.reporting.html_report import render_html

        program = analyse(CLEAN, filename="<script>alert(1)</script>.ctc")
        html = render_html(program)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_html_reports_the_dispositions_and_limitations(self):
        from codetrace.reporting.html_report import render_html

        program = analyse(VULNERABLE)
        html = render_html(program, run_id="run-html")
        self.assertIn("run-html", html)
        self.assertIn("command_execution", html)
        self.assertIn("Static analysis only", html)

    def test_html_report_is_written_to_disk(self):
        program = analyse(VULNERABLE)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "report.html")
            written = write_html_report(program, path, run_id="run-file")
            self.assertEqual(written, path)
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
        self.assertTrue(content.startswith("<!DOCTYPE html>"))
        self.assertIn("run-file", content)

    def test_empty_and_unsupported_programs_still_produce_a_report(self):
        from codetrace.reporting.html_report import render_html

        for source in ("", "int main() { switch (1) { case 1: return 0; } }"):
            with self.subTest(source=source[:20]):
                program = analyse(source)
                report = build_report(program)
                self.assertIn("limitations", report)
                html = render_html(program)
                self.assertIn("Analysis limitations", html)
                self.assertIn("never assumed safe", html)


class ValidatorSuppressionReportingTests(unittest.TestCase):
    """A cleared flow must be reported as a cleared flow, never as an absence.

    The engine records the assumption; these tests hold the two published
    report formats to actually carrying it, because a report that shows zero
    findings without naming the validator reads as "nothing ever reached the
    sink" -- which is a different and untrue claim.
    """

    GUARDED = """
int main() {
  string name = input();
  if (is_safe_command(name)) {
    system(name);
  }
  return 0;
}
"""

    def setUp(self):
        self.program = analyse(self.GUARDED, filename="guarded.ctc")
        self.report = build_report(self.program, run_id="run-guard")
        self.dispositions = self.report["summary"]["dispositions"]

    def test_the_run_has_no_findings_and_says_why(self):
        self.assertEqual(self.report["summary"]["findings"], 0)
        self.assertEqual(self.dispositions["sink_calls_seen"], 1)
        self.assertEqual(self.dispositions["reported"], 0)
        self.assertEqual(self.dispositions["unreported_count"], 1)
        reason = self.dispositions["unreported_sink_calls"][0]["reason"]
        self.assertIn("validate_command", reason)
        self.assertIn("cleared", reason)
        # The old generic wording claimed no taint arrived; it did arrive.
        self.assertNotIn("no taint of the required context reached", reason)

    def test_the_guard_record_carries_the_evidence(self):
        guard = self.dispositions["validator_guards"][0]
        self.assertEqual(guard["validator"], "validate_command")
        self.assertEqual(guard["validator_function"], "is_safe_command")
        self.assertEqual(guard["symbol"], "name")
        self.assertEqual(guard["context"], "command")
        self.assertEqual(guard["removed_atoms"], ["src:stdin@command"])
        self.assertIn("assumes it rejects", guard["assumption"])

    def test_the_limitation_section_states_the_assumption(self):
        matched = [l for l in self.report["limitations"] if "unreported sink call" in l]
        self.assertEqual(len(matched), 1)
        self.assertIn("validate_command", matched[0])
        self.assertTrue(any("never executed" in l for l in self.report["limitations"]))

    def test_the_report_carries_the_run_notes(self):
        self.assertTrue(self.report["notes"])
        self.assertTrue(any("cleared on" in note for note in self.report["notes"]))

    def test_an_unrelated_suppression_is_not_counted_as_hidden(self):
        # The guard covers ``checked``; the reported finding is about ``other``.
        # Nothing was hidden by the guard, so the run must not claim otherwise.
        program = analyse(
            """
int main() {
  string checked = input();
  string other = input();
  if (is_safe_command(checked)) {
    system(other);
  }
  return 0;
}
"""
        )
        report = build_report(program, run_id="run-unrelated")
        self.assertEqual(report["summary"]["findings"], 1)
        self.assertEqual(
            [l for l in report["limitations"] if "unreported sink call" in l], []
        )
        self.assertTrue(report["summary"]["dispositions"]["validator_guards"])

    def test_a_run_without_guards_has_no_suppression_limitation(self):
        program = analyse(VULNERABLE, filename="plain.ctc")
        report = build_report(program, run_id="run-plain")
        self.assertEqual(report["summary"]["dispositions"]["validator_guards"], [])
        self.assertEqual(
            [l for l in report["limitations"] if "unreported sink call" in l], []
        )

    def test_the_html_report_shows_the_guard_instead_of_an_empty_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "guarded.html")
            write_html_report(self.program, path, run_id="run-guard")
            with open(path, encoding="utf-8") as handle:
                html = handle.read()
        self.assertIn("What the engine saw but did not report", html)
        self.assertIn("validate_command", html)
        self.assertIn("assumption", html)
        self.assertIn("guards name for context 'command' at line 3", html)
        self.assertIn("src:stdin@command", html)
        self.assertIn("inspected and not reported (1)", html)
        # The clear statement that the run is not a proof survives alongside it.
        self.assertIn("not a proof of exploitability", html)


class EvaluationHarnessTests(unittest.TestCase):
    def test_the_labelled_corpus_harness_runs_and_writes_json(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "evaluation.json")
            result = subprocess.run(
                [sys.executable, "evaluation/run_evaluation.py", "--json", target],
                cwd=ROOT, capture_output=True, text=True, timeout=600,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("TP=", result.stdout)
            with open(target, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        totals = payload["totals"]
        self.assertEqual(totals["cases_failed"], 0)
        self.assertGreaterEqual(totals["true_positives"], 15)
        self.assertEqual(totals["false_positives"], 0)
        self.assertEqual(totals["false_negatives"], 0)
        self.assertGreaterEqual(totals["file_level_true_negatives"], 8)
        self.assertEqual(payload["metrics"]["precision"], 1.0)
        self.assertEqual(payload["metrics"]["recall"], 1.0)
        self.assertEqual(payload["metrics"]["f1"], 1.0)
        self.assertEqual(payload["metrics"]["precision_note"], "", "no zero-denominator adjustment was needed")
        self.assertTrue(payload["cases"], "per-file results are recorded")
        self.assertTrue(all(case["verdict"] == "pass" for case in payload["cases"]))
        self.assertEqual(totals["cases_passed"], len(payload["cases"]))
        # "analysis_ok" is the engine's verdict on the file, which is false for the
        # deliberately malformed and unsupported cases; that is expected there.
        self.assertLess(
            sum(1 for case in payload["cases"] if case["analysis_ok"]), len(payload["cases"])
        )
        self.assertIn("environment", payload, "the benchmark records the machine it ran on")
        first = payload["cases"][0]
        for key in ("file", "label", "verdict", "reasons", "analysis_ok", "findings",
                    "reported_rules", "seconds"):
            self.assertIn(key, first)

    def test_every_corpus_case_enters_exactly_one_metric_group(self):
        # The documentation states the coverage as "17 expectations in 15 files,
        # 8 file-level cases, 6 diagnostic-only cases".  That accounting has to
        # be a property of the corpus rather than a sentence in a document, or a
        # later edit can quietly make "29 cases" sound like 29 detections.
        with open(os.path.join(ROOT, "evaluation", "expectations.json"), "r", encoding="utf-8") as handle:
            expectations = json.load(handle)
        cases = expectations["cases"]
        finding_level = [c for c in cases if c.get("expect")]
        file_level = [c for c in cases if c["label"] in ("safe", "sanitized")]
        diagnostic_only = [c for c in cases if c["label"] in ("unsupported", "syntax_error")]

        self.assertEqual(len(finding_level) + len(file_level) + len(diagnostic_only), len(cases),
                         "the three metric groups partition the corpus")
        files = [c["file"] for c in cases]
        self.assertEqual(len(set(files)), len(files), "each file appears once")
        # A case may not be counted twice: an expectation-bearing case must not
        # also be a file-level case, and vice versa.
        self.assertEqual([c for c in finding_level if c["label"] in ("safe", "sanitized")], [])
        self.assertEqual([c for c in file_level if c.get("expect")], [])
        # The diagnostic-only cases declare no expectation and no safe label, so
        # they cannot enter a precision or recall denominator.
        for case in diagnostic_only:
            self.assertEqual(case.get("expect"), [], case["file"])
            self.assertTrue(case.get("expect_diagnostics"), case["file"])
        # And the counts the docs quote are the counts in the file.
        self.assertEqual(sum(len(c.get("expect") or []) for c in cases), 17)
        self.assertEqual(len(finding_level), 15)
        self.assertEqual(len(file_level), 8)
        self.assertEqual(len(diagnostic_only), 6)

    def test_the_corpus_is_separate_from_the_unit_tests(self):
        with open(os.path.join(ROOT, "evaluation", "expectations.json"), "r", encoding="utf-8") as handle:
            expectations = json.load(handle)
        self.assertGreaterEqual(len(expectations["cases"]), 25)
        self.assertIn("matching", expectations)
        for case in expectations["cases"]:
            for key in ("file", "label", "expect", "rationale", "expect_diagnostics"):
                self.assertIn(key, case)
            # The corpus files are examples, never test modules.
            self.assertFalse(case["file"].startswith("tests/"))
            self.assertTrue(
                os.path.exists(os.path.join(ROOT, "examples", case["file"])),
                f"{case['file']} is a bundled example",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
