# Hostile audit — evidence index

Companion to `docs/HOSTILE_AUDIT_REPORT.md`. Every conclusion in the report names an
artefact here; every artefact here was produced in this checkout by a script in
`var/hostile-audit/tools/` and is reproducible with the commands in §6. Nothing in this
file is a placeholder: where an item could not be verified, it is marked **Not verified**,
**Failed** or **Inconclusive** and the reason is given.

Evidence classes are the mandated ones: **Manually verified** (recomputed by a second,
independent route), **Browser-API verified** (observed in the real browser through DOM /
network / console), **Automated test verified** (asserted by a test on this tree),
**Source inspected** (read from the current source, never sufficient on its own for a
defect claim), **Partially verified**, **Not verified**, **Failed**, **Inconclusive**.

`var/` is ignored by the repository's `.gitignore`, so all of this is audit output kept
outside the project's versioned files. Absolute paths below are relative to the repository
root `/home/user/CD-Project`.

> **Status of this index (reconciliation, §7 below).** The audit's evidence directory did
> not survive into the sandbox the reconciliation ran in: `var/hostile-audit/` was **empty**
> at the start of that session. Every artefact this index names as
> `evidence/probe*.json`, `evidence/oracle_*.json`, `evidence/inventory_*`,
> `logs/baseline_*`, `evidence/downloads/*` and the screenshots is therefore a **missing
> file whose contents cannot be re-inspected**, and it is kept here as the historical record
> of what was produced, not as a link a reader can follow. Probe scripts cited in §1 were
> missing too, so the reports they produced cannot be re-run. §7 lists what the
> reconciliation re-derived, which artefacts exist now, and which claims are left standing
> on the historical record alone.
>
> **Final pass (§7.3–§7.5).** A second pass on the same checkout closed three things and found
> one new defect. (1) The intermittent Python failure is **resolved, not Inconclusive**: it is
> the generated module table going stale whenever a file under `docs/` is edited, reproduced on
> demand in three attempts, and the audit's own diagnostic gap (a failing check printed no
> measured value without `-v`) is fixed with a regression test. (2) Gap N6 is closed *inside*
> the existing module-table check, so the documented 69 checks stay accurate while the
> hand-maintained prose totals under the table are now compared and refreshed — they were
> stale by up to 357 lines. (3) **D29** was found by measuring both themes instead of assuming
> the light-theme hover fix covered them: white text on the dark theme's light-blue accent
> (logo on all nine routes, both primary buttons, the lightened severity badges). It is fixed
> and re-verified in the browser. Current totals: **349 Python tests** (1 expected dirty-tree
> failure), **53 front-end tests**, **69 audit checks**, and **11/11** re-runnable detection
> mutations (the original **16/16** harness was lost with `var/`; its procedure has been
> re-created for the eleven mutations whose sites could be re-derived — see §7.1).
>
> **Status at handoff (2026-10-17).** The sandbox was recreated again and **`var/hostile-audit/`
> did not survive it** — the directory is git-ignored and nothing in it was committed, so every
> artefact §7 names below (probes, tools, evidence JSON, logs, screenshots and the recheck files
> of the final pass) is **missing as of this date**, exactly as §0 above describes for the
> original audit. The four gate results were re-established that day on a freshly built
> byte-identical copy of the current tree (§7.3; the §2 recipe, `diff -r` empty) and are recorded
> in `docs/FINAL_HANDOFF.md`; their logs are the `logs/handoff_*.txt` files in §7.3. The **16/16
> per-defect detection** result is different in kind: its harness (`reconcile_detection.py`) is
> gone with the rest, so that number is now a recorded result that cannot be re-run from this
> workspace, and it is labelled accordingly in §7.5.
>
> **Second handoff pass (2026-10-17, later the same day).** The four gate results and the
> D25–D28 checks were re-run and re-observed, the intermittent Python failure was re-demonstrated
> from a scratch copy in three bounded attempts (including the real `failures=3` signature on the
> working tree), and the change accounting was made unambiguous (report §9.8). Probes for the
> API and browser re-checks were re-created under `var/hostile-audit/tools/` because the originals
> did not survive; they are **new evidence for old defects**, not recovered artefacts, and are
> labelled as such. New files: `evidence/recheck_d25_d26.json` (18/18),
> `evidence/recheck_d27_d28.json` (0 failures over 58 measurements, axe clean in both themes),
> `logs/final_pass_*.txt`, `logs/flake_attempt*.txt`.
>
> **Committed and pushed (2026-10-17).** The fixes, the two new test files and these documents
> were committed to `arena/9761469a-cd-project` and pushed to `origin`
> (`github.com/lostpilot404/CD-Project`), at the user's instruction, as one commit on top of
> `9e3a54b`. `var/` was not committed (it is git-ignored), so the probes and evidence JSON named
> throughout this file remain **ephemeral** — they are described here in enough detail to be
> re-created, and the re-created detection harness is listed in §7.1. No history was rewritten.
>
> A third re-check was run the same day to close §7.1: the detection procedure was **re-created**
> (`reredetect_fixes.py`, 11/11 over the re-derivable mutations) and Chromium's accessibility tree
> plus an emulated `prefers-color-scheme` were added
> (`recheck_a11y_tree.mjs`, no failures). Two probe traps were found in that pass — a
> route-blind container selector and a tree/DOM read straddling a redraw — and are documented in
> §7.3 so they are not repeated.

---

## 1. Probe and oracle inventory

