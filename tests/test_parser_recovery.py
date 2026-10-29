"""Parser error-recovery contracts (audit defects D2/D12 and the documented
for-header limitation — docs/COMPILER_THEORY.md §8, docs/ALGORITHMS.md §7).

The recovery design under test:

1. report SYN001 with a separators-first expected list (≤6 names, "+N more");
2. skip the statement for unsupported keywords / invalid tokens; stop at EOF;
3. statement-level resync at a ``;`` (relative bracket depth 0) or ``}``
   (depth < 0), accepted only when a simulated reduce/GOTO chain from the
   (possibly bracket-aware-popped) stack ends in SHIFT/ACCEPT (``_consumes``);
4. viable-prefix pop, then token discard; every step makes progress;
5. hard caps: ``max_errors`` = 25 (SYN011) and a table-step budget (SYN010).
"""

import unittest

from codetrace.analysis.pipeline import analyse_source, parse_source
from codetrace.rules.rule_language import load_builtin_rules

BUILTIN_RULES, _ = load_builtin_rules()


def codes(parse_outcome):
    return [d.code for d in parse_outcome.diagnostics]


class TestSingleFaultSingleError(unittest.TestCase):
    """One statement-level fault must produce exactly one SYN001 and the
    parse must continue usefully after it (the pre-fix parser cascaded)."""

    def test_missing_semicolon_between_statements(self):
        source = 'int main() { string name = input() system(name); return 0; }'
        outcome = parse_source(source, filename="t.ctc")
        syn = [d for d in outcome.diagnostics if d.code == "SYN001"]
        self.assertEqual(len(syn), 1, f"expected one SYN001, got {codes(outcome)}")
        self.assertFalse(outcome.accepted)
        # The error sits on the offending identifier, not somewhere later.
        self.assertIn("system", syn[0].message)
        self.assertEqual(syn[0].col, source.index("system(") + 1)

    def test_invalid_declaration_recovers_and_rest_still_parses(self):
        # The pre-fix behaviour either cascaded or abandoned the rest of the
        # function; one fault at the ';' must leave 'int b = 2; return b;'
        # parsed without further syntax errors.
        outcome = parse_source('int main() { int a = ; int b = 2; return b; }', filename="t.ctc")
        syn = [d for d in outcome.diagnostics if d.code == "SYN001"]
        self.assertEqual(len(syn), 1)
        self.assertIn("unexpected ;", syn[0].message)

    def test_independent_faults_each_report_once(self):
        source = 'int main() { int a = ; int b = ; int c = ; return 0; }'
        outcome = parse_source(source, filename="t.ctc")
        syn = [d for d in outcome.diagnostics if d.code == "SYN001"]
        self.assertEqual(len(syn), 3)
        # Each error sits on one of the three broken declarations' ';'; the
        # fourth ';' (after 'return 0') parses normally and reports nothing.
        first_three_semis = [i + 1 for i, ch in enumerate(source) if ch == ";"][:3]
        self.assertEqual([d.col for d in syn], first_three_semis)


class TestExpectedTokenList(unittest.TestCase):
    """The expected-token detail is separators-first, bounded, honest."""

    SEPARATORS_FIRST = (";", ")", "]", ",", "&&", "=", "end of file")
    PREFIX = "the parser expected one of: "

    def names_of(self, detail):
        self.assertTrue(detail.startswith(self.PREFIX), detail)
        body = detail[len(self.PREFIX):]
        return body.split(" (+")[0].split(", "), body

    def test_format_and_bound(self):
        outcome = parse_source('int main() { string name = input() system(name); }', filename="t.ctc")
        syn = [d for d in outcome.diagnostics if d.code == "SYN001"]
        self.assertEqual(len(syn), 1)
        names, body = self.names_of(syn[0].detail)
        # A completed-expression state has ~27 viable terminals: the tail must
        # be disclosed, not silently dropped (the pre-fix alphabetical first
        # six hid the ';' that was actually wanted).
        self.assertRegex(body, r" \(\+\d+ more\)$")
        extra = int(body.rsplit("(+", 1)[1].split(" ")[0])
        self.assertGreater(extra, 0)
        self.assertEqual(len(names), 6, "exactly six names are shown before the tail")
        # Separators first.
        self.assertIn(names[0], self.SEPARATORS_FIRST)

    def test_format_is_consistent_across_states(self):
        # Every SYN001 detail is either the full short list (no tail) or
        # exactly six names plus an honest "(+N more)" tail — never a
        # truncated list without the tail.
        samples = (
            'int main() { int a = ; return 0; }',
            'int main() { string name = input() system(name); }',
            'int main() { int a = 2 + ; return 0; }',
            'int main() { if (x) { return 0; }',
            'int main() { for (int i = 0 i < 3; i = i + 1) { } return 0; }',
        )
        seen = 0
        for source in samples:
            for d in parse_source(source, filename="t.ctc").diagnostics:
                if d.code != "SYN001" or not d.detail:
                    continue
                if not d.detail.startswith(self.PREFIX):
                    # The end-of-file diagnostic has its own honest wording.
                    self.assertEqual(d.detail,
                                     "the input ended while the parser expected more tokens")
                    self.assertIn("end of file", d.message)
                    continue
                seen += 1
                names, body = self.names_of(d.detail)
                if " more)" in body:
                    self.assertEqual(len(names), 6, d.detail)
                    self.assertGreater(int(body.rsplit("(+", 1)[1].split(" ")[0]), 0)
                else:
                    self.assertLessEqual(len(names), 6, d.detail)
        self.assertGreaterEqual(seen, 4)


