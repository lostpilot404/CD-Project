"""Build submission/CodeTrace_Project_Report.docx (python-docx required).

Run: /tmp/venv/bin/python submission/tools/build_report.py
Personal details are placeholders in [square brackets] for the team to fill in.
"""
from pathlib import Path
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Inches, RGBColor

ROOT = Path(__file__).resolve().parents[2]
SUB = ROOT / "submission"
OUT = SUB / "CodeTrace_Project_Report.docx"

doc = Document()
st = doc.styles["Normal"]
st.font.name = "Times New Roman"
st.font.size = Pt(12)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
for name, size in (("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 12)):
    s = doc.styles[name]
    s.font.name = "Times New Roman"
    s.font.size = Pt(size)
    s.font.color.rgb = RGBColor(0, 0, 0)
    s.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
for sec in doc.sections:
    sec.left_margin = sec.right_margin = Inches(1.1)
    sec.top_margin = sec.bottom_margin = Inches(1)

# settings: ask Word to refresh fields (TOC, page numbers) on open
settings = doc.settings.element
upd = OxmlElement("w:updateFields")
upd.set(qn("w:val"), "true")
settings.append(upd)

# footer with page number
fp = doc.sections[0].footer.paragraphs[0]
fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
fld = OxmlElement("w:fldSimple")
fld.set(qn("w:instr"), "PAGE")
r = OxmlElement("w:r")
t = OxmlElement("w:t")
t.text = "1"
r.append(t)
fld.append(r)
fp._p.append(fld)


def P(text="", bold=False, italic=False, align=None, size=None, space_after=6):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    run.italic = italic
    if size:
        run.font.size = Pt(size)
    if align == "c":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == "j":
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(space_after)
    return p


def BODY(text):
    return P(text, align="j")


def H(text, level=1):
    return doc.add_heading(text, level=level)


def BUL(items):
    for it in items:
        p = doc.add_paragraph(it, style="List Bullet")
        p.paragraph_format.space_after = Pt(2)


def PB():
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def TABLE(headers, rows, widths=None, caption=None):
    if caption:
        P(caption, bold=True, size=10, space_after=2)
    tb = doc.add_table(rows=1, cols=len(headers))
    tb.style = "Table Grid"
    tb.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        c = tb.rows[0].cells[i]
        c.text = ""
        run = c.paragraphs[0].add_run(h)
        run.bold = True
        run.font.size = Pt(10)
        shade(c, "D9E2F3")
    for row in rows:
        cells = tb.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(v))
            run.font.size = Pt(10)
    if widths:
        for row in tb.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return tb


def FIG(path, caption, width=6.0):
    doc.add_picture(str(path), width=Inches(width))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    P(caption, italic=True, align="c", size=10, space_after=10)


# ---------------------------------------------------------------- cover
for _ in range(3):
    P("")
P("[INSTITUTION NAME]", bold=True, align="c", size=14)
P("[School / Department]", align="c")
P("")
P("CodeTrace: A Compiler-Driven Dependency and Vulnerability Analysis Tool", bold=True, align="c", size=18)
P("")
P("Project Report — 75% Core Milestone with Measured Extension Progress", align="c", size=12)
P("")
P("Submitted by", align="c", bold=True)
P("[Student name 1] — [Register number]", align="c")
P("[Student name 2] — [Register number]", align="c")
P("")
P("Under the guidance of", align="c", bold=True)
P("[Faculty guide name, designation]", align="c")
P("")
P("[Submission month], 2026", align="c", bold=True)
PB()

# ---------------------------------------------------------------- bonafide
H("Bonafide Certificate", 1)
BODY("This is to certify that the project report entitled “CodeTrace: A Compiler-Driven Dependency and "
     "Vulnerability Analysis Tool” is a bonafide record of the work carried out by [Student name 1] "
     "([Register number]) and [Student name 2] ([Register number]) under my supervision.")
BODY("The work reported here is the progress made up to the 75% core milestone. The results in this report "
     "were produced by the commands and logs listed in Chapter 5 and in the accompanying verification files.")
P("")
P("Signature of the Guide: ______________________________", space_after=2)
P("Name: [Faculty guide name]", space_after=2)
P("Date: ____________________", space_after=12)
P("Signature of the Head of the Department: ______________________________", space_after=2)
P("Name: [HoD name]", space_after=2)
P("Date: ____________________")
PB()

# ---------------------------------------------------------------- declaration
H("Declaration", 1)
BODY("We hereby declare that the project report titled “CodeTrace: A Compiler-Driven Dependency and "
     "Vulnerability Analysis Tool” is our own work. Where we used material from other sources, the material "
     "is cited in the text and listed in the References. The software and tests described here were written "
     "by us in the repository lostpilot404/CD-Project, branch arena/cd8dc62b-cd-project.")
P("")
P("Place: [Place]", space_after=2)
P("Date: [Date]", space_after=12)
P("[Student name 1] ______________________________", space_after=8)
P("[Student name 2] ______________________________")
PB()

# ---------------------------------------------------------------- abstract
H("Abstract", 1)
BODY("Injection vulnerabilities, in which untrusted input reaches a dangerous operation such as a shell command, "
     "an SQL query or a file path, remain common. CodeTrace is a static analysis tool for a small C-like "
     "language, CT-C, that reports such source-to-sink flows with the evidence needed to check them. The front end "
     "is written from scratch: a lexer with source positions and a canonical LR(1) parser generator whose tables "
     "are checked against textbook results and against an independent builder in the test suite. The analysis "
     "builds a control-flow graph and runs reaching definitions, liveness and definite-assignment analyses, a "
     "taint analysis from declared sources to sinks, a typed program dependency graph and backward, forward and "
     "security slicing. Each finding carries a certainty level (confirmed, approximate or unproven), an evidence path "
     "and stated limitations. Unsupported or malformed syntax produces a diagnostic and marks the analysis partial; "
     "it is never silently guessed at.")
BODY("This report covers the 75% core milestone. All ten core items are implemented and verified: 304 Python tests "
     "pass, 30 frontend tests pass, 69 repository audit checks pass, the labelled 33-case corpus gives 20 true "
     "positives, no false positives or false negatives, and 18 of 18 injected faults are caught by the test suite. "
     "The core items score 75 of 75. The extension items are implemented in part and score 7.75 of 25, so the measured "
     "total is 82.75%. Section 6.3 explains this measurement and the decision it leaves to the instructor.")
PB()

# ---------------------------------------------------------------- TOC
H("Table of Contents", 1)
p = doc.add_paragraph()
def _run_with(el):
    r_ = OxmlElement("w:r"); r_.append(el); p._p.append(r_)
fc1 = OxmlElement("w:fldChar"); fc1.set(qn("w:fldCharType"), "begin"); _run_with(fc1)
instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = 'TOC \\o "1-3" \\h \\z \\u'; _run_with(instr)
fc2 = OxmlElement("w:fldChar"); fc2.set(qn("w:fldCharType"), "separate"); _run_with(fc2)
txt = OxmlElement("w:t"); txt.text = "Right-click here and choose “Update Field” to build the table of contents."; _run_with(txt)
fc3 = OxmlElement("w:fldChar"); fc3.set(qn("w:fldCharType"), "end"); _run_with(fc3)
PB()

# ---------------------------------------------------------------- chapter 1
H("1. Introduction", 1)
H("1.1 Motivation", 2)
BODY("Many security defects in software are the result of data flowing from an untrusted source, such as user input "
     "or the network, into an operation that interprets it, such as a shell command (CWE-78, OS command injection [16]), "
     "an SQL query (CWE-89), a file path (CWE-22, path traversal) or a format string (CWE-134). Finding these "
     "defects by reading code is slow, and automated tools often report results that are hard to check. A useful "
     "analysis tool must therefore show why it reports a flow, and must be explicit about what it did not analyse.")
H("1.2 Objectives", 2)
BUL([
    "Build a complete front end for a C-like subset: lexer, LR(1) parser generator, AST and semantic checks.",
    "Build classical analyses over the program: control-flow graph, reaching definitions, liveness and definite assignment.",
    "Report source-to-sink taint flows with stable identifiers, certainty levels, evidence paths and limitations.",
    "Provide a dependency graph and program slices, and an interface (HTTP API and browser UI) for running and exploring analyses.",
    "Verify the work with independent checks, not only with tests written against the same code.",
])
H("1.3 Scope and non-goals", 2)
BODY("CodeTrace analyses source text. It never runs the analysed program. It is not a sound analysis: it reports "
     "flows it can find and says where it approximates. It does not analyse full C, preprocessor directives, pointers "
     "or switch statements; these are reported as unsupported. A finding is evidence to be reviewed, not a proof of "
     "exploitability.")

# ---------------------------------------------------------------- chapter 2
H("2. Literature Review", 1)
H("2.1 Parsing", 2)
BODY("LR parsing was introduced by Knuth, who showed that the class of grammars that can be parsed deterministically "
     "from left to right with bounded lookahead is exactly the class of deterministic context-free languages [4]. "
     "DeRemer defined the simpler SLR(1) class [5], and DeRemer and Pennello gave an efficient method for computing "
     "LALR(1) lookahead sets [6]. Canonical LR(1) tables are larger than LALR(1) tables but accept more grammars [1]. "
     "The Dragon book gives the standard algorithms and the state-count examples used in this project's tests [1].")
H("2.2 Data-flow analysis", 2)
BODY("Classical data-flow analysis computes facts that hold at each program point by solving equations over a "
     "control-flow graph. Allen formalised control-flow analysis [2], and Kildall gave the unified lattice framework "
     "with a worklist algorithm [7]. Reaching definitions and liveness are standard instances [1][3]. Nielson, "
     "Nielson and Hankin present these analyses with their correctness arguments [3].")
H("2.3 Taint analysis", 2)
BODY("Taint analysis tracks data from sources of untrusted input to sensitive sinks. Dynamic taint tracking was used "
     "for exploit detection on commodity software [8]. Static taint analyses for web applications and Java were "
     "described by Livshits and Lam [9], by Vogt and colleagues for cross-site scripting [10], and by Tripp and "
     "colleagues in the TAJ system [11]. These works show that the main difficulties are the precision of the "
     "treatment of calls and the handling of sanitizers. CodeTrace treats both conservatively and labels results "
     "accordingly.")
H("2.4 Program dependence and slicing", 2)
BODY("A program slice is the subset of statements that can affect the values at a point of interest. Weiser defined "
     "slicing over the control-flow graph [12]. Ferrante, Ottenstein and Warren introduced the program dependence "
     "graph, which combines control and data dependences [13]. Horwitz, Reps and Binkley extended slicing across "
     "procedures using system dependence graphs [14], and Reps and colleagues showed that interprocedural dataflow "
     "can be solved by graph reachability [15].")
H("2.5 Gap addressed", 2)
BODY("Textbook tools and research prototypes exist for each of these parts, but this project needed one "
     "implementation in which every stage is visible, tested and tied to a stated limitation. The emphasis is on "
     "explaining each result, not on breadth of language coverage.")

# ---------------------------------------------------------------- chapter 3
H("3. System Design", 1)
H("3.1 Architecture", 2)
BODY("The system is a pipeline. Each stage consumes the output of the previous stage and produces data that is "
     "stored for the report. Figure 1 shows the stages and the modules that implement them.")
FIG(SUB / "figures" / "architecture.png", "Figure 1. CodeTrace analysis pipeline and module structure (generated by submission/tools/make_architecture_figure.py).", width=6.4)
H("3.2 Stages", 2)
TABLE(["Stage", "Module(s)", "Output"], [
    ["Lexer", "codetrace/frontend/lexer.py, tokens.py", "Tokens with offset, line and column; LEX diagnostics"],
    ["CLR(1) parser", "frontend/clr_parser.py, grammar.py", "Parse tree or SYN diagnostics with expected tokens"],
    ["AST and semantics", "frontend/ast_nodes.py, semantics/", "AST with spans; symbol table; semantic diagnostics"],
    ["Control-flow graph", "analysis/cfg.py", "Basic blocks, branches, loops, return edges, reachability"],
    ["Data-flow framework", "analysis/dataflow.py, reaching_definitions.py, liveness.py, definite_assignment.py", "Per-block and per-statement IN/OUT sets"],
    ["Taint analysis", "analysis/taint.py, accesses.py, rules/", "Source-to-sink flows with certainty and sanitizers seen"],
    ["Dependency graph", "analysis/dependencies.py", "Typed edges, each with the analysis result that justifies it"],
    ["Slicing", "analysis/slicing.py", "Backward, forward and security slices"],
    ["Findings and reports", "findings/, reporting/", "Stable finding IDs, JSON (schema 1.0) and HTML reports"],
    ["Pipeline and API", "analysis/pipeline.py, api/server.py", "Runs the stages in order; HTTP JSON API"],
    ["Web UI", "frontend/ (static HTML, JS, CSS)", "Browser views: overview, analyse, findings, graph, data-flow, slicing, rules, reports"],
], widths=[1.4, 2.6, 2.6], caption="Table 1. Pipeline stages, modules and outputs")
H("3.3 Design decisions", 2)
BUL([
    "Own parser generator. The LR(1) tables are built by the project's code, so a conflict is reported rather than hidden. The shipped grammar has 102 productions and 0 conflicts.",
    "Certainty on every finding. A finding is confirmed, approximate or unproven. A result that depends on an approximation is never labelled confirmed.",
    "Partial analysis is explicit. If the parser recovers from a syntax error, or an unsupported construct is skipped, the run is marked partial and the skipped constructs are listed.",
    "Stable identifiers. Findings are matched between runs by rule, sink operation and statement text, so that inserting a line above a finding does not make it look new.",
    "No execution. The analysed program is never run.",
])

# ---------------------------------------------------------------- chapter 4
H("4. Implementation", 1)
BODY("The engine is 39 Python modules (12,632 lines). The browser interface is 2,207 lines of JavaScript with static "
     "HTML and CSS, and is served by the same application. The implementation is in the repository "
     "lostpilot404/CD-Project. The main parts are summarised below.")
H("4.1 Front end", 2)
BODY("The lexer reports every token with its offset, line and column, and emits lexical diagnostics such as LEX001, "
     "LEX003, LEX007 and LEX008 at the position of the offending character. The parser is a canonical LR(1) parser "
     "generator. For the CT-C grammar it has 167 LALR(1) states and no conflicts; a separate builder in the test suite "
     "gives 656 canonical LR(1) states for the same grammar, and the test suite also checks the textbook state counts "
     "and the LR(1)-but-not-LALR(1) example. Syntax diagnostics list the tokens the parser expected at the error point. "
     "This list is built from both shift and reduce actions; an earlier version counted only shifts and so printed "
     "“expected one of: nothing”, which was fixed and is covered by a regression test.")
H("4.2 Analyses", 2)
BODY("The control-flow graph is built from the AST. Reaching definitions and liveness are solved with a worklist over "
     "the CFG; the browser shows the equations, the number of iterations and the per-statement IN and OUT sets. "
     "Definite assignment reports variables that may be read before assignment. Taint propagates from declared "
     "sources through assignments, expressions and calls, using conservative summaries for user-defined functions. "
     "Known sanitizers, such as shell escaping, SQL escaping and integer parsing, are recognised and recorded on the "
     "finding. The dependency graph joins control, data and call dependences, and slicing traverses it.")
H("4.3 Rules", 2)
BODY("Sources, sinks and flows are described by a rule set. The built-in rule set (identifier builtin-3387b7dcd97a95f3) "
     "has 5 sources, 8 sinks and 4 flows. Users can add rules in the rule language, which is validated before use: "
     "a rule that names an unknown selector is rejected.")
H("4.4 Interface", 2)
BODY("The HTTP API serves the analysis results as JSON and is documented in docs/API.md. The browser interface offers "
     "nine views. It does not analyse code itself; it calls the API. Findings can be exported as JSON and as a "
     "self-contained HTML report that escapes all analysed source text.")

# ---------------------------------------------------------------- chapter 5
H("5. Testing and Results", 1)
H("5.1 Verification commands", 2)
BODY("Every result below comes from a command run in the project sandbox. The exit codes and logs are kept in the "
     "repository under submission/evidence/. Table 2 lists the gates.")
TABLE(["Gate", "Command", "Result"], [
    ["Python tests", "python3 -m unittest discover -s tests -t . -v", "304 tests, OK"],
    ["Frontend tests", "npm test (in frontend/)", "30 pass, 0 fail"],
    ["Repository audit", "python3 scripts/audit.py -v", "69 checks passed"],
    ["Corpus evaluation", "scripts/evaluate.sh", "TP 20, FP 0, FN 0; TN 9/9; precision, recall, F1 = 1.0"],
    ["Mutation check", "python3 scripts/mutation_check.py (fresh clone)", "18 of 18 mutations caught"],
], widths=[1.5, 2.9, 2.2], caption="Table 2. Verification gates (2026-10-13)")
H("5.2 Independent checks", 2)
BODY("To avoid testing the engine only against its own output, three independent checks were added:")
BUL([
    "LR(1) theory (9 tests): FIRST and FOLLOW sets against textbook values, the Dragon-book state counts, the LR(1)-but-not-LALR(1) grammar, and an independent LR(0)/canonical LR(1) builder that gives 656 and 167 states for CT-C.",
    "Hand-labelled taint battery (7 tests): 32 small programs whose expected sink lines were labelled by reading the source. Three labels written from memory were wrong at first; they were corrected against the source. The first-run output is kept as evidence (10 of 13 matched) together with the corrected run (13 of 13).",
    "Hand-worked probes for the CFG, reaching definitions, symbol identity and semantic errors, whose outputs were worked out on paper before being compared with the engine.",
])
H("5.3 Corpus", 2)
BODY("The corpus has 33 labelled files: 20 vulnerable programs, each with one expected finding, and 9 safe or sanitized "
     "programs with none, plus interprocedural cases. The evaluation found all 20 expected findings and reported no "
     "others. The corpus is small and hand-written, so these figures are a regression signal and not an estimate of "
     "real-world detection rates. The evaluation JSON says the same thing.")
H("5.4 Mutation check", 2)
BODY("The mutation check introduces one fault at a time into a clean copy of the code and checks that the test suite "
     "fails. All 18 faults were caught, including faults in rule validation and in report limitations.")
H("5.5 Browser results", 2)
BODY("The application was started and driven in headless Chromium. Ten screenshots were captured with no console or "
     "page errors. The figures below show the main views. Figure 2 shows the run on the vulnerable example; Figure 3 "
     "the finding and its evidence path.")
FIG(SUB / "screenshots" / "02-analyze-vulnerable-run.png", "Figure 2. Analyse Code page after running the command-injection example.", width=6.2)
FIG(SUB / "screenshots" / "03-findings-list-and-detail.png", "Figure 3. Findings list and detail: HIGH severity, approximate certainty, and an 8-step evidence path from source to sink.", width=6.2)
FIG(SUB / "screenshots" / "04-program-graph.png", "Figure 4. Program graph with typed dependency edges.", width=6.2)
FIG(SUB / "screenshots" / "08-safe-counterpart-zero-findings.png", "Figure 5. Safe counterpart: no findings, and the page says that this is not a proof that the program is safe.", width=6.2)
FIG(SUB / "screenshots" / "09-syntax-error.png", "Figure 6. Syntax-error diagnostics after the fix: the expected-token list names real tokens, and the analysis is marked partial.", width=6.2)
FIG(SUB / "screenshots" / "10-unsupported-switch.png", "Figure 7. Unsupported switch statement: reported as unsupported and not guessed at.", width=6.2)
H("5.6 Defects found and fixed in this phase", 2)
TABLE(["#", "Defect", "Fix"], [
    ["1", "Top-bar badge showed 'undefined states' when the grammar summary was missing.", "Frontend reads the real grammar summary; covered by frontend tests."],
    ["2", "A semantic error could leave a run marked complete.", "Run is marked partial with the reason; 2 new semantic tests."],
    ["3", "Syntax errors said 'expected one of: nothing'.", "Expected list counts reduce actions; regression test added."],
    ["4", "Program graph too small to read on wide inputs.", "Graph and CSS changed; renders at natural width."],
    ["5", "Documentation had stale counts and omitted two approximations.", "Docs updated; module table checked against the tree."],
    ["6", "Three taint-battery labels were wrong.", "Labels corrected against the source lines."],
], widths=[0.4, 3.0, 3.2], caption="Table 3. Defects found in this phase")
H("5.7 Known limits", 2)
BUL([
    "After a missing semicolon the error is reported at the next token, not at the end of the previous line, and ';' is not in the expected list.",
    "Pointer syntax produces a generic 'unexpected *' syntax error rather than an unsupported-construct message.",
    "Implicit (control-dependence) flows are not tracked as taint.",
    "Interprocedural analysis uses summaries and is not context-sensitive.",
    "Interval and range reasoning are not implemented; only literal-false branch pruning and validator guards are.",
    "Loops are over-approximated: a loop that may run zero times is treated as possibly executed, so its taint result is approximate.",
])

# ---------------------------------------------------------------- chapter 6
H("6. Progress Against the Rubric", 1)
H("6.1 Core items (75 points)", 2)
TABLE(["Item", "Points", "Status", "Evidence"], [
    ["C1 Architecture, entry point, HTTP API", "5", "Verified", "37 API tests"],
    ["C2 Lexer with positions and diagnostics", "8", "Verified", "19 lexer tests; position probe"],
    ["C3 Canonical LR(1) parser and conflicts", "12", "Verified", "27 parser tests; 9 theory tests; 0 conflicts"],
    ["C4 AST and source locations", "7", "Verified", "27 parser tests; span probes"],
    ["C5 Symbols, scopes, semantic checks", "7", "Verified", "20 semantics tests; symbol probe"],
    ["C6 Control-flow graph", "9", "Verified", "15 CFG tests; shape probe"],
    ["C7 Reaching definitions and liveness", "9", "Verified", "26 data-flow tests; hand-check probe"],
    ["C8 Intraprocedural taint", "9", "Verified", "40 taint tests; 32-case battery"],
    ["C9 Findings, evidence, JSON/HTML reports", "5", "Verified", "24 reporting tests; exported report"],
    ["C10 Tests, documentation, claims", "4", "Verified", "304 + 30 tests; 69 audit checks; 18/18 mutations"],
    ["Total", "75", "75 / 75 measured", ""],
], widths=[2.6, 0.7, 1.2, 2.2], caption="Table 4. Core items")
H("6.2 Extension items (25 points)", 2)
TABLE(["Item", "Max", "Measured", "Status"], [
    ["E1 Rule language and sanitizers", "5", "2.5", "Implemented, partly verified (50%)"],
    ["E2 Context-sensitive interprocedural analysis", "5", "1.25", "In progress (25%)"],
    ["E3 Dependency graph and slicing", "5", "2.5", "Implemented, partly verified (50%)"],
    ["E4 Branch feasibility and range reasoning", "3", "0.75", "In progress (25%)"],
    ["E5 External benchmark", "3", "0.75", "In progress (25%)"],
    ["E6 CI, performance, extra export formats", "4", "0", "Not started"],
    ["Total", "25", "7.75", ""],
], widths=[2.8, 0.6, 1.0, 2.2], caption="Table 5. Extension items (measured, not rounded)")
H("6.3 Overall measurement and decision point", 2)
BODY("The core milestone is 75 of 75 and is fully verified. The measured overall total is 82.75 of 100 (82.75%). "
     "The extension figures are recorded as measured. The instructor should decide whether the milestone is reported "
     "as the core 75% only, or as the measured total. This report does not make that choice for the team.")
H("6.4 Remaining work", 2)
BUL([
    "E6: continuous integration, a timing benchmark and at least one more export format.",
    "E2: context-sensitive procedure summaries and tests for them.",
    "E4: an interval domain for integer guards.",
    "E5: an external labelled benchmark, with precision and recall reported with their uncertainty.",
    "E1 and E3: wider sanitizer models and more slicing cases.",
])

# ---------------------------------------------------------------- chapter 7
H("7. Conclusion and Future Work", 1)
BODY("CodeTrace meets the 75% core milestone. It analyses a small C-like language from source text to source-to-sink "
     "findings, and every stage has an explicit output, a test, and a stated limitation. The most useful result of "
     "this phase was not a new feature but the set of checks that found real defects: a wrong badge, a complete-looking "
     "run that was partial, an empty syntax-error list, and mislabelled tests. Each was fixed and is covered by a "
     "regression test or a documented limit.")
BODY("Future work is the remaining extension scope listed in Section 6.4. The most important is an external benchmark, "
     "because the current corpus is hand-written and small.")

# ---------------------------------------------------------------- references
H("References", 1)
refs = [
    "[1] A. V. Aho, M. S. Lam, R. Sethi and J. D. Ullman, Compilers: Principles, Techniques, and Tools, 2nd ed. Pearson, 2006.",
    "[2] F. E. Allen, “Control flow analysis,” ACM SIGPLAN Notices, vol. 5, no. 7, pp. 1–19, 1970.",
    "[3] F. Nielson, H. R. Nielson and C. Hankin, Principles of Program Analysis. Springer, 1999.",
    "[4] D. E. Knuth, “On the translation of languages from left to right,” Information and Control, vol. 8, no. 6, pp. 607–639, 1965.",
    "[5] F. L. DeRemer, “Simple LR(k) grammars,” Communications of the ACM, vol. 14, no. 7, pp. 453–460, 1971.",
    "[6] F. DeRemer and T. Pennello, “Efficient computation of LALR(1) look-ahead sets,” ACM Transactions on Programming Languages and Systems, vol. 4, no. 4, pp. 615–649, 1982.",
    "[7] G. A. Kildall, “A unified approach to global program optimization,” in Proc. ACM POPL, 1973.",
    "[8] J. Newsome and D. Song, “Dynamic taint analysis for automatic detection, analysis, and signature generation of exploits on commodity software,” in Proc. NDSS, 2005.",
    "[9] V. B. Livshits and M. S. Lam, “Finding security vulnerabilities in Java applications with static analysis,” in Proc. USENIX Security Symposium, 2005.",
    "[10] P. Vogt, F. Nentwich, N. Jovanovic, E. Kirda, C. Kruegel and G. Vigna, “Cross site scripting prevention with dynamic data tainting and static analysis,” in Proc. NDSS, 2007.",
    "[11] O. Tripp, M. Pistoia, S. J. Fink, M. Sridharan and O. Weisman, “TAJ: Effective taint analysis of web applications,” in Proc. ACM PLDI, 2009.",
    "[12] M. Weiser, “Program slicing,” IEEE Transactions on Software Engineering, vol. SE-10, no. 4, pp. 352–357, 1984.",
    "[13] J. Ferrante, K. J. Ottenstein and J. D. Warren, “The program dependence graph and its use in optimization,” ACM Transactions on Programming Languages and Systems, vol. 9, no. 3, pp. 319–349, 1987.",
    "[14] S. Horwitz, T. Reps and D. Binkley, “Interprocedural slicing using dependence graphs,” ACM Transactions on Programming Languages and Systems, vol. 12, no. 1, pp. 26–60, 1990.",
    "[15] T. Reps, S. Horwitz, M. Sagiv and G. Rosay, “Precise interprocedural dataflow analysis via graph reachability,” in Proc. ACM POPL, 1995.",
    "[16] MITRE, “CWE-78: Improper neutralization of special elements used in an OS command,” cwe.mitre.org/data/definitions/78.html.",
]
for r_ in refs:
    p = doc.add_paragraph(r_)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.left_indent = Inches(0.3)
    p.paragraph_format.first_line_indent = Inches(-0.3)
P("Note: the bibliographic details above were written from the team's reference knowledge and must be checked against "
  "the library catalogue or the publisher before submission.", italic=True, size=10)

# ---------------------------------------------------------------- appendix
H("Appendix A. Evidence Index", 1)
TABLE(["Evidence", "Location in repository"], [
    ["Verification report (commands, results, limits)", "submission/VERIFICATION_REPORT.md"],
    ["Progress against rubric", "submission/PROGRESS_STATUS.md"],
    ["Demo script", "submission/DEMO_SCRIPT.md"],
    ["Test, audit, evaluation and mutation logs", "submission/evidence/logs/"],
    ["Probe outputs (hand-worked checks)", "submission/evidence/logs/probe_*.txt"],
    ["Taint battery outputs (first run and corrected run)", "submission/evidence/logs/battery_2_first_run.txt, battery_2.txt"],
    ["Exported report for command injection", "submission/evidence/report_command_injection.json and .html"],
    ["Browser capture summaries", "submission/evidence/ui_*.txt"],
    ["Screenshots", "submission/screenshots/01–10"],
    ["Architecture figure and its generator", "submission/figures/architecture.png; submission/tools/make_architecture_figure.py"],
    ["Probe and battery sources", "submission/tools/probes/"],
], widths=[2.8, 3.8], caption="Table A1. Where the evidence is")

doc.save(OUT)
print("wrote", OUT)
