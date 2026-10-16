# CodeTrace project handoff

**Purpose:** source-verified orientation for the next AI coding agent working in this checkout.  **As of:** 2026-10-16 UTC.  This document was written from the local repository, current command results and read-only inspection of the DOCX files; no external sources were consulted.

## How to read this handoff

- **Verified in checkout** means confirmed from implementation, tests, a current command, or the actual file artifact.
- **Documented claim** means a repository document says it, but the implementation was not independently confirmed or has a discrepancy noted below.
- **Historical** means a dated report/log describes an earlier commit or earlier run; do not reuse it as a current result.
- If a document conflicts with code, treat the code and a focused test as the implementation truth, and preserve the conflict as an open issue rather than silently reconciling it.

The current request was deliberately bounded: inspect thoroughly and create this handoff, but **do not modify application code, rewrite the project report, or change Git history**. No credentials or other private data are included.

## 1. Executive summary

CodeTrace is a compiler-design project and static-analysis workbench for **CT-C**, a deliberately small C-like source subset. It lexes/parses source, performs semantic analysis, builds control-flow and dependency graphs, solves data-flow problems, tracks configured source-to-sink taint, explains findings and exposes the intermediate results through an HTTP API and a browser UI. Its main entry points are `codetrace/frontend/pipeline.py::parse_source`, `codetrace/analysis/pipeline.py::analyse_source`, and `codetrace/api/server.py`.

It is **not** a full C/C++ compiler, does not compile to machine code, and does not execute submitted programs. It is not a proof of safety or exploitability. Findings are potential flows under the active rules and the analysis approximations; **zero findings means only that this run did not report a configured flow, not that the input is safe**. See `README.md`, `docs/LANGUAGE.md`, `docs/LIMITATIONS.md`, and `codetrace/analysis/pipeline.py`.

Version constants in `codetrace/version.py` are engine `1.0.0`, API `1.0`, report schema `1.0`, and language label `CT-C subset v1`. The frontend is vanilla ES modules; `frontend/package.json` declares no dependencies. The application runtime uses Python's standard library; the optional DOCX builder under `submission/tools/` imports `python-docx` and is separate from the application runtime.

## 2. CT-C language boundary

### Supported surface

The grammar and API language catalogue (`codetrace/frontend/grammar_lang.py`, `codetrace/frontend/tokens.py`, `docs/LANGUAGE.md`, `GET /api/language`) describe:

- Types `int`, `float`, `char`, `bool`, and `string`; `void` is a function return type, not a variable/parameter type.
- Fixed-size arrays, functions with parameters and return values, declarations, assignments, expression statements, blocks and empty statements.
- `if`/`else`, `while`, `for`, `return`, `break`, and `continue`.
- Identifiers, literals, calls, array indexing, unary operators, arithmetic, comparison and logical expressions, assignment operators, and increment/decrement.

The grammar has 102 productions, 51 terminals and 36 non-terminals. It is a one-translation-unit analysis; there is no linker or multi-file analysis. The exact productions and operator precedence are in `docs/LANGUAGE.md` and `codetrace/frontend/grammar_lang.py`.

### Unsupported or partial input

There is no preprocessing or macro expansion, pointer/alias analysis, `struct`/`union`/`enum`, `typedef`, `switch`, `goto`, `do/while`, C++ syntax, dynamic-memory model, or full C type system. Recognized unsupported keywords and preprocessor directives are diagnosed; other unsupported syntax can produce ordinary parser errors. For example, `examples/unsupported/pointer_type.ctc` may yield a generic syntax diagnostic because `*` is also a valid multiplication token. `examples/unsupported/switch_statement.ctc` demonstrates an explicitly unsupported keyword.

A parse-recovered program, an unsupported construct, or a non-unsupported semantic error makes `partial_reasons` non-empty in the current pipeline (`codetrace/analysis/pipeline.py`). Partial runs can still have useful results, but omitted/skipped code means findings are incomplete. Do not describe a successful parse or a clean finding list as a full-C result.

## 3. Architecture and end-to-end flow

At runtime there are two main components: the Python server and the browser. The browser is a thin client and makes relative, same-origin API requests; all compiler and analysis results come from Python (`frontend/js/api.js`, `frontend/js/app.js`, `docs/TECHNICAL_DESIGN.md`).

```text
Browser: frontend/index.html + ES modules
  └─ relative HTTP/JSON request
       └─ codetrace/api/server.py (ThreadingHTTPServer, validation, routes, in-memory RunStore)
            └─ codetrace/analysis/pipeline.py::analyse_source
                 1. lex → parse → AST/source locations
                 2. semantic analysis and symbol/access information
                 3. statement IDs and per-function CFGs
                 4. reaching definitions, liveness, definite assignment
                 5. interprocedural taint summaries and concrete replay
                 6. dependency graph → slices → findings and explanations
                 7. API summary / JSON report / self-contained HTML report
            └─ stores the Program in an in-memory LRU for follow-up endpoints
       └─ browser renders returned results; it does not recompute analysis
```

