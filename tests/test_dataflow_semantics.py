"""Access collection and definite-assignment contracts (audit defects D1/D11).

Pins:
* writing one array element does not read the array base (false DFA001 and
  liveness kept alive across writes were the pre-fix behaviour);
* index expressions are still reads;
* a compound assignment ``a[i] += 1`` still reads its target;
* non-data-flow locations (a function used as a value, SEM014) never surface
  as the placeholder diagnostic ``variable '?'``;
* two-dimensional indexing is outside the subset and rejected cleanly.
"""

import unittest

from codetrace.analysis.pipeline import analyse_source
from codetrace.rules.rule_language import load_builtin_rules

BUILTIN_RULES, _ = load_builtin_rules()


def run(source):
    return analyse_source(source, filename="t.ctc", rules=BUILTIN_RULES)


def dfa001_messages(program):
    return [d.message for d in program.diagnostics if d.code == "DFA001"]


class TestArrayElementAccesses(unittest.TestCase):
    def test_element_write_is_not_a_base_read(self):
        # The corpus twin of this case is examples/safe/array_element_write.ctc.
        program = run("""int main() {
  int a[4];
  a[0] = 7;
  int b = a[0] + 1;
  a[1] = b;
  a[1] += 1;
  return a[1];
}""")
        self.assertEqual(dfa001_messages(program), [],
                         "writing a[i] defines the element; the base is never read first")
        self.assertTrue(program.analysis_complete)

    def test_index_expression_is_still_read(self):
        program = run('int main() { int a[4]; int i; a[0] = 1; int b = a[i]; return b; }')
        messages = dfa001_messages(program)
        self.assertTrue(any("'i'" in m for m in messages),
                        f"the index variable is read uninitialised: {messages}")

    def test_compound_assignment_still_reads_target(self):
        program = run('int main() { int a[2]; a[0] += 1; return a[0]; }')
        messages = dfa001_messages(program)
        self.assertTrue(any("'a'" in m for m in messages),
                        f"a[i] += 1 reads the previous value: {messages}")

    def test_two_dimensional_index_rejected_cleanly(self):
        # 2-D arrays are outside the documented subset: a clean syntax error,
        # no crash, no invented diagnostics.
        program = run('int main() { int m[2][2]; m[0][0] = 5; return m[0][0]; }')
        codes = {d.code for d in program.diagnostics}
        self.assertIn("SYN001", codes)
        self.assertFalse(program.parse.accepted)
        self.assertFalse(program.analysis_complete)


class TestNoPlaceholderDiagnostics(unittest.TestCase):
    def test_function_as_value_never_becomes_variable_question_mark(self):
        program = run('int main() { int x = main; return x; }')
        codes = [d.code for d in program.diagnostics]
        self.assertIn("SEM014", codes)
        self.assertNotIn("DFA001", codes)
        for diagnostic in program.diagnostics:
            self.assertNotIn("?", diagnostic.message,
                             "no fabricated placeholder name may reach the user")

    def test_genuine_use_before_init_still_reported(self):
        # The other side of the D11 fix: real cases must keep firing.
        program = run('int main() { int x; int y = x + 1; return y; }')
        messages = dfa001_messages(program)
        self.assertTrue(any("'x'" in m for m in messages), messages)


if __name__ == "__main__":
    unittest.main()
