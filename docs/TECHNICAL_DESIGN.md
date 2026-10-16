# Technical design

## 1. What the system does

CodeTrace takes a single source file in the CT-C subset (`docs/LANGUAGE.md`),
runs a compiler pipeline over it, and reports *potential* taint flows from
declared sources to declared sinks, together with the evidence for each claim:
the ordered data-flow path, the dependency graph around it, a slice, the
data-flow facts at every statement, and a report. The same pipeline exposes the
compiler artefacts themselves — token stream, LR tables, item sets, AST, CFG —
because the project is a compiler-design project first and a scanner second.

## 2. Runtime shape

```
                        ┌──────────────────────────────────────────┐
   browser (ES modules) │ frontend/  index.html, css/app.css, js/* │
                        └───────────────┬──────────────────────────┘
                                        │ fetch (JSON over HTTP, no build step)
                        ┌───────────────▼──────────────────────────┐
   HTTP server          │ codetrace/api/server.py                  │
                        │  routing, validation, limits, RunStore   │
                        └───────────────┬──────────────────────────┘
                                        │ analyse_source(source, rules, …)
   pipeline             ┌───────────────▼──────────────────────────┐
                        │ codetrace/analysis/pipeline.py: Program  │
                        └───┬────┬────┬────┬────┬────┬────┬────────┘
      lexer/parser ─────────┘    │    │    │    │    │    │
      semantics ─────────────────┘    │    │    │    │    │
      CFG ────────────────────────────┘    │    │    │    │
      data flow (RD/LV/DA) ────────────────┘    │    │    │
      taint (summaries + replay) ───────────────┘    │    │
      dependency graph ──────────────────────────────┘    │
      slicing ────────────────────────────────────────────┘
      findings + explanations ────────────────────────────────────┐
      reporting (JSON/HTML) ──────────────────────────────────────┘
```

There are exactly two processes at runtime: the Python server and the browser.
No build step, no bundler, no database, no network access beyond the server
itself. `python3 -m codetrace.api` is the whole deployment.

## 3. Modules and responsibilities

| Package | Files | Lines | Responsibility |
| --- | --- | --- | --- |
| `codetrace/frontend` | 9 | 3277 | tokens, lexer, grammar (NULLABLE/FIRST/FOLLOW, closure, GOTO, canonical/LALR/SLR automata), LR tables and parser, AST nodes, grammar documentation, pipeline (`parse_source`, cached `parser_tables`) |
| `codetrace/semantics` | 4 | 1352 | scopes and symbol table, external resolution through the rule set, type checks, per-statement accesses (reads/writes/definitions) |
| `codetrace/analysis` | 11 | 4062 | CFG, data-flow framework + reaching definitions / liveness / definite assignment, taint, dependency graph, slicing, `Program` orchestration |
| `codetrace/rules` | 3 | 1026 | rule model and validation, declarative rule language parser, built-in rule loader (plus `builtin/standard.ctrule`) |
| `codetrace/findings` | 3 | 1225 | finding model and stable identity, run comparison, explanation and certainty |
| `codetrace/reporting` | 3 | 650 | JSON report, self-contained HTML report |
| `codetrace/api` | 4 | 1152 | HTTP server, routing, request validation, limits, schemas catalogue, `python3 -m` entry point |
| `codetrace/*.py` | 2 | 22 | version constants and the package docstring |
| `tests/` | 18 | 6195 | lexer, parser, semantics, CFG, data flow, taint, slicing, rules, API, reporting, end-to-end workflow, audit and mutation-check self-tests |
| `frontend/` | 21 | 3486 | ES-module UI: 9 routes, graph layout, filters, API client, CSS, HTML shell |
| `frontend/tests/` | 5 | 2108 | stub DOM, harness, library tests, view tests against a real engine |
| `evaluation/` | 2 | 754 | labelled corpus harness and `expectations.json` |
| `scripts/` | 5 | 1485 | dev server, full test run, corpus evaluation, independent audit, mutation check |
| `docs/` | 15 | 5380 | the documentation set (see `README.md`) |
| `examples/` | 34 | 307 | 33 labelled `.ctc` sources and one example rule file |

Total implementation: 12 766 lines of Python in `codetrace/` (39 files), 6 195
lines of engine tests, 5 594 lines of frontend assets (of which 2 108 are the
interface tests), 1 485lines of scripts and 5 380 lines of documentation.
Counted with `wc -l`-style line counts, which include blank lines and comments.
The table is **checked**: `python3 scripts/audit.py` re-derives every row from
the tree and fails if a number here disagrees, so a stale row cannot survive a
green audit. When the audit reports drift, the same tool fixes it:

```bash
python3 scripts/audit.py -v                    # shows which rows drifted
python3 scripts/audit.py --write-module-table  # re-measures and rewrites them
```

Editing a file in `scripts/` or `docs/` therefore changes the numbers on the
next line of this paragraph; that is the check working, not a problem to ignore.

## 4. Module boundaries

