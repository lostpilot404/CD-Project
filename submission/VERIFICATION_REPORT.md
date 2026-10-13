# CodeTrace — Verification Report (75% core milestone)

Date of verification: 2026-10-13 (UTC). Repository: `lostpilot404/CD-Project`, branch `arena/cd8dc62b-cd-project`.
Code verified: commit `0f2e994` (the logs were produced from the same working tree that this commit records).

Every number below comes from a command that was run in this sandbox. Logs are in `submission/evidence/logs/`; the exit codes of the main gates are in `submission/evidence/logs/exit_codes.txt`.

## 1. Commands and results

| Gate | Command (run from repo root) | Result | Log |
|---|---|---|---|
| Python test suite | `python3 -m unittest discover -s tests -t . -v` | **304 tests, OK** (exit 0) | `logs/python_tests_full.log` |
| Frontend tests | `npm test` in `frontend/` | **30 pass, 0 fail** (exit 0) | `logs/frontend_tests.log` |
| Repository audit | `python3 scripts/audit.py -v` | **69 checks passed** (exit 0) | `logs/audit_verbose.log` |
| Corpus evaluation | `scripts/evaluate.sh` | **TP 20, FP 0, FN 0; TN 9/9; precision = recall = F1 = 1.0** (exit 0) | `logs/evaluation.log`, `logs/evaluation.json` |
| Mutation check | `python3 scripts/mutation_check.py` (run on a fresh clone of `0f2e994`) | **18/18 mutations caught** (exit 0) | run output reproduced in §4 |

The corpus has 33 labelled files: 20 vulnerable (one expected finding each) and 9 safe or sanitized (no finding expected), plus 4 extra interprocedural cases. The corpus is small and hand-written, so these metrics are a regression signal, not an estimate of real-world detection quality. The evaluation JSON says the same thing.

Test counts by file (`unittest` discovery, 304 total): `test_api` 37, `test_taint` 40, `test_parser` 27, `test_dataflow` 26, `test_reporting` 24, `test_rules` 29, `test_workflow` 20, `test_slicing` 20, `test_semantics` 20, `test_lexer` 19, `test_cfg` 15, `test_clr_theory` 9, `test_mutation_check` 7, `test_core_battery` 7, `test_audit` 4.

## 2. Independent checks added in this phase

These tests check the engine against sources that do not come from the code under test.

**2.1 LR(1) parser against textbook results (`tests/test_clr_theory.py`, 9 tests).**
- FIRST and FOLLOW sets for the expression grammar match the textbook values.
- The canonical LR(1) and LALR(1) state counts match the textbook examples.
- A grammar that is LR(1) but not LALR(1) produces the expected reduce/reduce conflicts under LALR and no conflicts under canonical LR(1).
- An independent LR(0)/canonical LR(1) builder in the test file gives 656 canonical states and 167 LALR states for the CT-C grammar, which matches the engine. The grammar has 102 productions and 0 conflicts.
- Regression tests for syntax diagnostics: the expected-token list in a syntax error must name real tokens (see §3).

Evidence: `logs/probe_textbook_grammar_check.txt` and `logs/probe_independent_lr_counts.txt` (both exit 0).

**2.2 Hand-labelled taint battery (`tests/test_core_battery.py`, 7 tests).**
32 hand-labelled taint cases with the expected sink lines, plus pinned tests for two cases (Q5 and Q13). Labels were written by reading the source line by line.

Honest record of how the battery was built: the first version of the labels contained three errors that were written from memory (Q4, Q9 and Q13). The corrected labels were checked against the source lines. The first-run output is kept in `logs/battery_2_first_run.txt` (10/13 matched). After the label correction the output is `logs/battery_2.txt` (13/13). Q13 is documented as an over-approximation: a loop that may run zero times is treated as possibly executed, so the taint is reported as `approximate` rather than cleared.

**2.3 Data-flow and CFG hand checks.** `logs/probe_dataflow_hand_check.txt`, `logs/probe_cfg_shapes.txt`, `logs/probe_symbol_identity.txt`, `logs/probe_semantics_probe.txt`: small programs whose reaching-definition sets, block shapes, symbol identity and semantic errors were worked out by hand and compared with the engine output. All match.

## 3. Defects found and fixed in this phase

