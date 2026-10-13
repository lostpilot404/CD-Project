# Compiler theory in CodeTrace

This document explains every compiler concept the project is built on, why it is
needed here, how it is implemented, the equations it follows, and a worked
example with the intermediate results the implementation really produces. Every
number quoted below was printed from this checkout (engine 1.0.0, Python 3.11.2);
every claim points at the file and the test that pins it.

| Concept | Section | Implementation |
| --- | --- | --- |
| Lexical analysis | §1 | `codetrace/frontend/lexer.py` |
| Context-free grammars, NULLABLE/FIRST/FOLLOW | §2 | `codetrace/frontend/grammar.py` |
| LR(1) items, closure, GOTO | §3 | `Grammar.closure`, `Grammar.goto` |
| Canonical LR(1) collection | §4 | `build_canonical_lr1_automaton` |
| LALR(1) merging | §5 | `merge_lalr_states` |
| SLR(1) | §6 | `build_lr0_automaton` + FOLLOW |
| ACTION/GOTO tables, conflicts | §7 | `codetrace/frontend/clr_parser.py` |
| LR parsing + error recovery | §8 | `CLRParser.parse` |
| Syntax-directed translation → AST | §9 | `codetrace/frontend/ast_nodes.py` |
| Attribute grammars, symbol tables, types | §10 | `codetrace/semantics/` |
| Control-flow graphs | §11 | `codetrace/analysis/cfg.py` |
| Data-flow framework | §12 | `codetrace/analysis/dataflow.py` |
| Reaching definitions | §13 | `codetrace/analysis/reaching_definitions.py` |
| Live variables | §14 | `codetrace/analysis/liveness.py` |
| Definite assignment | §15 | `codetrace/analysis/definite_assignment.py` |
| Interprocedural taint analysis | §16 | `codetrace/analysis/taint.py` |
| Program dependency graph | §17 | `codetrace/analysis/dependencies.py` |
| Program slicing | §18 | `codetrace/analysis/slicing.py` |
| Stable identity and run comparison | §19 | `codetrace/findings/models.py` |

---

## §1 Lexical analysis

**Definition.** A lexer turns a character stream into the longest-match tokens of
a regular language, attaching a source location to each token.

**Why here.** Every later phase reports positions in the original file: findings
give `line:col`, the AST carries spans, and the report highlights the source.
The lexer is the only phase that knows about characters, so it owns offsets.

**How.** A hand-written scanner with **maximal munch** (`lexer.py`,
`Lexer._scan_token`): at each position the scanner tries the multi-character
operators first, then single characters, then numbers, identifiers, string and
character literals. Comments are consumed but not emitted. Two pieces of state
are carried: `line`/`col` for diagnostics and a monotonically increasing byte
`offset` for slicing and highlighting. A `LineIndex` maps an offset back to
`(line, column)` for every other phase.

Diagnostics are *non-fatal*: the lexer records `LEX001`–`LEX008` and `LEX100`–
`LEX102` and continues at the next character it can classify, so one bad escape
does not hide the rest of the file.

**Worked example.** Input `string cmd = input(); // note` produces (kind, lexeme,
offset) pairs:

```
KW_STRING  'string'  [0,6)      IDENT 'cmd' [7,10)     ASSIGN '=' [11,12)
IDENT      'input'   [13,18)    LPAREN '(' [18,19)     RPAREN ')' [19,20)
SEMI       ';'       [20,21)    EOF    '' [31,31)
```

The trailing comment produces no token, and `EOF` has `offset = len(source)`.
Diagnostics from `LEX100`–`LEX102` carry the *keyword* span, e.g. `switch` at
`1:14` in `examples/unsupported/switch_statement.ctc`.

**Implementation / tests / limits.** `codetrace/frontend/lexer.py`;
`tests/test_lexer.py` (19 tests: token kinds, offsets, comments, literals,
invalid characters, unterminated literals, unsupported keywords).
Limit: regular languages cannot count nesting — that is the parser's job.

---

## §2 Context-free grammars, NULLABLE, FIRST, FOLLOW

**Definition.** A context-free grammar is `G = (N, T, P, S)`. `NULLABLE`, `FIRST`
and `FOLLOW` are the three sets every LR construction needs.

**Why here.** FIRST decides which tokens may *start* a production, so shift
actions can be built; FOLLOW gives the SLR lookahead set; NULLABLE makes the
empty productions of `decl_list -> ε`, `stmt_list -> ε`, `args_opt -> ε`,
`params_opt -> ε`, `expr_opt -> ε` legal.

**How (fixpoint equations).**

```
NULLABLE = least fixpoint of:
    A ∈ NULLABLE        if A → ε
    A ∈ NULLABLE        if A → X1 … Xn and Xi ∈ NULLABLE for all i

FIRST(A) = least fixpoint of:
    FIRST(A) ⊇ FIRST(X1)
    FIRST(A) ⊇ FIRST(X2)                if X1 ∈ NULLABLE
    ...
    FIRST(A) ⊇ FIRST(Xk)                if X1 … X(k-1) ∈ NULLABLE

FOLLOW(A) = least fixpoint of:
    $end ∈ FOLLOW(S')
    FIRST(β) − {ε} ⊆ FOLLOW(B)          for A → α B β
    FOLLOW(A) ⊆ FOLLOW(B)               for A → α B β with β ∈ NULLABLE*
```

