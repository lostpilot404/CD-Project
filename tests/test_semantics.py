"""Semantic analysis tests: scopes, shadowing, types, symbols and diagnostics."""

from __future__ import annotations

import unittest

from tests.helpers import analyse, codes, messages  # noqa: E402


def symbol_map(program):
    return {symbol.name: symbol for symbol in program.semantic.symbols.symbols.values()}


class SymbolTableTests(unittest.TestCase):
    def test_variables_of_different_scopes_have_different_symbols(self):
        program = analyse(
            """
            int main() {
              int value = 1;
              if (value > 0) {
                int value = 2;
                print_int(value);
              }
              return value;
            }
            """
        )
        variables = [s for s in program.semantic.symbols.symbols.values() if s.name == "value"]
        self.assertEqual(len(variables), 2, "shadowing creates two distinct symbols")
        self.assertNotEqual(variables[0].id, variables[1].id)
        self.assertNotEqual(variables[0].scope_id, variables[1].scope_id)
        # The declaration inside the branch is reported as shadowing, not as a
        # duplicate declaration.
        self.assertIn("SEM018", codes(program.diagnostics))
        self.assertNotIn("SEM002", codes(program.diagnostics))

    def test_duplicate_declaration_in_one_scope_is_an_error(self):
        program = analyse("int main() { int a = 1; int a = 2; return a; }")
        self.assertIn("SEM002", codes(program.diagnostics))
        self.assertFalse(program.ok)

    def test_undeclared_identifier_is_an_error(self):
        program = analyse("int main() { return missing + 1; }")
        diagnostic = next(d for d in program.diagnostics if d.code == "SEM001")
        self.assertEqual(diagnostic.severity, "error")
        self.assertIn("missing", diagnostic.message)
        self.assertGreaterEqual(diagnostic.line, 1)

    def test_function_symbols_are_resolved(self):
        program = analyse("int helper() { return 1; }\nint main() { return helper(); }")
        symbols = symbol_map(program)
        self.assertEqual(symbols["helper"].kind, "function")
        self.assertEqual(symbols["main"].kind, "function")
        calls = {call.name: call for call in program.semantic.calls}
        self.assertEqual(calls["helper"].kind, "user")

    def test_unknown_external_is_reported_but_analysis_continues(self):
        program = analyse("int main() { return mystery(1); }")
        self.assertIn("SEM008", codes(program.diagnostics))
        call = next(c for c in program.semantic.calls if c.name == "mystery")
        self.assertEqual(call.kind, "unknown")

    def test_known_external_functions_are_looked_up(self):
        program = analyse("int main() { string s = input(); system(s); return 0; }")
        calls = {call.name: call for call in program.semantic.calls}
        self.assertEqual(calls["input"].kind, "external")
        self.assertEqual(calls["input"].external.category, "source")
        self.assertEqual(calls["system"].external.category, "sink")

    def test_arity_mismatch_is_reported(self):
        program = analyse(
            "int add(int a, int b) { return a + b; }\nint main() { return add(1); }"
        )
        self.assertIn("SEM009", codes(program.diagnostics))

    def test_argument_type_mismatch_is_reported(self):
        program = analyse(
            'int add(int a, int b) { return a + b; }\nint main() { return add("x", 2); }'
        )
        self.assertTrue({"SEM010", "SEM005"} & set(codes(program.diagnostics)), messages(program.diagnostics))

    def test_type_error_in_assignment_is_reported(self):
        program = analyse('int main() { int a = 1; a = "text"; return a; }')
        self.assertIn("SEM005", codes(program.diagnostics))

    def test_return_type_mismatch_is_reported(self):
        program = analyse('int helper() { return "text"; }\nint main() { return helper(); }')
        self.assertIn("SEM005", codes(program.diagnostics))

    def test_break_outside_loop_is_reported(self):
        program = analyse("int main() { break; return 0; }")
        self.assertIn("SEM012", codes(program.diagnostics))

    def test_return_outside_function_is_not_possible(self):
        # The grammar only allows `return` inside a function body; a stray one is
        # a syntax error, which is checked here to make the boundary explicit.
        from tests.helpers import parse

        outcome = parse("return 0;\n")
        self.assertFalse(outcome.accepted)

    def test_missing_main_is_reported_as_information(self):
        program = analyse("int helper() { return 1; }")
        diagnostic = next(d for d in program.diagnostics if d.code == "SEM020")
        self.assertEqual(diagnostic.severity, "info")

    def test_indirect_call_is_unsupported_not_guessed(self):
        program = analyse("int main() { int f = 1; return f(2); }")
        diagnostic = next(d for d in program.diagnostics if d.code == "SEM017")
        self.assertTrue(diagnostic.unsupported)
        self.assertIn("not a function", diagnostic.message)
        self.assertFalse(program.analysis_complete)

    def test_function_used_as_value_is_reported(self):
        program = analyse("int helper() { return 1; }\nint main() { int x = helper; return x; }")
        self.assertIn("SEM014", codes(program.diagnostics))

    def test_symbol_ids_are_stable_across_runs(self):
        source = "int main() { int a = 1; int b = a; return b; }"
        first = analyse(source).semantic.symbols
        second = analyse(source).semantic.symbols
        self.assertEqual(
            [(s.name, s.id, s.scope_id) for s in first.symbols.values()],
            [(s.name, s.id, s.scope_id) for s in second.symbols.values()],
        )

    def test_global_counters_are_shared_between_functions(self):
        program = analyse(
            """
            int counter = 0;
            void bump() { counter = counter + 1; }
            int main() { bump(); return counter; }
            """
        )
        self.assertEqual(codes(program.diagnostics), [], messages(program.diagnostics))
        symbols = symbol_map(program)
        self.assertTrue(symbols["counter"].is_global)

    def test_unsupported_construct_is_recorded_with_an_offset(self):
        program = analyse("int main() { switch (1) { } return 0; }")
        self.assertTrue(program.semantic.unsupported_offsets, "the skipped construct must be recorded")
        self.assertFalse(program.analysis_complete)
        self.assertTrue(any(d.unsupported for d in program.diagnostics))
        self.assertTrue(program.partial_reasons)


if __name__ == "__main__":
    unittest.main()
