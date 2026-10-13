"""Finding construction and path explanation.

Two responsibilities live here:

``PathExplainer``
    Reconstructs **why** data is tainted at a program point.  The explanation
    is not a guess: every hop is justified by a concrete analysis result --
    reaching definitions say which write supplied a value, the taint state says
    which atom was present, the call graph and function summaries say how a
    value crossed a function boundary, and the rule set says which sanitizer
    (if any) was applied.

``build_findings``
    Turns raw sink hits produced by the taint engine into :class:`Finding`
    objects: it applies the configured flows as the reporting policy, computes
    the path, the certainty, the limitations, the remediation hint and the
    stable identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..version import ENGINE_VERSION
from ..analysis.cfg import PROGRAM_START_SID, DECL_INIT, DECL_UNINIT, GLOBAL_INIT, GLOBAL_UNINIT, PARAMETER
from ..analysis.taint import ALL_CONTEXTS, SinkHit, atom_context, atom_origin
from ..analysis.dependencies import ControlDep, control_dependencies
from ..frontend.ast_nodes import (
    Assign,
    BinaryOp,
    Call,
    ExprStmt,
    ForStmt,
    Ident,
    Index,
    Node,
    ReturnStmt,
    UnaryOp,
    VarDecl,
)
from .models import (
    APPROXIMATE,
    CONFIRMED,
    HIGH,
    LOW,
    MEDIUM,
    UNPROVEN,
    Finding,
    stable_finding_id,
)

MAX_DEPTH = 14

REMEDIATION = {
    "command-injection": (
        "Do not build a command from untrusted input. Prefer a fixed program path with arguments "
        "passed as separate values; if a shell string is unavoidable, escape the value for the "
        "command context (for example with the 'shell_escape' rule) and re-run the analysis to "
        "confirm the flow disappears."
    ),
    "sql-injection": (
        "Use parameterised queries instead of building SQL text from untrusted input. If text "
        "concatenation is unavoidable, escape it for the SQL context with the 'sql_escape' rule."
    ),
    "path-traversal": (
        "Resolve the path against a fixed base directory, reject '..' components after "
        "normalisation (the 'path_normalize' rule models this) and verify the result stays inside "
        "the permitted directory."
    ),
    "arbitrary-file-write": (
        "Never derive the destination of a write from untrusted input. Use a fixed set of "
        "permitted paths or normalise and validate the value, then re-run the analysis."
    ),
    "format-string": (
        "Never pass untrusted data as the format string; use a constant format such as "
        "'printf(\"%s\", value)' and pass the data as an argument."
    ),
}

DEFAULT_REMEDIATION = (
    "Validate or neutralise the value before it reaches this operation, and re-run the analysis "
    "to confirm that the reported flow no longer exists."
)


@dataclass
class TraceStep:
    kind: str
    sid: int
    function: str
    line: int = 0
    col: int = 0
    symbol: str = ""
    label: str = ""
    detail: str = ""
    atoms: Tuple[str, ...] = ()
    from_sid: int = -1
    #: The context the step's construct was declared for, when it has one (a
    #: sanitizer rule declares the context it neutralises).
    context: str = ""

    def to_json(self) -> dict:
        return {
            "kind": self.kind,
            "sid": self.sid,
            "function": self.function,
            "line": self.line,
            "col": self.col,
            "symbol": self.symbol,
            "label": self.label,
            "detail": self.detail,
            "atoms": list(self.atoms),
            "from_sid": self.from_sid,
            "context": self.context,
        }


class PathExplainer:
    """Reconstructs source-to-sink explanations from analysis results."""

    def __init__(self, program) -> None:
        self.program = program
        self._call_sites: Dict[str, List] = {}
        for function, run in program.taint.runs.items():
            for call in run.call_sites:
                self._call_sites.setdefault(call.callee, []).append(call)

    # -- state helpers ---------------------------------------------------
    def _problem(self, function: str):
        return self.program.taint.problems.get(function)

    def _state_in(self, function: str, sid: int) -> int:
        run = self.program.taint.runs.get(function)
        if run is None:
            return 0
        return run.statement_in.get(sid, 0)

    def _eval(self, function: str, sid: int, expr: Optional[Node]) -> int:
        problem = self._problem(function)
        if problem is None or expr is None:
            return 0
        return self.program.taint_engine_eval(function, expr, self._state_in(function, sid)) if hasattr(
            self.program, "taint_engine_eval"
        ) else problem.engine.eval_expr(problem, expr, self._state_in(function, sid), None)

    def _has_atom(self, function: str, sid: int, expr: Optional[Node], atom: str) -> bool:
        problem = self._problem(function)
        if problem is None or expr is None:
            return False
        mask = self._eval(function, sid, expr)
        return atom in problem.atom_texts(mask)

    def _statement_location(self, function: str, sid: int) -> Tuple[int, int]:
        node = self.program.statements.get(sid)
        if node is None:
            return (0, 0)
        return (node.line, node.col)

    # -- public ----------------------------------------------------------
    def explain(self, hit: SinkHit, atom: str) -> List[TraceStep]:
        """Ordered trace: source first, sink last."""
        problem = self._problem(hit.function)
        if problem is None:
            return []
        sink_step = TraceStep(
            kind="sink",
            sid=hit.sid,
            function=hit.function,
            line=getattr(hit.expression, "line", 0),
            col=getattr(hit.expression, "col", 0),
            symbol=self._expression_label(hit.expression),
            label=(
                f"{hit.rule.function}() argument {hit.argument_index} consumes data that is "
                f"not safe for context '{hit.rule.context}'"
            ),
            detail=(
                f"sink rule '{hit.rule.id}' ({hit.rule.description or hit.rule.category}) "
                f"matched by the taint engine"
            ),
            atoms=(atom,),
        )
        prefix = self._trace_expression(
            hit.function, hit.sid, hit.expression, atom, frozenset(), 0
        )
        return prefix + [sink_step]

    # -- tracing ---------------------------------------------------------
    def _trace_symbol(
        self, function: str, sid: int, symbol_id: int, atom: str, visiting: frozenset, depth: int
    ) -> List[TraceStep]:
        key = (function, sid, symbol_id, "symbol", atom)
        if key in visiting or depth > MAX_DEPTH:
            return []
        visiting = visiting | {key}
        analysis = self.program.analyses.get(function)
        if analysis is None:
            return []
        symbol = self.program.semantic.symbols.get(symbol_id)
        steps: List[TraceStep] = []
        definitions = analysis.reaching.definitions_reaching(
            analysis.reaching_states, sid, symbol_id
        )
        if definitions:
            # Several writes can reach this statement (for example one per
            # branch).  A write that cannot have supplied the tainted value --
            # a clean assignment such as ``cmd = "ls"`` -- is not part of the
            # explanation, and following it would end in a spurious
            # "unresolved" step that understates the finding.
            explanatory = [d for d in definitions if self._explains(d, atom)]
            if explanatory:
                definitions = explanatory
        if not definitions:
            return [
                TraceStep(
                    kind="unresolved",
                    sid=sid,
                    function=function,
                    line=self._statement_location(function, sid)[0],
                    col=self._statement_location(function, sid)[1],
                    symbol=symbol.name if symbol else "",
                    label=f"no definition of '{symbol.name if symbol else symbol_id}' reaches this statement",
                    detail="the reaching-definitions analysis found no write that could supply "
                    "this value; the origin of the taint could not be established",
                )
            ]
        for definition in definitions:
            steps.extend(self._trace_definition(definition, atom, visiting, depth + 1))
        return steps

    @staticmethod
    def _trace_rank(steps: List[TraceStep]) -> Tuple[bool, int]:
        """Rank a candidate trace: one that reaches a source beats a longer one
        that does not, and among equals the more complete trace wins."""
        return (any(step.kind == "source" for step in steps), len(steps))

    def _explains(self, definition, atom: str) -> bool:
        """True when this write can have produced the tainted value.

        A parameter or a file-scope variable carries the value in from outside
        the function, so it always qualifies.  A plain write qualifies when the
        value it stores contains the atom, or when the symbol already carried
        the atom before the write (loop-carried taint).
        """
        if definition.kind in (PARAMETER, GLOBAL_INIT, GLOBAL_UNINIT):
            return True
        problem = self._problem(definition.function)
        if problem is None:
            return False
        state = problem.statement_in.get(definition.sid, 0)
        if atom in problem.atom_texts(problem.get(state, definition.symbol_id)):
            return True
        statement = self.program.statements.get(definition.sid)
        if statement is None:
            return False
        rhs = self._written_expression(statement, definition.symbol_id)
        if rhs is None:
            return False
        return self._has_atom(definition.function, definition.sid, rhs, atom)

    def _trace_definition(self, definition, atom: str, visiting: frozenset, depth: int) -> List[TraceStep]:
        function = definition.function
        sid = definition.sid
        line, col = definition.line, definition.col
        if definition.kind == PARAMETER:
            step = TraceStep(
                kind="parameter",
                sid=sid,
                function=function,
                line=line,
                col=col,
                symbol=definition.symbol_name,
                label=f"'{definition.symbol_name}' is a parameter of {function}()",
                detail="the value enters this function through its parameter list",
                atoms=(atom,),
            )
            return self._trace_parameter(definition, atom, visiting, depth + 1) + [step]
        if definition.kind in (GLOBAL_INIT, GLOBAL_UNINIT):
            step = TraceStep(
                kind="global",
                sid=sid,
                function=function,
                line=line,
                col=col,
                symbol=definition.symbol_name,
                label=f"file-scope variable '{definition.symbol_name}'",
                detail="the value is stored in a file-scope variable, which is visible to every function",
                atoms=(atom,),
            )
            return self._trace_global(definition, atom, visiting, depth + 1) + [step]

        statement = self.program.statements.get(sid)
        if statement is None:
            return []
        kind = "declaration" if definition.kind in (DECL_INIT, DECL_UNINIT) else "assignment"
        rhs = self._written_expression(statement, definition.symbol_id)
        step = TraceStep(
            kind=kind,
            sid=sid,
            function=function,
            line=statement.line,
            col=statement.col,
            symbol=definition.symbol_name,
            label=f"'{definition.symbol_name}' is assigned a tainted value at line {statement.line}",
            detail=definition.describe(),
            atoms=(atom,),
        )
        if rhs is None:
            return [step]
        if self._has_atom(function, sid, rhs, atom):
            return self._trace_expression(function, sid, rhs, atom, visiting, depth + 1) + [step]
        # The taint arrived from a previous iteration of a loop (or from a
        # value that is not re-derived here): continue from the incoming state.
        return self._trace_symbol(function, sid, definition.symbol_id, atom, visiting, depth + 1) + [step]

    def _trace_parameter(self, definition, atom: str, visiting: frozenset, depth: int) -> List[TraceStep]:
        steps: List[TraceStep] = []
        problem = self._problem(definition.function)
        declaration = self.program.functions.get(definition.function)
        if declaration is None or problem is None:
            return steps
        index = None
        for position, param in enumerate(declaration.params):
            if param.symbol_id == definition.symbol_id:
                index = position
                break
        if index is None:
            return steps
        found = False
        candidates: List[Tuple[TraceStep, List[TraceStep]]] = []
        for call in self._call_sites.get(definition.function, []):
            if index >= len(call.argument_atoms):
                continue
            if atom not in call.argument_atoms[index]:
                continue
            found = True
            argument = call.node.args[index] if index < len(call.node.args) else None
            step = TraceStep(
                kind="argument",
                sid=call.sid,
                function=call.caller,
                line=getattr(argument, "line", 0),
                col=getattr(argument, "col", 0),
                symbol=self._expression_label(argument),
                label=f"argument {index} of the call to {definition.function}() is tainted",
                detail=(
                    f"the caller passes this value to parameter {index} "
                    f"('{definition.symbol_name}') at line {getattr(argument, 'line', 0)}"
                ),
                atoms=(atom,),
                from_sid=call.sid,
            )
            chain: List[TraceStep] = []
            if argument is not None:
                chain.extend(
                    self._trace_expression(call.caller, call.sid, argument, atom, visiting, depth + 1)
                )
            candidates.append((step, chain))
        if candidates:
            # Several call sites can supply the same parameter, and a recursive
            # function calls itself.  Prefer the trace that reaches the origin;
            # only if none of them does are all routes shown, because then the
            # caller is genuinely outside this file.
            best_step, best_chain = max(
                candidates,
                key=lambda item: self._trace_rank(item[1] + [item[0]]),
            )
            if len(candidates) > 1:
                best_step.detail = (
                    f"{best_step.detail}; {len(candidates)} call sites pass tainted data to this "
                    "parameter and the analysis is context-insensitive between them"
                )
            if any(step.kind == "source" for step in best_chain):
                steps.extend(best_chain)
                steps.append(best_step)
            else:
                for step, chain in candidates:
                    steps.extend(chain)
                    steps.append(step)
        if not found:
            steps.append(
                TraceStep(
                    kind="interprocedural-note",
                    sid=definition.sid,
                    function=definition.function,
                    line=definition.line,
                    col=definition.col,
                    symbol=definition.symbol_name,
                    label="taint reaches this parameter, but no analysed call site passes tainted data",
                    detail=(
                        "the analysis is context-insensitive: the summary records that the "
                        "parameter can influence this value, while the concrete call sites "
                        "analysed in this file do not supply taint"
                    ),
                )
            )
        return steps

    def _trace_global(self, definition, atom: str, visiting: frozenset, depth: int) -> List[TraceStep]:
        steps: List[TraceStep] = []
        for name, cfg in self.program.cfgs.items():
            if name == definition.function:
                continue
            for candidate in cfg.definitions:
                if candidate.symbol_id != definition.symbol_id:
                    continue
                problem = self._problem(name)
                run = self.program.taint.runs.get(name)
                if problem is None or run is None:
                    continue
                out_state = run.statement_out.get(candidate.sid, 0)
                if atom not in problem.atom_texts(problem.get(out_state, definition.symbol_id)):
                    continue
                step = TraceStep(
                    kind="global-write",
                    sid=candidate.sid,
                    function=name,
                    line=candidate.line,
                    col=candidate.col,
                    symbol=candidate.symbol_name,
                    label=f"file-scope variable '{candidate.symbol_name}' is written in {name}()",
                    detail="the taint reaches the file-scope variable in another function",
                    atoms=(atom,),
                )
                steps.extend(self._trace_definition(candidate, atom, visiting, depth + 1))
                steps.append(step)
        return steps

    def _trace_expression(
        self, function: str, sid: int, expr: Optional[Node], atom: str, visiting: frozenset, depth: int
    ) -> List[TraceStep]:
        if expr is None or depth > MAX_DEPTH:
            return []
        if isinstance(expr, Ident):
            return self._trace_symbol(function, sid, expr.symbol_id, atom, visiting, depth + 1)
        if isinstance(expr, Call):
            return self._trace_call(function, sid, expr, atom, visiting, depth + 1)
        if isinstance(expr, (BinaryOp, Index)):
            steps: List[TraceStep] = []
            for child in expr.children():
                if self._has_atom(function, sid, child, atom):
                    steps.extend(self._trace_expression(function, sid, child, atom, visiting, depth + 1))
            return steps
        if isinstance(expr, (UnaryOp, Assign)):
            inner = expr.operand if isinstance(expr, UnaryOp) else expr.value
            return self._trace_expression(function, sid, inner, atom, visiting, depth + 1)
        return []

    def _trace_call(
        self, function: str, sid: int, call: Call, atom: str, visiting: frozenset, depth: int
    ) -> List[TraceStep]:
        rules = self.program.rules
        kind, name = atom_origin(atom)
        context = atom_context(atom)
        for source in rules.source_rules(call.name):
            if kind == "src" and name == source.id:
                if source.argument is not None and source.argument < len(call.args):
                    steps = self._trace_expression(
                        function, sid, call.args[source.argument], atom, visiting, depth + 1
                    )
                    steps.append(self._source_step(call, source, function, sid, atom, argument=source.argument))
                    return steps
                return [self._source_step(call, source, function, sid, atom)]
        for sanitizer in rules.sanitizer_rules(call.name):
            if sanitizer.kind != "sanitizer" or sanitizer.argument >= len(call.args):
                continue
            # Does this rule claim the context the traced atom belongs to?
            covers = sanitizer.context == ALL_CONTEXTS or sanitizer.context == context
            contributors: List[int] = []
            for index, argument in enumerate(call.args):
                if index == sanitizer.argument and covers:
                    # The rule says this argument is neutralised for this
                    # context, so the atom cannot have come from it.
                    continue
                if self._has_atom(function, sid, argument, atom):
                    contributors.append(index)
            steps: List[TraceStep] = []
            for index in contributors:
                steps.extend(
                    self._trace_expression(function, sid, call.args[index], atom, visiting, depth + 1)
                )
            if covers and contributors:
                detail = (
                    f"the rule '{sanitizer.id}' sanitizes argument {sanitizer.argument} for context "
                    f"'{sanitizer.context}', but the reported data entered through another argument, "
                    "so it is not neutralised"
                )
            else:
                detail = (
                    f"the rule '{sanitizer.id}' removes taint atoms for context "
                    f"'{sanitizer.context}'; atoms of other contexts survive"
                )
            steps.append(
                TraceStep(
                    kind="sanitizer",
                    sid=sid,
                    function=function,
                    line=call.line,
                    col=call.col,
                    symbol=sanitizer.id,
                    label=f"{call.name}() applied ({sanitizer.kind} for context '{sanitizer.context}')",
                    detail=detail,
                    atoms=(atom,),
                    context=sanitizer.context,
                )
            )
            return steps
        if call.name in self.program.functions:
            steps: List[TraceStep] = []
            return_value = None
            callee = self.program.functions[call.name]
            if callee.body is not None:
                # A function can return a tainted value from several places (and
                # a recursive function returns its own call).  Every candidate
                # whose returned expression carries the atom is traced, and the
                # most complete trace wins -- taking the first one would show a
                # recursive hop that never reaches the origin.
                for node in callee.body.walk():
                    if not (isinstance(node, ReturnStmt) and node.value is not None):
                        continue
                    if not self._has_atom(call.name, node.sid, node.value, atom):
                        continue
                    candidate = self._trace_expression(
                        call.name, node.sid, node.value, atom, visiting, depth + 1
                    )
                    candidate.append(
                        TraceStep(
                            kind="return",
                            sid=node.sid,
                            function=call.name,
                            line=node.line,
                            col=node.col,
                            symbol="return",
                            label=f"{call.name}() returns a tainted value",
                            detail="the returned expression carries the same taint atom",
                            atoms=(atom,),
                        )
                    )
                    if self._trace_rank(candidate) > self._trace_rank(steps):
                        steps = candidate
                        return_value = node
            steps.append(
                TraceStep(
                    kind="call",
                    sid=sid,
                    function=function,
                    line=call.line,
                    col=call.col,
                    symbol=call.name,
                    label=f"call to {call.name}() propagates taint to the caller",
                    detail=(
                        "the function summary records that the arguments flowing into this call "
                        "influence the returned value"
                    ),
                    atoms=(atom,),
                )
            )
            return steps
        # Unknown external function: conservative propagation.
        steps = []
        for argument in call.args:
            if self._has_atom(function, sid, argument, atom):
                steps.extend(self._trace_expression(function, sid, argument, atom, visiting, depth + 1))
        steps.append(
            TraceStep(
                kind="unknown-call",
                sid=sid,
                function=function,
                line=call.line,
                col=call.col,
                symbol=call.name,
                label=f"{call.name}() is not modelled; taint is propagated conservatively",
                detail=(
                    "the function is not defined in this file and has no rule; CodeTrace assumes "
                    "its result may depend on its arguments and does not assume it validates them"
                ),
                atoms=(atom,),
            )
        )
        return steps

    # -- helpers ---------------------------------------------------------
    def _source_step(self, call: Call, source, function: str, sid: int, atom: str,
                     argument: Optional[int] = None) -> TraceStep:
        if argument is None:
            label = f"{call.name}() introduces untrusted data (source rule '{source.id}')"
            symbol = call.name
            detail = source.description or "configured source"
        else:
            label = (
                f"{call.name}() treats argument {argument} as untrusted input "
                f"(source rule '{source.id}')"
            )
            symbol = self._expression_label(call.args[argument] if argument < len(call.args) else None)
            detail = source.description or "configured source"
        return TraceStep(
            kind="source",
            sid=sid,
            function=function,
            line=call.line,
            col=call.col,
            symbol=symbol,
            label=label,
            detail=detail,
            atoms=(atom,),
        )

    def _written_expression(self, statement: Node, symbol_id: int) -> Optional[Node]:
        if isinstance(statement, VarDecl):
            for declarator in statement.declarators:
                if declarator.symbol_id == symbol_id:
                    return declarator.init
            return None
        if isinstance(statement, ExprStmt) and statement.expr is not None:
            expr = statement.expr
            if isinstance(expr, Assign) and self._target_symbol(expr.target) == symbol_id:
                return expr.value
            if isinstance(expr, UnaryOp) and self._target_symbol(expr.operand) == symbol_id:
                return expr.operand
            return expr
        if isinstance(statement, ReturnStmt):
            return statement.value
        if isinstance(statement, (ForStmt,)):
            return None
        return None

    def _target_symbol(self, node: Optional[Node]) -> int:
        if isinstance(node, Ident):
            return node.symbol_id
        if isinstance(node, Index) and isinstance(node.base, Ident):
            return node.base.symbol_id
        return -1

    def _expression_label(self, node: Optional[Node]) -> str:
        if node is None:
            return ""
        if isinstance(node, Ident):
            return node.name
        if isinstance(node, Call):
            return f"{node.name}()"
        if isinstance(node, Index):
            return f"{self._expression_label(node.base)}[...]"
        if isinstance(node, BinaryOp):
            return f"{self._expression_label(node.left)} {node.op} {self._expression_label(node.right)}"
        if isinstance(node, (UnaryOp,)):
            return f"{node.op}{self._expression_label(node.operand)}"
        text = getattr(node, "text", None)
        return text if text else node.kind


# ----------------------------------------------------------------------
# Finding construction
# ----------------------------------------------------------------------
def _limitations_for(program, path: List[TraceStep], hit: SinkHit, interprocedural: bool) -> List[str]:
    limitations: List[str] = []
    if interprocedural:
        limitations.append(
            "Interprocedural reasoning is context-insensitive: parameters are summarised across "
            "all call sites, which can add flows that a single call site cannot actually create."
        )
    if any(step.kind == "sanitizer" for step in path):
        limitations.append(
            "A sanitizer rule appears on the reported path but does not neutralise the reported "
            "value: it covers a different context, or the taint entered through an argument the "
            "rule does not sanitise. The flow is reported conservatively."
        )
    if any(step.kind == "unknown-call" for step in path):
        limitations.append(
            "The path passes through a function that is not modelled, so the analysis assumes its "
            "result depends on its arguments instead of proving it."
        )
    if any(step.kind == "unresolved" for step in path) or not any(step.kind == "source" for step in path):
        limitations.append(
            "The recorded path does not reach a configured source: the origin of the taint could "
            "not be established from this file (it may come from a caller, a file-scope variable "
            "or an unmodelled construct)."
        )
    if program.semantic.unsupported_offsets:
        limitations.append(
            f"{len(set(program.semantic.unsupported_offsets))} construct(s) in this file are outside the "
            "supported language subset and were not analysed."
        )
    if program.semantic.unknowns:
        limitations.append(
            f"{len(program.semantic.unknowns)} value(s) in this file have an unknown type or shape and are "
            "treated conservatively."
        )
    symbols = program.semantic.symbols
    if any(symbol.is_array for symbol in symbols):
        limitations.append(
            "Array elements are not tracked individually: taint assigned to any element taints the "
            "whole array, and indices are not proved to be in range."
        )
    if any(step.kind in ("assignment", "declaration") for step in path) and any(
        step.kind == "control" for step in path
    ):
        limitations.append(
            "Path conditions were recorded but not proved feasible: the analysis reports the flow "
            "as structurally possible, not as reachable at run time."
        )
    limitations.append(
        "The flow was detected by static analysis only; the analysed program was never executed and "
        "exploitability was not established."
    )
    return limitations


#: How a guarding condition was classified.  The classification is deliberately
#: syntactic: CodeTrace does **not** run a solver or a symbolic evaluator, so an
#: expression that is not a literal is honestly reported as "not evaluated"
#: rather than being guessed at.
FEASIBILITY_LITERAL_TRUE = "literal-true"
FEASIBILITY_LITERAL_FALSE = "literal-false"
FEASIBILITY_NOT_EVALUATED = "not-evaluated"

#: Overall classification of a reported path.
PATH_UNCONDITIONAL = "unconditional"
PATH_GUARDED = "guarded"
PATH_INFEASIBLE_GUARD = "conditionally-infeasible"


def _confidence_and_certainty(
    path: List[TraceStep], interprocedural: bool, program, feasibility: str = PATH_UNCONDITIONAL
) -> Tuple[str, str]:
    """Map what the trace could establish onto (confidence, certainty).

    ``confirmed`` is reserved for a straight-line flow inside one modelled
    function with no undecided guard: every hop is justified by a reaching
    definition.  Anything the analysis had to approximate -- an unmodelled
    call, a summary rather than a real call chain, a construct outside the
    supported subset, or a guard whose outcome was not decided -- is
    ``approximate``.  A trace that cannot even name the origin of the value, or
    that runs only under a guard already known to be false, is ``unproven``.
    """
    has_source = any(step.kind == "source" for step in path)
    has_unknown = any(step.kind == "unknown-call" for step in path)
    has_unresolved = any(step.kind == "unresolved" for step in path)
    if not has_source or has_unresolved or feasibility == PATH_INFEASIBLE_GUARD:
        return LOW, UNPROVEN
    if (
        interprocedural
        or has_unknown
        or program.semantic.unsupported_offsets
        or feasibility == PATH_GUARDED
    ):
        return MEDIUM, APPROXIMATE
    return HIGH, CONFIRMED


def build_findings(program) -> List[Finding]:
    """Turn taint hits into explainable findings, applying the flow policy."""
    findings: List[Finding] = []
    explainer = PathExplainer(program)
    rules = program.rules
    # Guard stack per statement: taken from the CFG structure (see
    # dependencies.control_dependencies), never from searching the source text.
    guards_by_sid = control_dependencies(program)

    for hit in program.taint.hits:
        by_source: Dict[str, List[str]] = {}
        for atom in hit.atoms:
            kind, name = atom_origin(atom)
            if kind == "src":
                by_source.setdefault(name, []).append(atom)
        if not by_source:
            continue
        for source_rule_id, atoms in sorted(by_source.items()):
            flow = rules.flow_for(hit.rule.id, source_rule_id)
            if flow is None:
                # Policy: the flow rules decide which source/sink combinations
                # are reported at all.
                continue
            source_rule = rules.sources[source_rule_id]
            atoms = sorted(atoms)
            # Prefer the atom that yields the longest, most complete trace.
            best_path: List[TraceStep] = []
            for atom in atoms:
                candidate = explainer.explain(hit, atom)
                if len(candidate) > len(best_path):
                    best_path = candidate
            interprocedural = any(step.function != hit.function for step in best_path)
            branch_conditions = _branch_conditions(guards_by_sid, best_path)
            feasibility, feasibility_note = _path_feasibility(branch_conditions)
            confidence, certainty = _confidence_and_certainty(
                best_path, interprocedural, program, feasibility
            )
            sink_statement = program.statements.get(hit.sid)
            sink_text = program.statement_text(hit.sid)
            finding_id = stable_finding_id(
                rule_id=flow.id,
                sink_function=hit.rule.function,
                sink_rule=hit.rule.id,
                argument_index=hit.argument_index,
                source_rules=[source_rule.id],
                sink_text=sink_text,
            )
            path_json = []
            for index, step in enumerate(best_path):
                entry = step.to_json()
                entry["index"] = index
                entry["from_sid"] = best_path[index - 1].sid if index else -1
                path_json.append(entry)
            source_description = source_rule.description or source_rule.function
            sink_description = hit.rule.description or hit.rule.function
            finding = Finding(
                id=finding_id,
                rule_id=flow.id,
                flow_id=flow.id,
                category=flow.category,
                severity=flow.severity,
                confidence=confidence,
                certainty=certainty,
                sink={
                    "rule": hit.rule.id,
                    "function": hit.rule.function,
                    "category": hit.rule.category,
                    "severity": hit.rule.severity,
                    "context": hit.rule.context,
                    "argument_index": hit.argument_index,
                    "description": sink_description,
                    "sid": hit.sid,
                    "line": getattr(hit.expression, "line", 0),
                    "col": getattr(hit.expression, "col", 0),
                    "statement_text": sink_text.strip(),
                    "enclosing_function": hit.function,
                    "block": hit.block,
                    "expression": explainer._expression_label(hit.expression),
                },
                source={
                    "rule": source_rule.id,
                    "function": source_rule.function,
                    "description": source_description,
                    "line": next((s.line for s in best_path if s.kind == "source"), 0),
                    "col": next((s.col for s in best_path if s.kind == "source"), 0),
                    "sid": next((s.sid for s in best_path if s.kind == "source"), -1),
                    "contexts": list(source_rule.contexts),
                },
                path=path_json,
                sanitizers_seen=[
                    {
                        "rule": step.symbol,
                        "context": step.context,
                        "detail": step.detail,
                        "line": step.line,
                    }
                    for step in best_path
                    if step.kind == "sanitizer"
                ],
                branch_conditions=branch_conditions,
                feasibility=feasibility,
                feasibility_note=feasibility_note,
                interprocedural=interprocedural,
                explanation=_explanation_text(
                    flow, source_rule, hit, best_path, certainty, interprocedural,
                    branch_conditions,
                ),
                limitations=_limitations_for(program, best_path, hit, interprocedural),
                remediation=REMEDIATION.get(flow.category, DEFAULT_REMEDIATION),
                evidence={
                    "engine_version": ENGINE_VERSION,
                    "rules_version": rules.version_label(),
                    "taint_engine": "context-insensitive, flow-sensitive may-analysis over the CFG",
                    "reaching_definitions": "used to justify each data-flow hop in the path",
                    "analyses": [
                        "lexer",
                        "canonical LR parser (LALR tables)",
                        "semantic analysis",
                        "control-flow graph",
                        "reaching definitions",
                        "liveness",
                        "definite assignment",
                        "taint propagation",
                        "program dependency graph",
                    ],
                    "atoms": atoms,
                    "flow_rule": flow.to_json(),
                    "sink_statement_span": list(sink_statement.span) if sink_statement else [],
                },
                statement_ids=[step.sid for step in best_path if step.sid >= 0],
                path_atoms=atoms,
            )
            findings.append(finding)
    findings.sort(key=lambda f: (f.sort_key, f.id))
    return findings


def _literal_truth(condition: str) -> Optional[bool]:
    """Truth value of a condition that is a literal, or ``None``.

    Only integer and boolean literals are recognised.  Anything else -- a
    comparison, a call, a variable -- is not evaluated, because CodeTrace does
    not implement symbolic execution.
    """
    text = (condition or "").strip()
    while text.startswith("(") and text.endswith(")") and len(text) > 2:
        text = text[1:-1].strip()
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        return int(text, 0) != 0
    except ValueError:
        return None


def _feasibility_of(condition: str) -> str:
    truth = _literal_truth(condition)
    if truth is True:
        return FEASIBILITY_LITERAL_TRUE
    if truth is False:
        return FEASIBILITY_LITERAL_FALSE
    return FEASIBILITY_NOT_EVALUATED


def _branch_conditions(
    guards_by_sid: Dict[int, List[ControlDep]], path: List[TraceStep]
) -> List[dict]:
    """Conditions that guard the statements on a reported path.

    Every entry is a real control dependency taken from the CFG structure.  The
    ``feasibility`` field says only what a syntactic check can support; the
    analysis never claims that a condition holds at run time.
    """
    entries: List[dict] = []
    seen: Set[Tuple[int, int, str]] = set()
    for step in path:
        if step.sid < 0:
            continue
        for guard in guards_by_sid.get(step.sid, []):
            key = (guard.controller_sid, step.sid, guard.condition)
            if key in seen:
                continue
            seen.add(key)
            feasibility = _feasibility_of(guard.condition)
            entries.append(
                {
                    "line": guard.line,
                    "col": guard.col,
                    "sid": guard.controller_sid,
                    "guarded_sid": step.sid,
                    "condition": guard.condition,
                    "kind": guard.kind,
                    "feasibility": feasibility,
                    "note": (
                        "the condition is a literal and is therefore known "
                        + ("true" if feasibility == FEASIBILITY_LITERAL_TRUE else "false")
                        + " without executing the program"
                        if feasibility != FEASIBILITY_NOT_EVALUATED
                        else "the condition was not evaluated: CodeTrace records the guard but "
                        "does not decide whether it holds at run time"
                    ),
                }
            )
    entries.sort(key=lambda entry: (entry["line"], entry["col"], entry["guarded_sid"]))
    return entries


def _path_feasibility(branch_conditions: List[dict]) -> Tuple[str, str]:
    """Overall feasibility label for a reported path, with an explanation."""
    if not branch_conditions:
        return (
            PATH_UNCONDITIONAL,
            "no branch condition guards the reported path; the path is structurally reachable "
            "from the entry of the enclosing function.",
        )
    literal_false = [e for e in branch_conditions if e["feasibility"] == FEASIBILITY_LITERAL_FALSE]
    if literal_false:
        return (
            PATH_INFEASIBLE_GUARD,
            "at least one guard on the reported path has a literal false condition, so the path "
            "cannot execute as written; the reported flow is kept for review but is not reachable.",
        )
    unevaluated = [e for e in branch_conditions if e["feasibility"] == FEASIBILITY_NOT_EVALUATED]
    return (
        PATH_GUARDED,
        f"{len(branch_conditions)} branch condition(s) guard the reported path"
        + (f" ({len(unevaluated)} of them were not evaluated)" if unevaluated else "")
        + ". The data flow is established by a may-analysis; whether the guards hold at run time "
        "was not decided, because CodeTrace does not perform symbolic execution.",
    )


def _explanation_text(flow, source_rule, hit: SinkHit, path: List[TraceStep], certainty: str,
                      interprocedural: bool, branch_conditions: Optional[List[dict]] = None) -> str:
    source_step = next((s for s in path if s.kind == "source"), None)
    hops = [
        f"{step.label} (line {step.line})" for step in path if step.kind not in ("sink",)
    ]
    route = " -> ".join(hops) if hops else "the sink argument"
    origin = (
        f"line {source_step.line} ({source_step.symbol})" if source_step else "an origin that could not be resolved"
    )
    cross = (
        "The flow crosses at least one function boundary, so the interprocedural summary was used."
        if interprocedural
        else "The flow is intraprocedural."
    )
    guarded = ""
    if branch_conditions:
        described = ", ".join(
            f"'{entry['condition']}' at line {entry['line']} ({entry['kind']}, {entry['feasibility']})"
            for entry in branch_conditions[:4]
        )
        guarded = (
            f" {len(branch_conditions)} branch condition(s) guard this path: {described}"
            + (", ..." if len(branch_conditions) > 4 else "")
            + ". Whether they hold at run time was not decided."
        )
    return (
        f"Potential {flow.category.replace('-', ' ')} flow detected: data introduced at {origin} reaches "
        f"argument {hit.argument_index} of {hit.rule.function}() at line "
        f"{getattr(hit.expression, 'line', 0)}, which rule '{hit.rule.id}' classifies as a "
        f"'{hit.rule.context}' context operation. The taint engine propagated the atom(s) "
        f"{', '.join(sorted(set(hit.atoms)))} along {len(path) - 1} recorded step(s): {route}. "
        f"{cross} The flow rule '{flow.id}' connects source '{source_rule.id}' to sink '{hit.rule.id}'"
        + (
            f" and lists sanitizers {', '.join(flow.sanitizers)}; none of them removed the atoms that "
            f"reached this sink."
            if flow.sanitizers
            else "."
        )
        + guarded
        + f" Analysis certainty: {certainty}. This is a static finding: exploitability was not "
        "established."
    )
