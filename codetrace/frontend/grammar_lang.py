"""The CT-C grammar: productions, semantic actions and grammar documentation.

The grammar is written directly in the notation of the LR literature:
nonterminals are lower-case, terminals are the token kinds produced by
:mod:`codetrace.frontend.lexer`.  Precedence and associativity are encoded as
grammar levels (``assign``/``logic_or``/``logic_and``/``equality``/
``relational``/``additive``/``multiplicative``/``unary``/``postfix``/
``primary``) instead of using a yacc-style precedence table, because the whole
point of CodeTrace is to build LR(1) tables from a grammar rather than to
dodge conflicts.

Two deliberate engineering decisions are visible in the production list:

* **Dangling else.**  The statement grammar is factored into
  ``matched_statement`` / ``open_statement`` (the standard dragon-book
  factoring) so that the grammar is conflict-free *by construction* rather
  than relying on the generic "shift wins" conflict-resolution policy.
* **``for`` loops.**  ``for_setup``/``for_tail`` use an ``expr_opt``
  nonterminal so that every optional clause has exactly one production,
  which removes the shift/reduce conflict a naive 4-way factoring produces.

Both are checked by :mod:`codetrace.tests.test_parser_generator`, which
asserts that the built-in grammar builds with zero conflicts.
"""

from __future__ import annotations

from typing import List, Optional

from .ast_nodes import (
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
)
from .grammar import Grammar
from .lexer import Diagnostic
from .source import LineIndex
from .tokens import (
    AMP,
    ANDAND,
    ARROW,
    ASSIGN,
    KW_BREAK,
    CHAR_LIT,
    COMMA,
    KW_CONTINUE,
    DECR,
    DOT,
    KW_ELSE,
    EQ,
    FLOAT_LIT,
    KW_FOR,
    GE,
    GT,
    IDENT,
    INCR,
    INT_LIT,
    KW_BOOL,
    KW_FALSE,
    KW_CHAR,
    KW_FLOAT,
    KW_IF,
    KW_INT,
    KW_RETURN,
    KW_STRING,
    KW_TRUE,
    KW_VOID,
    KW_WHILE,
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
)

#: Spelling of the operators that the ``assign`` productions accept.
ASSIGN_OPS = {
    ASSIGN: "=",
    PLUSEQ: "+=",
    MINUSEQ: "-=",
    STAREQ: "*=",
    SLASHEQ: "/=",
    PERCENTEQ: "%=",
}

BINARY_OP_TEXT = {
    PLUS: "+",
    MINUS: "-",
    STAR: "*",
    SLASH: "/",
    PERCENT: "%",
    EQ: "==",
    NE: "!=",
    LT: "<",
    LE: "<=",
    GT: ">",
    GE: ">=",
    ANDAND: "&&",
    OROR: "||",
}

TYPE_KEYWORDS = {
    KW_INT: "int",
    KW_FLOAT: "float",
    KW_CHAR: "char",
    KW_BOOL: "bool",
    KW_STRING: "string",
    KW_VOID: "void",
}


