# -*- coding: utf-8 -*-
"""Content of the BCSE307P project report for CodeTrace.

The text is kept separate from the DOCX builder so that it can be reviewed as
plain text.  Blocks are tuples interpreted by ``build_bcse307p_report.py``:

    ("h2", text)                      second-level heading (appears in the TOC)
    ("h3", text)                      third-level heading
    ("p", text)                       justified body paragraph
    ("bullets", [text, ...])          bulleted list
    ("numbered", [text, ...])         numbered list
    ("figure", path, caption, width)  centred picture + caption (width in inches)
    ("table", caption, header, rows, widths)   caption above, widths in inches
    ("code", [lines])                 monospace listing
    ("caption", text)                 centred caption paragraph (e.g. for a listing)
    ("pagebreak",)

Inline markup inside text: ``**bold**``, ``*italic*``, ```code``` and
citation keys written as ``{key}``; keys are numbered in order of first use
and the reference list is generated from REFERENCES.
"""

TITLE = "CodeTrace — Static Program Analysis and Security Vulnerability Detection"
GUIDE = "Nithya K, Assistant Professor Senior Grade II, School of Computer Science and Engineering, VIT Vellore"

FIG = "submission/figures/"

ABSTRACT = [
    "Static analysis is one of the most dependable ways of detecting injection-style security "
    "weaknesses before software is deployed, yet many tools present their findings as opaque "
    "verdicts that developers find difficult to trust. This report presents CodeTrace, a "
    "compiler-driven static analysis platform that detects data-flow security vulnerabilities in "
    "programs written in CT-C, a C-like language subset, and explains every result through the "
    "program structures that a compiler front end produces. The system implements its own compiler "
    "pipeline in Python without third-party libraries: a hand-written lexer, an LR parser generator "
    "that constructs canonical LR(1), LALR(1) and SLR(1) tables from a declarative grammar, an "
    "abstract syntax tree with source spans, semantic analysis with scoped symbol tables, "
    "control-flow graph construction, and worklist-based data-flow analyses for reaching "
    "definitions, live variables and definite assignment. On top of these phases, an interprocedural "
    "taint engine driven by a declarative rule language identifies flows from untrusted sources to "
    "dangerous sinks while respecting context-specific sanitizers and validators; a typed program "
    "dependency graph supports backward, forward and security slicing; and each finding is reported "
    "with a step-by-step evidence path, a certainty level, its limitations and a remediation hint. A "
    "browser-based interface served by a lightweight HTTP API visualises the control-flow graph, the "
    "dependency graph, the data-flow sets and the slices, and reports can be exported in JSON or HTML "
    "and compared across runs. The outcome is a working, inspectable analysis tool in which compiler "
    "theory is not only applied but made visible to its user.",
]
KEYWORDS = ("Static program analysis; LR parsing; control-flow graph; data-flow analysis; taint "
            "analysis; program dependency graph; program slicing; vulnerability detection.")

CHAPTER1 = [
    ("h2", "1.1 Background"),
    ("p", "Software security weaknesses such as operating-system command injection, SQL injection, "
          "path traversal and format-string misuse share a common structure: data that enters a program "
          "through an untrusted input reaches a sensitive operation without adequate neutralisation. "
          "The Common Weakness Enumeration catalogues these defects as CWE-78, CWE-89, CWE-22 and "
          "CWE-134 respectively {cwe}. Because the defect lies in how a value travels through the "
          "program rather than in any single statement, it can be detected reliably only by reasoning "
          "about control flow and data flow across statements and across function boundaries."),
    ("p", "That form of reasoning is precisely what a compiler performs. A compiler front end tokenises "
          "the source text, parses it into a syntax tree, resolves names and types, and builds "
          "intermediate representations such as the control-flow graph on which data-flow analyses "
          "compute facts about every program point {aho}, {kildall}. The machinery that lets an "
          "optimiser decide whether a definition reaches a use also lets a security analyser decide "
          "whether an attacker-controlled value reaches a dangerous call. Taint analysis, dependence "
          "graphs and program slicing are all extensions of these classical compiler analyses "
          "{denning}, {ferrante}, {weiser}."),
    ("p", "In practice, however, developers frequently distrust or ignore static analysis tools. "
          "Empirical studies report that unexplained warnings, high false-positive rates and the absence "
          "of a visible rationale are among the main reasons for abandoning such tools {johnson}, "
          "{christakis}, and industrial experience confirms that a result developers cannot follow is "
          "treated as a false positive whether or not it is one {bessey}. Teaching contexts face a "
          "complementary difficulty: compiler courses construct parsers and data-flow analyses, but the "
          "resulting structures are seldom applied to a concrete, security-relevant question."),
    ("p", "CodeTrace was developed in the Compiler Design Laboratory to address both concerns. It is a "
          "complete compiler front end and analysis pipeline for a C-like subset, implemented from first "
          "principles, in which the intermediate results—tokens, parser tables, syntax trees, symbol "
          "tables, control-flow graphs, data-flow sets, dependency graphs and slices—are not hidden "
          "artefacts but first-class outputs that are shown to the user and used to justify every "
          "reported vulnerability."),
    ("h2", "1.2 Problem Statement"),
    ("p", "The problem addressed by this project is the detection of injection-style vulnerabilities in "
          "source programs by static analysis in a manner that is both grounded in compiler theory and "
          "transparent to the user. Specifically, the system must:"),
    ("numbered", [
        "accept a program written in a well-defined C-like language subset and process it with genuine "
        "compiler phases—lexical analysis, LR parsing, syntax-tree construction and semantic "
        "analysis—rather than by pattern matching on text;",
        "compute the control-flow and data-flow facts required to decide whether data originating at "
        "an untrusted source can reach a sensitive sink, including flows that cross function calls "
        "through arguments and return values;",
        "respect declared sanitizers and validators so that neutralised flows are not reported, while "
        "distinguishing the context (shell command, SQL query, file path, format string) in which a "
        "sanitizer is effective;",
        "explain each finding through an evidence path over the program's own statements, state how "
        "certain the analysis is, and list explicitly what it could not establish; and",
        "expose the intermediate representations—parser diagnostics, control-flow graph, reaching "
        "definitions, live variables, dependency graph and slices—so that a reader can verify a "
        "result instead of having to trust it.",
    ]),
    ("p", "Three constraints shape the solution. The analysed program must never be executed; the rule "
          "definitions must be treated as data rather than as code; and the implementation must remain "
          "comprehensible—a single Python code base without third-party dependencies that is suitable "
          "for study and extension within a laboratory course."),
    ("h2", "1.3 Objectives & Novelty"),
    ("p", "The objectives of the project are:"),
    ("bullets", [
        "To design and implement a complete compiler front end for the CT-C subset: a lexer with precise "
        "source positions, a parser generator that produces canonical LR(1), LALR(1) and SLR(1) tables "
        "from a declarative grammar, an abstract syntax tree with source spans, and semantic analysis "
        "with scoped symbol tables and located diagnostics.",
        "To construct per-function control-flow graphs with typed edges (sequential, true, false, "
        "loop-back, break, continue, return) and reachability information.",
        "To implement the classical data-flow analyses—reaching definitions, live variables and definite "
        "assignment—as instances of one generic worklist fixpoint solver, and to expose their IN and OUT "
        "sets per basic block and per statement.",
        "To build an interprocedural taint analysis driven by a declarative, validated rule language of "
        "sources, sinks, sanitizers, validators and flows, with context-sensitive sanitisation.",
        "To derive a typed program dependency graph and backward, forward and security slices from these "
        "analyses, recording the reason for every edge and for every statement included in a slice.",
        "To report findings with a stable identity, severity, certainty, an evidence path, limitations "
        "and remediation, and to provide JSON and HTML reports with run-to-run comparison.",
        "To provide a browser-based interface that visualises every phase of the pipeline, served by a "
        "documented HTTP API.",
    ]),
    ("p", "The novelty of CodeTrace lies not in a new algorithm but in the combination and the exposure of "
          "established ones. First, the parser is generated at start-up from the grammar by the project's "
          "own LR(1) construction, and the number of automaton states and conflicts is shown to the user. "
          "Second, the same LR machinery parses the security rule language, so rule sets are validated "
          "syntactically and semantically before they influence an analysis. Third, every vulnerability "
          "report carries a step-wise evidence path, a certainty level and an explicit list of what the "
          "analysis did not establish, including the sink calls that were inspected and deliberately not "
          "reported together with the reason. Fourth, the data-flow sets, the dependency graph and the "
          "slices that justify a finding can be inspected interactively. Unlike signature-based scanners "
          "that match function names in text, CodeTrace treats a vulnerability as a property of the "
          "program's data-flow structure, and unlike production analysers it keeps the entire path from "
          "grammar to finding small enough to be read and understood."),
]