`first_of_sequence(α)` implements the nullable-aware union:
`FIRST(X1) ∪ (FIRST(X2) if X1 nullable) ∪ …` and returns `(set, nullable)`.

**Worked example (real values from the shipped grammar).**

```
NULLABLE     = {program', program, decl_list, stmt_list, params_opt, args_opt, expr_opt}
FIRST(expr)  = {IDENT, INT_LIT, FLOAT_LIT, STRING_LIT, CHAR_LIT, KW_TRUE, KW_FALSE,
                LPAREN, MINUS, NOT, INCR, DECR}
FOLLOW(expr) = {SEMI, RPAREN, RBRACKET, COMMA}
FOLLOW(stmt_list) has 27 terminals, including RBRACE and every statement keyword
```

`program` is nullable because `decl_list` is: an empty translation unit is a
legal program (the test `test_empty_input_parses_as_an_empty_translation_unit`
pins that, and `SEM020` *reports* that there is no `main`).

**Terminals and non-terminals are disjoint.** `Grammar.finalize()` computes the
terminal set as "right-hand-side symbols that are never left-hand sides", and
subtracts the non-terminals that were provisionally recorded while productions
were added. Without that subtraction FOLLOW sets contain non-terminals and the
ACTION table gains entries no token can match; `test_terminals_and_nonterminals_
are_disjoint` and `test_action_table_is_keyed_by_token_kinds` guard the invariant.

**Implementation / tests / limits.** `codetrace/frontend/grammar.py`;
`tests/test_parser.py::GrammarConstructionTests`. Limitation: the grammar is not
LL(k) — `else` binds to the nearest `if` and the layered expression productions
need one token of lookahead, which is exactly why LR is used.

---

## §3 LR(1) items, closure, GOTO

**Definition.** An LR(1) item is `[A → α · β, a]`: "we have derived `α` and
expect to see `β`, and after reducing `A → αβ` the next token may be `a`".

**Why here.** The item set is the state of the automaton; the closure operation
is what makes one state "know" all the productions it may start.

**How.**

```
closure(I) = smallest set J ⊇ I with:
    if [A → α · B β, a] ∈ J and B → γ ∈ P
    then [B → γ · , b] ∈ J for every b ∈ FIRST(βa)

GOTO(I, X) = closure({ [A → α X · β, a] | [A → α · X β, a] ∈ I })
```

Terminal lookaheads and non-terminal transitions are handled separately: GOTO is
defined for both terminals and non-terminals, closure only expands non-terminals.

**Worked example.** The start item `[program' → · program, $end]` has closure

```
[program'  → · program,      $end]      [program    → · decl_list,      $end]
[decl_list → · decl_list decl, $end]    [decl_list  → · ,              $end]
```

Four items — `decl_list` is nullable, so `decl_list → ·` is in the closure and
no production of `decl` is needed yet. Item sets are stored as `frozenset`s, so
duplicate items cannot appear (`test_item_sets_are_deduplicated`).

**Implementation / tests / limits.** `Grammar.closure`, `Grammar.goto`;
`tests/test_parser.py`. Limit: closure is computed per construction step, so a
much larger grammar would want the kernel-item representation used by LALR.

---

## §4 Canonical LR(1) collection

**Definition.** The canonical collection is the least set of item sets closed
under `closure` and `GOTO` starting from `closure({[S' → · S, $end]})`.

**Why here.** It is the reference construction: it accepts exactly the LR(1)
languages, and every other mode in this project is compared against it (LALR may
introduce reduce/reduce conflicts by merging; canonical cannot).

**How.** Worklist construction with a hash of each item set for dedup
(`build_canonical_lr1_automaton`). A safety valve (`max_states = 2500`) raises a
`GrammarError` instead of consuming memory forever if a future grammar explodes.

**Worked example (measured).**

```
mode      states  transitions  items_total  items_max  terminals  nonterminals
canonical  656       1027          1832         76          51           36
```

State 0 holds 16 LR(1) items (the same four LR(0) items, each with the several
lookaheads `FIRST` can produce from that context).

**Implementation / tests / limits.** `build_canonical_lr1_automaton`;
`tests/test_parser.py::test_canonical_lr1_has_more_states_than_lalr`.
Limit: 656 states for this grammar is 3.9× the LALR size — the table cost is the
classic reason to prefer LALR in production compilers.

---

## §5 LALR(1): merging canonical states by kernel

**Definition.** LALR(1) merges canonical LR(1) states that have the same LR(0)
kernel; the lookahead sets of the merged items are **unioned**.

**Why here.** It keeps the LR(0) state count (167 instead of 656) with almost
all the power of LR(1) — and it gives the project something honest to say about
conflicts: merging can *introduce* reduce/reduce conflicts, and this
implementation reports them rather than hiding them.

