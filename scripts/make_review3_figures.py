#!/usr/bin/env python3
"""Draw the Review 3 report figures from the engine's own output.

One figure in the Review 3 report is not a drawing of the design but a drawing of a
result: the typed dependency graph of ``examples/vulnerable/command_injection.ctc``,
built by running the pipeline on that file and plotting the graph it returns. Every
node label, every edge kind and every edge count in the picture therefore comes from
the analysis, and a change in the engine shows up in the figure only if it changes the
analysis.

    python3 scripts/make_review3_figures.py

Writes ``docs/review3_report_assets/fig_dependency_graph.png`` (and copies the
institute mark beside it). Requires matplotlib at build time only.
"""

from __future__ import annotations

import os
import shutil
import sys

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
except ImportError:  # pragma: no cover - build-time dependency
    sys.exit("matplotlib is required: pip install matplotlib")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "docs", "review3_report_assets")
SOURCE = os.path.join(ROOT, "examples", "vulnerable", "command_injection.ctc")
REVIEW2_ASSETS = os.path.join(ROOT, "docs", "review2_report_assets")

sys.path.insert(0, ROOT)
from codetrace.analysis.pipeline import analyse_source  # noqa: E402

INK = "#111111"
EDGE = "#3a3f47"
MUTED = "#5a5f66"
PATH_RED = "#8c1d18"

#: How each dependency edge is drawn: colour, dash pattern and the legend wording.
EDGE_STYLE = {
    "define": ("#3a3f47", "solid", "definition of a name"),
    "taint": ("#8c1d18", "solid", "taint: the definition carries untrusted data"),
    "data": ("#3a3f47", "solid", "data: a reaching definition"),
    "call": ("#1f3f6b", "solid", "call: statement to callee"),
    "return": ("#1f3f6b", (0, (5, 2)), "return: callee value to the call"),
    "source-to-sink": (PATH_RED, (0, (4, 2)), "source-to-sink: the reported path"),
    "control": ("#3a3f47", (0, (1, 2)), "control: guarded by a condition"),
    "sanitize": ("#2f6b3f", "solid", "sanitize: a rule removes the taint"),
}

#: The layout, in figure coordinates. The engine decides *what* is drawn; this table
#: only decides where each node sits, because a graph drawing has to be placed by hand
#: to stay readable at page width.
POSITIONS = {
    # column one: the callee, its parameter definition and its return statement
    "f:build_command": (0.15, 0.93),
    "d0": (0.15, 0.76),
    "s0": (0.15, 0.59),
    # column two: the caller's statements, in program order
    "f:main": (0.50, 0.93),
    "s1": (0.50, 0.76),
    "s2": (0.50, 0.59),
    "s3": (0.50, 0.42),
    "s4": (0.50, 0.31),
    # column three: the definitions those statements create
    "d1": (0.83, 0.76),
    "d2": (0.83, 0.59),
}

#: Box width in figure coordinates; text is wrapped to fit inside it.
BOX_WIDTH = 0.27
BOX_HEIGHT = 0.075