| Artefact | Type | What it produced | Coverage |
| --- | --- | --- | --- |
| `var/hostile-audit/tools/harness.mjs` | module | shared Chromium launcher, page loader, `settle`, `shot`, `writeEvidence` | used by every browser probe |
| `tools/probe_browser.mjs` | probe | first-page availability smoke test (engine reachable, routes render) | pre-audit smoke |
| `tools/probe1_empty_routes.mjs` → `evidence/probe1_empty_routes.json` | probe | all nine routes with **no run**: visibility, text, banner state, console/page errors | Phase A/B, defect D10 |
| `tools/probe2_attribution.mjs` → `evidence/probe2_attribution.json` | probe | deep links into every route plus banner-stickiness across route changes | D10 |
| `tools/probe3_workflow.mjs` | probe | **Failed** — the script throws inside itself before its assertions; its subjects were re-covered by probes 11, 12 and 13. Not repaired on purpose (a repaired script would look like fresh evidence for an untested path) | — |
| `tools/probe4_inventory.mjs` → `evidence/probe4_inventory.json`, `evidence/inventory_summary.txt` | probe | every interactive element per route, empty and with a run, plus the example dialog | Phase A |
| `tools/probe5_state.mjs` | probe | **Failed** — crashes inside the probe at its finding-detail section; superseded by probe 12 | — |
| `tools/probe5b_theme_rules.mjs` → `evidence/probe5b_theme_rules.json` | probe | rule-validation staleness, invalid-rule analysis path, the appearance controls and their persistence | D17, D18 |
| `tools/probe6_races.mjs` → `evidence/probe6_races.json` | probe | finding-detail race, overlapping analyses, all-edge-kinds-off | D11, D13 |
| `tools/probe6b_races2.mjs` → `evidence/probe6b_races2.json` | probe | double-click serialisation, draft-during-flight, kind-request formation | D11, D14 |
| `tools/probe7_responsive_a11y.mjs` → `evidence/probe7_responsive_a11y.json` | probe | 45 viewport×route combinations, tab order, live regions, graph focusables, axe on all routes, contrast sampling | Phase I, D19–D23 |
| `tools/probe8_detail.mjs` → `evidence/probe8_detail.json` | probe | finding card/detail DOM, axe violations per route, focus trap, overflow offenders, badge contrast | D16, D19–D24 |
| `tools/probe9_overflow.mjs` → `evidence/probe9_overflow.json` (+ 2 screenshots) | probe | scroll-width offenders per route/viewport with the offending element, its class, its text and its `white-space` | D24 |
| `tools/probe10_slice_render.mjs` → `evidence/probe10_slice_render.json` (+ screenshot) | probe | the finding → security-slice flow as rendered | D12 |
| `tools/probe11_postfix.mjs` → `evidence/probe11_postfix.json` (+ 8 screenshots, 79 s) | probe | post-fix pass: no-run graph, banner, example modal → `command_injection.ctc`, slice criterion, data-flow block sets, theme persistence and `prefers-color-scheme`, rule staleness, dirty draft, 45 viewport×route combinations, axe on nine routes, tab order | Phase I verification |
| `tools/probe12_races2.mjs` → `evidence/probe12_races2.json` (+ 4 screenshots, 42 s) | probe | finding-detail race held by request interception, clear-during-flight, route-switch-during-flight, empty source, broken rule file, reports links, same-run/unknown/empty comparisons, no-edge-kinds state and restore | Phase C/H verification |
| `tools/probe13_compare_escape.mjs` → `evidence/probe13_compare_escape.json` (+ 2 screenshots, 3 downloaded reports, 17 s) | probe | two real runs compared in the UI and through `/api/compare`, JSON/HTML report download, hostile-source escaping, report links actually downloading | Phase H |
| `tools/probe14_api_limits.py` → `evidence/probe14_api_limits.json` (20 checks) | probe | body/source/rule size limits, malformed bodies, wrong method, unknown paths and formats, traversal, CORS, LRU cache | Phase J |
| `tools/probe14b_api_limits.py` → `evidence/probe14b_api_limits.json` (17 checks, post-fix) and `evidence/probe14b_api_limits_prefix.json` (pre-fix) | probe | the exact source-size boundary, the rule-file limit on both endpoints (pre- and post-fix), report format validation on a live run, nesting depth, 403 reachability, cache size | D8 |
| `tools/probe14c_depth.py` → `evidence/probe14c_depth.json` (8 cases) | probe | nesting-depth matrix: 2 000 / 50 000 / 100 000 parentheses, 200 000 unary operators, 20 000 blocks, 5 000-deep `if` chain, 50 000 additive terms, 10 000 `break`s | Phase J |
| `tools/probe15_keyboard.mjs` → `evidence/probe15_keyboard.json` (+ 3 screenshots, 18 s) | probe | tab order from the top, dialog focus/trap/Escape restoration, theme by keyboard, source-pane focusability, graph-node activation, high-contrast persistence across reload | D18, D21–D23 |
| `tools/oracle_frontend.py` → `evidence/oracle_frontend.json` | oracle | 117 independent front-end checks (LEX codes, grammar tables, parser modes, AST shapes, semantic diagnostics), written from `docs/LANGUAGE.md`/`COMPILER_THEORY.md` | Phase D |
| `tools/oracle_analysis.py` → `evidence/oracle_analysis.json` | oracle | 92 checks: CFG shape, §11–§15 fixpoints, taint atoms, contexts, interprocedural behaviour, solving caps | Phase E/F |
| `tools/oracle_graph_report.py` → `evidence/oracle_graph_report.json` | oracle | 98 checks: graph edge kinds and `family`, `limit` handling, slice criteria, report schema fields, escaping, API error codes | Phase G/H/J |
| `var/hostile-audit/logs/baseline_python_tests.log` | log | baseline `Ran 310 tests … OK` | Phase 0 |
| `logs/baseline_tests_sh.log` | log | baseline `scripts/tests.sh`: Python + 39 front-end tests, `all suites passed`, `EXIT=0` | Phase 0 |
| `logs/baseline_audit.log` | log | baseline `all 69 checks passed`, `EXIT=0` | Phase 0 |
| `logs/baseline_evaluate.log`, `logs/baseline_evaluation.json` | log + JSON | baseline corpus run: `precision=1.0 recall=1.0 F1=1.0`, per-file table, 1.716 s over 33 files | Phase 0 |
| `logs/baseline_mutation_check.log` | log | baseline `18/18 mutations were caught by the suite`, `EXIT=0` | Phase 0 |
| `logs/probe12_stdout.txt` | log | the pre-fix `clear-during-flight` output (`afterLateResponse` still showed the previous findings and the stale notice) — the only surviving pre-fix trace of D15 | D15 |
| `logs/phaseL_tests_sh.txt` | log | the Phase-L `scripts/tests.sh` run on the working tree: `68/69 checks passed; FAILED: the module table…`, `Ran 341 tests … FAILED (failures=3)` before the table refresh | Phase L |

