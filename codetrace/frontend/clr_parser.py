"""Table-driven LR parser: SLR(1), LALR(1) and canonical LR(1).

The table builder consumes the automaton produced by
:mod:`codetrace.frontend.grammar` and produces ACTION/GOTO tables exactly as
described in the standard LR construction:

* ACTION[i, a] = shift j       if [A -> α . a β]  ∈ I_i and GOTO(I_i, a) = I_j
* ACTION[i, a] = reduce A -> α if [A -> α .]     ∈ I_i and a ∈ LA(I_i, A -> α)
* ACTION[i, $end] = accept     if [S' -> S .]    ∈ I_i
* GOTO[i, A]   = j             if GOTO(I_i, A) = I_j

where ``LA`` is FOLLOW(A) for SLR(1) and the merged LR(1) lookahead set for
LALR(1) / canonical LR(1).

Conflict handling is explicit: every conflicting table entry is recorded with
both candidate actions and the resolution that was applied (shift preferred
over reduce, lowest-numbered production preferred for reduce/reduce).  Nothing
is silently dropped, and the conflict list is exposed through the API and the
generated grammar report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .grammar import END, Automaton, Grammar, GrammarError, Item, build_automaton
from .lexer import Diagnostic
from .tokens import EOF, INVALID, Token, display_kind

SHIFT = "shift"
REDUCE = "reduce"
ACCEPT = "accept"


@dataclass(frozen=True)
class Action:
    kind: str
    value: int = 0  # shift target state, or production index for reduce

    def to_json(self) -> dict:
        if self.kind == SHIFT:
            return {"kind": SHIFT, "state": self.value}
        if self.kind == REDUCE:
            return {"kind": REDUCE, "production": self.value}
        return {"kind": self.kind}


@dataclass
class Conflict:
    kind: str  # "shift/reduce" | "reduce/reduce" | "accept/reduce" | ...
    state: int
    terminal: str
    existing: Action
    incoming: Action
    resolved: Action
    reason: str

    def to_json(self, grammar: Optional[Grammar] = None) -> dict:
        return {
            "kind": self.kind,
            "state": self.state,
            "terminal": self.terminal,
            "terminal_display": display_kind(self.terminal) if self.terminal != END else "end of file",
            "existing": _action_text(self.existing, grammar),
            "incoming": _action_text(self.incoming, grammar),
            "resolved": _action_text(self.resolved, grammar),
            "reason": self.reason,
        }


def _action_text(action: Action, grammar: Optional[Grammar]) -> str:
    if action.kind == SHIFT:
        return f"shift to state {action.value}"
    if action.kind == REDUCE:
        if grammar is not None:
            return f"reduce by {grammar.productions[action.value].display()}"
        return f"reduce by production {action.value}"
    return action.kind


class ParserTableError(Exception):
    pass


@dataclass
class ParserTables:
    """ACTION/GOTO tables plus everything needed to visualise and audit them."""

    grammar: Grammar
    automaton: Automaton
    action: Dict[Tuple[int, str], Action]
    goto: Dict[Tuple[int, str], int]
    conflicts: List[Conflict] = field(default_factory=list)
    mode: str = "lalr"
    build_seconds: float = 0.0

    # ------------------------------------------------------------------
    def terminal_actions(self, state: int) -> List[Tuple[str, Action]]:
        rows = [(t, a) for (s, t), a in self.action.items() if s == state]
        rows.sort(key=lambda pair: pair[0])
        return rows

    def goto_actions(self, state: int) -> List[Tuple[str, int]]:
        rows = [(n, dst) for (s, n), dst in self.goto.items() if s == state]
        rows.sort(key=lambda pair: pair[0])
        return rows

    def describe_item(self, item: Item) -> str:
        prod_index, dot, lookahead = item
        prod = self.grammar.productions[prod_index]
        rhs = list(prod.rhs)
        body = " ".join(rhs[:dot] + ["•"] + rhs[dot:]) if rhs else "•"
        la = f", {lookahead}" if lookahead else ""
        return f"[{prod.lhs} -> {body}{la}]"

    def state_json(self, state: int, item_limit: int = 60) -> dict:
        items = sorted(self.automaton.states[state])
        return {
            "id": state,
            "item_count": len(items),
            "items": [self.describe_item(i) for i in items[:item_limit]],
            "items_truncated": max(0, len(items) - item_limit),
            "transitions": [
                {"symbol": sym, "target": dst, "kind": "terminal" if self.grammar.is_terminal(sym) else "nonterminal"}
                for sym, dst in self.automaton.symbol_of_edge(state)
            ],
            "actions": [{"terminal": t, "action": a.to_json()} for t, a in self.terminal_actions(state)],
        }

    def summary_json(self) -> dict:
        stats = self.automaton.stats.to_json()
        stats.update(
            {
                "mode": self.mode,
                "action_entries": len(self.action),
                "goto_entries": len(self.goto),
                "conflicts": len(self.conflicts),
                "conflicts_by_kind": _count_by(self.conflicts, lambda c: c.kind),
                "build_seconds": round(self.build_seconds, 6),
            }
        )
        stats["table_cells"] = (len(self.grammar.terminals) + len(self.grammar.nonterminals)) * stats["states"]
        stats["table_density"] = round(
            (len(self.action) + len(self.goto)) / stats["table_cells"], 4
        ) if stats["table_cells"] else 0.0
        return stats


def _count_by(items: Iterable, key: Callable[[object], str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        k = key(item)
        counts[k] = counts.get(k, 0) + 1
    return counts


def build_tables(
    grammar: Grammar,
    mode: str = "lalr",
    prefer_shift: bool = True,
    max_states: int = 2500,
) -> ParserTables:
    """Construct ACTION/GOTO tables for ``grammar`` in the requested mode."""
    import time

    started = time.perf_counter()
    grammar.finalize()
    automaton = build_automaton(grammar, mode=mode, max_states=max_states)

    action: Dict[Tuple[int, str], Action] = {}
    goto: Dict[Tuple[int, str], int] = {}
    conflicts: List[Conflict] = []

    def record(state: int, terminal: str, candidate: Action) -> None:
        existing = action.get((state, terminal))
        if existing is None:
            action[(state, terminal)] = candidate
            return
        if existing == candidate:
            return
        kind, resolved, reason = _resolve(existing, candidate, prefer_shift)
        conflicts.append(
            Conflict(
                kind=kind,
                state=state,
                terminal=terminal,
                existing=existing,
                incoming=candidate,
                resolved=resolved,
                reason=reason,
            )
        )
        action[(state, terminal)] = resolved

    for state in range(len(automaton.states)):
        items = automaton.states[state]
        # Shifts and accept ------------------------------------------------
        for prod_index, dot, _la in items:
            prod = grammar.productions[prod_index]
            if dot < len(prod.rhs):
                sym = prod.rhs[dot]
                if grammar.is_terminal(sym):
                    target = automaton.transitions.get((state, sym))
                    if target is not None:
                        record(state, sym, Action(SHIFT, target))
            else:
                if prod_index == 0 and dot == len(prod.rhs):
                    # [S' -> S .] : accept on end of input.
                    record(state, END, Action(ACCEPT))

        # Reductions --------------------------------------------------------
        la_map = automaton.lookaheads.get(state, {})
        for prod_index, dot, _la in items:
            prod = grammar.productions[prod_index]
            if dot != len(prod.rhs) or prod_index == 0:
                continue
            if mode == "slr":
                lookaheads: Set[str] = set(grammar.follow.get(prod.lhs, frozenset()))
            else:
                lookaheads = set(la_map.get((prod_index, dot), frozenset()))
            for terminal in lookaheads:
                record(state, terminal, Action(REDUCE, prod_index))

        # GOTO --------------------------------------------------------------
        for sym in grammar.nonterminals:
            target = automaton.transitions.get((state, sym))
            if target is not None:
                goto[(state, sym)] = target

    elapsed = time.perf_counter() - started
    return ParserTables(
        grammar=grammar,
        automaton=automaton,
        action=action,
        goto=goto,
        conflicts=conflicts,
        mode=mode,
        build_seconds=round(elapsed, 6),
    )


def _resolve(existing: Action, candidate: Action, prefer_shift: bool) -> Tuple[str, Action, str]:
    """Decide which action wins and describe the decision."""
    kinds = {existing.kind, candidate.kind}
    if kinds == {SHIFT, REDUCE}:
        shift, reduce = (existing, candidate) if existing.kind == SHIFT else (candidate, existing)
        if prefer_shift:
            return (
                "shift/reduce",
                shift,
                "shift preferred: the parser defers the reduction and keeps shifting "
                "(standard yacc-compatible policy)",
            )
        return (
            "shift/reduce",
            reduce,
            "reduce preferred: the parser reduces earlier (explicitly requested policy)",
        )
    if existing.kind == REDUCE and candidate.kind == REDUCE:
        winner = existing if existing.value <= candidate.value else candidate
        return (
            "reduce/reduce",
            winner,
            f"lowest-numbered production wins (production {winner.value} of the grammar, "
            "which is the earliest rule declared)",
        )
    if ACCEPT in kinds:
        winner = existing if existing.kind != ACCEPT else candidate
        return (
            "accept/other",
            winner,
            "accept entry kept only for end of input; the other candidate is retained",
        )
    return ("other", existing, "existing entry kept")


# ----------------------------------------------------------------------
# Parse driver
# ----------------------------------------------------------------------
@dataclass
class ParseStats:
    shifts: int = 0
    reductions: int = 0
    steps: int = 0
    recovered: int = 0
    max_stack_depth: int = 0
    suppress_errors: bool = False

    def to_json(self) -> dict:
        return {
            "shifts": self.shifts,
            "reductions": self.reductions,
            "steps": self.steps,
            "errors_recovered": self.recovered,
            "max_stack_depth": self.max_stack_depth,
        }


@dataclass
class ParseResult:
    tree: Optional[object]
    diagnostics: List[Diagnostic]
    stats: ParseStats
    tokens: List[Token]
    accepted: bool = False
    trace: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.accepted and not any(d.severity == "error" for d in self.diagnostics)


#: Tokens that always resynchronise a panicking parser.
_SYNC_TOKENS = {"SEMI", "RBRACE"}


class LRParser:
    """Deterministic LR parser driving the tables built above."""

    def __init__(
        self,
        tables: ParserTables,
        max_errors: int = 25,
        max_steps: int = 400_000,
        trace_limit: int = 0,
    ) -> None:
        self.tables = tables
        self.max_errors = max_errors
        self.max_steps = max_steps
        self.trace_limit = trace_limit
        self.trace: List[str] = []
        # Index of shiftable/acceptable terminals per state, used only by error
        # recovery.  Built once so recovery stays O(stack) instead of scanning
        # the whole ACTION table on every syntax error.
        self._shift_terminals: Dict[int, Set[str]] = {}
        for (state, terminal), action in tables.action.items():
            if action.kind in (SHIFT, ACCEPT):
                self._shift_terminals.setdefault(state, set()).add(terminal)

    # -- helpers -------------------------------------------------------
    def _reduce_value(self, prod_index: int, children: List[object], span: Tuple[int, int]) -> object:
        prod = self.tables.grammar.productions[prod_index]
        if prod.builder is not None:
            return prod.builder(children, span)
        if len(children) == 1:
            return children[0]
        return children

    def _viable_terminals(self, state_stack: Sequence[int]) -> Set[str]:
        """Terminals shiftable from any state currently on the stack.

        This is the standard "viable prefix" test used for LR error recovery:
        if the offending symbol belongs to this set, popping states (i.e.
        discarding part of the parse) re-enables a shift for that symbol.
        """
        viable: Set[str] = set()
        for state in state_stack:
            viable |= self._shift_terminals.get(state, set())
        return viable

    def parse(self, tokens: Sequence[Token], source: str = "") -> ParseResult:
        grammar = self.tables.grammar
        diagnostics: List[Diagnostic] = []
        stats = ParseStats()

        # The lexer may emit INVALID tokens; they were already reported by the
        # lexer, so the parser consumes them silently and never tries to shift
        # them (they are not part of the terminal alphabet).
        stream: List[Token] = [t for t in tokens if t.kind != INVALID]
        if not stream or stream[-1].kind != EOF:
            last = stream[-1] if stream else None
            stream.append(
                Token(
                    kind=EOF,
                    text="",
                    line=last.end_line if last else 1,
                    col=last.end_col if last else 1,
                    offset=last.end_offset if last else 0,
                    end_offset=last.end_offset if last else 0,
                )
            )

        state_stack: List[int] = [0]
        value_stack: List[object] = []
        pos = 0
        errors = 0

        while True:
            stats.steps += 1
            if stats.steps > self.max_steps:
                token = stream[min(pos, len(stream) - 1)]
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="SYN010",
                        message="parse aborted: step limit exceeded",
                        line=token.line,
                        col=token.col,
                        offset=token.offset,
                        end_offset=token.end_offset,
                        phase="parser",
                        detail=f"the parser executed more than {self.max_steps} table steps; "
                        "the input is too deeply nested or too large for this analysis budget",
                    )
                )
                break

            token = stream[pos]
            terminal = END if token.kind == EOF else token.kind
            state = state_stack[-1]
            action = self.tables.action.get((state, terminal))

            if action is None:
                # ---- error ------------------------------------------------
                errors += 1
                if errors > self.max_errors:
                    diagnostics.append(
                        Diagnostic(
                            severity="error",
                            code="SYN011",
                            message=f"too many syntax errors ({self.max_errors}); parsing stopped",
                            line=token.line,
                            col=token.col,
                            offset=token.offset,
                            end_offset=token.end_offset,
                            phase="parser",
                        )
                    )
                    break
                new_pos, popped = self._report_and_recover(
                    diagnostics, stream, pos, state_stack, value_stack, stats
                )
                stats.recovered += 1
                if new_pos == pos and not popped:
                    # No progress can be made; stop instead of looping.
                    break
                pos = new_pos
                continue

            # ---- shift / reduce / accept --------------------------------
            if action.kind == SHIFT:
                state_stack.append(action.value)
                value_stack.append(token)
                pos += 1
                stats.shifts += 1
                stats.max_stack_depth = max(stats.max_stack_depth, len(state_stack))
                if self.trace_limit and len(self.trace) < self.trace_limit:
                    self.trace.append(f"shift  {token.display()} -> state {action.value}")
                continue

            if action.kind == REDUCE:
                prod = grammar.productions[action.value]
                n = len(prod.rhs)
                if n:
                    children = value_stack[-n:]
                    del value_stack[-n:]
                    del state_stack[-n:]
                    span = _span_of(children, token)
                else:
                    children = []
                    span = (token.offset, token.offset)
                value = self._reduce_value(action.value, children, span)
                goto_state = self.tables.goto.get((state_stack[-1], prod.lhs))
                if goto_state is None:  # pragma: no cover - table consistency guard
                    raise ParserTableError(
                        f"missing GOTO[{state_stack[-1]}, {prod.lhs}] while reducing {prod.display()}"
                    )
                state_stack.append(goto_state)
                value_stack.append(value)
                stats.reductions += 1
                if self.trace_limit and len(self.trace) < self.trace_limit:
                    self.trace.append(f"reduce {prod.display()} -> state {goto_state}")
                continue

            # ACCEPT
            # ``accepted`` means "the input parsed without error recovery".
            # A parse that reached the accept state only after skipping tokens
            # is explicitly *not* accepted: the tree is returned (partial
            # results are still useful) but callers must treat the analysis as
            # incomplete rather than as a clean parse.
            tree = value_stack[-1] if value_stack else None
            return ParseResult(
                tree=tree,
                diagnostics=diagnostics,
                stats=stats,
                tokens=stream,
                accepted=stats.recovered == 0,
                trace=list(self.trace),
            )

        return ParseResult(
            tree=None,
            diagnostics=diagnostics,
            stats=stats,
            tokens=stream,
            accepted=False,
            trace=list(self.trace),
        )

    # ------------------------------------------------------------------
    def _report_and_recover(
        self,
        diagnostics: List[Diagnostic],
        stream: List[Token],
        pos: int,
        state_stack: List[int],
        value_stack: List[object],
        stats: ParseStats,
    ) -> Tuple[int, bool]:
        """Report a syntax error and restore a parsable configuration.

        Returns ``(new_input_position, popped_states)``.  When neither the
        position nor the stack changes, the caller stops: a recovery step that
        cannot make progress must not be retried forever.
        """
        token = stream[pos]
        terminal = END if token.kind == EOF else token.kind
        state = state_stack[-1]
        expected = sorted(
            {t for (s, t), a in self.tables.action.items() if s == state and a.kind in (SHIFT, ACCEPT)}
        )
        expected_txt = ", ".join(
            "end of file" if t == END else display_kind(t) for t in expected[:6]
        ) or "nothing (the parser cannot continue from this state)"

        if token.kind == "UNSUPPORTED_KW":
            code, message = "SYN100", f"unsupported construct: keyword '{token.text}'"
            detail = (
                "the analysed language subset does not define this keyword. CodeTrace does not "
                "guess the meaning of unsupported syntax: the enclosing statement is skipped and "
                "marked as unanalysed."
            )
        elif token.kind == EOF:
            code, message = "SYN001", "unexpected end of file"
            detail = "the input ended while the parser expected more tokens"
        else:
            code, message = "SYN001", f"unexpected {token.display()}"
            detail = f"the parser expected one of: {expected_txt}"

        diagnostics.append(
            Diagnostic(
                severity="error",
                code=code,
                message=message,
                line=token.line,
                col=token.col,
                offset=token.offset,
                end_offset=token.end_offset,
                phase="parser",
                detail=detail,
                unsupported=(token.kind == "UNSUPPORTED_KW"),
            )
        )

        # 1) An unsupported keyword or a stray invalid token: skip the whole
        #    statement so that one unsupported construct does not produce a
        #    cascade of spurious errors.
        if token.kind == "UNSUPPORTED_KW" or token.kind == INVALID:
            depth = 0
            while pos < len(stream):
                current = stream[pos]
                if current.kind == EOF:
                    break
                if current.kind in ("LPAREN", "LBRACE", "LBRACKET"):
                    depth += 1
                elif current.kind in ("RPAREN", "RBRACE", "RBRACKET"):
                    depth -= 1
                if depth <= 0 and current.kind == "SEMI":
                    pos += 1
                    break
                if depth < 0 and current.kind == "RBRACE":
                    break
                pos += 1
            return (pos, False)

        if token.kind == EOF:
            return (pos, False)

        # 2) Standard viable-prefix recovery: if the lookahead can be shifted
        #    from some state on the stack, pop until that state is on top.
        viable = self._viable_terminals(state_stack)
        if terminal in viable and len(state_stack) > 1:
            while len(state_stack) > 1:
                state_stack.pop()
                if value_stack:
                    value_stack.pop()
                stats.max_stack_depth = max(stats.max_stack_depth, len(state_stack))
                top = state_stack[-1]
                act = self.tables.action.get((top, terminal))
                if act is not None and act.kind == SHIFT:
                    return (pos, True)
            return (pos, True)

        # 3) Otherwise discard the offending token and continue.
        if pos < len(stream) - 1:
            return (pos + 1, False)
        return (pos, False)


def _span_of(children: Sequence[object], lookahead: Token) -> Tuple[int, int]:
    """Compute the source span covered by a reduction."""
    bounds: List[Tuple[int, int]] = []

    def collect(child: object) -> None:
        if isinstance(child, Token):
            bounds.append((child.offset, child.end_offset))
            return
        span = getattr(child, "span", None)
        if isinstance(span, tuple) and len(span) == 2:
            bounds.append((span[0], span[1]))
            return
        if isinstance(child, (list, tuple)):
            for item in child:
                collect(item)

    for child in children:
        collect(child)
    if not bounds:
        return (lookahead.offset, lookahead.offset)
    return (min(b[0] for b in bounds), max(b[1] for b in bounds))
