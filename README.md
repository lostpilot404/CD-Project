# CodeTrace

**A compiler-driven program dependency and vulnerability analysis platform.**

CodeTrace lexes and parses a small C subset with its own canonical LR(1) parser
generator, builds an abstract syntax tree and symbol tables, constructs a
control-flow graph, runs reusable data-flow analyses (reaching definitions,
liveness, definite assignment), propagates taint from configurable sources to
configurable sinks, builds a typed program dependency graph, computes program
slices, and reports each finding with the evidence that justifies it — through a
browser interface and an HTTP API.

It is written in Python 3.11 using **only the standard library**, plus a frontend
of plain ES modules with no build step and no npm dependencies. There is nothing
to install, no API key, no cloud service and no network access at run time.

The analysed program is **never executed**. CodeTrace is a static analysis tool:
it reads the file you give it as data and reports *potential* flows. A short
finding list means "no configured source-to-sink flow was detected for this file,
this rule set and this engine version" — never "this program is safe".

## Quick start

```bash
python3 -m codetrace.api                # http://0.0.0.0:8000
scripts/serve.sh --port 9000            # the same server, any port
```

Then open `http://localhost:8000`, go to **Analyze Code**, press
*Load example…*, pick `vulnerable/command_injection.ctc` and press *Run
analysis*. Start with `docs/USER_GUIDE.md` if you want the guided tour.

No third-party package is needed anywhere in the pipeline: there is no
`requirements.txt` because there are no requirements beyond Python 3.11.

```bash
scripts/tests.sh                 # every suite: engine, API, reporting, workflow, interface
scripts/tests.sh engine          # Python suites only (no Node needed)
scripts/evaluate.sh              # the labelled corpus, JSON evidence in var/
python3 scripts/audit.py         # independent Definition-of-Done audit (69 checks)
python3 scripts/audit.py -v      # ... printing the value behind every check
python3 scripts/audit.py --write-module-table   # refresh the measured module table
python3 scripts/mutation_check.py  # break the engine on purpose: does the suite notice?
python3 scripts/mutation_check.py --list   # the mutation catalogue, no changes made
```

## What it does

| Stage | What is produced |
| --- | --- |
| Lexer | tokens with type, value, offset and line:column; comments skipped; literals (including `\xHH`) and every lexical error reported with a code |
| Parser | canonical LR(1) / LALR(1) / SLR(1) tables built from the grammar, one state is one table row; parse tree with source spans; located syntax diagnostics and recovery |
| AST | one node class per construct, every node carrying its source range |
| Semantics | scoped symbol tables with stable symbol ids, shadowing, duplicate/undeclared/arity/type diagnostics, explicit "unsupported construct" reporting |
| CFG | per-function basic blocks with stable ids, typed edges (true/false/loop-back/return/…), loop headers with back edges, reachability computed, not guessed |
| Data-flow | a reusable worklist framework (direction, domain, boundary, transfer, meet, iteration caps) with reaching definitions, liveness and definite assignment, all bit-vector based |
| Taint | sources, sinks, sanitizers and validators declared by rules with contexts; atoms like `src:stdin@command`; context-sensitive sanitizers; interprocedural summaries with documented approximations |
| Dependencies | typed edges (data, control, call, return, taint, sanitize, define, source-to-sink) — every edge carries the reason it exists |
| Slicing | backward, forward and finding-focused slices with the reason each statement is in the slice |
| Findings | stable id, rule id, category, severity, certainty, source/sink locations, the path, branch conditions, sanitizers seen, why it matched, limitations, remediation |
| Reports | stable JSON report (documented in `docs/REPORT_SCHEMA.md`) and a self-contained HTML report that escapes all analysed text |
| Rules | a declarative rule language parsed by the same LR machinery, validated with `line:col` diagnostics before it is ever used |

## Repository layout

