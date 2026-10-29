"""Variable reads and writes per statement.

Data-flow analyses need to know which symbols a statement *reads* and which it
*writes*.  Deriving that from the AST -- rather than from the pattern of names
in the source text -- is what makes the analyses flow-sensitive and
scope-correct: ``x`` in two different scopes are two different symbols, and
``x = 1`` writes ``x`` while reading nothing.

The module deliberately reports *symbol ids*, not names.  An identifier that
semantic analysis could not resolve has id ``-1`` and is ignored here (it has
already been reported as an error).

Assignment targets need special care: the identifier on the left of ``=`` is a
*write*, not a read, and the array base of ``a[i] = v`` is written while the
index ``i`` is read.  :func:`lvalue_accesses` implements that distinction; a
naive "every identifier is a read" rule is the classic source of wrong
liveness and reaching-definitions results.
"""

from __future__ import annotations

from typing import Iterable, List, Set, Tuple

from ..frontend.ast_nodes import (
    Assign,
    BoolLit,
    CharLit,
    EmptyStmt,
    ExprStmt,
    FloatLit,
    ForStmt,
    Ident,
    IfStmt,
    Index,
    IntLit,
    Node,
    ReturnStmt,
    StringLit,
    UnaryOp,
    VarDecl,
    WhileStmt,
)

Accesses = Tuple[Set[int], Set[int]]
_NO_ACCESS: Accesses = (set(), set())


def expression_accesses(node: Node) -> Accesses:
    """``(symbols read, symbols written)`` by an r-value expression."""
    if node is None:
        return set(), set()
    if isinstance(node, Ident):
        return ({node.symbol_id}, set()) if node.symbol_id >= 0 else _NO_ACCESS
    if isinstance(node, (IntLit, FloatLit, CharLit, StringLit, BoolLit)):
        return set(), set()
    if isinstance(node, Assign):
        return _assignment_accesses(node)
    if isinstance(node, UnaryOp):
        if node.op in ("++", "--"):
            # ``x++`` and ``++x`` both read and write x.
            reads, writes = lvalue_accesses(node.operand)
            return reads | writes, writes
        return expression_accesses(node.operand)
    if isinstance(node, Index):
        base_reads, _base_writes = expression_accesses(node.base)
        index_reads, index_writes = expression_accesses(node.index)
        return base_reads | index_reads, index_writes
    reads: Set[int] = set()
    writes: Set[int] = set()
    for child in node.children():
        child_reads, child_writes = expression_accesses(child)
        reads |= child_reads
        writes |= child_writes
    return reads, writes


def lvalue_accesses(node: Node) -> Accesses:
    """``(symbols read, symbols written)`` by an assignment target."""
    if node is None:
        return set(), set()
    if isinstance(node, Ident):
        return (set(), {node.symbol_id}) if node.symbol_id >= 0 else _NO_ACCESS
    if isinstance(node, Index):
        # The array symbol is written; the index expression is read.  The base
        # is *not* a read here: ``a[i] = v`` overwrites one element and never
        # consults the previous contents of ``a``.  (A compound assignment such
        # as ``a[i] += v`` does read the target as well; that is added by
        # ``_assignment_accesses`` below, which unions the writes into the
        # reads for every operator except plain ``=``.)  Counting the base as a
        # read made definite assignment report ``int a[4]; a[0] = 1;`` as a use
        # of an uninitialised variable and made liveness keep ``a`` alive
        # across the write.
        base_reads, base_writes = lvalue_accesses(node.base)
        index_reads, index_writes = expression_accesses(node.index)
        return base_reads | index_reads, base_writes | index_writes
    # Anything else is not a valid lvalue in this subset; treat it as a read so
    # that no spurious write is invented (semantic analysis reports the error).
    return expression_accesses(node)


def _assignment_accesses(node: Assign) -> Accesses:
    target_reads, target_writes = lvalue_accesses(node.target)
    value_reads, value_writes = expression_accesses(node.value)
    if node.op != "=":
        # ``x += e`` reads the previous value of x as well as writing it.
        target_reads = target_reads | target_writes
    return target_reads | value_reads, target_writes | value_writes


def statement_accesses(statement: Node, initialisation_only: bool = False) -> Accesses:
    """``(symbols read, symbols written)`` by one statement (shallow).

    ``initialisation_only`` distinguishes the two meanings of "write" that the
    analyses need:

    * liveness treats ``int x;`` as a definition of ``x`` (the declaration
      gives the variable storage, so an earlier value is dead), which is the
      default;
    * definite-assignment analysis must *not* treat it as a write, because a
      declaration without an initialiser does not give the variable a value.
    """
    if statement is None or isinstance(statement, EmptyStmt):
        return set(), set()
    if isinstance(statement, VarDecl):
        writes = {
            d.symbol_id
            for d in statement.declarators
            if d.symbol_id >= 0 and (d.init is not None or not initialisation_only)
        }
        reads: Set[int] = set()
        for declarator in statement.declarators:
            if declarator.init is not None:
                init_reads, _init_writes = expression_accesses(declarator.init)
                reads |= init_reads
        return reads, writes
    if isinstance(statement, ExprStmt):
        return expression_accesses(statement.expr)
    if isinstance(statement, ReturnStmt):
        return expression_accesses(statement.value)
    if isinstance(statement, IfStmt):
        return expression_accesses(statement.cond)
    if isinstance(statement, (WhileStmt, ForStmt)):
        reads, writes = expression_accesses(statement.cond)
        if isinstance(statement, ForStmt) and statement.init is not None:
            init_reads, init_writes = statement_accesses(statement.init)
            reads |= init_reads
            writes |= init_writes
        return reads, writes
    if statement.kind == "Block":
        return set(), set()
    reads: Set[int] = set()
    writes: Set[int] = set()
    for child in statement.children():
        child_reads, child_writes = expression_accesses(child)
        reads |= child_reads
        writes |= child_writes
    return reads, writes


def statements_accesses(statements: Iterable[Node]) -> List[Accesses]:
    return [statement_accesses(statement) for statement in statements]