**How.**

```
LR0(I)     = { (p, d) | (p, d, a) ∈ I }
merge(I)   = the LR(0) state whose item set equals LR0(I)
LA[J, i]   = ∪ { lookaheads of i over all canonical states merged into J }
```

**Worked example (measured).**

```
canonical states     656
LALR merged states   167      -> merge ratio 3.93 : 1
reduce/reduce conflicts introduced by merging   0
```

**Implementation / tests / limits.** `merge_lalr_states`;
`test_canonical_lr1_has_more_states_than_lalr` asserts `canonical > lalr` and
that both have zero conflicts. Limit: LALR cannot be more powerful than
canonical LR(1); a grammar needing that power must use `mode="canonical"`
(`GET /api/grammar?mode=canonical`, and the *Grammar* panel in the UI).

---

## §6 SLR(1)

**Definition.** SLR(1) uses LR(0) item sets and the *global* `FOLLOW(A)` as the
lookahead for reducing with `A → α`.

**Why here.** It is the cheapest construction and a fair baseline: the project
shows it working on this grammar (167 states, 0 conflicts) and can demonstrate
on a deliberately ambiguous grammar that the extra power of LR(1) lookaheads
matters.

**How.** Same LR(0) automaton as LALR; the table builder substitutes
`LA(I, A → α) = FOLLOW(A)`.

**Worked example (measured).** `slr` mode: 167 states, 0 conflicts, 2172 ACTION
entries — identical to LALR here, because CT-C subset v1 happens to be SLR(1).
`tests/test_parser.py` builds an ambiguous expression grammar and asserts the
conflict *is reported*, which is the honest way to demonstrate the difference.

**Implementation / tests / limits.** `build_lr0_automaton` + the `slr` branch of
`build_tables`. Limit: SLR resolves less than LR(1); the project therefore ships
LALR as the default (`mode="lalr"`) and keeps canonical available for study.

---

## §7 ACTION/GOTO tables and conflict reporting

**Definition.** `ACTION[i, a]` is shift / reduce / accept / error, `GOTO[i, A]`
is the successor state for a non-terminal.

**Why here.** The table is the artifact that makes the parser *table-driven*:
`GET /api/grammar` exposes it, the UI can show the automaton statistics, and
conflicts are first-class data instead of a crash.

**How.**

```
ACTION[i, a] = shift j        if [A → α · a β] ∈ I_i and GOTO(I_i, a) = I_j
ACTION[i, a] = reduce A → α   if [A → α ·] ∈ I_i and a ∈ LA(I_i, A → α)
ACTION[i, $end] = accept      if [S' → S ·] ∈ I_i
GOTO[i, A]  = j               if GOTO(I_i, A) = I_j
```

On a collision the builder records a `Conflict(kind, state, terminal, existing,
incoming, resolved, reason)` and applies a documented resolution: **shift over
reduce**, **lower-numbered production over higher**. Nothing is dropped
silently; `len(tables.conflicts)` is 0 for every shipped mode and is reported by
`GET /api/health` and `/api/grammar`.

**Worked example (real table row).** State 2 of the LALR automaton holds

```
[program     → decl_list ·]                 [decl_list → decl_list · decl]
[... 10 closure items for decl, type, function_decl, var_decl ...]
```

and its action row is

```
ACTION[2, $end]      = reduce program → decl_list       (production 1)
ACTION[2, KW_INT]    = shift 6        ACTION[2, KW_BOOL]  = shift 9
ACTION[2, KW_CHAR]   = shift 3        ACTION[2, KW_FLOAT] = shift 12
ACTION[2, KW_STRING] = shift 10       ACTION[2, KW_VOID]  = shift 4
```

Read it as: "a declaration list is complete when the input ends; otherwise the
next type keyword starts another declaration".

**Implementation / tests / limits.** `codetrace/frontend/clr_parser.py`;
`test_action_goto_tables_are_consistent`, `test_tables_are_deterministic`,
`test_deliberate_conflict_is_detected_not_hidden`, `test_no_conflicts_in_the_
shipped_modes`. Limit: table size is `states × terminals`; at 167 × 51 ≈ 8.5k
entries this is trivial, and `items_max = 76` shows the states stay small.

---

## §8 LR parsing and error recovery

**Definition.** Shift-reduce parsing with an explicit stack of states.

**Why here.** It is the phase that consumes the table and produces the AST, and
it owns the parser diagnostics `SYN001`, `SYN010`, `SYN011`, `SYN100`.

**How.** The loop is the standard one:

```
push 0
for each token a:
    while ACTION[top, a] = reduce A → α:
        pop |α| states; push GOTO[top, A]
    if ACTION[top, a] = shift j:    push j; advance
    elif ACTION[top, a] = accept:   stop, return the tree
    else:                           error recovery
```

Error recovery has three parts, in order:

1. **Viable-prefix recovery** (`_report_and_recover`): if any state on the stack
   can shift the offending token, unwind to it and continue — the classic
   "discard until a shift is possible".
