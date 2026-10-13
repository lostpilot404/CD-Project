"""Token definitions for the CodeTrace source language (``CT-C``).

The lexer produces tokens whose ``kind`` is one of the symbolic names declared
here.  Grammar productions in :mod:`codetrace.frontend.grammar_lang` refer to
those symbolic names directly, so the token vocabulary of the lexer and the
terminal alphabet of the grammar can never drift apart silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# --------------------------------------------------------------------------
# Token kind constants
# --------------------------------------------------------------------------

EOF = "EOF"

# Literals and names ------------------------------------------------------
IDENT = "IDENT"
INT_LIT = "INT_LIT"
FLOAT_LIT = "FLOAT_LIT"
CHAR_LIT = "CHAR_LIT"
STRING_LIT = "STRING_LIT"

# Supported keywords ------------------------------------------------------
KW_INT = "KW_INT"
KW_FLOAT = "KW_FLOAT"
KW_CHAR = "KW_CHAR"
KW_BOOL = "KW_BOOL"
KW_STRING = "KW_STRING"
KW_VOID = "KW_VOID"
KW_IF = "KW_IF"
KW_ELSE = "KW_ELSE"
KW_WHILE = "KW_WHILE"
KW_FOR = "KW_FOR"
KW_RETURN = "KW_RETURN"
KW_BREAK = "KW_BREAK"
KW_CONTINUE = "KW_CONTINUE"
KW_TRUE = "KW_TRUE"
KW_FALSE = "KW_FALSE"

# Punctuation -------------------------------------------------------------
LPAREN = "LPAREN"
RPAREN = "RPAREN"
LBRACE = "LBRACE"
RBRACE = "RBRACE"
LBRACKET = "LBRACKET"
RBRACKET = "RBRACKET"
SEMI = "SEMI"
COMMA = "COMMA"
DOT = "DOT"

# Operators ---------------------------------------------------------------
PLUS = "PLUS"
MINUS = "MINUS"
STAR = "STAR"
SLASH = "SLASH"
PERCENT = "PERCENT"
ASSIGN = "ASSIGN"
PLUSEQ = "PLUSEQ"
MINUSEQ = "MINUSEQ"
STAREQ = "STAREQ"
SLASHEQ = "SLASHEQ"
PERCENTEQ = "PERCENTEQ"
INCR = "INCR"
DECR = "DECR"
EQ = "EQ"
NE = "NE"
LT = "LT"
LE = "LE"
GT = "GT"
GE = "GE"
ANDAND = "ANDAND"
OROR = "OROR"
NOT = "NOT"
ARROW = "ARROW"
AMP = "AMP"

#: Words belonging to C (or a C-family language) that CodeTrace deliberately
#: does not support.  They are tokenised separately so that the parser can
#: report "unsupported construct" instead of a generic syntax error.
UNSUPPORTED_KW = "UNSUPPORTED_KW"

#: Tokens that the lexer emits for text it could not classify.  These are
#: never shifted by the grammar; they only exist so that recovery has a token
#: to skip.
INVALID = "INVALID"


KEYWORDS: dict[str, str] = {
    "int": KW_INT,
    "float": KW_FLOAT,
    "char": KW_CHAR,
    "bool": KW_BOOL,
    "string": KW_STRING,
    "void": KW_VOID,
    "if": KW_IF,
    "else": KW_ELSE,
    "while": KW_WHILE,
    "for": KW_FOR,
    "return": KW_RETURN,
    "break": KW_BREAK,
    "continue": KW_CONTINUE,
    "true": KW_TRUE,
    "false": KW_FALSE,
}

#: Recognised-but-unsupported keywords.  Mapping word -> human explanation.
UNSUPPORTED_KEYWORDS: dict[str, str] = {
    "switch": "switch statements are outside the supported subset",
    "case": "switch/case statements are outside the supported subset",
    "default": "switch/default labels are outside the supported subset",
    "do": "do/while loops are outside the supported subset",
    "goto": "goto statements are outside the supported subset",
    "struct": "struct declarations are outside the supported subset",
    "union": "union declarations are outside the supported subset",
    "enum": "enum declarations are outside the supported subset",
    "typedef": "typedef is outside the supported subset",
    "sizeof": "sizeof is outside the supported subset",
    "unsigned": "signed/unsigned qualifiers are outside the supported subset",
    "signed": "signed/unsigned qualifiers are outside the supported subset",
    "short": "short is outside the supported subset",
    "long": "long is outside the supported subset",
    "double": "double is outside the supported subset",
    "static": "static storage class is outside the supported subset",
    "extern": "extern storage class is outside the supported subset",
    "const": "const qualifiers are outside the supported subset",
    "volatile": "volatile qualifiers are outside the supported subset",
    "register": "register storage class is outside the supported subset",
    "auto": "auto storage class is outside the supported subset",
    "inline": "inline is outside the supported subset",
    "class": "C++ class declarations are outside the supported subset",
    "namespace": "C++ namespaces are outside the supported subset",
    "template": "C++ templates are outside the supported subset",
    "new": "C++ new expressions are outside the supported subset",
    "delete": "C++ delete expressions are outside the supported subset",
    "try": "C++ exception handling is outside the supported subset",
    "catch": "C++ exception handling is outside the supported subset",
    "throw": "C++ exception handling is outside the supported subset",
}

BASE_TYPES = (KW_INT, KW_FLOAT, KW_CHAR, KW_BOOL, KW_STRING, KW_VOID)

#: Every token kind that may appear as a grammar terminal.  ``EOF`` is
#: included; ``INVALID`` is deliberately excluded because the grammar never
#: shifts it.
TERMINALS: tuple[str, ...] = (
    (EOF, IDENT, INT_LIT, FLOAT_LIT, CHAR_LIT, STRING_LIT)
    + (KW_INT, KW_FLOAT, KW_CHAR, KW_BOOL, KW_STRING, KW_VOID)
    + (KW_IF, KW_ELSE, KW_WHILE, KW_FOR, KW_RETURN, KW_BREAK, KW_CONTINUE, KW_TRUE, KW_FALSE)
    + (LPAREN, RPAREN, LBRACE, RBRACE, LBRACKET, RBRACKET, SEMI, COMMA, DOT)
    + (
        PLUS, MINUS, STAR, SLASH, PERCENT, ASSIGN, PLUSEQ, MINUSEQ, STAREQ,
        SLASHEQ, PERCENTEQ, INCR, DECR, EQ, NE, LT, LE, GT, GE, ANDAND, OROR,
        NOT, ARROW, AMP,
    )
)

#: Human-readable spelling used in diagnostics ("expected ``;``").
DISPLAY: dict[str, str] = {
    EOF: "end of file",
    IDENT: "identifier",
    INT_LIT: "integer literal",
    FLOAT_LIT: "float literal",
    CHAR_LIT: "character literal",
    STRING_LIT: "string literal",
    LPAREN: "(",
    RPAREN: ")",
    LBRACE: "{",
    RBRACE: "}",
    LBRACKET: "[",
    RBRACKET: "]",
    SEMI: ";",
    COMMA: ",",
    DOT: ".",
    PLUS: "+",
    MINUS: "-",
    STAR: "*",
    SLASH: "/",
    PERCENT: "%",
    ASSIGN: "=",
    PLUSEQ: "+=",
    MINUSEQ: "-=",
    STAREQ: "*=",
    SLASHEQ: "/=",
    PERCENTEQ: "%=",
    INCR: "++",
    DECR: "--",
    EQ: "==",
    NE: "!=",
    LT: "<",
    LE: "<=",
    GT: ">",
    GE: ">=",
    ANDAND: "&&",
    OROR: "||",
    NOT: "!",
    ARROW: "->",
    AMP: "&",
    KW_INT: "int",
    KW_FLOAT: "float",
    KW_CHAR: "char",
    KW_BOOL: "bool",
    KW_STRING: "string",
    KW_VOID: "void",
    KW_IF: "if",
    KW_ELSE: "else",
    KW_WHILE: "while",
    KW_FOR: "for",
    KW_RETURN: "return",
    KW_BREAK: "break",
    KW_CONTINUE: "continue",
    KW_TRUE: "true",
    KW_FALSE: "false",
}


@dataclass(frozen=True)
class Token:
    """A single lexical unit with a stable source location.

    ``line``/``col`` are 1-based; ``offset``/``end_offset`` are 0-based byte
    (character) offsets into the original source text.
    """

    kind: str
    text: str
    line: int
    col: int
    offset: int
    end_offset: int
    end_line: int = 0
    end_col: int = 0
    #: Decoded literal value for INT/FLOAT/CHAR/STRING tokens.
    value: Optional[object] = None

    def display(self) -> str:
        """Spelling used inside diagnostic messages."""
        if self.kind == IDENT:
            return f"identifier '{self.text}'"
        if self.kind == UNSUPPORTED_KW:
            return f"keyword '{self.text}'"
        if self.kind in DISPLAY:
            return DISPLAY[self.kind]
        if self.kind == INVALID:
            return f"invalid character '{self.text}'"
        return self.text

    def to_json(self) -> dict:
        return {
            "kind": self.kind,
            "text": self.text,
            "line": self.line,
            "col": self.col,
            "offset": self.offset,
            "end_offset": self.end_offset,
            "end_line": self.end_line,
            "end_col": self.end_col,
        }


def display_kind(kind: str) -> str:
    """Human-readable name of a terminal kind (used by parser diagnostics)."""
    return DISPLAY.get(kind, kind)
