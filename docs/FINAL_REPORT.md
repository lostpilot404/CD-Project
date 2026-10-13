# CodeTrace — final report

Ten parts, each with the evidence that produced it. Every number below was
measured on this checkout; the command that re-measures it is quoted with it.
Nothing in this document is a forward-looking claim about work that has not been
done — §10 lists what is *not* done.

Environment for all measurements: Python 3.11.2, Node v22.22.3, Linux x86_64,
2 processors, no third-party package installed, no network access required.

---

## 1. What was built

CodeTrace is a compiler-driven dependency and vulnerability analysis platform for
a documented subset of C. One pipeline runs from source text to report, and every
stage after the parser works on the same in-memory `Program` object, so the
interface, the API and the reports all read the same results:

```
source → lexer → canonical LR(1) parser → AST → semantics/symbol table
       → CFG → data-flow (reaching definitions, liveness, definite assignment)
       → taint (interprocedural, rule-driven) → dependency graph → slicing
       → findings → JSON/HTML report → interface
```

* **Language**: the CT-C subset, specified in `docs/LANGUAGE.md` (declarations,
  functions, `string`/`int`/`float`/`char`/`bool`, arrays, `if`/`else`,
  `while`, `for`, `do`-`while`, `break`, `continue`, `return`, the C expression
  grammar with precedence and associativity, comments). Constructs outside it —
  `switch`, pointers, structs, the preprocessor, `goto` — are rejected with a
  located diagnostic and a partial-analysis flag, never silently ignored.
* **Implementations**: 12 612 lines of Python across `codetrace/` (39 files), no
  third-party dependency (`python3 -m codetrace.api` needs nothing but Python).
* **Interface**: 9 routes, plain ES modules, no build step.

## 2. Compiler theory, demonstrated

| Concept | Where it is visible | Evidence |
| --- | --- | --- |
| Grammar, NULLABLE/FIRST/FOLLOW | `/api/grammar`, Documentation page | 102 productions, 51 terminals, 36 non-terminals, 7 nullable |
| LR(1) items, closure, GOTO, canonical collection with dedup | `/api/grammar?mode=canonical` | 656 canonical LR(1) states, 4281 transitions, 110 638 items, 1 277 items in the largest state |
| LALR(1) and SLR(1) construction | `?mode=lalr`, `?mode=slr` | 167 states each, 1 027 transitions; LALR merges the 656 LR(1) states |
| Conflicts | `conflicts: 0` in all three modes, on the Overview page | 0 conflicts; the rules are conflict-free by construction, and the checker refuses to hide any |
| Shift/reduce/accept/error, precedence, associativity | `tests/test_parser.py` (27 tests) | precedence and associativity cases, dangling-else, nesting |
| Error recovery with `line:col` | `examples/syntax_errors/*`, `/api/analyze` | `SYN001` with position; run marked partial with a reason |

The same machinery is reused for the rule language: its grammar is 40
productions, its LALR table 78 states, 0 conflicts (`/api/rules` →
`rule_language`).

## 3. Static analysis

* **CFG**: stable block ids, entry/exit, typed edges (`sequential`, `true`,
  `false`, `loop-back`, `break`, `continue`, `return`, `exit`), loop records
  (header, body entry, break/continue targets), and reachability computed by
  traversal rather than guessed from text (`tests/test_cfg.py`, 15 tests);
  an unreachable block is reported as `CFG001` and is excluded from the
  data-flow solutions.
* **Data-flow framework**: direction, domain, boundary, transfer, meet,
  worklist, fixpoint, iteration limits — one implementation
  (`codetrace/analysis/dataflow.py`) with three problems on top:
  reaching definitions (`OUT = GEN ∪ (IN − KILL)`, `IN = ∪ OUT[P]`), liveness
  (`OUT = ∪ IN[S]`, `IN = USE ∪ (OUT − DEF)`), definite assignment
  (`OUT = GEN ∪ (IN − KILL)`, `IN = ∩ OUT[P]`).
* **Reaching definitions and liveness** are re-derived by
  `scripts/audit.py` against hand calculations on a loop, and by
  `tests/test_dataflow.py` (26 tests). Ground truth for the audit's loop:
  `OUT(B0)={d0,d1}`, `OUT(B3)={d1,d2}`, `IN(B2)={d0,d1,d2}`;
  liveness `IN(B2)={a}`, `OUT(B3)={a}`, `USE(B3)={b}`, `DEF(B3)={a}`.
* **Definite assignment** is a *must* analysis, including its initialisation
  contract: the iteration starts at the lattice top except at the entry. The
  measured consequence of getting that wrong is documented in
  `docs/COMPILER_THEORY.md` §15 (two `DFA001` false positives on a one-line loop)
  and pinned by `MustAnalysisInitialisationTests`.
* **Taint**: rule-declared sources/sinks/sanitizers with stable ids and contexts;
  propagation through assignments, expressions, branches, arguments, returns and
  call summaries; context-sensitive sanitizers; **unknown calls never clear
  taint**; a declared validator guarding a branch clears the flow across that
  branch *and records the assumption* (§5).
