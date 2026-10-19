# Presentation outline and viva questions

For presenting CodeTrace, and for the questions that usually follow. Every number
here is produced by the commands quoted next to it; run them on the machine you
present from and read the output aloud rather than trusting this page.

## 0. Before the talk

```bash
python3 -m codetrace.api --port 8000     # or scripts/serve.sh
python3 scripts/audit.py                 # the Definition-of-Done self-audit
python3 -m unittest discover -s tests -t .   # the engine suite
scripts/evaluate.sh                      # the labelled corpus
```

Have these windows ready: the app on `http://localhost:8000`, a terminal with the
audit output, and `docs/COMPILER_THEORY.md` open at the table of contents. Test
the port before the audience arrives; if the port is busy the engine says so.

## 1. Talk outline (18 minutes, 12 slides)

| # | Slide | The one point | Time |
| --- | --- | --- | --- |
| 1 | Title + the sentence *"A compiler front end is a security tool"* | the claim | 0:30 |
| 2 | The problem: a command built from input, reachable only through a helper | why text search is not analysis | 1:00 |
| 3 | The pipeline diagram (lexer → CLR parser → AST → symbols → CFG → data-flow → taint → dependencies → slices → findings) | everything downstream depends on a correct parse | 1:30 |
| 4 | Grammar: 102 productions, FIRST/FOLLOW, LR(1) items, closure, GOTO | the theory is implemented, not cited | 2:00 |
| 5 | Table construction: canonical LR(1) 656 states → LALR 167 states, 0 conflicts; SLR for comparison | merging states merges lookaheads | 2:00 |
| 6 | Data-flow framework: reaching definitions and liveness on one loop, by hand and by the engine | the same equations, twice | 2:00 |
| 7 | Taint: sources, sinks, sanitizers, context, certainty, and the honesty rules (unknown call keeps taint; no symbolic execution) | what the tool does *not* conclude | 2:00 |
| 8 | Dependency graph and slices: typed edges with reasons, backward/forward/security slices | every edge is justified | 1:30 |
| 9 | The interface: nine pages, evidence per finding, comparison of runs | a result a human can check | 1:30 |
| 10 | Evaluation: 33 labelled files, TP 20, FP 0, FN 0, precision = recall = F1 = 1.0, ≈1.2 s | measured, on that corpus only | 1:30 |
| 11 | Limitations and threat model | credibility | 1:00 |
| 12 | What I would do next | judgement | 0:30 |

## 2. Demo script (7 minutes, no typing if you can avoid it)

1. **Overview** — the engine identity, the grammar statistics and the pipeline.
   Say: *"the engine built its tables at start-up; if they had conflicts it would
   say so here and in the API."*
2. **Analyze Code → Load example → `vulnerable/command_injection.ctc` → Run
   analysis.** Point at the summary: 1 finding, HIGH, and the statement/block
   counts. Then load `unsupported/switch_statement.ctc` and show the diagnostics
   panel: the construct is named, the file is marked partial, and no finding is
   claimed for the skipped region. Finally load
   `sanitized/validated_command.ctc` and stay on this page: zero findings, but
   *What the engine saw but did not report* says the sink call was inspected,
   names the validator that cleared the flow, and states that the validator's
   body was **not** analysed — the difference between "nothing reaches the sink"
   and "something was assumed to stop it" is the point of that panel.
3. Back to the vulnerable file, **Findings** page: filters, then the detail panel.
   Read the "Why this was reported" paragraph aloud; open **Evidence path** and
   show the `parameter` and `return` steps — that is the interprocedural hop.
4. **Program Graph** — hover an edge to show its reason; switch to the
   function-level view to show the call edge into the helper.
5. **Data-Flow Analysis** — `reaching definitions`, the loop blocks, the IN/OUT
   sets, the iteration count; switch to `liveness`.
6. **Program Slicing** — *Security slice of this finding*; read one reason from a
   row: it names the definition and the read it reaches.
7. **Rule Editor** — *Load example rule file* (`examples/custom_rules/strict_rules.ctrule`),
   *Validate* (no diagnostics, rule counts, grammar states), then *Use these rules
   for an analysis*, which puts the file in the Analyze page's custom-rules box;
   load `custom_rules/custom_rule_demo.ctc` and press *Run analysis*. Show that
   the custom rule fires where the built-in rules did not, and that the
   wrong-context sanitiser does not stop the flow. Also show that a broken rule
   file is rejected with `line:col` and never used.
