"""Semantic analysis: declaration collection, scope resolution, type checking.

Two passes are performed:

1. **Declaration pass.**  Every top-level declaration is processed first:
   functions receive their signature (and therefore a symbol that can be
   referenced before the definition), globals are declared in the global
   scope.  This is what allows forward references between functions without
   requiring prototypes.
2. **Body pass.**  Function bodies are analysed in source order with an
   explicit scope stack.  Identifiers are resolved to symbol ids, every use is
   recorded on the symbol (read/write with its source offset), and type rules
   are applied to declarations, assignments, conditions, calls and returns.

The analyser distinguishes three situations that static analysis must never
confuse:

* a *valid* construct whose value is known (``type_of`` returns a type),
* a *valid but unknown* value (``"unknown"``: unresolved call, partially
  modelled construct), and
* an *unsupported* construct, which always produces an ``unsupported=True``
  diagnostic and marks the enclosing symbol as ``partial``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..frontend.ast_nodes import (
    Assign,
    BinaryOp,
    Block,
    BoolLit,
    BreakStmt,
    Call,
    CharLit,
    ContinueStmt,
    EmptyStmt,
    ExprStmt,
    FloatLit,
    ForStmt,
    FunctionDecl,
    Ident,
    IfStmt,
    Index,
    IntLit,
    Node,
    Param,
    ReturnStmt,
    SourceUnit,
    StringLit,
    UnaryOp,
    VarDecl,
    VarDeclarator,
    WhileStmt,
    is_statement,
)
from ..frontend.lexer import Diagnostic
from ..frontend.source import LineIndex
from . import externals
from .symbol_table import (
    ARRAY,
    EXTERNAL_FUNCTION,
    FUNCTION,
    PARAMETER,
    SCOPE_BLOCK,
    SCOPE_FUNCTION,
    SCOPE_GLOBAL,
    VARIABLE,
    Symbol,
    SymbolTable,
)

UNKNOWN_TYPE = "unknown"
VOID_TYPE = "void"

#: Explicitly unsupported type rules -- documented in docs/LIMITATIONS.md.
ASSIGN_COMPAT: Dict[str, set] = {
    "int": {"int", "float"},
    "float": {"int", "float"},
    "char": {"char"},
    "string": {"string"},
    "bool": {"bool"},
}

ARITHMETIC_TYPES = ("int", "float", "string")

#: Conversion warnings: (target type, source type, code, message)
NARROWING = {
    ("int", "float"): (
        "SEM101",
        "implicit conversion from float to int may lose information",
    ),
    ("char", "int"): ("SEM103", "implicit conversion from int to char may truncate"),
}

CONDITION_ALLOWED = {"bool": None, "int": "SEM102", "char": "SEM102"}


@dataclass
class CallSite:
    """A resolved call, used by the call graph and by the taint engine."""

    name: str
    kind: str  # "user" | "external" | "unknown"
    node: Call
    args: List[Node] = field(default_factory=list)
    arg_types: List[str] = field(default_factory=list)
    span: Tuple[int, int] = (0, 0)
    line: int = 0
    col: int = 0
    sid: int = -1
    function: Optional[str] = None
    external: Optional[externals.ExternalFunction] = None

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "arg_count": len(self.args),
            "arg_types": list(self.arg_types),
            "line": self.line,
            "col": self.col,
            "sid": self.sid,
            "function": self.function,
            "signature": self.external.signature() if self.external else None,
            "category": self.external.category if self.external else None,
        }


@dataclass
class SemanticResult:
    tree: SourceUnit
    symbols: SymbolTable
    diagnostics: List[Diagnostic] = field(default_factory=list)
    calls: List[CallSite] = field(default_factory=list)
    functions: Dict[str, FunctionDecl] = field(default_factory=dict)
    problems_by_code: Dict[str, int] = field(default_factory=dict)
    analysis_notes: List[str] = field(default_factory=list)
    #: Offsets of constructs that could not be modelled.
    unsupported_offsets: List[int] = field(default_factory=list)
    unknowns: List[dict] = field(default_factory=list)

    @property
    def errors(self) -> List[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    def symbol_of(self, node: Optional[Node]) -> Optional[Symbol]:
        if isinstance(node, Ident) and node.symbol_id >= 0:
            return self.symbols.get(node.symbol_id)
        return None

    def next_symbol_id(self) -> int:
        return max(self.symbols.symbols, default=0) + 1


class SemanticAnalyzer:
    def __init__(self, tree: SourceUnit, index: LineIndex, filename: str = "<source>") -> None:
        self.tree = tree
        self.index = index
        self.filename = filename
        self.table = SymbolTable()
        self.diagnostics: List[Diagnostic] = []
        self.calls: List[CallSite] = []
        self.functions: Dict[str, FunctionDecl] = {}
        self.unsupported_offsets: List[int] = []
        self.unknowns: List[dict] = []
        self._unresolved_calls: Dict[str, str] = {}
        self.global_scope = self.table.root
        self.current_function: Optional[FunctionDecl] = None
        self.current_function_scope = self.global_scope
        self.loop_depth = 0

    # ------------------------------------------------------------------
    # diagnostics
    # ------------------------------------------------------------------
    def diagnostic(
        self,
        severity: str,
        code: str,
        message: str,
        node: Optional[Node] = None,
        offset: int = 0,
        detail: str = "",
        unsupported: bool = False,
    ) -> None:
        if node is not None:
            offset = node.span[0]
            line, col = node.line, node.col
            end = node.span[1]
        else:
            line, col = self.index.position(offset)
            end = offset
        self.diagnostics.append(
            Diagnostic(
                severity=severity,
                code=code,
                message=message,
                line=line,
                col=col,
                offset=offset,
                end_offset=end,
                phase="semantic",
                detail=detail,
                unsupported=unsupported,
            )
        )
        if unsupported:
            self.unsupported_offsets.append(offset)

    def note_unknown(self, kind: str, node: Node, detail: str) -> None:
        """Record a construct whose value cannot be established."""
        self.unknowns.append(
            {
                "kind": kind,
                "line": node.line,
                "col": node.col,
                "offset": node.span[0],
                "detail": detail,
            }
        )

    # ------------------------------------------------------------------
    # drivers
    # ------------------------------------------------------------------
    def run(self) -> SemanticResult:
        self._declaration_pass()
        self._body_pass()
        if "main" not in self.functions:
            self.diagnostics.append(
                Diagnostic(
                    severity="info",
                    code="SEM020",
                    message="no 'main' function found; analysis covers "
                    f"{len(self.functions)} declared function(s)",
                    line=1,
                    col=1,
                    offset=0,
                    end_offset=0,
                    phase="semantic",
                )
            )
        counts: Dict[str, int] = {}
        for diag in self.diagnostics:
            counts[diag.code] = counts.get(diag.code, 0) + 1
        notes = [
            "Identifiers are resolved to symbol ids; two variables with the same "
            "name in different scopes are distinct symbols.",
            "Calls to functions that are neither defined in this file nor part of the "
            "external model are reported as unknown and modelled conservatively.",
        ]
        if self.unsupported_offsets:
            notes.append(
                f"{len(self.unsupported_offsets)} construct(s) in this file are outside the "
                "supported subset; they are marked as unanalysed rather than assumed safe."
            )
        return SemanticResult(
            tree=self.tree,
            symbols=self.table,
            diagnostics=self.diagnostics,
            calls=self.calls,
            functions=self.functions,
            problems_by_code=counts,
            analysis_notes=notes,
            unsupported_offsets=sorted(set(self.unsupported_offsets)),
            unknowns=self.unknowns,
        )

    # ------------------------------------------------------------------
    # pass 1
    # ------------------------------------------------------------------
    def _declaration_pass(self) -> None:
        for decl in self.tree.decls:
            if isinstance(decl, FunctionDecl):
                self._declare_function(decl)
            elif isinstance(decl, VarDecl):
                self._declare_vars(decl, self.global_scope, is_global=True)

    def _declare_function(self, decl: FunctionDecl) -> None:
        existing = self.table.lookup_local(self.global_scope, decl.name)
        if existing is not None:
            self.diagnostic(
                "error", "SEM003", f"redefinition of '{decl.name}'",
                detail=f"'{decl.name}' was previously declared at line {existing.decl_line}",
                node=decl,
            )
            return
        symbol = self.table.declare(
            self.global_scope,
            decl.name,
            FUNCTION,
            decl.return_type,
            offset=decl.span[0],
            line=decl.line,
            col=decl.col,
            is_global=True,
        )
        symbol.function = decl.name
        decl.symbol_id = symbol.id
        self.functions[decl.name] = decl
        if decl.return_type == VOID_TYPE and len(decl.params) == 0:
            pass  # void f(void) is the normal shape

    def _declare_vars(self, decl: VarDecl, scope_id: int, is_global: bool = False) -> List[Symbol]:
        created: List[Symbol] = []
        if decl.type_name == VOID_TYPE:
            self.diagnostic(
                "error", "SEM006", "variables cannot have type 'void'", node=decl
            )
        for declarator in decl.declarators:
            existing = self.table.lookup_local(scope_id, declarator.name)
            if existing is not None:
                self.diagnostic(
                    "error", "SEM002", f"duplicate declaration of '{declarator.name}' in the same scope",
                    detail=f"first declared at line {existing.decl_line}, column {existing.decl_col}",
                    node=declarator,
                )
                declarator.symbol_id = existing.id
                continue
            hidden = self.table.shadowed_symbol(scope_id, declarator.name)
            if hidden is not None and scope_id != self.global_scope:
                self.diagnostic(
                    "warning", "SEM018",
                    f"declaration of '{declarator.name}' shadows the {hidden.kind.replace('_', ' ')} "
                    f"declared at line {hidden.decl_line}",
                    detail="the name resolves to the inner declaration inside this scope",
                    node=declarator,
                )
            symbol = self.table.declare(
                scope_id,
                declarator.name,
                ARRAY if declarator.array_size is not None else VARIABLE,
                decl.type_name,
                offset=declarator.span[0],
                line=declarator.line,
                col=declarator.col,
                is_array=declarator.array_size is not None,
                array_size=declarator.array_size,
                is_global=is_global,
            )
            if is_global:
                symbol.function = None
            else:
                symbol.function = self.current_function.name if self.current_function else None
            symbol.add_reference(
                declarator.span[0], declarator.line, declarator.col, "declaration"
            )
            declarator.symbol_id = symbol.id
            created.append(symbol)
        return created

    # ------------------------------------------------------------------
    # pass 2
    # ------------------------------------------------------------------
    def _body_pass(self) -> None:
        for decl in self.tree.decls:
            if isinstance(decl, FunctionDecl):
                self._analyse_function(decl)
            elif isinstance(decl, VarDecl):
                self._analyse_global_var(decl)

    def _analyse_global_var(self, decl: VarDecl) -> None:
        for declarator in decl.declarators:
            if declarator.init is not None:
                value_type = self.type_of(declarator.init)
                symbol = self.table.get(declarator.symbol_id)
                if symbol is not None:
                    self._check_assignable(decl.type_name, value_type, declarator, symbol)
                    symbol.add_reference(declarator.span[0], declarator.line, declarator.col, "write")

    def _analyse_function(self, decl: FunctionDecl) -> None:
        if decl.symbol_id < 0:
            return  # duplicate definition already reported
        self.current_function = decl
        func_scope = self.table.new_scope(
            SCOPE_FUNCTION, parent=self.global_scope, owner_function=decl.name, span=decl.span
        )
        self.current_function_scope = func_scope
        # parameters
        seen: Dict[str, Param] = {}
        for index, param in enumerate(decl.params):
            if param.name in seen:
                self.diagnostic(
                    "error", "SEM015", f"duplicate parameter name '{param.name}'", node=param
                )
                continue
            seen[param.name] = param
            if param.type_name == VOID_TYPE:
                self.diagnostic(
                    "error", "SEM007", "parameters cannot have type 'void'", node=param
                )
            symbol = self.table.declare(
                func_scope,
                param.name,
                PARAMETER,
                param.type_name,
                offset=param.span[0],
                line=param.line,
                col=param.col,
                param_index=index,
            )
            symbol.function = decl.name
            param.symbol_id = symbol.id
            symbol.add_reference(param.span[0], param.line, param.col, "declaration")
        if decl.body is not None:
            self.visit_block(decl.body, declare_scope=False)
        self.loop_depth = 0
        self.current_function = None
        self.current_function_scope = self.global_scope

    # ------------------------------------------------------------------
    # statements
    # ------------------------------------------------------------------
    def visit_statement(self, node: Node, scope_id: int) -> None:
        if isinstance(node, Block):
            self.visit_block(node, declare_scope=True, parent_scope=scope_id)
        elif isinstance(node, VarDecl):
            symbols = self._declare_vars(node, scope_id)
            for declarator, symbol in zip(node.declarators, symbols):
                if declarator.init is not None:
                    self.visit_expr(declarator.init, scope_id)
                    value_type = self.type_of(declarator.init)
                    self._check_assignable(node.type_name, value_type, declarator, symbol)
                    symbol.add_reference(
                        declarator.span[0], declarator.line, declarator.col, "write"
                    )
        elif isinstance(node, IfStmt):
            self.visit_condition(node.cond, scope_id)
            if node.then_branch is not None:
                self.visit_statement(node.then_branch, scope_id)
            if node.else_branch is not None:
                self.visit_statement(node.else_branch, scope_id)
        elif isinstance(node, WhileStmt):
            self.visit_condition(node.cond, scope_id)
            self.loop_depth += 1
            if node.body is not None:
                self.visit_statement(node.body, scope_id)
            self.loop_depth -= 1
        elif isinstance(node, ForStmt):
            inner_scope = scope_id
            if node.init is not None:
                if isinstance(node.init, VarDecl):
                    # A declaration in the for-header is scoped to the loop.
                    inner_scope = self.table.new_scope(
                        SCOPE_BLOCK, parent=scope_id,
                        owner_function=self.current_function.name if self.current_function else None,
                        span=node.span,
                    )
                    self.visit_statement(node.init, inner_scope)
                else:
                    self.visit_statement(node.init, scope_id)
            if node.cond is not None:
                self.visit_condition(node.cond, inner_scope)
            self.loop_depth += 1
            if node.body is not None:
                self.visit_statement(node.body, inner_scope)
            self.loop_depth -= 1
            if node.update is not None:
                self.visit_statement(node.update, inner_scope)
        elif isinstance(node, ReturnStmt):
            if node.value is not None:
                self.visit_expr(node.value, scope_id)
                value_type = self.type_of(node.value)
                if self.current_function is not None and self.current_function.return_type == VOID_TYPE:
                    self.diagnostic(
                        "error", "SEM016",
                        f"'return' with a value in void function '{self.current_function.name}'",
                        node=node,
                    )
                elif self.current_function is not None:
                    self._check_assignable(
                        self.current_function.return_type, value_type, node, None
                    )
            else:
                if self.current_function is not None and self.current_function.return_type != VOID_TYPE:
                    self.diagnostic(
                        "warning", "SEM016",
                        f"'return' without a value in function '{self.current_function.name}' "
                        f"declared to return {self.current_function.return_type}",
                        node=node,
                    )
        elif isinstance(node, (BreakStmt, ContinueStmt)):
            if self.loop_depth == 0:
                keyword = "break" if isinstance(node, BreakStmt) else "continue"
                self.diagnostic(
                    "error", "SEM012", f"'{keyword}' outside of a loop", node=node
                )
        elif isinstance(node, ExprStmt):
            if node.expr is not None:
                self.visit_expr(node.expr, scope_id)
        elif isinstance(node, EmptyStmt):
            pass
        else:  # pragma: no cover - defensive
            self.diagnostic(
                "warning", "SEM900", f"unsupported statement kind {node.kind}",
                node=node, unsupported=True,
            )

    def visit_block(self, block: Block, declare_scope: bool = True, parent_scope: Optional[int] = None) -> None:
        scope_id = parent_scope if parent_scope is not None else self.current_function_scope
        if declare_scope:
            scope_id = self.table.new_scope(
                SCOPE_BLOCK,
                parent=parent_scope if parent_scope is not None else self.current_function_scope,
                owner_function=self.current_function.name if self.current_function else None,
                span=block.span,
            )
        for statement in block.statements:
            self.visit_statement(statement, scope_id)

    def visit_condition(self, cond: Optional[Node], scope_id: int) -> None:
        if cond is None:
            return
        self.visit_expr(cond, scope_id)
        cond_type = self.type_of(cond)
        if cond_type in CONDITION_ALLOWED:
            code = CONDITION_ALLOWED[cond_type]
            if code is not None:
                self.diagnostic(
                    "warning", "SEM102",
                    f"condition has type {cond_type}; an implicit comparison with zero is assumed",
                    node=cond,
                )
        elif cond_type == UNKNOWN_TYPE:
            self.note_unknown("condition", cond, "the type of this condition could not be determined")
        else:
            self.diagnostic(
                "error", "SEM005",
                f"condition must have type bool, found {cond_type}",
                node=cond,
                detail="comparisons such as 'x != 0' produce a bool; strings and floats are not "
                "implicitly converted in this subset",
            )

    # ------------------------------------------------------------------
    # expressions
    # ------------------------------------------------------------------
    def visit_expr(self, expr: Optional[Node], scope_id: int, write: bool = False) -> None:
        if expr is None:
            return
        if isinstance(expr, Ident):
            self._resolve_ident(expr, scope_id, write)
        elif isinstance(expr, BinaryOp):
            self.visit_expr(expr.left, scope_id)
            self.visit_expr(expr.right, scope_id)
        elif isinstance(expr, UnaryOp):
            if expr.op in ("++", "--"):
                self.visit_expr(expr.operand, scope_id, write=True)
            else:
                self.visit_expr(expr.operand, scope_id)
        elif isinstance(expr, Assign):
            if expr.target is None or not self._is_assignable(expr.target):
                self.diagnostic(
                    "error", "SEM004",
                    "left-hand side of assignment is not a variable or array element",
                    node=expr.target if expr.target is not None else expr,
                )
                if expr.target is not None:
                    self.visit_expr(expr.target, scope_id)
            else:
                self.visit_expr(expr.target, scope_id, write=True)
            self.visit_expr(expr.value, scope_id)
            if expr.target is not None and expr.value is not None:
                target_type = self.type_of(expr.target)
                value_type = self.type_of(expr.value)
                if expr.op == "=":
                    # A plain assignment must be type compatible in exactly the
                    # same way a declaration initialiser is.
                    symbol = self.table.get(expr.target.symbol_id) if isinstance(expr.target, Ident) else None
                    self._check_assignable(target_type, value_type, expr, symbol)
                else:
                    if target_type == "string" or value_type == "string":
                        if expr.op != "+=":
                            self.diagnostic(
                                "error", "SEM005",
                                f"operator '{expr.op}' is not defined for type {target_type}",
                                node=expr,
                            )
                    else:
                        # `a op= b` is equivalent to `a = a op b`; the compound
                        # operator must be defined for both operand types.
                        self._check_assignable(target_type, target_type, expr, None)
        elif isinstance(expr, Call):
            self._resolve_call(expr, scope_id)
        elif isinstance(expr, Index):
            if expr.base is not None:
                self.visit_expr(expr.base, scope_id)
                base_symbol = expr.base.symbol_id if isinstance(expr.base, Ident) else -1
                symbol = self.table.get(base_symbol)
                if symbol is not None and not symbol.is_array:
                    self.diagnostic(
                        "error", "SEM013",
                        f"'{symbol.name}' is not an array and cannot be indexed",
                        node=expr,
                    )
            if expr.index is not None:
                self.visit_expr(expr.index, scope_id)
                index_type = self.type_of(expr.index)
                if index_type not in ("int", UNKNOWN_TYPE):
                    self.diagnostic(
                        "error", "SEM005",
                        f"array index must have type int, found {index_type}",
                        node=expr.index,
                    )
        elif isinstance(expr, (IntLit, FloatLit, CharLit, StringLit, BoolLit)):
            pass
        else:  # pragma: no cover - defensive
            self.diagnostic("warning", "SEM901", f"unsupported expression kind {expr.kind}", node=expr, unsupported=True)

    def _is_assignable(self, target: Node) -> bool:
        return isinstance(target, Ident) or isinstance(target, Index)

    def _resolve_ident(self, ident: Ident, scope_id: int, write: bool) -> None:
        symbol = self.table.lookup(scope_id, ident.name)
        if symbol is None:
            self.diagnostic(
                "error", "SEM001", f"use of undeclared identifier '{ident.name}'",
                node=ident,
                detail="the name is not declared in this scope or any enclosing scope",
            )
            ident.symbol_id = -1
            return
        if symbol.kind == FUNCTION:
            self.diagnostic(
                "error", "SEM014",
                f"function '{ident.name}' used where a value is expected",
                node=ident,
                detail="take the result of a call expression instead",
            )
        if symbol.is_array and not write:
            self.note_unknown(
                "array-value",
                ident,
                f"array '{ident.name}' is referenced as a whole; element-wise tracking is not "
                "modelled, so its value is treated as unknown",
            )
        ident.symbol_id = symbol.id
        symbol.add_reference(
            ident.span[0], ident.line, ident.col, "write" if write else "read"
        )

    def _resolve_call(self, call: Call, scope_id: int) -> None:
        if call.callee is None:
            self.diagnostic(
                "error", "SEM017",
                "call of a non-identifier expression is not supported",
                node=call,
                detail="indirect calls through function values or expressions are outside the "
                "supported subset and are not analysed",
                unsupported=True,
            )
            for arg in call.args:
                self.visit_expr(arg, scope_id)
            return
        name = call.name
        for arg in call.args:
            self.visit_expr(arg, scope_id)
        arg_types = [self.type_of(a) for a in call.args]

        # A call whose callee name resolves to a variable or parameter is an
        # indirect call through a function value.  That is outside the analysed
        # subset: saying so is more honest than reporting an unknown external.
        shadowing = self.table.lookup(scope_id, name)
        if shadowing is not None and shadowing.kind in (VARIABLE, PARAMETER, ARRAY):
            call.resolution = "unsupported-indirect"
            self.diagnostic(
                "error", "SEM017",
                f"call of '{name}', which is a {shadowing.kind}, not a function",
                node=call,
                detail=(
                    "indirect calls through function values or expressions are outside the "
                    "supported subset; the call is reported and not analysed"
                ),
                unsupported=True,
            )
            return

        user_function = self.functions.get(name)
        if user_function is not None:
            symbol = self.table.lookup(self.global_scope, name)
            call.symbol_id = symbol.id if symbol else -1
            call.resolution = "function"
            self._check_call_args(name, [p.type_name for p in user_function.params], arg_types, call)
            self.calls.append(
                CallSite(
                    name=name,
                    kind="user",
                    node=call,
                    args=list(call.args),
                    arg_types=arg_types,
                    span=call.span,
                    line=call.line,
                    col=call.col,
                    function=self.current_function.name if self.current_function else None,
                )
            )
            return

        external = externals.lookup(name)
        if external is not None:
            call.resolution = "external"
            symbol = self.table.lookup(self.global_scope, name)
            if symbol is None:
                symbol = self.table.declare(
                    self.global_scope,
                    name,
                    EXTERNAL_FUNCTION,
                    external.return_type,
                    offset=call.span[0],
                    line=call.line,
                    col=call.col,
                    is_global=True,
                )
            call.symbol_id = symbol.id
            self._check_call_args(name, list(external.params), arg_types, call, variadic=external.variadic)
            self.calls.append(
                CallSite(
                    name=name,
                    kind="external",
                    node=call,
                    args=list(call.args),
                    arg_types=arg_types,
                    span=call.span,
                    line=call.line,
                    col=call.col,
                    function=self.current_function.name if self.current_function else None,
                    external=external,
                )
            )
            return

        # Unknown external function: reported once per name, modelled
        # conservatively by the taint engine.
        call.resolution = "unknown"
        self._unresolved_calls.setdefault(name, "unknown")
        self.diagnostic(
            "warning", "SEM008",
            f"call to unknown function '{name}'",
            node=call,
            detail="the function is neither defined in this file nor part of the external model; "
            "the analysis assumes its result may depend on its arguments and does not assume "
            "that it validates anything",
        )
        symbol = self.table.lookup(self.global_scope, name)
        if symbol is None:
            symbol = self.table.declare(
                self.global_scope,
                name,
                EXTERNAL_FUNCTION,
                UNKNOWN_TYPE,
                offset=call.span[0],
                line=call.line,
                col=call.col,
                is_global=True,
            )
            symbol.partial = True
        call.symbol_id = symbol.id
        self.calls.append(
            CallSite(
                name=name,
                kind="unknown",
                node=call,
                args=list(call.args),
                arg_types=arg_types,
                span=call.span,
                line=call.line,
                col=call.col,
                function=self.current_function.name if self.current_function else None,
            )
        )

    def _check_call_args(
        self,
        name: str,
        param_types: Sequence[str],
        arg_types: Sequence[str],
        call: Call,
        variadic: bool = False,
    ) -> None:
        if not variadic and len(param_types) != len(arg_types):
            self.diagnostic(
                "error", "SEM009",
                f"function '{name}' expects {len(param_types)} argument(s) but {len(arg_types)} were given",
                node=call,
                detail="declared parameters: " + (", ".join(param_types) if param_types else "none"),
            )
            return
        if variadic and len(arg_types) < len(param_types):
            self.diagnostic(
                "error", "SEM009",
                f"function '{name}' expects at least {len(param_types)} argument(s) but {len(arg_types)} were given",
                node=call,
            )
            return
        for index, (expected, actual) in enumerate(zip(param_types, arg_types)):
            if actual == UNKNOWN_TYPE:
                self.unknowns.append(
                    {
                        "kind": "argument-type",
                        "line": call.line,
                        "col": call.col,
                        "offset": call.span[0],
                        "detail": f"the type of argument {index} of '{name}' could not be determined",
                    }
                )
                continue
            if expected not in ASSIGN_COMPAT or actual in ASSIGN_COMPAT.get(expected, set()):
                continue
            self.diagnostic(
                "error", "SEM010",
                f"argument {index} of '{name}' has type {actual} but {expected} is expected",
                node=call.args[index] if index < len(call.args) else call,
            )

    def _check_assignable(
        self, target_type: str, value_type: str, node: Node, symbol: Optional[Symbol]
    ) -> None:
        if value_type == UNKNOWN_TYPE:
            self.note_unknown(
                "assignment",
                node,
                f"the value assigned to {symbol.name if symbol else 'this location'} has an "
                "unknown type; the assignment is not type-checked",
            )
            if symbol is not None:
                symbol.partial = True
            return
        allowed = ASSIGN_COMPAT.get(target_type)
        if allowed is None:
            return
        if value_type in allowed:
            narrowing = NARROWING.get((target_type, value_type))
            if narrowing is not None:
                self.diagnostic("warning", narrowing[0], narrowing[1], node=node)
            return
        self.diagnostic(
            "error", "SEM005",
            f"cannot assign a value of type {value_type} to a location of type {target_type}",
            node=node,
            detail="this subset has no implicit conversions except int<->float and int->char",
        )

    # ------------------------------------------------------------------
    # types
    # ------------------------------------------------------------------
    def type_of(self, expr: Optional[Node]) -> str:
        """Abstract type of an expression: a type name or ``"unknown"``."""
        if expr is None:
            return UNKNOWN_TYPE
        if isinstance(expr, IntLit):
            return "int"
        if isinstance(expr, FloatLit):
            return "float"
        if isinstance(expr, CharLit):
            return "char"
        if isinstance(expr, StringLit):
            return "string"
        if isinstance(expr, BoolLit):
            return "bool"
        if isinstance(expr, Ident):
            symbol = self.table.get(expr.symbol_id)
            if symbol is None:
                return UNKNOWN_TYPE
            return symbol.type_name
        if isinstance(expr, Assign):
            return self.type_of(expr.target)
        if isinstance(expr, UnaryOp):
            if expr.op == "!":
                return "bool"
            if expr.op in ("++", "--"):
                return self.type_of(expr.operand)
            return self.type_of(expr.operand)
        if isinstance(expr, BinaryOp):
            return self._binary_type(expr)
        if isinstance(expr, Index):
            base = expr.base
            symbol = self.table.get(base.symbol_id) if isinstance(base, Ident) else None
            if symbol is not None:
                return symbol.type_name
            return UNKNOWN_TYPE
        if isinstance(expr, Call):
            if expr.callee is not None and expr.name in self.functions:
                return self.functions[expr.name].return_type
            external = externals.lookup(expr.name)
            if external is not None:
                return external.return_type
            return UNKNOWN_TYPE
        return UNKNOWN_TYPE

    def _binary_type(self, expr: BinaryOp) -> str:
        op = expr.op
        left = self.type_of(expr.left)
        right = self.type_of(expr.right)
        if op in ("==", "!=", "<", "<=", ">", ">=", "&&", "||"):
            return "bool"
        if op == "+" and (left == "string" or right == "string"):
            if left == "string" and right == "string":
                return "string"
            return "string" if "unknown" not in (left, right) else UNKNOWN_TYPE
        for side in (left, right):
            if side == "float":
                return "float"
            if side == UNKNOWN_TYPE:
                return UNKNOWN_TYPE
            if side not in ("int", "char"):
                return UNKNOWN_TYPE
        return "int"


def analyse(tree: SourceUnit, index: LineIndex, filename: str = "<source>") -> SemanticResult:
    """Run semantic analysis over a parsed translation unit."""
    return SemanticAnalyzer(tree, index, filename).run()