class TestForHeaderLimitation(unittest.TestCase):
    """The documented for-header limitation: one fault inside the header may
    emit several diagnostics, but the contract stays useful and bounded.  The
    total cascade count is deliberately NOT pinned (docs call it a limitation,
    not a promise); what is pinned: the first error's position, rejection,
    partial status, boundedness, termination and clean valid loops."""

    FAULTY = 'int main() { for (int i = 0 i < 3; i = i + 1) { print(i); } return 0; }'

    def test_first_diagnostic_is_the_fault(self):
        outcome = parse_source(self.FAULTY, filename="t.ctc")
        syn = [d for d in outcome.diagnostics if d.code == "SYN001"]
        self.assertGreater(len(syn), 1, "this input is documented to cascade")
        fault_col = self.FAULTY.index("0 i < 3") + 3  # the 'i' where the ';' is missing
        self.assertEqual(syn[0].col, fault_col)
        self.assertIn("identifier 'i'", syn[0].message)

    def test_rejected_partial_bounded_and_terminating(self):
        outcome = parse_source(self.FAULTY, filename="t.ctc")
        self.assertFalse(outcome.accepted)
        syn = [d for d in outcome.diagnostics if d.code == "SYN001"]
        self.assertLessEqual(len(syn), 25)
        self.assertNotIn("SYN010", codes(outcome))  # within the step budget
        program = analyse_source(self.FAULTY, filename="t.ctc", rules=BUILTIN_RULES)
        self.assertFalse(program.analysis_complete)
        self.assertTrue(any("syntax" in r.lower() for r in program.partial_reasons))

    def test_single_missing_separator_variants_rejected_at_fault(self):
        for source, fault in (
            ('int main() { for (int i = 0 i < 3; i = i + 1) { } return 0; }', "0 i"),
            ('int main() { for (int i = 0; i < 3 i = i + 1) { } return 0; }', "3 i"),
        ):
            outcome = parse_source(source, filename="t.ctc")
            syn = [d for d in outcome.diagnostics if d.code == "SYN001"]
            self.assertFalse(outcome.accepted)
            self.assertGreaterEqual(len(syn), 1)
            self.assertEqual(syn[0].col, source.index(fault) + len(fault))

    def test_valid_for_loop_is_untouched_by_recovery(self):
        # The recovery rework must not disturb valid input, including loops
        # and deep nesting (the old 'reject anything bracket-entered' idea
        # did exactly that and was abandoned).
        for source in (
            'int main() { for (int i = 0; i < 3; i = i + 1) { print(i); } return 0; }',
            'int main() { int s = 0; for (int i = 0; i < 10; i = i + 1) { s += i; } return s; }',
        ):
            outcome = parse_source(source, filename="t.ctc")
            self.assertTrue(outcome.accepted, codes(outcome))
            self.assertEqual([c for c in codes(outcome) if c.startswith("SYN")], [])

    def test_deep_valid_nesting_accepted(self):
        depth = 300
        source = "int main() { int x = 0;\n" + "if (x >= 0) {\n" * depth + "x = 1;\n" + "}\n" * depth + "return x; }"
        outcome = parse_source(source, filename="t.ctc")
        self.assertTrue(outcome.accepted, codes(outcome)[:5])
        self.assertEqual([c for c in codes(outcome) if c.startswith("SYN")], [])


class TestCapsAndProgress(unittest.TestCase):
    """The caps are real and the parse always terminates with progress."""

    def test_error_cap_reports_syn011(self):
        source = "int main() {\n" + "int v = ;\n" * 30 + "return 0;\n}"
        outcome = parse_source(source, filename="t.ctc")
        syn001 = [d for d in outcome.diagnostics if d.code == "SYN001"]
        self.assertEqual(len(syn001), 25)
        self.assertIn("SYN011", codes(outcome))
        self.assertFalse(outcome.accepted)

    def test_unterminated_string_reports_and_rejects(self):
        outcome = parse_source('int main() { string s = "abc; return 0; }', filename="t.ctc")
        self.assertIn("LEX001", codes(outcome))
        self.assertIn("SYN001", codes(outcome))
        self.assertFalse(outcome.accepted)


class TestLexerErrorPartial(unittest.TestCase):
    """D12: an error-severity lexer diagnostic marks the run partial — the
    token stream the parser saw is not exactly what the file says."""

    def test_multichar_literal_marks_partial(self):
        program = analyse_source("int main() { char c = 'ab'; return 0; }",
                                 filename="t.ctc", rules=BUILTIN_RULES)
        self.assertIn("LEX007", [d.code for d in program.diagnostics])
        self.assertFalse(program.analysis_complete)
        self.assertTrue(any("lexer" in r for r in program.partial_reasons),
                        program.partial_reasons)

    def test_semantic_error_does_not_claim_lexer_repair(self):
        program = analyse_source("int main() { int x = y; return 0; }",
                                 filename="t.ctc", rules=BUILTIN_RULES)
        self.assertFalse(program.analysis_complete)
        self.assertFalse(any("lexer" in r for r in program.partial_reasons),
                         program.partial_reasons)


if __name__ == "__main__":
    unittest.main()
