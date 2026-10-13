"""Data-flow analysis tests.

Every expected set in this module was computed **by hand** from the source
before the test was written.  The comment above each expectation shows the
calculation, so a failure tells you whether the engine or the expectation is
wrong.

Definitions used here:

* reaching definitions --- forward "may" analysis,
  ``OUT[B] = GEN[B] ∪ (IN[B] − KILL[B])``, ``IN[B] = ⋃ OUT[P]``.
* live variables --- backward "may" analysis,
  ``OUT[B] = ⋃ IN[S]``, ``IN[B] = USE[B] ∪ (OUT[B] − DEF[B])``.
* definite assignment --- forward "must" analysis,
  ``OUT[B] = IN[B] ∪ DEF[B]``, ``IN[B] = ⋂ OUT[P]``.
"""

from __future__ import annotations

import unittest

from codetrace.analysis.dataflow import BitVectorDomain, DataFlowProblem, solve
from tests.helpers import analyse

WHILE_SOURCE = """
int main() {
  int a = 1;
  int b = 2;
  while (a < 3) {
    b = a + b;
    a = a + 1;
  }
  return b;
}
"""

STRAIGHT_SOURCE = """
int main() {
  int x = 1;
  int y = 2;
  x = y + 1;
  return x;
}
"""


def strip(atoms) -> list:
    """Render atoms without their ``s<id>:``/``d`` decoration for readability."""
    return sorted(atom.split(":", 1)[1] if ":" in atom else atom for atom in atoms)


def names(problem, value) -> list:
    """Atoms of a bit-vector value, rendered without the symbol id prefix."""
    return strip(problem.domain.atoms_of(value))