2. **Sync-token skipping**: otherwise skip tokens until one that can follow the
   current statement (typically `;` or `}`), then continue. The routine returns
   the *new position* so recovery always makes progress (a fixed bug: without
   that, identical errors repeated forever).
3. **Limits**: at most `MAX_SYNTAX_ERRORS` diagnostics, and a step limit
   `SYN010`/`SYN011`. When a limit is hit the parse is marked partial and the
   report says so in `summary.partial_reasons`.

**Worked example.** `int main() { int a = ; return 0; }` yields exactly one
`SYN001` at the `;` with `expected: IDENT, INT_LIT, …` and the parser recovers to
parse the `return`; `examples/syntax_errors/*.ctc` are the labelled corpus cases
for this. A `switch` keyword produces `LEX100` + `SYN100` and the statement is
skipped, never silently ignored.

**Implementation / tests / limits.** `CLRParser.parse`;
`tests/test_parser.py::ParserDiagnosticTests`. Limit: recovery is heuristic — the
report states which statements were skipped rather than pretending the file
parsed.

---

## §9 Syntax-directed translation: spans and the AST

**Definition.** Every production carries a *builder* that assembles its node from
the children's semantic values; the result is an abstract syntax tree.

**Why here.** The AST is the interface to semantics, CFG construction and the
UI's node inspector; each node needs a source range so that every later result
can point back at the file.

**How.** Each production is registered as
`add(lhs, rhs, builder=lambda children, span: …, label="…")`. The builder
receives the children's nodes and the span computed from the first and last
child; `_span_of` falls back to the lookahead token's span for empty
productions. Nodes are dataclasses in `ast_nodes.py` with `line`, `col` and
`span`; the tree is printed as JSON with a depth cap for the API.

**Worked example (real tree, spans are byte offsets).** For
`int main() { string cmd = input(); system(cmd); }` (49 bytes):

```
SourceUnit                       span [0,49)
└── FunctionDecl 'main'           span [0,49)
    └── Block                    span [11,49)
        ├── VarDecl              span [13,34)
        │   └── VarDeclarator 'cmd'  span [20,33)
        │       └── Call 'input'     span [26,33)  resolution=external
        └── ExprStmt             span [35,47)
            └── Call 'system'    span [35,46)  resolution=external
                └── Ident 'cmd'  span [42,45)
```

`resolution` is filled in by the semantic phase: `external` (declared by a rule),
`function` (declared in the file) or `unresolved` (reported as `SEM008`). The
node inspector in the UI shows exactly this shape.

**Implementation / tests / limits.** `codetrace/frontend/ast_nodes.py`;
`test_locations_are_attached_to_every_node`, `test_second_parse_reports_correct_
locations` (the cached-tables bug that once reset every location to line 1).
Limit: the tree is concrete in the sense that parentheses and precedence
structure stay visible through the expression node hierarchy.

---

## §10 Attribute grammars: scopes, symbol tables, types

**Definition.** Semantic analysis computes attributes over the AST: the *type* of
an expression (synthesised), the *symbol* an identifier refers to (inherited
from the enclosing scope), and diagnostics when an attribute is undefined.

**Why here.** Stable symbol identity is the precondition for every data-flow
result: reaching definitions, liveness, taint and the dependency graph all
compare symbol ids. Two different variables called `i` in two scopes must never
be conflated.

**How.** A scope chain (`symbol_table.py`) holds `dict[name → Symbol]` per
scope; entering a block/function pushes a scope, leaving pops it. A `Symbol`
gets a **stable id** in declaration order and records `name`, `type`, `kind`,
`scope_id`, `line`, `col`. Lookup walks outwards and records the scope it found
the symbol in. The analyser then checks:

* `SEM001` undeclared identifier, `SEM002` duplicate declaration in one scope,
  `SEM018` (warning) declaration shadowing an outer one — shadowing is legal but
  reported, and the inner symbol id differs from the outer one;
* `SEM003` function redefinition, `SEM005`/`SEM101` type errors and narrowing
  conversions, `SEM016` return value mismatch, `SEM009`/`SEM010` argument count
  and type mismatch;
* `SEM008` unknown external call, `SEM017` indirect call, `SEM013` indexing a
  non-array, `SEM014` function used as a value, `SEM012` `break`/`continue`
  outside a loop, `SEM020` no `main`.

Externals are resolved through the rule set (`semantics/externals.py`), which is
why `input()`, `system()`, `shell_escape()` parse and type-check without
declarations — and why a function that no rule mentions is reported as an
unknown external instead of being assumed safe.

**Worked example.**

```c
int main() { int i = 1; { string i = "x"; print(i); } return i; }
```

```
scope 0 (global)   symbol #0 'main'   function
scope 1 (main)     symbol #1 'i'      int      declared 1:23
scope 2 (block)    symbol #2 'i'      string   declared 1:39   -> SEM018 shadowing warning
```