8. **Reports** — download the JSON report, open the HTML report, then compare the
   vulnerable run with the sanitised one and read the *resolved* bucket.
9. Close on **Documentation** — the language subset, the diagnostic catalogue and
   the document list, all served by the engine.

Fallback if something misbehaves live: `python3 scripts/audit.py` prints 69
independent checks (grammar, hand-computed data flow, graph, slices, rules, HTTP
workflow, malformed input, the interface contract, document accuracy) and each
line states what it observed.

## 3. Numbers to quote (and where they come from)

| Claim | Value | Command |
| --- | --- | --- |
| Grammar | 102 productions, 51 terminals, 36 non-terminals | `python3 scripts/audit.py -v` |
| Tables | 167 states in LALR and SLR, 656 canonical LR(1) states, 0 conflicts in all three modes | same |
| Rule language | 40 productions, 78 states, 0 conflicts | `/api/rules` |
| Tests | 350 engine tests + 53 interface tests | `python3 -m unittest discover -s tests -t .`, `cd frontend && npm test` |
| Audit | 69 checks | `python3 scripts/audit.py` |
| Mutation check | 18/18 deliberate defects caught | `python3 scripts/mutation_check.py` |
| Corpus | 33 labelled files, 20 expected findings, TP 20 / FP 0 / FN 0, TN 9/9, P = R = F1 = 1.0 | `scripts/evaluate.sh` |
| Speed | whole corpus in ≈1.1 s; median ≈11 ms per file; first file ≈0.8 s (parser-table build included) | `scripts/evaluate.sh` |
| Dependencies | none (Python 3.11 standard library only) | `ls requirements.txt` (absent) |

Quote the environment with the timing: Python 3.11, Linux x86-64, 2 CPUs. The
evaluation numbers describe that corpus, not security in general; say so before
someone else does.

## 4. Viva questions

### Lexer and parser

1. **Why write your own LR generator?** The pipeline needs a parse tree with
   exact source spans and the ability to *show* FIRST/FOLLOW, items, closure,
   GOTO and the tables; an opaque third-party parser would hide the theory and
   would treat unsupported syntax differently from the documented subset.
2. **Canonical LR(1) versus LALR(1) — what is merged, and what breaks?**
   Canonical LR(1) keeps a separate item set per lookahead; LALR merges states
   with identical LR(0) cores, intersecting lookaheads. Merging can introduce
   reduce/reduce conflicts that canonical LR(1) does not have. Here the merge
   produces zero conflicts, and the canonical construction runs as an independent
   check (167 states versus 656).
3. **Why is SLR included if it is weaker?** FOLLOW sets are coarser than
   lookaheads, so SLR can conflict where LALR does not; shipping all three lets
   the same grammar be compared and shows the students' textbook distinction is
   real. All three are conflict-free for this grammar.
4. **How do you know there are no conflicts?** The table builder collects them
   instead of resolving them silently: `tables.conflicts` is empty and is exposed
   through `/api/grammar` and the Documentation page. A conflicted grammar would
   be reported with the state, the item and the two actions.
5. **What happens on a syntax error?** The parser records a diagnostic with
   `line:col`, the unexpected token and the expected set, then recovers so that
   later errors are still found; the run is marked as not accepted and is never
   presented as analysed.
6. **How is precedence handled with an ambiguous-looking grammar?** The grammar
   is *not* ambiguous: expressions are stratified (or → and → equality →
   relational → additive → multiplicative → unary → postfix → primary), so
   precedence and associativity are encoded structurally rather than patched in
   with conflict resolutions.

### AST and semantics

7. **What does an AST node carry?** A node class, a source span, and the derived
   line/column of its first token, so any diagnostic or finding can be traced back
   to characters. The AST page shows type, children, span and resolved symbols.
8. **How are symbol IDs assigned, and why does that matter?** A `SymbolTable`
   walks the tree scope by scope and interns each declaration with a monotonically
   increasing id; two different `x` in nested scopes never share an id. Findings,
   taint atoms and the dependency graph all key on those ids, which is why
   shadowing cannot be silently confused.
9. **Which semantic errors are detected?** Undeclared identifiers, redeclaration
   in the same scope, arity and type mismatches on calls, and uses of
   uninitialised variables are reported with locations and codes; unknown
   functions become externals whose return value is `unknown`, never "safe".

### Control flow and data flow

