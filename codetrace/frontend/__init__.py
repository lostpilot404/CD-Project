"""Front end for the CT-C source subset.

``codetrace.frontend`` contains the compiler-theory machinery of CodeTrace:

======================  =================================================
module                  role
======================  =================================================
``tokens``              terminal alphabet and token record type
``lexer``               hand-written lexer with located diagnostics
``grammar``             grammar representation, NULLABLE/FIRST/FOLLOW,
                        LR(0)/LR(1) items, closure, GOTO, automata
``clr_parser``          ACTION/GOTO table construction, conflict reporting,
                        table-driven parse driver with error recovery
``grammar_lang``        the CT-C grammar expressed as productions + actions
``ast_nodes``           AST node classes used by every later phase
``pipeline``            lex + parse convenience entry point
======================  =================================================
"""

from .clr_parser import LRParser, ParserTables, build_tables
from .grammar import END, Grammar, build_automaton
from .pipeline import ParseOutcome, parse_source, parser_tables

__all__ = [
    "END",
    "Grammar",
    "LRParser",
    "ParserTables",
    "ParseOutcome",
    "build_automaton",
    "build_tables",
    "parse_source",
    "parser_tables",
]