def wrap(text, width=26):
    """Break a label at spaces so it fits the box; long identifiers stay whole."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:2]


def node_box(ax, x, y, node):
    """Draw one node as a rounded box with its label and its source position."""
    fill = "#f2f2f2" if node.kind in ("function",) else "white"
    if node.kind == "definition":
        fill = "#f7f7f7"
    box = FancyBboxPatch(
        (x - BOX_WIDTH / 2, y - BOX_HEIGHT / 2), BOX_WIDTH, BOX_HEIGHT,
        boxstyle="round,pad=0.004,rounding_size=0.012",
        linewidth=0.9, edgecolor=EDGE, facecolor=fill, zorder=3,
    )
    ax.add_patch(box)
    lines = wrap(node.label)
    top = y + 0.014 + (0.010 if len(lines) == 2 else 0)
    for index, line in enumerate(lines):
        ax.text(x, top - index * 0.019, line, ha="center", va="center", fontsize=7.6,
                color=INK, fontweight="bold" if node.kind == "function" else "normal", zorder=4)
    if node.kind == "function":
        sub = "function"
    elif node.kind == "definition":
        sub = f"definition \u00b7 line {node.line}"
    else:
        sub = f"{node.kind} \u00b7 line {node.line} \u00b7 {node.function}()"
    ax.text(x, y - 0.023, sub, ha="center", va="center", fontsize=6.2, color=MUTED, zorder=4)


def draw_edge(ax, start, end, colour, style, width):
    """Draw one arrow between two boxes, leaving and entering at their borders."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    if abs(dy) >= abs(dx) * 1.2:
        tail = (start[0], start[1] + (BOX_HEIGHT / 2 if dy > 0 else -BOX_HEIGHT / 2))
        head = (end[0], end[1] - (BOX_HEIGHT / 2 if dy > 0 else -BOX_HEIGHT / 2))
        curve = 0.0
    else:
        tail = (start[0] + (BOX_WIDTH / 2 if dx > 0 else -BOX_WIDTH / 2), start[1])
        head = (end[0] - (BOX_WIDTH / 2 if dx > 0 else -BOX_WIDTH / 2), end[1])
        curve = 0.18
    arrow = FancyArrowPatch(
        tail, head, arrowstyle="-|>", mutation_scale=9, linewidth=width,
        color=colour, linestyle=style, zorder=2, shrinkA=2.0, shrinkB=2.0,
        connectionstyle=f"arc3,rad={curve}",
    )
    ax.add_patch(arrow)


def draw(graph, out_path):
    fig, ax = plt.subplots(figsize=(6.6, 5.0))
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0.185, 1.0)
    ax.axis("off")

    for node_id, node in graph.nodes.items():
        x, y = POSITIONS[node_id]
        node_box(ax, x, y, node)

    for edge in graph.edges:
        if edge.src not in POSITIONS or edge.dst not in POSITIONS:
            continue
        colour, style, _ = EDGE_STYLE.get(edge.kind, (EDGE, "solid", edge.kind))
        draw_edge(ax, POSITIONS[edge.src], POSITIONS[edge.dst], colour, style,
                  1.7 if edge.kind == "source-to-sink" else 1.0)

    # the legend names only the kinds this graph contains, in the order they occur
    present = []
    for edge in graph.edges:
        if edge.kind not in present:
            present.append(edge.kind)
    handles = []
    for kind in present:
        colour, style, wording = EDGE_STYLE.get(kind, (EDGE, "solid", kind))
        line, = ax.plot([], [], color=colour, linestyle=style, linewidth=1.4, label=wording)
        handles.append(line)
    # the legend sits under the drawing, in two columns, so that it can never overlap a
    # node: a graph drawing has to be placed by hand, and a legend placed "somewhere"
    # will eventually collide with something
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.012, 0.012),
               ncol=2, frameon=False, fontsize=6.9, handlelength=2.4, labelspacing=0.34,
               columnspacing=1.6,
               title=(f"{len(graph.nodes)} nodes and {len(graph.edges)} edges, all computed by "
                      "the engine; every edge kind below occurs in this graph"),
               title_fontsize=6.9, alignment="left")

    fig.subplots_adjust(left=0.005, right=0.995, top=0.995, bottom=0.175)
    fig.savefig(out_path, dpi=300, facecolor="white")
    plt.close(fig)
    print(f"wrote {out_path} ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")


def main() -> int:
    os.makedirs(ASSETS, exist_ok=True)
    with open(SOURCE, encoding="utf-8") as handle:
        source = handle.read()
    program = analyse_source(source, os.path.basename(SOURCE))
    draw(program.dependencies, os.path.join(ASSETS, "fig_dependency_graph.png"))

    logo = os.path.join(REVIEW2_ASSETS, "vit_logo.png")
    if os.path.exists(logo):
        shutil.copyfile(logo, os.path.join(ASSETS, "vit_logo.png"))
        print("copied the institute mark")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