```
codetrace/             engine (Python, standard library only)
  frontend/            lexer, grammar, canonical LR(1) generator, AST, parser tables
  semantics/           scopes, symbols, types, semantic diagnostics
  analysis/            CFG, data-flow framework, reaching definitions, liveness,
                       definite assignment, taint, dependency graph, slicing, pipeline
  rules/               rule model, rule language, built-in rule file
  findings/            finding model, comparison of runs, explanation builder
  reporting/           JSON and HTML reports
  api/                 HTTP server, request schemas, error envelope
frontend/              interface: index.html, css, ES modules (no build step, no deps)
frontend/tests/        interface tests against a real engine (Node test runner)
tests/                 engine suite: lexer, parser, semantics, CFG, data-flow,
                       taint, slicing, rules, API, reporting, end-to-end workflow
examples/              33 labelled `.ctc` files and one example rule file
evaluation/            harness + `expectations.json` labels for the corpus
scripts/               serve.sh, tests.sh, evaluate.sh, audit.py, mutation_check.py
docs/                  the documentation set (below)
```

## Documentation

| Document | Contents |
| --- | --- |
| `docs/USER_GUIDE.md` | running the app, the nine pages, reading a finding, the fix-and-recheck loop, troubleshooting |
| `docs/LANGUAGE.md` | the CT-C subset: tokens, grammar, types, statements, every diagnostic code |
| `docs/RULE_LANGUAGE.md` | the declarative rule language: grammar, attributes, validation rules, examples |
| `docs/COMPILER_THEORY.md` | every compiler concept used, with definitions, equations, worked examples and pointers to the code and tests |
| `docs/ALGORITHMS.md` | pseudocode and complexity for each algorithm, plus measured timings |
| `docs/TECHNICAL_DESIGN.md` | architecture, module responsibilities, data flow through the engine, design decisions |
| `docs/API.md` | every endpoint, request/response schema, error envelope, limits, `curl` examples |
| `docs/REPORT_SCHEMA.md` | the exported report: keys, finding fields, path steps, stability rules |
| `docs/LIMITATIONS.md` | what the analysis does not do, per finding, and the threat model of the tool itself |
| `docs/EVALUATION.md` | how the labelled corpus was built and what the measured numbers mean |
| `docs/PRESENTATION.md` | talk outline, demo script and viva questions |
| `docs/FINAL_REPORT.md` | the completion report: what was built, the evidence for each claim, and what is not done |

The Documentation page inside the application serves the same facts from the
engine itself (language mode, grammar statistics, diagnostic catalogue, rule
language), so the interface cannot claim more than the engine implements.

## Verification

| Suite | Command | Result on this checkout |
| --- | --- | --- |
| Engine, API, reporting, workflow | `python3 -m unittest discover -s tests -t .` | 310 tests, all passing |
| Interface | `cd frontend && npm test` | 39 tests, all passing (real engine over HTTP, stub DOM) |
| Labelled corpus | `scripts/evaluate.sh` | 33 files, 20 expected findings, TP 20 / FP 0 / FN 0, file-level TN 9/9, precision = recall = F1 = 1.0, ≈1.2 s total |
| Independent audit | `python3 scripts/audit.py` | 69 checks covering grammar, hand-computed data flow, graph edges, slices, rules, the HTTP workflow, malformed input, the interface contract, document accuracy, the claims the documents make about the code, and drift between the module table and the tree |
| Mutation check | `python3 scripts/mutation_check.py` | 18 deliberate defects (parser, semantics, CFG, data flow, taint, slicing, rules, reporting); the suite has to catch every one, and does (18/18) |

The evaluation numbers describe this corpus only. See `docs/EVALUATION.md` for
what they do and do not mean, and `docs/LIMITATIONS.md` for the analysis limits
and the security model of the tool.

## Honesty rules this project follows

- Findings are stated as *potential* flows with a certainty level; exploitability
  is never claimed.
- Constructs outside the subset produce explicit diagnostics; the run is marked
  partial rather than being presented as analysed.
- Grammar conflicts, rule-language conflicts, limits reached and analysis
  approximations are reported in the interface, the API and the report.
- Nothing in the product mocks an analysis result: every number in the interface
  and every figure in these documents is produced by the engine on this checkout.