CHAPTER2 = [
    ("h2", "2.1 Existing Systems / Related Work"),
    ("p", "The project draws on four bodies of work: the theory of LR parsing and compiler front ends, "
          "the data-flow analysis frameworks developed for optimising compilers, dependence-based program "
          "analysis and slicing, and taint-based security analysis together with the tools that apply it. "
          "This section reviews each in turn and closes with the empirical literature on how developers "
          "use static analysis tools."),
    ("h3", "2.1.1 Compiler front ends and LR parsing"),
    ("p", "Knuth introduced LR(k) parsing and showed that deterministic bottom-up parsers can be "
          "constructed mechanically from a context-free grammar {knuth}. The canonical LR(1) construction "
          "is precise but produces large automata; the algorithm of DeRemer and Pennello for computing "
          "LALR(1) look-ahead sets made compact tables practical and underlies generators such as Yacc and "
          "Bison {deremer}. The textbook treatment by Aho, Lam, Sethi and Ullman covers the SLR, canonical "
          "LR and LALR constructions, the structure of the action and goto tables, and panic-mode error "
          "recovery based on viable prefixes {aho}. CodeTrace implements all three constructions and lets "
          "the user select the table mode, which makes the trade-off between automaton size and "
          "look-ahead precision directly observable."),
    ("h3", "2.1.2 Control-flow and data-flow analysis"),
    ("p", "Allen formalised control-flow analysis as operations on a directed graph of basic blocks "
          "{allen}. Kildall presented the unified lattice-based framework in which analyses such as "
          "reaching definitions are solved by iterating transfer functions to a fixed point {kildall}, "
          "and Kam and Ullman characterised the monotone frameworks for which the iterative algorithm "
          "is guaranteed to terminate with the maximal fixed point {kam}. Nielson, Nielson and Hankin give "
          "the modern formulation of these frameworks and their correctness arguments {nielson}, while "
          "Muchnick documents the engineering of worklist solvers in optimising compilers {muchnick}. "
          "Reaching definitions, live-variable analysis and definite-assignment analysis in CodeTrace are "
          "direct instances of this framework, with bit-vector domains, union or intersection as the "
          "confluence operator, and worklist iteration."),
    ("h3", "2.1.3 Dependence graphs and program slicing"),
    ("p", "Ferrante, Ottenstein and Warren introduced the program dependence graph, which unifies data "
          "and control dependences in a single structure {ferrante}. Weiser defined program slicing as the "
          "extraction of the statements that may affect the value computed at a chosen point {weiser}; "
          "Horwitz, Reps and Binkley extended slicing across procedures with the system dependence graph "
          "{horwitz}, and Tip surveyed the family of slicing techniques and their applications to "
          "debugging and program comprehension {tip}. Interprocedural analyses are made precise either "
          "through context sensitivity—the call-string and functional (summary) approaches of Sharir and "
          "Pnueli {sharir}—or through graph-reachability formulations such as IFDS {reps}. CodeTrace builds "
          "a dependence graph over statements and computes slices by graph traversal; its interprocedural "
          "reasoning uses function summaries without call-site distinction, the simpler, "
          "context-insensitive variant."),
    ("h3", "2.1.4 Taint analysis and static security analysis"),
    ("p", "Denning's lattice model of secure information flow provides the theoretical basis for tracking "
          "how data of a given classification—here, untrusted data—propagates through a program "
          "{denning}. Livshits and Lam showed that user-written source and sink specifications can be "
          "compiled into static analysers that find SQL injection and cross-site scripting in Java "
          "applications {livshits}; TAJ refined the approach for web applications and showed how to keep "
          "taint analysis precise in the presence of large libraries {tripp}. Schwartz, Avgerinos and "
          "Brumley clarified the semantics of taint propagation and the policies by which taint is "
          "introduced, propagated and checked {schwartz}. Annotation-based checkers for C such as Splint "
          "demonstrated that lightweight taint annotations can detect format-string and buffer "
          "vulnerabilities in real code {larochelle}, and Chess and West document how these ideas are "
          "packaged in industrial static analysis products {chess}. CodeTrace follows this lineage: "
          "sources, sinks and sanitizers are declared in a rule language, propagation is performed over "
          "the program's own data-flow facts, and sanitisation is context-specific, so that a shell escape "
          "removes command-context taint but leaves SQL-context taint in place."),
    ("h3", "2.1.5 Contemporary analysis tools"),
    ("p", "Yamaguchi et al. combined syntax trees, control-flow graphs and dependence graphs into the "
          "code property graph and showed that vulnerability patterns can be expressed as graph queries "
          "{yamaguchi}. GitHub's CodeQL extracts source code into a relational database and expresses "
          "vulnerability queries, including taint-tracking queries, in the object-oriented logic language "
          "QL {avgustinov}, {codeql}. Semgrep matches syntactic patterns against the abstract syntax tree "
          "and extends them with a lightweight taint mode {semgrep}; Flawfinder scans C and C++ text for "
          "risky function names and ranks the hits heuristically {flawfinder}; and the Clang Static "
          "Analyzer performs path-sensitive symbolic execution on the Clang abstract syntax tree {clang}. "
          "Table 2.1 summarises how these systems and CodeTrace differ in scope and in the way they "
          "present results. The comparison is one of design goals rather than of quality: the "
          "production tools analyse real languages at industrial scale, whereas CodeTrace analyses a "
          "teaching subset and optimises for inspectability."),
    ("table", "Table 2.1: Scope and presentation of results in related tools and in CodeTrace",
     ["Tool", "Language scope", "Program representation", "Flow analysis", "Rule specification", "Presentation of results"],
     [
         ["Flawfinder {flawfinder}", "C, C++", "Token stream", "None (lexical matching)", "Built-in database of risky functions", "Ranked hit list with CWE references"],
         ["Semgrep {semgrep}", "Many languages", "Abstract syntax tree", "Pattern matching; lightweight taint mode", "YAML rules with code patterns", "Matched location and message"],
         ["CodeQL {avgustinov}, {codeql}", "Many languages", "Relational database extracted by compiler front ends", "Global data-flow and taint libraries", "QL queries", "Source-to-sink paths in query results"],
         ["Joern / code property graph {yamaguchi}", "C, C++ and others", "Code property graph (AST + CFG + PDG)", "Data-flow traversals over the graph", "Graph queries in a Scala DSL", "Query results; graph export"],
         ["Clang Static Analyzer {clang}", "C, C++, Objective-C", "Clang AST and exploded graph", "Path-sensitive symbolic execution", "Checkers written in C++", "HTML reports with path notes"],
         ["CodeTrace (this project)", "CT-C subset", "AST, CFG, data-flow sets, dependency graph", "Worklist data-flow analyses; interprocedural taint with summaries", "Declarative rule language parsed and validated by the project's LR parser", "Evidence path, certainty, limitations, dispositions; interactive CFG, PDG, data-flow and slice views"],
     ],
     [0.95, 0.85, 1.25, 1.2, 1.15, 1.1]),
    ("h3", "2.1.6 Usability of static analysis"),
    ("p", "Johnson et al. found through developer interviews that poorly presented output, unexplained "
          "results and false positives are the principal barriers to adopting static analysis {johnson}. "
          "Christakis and Bird confirmed with a large survey that developers rank bad explanations and the "
          "lack of actionable results among the most severe pain points {christakis}. Bessey et al. report "
          "from the commercialisation of a static analyser that a correct result the developer cannot "
          "follow is, in effect, a false positive {bessey}. These observations motivated the emphasis on "
          "evidence paths, certainty levels and inspectable intermediate representations in CodeTrace."),
    ("h2", "2.2 Research Gap"),
    ("p", "The surveyed systems are mature and scale to industrial code bases, which CodeTrace does not "
          "attempt. The gap that this project addresses is deliberately narrower and concerns transparency "
          "and pedagogy. Four specific shortcomings were identified:"),
    ("bullets", [
        "**Opaque intermediate structures.** Production analysers expose their control-flow graphs, "
        "data-flow facts and dependence graphs only through query languages or debugging dumps; a user "
        "cannot normally see the reaching-definition sets or the slice that justify a result. In "
        "CodeTrace these structures are first-class, inspectable outputs of every run.",
        "**Explanations that stop at the path.** Tools that report source-to-sink paths rarely state the "
        "certainty of a result, the assumptions made (for example, that a validator rejects unsafe "
        "values) or the sinks that were examined and deliberately not reported. CodeTrace records a "
        "certainty level, a limitation list and a disposition for every inspected sink call.",
        "**Rules as unchecked configuration.** Specifications are usually accepted as free-form "
        "configuration. CodeTrace parses its rule language with the same LR machinery as the source "
        "language and rejects malformed or inconsistent rule sets with located diagnostics before any "
        "analysis runs.",
        "**Distance from compiler theory.** In many tools the parser is hand-written or produced by an "
        "external generator, so the relationship between the grammar, the automaton and the diagnostics "
        "remains hidden. CodeTrace builds its tables at run time from the grammar, reports the state and "
        "conflict counts, and derives the expected-token lists in its syntax errors from the action table.",
    ]),
    ("p", "These gaps are modest in research terms but central to the goals of a compiler-design "
          "laboratory project: they make the analysis verifiable by its user and demonstrate each "
          "compiler phase on a security-relevant task. The limitations that remain in the present "
          "implementation are stated in Section 4.5."),
]

