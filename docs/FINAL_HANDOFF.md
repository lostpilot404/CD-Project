# CodeTrace — final handoff

A one-page orientation for whoever picks this workspace up next. Everything here was checked
against the current checkout and the running application on **2026-10-17**; nothing is copied
from an earlier summary without being re-verified in this pass. The detailed audit lives in
`docs/HOSTILE_AUDIT_REPORT.md` and `docs/HOSTILE_AUDIT_EVIDENCE.md` (§8 below).

---

## 1. What CodeTrace currently does

CodeTrace is a **static analysis tool for a small C-like language** (CT-C, defined in
`docs/LANGUAGE.md`). It never executes the program it reads. The pipeline is:

1. **Lexer and parser** — hand-written lexer plus a canonical LR(1) / LALR / SLR parser
   generator, both in the repository; the loaded grammar is 102 productions, 51 terminals,
   167 LALR states, **0 conflicts**.
2. **Semantics** — symbol tables, scopes, external resolution, type checks,
   reads/writes/definitions per statement.
3. **Control-flow graph** and three reusable data-flow analyses — reaching definitions,
   liveness, definite assignment — each with a worklist fixpoint and documented caps.
4. **Taint analysis** from configurable sources to configurable sinks, across function calls,
   with validator/sanitizer awareness that records a suppression instead of staying silent.
5. **Dependency graph** with typed edges (data, control, call, return, taint), where every
   intra-procedural edge is justified by the reaching definitions that produced it.
6. **Slicing** — backward, forward and security slices, each sliced statement carrying a reason.
7. **Findings and reports** — each finding has a stable identity, a severity, a certainty
   (`approximate` unless the analysis could be exact), an 8-step evidence path from source to
   sink, a remediation hint, and limitations. Exports: a JSON report (schema 1.0) and a
   self-contained HTML report that escapes all analysed source text. Two runs can be compared,
   and a pure line shift is reported as *moved*, not *new*.

Served by one process: `codetrace/` (Python 3.11, standard library only) plus `frontend/`
(plain ES modules, no build step, no npm dependencies). Nothing is installed at run time.

**What it does not claim.** A short finding list means "no configured source-to-sink flow was
detected for this file, rule set and engine version" — never "this program is safe". The
documented limits are in `docs/LIMITATIONS.md`.

## 2. Start the application

The verified repository command (it is what the audit's start-up check exercises, and it is
what produced the results in §5):

```bash
cd CD-Project
python3 -m codetrace.api --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000`. The equivalent convenience wrapper is
`scripts/serve.sh` (no arguments = `--host 0.0.0.0 --port 8000`; any other port with
`scripts/serve.sh --port 9000`).

Check the top bar: it should show `engine ok`, `engine 1.0.0`, `rules builtin-…` and
`167 states / 0 conflicts`. `curl -s localhost:8000/api/health` prints the same facts as JSON.
If the port is busy, stop the older process rather than starting a second server — there is no
persistence, and every run lives in memory (24 runs, LRU).

## 3. Demonstrate the genuine command-injection example

This is the workflow `submission/DEMO_SCRIPT.md` narrates, with the numbers re-checked here:

1. Go to **Analyze Code** (`#/analyze`).
2. Press **Load example…**, pick `command_injection.ctc` (its real id is
   `vulnerable/command_injection.ctc`) and press **Run analysis** — the dialog only fills the
   editor; the analysis runs when you press the button, and the status line then shows
   `(run <id>)`.
3. The run reports **exactly one finding**, `FEF13A28F7E0E` — severity **HIGH**, certainty
   **approximate**, sink `system(command);` at line 10 (`command_system`, command context),
   source `input()` at line 8 (`stdin`). The evidence path is 8 steps, e.g. step 0
   *"input() introduces untrusted data (source rule 'stdin')"* and step 2 *"argument 0 of the
   call to build_command() is tainted"*.
4. The same run through the API (run id varies; the finding id does not):

```bash
curl -s -X POST localhost:8000/api/analyze -H 'Content-Type: application/json' \
  -d "{\"source\": $(python3 -c 'import json;print(json.dumps(open("examples/vulnerable/command_injection.ctc").read()))')}"
```

Repeat the demo with `safe/constant_command.ctc`: **0 findings**, plus the list of sinks that
were inspected and not reported, each with its reason. That contrast is the honest claim —
silence is not safety.

## 4. Inspect a finding, the graph, the data-flow result, a slice and a report

All of these read the same run; the status line names it, and every view states when it has no
run loaded rather than showing an empty drawing.

