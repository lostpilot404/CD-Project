"""Taint analysis: sources, sinks, sanitizers, interprocedural propagation.

Taint state
-----------
The state of the analysis is a mapping from symbol id to a set of **taint
atoms**.  An atom is a triple ``(origin, context)`` written as text:

* ``src:<source-rule-id>@<context>`` -- data introduced by a configured source,
* ``param:<function>.<index>@<context>`` -- the *i*-th parameter of a function
  (used to compute function summaries),
* ``glob:<function>@<context>`` -- a file-scope variable.

Contexts (``command``, ``sql``, ``path``, ``html``, ``numeric``, ``format``)
are what make sanitisation context-sensitive: ``shell_escape(x)`` removes the
``@command`` atoms of ``x`` and leaves the others, so the same value is still
reported when it reaches a SQL sink.  A source produces atoms in every context
listed in its declaration; a sanitizer removes atoms in the context it
declares (or in every context when declared with ``*``).

Propagation
-----------
Taint is a **may** analysis: the meet operator is set union, so a value is
tainted if *any* path could taint it.  Within a function the analysis replays
each basic block statement by statement from the block's IN state.

Calls are handled with context-insensitive **function summaries**:

* ``RET[F]`` -- the set of ``(parameter index, context)`` pairs such that the
  parameter can influence the value returned by ``F``.  Computed by running
  the intraprocedural analysis with every parameter tainted by its own
  symbolic atom and observing what reaches the return statements; iterated to
  a fixed point so that recursion is handled.
* at a call site ``y = F(a1..an)`` the taint of ``y`` is the union of the
  taint of ``a_i`` for those ``i`` that appear in ``RET[F]``.

Calls to functions that are neither defined in the file nor in the rule set are
**unknown**: their result is tainted when any argument is tainted, and they are
never assumed to validate anything.

Limitations are documented in ``docs/LIMITATIONS.md``: context-insensitivity
means a parameter tainted by one caller is treated as tainted in every caller;
pointer aliasing is not modelled; guards are recognised only in the simple
forms described in :meth:`TaintProblem.edge_transfer`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..frontend.ast_nodes import (
    Assign,
    BinaryOp,
    Block,
    BoolLit,
    Call,
    CharLit,
    EmptyStmt,
    ExprStmt,
    FloatLit,
    ForStmt,
    FunctionDecl,
    Ident,
    IfStmt,
    Index,
    IntLit,
    Node,
    ReturnStmt,
    SourceUnit,
    StringLit,
    UnaryOp,
    VarDecl,
    WhileStmt,
)
from ..rules.model import CONTEXTS, ALL_CONTEXTS, RuleSet, SanitizerRule, SinkRule, SourceRule
from .accesses import statement_accesses
from .cfg import CFG, BasicBlock, expression_text
from .dataflow import BitVectorDomain, DataFlowProblem, DataFlowResult, solve

# ----------------------------------------------------------------------
# Atoms
# ----------------------------------------------------------------------
SOURCE_PREFIX = "src"
PARAM_PREFIX = "param"
GLOBAL_PREFIX = "glob"


#: Reserved lattice cell that carries the atoms of an *expression* which is not
#: stored in any variable, for example the argument of ``system(input())`` or the
#: value passed by ``run(input())``.  Without it a function that declares neither
#: a variable nor a parameter would have an empty domain, and no source atom
#: could be represented anywhere -- which silently hid real flows.
EXPRESSION_SYMBOL = -1
EXPRESSION_NAME = "<expression>"


def source_atom(rule_id: str, context: str) -> str:
    return f"{SOURCE_PREFIX}:{rule_id}@{context}"


def param_atom(function: str, index: int, context: str) -> str:
    return f"{PARAM_PREFIX}:{function}.{index}@{context}"


def global_atom(name: str, context: str) -> str:
    return f"{GLOBAL_PREFIX}:{name}@{context}"


def atom_context(atom: str) -> str:
    return atom.split("@", 1)[1] if "@" in atom else ""


def atom_origin(atom: str) -> Tuple[str, str]:
    """``(kind, name)``: ``("src", rule_id)``, ``("param", "f.0")`` or ``("glob", "x")``."""
    head, _, _context = atom.partition("@")
    kind, _, name = head.partition(":")
    return kind, name


# ----------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------
@dataclass
class SinkHit:
    """A sink call whose sensitive argument carries taint atoms."""

    sid: int
    node: Call
    rule: SinkRule
    argument_index: int
    expression: Node
    atoms: Tuple[str, ...]
    function: str
    block: int
    #: Statement-level state before the statement (used by the explainer).
    in_state: int = 0

    def to_json(self) -> dict:
        return {
            "sid": self.sid,
            "sink_rule": self.rule.id,
            "function": self.rule.function,
            "argument_index": self.argument_index,
            "line": getattr(self.expression, "line", 0),
            "col": getattr(self.expression, "col", 0),
            "atoms": list(self.atoms),
            "context": self.rule.context,
            "block": self.block,
            "enclosing_function": self.function,
        }


@dataclass
class CallSite:
    """A recorded call, used for interprocedural propagation and explanation."""

    caller: str
    callee: str
    node: Call
    sid: int
    argument_atoms: List[Tuple[str, ...]]
    atoms_used: Tuple[str, ...]
    block: int
    in_state: int


@dataclass
class FunctionRun:
    """Result of the intraprocedural taint analysis of one function."""

    function: str
    converged: bool
    iterations: int
    statement_in: Dict[int, int] = field(default_factory=dict)
    statement_out: Dict[int, int] = field(default_factory=dict)
    block_in: Dict[int, int] = field(default_factory=dict)
    block_out: Dict[int, int] = field(default_factory=dict)
    hits: List[SinkHit] = field(default_factory=list)
    call_sites: List[CallSite] = field(default_factory=list)
    return_atoms: Tuple[str, ...] = ()
    global_writes: Dict[str, Tuple[str, ...]] = field(default_factory=dict)


@dataclass
class TaintResult:
    runs: Dict[str, FunctionRun] = field(default_factory=dict)
    ret_params: Dict[str, Dict[int, Set[str]]] = field(default_factory=dict)
    param_atoms: Dict[str, Dict[int, Set[str]]] = field(default_factory=dict)
    global_atoms: Dict[str, Set[str]] = field(default_factory=dict)
    hits: List[SinkHit] = field(default_factory=list)
    iterations: int = 0
    converged: bool = True
    infeasible_edges: List[dict] = field(default_factory=list)
    #: Flows that a **declared validator guard** cleared before the sink was
    #: reached.  Each entry says which validator, on which edge, removed which
    #: atoms for which symbol, so the suppression can be shown as an assumption
    #: instead of disappearing into "no taint reached this sink".
    guard_suppressions: List[dict] = field(default_factory=list)
    #: The final :class:`TaintProblem` per function (state queries, explainer).
    problems: Dict[str, object] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    engine_version: str = "taint-1"

    def statements_for(self, function: str) -> Dict[int, int]:
        run = self.runs.get(function)
        return run.statement_in if run else {}

    def to_json(self) -> dict:
        return {
            "engine_version": self.engine_version,
            "iterations": self.iterations,
            "converged": self.converged,
            "functions": {
                name: {
                    "converged": run.converged,
                    "iterations": run.iterations,
                    "hits": [h.to_json() for h in run.hits],
                    "call_sites": len(run.call_sites),
                }
                for name, run in self.runs.items()
            },
            "summaries": {
                fn: {str(index): sorted(contexts) for index, contexts in params.items()}
                for fn, params in self.ret_params.items()
            },
            "infeasible_branches": list(self.infeasible_edges),
            "guard_suppressions": list(self.guard_suppressions),
            "notes": list(self.notes),
        }


# ----------------------------------------------------------------------
# Taint problem for one function
# ----------------------------------------------------------------------
class TaintProblem(DataFlowProblem):
    """Block-level taint data flow for a single function."""

    def __init__(
        self,
        cfg: CFG,
        symbols: Sequence[Tuple[int, str]],
        atom_space: Sequence[str],
        engine: "TaintEngine",
        entry_atoms: int = 0,
        param_symbols: Sequence[Tuple[int, int]] = (),
    ) -> None:
        domain_symbols = [tuple(entry) for entry in symbols] + [(EXPRESSION_SYMBOL, EXPRESSION_NAME)]
        domain_atoms = [
            f"{symbol_id}|{atom}" for symbol_id, _name in domain_symbols for atom in atom_space
        ]
        domain = BitVectorDomain(atoms=domain_atoms, name=f"taint of {cfg.function}")
        super().__init__(cfg=cfg, domain=domain)
        self.name = f"taint:{cfg.function}"
        self.direction = "forward"
        self.engine = engine
        self.atom_space = list(atom_space)
        self.symbol_names = {symbol_id: name for symbol_id, name in symbols}
        self.symbols = [symbol_id for symbol_id, _ in symbols]
        # Mask of the atoms belonging to each symbol.
        self.symbol_masks: Dict[int, int] = {}
        for symbol_id in self.symbols:
            mask = 0
            for atom in atom_space:
                mask |= domain.singleton(f"{symbol_id}|{atom}")
            self.symbol_masks[symbol_id] = mask
        self.entry_atoms = entry_atoms
        self.param_symbols = list(param_symbols)
        self.guards: Dict[Tuple[int, int], List[Tuple[int, str]]] = {}
        #: ``(src, dst) -> [detail]`` for the guards on that edge, so a
        #: suppression can be reported with the validator that caused it.
        self.guard_details: Dict[Tuple[int, int], List[dict]] = {}
        self.infeasible_edges: Set[Tuple[int, int]] = set()
        self._collect_edges()
        self._reachable = self._compute_reachable()
        self.collected_hits: List[SinkHit] = []
        self.collected_calls: List[CallSite] = []
        self.global_writes: Dict[int, int] = {}
        self.block_in: Dict[int, int] = {}
        self.block_out: Dict[int, int] = {}
        self.statement_in: Dict[int, int] = {}
        self.statement_out: Dict[int, int] = {}
        self.final_block_out: Dict[int, int] = {}
        #: Hits and call sites are only recorded during the final replay, so
        #: the fixed-point iterations stay cheap and do not accumulate garbage.
        self.collecting: bool = False
        #: Bits of the expression cell: every atom has one there, so a source or
        #: parameter atom is representable even when the function declares no
        #: variable of its own.
        self.expression_mask = 0
        for atom in atom_space:
            self.expression_mask |= domain.singleton(f"{EXPRESSION_SYMBOL}|{atom}")
        #: Bare atom text -> OR of that atom's bits (expression cell included).
        #: ``retarget`` masks this down to one symbol's bits before a value is
        #: stored, so the expression cell never leaks into a variable.
        self.atom_bits: Dict[str, int] = {}
        for atom in atom_space:
            bits = domain.singleton(f"{EXPRESSION_SYMBOL}|{atom}")
            for symbol_id in self.symbols:
                bits |= domain.singleton(f"{symbol_id}|{atom}")
            self.atom_bits[atom] = bits

    # -- state helpers ---------------------------------------------------
    def get(self, state: int, symbol_id: int) -> int:
        """Atoms of one symbol, expressed in that symbol's own bit range."""
        return state & self.symbol_masks.get(symbol_id, 0)

    def retarget(self, atoms: int, symbol_id: int) -> int:
        """Re-express an expression's atoms in terms of ``symbol_id``'s bits.

        An expression's taint is a set of *atoms* together with the symbols the
        values came from; storing it into an assignment target must move the
        atoms into the target symbol's bit range.  Skipping this step is the
        classic taint-analysis bug that silently loses taint on every
        assignment between differently-named variables.
        """
        if atoms == 0:
            return 0
        target_mask = self.symbol_masks.get(symbol_id, 0)
        if target_mask == 0:
            return 0
        result = 0
        for text in self.atom_texts(atoms):
            result |= self.atom_bits.get(text, 0) & target_mask
        return result

    def set(self, state: int, symbol_id: int, atoms: int) -> int:
        """Overwrite the atoms of ``symbol_id`` with the atoms of ``atoms``."""
        mask = self.symbol_masks.get(symbol_id, 0)
        return (state & ~mask) | self.retarget(atoms, symbol_id)

    def add(self, state: int, symbol_id: int, atoms: int) -> int:
        """Add the atoms of ``atoms`` to the atoms already stored for ``symbol_id``."""
        return state | self.retarget(atoms, symbol_id)

    def atom_texts(self, value: int) -> Set[str]:
        out: Set[str] = set()
        for atom in self.domain.atoms_of(value):
            _symbol, _, text = atom.partition("|")
            out.add(text)
        return out

    def find_atom_bit(self, text: str) -> int:
        """Bit mask for a *bare* atom text (the atom is symbol-independent)."""
        return self.atom_bits.get(text, 0)

    # -- graph edges -----------------------------------------------------
    def _collect_edges(self) -> None:
        for block in self.cfg.sorted_blocks():
            for edge in block.successors:
                guard, details = self._guard_on_edge(block, edge)
                if guard:
                    self.guards[(block.id, edge.dst)] = guard
                    self.guard_details[(block.id, edge.dst)] = details
                if edge.kind in ("true", "false") and self._is_constant(edge):
                    self.infeasible_edges.add((block.id, edge.dst))

    def _is_constant(self, edge) -> bool:
        """A branch whose condition is a literal is decided statically."""
        condition = edge.condition.strip()
        if edge.kind == "true" and condition in ("false", "0"):
            return True
        if edge.kind == "false" and condition in ("true", "1"):
            return True
        return False

    def _guard_on_edge(self, block: BasicBlock, edge) -> Tuple[List[Tuple[int, str]], List[dict]]:
        """Validator guards carried by an ``if``/``while`` condition.

        Only two forms are recognised, because recognising more would require
        real path-sensitive reasoning:

        * ``if (validator(x))``  guards the **true** edge,
        * ``if (!validator(x))`` guards the **false** edge.

        Anything else (``&&``, ``||``, comparisons) guards neither edge.
        """
        statement = block.statements[-1] if block.statements else None
        if statement is None or not isinstance(statement, (IfStmt, WhileStmt)):
            return [], []
        cond = statement.cond
        if cond is None:
            return [], []
        negated = False
        if isinstance(cond, UnaryOp) and cond.op == "!":
            negated = True
            cond = cond.operand
        if not isinstance(cond, Call) or cond.callee is None:
            return [], []
        rules = self.engine.rules.sanitizer_rules(cond.name)
        validators = [r for r in rules if r.kind == "validator"]
        if not validators:
            return [], []
        applies_to = "false" if negated else "true"
        if edge.kind != applies_to:
            return [], []
        guard: List[Tuple[int, str]] = []
        details: List[dict] = []
        for validator in validators:
            if validator.argument >= len(cond.args):
                continue
            target = cond.args[validator.argument]
            symbol_id = target.symbol_id if isinstance(target, Ident) else -1
            if symbol_id < 0:
                # Only simple identifiers are refined; guards on compound
                # expressions are reported as unmodelled rather than guessed.
                self.engine.note(
                    "validator argument is not a plain variable; the guard is not applied"
                )
                continue
            guard.append((symbol_id, validator.context))
            details.append(
                {
                    "symbol_id": symbol_id,
                    "symbol": target.name,
                    "context": validator.context,
                    "validator": validator.id,
                    "validator_function": cond.name,
                    "negated": negated,
                    "guard_edge": edge.kind,
                    "statement_sid": statement.sid,
                    "line": statement.line,
                    "col": statement.col,
                    "statement_text": self.engine.program.statement_text(statement.sid),
                    "condition": edge.condition,
                }
            )
        return guard, details

    def _compute_reachable(self) -> Set[int]:
        seen: Set[int] = set()
        stack = [self.cfg.entry] if self.cfg.entry in self.cfg.blocks else []
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            for edge in self.cfg.block(current).successors:
                if (current, edge.dst) in self.infeasible_edges:
                    continue
                if edge.dst not in seen:
                    stack.append(edge.dst)
        return seen

    def reachable_blocks(self) -> Set[int]:
        return self._reachable

    # -- data-flow interface ----------------------------------------------
    def successors(self, block_id: int) -> List[int]:
        return sorted(
            e.dst for e in self.cfg.block(block_id).successors
            if (block_id, e.dst) not in self.infeasible_edges
        )

    def predecessors(self, block_id: int) -> List[int]:
        return sorted(
            p for p in self.cfg.block(block_id).predecessors
            if (p, block_id) not in self.infeasible_edges
        )

    def boundary_value(self, block_id: int) -> int:
        return self.entry_atoms

    def initial_value(self, block_id: int) -> int:
        return 0

    def meet(self, values: List[int]) -> int:
        result = 0
        for value in values:
            result |= value
        return result

    def edge_transfer(self, src: int, dst: int, value: int) -> int:
        guard = self.guards.get((src, dst))
        if not guard:
            return value
        refined = value
        for symbol_id, context in guard:
            atoms = self.get(refined, symbol_id)
            refined = self.set(refined, symbol_id, self._remove_context(atoms, context))
        return refined

    def _remove_context(self, atoms: int, context: str) -> int:
        if context == ALL_CONTEXTS:
            return 0
        result = atoms
        for text in self.atom_texts(atoms):
            if atom_context(text) == context:
                result &= ~self.find_atom_bit(text)
        return result

    def transfer(self, block_id: int, in_value: int) -> int:
        state = in_value
        for statement in self.cfg.block(block_id).statements:
            state = self.engine.transfer_statement(self, statement, state)
        return state

    # ------------------------------------------------------------------
    def replay(self) -> None:
        """Walk every block statement by statement, collecting hits/calls.

        This runs after the fixed point, so the collected results correspond to
        the converged solution.  The replay is deterministic: the same final IN
        values always produce the same hits, call sites and per-statement
        states.
        """
        self.collected_hits = []
        self.collected_calls = []
        self.global_writes = {}
        self.statement_in = {}
        self.statement_out = {}
        # Sink hits are recorded only while the statements are replayed in
        # order; auxiliary evaluations (return values, global writes) re-use the
        # same expression evaluator and must not duplicate hits.
        self.collecting = True
        for block in self.cfg.sorted_blocks():
            if block.id not in self._reachable:
                continue
            state = self.block_in.get(block.id, 0)
            for statement in block.statements:
                self.statement_in[statement.sid] = state
                state = self.engine.transfer_statement(self, statement, state)
                self.statement_out[statement.sid] = state
        self.final_block_out = {
            block.id: self.block_out.get(block.id, 0) for block in self.cfg.sorted_blocks()
        }
        # The statement walk is over: auxiliary evaluations that re-use the
        # expression evaluator (return values, global writes) must not add hits.
        self.collecting = False