CHAPTER3 = [
    ("h2", "3.1 Proposed System Architecture"),
    ("p", "CodeTrace is organised in three layers, shown in Figure 3.1: a browser-based presentation "
          "layer, a thin HTTP service layer, and the analysis engine in which the compiler phases run. "
          "The architecture follows directly from the implementation: the frontend directory holds the "
          "single-page interface, the `codetrace.api` package implements the server, and the remaining "
          "`codetrace` packages implement the engine. The analysed program never leaves the engine as "
          "anything other than data; it is parsed and analysed, but never executed, imported or written "
          "to disk."),
    ("figure", FIG + "architecture.png",
     "Figure 3.1: Layered architecture of CodeTrace. The analysis engine runs the ten pipeline stages in order; "
     "the security rule set is a side input to semantic analysis (declared external functions) and to the taint "
     "engine (sources, sinks, sanitizers, validators and flows).", 6.3),
    ("p", "The **presentation layer** is a single-page application written in HTML, CSS and plain "
          "ECMAScript modules without a build step. It offers nine pages—Overview, Analyze Code, Findings, "
          "Program Graph, Data-Flow Analysis, Program Slicing, Rule Editor, Reports and Documentation—each "
          "of which is a view over one analysis run that the browser retrieves from the API."),
    ("p", "The **service layer** is an HTTP server built on the Python standard library. It serves the "
          "static interface, validates every request against size and parameter limits, invokes the "
          "engine, keeps completed runs in an in-memory store keyed by run identifier, and renders JSON "
          "and HTML reports on demand. It also validates rule files and compares two runs so that the "
          "interface can show which findings are new, resolved, persistent or merely moved."),
    ("p", "The **analysis layer** is the compiler-based engine. A single entry point, "
          "`analyse_source`, runs the stages in a fixed order: lexical analysis, LR parsing, abstract "
          "syntax tree construction, semantic analysis, control-flow graph construction, the data-flow "
          "analyses, interprocedural taint propagation, dependency-graph construction, slicing and "
          "finding generation. Every later stage consumes the data structures of the earlier ones, and "
          "every structure keeps the source spans and the symbol identities assigned by the front end, "
          "which is what allows a finding to point back to exact lines and columns. The rule set is a "
          "side input: semantic analysis uses it to recognise external functions, and the taint engine "
          "uses its sources, sinks, sanitizers, validators and flows."),
    ("p", "Three design principles apply across the layers. Determinism: the same input and rule set "
          "always produce the same output, including the same finding identifiers. Honesty: whenever the "
          "analysis has to approximate—an unsupported construct, an unknown external function, a validator "
          "whose behaviour is assumed—the approximation is recorded as a diagnostic, a limitation or a "
          "note rather than silently resolved. Bounded resources: the engine enforces limits on source "
          "size (512 KiB and 20,000 lines), on the number of functions and on the number of fixed-point "
          "iterations, and reports when a limit was reached."),
    ("h2", "3.2 Module Description"),
    ("p", "Table 3.1 lists the modules of the implementation and their responsibilities. The engine is "
          "written in Python 3 using only the standard library; the interface is written in standard web "
          "technologies. Module boundaries follow the compiler phases, so each phase can be read, tested "
          "and demonstrated in isolation."),
    ("table", "Table 3.1: Modules of CodeTrace and their responsibilities",
     ["Package / directory", "Modules", "Responsibility"],
     [
         ["`codetrace/frontend`", "`tokens.py`, `lexer.py`", "Token vocabulary of CT-C; hand-written deterministic scanner that records line, column and character offsets and reports lexical diagnostics (LEX codes) without stopping."],
         ["", "`grammar.py`, `grammar_lang.py`", "Grammar representation; NULLABLE, FIRST and FOLLOW computation; LR(0) and LR(1) item sets; the CT-C grammar with its semantic actions."],
         ["", "`clr_parser.py`, `pipeline.py`", "Construction of canonical LR(1), LALR(1) and SLR(1) action/goto tables with conflict detection; table-driven parser with viable-prefix error recovery; cached parser tables."],
         ["", "`ast_nodes.py`, `source.py`", "Abstract syntax tree nodes with source spans; shared source-text and diagnostic helpers."],
         ["`codetrace/semantics`", "`symbol_table.py`, `analyzer.py`, `externals.py`", "Scoped symbol tables with stable symbol identities; declaration, type and control-flow checks (SEM codes); model of external functions declared by the rule set."],
         ["`codetrace/analysis`", "`cfg.py`, `accesses.py`", "Statement numbering; per-function control-flow graphs with typed edges and reachability; extraction of the variables each statement reads and writes."],
         ["", "`dataflow.py`, `reaching_definitions.py`, `liveness.py`, `definite_assignment.py`", "Generic bit-vector worklist framework and its three instances, including per-statement states and convergence records."],
         ["", "`taint.py`, `dependencies.py`, `slicing.py`", "Interprocedural taint engine with function summaries and context-specific sanitisation; typed dependency graph with justified edges; backward, forward and security slicing."],
         ["", "`pipeline.py`", "`analyse_source`: orchestration of all stages, limits, metrics and partial-analysis bookkeeping."],
         ["`codetrace/rules`", "`rule_language.py`, `model.py`, `builtin/standard.ctrule`", "Grammar, LR parser and validator of the rule language; immutable rule-set model; the built-in rule set."],
         ["`codetrace/findings`", "`models.py`, `explain.py`", "Finding model with stable identity and run comparison; construction of evidence paths, certainty, limitations and remediation."],
         ["`codetrace/reporting`", "`json_report.py`, `html_report.py`", "Canonical JSON report (schema 1.0) and the HTML rendering derived from it."],
         ["`codetrace/api`", "`server.py`, `schemas.py`", "HTTP server, request validation, run store, routing of the JSON API; request and response schemas."],
         ["`frontend/`", "`index.html`, `css/app.css`, `js/app.js`, `js/api.js`, `js/graph.js`, `js/views/*.js`", "Single-page interface: routing and state, API client, SVG graph layout and rendering, one view module per page."],
         ["`examples/`, `docs/`", "`*.ctc`, `*.ctrule`, Markdown", "Corpus of vulnerable, sanitized, safe, interprocedural, challenging, syntactically invalid and unsupported programs; language, rule-language, API and design documentation."],
     ],
     [1.35, 1.75, 3.4]),
    ("h2", "3.3 Compiler Phases Implementation"),
    ("p", "This section explains how each phase of a compiler front end is realised in CodeTrace and how "
          "the later analysis phases build on it. The project implements analysis phases only; no code "
          "generation or optimisation is performed, because the goal is to understand the program rather "
          "than to translate it. Table 3.2 maps the phases to the components and to the evidence each "
          "phase contributes to a finding. Listing 3.1 shows the running example used throughout "
          "Chapters 3 and 4: a program in which a line read from standard input is concatenated into a "
          "shell command inside a helper function and executed in the caller."),
    ("code", [
        "// Untrusted standard input is concatenated into a shell command.",
        "string build_command(string user_input) {",
        "  return \"ls \" + user_input;",
        "}",
        "",
        "int main() {",
        "  string name = input();",
        "  string command = build_command(name);",
        "  system(command);",
        "  return 0;",
        "}",
    ]),
    ("caption", "Listing 3.1: The running example, `command_injection.ctc` from the bundled corpus (the corpus "
                "file's expectation header comment is omitted)."),
    ("table", "Table 3.2: Compiler phases implemented in CodeTrace",
     ["Phase", "Component", "Output used by later phases and by the user"],
     [
         ["Lexical analysis", "`frontend/lexer.py`", "Token stream with positions; LEX diagnostics for unsupported characters and constructs."],
         ["Syntax analysis", "`frontend/grammar.py`, `frontend/clr_parser.py`", "LR automaton and tables; parse with error recovery; SYN diagnostics with expected-token lists."],
         ["AST construction", "`frontend/ast_nodes.py`, grammar actions", "Typed tree with source spans; AST endpoint of the API."],
         ["Semantic analysis", "`semantics/*`", "Scoped symbol tables, stable symbol identities, SEM diagnostics, known externals."],
         ["Control-flow analysis", "`analysis/cfg.py`", "Basic blocks, typed edges, reachability; CFG view."],
         ["Data-flow analysis", "`analysis/dataflow.py` and instances", "Reaching definitions, live variables, definite assignment per block and per statement; data-flow view."],
         ["Dependency analysis", "`analysis/taint.py`, `analysis/dependencies.py`", "Taint facts and summaries; typed dependency graph with reasons; program-graph view."],
         ["Program slicing", "`analysis/slicing.py`", "Backward, forward and security slices with per-statement justification; slicing view."],
         ["Rule evaluation and findings", "`rules/*`, `findings/*`", "Validated rule set; findings with evidence paths, certainty, limitations, remediation; dispositions of unreported sinks."],
         ["Diagnostics and reporting", "`reporting/*`, `api/*`", "Merged diagnostics, metrics, JSON and HTML reports, run comparison."],
     ],
     [1.45, 1.9, 3.15]),
    ("h3", "3.3.1 Source processing and lexical analysis"),
    ("p", "The engine first normalises the submitted text and checks it against the input limits. The "
          "lexer is a hand-written deterministic scanner over the CT-C token vocabulary: keywords, "
          "identifiers, integer, floating-point, character and string literals, operators and "
          "punctuation. Every token records its line, column and half-open character range, and these "
          "positions are carried through all later phases so that diagnostics, graph nodes and evidence "
          "steps can be located precisely. Lexical errors do not stop the scan; the lexer reports a "
          "diagnostic and resynchronises, which lets a single run report several unrelated problems. "
          "Constructs outside the subset—for instance the `switch` keyword, pointer declarators or "
          "preprocessor directives—produce LEX100, LEX101 or LEX102 diagnostics so that the run is marked "
          "as partial rather than analysed as if the construct were understood."),
    ("h3", "3.3.2 Syntax analysis: grammar, LR tables and parsing"),
    ("p", "CT-C is defined by a context-free grammar of 102 productions written in the notation of the LR "
          "literature. The grammar covers the types `int`, `float`, `char`, `bool`, `string` and `void`, "
          "fixed-size arrays, functions with parameters, the statements `if`/`else`, `while`, `for`, "
          "`return`, `break` and `continue`, and the usual arithmetic, relational, logical and assignment "
          "expressions with operator precedence resolved by precedence declarations. From this grammar "
          "the `grammar` module computes NULLABLE, FIRST and FOLLOW by fixed-point iteration and "
          "constructs LR(0) and LR(1) item sets, following the classical algorithms {aho}, {knuth}."),
    ("p", "The `clr_parser` module builds the action and goto tables in three modes. The canonical LR(1) "
          "construction yields 656 states; merging states with identical LR(0) cores, in the manner of "
          "the LALR(1) construction {deremer}, yields 167 states; and the SLR(1) construction, which "
          "uses FOLLOW sets as look-ahead, also yields 167 states for this grammar. All three tables are "
          "conflict-free. LALR(1) is the default because it combines the small table with the precision "
          "required by the grammar; the user may select another mode per run, and the interface reports "
          "the resulting state and conflict counts. The parser itself is the standard table-driven "
          "shift-reduce driver with a state stack and a value stack."),
    ("p", "Error handling follows the viable-prefix recovery described by Aho et al. {aho}. When no action "
          "exists for the look-ahead, the parser reports a SYN001 diagnostic whose expected-token list is "
          "derived from the terminals that have an action in the current state (a reduction on the "
          "look-ahead counts as expected, which is what makes the list non-empty after a missing "
          "semicolon). It then recovers in one of three ways: an unsupported keyword or invalid token "
          "causes the enclosing statement to be skipped as a unit; otherwise, if the look-ahead can be "
          "shifted from some state on the stack, states are popped until that state is exposed; "
          "otherwise the offending token is discarded. Every recovery marks the run as partial and the "
          "number of recoveries is recorded. Section 4.4 shows the diagnostics produced for a broken "
          "expression and for an unsupported statement."),
    ("h3", "3.3.3 Abstract syntax tree and symbol tables"),
    ("p", "The semantic actions attached to the productions build an abstract syntax tree in which every "
          "node carries its source span and the line and column of its first token. Node classes exist "
          "for the translation unit, function declarations, parameters, variable declarations, each "
          "statement form and each expression form. The tree is available from the API, which is how the "
          "interface counts nodes and how the test corpus checks the shape of parsed programs."),
    ("p", "Semantic analysis walks the tree with a stack of scopes. Each declaration creates exactly one "
          "`Symbol` with an integer identity that is unique within the run; later phases refer to symbols "
          "by this identity rather than by name, which is what makes shadowed and re-declared variables "
          "unambiguous (the identifier `value` in the examples of Chapter 4 appears as `s2:value`). The "
          "analyzer reports undeclared identifiers (SEM001), duplicate declarations and redefinitions "
          "(SEM002, SEM003), type mismatches in assignments, conditions, calls and returns (SEM004, SEM005, "
          "SEM016), `void` variables and parameters (SEM006, SEM007), `break` or `continue` outside a loop "
          "(SEM012), and warnings such as shadowing (SEM018), a missing `main` function (SEM020) and lossy "
          "implicit conversions (SEM103). Calls whose target is not defined in the file are resolved "
          "against the external functions declared by the active rule set; a call to an unknown external "
          "is not treated as neutral but as a value whose taint is preserved, which keeps the analysis "
          "conservative."),
    ("h3", "3.3.4 Control-flow graph construction"),
    ("p", "After semantic analysis every statement receives a stable identifier and a control-flow graph "
          "is built for each function. The builder creates an entry block and an exit block, places "
          "straight-line statements in basic blocks, and expands structured statements into the usual "
          "shapes: an `if` produces true and false edges that rejoin after the branches, a `while` or "
          "`for` produces a loop-header block with a true edge into the body, a false edge past the loop "
          "and a loop-back edge from the end of the body, and `break`, `continue` and `return` produce "
          "edges to the loop exit, the loop header and the function exit respectively. Edges are typed "
          "with these kinds, which later lets the dependency graph attach control dependences and lets "
          "the interface draw each edge kind distinctly. A breadth-first traversal from the entry block "
          "computes reachability; statements in unreachable blocks are reported with the CFG001 "
          "diagnostic and excluded from the data-flow domains. Figure 4.8 shows the graph of a function "
          "with a loop."),
    ("h3", "3.3.5 Data-flow analysis: reaching definitions and liveness"),
    ("p", "The data-flow analyses are instances of a single framework in the `dataflow` module. A "
          "problem is described by a domain of facts represented as a bit vector, a direction, a "
          "confluence operator and, for each block, GEN and KILL sets derived from the reads and writes "
          "that the `accesses` module extracts from the syntax tree. The solver iterates a worklist of "
          "blocks until no IN or OUT set changes, records the number of iterations and the processing "
          "order, and stops with an explicit non-convergence flag if the configured iteration limit is "
          "reached. Because every transfer function is monotone over a finite lattice, termination is "
          "guaranteed in the sense of Kam and Ullman {kam}; the limit exists only as a safety bound. "
          "After the fixed point is reached the solver replays the transfer functions inside each block "
          "to obtain the state between consecutive statements, which the interface shows as per-statement "
          "IN and OUT sets. Table 3.3 summarises the three instances."),
    ("table", "Table 3.3: Data-flow problems implemented on the common worklist framework",
     ["Problem", "Direction", "Confluence", "Transfer function", "Use in CodeTrace"],
     [
         ["Reaching definitions", "Forward", "Union (may)", "OUT = GEN ∪ (IN − KILL), where GEN holds the definitions created in the block and KILL the other definitions of the same symbols", "Definition–use edges of the dependency graph; which assignments can influence a sink argument; backward slicing"],
         ["Live variables", "Backward", "Union (may)", "IN = USE ∪ (OUT − DEF)", "Statement inspector; identification of values that are computed but never used afterwards"],
         ["Definite assignment", "Forward", "Intersection (must)", "OUT = DEF ∪ IN", "Detection of variables read before any assignment on some path"],
     ],
     [1.15, 0.8, 0.95, 1.9, 1.7]),
    ("p", "For the loop in the example of Figure 4.9, the domain contains four definitions: the "
          "declarations of `value` and `i` and their assignments in the loop body. The entry block "
          "generates the two declarations and kills the two assignments; the body block does the "
          "opposite; and the loop header receives all four definitions because its IN set is the union of "
          "the OUT sets of the entry block and of the loop-back edge. The fixed point is reached after a "
          "second pass over the loop, which the processing-order display makes visible."),
    ("h3", "3.3.6 Dependency analysis and program slicing"),
    ("p", "The taint engine implements the interprocedural core of the analysis. A taint atom names a "
          "source rule and a context, for example `src:stdin@command`; a value tainted by standard input "
          "carries one atom per context (command, SQL, path, HTML, numeric and format). Within a function "
          "the engine propagates atoms along the reaching-definition facts and through expressions; "
          "across functions it computes a symbolic summary per function that records how the taint of "
          "each parameter influences the return value, and iterates the summaries to a fixed point so "
          "that recursion and mutual calls are handled. The summaries are context-insensitive in the sense "
          "of Sharir and Pnueli's functional approach without call-site distinction {sharir}: a parameter "
          "tainted at one call site is treated as tainted at every call site, and this approximation is "
          "recorded as a note in every run that crosses a function boundary. A sanitizer rule removes the "
          "atoms of the contexts it neutralises from the value it returns; a validator rule removes atoms "
          "on the CFG edge guarded by a successful check, and because this is an assumption about the "
          "validator rather than a proof, every such removal is reported as a disposition."),
    ("p", "From the symbol tables, the CFG and the taint facts, the `dependencies` module builds a typed "
          "dependency graph in the spirit of the program dependence graph of Ferrante et al. {ferrante}. "
          "Nodes represent statements, symbols at particular positions and functions; edges are of kind "
          "data, define, control, call, return, taint and sanitize, and each edge carries a textual "
          "reason derived from the analysis result that created it (for example, \"definition of "
          "'command' at line 9 reaches the read of 'command' at line 10\"). The `SliceEngine` computes "
          "slices by traversing this graph: a backward slice from a criterion statement follows edges "
          "against their direction and collects the statements that may influence it {weiser}, a forward "
          "slice follows them in their direction, and a security slice restricts the traversal to the "
          "taint-carrying edges of a particular finding. Every statement in a slice records the edges by "
          "which it was reached, and slices are truncated with an explicit flag when they exceed the "
          "configured size. Interprocedural slices use the call and return edges in the manner of the "
          "system dependence graph {horwitz}, again without call-site distinction."),
    ("h3", "3.3.7 Static security analysis and rule evaluation"),
    ("p", "Security knowledge is expressed in a small declarative rule language rather than in code. A "
          "rule file declares a version and any number of sources (functions whose return value or "
          "arguments are untrusted, with the contexts they taint), sinks (functions whose argument at a "
          "given position must not carry taint of a given context, with a category and a severity), "
          "sanitizers (functions that neutralise given contexts), validators (predicates whose true "
          "branch is assumed safe) and flows (named pairings of source and sink categories that produce "
          "findings). The language has its own grammar of 40 productions; it is parsed by the same LR "
          "machinery as CT-C, with a 78-state conflict-free LALR(1) table, and validated for unknown "
          "references, duplicate identifiers and inconsistent declarations before use. Rule files are "
          "data: they can declare functions, contexts and severities, but they contain no expressions or "
          "statements and can never execute anything. The built-in rule set models standard input, "
          "integer input, environment variables, command-line arguments and file contents as sources; "
          "`system`, `exec`, `popen`, `fopen`, `readfile`, `writefile`, `sql_exec` and `printf` as "
          "sinks; `shell_escape`, `sql_escape`, `html_escape`, `path_normalize` and `to_int` as "
          "sanitizers; `is_safe_command` and `is_valid_path` as validators; and four flows for command "
          "execution, SQL injection, path traversal and format-string misuse, corresponding to the CWE "
          "entries cited in Section 1.1 {cwe}. A custom rule set submitted with a run is merged with the "
          "built-in rules unless the user disables them."),
    ("p", "Rule evaluation is the final analytical step. For every call to a sink the engine checks "
          "whether the argument at the declared position carries an atom of the declared context whose "
          "source category is paired with the sink by an enabled flow. If it does, the `explain` module "
          "reconstructs the shortest evidence path from source to sink over the taint edges, classifies "
          "the finding and records its remediation. If it does not, the sink call is still recorded, "
          "together with the reason—no taint of the required context reached it, the statement lies in a "
          "branch whose condition is a literal constant, or the taint was cleared on a guarded edge by a "
          "declared validator—so that a user can see what was examined."),
    ("h3", "3.3.8 Diagnostics, certainty and result generation"),
    ("p", "The result of a run is a single structure that merges the diagnostics of all phases (LEX, SYN, "
          "SEM and CFG codes, each with severity, line, column, phase and detail), the findings, the "
          "graphs and the measured metrics. A finding carries a deterministic identifier derived from "
          "the rule, the sink operation and the text of the sink statement rather than from line "
          "numbers, so that inserting lines above a finding does not make it appear new; this identity "
          "is what the run comparison uses to classify findings as new, resolved, persistent or moved. "
          "Each finding also carries a certainty level: *confirmed* when the flow is straight-line "
          "within one function and fully modelled, *approximate* when the analysis had to approximate "
          "(for example, by crossing a function boundary with a context-insensitive summary or by "
          "passing through an unmodelled call), and *unproven* when the origin of the value could not be "
          "named or the path runs only under a guard already known to be false. A run is marked partial "
          "when the parser recovered from errors, when unsupported constructs were skipped or when "
          "semantic errors occurred, and the reasons are listed. The JSON report (schema version 1.0) is "
          "the canonical representation; the HTML report is rendered from the same dictionary, so the two "
          "can never disagree."),
]

