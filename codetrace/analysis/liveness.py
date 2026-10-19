"""Live-variable analysis.

A variable is **live** at a program point if there is a path from that point to
a use of the variable along which it is not redefined first.  Liveness is a
backward "may" analysis with UNION as the meet operator::

    OUT[B] = ⋃ IN[S] over all successors S of B    (⋃ the boundary ∅ at exit)
    IN[B]  = USE[B] ∪ (OUT[B] − DEF[B])

where

* ``USE[B]`` is the set of variables read in ``B`` *before* being written in
  ``B`` (upward-exposed uses), and
* ``DEF[B]`` is the set of variables written in ``B`` *before* being read in
  ``B`` (upward-exposed definitions).

Liveness answers "does this value still matter?", which is *not* the same
question as reaching definitions ("which writes could have produced this
value?") nor as taint ("where could this data have come from?").  CodeTrace
keeps the three analyses separate and labels their results accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .accesses import statement_accesses
from .cfg import CFG
from .dataflow import BitVectorDomain, DataFlowProblem, DataFlowResult, DomainError, solve


def symbol_atom(symbol_id: int, name: str = "") -> str:
    return f"s{symbol_id}" + (f":{name}" if name else "")


def symbols_used(cfg: CFG) -> Set[int]:
    """Symbol ids that can carry a value inside ``cfg``.

    A function's lattice only needs cells for the names that actually occur in
    it: the symbols its blocks read or write, plus the symbols of its own
    definitions (parameters and file-scope variables included).  Building the
    domain this way keeps the bit vectors as small as the function, and it makes
    ``domain.atoms`` an accurate answer to "which variables does this analysis
    track for this function?".
    """
    used: Set[int] = set()
    for definition in cfg.definitions:
        used.add(definition.symbol_id)
    for block in cfg.sorted_blocks():
        for statement in block.statements:
            reads, writes = statement_accesses(statement)
            used |= reads
            used |= writes
    return used


@dataclass
class Liveness(DataFlowProblem):
    symbol_names: Dict[int, str] = field(default_factory=dict)
    #: ``USE`` per block (upward-exposed reads) and ``DEF`` per block
    #: (upward-exposed writes).  ``gen``/``kill`` alias these two dictionaries.
    use: Dict[int, int] = field(default_factory=dict)
    defs: Dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = "liveness"
        self.direction = "backward"
        self._index_blocks()

    def _index_blocks(self) -> None:
        for block in self.cfg.sorted_blocks():
            use: Set[int] = set()
            defs: Set[int] = set()
            for statement in block.statements:
                reads, writes = statement_accesses(statement)
                for symbol_id in reads - defs:
                    use.add(symbol_id)
                for symbol_id in writes:
                    defs.add(symbol_id)
            self.use[block.id] = self._bits(use)
            self.defs[block.id] = self._bits(defs)
        # Present the block contributions through the generic ``gen``/``kill``
        # slots as well, so that every problem in this package can be inspected
        # the same way: for the backward liveness problem GEN is USE and KILL is
        # DEF, exactly as in the textbook presentation of the equation.
        self.gen = self.use
        self.kill = self.defs

    def _bits(self, symbol_ids) -> int:
        value = 0
        for symbol_id in symbol_ids:
            atom = self._atom_for(symbol_id)
            if atom is None:
                continue
            try:
                value |= self.domain.singleton(atom)
            except DomainError:
                # A name that has no lattice cell (for example a function used
                # as a value) can neither be defined nor be live.  The semantic
                # analyser reports that misuse separately (SEM014), so liveness
                # simply ignores it instead of inventing a variable.
                continue
        return value

    def _atom_for(self, symbol_id: int) -> Optional[str]:
        return symbol_atom(symbol_id, self.symbol_names.get(symbol_id, ""))

    def meet(self, values: List[int]) -> int:
        result = 0
        for value in values:
            result |= value
        return result

    def transfer(self, block_id: int, out_value: int) -> int:
        return self.use.get(block_id, 0) | (out_value & ~self.defs.get(block_id, 0))

    def boundary_value(self, block_id: int) -> int:
        return 0

    # -- statement level refinement --------------------------------------
    def statement_states(self, result: DataFlowResult) -> Dict[int, Tuple[int, int]]:
        """``sid -> (in_bits, out_bits)`` computed statement by statement."""
        states: Dict[int, Tuple[int, int]] = {}
        for block in self.cfg.sorted_blocks():
            value = result.out_values.get(block.id, 0)
            for statement in reversed(block.statements):
                reads, writes = statement_accesses(statement)
                out_bits = value
                in_bits = self._bits(reads) | (out_bits & ~self._bits(writes))
                states[statement.sid] = (in_bits, out_bits)
                value = in_bits
        return states

    def live_variables(self, states: Dict[int, Tuple[int, int]], sid: int, at: str = "in") -> List[str]:
        bits = states.get(sid, (0, 0))[0 if at == "in" else 1]
        return sorted(self.domain.atoms_of(bits))

    def to_json(self, result: DataFlowResult) -> dict:
        payload = result.to_json(include_atoms=True)
        payload["use"] = {b: self.domain.atoms_of(v) for b, v in sorted(self.use.items())}
        payload["def"] = {b: self.domain.atoms_of(v) for b, v in sorted(self.defs.items())}
        return payload


def build_problem(cfg: CFG, symbol_names: Dict[int, str]) -> Liveness:
    used = symbols_used(cfg)
    names = {sid: name for sid, name in symbol_names.items() if sid in used}
    atoms = [symbol_atom(sid, names[sid]) for sid in sorted(names)]
    domain = BitVectorDomain(atoms=atoms, name=f"variables of {cfg.function}")
    return Liveness(cfg=cfg, domain=domain, symbol_names=names)


def analyse(cfg: CFG, symbol_names: Dict[int, str], max_iterations: int = 10_000):
    """Run liveness for one function; returns ``(problem, result, states)``."""
    problem = build_problem(cfg, symbol_names)
    result = solve(problem, max_iterations=max_iterations)
    states = problem.statement_states(result)
    return problem, result, states