The exact pipeline order and `Program` contents are implemented in `codetrace/analysis/pipeline.py`. The API stores up to 24 runs in memory (`codetrace/api/server.py::RUN_CACHE_SIZE`); a process restart loses them. Reports are generated on demand and the API does not persist uploaded source or reports to disk (`codetrace/reporting/json_report.py`, `codetrace/reporting/html_report.py`).

## 4. Repository map and runtime commands

| Path | Role / where to start |
| --- | --- |
| `README.md` | Project overview, quick start, capabilities and verification summary. Recheck dated/timing claims against current output. |
| `codetrace/frontend/` | Lexer, tokens, grammar, LR table generator/parser, AST, source locations and `parse_source`. |
| `codetrace/semantics/` | Symbol tables, scopes, type/semantic checks, accesses and external-function catalogue. |
| `codetrace/analysis/` | CFG, generic solver, reaching definitions, liveness, definite assignment, taint, dependency graph, slicing and orchestration. |
| `codetrace/rules/` | Declarative rule model, rule parser/validator and `builtin/standard.ctrule`. |
| `codetrace/findings/` | Finding IDs/models, comparison, path explanation, certainty and remediation text. |
| `codetrace/reporting/` | Canonical JSON report and self-contained HTML renderer. |
| `codetrace/api/` | HTTP server, endpoints, schemas and `python -m` entry point. |
| `frontend/` | Static HTML/CSS/ES-module UI; Node built-in test suite under `frontend/tests/`. |
| `docs/` | Technical design, language, algorithms, compiler theory, API, rule language, report schema, limitations, evaluation, user guide, final-report prose and presentation material. |
| `tests/` | Python unit, API, reporting, integration, audit and mutation-check tests. |
| `evaluation/expectations.json` | Hand-labelled corpus expectations. `evaluation/run_evaluation.py` runs the actual engine and computes the regression metrics. |
| `examples/` | Vulnerable, safe, sanitized, interprocedural, challenge, unsupported, syntax-error and custom-rule examples. |
| `scripts/` | Test, server, audit, evaluation and mutation-check entry points. |
| `submission/` | Historical progress/verification documents, generated DOCX, screenshots, evidence logs, report generator and probes. Do not treat dated values there as current without rerunning. |
| `BCSE307P_Complete_Project_Report_Template.docx` | Actual VIT BCSE307P template at the repository root. It is present despite a contrary statement in an older progress report. |
| `PROJECT_CONTEXT.md` | This handoff; the only file created for the current task. |

### Commands

Python 3.11.2, Node 22.22.3, and npm 10.9.8 were available during this review. The application needs Python 3.11+ according to `scripts/serve.sh`; no `npm install` or frontend build step is required.

```bash
# Start the combined API and static UI. Default bind is all interfaces.
scripts/serve.sh --port 8000
# Equivalent:
python3 -m codetrace.api --host 0.0.0.0 --port 8000

# Full Python + frontend suites:
scripts/tests.sh
# Python suites only:
scripts/tests.sh engine
# Frontend suite alone:
(cd frontend && npm test)

# Current corpus evaluation; choose an output path outside the repo if preferred:
scripts/evaluate.sh /tmp/codetrace-current-evaluation.json

# Independent repository audit:
python3 scripts/audit.py
python3 scripts/audit.py -v

# 18 deliberate mutation tests; this temporarily edits implementation files and restores them:
python3 scripts/mutation_check.py
python3 scripts/mutation_check.py --list
```

`scripts/tests.sh` runs `python3 -m unittest discover -s tests -t .`, then Node's built-in test runner. The current audit is useful but not exhaustive: it passed while several doc/code discrepancies listed below remained.

## 5. Compiler front end and semantic analysis

### Lexer, parser and grammar

`codetrace/frontend/lexer.py` scans CT-C, tracks source offsets/line/column and emits located lexical diagnostics. `codetrace/frontend/tokens.py` separates supported keywords from recognized unsupported keywords/operators. `codetrace/frontend/grammar.py` implements grammar and NULLABLE/FIRST/FOLLOW and LR automata; `codetrace/frontend/clr_parser.py` builds ACTION/GOTO tables, reports conflicts, runs the table-driven parser and recovers from syntax errors; `codetrace/frontend/ast_nodes.py` defines AST node classes. `codetrace/frontend/pipeline.py` joins lexing, parsing and location annotation and caches parser tables in-process.