| To inspect | Where | What to look for |
| --- | --- | --- |
| A finding | **Findings** (`#/findings`) → select the card in the list; the detail pane is `#finding-detail` | severity, certainty `approximate`, the 8-step path, the sink and source records, sanitizers seen, limitations, remediation |
| The graph | **Program Graph** (`#/graph`) | 8 nodes / 7 edges for this example, each typed edge carrying the analysis result that justifies it; **Select all** restores the edge kinds after filtering, and filtering to one kind draws a strictly smaller set |
| Data flow | **Data-Flow Analysis** (`#/dataflow`) → pick `build_command` and *Reaching definitions* | the equations, the iteration count (`converged`), and the per-statement IN/OUT sets — the same numbers the audit recomputed by hand |
| A slice | **Program Slicing** (`#/slicing`) → choose the finding/sink criterion | 4 statements in the backward slice of this sink, each with its reason; the security slice contains both endpoints of the reported flow |
| Reports | **Reports** (`#/reports`) | **Download JSON report** (`schema_version` 1.0, `input.sha256` `675d372e7081…`, 8 limitations) and **Open HTML report** (self-contained; a hostile source's `<img`, `</script>` and `&` all appear escaped) |

## 5. Appearance: Dark / Light / System

The **Theme: …** button in the top bar (`#theme-toggle`) cycles **light → dark → system** and
persists the choice; `system` follows `prefers-color-scheme` live, so an OS-level switch is
reflected without a reload. The separate **High contrast: on/off** button
(`#contrast-toggle`) is its own control and also persists across reloads.

Verified colour facts for this build: light theme primary button 6.09:1, dark theme
8.17:1, high-contrast 9.27:1, and every control measured in normal / hover / keyboard-focus /
disabled states in both themes passes its WCAG requirement (the dark theme previously painted
white text on its light-blue accent — defect D29, fixed; see report §9.3).

## 6. Currently verified test commands and results

**Reading the two columns matters.** The table describes the state *during the audit*, when the
working tree was dirty by design (see §7) and `scripts/mutation_check.py` rewrites files in
place: it refused to run there — exit 2 — and `tests/test_mutation_check.py` asserts that refusal
never happens, so the *combined* `scripts/tests.sh` command **could not pass on the dirty tree**.
That was the guard working, not a test failure, and it was never bypassed. On the now-committed
branch the guard no longer fires: the commands in the "isolated copy" column run directly against
the branch, and the recorded numbers there are what to expect.

| Command | Working tree (current) | Isolated copy of this tree |
| --- | --- | --- |
| `python3 -m unittest discover -s tests -t .` | **349 tests, 1 failure** (exit 1) — the single failure is `test_one_real_mutation_is_caught_by_the_real_suite`, the guard's refusal surfacing as `2 != 0` | **349 tests, OK** (exit 0) |
| `npm test --prefix frontend` | **53 pass / 0 fail / 0 skip** (exit 0) | **53 pass** |
| `python3 scripts/audit.py` | **all 69 checks passed** (exit 0) | **all 69** |
| `bash scripts/evaluate.sh` | TP=20 FP=0 FN=0 TN=9, precision = recall = F1 = 1.0 over 33 files | unchanged |
| `bash scripts/tests.sh` | exit 1 — the guard fires first (`set -e`) | **exit 0**, "all suites passed" (349 + 53) |
| `python3 scripts/mutation_check.py` | refuses: 4 dirty files, exit 2 | **18/18 mutations caught** (exit 0) |
| `git diff --check` | clean (exit 0) | n/a |

The copy is a `tar` of this tree (excluding `var/`, `node_modules/`, `.git/`) committed in a
throw-away repository — `git status` clean, **195 files**, `diff -r` against the working tree
empty. The table above quotes no commit hash on purpose: writing one into a document stored
*inside* the tree changes the tree, so the copy is identified by the recipe and by the empty
`diff -r`, which is the property that makes its numbers describe this code. Build it and re-run
the two guarded commands with:

```bash
tar -c --exclude=./var --exclude=./node_modules --exclude=./.git . | tar -x -C /tmp/ct-copy
cd /tmp/ct-copy && git init -q . && git add -A && git commit -qm scratch
bash scripts/tests.sh && python3 scripts/mutation_check.py && python3 scripts/audit.py
```

One result is **not** re-runnable from this workspace and is recorded rather than claimed as
current: the three oracles' **117 / 92 / 98** checks (their scripts were missing before the
reconciliation began). The audit's per-defect detection harness was also lost with `var/`, but its
procedure has since been **re-created** — `var/hostile-audit/tools/reredetect_fixes.py` removes
each fix in a disposable copy and requires the covering test to fail: **11/11 detected, 11/11
controls passed** (D2, D3, D5, D6, D8, D10, D25, D26, D27, D28, D29); the remaining five front-end
mutations (D9, D11, D12, D16, D17) rest on the historical record. The defect fixes themselves are
in the source and their tests run. Probes for all of this live under `var/hostile-audit/tools/`,
which is **git-ignored** — but the harness no longer depends on them surviving: the eleven
mutation recipes are recorded verbatim in `docs/HOSTILE_AUDIT_EVIDENCE.md` §7.1a (checked to
round-trip against the harness byte for byte), so the detection run can be rebuilt exactly.

## 7. Commit and push status

**The work is committed and pushed.** On 2026-10-17, at the user's instruction, everything below
was committed to branch `arena/9761469a-cd-project` and pushed to `origin`
(`https://github.com/lostpilot404/CD-Project.git`), as one commit on top of
`9e3a54b9601ba8ae630171fdbdfa629a56022671` (`Add files via upload`, the single shallow commit this
checkout arrived with):