* **Dependency graph and slicing**: typed edges, each with a machine-readable
  reason; backward/forward/security slices built from those edges;
  `scripts/audit.py` re-checks every intra-procedural data/taint edge against the
  reaching definitions and fails if one cannot be justified.

## 4. Product surface

* **API**: 21 endpoints (`/api/schemas` lists them with their schemas), a single
  error envelope, size/time/graph limits enforced server-side, no filesystem or
  command execution reachable from a request.
* **Interface**: Overview, Analyze Code, Findings, Program Graph, Data-Flow
  Analysis, Program Slicing, Rule Editor, Reports, Documentation — all nine
  render real content and are covered by `frontend/tests/views.test.js` against a
  real engine over HTTP (30 tests).
* **Findings** carry a stable id (independent of line numbers), rule id,
  category, severity, confidence, certainty, source/sink positions, the evidence
  path, branch conditions, sanitizers seen and *why they did not neutralise the
  flow*, feasibility, limitations, remediation and source navigation.
* **Rule language**: sources, sinks, sanitizers, validators, flows; validated
  before execution with `line:col`; untrusted by design (no embedded Python, no
  `eval`); the example file and a deliberately broken one are both exercised by
  the tests and the audit.

## 5. What the tool says when it finds nothing

The most easily misread result is an empty finding list, so the run carries an
explicit account of it:

* **Dispositions** (`summary.dispositions`, shown on the Analyze Code page and in
  both report formats): how many sink calls were inspected, how many became
  findings, and for each inspected-but-unreported call *why* — no taint reached
  it, the branch is statically dead, or a declared validator cleared it.
* **Validator-guard suppressions** (`taint.guard_suppressions`,
  `dispositions.validator_guards`): symbol, context, validator rule, position,
  guarded edge and the atoms that were removed, plus the sentence that the
  validator's body was **not** analysed. A run that reported nothing because of a
  guard says so; a run whose guard hid nothing does not claim otherwise.
* **Partial analyses**: `analysis_complete`, `partial_reasons` and the
  unsupported-construct list, surfaced as a warning in the interface.

## 6. Test and verification evidence

| Suite | Command | Result |
| --- | --- | --- |
| Engine, API, reporting, workflow | `python3 -m unittest discover -s tests -t .` | **286 tests, all passing** (test_api 37, test_audit 4, test_cfg 15, test_dataflow 26, test_lexer 19, test_mutation_check 7, test_parser 27, test_reporting 24, test_rules 29, test_semantics 18, test_slicing 20, test_taint 40, test_workflow 20) |
| Interface | `cd frontend && npm test` | **30 tests, all passing** |
| Labelled corpus | `scripts/evaluate.sh` | **33 cases, 33 passed**: TP 20 / FP 0 / FN 0, file-level TN 9/9, precision = recall = F1 = 1.0, 1.14 s total |
| Independent audit | `python3 scripts/audit.py` | **69 checks, all passing** |
| Mutation check | `python3 scripts/mutation_check.py` | **18/18 deliberate defects caught** |

The mutation check is the evidence that the suite can fail: for each defect it
applies the edit, runs the tests that should notice it, restores the file
byte-for-byte, and reports an escape as a hole in the tests. It refuses to run on
a file with uncommitted changes.

## 7. Evaluation: what the numbers mean

The corpus is separate from the unit tests, hand-labelled, and intentionally
includes negatives and adversarial cases. The accounting is explicit
(`docs/EVALUATION.md` §2) because "33 cases" is not "33 detections":

| Metric group | Files | Enters |
| --- | --- | --- |
| finding-level | 18 | TP/FN over the 20 declared expectations |
| file-level (`safe`/`sanitized`) | 9 | file-level TN/FP |
| diagnostic-only (`unsupported`/`syntax_error`) | 6 | no precision/recall denominator; required diagnostics, and a finding there would still count as an FP |

The limits of these numbers, stated in the same document: they describe 33
hand-written files, with no real-world corpus, no large functions, no macros and
no aliasing. `sanitized/validated_command.ctc` counts as a true negative **only
because of the recorded validator assumption** — the taint does reach the sink.
The corpus deliberately does not include a case designed to expose the
documented context-insensitive interprocedural approximation; its effect is
described in `docs/LIMITATIONS.md` and reproducible by hand (see §10).

## 8. Security and performance posture

* **The analysed program is never executed.** No `eval`, `exec`, `compile`,
  `subprocess` or shell call anywhere in `codetrace/` (asserted by a test that
  scans the package sources); an uploaded program that would create a canary file
  when run leaves the file absent (checked by the tests and the audit).
* **Rules are data.** They are compiled by the rule-language parser; the engine
  rejects what it does not implement; injected Python inside a rule file is
  treated as text (verified live, §9).
* **Limits**: 1 100 000-byte body, 524 288-byte source and rule file,
  `sid ∈ [0, 1999]`, 4000-node/edge graph payloads, 5000-statement/500-edge
  slices, 10 000 data-flow iterations / 200 000 steps, 24 stored runs (LRU).
  Exceeding a limit is reported, and an oversized body is drained before the
  `413` envelope is sent so clients read the error instead of a reset connection.