class ReachingDefinitionsTests(unittest.TestCase):
    """Hand-checked fixpoints for ``OUT = GEN ∪ (IN − KILL)`` and ``IN = ⋃OUT[P]``."""

    def setUp(self):
        self.program = analyse(STRAIGHT_SOURCE)
        self.analysis = self.program.analyses["main"]
        self.cfg = self.analysis.cfg
        self.problem = self.analysis.reaching
        self.result = self.analysis.reaching_result

    def test_straight_line_hand_computation(self):
        # d0 = int x = 1;  d1 = int y = 2;  d2 = x = y + 1;
        #
        # B0 GEN={d1,d2} KILL={d0}:  IN(B0)=∅  -> OUT(B0) = {d1,d2}
        # B1 GEN=∅ KILL=∅:           IN(B1)={d1,d2} -> OUT(B1)={d1,d2}
        definitions = [(d.id, d.symbol_name, d.sid, d.kind) for d in self.cfg.definitions]
        self.assertEqual(
            definitions,
            [(0, "x", 0, "decl-init"), (1, "y", 1, "decl-init"), (2, "x", 2, "assign")],
        )
        self.assertEqual(names(self.problem, self.result.in_values[0]), [])
        self.assertEqual(names(self.problem, self.result.out_values[0]), ["d1", "d2"])
        self.assertEqual(names(self.problem, self.result.in_values[1]), ["d1", "d2"])
        self.assertEqual(names(self.problem, self.result.out_values[1]), ["d1", "d2"])
        # Per statement, inside the block.  ``x = y + 1`` kills d0 and
        # generates d2, which is exactly why the statement-level state is the
        # informative one for the UI.
        expected = {
            0: ([], ["d0"]),
            1: (["d0"], ["d0", "d1"]),
            2: (["d0", "d1"], ["d1", "d2"]),
            3: (["d1", "d2"], ["d1", "d2"]),
        }
        for sid, (want_in, want_out) in expected.items():
            states = self.analysis.reaching_states[sid]
            self.assertEqual(names(self.problem, states[0]), want_in, f"IN of s{sid}")
            self.assertEqual(names(self.problem, states[1]), want_out, f"OUT of s{sid}")

    def test_while_loop_hand_computation(self):
        program = analyse(WHILE_SOURCE)
        analysis = program.analyses["main"]
        cfg, problem, result = analysis.cfg, analysis.reaching, analysis.reaching_result
        # Blocks: 0 entry [s0,s1] -> 2 header [s2] -> {4 body [s3,s4], 3 after [s5]},
        # and 4 loops back to 2.
        self.assertEqual(
            [(d.id, d.symbol_name, d.sid) for d in cfg.definitions],
            [(0, "a", 0), (1, "b", 1), (2, "b", 3), (3, "a", 4)],
        )
        expected_in_out = {
            # B0: IN=∅ (boundary), OUT=GEN={d0,d1}
            0: ([], ["d0", "d1"]),
            # B2 (header): IN = OUT(B0) ∪ OUT(B4) = {d0,d1} ∪ {d2,d3} = all
            2: (["d0", "d1", "d2", "d3"], ["d0", "d1", "d2", "d3"]),
            # B4 (body): GEN={d2,d3}, KILL={d0,d1} -> OUT = {d2,d3} ∪ (all − {d0,d1})
            4: (["d0", "d1", "d2", "d3"], ["d2", "d3"]),
            # B3 (after loop) = OUT(B2); B1 (exit) = OUT(B3)
            3: (["d0", "d1", "d2", "d3"], ["d0", "d1", "d2", "d3"]),
            1: (["d0", "d1", "d2", "d3"], ["d0", "d1", "d2", "d3"]),
        }
        for block_id, (want_in, want_out) in expected_in_out.items():
            self.assertEqual(names(problem, result.in_values[block_id]), want_in, f"IN(B{block_id})")
            self.assertEqual(names(problem, result.out_values[block_id]), want_out, f"OUT(B{block_id})")
        self.assertEqual(names(problem, problem.gen[0]), ["d0", "d1"])
        self.assertEqual(names(problem, problem.kill[0]), ["d2", "d3"])
        self.assertEqual(names(problem, problem.gen[4]), ["d2", "d3"])
        self.assertEqual(names(problem, problem.kill[4]), ["d0", "d1"])
        self.assertEqual(names(problem, problem.gen[2]), [])
        self.assertEqual(names(problem, problem.kill[2]), [])
        # Statement states: the body's second write kills the first one.
        statement_expected = {
            0: ([], ["d0"]),
            3: (["d0", "d1", "d2", "d3"], ["d0", "d2", "d3"]),
            4: (["d0", "d2", "d3"], ["d2", "d3"]),
            5: (["d0", "d1", "d2", "d3"], ["d0", "d1", "d2", "d3"]),
        }
        for sid, (want_in, want_out) in statement_expected.items():
            states = analysis.reaching_states[sid]
            self.assertEqual(names(problem, states[0]), want_in, f"IN of s{sid}")
            self.assertEqual(names(problem, states[1]), want_out, f"OUT of s{sid}")

    def test_transfer_is_gen_union_in_minus_kill(self):
        for block_id in self.cfg.blocks:
            for in_value in (0, self.problem.domain.full()):
                expected = self.problem.gen.get(block_id, 0) | (
                    in_value & ~self.problem.kill.get(block_id, 0)
                )
                self.assertEqual(
                    self.problem.transfer(block_id, in_value), expected, f"block {block_id}"
                )

    def test_meet_is_union_of_predecessor_outputs(self):
        union = self.problem.domain.of(["d0", "d1"])
        self.assertEqual(self.problem.meet([self.problem.domain.of(["d0"]), self.problem.domain.of(["d1"])]), union)
        self.assertEqual(self.problem.meet([union, self.problem.domain.of(["d1"])]), union)
        self.assertEqual(self.problem.meet([]), 0)
        # In the loop program the header really is the join point of the two
        # paths into it, so IN(header) must equal the meet of their OUT values.
        loop = analyse(WHILE_SOURCE).analyses["main"]
        header = loop.cfg.loops[0].header
        computed = [
            loop.reaching_result.out_values[pred] for pred in loop.cfg.block(header).predecessors
        ]
        self.assertGreaterEqual(len(computed), 2)
        self.assertEqual(loop.reaching.meet(computed), loop.reaching_result.in_values[header])

    def test_domain_holds_one_atom_per_definition(self):
        self.assertEqual(sorted(self.problem.domain.atoms), ["d0", "d1", "d2"])
        self.assertEqual(len(self.problem.domain), len(self.cfg.definitions))
        self.assertEqual(len(self.result.domain), 3)
        self.assertEqual(self.result.to_json()["domain_size"], 3)
        self.assertEqual(self.result.problem, "reaching-definitions")
        self.assertEqual(self.result.direction, "forward")

    def test_json_matches_the_computed_values(self):
        payload = self.result.to_json()
        self.assertEqual(payload["problem"], "reaching-definitions")
        self.assertTrue(payload["converged"])
        by_block = {entry["block"]: entry for entry in payload["blocks"]}
        for block_id in self.cfg.blocks:
            self.assertEqual(
                by_block[block_id]["in"], names(self.problem, self.result.in_values[block_id])
            )
            self.assertEqual(
                by_block[block_id]["out"], names(self.problem, self.result.out_values[block_id])
            )


