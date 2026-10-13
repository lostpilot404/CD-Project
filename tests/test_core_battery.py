"""Hand-labelled taint battery (positive, negative and boundary cases).

Each case states the expected number of findings and the sink line that must
carry them, written from the program text before the analysis was run.
Three line-number labels (P4, P5, P8 in the first group; Q4, Q9 above) were
corrected once after the first run, after counting lines in the source: the
analysis was right and the labels were wrong.  Q13 is a documented over-
approximation and is pinned as such (see its test).
"""

from __future__ import annotations

import unittest

from tests.helpers import analyse  # noqa: E402

# (name, expected findings, expected sink line or None, source)
CASES = [
    ('P1 direct source->sink via variable', 1, 3, 'int main() {\n  string c = input();\n  system(c);\n  return 0;\n}'),
    ('P2 assignment chain a->b->c', 1, 5, 'int main() {\n  string a = input();\n  string b = a;\n  string c = b;\n  system(c);\n  return 0;\n}'),
    ('P3 propagation through concatenation expression', 1, 3, 'int main() {\n  string cmd = "ls " + input();\n  system(cmd);\n  return 0;\n}'),
    ('P4 branch merge: tainted on one path only', 1, 5, 'int main() {\n  int flag = input_int();\n  string c = "ls";\n  if (flag > 0) { c = input(); }\n  system(c);\n  return 0;\n}'),
    ('P5 loop-carried taint reaches sink in next iteration', 1, 4, 'int main() {\n  string c = "ls";\n  int i = 0;\n  while (i < 2) { system(c); c = input(); i = i + 1; }\n  return 0;\n}'),
    ('P6 different sink: SQL with environment source', 1, 3, 'int main() {\n  string q = readenv("QUERY");\n  sql_exec(q);\n  return 0;\n}'),
    ('P7 path sink fopen via argv', 1, 3, 'int main() {\n  string p = argv(1);\n  fopen(p, "r");\n  return 0;\n}'),
    ('N1 strong update: constant redefinition kills taint', 0, None, 'int main() {\n  string c = input();\n  c = "ls";\n  system(c);\n  return 0;\n}'),
    ('N2 independent variable is untainted', 0, None, 'int main() {\n  string u = input();\n  string safe = "ls";\n  system(safe);\n  return 0;\n}'),
    ('N3 source never reaches sink', 0, None, 'int main() {\n  string u = input();\n  system("ls");\n  return 0;\n}'),
    ('N4 comment and string decoys are not code', 0, None, 'int main() {\n  // system(input());  <- commented out\n  string s = "system(input())";\n  system("date");\n  return 0;\n}'),
    ('N5 configured sanitizer neutralises command taint', 0, None, 'int main() {\n  string c = shell_escape(input());\n  system(c);\n  return 0;\n}'),
    ('N6 sanitizer for a different context does not neutralise', 1, 4, 'int main() {\n  string c = input();\n  string d = sql_escape(c);\n  system(d);\n  return 0;\n}'),
    ('N7 parse_to_int destroys text for all contexts', 0, None, 'int main() {\n  string n = input();\n  int v = to_int(n);\n  system(v);\n  return 0;\n}'),
    ('N8 shadowed name: inner clean variable is the sink argument', 0, None, 'int main() {\n  string c = input();\n  {\n    string c = "ls";\n    system(c);\n  }\n  return 0;\n}'),
    ('N9 sink in a branch literally never taken', 0, None, 'int main() {\n  string c = input();\n  if (0) { system(c); }\n  return 0;\n}'),
    ('N10 tainted value overwritten on every path before sink', 0, None, 'int main() {\n  string c = input();\n  if (1 > 0) { c = "ls"; } else { c = "pwd"; }\n  system(c);\n  return 0;\n}'),
    ('P8 shadowed name: inner tainted variable is the sink argument', 1, 5, 'int main() {\n  string c = "ls";\n  {\n    string c = input();\n    system(c);\n  }\n  return 0;\n}'),
    ('P9 two sinks, only one tainted', 1, 5, 'int main() {\n  string safe = "ls";\n  string u = input();\n  system(safe);\n  system(u);\n  return 0;\n}'),
    ('Q1 sanitizer applied to a different variable does not clean c', 1, 4, 'int main() {\n  string c = input();\n  string d = shell_escape("x");\n  system(c);\n  return 0;\n}'),
    ('Q2 compound assignment += propagates taint', 1, 4, 'int main() {\n  string c = "ls ";\n  c += input();\n  system(c);\n  return 0;\n}'),
    ('Q3 sanitising helper function (interprocedural) cleans its return', 0, None, 'string clean(string s) {\n  return shell_escape(s);\n}\nint main() {\n  string c = clean(input());\n  system(c);\n  return 0;\n}'),
    ('Q4 sink argument is a direct expression containing source', 1, 2, 'int main() {\n  system("ls " + input());\n  return 0;\n}'),
    ('Q5 implicit flow via condition is NOT tracked (documented limitation)', 0, None, 'int main() {\n  string c = "ls";\n  if (input() == "x") { c = "pwd"; }\n  system(c);\n  return 0;\n}'),
    ('Q6 same name in another function does not leak taint', 0, None, 'int f() {\n  string c = input();\n  return 0;\n}\nint main() {\n  string c = "ls";\n  system(c);\n  return 0;\n}'),
    ('Q7 comment-contained sink and source ignored', 0, None, 'int main() {\n  /* system(input());\n     string c = input(); */\n  system("date");\n  return 0;\n}'),
    ('Q8 string literal containing a comment marker is not a comment', 1, 4, 'int main() {\n  string url = "http://x // not a comment";\n  string c = input();\n  system(c);\n  return 0;\n}'),
    ('Q9 tainted then clean-only on the other path: may-flow stays', 1, 5, 'int main() {\n  string c = shell_escape(input());\n  int k = input_int();\n  if (k > 0) { c = input(); }\n  system(c);\n  return 0;\n}'),
    ('Q10 taint enters through a parameter of a helper that runs the sink', 1, 2, 'int run(string cmd) {\n  system(cmd);\n  return 0;\n}\nint main() {\n  run(input());\n  return 0;\n}'),
    ('Q11 helper called only with a constant does not report', 0, None, 'int run(string cmd) {\n  system(cmd);\n  return 0;\n}\nint main() {\n  run("ls");\n  return 0;\n}'),
    ('Q12 array element taint (whole-array attribution, documented)', 1, 4, 'int main() {\n  string arr[2];\n  arr[0] = input();\n  system(arr[1]);\n  return 0;\n}'),
    ('Q13 loop may run zero times: documented over-approximation', 1, 5, 'int main() {\n  string c = input();\n  int i = 0;\n  while (i < 3) { c = "ls"; i = i + 1; }\n  system(c);\n  return 0;\n}'),
]


