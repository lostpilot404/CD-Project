# HTTP API

The engine and the browser talk over a small JSON API served by the same process
that serves the frontend (`python3 -m codetrace.api --host 0.0.0.0 --port 8000`).
The complete machine-readable catalogue is always available at
**`GET /api/schemas`**, which lists every endpoint and the request/response
schemas below; this document explains the semantics and the limits.

* base URL: `http://<host>:<port>`
* content type: `application/json` for every `/api/…` response except
  `/api/runs/{id}/report?format=html`, which is `text/html`
* errors: always the envelope below, never a stack trace or a server path
* no authentication: the server is meant to run locally; it never executes the
  analysed program and never touches the filesystem outside `frontend/` and
  `examples/`
* CORS: the API answers `Access-Control-Allow-Origin: *` so the preview host can
  call it from a different origin

## 1. Error envelope

```json
{"error": {"code": "invalid-parameter", "message": "'direction' must be 'backward' or 'forward'",
           "detail": ""}}
```

| Status | Codes |
| --- | --- |
| 400 | `missing-source`, `invalid-filename`, `invalid-parser-mode`, `missing-rules`, `invalid-format`, `unknown-analysis`, `missing-parameter`, `invalid-parameter`, `invalid-json` |
| 403 | `path-not-allowed` |
| 404 | `not-found`, `example-not-found`, `run-not-found`, `finding-not-found`, `statement-not-found`, `function-not-found` |
| 409 | `graph-unavailable`, `slicing-unavailable` (the run was analysed with `run_dependencies: false`) |
| 413 | `payload-too-large`, `source-too-large`, `rules-too-large` |
| 422 | `invalid-rules` (detail lists code, line and message), `input-too-deep`, `analysis-rejected` (the source broke a documented analysis limit) |
| 500 | `internal-error` (message is generic; the traceback goes to the server log only) |

## 2. Metadata endpoints

### `GET /api/health`

```json
{"status": "ok", "engine_version": "1.0.0", "api_version": "1.0", "schema_version": "1.0",
 "rules_version": "builtin-3387b7dcd97a95f3",
 "grammar": {"productions": 102, "terminals": 51, "nonterminals": 36,
             "lalr_states": 167, "conflicts": 0, "mode": "lalr"},
 "runs_in_memory": 0, "uptime_seconds": 12.4}
```

### `GET /api/language`

Supported types, statements, expressions, the keyword exclusion table with a
reason per keyword, the six contexts, the five severities and the full
diagnostics catalogue (`code`, `phase`, `meaning`).

### `GET /api/grammar?mode=lalr|slr|canonical`

`start_symbol`, `augmented_start`, sorted `terminals` / `nonterminals`,
`nullable`, `first`, `follow` (all terminal-only), the numbered production list
(`display` + `label`), automaton statistics (states, transitions, items,
`lr1_states_before_merge`, build seconds) and the action/goto entry counts plus
the conflict list. `lalr` is the default; `/api/analyze` accepts any of the three
modes through `parser_mode` (the grammar is conflict-free in all of them, so all
three accept the same language — the tables just differ in size).

### `GET /api/rules`

The active rule set (`sources`, `sinks`, `sanitizers`, `flows`, each rule with
its file/line, category, severity and contexts), the rule-language size
(productions, states, conflicts) and any loader diagnostics.

### `GET /api/examples` and `GET /api/examples/{id}`

The bundled corpus: `id` is `category/name` (for example
`vulnerable/command_injection.ctc`), plus `name`, `category` and the documented
`expectation` taken from the file's `// expect:` comment. The detail endpoint
returns the file `content`. Requests for a path outside `examples/` are refused
with 403.

### `GET /api/schemas`

The schemas (`HealthResponse`, `AnalysisRequest`, `AnalysisResponse`,
`RuleValidationRequest`, `RuleValidationResponse`, `ComparisonRequest`,
`ErrorResponse`) and the endpoint catalogue (21 entries).

## 3. `POST /api/analyze`

Request (`AnalysisRequest`):

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `source` | string | required | CT-C source, ≤ 512 KiB |
| `filename` | string | `<source>` | display name for reports and diagnostics, ≤ 200 chars; never used as a filesystem path |
| `rules` | string | absent | rule file text, validated first; a broken file is `422` |
| `use_builtin_rules` | boolean | `true` | `false` analyses with the submitted rules alone — or with no rules at all when no file is submitted |
| `run_dependencies` | boolean | `true` | `false` skips the dependency graph and the slices; findings are unaffected, but `/graph` and `/slice` then answer `409` |
| `parser_mode` | enum | `lalr` | `lalr`, `slr` or `canonical` |