class LivenessTests(unittest.TestCase):
    """Hand-checked fixpoints for ``OUT = ⋃IN[S]`` and ``IN = USE ∪ (OUT − DEF)``."""

    def setUp(self):
        self.program = analyse(STRAIGHT_SOURCE)
        self.analysis = self.program.analyses["main"]
        self.cfg = self.analysis.cfg
        self.problem = self.analysis.live
        self.result = self.analysis.live_result

    def test_straight_line_hand_computation(self):
        # Program order: s0 ``int x = 1;``  s1 ``int y = 2;``  s2 ``x = y + 1;``
        # s3 ``return x;``  -- the whole body is one block.
        #
        # Scanning the block forwards: s0 defines x, s1 defines y, s2 reads y
        # (already defined -> not a use) and defines x, s3 reads x (already
        # defined -> not a use).  So USE(B0)=∅ and DEF(B0)={x,y}; the block is
        # therefore dead at its boundaries, yet the statements are individually
        # live, which is exactly the difference this analysis makes visible.
        self.assertEqual(names(self.problem, self.problem.use[0]), [])
        self.assertEqual(names(self.problem, self.problem.defs[0]), ["x", "y"])
        self.assertEqual(names(self.problem, self.result.in_values[0]), [])
        self.assertEqual(names(self.problem, self.result.out_values[0]), [])
        self.assertEqual(names(self.problem, self.result.in_values[1]), [])
        expected = {0: ([], []), 1: ([], ["y"]), 2: (["y"], ["x"]), 3: (["x"], [])}
        for sid, (want_in, want_out) in expected.items():
            self.assertEqual(strip(self.analysis.live.live_variables(self.analysis.live_states, sid, "in")), want_in, f"IN of s{sid}")
            self.assertEqual(strip(self.analysis.live.live_variables(self.analysis.live_states, sid, "out")), want_out, f"OUT of s{sid}")

    def test_while_loop_hand_computation(self):
        program = analyse(WHILE_SOURCE)
        analysis = program.analyses["main"]
        cfg, problem, result = analysis.cfg, analysis.live, analysis.live_result
        # Block bodies: B0 [int a = 1; int b = 2;]      USE=∅     DEF={a,b}
        #               B2 [while (a < 3)]              USE={a}   DEF=∅
        #               B4 [b = a + b; a = a + 1;]      USE={a,b} DEF={a,b}
        #               B3 [return b;]                  USE={b}   DEF=∅
        #               B1 exit                         USE=∅     DEF=∅
        expected_use_def = {
            0: ([], ["a", "b"]),
            2: (["a"], []),
            4: (["a", "b"], ["a", "b"]),
            3: (["b"], []),
            1: ([], []),
        }
        for block_id, (want_use, want_def) in expected_use_def.items():
            self.assertEqual(names(problem, problem.use[block_id]), want_use, f"USE(B{block_id})")
            self.assertEqual(names(problem, problem.defs[block_id]), want_def, f"DEF(B{block_id})")
        # OUT(B3)=OUT(exit)=∅, IN(B3)={b}; OUT(B2)=IN(B4)∪IN(B3)={a,b},
        # IN(B2)={a}∪({a,b}−∅)={a,b}; OUT(B4)=IN(B2)={a,b},
        # IN(B4)={a,b}∪({a,b}−{a,b})={a,b}; OUT(B0)=IN(B2)={a,b}, IN(B0)=∅.
        expected_in_out = {
            1: ([], []),
            3: (["b"], []),
            2: (["a", "b"], ["a", "b"]),
            4: (["a", "b"], ["a", "b"]),
            0: ([], ["a", "b"]),
        }
        for block_id, (want_in, want_out) in expected_in_out.items():
            self.assertEqual(names(problem, result.in_values[block_id]), want_in, f"IN(B{block_id})")
            self.assertEqual(names(problem, result.out_values[block_id]), want_out, f"OUT(B{block_id})")
        # Statements: s2 is the loop condition (a is live), s3 reads a and b,
        # s4 reads a, s5 reads b.
        statement_expected = {
            0: ([], ["a"]),
            2: (["a", "b"], ["a", "b"]),
            3: (["a", "b"], ["a", "b"]),
            4: (["a", "b"], ["a", "b"]),
            5: (["b"], []),
        }
        for sid, (want_in, want_out) in statement_expected.items():
            self.assertEqual(strip(problem.live_variables(analysis.live_states, sid, "in")), want_in, f"IN of s{sid}")
            self.assertEqual(strip(problem.live_variables(analysis.live_states, sid, "out")), want_out, f"OUT of s{sid}")

    def test_use_is_upward_exposed_and_def_is_upward_exposed(self):
        # USE holds names read *before* they are written in the block:
        #   int sum = a + b;   reads a and b, writes sum
        #   sum = sum + 1;     reads sum, but sum is already defined here
        # so USE = {a,b} and DEF = {sum}, even though ``sum`` is read as well.
        analysis = analyse(
            """
int add(int a, int b) {
  int sum = a + b;
  sum = sum + 1;
  return sum;
}
"""
        ).analyses["add"]
        problem = analysis.live
        block = analysis.cfg.entry
        self.assertEqual(names(problem, problem.use[block]), ["a", "b"])
        self.assertEqual(names(problem, problem.defs[block]), ["sum"])
        # Reading a name that this block already wrote is *not* a use.
        other = analyse(
            """
int main() {
  int x = 1;
  int y = x;
  return y;
}
"""
        ).analyses["main"]
        self.assertEqual(names(other.live, other.live.use[other.cfg.entry]), [])
        self.assertEqual(names(other.live, other.live.defs[other.cfg.entry]), ["x", "y"])

    def test_same_named_variables_in_different_scopes_are_distinct_atoms(self):
        program = analyse(
            """
int f(int p) {
  int x = p + 1;
  return x;
}
int g() {
  int x = 2;
  return x;
}
"""
        )
        first = program.analyses["f"].live.domain
        second = program.analyses["g"].live.domain
        self.assertNotEqual(sorted(first.atoms), sorted(second.atoms))
        self.assertTrue(all(atom.endswith(":x") or atom.endswith(":p") for atom in first.atoms))
        # ``x`` of f and ``x`` of g are different symbols, so the two functions
        # never share a lattice cell even though the spelling is identical.
        xs = program.semantic.symbols.by_name("x")
        self.assertGreaterEqual(len(xs), 2, "one x per function")
        self.assertEqual(len({symbol.id for symbol in xs}), len(xs))
        self.assertNotEqual(xs[0].id, xs[1].id)
        # The two lattice cells are disjoint: the same spelling in two scopes
        # never shares a bit.
        self.assertEqual(set(first.atoms) & set(second.atoms), set())

    def test_gen_and_kill_expose_the_textbook_equation(self):
        # ``gen``/``kill`` are aliases of ``use``/``defs`` so that every problem
        # in the package can be inspected uniformly; the equation that the
        # solver applies is still IN = USE ∪ (OUT − DEF).
        for block_id in self.cfg.blocks:
            self.assertEqual(self.problem.gen[block_id], self.problem.use[block_id])
            self.assertEqual(self.problem.kill[block_id], self.problem.defs[block_id])
            for out_value in (0, self.problem.domain.full()):
                expected = self.problem.use.get(block_id, 0) | (
                    out_value & ~self.problem.defs.get(block_id, 0)
                )
                self.assertEqual(self.problem.transfer(block_id, out_value), expected)


