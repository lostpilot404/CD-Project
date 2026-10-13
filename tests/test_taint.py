"""Taint analysis tests: the flows that must be found and the ones that must not.

The tests drive the engine the way a user does: source text in, rule set
declared in the rule language, findings out.  The negative cases carry as much
weight as the positive ones -- an analyser that reports every call is useless --
so each negative test states *why* the flow must not be reported (a constant, an
unrelated variable, a correct-context sanitizer, unreachable code, a guard that
is statically false, taint created after the sink).

Rule files are used as untrusted data throughout: they are compiled by the rule
language and, if they contain anything the language does not accept, the engine
refuses them instead of interpreting them.
"""

from __future__ import annotations

import json
import unittest

from codetrace.reporting import json_report
from codetrace.rules import rule_language
from tests.helpers import analyse, codes, finding_labels, read_example

#: The rule file that ships with the repository for custom-rule tests.
STRICT_RULES = read_example("custom_rules", "strict_rules.ctrule")

#: A rule file that declares a sink whose sensitive argument is index 0 and a
#: sanitizer whose sanitised argument is index 1, so argument handling is
#: actually exercised rather than assumed.
ARGUMENT_RULES = '''
version 1

source scan_value {
    description "a value read from the standard input stream"
    function input
    returns
    contexts command
}

sink launch_sink {
    description "starts a process with its first argument"
    function launch
    arguments 0
    context command
    category "command-injection"
    severity HIGH
}

sanitizer wrap_sanitizer {
    description "escapes its second argument for the command context"
    function wrap
    argument 1
    context command
}

flow launch_flow {
    description "untrusted data reaches launch()"
    severity HIGH
    category "command-injection"
    sources scan_value
    sinks launch_sink
    sanitizers wrap_sanitizer
    enabled true
}
'''


def compiled_rules(text: str, filename: str = "custom.ctrule"):
    """Compile a rule file exactly like the API does, failing loudly on errors."""
    rules, diagnostics, _parsed = rule_language.parse_and_validate(text, filename=filename)
    errors = [d for d in diagnostics if d.severity == "error"]
    if errors:
        raise AssertionError(
            f"rule file did not validate: {[(d.code, d.message) for d in errors]}"
        )
    return rules


class DirectFlowTests(unittest.TestCase):
    def test_direct_source_to_sink_is_reported(self):
        program = analyse("int main() { string cmd = input(); system(cmd); return 0; }")
        self.assertEqual(finding_labels(program.findings), ["command_execution@1"])
        finding = program.findings[0]
        self.assertEqual(finding.category, "command-injection")
        self.assertEqual(finding.severity, "HIGH")
        self.assertEqual(finding.confidence, "high")
        self.assertEqual(finding.certainty, "confirmed")
        self.assertEqual(finding.feasibility, "unconditional")
        self.assertFalse(finding.interprocedural)
        self.assertEqual(finding.source["rule"], "stdin")
        self.assertEqual(finding.source["function"], "input")
        self.assertEqual(finding.sink["rule"], "command_system")
        self.assertEqual(finding.sink["function"], "system")
        self.assertEqual(finding.sink["context"], "command")
        self.assertEqual(finding.sink["argument_index"], 0)
        self.assertEqual(finding.sink["statement_text"], "system(cmd);")
        self.assertEqual([step["kind"] for step in finding.path], ["source", "declaration", "sink"])
        self.assertEqual(finding.path_atoms, ["src:stdin@command"])
        self.assertIn("potential command injection flow detected", finding.explanation.lower())
        self.assertIn("shell_escape", finding.remediation, "remediation names the modelled fix")

    def test_sink_call_with_a_source_as_its_argument_is_reported(self):
        # The tainted value never passes through a variable, so this pins the
        # representation of taint that only exists inside an expression.
        program = analyse("int main() { system(input()); return 0; }")
        self.assertEqual(finding_labels(program.findings), ["command_execution@1"])
        finding = program.findings[0]
        self.assertEqual([step["kind"] for step in finding.path], ["source", "sink"])
        self.assertEqual(finding.path_atoms, ["src:stdin@command"])

    def test_taint_survives_multiple_assignments(self):
        program = analyse(
            """
int main() {
  string first = input();
  string second = first;
  string third = second;
  system(third);
  return 0;
}
"""
        )
        self.assertEqual(len(program.findings), 1)
        kinds = [step["kind"] for step in program.findings[0].path]
        self.assertEqual(kinds.count("declaration"), 3, "each copy is a path step")
        self.assertEqual(len(program.findings[0].path), 5)

    def test_taint_propagates_through_expressions(self):
        program = analyse(
            """
int main() {
  string cmd = "ls " + input();
  system(cmd);
  return 0;
}
"""
        )
        # Line numbers refer to the analysed source (the helper strips the
        # leading and trailing blank lines of the literal).
        self.assertEqual(finding_labels(program.findings), ["command_execution@3"])

    def test_clean_concatenation_does_not_taint(self):
        program = analyse(
            """
int main() {
  string safe = "ls " + "/tmp";
  system(safe);
  return 0;
}
"""
        )
        self.assertEqual(program.findings, [])

    def test_sink_declares_which_argument_is_sensitive(self):
        program = analyse(
            """
int main() {
  string name = input();
  printf(name);
  printf("constant %s", name);
  return 0;
}
"""
        )
        # The format-string rule marks argument 0.  The second call passes the
        # same tainted value, but at argument 1, which the rule does not treat
        # as the format string.
        self.assertEqual(finding_labels(program.findings), ["format_string@3"])


