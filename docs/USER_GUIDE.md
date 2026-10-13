# User guide

CodeTrace analyses one file written in the CT-C subset (`docs/LANGUAGE.md`) and
reports *potential* flows from untrusted input to dangerous operations, with the
evidence for each claim. This guide covers running it, walking through the nine
pages, reading a finding, and the fix-and-recheck loop.

## 1. Running the application

Requirements: **Python 3.11 or newer**. Nothing else — no installer, no
`pip install`, no API key, no network access.

```bash
python3 -m codetrace.api                # http://0.0.0.0:8000
python3 -m codetrace.api --port 9000    # another port
scripts/serve.sh                        # the same command, documented in one place
```

Then open `http://localhost:8000` (or the preview URL if you are running inside a
sandbox). The engine prints its identity and grammar statistics at start-up:

```
CodeTrace 1.0.0 listening on http://0.0.0.0:8000
  grammar: 102 productions, 167 LALR states, 0 conflicts
  rules:   builtin-3387b7dcd97a95f3 (5 sources, 8 sinks, 4 flows)
```

If the port is taken, pass `--port`. If you are behind another origin, the API
answers CORS requests and the frontend is served from the same process, so no
proxy configuration is needed.

## 2. A five-minute tour

1. **Analyze Code** — press *Load example…* and pick
   `vulnerable/command_injection.ctc`, then *Run analysis*. The status line shows
   the run id and the analysis time.
2. **Findings** — one finding is listed. Click it.
3. Read the detail panel top to bottom: **Why this was reported** (the
   explanation), **Evidence path** (source → declaration → sink, one line per
   step with the taint atoms), **Branch conditions on this path** (empty here),
   **Sanitizers seen on this path** (empty), **Limitations of this finding**,
   **Remediation**, and **Source context** with the sink line highlighted.
4. **Program Graph** — the *Show in Program Graph* button focuses the graph on
   this finding; every edge states its reason in its tooltip and in the edge
   table.
5. **Program Slicing** — *Security slice for this finding* lists the statements
   that actually matter and why each one is in the slice.
6. **Data-Flow Analysis** — pick a function and switch between *reaching
   definitions*, *liveness* and *definite assignment*; the per-statement IN/OUT
   values come from the fixpoint, not from a heuristic walk.
7. **Rule Editor** — *Load example rule file*, press *Validate*, then
   *Use these rules for an analysis*: the rule file is placed in the custom-rules
   box of the Analyze Code page, where *Run analysis* then applies it.
8. **Reports** — download the JSON report, open the HTML report, and compare the
   run before and after your fix.

## 3. The pages

### Overview

Health of the running engine (version, grammar statistics, conflicts, rule set),
the pipeline the analysis went through, and the current run's measured numbers.
If nothing has been analysed yet, it says so instead of showing an empty chart.

### Analyze Code

*Pastable source* with a filename field, a parser-mode choice (LALR (1) is the
default; SLR (1) and canonical LR (1) are available for study), a toggle for the
built-in rule set, an optional custom rule file, and a toggle for building the
dependency graph and slices. *Run analysis* posts the source to the engine and
stores the run. *Load example…* fills the editor from the bundled corpus, and
*Clear* empties it.

Diagnostics (lexer, parser, semantic, CFG, data-flow) are listed with their
`line:col`; the run summary states whether the analysis was complete, and lists
everything that was outside the supported subset. A file that does not parse is
**not** presented as analysed.

### Findings

The list on the left, the evidence for the selected finding on the right.

* Toolbar filters: severity, category, rule, certainty, enclosing function,
  status (open / fixed — only shown once two runs have been compared) and a
  search box; **Sort by** severity, line, rule, category or certainty. Filtering
  and sorting are done on the findings the engine returned; nothing is
  recomputed in the browser.
* Each card shows severity, category, certainty, the rule, the sink location and
  the source rule.
* The detail panel shows the locations, the explanation, the ordered evidence
  path with the atoms at each step, branch conditions with an explicit note that
  conditions are recorded, not proved, sanitizers that were seen and why they did
  not neutralise the flow, the limitations that apply to *this* finding, and the
  remediation hint. You can jump from a finding to its graph or its slice.

### Program Graph

The *Graph* selector switches between the **Program dependency graph** (data,
control, call, return, taint, sanitize, define and source-to-sink edges, each
with its reason), the **Control-flow graph** of one function, and the
**Function-level call view**. The *Edge kinds* fieldset filters the dependency
view. Selecting a node shows its statement, its line, the definitions that reach
it and the taint atoms that reach it. Large graphs are truncated with a visible
warning instead of being silently cut.

### Data-Flow Analysis

Per function: the basic blocks with their statements and typed successor edges,
the analysis selector, the per-block IN/OUT values, the per-statement states
replayed after the fixpoint, iteration counts and convergence, and — for definite
assignment — the reads that may happen before an assignment (`DFA001`).

### Program Slicing

Choose a criterion (a statement from the current run) and a direction
(backward or forward): the slice, the reason each statement is included, and the
induced dependency subgraph. The security slice of a finding is one click away
from the Findings page. The panel states that slices are conservative
over-approximations.

