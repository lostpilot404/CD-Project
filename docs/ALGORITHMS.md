# Algorithms, pseudocode and complexity

Every algorithm below is the one that runs in this checkout. Complexity is given
in terms of `n` = source characters, `t` = tokens, `P` = grammar productions,
`B` = basic blocks of a function, `E` = CFG edges, `A` = lattice atoms of an
analysis, `S` = statements, `w` = machine words in a bitset (`ceil(A/30)` for
CPython's small-int digits). "Measured" numbers come from this environment
(Python 3.11.2, engine 1.0.0) and are reproducible with
`evaluation/run_evaluation.py`.

---

## 1. Lexer — maximal munch

```
scan(source):
    i := 0
    while i < len(source):
        skip whitespace and comments, keeping line/col
        start := i; line, col := current position
        for each pattern in {3-char operators, 2-char operators, single chars,
                             number, identifier, string, character}:
            if pattern matches at i: emit token(kind, text, offset, line, col); break
        if nothing matched: record LEX008; i := i + 1     # never stall
```

* **Complexity:** O(n) time, O(1) extra space (tokens are appended to a list).
* **Why this order:** longest match wins, so `<=` is one token and `+=` is one
  token; identifiers are checked before keywords and keywords by table lookup.
* **Diagnostics never abort the scan** — a bad escape or unsupported operator is
  recorded and scanning continues, so one mistake does not hide the rest.
* Measured: the 33 corpus files lex in well under a millisecond each
  (0.08–0.25 ms, median ≈ 0.13 ms).

## 2. NULLABLE / FIRST / FOLLOW fixpoints

```
nullable := { A | A → ε };  repeat until stable:
    for each A → X1…Xn: if all Xi ∈ nullable then add A

first[X] := {X} for terminals;  ∅ for non-terminals
repeat until stable:
    for each A → X1…Xn:
        for i in 1..n:
            first[A] ⊇ first[Xi]
            if Xi ∉ nullable: break            # stop at the first non-nullable

follow[S'] := {$end}
repeat until stable:
    for each A → X1…Xn, scanning right to left with trailer := follow[A]:
        if Xi is a non-terminal:
            follow[Xi] ⊇ trailer
            trailer := first[Xi] ∪ (trailer if Xi nullable else ∅)
        else:
            trailer := {Xi}
```

* **Complexity:** naive fixpoint iteration is O(P · |G|) per sweep; with
  `|G| = 102` productions and 51 terminals the shipped grammar converges in a
  handful of sweeps (measured: canonical automaton built in ≈ 0.5 s, LALR tables
  in ≈ 0.3 s).
* **Correctness detail:** every right-hand-side symbol is stored in one symbol
  namespace during construction and the non-terminals are subtracted in
  `finalize()`, so FIRST/FOLLOW and ACTION contain only terminals.

## 3. Canonical LR(1) collection

```
closure(I):
    J := I
    worklist := I
    while worklist:
        [A → α · B β, a] := pop(worklist)
        for b in first(β a):                       # β nullable-aware
            for each production B → γ:
                if [B → γ · , b] ∉ J: add to J and worklist
    return J

goto(I, X) := closure({ [A → α X · β, a] | [A → α · X β, a] ∈ I })

canonical():
    C := { closure({[S' → · S, $end]}) };  worklist := C
    while worklist:
        I := pop(worklist)
        for each symbol X after a dot in I:
            J := goto(I, X)
            if J ∉ C: C := C ∪ {J}; push(J)
            transitions[(I, X)] := J
```

* **Complexity:** O(|C| · |P| · |items per closure|) with hashing for set
  membership; item sets are `frozenset`s so deduplication is exact.
* **Measured:** 656 canonical states, 1027 transitions, 1832 items in total,
  largest state 76 items.
* **Safeguard:** `max_states = 2500` raises an error rather than exhausting
  memory on a pathological future grammar.

## 4. LALR(1) merging

```
merge(lr0_states, canonical_states):
    for each canonical state I:
        J := the LR(0) state whose item set equals {(p, d) | (p, d, a) ∈ I}
        for each (p, d, a) ∈ I:  lookaheads[J][(p, d)] ⊇ {a}
```

* **Complexity:** O(|C| · items) with a dict keyed by the LR(0) item set.
* **Measured:** 656 canonical states → 167 LALR states (3.93 : 1), 0 conflicts
  introduced by merging.
* **Trade-off:** merging can create reduce/reduce conflicts. The builder records
  them instead of hiding them (`Conflict.to_json(grammar)` names both actions and
  the resolution applied).

## 5. ACTION/GOTO table construction

```
for each state i:
    for each item [A → α · a β] with a terminal:  ACTION[i, a] := shift goto(i, a)
    for each item [A → α ·] :
        for a in LA(i, A → α):                    # FOLLOW(A) for SLR
            ACTION[i, a] := reduce A → α
    if [S' → S ·] ∈ i: ACTION[i, $end] := accept
    for each non-terminal A: GOTO[i, A] := goto(i, A)
    on collision: record Conflict(...) and resolve: shift > reduce,
                  lower-numbered production > higher-numbered
```

* **Complexity:** O(states · (terminals + reduces · lookaheads)) — measured
  2172 ACTION entries and 382 GOTO entries for 167 states and 51 terminals.
* **Determinism:** the iteration order is the production order, so two builds in
  one process (or in two processes with the same Python version) produce
  identical tables.

## 6. LR parsing

```
parse(tokens):
    stack := [0];  i := 0
    loop:
        action := ACTION[stack.top, tokens[i].kind]
        if action is shift j:   stack.push(j); i := i + 1
        elif action is reduce A → α:
            pop |α| states; stack.push(GOTO[stack.top, A]); build node from |α| values
        elif action is accept:  return tree, accepted = true
        else: i := recover(stack, i)            # see §7
    limits: MAX_STEPS (SYN010), MAX_SYNTAX_ERRORS (SYN011)
```

* **Complexity:** O(t) table lookups plus one reduction per production instance;
  total work is linear in the token count, with a worst-case O(t) stack.
* **Measured:** tokenising and parsing a 60-byte example takes ≈ 0.35 ms in
  total; parsing dominates lexing by roughly 2–3×.

## 7. Error recovery (viable prefix + sync tokens)

```
recover(stack, i):
    report SYN001 with the expected token list
    while i < len(tokens):
        if any state on stack can shift tokens[i]:     # viable-prefix recovery
            unwind the stack to that state; return i
        if tokens[i].kind in SYNC (SEMI, RBRACE) or tokens[i] is a statement start:
            return i + 1                               # skip to a statement boundary
        i := i + 1
    return i
```

* **Complexity:** O(stack depth + skipped tokens) per error, and the routine
  always returns a strictly greater index so the parse makes progress (a fixed
  defect in early iterations).
* **Reporting:** the number of syntax errors, the token that failed, the
  expected set and the recovered statement spans are all in the diagnostics and
  the run's `partial_reasons`.

## 8. Semantic analysis (attribute evaluation)

```
analyse(ast):
    push scope
    walk(ast):
        on VarDecl:      lookup-in-current-scope → SEM002 on duplicates
                         shadowing of an outer scope → SEM018 (warning)
                         allocate Symbol(id, name, type, scope, line, col)
        on Ident:        lookup outward through the scope chain → SEM001 if absent
        on Call:         resolve declared function, else rule-declared external,
                         else SEM008 (unknown external, result assumed to depend
                         on its arguments)
        on Assign/Return/op: type rules → SEM004/005/016/101/102
        on entering a block/function: push scope; record scope_id and depth
    pop scope
```

* **Complexity:** O(ast nodes · scope depth) with dict lookups per scope.
* **Symbol identity:** ids are allocated in declaration order, so the same name
  in two scopes yields two ids and never conflates two variables.
* **Measured:** semantic analysis of a 60-byte example is ≈ 0.09 ms.

## 9. CFG construction

```
build(function):
    entry := new block; current := entry
    for each statement in order:
        current.add(statement)
        if statement is if/while/for:
            create condition/header/body/merge blocks
            add typed edges: true/false/loop-back/break/continue/return/exit
            recurse into the bodies with the correct `continue`/`break` targets
    connect the exit; compute reachability by BFS from the entry
    unreachable blocks → CFG001 and metrics["unreachable_blocks"]
```

* **Complexity:** O(S) blocks and edges with an amortised O(1) per statement;
  loops are identified by the back edges recorded during construction.
* **Measured:** the loop example from §10 yields 5 blocks, 5 edges, 1 loop, 0
  unreachable blocks.

## 10. Worklist data-flow solver

```
solve(problem, max_iterations, max_steps):
    for B in blocks: IN[B] := initial(B); OUT[B] := ⊥
    IN[boundary] := boundary_value
    worklist := order(problem)                     # RPO for forward problems
    while worklist:
        B := pop(worklist)
        IN := meet(OUT[P] for P in predecessors(B))   # successors for backward
        OUT := transfer(B, IN)
        if OUT changed: push each neighbour not already queued
        if iterations > max_iterations or steps > max_steps: converged := false
```

* **Complexity:** for a bit-vector lattice, each block's value can grow at most
  `A` times, and each growth re-evaluates its neighbours, so the number of
  transfer evaluations is O(A · E); with word-parallel bitsets each evaluation
  costs O(w) machine words → O(A · E · w). In practice: that loop needs
  **10** iterations for reaching definitions and **6** for liveness on 5 blocks.
* **Why a worklist:** sparse updates beat round-robin sweeps — most blocks are
  stable after the first pass, and the solver reports `processed_order`,
  `iterations`, `steps` and `blocks_with_changes` as evidence.

## 11. Reaching definitions and live variables

```
ReachingDefinitions (forward, union):
    GEN[B] := definitions created in B, minus those killed later in B
    KILL[B] := definitions of the same symbol elsewhere
    OUT[B] := GEN[B] | (IN[B] & ~KILL[B])
    IN[B]  := ∪ OUT[P]                       # bitsets: | over predecessors

Liveness (backward, union):
    USE[B] := symbols read before any write in B
    DEF[B] := symbols written in B
    IN[B]  := USE[B] | (OUT[B] & ~DEF[B])
    OUT[B] := ∪ IN[S]                        # bitsets: | over successors
```

* **Complexity:** as §10. Domains are bit vectors over `d<id>` / `s<id>:<name>`
  atoms, so meet and transfer are one or two integer operations each.
* **Measured:** the loop example converges in 10 and 6 iterations respectively,
  the same sets a hand calculation gives.

## 12. Definite assignment (*must* analysis)

```
    OUT[B] := GEN[B] | (IN[B] & ~KILL[B])
    IN[B]  := ⋂ OUT[P]                       # bitsets: & over predecessors
    IN[entry] := ∅ ; initial value for all other blocks := ⊤ (all assigned)
    uninitialised reads := reads of v at s with v ∉ IN[s] and no definition of v
                           earlier in the same block
```

The asymmetry is what makes this a *must* analysis rather than a *may* one: an
intersection meet can only lose facts, so the iteration starts at "everything is
assigned" and is refined downwards, while the entry keeps an empty fact because
nothing is assigned before the program starts. Seeding the other blocks with ∅
instead lets a loop header lose a fact that its back edge has not yet
established, which turns into a `DFA001` false positive. Measured: with ∅
seeding, the loop body `for (int i = 0; i < 3; i++) { if (i == 1) { continue; }
n = n + i; }` over a variable assigned before the loop yields two `DFA001` false
positives (at the read inside the loop and at `return n;`); with ⊤ seeding it
yields none. `MustAnalysisInitialisationTests` pins the same contract on a
nested loop whose inner header has two back edges.

* **Complexity:** as §10; the intersection meet means values only shrink, which
  bounds the iterations the same way.
* **Measured:** for `int a; int b = a + 1;` the read of `a` at `1:21` is reported
  with `DFA001` and the per-statement states `{} → {}`, `{} → {s3:b}`,
  `{s3:b} → {s3:b}`.

## 13. Interprocedural taint analysis

```
summaries(function f):
    symbolic run over the body with parameters as symbolic atoms:
        param j of f      → {atoms that reach the return value}
        return statement  → union of the atoms of its expression
    fixpoint over the call graph:
        repeat until no summary changes, with a visited set for recursion

replay(main):
    start with the atoms of the source rules
    evaluate statements in call order, using the summaries of callees:
        assignment      : atoms(rhs) (killed for the symbol, unioned for others)
        call f(args)    : union of arg atoms for parameter positions of f
                          + summary atoms for the return value
                          + taint of previously tainted globals passed in
        branch guard    : prune the edge when a validator/sanitizer guards the
                          condition, or the literal is false; otherwise keep the
                          edge and record the condition as `guarded`
        unknown call    : result := union of argument atoms (never "safe"),
                          path step kind `unknown-call`, certainty approximate
    hits := (sink rule, argument index, atom) triples whose contexts match
```

* **Complexity:** summaries cost O(functions · statements · atoms); the fixpoint
  is bounded by the height of the atom lattice times the number of call edges;
  the replay is O(statements · atoms) with bitset-free atom sets (atom counts are
  small: the built-in set has 5 source rules and 6 contexts, so ≤ 30 atoms).
* **Termination:** recursion is handled by the visited set plus per-call depth
  limits; the recursive corpus case converges and is reported as *approximate*
  with the call-site limitation attached.
* **Measured:** taint is the second most expensive phase after parsing
  (≈ 0.4 ms for a 60-byte example, ≈ 32 ms per corpus file end to end).
* **Recorded guard suppressions:** after the fixpoint, every edge that a
  validator guard pruned is inspected (`_guard_suppression_report`). An edge
  whose pruning actually removed atoms from the block's `IN` set is recorded in
  `guard_suppressions` with the symbol, context, validator rule, source
  position, edge role and the atoms it removed. Reporting matches each record
  against the sink calls in its function *by symbol id* (`statement_accesses`),
  so a guard on an unrelated variable is never blamed for an unreported sink.
  The report's `summary.dispositions.validator_guards` and the run's
  `limitations` entry are built from that match, not from the raw record count.

## 14. Dependency graph construction

```
build_graph(program):
    for each function, for each statement s:
        add statement node s<sid>; add definition node d<defid> for each definition
        add define edge s<sid> → d<defid>
        for each symbol read at s:                     # def-use via §11
            for d in definitions_reaching(IN[s], symbol): add data edge d → s
        for each condition that controls s: add control edge condition → s
        for each call: add call edge s<sid> → f:callee, return edge callee → s
        for each reported flow: add taint edges (with atoms) and a source-to-sink edge
    verify each data/taint edge against the reaching definitions (assert-free check)
```

* **Complexity:** O(S · atoms) for the def-use lookup (bitset membership is O(1))
  plus O(S) for control edges from an AST walk.
* **Measured:** 3–13 nodes and 1–19 edges across the 30 analysable corpus files
  (largest: `interprocedural/recursion.ctc`).  The count includes the
  `source-to-sink` edges of the reported flows, so a file that reports a
  finding carries more edges than its data/control graph alone. Every
  intra-procedural data and taint edge names the reaching definition that
  justifies it.

## 15. Slicing

```
backward(criterion):
    frontier := {criterion}; slice := ∅
    while frontier:
        s := pop(frontier)
        for each incoming data/control/call/taint/define edge e → s:
            slice.add(e.src, reason = e.reason)
            if e.src not in seen: push(frontier, e.src)
    close over the definition nodes referenced by the slice   # subgraph payload
```

* **Complexity:** O(|V| + |E|) for the induced subgraph, with caps
  `MAX_STATEMENTS = 5000` / `MAX_EDGES = 500` that set `truncated` instead of
  growing without bound.
* **Measured (hand-verified):** `backward(5) = [0, 2, 5]`, `forward(1) = [1, 3, 4]`
  on the program in `docs/COMPILER_THEORY.md` §18.

## 16. Finding construction and explanation

```
for each TaintHit:
    id := "F" + sha256(rule | sink function | sink rule | argument |
                       sorted(source rules) | normalised sink text)[:12]
    path := explainer_trace(hit)     # candidates ranked by (has source step, length)
    certainty := confirmed  (straight-line, intraprocedural, no unresolved step)
               | approximate (guarded, interprocedural, unknown call, recursion)
               | unproven    (no source step could be traced to a configured source)
```

* **Complexity:** O(hits · path length · candidates) time; the explainer keeps a
  visited set per trace so cycles (recursion) terminate.
* **Determinism:** findings are sorted by
  `(severity rank, certainty rank, line, column)` and the id is a pure function
  of the analysis result, so the same source and rule set give the same ids and
  the same order.

## 17. Run comparison

```
compare(before, after):
    by_id_before := {id: finding}; by_id_after := {id: finding}
    new        := ids only in after
    resolved   := ids only in before
    moved      := ids in both whose (line, col) differ
    persistent := ids in both with the same (line, col)
```

* **Complexity:** O(|before| + |after|) with hash lookups; identity is
  line-independent by construction (`docs/COMPILER_THEORY.md` §19).
* **Measured:** inserting a blank line reports 1 *moved*; replacing the tainted
  value with a sanitiser reports 1 *resolved* and 0 *new*.

---

## Complexity at a glance

| Phase | Time | Measured on a 55-byte example (median of 25 runs) |
| --- | --- | --- |
| Lexing | O(n) | 0.10 ms (0.09–0.16) |
| LR parsing | O(t) | 0.49 ms (0.35–0.68) |
| Parser tables (cached) | O(states · P) per process | 0.98 ms on the first analysis in a process, ~0 after |
| Semantics | O(nodes · depth) | 0.08 ms (0.07–0.13) |
| CFG | O(S) | 0.08 ms (0.07–0.12) |
| Reaching definitions + liveness (+ definite assignment) | O(A · E · w) | 0.18 ms (0.16–0.27) |
| Taint (summaries + replay) | O(functions · S · atoms) | 0.48 ms (0.45–0.63) |
| Dependency graph | O(S · atoms) | 0.06 ms (0.05–0.08) |
| Slicing (per query) | O(V + E) | 0.001 ms setup |
| Findings + explanations | O(hits · path) | 0.32 ms (0.24–0.50) |

Whole corpus: 33 files in **≈1.2 s** end to end (≈ 36 ms/file, including rule
loading, JSON serialisation and metric collection) on this machine. Numbers are
reported per run in `metrics.timings`; the report does not claim better
performance than it measures, and every timing is wall-clock in this environment
(Python 3.11.2), not a synthetic benchmark.