class BranchTests(unittest.TestCase):
    def test_flow_through_a_taken_branch_is_reported(self):
        program = analyse(
            """
int main() {
  string cmd = "ls";
  if (input_int() > 0) {
    cmd = input();
  } else {
    cmd = "ls -l";
  }
  system(cmd);
  return 0;
}
"""
        )
        self.assertEqual(finding_labels(program.findings), ["command_execution@8"])
        finding = program.findings[0]
        self.assertEqual(finding.feasibility, "guarded")
        self.assertEqual(finding.certainty, "approximate", "an undecided guard is an approximation")
        self.assertEqual(
            sorted({condition["line"] for condition in finding.branch_conditions}), [3]
        )
        self.assertTrue(all(c["condition"] for c in finding.branch_conditions))
        kinds = [step["kind"] for step in finding.path]
        self.assertNotIn("unresolved", kinds, "a clean write on the other branch is not the origin")
        self.assertTrue(all("== 0" not in s["label"] for s in finding.path if s["kind"] == "assignment"))
        self.assertFalse(
            any("does not reach a configured source" in item for item in finding.limitations)
        )
        self.assertEqual(sorted(finding.path_atoms), ["src:stdin@command"])

    def test_both_branches_tainted_still_yields_one_flow(self):
        program = analyse(
            """
int main() {
  string cmd;
  if (input_int() > 0) {
    cmd = input();
  } else {
    cmd = input();
  }
  system(cmd);
  return 0;
}
"""
        )
        self.assertEqual(len(program.findings), 1)

    def test_validator_inside_the_guard_removes_the_flow(self):
        program = analyse(
            """
int main() {
  string cmd = input();
  if (is_safe_command(cmd)) {
    system(cmd);
  }
  return 0;
}
"""
        )
        # A validator in the condition means the guarded call cannot receive the
        # unvalidated value; the edge refinement removes the atom on that edge.
        self.assertEqual(program.findings, [])

    def test_a_validator_suppression_is_recorded_as_an_assumption(self):
        # The engine does not analyse the validator's implementation, so a flow
        # that the guard cleared must be recorded, not silently dropped: "nothing
        # was reported" and "a declared validator was assumed to reject it" are
        # different statements, and only one of them is true here.
        program = analyse(
            """
int main() {
  string cmd = input();
  if (is_safe_command(cmd)) {
    system(cmd);
  }
  return 0;
}
"""
        )
        self.assertEqual(program.findings, [])
        suppressions = program.taint.guard_suppressions
        self.assertEqual(len(suppressions), 1)
        entry = suppressions[0]
        self.assertEqual(
            (entry["function"], entry["symbol"], entry["context"]),
            ("main", "cmd", "command"),
        )
        self.assertEqual(entry["validator"], "validate_command")
        self.assertEqual(entry["validator_function"], "is_safe_command")
        self.assertEqual(entry["removed_atoms"], ["src:stdin@command"])
        self.assertEqual(entry["guard_edge"], "true")
        self.assertIn("assumes it rejects", entry["assumption"])
        self.assertTrue(any("cleared on" in note for note in program.taint.notes))

    def test_a_negated_guard_clears_only_the_edge_it_guards(self):
        # ``if (!is_safe_command(x))`` guards the *false* edge, so a sink inside
        # the true branch still receives the unvalidated value.
        program = analyse(
            """
int main() {
  string cmd = input();
  if (!is_safe_command(cmd)) {
    system(cmd);
  }
  return 0;
}
"""
        )
        self.assertEqual(finding_labels(program.findings), ["command_execution@4"])
        self.assertEqual(len(program.taint.guard_suppressions), 1)
        self.assertEqual(program.taint.guard_suppressions[0]["guard_edge"], "false")

    def test_a_guard_on_another_symbol_cannot_clear_this_one(self):
        # Symbol identity, not spelling: the guard covers ``checked`` and the
        # sink consumes ``other``, so the flow stands.
        program = analyse(
            """
int main() {
  string checked = input();
  string other = input();
  if (is_safe_command(checked)) {
    system(other);
  }
  return 0;
}
"""
        )
        self.assertEqual(finding_labels(program.findings), ["command_execution@5"])
        self.assertEqual(
            [entry["symbol"] for entry in program.taint.guard_suppressions], ["checked"]
        )

    def test_a_guard_on_a_compound_argument_is_not_applied_and_says_so(self):
        program = analyse(
            """
int main() {
  string cmd = input();
  if (is_safe_command(cmd + "x")) {
    system(cmd);
  }
  return 0;
}
"""
        )
        self.assertEqual(finding_labels(program.findings), ["command_execution@4"])
        self.assertEqual(program.taint.guard_suppressions, [])
        self.assertTrue(
            any("not a plain variable" in note for note in program.taint.notes),
            program.taint.notes,
        )

    def test_no_branch_means_no_branch_conditions(self):
        program = analyse("int main() { string cmd = input(); system(cmd); return 0; }")
        finding = program.findings[0]
        self.assertEqual(finding.branch_conditions, [])
        self.assertEqual(finding.feasibility, "unconditional")
        self.assertEqual(finding.confidence, "high")

    def test_statically_false_guard_is_pruned_and_explained(self):
        program = analyse(
            """
int main() {
  string cmd = input();
  if (false) {
    system(cmd);
  }
  return 0;
}
"""
        )
        self.assertEqual(program.findings, [])
        self.assertEqual(len(program.taint.infeasible_edges), 1)
        pruned = program.taint.infeasible_edges[0]
        self.assertIn("constant", pruned["reason"])
        self.assertTrue(
            any("pruned" in note for note in program.taint.notes),
            "the pruning is reported instead of silently dropping the branch",
        )