### Rule Editor

Paste a rule file, or press *Load example rule file*; *Validate* parses it and
reports every diagnostic with `line:col`, the rule counts and the states and
conflicts of the rule-language grammar (a conflict would be printed, not hidden).
*Use these rules for an analysis* copies the editor's rule file into the
custom-rules box of the Analyze Code page (the box the engine actually reads) and
switches to that page, so what you see there is what the analysis will use. The
*Active rules* table lists the rule set the engine would use, and a rule file
that does not validate is rejected with `line:col` before any analysis runs.

### Reports

*Download JSON report* and *Open HTML report* export the current run; the HTML
report is self-contained and escapes all analysed text. In the *Compare* panel,
type the earlier and the later run id and press *Run comparison*: the buckets show
new / resolved / persistent / moved, and the Findings page then offers the status
filter described above. Identity is the flow, so inserting lines above a finding
makes it *moved*, not *new*.

### Documentation

A live index of the engine's capabilities (language subset, diagnostics
catalogue, rule language, contexts and severities, limits) plus the document list
below. Every entry points at a file that exists in this repository.

## 4. Reading a finding

A finding is a claim with evidence. In order:

1. **What** — *Potential <category> flow detected*: the tool states a potential
   flow, never an exploit.
2. **Where** — source location and sink location, each with line:col and the
   statement text.
3. **How** — the evidence path: each step names the program point, the action
   (`source`, `declaration`, `assignment`, `parameter`, `argument`, `call`,
   `return`, `sanitizer`, `validator`, `unknown-call`, `unresolved`, `sink`) and
   the taint atoms that travelled (`src:<rule>@<context>`).
4. **Why it matched** — the explanation names the flow rule, the source rule, the
   sink rule and the sanitizers the rule set expects to stop this flow.
5. **How sure** — *certainty*: `confirmed` (straight-line, intraprocedural, no
   unresolved step), `approximate` (guarded, interprocedural, unknown call or
   recursion) or `unproven` (the tracer could not follow the value to a
   configured source). Every downgrade is explained in the limitations.
6. **What to do** — the remediation hint, which usually also tells you how to
   confirm the fix by re-running the analysis.

A clean report is a statement about *this* file, *this* rule set and *this*
analysis — the report lists what was unsupported and what was not analysed, and
never claims the file is safe.

## 5. The fix-and-recheck loop

1. Analyse the file and note the run id (Findings page, status line).
2. Apply a fix — for a command-injection finding, wrap the value in the
   sanitiser the rule set declares (for example `shell_escape`).
3. Analyse the fixed file. The findings list should be empty.
4. Open **Reports**, compare the earlier run id with the new one: the finding is
   reported as *resolved*, with no *new* entries — evidence that the fix removed
   that flow and did not introduce another.
5. If you only reformatted the file, the same finding comes back as *moved* with
   its old and new line, which is how you know the identity is the flow and not
   the line number.

`examples/safe/*.ctc` and `examples/sanitized/*.ctc` are the corpus cases that
demonstrate a silent report and a resolved comparison.

## 6. Keyboard access, themes and printing

* The navigation is a list of links; `Tab` reaches every control in order and the
  current section is marked with `aria-current="page"`.
* Graph nodes are focusable: `Tab` to a node and press `Enter` or `Space` to
  select it. Status messages use `role="status"` and `aria-live="polite"`, so a
  screen reader announces the run result.
* The theme toggle switches light/dark and remembers the preference;
  `prefers-reduced-motion` is honoured.
* The layout collapses to a single column below 62 rem, and the HTML report has a
  print stylesheet (navigation and buttons are hidden when printing, so
  *Print → Save as PDF* produces a clean document).

## 7. Command-line and API use

Everything the interface does is also available without a browser — see
`docs/API.md`. The short version:

```bash
python3 -m codetrace.api --port 8000 &
curl -s localhost:8000/api/analyze -H 'content-type: application/json' \
     -d '{"source": "int main() { string c = input(); system(c); return 0; }"}'
```

## 8. Troubleshooting

| Symptom | Reason and what to do |
| --- | --- |
| "This run is no longer available in memory" | the server keeps the last 24 runs; analyse again — runs are deliberately not persisted |
| "no 'main' function found; analysis covers 0 declared function(s)" (`SEM020`) | the file has no `main`; functions are still parsed and analysed, but there is no entry point for a whole-program view |
| A finding is missing that you expected | check *Unsupported constructs* and the diagnostics: a construct outside the subset is reported, not analysed; also check that the sink function is declared by a rule (`docs/RULE_LANGUAGE.md`) |
| The report says the analysis is partial | a limit was hit (parse steps, iterations, graph size); `limits_hit` and `partial_reasons` name it |
| Your custom rule fires nothing | press *Validate*: a flow that references an unknown source/sink is `RULE020`/`RULE021`, and `RULE026` warns when a flow connects a source to a sink whose context the source never declares |
| `invalid-filename` when analysing | the filename must not contain a path separator; it is a label, not a path — the engine never reads the filesystem for your source |
| Port already in use | `--port <n>` |
