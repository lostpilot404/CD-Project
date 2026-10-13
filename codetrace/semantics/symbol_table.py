"""Symbol tables with stable symbol identities.

A :class:`Symbol` is created exactly once per declaration and is identified by
an integer ``id`` that is unique within an analysis run.  Later phases
(reaching definitions, taint propagation, slicing, graphs) refer to symbols by
id, never by name, which is what prevents two variables that happen to share a
spelling in different scopes from being conflated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional

#: Symbol kinds.
VARIABLE = "variable"
PARAMETER = "parameter"
FUNCTION = "function"
EXTERNAL_FUNCTION = "external_function"
ARRAY = "array"

SCOPE_GLOBAL = "global"
SCOPE_FUNCTION = "function"
SCOPE_BLOCK = "block"


@dataclass
class Reference:
    """One use of a symbol in the source."""

    offset: int
    line: int
    col: int
    kind: str  # "read" | "write" | "readwrite" | "declaration" | "call"
    sid: int = -1  # statement id, when known


@dataclass
class Symbol:
    id: int
    name: str
    kind: str
    type_name: str
    scope_id: int
    decl_offset: int = 0
    decl_line: int = 0
    decl_col: int = 0
    function: Optional[str] = None
    is_global: bool = False
    is_array: bool = False
    array_size: Optional[int] = None
    param_index: Optional[int] = None
    references: List[Reference] = field(default_factory=list)
    #: Set for symbols whose declaration the analyser could not fully model.
    partial: bool = False

    # -- convenience ---------------------------------------------------
    @property
    def reads(self) -> List[Reference]:
        return [r for r in self.references if r.kind in ("read", "readwrite")]

    @property
    def writes(self) -> List[Reference]:
        return [r for r in self.references if r.kind in ("write", "readwrite")]

    def add_reference(self, offset: int, line: int, col: int, kind: str, sid: int = -1) -> None:
        self.references.append(Reference(offset=offset, line=line, col=col, kind=kind, sid=sid))

    def to_json(self, include_references: bool = True) -> dict:
        payload = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "type": self.type_name,
            "scope_id": self.scope_id,
            "decl": {"offset": self.decl_offset, "line": self.decl_line, "col": self.decl_col},
            "function": self.function,
            "is_global": self.is_global,
            "is_array": self.is_array,
            "array_size": self.array_size,
            "param_index": self.param_index,
            "partial": self.partial,
            "read_count": len(self.reads),
            "write_count": len(self.writes),
        }
        if include_references:
            payload["references"] = [
                {"offset": r.offset, "line": r.line, "col": r.col, "kind": r.kind, "sid": r.sid}
                for r in self.references
            ]
        return payload

    def describe(self) -> str:
        kind = self.kind.replace("_", " ")
        where = f"{self.decl_line}:{self.decl_col}"
        return f"{kind} '{self.name}' of type {self.type_name} declared at {where}"


@dataclass
class Scope:
    id: int
    kind: str
    parent: Optional[int] = None
    owner_function: Optional[str] = None
    span: tuple = (0, 0)
    symbols: Dict[str, Symbol] = field(default_factory=dict)

    def to_json(self, with_symbols: bool = False) -> dict:
        payload = {
            "id": self.id,
            "kind": self.kind,
            "parent": self.parent,
            "function": self.owner_function,
            "span": list(self.span),
            "symbol_ids": sorted(s.id for s in self.symbols.values()),
            "symbol_names": sorted(self.symbols),
        }
        if with_symbols:
            payload["symbols"] = {name: sym.to_json() for name, sym in self.symbols.items()}
        return payload


class SymbolTable:
    """Scope tree plus symbol registry for one translation unit."""

    def __init__(self) -> None:
        self.scopes: Dict[int, Scope] = {}
        self.symbols: Dict[int, Symbol] = {}
        self.root = self.new_scope(SCOPE_GLOBAL, parent=None)
        self._next_symbol_id = 1

    # ------------------------------------------------------------------
    def new_scope(self, kind: str, parent: Optional[int], owner_function: Optional[str] = None,
                  span: tuple = (0, 0)) -> int:
        scope_id = len(self.scopes)
        self.scopes[scope_id] = Scope(
            id=scope_id, kind=kind, parent=parent, owner_function=owner_function, span=span
        )
        return scope_id

    def declare(
        self,
        scope_id: int,
        name: str,
        kind: str,
        type_name: str,
        offset: int = 0,
        line: int = 0,
        col: int = 0,
        is_array: bool = False,
        array_size: Optional[int] = None,
        param_index: Optional[int] = None,
        is_global: bool = False,
    ) -> Symbol:
        symbol = Symbol(
            id=self._next_symbol_id,
            name=name,
            kind=kind,
            type_name=type_name,
            scope_id=scope_id,
            decl_offset=offset,
            decl_line=line,
            decl_col=col,
            function=None,
            is_global=is_global,
            is_array=is_array,
            array_size=array_size,
            param_index=param_index,
        )
        self._next_symbol_id += 1
        self.symbols[symbol.id] = symbol
        self.scopes[scope_id].symbols[name] = symbol
        return symbol

    # ------------------------------------------------------------------
    def lookup(self, scope_id: int, name: str) -> Optional[Symbol]:
        """Resolve ``name`` starting at ``scope_id`` and walking to the root."""
        current: Optional[int] = scope_id
        while current is not None:
            scope = self.scopes[current]
            if name in scope.symbols:
                return scope.symbols[name]
            current = scope.parent
        return None

    def lookup_local(self, scope_id: int, name: str) -> Optional[Symbol]:
        return self.scopes[scope_id].symbols.get(name)

    def shadowed_symbol(self, scope_id: int, name: str) -> Optional[Symbol]:
        """Symbol hidden by a new declaration of ``name`` in ``scope_id``."""
        parent = self.scopes[scope_id].parent
        return self.lookup(parent, name) if parent is not None else None

    def scope_chain(self, scope_id: int) -> List[Scope]:
        chain: List[Scope] = []
        current: Optional[int] = scope_id
        while current is not None:
            chain.append(self.scopes[current])
            current = self.scopes[current].parent
        return chain

    def get(self, symbol_id: int) -> Optional[Symbol]:
        return self.symbols.get(symbol_id)

    def by_name(self, name: str) -> List[Symbol]:
        return [s for s in self.symbols.values() if s.name == name]

    def globals(self) -> List[Symbol]:
        return [s for s in self.symbols.values() if s.is_global]

    def functions(self) -> List[Symbol]:
        return [s for s in self.symbols.values() if s.kind == FUNCTION]

    def variables(self) -> List[Symbol]:
        return [s for s in self.symbols.values() if s.kind in (VARIABLE, PARAMETER, ARRAY)]

    def __iter__(self) -> Iterator[Symbol]:
        return iter(self.symbols.values())

    def to_json(self, with_symbols: bool = True) -> dict:
        return {
            "scopes": [self.scopes[i].to_json(with_symbols=False) for i in sorted(self.scopes)],
            "scope_tree": self._tree_json(self.root),
            "symbols": [s.to_json() for s in sorted(self.symbols.values(), key=lambda s: s.id)]
            if with_symbols
            else [],
            "symbol_count": len(self.symbols),
            "scope_count": len(self.scopes),
        }

    def _tree_json(self, scope_id: int) -> dict:
        children = [s.id for s in self.scopes.values() if s.parent == scope_id]
        return {
            "id": scope_id,
            "kind": self.scopes[scope_id].kind,
            "function": self.scopes[scope_id].owner_function,
            "span": list(self.scopes[scope_id].span),
            "symbols": [
                {"id": sym.id, "name": sym.name, "type": sym.type_name, "kind": sym.kind}
                for sym in sorted(self.scopes[scope_id].symbols.values(), key=lambda s: s.id)
            ],
            "children": [self._tree_json(c) for c in sorted(children)],
        }
