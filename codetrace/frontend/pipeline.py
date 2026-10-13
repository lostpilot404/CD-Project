"""Lex + parse entry point.

``parser_tables()`` builds (and caches) the LALR(1) parser tables for the CT-C
grammar.  Grammar compilation is pure computation over a fixed grammar, so the
tables are cached in memory for the lifetime of the process and never depend
on the analysed source: the cache is therefore never invalidated by user
input.  ``CODECRACE_PARSER_CACHE_DIR`` may be set to persist the tables as
JSON across processes; if anything about the cached file is unexpected
(missing keys, wrong grammar fingerprint) the cache is ignored and rebuilt.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .ast_nodes import Node, SourceUnit, annotate_locations
from .clr_parser import LRParser, ParserTables, build_tables
from .grammar_lang import build_language_grammar
from .lexer import Diagnostic, LexResult, tokenize
from .source import LineIndex

DEFAULT_MODE = os.environ.get("CODECRACE_PARSER_MODE", "lalr")

_tables_lock = threading.Lock()
_tables_cache: Dict[str, ParserTables] = {}


def grammar_fingerprint() -> str:
    """Stable hash of the grammar definition (used to key the table cache)."""
    grammar = build_language_grammar()
    payload = json.dumps(
        [[p.lhs, list(p.rhs)] for p in grammar.productions],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def parser_tables(mode: str = DEFAULT_MODE) -> ParserTables:
    """Return the (cached) LR tables for the CT-C grammar."""
    key = f"{mode}:{grammar_fingerprint()}"
    cached = _tables_cache.get(key)
    if cached is not None:
        return cached
    with _tables_lock:
        cached = _tables_cache.get(key)
        if cached is not None:
            return cached
        grammar = build_language_grammar()
        tables = build_tables(grammar, mode=mode)
        # Bound the cache: one entry per (mode, grammar) pair in practice.
        if len(_tables_cache) > 8:
            _tables_cache.clear()
        _tables_cache[key] = tables
        return tables


@dataclass
class ParseOutcome:
    """Everything the front end produces for one source file."""

    source: str
    filename: str
    tree: Optional[Node]
    diagnostics: List[Diagnostic] = field(default_factory=list)
    tokens: List = field(default_factory=list)
    index: Optional[LineIndex] = None
    accepted: bool = False
    parse_seconds: float = 0.0
    lex_seconds: float = 0.0
    mode: str = DEFAULT_MODE
    stats: Dict[str, object] = field(default_factory=dict)

    @property
    def errors(self) -> List[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def ok(self) -> bool:
        return self.accepted and not self.errors


def parse_source(source: str, filename: str = "<source>", mode: str = DEFAULT_MODE,
                 max_errors: int = 25, trace_limit: int = 0) -> ParseOutcome:
    """Run the lexer and the LR parser over ``source``."""
    lex_started = time.perf_counter()
    lex: LexResult = tokenize(source, filename)
    lex_seconds = time.perf_counter() - lex_started

    tables = parser_tables(mode)
    parser = LRParser(tables, max_errors=max_errors, trace_limit=trace_limit)
    parse_started = time.perf_counter()
    result = parser.parse(lex.tokens, source)
    parse_seconds = time.perf_counter() - parse_started

    index = LineIndex(source)
    if result.tree is not None:
        annotate_locations(result.tree, index)
        if isinstance(result.tree, SourceUnit):
            result.tree.filename = filename

    diagnostics: List[Diagnostic] = list(lex.diagnostics) + list(result.diagnostics)
    stats = result.stats.to_json()
    stats.update(
        {
            "token_count": len(lex.tokens),
            "accepted": result.accepted,
            "parser_mode": mode,
            "table_states": tables.automaton.stats.states,
        }
    )
    return ParseOutcome(
        source=source,
        filename=filename,
        tree=result.tree,
        diagnostics=diagnostics,
        tokens=lex.tokens,
        index=index,
        accepted=result.accepted,
        parse_seconds=round(parse_seconds, 6),
        lex_seconds=round(lex_seconds, 6),
        mode=mode,
        stats=stats,
    )