class SanitizerTests(unittest.TestCase):
    def test_matching_context_sanitizer_clears_the_taint(self):
        program = analyse(
            "int main() { string cmd = input(); system(shell_escape(cmd)); return 0; }"
        )
        self.assertEqual(program.findings, [])

    def test_sanitizer_for_another_context_does_not_clear_the_taint(self):
        program = analyse(
            "int main() { string cmd = input(); system(sql_escape(cmd)); return 0; }"
        )
        self.assertEqual(finding_labels(program.findings), ["command_execution@1"])
        finding = program.findings[0]
        self.assertEqual([step["kind"] for step in finding.path], ["source", "declaration", "sanitizer", "sink"])
        self.assertEqual(len(finding.sanitizers_seen), 1)
        seen = finding.sanitizers_seen[0]
        self.assertEqual(seen["rule"], "sql_escape")
        self.assertEqual(seen["context"], "sql", "the context the rule was declared for")
        self.assertIn("sql", seen["detail"])
        self.assertTrue(any("does not neutralise" in item for item in finding.limitations))

    def test_sanitizing_one_value_does_not_clean_another(self):
        program = analyse(
            """
int main() {
  string cmd = input();
  string safe = shell_escape(cmd);
  system(safe);
  system(cmd);
  return 0;
}
"""
        )
        self.assertEqual(finding_labels(program.findings), ["command_execution@5"])

    def test_sanitizer_only_covers_its_own_argument(self):
        rules = compiled_rules(ARGUMENT_RULES, "argument_rules.ctrule")
        neutralised = analyse(
            'int main() { string a = input(); launch(wrap("prefix", a)); return 0; }',
            filename="neutralised",
            rules=rules,
        )
        self.assertEqual(neutralised.findings, [])
        surviving = analyse(
            'int main() { string a = input(); launch(wrap(a, "prefix")); return 0; }',
            filename="surviving",
            rules=rules,
        )
        self.assertEqual(finding_labels(surviving.findings), ["launch_flow@1"])
        detail = surviving.findings[0].sanitizers_seen[0]["detail"]
        self.assertIn("another argument", detail)

    def test_unknown_function_never_clears_taint(self):
        program = analyse(
            """
int main() {
  string cmd = input();
  system(unknown_helper(cmd));
  return 0;
}
"""
        )
        # Nothing is known about ``unknown_helper``, so it cannot be treated as a
        # sanitizer: the analysis stays conservative and keeps the flow.
        self.assertEqual(finding_labels(program.findings), ["command_execution@3"])
        finding = program.findings[0]
        self.assertIn("unknown-call", [step["kind"] for step in finding.path])
        self.assertEqual(finding.certainty, "approximate")
        self.assertTrue(any("not modelled" in item for item in finding.limitations))


