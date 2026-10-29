# Frontend regression tests (development-only)

Scripted-DOM tests for the CodeTrace web interface. They run the **real**
ES modules from `frontend/js/` in [jsdom](https://github.com/jsdom/jsdom),
wired over real HTTP to the **real** Python API, which the suite starts
itself with the documented command (`python3 -m codetrace.api`) on an
ephemeral port. Nothing here ships with the application; the app itself
remains dependency-free with no build step.

## Requirements

* Node.js ≥ 20 (uses the built-in test runner and global `fetch`)
* Python 3.11+ for the API server the suite spawns

## Run

```bash
cd frontend-tests
npm install        # once; installs jsdom only
npm test
```

The Python engine tests live in `tests/` at the repository root
(`scripts/test.sh`); the corpus gate is `scripts/evaluate.sh`.

## What these tests do and do not prove

They pin interaction contracts that were fixed in the 2026-10 audit:
example-picker filtering and persistent notices, rule-editor hand-off,
mid-analysis navigation, finding focus in the graph, function-level mode
controls, the comparison's record lists and `fixed` filter (including that
an earlier-run finding's detail is fetched from the earlier run and its
graph/slice actions are withheld), filter-controls-actually-filter, and the
slice detail-truncation notice.

jsdom is **not a browser**: no layout, painting, focus rings, responsive
breakpoints or rendered contrast is exercised here, and synthetic events can
differ from real user input (a dispatched click on a disabled button, for
instance, bypasses the browser's activation suppression). Those checks are
listed in `docs/MANUAL_BROWSER_VERIFICATION.md`.
