"""Security rule model and registry.

A :class:`RuleSet` is the complete, validated rule configuration an analysis
run uses.  It is immutable from the analysis engine's point of view: the taint
engine never mutates it and caches derived lookups on it.

Model overview
--------------
* :class:`SourceRule`  -- a call that *introduces* untrusted data
  (``input()``, ``readenv("X")``, ``argv(1)``).  ``argument``/``returns``
  selects whether the taint originates from an argument or from the result.
* :class:`SinkRule`    -- a call that *consumes* data in a security-sensitive
  way, together with the argument positions that must not receive untrusted
  data and the *context* (command, sql, path, html, numeric, format) that the
  data must be safe for.
* :class:`SanitizerRule` -- a call that neutralises taint **for one context**;
  ``kind`` distinguishes a transformation (``sanitizer``) from a predicate
  (``validator``, which is used as a branch guard).
* :class:`FlowRule`    -- the policy that ties sources, sinks and sanitizers
  together and carries the severity/category reported in findings.

Contexts are deliberately first-class: escaping for SQL does **not** make a
value safe for a shell, and the analysis models that.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: Taint/sanitizer contexts understood by the engine.  ``*`` means "every
#: context" and is only meaningful for sanitizers that destroy the text
#: representation of a value (e.g. parsing it into an integer).
CONTEXTS: Tuple[str, ...] = ("command", "sql", "path", "html", "numeric", "format")
ALL_CONTEXTS = "*"

SEVERITIES: Tuple[str, ...] = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")

#: Severity -> numeric rank, used by the UI's default ordering only.
SEVERITY_RANK = {name: index for index, name in enumerate(reversed(SEVERITIES))}


class RuleError(Exception):
    """Raised when a rule set cannot be built (programming error, not user input)."""


@dataclass(frozen=True)
class Item:
    """One ``key value`` line inside a declaration, with its location."""

    key: str
    value: object
    line: int
    col: int
    raw: str = ""


@dataclass(frozen=True)
class SourceRule:
    id: str
    function: str
    description: str = ""
    argument: Optional[int] = None
    contexts: Tuple[str, ...] = CONTEXTS
    severity: str = "MEDIUM"
    tags: Tuple[str, ...] = ()
    line: int = 0
    col: int = 0
    builtin: bool = False
    source_file: str = "<built-in>"
    #: Rule category, used for grouping in the UI and in reports.
    kind: str = "source"

    @property
    def from_return_value(self) -> bool:
        return self.argument is None

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "kind": "source",
            "function": self.function,
            "description": self.description,
            "argument": self.argument,
            "origin": "return value" if self.from_return_value else f"argument {self.argument}",
            "contexts": list(self.contexts),
            "severity": self.severity,
            "tags": list(self.tags),
            "builtin": self.builtin,
            "line": self.line,
            "col": self.col,
        }


@dataclass(frozen=True)
class SinkRule:
    id: str
    function: str
    arguments: Tuple[int, ...] = (0,)
    context: str = "command"
    description: str = ""
    category: str = "unspecified"
    severity: str = "HIGH"
    tags: Tuple[str, ...] = ()
    line: int = 0
    col: int = 0
    builtin: bool = False
    source_file: str = "<built-in>"

    kind: str = "sink"

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "kind": "sink",
            "function": self.function,
            "description": self.description,
            "arguments": list(self.arguments),
            "context": self.context,
            "category": self.category,
            "severity": self.severity,
            "tags": list(self.tags),
            "builtin": self.builtin,
            "line": self.line,
            "col": self.col,
        }


@dataclass(frozen=True)
class SanitizerRule:
    id: str
    function: str
    kind: str = "sanitizer"  # "sanitizer" | "validator"
    argument: int = 0
    context: str = "command"
    description: str = ""
    tags: Tuple[str, ...] = ()
    line: int = 0
    col: int = 0
    builtin: bool = False
    source_file: str = "<built-in>"

    @property
    def removes_all_contexts(self) -> bool:
        return self.context == ALL_CONTEXTS

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "function": self.function,
            "description": self.description,
            "argument": self.argument,
            "context": self.context,
            "tags": list(self.tags),
            "builtin": self.builtin,
            "line": self.line,
            "col": self.col,
        }


@dataclass(frozen=True)
class FlowRule:
    id: str
    description: str = ""
    severity: str = "HIGH"
    category: str = "unspecified"
    sources: Tuple[str, ...] = ()
    sinks: Tuple[str, ...] = ()
    sanitizers: Tuple[str, ...] = ()
    enabled: bool = True
    line: int = 0
    col: int = 0
    builtin: bool = False
    source_file: str = "<built-in>"

    kind: str = "flow"

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "kind": "flow",
            "description": self.description,
            "severity": self.severity,
            "category": self.category,
            "sources": list(self.sources),
            "sinks": list(self.sinks),
            "sanitizers": list(self.sanitizers),
            "enabled": self.enabled,
            "builtin": self.builtin,
            "line": self.line,
            "col": self.col,
        }


@dataclass
class RuleSet:
    """A validated, self-consistent set of security rules."""

    sources: Dict[str, SourceRule] = field(default_factory=dict)
    sinks: Dict[str, SinkRule] = field(default_factory=dict)
    sanitizers: Dict[str, SanitizerRule] = field(default_factory=dict)
    flows: Dict[str, FlowRule] = field(default_factory=dict)
    origin: str = "built-in rules"

    # -- lookups used by the engine -------------------------------------
    def __post_init__(self) -> None:
        self._by_function_source: Dict[str, List[SourceRule]] = {}
        for rule in self.sources.values():
            self._by_function_source.setdefault(rule.function, []).append(rule)
        self._by_function_sink: Dict[str, List[SinkRule]] = {}
        for rule in self.sinks.values():
            self._by_function_sink.setdefault(rule.function, []).append(rule)
        self._by_function_sanitizer: Dict[str, List[SanitizerRule]] = {}
        for rule in self.sanitizers.values():
            self._by_function_sanitizer.setdefault(rule.function, []).append(rule)

    def source_rules(self, function: str) -> List[SourceRule]:
        return self._by_function_source.get(function, [])

    def sink_rules(self, function: str) -> List[SinkRule]:
        return self._by_function_sink.get(function, [])

    def sanitizer_rules(self, function: str) -> List[SanitizerRule]:
        return self._by_function_sanitizer.get(function, [])

    def flow_for(self, sink_id: str, source_id: str) -> Optional[FlowRule]:
        """The enabled flow that connects ``source_id`` to ``sink_id``."""
        for flow in self.flows.values():
            if not flow.enabled:
                continue
            if sink_id in flow.sinks and source_id in flow.sources:
                return flow
        return None

    def flows_for_sink(self, sink_id: str) -> List[FlowRule]:
        return [f for f in self.flows.values() if f.enabled and sink_id in f.sinks]

    def enabled_flows(self) -> List[FlowRule]:
        return [f for f in self.flows.values() if f.enabled]

    # -- introspection ---------------------------------------------------
    def all_rules(self) -> List[object]:
        return list(self.sources.values()) + list(self.sinks.values()) + list(
            self.sanitizers.values()
        ) + list(self.flows.values())

    def fingerprint(self) -> str:
        payload = json.dumps(
            [
                rule.to_json()
                for rule in sorted(
                    (r for r in self.all_rules()),
                    key=lambda r: (r.__class__.__name__, r.id),
                )
            ],
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

    def version_label(self) -> str:
        """Human-readable rule-set identity, e.g. ``builtin-4f2a91c7``."""
        prefix = "builtin" if self.origin.startswith("built-in") else "custom"
        return f"{prefix}-{self.fingerprint()}"

    def source_ids(self) -> List[str]:
        return sorted(self.sources)

    def stats(self) -> dict:
        return {
            "sources": len(self.sources),
            "sinks": len(self.sinks),
            "sanitizers": len([s for s in self.sanitizers.values() if s.kind == "sanitizer"]),
            "validators": len([s for s in self.sanitizers.values() if s.kind == "validator"]),
            "flows": len(self.flows),
            "enabled_flows": len(self.enabled_flows()),
            "fingerprint": self.fingerprint(),
            "version": self.version_label(),
            "origin": self.origin,
        }

    def to_json(self, include_builtin: bool = True) -> dict:
        rules = [
            rule.to_json()
            for rule in sorted(self.all_rules(), key=lambda r: (r.kind, r.id))  # type: ignore[attr-defined]
            if include_builtin or not rule.builtin  # type: ignore[attr-defined]
        ]
        return {"version": self.version_label(), "stats": self.stats(), "rules": rules}


def merge(primary: RuleSet, secondary: RuleSet) -> RuleSet:
    """Merge two rule sets; rules in ``secondary`` override equal ids."""
    merged = RuleSet(origin=f"{primary.origin} + {secondary.origin}")
    merged.sources.update(primary.sources)
    merged.sources.update(secondary.sources)
    merged.sinks.update(primary.sinks)
    merged.sinks.update(secondary.sinks)
    merged.sanitizers.update(primary.sanitizers)
    merged.sanitizers.update(secondary.sanitizers)
    merged.flows.update(primary.flows)
    merged.flows.update(secondary.flows)
    merged.__post_init__()
    return merged
