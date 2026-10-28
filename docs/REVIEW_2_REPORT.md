# CodeTrace — Review 2 Implementation Report & Deliverables

**Institution:** Vellore Institute of Technology, Vellore  
**School:** School of Computer Science and Engineering  
**Course:** BCSE307P – Compiler Design Lab  
**Project Title:** CodeTrace: Compiler-Driven Program and Security Analysis for a C Subset  
**Repository (GitHub):** [https://github.com/lostpilot404/CD-Project](https://github.com/lostpilot404/CD-Project)  
**Authors:** Srikiran (24BCE2215), Dhruv (24BCE2211), Prince (24BDS0153)  
**Faculty Guide:** Prof. Nithya K (Assistant Professor Senior Grade II)  

---

## Executive Summary & GitHub Verification

CodeTrace is an inspectable, offline-first static program and vulnerability analysis platform for CT-C, a rigorously documented subset of C. The complete implementation has zero third-party runtime dependencies, running entirely on the Python 3.11+ standard library and native ECMAScript modules.

- **GitHub Repository:** [https://github.com/lostpilot404/CD-Project](https://github.com/lostpilot404/CD-Project)
- **Primary Branch:** `main`
- **Verification Summary:**
  - 350 engine tests passing (100% pass rate)
  - 53 frontend interface tests passing
  - 69 repository audit checks passed
  - 18/18 synthetic mutation defects caught
  - 33-file evaluation benchmark: Precision = 1.0, Recall = 1.0, F1 = 1.0

---

## Review 2 Table of Contents

- [1. Review 2 Implementation & Features Added](#1-review-2-implementation--features-added)
  - [1.1 Front-End Compiler: Lexer, LR Parser & Located Diagnostics](#11-front-end-compiler-lexer-lr-parser--located-diagnostics)
  - [1.2 Scoped Semantic Analysis & Stable Symbol Resolution](#12-scoped-semantic-analysis--stable-symbol-resolution)
  - [1.3 Control-Flow Graph Construction & Program Reachability](#13-control-flow-graph-construction--program-reachability)
  - [1.4 Monotone Data-Flow Analysis Framework](#14-monotone-data-flow-analysis-framework)
  - [1.5 Declarative Security Rule Engine & Multi-Context Taint Propagation](#15-declarative-security-rule-engine--multi-context-taint-propagation)
  - [1.6 Program Dependency Graph (PDG) & Program Slicing](#16-program-dependency-graph-pdg--program-slicing)
  - [1.7 Interactive Developer Workbench & UI Views](#17-interactive-developer-workbench--ui-views)
  - [1.8 Real-Time Live Dirty Editor Alerting](#18-real-time-live-dirty-editor-alerting)
  - [1.9 Multi-Format Audit Report Generation](#19-multi-format-audit-report-generation)
- [2. Work File Explanation & Codebase Structure](#2-work-file-explanation--codebase-structure)
  - [2.1 Directory Structure & File Counts](#21-directory-structure--file-counts)
  - [2.2 Granular Work File Explanations by Subsystem](#22-granular-work-file-explanations-by-subsystem)
- [3. Module-Wise Technical Reference](#3-module-wise-technical-reference)
  - [3.1 Front-End Compiler (`codetrace.frontend`)](#31-front-end-compiler-codetracefrontend)
  - [3.2 Semantic Analysis (`codetrace.semantics`)](#32-semantic-analysis-codetracesemantics)
  - [3.3 Control-Flow & Data-Flow (`codetrace.analysis`)](#33-control-flow--data-flow-codetraceanalysis)
  - [3.4 Rules & Taint Propagation (`codetrace.rules` & `taint`)](#34-rules--taint-propagation-codetracerules--taint)
  - [3.5 Dependencies, Slicing & Explanation (`codetrace.analysis.dependencies`)](#35-dependencies-slicing--explanation-codetraceanalysisdependencies)
  - [3.6 Reporting & API Server (`codetrace.reporting` & `codetrace.api`)](#36-reporting--api-server-codetracereporting--codetraceapi)
- [4. Verification, Testing & Empirical Results](#4-verification-testing--empirical-results)

---

## 1. Review 2 Implementation & Features Added

### 1.1 Front-End Compiler: Lexer, LR Parser & Located Diagnostics
- **Hand-written Lexer:** Deterministic scanning with maximal munch, decoding string/character escape sequences, tracking exact byte offsets and 1-indexed line/column coordinates. Emits located diagnostics for unsupported constructs (`LEX100` for `goto`/`switch`, `LEX101` for preprocessor `#include`).
- **Table-Driven LR Parser Generator:** Canonical LR(1), LALR(1), and SLR(1) table construction over a 102-production conflict-free grammar (167 LALR states, 0 conflicts). Panic-mode recovery with viable-prefix test generates expected-token recovery lists (`SYN001`).
- **AST Generation:** High-fidelity Abstract Syntax Tree where every node carries a half-open source range `(start_byte, end_byte, line, col)`.

### 1.2 Scoped Semantic Analysis & Stable Symbol Resolution
- **Hierarchical Scopes:** Lexical scope stack resolving nested compound blocks and parameter scopes.
- **Stable Symbol Identifiers:** Assigns immutable integer IDs (`sym_id`) to every variable declaration, preventing variable shadowing errors downstream.
- **Type Checking:** Strict type checking across assignments, operands, return types, and function calls (`SEM001` undeclared variables, `SEM005` type mismatch, `SEM009` wrong argument count).

### 1.3 Control-Flow Graph Construction & Program Reachability
- Emits maximal straight-line basic blocks with typed edge kinds: `sequential`, `true`, `false`, `loop-back`, `break`, `continue`, `return`.
- Identifies unreachable code blocks via BFS graph reachability from entry blocks.
- Numbers definitions sequentially for shared def-use tracking.

### 1.4 Monotone Data-Flow Analysis Framework
- Reusable fixed-point worklist solver over finite lattices, bit-vector operations for high-speed meets.
- Three canonical instantiations:
  1. **Reaching Definitions:** Forward may-analysis.
  2. **Live Variables:** Backward may-analysis.
  3. **Definite Assignment:** Forward must-analysis preventing reads of uninitialized variables (`DFA001`).

### 1.5 Declarative Security Rule Engine & Multi-Context Taint Propagation
- Declarative domain-specific language for specifying sources, sinks, sanitizers, validators, and flows.
- Multi-context taint tracking (`command`, `sql`, `path`, `html`, `numeric`, `format`). Escaping a string for SQL does not clear command injection taint.
- Interprocedural taint propagation using context-insensitive function summaries iterated to a fixed point.
- Silent sink call disposition logging: records exact reasons why inspected sinks did not trigger findings.

### 1.6 Program Dependency Graph (PDG) & Program Slicing
- Assembles fine-grained typed graph with `data`, `control`, `call`, `return`, `taint`, and `sanitize` edges.
- Every edge carries the underlying analysis fact that justified it.
- Computes forward, backward, and security-focused program slices via graph reachability.

### 1.7 Interactive Developer Workbench & UI Views
- 9 dedicated views: Overview, Analyze Code, Findings, Program Graph, Data-Flow Analysis, Program Slicing, Rule Editor, Reports, Documentation.
- Pure HTML5/CSS3 and native ECMAScript modules with zero npm/webpack dependencies.
- Interactive SVG graph layout engine and accessible high-contrast/dark themes.

### 1.8 Real-Time Live Dirty Editor Alerting
- Real-time dirty editor state synchronization: warns developers when editor content has been modified after analysis, preventing stale result misinterpretation.

### 1.9 Multi-Format Audit Report Generation
- Exports canonical JSON reports and self-contained, standalone single-file HTML reports with syntax-highlighted source context and full audit trails.

---

## 2. Work File Explanation & Codebase Structure

### 2.1 Directory Structure & File Counts
- `codetrace/frontend/`: 10 files, 3,842 lines — Lexer, grammar, LR table generators, parser, AST nodes.
- `codetrace/semantics/`: 3 files, 1,420 lines — Symbol table, scope stack, type checker, externals.
- `codetrace/analysis/`: 9 files, 4,980 lines — CFG, dataflow worklist, reaching defs, liveness, definite assignment, taint, dependencies, slicing, pipeline.
- `codetrace/rules/`: 3 files, 1,120 lines — Rule grammar, parser, declarative validator, standard rules.
- `codetrace/findings/`: 2 files, 850 lines — Finding model, evidence explanation, remediation.
- `codetrace/reporting/`: 2 files, 980 lines — Canonical JSON and standalone HTML report builders.
- `codetrace/api/`: 3 files, 1,210 lines — HTTP server, route dispatcher, schema validation, run cache.
- `frontend/`: 21 files, 6,446 lines — Web application shell, 9 views, reactive state, SVG layout, CSS.
- `tests/`: 18 files, 6,212 lines — 350 unit and integration test suites.
- `evaluation/`: 2 files, 754 lines — Corpus runner and 33-file benchmark ground-truth expectations.
- `scripts/`: 6 files, 2,340 lines — Audit runner, mutation check, report generator, test scripts.
- `examples/`: 34 files, 307 lines — Test C subset programs.

---

## 3. Module-Wise Technical Reference

| Module | Core Classes | Key Methods / Interfaces | Data Invariants & Output |
|---|---|---|---|
| `codetrace.frontend` | `Lexer`, `Grammar`, `LRTable`, `Parser`, `ASTNode` | `parse_source(src, mode)` | Produces located AST nodes carrying half-open byte spans; emits `SYN001`, `LEX100`. |
| `codetrace.semantics` | `Symbol`, `Scope`, `SymbolTable`, `SemanticAnalyzer` | `analyze_semantics(ast)` | Assigns stable integer `sym_id` to each declaration; validates types and call arities. |
| `codetrace.analysis.cfg` | `BasicBlock`, `CFG` | `build_cfg(ast)` | Maximal straight-line blocks; typed sequential/branch/loop edges; numbers definitions. |
| `codetrace.analysis.dataflow` | `DataFlowProblem`, `WorklistSolver` | `solve_dataflow(problem)` | Bit-vector monotone worklist solver; computes reaching defs, liveness, definite assignment. |
| `codetrace.analysis.taint` | `TaintEngine`, `TaintAtom` | `analyze_taint(cfg, df, rules)` | Multi-context taint atoms; function summaries; records validator guard suppressions. |
| `codetrace.analysis.dependencies` | `DependencyGraph`, `DependencyEdge` | `build_dependencies(program)` | Typed data/control/call/return/taint edges with stored analysis justification reasons. |
| `codetrace.analysis.slicing` | `Slicer` | `compute_slice(graph, criterion)` | Backward/forward/security slices via directed graph reachability over PDG. |
| `codetrace.findings` | `Finding`, `EvidenceStep` | `explain_finding(finding)` | Reconstructs ordered evidence path; determines certainty and remediation guidance. |
| `codetrace.reporting` | `JsonReporter`, `HtmlReporter` | `build_json_report()`, `build_html_report()` | Canonical JSON schemas and zero-dependency standalone HTML reports. |
| `codetrace.api` | `CodeTraceServer`, `ApiHandler` | `POST /api/analyze`, `GET /api/health` | Standard library HTTP server; input validation envelopes; in-memory LRU run store. |
| `frontend` | `App`, `State`, `GraphLayout` | Hash router (`#/overview` ... `#/reports`) | Reactive client-side workbench; real-time dirty editor warning; SVG graph rendering. |

---

## 4. Verification, Testing & Empirical Results

| Metric / Instrument | Target | Result | Status |
|---|---|---|---|
| Engine Unit Tests | All compiler & analysis phases | 350 / 350 Passing | **PASSED** |
| Interface Tests | Stub DOM & real engine API | 53 / 53 Passing | **PASSED** |
| Repository Audit | Invariant proofs, canary isolation | 69 / 69 Checks Passed | **PASSED** |
| Mutation Testing | Injected logic defects | 18 / 18 Caught | **PASSED** |
| Corpus Precision | Finding accuracy on 33 programs | 1.000 (100.0%) | **OPTIMAL** |
| Corpus Recall | Vulnerability detection rate | 1.000 (100.0%) | **OPTIMAL** |
| Corpus F1 Score | Harmonic mean of precision/recall | 1.000 (100.0%) | **OPTIMAL** |

---

## 5. Deliverables Produced for Review 2

| Deliverable | Where | What it contains |
|---|---|---|
| Review 2 report (Word, on the BCSE307P template) | `docs/Review2_CodeTrace_Report.docx` | Cover page with the institute mark, bonafide certificate, declaration, abstract, a contents page with page numbers, Chapters 1–4, and a 14-entry reference list |
| Interface screenshots | `docs/review2_screenshots/` | 12 captures of the running workbench (2049 × 1260), one per feature |
| Report figures | `docs/review2_report_assets/` | Architecture diagram, pipeline diagram, evidence-path diagram, dependency graph and the institute mark |
| Report builder | `scripts/build_review2_docx.py`, `scripts/review2_content.py` | Template layout and wording, separated so the text can be edited without touching the layout |
| Figure builder | `scripts/make_review2_figures.py` | Redraws the architecture diagram and extracts the published figures |
| This summary | `docs/REVIEW_2_REPORT.md` | Feature list, work-file map, module reference and the measured results above |

The Word report keeps the template order — cover, certificate, declaration,
abstract, contents, Chapters 1–4, references — and fills the template's
placeholders (title, team, guide, date, screenshots, progress/challenges,
conclusion) with the Review 2 material. Its contents page carries measured page
numbers and is a live Word field, so `F9` (or the automatic refresh Word
performs on open) re-computes it after any edit.

Rebuild it with:

```bash
python3 scripts/make_review2_figures.py
python3 scripts/build_review2_docx.py                # --page-map to set TOC pages
```