The default is LALR(1). The API and UI also expose SLR(1) and canonical LR(1) teaching modes. The following table was computed directly from the current `parser_tables(mode)` objects in this checkout; it is not a benchmark:

| Mode | States | Transitions | Total items | Conflicts |
| --- | ---: | ---: | ---: | ---: |
| LALR(1) | 167 | 1,027 | 1,832 | 0 |
| SLR(1) | 167 | 1,027 | 1,832 | 0 |
| Canonical LR(1) | 656 | 4,281 | 110,638 | 0 |

The LR construction follows nullable-aware FIRST/FOLLOW, LR(1) closure/GOTO, canonical collection, LALR core merging, then ACTION/GOTO generation. `docs/COMPILER_THEORY.md` and `docs/ALGORITHMS.md` explain the algorithms. The parser has a 400,000-step cap and a 25-error recovery cap (`codetrace/frontend/clr_parser.py`); key diagnostics include `SYN001`, `SYN010`, `SYN011`, and `SYN100`.

### Semantic pass

`codetrace/semantics/analyzer.py` builds nested scopes and stable symbol identities, resolves names/calls and records reads/writes/definitions for later phases. It diagnoses undeclared or duplicate names, type/argument/return mismatches, unsupported operations and related issues. `codetrace/semantics/externals.py` supplies external signatures and categories; configured sources/sinks/sanitizers/validators are represented in `codetrace/rules/` and drive taint policy. An unknown external is not assumed safe: the analysis warns and conservatively allows its result to depend on tainted arguments.

The API catalogue at `GET /api/language` is **not actually complete**: see the diagnostic-catalogue discrepancy in §9. `docs/LANGUAGE.md` says it is complete, but semantic code currently emits at least `SEM103`, `SEM900`, and `SEM901`, which are not included in `codetrace/api/server.py::DIAGNOSTIC_CATALOGUE`.

## 6. Analysis algorithms and interpretation

### CFG and IDs

`codetrace/analysis/cfg.py` builds a structured CFG for each function, with entry/exit and typed sequential, true/false, loop-back, break, continue, return and exit edges. Statement IDs are assigned in source-span order; definitions include parameters/file-scope values, initialized and uninitialized declarations, assignments, and increment/decrement. Unreachable-after-terminator statements remain represented and can receive `CFG001`.

CFG reachability is structural: a branch whose condition is literally false is still connected in the CFG and in the classical data-flow analyses. The taint engine separately prunes only simple literal branches. Do not conflate a structurally reachable block with a feasible runtime path.

### Classical data flow

`codetrace/analysis/dataflow.py` is a reusable bit-vector worklist solver. It visits reachable CFG blocks, records iterations/steps/convergence, and supports forward/backward direction and union/intersection meets.

- **Reaching definitions** (`codetrace/analysis/reaching_definitions.py`) is forward/may, with union at joins: `IN[B] = ⋃ OUT[pred]`; `OUT[B] = GEN[B] ∪ (IN[B] − KILL[B])`. Per-statement state is obtained by replaying transfers inside each block.
- **Liveness** (`codetrace/analysis/liveness.py`) is backward/may: `OUT[B] = ⋃ IN[succ]`; `IN[B] = USE[B] ∪ (OUT[B] − DEF[B])`.
- **Definite assignment** (`codetrace/analysis/definite_assignment.py`) is forward/must, using predecessor intersection and a top initial value for non-entry blocks. Parameters and file-scope variables are assigned at function entry; a read not definitely assigned can produce warning `DFA001`.

The public data-flow endpoint and UI expose domains, direction, GEN/KILL or USE/DEF, per-block and per-statement IN/OUT facts, iteration/step counts and convergence. These analyses do not perform symbolic execution or prove branch conditions.

### Taint, rules and findings

`codetrace/analysis/taint.py` tracks context-tagged atoms such as `src:stdin@command`, symbolic parameter atoms and global atoms. Taint is a flow-sensitive **may** analysis: facts are unioned at CFG joins; assignment retargets the value's atoms to the receiving symbol. Interprocedural propagation first computes parameter-to-return summaries, then concrete parameter/global propagation, then replays the states to collect sink hits. Each fixpoint loop is capped at 12 iterations by default. The result is explicitly context-insensitive across call sites.

Important precision boundaries verified in `codetrace/analysis/taint.py` and `codetrace/findings/explain.py`:

- A sink reports only when a configured source-to-sink flow connects the source and sink rule and the taint context matches the sink context.
- Unknown external calls conservatively propagate argument taint to the result. Sanitizers remove only declared argument/context atoms; another context survives.
- Literal `false`/`0` true-edges and `true`/`1` false-edges can be pruned in taint analysis. This is syntactic literal handling, not constant propagation or interval reasoning.
- Validator guards are narrow: direct `if (validator(x))` refines the true edge, and `if (!validator(x))` the false edge; only a plain identifier argument is refined. Compound conditions are not interpreted. Validator bodies are not checked; a guard suppression is an assumption and is surfaced in notes/dispositions/limitations.
- Implicit/control-dependent taint is not tracked. Arrays are coarse (elements are not individually distinguished); pointer aliasing is not modelled. Loops and summary joins can over-approximate.

