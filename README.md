# CodeTrace

**A compiler-driven program and security analysis platform for a C subset.**

CodeTrace reads a program written in CT-C, a documented subset of C, and reports the
security-relevant data flows in it. The analysis is built on the classical phases of a
compiler rather than on pattern matching: a hand-written scanner produces tokens with
source positions, an LR parser generator written for the project builds SLR(1), LALR(1)
or canonical LR(1) tables for the grammar, and a scoped semantic analyser resolves
declarations and gives every definition a stable identity. Control-flow graphs, a
worklist data-flow framework, taint propagation over a declarative rule set, a typed
program dependency graph and program slices are built on that output, and each finding
carries the path that produced it.

The engine is Python 3.11 using **only the standard library**. The interface is plain
HTML, CSS and ECMAScript modules with no build step and no dependencies. There is
nothing to install, no service to reach and no network access at run time.

The analysed program is **never executed**. CodeTrace is a static analysis tool: it
reads the file as data and reports *potential* flows. An empty finding list means
"no configured source-to-sink flow was found for this file, this rule set and this
engine version", never "this program is safe".

## Quick start

```bash
python3 -m codetrace.api              # http://0.0.0.0:8000
scripts/serve.sh --port 9000          # the same server, any port
```

Open `http://localhost:8000`, go to **Analyze Code**, press *Load example…*, choose
`vulnerable/command_injection.ctc`, and press *Run analysis*. The run is then available
in every view: Overview, Findings, Program Graph, Data-Flow Analysis, Program Slicing,
Rule Editor, Reports and Documentation. `docs/USER_GUIDE.md` is the guided tour.

The labelled corpus is evaluated with:

```bash
scripts/evaluate.sh                   # table on stdout, JSON evidence in var/
```

## What it does

| Stage | What is produced |
| --- | --- |
| Lexer | tokens with type, value, offset and line:column; comments skipped; literals (including `\xHH`); every lexical error carrying a code |
| Parser | SLR(1), LALR(1) or canonical LR(1) tables built from the grammar, one state per table row; syntax tree with source spans; located diagnostics and recovery |
| AST | one node class per construct, every node carrying its source range |
| Semantics | scoped symbol tables with stable symbol identities, shadowing, duplicate/undeclared/arity/type diagnostics, explicit "unsupported construct" reporting |
| CFG | per-function basic blocks with stable ids, typed edges (true/false/loop-back/return), loop headers with back edges, computed reachability |
| Data-flow | a worklist framework (direction, domain, boundary, transfer, meet, iteration caps) with reaching definitions, liveness and definite assignment |
| Taint | sources, sinks, sanitisers and validators declared by rules with contexts; context-sensitive sanitisers; interprocedural summaries with documented approximations |
| Dependencies | typed edges (data, control, call, return, taint, sanitise, define, source-to-sink), each carrying the reason it exists |
| Slicing | backward, forward and finding-focused slices, with the reason each statement belongs |
| Findings | stable identity, severity, category, certainty, ordered evidence path, remediation |
| Reports | schema-versioned JSON and a self-contained HTML document; two runs can be compared finding by finding |
| API | JSON over HTTP for analysis, rules, grammar, documentation, slices and reports |

## Repository layout

```
codetrace/            the engine
  frontend/           scanner, grammar, LR automata and tables, parser, syntax tree
  semantics/          scopes, symbol identities, type and declaration checks
  rules/              rule grammar, parser, validator, built-in rule file
  analysis/           control-flow graphs, data-flow framework, taint, dependencies, slices
  findings/           finding model and evidence paths
  reporting/          JSON and HTML report builders
  api/                HTTP server and request/response schemas
frontend/             the workbench: nine views, SVG graph renderer, styles, HTML shell
examples/             the CT-C programs used by the example picker and the corpus
evaluation/           labels for the corpus and the harness that runs it
docs/                 design and reference documentation, screenshots, the project report
scripts/              server launch and corpus evaluation
```

## Usage

```bash
python3 -m codetrace.api --port 9000 --host 0.0.0.0
python3 evaluation/run_evaluation.py --json var/evaluation.json
```

The API accepts a program, a parser mode (`slr`, `lalr` or `canonical`) and an optional
rule file, and returns the run: diagnostics, statements, control-flow graphs, data-flow
facts, dependency graph, slices and findings. It is documented in `docs/API.md`, and
the exported report format in `docs/REPORT_SCHEMA.md`.

Security knowledge is data, not code. A rule file declares sources, sinks, sanitisers
and validators with the external functions they correspond to, the argument positions,
the contexts in which they apply and, for sinks, a category and a severity. Rule files
are parsed by the same LR machinery as the analysed language and validated before use;
nothing in a rule file can execute, import or write. The built-in set declares five
sources, eight sinks, five sanitisers, two validators and four flows, and is identified
by a fingerprint that appears in every run.

## Results

The engine is evaluated against a corpus of thirty-three CT-C programs with
hand-written labels — twenty expected findings across seventeen vulnerable programs,
one program that exercises a submitted rule file, five safe programs, four sanitised
ones, and six programs that must be rejected with a specific diagnostic because they
use a construct outside the language. All twenty expected findings are reported with
the expected rule, category and severity; there is no false positive and no false
negative on this corpus. `docs/EVALUATION.md` explains what these numbers do and do not
mean.

## Documentation

| Document | Contents |
| --- | --- |
| `docs/USER_GUIDE.md` | installing nothing, running the app, using each view, reading a finding |
| `docs/LANGUAGE.md` | the CT-C subset: types, statements, expressions, unsupported constructs |
| `docs/RULE_LANGUAGE.md` | the declarative rule language, its grammar and its diagnostics |
| `docs/TECHNICAL_DESIGN.md` | architecture, module responsibilities, the path of one analysis |
| `docs/COMPILER_THEORY.md` | every compiler concept used, with the equations and worked examples |
| `docs/ALGORITHMS.md` | pseudocode and complexity of each algorithm |
| `docs/API.md` | endpoints, request and response schemas, limits |
| `docs/REPORT_SCHEMA.md` | the exported report: keys, finding fields, path steps, stability |
| `docs/EVALUATION.md` | how the labelled corpus was built and what the measured numbers mean |
| `docs/LIMITATIONS.md` | what the tool does not do, and the threat model of the tool itself |

## The project report

`docs/Review3_CodeTrace_Report.docx` is the BCSE307P project report (Review 3), with
`docs/Review3_CodeTrace_Report_preview.pdf` as a rendered copy. It describes the
architecture, the compiler phases, the module-wise mapping to the course, a worked
example and the features added in this review, with screenshots taken from the running
system in `docs/screenshots/`.

## Scope and limitations

CT-C is a documented subset: no pointers, unions, preprocessor expansion, dynamic
memory, `switch`, `goto` or user-defined types. A construct outside the subset is
rejected with a diagnostic instead of being approximated, so an absence of findings is
a statement about analysed code rather than about skipped code. Flow is followed within
a function directly and across functions only through explicit arguments and return
values, up to a configured depth; there is no alias analysis. The complete list is in
`docs/LIMITATIONS.md`.