Response (`AnalysisResponse`):

```json
{"run_id": "9f1c3b7d2a4e", "status": "completed", "accepted": true,
 "filename": "command_injection.ctc",
 "summary": {"findings": 1, "by_severity": {"HIGH": 1}, "by_category": {"command-injection": 1},
             "by_certainty": {"approximate": 1}, "errors": 0, "warnings": 0,
             "unsupported_constructs": 0, "functions": ["build_command", "main"],
             "analysis_complete": true, "partial_reasons": [],
             "dispositions": {"sink_calls_seen": 1, "reported": 1,
                              "unreported_sink_calls": [],
                              "unreported_count": 0, "validator_guards": []}},
 "notes": ["…per-run notes, including any atom cleared by a declared validator guard…"],
 "diagnostics": [{"code": "SEM018", "severity": "warning", "message": "…", "line": 1, "col": 34, "phase": "semantics"}],
 "findings": [{"id": "F…", "rule_id": "command_execution", "category": "command-injection",
               "severity": "HIGH", "certainty": "approximate", "source": {…}, "sink": {…},
               "statement_ids": [1, 2, 3], "explanation": "…"}],
 "statements": [{"sid": 0, "line": 4, "col": 3, "kind": "VarDecl", "text": "…", "function": "main", "block": 0}],
 "metrics": {"source_lines": 12, "tokens": 74, "ast_nodes": 41, "statements": 8, "functions": 2,
             "basic_blocks": 5, "cfg_edges": 5, "definitions": 4, "taint_hits": 1, "findings": 1,
             "dataflow_iterations": 12, "unreachable_blocks": 0,
             "timings": {"lex_seconds": 0.0001, "parse_seconds": 0.0003, "…": 0.0}},
 "total_analysis_seconds": 0.0123, "limits_hit": [], "notes": [], "engine_version": "1.0.0",
 "grammar": {"productions": 102, "states": 167, "conflicts": 0, "parser_mode": "lalr"},
 "rules": {"version": "builtin-…", "sources": 5, "sinks": 8, "sanitizers": 5, "flows": 4},
 "rule_diagnostics": []}
```

The embedded `findings` omit the full `path` (it is large); fetch
`/api/runs/{run_id}/findings/{finding_id}` for the evidence path. `metrics` never
contains invented values: every number is counted during the run, and `timings`
is wall clock for this process. `summary.dependencies_built` and
`summary.slicing_available` state whether the run has a dependency graph and a
slice engine (`false` exactly when the request set `run_dependencies: false`).

## 4. Run endpoints

All of these address a stored run by `run_id`; a run that is gone answers
`404 run-not-found` with the hint to analyse again.

| Endpoint | Meaning |
| --- | --- |
| `GET /api/runs/{id}` | the same summary/metrics as the analyse response |
| `GET /api/runs/{id}/findings` | findings **with** their evidence path; filters `severity`, `category`, `certainty`, `rule`, `q` (substring search over the finding) |
| `GET /api/runs/{id}/findings/{fid}` | one finding plus `dependency_evidence` (the graph nodes and edges around its statements) |
| `GET /api/runs/{id}/findings/{fid}/slice` | the security slice: `statements`, `reasons`, `edges`, `subgraph`, `statements_detail`, the conservative `note` |
| `GET /api/runs/{id}/ast` | the AST with spans, symbol ids and resolutions (`tree`, or `null` with a note when the file did not parse) |
| `GET /api/runs/{id}/cfg?function=NAME` | one function's CFG (blocks with statements, typed successor edges, predecessors, definitions); without `function`, every CFG at depth 1 plus statistics |
| `GET /api/runs/{id}/dataflow?function=NAME&analysis=reaching\|liveness\|definite` | domain, direction, GEN/KILL or USE/DEF, per-block IN/OUT and sizes, `statement_states`, `iterations`, `steps`, `converged`, `processed_order`, `reachable`; `definite` also returns `uninitialised_reads` |
| `GET /api/runs/{id}/statements/{sid}` | one statement: text, kind, line/col, span, enclosing function and block, reaching definitions, live variables, taint atoms, control dependencies, and the AST node for selection in the UI |
| `GET /api/runs/{id}/graph?kinds=data,control,…&limit=4000` | the dependency graph: `nodes`, `edges` (each with `kind`, `family`, `reason`, `condition`, `taint_atoms`), `stats`, `limit`, `truncated` |
| `GET /api/runs/{id}/slice?sid=N&direction=backward\|forward` | a slice from a statement criterion, with `statements_detail` and the conservative note |
| `GET /api/runs/{id}/report?format=json\|html` | the exported report (see `docs/REPORT_SCHEMA.md`); generated on demand, never stored |