* **27 files** — the 22 modified tracked files plus the audit's 5 untracked deliverables
  (`docs/HOSTILE_AUDIT_REPORT.md`, `docs/HOSTILE_AUDIT_EVIDENCE.md`, this file,
  `frontend/tests/regressions.test.js`, `tests/test_audit_regressions.py`), **3247 insertions and
  75 deletions** staged. The commit hash is deliberately **not** written into these documents: a
  document cannot contain the hash of the commit that carries it, and adding it would change the
  tree it describes. Use `git log --oneline -1` on the branch.
* **Not rewritten:** no `reset`, `clean`, `stash`, `amend`, `rebase` or force-push; `main` is
  untouched; `submission/`, `evaluation/`, `examples/`, `docs/FINAL_REPORT.md`,
  `docs/PRESENTATION.md` and `.gitignore` were never edited.
* **Not committed:** `var/` (git-ignored) — the evidence, logs, probes and evaluation output all
  live there and are cleared when the sandbox is recreated. They are ephemeral by design; anything
  that must outlive this workspace is either in the commit or described in §6 and in
  `docs/HOSTILE_AUDIT_EVIDENCE.md`.

The accounting below is the state the audit recorded **before** that commit; it is what the
pre-existing-vs-audit split rests on, and it is unchanged by committing.

* Branch `arena/9761469a-cd-project`, parent `9e3a54b9601ba8ae630171fdbdfa629a56022671`
  (`Add files via upload`, the single shallow commit this checkout came with).
* **22 modified tracked files, 5 untracked files, 0 staged** at the time of the accounting;
  `git diff --stat` = 621 insertions, 75 deletions (the untracked files are not in that figure —
  `git diff` does not see them).
* The 5 untracked files were the audit's own output, listed above. Before this handoff note
  existed the untracked count was 4.
* 20 of the 22 modified tracked files were already modified when the audit began; the audit's
  own edits touched `codetrace/api/server.py`, `frontend/css/app.css`, `frontend/js/graph.js`,
  `docs/TECHNICAL_DESIGN.md`, `scripts/audit.py` and `tests/test_audit.py` on top of them.
  The file-level accounting, and what it cannot settle, is report §9.8. Hunk-level attribution
  **cannot** be established: the snapshot that separated the two recorded per-file diffstats, not
  contents, and it is gone with `var/`.

**Consequence for the gate table in §6.** With the branch committed, `scripts/mutation_check.py`
no longer sees uncommitted files, so the *working-tree* column of §6 no longer applies on the
pushed branch: the guarded commands now run there directly. What was verified on the isolated
copy before the commit — 349 tests `OK`, 53 front-end, 69 audit checks, 18/18 mutations — is
therefore now verifiable on the branch itself.

## 8. The two audit documents, and what remains unverified

* `docs/HOSTILE_AUDIT_REPORT.md` — the audit itself: defect register D1–D29, fix status,
  severities, phases, the acceptance table, the change accounting (§9.8) and the verdict (§9.9:
  **audit complete with outstanding limitations**).
* `docs/HOSTILE_AUDIT_EVIDENCE.md` — the evidence index: probe inventory, the mandatory
  evidence table, and §7 which lists what the reconciliation re-derived and what is left
  standing on the historical record alone.

Explicitly **not verified**, in this workspace and in general:

* The three oracles' 117 / 92 / 98 checks and every claim resting on the original audit's
  probes, baseline logs, downloaded reports and screenshots — those artefacts are gone.
* The audit's own `var/` evidence from the reconciliation, and the original 16/16 detection
  harness (recorded, not re-runnable *as recorded*) — its procedure has since been re-created
  and re-run for eleven of the sixteen mutations (11/11, see §6); D9, D11, D12, D16 and D17 rest
  on the historical record only.
* The non-convergence caps of the data-flow solver: **source-inspected only** — they cannot be
  driven to their limit through the public API without patching the engine.
* Any browser other than Chromium (133 in the reconciliation, 153 historically) — the
  dark-theme colour measurements and the painted focus ring are Chromium-only observations.
* Screen-reader behaviour — **not** testable here. Beyond axe, Chromium's own accessibility
  tree was inspected on six populated routes (every button named, the graph and slicing node
  controls exposed with matching names, lists and live regions present), which is what assistive
  technology reads but is not a screen reader.
* A real OS-level theme switch. The app's `system` mode *was* verified against an emulated
  `prefers-color-scheme` (switching the emulated preference moves the app live, without a
  reload), but that is emulation, not the operating system.
* Concurrent/multi-user use, persistence across restarts and non-localhost deployment — out of
  scope by design for a single-process, in-memory tool.

**Verdict: ready to hand over, audit complete with outstanding limitations.** The application
runs, the genuine finding reproduces, and every suite that can run in this workspace has been
run with its exact result above. It is not "fully verified": the missing evidence base, the
solver caps, the single-browser measurements and the whole-suite command's deliberate refusal on
the dirty tree are limitations of the evidence, not defects — and they are stated here rather
than smoothed over.
