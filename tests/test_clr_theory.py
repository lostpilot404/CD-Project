"""Parser-generator checks against textbook answers and an independent builder.

The existing parser tests check the shipped grammar and one ambiguous grammar.
These tests add two kinds of evidence that do not rely on the engine's own
code path:

* grammars whose FIRST/FOLLOW sets and LR(1)/LALR(1) state counts are given in
  the literature (Aho, Lam, Sethi, Ullman, *Compilers*, 2nd ed., sections 4.4-4.7);
* an independent, deliberately naive LR(0)/canonical LR(1) builder, written from
  the textbook definitions and sharing no code with ``codetrace.frontend``.
  Its state counts for the shipped CT-C grammar must equal the engine's.
"""

from __future__ import annotations

import unittest

from tests.helpers import ROOT  # noqa: F401  (puts the repository on sys.path)

from codetrace.frontend.clr_parser import build_tables
from codetrace.frontend.grammar import Grammar
from codetrace.frontend.grammar_lang import build_language_grammar


def make_grammar(start, productions, terminals):
    grammar = Grammar(start_symbol=start)
    for lhs, rhs in productions:
        grammar.add(lhs, tuple(rhs))
    for terminal in terminals:
        grammar.declare_terminal(terminal)
    return grammar.finalize()


def independent_state_counts(productions, start):
    """Return (canonical LR(1) states, LR(0) states, LALR states by core).

    Written from the textbook definitions with naive fixed points; it does not
    import anything from ``codetrace``.  Production 0 is the augmented start.
    """
    prods = [("S'", (start,))] + list(productions)
    nonterminals = {lhs for lhs, _ in prods}
    symbols = {s for _, rhs in prods for s in rhs}

    nullable, changed = set(), True
    while changed:
        changed = False
        for lhs, rhs in prods:
            if lhs not in nullable and all(s in nullable for s in rhs):
                nullable.add(lhs)
                changed = True
    first = {s: ({s} if s not in nonterminals else set()) for s in symbols | nonterminals}
    changed = True
    while changed:
        changed = False
        for lhs, rhs in prods:
            for s in rhs:
                before = len(first[lhs])
                first[lhs] |= first[s]
                if len(first[lhs]) != before:
                    changed = True
                if s not in nullable:
                    break

    def first_of(seq, lookahead):
        out = set()
        for s in seq:
            out |= first[s]
            if s not in nullable:
                return out
        return out | {lookahead}

    def closure1(items):
        items = set(items)
        work = list(items)
        while work:
            p, d, la = work.pop()
            rhs = prods[p][1]
            if d < len(rhs) and rhs[d] in nonterminals:
                for q, (lhs2, _) in enumerate(prods):
                    if lhs2 == rhs[d]:
                        for b in first_of(rhs[d + 1:], la):
                            item = (q, 0, b)
                            if item not in items:
                                items.add(item)
                                work.append(item)
        return frozenset(items)

    def closure0(kernel):
        items = set(kernel)
        work = list(items)
        while work:
            p, d = work.pop()
            rhs = prods[p][1]
            if d < len(rhs) and rhs[d] in nonterminals:
                for q, (lhs2, _) in enumerate(prods):
                    if lhs2 == rhs[d] and (q, 0) not in items:
                        items.add((q, 0))
                        work.append((q, 0))
        return frozenset(items)

    def canonical_collection():
        start_state = closure1({(0, 0, "$end")})
        states, index, work = [start_state], {start_state: 0}, [start_state]
        while work:
            items = work.pop()
            for x in sorted({prods[p][1][d] for p, d, _ in items if d < len(prods[p][1])}):
                moved = {(p, d + 1, la) for p, d, la in items if d < len(prods[p][1]) and prods[p][1][d] == x}
                if not moved:
                    continue
                target = closure1(moved)
                if target not in index:
                    index[target] = len(states)
                    states.append(target)
                    work.append(target)
        return states

    def lr0_collection():
        start_state = closure0({(0, 0)})
        states, index, work = [start_state], {start_state: 0}, [start_state]
        while work:
            kernel = work.pop()
            for x in sorted({prods[p][1][d] for p, d in kernel if d < len(prods[p][1])}):
                moved = {(p, d + 1) for p, d in kernel if d < len(prods[p][1]) and prods[p][1][d] == x}
                if not moved:
                    continue
                target = closure0(moved)
                if target not in index:
                    index[target] = len(states)
                    states.append(target)
                    work.append(target)
        return states

    canonical = canonical_collection()
    cores = {frozenset((p, d) for p, d, _ in state) for state in canonical}
    return len(canonical), len(lr0_collection()), len(cores)