# ----------------------------------------------------------------------
# Engine
# ----------------------------------------------------------------------
class TaintEngine:
    """Whole-program taint analysis driven by a validated rule set."""

    def __init__(self, program) -> None:
        # ``program`` is a codetrace.analysis.pipeline.Program (duck-typed to
        # avoid a circular import).
        self.program = program
        self.rules: RuleSet = program.rules
        self.notes: List[str] = []
        self._symbols_by_function: Dict[str, List[Tuple[int, str]]] = {}
        self._globals: List[Tuple[int, str]] = []
        self._prepare_symbols()

    # ------------------------------------------------------------------
    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def _prepare_symbols(self) -> None:
        symbols = self.program.semantic.symbols
        for name, cfg in self.program.cfgs.items():
            entries: List[Tuple[int, str]] = []
            for symbol in symbols:
                if symbol.kind in ("parameter", "variable", "array") and symbol.function == name:
                    entries.append((symbol.id, symbol.name))
            self._symbols_by_function[name] = entries
        self._globals = [
            (symbol.id, symbol.name)
            for symbol in symbols
            if symbol.is_global and symbol.kind in ("variable", "array")
        ]

    def _atom_space(self, function: str, symbolic_params: bool) -> List[str]:
        """Taint atoms relevant to one function's analysis."""
        atoms: List[str] = []
        for source in self.rules.sources.values():
            for context in source.contexts:
                atoms.append(source_atom(source.id, context))
        if symbolic_params:
            parameters = self.program.functions.get(function)
            count = len(parameters.params) if parameters else 0
            for index in range(count):
                for context in CONTEXTS:
                    atoms.append(param_atom(function, index, context))
        for _symbol_id, name in self._globals:
            for context in CONTEXTS:
                atoms.append(global_atom(name, context))
        return atoms

    # ------------------------------------------------------------------
    def _build_problem(self, function: str, symbolic_params: bool, param_state: int, ret_params) -> TaintProblem:
        cfg = self.program.cfgs[function]
        symbols = self._symbols_by_function.get(function, [])
        problem = TaintProblem(
            cfg=cfg,
            symbols=symbols,
            atom_space=self._atom_space(function, symbolic_params),
            engine=self,
        )
        problem.ret_params = ret_params
        return problem

    def _entry_state(self, problem: TaintProblem, function: str, symbolic_params: bool,
                     param_atoms: Dict[int, Set[str]], global_atoms: Dict[str, Set[str]]) -> int:
        state = 0
        declaration = self.program.functions.get(function)
        if declaration is not None:
            for index, param in enumerate(declaration.params):
                if param.symbol_id < 0:
                    continue
                if symbolic_params:
                    atoms = {
                        param_atom(function, index, context): True for context in CONTEXTS
                    }
                else:
                    atoms = {atom: True for atom in param_atoms.get(index, set())}
                state = self._add_atoms(problem, state, param.symbol_id, atoms)
        for symbol_id, name in self._globals:
            payload = global_atoms.get(name, set())
            state = self._add_atoms(problem, state, symbol_id, {atom: True for atom in payload})
        return state

    def _add_atoms(self, problem: TaintProblem, state: int, symbol_id: int, atoms: Dict[str, bool]) -> int:
        for text in atoms:
            try:
                state = problem.add(state, symbol_id, problem.domain.singleton(f"{symbol_id}|{text}"))
            except Exception:
                continue
        return state

    # ------------------------------------------------------------------
    def run(self, max_iterations: int = 12) -> TaintResult:
        result = TaintResult()
        functions = list(self.program.cfgs)
        if not functions:
            return result

        # ---- phase 1: summaries (parameter -> return-value influence) ----
        ret_params: Dict[str, Dict[int, Set[str]]] = {name: {} for name in functions}
        for iteration in range(max_iterations):
            changed = False
            for name in functions:
                summary = self._run_symbolic(name, ret_params)
                for index, contexts in summary.items():
                    bucket = ret_params.setdefault(name, {}).setdefault(index, set())
                    if not contexts <= bucket:
                        bucket |= contexts
                        changed = True
            result.iterations = iteration + 1
            if not changed:
                break
        result.ret_params = ret_params

        # ---- phase 2: concrete interprocedural propagation ---------------
        param_atoms: Dict[str, Dict[int, Set[str]]] = {name: {} for name in functions}
        global_atoms: Dict[str, Set[str]] = {}
        runs: Dict[str, FunctionRun] = {}
        converged = False
        for _iteration in range(max_iterations):
            changed = False
            proposed_param: Dict[str, Dict[int, Set[str]]] = {}
            proposed_global: Dict[str, Set[str]] = {}
            for name in functions:
                run = self._run_concrete(name, param_atoms.get(name, {}), global_atoms, ret_params)
                runs[name] = run
                for call in run.call_sites:
                    for index, atoms in enumerate(call.argument_atoms):
                        if not atoms:
                            continue
                        bucket = proposed_param.setdefault(call.callee, {}).setdefault(index, set())
                        bucket |= set(atoms)
                for global_name, atoms in run.global_writes.items():
                    proposed_global.setdefault(global_name, set()).update(atoms)
            # Merge the newly discovered taint; anything genuinely new keeps
            # the iteration running.
            for name, params in proposed_param.items():
                for index, atoms in params.items():
                    bucket = param_atoms.setdefault(name, {}).setdefault(index, set())
                    fresh = atoms - bucket
                    if fresh:
                        bucket |= fresh
                        changed = True
            for name, atoms in proposed_global.items():
                bucket = global_atoms.setdefault(name, set())
                fresh = atoms - bucket
                if fresh:
                    bucket |= fresh
                    changed = True
            result.iterations += 1
            if not changed:
                converged = True
                break

        # ---- final run with the converged inputs -------------------------
        final_runs: Dict[str, FunctionRun] = {}
        for name in functions:
            run, problem = self._run_concrete(
                name, param_atoms.get(name, {}), global_atoms, ret_params, want_problem=True
            )
            final_runs[name] = run
            result.problems[name] = problem
        result.runs = final_runs
        result.param_atoms = param_atoms
        result.global_atoms = global_atoms
        result.converged = converged
        result.hits = [hit for run in final_runs.values() for hit in run.hits]
        result.infeasible_edges = self._infeasible_report()
        result.guard_suppressions = self._guard_suppression_report(result.problems)
        result.notes = list(self.notes)
        result.notes.append(
            "Interprocedural propagation is context-insensitive: a parameter that is tainted "
            "at one call site is analysed as tainted at every call site of that function."
        )
        if not converged:
            result.notes.append(
                "The interprocedural taint fixpoint did not converge within the iteration budget; "
                "results are a conservative approximation of the current iteration."
            )
        # Branches whose condition is a literal and therefore decidable without
        # running the program.  They are reported so that "not found" is
        # explained rather than silent.
        result.infeasible_edges = self._infeasible_report()
        if result.infeasible_edges:
            result.notes.append(
                f"{len(result.infeasible_edges)} branch(es) were statically pruned because their "
                "condition is a literal constant; statements in those branches are not analysed "
                "as reachable (see infeasible_branches)."
            )
        if result.guard_suppressions:
            validators = sorted({entry["validator"] for entry in result.guard_suppressions})
            atoms_cleared = sum(len(entry["removed_atoms"]) for entry in result.guard_suppressions)
            result.notes.append(
                f"{atoms_cleared} taint atom(s) were cleared on {len(result.guard_suppressions)} "
                f"declared validator guard(s) ({', '.join(validators)}): CodeTrace does not analyse "
                "the validator's implementation and assumes it rejects every value unsafe for its "
                "context (see guard_suppressions).  A cleared atom only means 'nothing reported' "
                "where a sink consumes that symbol on the guarded edge; the run's dispositions say "
                "which sink calls that applies to."
            )
        return result

    def _guard_suppression_report(self, problems: Dict[str, object]) -> List[dict]:
        """Which declared validator guards actually cleared taint, and where.

        The guards are applied on the ``true``/``false`` edge of an ``if`` whose
        condition calls a rule-declared validator.  A suppression is only worth
        reporting when the guard *really* removed an atom, so the check runs
        after the fixpoint, on the predecessor's converged OUT value.

        Recording it matters because of what it implies: CodeTrace never looks at
        the validator's implementation, so a suppressed flow is not "no flow was
        found" -- it is "a flow was found and a declared validator is assumed to
        reject it".  Without this record the run would report nothing and explain
        nothing.
        """
        report: List[dict] = []
        for function, problem in sorted(problems.items()):
            if problem is None:
                continue
            for (src, dst), details in sorted(problem.guard_details.items()):
                value = problem.block_out.get(src, 0)
                for detail in details:
                    atoms = problem.atom_texts(problem.get(value, detail["symbol_id"]))
                    removed = sorted(
                        text
                        for text in atoms
                        if atom_context(text) == detail["context"]
                    )
                    if not removed:
                        continue
                    entry = dict(detail)
                    entry["function"] = function
                    entry["from_block"] = src
                    entry["to_block"] = dst
                    entry["removed_atoms"] = removed
                    entry["assumption"] = (
                        "the validator is declared by the rule set and its implementation is "
                        "not analysed: CodeTrace assumes it rejects every value that is unsafe "
                        f"for context {detail['context']!r}"
                    )
                    report.append(entry)
        return report

    def _infeasible_report(self) -> List[dict]:
        out: List[dict] = []
        for name, cfg in self.program.cfgs.items():
            for block in cfg.sorted_blocks():
                for edge in block.successors:
                    if edge.condition.strip() in ("false", "0") and edge.kind == "true":
                        out.append(
                            {
                                "function": name,
                                "from": block.id,
                                "to": edge.dst,
                                "reason": f"condition '{edge.condition}' is a constant that makes this branch impossible",
                            }
                        )
        return out

    # ------------------------------------------------------------------
    def _run_symbolic(self, function: str, ret_params) -> Dict[int, Set[str]]:
        """Determine which parameters can influence the return value."""
        problem = self._build_problem(function, symbolic_params=True, param_state=0, ret_params=ret_params)
        entry = self._entry_state(problem, function, symbolic_params=True, param_atoms={}, global_atoms={})
        problem.entry_atoms = entry
        outcome = solve(problem)
        problem.block_in = outcome.in_values
        problem.block_out = outcome.out_values
        problem.replay()
        influence: Dict[int, Set[str]] = {}
        for block in problem.cfg.sorted_blocks():
            if block.id not in problem._reachable:
                continue
            for statement in block.statements:
                if isinstance(statement, ReturnStmt) and statement.value is not None:
                    state = problem.statement_in.get(statement.sid, 0)
                    atoms = problem.atom_texts(self.eval_expr(problem, statement.value, state, None))
                    for atom in atoms:
                        kind, name = atom_origin(atom)
                        if kind != PARAM_PREFIX:
                            continue
                        _fn, _, index = name.partition(".")
                        if index.isdigit() and _fn == function:
                            influence.setdefault(int(index), set()).add(atom_context(atom))
        return influence

    def _run_concrete(
        self,
        function: str,
        param_atoms: Dict[int, Set[str]],
        global_atoms: Dict[str, Set[str]],
        ret_params,
        want_problem: bool = False,
    ):
        problem = self._build_problem(function, symbolic_params=False, param_state=0, ret_params=ret_params)
        entry = self._entry_state(
            problem, function, symbolic_params=False, param_atoms=param_atoms, global_atoms=global_atoms
        )
        problem.entry_atoms = entry
        outcome = solve(problem)
        problem.block_in = outcome.in_values
        problem.block_out = outcome.out_values
        problem.replay()
        returns: Set[str] = set()
        for block in problem.cfg.sorted_blocks():
            if block.id not in problem._reachable:
                continue
            for statement in block.statements:
                if isinstance(statement, ReturnStmt) and statement.value is not None:
                    state = problem.statement_in.get(statement.sid, 0)
                    returns |= problem.atom_texts(self.eval_expr(problem, statement.value, state, None))
        global_writes: Dict[str, Set[str]] = {}
        for symbol_id, name in self._globals:
            atoms: Set[str] = set()
            for block in problem.cfg.sorted_blocks():
                if block.id not in problem._reachable:
                    continue
                atoms |= problem.atom_texts(problem.get(problem.block_out.get(block.id, 0), symbol_id))
            if atoms:
                global_writes[name] = atoms
        run = FunctionRun(
            function=function,
            converged=outcome.converged,
            iterations=outcome.iterations,
            statement_in=problem.statement_in,
            statement_out=problem.statement_out,
            block_in=problem.block_in,
            block_out=problem.block_out,
            hits=problem.collected_hits,
            call_sites=problem.collected_calls,
            return_atoms=tuple(sorted(returns)),
            global_writes={k: tuple(sorted(v)) for k, v in global_writes.items()},
        )
        return (run, problem) if want_problem else run

    # ------------------------------------------------------------------
    # Statement transfer
    # ------------------------------------------------------------------
    def transfer_statement(self, problem: TaintProblem, statement: Node, state: int) -> int:
        if statement is None or isinstance(statement, EmptyStmt):
            return state
        if isinstance(statement, VarDecl):
            for declarator in statement.declarators:
                if declarator.symbol_id < 0:
                    continue
                atoms = 0
                if declarator.init is not None:
                    atoms = self.eval_expr(problem, declarator.init, state, statement)
                # A declaration without an initialiser gives the variable no
                # value, so it carries no taint.
                state = problem.set(state, declarator.symbol_id, atoms)
            return state
        if isinstance(statement, ExprStmt):
            return self.transfer_expression(problem, statement.expr, state, statement)
        if isinstance(statement, ReturnStmt):
            if statement.value is not None:
                self.eval_expr(problem, statement.value, state, statement)
            return state
        if isinstance(statement, (IfStmt, WhileStmt, ForStmt)):
            if statement.cond is not None:
                self.eval_expr(problem, statement.cond, state, statement)
            if isinstance(statement, ForStmt) and statement.init is not None:
                state = self.transfer_statement(problem, statement.init, state)
            return state
        # Other statements carry no data-flow effect.
        return state

    def transfer_expression(self, problem: TaintProblem, expr: Node, state: int, statement: Node) -> int:
        if expr is None:
            return state
        if isinstance(expr, Assign):
            value = self.eval_expr(problem, expr.value, state, statement)
            symbol_id = self._target_symbol(expr.target)
            if symbol_id < 0:
                return state
            if expr.op == "=":
                if isinstance(expr.target, Index):
                    # Array elements are not tracked individually; the array
                    # symbol accumulates the taint of any element assigned.
                    return problem.add(state, symbol_id, value)
                return problem.set(state, symbol_id, value)
            # Compound assignment keeps the previous taint.
            return problem.add(state, symbol_id, value)
        if isinstance(expr, UnaryOp) and expr.op in ("++", "--"):
            # ``x++`` is a read of x: the taint of the counter flows into the
            # expression, so the value is evaluated for sink checking.
            self.eval_expr(problem, expr, state, statement)
            return state
        if isinstance(expr, Call):
            self.eval_expr(problem, expr, state, statement)
            return state
        self.eval_expr(problem, expr, state, statement)
        return state

    def _target_symbol(self, node: Optional[Node]) -> int:
        if isinstance(node, Ident):
            return node.symbol_id
        if isinstance(node, Index) and isinstance(node.base, Ident):
            return node.base.symbol_id
        return -1

    # ------------------------------------------------------------------
    # Expression evaluation
    # ------------------------------------------------------------------
    def eval_expr(self, problem: TaintProblem, expr: Optional[Node], state: int, statement: Optional[Node]) -> int:
        """Taint atoms (as a bit mask) of an expression evaluated in ``state``."""
        if expr is None:
            return 0
        if isinstance(expr, Ident):
            return problem.get(state, expr.symbol_id) if expr.symbol_id >= 0 else 0
        if isinstance(expr, (IntLit, FloatLit, CharLit, StringLit, BoolLit)):
            return 0
        if isinstance(expr, Index):
            return self.eval_expr(problem, expr.base, state, statement) | self.eval_expr(
                problem, expr.index, state, statement
            )
        if isinstance(expr, BinaryOp):
            return self.eval_expr(problem, expr.left, state, statement) | self.eval_expr(
                problem, expr.right, state, statement
            )
        if isinstance(expr, UnaryOp):
            return self.eval_expr(problem, expr.operand, state, statement)
        if isinstance(expr, Assign):
            return self.eval_expr(problem, expr.value, state, statement)
        if isinstance(expr, Call):
            return self._eval_call(problem, expr, state, statement)
        # Unknown expression form: report and treat as untainted but recorded.
        self.note(f"unsupported expression form {expr.kind}; its taint is not modelled")
        return 0

    def _eval_call(self, problem: TaintProblem, call: Call, state: int, statement: Optional[Node]) -> int:
        argument_atoms = [self.eval_expr(problem, arg, state, statement) for arg in call.args]
        sources = self.rules.source_rules(call.name)
        sanitizers = self.rules.sanitizer_rules(call.name)
        sinks = self.rules.sink_rules(call.name)
        result_atoms = 0

        # 1) sink check -------------------------------------------------
        if sinks and problem.collecting:
            for sink in sinks:
                for argument_index in sink.arguments:
                    if argument_index >= len(call.args):
                        continue
                    atoms = argument_atoms[argument_index]
                    # Context matching is authoritative: a value is reported at
                    # a sink only when it carries taint for that sink's context.
                    # A flow whose source does not declare the sink's context is
                    # rejected by the rule validator (RULE026) instead of being
                    # silently reinterpreted here.
                    matching = self._atoms_for_context(problem, atoms, sink.context)
                    if matching:
                        hit = SinkHit(
                            sid=statement.sid if statement is not None else -1,
                            node=call,
                            rule=sink,
                            argument_index=argument_index,
                            expression=call.args[argument_index],
                            atoms=tuple(sorted(problem.atom_texts(matching))),
                            function=problem.cfg.function,
                            block=problem.cfg.entry,
                            in_state=state,
                        )
                        # Locate the block containing this statement for the UI.
                        for block in problem.cfg.sorted_blocks():
                            if statement is not None and statement.sid in block.statement_ids:
                                hit.block = block.id
                                break
                        problem.collected_hits.append(hit)

        # 2) source --------------------------------------------------------
        for source in sources:
            if source.from_return_value:
                result_atoms |= self._source_atoms(problem, source)
            elif source.argument < len(call.args):
                result_atoms |= argument_atoms[source.argument]

        # 3) sanitizer -----------------------------------------------------
        if sanitizers:
            base = 0
            for atoms in argument_atoms:
                base |= atoms
            for sanitizer in sanitizers:
                if sanitizer.argument >= len(call.args):
                    continue
                if sanitizer.kind == "validator":
                    # A validator used as a value yields a boolean, which
                    # carries no string taint.
                    result_atoms |= 0
                    continue
                selected = argument_atoms[sanitizer.argument]
                base = (base & ~selected) | self._remove_context(problem, selected, sanitizer.context)
            result_atoms |= base

        # 4) call into the analysed program --------------------------------
        if call.name in self.program.functions:
            summary = problem.ret_params.get(call.name, {}) if hasattr(problem, "ret_params") else {}
            for index, contexts in summary.items():
                if index >= len(argument_atoms):
                    continue
                if contexts >= set(CONTEXTS):
                    result_atoms |= argument_atoms[index]
                else:
                    for context in contexts:
                        result_atoms |= self._atoms_for_context(problem, argument_atoms[index], context)
            if problem.collecting:
                problem.collected_calls.append(
                    CallSite(
                        caller=problem.cfg.function,
                        callee=call.name,
                        node=call,
                        sid=statement.sid if statement is not None else -1,
                        argument_atoms=[tuple(sorted(problem.atom_texts(a))) for a in argument_atoms],
                        atoms_used=tuple(sorted(problem.atom_texts(result_atoms))),
                        block=-1,
                        in_state=state,
                    )
                )
        elif not sources and not sanitizers and not sinks:
            # Unknown external function: conservative model -- the result may
            # depend on any argument, and nothing is assumed to be validated.
            for atoms in argument_atoms:
                result_atoms |= atoms
            if any(argument_atoms):
                self.note(
                    f"call to unknown function '{call.name}': argument taint is propagated to the "
                    "result and no sanitisation is assumed"
                )
        return result_atoms

    def _source_atoms(self, problem: TaintProblem, source: SourceRule) -> int:
        atoms = 0
        for context in source.contexts:
            text = source_atom(source.id, context)
            atoms |= problem.find_atom_bit(text)
        return atoms

    def _remove_context(self, problem: TaintProblem, atoms: int, context: str) -> int:
        if context == ALL_CONTEXTS:
            return 0
        result = atoms
        for text in problem.atom_texts(atoms):
            if atom_context(text) == context:
                result &= ~problem.find_atom_bit(text)
        return result

    def _atoms_for_context(self, problem: TaintProblem, atoms: int, context: str) -> int:
        result = 0
        for text in problem.atom_texts(atoms):
            if atom_context(text) == context or context == ALL_CONTEXTS:
                result |= problem.find_atom_bit(text)
        return result
