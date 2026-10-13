"""A small, reusable data-flow analysis framework.

The framework implements the classical fixed-point iteration over a
control-flow graph:

* a **domain** (the lattice of data-flow facts) -- here a bit vector, so that
  set operations are single word operations and comparisons are O(1);
* a **direction** (forward for reaching definitions, backward for liveness);
* a **boundary condition** (the value at the entry, respectively exit, block);
* a **meet operator** (set union for "may" analyses, set intersection for
  "must" analyses);
* a **transfer function** per basic block;
* a **worklist solver** that iterates until no block's OUT value changes,
  with an explicit iteration cap so that a pathological CFG cannot hang the
  server.

Every result records the number of iterations and the processing order, which
is what the UI shows next to the computed sets: the numbers are measured, not
estimated.

Facts are represented as Python integers used as bit vectors.  ``1 << i``
denotes the presence of atom ``i``; a value is a *set* of atoms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .cfg import CFG, BasicBlock


class DomainError(Exception):
    pass


@dataclass
class BitVectorDomain:
    """A finite lattice of subsets of ``atoms``, represented as bit vectors."""

    atoms: Sequence[str]
    name: str = "domain"

    def __post_init__(self) -> None:
        self._bits: Dict[str, int] = {atom: index for index, atom in enumerate(self.atoms)}
        self._full = (1 << len(self.atoms)) - 1 if self.atoms else 0

    # -- construction ---------------------------------------------------
    def empty(self) -> int:
        return 0

    def full(self) -> int:
        return self._full

    def singleton(self, atom: str) -> int:
        bit = self._bits.get(atom)
        if bit is None:
            raise DomainError(f"atom {atom!r} is not part of the {self.name} domain")
        return 1 << bit

    def of(self, atoms: Iterable[str]) -> int:
        value = 0
        for atom in atoms:
            value |= self.singleton(atom)
        return value

    # -- lattice operations ---------------------------------------------
    def union(self, left: int, right: int) -> int:
        return left | right

    def intersect(self, left: int, right: int) -> int:
        return left & right

    def difference(self, left: int, right: int) -> int:
        return left & ~right

    def is_subset(self, left: int, right: int) -> bool:
        return (left & ~right) == 0

    def contains(self, value: int, atom: str) -> bool:
        bit = self._bits.get(atom)
        return bit is not None and bool(value & (1 << bit))

    def atoms_of(self, value: int) -> List[str]:
        return [atom for atom, bit in self._bits.items() if value & (1 << bit)]

    def size(self, value: int) -> int:
        return bin(value).count("1")

    def __len__(self) -> int:
        return len(self.atoms)


@dataclass
class DataFlowProblem:
    """Base class for a data-flow problem defined over one function's CFG."""

    cfg: CFG
    domain: BitVectorDomain
    name: str = "dataflow"
    direction: str = "forward"  # or "backward"
    #: GEN / USE style per-block contribution, filled by subclasses.
    gen: Dict[int, int] = field(default_factory=dict)
    kill: Dict[int, int] = field(default_factory=dict)

    # -- to be provided by subclasses -----------------------------------
    def boundary_value(self, block_id: int) -> int:
        """Value at the entry block (forward) or exit block (backward)."""
        return self.domain.empty()

    def initial_value(self, block_id: int) -> int:
        """Starting value of the iteration for a block that is not the boundary.

        The lattice bottom is the right start for a *may* analysis (union meet):
        the iteration only ever adds facts, so it climbs to the least fixpoint,
        which is the meet-over-all-paths solution.

        A *must* analysis (intersection meet) has to start at the lattice **top**
        instead and be refined downwards, because its facts hold only if every
        predecessor path establishes them; starting at the bottom there makes the
        intersection of a partially computed block with a fully computed one lose
        facts that are in fact true on every path.  Analyses that meet with
        intersection therefore override this method.
        """
        return self.domain.empty()

    def meet(self, values: List[int]) -> int:
        raise NotImplementedError

    def transfer(self, block_id: int, in_value: int) -> int:
        raise NotImplementedError

    def edge_transfer(self, src: int, dst: int, value: int) -> int:
        """Value refinement applied when control flows along an edge.

        The default is the identity, which is correct for every "classical"
        problem in this framework.  Path-sensitive refinements (for example a
        validator guard in an ``if`` condition) override this method; the solver
        applies it to a predecessor's OUT value *before* the meet.
        """
        return value

    def reachable_blocks(self) -> Set[int]:
        """Blocks the solver should analyse (by default the CFG's reachable set)."""
        return set(self.cfg.reachable)

    # -- derived helpers -------------------------------------------------
    def predecessors(self, block_id: int) -> List[int]:
        block = self.cfg.block(block_id)
        return sorted(block.predecessors)

    def successors(self, block_id: int) -> List[int]:
        return sorted(e.dst for e in self.cfg.block(block_id).successors)

    def entry_blocks(self) -> List[int]:
        return [self.cfg.entry]

    def exit_blocks(self) -> List[int]:
        return [self.cfg.exit]

    def order(self) -> List[int]:
        """Deterministic processing order (ascending block id)."""
        return sorted(self.cfg.blocks)


