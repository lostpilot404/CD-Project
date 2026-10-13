"""Draw the CodeTrace pipeline figure used in the project report.

Run: python3 submission/tools/make_architecture_figure.py
Output: submission/figures/architecture.png (needs matplotlib; not a runtime dependency).
Module names follow the repository layout under codetrace/.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "figures" / "architecture.png"
W, H, DX, DY = 2.9, 1.05, 3.4, 1.9

# name -> (column, row, title, module list)
boxes = {
    "src":   (0, 2, "Source text (CT-C)", "examples/, user paste or upload"),
    "lex":   (1, 2, "Lexer", "frontend/lexer.py, tokens.py"),
    "clr":   (2, 2, "CLR(1) parser", "frontend/clr_parser.py, grammar.py"),
    "ast":   (3, 2, "AST + semantics", "frontend/ast_nodes.py, semantics/"),
    "cfg":   (4, 2, "Control-flow graph", "analysis/cfg.py"),
    "df":    (4, 1, "Data-flow framework", "analysis/dataflow.py,\nreaching_definitions.py, liveness.py,\ndefinite_assignment.py"),
    "taint": (3, 1, "Taint analysis", "analysis/taint.py, accesses.py, rules/"),
    "dep":   (2, 1, "Dependency graph", "analysis/dependencies.py"),
    "slice": (1, 1, "Slicing", "analysis/slicing.py"),
    "find":  (3, 0, "Findings + evidence", "findings/models.py, explain.py"),
    "rep":   (2, 0, "Reports", "reporting/json_report.py,\nhtml_report.py"),
    "api":   (0, 0, "API server", "api/server.py, api/schemas.py"),
}
# edges: (from, to, direction) direction: 'r' = from's right side to to's left side ... computed below
edges = [("src", "lex"), ("lex", "clr"), ("clr", "ast"), ("ast", "cfg"),
         ("cfg", "df"), ("df", "taint"), ("taint", "dep"), ("dep", "slice"),
         ("taint", "find"), ("find", "rep")]

def xy(name):
    c, r, _, _ = boxes[name]
    return c * DX, r * DY

fig, ax = plt.subplots(figsize=(16, 8))
for name, (c, r, title, mods) in boxes.items():
    x, y = xy(name)
    ax.add_patch(FancyBboxPatch((x, y), W, H, boxstyle="round,pad=0.03",
                                fc="#eef4fb", ec="#1f4e8c", lw=1.4))
    ax.text(x + W / 2, y + H - 0.25, title, ha="center", va="center",
            fontsize=10.5, weight="bold", color="#10305a")
    ax.text(x + W / 2, y + 0.3, mods, ha="center", va="center", fontsize=7.4, color="#333")

def mid(name, side):
    x, y = xy(name)
    return {"l": (x, y + H / 2), "r": (x + W, y + H / 2),
            "t": (x + W / 2, y + H), "b": (x + W / 2, y)}[side]

def arrow(a, b, sa, sb):
    (x1, y1), (x2, y2) = mid(a, sa), mid(b, sb)
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color="#555", lw=1.2,
                                shrinkA=1, shrinkB=1))

arrow("src", "lex", "r", "l")
arrow("lex", "clr", "r", "l")
arrow("clr", "ast", "r", "l")
arrow("ast", "cfg", "r", "l")
arrow("cfg", "df", "b", "t")
arrow("df", "taint", "l", "r")
arrow("taint", "dep", "l", "r")
arrow("dep", "slice", "l", "r")
arrow("taint", "find", "b", "t")
arrow("find", "rep", "l", "r")

# Web UI box placed under API as a separate element
ux, uy = 0 * DX, -1.9
ax.add_patch(FancyBboxPatch((ux, uy), W, H, boxstyle="round,pad=0.03",
                            fc="#fff7e8", ec="#b06a00", lw=1.4))
ax.text(ux + W / 2, uy + H - 0.25, "Web UI (browser)", ha="center", va="center",
        fontsize=10.5, weight="bold", color="#6b4300")
ax.text(ux + W / 2, uy + 0.3, "frontend/ (static HTML, JS, CSS)", ha="center", va="center",
        fontsize=7.4, color="#333")
ax.annotate("", xy=(ux + W / 2, uy + H), xytext=(ux + W / 2, 0.0),
            arrowprops=dict(arrowstyle="<|-|>", color="#b06a00", lw=1.2, shrinkA=1, shrinkB=1))
ax.text(ux + W / 2 + 0.12, -0.45, "JSON over HTTP", fontsize=7.4, color="#6b4300")

ax.text(0.0, -2.75,
        "analysis/pipeline.py coordinates the stages in order. Every finding keeps its certainty "
        "(confirmed / approximate / unproven),\nits data-flow path and its limitations. "
        "Unsupported or malformed syntax produces a diagnostic and marks the analysis partial.\n"
        "The browser never runs analysis; it calls the API, which runs the pipeline on the server.",
        fontsize=9, color="#333", va="top")
ax.set_xlim(-0.4, 4 * DX + W + 0.4)
ax.set_ylim(-3.4, 2 * DY + H + 0.5)
ax.set_aspect("equal")
ax.axis("off")
ax.set_title("Figure 1. CodeTrace analysis pipeline and module structure", fontsize=12, loc="left")
OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print("wrote", OUT)
