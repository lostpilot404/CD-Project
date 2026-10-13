"""Parser tests: LR(1) construction, parsing, diagnostics and recovery."""

from __future__ import annotations

import unittest

from tests.helpers import codes, messages, parse  # noqa: E402

from codetrace.frontend.clr_parser import build_tables


def _item_key(item):
    """(production index, dot, lookahead) for the item representations in use."""
    if isinstance(item, tuple):
        return (item[0], item[1], item[2])
    return (item.production.index, item.dot, item.lookahead)


def _state_key(state):
    return sorted(_item_key(item) for item in state)
from codetrace.frontend.grammar import Grammar, Production
from codetrace.frontend.grammar_lang import build_language_grammar
from codetrace.frontend.pipeline import parser_tables


class GrammarConstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = parser_tables("lalr")
        cls.grammar = cls.tables.grammar

    def test_grammar_shape(self):
        self.assertEqual(self.grammar.start_symbol, "program")
        self.assertGreater(len(self.grammar.productions), 80)
        self.assertGreater(len(self.grammar.terminals), 40)
        self.assertIn("$end", self.grammar.terminals)
        for kind in ("KW_IF", "IDENT", "INT_LIT", "STRING_LIT", "SEMI", "LPAREN"):
            self.assertIn(kind, self.grammar.terminals)

    def test_terminals_and_nonterminals_are_disjoint(self):
        # A symbol that is defined by a production is a non-terminal; it must
        # never also be treated as a terminal, or FOLLOW sets and the ACTION
        # table would carry lookaheads no token can match.
        overlap = self.grammar.terminals & self.grammar.nonterminals
        self.assertEqual(overlap, set(), f"symbols classified twice: {sorted(overlap)}")
        for nonterminal, values in self.grammar.first.items():
            self.assertFalse(
                values & self.grammar.nonterminals,
                f"FIRST({nonterminal}) contains non-terminals: {sorted(values & self.grammar.nonterminals)}",
            )
        for nonterminal, values in self.grammar.follow.items():
            self.assertFalse(
                values & self.grammar.nonterminals,
                f"FOLLOW({nonterminal}) contains non-terminals: {sorted(values & self.grammar.nonterminals)}",
            )

    def test_action_table_is_keyed_by_token_kinds(self):
        for (_state, symbol) in self.tables.action:
            self.assertIn(symbol, self.grammar.terminals,
                          "every ACTION entry is indexed by a terminal")

    def test_nullable_and_first_sets(self):
        grammar = self.grammar
        # The start symbol derives a non-empty sentence, so FIRST(program) is not empty.
        first, _nullable = grammar.first_of_sequence(("program",))
        self.assertTrue(first)
        # Nullable symbols are those that derive the empty string.
        self.assertTrue(grammar.nullable, "the CT-C grammar has nullable non-terminals")
        for symbol in grammar.nonterminals:
            first_of_symbol, _ = grammar.first_of_sequence((symbol,))
            self.assertTrue(first_of_symbol or symbol in grammar.nullable,
                            f"FIRST({symbol}) is empty and {symbol} is not nullable")

    def test_item_sets_are_deduplicated(self):
        states = self.tables.automaton.states
        # Item sets are frozensets, so a repeated item cannot survive inside a
        # state; equality of the states themselves is what dedup must guarantee.
        self.assertEqual(len(states), len(set(states)), "two item sets are identical")
        for index, state in enumerate(states):
            keys = [_item_key(item) for item in state]
            self.assertEqual(len(keys), len(set(keys)), f"state {index} contains a duplicate item")
            self.assertTrue(state, f"state {index} is empty")

    def test_no_conflicts_in_the_shipped_modes(self):
        for mode in ("slr", "lalr", "canonical"):
            tables = parser_tables(mode)
            self.assertEqual(
                tables.conflicts, [],
                f"{mode}: " + "; ".join(c.describe(tables.grammar) for c in tables.conflicts),
            )

    def test_canonical_lr1_has_more_states_than_lalr(self):
        lalr = parser_tables("lalr")
        canonical = parser_tables("canonical")
        self.assertEqual(lalr.automaton.stats.lr1_states_before_merge, canonical.automaton.stats.states)
        self.assertEqual(lalr.automaton.stats.states, len(set(lalr.automaton.states)))
        self.assertLess(lalr.automaton.stats.states, canonical.automaton.stats.states)
        # LALR(1) merges canonical states with the same LR(0) core.
        self.assertEqual(lalr.automaton.stats.states, len(lalr.automaton.states))
        cores = {frozenset(_item_key(item)[:2] for item in state) for state in lalr.automaton.states}
        self.assertEqual(len(cores), lalr.automaton.stats.states, "LALR states do not share LR(0) cores")

    def test_action_goto_tables_are_consistent(self):
        state_count = len(self.tables.automaton.states)
        accepts = 0
        for (state, _terminal), entry in self.tables.action.items():
            self.assertIn(entry.kind, ("shift", "reduce", "accept", "error"))
            self.assertLess(state, state_count)
            if entry.kind == "accept":
                accepts += 1
            if entry.kind == "shift":
                self.assertLess(entry.value, state_count)
            if entry.kind == "reduce":
                self.assertLess(entry.value, len(self.grammar.productions))
        self.assertEqual(accepts, 1, "there must be exactly one accept action")
        for (state, nonterminal), target in self.tables.goto.items():
            self.assertIn(nonterminal, self.grammar.nonterminals)
            self.assertLess(target, state_count)

    def test_tables_are_deterministic(self):
        again = build_tables(build_language_grammar(), mode="lalr")
        self.assertEqual([_state_key(state) for state in again.automaton.states],
                         [_state_key(state) for state in self.tables.automaton.states])
        self.assertEqual(again.action, self.tables.action)
        self.assertEqual(again.goto, self.tables.goto)
        self.assertEqual(again.automaton.stats.transitions, self.tables.automaton.stats.transitions)
        self.assertEqual(again.automaton.stats.items_total, self.tables.automaton.stats.items_total)

    def test_deliberate_conflict_is_detected_not_hidden(self):
        """A classic ambiguous grammar must produce a reported conflict."""
        grammar = Grammar(start_symbol="E")
        grammar.add("E", ("E", "PLUS", "E"))
        grammar.add("E", ("ID",))
        grammar.declare_terminal("ID")
        grammar.declare_terminal("PLUS")
        grammar.finalize()
        tables = build_tables(grammar, mode="lalr")
        self.assertTrue(tables.conflicts, "an ambiguous grammar must report a conflict")
        kinds = {conflict.kind for conflict in tables.conflicts}
        self.assertTrue(kinds & {"shift-reduce", "shift/reduce"}, kinds)
        # The conflict is reported with the state, the terminal and both
        # candidate actions, which is what a grammar author needs to fix it.
        conflict = tables.conflicts[0]
        payload = conflict.to_json(grammar)
        self.assertIn("state", payload)
        self.assertEqual(payload["terminal"], "PLUS")
        self.assertTrue(payload["existing"].startswith(("shift", "reduce")))
        self.assertTrue(payload["incoming"].startswith(("shift", "reduce")))
        self.assertTrue(payload["reason"])
        # ... and the table's own summary reports it (nothing is hidden).
        self.assertTrue(tables.summary_json()["conflicts"])


