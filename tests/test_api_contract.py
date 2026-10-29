"""HTTP API contracts: error schema, documented limits and truncation
indicators (audit defects D13/D22/D23; docs/API.md §7, docs/LIMITATIONS.md §1.4).

A real ThreadingHTTPServer is started on an ephemeral port for this module —
the same ``create_server`` the documented startup command uses — so the tests
exercise the wire format users see, not an internal call path.
"""

import json
import threading
import unittest
import urllib.error
import urllib.request

from codetrace.api.server import create_server

_server = None
_thread = None
BASE = None


def setUpModule():
    global _server, _thread, BASE
    _server = create_server("127.0.0.1", 0, verbose=False)
    BASE = f"http://127.0.0.1:{_server.server_address[1]}"
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()


def tearDownModule():
    _server.shutdown()
    _server.server_close()
    _thread.join(timeout=5)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as response:
        return response.status, json.loads(response.read())


def post(path, payload):
    request = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.status, json.loads(response.read())


def call(path, payload=None):
    """(status, body) for success and error responses alike."""
    try:
        if payload is None:
            return get(path)
        return post(path, payload)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, raw


def analyse(source, filename="t.ctc", **extra):
    status, body = call("/api/analyze", {"source": source, "filename": filename, **extra})
    assert status == 200, body
    return body


SIMPLE = 'int main() { string name = input(); system(name); return 0; }'


class TestHealthAndErrors(unittest.TestCase):
    def test_health(self):
        status, body = get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_error_schema_is_uniform(self):
        for path, payload, want_status, want_code in (
            ("/api/runs/ffffffffffffffff", None, 404, "run-not-found"),
            ("/api/analyze", {"filename": "t.ctc"}, 400, "missing-source"),
            ("/api/analyze", {"source": SIMPLE, "filename": "t.ctc", "parser_mode": "earley"},
             400, "invalid-parser-mode"),
            ("/api/rules/validate", {}, 400, "missing-rules"),
            ("/api/compare", {"before": "ffffffffffffffff", "after": "eeeeeeeeeeeeeeee"},
             404, "run-not-found"),
        ):
            status, body = call(path, payload)
            self.assertEqual(status, want_status, (path, body))
            self.assertEqual(body["error"]["code"], want_code, (path, body))
            self.assertTrue(body["error"]["message"])
            self.assertIn("detail", body["error"])

    def test_broken_rules_on_analyze_are_422(self):
        status, body = call("/api/analyze",
                            {"source": SIMPLE, "filename": "t.ctc",
                             "rules": "version 1\nsink } broken {"})
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["code"], "invalid-rules")

    def test_validate_endpoint_reports_instead_of_failing(self):
        status, body = call("/api/rules/validate", {"rules": "version 1\nsink } broken {"})
        self.assertEqual(status, 200)
        self.assertFalse(body["valid"])
        self.assertTrue(any(d["severity"] == "error" for d in body["diagnostics"]))

    def test_statement_endpoint_id_contracts(self):
        run = analyse(SIMPLE)
        run_id = run["run_id"]
        status, _body = call(f"/api/runs/{run_id}/statements/999999")
        self.assertEqual(status, 404)
        status, _body = call(f"/api/runs/{run_id}/statements/not-a-number")
        self.assertEqual(status, 400)