class DefiniteAssignmentTests(unittest.TestCase):
    """Hand-checked fixpoints for the "must" analysis ``IN = ⋂ OUT[P]``."""

    def analysis_for(self, source: str):
        return analyse(source).analyses["main"]

    def test_possibly_uninitialised_read_inside_branch(self):
        # int a;            -> no initialisation, so ``a`` is not assigned
        # if (a > 0)        -> read of a with IN(B0)=∅        -> DFA001
        #   a = 1;          -> B2 OUT = {a}
        # return a;         -> IN(B3) = ⋂{OUT(B2)} = {a} ... but the false
        #                     branch goes straight to B3, so IN(B3) = ∅ -> DFA001
        analysis = self.analysis_for(
            """
int main() {
  int a;
  if (a > 0) {
    a = 1;
  }
  return a;
}
"""
        )
        reports = analysis.definite.uninitialised_reads(analysis.definite_result)
        self.assertEqual(
            [(report["symbol"], report["sid"]) for report in reports], [("a", 1), ("a", 3)]
        )
        blocks = {block.id: block.statement_ids for block in analysis.cfg.sorted_blocks()}
        assign_block = next(bid for bid, sids in blocks.items() if sids == [2])
        return_block = next(bid for bid, sids in blocks.items() if sids == [3])
        self.assertEqual(names(analysis.definite, analysis.definite_result.in_values[assign_block]), [])
        self.assertEqual(
            names(analysis.definite, analysis.definite_result.out_values[assign_block]), ["a"]
        )
        # The return is reached from the assignment and from the fall-through,
        # so the "must" analysis cannot claim ``a`` has a value here.
        self.assertEqual(names(analysis.definite, analysis.definite_result.in_values[return_block]), [])

    def test_both_branches_assign_is_clean(self):
        # IN(merge) = OUT(then) ⋂ OUT(else) = {a} ⋂ {a} = {a} -> no report.
        analysis = self.analysis_for(
            """
int main() {
  int a;
  if (1 > 0) { a = 1; } else { a = 2; }
  return a;
}
"""
        )
        self.assertEqual(analysis.definite.uninitialised_reads(analysis.definite_result), [])

    def test_reachable_read_reported_but_dead_read_is_not(self):
        reachable = self.analysis_for(
            """
int main() {
  int z;
  z = z + 1;
  return 1;
}
"""
        )
        self.assertEqual(len(reachable.definite.uninitialised_reads(reachable.definite_result)), 1)
        dead = self.analysis_for(
            """
int main() {
  int z;
  return 1;
  z = z + 1;
}
"""
        )
        # ``return 1;`` makes ``z = z + 1;`` unreachable: the CFG says so and
        # the analysis does not pretend to have proved anything about it.
        self.assertEqual(len(dead.cfg.unreachable), 1)
        self.assertEqual(dead.definite.uninitialised_reads(dead.definite_result), [])

    def test_entry_value_holds_parameters_and_globals_only(self):
        # ``a`` (parameter) and ``limit`` (file scope) already have a value when
        # the body starts; ``b`` does not, because it is declared inside.
        add = analyse(
            """
int limit = 5;
int add(int a) {
  int b;
  b = a + limit;
  return b;
}
"""
        ).analyses["add"]
        self.assertEqual(names(add.definite, add.definite.entry_bits), ["a", "limit"])
        # ``b`` is declared without an initialiser inside the function, so a
        # read of it before the assignment is still reported.
        reports = add.definite.uninitialised_reads(add.definite_result)
        self.assertEqual([report["symbol"] for report in reports], [])
        broken = self.analysis_for(
            """
int main() {
  int local;
  int other = local;
  return other;
}
"""
        )
        self.assertEqual(
            [(report["symbol"], report["sid"]) for report in broken.definite.uninitialised_reads(broken.definite_result)],
            [("local", 1)],
        )

    def test_meet_is_intersection_and_gen_aliases_definitions(self):
        analysis = self.analysis_for(STRAIGHT_SOURCE)
        problem = analysis.definite
        # Atoms carry the stable symbol id, so they are looked up from the
        # domain itself instead of being spelled by hand.
        atom_x = next(atom for atom in problem.domain.atoms if atom.endswith(":x"))
        atom_y = next(atom for atom in problem.domain.atoms if atom.endswith(":y"))
        left = problem.domain.of([atom_x])
        right = problem.domain.of([atom_x, atom_y])
        self.assertEqual(problem.meet([left, right]), left)
        self.assertEqual(problem.meet([]), 0)
        self.assertEqual(problem.kill, {})
        for block_id in analysis.cfg.blocks:
            self.assertEqual(problem.gen[block_id], problem.defs.get(block_id, 0))
            self.assertEqual(problem.transfer(block_id, left), left | problem.defs.get(block_id, 0))


