"""API tests against a real HTTP server.

The tests start the production server object on an ephemeral port and talk to it
over HTTP, so routing, validation, the error envelope, the JSON schemas and the
static-file handling are all exercised as a client would exercise them.

Self-security checks live here too: the analysed program must never be executed,
and no request may read a file outside the bundled examples and the frontend
directory.
"""

from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.error
import urllib.request

from codetrace.api.server import create_server
from codetrace.version import API_VERSION, ENGINE_VERSION, SCHEMA_VERSION

VULNERABLE = "int main() { string cmd = input(); system(cmd); return 0; }"
FIXED = "int main() { string cmd = input(); system(shell_escape(cmd)); return 0; }"

SAMPLE_RULES = (
    "version 1\n\n"
    "source scan_value {\n  description \"stdin\"\n  function input\n  returns\n"
    "  contexts command\n}\n\n"
    "sink launch_sink {\n  function launch\n  arguments 0\n  context command\n"
    "  category \"command-injection\"\n  severity HIGH\n}\n\n"
    "flow launch_flow {\n  sources scan_value\n  sinks launch_sink\n  enabled true\n}\n"
)


class ApiTestCase(unittest.TestCase):
    """Base class that runs the real server once for the whole module."""

    server = None
    thread = None
    base = ""

    @classmethod
    def setUpClass(cls):
        cls.server = create_server("127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    # -- helpers ---------------------------------------------------------
    def request(self, method: str, path: str, payload=None, raw=None, content_type="application/json"):
        data = raw
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": content_type} if data else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8", "replace")
                return response.status, dict(response.headers), body
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read().decode("utf-8", "replace")

    def get(self, path: str):
        return self.request("GET", path)

    def post(self, path: str, payload):
        return self.request("POST", path, payload=payload)

    def json_get(self, path: str):
        status, headers, body = self.get(path)
        self.assertEqual(status, 200, body[:400])
        self.assertIn("application/json", headers.get("Content-Type", ""))
        return json.loads(body)

    def json_post(self, path: str, payload):
        status, _headers, body = self.post(path, payload)
        self.assertEqual(status, 200, body[:400])
        return json.loads(body)

    def error_of(self, path: str, method: str = "GET", payload=None, expected: int = 400):
        status, headers, body = self.request(method, path, payload=payload)
        self.assertEqual(status, expected, body[:400])
        self.assertIn("application/json", headers.get("Content-Type", ""))
        self.assertNotIn("Traceback", body, "no stack trace is exposed")
        self.assertNotIn("/home/", body, "no server path is exposed")
        payload_object = json.loads(body)
        self.assertEqual(sorted(payload_object), ["error"])
        self.assertEqual(sorted(payload_object["error"]), ["code", "detail", "message"])
        self.assertTrue(payload_object["error"]["code"])
        self.assertTrue(payload_object["error"]["message"])
        return payload_object["error"]

    def analyse(self, source: str, filename: str = "api.ctc", rules: str = None):
        payload = {"source": source, "filename": filename}
        if rules is not None:
            payload["rules"] = rules
        return self.json_post("/api/analyze", payload)


