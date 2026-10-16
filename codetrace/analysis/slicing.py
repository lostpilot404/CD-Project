"""Program slicing over the program dependency graph.

The slicer is a graph traversal over :mod:`codetrace.analysis.dependencies`;
it never inspects the source text to decide what belongs to a slice, so every
included statement is justified by a dependency edge with a reason.

* **Backward slice** -- starting from a criterion statement, follow incoming
  data, control, call and return edges: everything that can influence the
  criterion.
* **Forward slice** -- follow the same edges in the opposite direction:
  everything the criterion can influence.
* **Security slice** -- the backward slice of a finding's sink, annotated with
  the source-to-sink path so that the tool can highlight the route.

Slices are **conservative**: they include every statement that a sound may
analysis cannot exclude.  They are not minimal, and the API says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .dependencies import (
    CALL,
    CONTROL,
    DATA,
    DEFINE,
    RETURN,
    SANITIZE,
    SOURCE_SINK,
    TAINT,
    DependencyGraph,
)

#: Edge kinds followed when slicing.  `define` edges are part of a slice: they
#: connect a definition node back to the statement that created it, which is how
#: the traversal crosses a def-use chain.
SLICE_KINDS = (DATA, CONTROL, CALL, RETURN, TAINT, SANITIZE, DEFINE, SOURCE_SINK)

CONSERVATIVE_NOTE = (
    "The slice is conservative: it contains every statement the analysis cannot "
    "exclude. It is not guaranteed to be minimal, and constructs outside the "
    "supported language subset are not sliced at all."
)


@dataclass
class Slice:
    kind: str
    criterion: dict
    statements: List[int] = field(default_factory=list)
    reasons: Dict[int, List[str]] = field(default_factory=dict)
    edges: List[dict] = field(default_factory=list)
    note: str = CONSERVATIVE_NOTE
    truncated: bool = False
    finding_id: Optional[str] = None

    def to_json(self) -> dict:
        return {
            "kind": self.kind,
            "criterion": self.criterion,
            "statements": list(self.statements),
            "reasons": {str(k): v for k, v in self.reasons.items()},
            "edges": self.edges,
            "note": self.note,
            "truncated": self.truncated,
            "finding_id": self.finding_id,
            "statement_count": len(self.statements),
        }


class SliceEngine:
    """Computes backward, forward and finding-focused slices."""

    #: Cap on the number of statements a slice may contain; the UI shows the
    #: truncation flag rather than freezing on a degenerate program.
    MAX_STATEMENTS = 5000

    #: Cap on the number of dependency edges listed with a slice.  When the cap
    #: bites, the slice note says so -- evidence is never dropped silently.
    MAX_EDGES = 500

    def __init__(self, program) -> None:
        self.program = program
        self.graph: DependencyGraph = program.dependencies or DependencyGraph()

    # ------------------------------------------------------------------
    def _walk(self, start: str, direction: str, kinds: Sequence[str]) -> Tuple[Set[str], List[dict]]:
        visited: Set[str] = set()
        queue: List[str] = [start]
        edges_used: List[dict] = []
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            if len(visited) > self.MAX_STATEMENTS * 4:
                break
            edges = (
                self.graph.incoming(node, kinds)
                if direction == "backward"
                else self.graph.outgoing(node, kinds)
            )
            for edge in edges:
                edges_used.append(edge.to_json())
                neighbour = edge.src if direction == "backward" else edge.dst
                if neighbour not in visited:
                    queue.append(neighbour)
        return visited, edges_used

    def _collect(
        self, nodes: Set[str], edges: List[dict]
    ) -> Tuple[List[int], Dict[int, List[str]], bool]:
        """Statements of a traversal, the reason each one is included, truncation.

        A reason is recorded for *every* statement an edge touches that is part of
        the slice, not only for the statement the traversal arrived from: a
        forward slice would otherwise contain statements whose justification is
        an edge leaving a definition node, which left them unexplained.
        """
        statements: List[int] = []
        reasons: Dict[int, List[str]] = {}
        for node_id in nodes:
            if not node_id.startswith("s"):
                continue
            try:
                sid = int(node_id[1:])
            except ValueError:
                continue
            statements.append(sid)
        statements.sort()
        included = set(statements)
        for edge in edges:
            text = f"{edge['kind']}: {edge['reason']}"
            for side in ("from", "to"):
                node_id = edge[side]
                if not node_id.startswith("s"):
                    continue
                try:
                    sid = int(node_id[1:])
                except ValueError:
                    continue
                if sid not in included:
                    continue
                bucket = reasons.setdefault(sid, [])
                if text not in bucket:
                    bucket.append(text)
        truncated = len(statements) > self.MAX_STATEMENTS
        if truncated:
            statements = statements[: self.MAX_STATEMENTS]
        return statements, reasons, truncated

    # ------------------------------------------------------------------
    def backward(self, sid: int, kinds: Sequence[str] = SLICE_KINDS) -> Slice:
        node = f"s{sid}"
        if node not in self.graph.nodes:
            return Slice(
                kind="backward",
                criterion={"sid": sid},
                note="no statement with this id exists in the analysed file",
            )
        nodes, edges = self._walk(node, "backward", kinds)
        statements, reasons, truncated = self._collect(nodes, edges)
        statement = self.program.statements.get(sid)
        criterion = {
            "sid": sid,
            "text": self.program.statement_text(sid).strip(),
            "line": statement.line if statement else 0,
            "col": statement.col if statement else 0,
            "function": self.program.function_of_statement(sid),
        }
        return Slice(
            kind="backward",
            criterion=criterion,
            statements=statements,
            reasons=reasons,
            edges=edges[: self.MAX_EDGES],
            note=CONSERVATIVE_NOTE + self._edge_note(edges),
            truncated=truncated,
        )

    def forward(self, sid: int, kinds: Sequence[str] = SLICE_KINDS) -> Slice:
        node = f"s{sid}"
        if node not in self.graph.nodes:
            return Slice(
                kind="forward",
                criterion={"sid": sid},
                note="no statement with this id exists in the analysed file",
            )
        nodes, edges = self._walk(node, "forward", kinds)
        statements, reasons, truncated = self._collect(nodes, edges)
        statement = self.program.statements.get(sid)
        criterion = {
            "sid": sid,
            "text": self.program.statement_text(sid).strip(),
            "line": statement.line if statement else 0,
            "col": statement.col if statement else 0,
            "function": self.program.function_of_statement(sid),
        }
        return Slice(
            kind="forward",
            criterion=criterion,
            statements=statements,
            reasons=reasons,
            edges=edges[: self.MAX_EDGES],
            note=CONSERVATIVE_NOTE + self._edge_note(edges),
            truncated=truncated,
        )

    def for_finding(self, finding) -> Slice:
        """Security slice: the sink's backward slice plus the source-to-sink path."""
        sink_sid = finding.sink.get("sid", -1)
        sink_statement = self.program.statements.get(sink_sid)
        base = self.backward(sink_sid)
        path_statements = [step["sid"] for step in finding.path if step.get("sid", -1) >= 0]
        merged: List[int] = sorted(set(base.statements) | set(path_statements))
        truncated = base.truncated or len(merged) > self.MAX_STATEMENTS
        if len(merged) > self.MAX_STATEMENTS:
            merged = merged[: self.MAX_STATEMENTS]
        reasons = dict(base.reasons)
        for step in finding.path:
            sid = step.get("sid", -1)
            if sid >= 0:
                reasons.setdefault(sid, []).append(
                    f"source-to-sink path step: {step.get('label', step.get('kind', ''))}"
                )
        edges = list(base.edges)
        for step in finding.path:
            if step.get("sid", -1) >= 0:
                edges.append(
                    {
                        "from": f"s{step.get('from_sid', step['sid'])}",
                        "to": f"s{step['sid']}",
                        "kind": SOURCE_SINK,
                        "reason": step.get("detail", "step on the reported source-to-sink path"),
                        "symbol": step.get("symbol", ""),
                        "symbol_id": -1,
                        "definition_id": -1,
                        "condition": "",
                        "taint_atoms": list(step.get("atoms", [])),
                    }
                )
        return Slice(
            kind="security",
            criterion={
                "finding_id": finding.id,
                "rule": finding.rule_id,
                "sink": finding.sink,
                "source": finding.source,
                "sid": sink_sid,
                "text": self.program.statement_text(sink_sid).strip(),
                "line": sink_statement.line if sink_statement else 0,
                "col": sink_statement.col if sink_statement else 0,
                "function": self.program.function_of_statement(sink_sid),
            },
            statements=merged,
            reasons=reasons,
            edges=edges[: self.MAX_EDGES],
            note=(
                CONSERVATIVE_NOTE
                + " This slice is restricted to the statements reachable through the recorded "
                "dependencies of the reported flow."
                + self._edge_note(edges)
                + self._statement_note(truncated)
            ),
            finding_id=finding.id,
            truncated=truncated,
        )

    def _edge_note(self, edges: List[dict]) -> str:
        if len(edges) <= self.MAX_EDGES:
            return ""
        return (
            f" Only the first {self.MAX_EDGES} of {len(edges)} dependency edges are listed "
            "with this slice."
        )

    def _statement_note(self, truncated: bool) -> str:
        if not truncated:
            return ""
        return (
            f" The slice was cut at the {self.MAX_STATEMENTS}-statement limit, so it is "
            "incomplete."
        )

    def subgraph_json(self, statements: Sequence[int], kinds: Optional[Sequence[str]] = None) -> dict:
        """Dependency subgraph induced by a set of statements (for the UI).

        Statement-to-statement edges alone would hide the data dependencies that
        justify a slice, because those run through definition nodes.  The
        subgraph is therefore closed over the definitions that connect two
        included statements: for a ``data``/``taint`` edge *d -> s* whose
        reading statement is in the slice and whose defining statement is in the
        slice as well, the definition node and its ``define`` edge are included
        too.  No statement outside the slice is ever added.
        """
        statement_ids = {int(sid) for sid in statements}
        node_ids = {f"s{sid}" for sid in statement_ids}
        for edge in self.graph.edges:
            if edge.kind not in ("data", "taint"):
                continue
            if not edge.dst.startswith("s") or not edge.src.startswith("d"):
                continue
            if int(edge.dst[1:]) not in statement_ids:
                continue
            producers = [
                candidate
                for candidate in self.graph.incoming(edge.src)
                if candidate.kind == "define" and candidate.src in node_ids
            ]
            if not producers:
                continue
            node_ids.add(edge.src)
            for producer in producers:
                node_ids.add(producer.src)
        edges = [
            edge
            for edge in self.graph.edges
            if edge.src in node_ids and edge.dst in node_ids and (kinds is None or edge.kind in kinds)
        ]
        return {
            "nodes": [self.graph.nodes[n].to_json() for n in sorted(node_ids) if n in self.graph.nodes],
            "edges": [e.to_json() for e in edges],
        }