class MustAnalysisInitialisationTests(unittest.TestCase):
    """The solver contract for a meet-by-intersection ("must") analysis.

    A must-analysis iterates *downwards* from the lattice top.  If it starts at
    the lattice bottom instead, a block whose predecessors are computed late
    loses facts that are true on every path, and the loss depends on the order in
    which the worklist happened to visit the cycle.  These tests pin both halves
    of that contract: the concrete definite-assignment analysis, and the generic
    solver that must honour a problem's ``initial_value``.
    """

    # The inner loop header has three predecessors, two of which are back edges
    # into the same cycle: the worst case for a badly initialised must-analysis.
    NESTED_LOOPS = """
int main() {
  int total = 0;
  int i = 0;
  while (i < 3) {
    int j = 0;
    while (j < 4) {
      if (j == 1) { j = j + 1; continue; }
      if (j == 3) { break; }
      total = total + 1;
      j = j + 1;
    }
    i = i + 1;
  }
  return total;
}
"""

    def test_facts_assigned_before_a_nested_loop_survive_both_back_edges(self):
        # By hand: every path reaching the inner header passes the two
        # initialisations in the entry block, and neither inner loop assigns
        # ``total`` or ``i`` before reading them again, so the inner header's IN
        # is {total, i, j} and no read can be "possibly uninitialised".
        analysis = analyse(self.NESTED_LOOPS).analyses["main"]
        self.assertEqual(analysis.definite.uninitialised_reads(analysis.definite_result), [])
        headers = [entry["header"] for entry in analysis.cfg.to_json()["loops"]]
        self.assertEqual(len(headers), 2)
        for header in headers:
            assigned = analysis.definite.definitely_assigned(analysis.definite_result, header)
            self.assertIn("total", strip(assigned))
        # The inner header (the larger id here) also sees ``j``, which the outer
        # body initialises before the inner loop is entered.
        inner = max(headers)
        self.assertEqual(
            strip(analysis.definite.definitely_assigned(analysis.definite_result, inner)),
            ["i", "j", "total"],
        )
        outer = min(headers)
        self.assertEqual(
            strip(analysis.definite.definitely_assigned(analysis.definite_result, outer)),
            ["i", "total"],
        )

    def test_a_variable_only_assigned_inside_a_loop_is_still_reported_after_it(self):
        # A must-analysis must not become optimistic: the loop may execute zero
        # times, so ``n`` has no value at the return.
        analysis = analyse(
            """
int main() {
  int n;
  while (input_int() > 0) { n = 1; }
  return n;
}
"""
        ).analyses["main"]
        reports = analysis.definite.uninitialised_reads(analysis.definite_result)
        self.assertEqual(
            [(report["symbol"], report["line"]) for report in reports],
            [("n", 4)],
            [(r["symbol"], r["sid"], r["line"]) for r in reports],
        )

    def test_a_loop_condition_read_before_the_body_assigns_is_reported(self):
        analysis = analyse(
            """
int main() {
  int n;
  while (n > 0) { n = 1; }
  return 0;
}
"""
        ).analyses["main"]
        reports = analysis.definite.uninitialised_reads(analysis.definite_result)
        self.assertEqual([report["symbol"] for report in reports], ["n"])

    def test_the_entry_block_starts_from_its_boundary_not_from_the_top(self):
        # A read of a parameter is fine; a read of a variable declared and not
        # initialised in the entry block is not.  Starting the entry block at the
        # lattice top would hide the second case.
        analysis = analyse(
            """
int main(int argc) {
  int unused;
  return argc + unused;
}
"""
        ).analyses["main"]
        reports = analysis.definite.uninitialised_reads(analysis.definite_result)
        self.assertEqual([report["symbol"] for report in reports], ["unused"])

    def test_the_solver_honours_a_problem_that_starts_at_the_top(self):
        # A minimal must-analysis: ``x`` holds wherever every path from the entry
        # establishes it, generated only in the entry block.  Over the nested
        # loops, the fact has to survive two cycles whose back edges are partly
        # computed, which is exactly what a bottom-initialised iteration loses.
        cfg = analyse(self.NESTED_LOOPS).cfgs["main"]
        domain = BitVectorDomain(atoms=["x"], name="must-x")

        class MustReach(DataFlowProblem):
            def __post_init__(self) -> None:
                self.name = "must-x"
                self.direction = "forward"
                self.gen = {cfg.entry: domain.singleton("x")}

            def boundary_value(self, block_id: int) -> int:
                return domain.singleton("x") if block_id == cfg.entry else 0

            def initial_value(self, block_id: int) -> int:
                # The contract: every non-boundary block starts at the top.
                return 0 if block_id == cfg.entry else domain.full()

            def meet(self, values):
                result = values[0]
                for value in values[1:]:
                    result &= value
                return result

            def transfer(self, block_id: int, in_value: int) -> int:
                return in_value | self.gen.get(block_id, 0)

        result = solve(MustReach(cfg=cfg, domain=domain))
        self.assertTrue(result.converged)
        for block_id in cfg.reachable:
            self.assertIn(
                "x",
                domain.atoms_of(result.in_values[block_id]),
                f"block {block_id} lost the must-fact",
            )

    def test_the_solver_keeps_the_bottom_start_for_a_may_analysis(self):
        # The default must stay the lattice bottom: a union-meet analysis that
        # started at the top would claim every block reachable, which is exactly
        # the mistake this contract exists to avoid.
        cfg = analyse(self.NESTED_LOOPS).cfgs["main"]
        domain = BitVectorDomain(atoms=["x"], name="may-x")

        class MayReach(DataFlowProblem):
            def __post_init__(self) -> None:
                self.name = "may-x"
                self.direction = "forward"
                self.gen = {cfg.entry: domain.singleton("x")}

            def boundary_value(self, block_id: int) -> int:
                return domain.singleton("x") if block_id == cfg.entry else 0

            def meet(self, values):
                result = 0
                for value in values:
                    result |= value
                return result

            def transfer(self, block_id: int, in_value: int) -> int:
                return in_value

        problem = MayReach(cfg=cfg, domain=domain)
        self.assertEqual(problem.initial_value(cfg.entry), 0, "default start is the bottom")
        result = solve(problem)
        for block_id in cfg.reachable:
            self.assertIn("x", domain.atoms_of(result.in_values[block_id]))