The reference inside the block resolves to `#2`, the `return i` to `#1`; the
data-flow and taint results are expressed with those ids, so the two `i`s stay
separate (`tests/test_semantics.py::ScopeTests`).

**Implementation / tests / limits.** `codetrace/semantics/`;
`tests/test_semantics.py` (18 tests). Limit: no user-defined types, no
conversions beyond the documented narrowing rule, no overloading.

---

## §11 Control-flow graphs

**Definition.** A CFG is `(B, E, entry, exit)` where nodes are basic blocks and
edges model possible control transfer.

**Why here.** Every data-flow equation is written over blocks and their
successors; the CFG is also what the UI draws and what "unreachable code" means.

**How.** `CFGBuilder` walks the *structured* AST: `if`/`else` creates a
condition block with a `true` edge to the then-block and a `false` edge to the
else-block, both joining at a merge block; `while` creates a header with `true`
into the body, `false` out, and a **back edge** (`loop-back`) from the body to
the header; `for` adds a setup and a tail block; `break`/`continue` jump to the
loop's after-block/header; `return` targets the exit block. Every edge records a
`kind` (`sequential`, `true`, `false`, `loop-back`, `break`, `continue`,
`return`, `exit`) and a human-readable `label`/`condition`. Reachability is a BFS
from the entry: unreachable blocks are reported (`CFG001`, `cfg.unreachable`) and
`metrics["unreachable_blocks"]` is a real measurement, never a text search.

**Worked example (the loop used throughout §13–§14).**

```
block 0 entry        stmts [a=1, b=2]      succ 0 -sequential-> 2
block 1 exit                               pred 3
block 2 loop-header  stmts [a<3]           succ 2 -true-> 4, 2 -false-> 3   pred 0, 4
block 3 normal       stmts [return b]      succ 3 -return-> 1
block 4 normal       stmts [b=a+b, a=a+1]  succ 4 -loop-back-> 2            pred 2
```

`cfg.stats()`: 5 blocks, 5 edges, 4 definitions, 1 loop, 0 unreachable blocks.

**Implementation / tests / limits.** `codetrace/analysis/cfg.py`;
`tests/test_cfg.py` (15 tests). Limit: the language has no `goto`, so the CFG is
structured by construction; this is documented rather than hidden (it is also
why control dependence can be derived from the AST, see §17).

---

## §12 The data-flow framework

**Definition.** A data-flow analysis is a monotone framework
`(L, ⊑, ⊔, F, D)`: a lattice of values, a meet operator, a family of monotone
transfer functions and a direction. The result is the **least fixpoint** of

```
IN[B]  = ⊔ over predecessors P of OUT[P]           (forward, e.g. reaching defs)
OUT[B] = F_B(IN[B])

OUT[B] = ⊔ over successors S of IN[S]              (backward, e.g. liveness)
IN[B]  = F_B(OUT[B])
```

with the boundary value fixed at entry (forward) or exit (backward).

**Why here.** Reaching definitions, liveness and definite assignment share one
framework, so the worklist algorithm, the iteration accounting and the
convergence guarantees are written once, and the *fixpoint* — not a heuristic
walk — is what the UI and the reports expose.

**How.** `dataflow.py` defines `BitVectorDomain` (an atom list plus a bit per
atom, stored in one Python integer), `DataFlowProblem` (direction, boundary,
initial, meet, transfer, edge transfer, order, predecessor/successor helpers),
`DataFlowResult` (in/out per block, iterations, steps, converged, processed
order, reachable blocks, blocks with changes) and the worklist solver:

```
for each block B: IN[B] := initial value; OUT[B] := ⊥
IN[entry] := boundary
worklist := all blocks in the problem's order
while worklist:
    B := pop(worklist)
    IN  := ⊔ OUT[P] for P in preds(B)        (or OUT[S] for successors)
    OUT := transfer(B, IN)
    if OUT changed: enqueue the neighbours
```

Iteration and step caps (`max_iterations=10_000`, `max_steps=200_000`) turn a
future pathological input into an explicit `converged=False` with a reason
instead of a hang. Because bitsets are Python integers, meet and transfer are
single word-parallel operations (`|`, `& ~`), which is the standard optimisation
for bit-vector problems.

**Worked example.** The loop of §11 converges after **10 iterations** for
reaching definitions and **6** for live variables; the iteration counts are
reported per run in `metrics["dataflow_iterations"]` and per function in the
`/dataflow` payload.

**Implementation / tests / limits.** `codetrace/analysis/dataflow.py`,
`tests/test_dataflow.py` (20 tests, including hand-computed fixpoints and the
iteration cap). Limit: the framework is intra-procedural — the interprocedural
part is the taint layer (§16) — and the domain is finite and atom-based, so it
cannot express value-dependent facts.

---

## §13 Reaching definitions

**Definition.** Definition `d` *reaches* point `p` if there is a path from `d`
to `p` with no intervening redefinition of the same variable.

**Why here.** It is the basis of def-use chains: the dependency graph's data
edges and the "which assignment produced this value" answers in the UI are all
reaching definitions.

