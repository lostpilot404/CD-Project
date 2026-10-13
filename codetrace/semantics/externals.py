"""Model of the host environment: known external functions.

CodeTrace analyses a self-contained translation unit, so any call whose target
is not defined in the analysed file is a call into the *environment*.  Rather
than pretending such calls are neutral, CodeTrace keeps an explicit catalogue
of modelled external functions with

* a parameter list and return type (used by the type checker), and
* a **category** that the security rules use as a default model:

  ===========  ==========================================================
  category     meaning
  ===========  ==========================================================
  ``source``   returns attacker-controlled data (stdin, environment, ...)
  ``sink``     performs a security-sensitive operation with its arguments
  ``sanitizer``neutralises taint for one specific context (and only that one)
  ``validator``tests whether a value is acceptable for a context
  ``pure``     computed from its arguments only (taint flows through)
  ``converter``changes the representation (taint is preserved)
  ``unknown``  no model: CodeTrace keeps taint and records uncertainty
  ===========  ==========================================================

Calls to functions that are **not** in this catalogue and **not** defined in
the analysed file are reported as ``SEM008 unknown external function`` and are
modelled conservatively (their return value is tainted if any argument is
tainted).  Nothing is assumed safe by default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

SOURCE = "source"
SINK = "sink"
SANITIZER = "sanitizer"
VALIDATOR = "validator"
PURE = "pure"
CONVERTER = "converter"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExternalFunction:
    name: str
    params: Tuple[str, ...]
    return_type: str
    category: str
    #: Taint context neutralised by a sanitizer/validator (``command``,
    #: ``sql``, ``html``, ``path``, ``numeric``), empty for non-sanitizers.
    context: str = ""
    description: str = ""
    #: Argument indices that are security-sensitive for ``sink`` category.
    sensitive_args: Tuple[int, ...] = ()
    variadic: bool = False

    def signature(self) -> str:
        params = list(self.params)
        if self.variadic:
            params.append("...")
        return f"{self.return_type} {self.name}({', '.join(params) if params else 'void'})"


CATALOG: Tuple[ExternalFunction, ...] = (
    # -- sources ------------------------------------------------------
    ExternalFunction(
        "input", (), "string", SOURCE,
        description="reads one line from standard input (untrusted)",
    ),
    ExternalFunction(
        "input_int", (), "int", SOURCE,
        description="reads one integer from standard input (untrusted)",
    ),
    ExternalFunction(
        "readenv", ("string",), "string", SOURCE,
        description="reads an environment variable (untrusted in most deployments)",
    ),
    ExternalFunction(
        "argv", ("int",), "string", SOURCE,
        description="returns a command-line argument as text (untrusted)",
    ),
    ExternalFunction(
        "argc", (), "int", SOURCE,
        description="number of command-line arguments",
    ),
    # -- sinks --------------------------------------------------------
    ExternalFunction(
        "system", ("string",), "int", SINK,
        sensitive_args=(0,),
        description="executes its argument through the system command interpreter",
    ),
    ExternalFunction(
        "exec", ("string",), "int", SINK,
        sensitive_args=(0,),
        description="executes its argument as an external program",
    ),
    ExternalFunction(
        "popen", ("string",), "int", SINK,
        sensitive_args=(0,),
        description="runs a shell command and returns a handle to its output",
    ),
    ExternalFunction(
        "fopen", ("string", "string"), "int", SINK,
        sensitive_args=(0,),
        description="opens a filesystem path; attacker-controlled paths allow traversal",
    ),
    ExternalFunction(
        "readfile", ("string",), "string", SINK,
        sensitive_args=(0,),
        description="reads a filesystem path; attacker-controlled paths allow traversal",
    ),
    ExternalFunction(
        "writefile", ("string", "string"), "int", SINK,
        sensitive_args=(0,),
        description="writes to a filesystem path (arbitrary file write when uncontrolled)",
    ),
    ExternalFunction(
        "printf", ("string",), "int", SINK, variadic=True,
        sensitive_args=(0,),
        description="interprets its first argument as a format string",
    ),
    ExternalFunction(
        "sql_exec", ("string",), "int", SINK,
        sensitive_args=(0,),
        description="executes its argument as a database query",
    ),
    # -- sanitizers ---------------------------------------------------
    ExternalFunction(
        "shell_escape", ("string",), "string", SANITIZER, context="command",
        description="quotes shell metacharacters; neutralises command taint only",
    ),
    ExternalFunction(
        "sql_escape", ("string",), "string", SANITIZER, context="sql",
        description="escapes SQL metacharacters; neutralises SQL taint only",
    ),
    ExternalFunction(
        "html_escape", ("string",), "string", SANITIZER, context="html",
        description="escapes HTML metacharacters; neutralises HTML taint only",
    ),
    ExternalFunction(
        "path_normalize", ("string",), "string", SANITIZER, context="path",
        description="normalises a path; neutralises path taint only",
    ),
    ExternalFunction(
        "to_int", ("string",), "int", SANITIZER, context="numeric",
        description="parses an integer; the result carries no text-level taint",
    ),
    # -- validators ---------------------------------------------------
    ExternalFunction(
        "is_safe_command", ("string",), "bool", VALIDATOR, context="command",
        description="returns true when its argument is a known-safe command name",
    ),
    ExternalFunction(
        "is_valid_path", ("string",), "bool", VALIDATOR, context="path",
        description="returns true when its argument is an allowed path",
    ),
    # -- pure helpers -------------------------------------------------
    ExternalFunction("strlen", ("string",), "int", PURE, description="string length"),
    ExternalFunction("concat", ("string", "string"), "string", PURE, description="concatenation"),
    ExternalFunction("substr", ("string", "int", "int"), "string", PURE, description="substring"),
    ExternalFunction("print", ("string",), "int", PURE, description="writes to standard output"),
    ExternalFunction("puts", ("string",), "int", PURE, description="writes to standard output"),
    # -- converters ---------------------------------------------------
    ExternalFunction(
        "parse_int", ("string",), "int", CONVERTER,
        description="parses text as an integer without validating it",
    ),
    ExternalFunction("to_string", ("int",), "string", CONVERTER, description="integer to text"),
)

BY_NAME: Dict[str, ExternalFunction] = {fn.name: fn for fn in CATALOG}


def lookup(name: str) -> Optional[ExternalFunction]:
    return BY_NAME.get(name)


def categories(category: str) -> List[ExternalFunction]:
    return [fn for fn in CATALOG if fn.category == category]


def catalog_json() -> List[dict]:
    return [
        {
            "name": fn.name,
            "signature": fn.signature(),
            "params": list(fn.params),
            "return_type": fn.return_type,
            "category": fn.category,
            "context": fn.context,
            "description": fn.description,
            "sensitive_args": list(fn.sensitive_args),
            "variadic": fn.variadic,
        }
        for fn in CATALOG
    ]
