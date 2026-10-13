"""Abstract syntax tree for the CT-C subset.

Every node carries a source span (character offsets, half-open) plus the
1-based line/column of its first token, so that every later phase (semantic
analysis, CFG, data flow, taint, slicing, reporting) can point back at exact
source text.

Design notes
------------
* Nodes are plain dataclasses with a shared :class:`Node` base that provides
  ``kind``, ``walk()`` and ``to_json()``.  There is no visitor framework and no
  hidden global state: analyses receive a node and traverse it explicitly.
* Statements expose ``sid`` (a stable statement identifier assigned once by
  the CFG builder) and expressions carry ``eid``; both are stable within a
  single analysis run and are what the API/graph layers refer to.
* ``Ident.symbol`` is filled in by semantic analysis; an unresolved identifier
  keeps ``symbol = None`` and is reported as a diagnostic rather than being
  silently treated as safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

Span = Tuple[int, int]


@dataclass
class Node:
    """Base class for every AST node."""

    span: Span = (0, 0)
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    @property
    def kind(self) -> str:
        return type(self).__name__

    # -- traversal -----------------------------------------------------
    def children(self) -> List["Node"]:
        """Semantic children, in source order."""
        out: List[Node] = []
        for value in vars(self).values():
            _collect_nodes(value, out)
        return out

    def walk(self) -> Iterator["Node"]:
        """Pre-order traversal over this node and all descendants."""
        stack: List[Node] = [self]
        while stack:
            node = stack.pop()
            yield node
            kids = node.children()
            stack.extend(reversed(kids))

    # -- serialisation -------------------------------------------------
    def summary(self) -> Dict[str, Any]:
        """Small, human-oriented description shown next to a node."""
        return {}

    def to_json(self, depth: int = 0, max_depth: int = 60) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "kind": self.kind,
            "span": list(self.span),
            "line": self.line,
            "col": self.col,
        }
        payload.update(self.summary())
        if depth < max_depth:
            kids = [
                child.to_json(depth + 1, max_depth) if isinstance(child, Node) else child
                for child in self.children()
            ]
            if kids:
                payload["children"] = kids
        return payload


def _collect_nodes(value: Any, out: List[Node]) -> None:
    if isinstance(value, Node):
        out.append(value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_nodes(item, out)


# ======================================================================
# Program structure
# ======================================================================
@dataclass
class SourceUnit(Node):
    """A whole translation unit."""

    filename: str = "<source>"
    decls: List[Node] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {"filename": self.filename, "decl_count": len(self.decls)}


@dataclass
class Param(Node):
    name: str = ""
    type_name: str = "int"
    symbol_id: int = -1

    def summary(self) -> Dict[str, Any]:
        return {"name": self.name, "type": self.type_name, "symbol_id": self.symbol_id}


@dataclass
class FunctionDecl(Node):
    name: str = ""
    return_type: str = "int"
    params: List[Param] = field(default_factory=list)
    body: Optional["Block"] = None
    symbol_id: int = -1

    def summary(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "return_type": self.return_type,
            "params": [p.name for p in self.params],
            "symbol_id": self.symbol_id,
        }


@dataclass
class VarDeclarator(Node):
    name: str = ""
    init: Optional[Node] = None
    array_size: Optional[int] = None
    symbol_id: int = -1

    def summary(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "array_size": self.array_size,
            "has_init": self.init is not None,
            "symbol_id": self.symbol_id,
        }


@dataclass
class VarDecl(Node):
    """A declaration statement (may declare several variables)."""

    type_name: str = "int"
    declarators: List[VarDeclarator] = field(default_factory=list)
    sid: int = -1

    def summary(self) -> Dict[str, Any]:
        return {
            "type": self.type_name,
            "names": [d.name for d in self.declarators],
            "sid": self.sid,
        }


# ======================================================================
# Statements
# ======================================================================
@dataclass
class Block(Node):
    statements: List[Node] = field(default_factory=list)
    sid: int = -1

    def summary(self) -> Dict[str, Any]:
        return {"statements": len(self.statements), "sid": self.sid}


@dataclass
class IfStmt(Node):
    cond: Optional[Node] = None
    then_branch: Optional[Node] = None
    else_branch: Optional[Node] = None
    sid: int = -1

    def summary(self) -> Dict[str, Any]:
        return {"has_else": self.else_branch is not None, "sid": self.sid}


@dataclass
class WhileStmt(Node):
    cond: Optional[Node] = None
    body: Optional[Node] = None
    sid: int = -1

    def summary(self) -> Dict[str, Any]:
        return {"sid": self.sid}


@dataclass
class ForStmt(Node):
    init: Optional[Node] = None
    cond: Optional[Node] = None
    update: Optional[Node] = None
    body: Optional[Node] = None
    sid: int = -1

    @property
    def init_decl(self) -> Optional[VarDecl]:
        return self.init if isinstance(self.init, VarDecl) else None

    def summary(self) -> Dict[str, Any]:
        return {
            "init": self.init.kind if self.init is not None else None,
            "has_update": self.update is not None,
            "sid": self.sid,
        }


@dataclass
class ReturnStmt(Node):
    value: Optional[Node] = None
    sid: int = -1

    def summary(self) -> Dict[str, Any]:
        return {"has_value": self.value is not None, "sid": self.sid}


@dataclass
class BreakStmt(Node):
    sid: int = -1

    def summary(self) -> Dict[str, Any]:
        return {"sid": self.sid}


@dataclass
class ContinueStmt(Node):
    sid: int = -1

    def summary(self) -> Dict[str, Any]:
        return {"sid": self.sid}


@dataclass
class EmptyStmt(Node):
    sid: int = -1

    def summary(self) -> Dict[str, Any]:
        return {"sid": self.sid}


@dataclass
class ExprStmt(Node):
    expr: Optional[Node] = None
    sid: int = -1

    def summary(self) -> Dict[str, Any]:
        return {"sid": self.sid}


# ======================================================================
# Expressions
# ======================================================================
@dataclass
class IntLit(Node):
    value: int = 0
    text: str = ""

    def summary(self) -> Dict[str, Any]:
        return {"value": self.value, "literal": self.text}


@dataclass
class FloatLit(Node):
    value: float = 0.0
    text: str = ""

    def summary(self) -> Dict[str, Any]:
        return {"value": self.value, "literal": self.text}


@dataclass
class CharLit(Node):
    value: str = ""
    text: str = ""

    def summary(self) -> Dict[str, Any]:
        return {"value": self.value, "literal": self.text}


@dataclass
class StringLit(Node):
    value: str = ""
    text: str = ""

    def summary(self) -> Dict[str, Any]:
        return {"value": self.value, "literal": self.text}


@dataclass
class BoolLit(Node):
    value: bool = False

    def summary(self) -> Dict[str, Any]:
        return {"value": self.value}


@dataclass
class Ident(Node):
    name: str = ""
    symbol_id: int = -1

    def summary(self) -> Dict[str, Any]:
        return {"name": self.name, "symbol_id": self.symbol_id}


@dataclass
class BinaryOp(Node):
    op: str = "+"
    left: Optional[Node] = None
    right: Optional[Node] = None

    def summary(self) -> Dict[str, Any]:
        return {"op": self.op}


@dataclass
class UnaryOp(Node):
    op: str = "-"
    operand: Optional[Node] = None
    prefix: bool = True

    def summary(self) -> Dict[str, Any]:
        return {"op": self.op, "prefix": self.prefix}


@dataclass
class Assign(Node):
    op: str = "="
    target: Optional[Node] = None
    value: Optional[Node] = None

    def summary(self) -> Dict[str, Any]:
        return {"op": self.op}


@dataclass
class Call(Node):
    name: str = ""
    args: List[Node] = field(default_factory=list)
    callee: Optional[Ident] = None
    symbol_id: int = -1
    #: Filled by semantic analysis: "function", "external", or "unknown".
    resolution: str = "unknown"

    def children(self) -> List["Node"]:
        # ``callee`` is also the node the call was built from; it is already
        # covered by the argument list of the parent expression, so it is not
        # reported as a separate child (this keeps traversal duplicate-free).
        return list(self.args)

    def summary(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "arg_count": len(self.args),
            "resolution": self.resolution,
        }


@dataclass
class Index(Node):
    """Array element access ``base[index]``."""

    base: Optional[Node] = None
    index: Optional[Node] = None

    def summary(self) -> Dict[str, Any]:
        return {}


# ======================================================================
# Helpers
# ======================================================================
STATEMENT_KINDS = (
    Block,
    VarDecl,
    IfStmt,
    WhileStmt,
    ForStmt,
    ReturnStmt,
    BreakStmt,
    ContinueStmt,
    EmptyStmt,
    ExprStmt,
)


def is_statement(node: object) -> bool:
    return isinstance(node, STATEMENT_KINDS)


def expressions_of(node: Node) -> List[Node]:
    """All expression nodes contained in ``node`` (including nested ones)."""
    return [n for n in node.walk() if not is_statement(n) and not isinstance(n, (SourceUnit, FunctionDecl, Param, VarDeclarator))]


def identifiers_of(node: Node) -> List[Ident]:
    return [n for n in node.walk() if isinstance(n, Ident)]


def calls_of(node: Node) -> List[Call]:
    return [n for n in node.walk() if isinstance(n, Call)]


def node_to_json(node: Optional[Node]) -> Optional[Dict[str, Any]]:
    return node.to_json() if node is not None else None


def count_nodes(node: Node) -> int:
    return sum(1 for _ in node.walk())


def annotate_locations(node: Node, index) -> None:
    """Fill ``line``/``col``/``end_line``/``end_col`` from each node's span.

    Parsing happens against shared, cached parser tables, so the semantic
    actions only record character spans; this post-pass resolves those spans
    against the concrete source text of the current analysis.
    """
    for item in node.walk():
        start, end = item.span
        item.line, item.col = index.position(start)
        item.end_line, item.end_col = index.position(end)