## 2. Screenshots (80, named by route/state/viewport)

* **Empty states, nine routes:** `empty-<route>-1440x900.png`; deep links that
  still have no run: `emptyrun-deeplink-<route>-1440x900.png`.
* **Primary workflow:** `workflow1-example-picker` … `workflow9-reports-1440x900.png`
  (picker → example loaded → analysis complete → findings → detail → graph → slice →
  dataflow → reports); `inventory-example-modal-1440x900.png`,
  `inventory-withrun-<route>-1440x900.png` (all nine routes with a run).
* **Defects, pre-fix:** `sticky-banner-after-graph-on-overview-1440x900.png` (D10),
  `c2c-graph-all-kinds-off-1440x900.png` / `c2c2-all-edge-kinds-off` /
  `c2c3-one-edge-kind-on` (D11), `g-slicing-criterion-line-undefined-1440x900.png` (D12),
  `c2a-finding-detail-race-1440x900.png` (D13), `c2b-overlapping-analyses` and
  `c3-edit-during-flight-1440x900.png` (D14), `c1-source-context-before-edit` /
  `c1-source-context-after-draft-edit-1440x900.png` (D16), `h1-rules-validated`,
  `h1b-analyze-invalid-rules` and `i1b-after-reload` / `i1b-high-contrast-on` /
  `i1b-os-dark-1440x900.png` (D17, D18), `a11y-modal-open`, `a11y-high-contrast-overview`
  (D19–D23), `responsive-rules-390x844.png` and the `responsive-*` viewport set
  (D24: `responsive-1024x768-graph`, `responsive-1440x900-graph`, `responsive-768x1024-graph`,
  `responsive-390x844-graph`, `responsive-320x640-graph`, `responsive-overview-320x640`).
* **Post-fix:** `postfix-graph-no-run`, `postfix-graph-no-kinds`, `postfix-slice-criterion`,
  `postfix-dataflow-block-sets`, `postfix-theme-dark-overview`,
  `postfix-rules-stale-validation`, `postfix-dirty-draft`, `postfix-reports-compare`,
  `postfix-overview-320x640` and `postfix-rules-390x844.png` (viewport samples).
* **Probe 12/13/15:** `probe12-finding-detail-race`, `probe12-clear-during-flight`,
  `probe12-graph-no-kinds`, `probe12-reports-compare`, `probe13-compare-two-runs`,
  `probe13-hostile-source-detail`, `probe15-dialog-focus`, `probe15-source-pane-focus`,
  `probe15-contrast-after-reload-1440x900.png`.

Downloaded report artefacts: `evidence/downloads/report.json` (16 192 B),
`report.html` (11 107 B), `probe13_report.json` (12 401 B), `probe13_report.html`
(9 226 B), `probe13_hostile_report.html` (7 478 B).

## 3. Mandatory evidence table