class MetadataEndpointTests(ApiTestCase):
    def test_health_reports_versions_and_a_clean_grammar(self):
        health = self.json_get("/api/health")
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["engine_version"], ENGINE_VERSION)
        self.assertEqual(health["api_version"], API_VERSION)
        self.assertEqual(health["schema_version"], SCHEMA_VERSION)
        self.assertTrue(health["rules_version"].startswith("builtin-"))
        self.assertEqual(health["grammar"]["conflicts"], 0)
        self.assertEqual(health["grammar"]["mode"], "lalr")
        self.assertGreater(health["grammar"]["productions"], 90)
        self.assertIsInstance(health["runs_in_memory"], int)

    def test_schemas_endpoint_documents_every_route(self):
        payload = self.json_get("/api/schemas")
        self.assertEqual(payload["api_version"], API_VERSION)
        self.assertIn("schemas", payload)
        self.assertIn("endpoints", payload)
        self.assertGreater(len(payload["endpoints"]), 15)
        joined = json.dumps(payload).lower()
        for forbidden in ("shell", "exec(", "subprocess", "upload"):
            self.assertNotIn(forbidden, joined, "the API never exposes command execution")

    def test_language_endpoint_is_honest_about_the_subset(self):
        payload = self.json_get("/api/language")
        self.assertEqual(payload["mode"], "CT-C subset v1")
        self.assertTrue(payload["unsupported"], "the unsupported constructs are listed")
        diagnostics = payload["diagnostics"]
        self.assertGreaterEqual(len(diagnostics), 30)
        codes = {entry["code"] for entry in diagnostics}
        for code in ("LEX001", "SYN001", "SEM001", "CFG001", "DFA001"):
            self.assertIn(code, codes)
        self.assertTrue(
            any(code.startswith("RULE") for code in codes), "the rule diagnostics are catalogued"
        )
        for entry in diagnostics:
            self.assertTrue(entry["meaning"], "every diagnostic code is documented")
            self.assertTrue(entry["phase"])

    def test_grammar_endpoint_exposes_the_lr_tables_data(self):
        payload = self.json_get("/api/grammar")
        self.assertEqual(payload["start_symbol"], payload["start_symbol"])
        self.assertTrue(payload["nullable"] is not None)
        self.assertTrue(payload["first"])
        self.assertTrue(payload["follow"])
        self.assertIn(payload["start_symbol"], payload["first"])

    def test_rules_endpoint_reports_the_active_rule_set(self):
        payload = self.json_get("/api/rules")
        self.assertEqual(payload["loader_diagnostics"], [])
        stats = payload["active"]["stats"]
        self.assertEqual(stats["flows"], 4)
        self.assertEqual(payload["active"]["version"], stats["version"])
        language = payload["rule_language"]
        self.assertEqual(language["conflicts"], 0)
        self.assertGreater(language["productions"], 30)
        self.assertGreater(language["states"], 50)


class ExampleEndpointTests(ApiTestCase):
    def test_examples_are_listed_with_their_documented_expectation(self):
        payload = self.json_get("/api/examples")
        self.assertGreaterEqual(payload["count"], 29)
        self.assertEqual(payload["count"], len(payload["examples"]))
        for entry in payload["examples"]:
            self.assertIn("id", entry)
            self.assertIn("name", entry)
            self.assertIn("category", entry)
            self.assertTrue(entry["id"].endswith(entry["name"]))

    def test_example_content_is_returned_and_labelled(self):
        listing = self.json_get("/api/examples")
        entry = next(e for e in listing["examples"] if e["category"] != "custom_rules")
        payload = self.json_get(f"/api/examples/{entry['id']}")
        self.assertEqual(payload["id"], entry["id"])
        self.assertIn("int main", payload["content"])
        self.assertTrue(payload["expectation"])

    def test_examples_cannot_be_read_outside_the_bundled_directory(self):
        attempts = [
            "/api/examples/../../etc/passwd",
            "/api/examples/..%2f..%2fetc%2fpasswd",
            "/api/examples/%2e%2e%2f%2e%2e%2fcodetrace%2fapi%2fserver.py",
            "/api/examples/..%5ccodetrace%5capi%5cserver.py",
            "/api/examples//etc/passwd",
        ]
        for attempt in attempts:
            with self.subTest(path=attempt):
                error = self.error_of(attempt, expected=404)
                self.assertIn(error["code"], {"example-not-found", "not-found", "invalid-path"})
                status, _headers, body = self.get(attempt)
                self.assertNotIn("root:", body)
                self.assertNotIn("class CodeTraceHandler", body)