10. **How is the CFG built from a structured program?** `CFGBuilder` walks the
    statement tree: sequences chain, `if` creates true/false edges into a merge
    block, `while`/`for` create a header with a back edge, and `break`/`continue`
    target the loop's recorded exit and header. Then a reverse reachability pass
    marks blocks unreachable from the entry.
11. **Write the reaching-definition equations and the transfer function.**
    `OUT[B] = GEN[B] ∪ (IN[B] − KILL[B])`, `IN[B] = ⋃ OUT[P]` over predecessors;
    the statement-level transfer is `out(s) = gen(s) ∪ (in(s) − kill(s))`.
12. **Why does liveness run backwards?** A variable is live where a path exists
    to a use before any redefinition; that is a backwards may-analysis:
    `IN[B] = USE[B] ∪ (OUT[B] − DEF[B])`, `OUT[B] = ⋃ IN[S]`.
13. **Why a worklist instead of round-robin iteration?** The worklist only
    revisits blocks whose input changed, which is the classic fixpoint algorithm;
    the engine also caps iterations and steps and reports a `limits_hit` entry
    instead of looping forever.
14. **How do you know the fixpoint is right?** Three ways: monotone transfer
    functions over a finite lattice guarantee termination; the sets are bit
    vectors over a per-function domain, so the join is an OR; and the audit
    re-derives the result by hand for a five-line loop (block entry 2, body 4)
    and compares it with the engine's own `in_atoms`/`out_atoms`.
15. **What about definite assignment?** It is the same framework with
    `OUT[B] = GEN[B] ∪ IN[B]` over must-analysis (intersection at merges) and it
    reports `DFA001` where a read may happen before any assignment.

### Taint analysis

16. **What is a taint atom?** A string such as `src:stdin@command` meaning "data
    introduced by the source rule `stdin` that is dangerous in context
    `command`". Atoms travel with values through assignments, expressions,
    branches, arguments and returns, and a finding lists the atoms that arrived at
    the sink.
17. **Why contexts?** A value can be safe for a shell and unsafe in a SQL
    statement; the same source rule can declare several contexts, and a sink
    demands a specific one. Without contexts every sanitizer would either clear
    everything or nothing.
18. **Sanitizers are context-sensitive — what does that mean here?** A sanitizer
    call clears only the atoms whose context matches its declared contexts, and
    only when the value actually flows through it. `shell_escape` clears the
    shell context and leaves the others; `parse_to_int` clears everything by
    converting to a number.
19. **What happens when the analyser does not know a function?** The call is
    recorded as an unknown external; its return value keeps the taint of its
    arguments and the finding notes that an unknown call sits on the path. Taint
    is never *cleared* by a call the tool does not understand.
20. **How is interprocedural flow handled, and what is the approximation?**
    Each function gets a summary that maps "parameter *i* is tainted in context
    *c*" to "the return value is tainted in context *c*". Call sites apply the
    summary. It is context-insensitive: parameters are summarised across all call
    sites, which can produce flows no single call site creates. Findings that
    cross a function boundary therefore have lower certainty and say so.
21. **Why is there no symbolic execution?** Because it would need path constraints
    and solvers to be sound; instead the engine records the branch conditions on
    a path, marks feasibility as `unconditional`, `guarded`, `conditionally
    infeasible` or `unknown`, and states that the guard was not decided.
22. **Can the tool prove a program safe?** No. A short finding list means no
    configured source-to-sink flow was detected for that file, rule set and
    engine version. The report lists the unsupported constructs and the limits
    that were hit so the reader can see the blind spots.

### Dependencies, slicing and rules

23. **What makes an edge in the dependency graph legitimate?** Each edge has a
    kind and a reason string produced at construction time: a `data` edge exists
    because a definition reaches a read (checked with the reaching-definitions
    result), a `control` edge because the statement is nested in a condition, a
    `call`/`return` edge because the call graph recorded the boundary, and a
    `taint` edge because the taint analysis found the same value at both ends.
    Nothing is inferred from text.
24. **What is a slice, and why is it conservative?** The slice is the set of
    statements that the criterion's value can depend on (backward) or influence
    (forward), computed by traversing the graph and keeping the reasons per step.
    Constructs outside the subset cannot be modelled precisely, so the slice
    includes what it cannot exclude, and the note says it is not guaranteed
    minimal.