class TestDocumentedLimits(unittest.TestCase):
    def test_function_cap_is_applied_and_announced(self):
        functions = "\n".join(f"int f{i}() {{ return {i}; }}" for i in range(450))
        run = analyse(f"{functions}\nint main() {{ return f0(); }}", filename="many.ctc")
        self.assertEqual(len(run["summary"]["functions"]), 400)
        self.assertTrue(any("451" in note and "400" in note for note in run["limits_hit"]),
                        run["limits_hit"])

    def test_statement_index_cap_and_addressability(self):
        body = "\n".join(f"  int v{i} = {i};" for i in range(2000))
        run = analyse(f"int main() {{\n{body}\n  v1999 = v1998;\n  v1998 = v1999;\n  return 0;\n}}",
                      filename="big.ctc")
        self.assertEqual(len(run["statements"]), 2000)
        self.assertGreater(run["metrics"]["statements"], 2000)
        # Statements beyond the index stay addressable by sid — the documented
        # contract that makes the cap honest.
        status, detail = get(f"/api/runs/{run['run_id']}/statements/2001")
        self.assertEqual(status, 200)
        self.assertEqual(detail["sid"], 2001)

    def test_slice_detail_truncation_is_disclosed(self):
        lines = ["int main() {", "  int v0 = 0;"]
        lines += [f"  int v{i} = v{i - 1} + 1;" for i in range(1, 2100)]
        lines += ["  return v2099;", "}"]
        run = analyse("\n".join(lines), filename="chain.ctc")
        status, slice_payload = get(f"/api/runs/{run['run_id']}/slice?sid=2100&direction=backward")
        self.assertEqual(status, 200)
        self.assertGreater(len(slice_payload["statements"]), 2000)
        self.assertEqual(len(slice_payload["statements_detail"]), 2000)
        self.assertTrue(slice_payload["statements_detail_truncated"])
        self.assertFalse(slice_payload["truncated"],
                         "the slice itself is complete; only the detail table is capped")

    def test_small_slice_is_not_marked_truncated(self):
        run = analyse(SIMPLE)
        finding_id = run["findings"][0]["id"]
        status, payload = get(f"/api/runs/{run['run_id']}/findings/{finding_id}/slice")
        self.assertEqual(status, 200)
        self.assertFalse(payload["statements_detail_truncated"])
        self.assertEqual(len(payload["statements_detail"]), len(payload["statements"]))

    def test_oversized_source_is_413(self):
        status, body = call("/api/analyze", {"source": "int main() { return 0; }" + " " * (1024 * 1200),
                                             "filename": "huge.ctc"})
        self.assertEqual(status, 413)
        self.assertIn(body["error"]["code"], ("payload-too-large", "source-too-large"))

    def test_graph_limit_truncates_honestly(self):
        body = "\n".join(f"  int v{i} = {i};" for i in range(600))
        run = analyse(f"int main() {{\n{body}\n  return 0;\n}}", filename="g.ctc")
        status, graph = get(f"/api/runs/{run['run_id']}/graph?limit=5")
        self.assertEqual(status, 200)
        self.assertTrue(graph["truncated"])
        self.assertLessEqual(len(graph["nodes"]), 5)


class TestDataFlowEndpoints(unittest.TestCase):
    PROGRAM = 'int main() { int x = 1; x = 2; int y = x; return y; }'

    def test_reaching_definitions_kill_previous_definition(self):
        run = analyse(self.PROGRAM)
        y_sid = next(s["sid"] for s in run["statements"] if "y = x" in s["text"])
        status, payload = get(f"/api/runs/{run['run_id']}/dataflow?function=main&analysis=reaching")
        self.assertEqual(status, 200)
        self.assertTrue(payload["converged"])
        self.assertEqual(payload["direction"], "forward")
        # At 'int y = x;' the first definition of x has been killed by the
        # redefinition: exactly one definition of x reaches, and it is not d0.
        reaching_in = payload["statement_states"][str(y_sid)]["in"]
        self.assertEqual(len(reaching_in), 1, reaching_in)
        self.assertNotIn("d0", reaching_in)

    def test_liveness_backward(self):
        run = analyse(self.PROGRAM)
        status, payload = get(f"/api/runs/{run['run_id']}/dataflow?function=main&analysis=liveness")
        self.assertEqual(status, 200)
        self.assertEqual(payload["direction"], "backward")
        self.assertTrue(payload["converged"])

    def test_unknown_function_is_404(self):
        run = analyse(self.PROGRAM)
        status, body = call(f"/api/runs/{run['run_id']}/dataflow?function=ghost&analysis=reaching")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "function-not-found")


class TestRunLifecycle(unittest.TestCase):
    def test_z_eviction_after_24_runs(self):
        # Named test_z_* so it runs last: the run store is process-global and
        # eviction would pull runs out from under the other tests.
        first = analyse('int main() { return 1; }', filename="evict0.ctc")
        for i in range(1, 25):
            analyse(f"int main() {{ return {i}; }}", filename=f"evict{i}.ctc")
        status, body = call(f"/api/runs/{first['run_id']}")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "run-not-found")


if __name__ == "__main__":
    unittest.main()
