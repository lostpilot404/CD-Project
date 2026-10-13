"""Dependency graph and slicing tests.

Two things are checked here that no other test file covers:

* the dependency graph contains **only** edges that the analyses justify -- every
  ``data``/``taint`` edge is cross-checked against the reaching-definitions
  result for the reading statement, so a fabricated edge fails the test;
* the slices are what the traversal says they are: the statement sets are
  hand-verified against small programs, and every statement that ends up in a
  slice carries the reason it was included.
"""

from __future__ import annotations

import unittest

from codetrace.analysis import dependencies as dep_module
from codetrace.analysis.slicing import CONSERVATIVE_NOTE, SLICE_KINDS, SliceEngine
from tests.helpers import analyse, statements_of

SLICE_SOURCE = """
int main() {
  string cmd = input();
  string unused = "clean";
  int n = 3;
  if (n > 1) {
    cmd = cmd + "!";
  }
  system(cmd);
  return 0;
}
"""

INTERPROCEDURAL_SOURCE = """
string build(string value) {
  return "ls " + value;
}

int main() {
  string cmd = build(input());
  system(cmd);
  return 0;
}
"""


class DependencyGraphTests(unittest.TestCase):
    def setUp(self):
        self.program = analyse(SLICE_SOURCE, filename="slice.ctc")
        self.graph = self.program.dependencies

    def test_nodes_and_edges_are_consistent(self):
        nodes = self.graph.nodes
        self.assertTrue(nodes)
        for node_id, node in nodes.items():
            self.assertEqual(node.id, node_id)
            self.assertIn(node.kind, (dep_module.NODE_STATEMENT, dep_module.NODE_DEFINITION, dep_module.NODE_FUNCTION))
        for edge in self.graph.edges:
            self.assertIn(edge.kind, dep_module.EDGE_KINDS)
            self.assertIn(edge.src, nodes, f"edge source {edge.src} is not a node")
            self.assertIn(edge.dst, nodes, f"edge target {edge.dst} is not a node")

    def test_stats_match_the_graph(self):
        stats = self.graph.stats()
        self.assertEqual(stats["nodes"], len(self.graph.nodes))
        self.assertEqual(stats["edges"], len(self.graph.edges))
        counted: dict = {}
        for edge in self.graph.edges:
            counted[edge.kind] = counted.get(edge.kind, 0) + 1
        self.assertEqual(stats["edge_kinds"], counted)

    def test_every_edge_states_its_reason(self):
        for edge in self.graph.edges:
            self.assertTrue(edge.reason.strip(), f"edge {edge.src}->{edge.dst} has no reason")
            payload = edge.to_json()
            self.assertEqual(payload["from"], edge.src)
            self.assertEqual(payload["to"], edge.dst)
            self.assertEqual(payload["family"], edge.family)
            self.assertTrue(payload["reason"])

    def test_data_edges_are_backed_by_reaching_definitions(self):
        # This is the "no fabricated edge" check: for every data/taint edge
        # d -> s, the definition must be one the reaching-definitions analysis
        # actually reports for the read at statement s.
        checked = 0
        for edge in self.graph.edges:
            if edge.kind not in (dep_module.DATA, dep_module.TAINT):
                continue
            self.assertTrue(edge.src.startswith("d"), "data flows from a definition node")
            self.assertTrue(edge.dst.startswith("s"), "data flows into a statement node")
            sid = int(edge.dst[1:])
            function = self.program.function_of_statement(sid)
            analysis = self.program.analyses[function]
            reaching = analysis.reaching.definitions_reaching(
                analysis.reaching_states, sid, edge.symbol_id
            )
            self.assertIn(
                edge.definition_id,
                {definition.id for definition in reaching},
                f"edge {edge.src}->{edge.dst} claims a definition that does not reach the read",
            )
            checked += 1
        self.assertGreater(checked, 0, "the fixture produces data dependencies")

    def test_definition_nodes_match_the_control_flow_graph(self):
        definitions = {}
        for cfg in self.program.cfgs.values():
            for definition in cfg.definitions:
                definitions[definition.id] = definition
        for node in self.graph.nodes.values():
            if node.kind != dep_module.NODE_DEFINITION:
                continue
            definition = definitions[node.definition_id]
            self.assertEqual(node.symbol_id, definition.symbol_id)
            self.assertEqual(node.function, definition.function)
            self.assertEqual(node.line, definition.line)

    def test_control_edges_carry_the_condition(self):
        control = [edge for edge in self.graph.edges if edge.kind == dep_module.CONTROL]
        self.assertTrue(control)
        for edge in control:
            self.assertTrue(edge.condition.strip(), "a control edge names its condition")
            self.assertIn(edge.condition, edge.reason)

    def test_taint_edges_carry_the_atoms(self):
        taint = [edge for edge in self.graph.edges if edge.kind == dep_module.TAINT]
        self.assertTrue(taint)
        for edge in taint:
            self.assertTrue(edge.taint_atoms, "a taint edge lists the atoms it carries")
            self.assertTrue(all(atom.startswith("src:stdin") for atom in edge.taint_atoms))

    def test_call_and_return_edges_connect_the_functions(self):
        graph = analyse(INTERPROCEDURAL_SOURCE, filename="inter.ctc").dependencies
        calls = [edge for edge in graph.edges if edge.kind == dep_module.CALL]
        returns = [edge for edge in graph.edges if edge.kind == dep_module.RETURN]
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(returns), 1)
        self.assertTrue(calls[0].dst.startswith("f:"), "a call edge points at the callee")
        self.assertTrue(returns[0].src.startswith("s"), "a return edge starts at the return statement")
        self.assertIn("build", calls[0].reason)
        self.assertIn("build", returns[0].reason)

    def test_statement_node_lookup(self):
        stats = statements_of(self.program, "main")
        for sid in stats:
            node_id = self.graph.statement_node(sid)
            self.assertIn(node_id, self.graph.nodes)
            self.assertEqual(self.graph.nodes[node_id].sid, sid)

    def test_to_json_is_filterable_and_deterministic(self):
        again = analyse(SLICE_SOURCE, filename="slice.ctc").dependencies
        self.assertEqual(self.graph.to_json(), again.to_json())
        only_taint = self.graph.to_json(kinds=[dep_module.TAINT])
        self.assertTrue(only_taint["edges"])
        self.assertEqual({edge["kind"] for edge in only_taint["edges"]}, {dep_module.TAINT})
        payload = self.graph.to_json()
        self.assertEqual(sorted(payload), ["edges", "limit", "nodes", "stats", "truncated"])
        self.assertGreater(payload["limit"], 0)


