"""Control-flow graph tests.

Every expected number in this module was derived by hand from the source text
before the assertions were written; the comment above each expectation records
that derivation so a failure can be diagnosed without re-running the builder.
"""

from __future__ import annotations

import unittest

from tests.helpers import analyse, statements_of

#: Edge roles the builder is allowed to emit.  ``sequential`` is fall-through,
#: the rest are classified control transfers.
CFG_EDGE_KINDS = {
    "sequential",
    "true",
    "false",
    "loop-back",
    "break",
    "continue",
    "return",
    "exit",
}


def graph(source: str, function: str = "main"):
    program = analyse(source)
    return program, program.cfgs[function]


def successors(cfg, block_id):
    return sorted((edge.kind, edge.dst) for edge in cfg.block(block_id).successors)


class BasicShapeTests(unittest.TestCase):
    def test_straight_line_function_is_entry_plus_exit(self):
        # int a = 1; a = a + 2; return a;  -> all three statements run in the
        # entry block, and the trailing ``return`` jumps to the exit block.
        source = """
int main() {
  int a = 1;
  a = a + 2;
  return a;
}
"""
        program, cfg = graph(source)
        self.assertEqual(len(cfg.blocks), 2)
        self.assertEqual(cfg.entry, 0)
        self.assertEqual(cfg.exit, 1)
        entry = cfg.block(cfg.entry)
        self.assertEqual(entry.kind, "entry")
        self.assertEqual(sorted(entry.statement_ids), [0, 1, 2])
        self.assertEqual(cfg.block(cfg.exit).kind, "exit")
        self.assertEqual(successors(cfg, cfg.entry), [("return", cfg.exit)])
        self.assertEqual(successors(cfg, cfg.exit), [])
        self.assertEqual(cfg.loops, [])
        self.assertEqual(cfg.unreachable, set())
        self.assertEqual(len(cfg.edges()), 1)
        self.assertEqual(len(cfg.definitions), 2)  # decl-init + assign

    def test_if_else_creates_branch_and_merge(self):
        # B0 keeps both leading statements and branches; the then/else blocks
        # join again in the merge block that holds the trailing return.
        source = """
int main() {
  int a = 1;
  if (a < 2) {
    a = 3;
  } else {
    a = 4;
  }
  return a;
}
"""
        program, cfg = graph(source)
        self.assertEqual(len(cfg.blocks), 5)
        self.assertEqual(len(cfg.edges()), 5)
        self.assertEqual(cfg.loops, [])
        self.assertEqual(sorted(cfg.block(0).statement_ids), [0, 1])
        self.assertEqual(successors(cfg, 0), [("false", 4), ("true", 3)])
        self.assertEqual(sorted(cfg.block(3).statement_ids), [2])  # a = 3;
        self.assertEqual(sorted(cfg.block(4).statement_ids), [3])  # a = 4;
        self.assertEqual(sorted(cfg.block(2).statement_ids), [4])  # return a;
        self.assertEqual(successors(cfg, 3), [("sequential", 2)])
        self.assertEqual(successors(cfg, 4), [("sequential", 2)])
        # ``predecessors`` holds the incoming edge sources (block ids).
        self.assertEqual(sorted(cfg.block(2).predecessors), [3, 4])
        self.assertEqual(successors(cfg, 2), [("return", cfg.exit)])

    def test_branch_edge_conditions_record_direction(self):
        program, cfg = graph(
            """
int main() {
  int a = 1;
  if (a < 2) { a = 3; }
  return a;
}
"""
        )
        by_kind = {}
        for edge in cfg.edges():
            by_kind.setdefault(edge.kind, []).append(edge)
        self.assertEqual([edge.condition for edge in by_kind["true"]], ["a < 2"])
        self.assertEqual([edge.condition for edge in by_kind["false"]], ["not (a < 2)"])
        self.assertTrue(by_kind["true"][0].label)