**The frontend never computes analysis.** No taint, dependency or data-flow
result is derived in JavaScript: the UI renders payloads produced by the engine
and nothing else. `frontend/js/graph.js` only *lays out* the nodes it is given
(`computeLayers` is a placement helper, not a reachability analysis), and
`frontend/js/lib/filter.js` only filters the finding array it receives.

**The engine never serves HTML for analysis results.** `render_html` is a
reporting module; the interactive views fetch JSON.

**Rules are data everywhere.** The rule file is parsed by the rule-language
grammar and turned into `SourceRule` / `SinkRule` / `SanitizerRule` / `FlowRule`
dataclasses. The taint engine consumes those objects; nothing in the engine
evaluates rule text.

## 5. Data flow through the engine

`analyse_source(source, filename, rules=None, parser_mode="lalr", …)` returns a
`Program` object that owns every intermediate result, which is why the API can
serve any of them later without re-running the analysis:

```
Program
├── parse            : tokens, AST, accepted flag, per-phase timings
├── semantic         : symbols, scopes, diagnostics, per-statement accesses
├── cfgs             : function → CFG (blocks, typed edges, definitions)
├── analyses         : function → FunctionAnalyses
│                        .reaching/.reaching_result/.reaching_states
│                        .live/.live_result/.live_states
│                        .definite/.definite_result/.definite_states
├── taint            : atoms, hits, interprocedural summaries, converged flag,
│                        guard_suppressions (validator guards that cleared atoms),
│                        notes (per-run disclosures)
├── dependencies     : DependencyGraph (nodes, typed edges, stats)
├── slicing          : SliceEngine (backward/forward/for_finding)
├── findings         : ordered findings with evidence and explanations
├── diagnostics      : every diagnostic with code, phase, line, col, offsets
├── metrics          : counts and per-phase timings actually measured
├── limits_hit       : which caps were reached (partial analysis is disclosed)
└── rules            : the RuleSet that was actually used
```

Stages and their order: **lex → parse → semantics → CFG → data flow → taint →
dependency graph → slicing → findings → reporting**. Each stage records wall
clock time in `metrics.timings`, and each stage can be skipped by the caller
(`run_dependencies=False`, `run_slicing=False`) when only findings are wanted.

Every id that crosses a stage boundary is stable for a given source and rule
set: symbol ids in declaration order, statement ids in source order, definition
ids in access order, block ids in construction order. The API and the reports
address results by those ids, and findings hash their identity from the flow
itself (`docs/COMPILER_THEORY.md` §19).

### 5.1 Reporting what was *not* reported

Three of the stages above keep information that never becomes a finding, and the
interface and the reports would be misleading without it. Rather than let a
finding list stand for the whole result, the engine carries it explicitly:

| Situation | Where it lives | How it reaches the user |
| --- | --- | --- |
| a validator guard cleared a flow that would otherwise be reported | `taint.guard_suppressions` (per guard: symbol id, context, validator rule, position, guarded edge, removed atoms) | `summary.dispositions.validator_guards`, the run's `notes`, a run-level string in `limitations`, the Analyze Code page panel "What the engine saw but did not report", and the HTML report's section of the same name |
| a sink call was inspected and produced no finding | `reporting/json_report.py::dispositions` — reason per sink call, distinguished into *no taint reached it*, *statically pruned branch*, or *cleared by validator X* | `summary.dispositions.unreported_sink_calls` and the same panel/section |
| a stage was cut short by a limit or an unsupported construct | `limits_hit`, `partial_reasons`, `unsupported` | `summary.analysis_complete` / `partial_reasons`, the Analyze page warning, and the report's limitations |

The disposition reason is decided by symbol identity: a suppressed guard is
matched against the sink call's own reads (`analysis.accesses.statement_accesses`
over `guard_suppressions.symbol_id`), so a guard on an unrelated variable is
never blamed for an unreported sink, and a run that *did* report a finding
elsewhere does not claim that the guard hid anything.

## 6. Storage

There is no database. The server keeps an in-memory `RunStore` (LRU, 24 runs) of
`{run_id, program, rule_set, created_at}`; a run is lost when the process exits,
and the API says so (`404 run-not-found` with "run the analysis again"). Reports
and JSON payloads are generated on demand from the stored `Program` and are never
written to disk by the server. `var/` is used only by `scripts/evaluate.sh` and
is git-ignored.

## 7. Requests, limits and validation

| Guard | Value | Where |
| --- | --- | --- |
| request body | 1.1 MiB (`MAX_BODY_BYTES`) | `api/server.py` |
| source size | 1 MiB (`MAX_SOURCE_BYTES`) | `_analyze` |
| rule file size | 1 MiB | `_validate_rules` |
| statement index | 2000 (`MAX_STATEMENT_INDEX`) | endpoint parameter validation |
| graph payload | 4000 nodes/edges | `DependencyGraph.to_json` |
| slice size | 5000 statements / 500 edges | `SliceEngine` |
| data-flow iterations | 10 000 iterations / 200 000 steps | `dataflow.solve` |
| parse steps | `SYN010` | parser |
| syntax errors | `SYN011` | parser |
| recursion depth | `input-too-deep` (422) | `_analyze` |
| parser automaton | 2500 states | `build_canonical_lr1_automaton` |

