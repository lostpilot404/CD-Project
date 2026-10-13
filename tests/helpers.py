"""Shared helpers for the test suite.

The tests deliberately go through the public entry points (``tokenize``,
``parse_source``, ``analyse_source``) instead of poking at internals, so a test
failure means the observable behaviour changed, not that a private helper was
renamed.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from codetrace.analysis.pipeline import Program, analyse_source  # noqa: E402
from codetrace.frontend.lexer import tokenize  # noqa: E402
from codetrace.frontend.pipeline import parse_source  # noqa: E402

EXAMPLES_DIR = os.path.join(ROOT, "examples")


def example_path(*parts: str) -> str:
    return os.path.join(EXAMPLES_DIR, *parts)


def read_example(*parts: str) -> str:
    with open(example_path(*parts), "r", encoding="utf-8") as handle:
        return handle.read()


def analyse(source: str, filename: str = "<test>", **kwargs) -> Program:
    return analyse_source(source.strip() + "\n", filename=filename, **kwargs)


def analyse_example(*parts: str, **kwargs) -> Program:
    return analyse_source(read_example(*parts), filename=parts[-1], **kwargs)


def parse(source: str, mode: str = "lalr"):
    return parse_source(source, filename="<test>", mode=mode)


def codes(diagnostics) -> List[str]:
    return [diagnostic.code for diagnostic in diagnostics]


def messages(diagnostics) -> str:
    return "; ".join(f"{d.code} {d.line}:{d.col} {d.message}" for d in diagnostics)


def finding_labels(findings) -> List[str]:
    return [f"{f.rule_id}@{f.sink.get('line')}" for f in findings]


def statements_of(program: Program, function: str) -> Dict[int, str]:
    """Statement id -> stripped statement text for one function."""
    result = {}
    for sid, node in program.statements.items():
        if program.function_of_statement(sid) == function:
            result[sid] = program.statement_text(sid).strip()
    return result


def atoms(texts) -> List[str]:
    return sorted(set(texts))