class ParsingTests(unittest.TestCase):
    def assertAccepted(self, source):
        outcome = parse(source)
        self.assertEqual(codes(outcome.diagnostics), [], messages(outcome.diagnostics))
        self.assertTrue(outcome.accepted, messages(outcome.diagnostics))
        self.assertIsNotNone(outcome.tree)
        return outcome

    def test_minimal_program(self):
        outcome = self.assertAccepted("int f() { return 0; }\n")
        self.assertEqual(outcome.tree.kind, "SourceUnit")
        declaration = outcome.tree.decls[0]
        self.assertEqual(declaration.kind, "FunctionDecl")
        self.assertEqual(declaration.name, "f")

    def test_precedence_multiplication_before_addition(self):
        outcome = self.assertAccepted("int f() { return 1 + 2 * 3; }\n")
        expression = outcome.tree.decls[0].body.statements[0].value
        self.assertEqual(expression.kind, "BinaryOp")
        self.assertEqual(expression.op, "+")
        self.assertEqual(expression.right.kind, "BinaryOp")
        self.assertEqual(expression.right.op, "*")

    def test_precedence_comparison_before_logical_and(self):
        outcome = self.assertAccepted("int f() { if (1 < 2 && 3 > 4) { return 1; } return 0; }\n")
        condition = outcome.tree.decls[0].body.statements[0].cond
        self.assertEqual(condition.op, "&&")
        self.assertEqual(condition.left.op, "<")
        self.assertEqual(condition.right.op, ">")

    def test_left_associativity_of_subtraction(self):
        outcome = self.assertAccepted("int f() { return 1 - 2 - 3; }\n")
        expression = outcome.tree.decls[0].body.statements[0].value
        self.assertEqual(expression.op, "-")
        self.assertEqual(expression.left.kind, "BinaryOp")
        self.assertEqual(expression.left.op, "-")
        self.assertEqual(expression.right.kind, "IntLit")

    def test_else_binds_to_the_nearest_if(self):
        source = "int f() { if (1) { if (2) { return 1; } else { return 2; } } return 0; }\n"
        outcome = self.assertAccepted(source)
        outer = outcome.tree.decls[0].body.statements[0]
        inner = outer.then_branch.statements[0]
        self.assertIsNone(outer.else_branch)
        self.assertIsNotNone(inner.else_branch)

    def test_nested_blocks_and_loops(self):
        source = (
            "int f() {\n"
            "  int total = 0;\n"
            "  for (int i = 0; i < 3; i = i + 1) {\n"
            "    while (total < 10) {\n"
            "      total = total + i;\n"
            "    }\n"
            "  }\n"
            "  return total;\n"
            "}\n"
        )
        outcome = self.assertAccepted(source)
        body = outcome.tree.decls[0].body
        self.assertEqual([statement.kind for statement in body.statements],
                         ["VarDecl", "ForStmt", "ReturnStmt"])
        loop = body.statements[1]
        self.assertEqual(loop.body.statements[0].kind, "WhileStmt")

    def test_function_with_parameters_and_arrays(self):
        source = "int f(string name, int count) { int values[3]; values[0] = count; return count; }\n"
        outcome = self.assertAccepted(source)
        declaration = outcome.tree.decls[0]
        self.assertEqual([parameter.name for parameter in declaration.params], ["name", "count"])
        declarator = declaration.body.statements[0].declarators[0]
        self.assertEqual(declarator.name, "values")
        self.assertIsNotNone(declarator.array_size)

    def test_locations_are_attached_to_every_node(self):
        outcome = self.assertAccepted("int f() {\n  int a = 1;\n  return a;\n}\n")
        for node in outcome.tree.walk():
            self.assertGreaterEqual(node.line, 1, f"{node.kind} has no line")
            self.assertGreaterEqual(node.col, 1, f"{node.kind} has no column")
            self.assertLessEqual(node.span[0], node.span[1])

    def test_second_parse_reports_correct_locations(self):
        """Locations must not depend on cached parser state (regression)."""
        parse("int f() { return 1; }\n")
        outcome = parse("int g() {\n  return 2;\n}\n")
        self.assertEqual(outcome.tree.decls[0].line, 1)
        self.assertEqual(outcome.tree.decls[0].body.statements[0].line, 2)
        self.assertEqual(outcome.tree.decls[0].body.statements[0].col, 3)


