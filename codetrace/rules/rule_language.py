"""Grammar, parser and validator for the CodeTrace security rule language.

The rule language is a *declarative configuration language*: it can describe
sources, sinks, sanitizers, validators and flows, and it deliberately has **no
expressions, no statements and no way to express computation**.  That property
is what makes it safe to accept rule files from users: there is no construct
that could execute code, and the parser never evaluates anything it reads.

The language is parsed with the same LR(1) machinery as the source language
(:mod:`codetrace.frontend.grammar` and :mod:`codetrace.frontend.clr_parser`),
which is also the reason the syntax is designed to be LALR(1): every item is a
distinct keyword followed by a literal, list or identifier.

Example rule file::

    version 1

    source stdin {
        description "reads standard input"
        function input
        returns
        contexts command, sql, path, html, numeric, format
    }

    sink system_argument_0 {
        description "command execution"
        function system
        arguments 0
        context command
        category "command-injection"
        severity HIGH
    }

    sanitizer shell_escape {
        description "quotes shell metacharacters"
        function shell_escape
        argument 0
        context command
    }

    flow command_execution {
        description "untrusted input reaching command execution"
        severity HIGH
        category "command-injection"
        sources stdin
        sinks system_argument_0
        sanitizers shell_escape
        enabled true
    }
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..frontend.clr_parser import LRParser, ParserTables, build_tables
from ..frontend.grammar import Grammar
from ..frontend.lexer import Diagnostic, tokenize
from ..frontend.source import LineIndex
from ..frontend.tokens import (
    ASSIGN,
    CHAR_LIT,
    COMMA,
    DOT,
    INT_LIT,
    INVALID,
    LBRACE,
    LBRACKET,
    LPAREN,
    MINUS,
    RBRACE,
    RBRACKET,
    RPAREN,
    SEMI,
    STAR,
    STRING_LIT,
    UNSUPPORTED_KW,
)
from .model import (
    ALL_CONTEXTS,
    CONTEXTS,
    SEVERITIES,
    FlowRule,
    Item,
    RuleSet,
    SanitizerRule,
    SinkRule,
    SourceRule,
)

# ----------------------------------------------------------------------
# Rule-language lexer configuration
# ----------------------------------------------------------------------
RULE_KEYWORDS: Dict[str, str] = {
    "version": "KW_VERSION",
    "source": "KW_SOURCE",
    "sink": "KW_SINK",
    "sanitizer": "KW_SANITIZER",
    "validator": "KW_VALIDATOR",
    "flow": "KW_FLOW",
    "description": "KW_DESCRIPTION",
    "function": "KW_FUNCTION",
    "argument": "KW_ARGUMENT",
    "arguments": "KW_ARGUMENTS",
    "context": "KW_CONTEXT",
    "contexts": "KW_CONTEXTS",
    "category": "KW_CATEGORY",
    "severity": "KW_SEVERITY",
    "tags": "KW_TAGS",
    "enabled": "KW_ENABLED",
    "returns": "KW_RETURNS",
    "sources": "KW_SOURCES",
    "sinks": "KW_SINKS",
    "sanitizers": "KW_SANITIZERS",
    "true": "KW_TRUE",
    "false": "KW_FALSE",
}

#: Words that exist in other rule languages / scripting languages and are
#: explicitly rejected, so that a mistaken attempt to express behaviour gets a
#: clear message instead of a generic syntax error.
RULE_UNSUPPORTED_KEYWORDS: Dict[str, str] = {
    "if": "the rule language has no conditionals: rules are declarative only",
    "else": "the rule language has no conditionals: rules are declarative only",
    "for": "the rule language has no loops: rules are declarative only",
    "while": "the rule language has no loops: rules are declarative only",
    "def": "the rule language cannot contain code; use 'function NAME' to bind a rule to a call",
    "lambda": "the rule language cannot contain code",
    "class": "the rule language has no classes",
    "let": "the rule language has no variables",
    "var": "the rule language has no variables",
    "return": "the rule language cannot contain code",
}


# ----------------------------------------------------------------------
# Grammar
# ----------------------------------------------------------------------
class _RuleGrammarBuilder:
    def __init__(self) -> None:
        self.grammar = Grammar("rule_file")
        self._build()

    def _build(self) -> None:
        g = self.grammar
        g.add("rule_file", ("decl_list",), lambda ch, span: ch[0], "rule file")
        g.add("decl_list", ("decl_list", "decl"), lambda ch, span: ch[0] + [ch[1]], "declarations")
        g.add("decl_list", (), lambda ch, span: [], "empty rule file")

        g.add("decl", ("KW_VERSION", INT_LIT), lambda ch, span: self._version(ch, span), "version")
        for keyword in ("KW_SOURCE", "KW_SINK", "KW_SANITIZER", "KW_VALIDATOR", "KW_FLOW"):
            g.add(
                "decl",
                (keyword, "IDENT", LBRACE, "item_list", RBRACE),
                lambda ch, span, kw=keyword: {
                    "kind": kw,
                    "id": ch[1].text,
                    "items": ch[3],
                    "span": span,
                    "line": ch[1].line,
                    "col": ch[1].col,
                },
                f"declaration {keyword}",
            )

        g.add("item_list", ("item_list", "item"), lambda ch, span: ch[0] + [ch[1]], "items")
        g.add("item_list", (), lambda ch, span: [], "no items")

        g.add("item", ("KW_FUNCTION", "IDENT"), lambda ch, span: self._item("function", ch[1].text, ch, span), "function item")
        g.add("item", ("KW_ARGUMENT", "signed_int"), lambda ch, span: self._item("argument", ch[1], ch, span), "argument item")
        g.add("item", ("KW_ARGUMENTS", "int_list"), lambda ch, span: self._item("arguments", ch[1], ch, span), "arguments item")
        g.add("item", ("KW_CONTEXT", "context_value"), lambda ch, span: self._item("context", ch[1], ch, span), "context item")
        g.add("item", ("KW_CONTEXTS", "context_list"), lambda ch, span: self._item("contexts", ch[1], ch, span), "contexts item")
        g.add("item", ("KW_DESCRIPTION", STRING_LIT), lambda ch, span: self._item("description", ch[1].value, ch, span), "description item")
        g.add("item", ("KW_CATEGORY", STRING_LIT), lambda ch, span: self._item("category", ch[1].value, ch, span), "category item")
        g.add("item", ("KW_SEVERITY", "IDENT"), lambda ch, span: self._item("severity", ch[1].text, ch, span), "severity item")
        g.add("item", ("KW_TAGS", "tag_list"), lambda ch, span: self._item("tags", ch[1], ch, span), "tags item")
        g.add("item", ("KW_RETURNS",), lambda ch, span: self._item("returns", True, ch, span), "returns item")
        g.add("item", ("KW_ENABLED", "bool_value"), lambda ch, span: self._item("enabled", ch[1], ch, span), "enabled item")
        g.add("item", ("KW_SOURCES", "id_list"), lambda ch, span: self._item("sources", ch[1], ch, span), "sources item")
        g.add("item", ("KW_SINKS", "id_list"), lambda ch, span: self._item("sinks", ch[1], ch, span), "sinks item")
        g.add("item", ("KW_SANITIZERS", "id_list"), lambda ch, span: self._item("sanitizers", ch[1], ch, span), "sanitizers item")

        # Argument indices may be written with a sign so that a negative index is
        # reported by the semantic validator (RULE012) with a line:col and an
        # explanation, instead of failing inside the parser with "unexpected -".
        g.add("signed_int", (INT_LIT,), lambda ch, span: int(ch[0].value), "index")
        g.add("signed_int", (MINUS, INT_LIT), lambda ch, span: -int(ch[1].value), "negative index")
        g.add("int_list", ("signed_int",), lambda ch, span: [ch[0]], "one index")
        g.add("int_list", ("int_list", COMMA, "signed_int"), lambda ch, span: ch[0] + [ch[2]], "more indices")
        g.add("context_value", ("IDENT",), lambda ch, span: ch[0].text, "context name")
        g.add("context_value", (STAR,), lambda ch, span: ALL_CONTEXTS, "wildcard context")
        g.add("context_list", ("context_value",), lambda ch, span: [ch[0]], "one context")
        g.add("context_list", ("context_list", COMMA, "context_value"), lambda ch, span: ch[0] + [ch[2]], "more contexts")
        g.add("id_list", ("IDENT",), lambda ch, span: [ch[0].text], "one identifier")
        g.add("id_list", ("id_list", COMMA, "IDENT"), lambda ch, span: ch[0] + [ch[2].text], "more identifiers")
        g.add("tag_list", (STRING_LIT,), lambda ch, span: [ch[0].value], "one tag")
        g.add("tag_list", ("tag_list", COMMA, STRING_LIT), lambda ch, span: ch[0] + [ch[2].value], "more tags")
        g.add("bool_value", ("KW_TRUE",), lambda ch, span: True, "true")
        g.add("bool_value", ("KW_FALSE",), lambda ch, span: False, "false")
        g.finalize()

    def _version(self, ch, span) -> dict:
        return {
            "kind": "KW_VERSION",
            "id": "version",
            "items": [Item("version", int(ch[1].value), ch[1].line, ch[1].col, ch[1].text)],
            "span": span,
            "line": ch[0].line,
            "col": ch[0].col,
        }

    def _item(self, key: str, value, ch, span) -> Item:
        token = next((c for c in ch if hasattr(c, "line")), None)
        return Item(
            key=key,
            value=value,
            line=token.line if token else 0,
            col=token.col if token else 0,
            raw=" ".join(str(getattr(c, "text", c)) for c in ch if hasattr(c, "text")),
        )


_rule_tables: Optional[ParserTables] = None


def rule_tables() -> ParserTables:
    """Parser tables for the rule language (built once, cached in memory)."""
    global _rule_tables
    if _rule_tables is None:
        grammar = _RuleGrammarBuilder().grammar
        _rule_tables = build_tables(grammar, mode="lalr")
    return _rule_tables


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------
@dataclass
class RuleParseResult:
    declarations: List[dict] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)
    accepted: bool = False
    parse_seconds: float = 0.0
    tokens: int = 0

    @property
    def errors(self) -> List[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]


def parse_rule_text(text: str, filename: str = "<rules>") -> RuleParseResult:
    started = time.perf_counter()
    lex = tokenize(
        text,
        filename,
        keywords=RULE_KEYWORDS,
        unsupported_keywords=RULE_UNSUPPORTED_KEYWORDS,
        language="rule",
        hash_comments=True,
    )
    tables = rule_tables()
    parser = LRParser(tables, max_errors=25)
    result = parser.parse(lex.tokens, text)
    diagnostics = list(lex.diagnostics) + list(result.diagnostics)
    declarations: List[dict] = []
    if result.tree is not None:
        index = LineIndex(text)
        declarations = result.tree if isinstance(result.tree, list) else []
        for decl in declarations:
            marker = index.position(decl["span"][0])
            decl["line"], decl["col"] = marker
    return RuleParseResult(
        declarations=declarations,
        diagnostics=diagnostics,
        accepted=result.accepted,
        parse_seconds=round(time.perf_counter() - started, 6),
        tokens=len(lex.tokens),
    )


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------
#: Which item keys are meaningful for which declaration kind.
ALLOWED_ITEMS: Dict[str, set] = {
    "KW_SOURCE": {"function", "argument", "returns", "contexts", "description", "severity", "tags"},
    "KW_SINK": {"function", "argument", "arguments", "context", "description", "category", "severity", "tags"},
    "KW_SANITIZER": {"function", "argument", "context", "description", "tags"},
    "KW_VALIDATOR": {"function", "argument", "context", "description", "tags"},
    "KW_FLOW": {"description", "severity", "category", "sources", "sinks", "sanitizers", "enabled", "tags"},
    "KW_VERSION": {"version"},
}

#: Item keys that must be present for a declaration to be usable.
REQUIRED_ITEMS: Dict[str, set] = {
    "KW_SOURCE": {"function"},
    "KW_SINK": {"function"},
    "KW_SANITIZER": {"function"},
    "KW_VALIDATOR": {"function"},
    "KW_FLOW": set(),
}

SUPPORTED_VERSIONS = (1,)


def _diag(
    severity: str,
    code: str,
    message: str,
    line: int,
    col: int,
    detail: str = "",
    phase: str = "rule-validator",
) -> Diagnostic:
    return Diagnostic(
        severity=severity,
        code=code,
        message=message,
        line=line,
        col=col,
        offset=0,
        end_offset=0,
        phase=phase,
        detail=detail,
    )


def _value(items: Dict[str, Item], key: str, default):
    """Value of an optional item, or ``default`` when the item is absent."""
    item = items.get(key)
    return default if item is None else item.value


def _is_identifier(name: str) -> bool:
    if not name:
        return False
    if not (name[0].islower() or name[0] == "_"):
        return False
    return all(ch.isalnum() or ch == "_" for ch in name)


def validate_declarations(
    declarations: Sequence[dict], origin: str = "custom rules", builtin: bool = False
) -> Tuple[RuleSet, List[Diagnostic]]:
    """Turn parsed declarations into a :class:`RuleSet`, reporting every problem.

    Validation is complete before the rule set is used: a rule set with errors
    is never handed to the analysis engine.
    """
    diagnostics: List[Diagnostic] = []
    rule_set = RuleSet(origin=origin)
    seen_ids: Dict[str, Tuple[str, int]] = {}
    versions: List[int] = []

    # -- pass 1: structural validation ---------------------------------
    for decl in declarations:
        kind = decl["kind"]
        identifier = decl["id"]
        line, col = decl.get("line", 0), decl.get("col", 0)
        if kind == "KW_VERSION":
            for item in decl["items"]:
                if item.value not in SUPPORTED_VERSIONS:
                    diagnostics.append(
                        _diag(
                            "error", "RULE006",
                            f"unsupported rule language version {item.value}; "
                            f"supported: {', '.join(str(v) for v in SUPPORTED_VERSIONS)}",
                            item.line, item.col,
                        )
                    )
                else:
                    versions.append(int(item.value))
            continue

        if not _is_identifier(identifier):
            diagnostics.append(
                _diag(
                    "error", "RULE002",
                    f"invalid rule identifier '{identifier}'",
                    line, col,
                    detail="identifiers must start with a lowercase letter or '_' and contain only "
                    "lowercase letters, digits and '_'",
                )
            )
            continue
        if identifier in seen_ids:
            previous_kind, previous_line = seen_ids[identifier]
            diagnostics.append(
                _diag(
                    "error", "RULE003",
                    f"duplicate rule identifier '{identifier}'",
                    line, col,
                    detail=f"already declared as {previous_kind} at line {previous_line}",
                )
            )
            continue
        seen_ids[identifier] = (kind.replace("KW_", "").lower(), line)

        allowed = ALLOWED_ITEMS.get(kind, set())
        keys: Dict[str, Item] = {}
        for item in decl["items"]:
            if item.key not in allowed:
                diagnostics.append(
                    _diag(
                        "error", "RULE004",
                        f"'{item.key}' is not allowed inside a {kind.replace('KW_', '').lower()} declaration",
                        item.line, item.col,
                        detail=f"allowed items: {', '.join(sorted(allowed))}",
                    )
                )
                continue
            if item.key in keys:
                diagnostics.append(
                    _diag(
                        "error", "RULE005",
                        f"'{item.key}' is specified more than once",
                        item.line, item.col,
                        detail=f"first specified at line {keys[item.key].line}",
                    )
                )
                continue
            keys[item.key] = item

        for required in REQUIRED_ITEMS.get(kind, set()):
            if required not in keys:
                diagnostics.append(
                    _diag(
                        "error", "RULE007",
                        f"missing required item '{required}' in {kind.replace('KW_', '').lower()} "
                        f"declaration '{identifier}'",
                        line, col,
                    )
                )

        # argument vs returns for sources
        if kind == "KW_SOURCE" and "argument" in keys and "returns" in keys:
            diagnostics.append(
                _diag(
                    "error", "RULE008",
                    "a source cannot both read an argument and return a tainted value",
                    keys["returns"].line, keys["returns"].col,
                )
            )
        if kind == "KW_SINK" and "argument" in keys and "arguments" in keys:
            diagnostics.append(
                _diag(
                    "error", "RULE008",
                    "use either 'argument' or 'arguments', not both",
                    keys["arguments"].line, keys["arguments"].col,
                )
            )

        # contexts and severities
        for key in ("context", "contexts"):
            if key not in keys:
                continue
            values = keys[key].value
            values = values if isinstance(values, list) else [values]
            for value in values:
                if value == ALL_CONTEXTS:
                    if kind not in ("KW_SANITIZER", "KW_VALIDATOR"):
                        diagnostics.append(
                            _diag(
                                "error", "RULE009",
                                "'*' (all contexts) is only meaningful for sanitizers and validators",
                                keys[key].line, keys[key].col,
                            )
                        )
                    continue
                if value not in CONTEXTS:
                    diagnostics.append(
                        _diag(
                            "error", "RULE010",
                            f"unknown context '{value}'",
                            keys[key].line, keys[key].col,
                            detail=f"known contexts: {', '.join(CONTEXTS)}, or '*'",
                        )
                    )
        if "severity" in keys:
            value = str(keys["severity"].value)
            if value not in SEVERITIES:
                diagnostics.append(
                    _diag(
                        "error", "RULE011",
                        f"unknown severity '{value}'",
                        keys["severity"].line, keys["severity"].col,
                        detail=f"known severities: {', '.join(SEVERITIES)}",
                    )
                )
        if "argument" in keys and int(keys["argument"].value) < 0:
            diagnostics.append(
                _diag(
                    "error", "RULE012",
                    "'argument' must be a non-negative index",
                    keys["argument"].line, keys["argument"].col,
                )
            )
        if "arguments" in keys:
            negative = [index for index in keys["arguments"].value if int(index) < 0]
            if negative:
                # A negative index can never match a call argument, so the rule
                # would silently never fire: reject it instead.
                diagnostics.append(
                    _diag(
                        "error", "RULE012",
                        f"'arguments' must list non-negative indices, got {', '.join(str(i) for i in negative)}",
                        keys["arguments"].line, keys["arguments"].col,
                    )
                )

    # -- pass 2: build rules --------------------------------------------
    for decl in declarations:
        kind = decl["kind"]
        identifier = decl["id"]
        if kind == "KW_VERSION" or identifier not in seen_ids:
            continue
        items = {item.key: item for item in decl["items"]}
        line, col = decl.get("line", 0), decl.get("col", 0)
        if any(item.key not in ALLOWED_ITEMS.get(kind, set()) for item in decl["items"]):
            continue  # structural errors already reported
        if any(required not in items for required in REQUIRED_ITEMS.get(kind, set())):
            continue

        if kind == "KW_SOURCE":
            argument = int(items["argument"].value) if "argument" in items else None
            rule_set.sources[identifier] = SourceRule(
                id=identifier,
                function=str(items["function"].value),
                description=str(_value(items, "description", "")),
                argument=argument,
                contexts=tuple(items["contexts"].value) if "contexts" in items else CONTEXTS,
                severity=str(_value(items, "severity", "MEDIUM")),
                tags=tuple(_value(items, "tags", [])),
                line=line,
                col=col,
                builtin=builtin,
            )
        elif kind == "KW_SINK":
            if "arguments" in items:
                arguments = tuple(int(v) for v in items["arguments"].value)
            elif "argument" in items:
                arguments = (int(items["argument"].value),)
            else:
                arguments = (0,)
            rule_set.sinks[identifier] = SinkRule(
                id=identifier,
                function=str(items["function"].value),
                arguments=arguments,
                context=str(_value(items, "context", "command")),
                description=str(_value(items, "description", "")),
                category=str(_value(items, "category", "unspecified")),
                severity=str(_value(items, "severity", "HIGH")),
                tags=tuple(_value(items, "tags", [])),
                line=line,
                col=col,
                builtin=builtin,
            )
        elif kind in ("KW_SANITIZER", "KW_VALIDATOR"):
            rule_set.sanitizers[identifier] = SanitizerRule(
                id=identifier,
                function=str(items["function"].value),
                kind="sanitizer" if kind == "KW_SANITIZER" else "validator",
                argument=int(items["argument"].value) if "argument" in items else 0,
                context=str(_value(items, "context", "command")),
                description=str(_value(items, "description", "")),
                tags=tuple(_value(items, "tags", [])),
                line=line,
                col=col,
                builtin=builtin,
            )
        elif kind == "KW_FLOW":
            rule_set.flows[identifier] = FlowRule(
                id=identifier,
                description=str(_value(items, "description", "")),
                severity=str(_value(items, "severity", "HIGH")),
                category=str(_value(items, "category", "unspecified")),
                sources=tuple(_value(items, "sources", [])),
                sinks=tuple(_value(items, "sinks", [])),
                sanitizers=tuple(_value(items, "sanitizers", [])),
                enabled=bool(items["enabled"].value) if "enabled" in items else True,
                line=line,
                col=col,
                builtin=builtin,
            )

    # -- pass 3: cross references ---------------------------------------
    for flow in rule_set.flows.values():
        for source_id in flow.sources:
            if source_id not in rule_set.sources:
                diagnostics.append(
                    _diag(
                        "error", "RULE020",
                        f"flow '{flow.id}' references unknown source '{source_id}'",
                        flow.line, flow.col,
                        detail=f"known sources: {', '.join(sorted(rule_set.sources)) or 'none'}",
                    )
                )
        for sink_id in flow.sinks:
            if sink_id not in rule_set.sinks:
                diagnostics.append(
                    _diag(
                        "error", "RULE021",
                        f"flow '{flow.id}' references unknown sink '{sink_id}'",
                        flow.line, flow.col,
                        detail=f"known sinks: {', '.join(sorted(rule_set.sinks)) or 'none'}",
                    )
                )
        for sanitizer_id in flow.sanitizers:
            if sanitizer_id not in rule_set.sanitizers:
                diagnostics.append(
                    _diag(
                        "error", "RULE022",
                        f"flow '{flow.id}' references unknown sanitizer '{sanitizer_id}'",
                        flow.line, flow.col,
                        detail=f"known sanitizers: {', '.join(sorted(rule_set.sanitizers)) or 'none'}",
                    )
                )
        if not flow.sources:
            diagnostics.append(
                _diag("error", "RULE023", f"flow '{flow.id}' declares no sources", flow.line, flow.col)
            )
        if not flow.sinks:
            diagnostics.append(
                _diag("error", "RULE024", f"flow '{flow.id}' declares no sinks", flow.line, flow.col)
            )

    # A flow that connects a source to a sink whose context the source does not
    # declare cannot report anything: the source's values are never tagged with
    # that context, so the context-based match at the sink fails.  This is a
    # warning rather than an error because the rule file is still consistent,
    # but it is almost always a mistake in the rule, not in the program.
    for flow in rule_set.flows.values():
        for source_id in flow.sources:
            source = rule_set.sources.get(source_id)
            if source is None:
                continue
            for sink_id in flow.sinks:
                sink = rule_set.sinks.get(sink_id)
                if sink is None or sink.context in source.contexts:
                    continue
                diagnostics.append(
                    _diag(
                        "warning", "RULE026",
                        f"flow '{flow.id}' connects source '{source_id}' to sink '{sink_id}', but "
                        f"source '{source_id}' does not declare the '{sink.context}' context, so "
                        f"values of this source can never be reported at that sink",
                        flow.line, flow.col,
                        detail=f"source '{source_id}' declares contexts: "
                               f"{', '.join(source.contexts) or 'none'}",
                    )
                )

    # Functions bound to more than one rule of the same kind are ambiguous.
    for kind_name, collection in (("source", rule_set.sources), ("sink", rule_set.sinks), ("sanitizer", rule_set.sanitizers)):
        by_function: Dict[str, List[str]] = {}
        for rule in collection.values():
            by_function.setdefault(rule.function, []).append(rule.id)
        for function, ids in by_function.items():
            if len(ids) > 1:
                rule = collection[ids[1]]
                diagnostics.append(
                    _diag(
                        "error", "RULE025",
                        f"function '{function}' is bound to more than one {kind_name} rule: {', '.join(sorted(ids))}",
                        rule.line, rule.col,
                    )
                )

    if not versions and declarations:
        diagnostics.append(
            _diag(
                "warning", "RULE001",
                "rule file does not declare a version; assuming version 1",
                1, 1,
            )
        )
    errors = [d for d in diagnostics if d.severity == "error"]
    if errors:
        # A rule set with errors is never used.
        return RuleSet(origin=origin), diagnostics
    rule_set.__post_init__()
    return rule_set, diagnostics


def parse_and_validate(text: str, filename: str = "<rules>", origin: str = "custom rules",
                       builtin: bool = False) -> Tuple[RuleSet, List[Diagnostic], RuleParseResult]:
    """Full rule-file pipeline: lex, parse, validate."""
    parsed = parse_rule_text(text, filename)
    if parsed.errors:
        return RuleSet(origin=origin), list(parsed.diagnostics), parsed
    rule_set, diagnostics = validate_declarations(parsed.declarations, origin=origin, builtin=builtin)
    return rule_set, list(parsed.diagnostics) + diagnostics, parsed


# ----------------------------------------------------------------------
# Built-in rules
# ----------------------------------------------------------------------
BUILTIN_RULE_PATH = os.path.join(os.path.dirname(__file__), "builtin", "standard.ctrule")


def load_builtin_rules(path: str = BUILTIN_RULE_PATH) -> Tuple[RuleSet, List[Diagnostic]]:
    """Load the built-in rule file written in the rule language itself."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:  # pragma: no cover - packaging error
        raise RuntimeError(f"built-in rule file is missing: {path}") from exc
    rule_set, diagnostics, _parsed = parse_and_validate(
        text, filename=os.path.basename(path), origin="built-in rules", builtin=True
    )
    errors = [d for d in diagnostics if d.severity == "error"]
    if errors:
        raise RuntimeError(
            "built-in rule file failed validation: "
            + "; ".join(f"{d.code} line {d.line}: {d.message}" for d in errors)
        )
    return rule_set, diagnostics