25. **What is the rule language, and how is it safe?** A small declarative
    grammar (40 productions) parsed by the same LR machinery: `source`, `sink`,
    `sanitizer`, `validator`, `flow` blocks with attributes. Rules are never
    Python: they are parsed into a data model, checked semantically (unknown
    references, arity, duplicate ids, unreachable flows) and only then handed to
    the engine. There is no `eval`, no `exec`, and the AST scan in the tests fails
    the build if a rule ever tries one.
26. **What does the rule validator reject?** Syntax errors with `line:col`; a flow
    that names an unknown source or sink (`RULE020`/`RULE021`); a sanitizer
    declared on a flow without a matching context; a source that declares both
    `returns` and `argument`; and injection attempts such as an embedded Python
    call or a `__import__` in an attribute, which are syntax errors rather than
    something to interpret.
27. **A rule set with one error — what happens?** The whole set is rejected; the
    analysis runs with the built-in rules only (or with none, if built-ins were
    disabled) and the API returns the diagnostics. Partial rule sets would make
    the result state-dependent.

### API, security and evaluation

28. **What is the API surface?** 21 declared endpoints under `/api`: metadata
    (health, schemas, language, grammar, rules, examples), analysis (`analyze`),
    run retrieval (`run`, `findings`, `finding`, `ast`, `cfg`, `dataflow`,
    `statements`, `graph`, `slice`, `report`), rule validation, and `compare`.
    Every one is declared in `codetrace/api/schemas.py` and mirrored on the
    Documentation page; the interface may only call those, which the audit checks.
29. **How is the tool itself protected from the code it analyses?** Source is
    data: it is never written to disk, never imported and never executed (the
    audit drives an analysis with a canary string that would create a file if
    anything executed it, and checks that no file appears). Requests are validated
    (size caps, filename without separators, integer ids, enumerated parameters),
    static files are served through a traversal guard, and errors never include
    server paths or stack traces.
30. **What are the limits, and what happens when one is hit?** Body 1.1 MB, source
    and rule files 512 KiB, statement ids below 2000, graphs limited to 4000
    nodes/edges, bounded worklist iterations and parser recovery steps, and a step
    budget for the analysis. Hitting one sets `limits_hit`, marks the run partial
    and returns what was analysed up to that point; it never silently pretends the
    result is complete.
31. **How was the evaluation corpus built?** 33 files, each with a comment header
    stating the expected result, grouped as vulnerable (14 with findings), safe,
    sanitized, unsupported (3), syntax-error (3) and one custom-rule case; the
    labels are in `evaluation/expectations.json` and describe rule, category,
    severity, sink statement text and source rule. It is deliberately separate
    from the unit tests so it can measure the tool rather than test its
    implementation.
32. **What do precision = recall = F1 = 1.0 mean here, and what do they not
    mean?** They mean that on those 33 files, every expected finding was reported
    (17/17), every reported finding was expected (0 false positives) and the
    diagnostic expectations matched. They say nothing about other code: the corpus
    is small, hand-written, drawn from the same language subset, and the negative
    cases are the tool's own challenge cases. The README and `docs/EVALUATION.md`
    say this explicitly.
33. **What is the biggest limitation?** The interprocedural model is
    context-insensitive and the language subset is small: no pointers, no structs,
    no dynamic dispatch, and nothing that is not modelled is analysed. Both are
    documented per finding and per report rather than hidden.
34. **What would you do next?** First, path-sensitivity for the guards that are
    currently only recorded; second, a context-sensitive interprocedural summary
    (call-site sensitivity with a bounded depth); third, extend the subset with
    structs and arrays of known size; fourth, incremental analysis so a saved run
    can be re-analysed after a one-function edit instead of from scratch.

## 5. Questions to expect about honesty

- *"Did you test your own tests?"* Every test that asserts a number also prints
  the observed value on failure; the audit re-derives the hand-checked data-flow
  results independently of the suite; and two tests failed during development
  because the documentation drifted from the implementation, which is why the
  audit now checks that every file the documents reference exists.
- *"Is the app complete?"* Nine pages, 21 endpoints, no dead controls: each
  navigation target has a section, and the audit checks that the page served
  contains them and that the interface only calls declared endpoints.
- *"Can I see a failure?"* Yes: `examples/syntax_errors/*.ctc` produce located
  diagnostics and a run that is explicitly not accepted; `unsupported/*.ctc`
  produce the unsupported-construct diagnostics and a partial analysis; and both
  are visible in the interface and in the HTML report.