class LoopTests(unittest.TestCase):
    def test_while_loop_header_back_edge_and_loop_info(self):
        # int a = 1;                 -> block 0
        # while (a < 3) {            -> block 2 (header, back-edge target)
        #   a = a + 1;               -> block 4 (body)
        # }
        # return a;                  -> block 3 (after loop)
        source = """
int main() {
  int a = 1;
  while (a < 3) {
    a = a + 1;
  }
  return a;
}
"""
        program, cfg = graph(source)
        self.assertEqual(len(cfg.blocks), 5)
        self.assertEqual(len(cfg.edges()), 5)
        self.assertEqual(len(cfg.loops), 1)
        self.assertEqual(successors(cfg, 0), [("sequential", 2)])
        header = cfg.block(2)
        self.assertEqual(header.kind, "loop-header")
        self.assertEqual(sorted(header.statement_ids), [1])
        self.assertEqual(successors(cfg, 2), [("false", 3), ("true", 4)])
        self.assertEqual(successors(cfg, 4), [("loop-back", 2)])
        loop = cfg.loops[0]
        self.assertEqual(loop.header, 2)
        self.assertEqual(loop.body_entry, 4)
        self.assertEqual(loop.break_target, 3)
        self.assertEqual(loop.continue_target, 2)
        self.assertEqual(loop.kind, "while")
        # The header is entered from before the loop and from the back edge.
        self.assertEqual(sorted(header.predecessors), [0, 4])

    def test_break_and_continue_targets_are_distinct_blocks(self):
        source = """
int main() {
  int i = 0;
  while (i < 10) {
    i = i + 1;
    if (i == 3) { continue; }
    if (i == 5) { break; }
    i = i + 1;
  }
  return i;
}
"""
        program, cfg = graph(source)
        self.assertEqual(len(cfg.blocks), 9)
        self.assertEqual(len(cfg.edges()), 11)
        loop = cfg.loops[0]
        kinds = {}
        for edge in cfg.edges():
            kinds.setdefault(edge.kind, []).append(edge)
        self.assertEqual(sorted((e.src, e.dst) for e in kinds["continue"]), [(6, loop.header)])
        self.assertEqual(sorted((e.src, e.dst) for e in kinds["break"]), [(8, loop.break_target)])
        self.assertEqual(sorted((e.src, e.dst) for e in kinds["loop-back"]), [(7, loop.header)])

    def test_for_loop_initialiser_update_and_single_header(self):
        # The initialiser is a statement of the enclosing function and runs
        # once, before the header; the update runs before every back edge.
        source = """
int main() {
  int total = 0;
  for (int i = 0; i < 4; i = i + 1) {
    total = total + i;
  }
  return total;
}
"""
        program, cfg = graph(source)
        texts = statements_of(program, "main")
        self.assertEqual(len(cfg.blocks), 6)
        self.assertEqual(len(cfg.loops), 1)
        entry_statements = [texts[sid] for sid in sorted(cfg.block(0).statement_ids)]
        # The initialiser is a declaration statement and keeps its ``;``; the
        # update is a bare expression node and is rendered without one.
        self.assertEqual(entry_statements, ["int total = 0;", "int i = 0;"])
        header = cfg.block(cfg.loops[0].header)
        self.assertEqual(header.kind, "loop-header")
        header_texts = [texts[sid] for sid in header.statement_ids]
        self.assertEqual(len(header_texts), 1)
        self.assertTrue(header_texts[0].startswith("for (int i = 0; i < 4; i = i + 1)"))
        self.assertIn("total = total + i;", header_texts[0])
        update = cfg.block(cfg.loops[0].continue_target)
        self.assertEqual([texts[sid] for sid in update.statement_ids], ["i = i + 1"])
        self.assertEqual(successors(cfg, update.id), [("loop-back", header.id)])

    def test_nested_loops_produce_two_headers(self):
        source = """
int main() {
  int i = 0;
  while (i < 3) {
    int j = 0;
    while (j < 3) {
      j = j + 1;
    }
    i = i + 1;
  }
  return i;
}
"""
        program, cfg = graph(source)
        self.assertEqual(len(cfg.blocks), 8)
        self.assertEqual(len(cfg.edges()), 9)
        self.assertEqual(len(cfg.loops), 2)
        headers = sorted(loop.header for loop in cfg.loops)
        self.assertEqual(headers, [2, 5])
        self.assertEqual(cfg.block(2).kind, "loop-header")
        self.assertEqual(cfg.block(5).kind, "loop-header")
        back_edges = sorted(edge.src for edge in cfg.edges() if edge.kind == "loop-back")
        self.assertEqual(back_edges, [6, 7])  # inner body -> header, outer update -> header
        self.assertEqual(
            sorted((loop.kind, loop.header, loop.body_entry) for loop in cfg.loops),
            [("while", 2, 4), ("while", 5, 7)],
        )