class HandLabelledTaintBatteryTests(unittest.TestCase):
    def test_every_case_matches_its_hand_label(self):
        failures = []
        for name, expected, sink_line, source in CASES:
            program = analyse(source)
            lines = [finding.sink.get("line") for finding in program.findings]
            if len(program.findings) != expected or (sink_line is not None and lines != [sink_line] * expected):
                failures.append(f"{name}: expected {expected} at line {sink_line}, got {lines}")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_positive_cases_are_all_present(self):
        positives = [case for case in CASES if case[1] > 0]
        self.assertGreaterEqual(len(positives), 10)
        for name, expected, sink_line, source in positives:
            with self.subTest(case=name):
                self.assertEqual(len(analyse(source).findings), expected)

    def test_negative_cases_report_nothing(self):
        negatives = [case for case in CASES if case[1] == 0]
        self.assertGreaterEqual(len(negatives), 10)
        for name, expected, sink_line, source in negatives:
            with self.subTest(case=name):
                self.assertEqual(analyse(source).findings, [])

    def test_each_finding_carries_source_and_sink_evidence(self):
        program = analyse(CASES[0][3])
        self.assertEqual(len(program.findings), 1)
        finding = program.findings[0]
        self.assertIsNotNone(finding.source.get("line"))
        self.assertIsNotNone(finding.sink.get("line"))
        self.assertTrue(finding.path, "the evidence path is not empty")
        self.assertTrue(program.analysis_complete)

    def test_documented_loop_over_approximation_is_pinned(self):
        # Q13 in the battery: c is tainted before a loop whose body always
        # overwrites it.  Real execution always runs the body (i = 0 < 3), so
        # the sink is safe, but the engine does not evaluate loop conditions and
        # keeps the zero-iteration path.  The finding must say so (approximate).
        source = next(case[3] for case in CASES if case[0].startswith("Q13"))
        program = analyse(source)
        self.assertEqual(program.findings[0].sink.get("line"), 5)
        self.assertEqual(len(program.findings), 1)
        self.assertEqual(program.findings[0].certainty, "approximate")

    def test_documented_implicit_flow_false_negative_is_pinned(self):
        # Q5: a value chosen by a branch on untrusted data is not tainted, because
        # taint follows data dependencies only (docs/LIMITATIONS.md, section 1.3).
        source = next(case[3] for case in CASES if case[0].startswith("Q5"))
        self.assertEqual(analyse(source).findings, [])


class CorpusDocumentTests(unittest.TestCase):
    """Regression: docs/LIMITATIONS.md quoted a stale corpus size (29, not 33)."""

    def test_documented_corpus_size_matches_the_examples_directory(self):
        import glob
        import os
        import re

        from tests.helpers import ROOT

        count = len(glob.glob(os.path.join(ROOT, "examples", "*", "*.ctc")))
        with open(os.path.join(ROOT, "docs", "LIMITATIONS.md"), encoding="utf-8") as handle:
            text = handle.read()
        quoted = re.findall(r"describe \*\*the (\d+)\s+hand-written", text)
        self.assertEqual(quoted, [str(count)], "the quoted corpus size must match examples/")


if __name__ == "__main__":
    unittest.main()