@dataclass
class DataFlowResult:
    """Fixed-point solution of a :class:`DataFlowProblem`."""

    problem: str
    direction: str
    domain: BitVectorDomain
    in_values: Dict[int, int]
    out_values: Dict[int, int]
    iterations: int
    steps: int
    converged: bool
    processed_order: List[int]
    reachable: Set[int]
    blocks_with_changes: List[int] = field(default_factory=list)
    _index: Dict[int, BasicBlock] = field(default_factory=dict)

    # -- queries ---------------------------------------------------------
    def in_atoms(self, block_id: int) -> List[str]:
        return self.domain.atoms_of(self.in_values.get(block_id, 0))

    def out_atoms(self, block_id: int) -> List[str]:
        return self.domain.atoms_of(self.out_values.get(block_id, 0))

    def to_json(self, include_atoms: bool = True) -> dict:
        blocks = []
        for block_id in sorted(self.in_values):
            entry = {
                "block": block_id,
                "reachable": block_id in self.reachable,
                "in_size": self.domain.size(self.in_values[block_id]),
                "out_size": self.domain.size(self.out_values[block_id]),
            }
            if include_atoms:
                entry["in"] = self.in_atoms(block_id)
                entry["out"] = self.out_atoms(block_id)
            entry["block_in"] = self.in_values[block_id]
            entry["block_out"] = self.out_values[block_id]
            blocks.append(entry)
        return {
            "problem": self.problem,
            "direction": self.direction,
            "domain": self.domain.name,
            "domain_size": len(self.domain),
            "iterations": self.iterations,
            "steps": self.steps,
            "converged": self.converged,
            "processed_order": self.processed_order,
            "reachable": sorted(self.reachable),
            "blocks": blocks,
        }


def solve(problem: DataFlowProblem, max_iterations: int = 10_000, max_steps: int = 200_000) -> DataFlowResult:
    """Worklist fixed-point solver.

    The algorithm is the standard iterative algorithm from the data-flow
    literature: start every block at the lattice bottom (except the boundary
    block), then repeatedly recompute a block's OUT value from its IN value
    until nothing changes.  Convergence is guaranteed because both the domain
    (finite) and the transfer functions (monotone) are well behaved; the
    iteration budget is a safety valve for pathological inputs, and exceeding
    it is reported instead of silently returning an unmatured result.
    """
    forward = problem.direction == "forward"
    blocks = problem.order()
    reachable = problem.reachable_blocks()
    in_values: Dict[int, int] = {}
    out_values: Dict[int, int] = {}

    for block_id in blocks:
        if block_id not in reachable:
            # Unreachable blocks are not analysed; they cannot influence a
            # reachable result and pretending otherwise would be misleading.
            in_values[block_id] = problem.domain.empty()
            out_values[block_id] = problem.domain.empty()
            continue
        in_values[block_id] = problem.initial_value(block_id)
        out_values[block_id] = problem.initial_value(block_id)

    if forward:
        if problem.cfg.entry in in_values:
            in_values[problem.cfg.entry] = problem.boundary_value(problem.cfg.entry)
    else:
        if problem.cfg.exit in out_values:
            out_values[problem.cfg.exit] = problem.boundary_value(problem.cfg.exit)

    entry_id = problem.cfg.entry
    exit_id = problem.cfg.exit
    worklist: List[int] = [b for b in blocks if b in reachable]
    worklist.sort(reverse=not forward)
    queued: Set[int] = set(worklist)
    iterations = 0
    steps = 0
    processed: List[int] = []
    changed_blocks: Set[int] = set()

    while worklist:
        block_id = worklist.pop(0)
        queued.discard(block_id)
        iterations += 1
        steps += 1
        processed.append(block_id)
        if iterations > max_iterations or steps > max_steps:
            break

        if forward:
            # IN[B] = meet over predecessors' OUT, with the boundary value
            # acting as a virtual predecessor of the entry block.  This is what
            # makes loop back edges into the entry block behave correctly.
            preds = [p for p in problem.predecessors(block_id) if p in reachable]
            sources = [problem.edge_transfer(p, block_id, out_values[p]) for p in preds]
            if block_id == entry_id:
                sources.append(problem.boundary_value(block_id))
            if sources:
                new_in = problem.meet(sources)
                if new_in != in_values[block_id]:
                    in_values[block_id] = new_in
                    changed_blocks.add(block_id)
            new_out = problem.transfer(block_id, in_values[block_id])
            if new_out != out_values[block_id]:
                out_values[block_id] = new_out
                changed_blocks.add(block_id)
                for succ in problem.successors(block_id):
                    if succ in reachable and succ not in queued:
                        worklist.append(succ)
                        queued.add(succ)
        else:
            succs = [s for s in problem.successors(block_id) if s in reachable]
            sources = [problem.edge_transfer(block_id, s, in_values[s]) for s in succs]
            if block_id == exit_id:
                sources.append(problem.boundary_value(block_id))
            if sources:
                new_out = problem.meet(sources)
                if new_out != out_values[block_id]:
                    out_values[block_id] = new_out
                    changed_blocks.add(block_id)
            new_in = problem.transfer(block_id, out_values[block_id])
            if new_in != in_values[block_id]:
                in_values[block_id] = new_in
                changed_blocks.add(block_id)
                for pred in problem.predecessors(block_id):
                    if pred in reachable and pred not in queued:
                        worklist.append(pred)
                        queued.add(pred)

    return DataFlowResult(
        problem=problem.name,
        direction=problem.direction,
        domain=problem.domain,
        in_values=in_values,
        out_values=out_values,
        iterations=iterations,
        steps=steps,
        converged=(not worklist) and iterations <= max_iterations,
        processed_order=processed,
        reachable=set(reachable),
        blocks_with_changes=sorted(changed_blocks),
    )
