# Limitations and threat model

Two different questions are answered here:

1. **What the analysis cannot do** (its limits as a static analyser), and
2. **what the tool itself does to stay safe** while handling untrusted input.

Nothing in this document is aspirational: each paragraph describes behaviour you
can check in this checkout.

---

## Part 1 — Limits of the analysis

### 1.1 It is static analysis, not a proof

CodeTrace never executes the analysed program. A reported flow means *the
analysis could not rule it out*, and the report says so verbatim:

> Static analysis only: the analysed program is never executed. A reported flow
> means the analysis could not exclude it, not that it is exploitable.

The finding text is written accordingly ("Potential … flow detected",
"exploitability was not established"), and the finding records certainty as
`confirmed` / `approximate` / `unproven`. A clean run is **not** a statement that
the file is safe: the report lists what was not analysed (`unsupported`) and what
the analysis could not see (`unknown_values`, which is kept empty rather than
filled with guesses).

### 1.2 Language subset

The analyser covers CT-C subset v1 (`docs/LANGUAGE.md`): a small C-like language
without the preprocessor, pointers, structs, unions, enums, `switch`, `goto`,
`do/while`, exceptions, templates or multi-file translation units. Constructs
outside the subset are reported (`LEX100`, `LEX101`, `LEX102`, `SYN100`) with
their exact location and are counted in `summary.unsupported_constructs`; the run
is then marked partial. A file using them is **not** silently treated as clean.

Consequences worth stating plainly:

* a macro that hides a sink (`#define RUN(c) system(c)`) is not analysed — the
  directive is reported, and the call it would expand to does not exist in the
  parsed source;
* a pointer passed to a sink is outside the subset, so the flow that would go
  through it cannot be reported;
* code guarded by `#ifdef` is not conditionally compiled; both branches may
  appear, and the directive itself is an unsupported construct.
