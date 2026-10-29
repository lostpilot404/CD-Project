"""Taint-engine precision contracts (audit defects D9/D10/D16/D17).

Pins:
* a validator used as a boolean value does not propagate its argument's
  taint into the result (the pre-fix engine reported false positives for
  ``bool ok = is_safe_command(n); system(ok);``), while the semantic warning
  for the suspicious conversion survives and genuine flows still report;
* statically impossible branches are pruned *and* disclosed consistently for
  both edge forms (``if (0)`` true-edge and ``if (1) … else`` false-edge,
  whose condition the CFG stores as ``not (…)``);
* multi-sanitizer kill-context merging removes exactly the declared contexts
  — no lost kills, no over-kill into undeclared contexts;
* a catalog-resolved call without a rule role is explained accurately and
  differently from a truly unknown function;
* the source-to-sink edges of the dependency graph are exactly the deduplicated
  non-degenerate hops of the reported findings' paths.
"""

import os
import unittest

from codetrace.analysis.pipeline import analyse_source
from codetrace.reporting.json_report import build_report
from codetrace.rules.rule_language import load_builtin_rules, parse_and_validate
from codetrace.rules.model import merge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILTIN_RULES, _ = load_builtin_rules()


def run(source, rules=None):
    return analyse_source(source, filename="t.ctc", rules=rules or BUILTIN_RULES)


def custom_rules(text):
    rule_set, diagnostics, _parsed = parse_and_validate(text)
    errors = [d for d in diagnostics if d.severity == "error"]
    assert not errors, [(d.code, d.message) for d in errors]
    return rule_set


class TestValidatorBooleanResult(unittest.TestCase):
    def test_boolean_result_carries_no_string_taint(self):
        program = run("""int main() {
  string name = input();
  bool ok = is_safe_command(name);
  system(ok);
  return 0;
}""")
        self.assertEqual(program.findings, [],
                         "a boolean cannot carry the command-context taint of its argument")
        codes = [d.code for d in program.diagnostics]
        self.assertIn("SEM010", codes,
                      "the suspicious bool-to-string conversion must still be reported")

    def test_genuine_flow_still_reports(self):
        # Negative control: the case above passes because of the boolean rule,
        # not because the engine went quiet.
        program = run('int main() { string name = input(); system(name); return 0; }')
        self.assertEqual(len(program.findings), 1)
        self.assertEqual(program.findings[0].rule_id, "command_execution")

    def test_validator_guard_still_suppresses(self):
        program = run("""int main() {
  string name = input();
  if (is_safe_command(name)) {
    system(name);
  }
  return 0;
}""")
        self.assertEqual(program.findings, [])


class TestConstantBranchPruning(unittest.TestCase):
    def test_constant_false_true_edge_pruned_and_disclosed(self):
        program = run("""int main() {
  string name = input();
  if (0) {
    system(name);
  }
  return 0;
}""")
        self.assertEqual(program.findings, [])
        reasons = [entry["reason"] for entry in program.taint.infeasible_edges]
        self.assertEqual(len(reasons), 1, program.taint.infeasible_edges)
        self.assertIn("'0'", reasons[0])

    def test_constant_true_false_edge_pruned_and_disclosed(self):
        # The CFG stores a false edge's condition as "not (…)"; the pre-fix
        # engine matched raw text only, analysed the dead else branch as live
        # and reported the sink.
        program = run("""int main() {
  string name = input();
  if (1) {
    return 0;
  } else {
    system(name);
  }
  return 0;
}""")
        self.assertEqual(program.findings, [])
        reasons = [entry["reason"] for entry in program.taint.infeasible_edges]
        self.assertEqual(len(reasons), 1, program.taint.infeasible_edges)
        self.assertIn("'1'", reasons[0])

    def test_disclosure_reaches_the_report_dispositions(self):
        program = run("""int main() {
  string name = input();
  if (0) {
    system(name);
  }
  return 0;
}""")
        report = build_report(program)
        pruned = report["summary"]["dispositions"]["statically_pruned_branches"]
        self.assertEqual(len(pruned), 1)
        self.assertIn("'0'", pruned[0]["reason"])


CLEAN_PROGRAM = """int main() {
  string value = shell_escape(input());
  system(value);
  sql_exec(value);
  return 0;
}"""


class TestKillContextMerging(unittest.TestCase):
    """One rule file may bind only one sanitizer rule per function (RULE025),
    so the multi-rule merge path arises when a custom rule set is merged over
    the builtins: the built-in shell_escape kills the command context, a
    custom rule adds the sql context for the same function."""

    def setUp(self):
        self.builtin, _ = load_builtin_rules()
        self.merged = merge(self.builtin, custom_rules("""version 1
sanitizer shell_escape_sql { function shell_escape argument 0 context sql }
"""))

    def test_merged_contexts_both_removed(self):
        program = run(CLEAN_PROGRAM, rules=self.merged)
        self.assertEqual(program.findings, [],
                         "sanitizer rules merged from both layers must kill "
                         "their respective contexts, not overwrite each other")

    def test_undeclared_context_not_removed(self):
        program = run(CLEAN_PROGRAM, rules=self.builtin)
        reported = {f.rule_id for f in program.findings}
        self.assertEqual(reported, {"sql_injection"},
                         "the command context is sanitised; the sql context must still report")


class TestExternalCallNotes(unittest.TestCase):
    def test_catalog_name_without_rule_role_is_explained_accurately(self):
        program = run('int main() { string name = input(); print(name); return 0; }')
        notes = " ".join(program.taint.notes)
        self.assertIn("print", notes)
        self.assertIn("external model resolves", notes)
        self.assertNotIn("unknown function 'print'", notes)

    def test_truly_unknown_function_keeps_the_unknown_note(self):
        program = run('int main() { string name = input(); myhelper(name); return 0; }')
        notes = " ".join(program.taint.notes)
        self.assertIn("unknown function 'myhelper'", notes)


class TestSourceToSinkEdgeConsistency(unittest.TestCase):
    def test_edges_are_exactly_the_path_hops(self):
        path = os.path.join(ROOT, "examples", "vulnerable", "two_step_command.ctc")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        program = run(source)
        self.assertEqual(len(program.findings), 1)
        graph = program.dependencies
        edges = {(e.src, e.dst) for e in graph.edges if e.kind == "source-to-sink"}
        expected = set()
        for finding in program.findings:
            for step in finding.path:
                src, dst = step.get("from_sid", -1), step.get("sid", -1)
                if src < 0 or dst < 0 or src == dst:
                    continue
                if f"s{src}" in graph.nodes and f"s{dst}" in graph.nodes:
                    expected.add((f"s{src}", f"s{dst}"))
        self.assertEqual(edges, expected)
        self.assertTrue(edges, "the reported flow must be visible in the graph")


if __name__ == "__main__":
    unittest.main()