CHAPTER4 = [
    ("h2", "4.1 Technology Stack and Project Structure"),
    ("p", "CodeTrace is deliberately built on a minimal technology stack so that every component can be "
          "read and understood. Table 4.1 lists the technologies and the reason each was chosen. The "
          "engine and the server require only a Python 3 interpreter; the interface requires only a "
          "modern browser; the repository contains the engine (about 12,600 lines of Python across the "
          "`codetrace` packages), the interface (about 3,000 lines of JavaScript and CSS), the example "
          "corpus, the documentation and an automated test suite."),
    ("table", "Table 4.1: Technology stack",
     ["Layer", "Technology", "Rationale"],
     [
         ["Analysis engine", "Python 3.11, standard library only (`dataclasses`, `hashlib`, `json`, `re`)", "Readable implementation of every compiler phase; no hidden parsing or analysis libraries; deterministic, dependency-free deployment."],
         ["HTTP API server", "`http.server` from the Python standard library {pydocs}, JSON over HTTP", "Small, auditable server adequate for a single-user analysis workstation; no framework configuration."],
         ["Web interface", "HTML5, CSS, ECMAScript modules; SVG for graphs", "No build toolchain; the page is served as static files and renders graphs with a small layered-layout routine written for the project."],
         ["Rule definitions", "Project-specific declarative language (`.ctrule`)", "Rules are validated data, parsed by the project's own LR parser; they cannot execute code."],
         ["Reports", "JSON (documented schema) and self-contained HTML", "Machine-readable output for tooling; human-readable output for review; identical content by construction."],
         ["Quality assurance", "`unittest` suite over the engine, API and corpus", "Every phase and every documented behaviour is exercised automatically; the corpus files state their expected outcome in a header comment."],
     ],
     [1.2, 2.4, 2.9]),
    ("h2", "4.2 Backend Implementation: Analysis Engine and HTTP API"),
    ("p", "The engine is invoked through `analyse_source(source, filename, rules, options)`, which "
          "returns an `AnalysisResult` containing the parsed program, the per-function CFGs and "
          "data-flow results, the taint facts, the dependency graph, the slice engine, the findings, the "
          "diagnostics and the metrics. The function enforces the input limits before lexing, times each "
          "stage, and records the partial-analysis reasons. All numbers shown in the interface—token, "
          "node, statement, block, edge and definition counts, iteration counts and timings—are measured "
          "by the engine for the specific run; none are estimated."),
    ("p", "The HTTP server exposes the engine through a JSON API summarised in Table 4.2. A request to "
          "`POST /api/analyze` carries the source text, a file name used in diagnostics, optional custom "
          "rules, a flag for the built-in rules, a flag for dependency-graph construction and the parser "
          "mode. The response contains the run identifier, the summary, the findings, the statements and "
          "the metrics; all other views are retrieved on demand with the run identifier, so that the "
          "potentially large graph, data-flow and slice payloads are transferred only when a page needs "
          "them. Errors use a uniform envelope with stable codes: for example, a request for an unknown "
          "run yields HTTP 404 with the code `run-not-found`, an invalid rule file yields HTTP 422 with "
          "`invalid-rules` and located diagnostics, and a slice request for a run that was analysed "
          "without dependency construction yields HTTP 409 with `slicing-unavailable`."),
    ("table", "Table 4.2: Principal endpoints of the HTTP API",
     ["Endpoint", "Purpose"],
     [
         ["`GET /api/health`, `/api/language`, `/api/grammar?mode=`, `/api/rules`, `/api/schemas`", "Engine and rule-set versions; language description; grammar, automaton and conflict report for a table mode; active rules; request and response schemas."],
         ["`GET /api/examples`, `/api/examples/{id}`", "Index and content of the bundled example programs and rule files."],
         ["`POST /api/analyze`", "Analyse a source text and create a run."],
         ["`POST /api/rules/validate`", "Parse and validate a rule file without running an analysis."],
         ["`POST /api/compare`", "Compare two runs by stable finding identity (new, resolved, persistent, moved)."],
         ["`GET /api/runs/{id}`, `/findings`, `/findings/{fid}`, `/findings/{fid}/slice`", "Run summary; findings with evidence paths; the security slice of one finding."],
         ["`GET /api/runs/{id}/ast`, `/cfg?function=`, `/dataflow?function=&analysis=`, `/graph?kinds=&limit=`", "Abstract syntax tree; control-flow graph of a function; reaching, liveness or definite-assignment results with per-statement states; dependency graph filtered by edge kind."],
         ["`GET /api/runs/{id}/statements/{sid}`, `/slice?sid=&direction=`", "Everything known about one statement; backward or forward slice from a criterion statement."],
         ["`GET /api/runs/{id}/report?format=json|html`", "JSON or HTML report of the run."],
     ],
     [3.0, 3.5]),
    ("h2", "4.3 Frontend Implementation and Analysis Workflow"),
    ("p", "The interface is a single-page application whose router maps a URL fragment to one of the nine "
          "views. A small state module holds the current run and the user's selections; each view "
          "renders from that state and requests additional data from the API client when needed. Graphs "
          "are drawn as SVG by a deterministic layered layout routine: nodes are assigned to layers by a "
          "breadth-first pass over the edges, ordered within a layer by identifier, and connected by cubic "
          "curves whose style encodes the edge kind, so the same analysis always produces the same picture. Every node is keyboard-focusable and selecting a node or a "
          "table row opens the statement inspector, which shows the reaching definitions, live variables, "
          "taint atoms and control dependences recorded for that statement. The interface offers a "
          "high-contrast mode and never evaluates analysed text as markup: all source and rule text is "
          "inserted as text nodes."),
    ("p", "A typical workflow proceeds as follows. The user opens the Analyze Code page, pastes a program "
          "or loads one of the bundled examples, optionally supplies custom rules and selects the parser "
          "table mode, and runs the analysis. The summary and the diagnostics appear immediately, together "
          "with a panel that lists the sink calls the engine inspected and the disposition of each. The "
          "Findings page then lists the findings with filters by severity, category, rule, certainty and "
          "function; selecting a finding shows its evidence path, limitations, remediation and the "
          "highlighted source context. The Program Graph page displays the dependency graph or the "
          "control-flow graph of a chosen function; the Data-Flow Analysis page displays the IN and OUT "
          "sets of the chosen problem; the Program Slicing page computes a slice from any statement; the "
          "Rule Editor validates rule files; and the Reports page exports the run and compares it with "
          "an earlier run. The screenshots in Section 4.4 follow this workflow."),
    ("h2", "4.4 Screenshots – Evidence of the Working Application"),
    ("p", "All figures in this section are unedited screenshots of the running system taken in a web "
          "browser connected to the local server; the values shown were computed by the engine for the "
          "bundled example programs. Figures 4.1 to 4.7 follow the command-injection example of Listing "
          "3.1 through the pipeline; Figures 4.8 to 4.11 use a loop-carrying example to show the "
          "control-flow graph and the data-flow analyses; Figures 4.12 to 4.14 show error detection; and "
          "Figures 4.15 to 4.17 show rule validation, sanitizer handling and reporting."),
    ("h3", "4.4.1 Analysis of a vulnerable program"),
    ("p", "Figure 4.1 shows the interface after the engine has started. The header reports the engine "
          "version, the fingerprint of the active rule set and the size of the LALR(1) automaton (167 "
          "states, 0 conflicts), and the Overview page lists the pipeline stages and the measured "
          "statistics of the most recent run."),
    ("figure", FIG + "ui-overview.png",
     "Figure 4.1: Overview page after a run, showing the navigation, the engine and grammar statistics, the "
     "measured values of the current run and the stages of the pipeline.", 6.0),
    ("p", "Figure 4.2 shows the Analyze Code page with the running example loaded. The options panel "
          "selects the parser tables, enables the built-in rules, accepts custom rules and controls "
          "dependency-graph construction. The summary reports one HIGH finding in the command-injection "
          "category, five statements in four basic blocks and seven dependency edges, and confirms that "
          "no resource limit was reached."),
    ("figure", FIG + "ui-analyze.png",
     "Figure 4.2: Analyze Code page with the command-injection example and the summary of the completed run.", 6.3),
    ("p", "The Findings page (Figure 4.3) lists the finding with its severity, category, certainty and "
          "stable identifier, and the detail panel states the flow rule, the confidence and certainty, "
          "the interprocedural nature of the reasoning, the path feasibility and the sink and source "
          "positions. Figure 4.4 shows the evidence path: eight steps lead from the call to `input()` at "
          "line 8, through the parameter and return value of `build_command`, to the argument of "
          "`system()` at line 10, each step naming the kind of step, the position and the function. "
          "Figure 4.5 shows the limitations recorded for this finding—the context-insensitive "
          "interprocedural reasoning and the static nature of the result—the remediation hint, and the "
          "source context in which the lines that take part in the finding are highlighted and the sink "
          "line is marked."),
    ("figure", FIG + "ui-findings.png",
     "Figure 4.3: Findings page with the filters, the finding card and the header of the finding detail.", 6.3),
    ("figure", FIG + "ui-evidence-path.png",
     "Figure 4.4: Evidence path of the command-injection finding: source, declaration, argument, parameter, "
     "return, call, declaration and sink steps, each with its position.", 4.2),
    ("figure", FIG + "ui-source-context.png",
     "Figure 4.5: Limitations, remediation and highlighted source context of the finding.", 4.2),
    ("p", "Figure 4.6 shows the program dependency graph of the example. The eight nodes are the "
          "statements and the symbol occurrences that take part in the flow; red edges carry taint, blue "
          "edges are the call into and the return from `build_command`, and violet edges link a statement "
          "to the definition it creates. Selecting the sink node opens the statement inspector of "
          "Figure 4.7, which lists the definitions that reach the statement, the variables live before and "
          "after it, the taint atoms present on `name` and `command` for every context, and the absence "
          "of any guarding condition."),
    ("figure", FIG + "ui-pdg.png",
     "Figure 4.6: Program dependency graph of the command-injection example with the sink statement selected; "
     "the edge-kind filters above the canvas control which edges are drawn.", 6.3),
    ("figure", FIG + "ui-statement-inspector.png",
     "Figure 4.7: Statement inspector for `system(command)`: reaching definitions, live variables, taint atoms "
     "before the statement and control dependences.", 3.0),
    ("h3", "4.4.2 Control-flow graph and data-flow analyses"),
    ("p", "The second example contains a `while` loop that appends to a string read from standard "
          "input before passing it to `system()`. Figure 4.8 shows its control-flow graph: the entry "
          "block, the loop header, the body block, the block after the loop and the exit block, with the "
          "true edge into the body, the false edge past the loop, the dotted loop-back edge from the body "
          "to the header and the return edge to the exit."),
    ("figure", FIG + "ui-cfg.png",
     "Figure 4.8: Control-flow graph of main() in the loop example, with the loop-header block selected.", 6.3),
    ("p", "Figure 4.9 shows the reaching-definitions page for the same function. The header states the "
          "domain (four definitions), the direction, the equations, the number of worklist iterations "
          "and the processing order, which visits the loop twice before the fixed point is reached. The "
          "block table lists |IN|, IN, |OUT| and OUT per block, and the per-statement table shows the "
          "states between statements: the two assignments inside the body kill the declarations of the "
          "same variables, while the loop header and the sink receive all four definitions. Figure 4.10 "
          "shows the live-variable analysis of the same function, computed backward: `value` and `i` are "
          "live throughout the loop, only `value` is live before the sink and nothing is live after it."),
    ("figure", FIG + "ui-reaching-definitions.png",
     "Figure 4.9: Reaching definitions of main() in the loop example: solver statistics, per-block IN/OUT sets "
     "and per-statement states.", 6.3),
    ("figure", FIG + "ui-live-variables.png",
     "Figure 4.10: Live-variable analysis of the same function, solved backward over the control-flow graph.", 6.3),
    ("p", "Figure 4.11 shows the Program Slicing page with the backward slice from the sink of the "
          "command-injection example. The slice contains four statements across both functions, and the "
          "right-hand column states, for each statement, the dependency edges by which it entered the "
          "slice—return, define and taint edges with the reasons recorded during dependency analysis."),
    ("figure", FIG + "ui-slice.png",
     "Figure 4.11: Backward slice from the criterion statement `system(command)` with the justification of every "
     "included statement.", 6.3),
    ("h3", "4.4.3 Error detection and partial analysis"),
    ("p", "Figures 4.12 and 4.13 show the parser's response to a syntax error. The program in Figure 4.12 "
          "contains the expression `1 + * 2`; the parser reports SYN001 at line 3, column 19, names the "
          "unexpected token and lists the tokens that would have been accepted in that state, and the "
          "run is marked as partial because the statement was skipped during recovery. Figure 4.14 shows "
          "the diagnostics for a program that uses a `switch` statement, which is outside the subset: the "
          "lexer reports the unsupported keyword and the `case` label (LEX100, LEX102) and the parser "
          "reports SYN100 for the skipped statement, so the program is not analysed as if the construct "
          "were safe."),
    ("figure", FIG + "ui-syntax-source.png",
     "Figure 4.12: Source editor with a syntactically invalid expression.", 4.2),
    ("figure", FIG + "ui-syntax-diagnostics.png",
     "Figure 4.13: Diagnostics panel for the invalid expression: the SYN001 error with position and expected-token "
     "list, and the partial-analysis notice.", 6.3),
    ("figure", FIG + "ui-unsupported-diagnostics.png",
     "Figure 4.14: Diagnostics for an unsupported `switch` statement: lexical and syntactic diagnostics mark the "
     "construct and the run as partial.", 6.3),
    ("h3", "4.4.4 Rules, sanitizers and reports"),
    ("p", "Figure 4.15 shows the Rule Editor with the example rule file loaded and validated. The file "
          "declares a source, a sink, a sanitizer and a flow for a fictional interface; the validation "
          "result reports the number of tokens parsed, that the rule parser accepted the file, and the "
          "counts and fingerprint of the resulting rule set. Figure 4.16 shows the disposition panel for "
          "the sanitized counterpart of the running example, in which the input is passed through "
          "`shell_escape()` before reaching `system()`: the sink call was inspected and not reported, and "
          "the reason is stated. Figure 4.17 shows the Reports page, where the JSON and HTML reports can be "
          "exported and the sanitized run is compared with the vulnerable run: the single finding is "
          "classified as resolved."),
    ("figure", FIG + "ui-rule-editor.png",
     "Figure 4.15: Rule Editor with the example rule file and its validation result.", 4.0),
    ("figure", FIG + "ui-dispositions.png",
     "Figure 4.16: Disposition panel for the sanitized example: the inspected sink call, the reason it was not "
     "reported and the notes recorded for the run.", 6.3),
    ("figure", FIG + "ui-reports.png",
     "Figure 4.17: Reports page with report export and the comparison of the vulnerable run with its sanitized "
     "counterpart.", 6.3),
    ("h2", "4.5 Current Progress and Challenges"),
    ("p", "All modules planned for the project have been implemented and are exercised by the automated "
          "test suite and by the bundled corpus. Table 4.3 summarises the state of each module and the "
          "constraints that remain. The limitations listed are intrinsic to the chosen scope rather than "
          "incomplete work: each is documented in the project's limitation notes and, where relevant, "
          "reported to the user inside the affected run."),
    ("table", "Table 4.3: Status of the modules and known constraints",
     ["Module", "Status", "Known constraints"],
     [
         ["Lexer and LR parser generator", "Complete", "Grammar covers the CT-C subset; pointers, structures, `switch` and preprocessor directives are reported as unsupported rather than parsed."],
         ["AST and semantic analysis", "Complete", "Array elements are not distinguished from the array as a whole; implicit conversions are only warned about."],
         ["Control-flow graph", "Complete", "Loop trip counts are not evaluated; branches on literal constants are pruned, other conditions are treated as both possible."],
         ["Data-flow analyses", "Complete", "Flow-sensitive but path-insensitive; facts are computed per function."],
         ["Taint engine", "Complete", "Explicit flows only (no implicit flow through conditions); function summaries are context-insensitive; unknown external functions preserve taint."],
         ["Dependency graph and slicing", "Complete", "Graph and slice sizes are bounded by configurable limits and truncation is reported."],
         ["Rule language and built-in rules", "Complete", "Rules describe functions by name; aliasing of function pointers is outside the language."],
         ["Findings, reports and comparison", "Complete", "Finding identity is text-based; rewriting the sink statement produces a new identity."],
         ["HTTP API and web interface", "Complete", "Runs are held in memory for the lifetime of the server process; the server is intended for local, single-user use."],
     ],
     [1.75, 0.85, 3.9]),
    ("p", "Several challenges were encountered during development. The first concerned syntax-error "
          "reporting: counting only shift actions as \"expected tokens\" produced an empty list after a "
          "missing semicolon, because the state reached before the offending token only reduces; the "
          "expected-token list therefore includes reductions on the look-ahead. The second concerned "
          "soundness in the presence of unknown functions: treating an unmodelled external call as "
          "harmless would silently drop taint, so the engine preserves taint through such calls and "
          "records the approximation as a limitation. The third concerned validators: a check such as "
          "`is_safe_command(x)` can only be trusted by assumption, so taint cleared on a guarded edge is "
          "not forgotten but surfaced as a disposition. The fourth concerned the stability of results "
          "across edits: identifying findings by line numbers made every inserted line look like a new "
          "finding, which motivated the text-based stable identity. Finally, the interface had to display "
          "potentially large graphs without external libraries, which led to the simple layered layout "
          "and the edge-kind filters and limits shown in Figure 4.6."),
    ("h2", "4.6 Conclusion and Future Enhancements"),
    ("p", "This project set out to apply the phases of a compiler front end to the detection of security "
          "vulnerabilities and to make the application visible. CodeTrace implements lexical analysis, "
          "LR parsing with tables generated from the grammar in three modes, abstract syntax trees, "
          "semantic analysis with scoped symbol tables, control-flow graph construction, worklist-based "
          "data-flow analyses, an interprocedural taint analysis driven by a validated rule language, a "
          "typed dependency graph with slicing, and finding generation with evidence paths, certainty "
          "levels and dispositions. The system is served through a documented HTTP API and a browser "
          "interface in which every intermediate representation can be inspected. The report has shown, "
          "on the bundled examples, that the pipeline detects a command-injection flow across a function "
          "boundary, explains it step by step, recognises its sanitized counterpart as safe with a stated "
          "reason, and reports syntax errors and unsupported constructs with precise positions rather "
          "than analysing them as if they were understood."),
    ("p", "Several enhancements would extend the system while preserving its design principles. "
          "Context-sensitive interprocedural analysis, following the call-string or functional approach "
          "{sharir} or a graph-reachability formulation {reps}, would remove the main source of "
          "approximate certainty. Field- and element-sensitive modelling of arrays and, eventually, of "
          "structures would widen the language subset. A path-sensitive refinement of branch conditions "
          "would let the engine discharge more guards than literal constants. Support for implicit flows "
          "would allow information-flow policies beyond explicit data dependence to be checked. On the "
          "engineering side, persistent storage of runs, an export of the dependency graph in a standard "
          "graph format, and integration of the JSON report with editor and continuous-integration "
          "tooling would make the tool usable beyond the laboratory. Each extension would be visible in "
          "the same views as the present analyses, which is the property the project set out to "
          "establish."),
]