* a program with an **error-severity semantic diagnostic** (for example an
  undeclared identifier `SEM001`, a wrong argument count `SEM009`, or a type
  mismatch `SEM005`/`SEM010`) would not compile under C rules. The run is marked
  partial (`analysis_complete: false`, reason "semantic error(s) were
  reported"), because the names or values involved could not be resolved.
  Warnings such as shadowing (`SEM018`) do not make a run partial.

### 1.3 Analysis approximations

| Approximation | Where it shows | What it means for a finding |
| --- | --- | --- |
| **Context-insensitive interprocedural summaries** | `analysis.taint.notes`, finding limitation | a parameter tainted at *one* call site makes the function's return value tainted at *every* call site; findings may therefore be conservative (false positives possible) |
| **Flow-sensitive but not path-sensitive taint** | `feasibility` | straight-line and guarded paths are distinguished, and literal `false` prunes an edge, but correlated conditions (`if (a) … if (a)`) are not solved; the wording never claims symbolic execution |
| **Loop conditions are not evaluated** | `certainty: approximate` | a loop body is treated as possibly skipped, so a value tainted *before* a loop whose body always overwrites it (`c = input(); while (i < 3) { c = "ls"; … } system(c);`) is still reported. The engine does not compute the trip count, so this is a may-analysis false positive, marked `approximate` |
| **Explicit flows only (no implicit flows)** | — | taint follows data dependencies (assignments, expressions, arguments, returns). It does not follow control dependencies: `if (input() == "x") { c = "pwd"; }` does not make `c` tainted, so a value chosen by a branch on untrusted data is not reported. This is the standard explicit-flow policy and is a known false-negative class |
| **May-analysis data dependence** | dependency graph edges, slices | an edge exists when the definition *may* reach the use; slices are conservative over-approximations and the slice carries a note saying so |
| **No alias analysis** | pointers are unsupported, arrays are coarse | taint assigned to one array element is attributed to the whole array; two array elements are never distinguished |
| **No struct/field precision** | structs are unsupported | — |
| **Intra-procedural definite assignment** | `DFA001` | uninitialised reads are tracked within a function, not across function boundaries |
| **Text-based finding identity** | run comparison | identity hashes the sink statement text, so renaming the sink's variable reports the finding as *new* + *resolved* rather than *moved* |
| **Context-insensitive summaries, measured** | `certainty: approximate`, `feasibility: guarded` | `run(c)` called only with a constant reports nothing; `run(input())` together with `run("ls")` reports once, at the sink inside `run`, without naming the responsible call site; `d = input(); run(d, 0);` where `0` disables the sink branch reports a flow marked `guarded`, because the summary cannot use the caller's argument at the callee's branch |
| **Sanitizers only where declared** | `sanitizers_seen`, `RULE026` warning | a sanitiser that is not declared in a rule is treated as an unknown function, so taint continues through it; a declared sanitiser is trusted for exactly one context (or all contexts with `*`) and only for the argument it declares |
| **Modelled externals only** | `unknown-call` path steps | an unmodelled function's result is assumed to depend on its arguments (never assumed safe), and the finding records that assumption |
| **Validator bodies are not analysed** | `validator_guards`, `guard_suppressions`, run `notes` | a rule-declared validator guarding a branch clears the taint that crosses that branch, and the analysis assumes it rejects every value unsafe for its declared context. The assumption is recorded per guard (symbol, context, line, removed atoms) and repeated in the run's `limitations`, so a suppressed flow is never presented as a flow that never existed |

### 1.4 Bounded work, disclosed when it bites

Every analysis is capped: 1 MiB source, 400 analysed functions per run,
2000 statement index, 4000 graph
nodes/edges, 5000 slice statements / 500 slice edges, 10 000 data-flow
iterations / 200 000 steps, parser step and syntax-error limits, 2500 automaton
states. When a cap is reached the run sets `limits_hit`, marks the analysis
partial (`summary.analysis_complete = false`, `partial_reasons`) and says which
cap was hit. Truncation is never silent.

### 1.5 Coverage of the evaluation corpus

The measured precision/recall figures in `docs/EVALUATION.md` describe **the 33
hand-written `.ctc` corpus files in `examples/`**, nothing else. They are a
regression signal for the pipeline, not an estimate of real-world detection
quality, and the corpus is small enough that a single case moves the numbers by
several points.

---

## Part 2 — Threat model of the tool

The analyser processes untrusted input: source files and rule files supplied by
whoever uses the app. The design assumption is that **both are data**.

### 2.1 The analysed program is never executed

* The pipeline is parsers and analyses only: no `eval`, `exec`, `compile`,
  `__import__`, `subprocess`, `os.system` or dynamic import anywhere in
  `codetrace/`.
* Uploading a program that would create a canary file when run leaves the file
  absent, because nothing executes it.
* Nothing writes the analysed source to disk: it lives in memory for the
  lifetime of the run.

### 2.2 Rule files are never executed either

The rule language has no expressions, no control flow and no host-language
interop. A rule file is parsed by the rule-language grammar (40 productions, 78
states, 0 conflicts) and then checked by declarative validators. A rule file
containing `__import__('os').system(...)` is a syntax error at a reported
line:column, and a file with any error is refused before analysis (`422
invalid-rules`). Rule diagnostics never echo server state.

### 2.3 Filesystem

* Static files are served only from `frontend/`, with a `realpath` prefix check;
  traversal attempts (`/..%2f…`, `%2e%2e%2f`, `..%5c`, `%2fetc%2fpasswd`) answer
  `403 path-not-allowed` or `404` and leak nothing.
* Example files are served only from `examples/`, by id from an index built from
  that directory (`category/name`); an id that does not match is `404`.
* The server never writes reports or runs to disk; `var/` is written only by the
  evaluation script the user runs deliberately.

### 2.4 Resource exhaustion

Request bodies (1.1 MiB), sources (512 KiB), rule files (512 KiB), stored runs
(LRU 24), graph payloads, slices and fixpoints are all capped, and hitting a cap
produces a structured error or a partial-analysis flag instead of a hang. Deeply
nested input that exceeds the recursion budget answers `422 input-too-deep`.
Malformed JSON is `400 invalid-json`; unknown parameters are `400
invalid-parameter`; there is no endpoint that takes a path, a URL, a command or a
filename to read.

### 2.5 Information exposure

Every error uses one envelope
(`{"error": {"code", "message", "detail"}}`) and never contains a stack trace, a
filesystem path or environment content: no error body carries a `Traceback` or a
host path. The JSON and
HTML reports contain the analysed source (which the requester supplied) and the
filename as given, escaped for HTML.

### 2.6 Supply chain

There is no supply chain to attack: the project has **zero third-party runtime
dependencies** (Python 3.11 standard library only) and the frontend is vanilla ES
modules with no bundler and no npm packages. Nothing calls a remote service, and no
credential, API key or paid account is required at any point.

### 2.7 Deployment assumptions

The server binds `0.0.0.0` by default so the sandbox preview can reach it, and it
has **no authentication**. It is meant to run locally, on the user's own machine
or in a container, for one user at a time. Before exposing it to a network, add
an authenticating reverse proxy; running it on the public internet as-is is
outside the intended use.

### 2.8 What the tool does not protect against

* **It does not make the analysed program safe.** Fixing what CodeTrace reports
  removes one class of flow; it says nothing about the rest of the program.
* **It does not detect all vulnerabilities.** Only the flow rules in the active
  rule set are checked (by default: command injection, SQL injection, path
  traversal, format string). Logic bugs, authentication, cryptography and memory
  safety of the *analysed* language are out of scope.
* **It does not sandbox a malicious rule file's *content* beyond parsing it** —
  but since rule text is never executed, a hostile rule file can at most define
  rules that report nothing or report noise; it cannot run code or read files.
* **It does not defend the host from a compromised browser session**; the
  frontend renders engine data, not user-authored markup (source is inserted
  with `textContent`, never `innerHTML`), which removes the obvious XSS vector
  from a report filename or source line.