`codetrace/findings/explain.py` reconstructs a source-to-sink explanation using taint state and reaching definitions. Finding IDs are derived from the flow/sink identity and normalized sink text, not line number (`codetrace/findings/models.py`). Certainty is `confirmed`, `approximate`, or `unproven`; it is not a probability. Straight-line, intraprocedural, resolved paths can be confirmed; interprocedural summaries, guarded paths, unsupported constructs or unknown calls make a result approximate; unresolved origins or a known-false guard can be unproven. Every finding is static evidence, not proof of exploitability.

### Dependency graph and slices

`codetrace/analysis/dependencies.py` builds statement/definition/function nodes and typed define, data, taint, control, call, return, sanitizer and source-to-sink edges. Data edges are based on reaching definitions. `codetrace/analysis/slicing.py` traverses dependency edges for backward, forward and finding-focused slices and records reasons. The result is conservative and may include extra statements; it is not a minimal slice. Slice serialization limits are described in §9.

## 7. Declarative security rule language

The rule language (`codetrace/rules/rule_language.py`, `codetrace/rules/model.py`) is data-only: `version 1`, `source`, `sink`, `sanitizer`, `validator`, and `flow` declarations with literal attributes and lists. It has no expressions, control flow, host-language calls or execution. It is parsed by the project's LR machinery; the current rule grammar is 40 productions, 78 LALR states, 0 conflicts. Validation rejects malformed identifiers, duplicates, unknown/invalid attributes, invalid contexts/severities/argument indices, missing/unknown references and ambiguous function bindings. Rule diagnostics are `RULE...` codes.