**How.** Forward, `⊔ = ∪`:

```
GEN[B]  = definitions created in B (killed by later redefinitions in B are removed)
KILL[B] = definitions of the same variable outside B
OUT[B]  = GEN[B] ∪ (IN[B] − KILL[B])
IN[B]   = ∪ OUT[P] for P ∈ pred(B)
IN[entry] = ∅            (use-before-assignment is a separate analysis, §15)
```

Atoms are `d<id>`; `statement_states` replays each statement to give per-statement
IN/OUT.

**Worked example (hand-computed and asserted).** For

```c
int main() { int a = 1; int b = 2; while (a < 3) { b = a + b; a = a + 1; } return b; }
```

| Block | IN | OUT |
| --- | --- | --- |
| 0 entry (a=1, b=2) | ∅ | {d0, d1} |
| 2 header (a<3) | {d0, d1, d2, d3} | {d0, d1, d2, d3} |
| 4 body (b=a+b, a=a+1) | {d0, d1, d2, d3} | {d2, d3} |
| 3 return (return b) | {d0, d1, d2, d3} | {d0, d1, d2, d3} |

`OUT(body) = {d2, d3} ⊆ IN(header)` is the loop-carried fact that only a
fixpoint finds; a single pass over the blocks would report `{d0, d1}`.
`scripts/audit.py` re-checks exactly these sets.

**Implementation / tests / limits.** `codetrace/analysis/reaching_definitions.py`;
`tests/test_dataflow.py::ReachingDefinitionTests`, `tests/test_workflow.py`.
Limit: array elements and struct fields are not distinguished.

---

## §14 Live variables

**Definition.** Variable `v` is *live* at point `p` if some path from `p` reads
`v` before it is redefined.

**Why here.** Liveness is the backward counterpart of §13 and is what makes
"this assignment is dead" and "this value is still needed" answerable; it also
feeds the dependency graph's sanity checks and the UI's statement inspector.

**How.** Backward, `⊔ = ∪`:

```
USE[B] = variables read in B before any definition in B
DEF[B] = variables defined in B
IN[B]  = USE[B] ∪ (OUT[B] − DEF[B])
OUT[B] = ∪ IN[S] for S ∈ succ(B)
OUT[exit] = ∅
```

Atoms are `s<symbol-id>:<name>`, so two same-named variables in different scopes
are different atoms.

**Worked example (hand-computed and asserted).** Same program as §13:

| Block | IN | OUT |
| --- | --- | --- |
| 0 entry | ∅ | {s2:a, s3:b} |
| 2 header | {s2:a, s3:b} | {s2:a, s3:b} |
| 4 body | {s2:a, s3:b} | {s2:a, s3:b} |
| 3 return | {s3:b} | ∅ |

`IN(return) = {s3:b}` and `OUT(return) = ∅` are the facts that make the final
`return b` the only live use at the exit; convergence takes 6 iterations.

**Implementation / tests / limits.** `codetrace/analysis/liveness.py`;
`tests/test_dataflow.py::LivenessTests`, `scripts/audit.py`. Limit: as above,
no alias or array-element precision.

---

## §15 Definite assignment (a *must* analysis)

**Definition.** "Variable `v` is definitely assigned" holds if every path from
the entry to `p` contains an assignment to `v`. It is a must-analysis: the meet
operator is **intersection**, and the initial value is the *top* of the lattice
(all variables assigned) so that the union at a merge keeps only what both paths
guarantee.

**Why here.** Reading an uninitialised variable is undefined behaviour in C, and
it is not expressible in the may-analysis of §13: `int a; int b = a + 1;` has no
reaching definition for `a` at all, which is precisely the bug to report.

**How.**

```
OUT[B] = GEN[B] ∪ (IN[B] − KILL[B])
IN[B]  = ∩ OUT[P] for P ∈ pred(B)        (init = ⊤ = "everything assigned")
IN[entry] = ∅                            (nothing assigned yet)
uninitialised reads = { reads of v at p | v ∉ IN[p] and v not killed by a
                        definition earlier in the same block }
```

**Worked example (measured).** For `int main() { int a; int b = a + 1; return b; }`

```
statement states:  0: in {} out {}        1: in {} out {s3:b}      2: in {s3:b} out {s3:b}
uninitialised_reads: [{symbol_id: 2, symbol: "a", sid: 1, offset: 20, line: 1, col: 21, block: 0}]
diagnostics: DFA001 at 1:21
```

The declaration `int a;` creates no definition (it is `DECL_UNINIT`), so the
block's GEN set is `{b}` and the read of `a` in the same statement is flagged
with its exact location.

