"""Regression tests for compiler, HTTP API and interface defects.

Every test here reproduces a failure first observed against the running
application (browser or HTTP). The tests are written against the documented
behaviour -- ``docs/LANGUAGE.md`` §1/§4, ``docs/API.md`` §1/§4/§7 and
``docs/USER_GUIDE.md`` §6 -- not against the implementation's previous output.

The data-flow tests at the end are *independent reference cases*: they solve the
same problems with a second, deliberately small fixpoint over the GEN/KILL (or
USE/DEF) sets the engine reports, and compare the two solutions.
"""

from __future__ import annotations

import os
import pathlib
import re
import unittest
from urllib.parse import quote

from tests.helpers import analyse, analyse_example, codes, tokenize  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ----------------------------------------------------------------------
# docs/LANGUAGE.md §1: operators outside the subset are LEX102
# ----------------------------------------------------------------------
class LexerSubsetTests(unittest.TestCase):
    def test_arrow_is_reported_as_an_unsupported_operator(self):
        """§1 lists ``->`` as LEX102; it used to be tokenised silently and only
        failed later as a generic syntax error, so it was never counted in
        ``summary.unsupported_constructs``."""
        result = tokenize("int main() { p -> value; return 0; }\n")
        lex102 = [d for d in result.diagnostics if d.code == "LEX102"]
        self.assertTrue(lex102, [d.code for d in result.diagnostics])
        self.assertEqual(lex102[0].col, 16)
        self.assertTrue(getattr(lex102[0], "unsupported", False))
        arrow = [t for t in result.tokens if t.text == "->"]
        self.assertEqual([t.kind for t in arrow], ["INVALID"])

    def test_address_of_is_reported_as_an_unsupported_operator(self):
        """§1 lists ``&`` as LEX102 while ``&&`` stays a valid operator."""
        result = tokenize("int main() { int a = 1; int b = &a; return b; }\n")
        lex102 = [d for d in result.diagnostics if d.code == "LEX102"]
        self.assertTrue(lex102, [d.code for d in result.diagnostics])
        self.assertTrue(getattr(lex102[0], "unsupported", False))
        self.assertEqual([t.text for t in result.tokens if t.text == "&"], ["&"])
        self.assertEqual([t.kind for t in result.tokens if t.text == "&"], ["INVALID"])

    def test_logical_and_is_still_a_single_token(self):
        """The ``&`` change must not split ``&&``."""
        result = tokenize("int main() { bool a = true; bool b = a && a; return 0; }\n")
        self.assertEqual([t.kind for t in result.tokens if t.text == "&&"], ["ANDAND"])
        self.assertEqual([d.code for d in result.diagnostics if d.code == "LEX102"], [])

    def test_non_ascii_identifier_is_outside_the_alphabet(self):
        """§1 defines identifiers as ``[A-Za-z_][A-Za-z0-9_]*``; ``ü`` used to be
        accepted as an identifier because the lexer used ``str.isalpha()``."""
        result = tokenize("int ü = 1;\n")
        self.assertIn("LEX008", codes(result.diagnostics))
        self.assertEqual([t.kind for t in result.tokens if t.text == "ü"], ["INVALID"])

    def test_non_ascii_digit_is_outside_the_alphabet(self):
        result = tokenize("int main() { int a = 1; return ٠; }\n")
        self.assertIn("LEX008", codes(result.diagnostics))

    def test_hash_still_reports_a_preprocessor_directive_and_emits_eof(self):
        """A ``#`` line is LEX101 and must not truncate the token stream."""
        result = tokenize("a #\n")
        self.assertIn("LEX101", codes(result.diagnostics))
        self.assertEqual(result.tokens[-1].kind, "EOF")