class LanguageGrammarBuilder:
    """Builds the CT-C grammar with semantic actions bound to a source text."""

    def __init__(self, source: str = "", filename: str = "<source>") -> None:
        self.source = source
        self.filename = filename
        self.index = LineIndex(source)
        self.grammar = Grammar("program")
        self._build()

    # ------------------------------------------------------------------
    def mk(self, cls, children, span, **kwargs):
        """Instantiate an AST node carrying its source span.

        Line/column fields are filled in after parsing by
        :func:`codetrace.frontend.pipeline.parse_source`, which resolves spans
        against the actual source text.  Keeping the builders independent of
        the source text is what allows the parser tables (and therefore this
        grammar instance) to be shared and cached across analyses.
        """
        return cls(span=span, **kwargs)

    def _token_span(self, token_or_node) -> tuple:
        span = getattr(token_or_node, "span", None)
        if span is not None:
            return tuple(span)
        return (token_or_node.offset, token_or_node.end_offset)

    # ------------------------------------------------------------------
    def _build(self) -> None:
        g = self.grammar
        mk = self.mk

        # -- program structure ----------------------------------------
        g.add("program", ("decl_list",), lambda ch, span: mk(SourceUnit, ch, span, filename=self.filename, decls=ch[0]), "translation unit")
        g.add("decl_list", ("decl_list", "decl"), lambda ch, span: ch[0] + [ch[1]], "append declaration")
        g.add("decl_list", (), lambda ch, span: [], "empty declaration list")

        g.add("decl", ("function_decl",), lambda ch, span: ch[0], "function")
        g.add("decl", ("var_decl",), lambda ch, span: ch[0], "global variable")

        g.add(
            "function_decl",
            ("type", IDENT, LPAREN, "params_opt", RPAREN, "block"),
            lambda ch, span: mk(
                FunctionDecl,
                ch,
                span,
                name=ch[1].text,
                return_type=ch[0].text,
                params=ch[3],
                body=ch[5],
            ),
            "function definition",
        )

        g.add("params_opt", (), lambda ch, span: [], "no parameters")
        g.add("params_opt", (KW_VOID,), lambda ch, span: [], "explicit void parameter list")
        g.add("params_opt", ("param_list",), lambda ch, span: ch[0], "parameter list")
        g.add("param_list", ("param",), lambda ch, span: [ch[0]], "one parameter")
        g.add("param_list", ("param_list", COMMA, "param"), lambda ch, span: ch[0] + [ch[2]], "another parameter")
        g.add(
            "param",
            ("type", IDENT),
            lambda ch, span: mk(Param, ch, span, name=ch[1].text, type_name=ch[0].text),
            "parameter",
        )

        for token_kind, type_name in TYPE_KEYWORDS.items():
            g.add("type", (token_kind,), lambda ch, span, name=type_name: ch[0], f"type {type_name}")

        # -- declarations ---------------------------------------------
        g.add(
            "var_decl",
            ("type", "declarator_list", SEMI),
            lambda ch, span: mk(VarDecl, ch, span, type_name=ch[0].text, declarators=ch[1]),
            "declaration",
        )
        g.add("declarator_list", ("declarator",), lambda ch, span: [ch[0]], "one declarator")
        g.add(
            "declarator_list",
            ("declarator_list", COMMA, "declarator"),
            lambda ch, span: ch[0] + [ch[2]],
            "another declarator",
        )
        g.add(
            "declarator",
            (IDENT,),
            lambda ch, span: mk(VarDeclarator, ch, span, name=ch[0].text),
            "plain declarator",
        )
        g.add(
            "declarator",
            (IDENT, ASSIGN, "expr"),
            lambda ch, span: mk(VarDeclarator, ch, span, name=ch[0].text, init=ch[2]),
            "initialised declarator",
        )
        g.add(
            "declarator",
            (IDENT, LBRACKET, INT_LIT, RBRACKET),
            lambda ch, span: mk(VarDeclarator, ch, span, name=ch[0].text, array_size=int(ch[2].value)),
            "array declarator",
        )

        # -- statements ------------------------------------------------
        g.add(
            "block",
            (LBRACE, "stmt_list", RBRACE),
            lambda ch, span: mk(Block, ch, span, statements=ch[1]),
            "block",
        )
        g.add("stmt_list", ("stmt_list", "statement"), lambda ch, span: ch[0] + [ch[1]], "statement sequence")
        g.add("stmt_list", (), lambda ch, span: [], "empty block")

        g.add("statement", ("matched_statement",), lambda ch, span: ch[0], "matched statement")
        g.add("statement", ("open_statement",), lambda ch, span: ch[0], "open statement")

        g.add("matched_statement", ("block",), lambda ch, span: ch[0], "matched block")
        g.add("matched_statement", ("var_decl",), lambda ch, span: ch[0], "matched declaration")
        g.add("matched_statement", ("expr_statement",), lambda ch, span: ch[0], "matched expression statement")
        g.add("matched_statement", ("empty_statement",), lambda ch, span: ch[0], "matched empty statement")
        g.add("matched_statement", ("jump_statement",), lambda ch, span: ch[0], "matched jump")
        g.add(
            "matched_statement",
            (KW_IF, LPAREN, "expr", RPAREN, "matched_statement", KW_ELSE, "matched_statement"),
            lambda ch, span: mk(IfStmt, ch, span, cond=ch[2], then_branch=ch[4], else_branch=ch[6]),
            "if/else (matched)",
        )
        g.add(
            "matched_statement",
            (KW_WHILE, LPAREN, "expr", RPAREN, "matched_statement"),
            lambda ch, span: mk(WhileStmt, ch, span, cond=ch[2], body=ch[4]),
            "while (matched)",
        )
        g.add(
            "matched_statement",
            (KW_FOR, LPAREN, "for_setup", "for_tail", RPAREN, "matched_statement"),
            lambda ch, span: mk(
                ForStmt, ch, span, init=self._for_init(ch[2]), cond=ch[3][0],
                update=self._for_update(ch[3][1]), body=ch[5]
            ),
            "for (matched)",
        )

        g.add(
            "open_statement",
            (KW_IF, LPAREN, "expr", RPAREN, "statement"),
            lambda ch, span: mk(IfStmt, ch, span, cond=ch[2], then_branch=ch[4], else_branch=None),
            "if without else (open)",
        )
        g.add(
            "open_statement",
            (KW_IF, LPAREN, "expr", RPAREN, "matched_statement", KW_ELSE, "open_statement"),
            lambda ch, span: mk(IfStmt, ch, span, cond=ch[2], then_branch=ch[4], else_branch=ch[6]),
            "if/else with open else",
        )
        g.add(
            "open_statement",
            (KW_WHILE, LPAREN, "expr", RPAREN, "open_statement"),
            lambda ch, span: mk(WhileStmt, ch, span, cond=ch[2], body=ch[4]),
            "while (open)",
        )
        g.add(
            "open_statement",
            (KW_FOR, LPAREN, "for_setup", "for_tail", RPAREN, "open_statement"),
            lambda ch, span: mk(
                ForStmt, ch, span, init=self._for_init(ch[2]), cond=ch[3][0],
                update=self._for_update(ch[3][1]), body=ch[5]
            ),
            "for (open)",
        )

        g.add(
            "expr_statement",
            ("expr", SEMI),
            lambda ch, span: mk(ExprStmt, ch, span, expr=ch[0]),
            "expression statement",
        )
        g.add("empty_statement", (SEMI,), lambda ch, span: mk(EmptyStmt, ch, span), "empty statement")
        g.add("jump_statement", (KW_RETURN, SEMI), lambda ch, span: mk(ReturnStmt, ch, span, value=None), "return")
        g.add(
            "jump_statement",
            (KW_RETURN, "expr", SEMI),
            lambda ch, span: mk(ReturnStmt, ch, span, value=ch[1]),
            "return expression",
        )
        g.add("jump_statement", (KW_BREAK, SEMI), lambda ch, span: mk(BreakStmt, ch, span), "break")
        g.add("jump_statement", (KW_CONTINUE, SEMI), lambda ch, span: mk(ContinueStmt, ch, span), "continue")

        # -- for-loop clauses ------------------------------------------
        g.add("for_setup", ("var_decl",), lambda ch, span: ch[0], "for initialisation declaration")
        g.add("for_setup", ("expr_opt", SEMI), lambda ch, span: ch[0], "for initialisation expression")
        g.add(
            "for_tail",
            ("expr_opt", SEMI, "expr_opt"),
            lambda ch, span: (ch[0], ch[2]),
            "for condition/update",
        )
        g.add("expr_opt", (), lambda ch, span: None, "absent expression")
        g.add("expr_opt", ("expr",), lambda ch, span: ch[0], "optional expression")

        # -- expressions ------------------------------------------------
        g.add("expr", ("assign",), lambda ch, span: ch[0], "expression")
        g.add("assign", ("logic_or",), lambda ch, span: ch[0], "plain expression")
        for token_kind, op_text in ASSIGN_OPS.items():
            g.add(
                "assign",
                ("unary", token_kind, "assign"),
                lambda ch, span, op=op_text: mk(Assign, ch, span, op=op, target=ch[0], value=ch[2]),
                f"assignment {op_text}",
            )

        g.add("logic_or", ("logic_and",), lambda ch, span: ch[0], "or operand")
        g.add(
            "logic_or",
            ("logic_or", OROR, "logic_and"),
            lambda ch, span: mk(BinaryOp, ch, span, op="||", left=ch[0], right=ch[2]),
            "logical or",
        )
        g.add("logic_and", ("equality",), lambda ch, span: ch[0], "and operand")
        g.add(
            "logic_and",
            ("logic_and", ANDAND, "equality"),
            lambda ch, span: mk(BinaryOp, ch, span, op="&&", left=ch[0], right=ch[2]),
            "logical and",
        )
        g.add("equality", ("relational",), lambda ch, span: ch[0], "equality operand")
        g.add(
            "equality",
            ("equality", EQ, "relational"),
            lambda ch, span: mk(BinaryOp, ch, span, op="==", left=ch[0], right=ch[2]),
            "equality",
        )
        g.add(
            "equality",
            ("equality", NE, "relational"),
            lambda ch, span: mk(BinaryOp, ch, span, op="!=", left=ch[0], right=ch[2]),
            "inequality",
        )
        g.add("relational", ("additive",), lambda ch, span: ch[0], "relational operand")
        for token_kind, op_text in ((LT, "<"), (LE, "<="), (GT, ">"), (GE, ">=")):
            g.add(
                "relational",
                ("relational", token_kind, "additive"),
                lambda ch, span, op=op_text: mk(BinaryOp, ch, span, op=op, left=ch[0], right=ch[2]),
                f"comparison {op_text}",
            )
        g.add("additive", ("multiplicative",), lambda ch, span: ch[0], "additive operand")
        g.add(
            "additive",
            ("additive", PLUS, "multiplicative"),
            lambda ch, span: mk(BinaryOp, ch, span, op="+", left=ch[0], right=ch[2]),
            "addition",
        )
        g.add(
            "additive",
            ("additive", MINUS, "multiplicative"),
            lambda ch, span: mk(BinaryOp, ch, span, op="-", left=ch[0], right=ch[2]),
            "subtraction",
        )
        g.add("multiplicative", ("unary",), lambda ch, span: ch[0], "multiplicative operand")
        for token_kind, op_text in ((STAR, "*"), (SLASH, "/"), (PERCENT, "%")):
            g.add(
                "multiplicative",
                ("multiplicative", token_kind, "unary"),
                lambda ch, span, op=op_text: mk(BinaryOp, ch, span, op=op, left=ch[0], right=ch[2]),
                f"multiplication {op_text}",
            )

        g.add("unary", ("postfix",), lambda ch, span: ch[0], "unary operand")
        g.add(
            "unary",
            (MINUS, "unary"),
            lambda ch, span: mk(UnaryOp, ch, span, op="-", operand=ch[1], prefix=True),
            "arithmetic negation",
        )
        g.add(
            "unary",
            (NOT, "unary"),
            lambda ch, span: mk(UnaryOp, ch, span, op="!", operand=ch[1], prefix=True),
            "logical negation",
        )
        g.add(
            "unary",
            (INCR, "unary"),
            lambda ch, span: mk(UnaryOp, ch, span, op="++", operand=ch[1], prefix=True),
            "pre-increment",
        )
        g.add(
            "unary",
            (DECR, "unary"),
            lambda ch, span: mk(UnaryOp, ch, span, op="--", operand=ch[1], prefix=True),
            "pre-decrement",
        )

        g.add("postfix", ("primary",), lambda ch, span: ch[0], "primary expression")
        g.add(
            "postfix",
            ("postfix", INCR),
            lambda ch, span: mk(UnaryOp, ch, span, op="++", operand=ch[0], prefix=False),
            "post-increment",
        )
        g.add(
            "postfix",
            ("postfix", DECR),
            lambda ch, span: mk(UnaryOp, ch, span, op="--", operand=ch[0], prefix=False),
            "post-decrement",
        )
        g.add(
            "postfix",
            ("postfix", LBRACKET, "expr", RBRACKET),
            lambda ch, span: mk(Index, ch, span, base=ch[0], index=ch[2]),
            "array element",
        )
        g.add(
            "postfix",
            ("postfix", LPAREN, "args_opt", RPAREN),
            lambda ch, span: self._call(ch[0], ch[2], ch, span),
            "call",
        )
        g.add("args_opt", (), lambda ch, span: [], "no arguments")
        g.add("args_opt", ("arg_list",), lambda ch, span: ch[0], "arguments")
        g.add("arg_list", ("expr",), lambda ch, span: [ch[0]], "one argument")
        g.add("arg_list", ("arg_list", COMMA, "expr"), lambda ch, span: ch[0] + [ch[2]], "another argument")

        g.add("primary", (IDENT,), lambda ch, span: mk(Ident, ch, span, name=ch[0].text), "identifier")
        g.add("primary", (INT_LIT,), lambda ch, span: mk(IntLit, ch, span, value=int(ch[0].value), text=ch[0].text), "integer literal")
        g.add("primary", (FLOAT_LIT,), lambda ch, span: mk(FloatLit, ch, span, value=float(ch[0].value), text=ch[0].text), "float literal")
        g.add("primary", (CHAR_LIT,), lambda ch, span: mk(CharLit, ch, span, value=str(ch[0].value), text=ch[0].text), "character literal")
        g.add("primary", (STRING_LIT,), lambda ch, span: mk(StringLit, ch, span, value=str(ch[0].value), text=ch[0].text), "string literal")
        g.add("primary", (KW_TRUE,), lambda ch, span: mk(BoolLit, ch, span, value=True), "true")
        g.add("primary", (KW_FALSE,), lambda ch, span: mk(BoolLit, ch, span, value=False), "false")
        g.add("primary", (LPAREN, "expr", RPAREN), lambda ch, span: ch[1], "parenthesised expression")

        g.finalize()

    # ------------------------------------------------------------------
    def _call(self, callee: Node, args: List[Node], children, span) -> Call:
        name = callee.name if isinstance(callee, Ident) else "<expression>"
        return self.mk(
            Call,
            [callee, *args],
            span,
            name=name,
            args=args,
            callee=callee if isinstance(callee, Ident) else None,
        )

    def _for_init(self, setup) -> Optional[Node]:
        """Normalise a ``for`` initialiser into a statement.

        A declaration stays a :class:`VarDecl`; a bare expression is wrapped in
        an :class:`ExprStmt` so that every part of a ``for`` header is a
        statement node with its own source span and statement id.
        """
        if setup is None:
            return None
        if isinstance(setup, VarDecl):
            return setup
        if isinstance(setup, Node):
            return self.mk(ExprStmt, [setup], setup.span, expr=setup)
        return None

    def _for_update(self, update) -> Optional[Node]:
        """Normalise the ``for`` update expression into an expression statement."""
        if update is None:
            return None
        return self.mk(ExprStmt, [update], update.span, expr=update)


def build_language_grammar(source: str = "", filename: str = "<source>") -> Grammar:
    """Convenience wrapper returning the CT-C grammar."""
    return LanguageGrammarBuilder(source, filename).grammar


def grammar_documentation() -> List[dict]:
    """Machine-readable grammar listing used by ``/api/grammar`` and the docs."""
    grammar = build_language_grammar()
    return [
        {
            "index": prod.index,
            "lhs": prod.lhs,
            "rhs": list(prod.rhs),
            "display": prod.display(),
            "label": prod.label,
        }
        for prod in grammar.productions
    ]