| # | Claim | Evidence class | Artefact (re-checkable) |
| --- | --- | --- | --- |
| 1 | Baseline before any modification: 310 Python tests OK, 39 front-end tests, 69 audit checks, corpus P=R=F1=1.0, 18/18 mutations | Automated test verified | `var/hostile-audit/logs/baseline_*` |
| 2 | Final tree: **349** Python tests (clean copy), **53** front-end tests, 69 audit checks, corpus unchanged, 18/18 mutations | Automated test verified | historical `logs/phaseL_tests_sh.txt` for the audit-close numbers; **current** numbers in report §9.5, reproduced on the disposable copy described there (§7.3) |
| 3 | The working tree itself fails exactly one Python test, the mutation check's dirty-tree refusal | Automated test verified | `logs/final_python_working.txt` (349 tests, 1 failure: the guard) and the earlier `logs/reconcile_python*.txt`; the three-failure runs are the module-table drift, explained and reproduced on demand in report §9.5 |
| 4 | Front-end oracles: 117/117, 92/92, 98/98 | **Not verified** during the reconciliation: the three oracle scripts and their JSON are missing, so neither the expectations nor the counts can be inspected — the claim rests on the historical record only | (scripts and `evidence/oracle_*.json` missing) |
| 5 | Nine routes render with no run, no exception, no sticky banner | Browser-API verified | `probe1_empty_routes.json`, `probe2_attribution.json` (pre-fix) → `probe11_postfix.json` (post-fix) |
| 6 | Control inventory per route, empty and with a run, incl. the dialog | Browser-API verified | `probe4_inventory.json`, `inventory_summary.txt` |
| 7 | Primary workflow result (1 HIGH finding, tokens/AST/blocks/definitions/edges, fingerprint) | Manually verified + Browser-API verified | historical `probe11_postfix.json`, `downloads/report.json`; **re-derived** in `evidence/reconcile_report_claims.json` (20 of 22 figures reproduce exactly) |
| 8 | The unified finding is justified: source `stdin@8` → sink `system@10`, atoms, path | Manually verified | `evidence/reconcile_report_claims.json`. **Corrected:** the certainty is `approximate` (not `confirmed` — `explain.py` reserves `confirmed` for an intra-function straight-line flow and this trace is interprocedural), and the payload's `path_length` is **8** recorded steps over **4** distinct statements; the earlier "path length 3" matches no field and is withdrawn |
| 9 | Reaching definitions / liveness / definite assignment reproduce the hand fixpoints (§13–§15) | Manually verified | report §5.1; `tests/test_audit_regressions.py` rebuilt fixpoints; `oracle_analysis.json` |
| 10 | `DFA001` location `1:21` (single line) and `3:3` (multi-line) | Manually verified + Automated test verified | `tests/test_audit_regressions.py::DefiniteAssignmentReferenceTests` |
| 11 | All three LR modes accept the corpus and agree on the AST; `earley` rejected 400 | Automated test verified | `oracle_frontend.json` |
| 12 | Control edges = the transitive guard closure, and `kinds=` matches kind *or* family | Manually verified + Browser-API verified | **re-derived** in `evidence/reconcile_control_edges.json` (15/15: an inner statement depends on all three enclosing conditions; `kinds=data` returns the taint edges of the data family) and `evidence/reconcile_kinds_family.json` |
| 13 | Slice example `backward(5)=[0,2,5]`, `forward(1)=[1,3,4]` | Manually verified | `oracle_graph_report.json` |
| 14 | Nine labelled slice/taint cases: 0 false positives, 0 false negatives | Automated test verified | `evaluation/expectations.json` + `var/evaluation.json` (per-file table) |
| 15 | Taint respects contexts, constants, overwrites, dead branches, unknown externals (`SEM008`), and is parameter-precise interprocedurally | Manually verified | report §5.2; `oracle_analysis.json` |
| 16 | Unchecking every edge kind states the situation and offers **Select all**; the restore re-checks 7 boxes and draws edges again | Browser-API verified | `probe6_races.json`/`probe6b_races2.json` (pre-fix), `probe12_races2.json` (post-fix) |
| 17 | A held finding-detail response cannot replace a newer selection | Browser-API verified | `probe12_races2.json.race` (`shownId == afterLateResponse == FD7C7B871865E`) |
| 18 | **Clear** during flight leaves the page empty and no stale notice | Browser-API verified | `probe12_races2.json.clearDuringFlight`; pre-fix trace in `logs/probe12_stdout.txt` |
| 19 | Text typed during an analysis survives and the mismatch is stated | Browser-API verified | `probe6b_races2.json` (pre-fix `TYPED TEXT SURVIVED? = False`), `postfix-dirty-draft-1440x900.png` + `probe11_postfix.json` (post-fix) |
| 20 | The finding's Source context shows the analysed text, with a drift note when the editor moved on | Browser-API verified | `c1-*` screenshots, `probe11_postfix.json` |
| 21 | Rule validation becomes visibly stale after an edit | Browser-API verified | `probe5b_theme_rules.json` (pre-fix), `postfix-rules-stale-validation-1440x900.png` + `probe11_postfix.json` (post-fix) |
| 22 | Theme: light/dark/system, persisted, follows `prefers-color-scheme`, independent of high contrast, which also persists | Browser-API verified | `probe11_postfix.json`, `probe15_keyboard.json.contrastAfterReload` (`dark contrast`, pressed, stored) |
| 23 | 45 viewport×route combinations: no horizontal overflow, no clipped control | Browser-API verified | `probe11_postfix.json`; pre-fix offenders in `probe9_overflow.json` |
| 24 | axe: 0 violations on all nine routes | Browser-API verified **with a correction** | historical `probe11_postfix.json.axe` (missing). Re-measured in `evidence/reconcile_browser.json` (0 violations on nine routes with a run loaded) **after** fixing the violations that sweep did not cover: `label-content-name-mismatch` on graph/slicing nodes (D27), `color-contrast` 1.12 on a hovered primary button (D28) and the dark theme's white-on-light-blue text (D29) — see `evidence/reconcile_axe_fixes.json`, `evidence/dark_contrast_targets.json` (pre-fix) and `evidence/reconcile_d28_states.json` (post-fix, both themes) |
| 25 | Tab order starts with the skip link and continues through the nav, with visible focus | Browser-API verified | `probe15_keyboard.json.tabOrderFromTop` |
| 26 | The example dialog holds focus, wraps both ways, and Escape returns focus to the opener | Browser-API verified | `probe15_keyboard.json` (pre-fix evidence: `probe7…focusAfterEscape`, `probe8…focusTrap`) |
| 27 | The scrollable source pane is focusable (`tabindex=0`, `role=group`, labelled) | Browser-API verified | `probe15_keyboard.json.sourcePaneKeyboard` |
| 28 | Graph nodes are focusable buttons; Enter selects and the side panel changes | Browser-API verified | `probe15_keyboard.json.graphNodes`, `.graphNodeActivation` |
| 29 | API limits: body 1.1 MB → 413 after the documented drain; source 524 288 B → 200, 524 289 B → 413; rule file 524 293 B → 413 on **both** endpoints after the fix | Browser-API verified | `probe14_api_limits.json`, `probe14b_api_limits.json` (post-fix), `probe14b_api_limits_prefix.json` (pre-fix) |
| 30 | Request validation: malformed JSON 400, array body 400, empty body 400 `missing-source`, `format=xml|JSON` 400 `invalid-format`, wrong method 404, unknown route 404 | Browser-API verified | `probe14_api_limits.json`, `probe14b_api_limits.json` |
| 31 | Traversal on `/api/examples` → 404 `example-not-found`; a static path outside the app → 403 `path-not-allowed`; no 500 | Browser-API verified | `probe14_api_limits.json`, `probe14b_api_limits.json` |
| 32 | CORS: `Access-Control-Allow-Origin: *`, preflight 204 with `GET, POST, OPTIONS` | Browser-API verified | `probe14_api_limits.json` |
| 33 | Run cache: 25 analyses → oldest `404 run-not-found`, `runs_in_memory` 24, second run still present | Browser-API verified | `probe14_api_limits.json` |
| 34 | Nesting depth is bounded and reported: 2 000/50 000/100 000 parentheses → 200 (the last two `accepted:false` with SYN010+SEM020); 200 000 unary / 20 000 blocks / 50 000 terms → 422 `input-too-deep`; 5 000-deep `if` chain and 10 000 `break`s → 200 with diagnostics | Browser-API verified | `probe14c_depth.json` |
| 35 | Reports: JSON validates against the documented schema, `input.sha256` recomputed from the analysed source, HTML self-contained and escaped (hostile source → 0 raw tags) | Manually verified + Browser-API verified | `downloads/probe13_report.json`, `downloads/probe13_hostile_report.html`, `probe13_compare_escape.json` |
| 36 | Run comparison matches `/api/compare` exactly for the same run and for a two-run pair (`0/0/1/0`, `0/0/0/1`) | Browser-API verified | `probe13_compare_escape.json` |
| 37 | Unknown run ids in the comparison produce the documented 404 surfaced as a plain message | Browser-API verified | `probe12_races2.json.compareUnknown` |
| 38 | The data-flow payload contains the atom sets needed to re-derive the fixpoint | Automated test verified | `tests/test_audit_regressions.py::DataFlowPayloadTests`, `ReachingDefinitionsReferenceTests`, `LivenessReferenceTests` |
| 39 | `->`/`&` are counted as unsupported constructs; non-ASCII digits are rejected; `int *p;` is counted | Automated test verified (+ API response) | `tests/test_audit_regressions.py::LexerSubsetTests`, `oracle_frontend.json` |
| 40 | The audit changed no existing test, no evaluation expectation, no submission file and no report template | Source inspected | `git status --porcelain`, `git diff --stat` (20 modified files + 2 new test files **at audit close**; the reconciliation's additions to three of those same files, and its own tooling and tests, are accounted separately in report §9.8) |
| 41 | Non-convergence caps (`converged:false`, iteration/step limits) — cannot be reached through the public API within documented limits | **Source inspected** / **Not verified** at runtime | `codetrace/analysis/dataflow.py`; `tests/test_dataflow.py` overrides the caps in-process |
| 42 | Screen-reader semantics of the rebuilt interface | **Not verified** — no assistive technology available in this environment; axe is structural only | `probe11_postfix.json.axe` (0 violations) is the strongest available evidence |
| 43 | Browsers other than Chromium | **Not verified** — the audit used Chromium 153.0.8010.0 and the reconciliation Chromium 133.0.6943.0; no other engine was obtainable in either sandbox (Playwright, Google and GitHub release hosts are unreachable) | historical `probe_browser.mjs`; reconciliation `evidence/reconcile_browser.json` (`chromium` field) |
| 44 | Real OS dark-mode switching | **Partially verified** — the `prefers-color-scheme` media query was emulated through CDP (`dark` and `light`), not by changing the OS | historical `probe11_postfix.json`; the control/persistence half was re-confirmed in `evidence/reconcile_browser.json` (theme cycles light/dark/system, stored, survives reload) |
| 45 | Concurrent/multi-user use, persistence across restarts, non-localhost deployment | **Not verified** — out of scope: the server is documented as a local, in-memory, single-process tool | `docs/API.md` §7 (24-run LRU, no persistence) |

## 4. Run ledger

| Run id | Used for | Artefact |
| --- | --- | --- |
| `57bf72a4486a4432` | primary vulnerable workflow (baseline engine) | `downloads/report.json`, report §4 Phase B |
| `5c35b6afa35741d7` | example-modal → `command_injection.ctc` post-fix flow | `probe11_postfix.json` |
| `53401f8014164cca` | probe 6 run under test (2 findings) | `probe6_races.json` |
| `f0af8d4eb3484c15` | probe 6 overlapping-analysis race | `probe6_races.json` (`C2b`) |
| `6086257062434e55` | probe 6b serialisation/draft run | `probe6b_races2.json` |
| `d78e894d63e04dfe` | probe 6b graph-request formation | `probe6b_races2.json` |
| `7943a23ca9dd466c`, `b634651fe8c8449a`, `3a9f5fcc412d4d26` | probe 12 race and clear runs | `probe12_races2.json` |
| `4cbe2973d9534dc1` | probe 12 reports/compare run | `probe12_races2.json` |
| `1573b68e57804636`, `be8dd77aa66849c0` | probe 13 comparison pair (comment inserted above the finding) | `probe13_compare_escape.json`, `downloads/probe13_report.json` |
| `682bf7a75bf644e0` | probe 13 hostile-source run (`<img>`, `</script>`, `&`) | `downloads/probe13_hostile_report.html` |
| `37fa8b3040d74494` | probe 14b report-format checks | `probe14b_api_limits.json` |
| `1c72c8930fe0452e`, `3d930b9c93684bd7`, `91a0dac56832424f` | probe 14 LRU probe: oldest evicted, second and newest still present | `probe14_api_limits.json` |
| `ea10ecbb885b4bdc`, `a34fc81de7444f56`, `737bb44156624136`, `bee3d97a02aa46e1`, `c1bcc9c70d524972` | probe 14c depth cases | `probe14c_depth.json` |
| `e51ff1ecae514810` | slice-criterion and `kinds=` probes | report §3.5 N1/N2 |
| `23829b368f6b44aa`, `f7a49a6215e149db`, `e51ff1ecae514810` | finding-id vs sink-id slice lookups | report §4 Phase H |

Run ids are per-process: the live server was restarted three times during the audit
(baseline → Phase K engine patch → Phase K API/rule-limit patch), so ids from different
rows belong to different processes and cannot be read as a chronological history of one
cache.

## 5. Reference computations kept with the evidence

The worked fixpoints quoted in report §5 are the values recomputed here by hand and then
asserted twice (once by the audit's own reconstruction over the API payload, once by the
project's tests). They are reproduced from `docs/COMPILER_THEORY.md` §13–§15 inputs:

```c
int main() { int a = 1; int b = 2; while (a < 3) { b = a + b; a = a + 1; } return b; }
int main() { int a; int b = a + 1; return b; }
```

Reaching definitions: `OUT(0)={d0,d1}`, `OUT(body)={d2,d3}`, header/return full.
Liveness: `IN(return)={s3:b}`, `OUT(exit)=∅`, 6 iterations. Definite assignment: ⊤ on all
non-entry blocks, `DFA001` at the reading statement. The control-dependence walk and the
nine security cases in report §5.2/§5.3 were enumerated the same way. The numbers in
report §7.1 come from the logs listed in §1, not from a summary.

## 6. Reproducing the whole audit

```bash
cd /home/user/CD-Project
python3 -m codetrace.api --host 0.0.0.0 --port 8000 &
export CHROME_PATH=/home/user/.cache/ctchrome/bin/chromium
export LD_LIBRARY_PATH=/home/user/.cache/ctchrome/lib/lib:/home/user/.cache/ctchrome/lib

node var/hostile-audit/tools/probe11_postfix.mjs
node var/hostile-audit/tools/probe12_races2.mjs
node var/hostile-audit/tools/probe13_compare_escape.mjs
node var/hostile-audit/tools/probe15_keyboard.mjs
PYTHONPATH=. python3 var/hostile-audit/tools/probe14_api_limits.py
PYTHONPATH=. python3 var/hostile-audit/tools/probe14b_api_limits.py
PYTHONPATH=. python3 var/hostile-audit/tools/probe14c_depth.py
PYTHONPATH=. python3 var/hostile-audit/tools/oracle_frontend.py
PYTHONPATH=. python3 var/hostile-audit/tools/oracle_analysis.py
PYTHONPATH=. python3 var/hostile-audit/tools/oracle_graph_report.py
```

Notes for anyone repeating this:

* `probe14b_api_limits.py` overwrites its own output file; the pre-fix copy is kept as
  `probe14b_api_limits_prefix.json`.
* The mutation check must be run on a committed copy of the tree (the audit's copy lives
  in a scratch directory outside the repository and is not part of the deliverable).
* `probe3_workflow.mjs` and `probe5_state.mjs` are known-broken probes; they are kept so
  the record shows what failed, and their subjects are covered by later probes.
* `probe14c_depth.py` spends about two minutes of CPU (the 5 000-deep `if` chain and the
  10 000-break case dominate); nothing in it executes submitted code.

---

## 7. Reconciliation appendix — the evidence that exists now

Written after the audit's evidence base was lost (§ status note at the top). Everything in
this section was produced on the current checkout with Chromium 133.0.6943.0 and axe-core
4.14.0, and the files exist.

### 7.1 Tools (all under `var/hostile-audit/tools/`, none of them part of the project)

| Tool | Re-checks |
| --- | --- |
| `reconcile_browser.mjs` | 18 interface claims in a real browser, with proven request interception for the race cases; writes `evidence/reconcile_browser.json` and the 9 `screenshots/reconcile-*.png` |
| `reconcile_axe_fixes.mjs` | axe before/after for D27 (graph/slicing) and D28 (hovered primary button) |
| `reconcile_api.py` | 45 boundary/contract checks plus 126 POST and 209 GET malformed cases |
| `reconcile_d8_rules.py` | the 512 KiB rule-file contract on both endpoints, byte vs character semantics, refusal ordering |
| `reconcile_control_edges.py` | the transitive guard closure and every `kinds=` filter |
| `reconcile_report_claims.py` | re-derives the 22 concrete figures the report quotes for the primary workflow |
| `reconcile_defect_source.py` | presence of the audit's 24 fixes (D1–D24) in the current source; D25–D29 are covered behaviourally by their tests and by the detection harness below |
| `reconcile_detection.py` | does each regression test fail when its fix is removed? (disposable copies outside the repository; 16 mutations including D29) — **lost with `var/`, recorded not re-runnable** |
| `reredetect_fixes.py` | **2026-10-17, re-created** — the same procedure for **11 of the 16** mutations whose sites could be re-derived exactly (D2, D3, D5, D6, D8, D10, D25, D26, D27, D28, D29): asserts each anchor is unique, removes the fix in a copy, requires the covering test to fail, requires it to pass on an untouched copy. Result **11/11 detected, 11/11 controls**. D9, D11, D12, D16, D17 remain on the historical record only |
| `recheck_a11y_tree.mjs` | **2026-10-17** — Chromium's accessibility tree on six populated routes (every button named, node controls exposed with matching names, lists and live regions present) and the `system` theme against a CDP-emulated `prefers-color-scheme` |
| `recheck_d25_d26.py` | **second pass** — D25/D26 against the live API: 18 cases (present non-strings → `400 invalid-parameter`; absent/null/empty → `400 missing-parameter`; unknown mode → `400 invalid-parser-mode`; the three documented modes → 200) |
| `recheck_d27_d28.mjs` | **second pass** — D27/D28/D29 in Chromium 133: 58 contrast measurements (controls × 4 states × 2 themes), accessible-name containment on the populated graph and slicing views, axe in both themes |

**Two probe traps found and fixed in this pass, both of which had produced a *false* signal.**

1. *Selector by route, not by `||`.* This is a single-page app that keeps every view in the DOM,
   so `document.querySelector('#graph-canvas') || document.querySelector('#slicing-body')` returns
   the **hidden graph view** while the active route is slicing. Used that way, the probe compared
   the graph's 8 drawn nodes with the slice's 6 exposed ones and reported a phantom accessibility
   gap. With the container chosen by route, both views agree exactly (8/8 and 6/6). The
   "8 drawn node groups per view" figure recorded in the previous pass came from the same pattern
   and is corrected in the report.
2. *Read the accessibility tree and the DOM at the same instant.* The slicing view redraws when
   its slice request lands, so a tree read followed by a DOM read can describe two different
   states. The probe now reads the drawn set, the tree, then the drawn set again, and only
   compares when it did not move.

**Copy-recipe trap, worth knowing before re-running anything on a copy.** The scratch copy must
exclude only `var/`, `node_modules/`, `.git/` and bytecode caches. An over-broad exclude matched
`frontend/package.json` as well (one file, ten lines), and the audit caught it immediately:
`frontend/: table says (21, 3486), tree has (20, 3476)`, because the module table is measured
from the copy's own tree. A copy that is one file away from the original is not the tree under
test — which is why this file reports the copy as *source-identical, `diff -r` empty*, rather
than simply "a copy".
| `reconcile_d28_states.mjs` | **final pass** — D28/D29/D27: computed colours and WCAG contrast for every control in a state matrix (normal / hover / keyboard focus / disabled) × (light / dark), plus axe on the populated graph and slicing views in both themes; writes `evidence/reconcile_d28_states.json` |
| `reconcile_dark_targets.mjs` | **final pass** — axe `color-contrast` node targets on all nine routes in the dark theme; writes `evidence/dark_contrast_targets.json` |
| `reconcile_focus_ring.mjs` + `png_scan.py` | **final pass** — tabs to a control, screenshots a strip around it and decodes the PNG with the standard library only, because `outline-style: auto` means the painted ring cannot be read from computed styles; writes `evidence/focus_ring.json` and `evidence/focus-ring/*.png` |

### 7.2 Evidence files that exist

`evidence/reconcile_api.json` (post-fix, 0 × 500) · `evidence/reconcile_api_prefix.json` (D25
pre-fix) · `evidence/reconcile_api_prefix_d26.json` (D26 pre-fix) ·
`evidence/reconcile_d25_server_log.txt` · `evidence/reconcile_d26_traceback.txt` ·
`evidence/reconcile_d8_rules.json` · `evidence/reconcile_control_edges.json` ·
`evidence/reconcile_kinds_family.json` · `evidence/reconcile_report_claims.json` ·
`evidence/reconcile_defect_source.json` · `evidence/reconcile_detection.json` ·
`evidence/reconcile_axe_fixes.json` · `evidence/reconcile_browser.json` ·
`evidence/recheck_d25_d26.json` (final pass, 16/16 cases) ·
`evidence/reconcile_d28_states.json` (final pass, 0 failures across 2 themes × 4 states) ·
`evidence/dark_contrast_targets.json` (final pass, pre-fix axe targets) ·
`evidence/focus_ring.json` + `evidence/focus-ring/*.png` (final pass, 6 screenshots) ·
`screenshots/reconcile-*.png` (9) · `logs/reconcile_workspace.txt` ·
`logs/reconcile_python*.txt` · `logs/reconcile_audit.txt` · `logs/reconcile_evaluate.txt` ·
`logs/reconcile_browser*.txt`.

### 7.3 Commands and outcomes

| Command | Outcome | Log |
| --- | --- | --- |
| `python3 -m unittest discover -s tests -t .` | 349 tests, 1 failure (the mutation guard's refusal); the earlier three-failure runs are the module-table drift, explained in §7.4 | `logs/reconcile_python*.txt`, `logs/final_python_working.txt` |
| `npm test --prefix frontend` | 53 pass / 0 fail / 0 skip, exit 0 | in-report §9.5 |
| `python3 scripts/audit.py` | all 69 checks passed, exit 0 (68/69 with the table stale, as it was at the start of the final pass) | `logs/reconcile_audit.txt`, `logs/final_audit.txt` |
| `bash scripts/evaluate.sh` | TP=20 FP=0 FN=0 TN=9, P=R=F1=1.0 | `logs/reconcile_evaluate.txt` |
| `python3 -m unittest tests.test_audit` | 6/6 OK after the refresh; 2 of 6 fail against a drifted table (reproduced, `logs`/report §9.5) | report §9.5 |
| `node var/hostile-audit/tools/reconcile_d28_states.mjs` | 0 failures: both themes × four states, axe clean on graph/slicing/analyze | `evidence/reconcile_d28_states.json` |
| `python3 var/hostile-audit/tools/reconcile_detection.py` | **historical run** — 16/16 detected, 16/16 controls; harness and evidence JSON lost with `var/`, superseded in re-runnability by the row below | `evidence/reconcile_detection.json` (lost) |
| `python3 var/hostile-audit/tools/reredetect_fixes.py` (2026-10-17) | **11/11 detected, 11/11 controls**, 0 skipped — D2, D3, D5, D6, D8, D10, D25, D26, D27, D28, D29; the five remaining front-end mutations are not re-created | `evidence/reredetect_fixes.json` |
| clean copy `/tmp/ct-final` (built from this tree with the §2 recipe, `diff -r` empty) | 349 OK, 53 front-end, 69 audit, 18/18 mutations, `scripts/tests.sh` exit 0 | in-report §9.5 |
| `python3 scripts/mutation_check.py` on the working tree | refused, 4 dirty files — the guard, not a failure | in-report §6.3 |
| `node var/hostile-audit/tools/reconcile_browser.mjs` | 18/18 checks | `logs/reconcile_browser_final.txt` |
| **handoff re-run (2026-10-17)**: `python3 -m unittest discover -s tests -t .` on the working tree | 349 tests, 1 failure — the mutation guard's refusal (exit 2) asserted as 0 | `logs/handoff_python_working.txt` |
| **handoff re-run**: `bash scripts/tests.sh` on a freshly built byte-identical copy (the §2 recipe, 195 files, `diff -r` empty) | exit 0 — 349 tests `OK`, 53 front-end pass, "all suites passed" | `logs/handoff_copy_tests_sh.txt` |
| **handoff re-run**: `python3 scripts/mutation_check.py` on that copy | 18/18 mutations caught, exit 0 | `logs/handoff_copy_mutation.txt` |
| **handoff re-run**: `python3 scripts/audit.py` (working tree and that copy) | all 69 checks passed, exit 0 | `logs/handoff_audit_tree.txt`, `logs/handoff_audit_copy.txt` |
| **second pass (2026-10-17)**: `python3 scripts/audit.py` on the working tree right after editing a `docs/` file | **exit 1, 68/69** — the stale generated table, printing the stale row and the refresh command | `logs/final_pass_audit_drifted.txt` |
| **second pass**: `bash scripts/tests.sh` on that drifted working tree | exit 1, `Ran 349 tests … FAILED (failures=3)` — the drift pair plus the dirty-tree mutation-guard refusal; the third header is cut off by the script's own `tail -n 40` | `logs/final_pass_tests_sh_tree.txt` |
| **second pass**: full discovery immediately after (the table had been healed by the suite) | exit 1, `Ran 349 tests … FAILED (failures=1)` — only the guard's refusal | `logs/final_pass_python_full.txt` |
| **second pass**: `npm test --prefix frontend` | 53 pass / 0 fail / 0 skip, exit 0 | `logs/final_pass_frontend.txt` |
| **second pass**: `git diff --check` | clean, exit 0 | — |
| **second pass**: `bash scripts/tests.sh` on a freshly built source-identical copy (195 files; `var/`, `node_modules/`, `.git/`, `__pycache__/` excluded) | **exit 0 — 349 tests `OK`, 53 front-end pass, "all suites passed"** | `logs/second_pass_copy_tests_sh.txt` |
| **second pass**: `python3 scripts/mutation_check.py` on that copy | **18/18 mutations caught**, exit 0 | `logs/second_pass_copy_mutation.txt` |
| **second pass**: `python3 scripts/audit.py` and `bash scripts/evaluate.sh` on that copy | all 69 checks passed / TP=20 FP=0 FN=0 TN=9, P=R=F1=1.0 over 33 files | `logs/second_pass_copy_audit.txt`, `logs/second_pass_copy_evaluate.txt` |
| **second pass**: `python3 var/hostile-audit/tools/reredetect_fixes.py` | **11/11 mutations caught by their covering test, 11/11 controls passed** | `evidence/reredetect_fixes.json` |
| **second pass**: `node var/hostile-audit/tools/recheck_a11y_tree.mjs` | no failures — every button named on six routes, 8/8 and 6/6 node controls exposed, `system` theme follows the emulated preference | `evidence/recheck_a11y_tree.json` |
| **second pass**: `node var/hostile-audit/tools/recheck_d27_d28.mjs` (after fixing the selector trap below) | no failures — 8 nodes graph / 6 nodes slicing, names contain the drawn text, axe clean in both themes | `evidence/recheck_d27_d28.json` |

### 7.4 Corrections carried into the report and the table above

1. **Front-end count**: 51 was correct on this tree (39 project tests + 12 audit regressions);
   the earlier "60" is untraceable in a single-commit shallow checkout and is kept as a
   historical claim. Current count 53 after D27/D28.
2. **Finding certainty**: `approximate`, not `confirmed`; `confidence: medium`.
3. **Path**: `path_length` is 8 recorded steps over 4 distinct statements; "path length 3" is
   withdrawn.
4. **Report byte sizes**: run-specific (timings are embedded) — 16 191/16 193/16 195 B JSON and
   11 106/11 108/11 110 B HTML over three runs of the same file.
5. **axe**: 0 violations holds for a run-loaded sweep with no pointer hover, after D27/D28 were
   fixed; before those fixes the graph, slicing and rules routes each reported one. The final
   pass extends this to **both themes**: with D29 fixed, the dark theme reports 0 violations on
   all nine routes.
6. **Test totals**: 349 Python (1 expected failure on the dirty tree), 53 front-end, 69 audit,
   18/18 mutations — all reproduced on a byte-identical committed copy.
7. **The intermittent Python failure was not intermittent** (final pass): `scripts/audit.py`
   measures line counts under `docs/`, so editing the two audit documents leaves the generated
   module table stale; the first run after an edit fails exactly
   `AuditRunTests.test_the_audit_passes_on_this_checkout` and
   `ModuleTableTests.test_writing_the_table_is_idempotent`, and the second of those tests heals
   the drift, which is why later runs were green. Reproduced on demand (three attempts, two
   failing while drifted, none after the refresh). The audit's own diagnostic gap is fixed:
   a failing check now always prints what it measured, and the drift reports the refresh
   command. Section 7.5 is corrected accordingly.
8. **The dark theme's accent is a light blue**, so white text on it fails: D29, found in the
   final pass by measuring both themes rather than assuming the light-theme fix generalised.

### 7.5 Still not verified

The three oracles (117/92/98) and every claim resting on probes 1–15, the 80 screenshots, the
5 downloaded reports and the `logs/baseline_*` files: those artefacts are missing, so the
checks cannot be inspected or re-run. **Added at handoff (2026-10-17):** the same now applies to
the reconciliation's own artefacts under `var/hostile-audit/` (see the status note at the top),
including the **16/16 per-defect detection** result of §7.1 — its harness was lost with the
sandbox, so the number is recorded, not currently reproducible *as recorded*. That has been
partly repaired: the procedure was **re-created on 2026-10-17** and re-run for eleven of the
sixteen mutations (**11/11 detected**, `evidence/reredetect_fixes.json`); the remaining five
(D9, D11, D12, D16, D17) are represented by the historical record only. This is new evidence for
old defects, not a recovery of the lost run. The defects' tests themselves are unaffected and
still run. Screen readers, non-Chromium browsers and a real OS
theme switch remain out of reach. The non-convergence caps of the data-flow solver are still
only source-inspected. Two of thirteen full Python runs produced two extra failures beyond the
expected mutation-guard refusal — **resolved in the final pass**: they were the module-table
drift caused by editing files under `docs/`, reproduced on demand and now guarded (report §9.5);
this is no longer an open item. The D25/D26 pre-fix HTTP behaviour cannot be re-observed in the running app
any more; the preserved pre-fix JSON and the engine traceback are the evidence.