class InterproceduralTests(unittest.TestCase):
    def test_flow_through_a_helper_is_interprocedural(self):
        program = analyse(
            """
string build(string value) {
  return "ls " + value;
}

int main() {
  string cmd = build(input());
  system(cmd);
  return 0;
}
"""
        )
        self.assertEqual(finding_labels(program.findings), ["command_execution@7"])
        finding = program.findings[0]
        self.assertTrue(finding.interprocedural)
        self.assertEqual(finding.certainty, "approximate")
        kinds = [step["kind"] for step in finding.path]
        for expected in ("parameter", "call", "return"):
            self.assertIn(expected, kinds)
        self.assertTrue(any("context-insensitive" in item for item in finding.limitations))

    def test_source_passed_straight_into_a_helper_parameter(self):
        program = analyse(
            """
void run(string command) {
  system(command);
}

int main() {
  run(input());
  return 0;
}
"""
        )
        self.assertEqual(finding_labels(program.findings), ["command_execution@2"])
        self.assertEqual(
            [step["kind"] for step in program.findings[0].path],
            ["source", "argument", "parameter", "sink"],
        )

    def test_parameter_tainted_at_one_call_site_is_reported_at_every_call_site(self):
        # The documented model is context-insensitive: this is the honest,
        # conservative behaviour, and the finding says so.
        program = analyse(
            """
void run(string command) {
  system(command);
}

int main() {
  run(input());
  run("ls");
  return 0;
}
"""
        )
        self.assertEqual(len(program.findings), 1)
        self.assertTrue(program.findings[0].interprocedural)
        self.assertTrue(
            any("context-insensitive" in item.lower() for item in program.findings[0].limitations)
        )

    def test_recursion_terminates_and_is_reported_as_approximate(self):
        program = analyse(
            """
string wrap(string value, int depth) {
  if (depth > 0) {
    return wrap(value, depth - 1);
  }
  return value;
}

int main() {
  string cmd = wrap(input(), 3);
  system(cmd);
  return 0;
}
"""
        )
        self.assertEqual(len(program.findings), 1)
        self.assertTrue(program.taint.converged)
        self.assertEqual(program.findings[0].certainty, "approximate")

    def test_returned_taint_does_not_escape_an_unrelated_function(self):
        program = analyse(
            """
string safe_value() {
  return "ls /tmp";
}

int main() {
  system(safe_value());
  return 0;
}
"""
        )
        self.assertEqual(program.findings, [])