# ----------------------------------------------------------------------
# docs/LANGUAGE.md §4: unsupported constructs are counted and reported
# ----------------------------------------------------------------------
class UnsupportedConstructTests(unittest.TestCase):
    def test_pointer_declarator_is_counted_as_unsupported(self):
        """``int *p;`` is documented as an unsupported construct that is counted
        in ``summary.unsupported_constructs`` and listed in the report; it used
        to be a bare SYN001 with a count of 0."""
        program = analyse("int main() {\n  int *pointer = 0;\n  return 0;\n}\n", "pointer.ctc")
        syntax = [d for d in program.diagnostics if d.code == "SYN001"]
        self.assertTrue(syntax, [d.code for d in program.diagnostics])
        self.assertTrue(getattr(syntax[0], "unsupported", False))
        self.assertEqual((syntax[0].line, syntax[0].col), (2, 7))
        self.assertGreaterEqual(len(program.semantic.unsupported_offsets), 1)

    def test_pointer_example_reports_one_unsupported_construct(self):
        program = analyse_example("unsupported", "pointer_type.ctc")
        self.assertEqual(len(set(program.semantic.unsupported_offsets)), 1)
        self.assertFalse(program.parse.accepted)

    def test_a_broken_expression_is_still_a_plain_syntax_error(self):
        """``1 + * 2`` is a typo, not a pointer declaration: it must stay SYN001
        without being relabelled an unsupported construct."""
        program = analyse("int f() {\n  int a = 1 + * 2;\n  return a;\n}\n", "broken.ctc")
        syntax = [d for d in program.diagnostics if d.code == "SYN001"]
        self.assertTrue(syntax)
        self.assertFalse(getattr(syntax[0], "unsupported", False))


# ----------------------------------------------------------------------
# Slicing: a finding's slice describes a finding, not a line
# ----------------------------------------------------------------------
class SliceCriterionTests(unittest.TestCase):
    def test_security_slice_criterion_carries_its_location(self):
        """The interface printed ``line undefined: …`` because the security
        slice's criterion had no ``line`` field."""
        program = analyse_example("vulnerable", "command_injection.ctc")
        finding = program.findings[0]
        payload = program.slicing.for_finding(finding).to_json()
        criterion = payload["criterion"]
        self.assertEqual(criterion["finding_id"], finding.id)
        self.assertIn("line", criterion)
        self.assertIn("col", criterion)
        self.assertIn("function", criterion)
        self.assertGreater(criterion["line"], 0)
        self.assertEqual(criterion["line"], finding.sink["line"])
        self.assertEqual(criterion["text"], finding.sink["statement_text"])

    def test_statement_slice_criterion_still_has_its_line(self):
        program = analyse("int main() {\n  int a = 1;\n  return a;\n}\n", "plain.ctc")
        payload = program.slicing.backward(1).to_json()
        self.assertEqual((payload["criterion"]["sid"], payload["criterion"]["line"]), (1, 3))


# ----------------------------------------------------------------------
# docs/API.md §4: per-block IN/OUT are part of the data-flow payload
# ----------------------------------------------------------------------
class DataFlowPayloadTests(unittest.TestCase):
    PROGRAM = (
        "int main() {\n"
        "  int a = 1;\n"
        "  int b = 2;\n"
        "  while (a < 3) {\n"
        "    b = a + b;\n"
        "    a = a + 1;\n"
        "  }\n"
        "  return b;\n"
        "}\n"
    )

    def _payload(self, analysis: str, name: str = "main") -> dict:
        program = analyse(self.PROGRAM, "df.ctc")
        analyses = program.analyses[name]
        problem, result = {
            "reaching": (analyses.reaching, analyses.reaching_result),
            "liveness": (analyses.live, analyses.live_result),
            "definite": (analyses.definite, analyses.definite_result),
        }[analysis]
        return problem.to_json(result)

    def test_every_block_carries_its_in_and_out_sets(self):
        for analysis in ("reaching", "liveness", "definite"):
            payload = self._payload(analysis)
            self.assertTrue(payload["blocks"])
            for block in payload["blocks"]:
                self.assertIn("in", block, analysis)
                self.assertIn("out", block, analysis)
                self.assertEqual(len(block["in"]), block["in_size"], (analysis, block))
                self.assertEqual(len(block["out"]), block["out_size"], (analysis, block))

    def test_the_ui_never_sees_an_empty_set_beside_a_non_zero_size(self):
        """The data-flow table renders ``∅`` when the set is missing, which read
        as ``|IN| = 1, IN = ∅``."""
        payload = self._payload("reaching")
        for block in payload["blocks"]:
            if block["in_size"]:
                self.assertTrue(block["in"], block)
            if block["out_size"]:
                self.assertTrue(block["out"], block)