class SlicingTests(unittest.TestCase):
    def setUp(self):
        self.program = analyse(SLICE_SOURCE, filename="slice.ctc")
        self.slicing = self.program.slicing
        self.statements = statements_of(self.program, "main")

    def test_backward_slice_contains_only_the_dependencies(self):
        # Hand-checked: statement 4 (`cmd = cmd + "!"`) depends on the assignment
        # of `cmd` (0), on the if statement that guards it (3) and hence on `n`
        # (2), and on itself.  `unused` (1) and the sink (5) are not inputs.
        result = self.slicing.backward(4)
        self.assertEqual(result.kind, "backward")
        self.assertEqual(result.statements, [0, 2, 3, 4])
        self.assertEqual(result.criterion["line"], 6)
        self.assertEqual(result.criterion["function"], "main")
        self.assertEqual(result.criterion["text"], 'cmd = cmd + "!";')
        self.assertIn("cmd = cmd +", self.statements[4])
        self.assertNotIn(1, result.statements)
        self.assertNotIn(5, result.statements)

    def test_every_statement_in_a_slice_carries_a_reason(self):
        for result in (self.slicing.backward(4), self.slicing.forward(0), self.slicing.backward(5)):
            for sid in result.statements:
                self.assertTrue(
                    result.reasons.get(sid), f"statement {sid} is in the slice without a reason"
                )
                self.assertTrue(all(":" in reason for reason in result.reasons[sid]))

    def test_forward_slice_follows_the_direction_of_the_flow(self):
        self.assertEqual(self.slicing.forward(0).statements, [0, 4, 5])
        # Nothing reads `unused`, so its forward slice is just itself.
        self.assertEqual(self.slicing.forward(1).statements, [1])
        self.assertEqual(self.slicing.backward(1).statements, [1])

    def test_security_slice_of_a_finding(self):
        finding = self.program.findings[0]
        result = self.slicing.for_finding(finding)
        self.assertEqual(result.kind, "security")
        self.assertEqual(result.finding_id, finding.id)
        self.assertEqual(
            result.statements, [0, 2, 3, 4, 5], "the sink's backward slice plus the path"
        )
        self.assertEqual(result.criterion["finding_id"], finding.id)
        self.assertEqual(result.criterion["rule"], "command_execution")
        self.assertEqual(result.criterion["sid"], finding.sink["sid"])
        self.assertIn(CONSERVATIVE_NOTE, result.note)
        self.assertIn("conservative", result.note.lower())
        self.assertFalse(result.truncated)

    def test_a_source_to_sink_edge_is_added_to_the_security_slice(self):
        finding = self.program.findings[0]
        result = self.slicing.for_finding(finding)
        kinds = {edge["kind"] for edge in result.edges}
        self.assertIn(dep_module.SOURCE_SINK, kinds)
        self.assertIn(dep_module.TAINT, kinds)

    def test_unknown_criterion_is_reported_not_crashed(self):
        result = self.slicing.backward(9999)
        self.assertEqual(result.statements, [])
        self.assertEqual(result.edges, [])
        self.assertIn("no statement with this id", result.note)
        self.assertEqual(result.to_json()["statement_count"], 0)

    def test_slice_json_is_self_consistent_and_deterministic(self):
        again = analyse(SLICE_SOURCE, filename="slice.ctc").slicing
        first = [self.slicing.backward(4).to_json(), self.slicing.forward(0).to_json()]
        second = [again.backward(4).to_json(), again.forward(0).to_json()]
        self.assertEqual(first, second)
        payload = self.slicing.backward(4).to_json()
        self.assertEqual(sorted(payload), [
            "criterion", "edges", "finding_id", "kind", "note", "reasons",
            "statement_count", "statements", "truncated",
        ])
        self.assertEqual(payload["statement_count"], len(payload["statements"]))

    def test_subgraph_of_a_slice_never_escapes_the_slice(self):
        result = self.slicing.backward(4)
        subgraph = self.slicing.subgraph_json(result.statements)
        node_ids = {node["id"] for node in subgraph["nodes"]}
        statement_nodes = {node_id for node_id in node_ids if node_id.startswith("s")}
        self.assertEqual(statement_nodes, {f"s{sid}" for sid in result.statements})
        for edge in subgraph["edges"]:
            self.assertIn(edge["from"], node_ids)
            self.assertIn(edge["to"], node_ids)
        # The definitions that justify the slice are visible in the subgraph.
        self.assertTrue({node_id for node_id in node_ids if node_id.startswith("d")})

    def test_subgraph_of_a_security_slice_stays_consistent(self):
        finding = self.program.findings[0]
        result = self.slicing.for_finding(finding)
        subgraph = self.slicing.subgraph_json(result.statements)
        node_ids = {node["id"] for node in subgraph["nodes"]}
        self.assertLessEqual(
            {node_id for node_id in node_ids if node_id.startswith("s")},
            {f"s{sid}" for sid in result.statements},
        )
        for edge in subgraph["edges"]:
            self.assertIn(edge["src"] if "src" in edge else edge["from"], node_ids)
            self.assertIn(edge["to"], node_ids)

    def test_disabling_slices_leaves_no_slice_engine_behind(self):
        # Regression: ``run_slicing=False`` was accepted but never read, so a
        # findings-only run still built the slice engine.
        program = analyse(SLICE_SOURCE, filename="noslice.ctc", run_slicing=False)
        self.assertIsNone(program.slicing)
        self.assertIsNotNone(program.dependencies, "the graph itself is still built")
        self.assertTrue(program.findings, "findings never depend on the slices")

    def test_disabling_the_graph_disables_the_slices_traversing_it(self):
        program = analyse(SLICE_SOURCE, filename="nodeps.ctc", run_dependencies=False)
        self.assertIsNone(program.dependencies)
        self.assertIsNone(program.slicing)
        self.assertTrue(program.findings, "findings never depend on the graph")

    def test_slice_kinds_and_limits_are_documented_constants(self):
        self.assertEqual(
            set(SLICE_KINDS),
            {
                dep_module.DATA, dep_module.CONTROL, dep_module.CALL, dep_module.RETURN,
                dep_module.TAINT, dep_module.SANITIZE, dep_module.DEFINE, dep_module.SOURCE_SINK,
            },
        )
        self.assertEqual(SliceEngine.MAX_STATEMENTS, 5000)
        self.assertEqual(SliceEngine.MAX_EDGES, 500)
        self.assertIn("conservative", CONSERVATIVE_NOTE.lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