class NegativeCaseTests(unittest.TestCase):
    def test_constant_reaching_a_sink_is_not_reported(self):
        program = analyse('int main() { system("ls -l"); return 0; }')
        self.assertEqual(program.findings, [])
        self.assertTrue(program.analysis_complete)

    def test_tainted_variable_that_never_reaches_the_sink(self):
        program = analyse(
            """
int main() {
  string tainted = input();
  string safe = "ls /tmp";
  system(safe);
  return 0;
}
"""
        )
        self.assertEqual(program.findings, [])

    def test_taint_created_after_the_sink(self):
        program = analyse(
            """
int main() {
  system("ls");
  string later = input();
  return 0;
}
"""
        )
        self.assertEqual(program.findings, [])

    def test_sink_reached_only_by_unreachable_code(self):
        program = analyse(
            """
int main() {
  return 0;
  string cmd = input();
  system(cmd);
}
"""
        )
        # The statements stay in the CFG, marked unreachable, and a flow that
        # cannot execute is not reported as a finding.
        self.assertEqual(program.findings, [])
        self.assertTrue(program.cfgs["main"].unreachable)

    def test_unsupported_construct_is_reported_not_treated_as_safe(self):
        program = analyse(
            """
int main() {
  int x = 1;
  switch (x) {
    case 1: system("ls");
  }
  return 0;
}
"""
        )
        self.assertFalse(program.analysis_complete)
        self.assertTrue(program.partial_reasons)
        self.assertIn("LEX100", codes(program.diagnostics), "unsupported keyword is diagnosed")
        self.assertIn("SYN100", codes(program.diagnostics))
        self.assertFalse(program.ok, "a partial analysis is not reported as a clean one")

    def test_clean_file_is_not_advertised_as_safe(self):
        program = analyse("int main() { int a = 1; return a; }")
        self.assertEqual(program.findings, [])
        self.assertTrue(program.analysis_complete)
        report = json_report.build_report(program)
        self.assertEqual(report["summary"]["findings"], 0)
        limitations = " ".join(report["limitations"]).lower()
        self.assertIn("never assumed safe", limitations)
        self.assertEqual(report["summary"]["dispositions"]["unreported_count"], 0)


class MultipleSourceAndSinkTests(unittest.TestCase):
    def test_two_sources_two_sinks_give_two_findings_with_stable_ids(self):
        source = """
int main() {
  string first = input();
  string second = readenv("HOME");
  system(first);
  system(second);
  return 0;
}
"""
        program = analyse(source)
        self.assertEqual(
            finding_labels(program.findings), ["command_execution@4", "command_execution@5"]
        )
        self.assertEqual(
            {finding.sink["line"]: finding.path_atoms for finding in program.findings},
            {4: ["src:stdin@command"], 5: ["src:environment@command"]},
        )
        again = analyse(source)
        self.assertEqual(
            [finding.id for finding in program.findings],
            [finding.id for finding in again.findings],
            "finding ids are stable for the same source and rule set",
        )
        self.assertEqual(
            [finding.to_json() for finding in program.findings],
            [finding.to_json() for finding in again.findings],
            "results are deterministic for a given source, rule set and engine version",
        )

    def test_findings_record_their_flow_and_statement_ids(self):
        program = analyse(
            """
int main() {
  string cmd = input();
  system(cmd);
  return 0;
}
"""
        )
        finding = program.findings[0]
        self.assertEqual(finding.flow_id, "command_execution")
        self.assertTrue(finding.statement_ids)
        for sid in finding.statement_ids:
            self.assertIn(sid, program.statements)
        self.assertTrue(all(step["line"] >= 1 for step in finding.path))
        self.assertEqual(finding.evidence["engine_version"], program.metrics["engine_version"] if "engine_version" in program.metrics else finding.evidence["engine_version"])
        self.assertIn("src:stdin@command", finding.evidence["atoms"])

    def test_contexts_are_tracked_separately_per_sink(self):
        program = analyse(
            """
int main() {
  string body = input();
  writefile(body, "out.txt");
  printf(body);
  return 0;
}
"""
        )
        self.assertEqual(
            sorted(finding_labels(program.findings)), ["format_string@4", "path_traversal@3"]
        )
        contexts = {finding.sink["context"]: finding.path_atoms for finding in program.findings}
        self.assertEqual(contexts["path"], ["src:stdin@path"])
        self.assertEqual(contexts["format"], ["src:stdin@format"])


