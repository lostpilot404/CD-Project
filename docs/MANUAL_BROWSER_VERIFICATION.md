# Manual browser verification procedure

**Status at the time of writing: BLOCKED — NOT VERIFIED.** The environment in
which this branch was developed and tested has no browser binary available, so
no step below was executed in a real browser. Nothing in this document or in the
repository claims real-browser verification.

What *is* verified automatically:

* the engine, the HTTP API and the corpus gate — `scripts/test.sh`,
  `scripts/evaluate.sh` (Python suite, 56 tests; corpus, 36 cases);
* the workbench at the DOM level — `frontend-tests/` drives the real
  `index.html`, the real view code and the real API inside `jsdom` (10 tests:
  boot, end-to-end analysis, filters that change data, the example picker,
  notices surviving navigation, mid-analysis navigation, graph focus/function
  modes, run comparison, slice-table truncation).

A scripted DOM is **not** a browser: it does not prove layout, CSS, real focus
handling, downloads or timing behaviour. This procedure is the manual
acceptance pass that closes that gap. It takes about 15 minutes.

## Prerequisites

* Python ≥ 3.10 (developed on 3.11.2). No Python dependencies to install.
* Google Chrome (or Chromium/Firefox — steps are written for Chrome).
* Start the server and check it answers:

```bash
python3 -m codetrace.api          # listens on http://0.0.0.0:8000
curl -s http://localhost:8000/api/health
```

Expected: `{"status": "ok", ...}`. Then open `http://localhost:8000` in the
browser and open DevTools → Console before starting. **The console must stay
free of errors through every step**; any red entry is a failure to record.

## Procedure

Record the evidence named in each step (screenshot file + a line in the
checklist at the bottom). The status line under the editor prints the current
run id (`run xxxxxxxxxxxxxxxx`) — note it whenever a step fails.

| # | Action | Expected behaviour | Evidence |
| --- | --- | --- | --- |
| 1 | Load the page | Overview is visible; the stats panels show the engine version, the LALR(1) state count, the rule-set version label (`builtin-…`) and the last analysed file; the sidebar lists nine views (Overview, Analyze Code, Findings, Program Graph, Data-Flow Analysis, Program Slicing, Rule Editor, Reports, Documentation) | screenshot `01-overview` |
| 2 | Analyze Code → *Load example…* | A modal opens listing the bundled examples grouped by category. **Every entry is a `.ctc` program — the `.ctrule` rule file must not appear here** (it belongs to the Rule Editor's own button). The list loads without a stuck spinner | screenshot `02-picker` |
| 3 | Pick `vulnerable/command_injection.ctc` | Modal closes; editor and filename are filled; the status area shows an info notice `Loaded vulnerable/command_injection.ctc — …` and the notice states the expected finding count | screenshot `03-loaded-notice` |
| 4 | *Run analysis* | Status shows `Analysed command_injection.ctc in … (run …)` plus the notice from step 3; the summary reports 1 finding | screenshot `04-summary` |
| 5 | Navigate to Overview, then back to Analyze Code | The `Loaded …` notice is still there (it is state-held, not a transient DOM paint) | note in checklist |
| 6 | Findings | One finding card (category `command-injection`, rule `command_execution`, severity HIGH). Click it: the detail pane shows the source, the sink, the evidence path and slice links. Change the severity filter to `INFO`: the list empties; back to the default: the card returns. The filter must change the list, not just the widget | screenshots `06-finding-detail`, `06-filter-empty` |
| 7 | Program Graph | Statement-level mode draws the CFG of the finding's function; *Focus* marks exactly one highlighted node and the caption mentions the focused finding. Switch to function-level mode: the dependency checkboxes disappear, a function with no calls/returns shows an honest empty state, not a blank canvas | screenshots `07-focus`, `07-function-mode` |
| 8 | Data-Flow Analysis | The kind selector offers reaching definitions, liveness and definite assignment; each renders a per-statement IN/OUT table for the selected function; picking a statement highlights it | screenshot `08-dataflow` |
| 9 | Program Slicing | Choose the sink statement as the criterion, backward direction: the slice lists the statements the sink depends on (the tainted assignment chain); clicking a slice entry shows its detail | screenshot `09-slice` |
| 10 | Rule Editor | *Load example* fills the editor with a rule file; *Validate rules* reports `Valid: N source(s), N sink(s), …`. Replace the text with `version 1` + `sink broken { function system arguments 0 context command }`, then delete the `function system` item and validate again: a rejected alert appears with `RULE007` (missing required item) and its line/column | screenshots `10-valid`, `10-rejected` |
| 11 | Restore the example rules, press *Analyze with these rules* | The app navigates to Analyze Code, the rules box is filled, and a confirmation notice survives the hash change | screenshot `11-handoff` |
| 12 | Clear the custom-rules textarea on Analyze Code (select all, delete — the *Clear* button resets the source editor and the run, not the rules box), then load and analyze `sanitized/shell_escape.ctc` from the picker | The run completes with **0 findings** — the sanitizer kills the flow; the summary reports the zero honestly instead of hiding the view. (Leaving rules in the box would send them with this analysis — clearing is part of the step) | screenshot `12-sanitized-clean` |
| 13 | Reports | The run history lists both runs. Select the vulnerable run as *before* and the sanitized run as *after*, press *Compare*: the comparison records the resolved finding (`command_execution`) from the earlier run | screenshot `13-compare` |
| 14 | Reports → export | JSON and HTML export buttons download files; the JSON opens and contains `schema_version`; the HTML renders in a new tab | downloaded files |
| 15 | Mid-analysis navigation | Back on Analyze Code, paste any source and press *Run analysis*; while the spinner is up, immediately click Overview, wait a second, return to Findings | the completed run's results are there — navigating away mid-analysis must not lose the result | note in checklist |
| 16 | Console & network hygiene | DevTools Console: no errors at any point. Network tab: every `/api/*` request answered 2xx except deliberately invalid ones (step 10 validation still returns HTTP 200 with `valid: false`) | screenshot `16-console` |

## Checklist to fill in

```
step  result (PASS/FAIL)  evidence file / note
1     ____                ____
…     ____                ____
16    ____                ____
browser + version: ________    date: ________    run ids seen: ________
```

## If a step fails

1. Record the run id from the status line, the exact console error, and the
   failing request/response from the Network tab.
2. Check whether the equivalent scripted-DOM test in `frontend-tests/` passes
   (`cd frontend-tests && npm test`). If it does, the defect is
   browser-specific (layout, focus, timing) — file it as such.
3. Do not edit expectations or tests to make a failure disappear; the corpus
   and the suites are regression signals, not fixtures to bend.