# ----------------------------------------------------------------------
# Independent data-flow reference cases
# ----------------------------------------------------------------------
class ReachingDefinitionsReferenceTests(unittest.TestCase):
    """§13 fixed point, re-solved here from the reported GEN/KILL sets."""

    PROGRAM = DataFlowPayloadTests.PROGRAM

    def _solution(self):
        program = analyse(self.PROGRAM, "df.ctc")
        analyses = program.analyses["main"]
        payload = analyses.reaching.to_json(analyses.reaching_result)
        cfg = program.cfgs["main"]

        order = [d["id"] for d in payload["definitions"]]
        index = {f"d{i}": position for position, i in enumerate(order)} if order else {}
        if not index:                                    # no definitions at all
            index = {atom: position for position, atom in
                     enumerate(sorted({a for v in payload["gen"].values() for a in v}))}
        gen = {b: sum(1 << index[a] for a in atoms) for b, atoms in payload["gen"].items()}
        kill = {b: sum(1 << index[a] for a in atoms) for b, atoms in payload["kill"].items()}
        preds = {b.id: list(b.predecessors) for b in cfg.blocks.values()}
        entry = cfg.entry

        in_values = {b: 0 for b in preds}
        out_values = {b: 0 for b in preds}
        changed, iterations = True, 0
        while changed:
            changed = False
            iterations += 1
            self.assertLess(iterations, 50, "the reference fixpoint must converge")
            for block in sorted(preds):
                inside = 0 if block == entry else 0
                if block != entry:
                    for predecessor in preds[block]:
                        inside |= out_values.get(predecessor, 0)
                outside = gen.get(block, 0) | (inside & ~kill.get(block, 0))
                if (inside, outside) != (in_values[block], out_values[block]):
                    in_values[block], out_values[block] = inside, outside
                    changed = True
        return payload, index, in_values, out_values

    def test_engine_solution_equals_an_independent_fixpoint(self):
        payload, index, in_values, out_values = self._solution()
        self.assertTrue(payload["blocks"])
        for block in payload["blocks"]:
            block_id = block["block"]
            self.assertEqual(
                set(block["in"]),
                {a for a, mask in index.items() if in_values[block_id] & (1 << mask)},
                block_id,
            )
            self.assertEqual(
                set(block["out"]),
                {a for a, mask in index.items() if out_values[block_id] & (1 << mask)},
                block_id,
            )

    def test_killed_definition_is_removed_from_the_kill_set(self):
        payload, _index, _in_values, _out_values = self._solution()
        loop_body = max(payload["blocks"], key=lambda b: len(payload["gen"][b["block"]]))
        self.assertTrue(payload["kill"][loop_body["block"]], "the loop body must kill an earlier definition")
        for atom in payload["kill"][loop_body["block"]]:
            self.assertNotIn(atom, loop_body["out"])

    def test_convergence_is_reported(self):
        program = analyse(self.PROGRAM, "df.ctc")
        result = program.analyses["main"].reaching_result
        self.assertTrue(result.converged)
        self.assertGreaterEqual(result.iterations, 1)
        self.assertGreater(result.steps, 0)


class LivenessReferenceTests(unittest.TestCase):
    """§14 backward fixed point, re-solved from the reported USE/DEF sets."""

    PROGRAM = DataFlowPayloadTests.PROGRAM

    def test_engine_solution_equals_an_independent_fixpoint(self):
        program = analyse(self.PROGRAM, "df.ctc")
        analyses = program.analyses["main"]
        payload = analyses.live.to_json(analyses.live_result)
        cfg = program.cfgs["main"]

        atoms = sorted(
            {a for table in (payload["use"], payload["def"]) for values in table.values() for a in values},
            key=lambda a: (int(a.split(":")[0][1:]), a),
        )
        index = {a: position for position, a in enumerate(atoms)}
        use = {b: sum(1 << index[a] for a in values) for b, values in payload["use"].items()}
        defs = {b: sum(1 << index[a] for a in values) for b, values in payload["def"].items()}
        succs = {b.id: [e.dst for e in b.successors] for b in cfg.blocks.values()}
        exit_block = cfg.exit

        in_values = {b: 0 for b in succs}
        out_values = {b: 0 for b in succs}
        changed, iterations = True, 0
        while changed:
            changed = False
            iterations += 1
            self.assertLess(iterations, 50, "the reference fixpoint must converge")
            for block in sorted(succs, reverse=True):
                outside = 0
                if block != exit_block:
                    for successor in succs[block]:
                        outside |= in_values.get(successor, 0)
                inside = use.get(block, 0) | (outside & ~defs.get(block, 0))
                if (inside, outside) != (in_values[block], out_values[block]):
                    in_values[block], out_values[block] = inside, outside
                    changed = True

        for block in payload["blocks"]:
            block_id = block["block"]
            self.assertEqual(
                set(block["in"]),
                {a for a, mask in index.items() if in_values[block_id] & (1 << mask)},
                block_id,
            )
            self.assertEqual(
                set(block["out"]),
                {a for a, mask in index.items() if out_values[block_id] & (1 << mask)},
                block_id,
            )
        self.assertEqual(payload["direction"], "backward")

    def test_the_return_block_uses_the_returned_variable(self):
        program = analyse(self.PROGRAM, "df.ctc")
        payload = program.analyses["main"].live.to_json(program.analyses["main"].live_result)
        used = {a for values in payload["use"].values() for a in values}
        self.assertTrue(any(a.endswith(":b") for a in used), used)