* **Errors carry no server paths** (checked live and in the audit).
* **Performance, measured**: the whole 33-file corpus analyses in 1.14 s;
  per-phase timings for a 55-byte program are in `docs/ALGORITHMS.md`
  (medians of 25 runs, with the observed range). Timings are wall-clock on this
  machine, reported per run in `metrics.timings`; nothing in the reports claims a
  better number than the run measured.

## 9. Independent verification performed for this report

Beyond the suites, the following was done by hand against the running server:

| Check | Result |
| --- | --- |
| Launch the app and load a page | `GET /` → 200 (9 621 bytes); engine listening on `0.0.0.0:8000` |
| Full workflow over HTTP | load `vulnerable/command_injection.ctc` → analyse (1 finding) → finding detail (8-step evidence path, atoms `src:stdin@command`) → graph (8 nodes, 7 edges, kinds `call/define/return/taint`) → backward slice `[0,1,2,3]` → security slice `[0,1,2,3]` → data-flow (`reaching`, `liveness`, `definite`, all converged) |
| Custom rule validated and used | built-in rules alone on `custom_rule_demo.ctc` → 0 findings; plus `strict_rules.ctrule` → 1 finding `audit_injection` at `audit_write`; rule set becomes `built-in rules + submitted rules`, 6 sources / 9 sinks |
| Broken rule file | rejected, `SYN001` at 3:1, `valid: false`, never used |
| Rule file containing Python text | accepted as text; nothing executed |
| Syntax error | `SYN001`, `analysis_complete: false`, no finding claimed |
| Unsupported construct (pointer) | `SYN001`, run partial, reason stated |
| Oversized upload | `413 payload-too-large` envelope received by the client, no server path in the message |
| Guarded flow | `sanitized/validated_command.ctc`: 0 findings, 1 suppression record naming `validate_command`/`is_safe_command`, the disposition says the taint *did* reach the sink, and the report and the page both state the validator body was not analysed |

## 10. What is not done, and known limitations

Stated plainly, because a report that lists only successes is not a report:

* **No real-world corpus.** The evaluation is 33 hand-written files written for
  this project; precision/recall say nothing about detection quality on arbitrary
  C. There is no comparison against another tool.
* **No context-sensitive interprocedural analysis.** A parameter tainted at one
  call site is summarised as tainted for the whole function, so the tool cannot
  say *which* call site is responsible and it cannot use the caller's argument at
  the callee's branch. Measured, on three shapes:

  | Program | Result |
  | --- | --- |
  | `run(c)` called only with `"ls /tmp"` | 0 findings — the summary is not tainted by a call site that passes a constant |
  | `run(d)` with `d = input()` **and** `run(s)` with `s = "ls"` | 1 finding, at the sink inside `run`, certainty `approximate` — correct, but it does not name the call site that made the parameter tainted |
  | `run(d, 0)` (which disables the sink branch) plus `run(s, 1)` | 1 finding with `feasibility: guarded` and certainty `approximate` — a potential flow, disclosed as branch-dependent rather than claimed as reachable |

  The consequence is imprecision that the finding's own fields disclose, not an
  unqualified claim: nothing in these shapes is reported as `confirmed`. It is
  reproducible by hand and stated in `docs/LIMITATIONS.md` §1.3; no corpus case
  scores it, so the corpus numbers do not include it.
* **No pointer, aliasing, struct, union, `switch`, `goto` or preprocessor
  support.** Constructs outside the subset are rejected with diagnostics; they
  are never analysed as if they were safe.
* **Arrays are not tracked element-wise**; taint on one element is attributed to
  the whole array, and the report says so.
* **No symbolic execution, no path feasibility beyond literal conditions and
  declared guards.** Certainty categories (`confirmed`/`approximate`/`unproven`)
  exist so that this is visible per finding rather than averaged away.
* **No PDF export.** The HTML report is self-contained and printable; a PDF
  writer is not implemented, and no UI control pretends otherwise.
* **No CI configuration** is included. The equivalent local gate is
  `scripts/tests.sh`, `scripts/audit.py`, `scripts/evaluate.sh` and
  `scripts/mutation_check.py`, all of which run offline; wiring them into
  GitHub Actions would be a one-file change, but it has not been run here and is
  therefore not claimed.
* **Wall-clock numbers vary** with the machine and load (the corpus has measured
  0.8 s–1.3 s here). Deterministic numbers — counts, states, sets, findings — are
  reproducible exactly; timings are recorded per run rather than fixed.
* **The interface is not a penetration-tested web application.** It has no
  authentication and is intended to run locally; `docs/LIMITATIONS.md` §2.7
  states the deployment assumptions.

## 11. How to reproduce every claim above

```bash
python3 -m unittest discover -s tests -t .   # 286 tests
scripts/tests.sh                             # the above plus 30 interface tests
scripts/evaluate.sh                          # 33 cases, JSON evidence in var/
python3 scripts/audit.py -v                  # 69 independent checks, values printed
python3 scripts/mutation_check.py            # 18 mutations, all must be caught
python3 -m codetrace.api --port 8000         # the app, then open http://localhost:8000
```

The repository needs no key, account, network access or paid service for any of
these commands.
