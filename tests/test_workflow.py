"""End-to-end workflow tests over the real HTTP API.

These tests drive the product the way the user interface drives it, in the order
a user does: load a bundled example, analyse it, open the reported finding,
follow its evidence back to the source and into the graphs, take a slice, write
and validate a custom rule, run the analysis with that rule, export a report, fix
the source, re-analyse and confirm through a comparison that the flow is gone.

Nothing here is mocked: every number, path, graph and report comes from the real
engine over HTTP, and the interface's own module is checked against the server's
declared endpoints so the browser cannot call something the API does not serve.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from tests.test_api import ApiTestCase

VULNERABLE = "vulnerable/command_injection.ctc"
SANITIZED = "sanitized/shell_escape.ctc"

# A rule file naming a function the built-in rules do not know, so any finding
# on the program below can only come from the custom rule set.
CUSTOM_RULES = """version 1

source argv_argument {
    description "process argument"
    function argv
    returns
    contexts command
}

sink launch_sink {
    description "launch helper"
    function launch
    arguments 0
    context command
    category "command-injection"
    severity HIGH
}

flow argv_to_launch {
    sources argv_argument
    sinks launch_sink
    enabled true
}
"""

CUSTOM_SOURCE = (
    "int launch(string command) {\n"
    "  return 0;\n"
    "}\n"
    "\n"
    "int main() {\n"
    "  string argument = argv(1);\n"
    "  launch(argument);\n"
    "  return 0;\n"
    "}\n"
)

FIXED_SOURCE = """// Untrusted input is escaped before it reaches the command.
int main() {
  string name = input();
  string escaped = shell_escape(name);
  system(escaped);
  return 0;
}
"""

PLAIN_SOURCE = "int main() {\n  string name = input();\n  system(name);\n  return 0;\n}\n"
SHIFTED_SOURCE = (
    "// A banner comment inserted above the same program.\n"
    "// The flow itself is unchanged, so the finding must be reported as moved.\n"
    + PLAIN_SOURCE
)


class LoadAndDetectTests(ApiTestCase):
    """Steps 1-6 of the workflow: load, analyse, detect, open the finding."""

    def test_a_bundled_example_loads_and_is_analysed(self):
        listing = self.json_get("/api/examples")
        ids = [entry["id"] for entry in listing["examples"]]
        self.assertIn(VULNERABLE, ids)
        self.assertIn(SANITIZED, ids)

        example = self.json_get(f"/api/examples/{VULNERABLE}")
        self.assertEqual(example["id"], VULNERABLE)
        self.assertEqual(example["id"].split("/")[0], "vulnerable")
        self.assertTrue(example["content"].strip(), "the example has no source")
        # Every corpus file states its own expectation, so this test repeats the
        # expectation the file carries instead of keeping a second, drifting copy.
        self.assertIn("// expect:", example["content"])
        self.assertTrue(example["expectation"])

        run = self.analyse(example["content"], filename=os.path.basename(VULNERABLE))
        self.assertTrue(run["accepted"])
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["filename"], "command_injection.ctc")
        self.assertGreater(run["metrics"]["statements"], 0)

    def test_the_reported_finding_carries_its_evidence(self):
        example = self.json_get(f"/api/examples/{VULNERABLE}")
        run = self.analyse(example["content"], filename="command_injection.ctc")
        payload = self.json_get(f"/api/runs/{run['run_id']}/findings")
        self.assertEqual(payload["count"], 1)
        finding = payload["findings"][0]

        self.assertEqual(finding["rule_id"], "command_execution")
        self.assertEqual(finding["category"], "command-injection")
        self.assertEqual(finding["severity"], "HIGH")
        self.assertEqual(finding["sink"]["function"], "system")
        self.assertEqual(finding["sink"]["line"], 10)
        self.assertEqual(finding["source"]["rule"], "stdin")
        # A finding states a potential flow; it must not promise an exploit.
        self.assertIn("Potential", finding["explanation"])
        self.assertTrue(finding["remediation"])
        self.assertTrue(finding["limitations"])
        # The analyse response keeps the per-run payload small: findings carry
        # their identifiers and locations, and the path arrives on demand.
        self.assertNotIn("path", run["findings"][0])

        detail = self.json_get(f"/api/runs/{run['run_id']}/findings/{finding['id']}")
        self.assertEqual(detail["id"], finding["id"])
        kinds = [step["kind"] for step in detail["path"]]
        self.assertEqual(kinds[0], "source")
        self.assertEqual(kinds[-1], "sink")
        self.assertIn("argument", kinds)  # the call boundary was crossed
        self.assertIn("parameter", kinds)
        self.assertIn("return", kinds)
        self.assertTrue(detail["statement_ids"])

    def test_the_sanitizer_is_what_makes_the_difference(self):
        example = self.json_get(f"/api/examples/{SANITIZED}")
        sanitized = self.analyse(example["content"], filename="shell_escape.ctc")
        self.assertEqual(
            self.json_get(f"/api/runs/{sanitized['run_id']}/findings")["count"], 0
        )
        self.assertTrue(sanitized["summary"]["analysis_complete"])

        # The same statement without the sanitiser does produce a finding, so the
        # silence above is the sanitiser and not a detector that missed the sink.
        unsanitized = self.analyse(
            "int main() {\n  string c = input();\n  system(c);\n  return 0;\n}\n",
            filename="unsanitized.ctc",
        )
        self.assertEqual(
            self.json_get(f"/api/runs/{unsanitized['run_id']}/findings")["count"], 1
        )


class NavigationTests(ApiTestCase):
    """Steps 7-10: statement, AST, CFG, data-flow, dependency graph."""

    def setUp(self):
        super().setUp()
        example = self.json_get(f"/api/examples/{VULNERABLE}")
        self.run = self.analyse(example["content"], filename="command_injection.ctc")
        self.finding = self.json_get(f"/api/runs/{self.run['run_id']}/findings")["findings"][0]
        self.detail = self.json_get(
            f"/api/runs/{self.run['run_id']}/findings/{self.finding['id']}"
        )

    def test_every_step_of_the_evidence_has_a_statement_to_open(self):
        seen = set()
        for step in self.detail["path"]:
            if step["sid"] < 0:
                continue  # parameter and return steps name a function, not a line
            if step["sid"] in seen:
                continue
            seen.add(step["sid"])
            statement = self.json_get(
                f"/api/runs/{self.run['run_id']}/statements/{step['sid']}"
            )
            self.assertEqual(statement["sid"], step["sid"])
            self.assertTrue(statement["text"])
            self.assertEqual(statement["line"], step["line"])
            self.assertTrue(statement["ast"])
            self.assertIsInstance(statement["block"], int)

        sink = self.json_get(
            f"/api/runs/{self.run['run_id']}/statements/{self.finding['sink']['sid']}"
        )
        self.assertIn("system(", sink["text"])
        self.assertEqual(sink["function"], "main")
        # The taint the engine computed for this statement names the source rule
        # and the context it is dangerous in; the interface shows these atoms.
        atoms = {atom for entry in sink["taint"] for atom in entry["atoms"]}
        self.assertIn("src:stdin@command", atoms)
        self.assertTrue(sink["reaching_definitions"])
        self.assertEqual(len(sink["span"]), 2)

    def test_the_sink_call_exists_in_the_ast_with_its_source_span(self):
        tree = self.json_get(f"/api/runs/{self.run['run_id']}/ast")["tree"]
        calls = []

        def walk(node):
            if node.get("kind") == "Call":
                calls.append(node)
            for child in node.get("children") or []:
                walk(child)

        walk(tree)
        system_calls = [node for node in calls if node.get("name") == "system"]
        self.assertEqual(len(system_calls), 1)
        call = system_calls[0]
        self.assertEqual(call["arg_count"], 1)
        self.assertEqual(call["line"], self.finding["sink"]["line"])
        self.assertEqual(len(call["span"]), 2)
        # Calls are classified by the symbol table: 'system' has no definition in
        # this file, while the call to build_command resolves to a declared one.
        self.assertEqual(call["resolution"], "external")
        user_calls = [node for node in calls if node.get("name") == "build_command"]
        self.assertEqual([node["resolution"] for node in user_calls], ["function"])

    def test_the_control_flow_graph_locates_the_sink_block(self):
        cfg = self.json_get(f"/api/runs/{self.run['run_id']}/cfg?function=main")
        self.assertEqual(cfg["function"], "main")
        self.assertEqual(cfg["blocks"][0]["kind"], "entry")
        block = next(
            entry for entry in cfg["blocks"]
            if self.finding["sink"]["sid"] in entry["statement_ids"]
        )
        kinds = {entry["kind"] for entry in cfg["blocks"]}
        self.assertTrue({"entry", "exit"} <= kinds)
        self.assertTrue(
            kinds <= {"entry", "exit", "normal", "loop-header", "merge", "branch"}
        )
        self.assertEqual(cfg["blocks"][-1]["statement_ids"], [])
        vocabulary = {"sequential", "true", "false", "while", "for", "loop-back",
                      "break", "continue", "return", "exit"}
        self.assertTrue({edge["kind"] for edge in cfg["edges"]} <= vocabulary)
        self.assertTrue(cfg["reachable"])
        self.assertEqual(cfg["unreachable"], [])
        self.assertEqual(cfg["loops"], [])

    def test_the_dependency_graph_justifies_every_edge(self):
        graph = self.json_get(f"/api/runs/{self.run['run_id']}/graph")
        kinds = {edge["kind"] for edge in graph["edges"]}
        self.assertIn("taint", kinds)
        self.assertIn("define", kinds)
        for edge in graph["edges"]:
            self.assertTrue(edge.get("reason"), f"edge without a reason: {edge}")
            self.assertIn(edge["family"], {"data", "control", "call", "return",
                                           "taint", "sanitize", "define",
                                           "source-to-sink"})
            self.assertTrue(edge["from"] and edge["to"])
        sink_nodes = [
            node for node in graph["nodes"]
            if node.get("sid") == self.finding["sink"]["sid"] and node["kind"] == "statement"
        ]
        self.assertEqual(len(sink_nodes), 1)

        # The graph view can show a subset of the families without inventing any.
        filtered = self.json_get(f"/api/runs/{self.run['run_id']}/graph?kinds=data,taint")
        self.assertTrue(filtered["edges"])
        self.assertTrue(all(edge["kind"] in {"data", "taint"} for edge in filtered["edges"]))

    def test_reaching_definitions_and_liveness_explain_the_sink_statement(self):
        sink_statement = self.json_get(
            f"/api/runs/{self.run['run_id']}/statements/{self.finding['sink']['sid']}"
        )
        reaching = self.json_get(
            f"/api/runs/{self.run['run_id']}/dataflow?function=main&analysis=reaching"
        )
        self.assertEqual(reaching["analysis"], "reaching")
        self.assertEqual(reaching["function"], "main")
        self.assertTrue(reaching["converged"])
        self.assertGreater(reaching["iterations"], 0)
        block = next(
            entry for entry in reaching["blocks"] if entry["block"] == sink_statement["block"]
        )
        # The sink sits in the entry block of main, so nothing reaches it from a
        # predecessor; the definitions created inside it are what its OUT holds.
        self.assertGreater(block["out_size"], 0)
        self.assertTrue(sink_statement["reaching_definitions"])
        self.assertTrue(all(
            definition["line"] <= self.finding["sink"]["line"]
            for definition in sink_statement["reaching_definitions"]
        ))

        live = self.json_get(
            f"/api/runs/{self.run['run_id']}/dataflow?function=main&analysis=liveness"
        )
        self.assertEqual(live["analysis"], "liveness")
        live_block = next(
            entry for entry in live["blocks"] if entry["block"] == sink_statement["block"]
        )
        self.assertEqual(live_block["block"], sink_statement["block"])
        # The value consumed by the sink is live immediately before it.
        sink_symbol = self.finding["sink"]["expression"]
        state = live["statement_states"][str(self.finding["sink"]["sid"])]
        self.assertTrue(
            any(atom.endswith(f":{sink_symbol}") for atom in state["in"]), state
        )


class SlicingTests(ApiTestCase):
    """Step 11: the slice contains exactly the statements that justify it."""

    def setUp(self):
        super().setUp()
        example = self.json_get(f"/api/examples/{VULNERABLE}")
        self.run = self.analyse(example["content"], filename="command_injection.ctc")
        self.finding = self.json_get(f"/api/runs/{self.run['run_id']}/findings")["findings"][0]

    def test_the_security_slice_of_the_finding_explains_each_statement(self):
        payload = self.json_get(
            f"/api/runs/{self.run['run_id']}/findings/{self.finding['id']}/slice"
        )
        self.assertEqual(payload["finding_id"], self.finding["id"])
        statements = payload["statements"]
        self.assertIn(self.finding["source"]["sid"], statements)
        self.assertIn(self.finding["sink"]["sid"], statements)
        self.assertEqual(set(payload["reasons"]), {str(sid) for sid in statements})
        for sid, reasons in payload["reasons"].items():
            self.assertTrue(reasons, f"statement {sid} entered the slice without a reason")
        self.assertFalse(payload["truncated"])
        self.assertIn("conservative", payload["note"])
        self.assertGreaterEqual(payload["statement_count"], len(statements))

    def test_a_backward_slice_from_the_sink_contains_the_source(self):
        payload = self.json_get(
            f"/api/runs/{self.run['run_id']}/slice"
            f"?sid={self.finding['sink']['sid']}&direction=backward"
        )
        self.assertEqual(payload["kind"], "backward")
        self.assertEqual(payload["criterion"]["sid"], self.finding["sink"]["sid"])
        self.assertIn(self.finding["source"]["sid"], payload["statements"])

    def test_a_forward_slice_from_the_source_reaches_the_sink(self):
        payload = self.json_get(
            f"/api/runs/{self.run['run_id']}/slice"
            f"?sid={self.finding['source']['sid']}&direction=forward"
        )
        self.assertEqual(payload["kind"], "forward")
        self.assertIn(self.finding["sink"]["sid"], payload["statements"])


class CustomRuleWorkflowTests(ApiTestCase):
    """Steps 12-14: write a rule, validate it, analyse with it."""

    def test_the_rule_editor_round_trip_produces_a_custom_finding(self):
        validation = self.json_post("/api/rules/validate", {"rules": CUSTOM_RULES})
        self.assertTrue(validation["valid"], validation["diagnostics"])
        self.assertEqual(validation["diagnostics"], [])
        self.assertTrue(validation["parse"]["accepted"])
        self.assertEqual(validation["stats"]["sources"], 1)
        self.assertEqual(validation["stats"]["sinks"], 1)
        self.assertEqual(validation["stats"]["flows"], 1)
        self.assertGreater(validation["grammar"]["states"], 0)
        self.assertEqual(validation["grammar"]["conflicts"], 0)

        # A rule file with a broken reference is rejected with a line and a
        # column instead of being silently ignored.
        broken = CUSTOM_RULES.replace("sources argv_argument", "sources missing_source")
        rejected = self.json_post("/api/rules/validate", {"rules": broken})
        self.assertFalse(rejected["valid"])
        self.assertTrue(rejected["diagnostics"])
        self.assertTrue(all(d["line"] > 0 for d in rejected["diagnostics"]))
        self.assertTrue(all(d["code"] for d in rejected["diagnostics"]))

        run = self.json_post(
            "/api/analyze",
            {
                "source": CUSTOM_SOURCE,
                "filename": "custom.ctc",
                "rules": CUSTOM_RULES,
                "use_builtin_rules": False,
            },
        )
        self.assertEqual(run["rules"]["version"], validation["stats"]["version"])
        findings = self.json_get(f"/api/runs/{run['run_id']}/findings")["findings"]
        self.assertEqual(len(findings), 1, findings)
        self.assertEqual(findings[0]["rule_id"], "argv_to_launch")
        self.assertEqual(findings[0]["sink"]["function"], "launch")
        self.assertEqual(findings[0]["severity"], "HIGH")

        # Without the custom rule set the same program is silent: the finding
        # really came from the rule file, not from a built-in rule.
        builtin_only = self.analyse(CUSTOM_SOURCE, filename="custom.ctc")
        self.assertNotEqual(builtin_only["rules"]["version"], validation["stats"]["version"])
        self.assertEqual(
            self.json_get(f"/api/runs/{builtin_only['run_id']}/findings")["count"], 0
        )

    def test_the_active_rule_set_is_reported_as_data(self):
        payload = self.json_get("/api/rules")
        active = payload["active"]
        self.assertTrue(active["version"].startswith("builtin-"))
        self.assertEqual(payload["loader_diagnostics"], [])
        self.assertTrue(active["rules"])
        sources = [rule for rule in active["rules"] if rule["kind"] == "source"]
        sinks = [rule for rule in active["rules"] if rule["kind"] == "sink"]
        flows = [rule for rule in active["rules"] if rule["kind"] == "flow"]
        self.assertEqual(len(sources), active["stats"]["sources"])
        self.assertEqual(len(sinks), active["stats"]["sinks"])
        for entry in sources:
            self.assertTrue(entry["id"])
            self.assertTrue(entry["function"])
        for entry in sinks:
            self.assertTrue(entry["id"])
            self.assertIn("severity", entry)
        self.assertTrue(flows)
        for entry in flows:
            self.assertTrue(entry["sources"], entry)
            self.assertTrue(entry["sinks"], entry)
        # The rule language grammar is reported with the same honesty as the
        # language grammar: states and, if any, conflicts.
        self.assertGreater(payload["rule_language"]["states"], 0)
        self.assertEqual(payload["rule_language"]["conflicts"], 0)
        self.assertGreater(payload["rule_language"]["productions"], 10)


class ExportAndCompareTests(ApiTestCase):
    """Steps 15-18: export a report, fix the source, prove the change."""

    def test_report_export_is_stable_and_the_html_report_is_inert(self):
        example = self.json_get(f"/api/examples/{VULNERABLE}")
        run = self.analyse(example["content"], filename="command_injection.ctc")
        run_id = run["run_id"]

        first = self.json_get(f"/api/runs/{run_id}/report?format=json")
        second = self.json_get(f"/api/runs/{run_id}/report?format=json")
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual(first["schema_version"], "1.0")
        self.assertEqual(first["run"]["run_id"], run_id)
        self.assertEqual(len(first["findings"]), 1)
        self.assertTrue(first["limitations"])
        self.assertEqual(first["input"]["filename"], "command_injection.ctc")

        status, headers, body = self.get(f"/api/runs/{run_id}/report?format=html")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertNotIn("<script", body.lower())
        # The analysed source text appears escaped, so the file cannot inject
        # markup into the report.
        self.assertIn("system(command);", body)
        self.assertIn("Analysis limitations", body)

    def test_a_fix_is_reported_as_resolved_and_not_as_new(self):
        before = self.analyse(PLAIN_SOURCE, filename="before.ctc")
        before_findings = self.json_get(f"/api/runs/{before['run_id']}/findings")["findings"]
        self.assertEqual(len(before_findings), 1)

        after = self.analyse(FIXED_SOURCE, filename="after.ctc")
        self.assertEqual(self.json_get(f"/api/runs/{after['run_id']}/findings")["count"], 0)

        comparison = self.json_post(
            "/api/compare", {"before": before["run_id"], "after": after["run_id"]}
        )
        self.assertEqual(comparison["resolved_ids"], [before_findings[0]["id"]])
        self.assertEqual(comparison["new_ids"], [])
        self.assertEqual(comparison["persistent_ids"], [])
        self.assertEqual(comparison["summary"]["resolved"], 1)
        self.assertEqual(comparison["summary"]["new"], 0)

    def test_inserting_lines_above_a_flow_marks_it_moved_not_new(self):
        before = self.analyse(PLAIN_SOURCE, filename="before.ctc")
        after = self.analyse(SHIFTED_SOURCE, filename="after.ctc")
        comparison = self.json_post(
            "/api/compare", {"before": before["run_id"], "after": after["run_id"]}
        )
        self.assertEqual(comparison["new_ids"], [])
        self.assertEqual(comparison["resolved_ids"], [])
        self.assertEqual(len(comparison["moved_ids"]), 1)
        moved = comparison["moved"][0]
        self.assertEqual(moved["before"]["line"], 3)
        self.assertEqual(moved["after"]["line"], 5)
        self.assertEqual(moved["before"]["severity"], "HIGH")
        self.assertEqual(comparison["summary"]["moved"], 1)

    def test_the_evidence_survives_the_export(self):
        """What the interface shows and what the report says are the same facts."""
        example = self.json_get(f"/api/examples/{VULNERABLE}")
        run = self.analyse(example["content"], filename="command_injection.ctc")
        run_id = run["run_id"]
        finding = self.json_get(f"/api/runs/{run_id}/findings")["findings"][0]
        detail = self.json_get(f"/api/runs/{run_id}/findings/{finding['id']}")
        report = self.json_get(f"/api/runs/{run_id}/report?format=json")
        exported = report["findings"][0]
        self.assertEqual(exported["id"], finding["id"])
        self.assertEqual(exported["sink"]["line"], finding["sink"]["line"])
        self.assertEqual(exported["explanation"], detail["explanation"])
        self.assertEqual(
            [step["kind"] for step in exported["path"]],
            [step["kind"] for step in detail["path"]],
        )


class InterfaceContractTests(ApiTestCase):
    """The interface can only call endpoints the engine really serves."""

    @staticmethod
    def _normalise(path: str) -> str:
        path = path.strip("`").split("?", 1)[0].lstrip("/")
        path = re.sub(r"\$\{[^}]*\}", "", path)  # JavaScript template holes
        path = re.sub(r"\{[^}]*\}", "", path)  # schema placeholders
        return re.sub(r"/+", "/", path).rstrip("/")

    def test_every_endpoint_the_interface_calls_exists(self):
        schemas = self.json_get("/api/schemas")
        declared = {self._normalise(entry["path"]) for entry in schemas["endpoints"]}
        self.assertTrue(declared)

        source = (ROOT / "frontend" / "js" / "api.js").read_text()
        used = {self._normalise(match) for match in re.findall(r"`?(api/[A-Za-z0-9/_{}$.\-]*)", source)}
        self.assertTrue(used)
        unknown = sorted(path for path in used if path not in declared)
        self.assertEqual(unknown, [], f"the interface calls undeclared endpoints: {unknown}")

    def test_the_served_page_has_a_section_and_a_module_for_every_route(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        routes = ["overview", "analyze", "findings", "graph", "dataflow",
                  "slicing", "rules", "reports", "documentation"]
        for route in routes:
            self.assertIn(f'id="view-{route}"', body)
            self.assertIn(f'data-route="{route}"', body)
            module = "docs.js" if route == "documentation" else f"{route}.js"
            self.assertTrue(
                (ROOT / "frontend" / "js" / "views" / module).exists(),
                f"no view module for {route}",
            )
        self.assertNotIn("onclick=", body, "no inline script is needed")
        self.assertNotIn("<script>", body.lower())

    def test_the_interface_never_injects_markup_or_evaluates_source(self):
        # The rule is about code, not about prose: the helpers document the ban
        # in their comments, so the check looks for real uses.
        dangerous = {
            "innerHTML assignment": re.compile(r"\binnerHTML\b\s*(\+?=)"),
            "outerHTML assignment": re.compile(r"\bouterHTML\b\s*(\+?=)"),
            "eval call": re.compile(r"(?:^|[^.\w])eval\s*\("),
            "Function constructor": re.compile(r"\bnew\s+Function\b"),
            "document.write": re.compile(r"\bdocument\.write\b"),
        }
        for path in sorted((ROOT / "frontend" / "js").rglob("*.js")):
            text = path.read_text()
            for label, pattern in dangerous.items():
                self.assertIsNone(pattern.search(text), f"{path} uses {label}")