class DefiniteAssignmentReferenceTests(unittest.TestCase):
    def test_uninitialised_read_is_reported_at_the_documented_position(self):
        """§15's worked case, verbatim: ``DFA001`` at 1:21."""
        program = analyse("int main() { int a; int b = a + 1; return b; }", "must.ctc")
        self.assertIn("DFA001", codes(program.diagnostics))
        diagnostic = next(d for d in program.diagnostics if d.code == "DFA001")
        self.assertEqual((diagnostic.line, diagnostic.col), (1, 21))
        self.assertIn("a", diagnostic.message)

    def test_the_same_case_on_several_lines_reports_the_statement_position(self):
        program = analyse("int main() {\n  int a;\n  int b = a + 1;\n  return b;\n}\n", "must2.ctc")
        diagnostic = next(d for d in program.diagnostics if d.code == "DFA001")
        self.assertEqual((diagnostic.line, diagnostic.col), (3, 3))

    def test_both_branches_assigning_is_clean(self):
        program = analyse(
            "int main() {\n  int a;\n  bool f = true;\n  if (f) { a = 1; } else { a = 2; }\n  return a;\n}\n",
            "both.ctc",
        )
        self.assertNotIn("DFA001", codes(program.diagnostics))

    def test_one_branch_assigning_is_reported(self):
        program = analyse(
            "int main() {\n  int a;\n  bool f = true;\n  if (f) { a = 1; }\n  return a;\n}\n",
            "one.ctc",
        )
        self.assertIn("DFA001", codes(program.diagnostics))

    def test_a_loop_header_is_not_a_must_fact(self):
        """§15: loop bodies start at ⊤ (not assigned), so seeding them with the
        entry fact would invent a false negative."""
        program = analyse(
            "int main() {\n  int n = 0;\n  for (int i = 0; i < 3; i = i + 1) { n = n + i; }\n  return n;\n}\n",
            "loop.ctc",
        )
        self.assertNotIn("DFA001", codes(program.diagnostics))

    def test_parameters_are_definitely_assigned(self):
        program = analyse("int f(int x) {\n  return x;\n}\nint main() {\n  return 0;\n}\n", "param.ctc")
        self.assertNotIn("DFA001", codes(program.diagnostics))