class FirstFollowTextbookTests(unittest.TestCase):
    """The expression grammar of Aho et al., Example 4.28 (the LL(1)-style grammar)."""

    @classmethod
    def setUpClass(cls):
        cls.grammar = make_grammar(
            "E",
            [
                ("E", ["T", "Ep"]),
                ("Ep", ["PLUS", "T", "Ep"]),
                ("Ep", []),
                ("T", ["F", "Tp"]),
                ("Tp", ["STAR", "F", "Tp"]),
                ("Tp", []),
                ("F", ["LP", "E", "RP"]),
                ("F", ["ID"]),
            ],
            ["PLUS", "STAR", "LP", "RP", "ID"],
        )

    def test_nullable_symbols(self):
        # Ep and Tp derive the empty string; nothing else does.
        self.assertEqual(self.grammar.nullable, {"Ep", "Tp"})

    def test_first_sets(self):
        # The engine keeps epsilon out of FIRST and tracks nullability separately,
        # which is the textbook convention once FIRST is used with NULLABLE.
        expected = {
            "E": {"LP", "ID"},
            "Ep": {"PLUS"},
            "T": {"LP", "ID"},
            "Tp": {"STAR"},
            "F": {"LP", "ID"},
        }
        for symbol, values in expected.items():
            self.assertEqual(set(self.grammar.first[symbol]), values, f"FIRST({symbol})")

    def test_follow_sets(self):
        expected = {
            "E": {"$end", "RP"},
            "Ep": {"$end", "RP"},
            "T": {"PLUS", "$end", "RP"},
            "Tp": {"PLUS", "$end", "RP"},
            "F": {"STAR", "PLUS", "$end", "RP"},
        }
        for symbol, values in expected.items():
            self.assertEqual(set(self.grammar.follow[symbol]), values, f"FOLLOW({symbol})")

    def test_expression_grammar_is_conflict_free_and_matches_lr0_count(self):
        tables = build_tables(self.grammar, mode="lalr")
        self.assertEqual(tables.conflicts, [])
        # The LR(0) automaton of this grammar has 16 states (independent count below).
        self.assertEqual(len(tables.automaton.states), 16)
        canonical, lr0, lalr = independent_state_counts(
            [(p.lhs, p.rhs) for p in self.grammar.productions[1:]], "E"
        )
        self.assertEqual((lr0, lalr), (16, 16))
        self.assertEqual(canonical, 30)