class SolverTests(unittest.TestCase):
    """The framework itself: worklist, limits, determinism, custom problems."""

    def test_iteration_cap_is_reported_not_hidden(self):
        program = analyse(WHILE_SOURCE)
        analysis = program.analyses["main"]
        result = solve(analysis.reaching, max_iterations=1)
        self.assertFalse(result.converged)
        self.assertTrue(all(block in result.in_values for block in analysis.cfg.blocks))
        # The uncapped run of the same problem does converge.
        self.assertTrue(analysis.reaching_result.converged)
        self.assertGreaterEqual(analysis.reaching_result.iterations, 1)
        self.assertEqual(analysis.reaching_result.processed_order[0], analysis.cfg.entry)
        self.assertEqual(sorted(set(analysis.reaching_result.processed_order)), sorted(analysis.cfg.blocks))

    def test_fixpoint_is_deterministic(self):
        first = analyse(WHILE_SOURCE).analyses["main"]
        second = analyse(WHILE_SOURCE).analyses["main"]
        self.assertEqual(first.reaching_result.to_json(), second.reaching_result.to_json())
        self.assertEqual(first.live_result.to_json(), second.live_result.to_json())
        self.assertEqual(
            first.definite_result.to_json(), second.definite_result.to_json()
        )

    def test_custom_problem_uses_the_same_solver(self):
        # Smallest possible client of the framework: forward block reachability
        # with a one-atom domain, union meet and the identity transfer.  It must
        # agree with the CFG's own reachability, which shows that the solver is
        # driven by the edges and not by any text-order guess.
        program = analyse(
            """
int main() {
  return 1;
  int a = 2;
}
"""
        )
        cfg = program.cfgs["main"]
        domain = BitVectorDomain(atoms=["reached"], name="block reachability")

        class Reachability(DataFlowProblem):
            def __post_init__(self) -> None:
                self.name = "reachability"
                self.direction = "forward"

            def boundary_value(self, block_id: int) -> int:
                return domain.singleton("reached") if block_id == cfg.entry else 0

            def meet(self, values):
                result = 0
                for value in values:
                    result |= value
                return result

            def transfer(self, block_id: int, in_value: int) -> int:
                return in_value

            def reachable_blocks(self):
                return set(cfg.blocks)  # analyse even the dead block

        result = solve(Reachability(cfg=cfg, domain=domain))
        reached = {
            block_id
            for block_id in cfg.blocks
            if domain.contains(result.in_values[block_id], "reached")
        }
        self.assertEqual(reached, cfg.reachable)
        self.assertEqual(result.reachable, set(cfg.blocks))

    def test_abstract_problem_must_implement_meet_and_transfer(self):
        cfg = analyse(STRAIGHT_SOURCE).cfgs["main"]
        problem = DataFlowProblem(cfg=cfg, domain=BitVectorDomain(atoms=["x"]))
        with self.assertRaises(NotImplementedError):
            problem.meet([0, 1])
        with self.assertRaises(NotImplementedError):
            problem.transfer(0, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
