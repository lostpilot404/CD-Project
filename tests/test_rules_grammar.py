"""Rule-language, rule-merging and parser-table contracts.

Pins the rule-layer behaviour the audit verified only by probe (docs
RULE_LANGUAGE.md / LANGUAGE.md §5) and the measured table statistics that
docs/COMPILER_THEORY.md §6 states, so the documentation cannot drift away
from the generator silently.
"""

import unittest

from codetrace.analysis.pipeline import analyse_source, parser_tables
from codetrace.frontend.clr_parser import REDUCE
from codetrace.reporting.json_report import build_report
from codetrace.rules.rule_language import load_builtin_rules, parse_and_validate
from codetrace.rules.model import merge


def validate(text):
    rule_set, diagnostics, _parsed = parse_and_validate(text)
    return rule_set, diagnostics


def error_codes(diagnostics):
    return {d.code for d in diagnostics if d.severity == "error"}


class TestRuleValidation(unittest.TestCase):
    def test_context_rejected_inside_source(self):
        _rules, diagnostics = validate("""version 1
source stdin { function input context command }
""")
        self.assertIn("RULE004", error_codes(diagnostics))

    def test_flow_with_unknown_source_rejected(self):
        _rules, diagnostics = validate("""version 1
sink cmd { function system arguments 0 context command }
flow f { sources ghost sinks cmd enabled true }
""")
        self.assertIn("RULE020", error_codes(diagnostics))

    def test_minimal_valid_set_counts(self):
        rules, diagnostics = validate("""version 1
source stdin {
    function input
    returns
    contexts command
}
sink cmd { function system arguments 0 context command }
flow f1 { sources stdin sinks cmd enabled true }
""")
        self.assertEqual(error_codes(diagnostics), set())
        stats = rules.stats()
        self.assertEqual((stats["sources"], stats["sinks"], stats["flows"], stats["enabled_flows"]),
                         (1, 1, 1, 1))

    def test_from_to_flow_syntax_is_rejected(self):
        # The documented flow syntax is 'sources <ids>' / 'sinks <ids>';
        # the intuitive 'from X to Y' form must fail validation loudly,
        # not parse into something else (LANGUAGE.md §5).
        _rules, diagnostics = validate("""version 1
source stdin {
    function input
    returns
    contexts command
}
sink cmd { function system arguments 0 context command }
flow f1 { from stdin to cmd }
""")
        self.assertTrue(error_codes(diagnostics))


class TestMergeAndFingerprint(unittest.TestCase):
    def setUp(self):
        self.builtin, builtin_diags = load_builtin_rules()
        self.assertEqual([d for d in builtin_diags if d.severity == "error"], [])
        self.custom, _ = validate("""version 1
source sensor {
    function fetch
    returns
    contexts command
}
sink danger { function danger arguments 0 context command }
flow custom_flow { sources sensor sinks danger enabled true }
""")

    def test_merge_keeps_both_layers(self):
        merged = merge(self.builtin, self.custom)
        self.assertTrue(merged.source_rules("input"), "builtin sources survive the merge")
        self.assertTrue(merged.source_rules("fetch"), "custom sources are added")
        self.assertTrue(merged.sink_rules("system"))
        self.assertTrue(merged.sink_rules("danger"))
        self.assertIsNotNone(merged.flow_for("command_system", "stdin"))
        self.assertIsNotNone(merged.flow_for("danger", "sensor"))

    def test_fingerprint_is_deterministic_and_sensitive(self):
        again, _ = validate("""version 1
source sensor {
    function fetch
    returns
    contexts command
}
sink danger { function danger arguments 0 context command }
flow custom_flow { sources sensor sinks danger enabled true }
""")
        self.assertEqual(again.fingerprint(), self.custom.fingerprint())
        self.assertNotEqual(self.custom.fingerprint(), self.builtin.fingerprint())


class TestNoFlowNoFinding(unittest.TestCase):
    def test_sink_without_connecting_flow_is_disclosed_not_reported(self):
        rules, _ = validate("""version 1
source sensor {
    function fetch
    returns
    contexts command
}
sink danger { function danger arguments 0 context command }
""")
        program = analyse_source(
            'int main() { string value = fetch(); danger(value); return 0; }',
            filename="t.ctc", rules=rules)
        self.assertEqual(program.findings, [],
                         "without an enabled flow connecting source and sink "
                         "there is nothing to report — by design")
        report = build_report(program)
        dispositions = report["summary"]["dispositions"]
        self.assertEqual(dispositions["reported"], 0)
        self.assertGreaterEqual(dispositions["sink_calls_seen"], 1)
        self.assertGreaterEqual(dispositions["unreported_count"], 1)
        self.assertIn("flow", dispositions["note"])


class TestParserTableStatistics(unittest.TestCase):
    """The numbers docs/COMPILER_THEORY.md §6 states, measured."""

    def test_lalr_tables(self):
        tables = parser_tables("lalr")
        self.assertEqual(len(tables.grammar.productions), 102)
        self.assertEqual(tables.automaton.stats.states, 167)
        self.assertEqual(len(tables.conflicts), 0)
        self.assertEqual(len(tables.action), 2172)
        self.assertEqual(len(tables.goto), 382)

    def test_slr_tables_differ_by_exactly_three_reduce_entries(self):
        slr = parser_tables("slr")
        lalr = parser_tables("lalr")
        self.assertEqual(slr.automaton.stats.states, 167)
        self.assertEqual(len(slr.conflicts), 0)
        self.assertEqual(len(slr.action), 2175)
        extra = set(slr.action) - set(lalr.action)
        missing = set(lalr.action) - set(slr.action)
        self.assertEqual(len(extra), 3)
        self.assertEqual(missing, set(), "LALR never has entries SLR lacks here")
        self.assertTrue(all(slr.action[key].kind == REDUCE for key in extra),
                        "the SLR-only entries are the coarser-lookahead reduces")
        shared_shifts_agree = all(
            slr.action[key].kind == lalr.action[key].kind
            and slr.action[key].value == lalr.action[key].value
            for key in set(slr.action) & set(lalr.action)
            if slr.action[key].kind != REDUCE
        )
        self.assertTrue(shared_shifts_agree)
        self.assertEqual(slr.goto, lalr.goto)

    def test_canonical_tables_build_conflict_free(self):
        tables = parser_tables("canonical")
        self.assertEqual(tables.automaton.stats.states, 656)
        self.assertEqual(len(tables.conflicts), 0)


if __name__ == "__main__":
    unittest.main()