Validation happens *before* work: unknown parameters are rejected with a
`400 invalid-parameter`, an unsupported parser mode with `400
invalid-parser-mode`, a broken rule file with `422 invalid-rules`, and an
oversized body with `413`. Every error uses the same envelope and never contains
a stack trace or a server path (`tests/test_api.py::ErrorEnvelopeTests`).

## 8. Security posture of the tool itself

* The analysed program is **never executed**: the pipeline is parsers and
  analyses only. `tests/test_api.py` and `scripts/audit.py` both upload a program
  that would create a canary file if executed and assert the file never appears.
* Uploaded rule files go through the rule-language parser and declarative
  validation; `tests/test_rules.py::UntrustedInputTests` asserts that no `eval`,
  `exec`, `compile` or `__import__` exists anywhere in the rule or analysis
  packages.
* Static file serving is restricted to `frontend/` with a `realpath` prefix
  check; traversal attempts (`/..%2f…`, `..%5c…`) answer `403 path-not-allowed`
  and leak nothing.
* Error messages quote the offending value but never the filesystem.
* Nothing in the project requires a credential, an API key or a paid service;
  the core application works offline.

## 9. Design decisions and trade-offs

| Decision | Why | Cost |
| --- | --- | --- |
| **Zero third-party dependencies** (Python standard library, vanilla ES modules) | the project must build and run anywhere, offline, without a package manager or an installer | no off-the-shelf LR generator, graph library or test runner — the parser generator and the frontend harness are part of the project, which is also what the assignment is about |
| **Own canonical LR(1)/LALR/SLR generator instead of a library** | the theory (items, closure, GOTO, conflicts) must be demonstrable and inspectable, and the same generator is reused for the rule language | slower table construction (≈ 0.3 s per mode) and a smaller grammar than a production C front end |
| **A documented C subset instead of full C** | honest, complete analyses on a subset beat silent mis-parsing of preprocessor macros, pointers and structs | unsupported constructs are reported as such and the report is marked partial |
| **Context-sensitive sanitisers with declared contexts** | a shell escape does not make SQL safe; conflating them produces false negatives | rules must declare contexts, and a wrong context produces a finding whose evidence explains why |
| **Unknown externals keep taint** | an unmodelled function is not evidence of validation | more findings on programs that use library helpers, each labelled `approximate` with the reason |
| **In-memory run store, no database** | the review workflow (analyse → fix → re-analyse → compare) fits in one process, and a database would be unused infrastructure | runs do not survive a restart; the API says so explicitly |
| **Rule sets extend the built-ins unless told otherwise** | a user's rule file should add policy, not silently disable existing policy | `use_builtin_rules: false` exists for the isolated case, and the run's `rules` block always states which set was used |
| **Per-phase timings in every report** | the assignment requires real metrics rather than claims | reports are not byte-identical across runs on the same input (timings and timestamp differ); the reporting tests freeze exactly those fields and assert that *findings* are identical |

## 10. Extension points

* **New rule sets** — write a `.ctrule` file; no Python. Add the file to the
  rule editor or POST it to `/api/rules/validate`.
* **New data-flow analyses** — subclass `DataFlowProblem` (direction, domain,
  boundary, transfer, meet) and reuse `solve`; the API's `analysis` parameter is
  the only place that needs a new branch.
* **New languages** — the parser is table-driven: `build_language_grammar()`
  returns a `Grammar`, and any grammar with the same node builders and the same
  `tokens.py` kinds would parse. The semantics, CFG and analyses are written
  against the AST dataclasses, not against the concrete syntax.
* **New reports** — `reporting/json_report.py` builds the canonical dictionary;
  HTML and any future format render from it, so the two cannot disagree.

## 11. Development commands

```bash
python3 -m codetrace.api                       # serve the app on :8000
scripts/serve.sh --port 9000                   # same, any flags passed through
python3 -m unittest discover -s tests -t .     # engine + API + reporting + workflow
scripts/tests.sh                               # the above plus the frontend suite
python3 evaluation/run_evaluation.py           # labelled corpus, table on stdout
scripts/evaluate.sh                            # same, JSON written to var/
python3 scripts/audit.py -v                    # independent end-to-end audit
python3 scripts/mutation_check.py              # break the engine on purpose, 18 mutations
python3 scripts/mutation_check.py --list       # the catalogue, without rewriting anything
```

No command needs network access, a key or a service account.

`mutation_check.py` is the check on the checks: for each of the 18 catalogue
entries it asserts the anchor still matches exactly once, applies the defect,
runs the test modules that are supposed to notice it, restores the file
byte-for-byte, and fails if any defect escapes the suite. It refuses to start
when a target file has uncommitted changes, so an interrupted run cannot lose
work, and it records mutations it deliberately does *not* include when they turn
out to be behaviourally equivalent (`SLICE_KINDS` already names every edge kind
the graph defines, so widening it to "all kinds" changes nothing).
