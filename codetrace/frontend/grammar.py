"""Grammar representation and LR analysis primitives.

This module is the theoretical core of CodeTrace's front end.  It provides:

* a grammar representation with an augmented start production,
* NULLABLE / FIRST / FOLLOW computation by fixed-point iteration,
* LR(0) items, LR(1) items, closure and GOTO,
* construction of the LR(0) automaton (used for SLR and, after lookahead
  merging, for LALR(1)),
* construction of the canonical LR(1) item-set collection.

The SLR/LALR/canonical table builders in :mod:`codetrace.frontend.clr_parser`
are written directly on top of these primitives, and the same primitives are
reused to parse the declarative security-rule language.  Nothing in this
module is analysis-specific; it is a small, general LR parser generator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

#: Grammar-level end-of-input marker.  The lexer emits the token ``EOF`` which
#: the parser driver translates to this symbol.
END = "$end"
#: Internal marker for the empty string on the right-hand side.
EPSILON = "ε"

Symbol = str
#: An LR(1) item: (production index, dot position, lookahead terminal).
Item = Tuple[int, int, str]

Builder = Callable[[List[object], Tuple[int, int]], object]


@dataclass(frozen=True)
class Production:
    """A context-free production ``lhs -> rhs`` with a semantic action.

    ``builder`` receives the list of parsed child values (semantic attributes)
    and the source span tuple, and returns the AST node (or an intermediate
    value) for this production.  ``builder`` may be ``None`` for productions
    whose value is a pass-through of a single child.
    """

    index: int
    lhs: Symbol
    rhs: Tuple[Symbol, ...]
    builder: Optional[Builder] = None
    label: str = ""

    def display(self) -> str:
        body = " ".join(self.rhs) if self.rhs else EPSILON
        return f"{self.lhs} -> {body}"

    def to_json(self) -> dict:
        return {
            "index": self.index,
            "lhs": self.lhs,
            "rhs": list(self.rhs),
            "display": self.display(),
            "label": self.label,
        }


class GrammarError(Exception):
    """Raised when a grammar definition is structurally invalid."""


class Grammar:
    """A context-free grammar with LR analysis helpers."""

    def __init__(self, start_symbol: Symbol, augmented_start: Optional[Symbol] = None) -> None:
        self.start_symbol = start_symbol
        self.augmented_start = augmented_start or (start_symbol + "'")
        self.productions: List[Production] = []
        self.terminals: Set[Symbol] = {END}
        self.nonterminals: Set[Symbol] = set()
        self._by_lhs: Dict[Symbol, List[int]] = {}
        self.nullable: Set[Symbol] = set()
        self.first: Dict[Symbol, FrozenSet[Symbol]] = {}
        self.follow: Dict[Symbol, FrozenSet[Symbol]] = {}
        self._finalized = False
        # Production 0 is the augmented production required by LR parsing.
        self._add_raw(self.augmented_start, (start_symbol,), None, "augmented start")
        self.nonterminals.add(self.augmented_start)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _add_raw(
        self,
        lhs: Symbol,
        rhs: Sequence[Symbol],
        builder: Optional[Builder],
        label: str,
    ) -> int:
        index = len(self.productions)
        self.productions.append(Production(index, lhs, tuple(rhs), builder, label))
        self.nonterminals.add(lhs)
        for sym in rhs:
            if sym != lhs:
                self.terminals.add(sym)  # provisional; corrected in finalize()
        return index

    def add(
        self,
        lhs: Symbol,
        rhs: Sequence[Symbol],
        builder: Optional[Builder] = None,
        label: str = "",
    ) -> int:
        """Add a production.  Must be called before :meth:`finalize`."""
        if self._finalized:
            raise GrammarError("cannot add productions to a finalised grammar")
        return self._add_raw(lhs, rhs, builder, label)

    def declare_terminal(self, name: Symbol) -> None:
        """Register a terminal that appears in no production (e.g. ``$end``)."""
        self.terminals.add(name)

    def finalize(self) -> "Grammar":
        """Compute NULLABLE, FIRST, FOLLOW and the LHS index."""
        self._by_lhs = {}
        for prod in self.productions:
            self._by_lhs.setdefault(prod.lhs, []).append(prod.index)

        # Any RHS symbol that is never a LHS is a terminal.
        defined = {p.lhs for p in self.productions}
        symbols: Set[Symbol] = set()
        for prod in self.productions:
            symbols.update(prod.rhs)
        self.terminals |= (symbols - defined) - {EPSILON}
        self.nonterminals = defined
        # ``add`` records every right-hand-side symbol provisionally so that
        # FIRST/FOLLOW can be computed over a single symbol namespace; symbols
        # that turned out to be left-hand sides are non-terminals and must not
        # appear in the terminal set (otherwise FOLLOW and the ACTION table
        # would carry non-terminal "lookaheads" that no token can match).
        self.terminals -= self.nonterminals

        self._compute_nullable()
        self._compute_first()
        self._compute_follow()
        self._finalized = True
        return self

    # ------------------------------------------------------------------
    # NULLABLE / FIRST / FOLLOW
    # ------------------------------------------------------------------
    def _compute_nullable(self) -> None:
        nullable: Set[Symbol] = set()
        changed = True
        while changed:
            changed = False
            for prod in self.productions:
                if prod.lhs in nullable:
                    continue
                if all(sym in nullable for sym in prod.rhs):
                    nullable.add(prod.lhs)
                    changed = True
        self.nullable = nullable

    def _compute_first(self) -> None:
        first: Dict[Symbol, Set[Symbol]] = {t: {t} for t in self.terminals}
        for nt in self.nonterminals:
            first.setdefault(nt, set())
        changed = True
        while changed:
            changed = False
            for prod in self.productions:
                target = first[prod.lhs]
                before = len(target)
                for sym in prod.rhs:
                    target |= first[sym]
                    if sym not in self.nullable:
                        break
                if len(target) != before:
                    changed = True
        self.first = {sym: frozenset(vals) for sym, vals in first.items()}

    def _compute_follow(self) -> None:
        follow: Dict[Symbol, Set[Symbol]] = {nt: set() for nt in self.nonterminals}
        follow[self.augmented_start] = {END}
        changed = True
        while changed:
            changed = False
            for prod in self.productions:
                trailer = set(follow[prod.lhs])
                for sym in reversed(prod.rhs):
                    if sym in self.nonterminals:
                        before = len(follow[sym])
                        follow[sym] |= trailer
                        if len(follow[sym]) != before:
                            changed = True
                        if sym in self.nullable:
                            trailer = trailer | self.first[sym]
                        else:
                            trailer = set(self.first[sym])
                    else:
                        trailer = set(self.first.get(sym, {sym}))
        self.follow = {sym: frozenset(vals) for sym, vals in follow.items()}

    # ------------------------------------------------------------------
    # Sequence helpers
    # ------------------------------------------------------------------
    def first_of_sequence(self, symbols: Sequence[Symbol]) -> Tuple[FrozenSet[Symbol], bool]:
        """Return ``(FIRST(sequence), sequence_is_nullable)``."""
        result: Set[Symbol] = set()
        for sym in symbols:
            result |= self.first.get(sym, frozenset({sym}))
            if sym not in self.nullable:
                return frozenset(result), False
        return frozenset(result), True

    def first_of_sequence_with_lookahead(
        self, symbols: Sequence[Symbol], lookahead: Symbol
    ) -> FrozenSet[Symbol]:
        """``FIRST(sequence · lookahead)`` -- the LR(1) closure lookahead set."""
        result, nullable = self.first_of_sequence(symbols)
        if nullable:
            return frozenset(set(result) | {lookahead})
        return result

    # ------------------------------------------------------------------
    # LR primitives
    # ------------------------------------------------------------------
    def productions_for(self, lhs: Symbol) -> List[int]:
        return self._by_lhs.get(lhs, [])

    def is_terminal(self, symbol: Symbol) -> bool:
        return symbol in self.terminals

    def is_nonterminal(self, symbol: Symbol) -> bool:
        return symbol in self.nonterminals

    def closure(self, items: Iterable[Item]) -> FrozenSet[Item]:
        """LR(1) closure: ``closure(I) = I ∪ {[B -> .γ, b] : [A -> α.Bβ, a] ∈ I,
        B -> γ, b ∈ FIRST(βa)}``."""
        result: Set[Item] = set(items)
        worklist = list(result)
        while worklist:
            prod_index, dot, lookahead = worklist.pop()
            prod = self.productions[prod_index]
            if dot >= len(prod.rhs):
                continue
            sym = prod.rhs[dot]
            if not self.is_nonterminal(sym):
                continue
            beta = prod.rhs[dot + 1 :]
            lookaheads = self.first_of_sequence_with_lookahead(beta, lookahead)
            for child_index in self.productions_for(sym):
                for la in lookaheads:
                    item = (child_index, 0, la)
                    if item not in result:
                        result.add(item)
                        worklist.append(item)
        return frozenset(result)

    def goto(self, items: Iterable[Item], symbol: Symbol) -> FrozenSet[Item]:
        moved = []
        for prod_index, dot, lookahead in items:
            prod = self.productions[prod_index]
            if dot < len(prod.rhs) and prod.rhs[dot] == symbol:
                moved.append((prod_index, dot + 1, lookahead))
        if not moved:
            return frozenset()
        return self.closure(moved)

    @staticmethod
    def kernel_of(items: Iterable[Item]) -> FrozenSet[Tuple[int, int]]:
        """LR(0) core (kernel) of an LR(1) item set."""
        return frozenset((p, d) for p, d, _a in items)

    @staticmethod
    def lr0_items(items: Iterable[Item]) -> FrozenSet[Tuple[int, int, str]]:
        """Drop lookaheads (LR(0) items use the empty lookahead marker)."""
        return frozenset((p, d, "") for p, d, _a in items)


# ----------------------------------------------------------------------
# Automaton construction
# ----------------------------------------------------------------------
@dataclass
class AutomatonStats:
    mode: str
    states: int
    transitions: int
    items_total: int
    items_max: int
    lr1_states_before_merge: int = 0
    terminal_count: int = 0
    nonterminal_count: int = 0
    production_count: int = 0
    build_seconds: float = 0.0

    def to_json(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Automaton:
    """An LR automaton: item sets plus a symbol-indexed transition table."""

    mode: str
    states: List[FrozenSet[Item]]
    transitions: Dict[Tuple[int, Symbol], int]
    stats: AutomatonStats
    #: For LALR/canonical, the per-state LR(1) lookahead map used by the table
    #: builder: {state: {(prod_index, dot): frozenset(lookaheads)}}.
    lookaheads: Dict[int, Dict[Tuple[int, int], FrozenSet[Symbol]]] = field(default_factory=dict)

    def symbol_of_edge(self, state: int) -> List[Tuple[Symbol, int]]:
        return sorted(
            ((sym, dst) for (src, sym), dst in self.transitions.items() if src == state),
            key=lambda pair: pair[0],
        )


def build_lr0_automaton(grammar: Grammar) -> Tuple[List[FrozenSet[Item]], Dict[Tuple[int, Symbol], int]]:
    """Construct the LR(0) collection of item sets with GOTO transitions.

    Items are represented as ``(prod, dot, "")``; the LR(0) automaton carries
    no lookahead information, which is exactly what SLR and LALR(1) share.
    """
    start_items = grammar.closure([(0, 0, "")])
    start_items = Grammar.lr0_items(start_items)
    states: List[FrozenSet[Item]] = [start_items]
    index: Dict[FrozenSet[Item], int] = {start_items: 0}
    transitions: Dict[Tuple[int, Symbol], int] = {}
    worklist = [0]

    while worklist:
        state_id = worklist.pop()
        items = states[state_id]
        # Collect the symbols the dot can precede.
        symbols: List[Symbol] = []
        seen: Set[Symbol] = set()
        for prod_index, dot, _la in items:
            rhs = grammar.productions[prod_index].rhs
            if dot < len(rhs):
                sym = rhs[dot]
                if sym not in seen:
                    seen.add(sym)
                    symbols.append(sym)
        for sym in symbols:
            moved = Grammar.lr0_items(grammar.goto(items, sym))
            if not moved:
                continue
            target = index.get(moved)
            if target is None:
                target = len(states)
                states.append(moved)
                index[moved] = target
                worklist.append(target)
            transitions[(state_id, sym)] = target
    return states, transitions


def build_canonical_lr1_automaton(
    grammar: Grammar, max_states: int = 2500
) -> Tuple[List[FrozenSet[Item]], Dict[Tuple[int, Symbol], int]]:
    """Construct the canonical LR(1) collection of item sets.

    ``max_states`` bounds the construction so that a pathological grammar (or
    a pathological rule file) cannot exhaust memory; exceeding it raises
    :class:`GrammarError` rather than silently truncating the automaton.
    """
    start_items = grammar.closure([(0, 0, END)])
    states: List[FrozenSet[Item]] = [start_items]
    index: Dict[FrozenSet[Item], int] = {start_items: 0}
    transitions: Dict[Tuple[int, Symbol], int] = {}
    worklist = [0]

    while worklist:
        state_id = worklist.pop()
        items = states[state_id]
        symbols: List[Symbol] = []
        seen: Set[Symbol] = set()
        for prod_index, dot, _la in items:
            rhs = grammar.productions[prod_index].rhs
            if dot < len(rhs):
                sym = rhs[dot]
                if sym not in seen:
                    seen.add(sym)
                    symbols.append(sym)
        for sym in symbols:
            moved = grammar.goto(items, sym)
            if not moved:
                continue
            target = index.get(moved)
            if target is None:
                if len(states) >= max_states:
                    raise GrammarError(
                        f"canonical LR(1) construction exceeded {max_states} states"
                    )
                target = len(states)
                states.append(moved)
                index[moved] = target
                worklist.append(target)
            transitions[(state_id, sym)] = target
    return states, transitions


def merge_lalr_states(
    grammar: Grammar,
    lr0_states: List[FrozenSet[Item]],
    lr0_transitions: Dict[Tuple[int, Symbol], int],
    lr1_states: List[FrozenSet[Item]],
    lr1_transitions: Dict[Tuple[int, Symbol], int],
) -> Tuple[List[FrozenSet[Item]], Dict[Tuple[int, Symbol], int], Dict[int, Dict[Tuple[int, int], FrozenSet[Symbol]]]]:
    """Merge canonical LR(1) states that share an LR(0) core (LALR(1)).

    Textbook LALR(1) propagates lookaheads on the LR(0) automaton; merging the
    canonical collection by core yields exactly the same parser (the
    "LALR-by-merging" construction) and is far easier to audit.
    """
    core_to_state: Dict[FrozenSet[Tuple[int, int]], int] = {
        grammar.kernel_of(items): idx for idx, items in enumerate(lr0_states)
    }
    # Map canonical LR(1) state -> LALR state id.
    remap: Dict[int, int] = {}
    for lr1_id, items in enumerate(lr1_states):
        core = grammar.kernel_of(items)
        target = core_to_state.get(core)
        if target is None:  # pragma: no cover - cores of LR(1) states are LR(0) states
            raise GrammarError("LR(1) state core does not correspond to an LR(0) state")
        remap[lr1_id] = target

    lookaheads: Dict[int, Dict[Tuple[int, int], Set[Symbol]]] = {}
    for lr1_id, items in enumerate(lr1_states):
        state = remap[lr1_id]
        bucket = lookaheads.setdefault(state, {})
        for prod_index, dot, la in items:
            bucket.setdefault((prod_index, dot), set()).add(la)

    transitions: Dict[Tuple[int, Symbol], int] = {}
    for (src, sym), dst in lr1_transitions.items():
        transitions[(remap[src], sym)] = remap[dst]

    frozen = {
        state: {key: frozenset(vals) for key, vals in bucket.items()}
        for state, bucket in lookaheads.items()
    }
    return lr0_states, transitions, frozen


def build_automaton(grammar: Grammar, mode: str = "lalr", max_states: int = 2500) -> Automaton:
    """Build the LR automaton in ``slr``, ``lalr`` or ``canonical`` mode."""
    import time

    if not grammar._finalized:
        grammar.finalize()

    started = time.perf_counter()
    lookaheads: Dict[int, Dict[Tuple[int, int], FrozenSet[Symbol]]] = {}
    if mode == "slr":
        # LR(0) states; the table builder uses FOLLOW sets for reductions.
        states, transitions = build_lr0_automaton(grammar)
        lr1_count = 0
    elif mode == "canonical":
        states, transitions = build_canonical_lr1_automaton(grammar, max_states=max_states)
        lr1_count = len(states)
        for state_id, items in enumerate(states):
            bucket: Dict[Tuple[int, int], Set[Symbol]] = {}
            for prod_index, dot, la in items:
                bucket.setdefault((prod_index, dot), set()).add(la)
            lookaheads[state_id] = {k: frozenset(v) for k, v in bucket.items()}
    elif mode == "lalr":
        # LALR(1): canonical LR(1) states whose kernels coincide are merged.
        lr0_states, lr0_transitions = build_lr0_automaton(grammar)
        lr1_states, lr1_transitions = build_canonical_lr1_automaton(grammar, max_states=max_states)
        states, transitions, lookaheads = merge_lalr_states(
            grammar, lr0_states, lr0_transitions, lr1_states, lr1_transitions
        )
        lr1_count = len(lr1_states)
    else:
        raise GrammarError(f"unknown automaton mode {mode!r}")

    elapsed = time.perf_counter() - started
    stats = AutomatonStats(
        mode=mode,
        states=len(states),
        transitions=len(transitions),
        items_total=sum(len(s) for s in states),
        items_max=max((len(s) for s in states), default=0),
        lr1_states_before_merge=lr1_count,
        terminal_count=len(grammar.terminals),
        nonterminal_count=len(grammar.nonterminals),
        production_count=len(grammar.productions),
        build_seconds=round(elapsed, 6),
    )
    return Automaton(mode=mode, states=states, transitions=transitions, stats=stats, lookaheads=lookaheads)
