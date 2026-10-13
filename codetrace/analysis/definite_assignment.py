"""Definite-assignment analysis (the "possibly uninitialised variable" check).

This is a forward **must** analysis: a variable is definitely assigned at a
program point only if *every* path from the function entry to that point
assigns it.  It therefore uses INTERSECTION as the meet operator, which is
exactly the dual of reaching definitions::

    OUT[B] = IN[B] ∪ DEF[B]
    IN[B]  = ⋂ OUT[P] over all predecessors P of B   (⋂ the boundary at entry)

The boundary value of the entry block contains the function parameters and all
file-scope variables, because those have a defined value before the first
statement of the function runs (file-scope variables are zero-initialised).

A read of a variable that is not definitely assigned at that point is reported
as ``DFA001 use of possibly uninitialised variable``.  The result is a
*warning*: the analysis is path-insensitive in the sense that it does not
evaluate which branch conditions can actually hold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .accesses import statement_accesses
from .cfg import CFG
from .dataflow import BitVectorDomain, DataFlowProblem, DataFlowResult, solve
from .liveness import symbol_atom, symbols_used


@dataclass
class DefiniteAssignment(DataFlowProblem):
    symbol_names: Dict[int, str] = field(default_factory=dict)
    defs: Dict[int, int] = field(default_factory=dict)
    entry_bits: int = 0

    def __post_init__(self) -> None:
        self.name = "definite-assignment"
        self.direction = "forward"
        for block in self.cfg.sorted_blocks():
            writes: Set[int] = set()
            for statement in block.statements:
                _reads, statement_writes = statement_accesses(statement, initialisation_only=True)
                writes |= statement_writes
            self.defs[block.id] = self._bits(writes)
        # A must-analysis accumulates facts instead of killing them, so the
        # generic ``gen`` slot holds DEF and the ``kill`` slot stays empty.  The
        # equation OUT[B] = GEN[B] ∪ (IN[B] − KILL[B]) therefore reduces to
        # OUT[B] = DEF[B] ∪ IN[B].
        self.gen = self.defs
        self.kill = {}
        # The boundary value of the entry block contains only what already has
        # a value before the function body runs: parameters and file-scope
        # variables.  Variables declared *inside* the entry block must not be
        # part of it, otherwise a use before their declaration would be
        # silently accepted.
        entry_symbols: Set[int] = set()
        entry_definition_ids = set(self.cfg.block(self.cfg.entry).entry_definition_ids)
        for definition in self.cfg.definitions:
            if definition.id in entry_definition_ids:
                entry_symbols.add(definition.symbol_id)
        self.entry_bits = self._bits(entry_symbols)

    def _bits(self, symbol_ids) -> int:
        value = 0
        for symbol_id in symbol_ids:
            atom = symbol_atom(symbol_id, self.symbol_names.get(symbol_id, ""))
            try:
                value |= self.domain.singleton(atom)
            except Exception:  # atom missing from the domain: ignore
                continue
        return value

    def meet(self, values: List[int]) -> int:
        if not values:
            return self.domain.empty()
        result = values[0]
        for value in values[1:]:
            result &= value
        return result

    def transfer(self, block_id: int, in_value: int) -> int:
        return in_value | self.defs.get(block_id, 0)

    def boundary_value(self, block_id: int) -> int:
        return self.entry_bits

    # -- queries ---------------------------------------------------------
    def uninitialised_reads(self, result: DataFlowResult) -> List[dict]:
        findings: List[dict] = []
        for block in self.cfg.sorted_blocks():
            if block.id not in result.reachable:
                continue
            value = result.in_values.get(block.id, 0)
            for statement in block.statements:
                reads, writes = statement_accesses(statement, initialisation_only=True)
                for symbol_id in sorted(reads):
                    atom = symbol_atom(symbol_id, self.symbol_names.get(symbol_id, ""))
                    if not self.domain.contains(value, atom):
                        findings.append(
                            {
                                "symbol_id": symbol_id,
                                "symbol": self.symbol_names.get(symbol_id, "?"),
                                "sid": statement.sid,
                                "offset": statement.span[0],
                                "line": statement.line,
                                "col": statement.col,
                                "block": block.id,
                            }
                        )
                value |= self._bits(writes)
        return findings

    def statement_states(self, result: DataFlowResult) -> Dict[int, Tuple[int, int]]:
        """``sid -> (in_bits, out_bits)`` for every statement, exactly.

        Inside a block a statement's incoming value is the block's IN value plus
        the writes of the statements that precede it in that block, which is the
        same replay the other two problems expose.  The pair is what the UI shows
        and what :meth:`uninitialised_reads` reasons over.
        """
        states: Dict[int, Tuple[int, int]] = {}
        for block in self.cfg.sorted_blocks():
            value = result.in_values.get(block.id, 0)
            for statement in block.statements:
                in_bits = value
                _reads, writes = statement_accesses(statement, initialisation_only=True)
                value = value | self._bits(writes)
                states[statement.sid] = (in_bits, value)
        return states

    def definitely_assigned(self, result: DataFlowResult, block_id: int) -> List[str]:
        return sorted(self.domain.atoms_of(result.in_values.get(block_id, 0)))

    def to_json(self, result: DataFlowResult) -> dict:
        payload = result.to_json(include_atoms=False)
        payload["def"] = {b: self.domain.atoms_of(v) for b, v in sorted(self.defs.items())}
        return payload


def build_problem(cfg: CFG, symbol_names: Dict[int, str]) -> DefiniteAssignment:
    used = symbols_used(cfg)
    selected = {sid: name for sid, name in symbol_names.items() if sid in used}
    atoms = [symbol_atom(sid, selected[sid]) for sid in sorted(selected)]
    domain = BitVectorDomain(atoms=atoms, name=f"variables of {cfg.function}")
    return DefiniteAssignment(cfg=cfg, domain=domain, symbol_names=selected)


def analyse(cfg: CFG, symbol_names: Dict[int, str], max_iterations: int = 10_000):
    problem = build_problem(cfg, symbol_names)
    result = solve(problem, max_iterations=max_iterations)
    return problem, result