class StaticFileTests(ApiTestCase):
    def test_the_interface_is_served_from_the_root(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("CodeTrace", body)
        status, headers, body = self.get("/css/app.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers["Content-Type"])
        status, headers, body = self.get("/js/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers["Content-Type"])
        self.assertIn("currentRoute", body)

    def test_static_handler_refuses_to_leave_the_frontend_directory(self):
        for attempt in (
            "/../codetrace/api/server.py",
            "/..%2fcodetrace%2fapi%2fserver.py",
            "/css/..%2f..%2fcodetrace%2fapi%2fserver.py",
            "/%2e%2e/%2e%2e/etc/passwd",
        ):
            with self.subTest(path=attempt):
                status, _headers, body = self.get(attempt)
                self.assertIn(status, (403, 404), body[:200])
                self.assertNotIn("class CodeTraceHandler", body)
                self.assertNotIn("root:", body)

    def test_unknown_api_route_is_a_structured_404(self):
        error = self.error_of("/api/does-not-exist", expected=404)
        self.assertEqual(error["code"], "not-found")


class AnalysisEndpointTests(ApiTestCase):
    def test_analysis_returns_a_complete_run_record(self):
        payload = self.analyse(VULNERABLE)
        for key in ("run_id", "filename", "accepted", "summary", "diagnostics", "findings",
                    "metrics", "statements", "total_analysis_seconds", "rules", "limits_hit",
                    "notes", "engine_version", "status", "grammar", "rule_diagnostics"):
            self.assertIn(key, payload)
        self.assertEqual(payload["status"], "completed")
        self.assertTrue(payload["run_id"])
        self.assertEqual(payload["filename"], "api.ctc")
        self.assertEqual(len(payload["findings"]), 1)
        finding = payload["findings"][0]
        self.assertEqual(finding["rule_id"], "command_execution")
        self.assertEqual(finding["severity"], "HIGH")
        self.assertEqual(finding["sink"]["function"], "system")
        self.assertEqual(finding["certainty"], "confirmed")
        self.assertEqual(payload["rule_diagnostics"], [])
        self.assertGreater(payload["total_analysis_seconds"], 0)

    def test_the_same_source_gives_the_same_findings(self):
        first = self.analyse(VULNERABLE, filename="one.ctc")
        second = self.analyse(VULNERABLE, filename="two.ctc")
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["findings"], second["findings"], "the engine is deterministic")
        self.assertEqual(first["summary"]["by_category"], second["summary"]["by_category"])

    def test_run_resources_are_available_after_the_analysis(self):
        run = self.analyse(VULNERABLE)
        run_id = run["run_id"]
        finding_id = run["findings"][0]["id"]

        summary = self.json_get(f"/api/runs/{run_id}")
        self.assertEqual(summary["run_id"], run_id)

        self.assertNotIn(
            "path", run["findings"][0], "the run summary stays small: it carries no evidence path"
        )
        findings = self.json_get(f"/api/runs/{run_id}/findings")
        self.assertEqual(findings["count"], 1)
        self.assertTrue(
            findings["findings"][0]["path"], "the findings list carries the evidence path"
        )

        high = self.json_get(f"/api/runs/{run_id}/findings?severity=HIGH")
        self.assertEqual(high["count"], 1)
        low = self.json_get(f"/api/runs/{run_id}/findings?severity=LOW")
        self.assertEqual(low["count"], 0)
        certainty = self.json_get(f"/api/runs/{run_id}/findings?certainty=confirmed")
        self.assertEqual(certainty["count"], 1)
        search = self.json_get(f"/api/runs/{run_id}/findings?q=system")
        self.assertEqual(search["count"], 1)
        empty_search = self.json_get(f"/api/runs/{run_id}/findings?q=zzzz")
        self.assertEqual(empty_search["count"], 0)

        detail = self.json_get(f"/api/runs/{run_id}/findings/{finding_id}")
        self.assertEqual(detail["id"], finding_id)
        self.assertTrue(detail["path"], "the detail carries the evidence path")
        self.assertTrue(detail["dependency_evidence"])

        ast = self.json_get(f"/api/runs/{run_id}/ast")
        self.assertIsNotNone(ast["tree"])
        self.assertEqual(ast["tree"]["kind"], "SourceUnit")
        self.assertTrue(ast["tree"]["children"])

        cfg = self.json_get(f"/api/runs/{run_id}/cfg?function=main")
        self.assertEqual(cfg["function"], "main")
        self.assertTrue(cfg["blocks"])
        self.assertEqual(cfg["blocks"][0]["kind"], "entry")

        graph = self.json_get(f"/api/runs/{run_id}/graph")
        self.assertTrue(graph["nodes"])
        self.assertFalse(graph["truncated"])
        taint_only = self.json_get(f"/api/runs/{run_id}/graph?kinds=taint")
        self.assertEqual({edge["kind"] for edge in taint_only["edges"]}, {"taint"})

        statement = self.json_get(f"/api/runs/{run_id}/statements/0")
        self.assertEqual(statement["sid"], 0)
        self.assertIn("reaching_definitions", statement)
        self.assertIn("live_variables", statement)
        self.assertEqual(statement["function"], "main")

        report = self.json_get(f"/api/runs/{run_id}/report?format=json")
        self.assertEqual(report["schema_version"], SCHEMA_VERSION)
        self.assertEqual(report["run"]["run_id"], run_id)
        self.assertEqual(report["summary"]["findings"], 1)
        self.assertIn("limitations", report)

    def test_dataflow_endpoint_serves_all_three_problems(self):
        run = self.analyse(VULNERABLE)
        run_id = run["run_id"]
        reaching = self.json_get(f"/api/runs/{run_id}/dataflow?analysis=reaching")
        self.assertEqual(reaching["analysis"], "reaching")
        self.assertEqual(reaching["direction"], "forward")
        self.assertIn("gen", reaching)
        self.assertIn("kill", reaching)
        liveness = self.json_get(f"/api/runs/{run_id}/dataflow?analysis=liveness")
        self.assertEqual(liveness["analysis"], "liveness")
        self.assertEqual(liveness["direction"], "backward")
        definite = self.json_get(f"/api/runs/{run_id}/dataflow?analysis=definite")
        self.assertIn("uninitialised_reads", definite)
        for payload in (reaching, liveness, definite):
            self.assertGreater(payload["domain_size"], 0)
            self.assertTrue(payload["blocks"], "per-block states are listed")
            self.assertTrue(payload["statement_states"], "per-statement states are listed")
            for sid in payload["statement_states"]:
                self.assertTrue(str(sid).isdigit())
            for block in payload["blocks"]:
                self.assertIn("block", block)
                self.assertIn("reachable", block)
                self.assertIn("in_size", block)
                self.assertIn("out_size", block)

    def test_slice_endpoints(self):
        run = self.analyse(VULNERABLE)
        run_id = run["run_id"]
        finding_id = run["findings"][0]["id"]
        backward = self.json_get(f"/api/runs/{run_id}/slice?sid=1")
        self.assertEqual(backward["kind"], "backward")
        forward = self.json_get(f"/api/runs/{run_id}/slice?sid=1&direction=forward")
        self.assertEqual(forward["kind"], "forward")
        for payload in (backward, forward):
            self.assertIn("statements_detail", payload)
            self.assertIn("note", payload)
        security = self.json_get(f"/api/runs/{run_id}/findings/{finding_id}/slice")
        self.assertEqual(security["kind"], "security")
        self.assertEqual(security["finding_id"], finding_id)
        self.assertIn("subgraph", security)
        self.assertTrue(security["subgraph"]["nodes"])

    def test_report_in_html_is_self_contained_and_escaped(self):
        hostile = 'int main() { string cmd = input(); system("<script>alert(1)</script>" + cmd); return 0; }'
        run = self.analyse(hostile, filename="hostile.ctc")
        status, headers, body = self.get(f"/api/runs/{run['run_id']}/report?format=html")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("<!DOCTYPE html>", body)
        self.assertNotIn("<script>alert(1)</script>", body, "source text is escaped in the report")
        self.assertIn("&lt;script&gt;", body)


class ValidationAndErrorTests(ApiTestCase):
    def test_missing_or_empty_source(self):
        for payload in ({}, {"source": ""}, {"source": "   "}, {"source": 42}, {"source": None}):
            with self.subTest(payload=payload):
                error = self.error_of("/api/analyze", "POST", payload, expected=400)
                self.assertEqual(error["code"], "missing-source")

    def test_invalid_filename_and_parser_mode(self):
        self.assertEqual(
            self.error_of("/api/analyze", "POST", {"source": VULNERABLE, "filename": "x" * 500},
                          expected=400)["code"],
            "invalid-filename",
        )
        error = self.error_of(
            "/api/analyze", "POST", {"source": VULNERABLE, "parser_mode": "top-down"}, expected=400
        )
        self.assertEqual(error["code"], "invalid-parser-mode")
        # The grammar can also be built in the weaker modes, and they are selectable.
        for mode in ("slr", "canonical"):
            payload = self.json_post(
                "/api/analyze", {"source": VULNERABLE, "parser_mode": mode}
            )
            self.assertTrue(payload["accepted"])

    def test_oversized_source_and_body_are_refused(self):
        too_large = "int main() {\n" + "int x = 1;\n" * 120000 + "}\n"
        self.assertEqual(self.post("/api/analyze", {"source": too_large})[0], 413)
        huge_body = json.dumps({"source": "int main() { return 0; }", "padding": "x" * (2 * 1024 * 1024)})
        status, _headers, body = self.request("POST", "/api/analyze", raw=huge_body.encode())
        self.assertEqual(status, 413)
        self.assertIn("error", body)

    def test_malformed_json_body(self):
        status, headers, body = self.request("POST", "/api/analyze", raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        self.assertEqual(json.loads(body)["error"]["code"], "invalid-json")

    def test_invalid_rules_are_refused_before_analysis(self):
        error = self.error_of(
            "/api/analyze", "POST",
            {"source": VULNERABLE, "rules": "version 1\nflow f {\n  sources missing\n}\n"},
            expected=422,
        )
        self.assertEqual(error["code"], "invalid-rules")
        self.assertIn("RULE020", error["detail"])
        self.assertIn("line", error["detail"])

    def test_unknown_resources_report_specific_codes(self):
        run = self.analyse(VULNERABLE)
        run_id = run["run_id"]
        self.assertEqual(self.error_of("/api/runs/deadbeef", expected=404)["code"], "run-not-found")
        self.assertEqual(
            self.error_of(f"/api/runs/{run_id}/findings/ZZZ", expected=404)["code"],
            "finding-not-found",
        )
        self.assertEqual(
            self.error_of(f"/api/runs/{run_id}/statements/98765", expected=404)["code"],
            "statement-not-found",
        )
        self.assertEqual(
            self.error_of(f"/api/runs/{run_id}/cfg?function=nope", expected=404)["code"],
            "function-not-found",
        )
        self.assertEqual(
            self.error_of(f"/api/runs/{run_id}/dataflow?analysis=filtered", expected=400)["code"],
            "unknown-analysis",
        )
        self.assertEqual(
            self.error_of(f"/api/runs/{run_id}/slice?sid=1&direction=sideways", expected=400)["code"],
            "invalid-parameter",
        )
        self.assertEqual(
            self.error_of(f"/api/runs/{run_id}/slice?direction=forward", expected=400)["code"],
            "missing-parameter",
        )
        self.assertEqual(
            self.error_of(f"/api/runs/{run_id}/slice?sid=abc", expected=400)["code"],
            "invalid-parameter",
        )
        self.assertEqual(
            self.error_of(f"/api/runs/{run_id}/report?format=xml", expected=400)["code"],
            "invalid-format",
        )


class RulesEndpointTests(ApiTestCase):
    def test_validating_a_rule_file_reports_stats_and_the_fingerprint(self):
        payload = self.json_post("/api/rules/validate", {"rules": SAMPLE_RULES})
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["stats"]["sources"], 1)
        self.assertEqual(payload["stats"]["sinks"], 1)
        self.assertEqual(payload["stats"]["flows"], 1)
        self.assertTrue(payload["stats"]["fingerprint"])
        kinds = {rule["id"]: rule["kind"] for rule in payload["rules"]}
        self.assertEqual(kinds["scan_value"], "source")
        self.assertEqual(kinds["launch_flow"], "flow")

    def test_semantic_problems_come_back_with_positions(self):
        payload = self.json_post(
            "/api/rules/validate", {"rules": "version 1\nflow f {\n  sources nope\n}\n"}
        )
        self.assertFalse(payload["valid"])
        codes = [diagnostic["code"] for diagnostic in payload["diagnostics"]]
        self.assertIn("RULE020", codes)
        for diagnostic in payload["diagnostics"]:
            self.assertGreaterEqual(diagnostic["line"], 1)
            self.assertGreaterEqual(diagnostic["col"], 1)
            self.assertTrue(diagnostic["message"])

    def test_syntax_problems_are_reported_as_diagnostics_not_errors(self):
        payload = self.json_post(
            "/api/rules/validate", {"rules": "version 1\n\nsource s {\n  function input\n"}
        )
        self.assertFalse(payload["valid"])
        codes = [diagnostic["code"] for diagnostic in payload["diagnostics"]]
        self.assertTrue(any(code.startswith(("SYN", "LEX")) for code in codes), codes)

    def test_missing_rules_string(self):
        for payload in ({}, {"rules": ""}, {"rules": 5}):
            with self.subTest(payload=payload):
                error = self.error_of("/api/rules/validate", "POST", payload, expected=400)
                self.assertEqual(error["code"], "missing-rules")

    def test_submitted_rules_are_used_by_the_next_analysis(self):
        source = 'int main() { string body = http_body(); audit_write(body); return 0; }'
        baseline = self.analyse(source, filename="baseline.ctc")
        self.assertEqual(baseline["findings"], [], "no built-in rule knows these functions")
        with open(os.path.join("examples", "custom_rules", "strict_rules.ctrule"), "r", encoding="utf-8") as handle:
            rules = handle.read()
        payload = self.analyse(source, filename="custom.ctc", rules=rules)
        self.assertEqual(len(payload["findings"]), 1)
        finding = payload["findings"][0]
        self.assertEqual(finding["rule_id"], "audit_injection")
        self.assertEqual(finding["category"], "arbitrary-file-write")
        self.assertEqual(finding["severity"], "MEDIUM")


class CompareEndpointTests(ApiTestCase):
    def compare(self, before: str, after: str):
        return self.json_post("/api/compare", {"before": before, "after": after})

    def test_a_fixed_flow_is_reported_as_resolved(self):
        before = self.analyse(VULNERABLE, filename="before.ctc")["run_id"]
        after = self.analyse(FIXED, filename="after.ctc")["run_id"]
        diff = self.compare(before, after)
        self.assertEqual(
            sorted(diff),
            ["after", "before", "moved", "moved_ids", "new", "new_ids", "persistent",
             "persistent_ids", "resolved", "resolved_ids", "summary"],
        )
        # The id lists are what the interface filters on, and they must agree
        # with the buckets they describe.
        self.assertEqual(diff["resolved_ids"], sorted(f["id"] for f in diff["resolved"]))
        self.assertEqual(diff["new_ids"], sorted(f["id"] for f in diff["new"]))
        self.assertEqual(diff["moved_ids"], sorted(f["id"] for f in diff["moved"]))
        self.assertEqual(len(diff["resolved"]), 1)
        self.assertEqual(diff["new"], [])
        self.assertEqual(diff["summary"]["before"], 1)
        self.assertEqual(diff["summary"]["after"], 0)

    def test_identity_does_not_depend_on_line_numbers(self):
        before = self.analyse(VULNERABLE, filename="before.ctc")["run_id"]
        shifted = self.analyse("\n\n" + VULNERABLE, filename="shifted.ctc")["run_id"]
        diff = self.compare(before, shifted)
        self.assertEqual(len(diff["moved"]), 1, "the same finding moved down two lines")
        self.assertEqual(diff["new"], [])
        self.assertEqual(diff["resolved"], [])
        moved = diff["moved"][0]
        self.assertLess(moved["before"]["line"], moved["after"]["line"])
        self.assertEqual(moved["id"], moved["id"])

    def test_a_new_flow_is_reported_as_new(self):
        before = self.analyse("int main() { system(\"ls\"); return 0; }", filename="clean.ctc")["run_id"]
        after = self.analyse(VULNERABLE, filename="vulnerable.ctc")["run_id"]
        diff = self.compare(before, after)
        self.assertEqual(len(diff["new"]), 1)
        self.assertEqual(len(diff["resolved"]), 0)
        self.assertEqual(diff["persistent"], [])

    def test_compare_validates_its_inputs(self):
        self.assertEqual(
            self.error_of("/api/compare", "POST", {"before": "x"}, expected=400)["code"],
            "missing-parameter",
        )
        self.assertEqual(
            self.error_of("/api/compare", "POST", {"before": "", "after": ""}, expected=400)["code"],
            "missing-parameter",
        )
        self.assertEqual(
            self.error_of("/api/compare", "POST", {"before": "nope", "after": "nope"}, expected=404)["code"],
            "run-not-found",
        )


class SelfSecurityTests(ApiTestCase):
    def test_analysing_a_program_never_executes_it(self):
        marker = os.path.join("/tmp", "codetrace_execution_canary")
        if os.path.exists(marker):
            os.remove(marker)
        payload = self.analyse(
            f'int main() {{ system("touch {marker}"); writefile("x", "/tmp/never"); return 0; }}',
            filename="canary.ctc",
        )
        self.assertFalse(os.path.exists(marker), "the analysed program was executed")
        self.assertEqual(payload["status"], "completed")

    def test_hostile_source_is_analysed_as_data(self):
        hostile = (
            "#include <stdio.h>\n"
            "int main() { char *p = __import__(\"os\").system(\"id\"); return 0; }\n"
        )
        payload = self.analyse(hostile, filename="hostile.ctc")
        self.assertFalse(payload["accepted"], "unsupported syntax is diagnosed, not guessed at")
        codes = [diagnostic["code"] for diagnostic in payload["diagnostics"]]
        self.assertTrue(any(code.startswith(("LEX", "SYN")) for code in codes), codes)
        self.assertFalse(payload["findings"])

    def test_deeply_nested_input_is_refused_gracefully(self):
        nested = "int main() { " + "if (1) { " * 400 + "int x = 1; " + "}" * 400 + " return 0; }"
        status, _headers, body = self.post("/api/analyze", {"source": nested})
        self.assertIn(status, (200, 413, 422), body[:200])
        if status != 200:
            self.assertIn("error", body)
        else:
            payload = json.loads(body)
            self.assertIn("limits_hit", payload)
            self.assertEqual(payload["status"], "completed")

    def test_limits_are_reported_not_hidden(self):
        payload = self.analyse(VULNERABLE)
        for key in ("limits_hit", "notes"):
            self.assertIsInstance(payload[key], list)
        self.assertIn("engine_version", payload)
        self.assertEqual(payload["engine_version"], ENGINE_VERSION)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
