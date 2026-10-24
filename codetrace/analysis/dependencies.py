"""Program dependency graph: data, control, call, return, taint and sanitizer edges.

Every edge in this graph carries the *reason* it exists, and each reason is
derived from a concrete analysis result rather than from the shape of the
source text:

===============  ==========================================================
edge kind        justification
===============  ==========================================================
``data``         definition *d* of symbol *s* is in the reaching-definitions
                 set at a statement that reads *s*
``control``      the statement is nested inside a branch or loop condition,
                 taken from the CFG's structure (the guard stack)
``call``         the statement contains a call to a function defined in this
                 file (call graph edge)
``return``       a return statement of the callee flows into the call site
``taint``        the data edge carries at least one taint atom, recorded by
                 the taint analysis
``sanitize``     the statement applies a sanitizer/validator rule to a value
``define``       the statement creates the definition (the write end of a
                 def-use chain; without it a definition node would be a sink
                 with no producer and slices could not cross it)
``source-sink``  the edge lies on a reported source-to-sink path
===============  ==========================================================

Nodes are statements, definitions and functions.  Statement nodes use the
stable ``sid``; definitions use ``d<id>``; functions use ``f:<name>``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..frontend.ast_nodes import (
    Assign,
    Block,
    Call,
    ExprStmt,
    ForStmt,
    FunctionDecl,
    Ident,
    IfStmt,
    Index,
    Node,
    ReturnStmt,
    SourceUnit,
    UnaryOp,
    VarDecl,
    WhileStmt,
)
from .accesses import statement_accesses
from .cfg import CFG, Definition, expression_text

# Edge kinds
DATA = "data"
CONTROL = "control"
CALL = "call"
RETURN = "return"
TAINT = "taint"
SANITIZE = "sanitize"
DEFINE = "define"
SOURCE_SINK = "source-to-sink"

EDGE_KINDS = (DATA, CONTROL, CALL, RETURN, TAINT, SANITIZE, DEFINE, SOURCE_SINK)

NODE_STATEMENT = "statement"
NODE_DEFINITION = "definition"
NODE_FUNCTION = "function"


@dataclass
class DepNode:
    id: str
    kind: str
    label: str
    sid: int = -1
    function: str = ""
    symbol_id: int = -1
    definition_id: int = -1
    line: int = 0
    col: int = 0
    span: Tuple[int, int] = (0, 0)
    taint_atoms: Tuple[str, ...] = ()

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "sid": self.sid,
            "function": self.function,
            "symbol_id": self.symbol_id,
            "definition_id": self.definition_id,
            "line": self.line,
            "col": self.col,
            "span": list(self.span),
            "taint_atoms": list(self.taint_atoms),
        }


@dataclass
class DepEdge:
    src: str
    dst: str
    kind: str
    reason: str
    symbol_id: int = -1
    symbol: str = ""
    definition_id: int = -1
    condition: str = ""
    taint_atoms: Tuple[str, ...] = ()

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.src, self.dst, self.kind)

    @property
    def family(self) -> str:
        """Coarse edge family used by the UI filters.

        A ``taint`` edge *is* a data edge: it says the same thing as a ``data``
        edge (a definition reaches a read) and adds that the value carries an
        untrusted-data atom.  Grouping it under the ``data`` family lets the
        graph view offer "data" (all value flow) and "taint only" (untrusted
        value flow) without duplicating edges.
        """
        return DATA if self.kind == TAINT else self.kind

    def to_json(self) -> dict:
        return {
            "from": self.src,
            "to": self.dst,
            "kind": self.kind,
            "family": self.family,
            "reason": self.reason,
            "symbol": self.symbol,
            "symbol_id": self.symbol_id,
            "definition_id": self.definition_id,
            "condition": self.condition,
            "taint_atoms": list(self.taint_atoms),
        }


@dataclass
class DependencyGraph:
    nodes: Dict[str, DepNode] = field(default_factory=dict)
    edges: List[DepEdge] = field(default_factory=list)
    _out: Dict[str, List[DepEdge]] = field(default_factory=dict)
    _in: Dict[str, List[DepEdge]] = field(default_factory=dict)

    def add_node(self, node: DepNode) -> DepNode:
        self.nodes[node.id] = node
        return node

    def add_edge(self, edge: DepEdge) -> None:
        self.edges.append(edge)
        self._out.setdefault(edge.src, []).append(edge)
        self._in.setdefault(edge.dst, []).append(edge)

    def outgoing(self, node_id: str, kinds: Optional[Sequence[str]] = None) -> List[DepEdge]:
        edges = self._out.get(node_id, [])
        if kinds:
            return [e for e in edges if e.kind in kinds]
        return list(edges)

    def incoming(self, node_id: str, kinds: Optional[Sequence[str]] = None) -> List[DepEdge]:
        edges = self._in.get(node_id, [])
        if kinds:
            return [e for e in edges if e.kind in kinds]
        return list(edges)

    def edge_kind_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for edge in self.edges:
            counts[edge.kind] = counts.get(edge.kind, 0) + 1
        return counts

    def statement_node(self, sid: int) -> str:
        return f"s{sid}"

    def stats(self) -> dict:
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "edge_kinds": self.edge_kind_counts(),
        }

    def to_json(self, kinds: Optional[Sequence[str]] = None, limit: int = 4000) -> dict:
        # ``kinds`` matches either the exact edge kind or the edge family, so
        # asking for "data" returns taint-carrying data edges as well.
        edges = [
            e for e in self.edges
            if kinds is None or e.kind in kinds or e.family in kinds
        ]
        used = {e.src for e in edges} | {e.dst for e in edges}
        nodes = [n.to_json() for n in self.nodes.values() if n.id in used]
        truncated = len(edges) > limit
        return {
            "nodes": nodes[:limit],
            "edges": [e.to_json() for e in edges[:limit]],
            "stats": self.stats(),
            "truncated": truncated,
            "limit": limit,
        }


# ----------------------------------------------------------------------
# Control dependencies from the AST
# ----------------------------------------------------------------------
@dataclass
class ControlDep:
    controller_sid: int
    condition: str
    kind: str  # "if" | "else" | "while" | "for"
    line: int
    col: int


def control_dependencies(program) -> Dict[int, List[ControlDep]]:
    """Map every statement to the conditions that control its execution.

    The walk mirrors the structured statement grammar: a statement nested in an
    ``if``/``while``/``for`` body is control dependent on that statement's
    condition.  Because the language has no ``goto``, this structured walk is
    exactly the control-dependence relation of the CFG for these constructs.
    """
    result: Dict[int, List[ControlDep]] = {}

    def visit(node: Node, guards: List[ControlDep]) -> None:
        if node is None:
            return
        if isinstance(node, Block):
            for statement in node.statements:
                visit(statement, guards)
            return
        if isinstance(node, (IfStmt, WhileStmt, ForStmt)):
            result.setdefault(node.sid, []).extend(guards)
            condition = expression_text(node.cond) if getattr(node, "cond", None) else ""
            if isinstance(node, IfStmt):
                new_guards = guards + [ControlDep(node.sid, condition or "true", "if", node.line, node.col)]
                if node.then_branch is not None:
                    visit(node.then_branch, new_guards)
                if node.else_branch is not None:
                    else_guards = guards + [
                        ControlDep(node.sid, f"not ({condition})" if condition else "false", "else", node.line, node.col)
                    ]
                    visit(node.else_branch, else_guards)
            else:
                kind = "while" if isinstance(node, WhileStmt) else "for"
                body_guards = guards + [
                    ControlDep(node.sid, condition or "true", kind, node.line, node.col)
                ]
                visit(node.body, body_guards)
                if isinstance(node, ForStmt):
                    for extra in (node.init, node.update):
                        if extra is not None:
                            visit(extra, guards)
            return
        result.setdefault(getattr(node, "sid", -1), []).extend(guards)

    result = {}
    for decl in program.semantic.tree.decls:
        if isinstance(decl, FunctionDecl) and decl.body is not None:
            visit(decl.body, [])
    return result


# ----------------------------------------------------------------------
# Graph construction
# ----------------------------------------------------------------------
def build_graph(program) -> DependencyGraph:
    graph = DependencyGraph()
    statements = program.statements
    index = program.parse.index
    controls = control_dependencies(program)

    # -- nodes ---------------------------------------------------------
    for sid, node in statements.items():
        text = program.source[node.span[0] : node.span[1]].strip().replace("\n", " ")
        if len(text) > 80:
            text = text[:77] + "..."
        graph.add_node(
            DepNode(
                id=graph.statement_node(sid),
                kind=NODE_STATEMENT,
                label=text or node.kind,
                sid=sid,
                function=program.function_of_statement(sid) or "",
                line=node.line,
                col=node.col,
                span=node.span,
            )
        )
    for name, cfg in program.cfgs.items():
        graph.add_node(
            DepNode(
                id=f"f:{name}",
                kind=NODE_FUNCTION,
                label=f"{name}()",
                function=name,
                line=cfg.span[0] and index.position(cfg.span[0])[0] if cfg.span != (0, 0) else 0,
                col=index.position(cfg.span[0])[1] if cfg.span != (0, 0) else 0,
                span=cfg.span,
            )
        )
        for definition in cfg.definitions:
            graph.add_node(
                DepNode(
                    id=f"d{definition.id}",
                    kind=NODE_DEFINITION,
                    label=f"{definition.symbol_name} @ {definition.line}:{definition.col}",
                    sid=definition.sid,
                    function=definition.function,
                    symbol_id=definition.symbol_id,
                    definition_id=definition.id,
                    line=definition.line,
                    col=definition.col,
                )
            )

    # -- definition edges (statement -> the definitions it creates) ------
    # A definition node records *what* was defined; this edge records *where*.
    # Together with the def-use edges below it turns the graph into a graph
    # over statements, which is what slicing traverses.
    for name, cfg in program.cfgs.items():
        for definition in cfg.definitions:
            if definition.sid < 0:
                continue
            src = graph.statement_node(definition.sid)
            if src not in graph.nodes:
                continue
            graph.add_edge(
                DepEdge(
                    src=src,
                    dst=f"d{definition.id}",
                    kind=DEFINE,
                    reason=(
                        f"statement at line {definition.line} creates definition "
                        f"'{definition.symbol_name}' ({definition.describe()})"
                    ),
                    symbol_id=definition.symbol_id,
                    symbol=definition.symbol_name,
                    definition_id=definition.id,
                )
            )

    # -- data dependency edges -----------------------------------------
    for name, analysis in program.analyses.items():
        cfg = analysis.cfg
        problem = analysis.reaching
        states = analysis.reaching_states
        taint_run = program.taint.runs.get(name)
        taint_problem = program.taint.problems.get(name)
        definitions = {d.id: d for d in cfg.definitions}
        for block in cfg.sorted_blocks():
            if block.id not in analysis.reaching_result.reachable:
                continue
            for statement in block.statements:
                sid = statement.sid
                reads, _writes = statement_accesses(statement)
                reaching_bits = states.get(sid, (0, 0))[0]
                state_in = taint_run.statement_in.get(sid, 0) if taint_run else 0
                for symbol_id in sorted(reads):
                    atoms: Tuple[str, ...] = ()
                    if taint_problem is not None and state_in:
                        atoms = tuple(
                            sorted(taint_problem.atom_texts(taint_problem.get(state_in, symbol_id)))
                        )
                    for definition in problem.definitions_reaching(states, sid, symbol_id):
                        reason = (
                            f"definition of '{definition.symbol_name}' at line {definition.line} "
                            f"({definition.describe()}) reaches the read of '{definition.symbol_name}' "
                            f"at line {statement.line}"
                        )
                        graph.add_edge(
                            DepEdge(
                                src=f"d{definition.id}",
                                dst=graph.statement_node(sid),
                                kind=TAINT if atoms else DATA,
                                reason=reason,
                                symbol_id=symbol_id,
                                symbol=definition.symbol_name,
                                definition_id=definition.id,
                                taint_atoms=atoms,
                            )
                        )

    # -- control dependency edges ---------------------------------------
    for sid, guards in controls.items():
        if sid < 0 or graph.statement_node(sid) not in graph.nodes:
            continue
        for guard in guards:
            if graph.statement_node(guard.controller_sid) not in graph.nodes:
                continue
            graph.add_edge(
                DepEdge(
                    src=graph.statement_node(guard.controller_sid),
                    dst=graph.statement_node(sid),
                    kind=CONTROL,
                    reason=(
                        f"statement executes only when the {guard.kind} condition "
                        f"'{guard.condition}' holds (line {guard.line})"
                    ),
                    condition=guard.condition,
                )
            )

    # -- call / return / sanitizer edges ---------------------------------
    for call_site in program.semantic.calls:
        caller_function = call_site.function or ""
        sid = _sid_of_node(program, call_site.node)
        callee = program.functions.get(call_site.name)
        if callee is not None and sid >= 0:
            graph.add_edge(
                DepEdge(
                    src=graph.statement_node(sid),
                    dst=f"f:{call_site.name}",
                    kind=CALL,
                    reason=(
                        f"statement calls {call_site.name}() with {len(call_site.args)} argument(s); "
                        f"the callee's parameters receive those values"
                    ),
                )
            )
            for return_sid, return_node in _returns_of(program, callee):
                if return_sid >= 0:
                    graph.add_edge(
                        DepEdge(
                            src=graph.statement_node(return_sid),
                            dst=graph.statement_node(sid),
                            kind=RETURN,
                            reason=(
                                f"the value returned at line {return_node.line} of "
                                f"{call_site.name}() becomes the value of the call expression"
                            ),
                        )
                    )
        if sid >= 0:
            rules = program.rules.sanitizer_rules(call_site.name)
            for rule in rules:
                if call_site.node.args:
                    graph.add_edge(
                        DepEdge(
                            src=graph.statement_node(sid),
                            dst=graph.statement_node(sid),
                            kind=SANITIZE,
                            reason=(
                                f"'{call_site.name}' is a configured {rule.kind} for context "
                                f"'{rule.context}': it removes taint atoms of that context from "
                                f"argument {rule.argument}"
                            ),
                            condition=rule.context,
                        )
                    )

    return graph


def add_source_sink_edges(program) -> int:
    """Add one ``source-to-sink`` edge per hop of every reported flow's path.

    ``EDGE_KINDS``, the module docstring, the API schema and the interface legend
    all declare ``source-to-sink`` as an edge kind of the dependency graph, and
    the path of a finding is an ordered chain of statements.  Without these
    edges the graph a caller reads -- and the Program Graph view that renders
    it -- would show every other relation of the program but omit the reported
    flows themselves, which is the one relation a reviewer came to see.

    The findings are produced after the graph is built (they summarise the
    analyses that run over it), so the edges are appended here, once the paths
    exist.  They are ordinary graph edges: they take part in the edge-kind
    filters and in the subgraph a slice induces, so the slicing view shows the
    route through the same edges the graph view draws.

    ``source-to-sink`` edges are *not* part of the backward/forward slice
    traversal's justification: a slice's membership is decided by the data,
    control, call, return and define edges it follows, exactly as before.
    """
    graph = program.dependencies
    if graph is None:
        return 0
    added = 0
    seen: Set[Tuple[str, str, str]] = set()
    for finding in program.findings:
        for step in finding.path:
            src_sid = step.get("from_sid", -1)
            dst_sid = step.get("sid", -1)
            if src_sid < 0 or dst_sid < 0:
                continue
            src, dst = f"s{src_sid}", f"s{dst_sid}"
            if src not in graph.nodes or dst not in graph.nodes:
                continue
            # A path that explains two things about one statement yields a hop
            # from that statement to itself; a relation joins two statements, so
            # those degenerate self-loops are left out.
            if src == dst:
                continue
            if (src, dst, SOURCE_SINK) in seen:
                continue
            seen.add((src, dst, SOURCE_SINK))
            label = step.get("label") or step.get("kind") or "path step"
            detail = step.get("detail")
            reason = f"source-to-sink path step: {label}"
            if detail:
                reason = f"{reason} ({detail})"
            graph.add_edge(
                DepEdge(
                    src=src,
                    dst=dst,
                    kind=SOURCE_SINK,
                    reason=reason,
                    symbol=step.get("symbol", ""),
                    taint_atoms=tuple(step.get("atoms", [])),
                )
            )
            added += 1
    return added


def _sid_of_node(program, node: Node) -> int:
    for sid, statement in program.statements.items():
        if statement is node:
            return sid
        if isinstance(statement, ExprStmt) and statement.expr is node:
            return sid
    # Fall back to the innermost statement containing the node.
    best = -1
    best_span = None
    for sid, statement in program.statements.items():
        start, end = statement.span
        if start <= node.span[0] and node.span[1] <= end:
            span = end - start
            if best_span is None or span < best_span:
                best_span = span
                best = sid
    return best


def _returns_of(program, function: FunctionDecl) -> List[Tuple[int, Node]]:
    out: List[Tuple[int, Node]] = []
    if function.body is None:
        return out
    for node in function.body.walk():
        if isinstance(node, ReturnStmt):
            out.append((_sid_of_node(program, node), node))
    return out
