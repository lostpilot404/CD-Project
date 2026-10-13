"""Whole-program analysis pipeline.

``analyse_source`` is the single entry point used by the API, the tests and the
evaluation harness.  It runs, in order: lexing, LR parsing, semantic analysis,
statement numbering, CFG construction, reaching definitions, liveness,
definite assignment, taint analysis, dependency-graph construction, slicing and
finding generation.  Every phase is timed and every count in the returned
metrics dict is measured, never estimated.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..findings.explain import build_findings
from ..findings.models import Finding
from ..frontend.ast_nodes import FunctionDecl, Node, SourceUnit
from ..frontend.lexer import Diagnostic
from ..frontend.pipeline import ParseOutcome, parse_source, parser_tables
from ..rules.model import RuleSet
from ..rules.rule_language import load_builtin_rules
from ..semantics.analyzer import SemanticResult, analyse as semantic_analyse
from ..semantics.symbol_table import ARRAY as SYMBOL_ARRAY
from ..semantics.symbol_table import PARAMETER as SYMBOL_PARAMETER
from ..semantics.symbol_table import VARIABLE as SYMBOL_VARIABLE
from . import definite_assignment, dependencies, liveness, reaching_definitions
from .cfg import CFG, Definition, assign_statement_ids, build_cfgs
from .dataflow import DataFlowResult
from .slicing import Slice, SliceEngine
from .taint import TaintEngine, TaintResult

from ..version import ENGINE_VERSION  # noqa: F401  (re-exported for callers)

#: Hard limits that keep a hostile or pathological input from exhausting the
#: server.  They are configuration, not magic numbers.
MAX_SOURCE_BYTES = 512 * 1024
MAX_SOURCE_LINES = 20_000
MAX_FUNCTIONS = 400
MAX_FIXPOINT_ITERATIONS = 10_000
#: Symbol kinds that can hold a value at run time.  Function symbols live in the
#: symbol table as well, but a function is never "defined" or "live" in the
#: data-flow sense, so they are kept out of the lattices.
DATAFLOW_SYMBOL_KINDS = (SYMBOL_VARIABLE, SYMBOL_PARAMETER, SYMBOL_ARRAY)


@dataclass
class FunctionAnalyses:
    """Per-function analysis results."""

    name: str
    cfg: CFG
    reaching: reaching_definitions.ReachingDefinitions
    reaching_result: DataFlowResult
    reaching_states: Dict[int, Tuple[int, int]]
    live: liveness.Liveness
    live_result: DataFlowResult
    live_states: Dict[int, Tuple[int, int]]
    definite: definite_assignment.DefiniteAssignment
    definite_result: DataFlowResult
    definite_states: Dict[int, Tuple[int, int]]


@dataclass
class Program:
    """Everything CodeTrace knows about one analysed translation unit."""

    filename: str
    source: str
    parse: ParseOutcome
    semantic: SemanticResult
    statements: Dict[int, Node]
    cfgs: Dict[str, CFG]
    functions: Dict[str, FunctionDecl]
    rules: RuleSet
    taint: TaintResult
    analyses: Dict[str, FunctionAnalyses] = field(default_factory=dict)
    dependencies: Optional[dependencies.DependencyGraph] = None
    findings: List[Finding] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)
    metrics: Dict[str, object] = field(default_factory=dict)
    slicing: Optional[SliceEngine] = None
    limits_hit: List[str] = field(default_factory=list)
    #: Why the analysis is partial, if it is: set when the parser had to
    #: recover from a syntax error or when a construct outside the supported
    #: subset had to be skipped.  A partial analysis is still useful, but its
    #: findings are incomplete and every consumer is told so.
    partial_reasons: List[str] = field(default_factory=list)

    @property
    def analysis_complete(self) -> bool:
        return not self.partial_reasons

    # -- convenience ------------------------------------------------------
    @property
    def errors(self) -> List[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def ok(self) -> bool:
        return self.parse.accepted and not self.errors

    def statement_text(self, sid: int) -> str:
        node = self.statements.get(sid)
        if node is None:
            return ""
        return self.source[node.span[0] : node.span[1]]

    def line_of(self, offset: int) -> int:
        return self.parse.index.position(offset)[0] if self.parse.index else 0

    def block_of_statement(self, sid: int, function: Optional[str] = None) -> Optional[int]:
        for name, cfg in self.cfgs.items():
            if function is not None and name != function:
                continue
            for block in cfg.sorted_blocks():
                if sid in block.statement_ids:
                    return block.id
        return None

    def function_of_statement(self, sid: int) -> Optional[str]:
        for name, cfg in self.cfgs.items():
            for block in cfg.sorted_blocks():
                if sid in block.statement_ids:
                    return name
        return None


def attach_call_statement_ids(semantic_result, statements: Dict[int, Node]) -> None:
    """Give every recorded call site the id of the statement that contains it.

    ``sid`` is ``-1`` when no statement contains the call (which cannot happen
    for a well-formed parse, but is legal to observe and is reported as such).
    """
    ordered = sorted(statements.items(), key=lambda item: (item[1].span[0], -item[1].span[1]))
    for call in semantic_result.calls:
        start, end = call.span
        best_sid, best_size = -1, None
        for sid, statement in ordered:
            s_start, s_end = statement.span
            if s_start <= start and end <= s_end:
                size = s_end - s_start
                if best_size is None or size < best_size:
                    best_sid, best_size = sid, size
        call.sid = best_sid


def _default_rules() -> RuleSet:
    rule_set, _diagnostics = load_builtin_rules()
    return rule_set


def analyse_source(
    source: str,
    filename: str = "<source>",
    rules: Optional[RuleSet] = None,
    parser_mode: str = "lalr",
    run_dependencies: bool = True,
    run_slicing: bool = True,
    include_builtin_rules: bool = True,
) -> Program:
    """Run the complete analysis pipeline over one source file."""
    timings: Dict[str, float] = {}
    metrics: Dict[str, object] = {}
    limits_hit: List[str] = []

    # -- input limits ----------------------------------------------------
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError(
            f"source is larger than the {MAX_SOURCE_BYTES} byte analysis limit"
        )
    line_count = source.count("\n") + 1
    if line_count > MAX_SOURCE_LINES:
        raise ValueError(
            f"source has more than {MAX_SOURCE_LINES} lines, which exceeds the analysis limit"
        )

    # ``rules`` replaces the default rule set.  Unless the caller asks for the
    # custom set to stand alone (``include_builtin_rules=False``, used by the
    # API once it has merged the two itself), the built-in rules are merged in
    # so a submitted rule file extends the shipped policy; on an id collision
    # the submitted rule wins (see ``rules.model.merge``).
    if rules is None:
        rule_set = _default_rules()
    elif include_builtin_rules:
        from ..rules.model import merge

        rule_set = merge(_default_rules(), rules)
    else:
        rule_set = rules

    # -- front end -------------------------------------------------------
    started = time.perf_counter()
    parse = parse_source(source, filename, mode=parser_mode)
    timings["lex_seconds"] = round(parse.lex_seconds, 6)
    timings["parse_seconds"] = round(parse.parse_seconds, 6)
    # The tables are built once and cached; the timing is recorded so the first
    # request in a process is not mistaken for a slow analysis.
    tables_started = time.perf_counter()
    tables = parser_tables(parser_mode)
    timings["grammar_tables_seconds"] = round(time.perf_counter() - tables_started, 6)
    metrics["grammar_states"] = tables.automaton.stats.states
    metrics["grammar_productions"] = len(tables.grammar.productions)
    metrics["grammar_conflicts"] = len(tables.conflicts)

    # -- semantic analysis ------------------------------------------------
    tree = parse.tree if isinstance(parse.tree, SourceUnit) else SourceUnit(filename=filename)
    semantic_started = time.perf_counter()
    semantic_result = semantic_analyse(tree, parse.index, filename)
    timings["semantic_seconds"] = round(time.perf_counter() - semantic_started, 6)

    statements: Dict[int, Node] = {}
    cfgs: Dict[str, CFG] = {}
    analyses: Dict[str, FunctionAnalyses] = {}
    taint_result = TaintResult()
    dependency_graph = None

    if tree.decls:
        if len(semantic_result.functions) > MAX_FUNCTIONS:
            limits_hit.append(
                f"file declares {len(semantic_result.functions)} functions; only the first "
                f"{MAX_FUNCTIONS} are analysed"
            )
        # -- statements and CFGs --------------------------------------
        cfg_started = time.perf_counter()
        statements = assign_statement_ids(tree)
        cfgs = build_cfgs(tree, statements)
        # Semantic analysis runs before statement ids exist, so the call sites
        # it recorded are linked to their statements here: the innermost
        # statement whose span contains the call is the statement that performs
        # it.  Call edges and dispositions depend on this being exact.
        attach_call_statement_ids(semantic_result, statements)
        timings["cfg_seconds"] = round(time.perf_counter() - cfg_started, 6)

        # -- classical data-flow analyses -----------------------------
        df_started = time.perf_counter()
        symbol_names = {
            symbol.id: symbol.name
            for symbol in semantic_result.symbols
            if symbol.kind in DATAFLOW_SYMBOL_KINDS
        }
        for name, cfg in cfgs.items():
            rd_problem, rd_result, rd_states = reaching_definitions.analyse(
                cfg, max_iterations=MAX_FIXPOINT_ITERATIONS
            )
            live_problem, live_result, live_states = liveness.analyse(
                cfg, symbol_names, max_iterations=MAX_FIXPOINT_ITERATIONS
            )
            da_problem, da_result = definite_assignment.analyse(
                cfg, symbol_names, max_iterations=MAX_FIXPOINT_ITERATIONS
            )
            for problem_name, outcome in (
                (name, rd_result), (name, live_result), (name, da_result)
            ):
                if not outcome.converged:
                    limits_hit.append(
                        f"data-flow analysis '{problem_name}' did not converge within "
                        f"{MAX_FIXPOINT_ITERATIONS} iterations"
                    )
            analyses[name] = FunctionAnalyses(
                name=name,
                cfg=cfg,
                reaching=rd_problem,
                reaching_result=rd_result,
                reaching_states=rd_states,
                live=live_problem,
                live_result=live_result,
                live_states=live_states,
                definite=da_problem,
                definite_result=da_result,
                definite_states=da_problem.statement_states(da_result),
            )
        timings["dataflow_seconds"] = round(time.perf_counter() - df_started, 6)

        # -- taint analysis -------------------------------------------
        taint_started = time.perf_counter()
        program_stub = Program(
            filename=filename,
            source=source,
            parse=parse,
            semantic=semantic_result,
            statements=statements,
            cfgs=cfgs,
            functions=semantic_result.functions,
            rules=rule_set,
            taint=TaintResult(),
            analyses=analyses,
        )
        engine = TaintEngine(program_stub)
        taint_result = engine.run()
        program_stub.taint = taint_result
        timings["taint_seconds"] = round(time.perf_counter() - taint_started, 6)

        # -- dependencies and slicing ----------------------------------
        # The dependency graph is built *after* the data-flow and taint
        # analyses so that every edge can carry the analysis result that
        # justifies it (a reaching definition for data edges, the taint state
        # for taint edges).  It is built from the same program object the
        # analyses wrote into, so it never sees a partially analysed program.
        dep_started = time.perf_counter()
        if run_dependencies:
            dependency_graph = dependencies.build_graph(program_stub)
        timings["dependencies_seconds"] = round(time.perf_counter() - dep_started, 6)

    partial_reasons: List[str] = []
    if not parse.accepted:
        partial_reasons.append(
            f"the parser recovered from {parse.stats.get('errors_recovered', 0)} syntax error(s), "
            "so statements were skipped and this analysis is partial"
        )
    unsupported = [
        d for d in list(parse.diagnostics) + list(semantic_result.diagnostics)
        if getattr(d, "unsupported", False)
    ]
    # Constructs skipped by the lexer/parser never reach semantic analysis, so
    # their offsets are merged in here: the reports and the interface must count
    # every unsupported construct, not only the ones the later phases saw.
    semantic_result.unsupported_offsets = sorted(
        set(semantic_result.unsupported_offsets) | {d.offset for d in unsupported}
    )
    if unsupported:
        partial_reasons.append(
            f"{len(unsupported)} construct(s) are outside the supported language subset and were "
            "not analysed: " + "; ".join(sorted({d.message for d in unsupported})[:3])
        )
    # An error-severity semantic diagnostic (for example an undeclared
    # identifier or an argument of the wrong type) means the program would not
    # compile under C rules, and the analysis had to guess what that name or
    # value refers to.  Such a run must not be presented as complete.  Errors
    # that are already counted as unsupported constructs are not counted twice.
    semantic_errors = [
        d for d in semantic_result.diagnostics
        if d.severity == "error" and not getattr(d, "unsupported", False)
    ]
    if semantic_errors:
        partial_reasons.append(
            f"{len(semantic_errors)} semantic error(s) were reported ("
            + "; ".join(sorted({d.code for d in semantic_errors})[:4])
            + "): the program would not compile, so names or values involved in those "
            "errors were not resolved and the findings may be incomplete"
        )

    program = Program(
        filename=filename,
        source=source,
        parse=parse,
        semantic=semantic_result,
        statements=statements,
        cfgs=cfgs,
        functions=semantic_result.functions,
        rules=rule_set,
        taint=taint_result,
        analyses=analyses,
        dependencies=dependency_graph,
        metrics={},
        limits_hit=limits_hit,
        partial_reasons=partial_reasons,
    )

    slice_started = time.perf_counter()
    # Slices are traversals of the dependency graph, so there is nothing to
    # traverse when the graph was not built.  ``run_slicing=False`` skips the
    # slice engine even when the graph exists (findings-only runs).
    if run_slicing and run_dependencies:
        program.slicing = SliceEngine(program)
    else:
        program.slicing = None
    timings["slicing_setup_seconds"] = round(time.perf_counter() - slice_started, 6)

    # -- findings ---------------------------------------------------------
    findings_started = time.perf_counter()
    program.findings = build_findings(program)
    timings["findings_seconds"] = round(time.perf_counter() - findings_started, 6)

    # -- diagnostics merge -------------------------------------------------
    diagnostics: List[Diagnostic] = []
    diagnostics.extend(parse.diagnostics)
    diagnostics.extend(semantic_result.diagnostics)
    diagnostics.extend(_cfg_diagnostics(program))
    diagnostics.extend(_dataflow_diagnostics(program))
    diagnostics.extend(_finding_diagnostics(program))
    program.diagnostics = diagnostics

    # -- metrics ------------------------------------------------------------
    metrics.update(
        {
            "source_lines": line_count,
            "source_bytes": len(source.encode("utf-8")),
            "tokens": len(parse.tokens),
            "ast_nodes": sum(1 for _ in tree.walk()),
            "statements": len(statements),
            "functions": len(cfgs),
            "symbols": len(semantic_result.symbols.symbols),
            "scopes": len(semantic_result.symbols.scopes),
            "calls": len(semantic_result.calls),
            "basic_blocks": sum(len(cfg.blocks) for cfg in cfgs.values()),
            "cfg_edges": sum(len(cfg.edges()) for cfg in cfgs.values()),
            "definitions": sum(len(cfg.definitions) for cfg in cfgs.values()),
            "unreachable_blocks": sum(len(cfg.unreachable) for cfg in cfgs.values()),
            "dependency_edges": len(dependency_graph.edges) if dependency_graph else 0,
            "dependency_nodes": len(dependency_graph.nodes) if dependency_graph else 0,
            "taint_hits": len(taint_result.hits),
            "findings": len(program.findings),
            "dataflow_iterations": sum(
                analysis.reaching_result.iterations
                + analysis.live_result.iterations
                + analysis.definite_result.iterations
                for analysis in analyses.values()
            ),
            "grammar_states": metrics.get("grammar_states"),
            "grammar_productions": metrics.get("grammar_productions"),
            "grammar_conflicts": metrics.get("grammar_conflicts"),
            "parser_mode": parser_mode,
            "engine_version": ENGINE_VERSION,
            "rules_version": rule_set.version_label(),
            "limits_hit": list(limits_hit),
            "analysis_complete": not partial_reasons,
            "partial_reasons": list(partial_reasons),
            "timings": timings,
        }
    )
    program.metrics = metrics
    return program


# ----------------------------------------------------------------------
# Diagnostics produced by the later phases
# ----------------------------------------------------------------------
def _cfg_diagnostics(program: Program) -> List[Diagnostic]:
    """Report statements that the CFG proves unreachable."""
    diagnostics: List[Diagnostic] = []
    index = program.parse.index
    for name, cfg in program.cfgs.items():
        for block_id in sorted(cfg.unreachable):
            block = cfg.block(block_id)
            if not block.statements:
                continue
            statement = block.statements[0]
            # Only report the first statement of an unreachable region; the
            # rest carry the same cause.
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="CFG001",
                    message=f"unreachable code in function '{name}': no control-flow path reaches this statement",
                    line=statement.line,
                    col=statement.col,
                    offset=statement.span[0],
                    end_offset=statement.span[1],
                    phase="cfg",
                    detail="the statement follows a return, break or continue in every path "
                    "leading to it, or a loop whose condition is never true",
                )
            )
    return diagnostics


def _dataflow_diagnostics(program: Program) -> List[Diagnostic]:
    """Uninitialised reads found by definite-assignment analysis."""
    diagnostics: List[Diagnostic] = []
    for name, analysis in program.analyses.items():
        for item in analysis.definite.uninitialised_reads(analysis.definite_result):
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="DFA001",
                    message=(
                        f"variable '{item['symbol']}' may be used before it is assigned"
                    ),
                    line=item["line"],
                    col=item["col"],
                    offset=item["offset"],
                    end_offset=item["offset"],
                    phase="dataflow",
                    detail="definite-assignment analysis found at least one path from the function "
                    "entry to this statement on which the variable is not assigned",
                )
            )
    return diagnostics


def _finding_diagnostics(program: Program) -> List[Diagnostic]:
    """Findings are reported through the findings list, not as diagnostics."""
    return []


# ----------------------------------------------------------------------
# Query helpers used by the API and the UI
# ----------------------------------------------------------------------
def reaching_definitions_at(
    program: Program, function: str, sid: int, symbol_id: Optional[int] = None
) -> List[dict]:
    """Which definitions may have supplied the value read at statement ``sid``."""
    analysis = program.analyses.get(function)
    if analysis is None:
        return []
    definitions = analysis.reaching.definitions_reaching(analysis.reaching_states, sid, symbol_id)
    return [
        {
            **definition.to_json(),
            "explanation": (
                f"{definition.describe()} at line {definition.line} reaches statement {sid}"
            ),
        }
        for definition in definitions
    ]


def live_variables_at(program: Program, function: str, sid: int, at: str = "in") -> List[str]:
    analysis = program.analyses.get(function)
    if analysis is None:
        return []
    return analysis.live.live_variables(analysis.live_states, sid, at=at)


def taint_at(program: Program, function: str, sid: int) -> List[dict]:
    """Taint atoms of every variable before statement ``sid``."""
    run = program.taint.runs.get(function)
    problem = program.taint.problems.get(function) if hasattr(program.taint, "problems") else None
    if run is None or problem is None:
        return []
    state = run.statement_in.get(sid, 0)
    out: List[dict] = []
    for symbol_id, name in problem.symbol_names.items():
        atoms = sorted(problem.atom_texts(problem.get(state, symbol_id)))
        if atoms:
            out.append({"symbol": name, "symbol_id": symbol_id, "atoms": atoms})
    return out