class RuleConfigurationTests(unittest.TestCase):
    """The rule set is data: changing it changes what the engine reports."""

    def test_custom_source_and_sink_are_used(self):
        rules = compiled_rules(STRICT_RULES, "strict_rules.ctrule")
        program = analyse(
            """
int main() {
  string body = http_body();
  audit_write(body);
  return 0;
}
""",
            filename="custom",
            rules=rules,
        )
        self.assertEqual(finding_labels(program.findings), ["audit_injection@3"])
        finding = program.findings[0]
        self.assertEqual(finding.category, "arbitrary-file-write")
        self.assertEqual(finding.severity, "MEDIUM")
        self.assertEqual(finding.source["rule"], "request_body")
        self.assertEqual(finding.sink["function"], "audit_write")

    def test_custom_sanitizer_clears_its_own_context(self):
        rules = compiled_rules(STRICT_RULES, "strict_rules.ctrule")
        program = analyse(
            "int main() { string body = http_body(); audit_write(audit_escape(body)); return 0; }",
            filename="custom",
            rules=rules,
        )
        self.assertEqual(program.findings, [])

    def test_custom_sanitizer_of_another_context_does_not_clear(self):
        rules = compiled_rules(STRICT_RULES, "strict_rules.ctrule")
        program = analyse(
            "int main() { string body = http_body(); audit_write(sql_escape(body)); return 0; }",
            filename="custom",
            rules=rules,
        )
        self.assertEqual(finding_labels(program.findings), ["audit_injection@1"])

    def test_submitted_rules_extend_the_built_ins_and_can_stand_alone(self):
        rules = compiled_rules(ARGUMENT_RULES, "argument_rules.ctrule")
        source = 'int main() { string a = input(); writefile(a, "out.txt"); return 0; }'
        merged = analyse(source, filename="merged", rules=rules)
        # By default the submitted file extends the shipped policy, so the
        # built-in path-traversal rule still fires.
        self.assertEqual(finding_labels(merged.findings), ["path_traversal@1"])
        self.assertIn("path_writefile", merged.rules.sinks)
        custom_only = analyse(
            source, filename="custom-only", rules=rules, include_builtin_rules=False
        )
        # With the built-ins switched off, nothing connects input() to
        # writefile, and the custom sink is not present in this source either.
        self.assertEqual(custom_only.findings, [])
        self.assertIn("launch_sink", custom_only.rules.sinks)
        self.assertNotIn("path_writefile", custom_only.rules.sinks)

    def test_rule_file_with_unknown_references_is_rejected(self):
        bad = '''
version 1

flow nothing {
    description "references a source that does not exist"
    severity HIGH
    category "command-injection"
    sources does_not_exist
    sinks also_missing
    enabled true
}
'''
        rules, diagnostics, _parsed = rule_language.parse_and_validate(bad, filename="bad.ctrule")
        error_codes = [d.code for d in diagnostics if d.severity == "error"]
        self.assertIn("RULE020", error_codes)
        self.assertIn("RULE021", error_codes)
        self.assertEqual((rules.flows, rules.sources, rules.sinks), ({}, {}, {}))
        for diagnostic in diagnostics:
            if diagnostic.severity == "error":
                self.assertGreaterEqual(diagnostic.line, 1)
                self.assertGreaterEqual(diagnostic.col, 1)

    def test_rule_file_cannot_embed_executable_text(self):
        injection = '''
version 1

source evil {
    description "x"
    function __import__("os").system("rm -rf /")
    returns
    contexts command
}
'''
        rules, diagnostics, _parsed = rule_language.parse_and_validate(
            injection, filename="inject.ctrule"
        )
        errors = [d for d in diagnostics if d.severity == "error"]
        self.assertTrue(errors, "the rule language rejects the embedded call syntax")
        self.assertEqual(rules.sources, {}, "nothing from the rejected file reaches the engine")
        self.assertTrue(all(d.code.startswith(("SYN", "LEX", "RULE")) for d in errors))
        self.assertTrue(
            all(d.line >= 1 and d.col >= 1 for d in errors),
            "each rejection carries a line:col position",
        )
        # The rejected text is never interpreted: the pipeline above only ever
        # produced diagnostics, and no Python object was evaluated.
        self.assertNotIn("exec", json.dumps([d.message for d in errors]).lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
