#!/usr/bin/env python3
"""Build the figure assets used by the Review 2 report.

Two kinds of asset live in ``docs/review2_report_assets``:

* ``vit_logo.png`` - the institute mark, lifted from the report template, and
  ``fig_pipeline.png`` / ``fig_evidence_flow.png`` / ``fig_program_graph.png`` -
  the diagrams already published with the Review 2 material, re-extracted from
  the submitted PDF so the Word report and the PDF agree.
* ``fig_architecture.png`` - the runtime architecture diagram drawn for
  Chapter 3.

Only the diagrams are generated here; the remaining assets are extracted once
and committed, so this script is reproducible without the source PDFs.

    python3 scripts/make_review2_figures.py [--r2 R2.pdf] [--template Template.pdf]

Requires matplotlib (build-time only).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "docs", "review2_report_assets")

INK = "#111111"
EDGE = "#4a5568"
HEADER = "#e8edf7"
ACCENT = "#2f5496"


def _rectangle(ax, x, y, w, h, text="", size=9, bold=False, fill="white", edge=EDGE,
               radius=0.06, color=INK, align="center", mono=False):
    from matplotlib.patches import FancyBboxPatch

    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0.005,rounding_size={radius}",
        linewidth=1.0, edgecolor=edge, facecolor=fill, zorder=2,
    )
    ax.add_patch(box)
    if text:
        family = "DejaVu Sans Mono" if mono else "DejaVu Sans"
        if align == "center":
            ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                    fontsize=size, color=color, fontweight="bold" if bold else "normal",
                    family=family, zorder=3, linespacing=1.35)
        else:
            ax.text(x + 0.12, y + h / 2, text, ha="left", va="center",
                    fontsize=size, color=color, fontweight="bold" if bold else "normal",
                    family=family, zorder=3, linespacing=1.35)
    return box


def _arrow(ax, start, end, label=None, style="<->", size=8):
    ax.annotate(
        "", xy=end, xytext=start,
        arrowprops=dict(arrowstyle=style, color=INK, linewidth=1.1, shrinkA=2, shrinkB=2),
        zorder=4,
    )
    if label:
        ax.text((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + 0.16, label,
                ha="center", va="bottom", fontsize=size, color=INK, style="italic", zorder=5)


def architecture():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11.6, 6.2), dpi=220)
    ax.set_xlim(0, 11.6)
    ax.set_ylim(0, 6.2)
    ax.axis("off")

    top, bottom = 6.02, 0.78          # vertical extent of the three panels

    # ---------------------------------------------------------- browser panel
    _rectangle(ax, 0.15, bottom, 3.05, top - bottom, fill="#fbfcfe")
    _rectangle(ax, 0.15, top - 1.02, 3.05, 1.02,
               "Browser interface\nfrontend/ · HTML, CSS, ES modules\nno build step, no npm dependency",
               size=8.2, bold=True, fill=HEADER)
    browser_rows = [
        "index.html + css/app.css\n9 routes, light / dark / high contrast",
        "js/app.js — hash router, run lifecycle\ndirty-editor guard, keyboard navigation",
        "js/state.js — run state cache\nselected statement, active filters",
        "js/views/*.js — 9 analysis views\nanalyze, findings, graph, data flow, slicing,\nrules, reports, docs, statement drill-down",
        "js/graph.js + js/lib/layout.js\nlayered SVG dependency-graph layout",
        "js/api.js — fetch client\nrelative URLs, structured ApiError",
    ]
    y = top - 1.14
    for text in browser_rows:
        _rectangle(ax, 0.34, y - 0.64, 2.67, 0.64, text, size=6.9, fill="white")
        y -= 0.72

    # -------------------------------------------------------------- api panel
    api_top = 5.02
    _rectangle(ax, 3.55, 1.95, 2.50, api_top - 1.95, fill="#fbfcfe")
    _rectangle(ax, 3.55, api_top - 0.92, 2.50, 0.92, "HTTP API\ncodetrace/api/server.py",
               size=8.6, bold=True, fill=HEADER)
    api_rows = [
        "routing · JSON envelopes\nschemas validated before the engine runs",
        "limits and error codes\n512 KiB source, 400 / 413 / 422 / 500",
        "RunStore — in-memory runs\nno database, no network, no API key",
        "GET endpoints for every artefact\n/ast /cfg /dataflow /graph /slice /report",
    ]
    y = api_top - 1.02
    for text in api_rows:
        _rectangle(ax, 3.72, y - 0.56, 2.16, 0.56, text, size=6.6, fill="white")
        y -= 0.63

    # ----------------------------------------------------------- engine panel
    _rectangle(ax, 6.45, bottom, 5.00, top - bottom, fill="#fbfcfe")
    _rectangle(ax, 6.45, top - 1.02, 5.00, 1.02,
               "Analysis engine — codetrace/analysis/pipeline.py\n"
               "analyse_source(source, rules, options) → Program",
               size=8.2, bold=True, fill=HEADER)
    stages = [
        ("Lexer → canonical LR(1) / LALR(1) / SLR(1) parser",
         "codetrace/frontend/  ·  located tokens, AST, SYN/LEX diagnostics"),
        ("Scoped semantic analysis",
         "codetrace/semantics/  ·  stable symbol ids, types, SEM diagnostics"),
        ("Control-flow graphs",
         "codetrace/analysis/cfg.py  ·  basic blocks, typed edges, reachability"),
        ("Data-flow framework",
         "reaching definitions · liveness · definite assignment"),
        ("Rule engine and taint propagation",
         "codetrace/rules/ + analysis/taint.py  ·  contexts, summaries"),
        ("Dependency graph and slicing",
         "analysis/dependencies.py, analysis/slicing.py  ·  typed edges"),
        ("Findings and explanations",
         "codetrace/findings/  ·  evidence path, certainty, remediation"),
        ("Reports",
         "codetrace/reporting/  ·  stable JSON, self-contained HTML"),
    ]
    y = top - 1.12
    for title, sub in stages:
        _rectangle(ax, 6.65, y - 0.44, 4.62, 0.44, f"{title}\n{sub}", size=6.6, fill="white")
        y -= 0.505

    # ----------------------------------------------------------------- arrows
    mid = (api_top + 1.95) / 2
    _arrow(ax, (3.22, mid), (3.53, mid))
    _arrow(ax, (6.07, mid), (6.43, mid))

    note = ("Python 3.11 · standard library only · the analysed program is data, never executed\n"
            "python3 -m codetrace.api   →   http://0.0.0.0:8000   (browser and API served by one process)")
    ax.text(5.8, 0.52, note, ha="center", va="top", fontsize=6.9, color="#333333", style="italic",
            linespacing=1.5)

    fig.tight_layout(pad=0.15)
    out = os.path.join(ASSETS, "fig_architecture.png")
    fig.savefig(out, dpi=220, facecolor="white")
    plt.close(fig)
    print("wrote", out)


def extract_from_pdfs(r2_path, template_path):
    try:
        import pymupdf
    except ImportError:
        print("pymupdf not installed: skipping PDF extraction (existing assets are kept)")
        return

    if template_path and os.path.exists(template_path):
        doc = pymupdf.open(template_path)
        page = doc[0]
        for image in page.get_images(full=True):
            pix = pymupdf.Pixmap(doc, image[0])
            if pix.n > 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            out = os.path.join(ASSETS, "vit_logo.png")
            pix.save(out)
            print("wrote", out)
            break
        doc.close()

    if r2_path and os.path.exists(r2_path):
        doc = pymupdf.open(r2_path)
        wanted = {
            10: "fig_pipeline.png",        # analysis pipeline, page 10
            11: "fig_program_graph.png",   # dependency graph of the worked example
            17: "fig_evidence_flow.png",   # source-to-sink evidence diagram
        }
        for page_no, name in wanted.items():
            page = doc[page_no - 1]
            images = page.get_images(full=True)
            if not images:
                continue
            pix = pymupdf.Pixmap(doc, images[0][0])
            if pix.n > 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            out = os.path.join(ASSETS, name)
            pix.save(out)
            print("wrote", out)
        doc.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--r2", default=None, help="path to the Review 2 PDF (optional)")
    parser.add_argument("--template", default=None, help="path to the report template PDF (optional)")
    parser.add_argument("--skip-architecture", action="store_true")
    args = parser.parse_args(argv)

    os.makedirs(ASSETS, exist_ok=True)
    if not args.skip_architecture:
        architecture()
    extract_from_pdfs(args.r2, args.template)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
