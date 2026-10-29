"""CodeTrace HTTP API (Python standard library only).

Design decisions that matter for the security of the tool itself:

* **The analysed program is never executed.**  Every request goes through the
  static pipeline; there is no code path that imports, compiles, evaluates or
  runs analysed source (or a rule file).
* **No arbitrary filesystem access.**  The only files the server reads are the
  bundled examples inside ``examples/``, addressed by a slug that is resolved
  against a pre-computed index; the resolved path is verified to stay inside
  the examples directory.
* **Bounded work.**  Request bodies, source size, line count, function count
  and analysis iterations are all capped, and the caps are reported in the
  response when they are hit.
* **Structured errors, no server internals.**  Errors are returned as
  ``{"error": {"code", "message", "detail"}}``; tracebacks stay in the log.
* **No persistence.**  Analysis runs live in a bounded in-memory LRU
  (``RUN_CACHE_SIZE``); reports are generated on demand and returned, never
  written to disk by the API.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from ..analysis import dependencies as dependency_module
from ..analysis.pipeline import ENGINE_VERSION, Program, analyse_source, live_variables_at, reaching_definitions_at, taint_at
from ..frontend.grammar_lang import grammar_documentation
from ..frontend.pipeline import parser_tables
from ..frontend.tokens import DISPLAY, UNSUPPORTED_KEYWORDS
from ..reporting.html_report import render_html
from ..reporting.json_report import (
    SCHEMA_VERSION,
    build_report,
    dispositions,
    to_json_text,
)
from ..rules.model import CONTEXTS, SEVERITIES, RuleSet
from ..rules.rule_language import load_builtin_rules, parse_and_validate, rule_tables
from .schemas import API_VERSION, ENDPOINTS, SCHEMAS

# ----------------------------------------------------------------------
# Limits (documented, not magic)
# ----------------------------------------------------------------------
MAX_BODY_BYTES = 1_100_000
MAX_SOURCE_BYTES = 512 * 1024

#: How much of an oversized request body the server reads before answering, so
#: that the client can finish sending and then read the error response.  Bounded
#: on purpose: the point is to deliver the 413 cleanly, not to accept a body the
#: API refuses.
DRAIN_BUDGET_BYTES = 8 * 1024 * 1024
DRAIN_TIMEOUT_SECONDS = 5.0
RUN_CACHE_SIZE = 24
MAX_STATEMENT_INDEX = 2000
EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "examples")
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "frontend")

DIAGNOSTIC_CATALOGUE: List[dict] = [
    {"code": "LEX001", "phase": "lexer", "meaning": "unterminated string or character literal"},
    {"code": "LEX002", "phase": "lexer", "meaning": "unterminated block comment"},
    {"code": "LEX003", "phase": "lexer", "meaning": "malformed hexadecimal literal"},
    {"code": "LEX004", "phase": "lexer", "meaning": "malformed numeric literal"},
    {"code": "LEX005", "phase": "lexer", "meaning": "unknown escape sequence"},
    {"code": "LEX006", "phase": "lexer", "meaning": "malformed hex escape"},
    {"code": "LEX007", "phase": "lexer", "meaning": "multi-character character literal"},
    {"code": "LEX008", "phase": "lexer", "meaning": "character outside the CT-C alphabet"},
    {"code": "LEX100", "phase": "lexer", "meaning": "unsupported keyword"},
    {"code": "LEX101", "phase": "lexer", "meaning": "preprocessor directive (unsupported)"},
    {"code": "LEX102", "phase": "lexer", "meaning": "unsupported operator"},
    {"code": "SYN001", "phase": "parser", "meaning": "syntax error with expected-token list"},
    {"code": "SYN010", "phase": "parser", "meaning": "parse step limit reached"},
    {"code": "SYN011", "phase": "parser", "meaning": "too many syntax errors"},
    {"code": "SYN100", "phase": "parser", "meaning": "unsupported keyword encountered during parsing"},
    {"code": "SEM001", "phase": "semantics", "meaning": "undeclared identifier"},
    {"code": "SEM002", "phase": "semantics", "meaning": "duplicate declaration in one scope"},
    {"code": "SEM003", "phase": "semantics", "meaning": "function redefinition"},
    {"code": "SEM004", "phase": "semantics", "meaning": "assignment to a non-assignable expression"},
    {"code": "SEM005", "phase": "semantics", "meaning": "type error"},
    {"code": "SEM006", "phase": "semantics", "meaning": "variable declared void"},
    {"code": "SEM007", "phase": "semantics", "meaning": "parameter declared void"},
    {"code": "SEM008", "phase": "semantics", "meaning": "call to an unknown external function"},
    {"code": "SEM009", "phase": "semantics", "meaning": "wrong number of arguments"},
    {"code": "SEM010", "phase": "semantics", "meaning": "argument type mismatch"},
    {"code": "SEM012", "phase": "semantics", "meaning": "break/continue outside a loop"},
    {"code": "SEM013", "phase": "semantics", "meaning": "indexing a non-array"},
    {"code": "SEM014", "phase": "semantics", "meaning": "function used as a value"},
    {"code": "SEM015", "phase": "semantics", "meaning": "duplicate parameter name"},
    {"code": "SEM016", "phase": "semantics", "meaning": "return value mismatch"},
    {"code": "SEM017", "phase": "semantics", "meaning": "indirect call (unsupported)"},
    {"code": "SEM018", "phase": "semantics", "meaning": "declaration shadows an outer declaration"},
    {"code": "SEM020", "phase": "semantics", "meaning": "no main function"},
    {"code": "SEM101", "phase": "semantics", "meaning": "narrowing conversion"},
    {"code": "SEM102", "phase": "semantics", "meaning": "non-boolean condition"},
    {"code": "CFG001", "phase": "cfg", "meaning": "unreachable code"},
    {"code": "DFA001", "phase": "dataflow", "meaning": "variable may be used before assignment"},
    {"code": "RULE001-RULE012", "phase": "rules",
     "meaning": "rule declaration problems: version, identifier, items, contexts, severity, "
                "argument indices"},
    {"code": "RULE020-RULE026", "phase": "rules",
     "meaning": "rule reference problems: unknown source/sink/sanitizer in a flow, a flow "
                "without sources or sinks, an ambiguous function binding, and a source whose "
                "contexts cannot reach its sink"},
]


def _example_index() -> List[dict]:
    """Slug -> path index of bundled examples (built once, sorted)."""
    entries: List[dict] = []
    for root, _dirs, files in os.walk(EXAMPLES_DIR):
        for name in sorted(files):
            if not name.endswith((".ctc", ".ctrule", ".md", ".json")):
                continue
            path = os.path.join(root, name)
            relative = os.path.relpath(path, EXAMPLES_DIR)
            entries.append(
                {
                    "id": relative.replace(os.sep, "/"),
                    "name": name,
                    "category": relative.split(os.sep)[0],
                    "path": path,
                }
            )
    return sorted(entries, key=lambda entry: entry["id"])


class RunStore:
    """Bounded in-memory store of analysis runs (documented as non-persistent)."""

    def __init__(self, capacity: int = RUN_CACHE_SIZE) -> None:
        self.capacity = capacity
        self._runs: "OrderedDict[str, dict]" = OrderedDict()
        self._lock = threading.Lock()

    def put(self, program: Program, rule_set: RuleSet) -> str:
        run_id = uuid.uuid4().hex[:16]
        with self._lock:
            self._runs[run_id] = {"program": program, "rules": rule_set, "created": time.time()}
            while len(self._runs) > self.capacity:
                self._runs.popitem(last=False)
        return run_id

    def get(self, run_id: str) -> Optional[dict]:
        with self._lock:
            return self._runs.get(run_id)

    def ids(self) -> List[str]:
        with self._lock:
            return list(self._runs)

    def __len__(self) -> int:
        with self._lock:
            return len(self._runs)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail


class CodeTraceHandler(BaseHTTPRequestHandler):
    server_version = f"CodeTrace/{ENGINE_VERSION}"
    store: RunStore = RunStore()
    started_at = time.time()
    verbose = False

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib signature
        if self.verbose:
            print(f"[api] {self.address_string()} {fmt % args}", flush=True)

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, content_type: str, status: int = 200) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str, detail: str = "") -> None:
        self._send_json({"error": {"code": code, "message": message, "detail": detail}}, status)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib naming
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _drain_request_body(self, remaining: int) -> None:
        """Read and discard up to ``remaining`` bytes of an unwanted body.

        Answering a request before reading its body would leave unread bytes in
        the socket; closing the connection then resets it, and the client sees a
        broken pipe instead of the error envelope the API documents.  Draining is
        bounded by both a byte budget and a short socket timeout, so a client that
        streams indefinitely cannot hold the worker for long: whatever is left
        when the budget runs out is abandoned and the connection is closed.
        """
        budget = min(max(remaining, 0), DRAIN_BUDGET_BYTES)
        if budget <= 0:
            return
        connection = self.connection
        previous_timeout = connection.gettimeout()
        connection.settimeout(DRAIN_TIMEOUT_SECONDS)
        try:
            while budget > 0:
                chunk = connection.recv(min(budget, 65536))
                if not chunk:
                    break
                budget -= len(chunk)
        except OSError:
            pass  # the client went away; nothing left to drain
        finally:
            try:
                connection.settimeout(previous_timeout)
            except OSError:
                pass

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            # Answering with a 413 without consuming the body makes clients fail
            # with a broken pipe instead of reading the documented error.
            self._drain_request_body(length)
            raise ApiError(413, "payload-too-large",
                           f"request body exceeds the {MAX_BODY_BYTES} byte limit")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, "invalid-json", "request body is not valid JSON", str(exc)) from exc
        if not isinstance(payload, dict):
            raise ApiError(400, "invalid-json", "request body must be a JSON object")
        return payload

    # ------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            if path.startswith("/api/"):
                self._handle_api_get(path, query)
            else:
                self._serve_static(path)
        except ApiError as error:
            self._error(error.status, error.code, error.message, error.detail)
        except Exception as exc:  # pragma: no cover - unexpected server fault
            traceback.print_exc()
            # The exception text stays in the server log: docs/API.md §1 promises a
            # generic client-visible message, and echoing str(exc) leaked internal
            # detail (e.g. "invalid literal for int() with base 10").
            self._error(500, "internal-error", "the analysis engine reported an internal error")

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            payload = self._read_json()
            if path == "/api/analyze":
                self._analyze(payload)
            elif path == "/api/rules/validate":
                self._validate_rules(payload)
            elif path == "/api/compare":
                self._compare(payload)
            else:
                raise ApiError(404, "not-found", f"no such endpoint: {path}")
        except ApiError as error:
            self._error(error.status, error.code, error.message, error.detail)
        except Exception as exc:  # pragma: no cover
            traceback.print_exc()
            # The exception text stays in the server log: docs/API.md §1 promises a
            # generic client-visible message, and echoing str(exc) leaked internal
            # detail (e.g. "invalid literal for int() with base 10").
            self._error(500, "internal-error", "the analysis engine reported an internal error")

    # ------------------------------------------------------------------
    # GET endpoints
    # ------------------------------------------------------------------
    def _handle_api_get(self, path: str, query: Dict[str, str]) -> None:
        if path == "/api/health":
            tables = parser_tables()
            rule_set, _ = load_builtin_rules()
            self._send_json(
                {
                    "status": "ok",
                    "engine_version": ENGINE_VERSION,
                    "api_version": API_VERSION,
                    "schema_version": SCHEMA_VERSION,
                    "rules_version": rule_set.version_label(),
                    "grammar": {
                        "productions": len(tables.grammar.productions),
                        "terminals": len(tables.grammar.terminals),
                        "nonterminals": len(tables.grammar.nonterminals),
                        "lalr_states": tables.automaton.stats.states,
                        "conflicts": len(tables.conflicts),
                        "mode": tables.mode,
                    },
                    "runs_in_memory": len(self.store),
                    "uptime_seconds": round(time.time() - self.started_at, 3),
                }
            )
            return

        if path == "/api/schemas":
            self._send_json({"api_version": API_VERSION, "schemas": SCHEMAS, "endpoints": ENDPOINTS})
            return

        if path == "/api/language":
            self._send_json(
                {
                    "mode": "CT-C subset v1",
                    "supported": {
                        "types": ["int", "float", "char", "bool", "string", "void (return type only)"],
                        "statements": [
                            "declaration", "assignment", "expression statement", "if/else",
                            "while", "for", "return", "break", "continue", "block", "empty statement",
                        ],
                        "expressions": [
                            "identifiers", "literals", "+ - * / %", "== != < <= > >=",
                            "&& || !", "parentheses", "assignment (= += -= *= /= %=)",
                            "increment/decrement", "array indexing", "function calls",
                        ],
                        "other": ["functions with parameters and return values", "arrays (fixed size)"],
                    },
                    "unsupported": {
                        keyword: reason for keyword, reason in sorted(UNSUPPORTED_KEYWORDS.items())
                    },
                    "contexts": list(CONTEXTS),
                    "severities": list(SEVERITIES),
                    "diagnostics": DIAGNOSTIC_CATALOGUE,
                }
            )
            return

        if path == "/api/grammar":
            mode = query.get("mode") or "lalr"
            if mode not in ("lalr", "slr", "canonical"):
                # grammar.build_automaton raises GrammarError for an unknown mode,
                # which is not an ApiError: the handler turned a bad query parameter
                # into a 500.  docs/API.md §1 lists invalid-parser-mode under 400 and
                # /api/analyze already answers exactly this way for parser_mode.
                raise ApiError(400, "invalid-parser-mode",
                               "mode must be one of lalr, slr, canonical")
            tables = parser_tables(mode)
            grammar = tables.grammar
            self._send_json(
                {
                    "mode": tables.mode,
                    "start_symbol": grammar.start_symbol,
                    "augmented_start": grammar.augmented_start,
                    "terminals": sorted(grammar.terminals),
                    "nonterminals": sorted(grammar.nonterminals),
                    "nullable": sorted(grammar.nullable),
                    "first": {name: sorted(values) for name, values in sorted(grammar.first.items())},
                    "follow": {name: sorted(values) for name, values in sorted(grammar.follow.items())},
                    "productions": grammar_documentation(),
                    "automaton": tables.automaton.stats.to_json(),
                    "table": {
                        "action_entries": len(tables.action),
                        "goto_entries": len(tables.goto),
                        "conflicts": [c.to_json(grammar) for c in tables.conflicts],
                    },
                }
            )
            return

        if path == "/api/rules":
            builtin, diagnostics = load_builtin_rules()
            self._send_json(
                {
                    "active": builtin.to_json(),
                    "rule_language": {
                        "grammar_reference": "docs/RULE_LANGUAGE.md",
                        "productions": len(rule_tables().grammar.productions),
                        "states": rule_tables().automaton.stats.states,
                        "conflicts": len(rule_tables().conflicts),
                    },
                    "loader_diagnostics": [d.to_json() for d in diagnostics],
                }
            )
            return

        if path == "/api/examples":
            entries = _example_index()
            listing = []
            for entry in entries:
                explanation = _example_expectation(entry["path"])
                listing.append(
                    {
                        "id": entry["id"],
                        "name": entry["name"],
                        "category": entry["category"],
                        "expectation": explanation,
                    }
                )
            self._send_json({"examples": listing, "count": len(listing)})
            return

        if path.startswith("/api/examples/"):
            example_id = path[len("/api/examples/"):]
            entry = next((e for e in _example_index() if e["id"] == example_id), None)
            if entry is None:
                raise ApiError(404, "example-not-found", f"no bundled example named {example_id!r}")
            resolved = os.path.realpath(entry["path"])
            if not resolved.startswith(os.path.realpath(EXAMPLES_DIR) + os.sep):
                raise ApiError(403, "path-not-allowed", "the requested example is outside the examples directory")
            with open(resolved, "r", encoding="utf-8") as handle:
                text = handle.read()
            self._send_json({"id": entry["id"], "name": entry["name"], "content": text,
                             "expectation": _example_expectation(resolved)})
            return

        match = re.fullmatch(r"/api/runs/([0-9a-f]+)(.*)", path)
        if match:
            run_id, rest = match.group(1), match.group(2)
            record = self.store.get(run_id)
            if record is None:
                raise ApiError(404, "run-not-found",
                               "this run is no longer available in memory; run the analysis again")
            self._run_endpoint(record, run_id, rest or "/", query)
            return

        raise ApiError(404, "not-found", f"no such endpoint: {path}")

    # ------------------------------------------------------------------
    def _run_endpoint(self, record: dict, run_id: str, rest: str, query: Dict[str, str]) -> None:
        program: Program = record["program"]
        if rest in ("", "/"):
            self._send_json(self._run_summary(program, run_id))
            return
        if rest == "/findings":
            findings = program.findings
            severity = query.get("severity")
            category = query.get("category")
            certainty = query.get("certainty")
            rule = query.get("rule")
            if severity:
                findings = [f for f in findings if f.severity == severity]
            if category:
                findings = [f for f in findings if f.category == category]
            if certainty:
                findings = [f for f in findings if f.certainty == certainty]
            if rule:
                findings = [f for f in findings if f.rule_id == rule]
            search = query.get("q")
            if search:
                needle = search.lower()
                findings = [
                    f for f in findings
                    if needle in json.dumps(f.to_json()).lower()
                ]
            self._send_json({"findings": [f.to_json() for f in findings], "count": len(findings)})
            return
        match = re.fullmatch(r"/findings/([A-Za-z0-9]+)(/slice)?", rest)
        if match:
            finding_id, want_slice = match.group(1), match.group(2)
            finding = next((f for f in program.findings if f.id == finding_id), None)
            if finding is None:
                raise ApiError(404, "finding-not-found", f"no finding with id {finding_id!r} in this run")
            if want_slice:
                slice_result = program.slicing.for_finding(finding) if program.slicing else None
                if slice_result is None:
                    raise ApiError(409, "slicing-unavailable",
                                   "slicing is not available for this run")
                payload = slice_result.to_json()
                payload["statements_detail"] = self._statements_detail(program, slice_result.statements)
                payload["statements_detail_truncated"] = len(slice_result.statements) > MAX_STATEMENT_INDEX
                payload["subgraph"] = program.slicing.subgraph_json(slice_result.statements) if program.slicing else {}
                self._send_json(payload)
                return
            payload = finding.to_json()
            payload["dependency_evidence"] = self._finding_edges(program, finding)
            self._send_json(payload)
            return
        if rest == "/ast":
            tree = program.parse.tree
            if tree is None:
                self._send_json({"tree": None, "note": "the file could not be parsed, so no AST exists"})
                return
            self._send_json({"tree": tree.to_json(max_depth=40)})
            return
        if rest == "/cfg":
            function = query.get("function")
            if function:
                cfg = program.cfgs.get(function)
                if cfg is None:
                    raise ApiError(404, "function-not-found", f"no function named {function!r}")
                self._send_json(cfg.to_json())
                return
            self._send_json(
                {
                    "functions": [cfg.to_json(statements_json=True, max_depth=1) for cfg in program.cfgs.values()],
                    "stats": [cfg.stats() for cfg in program.cfgs.values()],
                }
            )
            return
        if rest == "/dataflow":
            function = query.get("function") or next(iter(program.analyses), "")
            analysis = program.analyses.get(function)
            if analysis is None:
                raise ApiError(404, "function-not-found", f"no analysed function named {function!r}")
            kind = query.get("analysis", "reaching")
            if kind == "reaching":
                payload = analysis.reaching.to_json(analysis.reaching_result)
                payload["statement_states"] = {
                    str(sid): {
                        "in": analysis.reaching.domain.atoms_of(bits[0]),
                        "out": analysis.reaching.domain.atoms_of(bits[1]),
                    }
                    for sid, bits in sorted(analysis.reaching_states.items())
                }
            elif kind == "liveness":
                payload = analysis.live.to_json(analysis.live_result)
                payload["statement_states"] = {
                    str(sid): {
                        "in": analysis.live.domain.atoms_of(bits[0]),
                        "out": analysis.live.domain.atoms_of(bits[1]),
                    }
                    for sid, bits in sorted(analysis.live_states.items())
                }
            elif kind == "definite":
                payload = analysis.definite.to_json(analysis.definite_result)
                payload["uninitialised_reads"] = analysis.definite.uninitialised_reads(
                    analysis.definite_result
                )
                payload["statement_states"] = {
                    str(sid): {
                        "in": analysis.definite.domain.atoms_of(bits[0]),
                        "out": analysis.definite.domain.atoms_of(bits[1]),
                    }
                    for sid, bits in sorted(analysis.definite_states.items())
                }
            else:
                raise ApiError(400, "unknown-analysis",
                               "analysis must be one of reaching, liveness, definite")
            payload["function"] = function
            payload["analysis"] = kind
            self._send_json(payload)
            return
        match = re.fullmatch(r"/statements/([^/]+)", rest)
        if match:
            try:
                sid = int(match.group(1))
            except ValueError as exc:
                raise ApiError(400, "invalid-parameter", "'sid' must be an integer") from exc
            self._send_json(self._statement_detail(program, sid))
            return
        if rest == "/graph":
            kinds = [k for k in (query.get("kinds") or "").split(",") if k]
            graph = program.dependencies
            if graph is None:
                raise ApiError(409, "graph-unavailable", "no dependency graph was built for this run")
            limit_text = query.get("limit")
            limit = 4000
            if limit_text:
                try:
                    limit = int(limit_text)
                except ValueError as exc:
                    raise ApiError(400, "invalid-parameter", "'limit' must be an integer") from exc
                if limit < 0:
                    raise ApiError(400, "invalid-parameter", "'limit' must not be negative")
            self._send_json(graph.to_json(kinds=kinds or None, limit=limit))
            return
        if rest == "/slice":
            criterion = query.get("sid")
            if criterion is None:
                raise ApiError(400, "missing-parameter", "the 'sid' query parameter is required")
            try:
                sid = int(criterion)
            except ValueError as exc:
                raise ApiError(400, "invalid-parameter", "'sid' must be an integer") from exc
            direction = query.get("direction", "backward")
            if direction not in ("backward", "forward"):
                raise ApiError(
                    400, "invalid-parameter", "'direction' must be 'backward' or 'forward'"
                )
            if program.slicing is None:
                raise ApiError(409, "slicing-unavailable", "slicing is not available for this run")
            slice_result = (
                program.slicing.forward(sid) if direction == "forward" else program.slicing.backward(sid)
            )
            payload = slice_result.to_json()
            payload["statements_detail"] = self._statements_detail(program, slice_result.statements)
            payload["statements_detail_truncated"] = len(slice_result.statements) > MAX_STATEMENT_INDEX
            # The slicing view draws the induced dependency subgraph, so a slice
            # taken from a statement gets the same treatment as a finding slice.
            payload["subgraph"] = program.slicing.subgraph_json(slice_result.statements)
            self._send_json(payload)
            return
        if rest == "/report":
            fmt = query.get("format", "json")
            if fmt == "html":
                self._send_text(render_html(program, run_id=run_id), "text/html")
                return
            if fmt == "json":
                self._send_text(
                    to_json_text(build_report(program, run_id=run_id)), "application/json"
                )
                return
            raise ApiError(400, "invalid-format", "format must be 'json' or 'html'")
        raise ApiError(404, "not-found", f"no such run endpoint: {rest}")

    # ------------------------------------------------------------------
    # POST endpoints
    # ------------------------------------------------------------------
    def _analyze(self, payload: dict) -> None:
        source = payload.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ApiError(400, "missing-source", "the request must contain a non-empty 'source' string")
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ApiError(413, "source-too-large",
                           f"source exceeds the {MAX_SOURCE_BYTES} byte analysis limit")
        filename = payload.get("filename") or "<submitted source>"
        if not isinstance(filename, str) or len(filename) > 200:
            raise ApiError(400, "invalid-filename", "filename must be a string of at most 200 characters")
        parser_mode = payload.get("parser_mode", "lalr")
        if parser_mode not in ("lalr", "slr", "canonical"):
            raise ApiError(400, "invalid-parser-mode",
                           "parser_mode must be one of lalr, slr, canonical")
        use_builtin = payload.get("use_builtin_rules", True)
        if not isinstance(use_builtin, bool):
            raise ApiError(400, "invalid-parameter",
                           "'use_builtin_rules' must be a boolean")
        run_dependencies = payload.get("run_dependencies", True)
        if not isinstance(run_dependencies, bool):
            raise ApiError(400, "invalid-parameter",
                           "'run_dependencies' must be a boolean")

        rule_set, rule_diagnostics = self._resolve_rules(payload, use_builtin)

        try:
            program = analyse_source(
                source,
                filename=filename,
                rules=rule_set,
                parser_mode=parser_mode,
                # Slices traverse the dependency graph, so skipping the graph
                # skips the slices as well; findings never depend on either.
                run_dependencies=run_dependencies,
                run_slicing=run_dependencies,
                # ``_resolve_rules`` already combined the built-in and submitted
                # rule files, so the pipeline must not merge them a second time.
                include_builtin_rules=False,
            )
        except ValueError as exc:
            raise ApiError(422, "analysis-rejected", str(exc)) from exc
        except RecursionError as exc:  # deeply nested input
            raise ApiError(422, "input-too-deep",
                           "the analysis exceeded the recursion budget; the input is too deeply "
                           "nested for the supported subset") from exc

        run_id = self.store.put(program, rule_set)
        payload_out = self._run_summary(program, run_id)
        payload_out["status"] = "completed"
        payload_out["grammar"] = {
            "productions": program.metrics.get("grammar_productions"),
            "states": program.metrics.get("grammar_states"),
            "conflicts": program.metrics.get("grammar_conflicts"),
            "parser_mode": program.metrics.get("parser_mode"),
        }
        payload_out["rule_diagnostics"] = [d.to_json() for d in rule_diagnostics]
        self._send_json(payload_out)

    def _resolve_rules(self, payload: dict, use_builtin: bool = True) -> Tuple[RuleSet, list]:
        rules_text = payload.get("rules")
        if rules_text is not None and not isinstance(rules_text, str):
            # Silently falling back to the built-in rules would report a different
            # rule set than the caller asked for without saying so.
            raise ApiError(400, "invalid-parameter", "'rules' must be a string")
        if isinstance(rules_text, str) and len(rules_text.encode("utf-8")) > MAX_SOURCE_BYTES:
            # The documented rule-file limit (API.md sec.7) applies wherever a rule
            # file is accepted; /api/analyze used to accept megabytes of rules
            # while /api/rules/validate rejected the same text with 413.
            raise ApiError(413, "rules-too-large", "the rule file exceeds the analysis limit")
        builtin, diagnostics = load_builtin_rules()
        if not isinstance(rules_text, str) or not rules_text.strip():
            if use_builtin:
                return builtin, diagnostics
            # The caller explicitly disabled the built-in rules and submitted
            # no replacement: analyse with an empty rule set, not the built-in
            # one.  Returning the built-in set here would silently report
            # findings the caller asked not to look for.
            return RuleSet(origin="no rules (built-in rules disabled)"), []
        custom, custom_diagnostics, _parsed = parse_and_validate(
            rules_text, "<submitted rules>", origin="submitted rules"
        )
        errors = [d for d in custom_diagnostics if d.severity == "error"]
        if errors:
            raise ApiError(
                422,
                "invalid-rules",
                "the submitted rule file did not pass validation",
                "; ".join(f"{d.code} line {d.line}: {d.message}" for d in errors[:5]),
            )
        if not use_builtin:
            return custom, list(custom_diagnostics)
        from ..rules.model import merge

        return merge(builtin, custom), list(diagnostics) + list(custom_diagnostics)

    def _validate_rules(self, payload: dict) -> None:
        rules_text = payload.get("rules")
        if not isinstance(rules_text, str) or not rules_text.strip():
            raise ApiError(400, "missing-rules", "the request must contain a non-empty 'rules' string")
        if len(rules_text.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ApiError(413, "rules-too-large", "the rule file exceeds the analysis limit")
        rule_set, diagnostics, parsed = parse_and_validate(rules_text, "<submitted rules>", origin="submitted rules")
        tables = rule_tables()
        self._send_json(
            {
                "valid": not any(d.severity == "error" for d in diagnostics),
                "diagnostics": [d.to_json() for d in diagnostics],
                "stats": rule_set.stats(),
                "rules": [rule.to_json() for rule in rule_set.all_rules()],
                "parse": {
                    "accepted": parsed.accepted,
                    "tokens": parsed.tokens,
                    "seconds": parsed.parse_seconds,
                },
                "grammar": {
                    "productions": len(tables.grammar.productions),
                    "states": tables.automaton.stats.states,
                    "conflicts": len(tables.conflicts),
                },
            }
        )

    def _compare(self, payload: dict) -> None:
        before_id, after_id = payload.get("before"), payload.get("after")
        # The type test comes before the emptiness test.  With the emptiness test first,
        # a *present* but empty list or object (`{}`, `[]`) was reported as
        # "missing-parameter", which says the field was absent when it was not; only the
        # key being absent or explicitly null is "missing".
        if before_id is None or after_id is None:
            raise ApiError(400, "missing-parameter", "'before' and 'after' run ids are required")
        if not isinstance(before_id, str) or not isinstance(after_id, str):
            # ComparisonRequest (docs/API.md §6) types both as strings.  A truthy
            # non-string used to reach RunStore.get, whose dict lookup raised
            # "unhashable type" for a list/dict and surfaced as a 500.
            raise ApiError(400, "invalid-parameter", "'before' and 'after' must be run id strings")
        if not before_id or not after_id:
            raise ApiError(400, "missing-parameter", "'before' and 'after' run ids must not be empty")
        before = self.store.get(before_id)
        after = self.store.get(after_id)
        if before is None or after is None:
            raise ApiError(404, "run-not-found", "one of the runs is no longer available in memory")
        from ..findings.models import compare_findings

        diff = compare_findings(before["program"].findings, after["program"].findings)
        diff["before"] = {"run_id": before_id, "filename": before["program"].filename}
        diff["after"] = {"run_id": after_id, "filename": after["program"].filename}
        self._send_json(diff)

    # ------------------------------------------------------------------
    # payload builders
    # ------------------------------------------------------------------
    def _run_summary(self, program: Program, run_id: str) -> dict:
        metrics = dict(program.metrics)
        timings = metrics.get("timings", {})
        total = sum(v for v in timings.values() if isinstance(v, (int, float)))
        return {
            "run_id": run_id,
            "filename": program.filename,
            "accepted": program.parse.accepted,
            "summary": {
                "findings": len(program.findings),
                "by_severity": _tally(program.findings, lambda f: f.severity),
                "by_category": _tally(program.findings, lambda f: f.category),
                "by_certainty": _tally(program.findings, lambda f: f.certainty),
                "errors": len([d for d in program.diagnostics if d.severity == "error"]),
                "warnings": len([d for d in program.diagnostics if d.severity == "warning"]),
                "unsupported_constructs": len(set(program.semantic.unsupported_offsets)),
                "functions": list(program.cfgs),
                # What was seen but deliberately not reported, why this analysis
                # is partial (if it is), and whether the taint fixpoint converged.
                # The interface shows these next to the findings, so a short
                # finding list is never mistaken for a clean bill of health.
                "dispositions": dispositions(program),
                "analysis_complete": program.analysis_complete,
                "partial_reasons": list(program.partial_reasons),
                "analysis_converged": program.taint.converged,
                # Whether the dependency graph and the slice engine exist for
                # this run.  Both are skipped when the request sets
                # ``run_dependencies`` to false; the graph and slice endpoints
                # then answer 409 and the interface says so instead of failing.
                "dependencies_built": program.dependencies is not None,
                "slicing_available": program.slicing is not None,
            },
            "diagnostics": [d.to_json() for d in program.diagnostics],
            "findings": [f.to_json(include_path=False) for f in program.findings],
            "metrics": metrics,
            # Statement index: id, position, text and home block.  The interface
            # needs it to offer slice criteria and to navigate to a statement
            # without asking for every statement individually.
            "statements": self._statements_detail(program, sorted(program.statements)),
            "total_analysis_seconds": round(total, 6),
            "rules": program.rules.stats(),
            "limits_hit": list(program.limits_hit),
            "notes": list(program.taint.notes),
            "engine_version": ENGINE_VERSION,
        }

    def _statements_detail(self, program: Program, sids,
                           limit: int = MAX_STATEMENT_INDEX) -> List[dict]:
        """Per-statement rows for payload tables.

        ``limit`` bounds the work: the documented statement index of the
        analyse response lists the first ``MAX_STATEMENT_INDEX`` statements
        (docs/API.md §7), and the slice payloads use the same bound and say
        so with ``statements_detail_truncated`` instead of silently showing
        fewer rows than the slice header counts.
        """
        out: List[dict] = []
        for sid in sids[:limit]:
            node = program.statements.get(sid)
            if node is None:
                continue
            function = program.function_of_statement(sid)
            out.append(
                {
                    "sid": sid,
                    "line": node.line,
                    "col": node.col,
                    "kind": node.kind,
                    "text": program.statement_text(sid).strip(),
                    "function": function,
                    "block": program.block_of_statement(sid, function),
                }
            )
        return out

    def _statement_detail(self, program: Program, sid: int) -> dict:
        node = program.statements.get(sid)
        if node is None:
            raise ApiError(404, "statement-not-found", f"no statement with id {sid} in this run")
        function = program.function_of_statement(sid)
        analysis = program.analyses.get(function) if function else None
        payload: dict = {
            "sid": sid,
            "text": program.statement_text(sid).strip(),
            "kind": node.kind,
            "line": node.line,
            "col": node.col,
            "span": list(node.span),
            "function": function,
            "block": program.block_of_statement(sid, function),
            "ast": node.to_json(max_depth=3),
        }
        if analysis is not None:
            payload["reaching_definitions"] = reaching_definitions_at(program, function, sid)
            payload["live_variables"] = {
                "in": live_variables_at(program, function, sid, "in"),
                "out": live_variables_at(program, function, sid, "out"),
            }
            payload["taint"] = taint_at(program, function, sid)
            payload["control_dependencies"] = [
                {
                    "controller_sid": dep.controller_sid,
                    "condition": dep.condition,
                    "kind": dep.kind,
                    "line": dep.line,
                }
                for dep in dependency_module.control_dependencies(program).get(sid, [])
            ]
        return payload

    def _finding_edges(self, program: Program, finding) -> dict:
        graph = program.dependencies
        if graph is None:
            return {"nodes": [], "edges": []}
        node_ids = {f"s{sid}" for sid in finding.statement_ids if sid >= 0}
        edges = [
            edge.to_json()
            for edge in graph.edges
            if edge.src in node_ids or edge.dst in node_ids
        ]
        return {
            "nodes": [graph.nodes[n].to_json() for n in sorted(node_ids) if n in graph.nodes],
            "edges": edges[:500],
        }

    # ------------------------------------------------------------------
    # static files
    # ------------------------------------------------------------------
    def _serve_static(self, path: str) -> None:
        if path in ("/", "/index.html"):
            path = "/index.html"
        relative = path.lstrip("/")
        candidate = os.path.realpath(os.path.join(FRONTEND_DIR, relative))
        if not candidate.startswith(os.path.realpath(FRONTEND_DIR) + os.sep) and candidate != os.path.realpath(FRONTEND_DIR):
            raise ApiError(403, "path-not-allowed", "the requested path is outside the application directory")
        if not os.path.isfile(candidate):
            raise ApiError(404, "not-found", f"no such file: {path}")
        content_type, _encoding = mimetypes.guess_type(candidate)
        with open(candidate, "rb") as handle:
            body = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", (content_type or "application/octet-stream") + (
            "; charset=utf-8" if (content_type or "").startswith("text/") or content_type == "application/javascript" else ""
        ))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self._cors()
        self.end_headers()
        self.wfile.write(body)


def _tally(findings, key) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for finding in findings:
        value = key(finding)
        counts[value] = counts.get(value, 0) + 1
    return counts


def _example_expectation(path: str) -> str:
    """First ``# expect:`` comment block of an example (documented expectation)."""
    expectations: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped.startswith("#") and "expect" in stripped.lower():
                    expectations.append(stripped.lstrip("#").strip())
                elif stripped.startswith("//") and "expect" in stripped.lower():
                    expectations.append(stripped.lstrip("/").strip())
                elif expectations and not stripped.startswith(("#", "//")):
                    break
    except OSError:
        return ""
    joined = " ".join(expectations)
    lowered = joined.lower()
    if lowered.startswith("expect:"):
        joined = joined[len("expect:"):].strip()
    return joined[:400]


def create_server(host: str = "0.0.0.0", port: int = 8000, verbose: bool = False) -> ThreadingHTTPServer:
    handler = type("BoundCodeTraceHandler", (CodeTraceHandler,), {"verbose": verbose})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve(host: str = "0.0.0.0", port: int = 8000, verbose: bool = False) -> None:
    server = create_server(host, port, verbose)
    # Warm the parser tables and rules once so that the first request is fast
    # and any packaging problem surfaces at start-up rather than mid-request.
    tables = parser_tables()
    rule_set, _ = load_builtin_rules()
    print(
        f"CodeTrace {ENGINE_VERSION} listening on http://{host}:{port}\n"
        f"  grammar: {len(tables.grammar.productions)} productions, "
        f"{tables.automaton.stats.states} LALR states, {len(tables.conflicts)} conflicts\n"
        f"  rules:   {rule_set.version_label()} "
        f"({len(rule_set.sources)} sources, {len(rule_set.sinks)} sinks, {len(rule_set.flows)} flows)",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
