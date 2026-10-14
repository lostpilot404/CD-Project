"""Reaching-definitions analysis.

Equations (forward, "may" analysis; UNION is the meet operator)::

    OUT[B] = GEN[B] ∪ (IN[B] − KILL[B])
    IN[B]  = ⋃ OUT[P] over all predecessors P of B   (∪ the boundary ∅ at entry)

where, for a basic block ``B``,

* ``GEN[B]`` is the set of definitions in ``B`` that reach the end of ``B``
  (i.e. the *last* definition of each variable in the block), and
* ``KILL[B]`` is the set of all other definitions of the variables defined in
  ``B`` (definitions that ``B`` overwrites, wherever they are).

Statement-level results are obtained by replaying the same transfer function
statement by statement inside a block, starting from the block's IN value.
That gives an exact per-statement answer ("which definitions reach *this*
statement") without a second, different analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .cfg import CFG, Definition
from .dataflow import BitVectorDomain, DataFlowProblem, DataFlowResult, solve


def definition_atom(definition_id: int) -> str:
    return f"d{definition_id}"


@dataclass
class ReachingDefinitions(DataFlowProblem):
    """GEN/KILL-based reaching definitions over one function's CFG."""

    definitions: Dict[int, Definition] = field(default_factory=dict)
    #: Definitions contained in each block, in statement order.
    block_definitions: Dict[int, List[int]] = field(default_factory=dict)
    param_blocks: Dict[int, List[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = "reaching-definitions"
        self.direction = "forward"
        self._index_blocks()

    # ------------------------------------------------------------------
    def _index_blocks(self) -> None:
        self.block_definitions = {block_id: [] for block_id in self.cfg.blocks}
        by_sid: Dict[int, List[Definition]] = {}
        for definition in self.cfg.definitions:
            self.definitions[definition.id] = definition
            by_sid.setdefault(definition.sid, []).append(definition)
        for block in self.cfg.sorted_blocks():
            for definition_id in block.entry_definition_ids:
                self.block_definitions[block.id].append(definition_id)
            for sid in block.statement_ids:
                for definition in by_sid.get(sid, []):
                    self.block_definitions[block.id].append(definition.id)
            self.block_definitions[block.id].sort(
                key=lambda did: (self.definitions[did].offset, self.definitions[did].id)
            )

        # symbols defined anywhere in the function
        by_symbol: Dict[int, List[int]] = {}
        for definition in self.cfg.definitions:
            by_symbol.setdefault(definition.symbol_id, []).append(definition.id)
        self.by_symbol = by_symbol

        for block_id, definition_ids in self.block_definitions.items():
            self.gen[block_id], self.kill[block_id] = self._gen_kill(definition_ids)

    def _gen_kill(self, definition_ids: Sequence[int]) -> Tuple[int, int]:
        """GEN/KILL of an ordered sequence of definitions (block or statement).

        ``GEN`` keeps only the last definition of each variable in the
        sequence; every other definition of those variables (anywhere in the
        function) becomes part of ``KILL``.
        """
        gen = 0
        last_of_symbol: Dict[int, int] = {}
        for definition_id in definition_ids:
            symbol_id = self.definitions[definition_id].symbol_id
            previous = last_of_symbol.get(symbol_id)
            if previous is not None:
                gen &= ~self.domain.singleton(definition_atom(previous))
            last_of_symbol[symbol_id] = definition_id
            gen |= self.domain.singleton(definition_atom(definition_id))
        killed_ids: Set[int] = set()
        for symbol_id in last_of_symbol:
            for definition_id in self.by_symbol.get(symbol_id, []):
                killed_ids.add(definition_id)
        for surviving in last_of_symbol.values():
            killed_ids.discard(surviving)
        kill = 0
        for definition_id in killed_ids:
            kill |= self.domain.singleton(definition_atom(definition_id))
        return gen, kill

    # ------------------------------------------------------------------
    def meet(self, values: List[int]) -> int:
        result = 0
        for value in values:
            result |= value
        return result

    def transfer(self, block_id: int, in_value: int) -> int:
        return (in_value & ~self.kill.get(block_id, 0)) | self.gen.get(block_id, 0)

    def boundary_value(self, block_id: int) -> int:
        """Definitions already in force at the start of the function.

        Parameters and file-scope variables are defined before the first
        statement executes, so they reach the whole function body.
        """
        bits = 0
        for definition_id in self.cfg.block(block_id).entry_definition_ids:
            bits |= self.domain.singleton(definition_atom(definition_id))
        return bits

    # -- statement level refinement -------------------------------------
    def statement_states(self, result: DataFlowResult) -> Dict[int, Tuple[int, int]]:
        """``sid -> (in_bits, out_bits)`` for every statement, exactly.

        Inside a block the transfer function is applied statement by statement;
        the value flowing into the first statement of a block is the block's IN
        value from the fixed point.
        """
        states: Dict[int, Tuple[int, int]] = {}
        by_sid: Dict[int, List[Definition]] = {}
        for definition in self.cfg.definitions:
            by_sid.setdefault(definition.sid, []).append(definition)
        for block in self.cfg.sorted_blocks():
            # Statements are stored in program order, so replaying the
            # transfer function along ``statement_ids`` walks the block
            # exactly as execution would.
            value = result.in_values.get(block.id, 0)
            for sid in block.statement_ids:
                in_bits = value
                definition_ids = [
                    d.id for d in sorted(by_sid.get(sid, []), key=lambda d: (d.offset, d.id))
                ]
                local_gen, local_kill = self._gen_kill(definition_ids)
                value = (value & ~local_kill) | local_gen
                states[sid] = (in_bits, value)
        return states

    # -- queries ---------------------------------------------------------
    def definitions_reaching(
        self, states: Dict[int, Tuple[int, int]], sid: int, symbol_id: Optional[int] = None
    ) -> List[Definition]:
        bits = states.get(sid, (0, 0))[0]
        out: List[Definition] = []
        for definition_id, definition in self.definitions.items():
            if not self.domain.contains(bits, definition_atom(definition_id)):
                continue
            if symbol_id is not None and definition.symbol_id != symbol_id:
                continue
            out.append(definition)
        return sorted(out, key=lambda d: (d.offset, d.id))

    def to_json(self, result: DataFlowResult) -> dict:
        # Keep the per-block IN/OUT atom lists: the Data-Flow page prints them
        # next to |IN| and |OUT|, and docs/API.md promises them.
        payload = result.to_json(include_atoms=True)
        payload["gen"] = {b: self.domain.atoms_of(v) for b, v in sorted(self.gen.items())}
        payload["kill"] = {b: self.domain.atoms_of(v) for b, v in sorted(self.kill.items())}
        payload["definitions"] = [d.to_json() for d in sorted(self.definitions.values(), key=lambda d: d.id)]
        return payload


def build_problem(cfg: CFG) -> ReachingDefinitions:
    atoms = [definition_atom(d.id) for d in sorted(cfg.definitions, key=lambda d: d.id)]
    domain = BitVectorDomain(atoms=atoms, name=f"definitions of {cfg.function}")
    return ReachingDefinitions(cfg=cfg, domain=domain)


def analyse(cfg: CFG, max_iterations: int = 10_000):
    """Run reaching definitions for one function.

    Returns ``(problem, result, statement_states)``.
    """
    problem = build_problem(cfg)
    result = solve(problem, max_iterations=max_iterations)
    states = problem.statement_states(result)
    return problem, result, states