# ----------------------------------------------------------------------
# docs/API.md: parameter validation and error envelopes
# ----------------------------------------------------------------------
class ApiContractTests(unittest.TestCase):
    """These four checks are the HTTP-level regressions.  They assert the
    documented status/code pair, not whatever the server happened to answer."""

    @classmethod
    def setUpClass(cls):
        from tests.test_api import ApiTestCase

        cls._case = ApiTestCase("run")
        cls._case.setUpClass()
        cls.base = cls._case.base

    @classmethod
    def tearDownClass(cls):
        cls._case.tearDownClass()

    def get(self, path):
        """(status, decoded JSON) -- the harness returns (status, headers, body)."""
        import json

        status, _headers, body = self._case.get(path)
        return status, json.loads(body)

    def post(self, path, payload):
        import json

        status, _headers, body = self._case.post(path, payload)
        return status, json.loads(body)

    def analyse(self, source):
        status, payload = self.post("/api/analyze", {"source": source, "filename": "regress.ctc"})
        self.assertEqual(status, 200, payload)
        return payload

    def test_a_non_integer_statement_id_is_a_400_invalid_parameter(self):
        """docs/API.md §7: \"a non-integer sid is 400 invalid-parameter\"."""
        run = self.analyse("int main() { int a = 1; return a; }\n")
        status, payload = self.get(f"/api/runs/{run['run_id']}/statements/abc")
        self.assertEqual(status, 400, payload)
        self.assertEqual(payload["error"]["code"], "invalid-parameter")
        status, payload = self.get(f"/api/runs/{run['run_id']}/statements/1.5")
        self.assertEqual(status, 400, payload)

    def test_a_non_integer_graph_limit_is_a_400_not_a_500(self):
        """``?limit=abc`` raised ValueError inside the handler and answered
        500 with the exception text in ``detail``."""
        run = self.analyse("int main() { int a = 1; return a; }\n")
        status, payload = self.get(f"/api/runs/{run['run_id']}/graph?limit=abc")
        self.assertEqual(status, 400, payload)
        self.assertEqual(payload["error"]["code"], "invalid-parameter")
        self.assertEqual(payload["error"]["detail"], "")

    def test_a_negative_graph_limit_is_refused(self):
        run = self.analyse("int main() { int a = 1; return a; }\n")
        status, payload = self.get(f"/api/runs/{run['run_id']}/graph?limit=-5")
        self.assertEqual(status, 400, payload)

    def test_a_non_string_rules_field_is_refused(self):
        """docs/API.md §3 types ``rules`` as a string.  A list was ignored and
        the analysis silently used the built-in rules instead."""
        status, payload = self.post(
            "/api/analyze", {"source": "int main() { return 0; }\n", "rules": ["not", "a", "string"]}
        )
        self.assertEqual(status, 400, payload)
        self.assertEqual(payload["error"]["code"], "invalid-parameter")

    def test_an_oversized_rule_file_is_refused_by_analyze_as_well(self):
        """docs/API.md §7 documents the rule-file limit as ``413 rules-too-large``
        without restricting it to one endpoint.  ``/api/rules/validate`` enforced
        it, but ``/api/analyze`` accepted a 524 293-byte rule file (and a
        1 000 007-byte one) and analysed it, so the documented limit only held on
        half of the rule-carrying endpoints."""
        oversized = "// " + "z" * 524_289 + "\n"
        self.assertGreater(len(oversized.encode()), 512 * 1024)
        status, payload = self.post(
            "/api/analyze",
            {"source": "int main() { return 0; }\n", "filename": "r.ctc", "rules": oversized},
        )
        self.assertEqual(status, 413, payload)
        self.assertEqual(payload["error"]["code"], "rules-too-large")
        # the same text through the validation endpoint keeps its 413
        status, payload = self.post("/api/rules/validate", {"rules": oversized})
        self.assertEqual(status, 413, payload)
        self.assertEqual(payload["error"]["code"], "rules-too-large")

    def test_a_rule_file_at_the_limit_is_still_accepted(self):
        """The limit is a boundary, not an off-by-one rejection: exactly
        524 288 bytes of rule file must still be analysed."""
        padding = "// " + "z" * (524_288 - 4) + "\n"
        self.assertEqual(len(padding.encode()), 524_288)
        status, payload = self.post(
            "/api/analyze",
            {"source": "int main() { return 0; }\n", "filename": "r.ctc", "rules": padding},
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["accepted"], payload)

    def test_an_unknown_grammar_mode_is_a_400_not_a_500(self):
        """docs/API.md §2 documents ``/api/grammar?mode=lalr|slr|canonical`` and §1
        lists ``invalid-parser-mode`` under 400.  An unknown mode reached
        ``grammar.build_automaton``, whose ``GrammarError`` is not an ``ApiError``,
        so the request answered 500 internal-error."""
        for bad in ("abc", "SLR", "LALR", "null", "0x10", "1.5", " ", "<script>", "../../etc/passwd"):
            status, payload = self.get(f"/api/grammar?mode={quote(bad)}")
            self.assertEqual(status, 400, (bad, payload))
            self.assertEqual(payload["error"]["code"], "invalid-parser-mode", (bad, payload))
            self.assertEqual(payload["error"]["detail"], "", (bad, payload))

    def test_the_documented_grammar_modes_still_answer(self):
        for mode in ("lalr", "slr", "canonical"):
            status, payload = self.get(f"/api/grammar?mode={mode}")
            self.assertEqual(status, 200, mode)
            self.assertEqual(payload["mode"], mode, mode)
        # an absent or blank mode keeps the documented default
        status, payload = self.get("/api/grammar")
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "lalr")
        status, payload = self.get("/api/grammar?mode=")
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "lalr")

    def test_a_non_string_run_id_is_refused_by_the_comparison(self):
        """ComparisonRequest (docs/API.md §6) types ``before`` and ``after`` as
        strings.  A truthy non-string reached ``RunStore.get``, whose dict lookup
        raised "unhashable type: 'list'" for a list or dict and answered 500 with
        the generic internal-error envelope."""
        run = self.analyse("int main() { int a = 1; return a; }\n")
        # ``[]`` and ``{}`` used to be reported as missing-parameter when they were
        # present: the emptiness test ran before the type test, so only a non-string that
        # was *also* truthy reached the type check.  Both codes are 400, but the wrong one
        # blames the caller for omitting a field they did supply.
        for bad in ([[]], [], {"a": 1}, {}, ["x"], 1, True, 1.5):
            status, payload = self.post("/api/compare", {"before": bad, "after": run["run_id"]})
            self.assertEqual(status, 400, (bad, payload))
            self.assertEqual(payload["error"]["code"], "invalid-parameter", (bad, payload))
            status, payload = self.post("/api/compare", {"before": run["run_id"], "after": bad})
            self.assertEqual(status, 400, (bad, payload))
            self.assertEqual(payload["error"]["code"], "invalid-parameter", (bad, payload))

    def test_absent_or_empty_run_ids_still_report_missing_parameter(self):
        """The already-documented answer for an absent id must not change."""
        run = self.analyse("int main() { int a = 1; return a; }\n")
        for bad in (None, ""):
            status, payload = self.post("/api/compare", {"before": bad, "after": run["run_id"]})
            self.assertEqual(status, 400, (bad, payload))
            self.assertEqual(payload["error"]["code"], "missing-parameter", (bad, payload))
            status, payload = self.post("/api/compare", {"after": run["run_id"]})
            self.assertEqual(status, 400, (bad, payload))
            self.assertEqual(payload["error"]["code"], "missing-parameter", (bad, payload))

    def test_a_valid_comparison_still_works_after_the_type_check(self):
        run = self.analyse("int main() { int a = 1; return a; }\n")
        status, payload = self.post("/api/compare", {"before": run["run_id"], "after": run["run_id"]})
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["summary"]["before"], payload["summary"]["after"])

    def test_a_500_response_does_not_leak_the_exception_text(self):
        """docs/API.md §1: the message is generic and the traceback stays in the
        server log."""
        run = self.analyse("int main() { int a = 1; return a; }\n")
        for bad in ("abc", "1e3", "0x10", "%2B12"):
            status, payload = self.get(f"/api/runs/{run['run_id']}/graph?limit={bad}")
            self.assertIn(status, (200, 400), (bad, payload))
            if status == 400:
                self.assertEqual(payload["error"]["detail"], "", bad)