# IEEE references keyed by citation key; numbered in order of first appearance.
REFERENCES = {
    "cwe": "MITRE Corporation, “Common Weakness Enumeration (CWE),” CWE-78, CWE-89, CWE-22 and CWE-134. [Online]. Available: https://cwe.mitre.org/ (accessed Oct. 2026).",
    "aho": "A. V. Aho, M. S. Lam, R. Sethi, and J. D. Ullman, Compilers: Principles, Techniques, and Tools, 2nd ed. Boston, MA, USA: Addison-Wesley, 2006.",
    "kildall": "G. A. Kildall, “A unified approach to global program optimization,” in Proc. 1st ACM SIGACT-SIGPLAN Symp. Principles of Programming Languages (POPL ’73), Boston, MA, USA, 1973, pp. 194–206, doi: 10.1145/512927.512945.",
    "denning": "D. E. Denning, “A lattice model of secure information flow,” Communications of the ACM, vol. 19, no. 5, pp. 236–243, May 1976, doi: 10.1145/360051.360056.",
    "ferrante": "J. Ferrante, K. J. Ottenstein, and J. D. Warren, “The program dependence graph and its use in optimization,” ACM Transactions on Programming Languages and Systems, vol. 9, no. 3, pp. 319–349, Jul. 1987, doi: 10.1145/24039.24041.",
    "weiser": "M. Weiser, “Program slicing,” IEEE Transactions on Software Engineering, vol. SE-10, no. 4, pp. 352–357, Jul. 1984, doi: 10.1109/TSE.1984.5010248.",
    "johnson": "B. Johnson, Y. Song, E. Murphy-Hill, and R. Bowdidge, “Why don’t software developers use static analysis tools to find bugs?,” in Proc. 35th Int. Conf. Software Engineering (ICSE 2013), San Francisco, CA, USA, 2013, pp. 672–681, doi: 10.1109/ICSE.2013.6606613.",
    "christakis": "M. Christakis and C. Bird, “What developers want and need from program analysis: An empirical study,” in Proc. 31st IEEE/ACM Int. Conf. Automated Software Engineering (ASE 2016), Singapore, 2016, pp. 332–343, doi: 10.1145/2970276.2970347.",
    "bessey": "A. Bessey et al., “A few billion lines of code later: Using static analysis to find bugs in the real world,” Communications of the ACM, vol. 53, no. 2, pp. 66–75, Feb. 2010, doi: 10.1145/1646353.1646374.",
    "knuth": "D. E. Knuth, “On the translation of languages from left to right,” Information and Control, vol. 8, no. 6, pp. 607–639, Dec. 1965, doi: 10.1016/S0019-9958(65)90426-2.",
    "deremer": "F. DeRemer and T. Pennello, “Efficient computation of LALR(1) look-ahead sets,” ACM Transactions on Programming Languages and Systems, vol. 4, no. 4, pp. 615–649, Oct. 1982, doi: 10.1145/69622.357187.",
    "allen": "F. E. Allen, “Control flow analysis,” ACM SIGPLAN Notices, vol. 5, no. 7, pp. 1–19, Jul. 1970, doi: 10.1145/800028.808479.",
    "kam": "J. B. Kam and J. D. Ullman, “Monotone data flow analysis frameworks,” Acta Informatica, vol. 7, no. 3, pp. 305–317, 1977, doi: 10.1007/BF00290339.",
    "nielson": "F. Nielson, H. R. Nielson, and C. Hankin, Principles of Program Analysis. Berlin, Germany: Springer, 1999.",
    "muchnick": "S. S. Muchnick, Advanced Compiler Design and Implementation. San Francisco, CA, USA: Morgan Kaufmann, 1997.",
    "horwitz": "S. Horwitz, T. Reps, and D. Binkley, “Interprocedural slicing using dependence graphs,” ACM Transactions on Programming Languages and Systems, vol. 12, no. 1, pp. 26–60, Jan. 1990, doi: 10.1145/77606.77608.",
    "tip": "F. Tip, “A survey of program slicing techniques,” Journal of Programming Languages, vol. 3, no. 3, pp. 121–189, Sep. 1995.",
    "sharir": "M. Sharir and A. Pnueli, “Two approaches to interprocedural data flow analysis,” in Program Flow Analysis: Theory and Applications, S. S. Muchnick and N. D. Jones, Eds. Englewood Cliffs, NJ, USA: Prentice-Hall, 1981, pp. 189–233.",
    "reps": "T. Reps, S. Horwitz, and M. Sagiv, “Precise interprocedural dataflow analysis via graph reachability,” in Proc. 22nd ACM SIGPLAN-SIGACT Symp. Principles of Programming Languages (POPL ’95), San Francisco, CA, USA, 1995, pp. 49–61, doi: 10.1145/199448.199462.",
    "livshits": "V. B. Livshits and M. S. Lam, “Finding security vulnerabilities in Java applications with static analysis,” in Proc. 14th USENIX Security Symposium, Baltimore, MD, USA, 2005, pp. 271–286.",
    "tripp": "O. Tripp, M. Pistoia, S. J. Fink, M. Sridharan, and O. Weisman, “TAJ: Effective taint analysis of web applications,” in Proc. 30th ACM SIGPLAN Conf. Programming Language Design and Implementation (PLDI ’09), Dublin, Ireland, 2009, pp. 87–97, doi: 10.1145/1542476.1542486.",
    "schwartz": "E. J. Schwartz, T. Avgerinos, and D. Brumley, “All you ever wanted to know about dynamic taint analysis and forward symbolic execution (but might have been afraid to ask),” in Proc. IEEE Symp. Security and Privacy, Oakland, CA, USA, 2010, pp. 317–331, doi: 10.1109/SP.2010.26.",
    "larochelle": "D. Larochelle and D. Evans, “Statically detecting likely buffer overflow vulnerabilities,” in Proc. 10th USENIX Security Symposium, Washington, DC, USA, 2001, pp. 177–190.",
    "chess": "B. Chess and J. West, Secure Programming with Static Analysis. Boston, MA, USA: Addison-Wesley, 2007.",
    "yamaguchi": "F. Yamaguchi, N. Golde, D. Arp, and K. Rieck, “Modeling and discovering vulnerabilities with code property graphs,” in Proc. IEEE Symp. Security and Privacy, San Jose, CA, USA, 2014, pp. 590–604, doi: 10.1109/SP.2014.44.",
    "avgustinov": "P. Avgustinov, O. de Moor, M. P. Jones, and M. Schäfer, “QL: Object-oriented queries on relational data,” in Proc. 30th European Conf. Object-Oriented Programming (ECOOP 2016), Leibniz International Proceedings in Informatics, vol. 56, Rome, Italy, 2016, pp. 2:1–2:25, doi: 10.4230/LIPIcs.ECOOP.2016.2.",
    "codeql": "GitHub, Inc., “CodeQL documentation.” [Online]. Available: https://codeql.github.com/docs/ (accessed Oct. 2026).",
    "semgrep": "Semgrep, Inc., “Semgrep documentation.” [Online]. Available: https://semgrep.dev/docs/ (accessed Oct. 2026).",
    "flawfinder": "D. A. Wheeler, “Flawfinder.” [Online]. Available: https://dwheeler.com/flawfinder/ (accessed Oct. 2026).",
    "clang": "LLVM Project, “Clang Static Analyzer.” [Online]. Available: https://clang-analyzer.llvm.org/ (accessed Oct. 2026).",
    "pydocs": "Python Software Foundation, “http.server — HTTP servers,” The Python Standard Library, Python 3 documentation. [Online]. Available: https://docs.python.org/3/library/http.server.html (accessed Oct. 2026).",
}

