"""Rule language tests: the declarative rule file is untrusted input.

The rule language is parsed with the same CLR(1) machinery as the analysed
language, and validated completely *before* any rule reaches the engine.  These
tests pin that contract:

* the grammar builds with no conflicts, from the same table generator;
* lexical and syntax problems carry a line:col and produce no rule set;
* semantic problems are reported with stable codes (RULE001 - RULE026);
* a rule file can never carry executable content -- the analysis only ever sees
  the values the language defines.
"""

from __future__ import annotations

import ast
import os
import unittest

from codetrace.rules import rule_language as rl
from codetrace.rules.model import RuleSet, merge
from codetrace.rules.rule_language import (
    load_builtin_rules,
    parse_and_validate,
    parse_rule_text,
    rule_tables,
)
from tests.helpers import ROOT

BUILTIN_PATH = os.path.join(ROOT, "codetrace", "rules", "builtin", "standard.ctrule")

HEADER = "version 1\n\n"


def errors(diagnostics):
    return [(d.code, d.line, d.col, d.message) for d in diagnostics if d.severity == "error"]


def warnings(diagnostics):
    return [(d.code, d.line, d.col, d.message) for d in diagnostics if d.severity == "warning"]


def codes(diagnostics):
    return [d.code for d in diagnostics]


class RuleGrammarTests(unittest.TestCase):
    def test_rule_grammar_is_built_by_the_shared_table_generator(self):
        tables = rule_tables()
        self.assertIs(rule_tables(), tables, "the tables are built once and cached")
        self.assertEqual(len(tables.conflicts), 0, "the rule grammar is LALR(1) without conflicts")
        self.assertGreater(len(tables.grammar.productions), 30)
        self.assertGreater(tables.automaton.stats.states, 50)
        first, nullable = tables.grammar.first_of_sequence([])
        self.assertEqual(first, set())
        self.assertTrue(nullable, "the empty sequence is nullable")

    def test_the_documented_keywords_are_the_ones_the_lexer_knows(self):
        for keyword in ("source", "sink", "sanitizer", "validator", "flow", "version"):
            self.assertIn(keyword, rl.RULE_KEYWORDS)
        # Words from other languages are recognised only so that the error message
        # can say they are not part of the rule language.
        for keyword in ("def", "class", "lambda"):
            self.assertIn(keyword, rl.RULE_UNSUPPORTED_KEYWORDS)
        self.assertEqual(rl.SUPPORTED_VERSIONS, (1,))

    def test_comments_and_any_layout_are_accepted(self):
        one_line = parse_rule_text(
            "version 1\n# comment\nsource s { function input returns contexts command }\n"
        )
        multi_line = parse_rule_text(
            "version 1\n\n# comment\nsource s {\n  function input\n  returns\n  contexts command\n}\n"
        )
        for parsed in (one_line, multi_line):
            self.assertTrue(parsed.accepted)
            self.assertEqual(parsed.diagnostics, [])
            self.assertEqual([decl["id"] for decl in parsed.declarations], ["version", "s"])

    def test_syntax_error_reports_the_position(self):
        parsed = parse_rule_text("version 1\n\nsource s {\n  function input\n  returns\n")
        self.assertFalse(parsed.accepted)
        self.assertTrue(parsed.errors)
        error = parsed.errors[0]
        self.assertEqual(error.code, "SYN001")
        self.assertEqual((error.line, error.col), (6, 1), "unexpected end of file")
        self.assertIn("unexpected end of file", error.message)

    def test_unsupported_language_keyword_is_reported(self):
        parsed = parse_rule_text("version 1\n\ndef evil():\n  pass\n")
        self.assertFalse(parsed.accepted)
        self.assertTrue(parsed.errors)
        self.assertTrue(all(error.line >= 1 for error in parsed.errors))

    def test_unterminated_string_literal_is_a_lexical_error(self):
        parsed = parse_rule_text(
            'version 1\n\nsource s {\n  description "oops\n  function input\n  returns\n}\n'
        )
        self.assertIn("LEX001", codes(parsed.diagnostics))
        error = next(d for d in parsed.diagnostics if d.code == "LEX001")
        self.assertEqual((error.line, error.col), (4, 15))
        self.assertIn("unterminated string literal", error.message)