class ReachabilityTests(unittest.TestCase):
    def test_statements_after_return_are_unreachable_not_dropped(self):
        source = """
int main() {
  return 1;
  int a = 2;
  return a;
}
"""
        program, cfg = graph(source)
        self.assertEqual(len(cfg.blocks), 3)
        dead = cfg.unreachable
        self.assertEqual(dead, {2})
        self.assertEqual(cfg.block(2).kind, "unreachable")
        self.assertEqual(cfg.reachable, {0, 1})
        # The dead statements are still represented, with their own definition.
        self.assertEqual(sorted(cfg.block(2).statement_ids), [1, 2])
        self.assertEqual([definition.symbol_name for definition in cfg.definitions], ["a"])
        self.assertIn(2, [block_id for block_id in cfg.blocks if block_id in dead])

    def test_reachability_survives_dead_branch_after_continue(self):
        # ``int dead = 9;`` sits after an unconditional continue: unreachable.
        source = """
int main() {
  int i = 0;
  while (i < 4) {
    continue;
    int dead = 9;
  }
  return i;
}
"""
        program, cfg = graph(source)
        self.assertEqual(len(cfg.unreachable), 1)
        dead_id = sorted(cfg.unreachable)[0]
        self.assertEqual(cfg.block(dead_id).kind, "unreachable")
        self.assertEqual([definition.symbol_name for definition in cfg.definitions], ["i", "dead"])
        dead_sids = sorted(cfg.block(dead_id).statement_ids)
        self.assertEqual(
            [statements_of(program, "main")[sid] for sid in dead_sids], ["int dead = 9;"]
        )

    def test_configuration_is_deterministic(self):
        source = """
int main() {
  int i = 0;
  while (i < 3) {
    if (i == 1) { i = i + 2; } else { i = i + 1; }
  }
  return i;
}
"""
        first = analyse(source).cfgs["main"].to_json()
        second = analyse(source).cfgs["main"].to_json()
        self.assertEqual(first, second)


class DefinitionAndEntryTests(unittest.TestCase):
    def test_parameters_and_globals_are_entry_definitions(self):
        source = """
int limit = 5;
int add(int a) {
  int b = a + limit;
  b = b + 1;
  return b;
}
"""
        program = analyse(source)
        cfg = program.cfgs["add"]
        entry = cfg.block(cfg.entry)
        kinds = [(definition.symbol_name, definition.kind) for definition in cfg.definitions]
        self.assertEqual(
            sorted(kinds),
            [("a", "parameter"), ("b", "assign"), ("b", "decl-init"), ("limit", "global-init")],
        )
        entry_names = [
            next(d.symbol_name for d in cfg.definitions if d.id == def_id)
            for def_id in entry.entry_definition_ids
        ]
        self.assertEqual(sorted(entry_names), ["a", "limit"])
        self.assertEqual(
            sorted(definition.sid for definition in cfg.definitions if definition.kind == "parameter"),
            [-2],
        )

    def test_each_function_gets_its_own_cfg_with_unique_block_ids(self):
        source = """
int helper(int x) {
  return x + 1;
}
int main() {
  int a = helper(2);
  return a;
}
"""
        program = analyse(source)
        self.assertEqual(sorted(program.cfgs), ["helper", "main"])
        ids = []
        for cfg in program.cfgs.values():
            ids.extend(cfg.blocks)
        self.assertEqual(len(ids), len(set(ids)), "block ids must be unique across functions")
        self.assertEqual(program.cfgs["helper"].function, "helper")
        self.assertEqual(program.cfgs["main"].function, "main")

    def test_statements_are_attached_to_exactly_one_block(self):
        source = """
int main() {
  int a = 1;
  while (a < 3) {
    a = a + 1;
  }
  return a;
}
"""
        program, cfg = graph(source)
        seen = {}
        for block in cfg.sorted_blocks():
            for sid in block.statement_ids:
                self.assertNotIn(sid, seen, f"statement {sid} in two blocks")
                seen[sid] = block.id
        self.assertEqual(sorted(seen), sorted(program.statements))


class SerialisationTests(unittest.TestCase):
    def test_to_json_shape_and_edge_roles(self):
        source = """
int main() {
  int a = 1;
  if (a < 2) { a = 3; }
  return a;
}
"""
        program, cfg = graph(source)
        payload = cfg.to_json()
        self.assertEqual(
            sorted(payload),
            ["blocks", "definitions", "edges", "entry", "exit", "function", "loops", "reachable", "unreachable"],
        )
        self.assertEqual(payload["function"], "main")
        for edge in payload["edges"]:
            self.assertIn(edge["kind"], CFG_EDGE_KINDS)
        for block in payload["blocks"]:
            self.assertIn(block["kind"], {"entry", "exit", "normal", "loop-header", "unreachable"})
        stats = cfg.stats()
        self.assertEqual(stats["blocks"], len(cfg.blocks))
        self.assertEqual(stats["edges"], len(cfg.edges()))
        self.assertEqual(stats["unreachable_blocks"], 0)
        self.assertEqual(stats["loops"], 0)

    def test_json_blocks_carry_statement_ids_and_successors(self):
        source = """
int main() {
  int a = 1;
  return a;
}
"""
        program, cfg = graph(source)
        payload = cfg.to_json()
        first = payload["blocks"][0]
        self.assertEqual(first["id"], cfg.entry)
        self.assertEqual(first["statement_ids"], [0, 1])
        self.assertEqual([(edge["to"], edge["kind"]) for edge in first["successors"]], [(cfg.exit, "return")])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