class ThemeContrastTests(unittest.TestCase):
    """Text painted on a themed surface has to pass in *every* theme.

    The browser probe measures the states a running page can be put into, one theme at a
    time, with axe -- and axe only sees the badges that run happened to render.  This
    check reads the stylesheet instead: every rule that paints text on a themed
    background is measured in all three themes from the declared variables, so a variant
    that no run rendered cannot hide.
    """

    PATH = "frontend/css/app.css"
    #: selector prefix -> theme name (later themes win in the cascade)
    THEME_PREFIX = {"body.dark": "dark", "body.contrast": "contrast"}
    BASE_THEME = "light"

    @staticmethod
    def _rules(text):
        """(selector, declaration-text) for every rule, nesting ignored."""
        rules, depth, start, brace = [], 0, 0, 0
        for i, char in enumerate(text):
            if char == "{":
                if depth == 0:
                    brace = i
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    body = text[brace + 1:i]
                    if "{" not in body:
                        rules.append((text[start:brace].strip(), body))
                    start = i + 1
        return rules

    @staticmethod
    def _declarations(body):
        out = {}
        for chunk in body.split(";"):
            if ":" in chunk:
                name, _, value = chunk.partition(":")
                out.setdefault(name.strip(), value.strip())
        return out

    @staticmethod
    def _luminance(colour):
        def channel(value):
            value /= 255.0
            return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        r, g, b = (channel(c) for c in colour)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def _contrast(self, one, two):
        a, b = self._luminance(one), self._luminance(two)
        high, low = max(a, b), min(a, b)
        return (high + 0.05) / (low + 0.05)

    @staticmethod
    def _colour(value):
        value = (value or "").strip()
        if value.startswith("var(--"):
            return None
        value = value.lstrip("#")
        if len(value) == 3:
            value = "".join(c * 2 for c in value)
        if len(value) not in (6, 8) or any(c not in "0123456789abcdefABCDEF" for c in value):
            return None
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))

    def _split(self, selector):
        """(theme, [selectors]) -- the theme a rule applies in, and its own selectors."""
        theme, parts = None, []
        for part in (p.strip() for p in selector.split(",")):
            for prefix, name in self.THEME_PREFIX.items():
                if part == prefix or part.startswith(prefix + " "):
                    theme = name
                    part = part[len(prefix):].strip()
                    break
            parts.append(part)
        return theme, parts

    def test_text_on_a_themed_surface_passes_in_every_theme(self):
        raw = pathlib.Path(ROOT, self.PATH).read_text(encoding="utf-8")
        css = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)     # comments are not selectors
        rules = self._rules(css)

        themes = {self.BASE_THEME: {}, "dark": {}, "contrast": {}}
        for selector, body in rules:
            theme, _ = self._split(selector)
            if selector == ":root":
                theme = self.BASE_THEME
            if theme is None:
                continue
            for key, value in self._declarations(body).items():
                if key.startswith("--"):
                    themes[theme][key] = value
        self.assertIn("--accent-ink", themes["dark"], "the dark theme declares its accent ink")
        for name, values in themes.items():
            if name != self.BASE_THEME:
                for key, value in themes[self.BASE_THEME].items():
                    values.setdefault(key, value)      # a theme inherits what it does not redeclare

        checked = []
        for index, (selector, body) in enumerate(rules):
            theme, own = self._split(selector)
            if theme is not None or selector == ":root":
                continue
            declares = self._declarations(body)
            background = declares.get("background", "")
            if not background.startswith("var(--"):
                continue
            surface = background[4:-1].strip()   # "var(--accent)" -> "--accent"
            if surface not in themes[self.BASE_THEME]:
                continue
            for name in themes:
                # The ink may come from the rule itself or from a theme override
                # *anywhere* in the sheet: `body.dark .badge--CRITICAL` outranks
                # `.badge--CRITICAL` on specificity, not on source order.  The last
                # matching declaration in file order wins, as the cascade says.
                ink = None
                for other, other_body in rules:
                    other_theme, other_own = self._split(other)
                    if (other_theme or self.BASE_THEME) != name:
                        continue
                    if own and set(other_own) & set(own):
                        candidate = self._declarations(other_body).get("color")
                        if candidate:
                            ink = candidate
                if ink is None:
                    ink = declares.get("color", "")
                # a literal ink ("#fff") is its own value; only var(...) is looked up
                ink_colour = (self._colour(themes[name].get(ink[4:-1].strip(), ""))
                              if ink.startswith("var(--") else self._colour(ink))
                surface_colour = self._colour(themes[name].get(surface, ""))
                if ink_colour is None or surface_colour is None:
                    continue
                self.assertGreaterEqual(
                    self._contrast(ink_colour, surface_colour), 4.5,
                    f"{self.PATH}: {selector!r} in the {name} theme paints {ink} on "
                    f"{background} -- {self._contrast(ink_colour, surface_colour):.2f}:1")
                checked.append(f"{selector}/{name}")
        # 27 rules declare a themed background and a resolvable ink; the floor catches a
        # parser change that silently stops seeing the sheet.
        self.assertGreaterEqual(len(checked), 25, "the check actually looked at the sheet")
        for required in (".topbar__logo/light", ".topbar__logo/dark", ".button--primary/dark",
                         ".badge--LOW/dark", ".badge--INFO/dark", ".badge--CRITICAL/contrast"):
            self.assertIn(required, checked, f"{required} is covered")


if __name__ == "__main__":
    unittest.main()