Contexts are `command`, `sql`, `path`, `html`, `numeric`, and `format`; severities are `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, and `INFO`. Built-ins in `codetrace/rules/builtin/standard.ctrule` currently contain 5 sources, 8 sinks, 5 sanitizers, 2 validators, and 4 enabled flows (fingerprint `builtin-3387b7dcd97a95f3`). The built-in sources include `input`, `input_int`, `readenv`, `argv`, and `readfile`; `readfile` is intentionally both a source for returned file content and a path sink for its argument. Sinks include `system`, `exec`, `popen`, `fopen`, `readfile`, `writefile`, `sql_exec`, and `printf`. Sanitizers include `shell_escape`, `sql_escape`, `html_escape`, `path_normalize`, and `to_int`; validators include `is_safe_command` and `is_valid_path`.

Custom rules extend built-ins by default; a submitted rule with the same ID overrides that entry. `use_builtin_rules: false` uses the submitted rules alone, or no rules when no custom file is supplied (`codetrace/rules/model.py::merge`, `codetrace/api/server.py::_resolve_rules`). Use `examples/custom_rules/strict_rules.ctrule`, `examples/custom_rules/custom_rule_demo.ctc`, and `docs/RULE_LANGUAGE.md` for a working example. Rule files are not executable code.

## 8. Frontend, HTTP API and reports

### Browser UI

`frontend/index.html` defines nine routes/views: Overview, Analyze Code, Findings, Program Graph, Data-Flow Analysis, Program Slicing, Rule Editor, Reports, and Documentation. `frontend/js/api.js` uses relative URLs, a 30-second default timeout and a 60-second analysis timeout. `frontend/js/app.js` coordinates views/state; view modules live under `frontend/js/views/`; `frontend/js/graph.js` lays out server-provided graph data but does not perform the analysis.

### HTTP API

The API is implemented in `codetrace/api/server.py`; schemas and its endpoint catalogue are in `codetrace/api/schemas.py`; the human-readable reference is `docs/API.md`. Useful endpoints include `/api/health`, `/api/language`, `/api/grammar`, `/api/rules`, `/api/examples`, `POST /api/analyze`, `POST /api/rules/validate`, `POST /api/compare`, and per-run endpoints for findings, AST, CFG, data flow, statements, graph, slices and reports. `/api/analyze` returns a compact summary; fetch the finding detail or report to obtain the full evidence path.

### Report formats

`codetrace/reporting/json_report.py` builds the canonical report: input hash/filename, engine/rule/grammar provenance, summary/dispositions, findings and path evidence, diagnostics, unsupported features, analysis/metrics, notes and limitations. `codetrace/reporting/html_report.py` renders that report as a self-contained HTML document; it escapes source/user-facing values and has no external scripts or references. The API generates reports on demand. The UI supports JSON and HTML exports; no PDF generator is part of the application.

## 9. Security posture, limitations and known documentation drift

### Tool security is not analyzer completeness

The implementation is designed to treat submitted CT-C source and rule text as data, not executable code. The API's analysis path does not execute the input. Static files are resolved under `frontend/`, bundled examples under `examples/`, and the server does not write submitted source or reports to disk. HTML report data is escaped (`codetrace/api/server.py`, `codetrace/reporting/html_report.py`, `tests/test_api.py`, `tests/test_reporting.py`). These properties do **not** prove the application safe against every malicious input or runtime defect.

The API has **no authentication**, sends `Access-Control-Allow-Origin: *`, and binds to `0.0.0.0` by default (`codetrace/api/server.py`, `codetrace/api/__main__.py`). Treat it as a local/demo or protected-proxy service, not a public multi-user service. An exposed instance can accept analyses and consume its resources. The in-memory run store is not persistent and is not a security boundary.

### Limits confirmed from code

- HTTP request body: 1,100,000 bytes (`codetrace/api/server.py::MAX_BODY_BYTES`).
- Source and submitted rule text: 512 KiB (`MAX_SOURCE_BYTES` is `512 * 1024` in `codetrace/analysis/pipeline.py` and `codetrace/api/server.py`).
- Source line count: 20,000 (`codetrace/analysis/pipeline.py`).
- Parser: 400,000 table steps and 25 syntax errors (`codetrace/frontend/clr_parser.py`).
- Classical data-flow fixpoint: 10,000 iterations and solver default 200,000 steps (`codetrace/analysis/pipeline.py`, `codetrace/analysis/dataflow.py`).
- Taint summaries/concrete propagation: 12 iterations per loop by default (`codetrace/analysis/taint.py`).
- In-memory run LRU: 24 (`codetrace/api/server.py`).
- Analyze response statement list: first 2,000 (`MAX_STATEMENT_INDEX` in `codetrace/api/server.py`); the API can address statements by ID.
- Slice result: 5,000 statements / 500 edges (`codetrace/analysis/slicing.py`), with a traversal guard at four times the statement limit.
- Parser automaton construction guard: 2,500 states (`codetrace/frontend/grammar.py`).

### Discrepancies that must not be papered over

1. **Size limits drift.** Code enforces 512 KiB source and rule text. `docs/TECHNICAL_DESIGN.md` and `docs/LIMITATIONS.md` claim a 1 MiB source limit; `docs/RULE_LANGUAGE.md` claims a 1 MiB rule-file limit. `docs/API.md` and the later threat-model prose in `docs/LIMITATIONS.md` correctly say 512 KiB. Use the code/API values above until maintainers reconcile the docs.
2. **Not every recorded limit marks the run partial.** `codetrace/analysis/pipeline.py` appends some events to `limits_hit`, but `analysis_complete` is computed from `partial_reasons`, which is populated for parse rejection, unsupported constructs and semantic errors. A function-count warning (`MAX_FUNCTIONS = 400`) is recorded, but the shown pipeline continues building CFGs and running analyses for `cfgs`; the comment says only the first 400 are analysed, but no truncation occurs at that point. Solver non-convergence is recorded in `limits_hit`/convergence fields, not automatically added to `partial_reasons`. The API's `status: completed` means the request completed; inspect `analysis_complete`, `partial_reasons`, `limits_hit`, and per-analysis `converged` rather than treating that status as completeness. This differs from claims in `docs/TECHNICAL_DESIGN.md`, `docs/LIMITATIONS.md`, and `docs/USER_GUIDE.md` that every cap marks the analysis partial.
3. **Graph limit is not a hard cap as documented.** The server passes the `limit` query value directly to `DependencyGraph.to_json` (`codetrace/api/server.py`, `codetrace/analysis/dependencies.py`). The default is 4,000, but the query is not clamped to 4,000; `truncated` is computed from edge count, even though node serialization can also be truncated. Do not claim that every graph response is strictly bounded to 4,000 nodes/edges with a reliable truncation flag until this is fixed/tested. `docs/API.md` currently states a maximum of 4,000.
4. **Filename validation differs from one guide sentence.** The `/api/analyze` implementation accepts a display filename of at most 200 characters and does not reject path separators; it does not use that filename as a filesystem path (`codetrace/api/server.py::_analyze`). `docs/USER_GUIDE.md` says a path separator causes `invalid-filename`, which is not implemented.
5. **Diagnostic catalogue is incomplete.** `codetrace/semantics/analyzer.py` emits `SEM103`, `SEM900`, and `SEM901`; `codetrace/api/server.py::DIAGNOSTIC_CATALOGUE` omits them, while `docs/LANGUAGE.md` and `docs/API.md` describe the API catalogue as full/complete.
6. **Canonical-parser statistics in the algorithms document are mislabeled.** `docs/ALGORITHMS.md` §3 associates canonical LR(1)'s 656 states with 1,027 transitions and 1,832 total items. Those latter values are the current LALR/SLR numbers. Current computed canonical statistics are 656 states, 4,281 transitions and 110,638 total items (see §5 above). Do not copy the stale row into a report.
7. **Timing and corpus descriptions are not interchangeable.** README/`docs/ALGORITHMS.md` cite about 1.2 seconds. The current evaluation run's printed aggregate was 1.7074 seconds, calculated by summing per-case timers around `analyse_source` (not total shell-command wall time). Timing varies by environment; the old figure is not today's run. Also, `submission/VERIFICATION_REPORT.md` describes 20 vulnerable files plus 4 interprocedural cases; the current `evaluation/expectations.json` has 33 cases, 20 expected findings across 18 finding-bearing cases, 9 safe/sanitized cases, and 6 diagnostic-only unsupported/syntax-error cases. Prefer the current expectations file and current evaluator output.

The analyzer's core limits remain: no implicit-flow analysis, alias or pointer analysis, precise array-element tracking, symbolic execution, general path feasibility, range analysis or context-sensitive call-site summaries. A validator guard assumes the validator implementation is trustworthy; sanitizer behavior assumes rule declarations are accurate. A zero-finding run cannot rule out vulnerabilities outside the supported language, rules, or approximations. See `docs/LIMITATIONS.md` for the fuller narrative, but apply the code/doc discrepancies above.

## 10. Useful workflows and checked examples

### Run the UI and analyze an example

```bash
scripts/serve.sh --port 8000
# Open the app at the server's host/port, load vulnerable/command_injection.ctc, run analysis.
```

The API can be used without the UI; `docs/API.md` has the complete request shapes. For example, load `examples/vulnerable/command_injection.ctc` in the Analyze view or POST its text as the `source` field to `/api/analyze`. Use `/api/runs/{run_id}/findings/{finding_id}` to inspect the full trace, `/graph` for the typed graph, `/slice` or the finding slice endpoint for a conservative slice, and `/report?format=json|html` for exports.

### Current source-to-sink example

A fresh direct analysis of `examples/vulnerable/command_injection.ctc` in this checkout returned: parse accepted, analysis complete, no diagnostics, 5 executable statements, 1 command-injection finding, HIGH severity, `approximate` certainty. The source is `input()` at line 8; data flows through `name`, the `build_command()` parameter/return summary and `command` to `system(command)` at line 10. The evidence path has 8 steps. It is approximate because it crosses a function boundary and the interprocedural summaries are context-insensitive. The finding ID in this exact source/rule version was `FEF13A28F7E0E`.

`examples/sanitized/shell_escape.ctc` produced zero findings in the same direct check. That only means no configured flow was reported for that input; it is not a proof of safety. `examples/safe/constant_command.ctc`, `examples/safe/dead_branch_sink.ctc`, and other safe/sanitized cases are regression examples, not general safety certificates.

### Syntax recovery example

`examples/syntax_errors/missing_semicolon.ctc` is not accepted; current engine output contains two `SYN001` diagnostics (`unexpected identifier 'system'` at 4:3 and `unexpected ;` at 4:15), no findings, and a partial-analysis reason. The historical verification report explains the known diagnostic-quality issue: the first error is positioned at the next token rather than the omitted semicolon, and `;` is absent from that expected-token list. See `submission/evidence/ui_syntax_error_missing_semicolon.txt` and `submission/screenshots/09-syntax-error.png`.

### Custom rules

Use `examples/custom_rules/strict_rules.ctrule` with `examples/custom_rules/custom_rule_demo.ctc`, or submit text to `POST /api/rules/validate` before analysis. By default custom declarations extend the built-ins. To test an isolated policy, explicitly turn off built-ins. The rule validator rejects errors before an analysis run; rule text is never evaluated as Python or C.

## 11. VIT BCSE307P report/template and screenshot handoff

### Actual template requirements

The root file `BCSE307P_Complete_Project_Report_Template.docx` is present. Its extracted text/XML specifies Vellore Institute of Technology, Vellore; School of Computer Science and Engineering; `BCSE307P – Compiler Design Lab`; a project-report title; team-member names and registration numbers; guide Nithya K., Assistant Professor Senior Grade II; and the literal cover date `SEPTEMBER, 2026`. It includes a bonafide certificate, declaration, abstract prompt of **150–250 words**, table of contents, four numbered chapters, screenshots, progress/challenges, conclusion/future enhancements and references.

The template's actual chapter/subsection structure is:

- **Chapter 1 – Introduction:** 1.1 Background; 1.2 Problem Statement; 1.3 Objectives & Novelty.
- **Chapter 2 – Literature Survey:** 2.1 Existing Systems / Related Work; 2.2 Research Gap.
- **Chapter 3 – System Design:** 3.1 Proposed System Architecture; 3.2 Module Description; 3.3 Compiler Phases Implementation.
- **Chapter 4 – Implementation Details.**
- **Screenshots – Evidence of the working application, including successful compilation and error detection.**
- **Current Progress and Challenges; Conclusion and Future Enhancements; References.**

The DOCX XML confirms US Letter page size and one-inch margins on all sides. The inspected template did not establish an explicit body-font/size or line-spacing rule; confirm any additional department formatting requirements instead of guessing. The template's cover date is September 2026; confirm with the team/faculty whether that literal date remains appropriate for the final submission.

### Actual generated DOCX is not the template structure

`submission/CodeTrace_Project_Report.docx` is generated from scratch by `submission/tools/build_report.py` (`Document()`), not from the root template. Its real heading structure was extracted from the DOCX and is:

- Front matter: Bonafide Certificate; Declaration; Abstract; Table of Contents.
- **1. Introduction:** 1.1 Motivation; 1.2 Objectives; 1.3 Scope and non-goals.
- **2. Literature Review:** 2.1 Parsing; 2.2 Data-flow analysis; 2.3 Taint analysis; 2.4 Program dependence and slicing; 2.5 Gap addressed.
- **3. System Design:** 3.1 Architecture; 3.2 Stages; 3.3 Design decisions.
- **4. Implementation:** 4.1 Front end; 4.2 Analyses; 4.3 Rules; 4.4 Interface.
- **5. Testing and Results:** 5.1 Verification commands; 5.2 Independent checks; 5.3 Corpus; 5.4 Mutation check; 5.5 Browser results; 5.6 Defects found and fixed in this phase; 5.7 Known limits.
- **6. Progress Against the Rubric:** 6.1 Core items; 6.2 Extension items; 6.3 Overall measurement and decision point; 6.4 Remaining work.
- **7. Conclusion and Future Work; References; Appendix A. Evidence Index.**

This is a material structure mismatch, not a numbering detail: generated-report §3.3 is “Design decisions” (there is no “Compiler Phases” section), and §4.2 is a general analysis paragraph, not a command-injection code/listing/evidence subsection. Do not claim the generated DOCX follows the official template. The older `submission/PROGRESS_STATUS.md` says the official template was absent; that is contradicted by the root template now present in this checkout.

The report generator uses Times New Roman 12 pt normal text and 16/13/12 pt headings, 1.1-inch left/right and 1-inch top/bottom margins, adds a page-number field and asks Word to update fields. Those are generator choices, not confirmed template requirements. The TOC is a Word field with an “Update Field” placeholder; verify/refresh it in an office application before any final submission. The actual DOCX still has personal-data placeholders and embeds the old branch name `arena/cd8dc62b-cd-project` in its declaration. Its abstract/table also carries the historical 304 Python / 30 frontend counts and the self-assessed 82.75% rubric total. The rubric percentage is not a current test result or an official course grade. The builder itself asks that bibliographic details be verified (`submission/tools/build_report.py`). **None of the DOCX, generator, template or report prose was modified in this task.**

### Screenshot inventory and exact requested placements

The capture script and log (`submission/tools/ui_capture.mjs`, `submission/evidence/ui_capture_log.json`) say the ten existing PNGs were captured from the running interface; the logged capture had zero console and page errors. Current assets in `submission/screenshots/` are:

| Asset | What the checked capture shows |
| --- | --- |
| `01-overview.png` | Engine/pipeline overview. |
| `02-analyze-vulnerable-run.png` | Analyze view after the command-injection example runs. |
| `03-findings-list-and-detail.png` | HIGH, approximate command-injection finding, explanation and 8-step source-to-sink evidence path. |
| `04-program-graph.png` | Typed program/dependency graph. |
| `05-dataflow.png` | Data-flow page; capture workflow documents reaching-definitions/liveness/definite-assignment exploration. |
| `06-slicing.png` | Program slicing view. |
| `07-reports.png` | JSON/HTML report exports. |
| `08-safe-counterpart-zero-findings.png` | Zero findings plus explicit warning that this is not a proof of safety. |
| `09-syntax-error.png` | Missing-semicolon syntax diagnostics and partial run. |
| `10-unsupported-switch.png` | Unsupported `switch` diagnostic and partial run. |

`03b-finding-evidence-path-closeup.png` and `04b-program-graph-closeup.png` **do not exist** in the repository. The full-page `03` and `04` assets are present but are not close-up assets; do not rename them or claim they are the requested close-ups. PNG dimensions checked earlier include 02 at 1440×1402, 03 at 1440×2053, and 04/05 at 1440×1000.

The following are the user's requested placements for a future report edit, written here exactly as requirements. They are **not** the current DOCX layout:

1. Put `02-analyze-vulnerable-run.png` **before the command-injection listing in Section 4.2, after its intro**. The current §4.2 has no such listing; the existing DOCX instead puts screenshot 02 in §5.5.
2. Put `03b-finding-evidence-path-closeup.png` **after code and finding/evidence explanation in Section 4.2**. That asset and the required code/evidence explanation are absent from the current generated DOCX; the full-size `03-findings-list-and-detail.png` currently appears in §5.5.
3. Put `04b-program-graph-closeup.png` **in the system-design module discussion after the module table and before compiler-phases**. The close-up is absent. The official template has 3.2 Module Description and 3.3 Compiler Phases Implementation; the generated DOCX instead has 3.2 Stages and 3.3 Design decisions, and its full-size `04-program-graph.png` is in §5.5.
4. Put `05-dataflow.png` **after data-flow explanation**. The asset exists, but the generated DOCX does not insert it; §4.2 currently explains analyses in prose only.
5. Put `09-syntax-error.png` **after syntax-analysis explanation**. The asset exists; the generated DOCX currently puts it in §5.5, not after the parser explanation in §4.1.

Any later report work should first resolve the template/heading mismatch, obtain the real team details, update stale verification/branch text, and generate or obtain the two missing close-ups from genuine UI evidence if they remain mandatory. Those are future actions, not work done here.

## 12. Current verification and Git state

### Fresh checks on this checkout

All results below were produced on 2026-10-16 from the current HEAD `9e3a54b9601ba8ae630171fdbdfa629a56022671` before this Markdown handoff was created:

| Check | Current result |
| --- | --- |
| `scripts/tests.sh` | Passed: **310 Python tests** and **39 frontend tests**. |
| `python3 scripts/audit.py` | Passed: **69 checks**. |
| `scripts/evaluate.sh /tmp/codetrace-current-evaluation.json` | All **33** cases passed; 20 expected findings, 20 reported, TP=20, FP=0, FN=0; file-level TN=9/9 and file-level FP=0; precision=1.0, recall=1.0, F1=1.0; no diagnostic mismatches. |
| Evaluation timing | **1.7074 s** summed over 33 per-case `analyse_source` timers in the evaluator output; this is not end-to-end shell wall time. JSON evidence is at `/tmp/codetrace-current-evaluation.json`, outside the repository. |
| `python3 scripts/mutation_check.py` | **18/18 mutations caught**; script restored the deliberately modified implementation files. |

These metrics describe this small, hand-written repository corpus only; they are not estimates of real-world precision/recall and are not evidence that arbitrary programs are safe. The historical `submission/VERIFICATION_REPORT.md` and embedded report counts (304 Python, 30 frontend, verification dated 2026-10-13 at commit `0f2e994`) are not the current totals.

### Git / remote state observed

- Current branch: `arena/50a2b550-cd-project`.
- HEAD: `9e3a54b9601ba8ae630171fdbdfa629a56022671`, subject “Add files via upload”. Local `main` and `origin/main` pointed at the same commit when inspected.
- This checkout is shallow (`git rev-parse --is-shallow-repository` returned `true`) and the visible commit is marked grafted. Full earlier history was not verified.
- A read-only `gh pr list --head arena/50a2b550-cd-project --state all` query returned `[]`; no PR for this head was visible in that query. No fetch, commit, push, PR creation, merge or close was performed for this task.
- `git status --short --branch` was clean before creating this document. The final check showed only `?? PROJECT_CONTEXT.md`; application code, the DOCX/report, and Git history remain unchanged. Recheck status before any later commit or other operation.

## 13. Handoff status and suggested next steps

This handoff is complete; the requested application/report changes were explicitly out of scope and were not made. For a future authorized implementation/report task, a safe order is:

1. Re-run `git status --short --branch` and inspect the target tests before editing.
2. Reconcile code/docs around input limits, function-count handling, partial-result flags, graph truncation, API filename validation, diagnostic catalogue completeness and canonical parser statistics. Add focused regression tests before changing claims or behavior.
3. If report editing is authorized, use the actual root VIT template structure rather than assuming the generated DOCX matches it; confirm student/guide details and submission date; refresh the TOC; update the current verification evidence; follow the five exact screenshot-placement requirements in §11; do not fabricate the two missing close-up files.
4. Re-run `scripts/tests.sh`, `python3 scripts/audit.py`, evaluation and (when implementation files are clean) the mutation check after any code changes. Report current results separately from the 2026-10-13 historical submission evidence.

No safety claim should be inferred from an empty findings list, a passing finite test suite, or the corpus's perfect in-corpus metrics.