`sid` must be an integer and `direction` must be `backward` or `forward`;
anything else is `400 invalid-parameter`. `analysis` must be one of the three
data-flow problems, otherwise `400 unknown-analysis`.

## 5. `POST /api/rules/validate`

```json
{"rules": "version 1\n\nsource s { function input  returns  contexts command }\n"}
```

Response:

```json
{"valid": true, "diagnostics": [{"code": "RULE006", "severity": "error", "message": "…",
                                 "line": 3, "col": 5}],
 "stats": {"sources": 1, "sinks": 0, "sanitizers": 0, "validators": 0, "flows": 0,
           "enabled_flows": 0, "fingerprint": "…"},
 "rules": [{"id": "s", "kind": "source", "function": "input", …}],
 "parse": {"accepted": true, "tokens": 18, "seconds": 0.0004},
 "grammar": {"productions": 40, "states": 78, "conflicts": 0}}
```

A rule file that does not parse is **not** an HTTP error: the answer is
`valid: false` with the diagnostics and an empty `rules` list, because the caller
asked for validation. A missing `rules` field is `400 missing-rules`, and an
oversized one is `413 rules-too-large`. When the same text is submitted to
`/api/analyze`, a file with any error is refused with `422 invalid-rules` and the
first five diagnostics in `detail` — a broken rule set never reaches the engine.

## 6. `POST /api/compare`

```json
{"before": "3f8a…", "after": "9f1c…"}
```

```json
{"new": [], "resolved": [{"id": "F7A2E2F89F9F6", "…": "…"}], "persistent": [],
 "moved": [{"id": "F…", "before": {"line": 1, "col": 20, "severity": "HIGH"},
            "after": {"line": 2, "col": 20, "severity": "HIGH"}}],
 "summary": {"before": 1, "after": 0, "new": 0, "resolved": 1, "persistent": 0, "moved": 0},
 "before": {"run_id": "3f8a…", "filename": "a.ctc"},
 "after": {"run_id": "9f1c…", "filename": "a.ctc"}}
```

Both runs must still be in memory (`404 run-not-found` otherwise). Identity is
derived from the flow, not from line numbers, so a formatting change reports
`moved` rather than `new` + `resolved` (see `docs/COMPILER_THEORY.md` §19).

## 7. Limits

| Limit | Value | Behaviour when exceeded |
| --- | --- | --- |
| request body | 1 100 000 bytes | `413 payload-too-large` |
| source size | 524 288 bytes | `413 source-too-large` |
| rule file size | 524 288 bytes | `413 rules-too-large` |
| unknown statement id | — | `404 statement-not-found` (`/statements/{sid}`); a non-integer `sid` is `400 invalid-parameter` |
| statement index in the analyse response | first 2000 statements | the list is truncated; every statement stays addressable by `sid` |
| functions analysed per run | first 400 declared functions | `limits_hit` names the cap; the remaining functions are not analysed |
| `statements_detail` in slice payloads | first 2000 statements | `statements_detail_truncated: true`; the slice's own `statements` list stays complete |
| graph payload | `limit` ≤ 4000 nodes/edges | `truncated: true` in the payload |
| slice size | 5000 statements, 500 edges | `truncated: true`, note in the slice |
| data-flow fixpoint | 10 000 iterations / 200 000 steps | `converged: false` and a partial-analysis note |
| parse steps / syntax errors | internal caps | `SYN010` / `SYN011`, analysis marked partial |
| stored runs | 24 (LRU) | the oldest run is dropped; the API answers `404 run-not-found` |

An oversized body is rejected before it is parsed, and the bytes already sent are
drained (up to 8 MiB / 5 s) before the connection closes, so the client reads the
`413` error envelope instead of a reset connection. A client that keeps sending
past the drain budget gets the envelope anyway; only the unsent remainder is lost.

## 8. Using the API without the browser

```bash
# start the server
python3 -m codetrace.api --port 8000

# analyse a file
curl -s localhost:8000/api/analyze -H 'content-type: application/json' \
     -d "{\"source\": $(python3 -c 'import json,sys;print(json.dumps(open("examples/vulnerable/command_injection.ctc").read()))'), \"filename\": \"demo.ctc\"}" \
| python3 -m json.tool | head -40
```

The interface calls these endpoints over HTTP and renders whatever the server
returns; the error codes, the size limits and the comparison semantics are the ones
stated in the sections above, always inside the documented envelope.