| # | Defect | Fix | Regression coverage |
|---|---|---|---|
| 1 | Top-bar badge read "undefined states" when the grammar summary was missing. | Frontend reads the real grammar summary (167 states / 0 conflicts). | `frontend/tests/views.test.js` |
| 2 | A semantic error produced a run marked as complete. | `codetrace/analysis/pipeline.py` now marks the run partial and gives the reason. | 2 new tests in `tests/test_semantics.py` |
| 3 | Syntax errors said "the parser expected one of: nothing". | `codetrace/frontend/clr_parser.py` `_recover` now counts REDUCE actions as well as SHIFT, so the expected list is real. | `SyntaxDiagnosticRegressionTests` in `tests/test_clr_theory.py` |
| 4 | The program graph was too small to read on wide inputs. | `frontend/js/graph.js` and `frontend/css/app.css` changed; the graph now renders at its natural width. | `frontend/tests/lib.test.js` |
| 5 | Docs had stale counts and omitted two approximations. | `docs/LIMITATIONS.md`, `docs/TECHNICAL_DESIGN.md` updated (the module table was checked with `scripts/audit.py --write-module-table` and already matched). | `scripts/audit.py` (69 checks) |
| 6 | Three battery labels were wrong (see §2.2). | Labels corrected against source lines. | `tests/test_core_battery.py` |

Syntax-error example after the fix (`examples/syntax_errors/missing_semicolon.ctc`, from `logs`/`evidence/ui_syntax_error_missing_semicolon.txt`):

```
error  SYN001  4:3   parser  unexpected identifier 'system'
       the parser expected one of: &&, =, ,, --, ==, >=
error  SYN001  4:15  parser  unexpected ;
       the parser expected one of: ,, )
This analysis is partial: the parser recovered from 2 syntax error(s) ...
```

## 4. Mutation check

`scripts/mutation_check.py` applies one deliberate fault at a time to a clone and checks that the test suite fails. Run on a fresh clone of `0f2e994` the result was **18/18 mutations were caught by the suite** (exit 0, about 26 s). Examples from the last lines of the run: `rule-unknown-selector-allowed` caught; `report-limitations-dropped` caught.

## 5. Browser verification

The app was started with `scripts/serve.sh --port 8000` after the parser fix (the earlier server had been started before the fix and was restarted). The capture tool `submission/tools/ui_capture.mjs` drives headless Chromium with `puppeteer-core` and writes 10 screenshots to `submission/screenshots/`. The run reported 0 console errors and 0 page errors. Summary of what the screenshots show:

- Top bar: `engine 1.0.0`, `rules builtin-3387b7dcd97a95f3`, `167 states / 0 conflicts`.
- 02/03: the command-injection run, the finding list and the finding detail with an 8-step evidence path.
- 04: the program graph at natural width.
- 05: reaching definitions for `build_command()`, converged.
- 07: the reports page (JSON and HTML export, run comparison).
- 08: the safe counterpart, 0 findings, with the explicit "not that the program is safe" message.
- 09: the syntax-error diagnostics with the corrected expected-token lists.
- 10: the unsupported `switch` statement, reported as unsupported and not guessed at.

The export of the command-injection run is in `evidence/report_command_injection.json` (schema 1.0, 1 finding, `analysis_complete: true`) and `evidence/report_command_injection.html`.

## 6. Known limits (not fixed; reported honestly)

- After a missing semicolon, the error is reported at the next token (4:3), not at the end of the previous line, and the expected list does not include `;`.
- Pointer syntax (`*`) produces a generic SYN001 "unexpected *", not an unsupported-construct message.
- Implicit (control-dependence) flows are not tracked as taint.
- Interprocedural analysis is summary-based and not context-sensitive.
- Interval or range reasoning is not implemented; only literal-false branch pruning and validator guards are.
- Loop handling is an over-approximation (see Q13).
- The corpus has 33 hand-written cases; the metrics above are not a benchmark result.

## 7. Reproduction

```
python3 -m unittest discover -s tests -t . -v
(cd frontend && npm test)
python3 scripts/audit.py -v          # stop any app on port 8000 first
scripts/evaluate.sh
python3 scripts/mutation_check.py    # slow; ~30 s on a fresh clone
scripts/serve.sh --port 8000         # then run submission/tools/ui_capture.mjs
/tmp/venv/bin/python submission/tools/make_architecture_figure.py   # needs matplotlib
```