class ParserDiagnosticTests(unittest.TestCase):
    def test_missing_semicolon_is_located(self):
        outcome = parse("int f() {\n  int a = 1\n  return a;\n}\n")
        diagnostics = [d for d in outcome.diagnostics if d.code == "SYN001"]
        self.assertTrue(diagnostics)
        self.assertEqual((diagnostics[0].line, diagnostics[0].col), (3, 3))
        self.assertIn("expected one of", diagnostics[0].detail)
        self.assertFalse(outcome.accepted)

    def test_broken_expression_is_reported_at_the_failing_token(self):
        outcome = parse("int f() {\n  int a = 1 + * 2;\n  return a;\n}\n")
        diagnostics = [d for d in outcome.diagnostics if d.code == "SYN001"]
        self.assertTrue(diagnostics)
        self.assertEqual((diagnostics[0].line, diagnostics[0].col), (2, 15))
        self.assertIn("*", diagnostics[0].message)

    def test_unclosed_brace_is_reported(self):
        outcome = parse("int f() {\n  return 0;\n")
        self.assertFalse(outcome.accepted)
        self.assertIn("SYN001", codes(outcome.diagnostics))

    def test_recovery_makes_progress_and_does_not_flood_errors(self):
        source = "int f() {\n  int a = 1\n  int b = 2\n  int c = 3\n  return a;\n}\n"
        outcome = parse(source)
        syntax_errors = [d for d in outcome.diagnostics if d.code.startswith("SYN")]
        self.assertGreaterEqual(len(syntax_errors), 1)
        self.assertLessEqual(len(syntax_errors), 6, messages(outcome.diagnostics))
        self.assertGreater(outcome.stats["errors_recovered"], 0)

    def test_unsupported_keyword_produces_syn100_and_skips_the_statement(self):
        outcome = parse("int f() {\n  switch (1) { }\n  return 0;\n}\n")
        self.assertIn("SYN100", codes(outcome.diagnostics))
        self.assertFalse(outcome.accepted)

    def test_error_limit_is_enforced(self):
        source = "int f() {\n" + "".join(f"  int a{i} = ;\n" for i in range(40)) + "}\n"
        outcome = parse(source)
        self.assertIn("SYN011", codes(outcome.diagnostics))

    def test_empty_input_parses_as_an_empty_translation_unit(self):
        outcome = parse("")
        # An empty file is a valid (if useless) translation unit; the missing
        # `main` is a semantic finding, not a syntax error.
        self.assertTrue(outcome.accepted)
        self.assertEqual(codes(outcome.diagnostics), [])

    def test_parser_statistics_are_recorded(self):
        outcome = parse("int f() { int a = 1; return a; }\n")
        for key in ("shifts", "reductions", "steps", "max_stack_depth", "token_count"):
            self.assertIn(key, outcome.stats)
        self.assertGreater(outcome.stats["shifts"], 5)
        self.assertGreater(outcome.stats["reductions"], 5)
        self.assertEqual(outcome.stats["parser_mode"], "lalr")


if __name__ == "__main__":
    unittest.main()
