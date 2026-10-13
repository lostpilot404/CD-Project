"""Control-flow graph construction over the CT-C AST.

Construction is *structured*: the CFG is derived from the shape of the AST
rather than from statement order in the source text, which is what makes the
graph reflect real control flow.

The builder emits one block per maximal straight-line sequence of statements
("basic block" in the classical sense: single entry, single exit, no internal
branching) and connects them with typed edges:

======================  =====================================================
edge kind               meaning
======================  =====================================================
``sequential``          fall-through from one block to the next
``true`` / ``false``    the two outcomes of a conditional test
``loop-back``           edge from the end of a loop body to its header
``break``               jump out of the innermost loop
``continue``            jump to the loop update / header
``return``              return from the function to the exit block
``exit``                fall-off-the-end transition into the exit block
======================  =====================================================

Every block records the AST statements it contains, and every statement gets a
stable ``sid`` so that later phases and the UI can refer to statements without
re-parsing the source.

Definitions (assignments, initialised declarations, parameters, ``++``/``--``)
are numbered here as well, because reaching-definitions analysis and the taint
engine both need a stable notion of "this definition of this variable at this
statement".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..frontend.ast_nodes import (
    Assign,
    BinaryOp,
    Block,
    BreakStmt,
    Call,
    ContinueStmt,
    EmptyStmt,
    ExprStmt,
    ForStmt,
    FunctionDecl,
    Ident,
    IfStmt,
    Index,
    IntLit,
    FloatLit,
    CharLit,
    StringLit,
    BoolLit,
    Node,
    ReturnStmt,
    SourceUnit,
    UnaryOp,
    VarDecl,
    WhileStmt,
    is_statement,
)

# ----------------------------------------------------------------------
# Definitions
# ----------------------------------------------------------------------
ASSIGN = "assign"
DECL_INIT = "decl-init"
DECL_UNINIT = "decl-uninit"
PARAMETER = "parameter"
INCDEC = "incdec"
GLOBAL_INIT = "global-init"
GLOBAL_UNINIT = "global-uninit"
#: Pseudo statement id used for definitions that are in force before the first
#: statement of a function (parameters and file-scope variables).
PROGRAM_START_SID = -2


@dataclass(frozen=True)
class Definition:
    """A program point that writes a value to a symbol."""

    id: int
    symbol_id: int
    symbol_name: str
    kind: str
    sid: int
    offset: int
    line: int
    col: int
    function: str
    op: str = ""

    def describe(self) -> str:
        if self.kind == ASSIGN:
            return f"{self.symbol_name} = ... (assignment)"
        if self.kind == DECL_INIT:
            return f"{self.symbol_name} declared and initialised"
        if self.kind == DECL_UNINIT:
            return f"{self.symbol_name} declared without an initialiser (value undefined)"
        if self.kind == PARAMETER:
            return f"{self.symbol_name} is a parameter of {self.function}"
        if self.kind == INCDEC:
            return f"{self.symbol_name} updated by '{self.op}'"
        if self.kind == GLOBAL_INIT:
            return f"file-scope {self.symbol_name} initialised before program start"
        if self.kind == GLOBAL_UNINIT:
            return f"file-scope {self.symbol_name} (zero-initialised before program start)"
        return f"definition of {self.symbol_name}"

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "symbol_id": self.symbol_id,
            "symbol": self.symbol_name,
            "kind": self.kind,
            "sid": self.sid,
            "offset": self.offset,
            "line": self.line,
            "col": self.col,
            "function": self.function,
            "op": self.op,
            "description": self.describe(),
        }


# ----------------------------------------------------------------------
# Graph elements
# ----------------------------------------------------------------------
@dataclass
class CFGEdge:
    src: int
    dst: int
    kind: str
    label: str = ""
    condition: str = ""

    def to_json(self) -> dict:
        return {
            "from": self.src,
            "to": self.dst,
            "kind": self.kind,
            "label": self.label,
            "condition": self.condition,
        }


@dataclass
class BasicBlock:
    id: int
    function: str
    kind: str = "normal"  # entry | exit | normal | loop-header | unreachable
    statements: List[Node] = field(default_factory=list)
    statement_ids: List[int] = field(default_factory=list)
    #: Definitions already in force when this block runs: parameters and
    #: file-scope variables (entry block only).
    entry_definition_ids: List[int] = field(default_factory=list)
    successors: List[CFGEdge] = field(default_factory=list)
    predecessors: List[int] = field(default_factory=list)
    span: Tuple[int, int] = (0, 0)

    def add_edge(self, dst: "BasicBlock", kind: str, label: str = "", condition: str = "") -> CFGEdge:
        """Add a typed successor edge and keep the predecessor list in sync."""
        edge = CFGEdge(src=self.id, dst=dst.id, kind=kind, label=label, condition=condition)
        self.successors.append(edge)
        dst.predecessors.append(self.id)
        return edge

    def to_json(self, statements_json: bool = True, max_depth: int = 2) -> dict:
        return {
            "id": self.id,
            "function": self.function,
            "kind": self.kind,
            "statement_ids": list(self.statement_ids),
            "entry_definition_ids": list(self.entry_definition_ids),
            "statements": [s.to_json(max_depth=max_depth) for s in self.statements]
            if statements_json
            else [],
            "successors": [e.to_json() for e in self.successors],
            "predecessors": list(self.predecessors),
            "span": list(self.span),
        }


@dataclass
class LoopInfo:
    header: int
    body_entry: int
    break_target: int
    continue_target: int
    kind: str

    def to_json(self) -> dict:
        return {
            "header": self.header,
            "body_entry": self.body_entry,
            "break_target": self.break_target,
            "continue_target": self.continue_target,
            "kind": self.kind,
        }


@dataclass
class CFG:
    """Control-flow graph of one function."""

    function: str
    blocks: Dict[int, BasicBlock] = field(default_factory=dict)
    entry: int = -1
    exit: int = -1
    definitions: List[Definition] = field(default_factory=list)
    loops: List[LoopInfo] = field(default_factory=list)
    reachable: Set[int] = field(default_factory=set)
    unreachable: Set[int] = field(default_factory=set)
    span: Tuple[int, int] = (0, 0)

    # -- queries -------------------------------------------------------
    def block(self, block_id: int) -> BasicBlock:
        return self.blocks[block_id]

    def sorted_blocks(self) -> List[BasicBlock]:
        return [self.blocks[i] for i in sorted(self.blocks)]

    def edges(self) -> List[CFGEdge]:
        out: List[CFGEdge] = []
        for block in self.sorted_blocks():
            out.extend(block.successors)
        return out

    def definitions_of(self, symbol_id: int) -> List[Definition]:
        return [d for d in self.definitions if d.symbol_id == symbol_id]

    def definition_by_id(self, definition_id: int) -> Optional[Definition]:
        for definition in self.definitions:
            if definition.id == definition_id:
                return definition
        return None

    def compute_reachability(self) -> None:
        """Mark blocks reachable from the entry block."""
        seen: Set[int] = set()
        stack = [self.entry] if self.entry in self.blocks else []
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            for edge in self.blocks[current].successors:
                if edge.dst not in seen:
                    stack.append(edge.dst)
        self.reachable = seen
        self.unreachable = set(self.blocks) - seen

    def stats(self) -> dict:
        return {
            "function": self.function,
            "blocks": len(self.blocks),
            "edges": len(self.edges()),
            "definitions": len(self.definitions),
            "reachable_blocks": len(self.reachable),
            "unreachable_blocks": len(self.unreachable),
            "loops": len(self.loops),
        }

    def to_json(self, statements_json: bool = True, max_depth: int = 2) -> dict:
        return {
            "function": self.function,
            "entry": self.entry,
            "exit": self.exit,
            "blocks": [b.to_json(statements_json, max_depth) for b in self.sorted_blocks()],
            "edges": [e.to_json() for e in self.edges()],
            "definitions": [d.to_json() for d in self.definitions],
            "loops": [loop.to_json() for loop in self.loops],
            "reachable": sorted(self.reachable),
            "unreachable": sorted(self.unreachable),
        }


# ----------------------------------------------------------------------
# Statement ids
# ----------------------------------------------------------------------
def assign_statement_ids(tree: SourceUnit) -> Dict[int, Node]:
    """Give every executable statement a stable ``sid``; return ``sid -> node``.

    ``Block`` nodes are not executable statements in this model (their contents
    are scheduled individually), so they receive no id.
    """
    statements = [n for n in tree.walk() if is_statement(n) and not isinstance(n, Block)]
    statements.sort(key=lambda n: (n.span[0], -n.span[1]))
    mapping: Dict[int, Node] = {}
    for index, node in enumerate(statements):
        node.sid = index
        mapping[index] = node
    return mapping


# ----------------------------------------------------------------------
# Builder
# ----------------------------------------------------------------------
@dataclass
class LoopFrame:
    break_target: int
    continue_target: int
    kind: str


class CFGBuilder:
    """Builds one :class:`CFG` per function with globally unique block ids."""

    def __init__(self, statements: Optional[Dict[int, Node]] = None) -> None:
        self.statements = statements if statements is not None else {}
        self._next_block = 0
        self._next_definition = 0
        self._globals: List[VarDeclarator] = []
        self.cfgs: Dict[str, CFG] = {}

    # -- low level -----------------------------------------------------
    def new_block(self, cfg: CFG, kind: str = "normal") -> BasicBlock:
        block = BasicBlock(id=self._next_block, function=cfg.function, kind=kind)
        self._next_block += 1
        cfg.blocks[block.id] = block
        return block

    def add_definition(
        self, cfg: CFG, symbol_id: int, symbol_name: str, kind: str, sid: int, node: Node, op: str = ""
    ) -> Definition:
        definition = Definition(
            id=self._next_definition,
            symbol_id=symbol_id,
            symbol_name=symbol_name,
            kind=kind,
            sid=sid,
            offset=node.span[0],
            line=node.line,
            col=node.col,
            function=cfg.function,
            op=op,
        )
        self._next_definition += 1
        cfg.definitions.append(definition)
        return definition

    # -- public --------------------------------------------------------
    def build_program(self, tree: SourceUnit) -> Dict[str, CFG]:
        # File-scope variables are in force before any function runs, so they
        # become entry definitions of every function.
        self._globals = [
            declarator
            for decl in tree.decls
            if isinstance(decl, VarDecl)
            for declarator in decl.declarators
            if declarator.symbol_id >= 0
        ]
        for decl in tree.decls:
            if isinstance(decl, FunctionDecl):
                self.build_function(decl)
        return self.cfgs

    def build_function(self, function: FunctionDecl) -> CFG:
        cfg = CFG(function=function.name, span=function.span)
        entry = self.new_block(cfg, "entry")
        exit_block = self.new_block(cfg, "exit")
        cfg.entry = entry.id
        cfg.exit = exit_block.id

        for declarator in getattr(self, "_globals", []):
            kind = GLOBAL_INIT if declarator.init is not None else GLOBAL_UNINIT
            definition = self.add_definition(
                cfg, declarator.symbol_id, declarator.name, kind, PROGRAM_START_SID, declarator
            )
            entry.entry_definition_ids.append(definition.id)
        for param in function.params:
            if param.symbol_id < 0:
                continue
            definition = self.add_definition(
                cfg, param.symbol_id, param.name, PARAMETER, PROGRAM_START_SID, param
            )
            entry.entry_definition_ids.append(definition.id)

        current = entry
        if function.body is not None:
            current = self.build_block(cfg, function.body, current, [])
        if current is not None:
            current.add_edge(exit_block, "exit", label="end of function")
        cfg.compute_reachability()
        self.cfgs[function.name] = cfg
        return cfg

    # -- statements ----------------------------------------------------
    def build_block(
        self, cfg: CFG, block: Block, current: Optional[BasicBlock], loops: List[LoopFrame]
    ) -> Optional[BasicBlock]:
        for statement in block.statements:
            current = self.build_statement(cfg, statement, current, loops)
        return current

    def build_statement(
        self, cfg: CFG, statement: Optional[Node], current: Optional[BasicBlock], loops: List[LoopFrame]
    ) -> Optional[BasicBlock]:
        if statement is None:
            return current
        if current is None:
            # The statement follows a terminator (return/break/continue) and is
            # therefore unreachable.  It is kept in its own block so that the
            # reachability analysis can report it instead of dropping it.
            current = self.new_block(cfg, "unreachable")
        if isinstance(statement, Block):
            return self.build_block(cfg, statement, current, loops)
        if isinstance(statement, IfStmt):
            return self._build_if(cfg, statement, current, loops)
        if isinstance(statement, WhileStmt):
            return self._build_while(cfg, statement, current, loops)
        if isinstance(statement, ForStmt):
            return self._build_for(cfg, statement, current, loops)
        if isinstance(statement, ReturnStmt):
            self._append(cfg, current, statement)
            self._collect_definitions(cfg, statement)
            current.add_edge(cfg.block(cfg.exit), "return", label="return")
            return None
        if isinstance(statement, BreakStmt):
            self._append(cfg, current, statement)
            if loops:
                current.add_edge(cfg.block(loops[-1].break_target), "break", label="break")
            return None
        if isinstance(statement, ContinueStmt):
            self._append(cfg, current, statement)
            if loops:
                current.add_edge(cfg.block(loops[-1].continue_target), "continue", label="continue")
            return None
        # Linear statements -------------------------------------------------
        self._append(cfg, current, statement)
        self._collect_definitions(cfg, statement)
        return current

    def _append(self, cfg: CFG, block: BasicBlock, statement: Node) -> None:
        block.statements.append(statement)
        block.statement_ids.append(statement.sid)
        if block.span == (0, 0):
            block.span = statement.span
        else:
            block.span = (min(block.span[0], statement.span[0]), max(block.span[1], statement.span[1]))

    # -- definitions ---------------------------------------------------
    def _collect_definitions(self, cfg: CFG, statement: Node) -> None:
        """Record value-writing events contained in one linear statement."""
        if isinstance(statement, VarDecl):
            for declarator in statement.declarators:
                if declarator.symbol_id < 0:
                    continue
                kind = DECL_INIT if declarator.init is not None else DECL_UNINIT
                self.add_definition(
                    cfg, declarator.symbol_id, declarator.name, kind, statement.sid, declarator
                )
            return
        if isinstance(statement, ExprStmt):
            if statement.expr is not None:
                self._collect_expr_definitions(cfg, statement.expr, statement)
            return
        if isinstance(statement, ReturnStmt):
            if statement.value is not None:
                self._collect_expr_definitions(cfg, statement.value, statement)
            return
        if isinstance(statement, (IfStmt, WhileStmt, ForStmt)):
            condition = getattr(statement, "cond", None)
            if condition is not None:
                self._collect_expr_definitions(cfg, condition, statement)
            return
        if isinstance(statement, EmptyStmt):
            return
        self._collect_expr_definitions(cfg, statement, statement)

    def _collect_expr_definitions(self, cfg: CFG, expr: Node, statement: Node) -> None:
        for node in expr.walk():
            if isinstance(node, Assign):
                target = node.target
                symbol = self._target_symbol(target)
                if symbol is not None:
                    self.add_definition(
                        cfg, symbol[0], symbol[1], ASSIGN, statement.sid,
                        target if target is not None else node,
                    )
            elif isinstance(node, UnaryOp) and node.op in ("++", "--"):
                symbol = self._target_symbol(node.operand)
                if symbol is not None:
                    self.add_definition(
                        cfg, symbol[0], symbol[1], INCDEC, statement.sid,
                        node.operand if node.operand is not None else node, op=node.op,
                    )

    def _target_symbol(self, node: Optional[Node]) -> Optional[Tuple[int, str]]:
        if isinstance(node, Ident) and node.symbol_id >= 0:
            return (node.symbol_id, node.name)
        if isinstance(node, Index) and isinstance(node.base, Ident) and node.base.symbol_id >= 0:
            return (node.base.symbol_id, f"{node.base.name}[]")
        return None

    def _loop_header_block(self, cfg: CFG, current: BasicBlock) -> BasicBlock:
        """Return the block that should hold a loop header.

        A loop header is the target of a back edge, so it must start a basic
        block: if the current block already contains statements, the header is
        opened as a new block and the current block falls through into it.  A
        block is then executed as a unit on any single pass through the loop,
        which is what makes the per-statement data-flow states exact.
        """
        if not current.statement_ids:
            return current
        header = self.new_block(cfg)
        current.add_edge(header, "sequential")
        return header

    # -- control structures --------------------------------------------
    def _build_if(
        self, cfg: CFG, statement: IfStmt, current: BasicBlock, loops: List[LoopFrame]
    ) -> BasicBlock:
        self._append(cfg, current, statement)
        self._collect_definitions(cfg, statement)
        merge = self.new_block(cfg)
        then_block = self.new_block(cfg)
        condition_text = expression_text(statement.cond)
        current.add_edge(then_block, "true", label="true", condition=condition_text)
        then_end = self.build_statement(cfg, statement.then_branch, then_block, loops)
        if statement.else_branch is not None:
            else_block = self.new_block(cfg)
            current.add_edge(
                else_block, "false", label="false", condition=f"not ({condition_text})"
            )
            else_end = self.build_statement(cfg, statement.else_branch, else_block, loops)
            if then_end is not None:
                then_end.add_edge(merge, "sequential")
            if else_end is not None:
                else_end.add_edge(merge, "sequential")
        else:
            current.add_edge(
                merge, "false", label="false", condition=f"not ({condition_text})"
            )
            if then_end is not None:
                then_end.add_edge(merge, "sequential")
        return merge

    def _build_while(
        self, cfg: CFG, statement: WhileStmt, current: BasicBlock, loops: List[LoopFrame]
    ) -> BasicBlock:
        header = self._loop_header_block(cfg, current)
        self._append(cfg, header, statement)
        self._collect_definitions(cfg, statement)
        header.kind = "loop-header"
        after = self.new_block(cfg)
        body = self.new_block(cfg)
        condition_text = expression_text(statement.cond)
        header.add_edge(body, "true", label="true", condition=condition_text)
        header.add_edge(after, "false", label="false", condition=f"not ({condition_text})")
        loops.append(LoopFrame(break_target=after.id, continue_target=header.id, kind="while"))
        body_end = self.build_statement(cfg, statement.body, body, loops)
        loops.pop()
        if body_end is not None:
            body_end.add_edge(header, "loop-back", label="loop back edge")
        cfg.loops.append(
            LoopInfo(
                header=header.id,
                body_entry=body.id,
                break_target=after.id,
                continue_target=header.id,
                kind="while",
            )
        )
        return after

    def _build_for(
        self, cfg: CFG, statement: ForStmt, current: BasicBlock, loops: List[LoopFrame]
    ) -> BasicBlock:
        # The initialiser executes before the loop header, so it is part of
        # the incoming block and appears before the ``for`` statement itself.
        if statement.init is not None:
            self._append(cfg, current, statement.init)
            self._collect_definitions(cfg, statement.init)
        # The `for` statement is an unconditional branch to the header, and the
        # header is a back-edge target: it starts a basic block of its own.
        header = self.new_block(cfg, "loop-header")
        after = self.new_block(cfg)
        body = self.new_block(cfg)
        update = self.new_block(cfg)
        condition_text = expression_text(statement.cond)
        current.add_edge(header, "sequential")
        self._append(cfg, header, statement)
        self._collect_definitions(cfg, statement)
        header.add_edge(body, "true", label="true", condition=condition_text or "no condition (always true)")
        if statement.cond is not None:
            header.add_edge(after, "false", label="false", condition=f"not ({condition_text})")
        loops.append(LoopFrame(break_target=after.id, continue_target=update.id, kind="for"))
        body_end = self.build_statement(cfg, statement.body, body, loops)
        loops.pop()
        if body_end is not None:
            body_end.add_edge(update, "sequential")
        if statement.update is not None:
            self._append(cfg, update, statement.update)
            self._collect_definitions(cfg, statement.update)
        update.add_edge(header, "loop-back", label="loop back edge")
        cfg.loops.append(
            LoopInfo(
                header=header.id,
                body_entry=body.id,
                break_target=after.id,
                continue_target=update.id,
                kind="for",
            )
        )
        return after


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def expression_text(node: Optional[Node]) -> str:
    """Deterministic, compact rendering of an expression (edge labels, UI)."""
    if node is None:
        return ""
    if isinstance(node, Ident):
        return node.name
    if isinstance(node, UnaryOp):
        return f"{node.op}{expression_text(node.operand)}" if node.prefix else f"{expression_text(node.operand)}{node.op}"
    if isinstance(node, BinaryOp):
        return f"{expression_text(node.left)} {node.op} {expression_text(node.right)}"
    if isinstance(node, Assign):
        return f"{expression_text(node.target)} {node.op} {expression_text(node.value)}"
    if isinstance(node, Call):
        args = ", ".join(expression_text(a) for a in node.args)
        return f"{node.name}({args})"
    if isinstance(node, Index):
        return f"{expression_text(node.base)}[{expression_text(node.index)}]"
    if isinstance(node, StringLit):
        return f'"{node.value}"'
    if isinstance(node, CharLit):
        return f"'{node.value}'"
    if isinstance(node, BoolLit):
        return "true" if node.value else "false"
    if isinstance(node, (IntLit, FloatLit)):
        return str(node.value)
    return node.kind


def build_cfgs(tree: SourceUnit, statements: Optional[Dict[int, Node]] = None) -> Dict[str, CFG]:
    """Build a CFG for every function declared in ``tree``."""
    return CFGBuilder(statements).build_program(tree)
