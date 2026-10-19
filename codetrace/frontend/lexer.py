"""Hand-written lexer for the CT-C source subset.

The lexer is a deterministic scanner: it never backtracks more than one
character and always advances, so every input produces a finite token stream
ending in ``EOF``.  Lexical errors are reported as :class:`Diagnostic`
objects and scanning continues from a resynchronisation point, which lets a
single run report several unrelated lexical problems.

Guarantees used by later phases:

* every token carries line/column/offset information,
* ``token.end_*`` fields describe the half-open source range of the token,
* the emitted token stream never contains ``INVALID`` tokens unless the input
  contained characters the language does not define.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .tokens import (
    AMP,
    ANDAND,
    ARROW,
    ASSIGN,
    CHAR_LIT,
    COMMA,
    DECR,
    DOT,
    EOF,
    EQ,
    FLOAT_LIT,
    GE,
    GT,
    IDENT,
    INCR,
    INT_LIT,
    INVALID,
    KEYWORDS,
    LBRACE,
    LBRACKET,
    LE,
    LPAREN,
    LT,
    MINUS,
    MINUSEQ,
    NE,
    NOT,
    OROR,
    PERCENT,
    PERCENTEQ,
    PLUS,
    PLUSEQ,
    RBRACE,
    RBRACKET,
    RPAREN,
    SEMI,
    SLASH,
    SLASHEQ,
    STAR,
    STAREQ,
    STRING_LIT,
    Token,
    UNSUPPORTED_KEYWORDS,
    UNSUPPORTED_KW,
)

Escapes = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
    "\\": "\\",
    "'": "'",
    '"': '"',
}


@dataclass
class Diagnostic:
    """A located, machine-readable problem report.

    ``severity`` is one of ``error``/``warning``/``info``.  ``code`` is a
    stable identifier (``LEX001`` ...) that the UI, tests and reports rely on.
    """

    severity: str
    code: str
    message: str
    line: int
    col: int
    offset: int = 0
    end_offset: int = 0
    phase: str = "lexer"
    detail: str = ""
    unsupported: bool = False

    def to_json(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "line": self.line,
            "col": self.col,
            "offset": self.offset,
            "end_offset": self.end_offset,
            "phase": self.phase,
            "detail": self.detail,
            "unsupported": self.unsupported,
        }


@dataclass
class LexResult:
    tokens: List[Token] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)


def _is_ident_start(ch: str) -> bool:
    """``[A-Za-z_]`` -- the identifier alphabet of CT-C subset v1.

    ``str.isalpha()`` is not used on purpose: it also accepts non-ASCII letters,
    which are outside the documented alphabet and must raise ``LEX008``.
    """
    return ch == "_" or ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _is_ident_continue(ch: str) -> bool:
    """``[A-Za-z0-9_]``."""
    return _is_ident_start(ch) or _is_digit(ch)


def _is_digit(ch: str) -> bool:
    """``[0-9]`` -- literals are ASCII in CT-C subset v1 (docs/LANGUAGE.md §1).

    The Unicode-aware ``str.isdigit`` accepts other digit sets (U+0660, U+0663),
    which ``int()`` then converts, so ``int a = <U+0660>;`` analysed as ``0``.
    """
    return "0" <= ch <= "9"


class Lexer:
    """Longest-match lexer.

    The scanner is shared between the CT-C source language and the security
    rule language: only the keyword table differs, so there is exactly one
    implementation of string/number/comment scanning, unterminated-literal
    detection and source-location tracking.
    """

    def __init__(
        self,
        source: str,
        filename: str = "<source>",
        keywords: Optional[dict] = None,
        unsupported_keywords: Optional[dict] = None,
        language: str = "ct-c",
        hash_comments: bool = False,
    ) -> None:
        self.source = source
        self.filename = filename
        self.keywords = KEYWORDS if keywords is None else keywords
        self.unsupported_keywords = (
            UNSUPPORTED_KEYWORDS if unsupported_keywords is None else unsupported_keywords
        )
        self.language = language
        # ``#`` starts a line comment in the rule language; in CT-C it is the
        # preprocessor, which the subset does not support.
        self.hash_comments = hash_comments
        self.pos = 0
        self.line = 1
        self.col = 1
        self.diagnostics: List[Diagnostic] = []
        # ``_line_starts`` is built lazily for offset -> line/col conversion of
        # multi-line tokens (block comments, strings).
        self._line_starts: Optional[List[int]] = None

    # ------------------------------------------------------------------
    # Source position helpers
    # ------------------------------------------------------------------
    def _starts(self) -> List[int]:
        if self._line_starts is None:
            starts = [0]
            for i, ch in enumerate(self.source):
                if ch == "\n":
                    starts.append(i + 1)
            self._line_starts = starts
        return self._line_starts

    def position(self, offset: int) -> Tuple[int, int]:
        """Return the 1-based (line, col) of a character offset."""
        starts = self._starts()
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, offset - starts[lo] + 1

    def _advance(self, n: int = 1) -> None:
        for _ in range(n):
            if self.pos >= len(self.source):
                return
            if self.source[self.pos] == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
            self.pos += 1

    def _peek(self, ahead: int = 0) -> str:
        idx = self.pos + ahead
        return self.source[idx] if idx < len(self.source) else ""

    def _error(
        self,
        code: str,
        message: str,
        line: int,
        col: int,
        offset: int,
        end_offset: int,
        detail: str = "",
        severity: str = "error",
        unsupported: bool = False,
    ) -> None:
        self.diagnostics.append(
            Diagnostic(
                severity=severity,
                code=code,
                message=message,
                line=line,
                col=col,
                offset=offset,
                end_offset=end_offset,
                phase="lexer",
                detail=detail,
                unsupported=unsupported,
            )
        )

    def _make_token(
        self,
        kind: str,
        start: int,
        start_line: int,
        start_col: int,
        value: Optional[object] = None,
    ) -> Token:
        text = self.source[start : self.pos]
        return Token(
            kind=kind,
            text=text,
            line=start_line,
            col=start_col,
            offset=start,
            end_offset=self.pos,
            end_line=self.line,
            end_col=self.col,
            value=value,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def tokenize(self) -> LexResult:
        tokens: List[Token] = []
        src = self.source
        while self.pos < len(src):
            ch = src[self.pos]
            # Whitespace -------------------------------------------------
            if ch in " \t\r\n\f\v":
                self._advance()
                continue
            # Comments ---------------------------------------------------
            if ch == "/" and self._peek(1) == "/":
                while self.pos < len(src) and src[self.pos] != "\n":
                    self._advance()
                continue
            if ch == "/" and self._peek(1) == "*":
                self._block_comment()
                continue
            # ``#`` line comment or preprocessor directive -----------------
            if ch == "#":
                if self.hash_comments:
                    while self.pos < len(src) and src[self.pos] != "\n":
                        self._advance()
                else:
                    self._preprocessor_line()
                continue
            start, start_line, start_col = self.pos, self.line, self.col
            # Identifiers and keywords -----------------------------------
            if _is_ident_start(ch):
                while self.pos < len(src) and _is_ident_continue(src[self.pos]):
                    self._advance()
                word = src[start : self.pos]
                if word in self.keywords:
                    tokens.append(self._make_token(self.keywords[word], start, start_line, start_col, word))
                elif word in self.unsupported_keywords:
                    tok = self._make_token(UNSUPPORTED_KW, start, start_line, start_col, word)
                    tokens.append(tok)
                    self._error(
                        "LEX100",
                        f"unsupported construct: {self.unsupported_keywords[word]}",
                        start_line,
                        start_col,
                        start,
                        self.pos,
                        detail=self.unsupported_keywords[word],
                        unsupported=True,
                    )
                else:
                    tokens.append(self._make_token(IDENT, start, start_line, start_col, word))
                continue
            # Numbers -----------------------------------------------------
            if _is_digit(ch):
                tokens.append(self._number(start, start_line, start_col))
                continue
            # String literal ----------------------------------------------
            if ch == '"':
                token = self._string(start, start_line, start_col)
                if token is not None:
                    tokens.append(token)
                continue
            # Character literal -------------------------------------------
            if ch == "'":
                token = self._char(start, start_line, start_col)
                if token is not None:
                    tokens.append(token)
                continue
            # Operators and punctuation -----------------------------------
            token = self._operator(start, start_line, start_col)
            if token is not None:
                tokens.append(token)
            continue

        eof_line, eof_col = self.position(len(src))
        tokens.append(
            Token(
                kind=EOF,
                text="",
                line=eof_line,
                col=eof_col,
                offset=len(src),
                end_offset=len(src),
                end_line=eof_line,
                end_col=eof_col,
            )
        )
        return LexResult(tokens=tokens, diagnostics=self.diagnostics)

    # ------------------------------------------------------------------
    # Sub-scanners
    # ------------------------------------------------------------------
    def _block_comment(self) -> None:
        start, start_line, start_col = self.pos, self.line, self.col
        self._advance(2)
        closed = False
        while self.pos < len(self.source):
            if self.source[self.pos] == "*" and self._peek(1) == "/":
                self._advance(2)
                closed = True
                break
            self._advance()
        if not closed:
            self._error(
                "LEX002",
                "unterminated block comment (missing '*/')",
                start_line,
                start_col,
                start,
                self.pos,
                detail=(
                    "a block comment must be closed with '*/' before the end of the file; "
                    "everything after the opening '/*' was treated as comment text"
                ),
            )

    def _preprocessor_line(self) -> None:
        """Report ``#...`` directives as unsupported and skip the line."""
        start, start_line, start_col = self.pos, self.line, self.col
        while self.pos < len(self.source) and self.source[self.pos] != "\n":
            # A backslash-newline continues the directive
            if self.source[self.pos] == "\\" and self._peek(1) == "\n":
                self._advance(2)
                continue
            self._advance()
        text = self.source[start : self.pos].strip()
        self._error(
            "LEX101",
            f"unsupported construct: the preprocessor is not part of the {self.language} language",
            start_line,
            start_col,
            start,
            self.pos,
            detail=f"directive: {text[:60]}",
            unsupported=True,
        )

    def _number(self, start: int, start_line: int, start_col: int) -> Token:
        src = self.source
        is_float = False
        if src[start] == "0" and self._peek(1) in ("x", "X"):
            self._advance(2)
            digits = 0
            while self.pos < len(src) and (_is_digit(src[self.pos]) or src[self.pos].lower() in "abcdef_"):
                if src[self.pos] != "_":
                    digits += 1
                self._advance()
            if digits == 0:
                self._error("LEX003", "malformed hexadecimal literal", start_line, start_col, start, self.pos)
                return self._make_token(INVALID, start, start_line, start_col)
            text = src[start : self.pos].replace("_", "")
            return self._make_token(INT_LIT, start, start_line, start_col, int(text, 16))

        while self.pos < len(src) and (_is_digit(src[self.pos]) or src[self.pos] == "_"):
            self._advance()
        if self.pos < len(src) and src[self.pos] == "." and _is_digit(self._peek(1)):
            is_float = True
            self._advance()
            while self.pos < len(src) and (_is_digit(src[self.pos]) or src[self.pos] == "_"):
                self._advance()
        if self.pos < len(src) and src[self.pos] in "eE":
            nxt = self._peek(1)
            if _is_digit(nxt) or (nxt in "+-" and _is_digit(self._peek(2))):
                is_float = True
                self._advance()
                if src[self.pos] in "+-":
                    self._advance()
                while self.pos < len(src) and _is_digit(src[self.pos]):
                    self._advance()
        if self.pos < len(src) and _is_ident_start(src[self.pos]):
            # e.g. ``12abc`` -- trailing identifier characters are suspicious.
            self._error(
                "LEX004",
                "malformed numeric literal: unexpected trailing characters",
                start_line,
                start_col,
                start,
                self.pos,
            )
        text = src[start : self.pos].replace("_", "")
        if is_float:
            return self._make_token(FLOAT_LIT, start, start_line, start_col, float(text))
        return self._make_token(INT_LIT, start, start_line, start_col, int(text, 10))

    def _scan_escaped(self, quote: str, start_line: int, start_col: int, start: int) -> Tuple[str, bool]:
        """Consume the body of a character/string literal.

        Returns the decoded value and whether the literal terminated.
        """
        chars: List[str] = []
        while True:
            if self.pos >= len(self.source):
                return "".join(chars), False
            ch = self.source[self.pos]
            if ch == "\n":
                # Unterminated: do not consume the newline so line numbers of
                # subsequent tokens stay correct.
                return "".join(chars), False
            if ch == "\\":
                nxt = self._peek(1)
                if nxt == "":
                    self._advance()
                    return "".join(chars), False
                if nxt in Escapes:
                    chars.append(Escapes[nxt])
                    self._advance(2)
                    continue
                if nxt == "x":
                    self._advance(2)
                    hexdigits = ""
                    while self.pos < len(self.source) and len(hexdigits) < 2 and self.source[self.pos] in "0123456789abcdefABCDEF":
                        hexdigits += self.source[self.pos]
                        self._advance()
                    if not hexdigits:
                        self._error("LEX006", "malformed escape sequence '\\x'", start_line, start_col, start, self.pos)
                        chars.append("x")
                    else:
                        chars.append(chr(int(hexdigits, 16)))
                    continue
                self._error(
                    "LEX005",
                    f"unknown escape sequence '\\{nxt}'",
                    start_line,
                    start_col,
                    self.pos,
                    self.pos + 2,
                    severity="warning",
                )
                chars.append(nxt)
                self._advance(2)
                continue
            if ch == quote:
                self._advance()
                return "".join(chars), True
            chars.append(ch)
            self._advance()

    def _string(self, start: int, start_line: int, start_col: int) -> Optional[Token]:
        self._advance()  # opening quote
        value, closed = self._scan_escaped('"', start_line, start_col, start)
        if not closed:
            self._error(
                "LEX001",
                "unterminated string literal",
                start_line,
                start_col,
                start,
                self.pos,
                detail=(
                    'a string literal must be closed with a double quote before the end of '
                    'the line; the partial literal was kept so that later phases still see a value'
                ),
            )
            # Emit the partial literal so downstream phases keep a value.
            return Token(
                kind=STRING_LIT,
                text=self.source[start : self.pos],
                line=start_line,
                col=start_col,
                offset=start,
                end_offset=self.pos,
                end_line=self.line,
                end_col=self.col,
                value=value,
            )
        return self._make_token(STRING_LIT, start, start_line, start_col, value)

    def _char(self, start: int, start_line: int, start_col: int) -> Optional[Token]:
        self._advance()  # opening quote
        value, closed = self._scan_escaped("'", start_line, start_col, start)
        if not closed:
            self._error(
                "LEX001",
                "unterminated character literal",
                start_line,
                start_col,
                start,
                self.pos,
                detail="a character literal must be closed with a single quote on the same line",
            )
            return Token(
                kind=CHAR_LIT,
                text=self.source[start : self.pos],
                line=start_line,
                col=start_col,
                offset=start,
                end_offset=self.pos,
                end_line=self.line,
                end_col=self.col,
                value=value[:1] if value else "",
            )
        if len(value) != 1:
            self._error(
                "LEX007",
                "character literal must contain exactly one character",
                start_line,
                start_col,
                start,
                self.pos,
            )
        return self._make_token(CHAR_LIT, start, start_line, start_col, value[:1] if value else "")

    #: Ordered longest-first so that multi-character operators win over
    #: one-character ones (maximal munch).
    _OPERATORS: Tuple[Tuple[str, str], ...] = (
        ("<<=", INVALID),
        (">>=", INVALID),
        ("++", INCR),
        ("--", DECR),
        ("+=", PLUSEQ),
        ("-=", MINUSEQ),
        ("*=", STAREQ),
        ("/=", SLASHEQ),
        ("%=", PERCENTEQ),
        ("==", EQ),
        ("!=", NE),
        ("<=", LE),
        (">=", GE),
        ("&&", ANDAND),
        ("||", OROR),
        ("<<", INVALID),
        (">>", INVALID),
        ("->", INVALID),
        ("(", LPAREN),
        (")", RPAREN),
        ("{", LBRACE),
        ("}", RBRACE),
        ("[", LBRACKET),
        ("]", RBRACKET),
        (";", SEMI),
        (",", COMMA),
        (".", DOT),
        ("+", PLUS),
        ("-", MINUS),
        ("*", STAR),
        ("/", SLASH),
        ("%", PERCENT),
        ("=", ASSIGN),
        ("<", LT),
        (">", GT),
        ("!", NOT),
        ("&", INVALID),
    )

    #: Operators that are valid C but unsupported here; a dedicated message
    #: beats "invalid character".
    _UNSUPPORTED_OPS: dict[str, str] = {
        "->": "pointer member access ('->') is outside the supported subset",
        "&": "the address-of / bitwise-and operator ('&') is outside the supported subset",
        "<<": "bitwise shift operators are outside the supported subset",
        ">>": "bitwise shift operators are outside the supported subset",
        "<<=": "bitwise shift-assign operators are outside the supported subset",
        ">>=": "bitwise shift-assign operators are outside the supported subset",
    }

    def _operator(self, start: int, start_line: int, start_col: int) -> Optional[Token]:
        src = self.source
        for text, kind in self._OPERATORS:
            if src.startswith(text, start):
                if kind == INVALID:
                    self._advance(len(text))
                    tok = self._make_token(INVALID, start, start_line, start_col)
                    self._error(
                        "LEX102",
                        f"unsupported construct: {self._UNSUPPORTED_OPS.get(text, text)}",
                        start_line,
                        start_col,
                        start,
                        self.pos,
                        detail=self._UNSUPPORTED_OPS.get(text, text),
                        unsupported=True,
                    )
                    return tok
                self._advance(len(text))
                return self._make_token(kind, start, start_line, start_col)

        # Unknown single character -------------------------------------------
        ch = src[start]
        if ch in "^|~":
            hint = "bitwise operators are outside the supported subset"
            code, unsupported = "LEX102", True
        elif ch == "?":
            hint = "the conditional (?:) operator is outside the supported subset"
            code, unsupported = "LEX102", True
        elif ch == ":":
            hint = "the ':' token is outside the supported subset"
            code, unsupported = "LEX102", True
        elif ch == "\\":
            hint = "stray backslash outside a literal"
            code, unsupported = "LEX008", False
        else:
            hint = "the character is not part of the CT-C alphabet"
            code, unsupported = "LEX008", False
        self._advance()
        tok = self._make_token(INVALID, start, start_line, start_col)
        self._error(
            code,
            f"invalid character {ch!r}: {hint}" if not unsupported else f"unsupported construct: {hint}",
            start_line,
            start_col,
            start,
            self.pos,
            detail=hint,
            unsupported=unsupported,
        )
        return tok


def tokenize(
    source: str,
    filename: str = "<source>",
    keywords: Optional[dict] = None,
    unsupported_keywords: Optional[dict] = None,
    language: str = "ct-c",
    hash_comments: bool = False,
) -> LexResult:
    """Convenience wrapper used by the pipeline, the rule parser and the tests."""
    return Lexer(
        source, filename, keywords, unsupported_keywords, language, hash_comments
    ).tokenize()