**The initial value is not a formality.** A *may* analysis starts at the
interval/bitset bottom (∅) because the union meet can only grow; a *must*
analysis must start at ⊤ everywhere except the entry, because the intersection
meet can only shrink. Starting definite assignment at ∅ instead makes the result
depend on the order in which blocks are first visited: a loop header whose back
edge is processed before the fact has been established intersects with an empty
set and loses it. On `int n = 0; for (int i = 0; i < 3; i++) { n = n + i; }
return n;` the fact "`n` is assigned" survives the back edge only with ⊤
initialisation; with ∅ the analysis reports `DFA001` for a variable that is
assigned on every path — a false positive produced entirely by the choice of
initial value. The engine implements the boundary as
`initial_value(entry) = ∅`, `initial_value(other) = ⊤`
(`definite_assignment.py`), and the hand-verified loop and nested-loop tests in
`tests/test_dataflow.py::MustAnalysisInitialisationTests` fail if the override is
removed.

**Implementation / tests / limits.** `codetrace/analysis/definite_assignment.py`;
`tests/test_dataflow.py::DefiniteAssignmentTests::`
`::MustAnalysisInitialisationTests`, `/api/runs/{id}/dataflow?analysis=definite`,
`scripts/audit.py`. Limit: no path-sensitivity inside expressions, no tracking of
partially assigned arrays.

---

## §16 Interprocedural taint analysis

**Definition.** Taint analysis is a forward data-flow analysis whose domain is a
set of *atoms* `src:<rule>@<context>`; a finding exists when an atom with a
context matching a sink reaches that sink's argument.

**Why here.** This is the analysis the product is *about*: a user-visible,
configurable, explainable statement "untrusted data from X can reach dangerous
operation Y in context C".

**How.** Three phases (`codetrace/analysis/taint.py`):

1. **Symbolic summaries.** Each function is summarised as
   `param i → {atoms of the return value}` plus "which parameters reach the
   return" for every atom, computed by a first pass over the function's body.
   Because summaries are symbolic, they are valid for *every* caller.
2. **Interprocedural fixpoint.** Summaries are iterated over the call graph until
   they stop changing, with a visited-set safeguard for recursion, so a recursive
   helper terminates and is reported as `approximate` rather than crashing.
3. **Collecting replay.** Starting from the sources, each function is evaluated
   in call order with the summarised callee behaviour, propagating atoms through
   assignments, expressions, branches, arguments and returns. The result is the
   set of atoms at each statement plus one `TaintHit` per (sink, argument,
   atom), which the explainer turns into the ordered evidence path.

Design decisions that are *deliberate* and visible in the product:

* **Contexts**: `command`, `sql`, `path`, `html`, `numeric`, `format`; a source
  declares which contexts its data is dangerous in (`contexts …`), a sink
  declares *one* context, and a sanitiser is trusted for exactly one context (or
  all of them with `*`). A sanitiser for another context does not clear taint,
  and the finding records that reasoning.
* **Argument granularity**: a sanitiser cleans only the argument it declares
  (`argument 0`). `wrap("prefix", value)` stays tainted if taint entered through
  argument 1.
* **Unknown externals are never assumed safe**: if an unmodelled function
  receives a tainted argument, its result is assumed to depend on its arguments
  (`unknown-call` path step, limitation recorded, certainty `approximate`).
* **Branch feasibility**: conditions that a sanitiser or validator guards prune
  the edge; literal `false` prunes statically; anything else yields
  `feasibility: guarded` with the condition text. Nothing claims symbolic
  execution — the wording is "potential flow detected" plus a feasibility note.
* **Counters**: `taint.iterations` and `taint.converged` are reported per run.

**Worked example.** For `int main() { string cmd = input(); system(cmd); }`

```
atoms at the sink:  src:stdin@command
path:  source (input() introduces untrusted data, line 1)
    -> declaration ('cmd' is assigned a tainted value, line 1)
    -> sink (system() argument 0 consumes data unsafe for context 'command')
certainty: confirmed (high confidence, intraprocedural, unconditional)
```

With a helper (`build_command(name)` returning `"ls " + name`), the path gains a
`call`, a `parameter` and a `return` step, and the finding is marked
`interprocedural: true` with the context-insensitivity limitation attached.

**Implementation / tests / limits.** `codetrace/analysis/taint.py`,
`codetrace/findings/explain.py`; `tests/test_taint.py` (36 tests: positives,
negatives, sanitiser contexts and argument indices, unknown calls, branches,
recursion, custom rules). Limits: context-insensitive summaries (documented in
`docs/LIMITATIONS.md`), no path-sensitivity beyond the guard rules, no array or
alias precision.

---

## §17 Program dependency graph

**Definition.** The PDG has a node per statement (and per definition) and typed
edges: data dependence, control dependence, call, return-value, taint,
sanitisation.

**Why here.** The graph is what makes the *evidence* inspectable: every edge
carries the analysis result that justifies it, so a reviewer can check a claim
instead of trusting it.

**How.**

* **Data edges** come from the reaching definitions of §13: for each statement
  reading `v`, `d(v) → read` for every definition of `v` in `IN`.
* **Define edges** connect a statement to the definition it creates.
* **Control edges** connect a statement to the condition of the nearest
  enclosing `if`/`while`/`for`. With no `goto` in the language, this syntactic
  nesting relation *is* the control-dependence relation of the CFG, which is why
  the implementation can compute it from the AST and still be exact
  (`dependencies.control_dependencies`).
