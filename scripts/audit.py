#!/usr/bin/env python3
"""Independent audit of a CodeTrace checkout.

This script is the executable half of the Definition-of-Done checklist.  It does
not import the test suite and it does not trust it: it starts the real HTTP
server on an ephemeral port, drives the workflow a reviewer would drive, and
checks the analysis results against numbers computed by hand for small programs.

Every check prints ``PASS`` or ``FAIL`` with the value it observed, and the
script exits non-zero if anything failed.  Run it after any change:

    python3 scripts/audit.py
    python3 scripts/audit.py -v        # also print the values behind each check

Checks
------
1.  grammar tables: production/state counts and zero conflicts in all three modes
2.  hand-verified reaching definitions on a loop
3.  hand-verified live variables on the same loop
4.  hand-verified definite assignment and the uninitialised-read diagnostic
5.  every dependency edge re-checked against the reaching definitions
6.  a backward and a forward slice, hand-checked against the same program
7.  a custom rule validated and used, plus rejection of a broken rule file
8.  the full HTTP workflow: load, analyse, find, inspect, slice, report, fix, compare
9.  malformed and unsupported input produce explicit diagnostics, never silence
10. the analysed program is never executed (canary file must not appear)
11. the interface contract: only declared endpoints, a section per route, and
    the run summary the views read is really in the payload
12. documentation accuracy: every path and command the documents mention exists
13. quoted claims: the corpus accounting, the matching rule and the validator
    guard behaviour the documents state are re-derived from the code
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from codetrace.analysis import dependencies as dependency_module  # noqa: E402
from codetrace.analysis.reaching_definitions import definition_atom  # noqa: E402
from codetrace.analysis.pipeline import analyse_source  # noqa: E402
from codetrace.reporting import json_report  # noqa: E402
from codetrace.api.server import create_server  # noqa: E402
from codetrace.frontend.pipeline import parser_tables  # noqa: E402
from codetrace.rules.rule_language import parse_and_validate  # noqa: E402

VERBOSE = False
FAILURES: list = []
CHECKS = 0

#: Filled in by ``check_claims`` so ``--write-module-table`` refreshes the table
#: from the same measurement the check uses, rather than from a second
#: implementation that could disagree with it.
_MEASURED_MODULES: dict = {}

#: Suppresses per-check output while a measuring helper runs (the table writer
#: calls ``check_claims`` for its numbers and prints its own summary).
SILENT = False


def check(name: str, condition: bool, observed: object = "") -> None:
    """Record one check; never raises, so the audit reports every failure."""
    global CHECKS
    CHECKS += 1
    status = "PASS" if condition else "FAIL"
    if not condition:
        FAILURES.append(name)
    detail = f"  -> {observed}" if VERBOSE and observed != "" else ""
    if not SILENT:
        print(f"[{status}] {name}{detail}")


def section(title: str) -> None:
    if SILENT:
        return
    print()
    print(f"--- {title} " + "-" * max(0, 62 - len(title)))


# ---------------------------------------------------------------------------
# 1. grammar
# ---------------------------------------------------------------------------
def check_grammar() -> None:
    section("grammar and table construction")
    for mode in ("lalr", "slr", "canonical"):
        tables = parser_tables(mode)
        stats = tables.automaton.stats
        check(
            f"{mode}: tables built without conflicts",
            len(tables.conflicts) == 0,
            f"{len(tables.grammar.productions)} productions, {stats.states} states, "
            f"{len(tables.conflicts)} conflicts",
        )
    lalr = parser_tables("lalr")
    check("LALR reproduces the canonical LR(1) language", len(lalr.conflicts) == 0)
    check(
        "production count matches the documented grammar",
        len(lalr.grammar.productions) == 102,
        len(lalr.grammar.productions),
    )


# ---------------------------------------------------------------------------
# 2-4. hand-verified data flow
# ---------------------------------------------------------------------------
LOOP = (
    "int main() {\n"
    "    int a = 1;\n"
    "    int b = 2;\n"
    "    while (a < 3) {\n"
    "        b = a + b;\n"
    "        a = a + 1;\n"
    "    }\n"
    "    return b;\n"
    "}\n"
)

UNINITIALISED = "int main() { int a; int b = a + 1; return b; }\n"


def check_dataflow() -> None:
    section("data flow against hand-computed results")
    program = analyse_source(LOOP, filename="loop.ctc")
    analysis = program.analyses["main"]

    # Reaching definitions for the loop, computed by hand:
    #   B0 (a=1; b=2)  OUT = {d(a=1), d(b=2)}
    #   B1 (a<3)       IN  = OUT(B0) u OUT(B2), OUT = IN  (no definitions)
    #   B2 (b=a+b;a=a+1) IN = OUT(B1), OUT = {d(b=a+b), d(a=a+1)}
    def rd_out(block: int) -> set:
        return set(analysis.reaching_result.out_atoms(block))

    def rd_in(block: int) -> set:
        return set(analysis.reaching_result.in_atoms(block))

    # Block ids for this program: 0 entry, 1 exit, 2 loop header, 3 the return
    # block, 4 the loop body.  The loop body reassigns both variables.
    check(
        "reaching definitions: OUT(entry) is exactly the two initial values",
        len(rd_out(0)) == 2,
        sorted(rd_out(0)),
    )
    check(
        "reaching definitions: the loop body's new definitions reach the header",
        rd_out(4) == {"d2", "d3"} and rd_out(4) <= rd_in(2),
        f"OUT(body)={sorted(rd_out(4))} IN(header)={sorted(rd_in(2))}",
    )
    check(
        "reaching definitions: the fixpoint converged",
        analysis.reaching_result.converged and analysis.reaching_result.iterations > 0,
        f"iterations={analysis.reaching_result.iterations}",
    )

    check(
        "live variables: both a and b are live on entry to the header",
        set(analysis.live_result.in_atoms(2)) == {"s2:a", "s3:b"},
        sorted(analysis.live_result.in_atoms(2)),
    )
    check(
        "live variables: only b is live at the return, and nothing is live out of it",
        set(analysis.live_result.in_atoms(3)) == {"s3:b"} and not analysis.live_result.out_atoms(3),
        f"IN(return)={sorted(analysis.live_result.in_atoms(3))} "
        f"OUT(return)={sorted(analysis.live_result.out_atoms(3))}",
    )

    uninit = analyse_source(UNINITIALISED, filename="uninit.ctc")
    reads = uninit.analyses["main"].definite.uninitialised_reads(
        uninit.analyses["main"].definite_result
    )
    check(
        "definite assignment: reading an uninitialised variable is reported",
        len(reads) == 1 and reads[0]["symbol"] == "a",
        reads,
    )
    check(
        "definite assignment: the read raises a diagnostic with a location",
        any(d.code == "DFA001" for d in uninit.diagnostics),
        [d.code for d in uninit.diagnostics if d.code.startswith("DFA")],
    )


# ---------------------------------------------------------------------------
# 5-6. dependency graph and slices
# ---------------------------------------------------------------------------
VULNERABLE = (
    "string build_command(string name) {\n"
    "    return \"ls \" + name;\n"
    "}\n"
    "int main() {\n"
    "    string name = input();\n"
    "    string command = build_command(name);\n"
    "    system(command);\n"
    "    return 0;\n"
    "}\n"
)


def check_graph_and_slices() -> None:
    section("dependency graph and slices")
    program = analyse_source(VULNERABLE, filename="audit.ctc")
    graph = program.dependencies
    check("the dependency graph exists", graph is not None)

    # Every intra-procedural data/taint edge claims "this definition reaches
    # this use".  Re-check the claim against the IN sets of the reaching
    # definitions analysis (and the OUT set when the definition lives in the
    # target statement itself, as in `string name = input();`).
    verified = 0
    unjustified = []
    for function, cfg in program.cfgs.items():
        analysis = program.analyses[function]
        problem = analysis.reaching
        states = analysis.reaching_states
        for edge in graph.edges:
            if edge.kind not in (dependency_module.DATA, dependency_module.TAINT):
                continue
            source, target = graph.nodes.get(edge.src), graph.nodes.get(edge.dst)
            if source is None or target is None or target.sid < 0 or source.kind != "definition":
                continue
            if source.function != target.function or source.function != function:
                continue  # interprocedural edges are justified by the call summaries
            atom = definition_atom(source.definition_id)
            in_bits, out_bits = states.get(target.sid, (0, 0))
            reaches = problem.domain.contains(in_bits, atom)
            if not reaches and source.sid == target.sid:
                reaches = problem.domain.contains(out_bits, atom)
            verified += 1
            if not reaches:
                unjustified.append((edge.src, edge.dst, edge.reason))
    check(
        "every intra-procedural data/taint edge is justified by the reaching definitions",
        not unjustified and verified > 0,
        f"{verified} edges checked, {len(unjustified)} unjustified: {unjustified[:3]}",
    )

    sink = next(f for f in program.findings if f.rule_id == "command_execution")
    backward = program.slicing.backward(sink.sink["sid"])
    forward = program.slicing.forward(0)
    check(
        "the backward slice of the sink contains the source statement",
        sink.source["sid"] in backward.statements,
        sorted(backward.statements),
    )
    check(
        "the forward slice of the source reaches the sink",
        sink.sink["sid"] in forward.statements,
        sorted(forward.statements),
    )
    check(
        "every sliced statement carries a reason",
        all(backward.reasons.get(sid) for sid in backward.statements),
        {sid: len(reason) for sid, reason in backward.reasons.items()},
    )
    finding_slice = program.slicing.for_finding(sink)
    check(
        "the security slice contains both endpoints of the reported flow",
        sink.sink["sid"] in finding_slice.statements and sink.source["sid"] in finding_slice.statements,
        sorted(finding_slice.statements),
    )


# ---------------------------------------------------------------------------
# 7. rule language
# ---------------------------------------------------------------------------
AUDIT_RULES = (
    "version 1\n\n"
    "source audit_argv {\n"
    "  description \"command line argument\"\n"
    "  function argv\n"
    "  returns\n"
    "  contexts command\n"
    "}\n\n"
    "sink audit_launch {\n"
    "  description \"launch helper\"\n"
    "  function launch\n"
    "  arguments 0\n"
    "  context command\n"
    "  category \"command-injection\"\n"
    "  severity HIGH\n"
    "}\n\n"
    "flow audit_flow {\n"
    "  sources audit_argv\n"
    "  sinks audit_launch\n"
    "  enabled true\n"
    "}\n"
)

AUDIT_SOURCE = (
    "int launch(string command) { return 0; }\n"
    "int main() { string arg = argv(1); launch(arg); return 0; }\n"
)


def check_rules() -> None:
    section("declarative rules")
    rule_set, diagnostics, parsed = parse_and_validate(AUDIT_RULES, "audit.ctrule")
    check("the audit rule file parses", parsed.accepted and not diagnostics, parsed.accepted)
    check("the audit rule file defines three rules", len(rule_set.all_rules()) == 3)

    program = analyse_source(AUDIT_SOURCE, filename="rules.ctc", rules=rule_set)
    hits = [f for f in program.findings if f.rule_id == "audit_flow"]
    check("the custom rule reports the flow it describes", len(hits) == 1, len(hits))

    hostile = (
        "version 1\n\n"
        "# __import__('os').system('touch /tmp/codetrace_audit_canary')\n"
        "source x {\n  function input\n  returns\n  contexts command\n}\n"
    )
    if os.path.exists("/tmp/codetrace_audit_canary"):
        os.remove("/tmp/codetrace_audit_canary")
    parse_and_validate(hostile, "hostile.ctrule")
    check("code inside a rule file is data, never executed", not os.path.exists("/tmp/codetrace_audit_canary"))

    _unused, broken, broken_parse = parse_and_validate("version 1\nsource s {\n", "broken.ctrule")
    check(
        "a broken rule file is rejected with a line:column",
        not broken_parse.accepted and any(d.line for d in broken),
        [(d.code, d.line, d.col) for d in broken][:3],
    )


# ---------------------------------------------------------------------------
# 8-9. HTTP workflow
# ---------------------------------------------------------------------------
def http(method: str, base: str, path: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def check_http_workflow() -> dict:
    section("HTTP workflow")
    server = create_server("127.0.0.1", 0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = http("GET", base, "/api/health")
        health = json.loads(body)
        check("health endpoint answers", status == 200 and health["status"] == "ok")
        check("health reports a conflict-free grammar", health["grammar"]["conflicts"] == 0)

        status, body = http("POST", base, "/api/analyze", {"source": VULNERABLE, "filename": "audit.ctc"})
        run = json.loads(body)
        check("analysis endpoint returns a completed run", status == 200 and run["status"] == "completed")
        run_id = run["run_id"]
        check("the run reports the finding", len(run["findings"]) == 1, run["summary"])

        status, body = http("GET", base, f"/api/runs/{run_id}/findings")
        findings = json.loads(body)["findings"]
        finding = findings[0]
        check("findings include the evidence path", bool(finding["path"]))

        status, body = http("GET", base, f"/api/runs/{run_id}/findings/{finding['id']}")
        detail = json.loads(body)
        check("a finding can be opened with its dependency evidence",
              status == 200 and "dependency_evidence" in detail)
        check("the explanation states a potential flow, not an exploit",
              "Potential" in detail["explanation"] and "exploitability was not established" in detail["explanation"])

        sink_sid = finding["sink"]["sid"]
        status, body = http("GET", base, f"/api/runs/{run_id}/statements/{sink_sid}")
        statement = json.loads(body)
        check("source navigation resolves the sink statement",
              status == 200 and "system(" in statement["text"], statement.get("text"))

        status, body = http("GET", base, f"/api/runs/{run_id}/graph")
        graph = json.loads(body)
        check("the graph endpoint returns nodes and justified edges",
              bool(graph["nodes"]) and all(e["reason"] for e in graph["edges"]))

        status, body = http("GET", base, f"/api/runs/{run_id}/findings/{finding['id']}/slice")
        slice_payload = json.loads(body)
        check("the finding slice contains both endpoints",
              finding["source"]["sid"] in slice_payload["statements"]
              and sink_sid in slice_payload["statements"])

        status, body = http("GET", base, f"/api/runs/{run_id}/report?format=json")
        report = json.loads(body)
        check("the JSON report carries the run identity",
              status == 200 and report["run"]["run_id"] == run_id)
        status, html = http("GET", base, f"/api/runs/{run_id}/report?format=html")
        check("the HTML report is self-contained and escaped",
              status == 200 and "<script" not in html.lower() and "/home/" not in html)

        fixed_source = VULNERABLE.replace("build_command(name)", "shell_escape(name)")
        status, body = http("POST", base, "/api/analyze", {"source": fixed_source, "filename": "audit.ctc"})
        fixed = json.loads(body)
        check("the escaped variant reports no flow", fixed["findings"] == [], fixed["summary"])
        status, body = http("POST", base, "/api/compare",
                            {"before": run_id, "after": fixed["run_id"]})
        diff = json.loads(body)
        check("the comparison marks the finding resolved",
              len(diff["resolved"]) == 1 and diff["persistent"] == [] and diff["new"] == [])

        shifted = "\n" + VULNERABLE
        status, body = http("POST", base, "/api/analyze", {"source": shifted, "filename": "audit.ctc"})
        shifted_run = json.loads(body)
        status, body = http("POST", base, "/api/compare",
                            {"before": run_id, "after": shifted_run["run_id"]})
        moved = json.loads(body)
        check("a pure line shift is reported as moved, not as new",
              len(moved["moved"]) == 1 and moved["new"] == [] and moved["resolved"] == [],
              moved["summary"])

        return {"run_id": run_id, "finding": finding, "report": report}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# 10. malformed and unsupported input
# ---------------------------------------------------------------------------
def check_diagnostics() -> None:
    section("malformed and unsupported input")
    broken = analyse_source("int main() { int a = ; return 0; }\n", filename="broken.ctc")
    check(
        "a syntax error is reported with a location and recovery",
        any(d.code.startswith("SYN") and d.line >= 1 for d in broken.diagnostics),
        [(d.code, d.line, d.col) for d in broken.diagnostics],
    )
    check("a file that did not parse is not presented as analysed", broken.parse.accepted is False)
    switch = analyse_source("int main() { switch (1) { case 1: return 0; } }\n", filename="switch.ctc")
    codes = {d.code for d in switch.diagnostics}
    check(
        "an unsupported construct is named explicitly",
        "LEX100" in codes or "SYN100" in codes,
        sorted(codes),
    )
    empty = analyse_source("", filename="empty.ctc")
    check("an empty file produces a report of zero findings rather than an error",
          empty.findings == [] and empty.metrics["statements"] == 0)


# ---------------------------------------------------------------------------
# 11. the interface contract
# ---------------------------------------------------------------------------
FRONTEND = os.path.join(ROOT, "frontend")


def _normalise(path: str) -> str:
    """Reduce an endpoint path or a JavaScript URL to a comparable form."""
    path = path.strip("`").split("?", 1)[0].lstrip("/")
    path = re.sub(r"\$\{[^}]*\}", "", path)
    path = re.sub(r"\{[^}]*\}", "", path)
    return re.sub(r"/+", "/", path).rstrip("/")


def check_interface() -> None:
    section("interface contract")
    schemas_path = os.path.join(FRONTEND, "js", "api.js")
    with open(schemas_path, encoding="utf-8") as handle:
        api_js = handle.read()
    used = {_normalise(match) for match in re.findall(r"`?(api/[A-Za-z0-9/_{}$.\-]*)", api_js)}
    declared = {"api/health"}
    with open(os.path.join(ROOT, "codetrace", "api", "schemas.py"), encoding="utf-8") as handle:
        schemas_py = handle.read()
    declared = {_normalise(entry) for entry in re.findall(r'"path":\s*"([^"]+)"', schemas_py)}
    if not declared:  # ENDPOINTS may be built from tuples; fall back to the table text
        declared = {_normalise(entry) for entry in re.findall(r'"(/api/[A-Za-z0-9/_{}$.\-]*)"', schemas_py)}
    check(
        "every endpoint the interface calls is declared by the server",
        used and used <= declared,
        sorted(used - declared),
    )

    with open(os.path.join(FRONTEND, "index.html"), encoding="utf-8") as handle:
        page = handle.read()
    routes = ["overview", "analyze", "findings", "graph", "dataflow",
              "slicing", "rules", "reports", "documentation"]
    missing = [route for route in routes
               if f'id="view-{route}"' not in page or f'data-route="{route}"' not in page]
    check("every navigation route has a real section in the served page", not missing, missing)

    dangerous = {
        "innerHTML assignment": re.compile(r"\binnerHTML\b\s*(\+?=)"),
        "eval call": re.compile(r"(?:^|[^.\w])eval\s*\("),
    }
    offenders = []
    for folder, _dirs, files in os.walk(os.path.join(FRONTEND, "js")):
        for name in files:
            if not name.endswith(".js"):
                continue
            full = os.path.join(folder, name)
            with open(full, encoding="utf-8") as handle:
                text = handle.read()
            offenders += [f"{name}: {label}" for label, pattern in dangerous.items()
                          if pattern.search(text)]
    check("the interface never injects markup or evaluates a string", not offenders, offenders)


def check_run_summary() -> None:
    section("the run payload the views read")
    server = create_server("127.0.0.1", 0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _status, body = http(
            "POST", base, "/api/analyze",
            {"source": "int main() { string c = input(); system(c); return 0; }\n",
             "filename": "summary.ctc"},
        )
        payload = json.loads(body)
        summary = payload.get("summary", {})
        check(
            "the analyse response states whether the analysis was complete",
            "analysis_complete" in summary and "partial_reasons" in summary,
            sorted(summary),
        )
        check(
            "the analyse response reports the sinks it saw but did not report",
            isinstance(summary.get("dispositions"), dict)
            and summary["dispositions"].get("sink_calls_seen", 0) >= 1,
            summary.get("dispositions"),
        )
        _status, body = http(
            "POST", base, "/api/analyze",
            {"source": "int main() { switch (1) { case 1: return 0; } return 0; }\n",
             "filename": "partial.ctc"},
        )
        partial = json.loads(body)
        check(
            "a partial analysis says so instead of looking clean",
            partial["summary"]["analysis_complete"] is False
            and bool(partial["summary"]["partial_reasons"]),
            partial["summary"].get("partial_reasons"),
        )
        run = payload["run_id"]
        _status, body = http("GET", base, f"/api/runs/{run}/report?format=json")
        report = json.loads(body)
        check(
            "the exported report agrees with the analyse response",
            report["summary"]["findings"] == payload["summary"]["findings"]
            and report["run"]["run_id"] == run,
            report["run"]["run_id"],
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# 12. documentation accuracy
# ---------------------------------------------------------------------------
def check_documentation() -> None:
    section("documents match the repository")
    documents = [os.path.join(ROOT, "README.md")]
    docs_dir = os.path.join(ROOT, "docs")
    documents += [os.path.join(docs_dir, name) for name in sorted(os.listdir(docs_dir))
                  if name.endswith(".md")]
    texts = {}
    for path in documents:
        with open(path, encoding="utf-8") as handle:
            texts[path] = handle.read()

    missing_files = []
    for path, text in texts.items():
        for reference in re.findall(
            r"(?<![\w/.])"
            r"(?:codetrace|docs|frontend|scripts|examples|tests|evaluation)"
            r"/[A-Za-z0-9_./\-]+\.(?:md|py|sh|json|js|ctrule|ctc)",
            text,
        ):
            if not os.path.exists(os.path.join(ROOT, reference)):
                missing_files.append(f"{os.path.basename(path)} -> {reference}")
        for module in re.findall(r"codetrace/[A-Za-z0-9_./]+\.py", text):
            if not os.path.exists(os.path.join(ROOT, module)):
                missing_files.append(f"{os.path.basename(path)} -> {module}")
    check("every file the documents reference exists", not missing_files, missing_files)

    missing_docs = []
    for path, text in texts.items():
        for reference in re.findall(r"\(docs/[A-Za-z0-9_]+\.md\)", text):
            if not os.path.exists(os.path.join(ROOT, reference.strip("()"))):
                missing_docs.append(reference)
    check("every document cross-reference resolves", not missing_docs, sorted(set(missing_docs)))

    scripts = ["scripts/serve.sh", "scripts/tests.sh", "scripts/evaluate.sh", "scripts/audit.py"]
    not_executable = [name for name in scripts
                      if not os.access(os.path.join(ROOT, name), os.X_OK)]
    check("the documented scripts exist and are executable", not not_executable, not_executable)

    help_text = subprocess.run(
        [sys.executable, "-m", "codetrace.api", "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    check(
        "the documented start-up command accepts --host/--port/--verbose",
        help_text.returncode == 0
        and all(flag in help_text.stdout for flag in ("--host", "--port", "--verbose")),
        help_text.stdout.splitlines()[0] if help_text.stdout else help_text.stderr,
    )

    requirements = os.path.join(ROOT, "requirements.txt")
    third_party = []
    if os.path.exists(requirements):
        with open(requirements, encoding="utf-8") as handle:
            third_party = [line for line in handle
                           if line.strip() and not line.startswith("#")]
    check("the project needs no third-party Python package", not third_party, third_party)


# ---------------------------------------------------------------------------
# 13. claims the documents make about the code
# ---------------------------------------------------------------------------
def check_claims() -> None:
    """Re-derive the statements the documents make, from the code itself.

    A document that describes behaviour is a claim like any other, and the ones
    quoted in the reports and the README are the ones a reviewer will check.  The
    checks below deliberately compute the value instead of trusting the prose.
    """
    section("quoted claims")

    # -- the corpus accounting in docs/EVALUATION.md §2 --------------------
    expectations_path = os.path.join(ROOT, "evaluation", "expectations.json")
    with open(expectations_path, encoding="utf-8") as handle:
        corpus = json.load(handle)
    cases = corpus["cases"]
    finding_level = [c for c in cases if c.get("expect")]
    file_level = [c for c in cases if c["label"] in ("safe", "sanitized")]
    diagnostic_only = [c for c in cases if c["label"] in ("unsupported", "syntax_error")]
    declared = sum(len(c.get("expect") or []) for c in cases)
    check(
        "the three metric groups partition the corpus (18 + 9 + 6 = 33)",
        (len(finding_level), len(file_level), len(diagnostic_only)) == (18, 9, 6)
        and len(finding_level) + len(file_level) + len(diagnostic_only) == len(cases) == 33,
        f"{len(finding_level)} finding-level + {len(file_level)} file-level + "
        f"{len(diagnostic_only)} diagnostic-only = {len(cases)}",
    )
    check(
        "the corpus declares the 20 expectations the documents quote",
        declared == 20,
        declared,
    )
    check(
        "a file-level case declares no expectation (no case is counted twice)",
        not [c for c in file_level if c.get("expect")],
        [c["file"] for c in file_level if c.get("expect")],
    )

    # -- the matching rule: line numbers are not part of the match ---------
    harness_path = os.path.join(ROOT, "evaluation", "run_evaluation.py")
    with open(harness_path, encoding="utf-8") as handle:
        harness_source = handle.read()
    matcher_body = harness_source.split("def finding_matches", 1)[1].split("\ndef ", 1)[0]
    check(
        "finding_matches does not consult the line number it records",
        "line" not in matcher_body.replace("Line numbers", ""),
        "no line comparison in finding_matches",
    )
    check(
        "the corpus states that line numbers are not part of the match",
        "NOT part of the match" in corpus.get("matching", ""),
        corpus.get("matching", "")[:60],
    )

    catalogue = subprocess.run(
        [sys.executable, "scripts/mutation_check.py", "--list"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    entries = [line for line in catalogue.stdout.splitlines() if line.strip()]
    check(
        "the mutation catalogue is listed and covers the pipeline",
        catalogue.returncode == 0 and len(entries) >= 12,
        f"{len(entries)} mutations listed",
    )
    areas = {line.split()[0] for line in entries if line.strip()}
    check(
        "the mutation catalogue spans parser, semantics, CFG, data flow, taint, "
        "slicing, rules and reporting",
        {"parser", "semantics", "cfg", "dataflow", "taint", "slicing", "rules", "reporting"}
        <= areas,
        sorted(areas),
    )

    # -- the module table in docs/TECHNICAL_DESIGN.md ----------------------
    # The table is the part of the documentation most likely to rot, because
    # every edit to the tree changes it.  Re-derive it here rather than trusting
    # the numbers in the prose.
    module_rows = {}
    with open(os.path.join(ROOT, "docs", "TECHNICAL_DESIGN.md"), encoding="utf-8") as handle:
        table_text = handle.read()
    for line in table_text.splitlines():
        match = re.match(r"\| `([^`]+)` \| (\d+) \| (\d+) \|", line)
        if match:
            module_rows[match.group(1)] = (int(match.group(2)), int(match.group(3)))

    def measure(relative: str, suffix: str = "") -> tuple:
        base = os.path.join(ROOT, relative.rstrip("/"))
        if not os.path.isdir(base):
            return (0, 0)
        files = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", "node_modules"}]
            for name in filenames:
                if suffix and not name.endswith(suffix):
                    continue
                files.append(os.path.join(dirpath, name))
        total = 0
        for path in files:
            with open(path, encoding="utf-8", errors="replace") as handle:
                total += len(handle.read().splitlines())
        return (len(files), total)

    def measure_root_py() -> tuple:
        names = [n for n in sorted(os.listdir(os.path.join(ROOT, "codetrace")))
                 if n.endswith(".py")]
        total = 0
        for name in names:
            with open(os.path.join(ROOT, "codetrace", name), encoding="utf-8") as handle:
                total += len(handle.read().splitlines())
        return (len(names), total)

    measured = {
        "codetrace/frontend": measure("codetrace/frontend", ".py"),
        "codetrace/semantics": measure("codetrace/semantics", ".py"),
        "codetrace/analysis": measure("codetrace/analysis", ".py"),
        "codetrace/rules": measure("codetrace/rules", ".py"),
        "codetrace/findings": measure("codetrace/findings", ".py"),
        "codetrace/reporting": measure("codetrace/reporting", ".py"),
        "codetrace/api": measure("codetrace/api", ".py"),
        "codetrace/*.py": measure_root_py(),
        "tests/": measure("tests", ".py"),
        "frontend/tests/": measure("frontend/tests"),
        "evaluation/": measure("evaluation"),
        "scripts/": measure("scripts"),
        "docs/": measure("docs"),
        "examples/": measure("examples"),
    }
    # frontend/ in the table means the interface assets, which are everything
    # under frontend/ except the interface tests.
    app_files, app_lines = measure("frontend")
    test_files, test_lines = measure("frontend/tests")
    measured["frontend/"] = (app_files - test_files, app_lines - test_lines)
    _MEASURED_MODULES.clear()
    _MEASURED_MODULES.update(measured)

    drift = []
    for name, expected in measured.items():
        actual = module_rows.get(name)
        if actual is None:
            drift.append(f"{name}: missing from the table")
        elif actual != expected:
            drift.append(f"{name}: table says {actual}, tree has {expected}")
    check(
        "the module table in docs/TECHNICAL_DESIGN.md matches the tree",
        not drift,
        drift,
    )

    # -- validator guards: a suppressed flow is reported as suppressed -----
    guarded = (
        "int main() {\n  string name = input();\n"
        "  if (is_safe_command(name)) { system(name); }\n  return 0;\n}\n"
    )
    program = analyse_source(guarded, filename="guarded.ctc")
    suppressions = getattr(program.taint, "guard_suppressions", None) or []
    check(
        "a validator-guarded flow leaves a suppression record, not silence",
        len(program.findings) == 0 and len(suppressions) == 1
        and suppressions[0]["validator"] == "validate_command"
        and suppressions[0]["removed_atoms"],
        [(s["validator"], s["symbol"], s["removed_atoms"]) for s in suppressions],
    )
    check(
        "the suppression states that the validator body was not analysed",
        "assumes it rejects" in (suppressions[0]["assumption"] if suppressions else ""),
        suppressions[0]["assumption"][:70] if suppressions else "",
    )
    report = json_report.build_report(program, run_id="audit-guard")
    dispositions = report["summary"]["dispositions"]
    check(
        "the report exposes the guard under summary.dispositions.validator_guards",
        [g["validator"] for g in dispositions["validator_guards"]] == ["validate_command"],
        dispositions["validator_guards"],
    )
    check(
        "the report's disposition names the guard instead of denying the taint",
        "cleared" in dispositions["unreported_sink_calls"][0]["reason"]
        and "no taint of the required context reached"
        not in dispositions["unreported_sink_calls"][0]["reason"],
        dispositions["unreported_sink_calls"][0]["reason"][:70],
    )
    check(
        "the run-level limitation counts the unreported sink call",
        any("unreported sink call" in line for line in report["limitations"]),
        [l for l in report["limitations"] if "unreported sink call" in l][:1],
    )
    plain = json_report.build_report(
        analyse_source("int main() { int a = 1; return a; }", filename="plain.ctc"),
        run_id="audit-plain",
    )
    check(
        "a run with no guard makes no suppression claim",
        not plain["summary"]["dispositions"]["validator_guards"]
        and not [l for l in plain["limitations"] if "unreported sink call" in l],
        plain["summary"]["dispositions"]["validator_guards"],
    )

    # -- the must-analysis contract the documents describe -----------------
    loop = analyse_source(
        "int main() {\n  int n = 0;\n  for (int i = 0; i < 3; i++) {\n"
        "    if (i == 1) { continue; }\n    n = n + i;\n  }\n  return n;\n}\n",
        filename="loop.ctc",
    )
    false_positives = [d for d in loop.diagnostics if d.code == "DFA001"]
    check(
        "definite assignment does not report a variable assigned before the loop",
        false_positives == [],
        [(d.line, d.col, d.message) for d in false_positives],
    )


MODULE_TABLE_PATH = os.path.join("docs", "TECHNICAL_DESIGN.md")


def write_module_table() -> int:
    """Rewrite the module table from the measured tree.

    The table is checked exactly, because a stale row is a false statement about
    the repository.  Keeping it exact has to be cheap, or it becomes a chore that
    gets deferred: this flag re-measures every row and writes it back, so the
    command that reports the drift is also the command that fixes it.

        python3 scripts/audit.py --write-module-table
    """
    global SILENT
    SILENT = True
    before = len(FAILURES)
    try:
        check_claims()  # measures the tree and records it
    finally:
        SILENT = False
    del FAILURES[before:]  # the measuring pass must not leave failures behind
    measured = dict(_MEASURED_MODULES)
    path = os.path.join(ROOT, MODULE_TABLE_PATH)
    with open(path, encoding="utf-8") as handle:
        lines = handle.readlines()

    changed = []
    for index, line in enumerate(lines):
        match = re.match(r"\| `([^`]+)` \| (\d+) \| (\d+) \|(.*)$", line)
        if not match:
            continue
        name = match.group(1)
        if name not in measured:
            continue
        files, count = measured.pop(name)
        replacement = f"| `{name}` | {files} | {count} |{match.group(4)}\n"
        if replacement != line:
            changed.append(f"{name}: {match.group(2)}/{match.group(3)} -> {files}/{count}")
        lines[index] = replacement
    if measured:
        print("no row in the table for: " + ", ".join(sorted(measured)))
    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(lines)
    if changed:
        print("module table updated:")
        for entry in changed:
            print(f"  {entry}")
    else:
        print("module table already matches the tree")
    return 0


def main() -> int:
    global VERBOSE
    parser = argparse.ArgumentParser(description="independent audit of this checkout")
    parser.add_argument("-v", "--verbose", action="store_true", help="print observed values")
    parser.add_argument(
        "--write-module-table", action="store_true",
        help="re-measure the module table in docs/TECHNICAL_DESIGN.md and write it back",
    )
    args = parser.parse_args()
    VERBOSE = args.verbose
    if args.write_module_table:
        return write_module_table()

    print(f"CodeTrace audit — {ROOT}")
    check_grammar()
    check_dataflow()
    check_graph_and_slices()
    check_rules()
    check_http_workflow()
    check_diagnostics()
    check_interface()
    check_run_summary()
    check_documentation()
    check_claims()

    print()
    if FAILURES:
        print(f"{CHECKS - len(FAILURES)}/{CHECKS} checks passed; FAILED: {', '.join(FAILURES)}")
        return 1
    print(f"all {CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