class LRStateCountTests(unittest.TestCase):
    def test_dragon_grammar_s_to_cc_has_10_canonical_and_7_lalr_states(self):
        # S -> C C, C -> c C | d  (Aho et al., Figure 4.41 and Example 4.58).
        grammar = make_grammar(
            "S",
            [("S", ["C", "C"]), ("C", ["c", "C"]), ("C", ["d"])],
            ["c", "d"],
        )
        canonical = build_tables(grammar, mode="canonical")
        lalr = build_tables(grammar, mode="lalr")
        self.assertEqual(len(canonical.automaton.states), 10)
        self.assertEqual(len(lalr.automaton.states), 7)
        self.assertEqual(canonical.conflicts, [])
        self.assertEqual(lalr.conflicts, [])
        self.assertEqual(independent_state_counts([("S", ("C", "C")), ("C", ("c", "C")), ("C", ("d",))], "S")[:3],
                         (10, 7, 7))

    def test_lr1_grammar_that_is_not_lalr1_is_separated_by_the_table_builder(self):
        # S -> aAd | bBd | aBe | bAe, A -> c, B -> c (Aho et al., Example 4.61).
        # It is LR(1), so the canonical table has no conflicts; merging states
        # with the same core (LALR) creates reduce/reduce conflicts on d and e.
        grammar = make_grammar(
            "S",
            [
                ("S", ["a", "A", "d"]),
                ("S", ["b", "B", "d"]),
                ("S", ["a", "B", "e"]),
                ("S", ["b", "A", "e"]),
                ("A", ["c"]),
                ("B", ["c"]),
            ],
            ["a", "b", "c", "d", "e"],
        )
        canonical = build_tables(grammar, mode="canonical")
        lalr = build_tables(grammar, mode="lalr")
        self.assertEqual(canonical.conflicts, [])
        self.assertEqual(
            sorted((c.kind, c.terminal) for c in lalr.conflicts),
            [("reduce/reduce", "d"), ("reduce/reduce", "e")],
        )
        for conflict in lalr.conflicts:
            self.assertTrue(conflict.reason)

    def test_ambiguous_expression_grammar_reports_shift_reduce_conflicts(self):
        grammar = make_grammar(
            "E",
            [("E", ["E", "PLUS", "E"]), ("E", ["E", "STAR", "E"]), ("E", ["ID"])],
            ["PLUS", "STAR", "ID"],
        )
        tables = build_tables(grammar, mode="canonical")
        self.assertTrue(tables.conflicts)
        self.assertEqual({c.kind for c in tables.conflicts}, {"shift/reduce"})


class ShippedGrammarCrossCheckTests(unittest.TestCase):
    """The CT-C grammar built by two independent constructions must agree."""

    def test_ct_c_state_counts_match_the_independent_builder(self):
        grammar = build_language_grammar()
        productions = [(p.lhs, tuple(p.rhs)) for p in grammar.productions[1:]]
        canonical, lr0, lalr = independent_state_counts(productions, grammar.start_symbol)
        self.assertEqual(canonical, 656, "canonical LR(1) states (documented value)")
        self.assertEqual(lr0, 167)
        self.assertEqual(lalr, 167, "LALR states equal the LR(0) cores")

        engine_canonical = build_tables(grammar, mode="canonical")
        engine_lalr = build_tables(grammar, mode="lalr")
        self.assertEqual(len(engine_canonical.automaton.states), canonical)
        self.assertEqual(len(engine_lalr.automaton.states), lalr)
        self.assertEqual(engine_canonical.conflicts, [])
        self.assertEqual(engine_lalr.conflicts, [])


class SyntaxDiagnosticRegressionTests(unittest.TestCase):
    """Regression: a missing ';' reported 'the parser expected one of: nothing'.

    The expected-token list counted shift actions only, but the state reached
    before the offending token only reduces.  Reductions on the lookahead are
    expected tokens too, so the list must name real terminals.
    """

    def test_missing_semicolon_names_expected_tokens(self):
        from tests.helpers import parse

        source = "int main() {\n  string name = input()\n  system(name);\n  return 0;\n}\n"
        outcome = parse(source)
        errors = [d for d in outcome.diagnostics if d.code == "SYN001"]
        self.assertTrue(errors, "a missing semicolon must be a syntax error")
        for diagnostic in errors:
            self.assertNotIn("nothing", diagnostic.detail)
            self.assertIn("expected one of:", diagnostic.detail)
            self.assertGreater(diagnostic.line, 0)
            self.assertGreater(diagnostic.col, 0)


if __name__ == "__main__":
    unittest.main()