* **Call and return-value edges** connect a call statement with the callee's
  entry/return statements; **taint** edges carry the atoms that travel, and
  **source-to-sink** edges mark the reported flows.

`DependencyGraph.to_json(kinds=…)` filters by kind, caps the payload
(`limit=4000`, `truncated` flag) and never emits an edge whose endpoints are not
in the payload.

**Worked example.** `scripts/audit.py` re-verifies, for every intra-procedural
data/taint edge, that the source definition is in the target statement's IN set
(or OUT when the definition lives in the target statement, as in
`string name = input();`), using the bitsets of §13. In the audit run for the
`build_command` example: **6 edges checked, 0 unjustified**.

**Implementation / tests / limits.** `codetrace/analysis/dependencies.py`;
`tests/test_slicing.py::DependencyGraphTests`, `scripts/audit.py`. Limit: edges
are conservative (may-overlap), and interprocedural edges use the summary
information of §16 rather than a call-site-sensitive analysis.

---

## §18 Program slicing

**Definition.** A *backward slice* of a criterion `(statement s, variable v)` is
the set of statements that may affect `v` at `s`; a *forward slice* is the set of
statements the criterion may affect. Both are transitive closures over the PDG.

**Why here.** Slicing is the answer to "why is this a finding?" — the slice of a
finding is its evidence, reduced to the statements that actually matter.

**How.** `SliceEngine` walks the PDG:

```
backward(s) = least set closed under:  p ∈ slice, p → q data/control/call/taint ⇒ p ∈ slice
forward(s)  = least set closed under:  p ∈ slice, q → p ⇒ q ∈ slice
security(f) = closure over the union of the finding's statement ids and the
              def-use closure of their definitions
```

Each member statement carries a `reason` list naming the edge that put it there,
the slice records the direction, the criterion, the finding id (for security
slices), a conservative note, and `truncated` if a cap was hit
(`MAX_STATEMENTS = 5000`, `MAX_EDGES = 500`). The subgraph payload is the slice
induced on the PDG, closed over the definition nodes it references, so a viewer
sees *why* the statements belong together.

**Worked example (hand-verified, real statement ids).**

```c
int main() {
    string cmd = "ls";                    // statement 0
    int unused = 7;                       // statement 1
    cmd = cmd + input();                  // statement 2  <- the source
    if (unused > 0) { unused = 0; }       // statements 3 and 4
    system(cmd);                          // statement 5  <- the sink
    return 0;                             // statement 6
}
```

```
backward(5) = [0, 2, 5]
    reasons for 5: taint: definition of 'cmd' at line 4 reaches the read of 'cmd' at line 6
    reasons for 2: define: this statement creates definition 'cmd'
                   data:   the definition of 'cmd' at line 2 reaches the read at line 4
    reasons for 0: define: this statement creates definition 'cmd'
forward(1)  = [1, 3, 4]     (the unused variable influences the condition and the
                             assignment inside the branch, and nothing else)
security slice of the finding = [0, 2, 5]
```

The unrelated `unused` statements and the `return` are excluded, and the slice
keeps the two definitions of `cmd` that the sink's value flows through. The
security slice equals the backward slice of the sink here; in a program where
the sink's value also flows onwards, it is strictly larger.

**Implementation / tests / limits.** `codetrace/analysis/slicing.py`;
`tests/test_slicing.py` (20 tests: direction, criteria, closure, reasons,
determinism, subgraph consistency, search states). Limit: slices are
conservative over-approximations (the note says so), they use the same
may-overlap edges as §17, and array/alias imprecision carries over.

---

## §19 Stable identity and run comparison

**Definition.** A finding's identity must survive edits that do not change the
flow, so that "before vs after" comparison is meaningful.

**Why here.** The product's fix-and-recheck workflow depends on it: after a fix
the user must see *resolved*, and after an unrelated edit above the sink, the
same *moved* finding — not "1 new, 1 resolved".

**How.**

```
id = "F" + sha256(rule_id | sink_function | sink_rule | argument_index |
                  sorted(source_rules) | normalised_sink_text)[:12].upper()
```

Line and column numbers are deliberately **not** part of the hash. Comparison
classifies each finding as `new` (id only after), `resolved` (id only before),
`moved` (same id, different location) or `persistent` (same id, same location).

**Worked example.** Inserting a blank line above `system(cmd);` keeps the id
`F7A2E2F89F9F6` and the comparison reports `moved` with `before.line = 1`,
`after.line = 2`; replacing the tainted value with `shell_escape(...)` produces a
different id and is reported as `resolved` (verified over HTTP by
`scripts/audit.py` and `tests/test_workflow.py`).

**Implementation / tests / limits.** `codetrace/findings/models.py`
(`stable_finding_id`, `compare_findings`); `tests/test_api.py` (compare tests),
`tests/test_workflow.py::test_09_*`. Limit: identity is textual for the sink
statement, so renaming the sink's variable changes the id — a deliberate
trade-off, documented in `docs/LIMITATIONS.md`.