# IEEE style: periodical, book and proceedings titles in italics.
_ITALIC_TITLES = {
    "aho": ["Compilers: Principles, Techniques, and Tools"],
    "kildall": ["Proc. 1st ACM SIGACT-SIGPLAN Symp. Principles of Programming Languages (POPL ’73)"],
    "denning": ["Communications of the ACM"],
    "ferrante": ["ACM Transactions on Programming Languages and Systems"],
    "weiser": ["IEEE Transactions on Software Engineering"],
    "johnson": ["Proc. 35th Int. Conf. Software Engineering (ICSE 2013)"],
    "christakis": ["Proc. 31st IEEE/ACM Int. Conf. Automated Software Engineering (ASE 2016)"],
    "bessey": ["Communications of the ACM"],
    "knuth": ["Information and Control"],
    "deremer": ["ACM Transactions on Programming Languages and Systems"],
    "allen": ["ACM SIGPLAN Notices"],
    "kam": ["Acta Informatica"],
    "nielson": ["Principles of Program Analysis"],
    "muchnick": ["Advanced Compiler Design and Implementation"],
    "horwitz": ["ACM Transactions on Programming Languages and Systems"],
    "tip": ["Journal of Programming Languages"],
    "sharir": ["Program Flow Analysis: Theory and Applications"],
    "reps": ["Proc. 22nd ACM SIGPLAN-SIGACT Symp. Principles of Programming Languages (POPL ’95)"],
    "livshits": ["Proc. 14th USENIX Security Symposium"],
    "tripp": ["Proc. 30th ACM SIGPLAN Conf. Programming Language Design and Implementation (PLDI ’09)"],
    "schwartz": ["Proc. IEEE Symp. Security and Privacy"],
    "larochelle": ["Proc. 10th USENIX Security Symposium"],
    "chess": ["Secure Programming with Static Analysis"],
    "yamaguchi": ["Proc. IEEE Symp. Security and Privacy"],
    "avgustinov": ["Proc. 30th European Conf. Object-Oriented Programming (ECOOP 2016)"],
    "pydocs": ["The Python Standard Library"],
}
for _key, _titles in _ITALIC_TITLES.items():
    for _t in _titles:
        assert _t in REFERENCES[_key], (_key, _t)
        REFERENCES[_key] = REFERENCES[_key].replace(_t, "*" + _t + "*", 1)