class RuleValidationTests(unittest.TestCase):
    def check(self, body: str, code: str, expect_error: bool = True):
        rules, diagnostics, _parsed = parse_and_validate(HEADER + body, filename="<test rules>")
        codes_seen = codes(diagnostics)
        self.assertIn(code, codes_seen, f"expected {code}, got {codes_seen}")
        if expect_error:
            self.assertEqual(rules.stats()["sources"] + rules.stats()["sinks"], 0,
                             "a rule set with errors is never used")
        return rules, diagnostics

    def test_unsupported_version_is_rejected(self):
        rules, diagnostics = self.check("version 99\n", "RULE006")
        self.assertIn("supported: 1", next(d.message for d in diagnostics if d.code == "RULE006"))

    def test_missing_version_is_a_warning_and_the_rules_are_used(self):
        rules, diagnostics, _parsed = parse_and_validate(
            'source s {\n  function input\n  returns\n  contexts command\n}\n'
        )
        self.assertIn("RULE001", codes(diagnostics))
        self.assertEqual([d.severity for d in diagnostics if d.code == "RULE001"], ["warning"])
        self.assertIn("s", rules.sources)

    def test_duplicate_identifier_is_rejected(self):
        self.check(
            "source s {\n  function input\n  returns\n  contexts command\n}\n"
            "sink s {\n  function system\n  arguments 0\n  context command\n}\n",
            "RULE003",
        )

    def test_item_not_allowed_in_this_declaration(self):
        _rules, diagnostics = self.check(
            "source s {\n  function input\n  returns\n  contexts command\n  category \"x\"\n}\n",
            "RULE004",
        )
        detail = next(d.detail for d in diagnostics if d.code == "RULE004")
        self.assertIn("allowed items", detail)

    def test_item_specified_twice(self):
        self.check(
            "sink k {\n  function system\n  arguments 0\n  context command\n  context sql\n}\n",
            "RULE005",
        )

    def test_missing_required_item(self):
        self.check("sink k {\n  arguments 0\n  context command\n}\n", "RULE007")

    def test_source_cannot_read_an_argument_and_return_one(self):
        self.check(
            "source s {\n  function input\n  argument 0\n  returns\n  contexts command\n}\n",
            "RULE008",
        )

    def test_wildcard_context_is_only_allowed_for_sanitizers(self):
        self.check(
            "sink k {\n  function system\n  arguments 0\n  context *\n}\n", "RULE009"
        )

    def test_unknown_context_lists_the_known_ones(self):
        _rules, diagnostics = self.check(
            "source s {\n  function input\n  returns\n  contexts databse\n}\n", "RULE010"
        )
        detail = next(d.detail for d in diagnostics if d.code == "RULE010")
        for context in ("command", "sql", "path"):
            self.assertIn(context, detail)

    def test_unknown_severity(self):
        self.check("sink k {\n  function system\n  arguments 0\n  context command\n  severity HUGE\n}\n",
                   "RULE011")

    def test_negative_argument_index_is_rejected_with_a_position(self):
        _rules, diagnostics = self.check(
            "sanitizer z {\n  function f\n  argument -1\n  context command\n}\n", "RULE012"
        )
        error = next(d for d in diagnostics if d.code == "RULE012")
        self.assertEqual((error.line, error.col), (5, 3))
        # The list form is checked too: a negative index can never match.
        _rules, list_diagnostics = self.check(
            "sink k {\n  function system\n  arguments 0, -2\n  context command\n}\n", "RULE012"
        )
        self.assertIn("-2", next(d.message for d in list_diagnostics if d.code == "RULE012"))

    def test_flow_referencing_unknown_rules(self):
        body = (
            "flow f {\n  sources missing_source\n  sinks missing_sink\n"
            "  sanitizers missing_sanitizer\n}\n"
        )
        _rules, diagnostics = self.check(body, "RULE020")
        seen = codes(diagnostics)
        for code in ("RULE020", "RULE021", "RULE022"):
            self.assertIn(code, seen)
        for diagnostic in diagnostics:
            self.assertGreaterEqual(diagnostic.line, 1)
            self.assertGreaterEqual(diagnostic.col, 1)

    def test_flow_without_sources_or_sinks(self):
        _rules, diagnostics = self.check("flow f {\n  enabled true\n}\n", "RULE023")
        self.assertIn("RULE024", codes(diagnostics))

    def test_context_mismatch_between_source_and_sink_is_warned(self):
        body = (
            "source s {\n  function input\n  returns\n  contexts command\n}\n"
            "sink k {\n  function system\n  arguments 0\n  context sql\n}\n"
            "flow f {\n  sources s\n  sinks k\n}\n"
        )
        rules, diagnostics, _parsed = parse_and_validate(HEADER + body, filename="<test rules>")
        self.assertEqual(errors(diagnostics), [])
        self.assertIn("RULE026", codes(diagnostics))
        self.assertIn("f", rules.flows, "the rule file is still consistent and usable")
        warning = next(d for d in diagnostics if d.code == "RULE026")
        self.assertIn("can never be reported", warning.message)

    def test_two_rules_bound_to_the_same_function_are_ambiguous(self):
        body = (
            "sink one {\n  function system\n  arguments 0\n  context command\n}\n"
            "sink two {\n  function system\n  arguments 1\n  context command\n}\n"
        )
        self.check(body, "RULE025")

    def test_valid_rule_file_builds_every_rule_kind(self):
        body = (
            "source s {\n  description \"d\"\n  function input\n  returns\n"
            "  contexts command, sql\n  severity MEDIUM\n  tags \"a\", \"b\"\n}\n"
            "sink k {\n  description \"d\"\n  function system\n  arguments 0, 1\n"
            "  context command\n  category \"x\"\n  severity HIGH\n}\n"
            "sanitizer z {\n  function shell_escape\n  argument 0\n  context command\n}\n"
            "validator v {\n  function is_safe_command\n  argument 0\n  context command\n}\n"
            "flow f {\n  description \"d\"\n  severity HIGH\n  category \"x\"\n"
            "  sources s\n  sinks k\n  sanitizers z\n  enabled true\n}\n"
        )
        rules, diagnostics, _parsed = parse_and_validate(HEADER + body, filename="<test rules>")
        self.assertEqual(errors(diagnostics), [])
        self.assertEqual(warnings(diagnostics), [])
        self.assertEqual(rules.sources["s"].contexts, ("command", "sql"))
        self.assertEqual(rules.sources["s"].severity, "MEDIUM")
        self.assertEqual(rules.sources["s"].tags, ("a", "b"))
        self.assertEqual(rules.sinks["k"].arguments, (0, 1))
        self.assertEqual(rules.sanitizers["z"].kind, "sanitizer")
        self.assertEqual(rules.sanitizers["v"].kind, "validator")
        self.assertEqual(rules.flows["f"].sources, ("s",))
        self.assertTrue(rules.flows["f"].enabled)
        self.assertEqual(rules.source_rules("input")[0].id, "s")
        self.assertEqual(rules.sink_rules("system")[0].id, "k")
        self.assertEqual(len(rules.sanitizer_rules("shell_escape")), 1)
        self.assertEqual(rules.flow_for("k", "s").id, "f")
        self.assertIsNone(rules.flow_for("k", "other"))

    def test_disabled_flow_is_kept_but_not_selected(self):
        body = (
            "source s {\n  function input\n  returns\n  contexts command\n}\n"
            "sink k {\n  function system\n  arguments 0\n  context command\n}\n"
            "flow f {\n  sources s\n  sinks k\n  enabled false\n}\n"
        )
        rules, diagnostics, _parsed = parse_and_validate(HEADER + body, filename="<test rules>")
        self.assertEqual(errors(diagnostics), [])
        self.assertFalse(rules.flows["f"].enabled)
        self.assertIsNone(rules.flow_for("k", "s"), "a disabled flow is never selected")
        self.assertEqual(rules.stats()["enabled_flows"], 0)

    def test_rule_file_cannot_carry_executable_content(self):
        injections = {
            "call in a function name": 'source s {\n  function __import__("os")\n  returns\n  contexts command\n}\n',
            "assignment in a description": 'source s {\n  description "x" = 1\n  function input\n  returns\n  contexts command\n}\n',
            "python statement": "source s {\n  function input\n  returns\n  contexts command\n}\nprint('x')\n",
            "braces around code": "source s {\n  function input\n  returns\n  contexts command\n  __import__('os').system('echo')\n}\n",
        }
        for name, body in injections.items():
            with self.subTest(name=name):
                rules, diagnostics, _parsed = parse_and_validate(
                    HEADER + body, filename="<injection>"
                )
                self.assertTrue(errors(diagnostics), f"{name} must be rejected")
                self.assertEqual(rules.sources, {})
                self.assertEqual(rules.sinks, {})
                self.assertEqual(rules.flows, {})

    def test_rule_language_module_never_evaluates_its_input(self):
        # A structural check of the "rules are data" requirement: no dynamic
        # evaluation primitive appears anywhere in the rule pipeline.
        forbidden = {"eval", "exec", "compile", "__import__"}
        for module_name in ("rule_language.py", "model.py"):
            path = os.path.join(ROOT, "codetrace", "rules", module_name)
            with open(path, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            used = {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            self.assertEqual(used & forbidden, set(), f"{module_name} uses a dynamic primitive")


class BuiltinRuleTests(unittest.TestCase):
    def setUp(self):
        self.rules, self.diagnostics = load_builtin_rules()

    def test_builtin_file_loads_without_a_single_diagnostic(self):
        self.assertEqual(self.diagnostics, [])
        stats = self.rules.stats()
        self.assertEqual(stats["sources"], 5)
        self.assertEqual(stats["sinks"], 8)
        self.assertEqual(stats["sanitizers"], 5)
        self.assertEqual(stats["validators"], 2)
        self.assertEqual(stats["flows"], 4)
        self.assertEqual(stats["enabled_flows"], 4)
        self.assertEqual(stats["origin"], "built-in rules")
        self.assertTrue(self.rules.version_label().startswith("builtin-"))

    def test_builtin_rules_are_written_in_the_rule_language(self):
        with open(BUILTIN_PATH, "r", encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("#", text, "the built-in file is commented")
        reparsed, diagnostics, _parsed = parse_and_validate(
            text, filename="standard.ctrule", origin="built-in rules", builtin=True
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual(reparsed.version_label(), self.rules.version_label())
        self.assertTrue(all(rule.builtin for rule in reparsed.sources.values()))
        self.assertTrue(all(rule.builtin for rule in self.rules.sources.values()))

    def test_rule_set_serialisation(self):
        payload = self.rules.to_json()
        self.assertEqual(sorted(payload), ["rules", "stats", "version"])
        self.assertEqual(payload["stats"]["flows"], 4)
        ids = {rule["id"] for rule in payload["rules"]}
        self.assertIn("command_execution", ids)
        self.assertIn("path_traversal", ids)
        for rule in payload["rules"]:
            self.assertIn("kind", rule)
            self.assertIn("line", rule)
            self.assertGreaterEqual(rule["line"], 1)

    def test_merge_keeps_both_rule_sets_and_prefers_the_override(self):
        override = RuleSet(origin="override")
        custom, diagnostics, _parsed = parse_and_validate(
            HEADER
            + "sink command_system {\n  function system\n  arguments 0\n  context command\n"
              "  category \"command-injection\"\n  severity LOW\n}\n",
            filename="override.ctrule",
        )
        self.assertEqual(errors(diagnostics), [])
        merged = merge(self.rules, custom)
        self.assertEqual(merged.sinks["command_system"].severity, "LOW", "the later rule wins")
        self.assertEqual(len(merged.sources), len(self.rules.sources))
        self.assertIn("path_writefile", merged.sinks, "unrelated built-ins survive the merge")
        self.assertIn("built-in rules", merged.origin)
        self.assertEqual(override.origin, "override", "the dataclass is untouched by merge")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
