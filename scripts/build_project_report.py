#!/usr/bin/env python3
"""Build docs/CodeTrace_Project_Report.pdf from its editable source.

The report is a purely textual academic document: black text on white A4 pages,
no tables, images, colour or graphics.  It is produced with ReportLab's Platypus
document-flow system, which is a *build-time* dependency only.  The CodeTrace
application itself uses nothing outside the Python standard library and does not
import this script.

The source of truth for the prose is ``docs/CodeTrace_Project_Report.md``; its
small markup dialect is documented at the top of that file.  This script only
adds the front matter (cover, bonafide certificate, declaration), the generated
table of contents and the page layout.

Usage:
    python3 scripts/build_project_report.py            # writes the PDF
    python3 scripts/build_project_report.py --out /tmp/report.pdf
    python3 scripts/build_project_report.py --check    # rebuild and re-verify

The document is built twice: the first pass records the page on which every
heading lands, the second pass prints the table of contents with those page
numbers and asserts that pagination did not move.  The contents page therefore
cannot drift away from the body.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    PageBreak,
    PageTemplate,
    KeepTogether,
    Paragraph,
    Preformatted,
    Spacer,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "docs", "CodeTrace_Project_Report.md")
DEFAULT_OUT = os.path.join(ROOT, "docs", "CodeTrace_Project_Report.pdf")

# ---------------------------------------------------------------------------
# Document metadata (verified against the repository and the course template).
# ---------------------------------------------------------------------------

INSTITUTION = "VELLORE INSTITUTE OF TECHNOLOGY, VELLORE"
SCHOOL = "SCHOOL OF COMPUTER SCIENCE AND ENGINEERING"
COURSE = "BCSE307P - COMPILER DESIGN LAB"
TITLE = "CodeTrace: Compiler-Driven Program and Security Analysis for a C Subset"
TEAM = (
    ("Srikiran", "24BCE2215"),
    ("Dhruv", "24BCE2211"),
    ("Prince", "24BDS0153"),
)
GUIDE = "Nithya K"
GUIDE_TITLE = "Assistant Professor Senior Grade II"
SUBMISSION = "OCTOBER, 2026"

# ---------------------------------------------------------------------------
# Page geometry and typography
# ---------------------------------------------------------------------------

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT = RIGHT = 25 * mm
TOP = 24 * mm
BOTTOM = 25 * mm

BLACK = "#000000"

BODY = ParagraphStyle(
    "Body",
    fontName="Times-Roman",
    fontSize=11,
    leading=14.9,
    # Ragged right: justified text with unbreakable identifiers and paths in a
    # 156 mm column produces visible rivers of white space, so the body is set
    # flush left, which is also what the reference report does in practice.
    alignment=TA_LEFT,
    spaceBefore=0,
    spaceAfter=5.8,
    allowWidows=0,
    allowOrphans=0,
    textColor=BLACK,
)

LIST = ParagraphStyle(
    "List",
    parent=BODY,
    leftIndent=20,
    bulletIndent=6,
    spaceBefore=0,
    spaceAfter=3.6,
)

CODE = ParagraphStyle(
    "Code",
    fontName="Courier",
    fontSize=8.4,
    leading=10.7,
    alignment=TA_LEFT,
    leftIndent=12,
    spaceBefore=5,
    spaceAfter=9,
    textColor=BLACK,
)

CHAPTER_LABEL = ParagraphStyle(
    "ChapterLabel",
    fontName="Times-Bold",
    fontSize=14,
    leading=18,
    alignment=TA_CENTER,
    spaceAfter=4,
    textColor=BLACK,
)

CHAPTER_TITLE = ParagraphStyle(
    "ChapterTitle",
    fontName="Times-Bold",
    fontSize=16,
    leading=21,
    alignment=TA_CENTER,
    spaceAfter=16,
    textColor=BLACK,
)

SECTION = ParagraphStyle(
    "Section",
    fontName="Times-Bold",
    fontSize=12.2,
    leading=15.5,
    alignment=TA_LEFT,
    spaceBefore=11,
    spaceAfter=4.5,
    keepWithNext=1,
    textColor=BLACK,
)

SUBSECTION = ParagraphStyle(
    "Subsection",
    fontName="Times-Bold",
    fontSize=10.8,
    leading=14,
    alignment=TA_LEFT,
    spaceBefore=9,
    spaceAfter=3.5,
    keepWithNext=1,
    textColor=BLACK,
)

FRONT_HEADING = ParagraphStyle(
    "FrontHeading",
    fontName="Times-Bold",
    fontSize=14,
    leading=18,
    alignment=TA_CENTER,
    spaceAfter=18,
    textColor=BLACK,
)

REFERENCE = ParagraphStyle(
    "Reference",
    fontName="Times-Roman",
    fontSize=10.2,
    leading=13.6,
    alignment=TA_JUSTIFY,
    leftIndent=24,
    firstLineIndent=-24,
    spaceBefore=0,
    spaceAfter=7,
    allowWidows=0,
    allowOrphans=0,
    textColor=BLACK,
)

CENTER_SMALL = ParagraphStyle(
    "CenterSmall",
    fontName="Times-Roman",
    fontSize=11.5,
    leading=17,
    alignment=TA_CENTER,
    spaceAfter=0,
    textColor=BLACK,
)

CENTER_BOLD = ParagraphStyle(
    "CenterBold",
    fontName="Times-Bold",
    fontSize=13,
    leading=17,
    alignment=TA_CENTER,
    spaceAfter=0,
    textColor=BLACK,
)


# ---------------------------------------------------------------------------
# Flowables
# ---------------------------------------------------------------------------


class Heading(Paragraph):
    """A paragraph that remembers which table-of-contents entry it belongs to."""

    def __init__(self, text, style, toc_id, toc_level):
        Paragraph.__init__(self, text, style)
        self.toc_id = toc_id
        self.toc_level = toc_level


class TocLine(Flowable):
    """One contents line: title, dot leader and page number.

    Drawn with text only, so the contents page contains no table and no rule.
    """

    def __init__(self, title, page, level, bold=False):
        Flowable.__init__(self)
        self.height = 15.4
        self.title = title
        self.page = page
        self.level = level
        self.bold = bold

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        return (availWidth, self.height)

    def draw(self):
        canvas = self.canv
        font = "Times-Bold" if self.bold else "Times-Roman"
        size = 10.4
        indent = 0 if self.level == 1 else 16
        canvas.setFont(font, size)
        canvas.setFillColor(BLACK)
        page_text = str(self.page) if self.page else ""
        page_width = canvas.stringWidth(page_text, font, size)
        title_text = self.title
        limit = self.width - indent - page_width - 16
        while title_text and canvas.stringWidth(title_text, font, size) > limit:
            title_text = title_text[:-1]
        baseline = 4
        canvas.drawString(indent, baseline, title_text)
        title_width = canvas.stringWidth(title_text, font, size)
        if page_text:
            canvas.drawRightString(self.width, baseline, page_text)
        dot_start = indent + title_width + 4
        dot_end = self.width - page_width - 4
        dot_width = canvas.stringWidth(". ", "Times-Roman", size)
        if dot_end > dot_start and dot_width > 0:
            dots = int((dot_end - dot_start) / dot_width)
            canvas.setFont("Times-Roman", size)
            canvas.drawString(dot_start, baseline, ". " * dots)


# ---------------------------------------------------------------------------
# Inline markup
# ---------------------------------------------------------------------------


def inline(text):
    """Convert the small inline markup to ReportLab paragraph markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = []
    for piece in re.split(r"(`[^`]+`)", text):
        if piece.startswith("`") and piece.endswith("`") and len(piece) > 2:
            out.append('<font name="Courier" size="9.6">%s</font>' % piece[1:-1])
            continue
        piece = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", piece)
        piece = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", piece)
        out.append(piece)
    return "".join(out)


# ---------------------------------------------------------------------------
# Source parsing
# ---------------------------------------------------------------------------


class Block:
    def __init__(self, kind, **fields):
        self.kind = kind
        self.__dict__.update(fields)

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Block(%r)" % self.kind


def parse_source(path):
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().split("\n")

    blocks = []
    abstract = []
    target = blocks
    paragraph = []
    items = []
    list_kind = None
    in_code = False
    code_lines = []
    in_header_comment = False

    def flush_paragraph():
        if paragraph:
            target.append(Block("para", text=" ".join(paragraph).strip()))
            paragraph.clear()

    def flush_list():
        nonlocal list_kind
        if items:
            target.append(
                Block("list", ordered=(list_kind == "ordered"), items=list(items))
            )
            items.clear()
        list_kind = None

    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        index += 1

        if in_header_comment:
            if "-->" in line:
                in_header_comment = False
            continue
        if stripped.startswith("<!--"):
            in_header_comment = "-->" not in line
            continue

        if in_code:
            if stripped.startswith("```"):
                in_code = False
                target.append(Block("code", text="\n".join(code_lines)))
                code_lines = []
            else:
                code_lines.append(line)
            continue

        if stripped.startswith("```"):
            flush_paragraph()
            flush_list()
            in_code = True
            continue

        if stripped == "::: abstract":
            flush_paragraph()
            flush_list()
            target = abstract
            continue

        if stripped == "::: toc":
            flush_paragraph()
            flush_list()
            target = blocks
            blocks.append(Block("toc"))
            continue

        if stripped == "::: pagebreak":
            flush_paragraph()
            flush_list()
            target.append(Block("pagebreak"))
            continue

        if stripped.startswith("# "):
            flush_paragraph()
            flush_list()
            text = stripped[2:].strip()
            if "|" in text:
                label, title = [part.strip() for part in text.split("|", 1)]
                target.append(Block("chapter", label=label, title=title))
            else:
                target.append(Block("chapter", label="", title=text))
            continue

        if stripped.startswith("## "):
            flush_paragraph()
            flush_list()
            target.append(Block("section", title=stripped[3:].strip()))
            continue

        if stripped.startswith("### "):
            flush_paragraph()
            flush_list()
            target.append(Block("subsection", title=stripped[4:].strip()))
            continue

        if not stripped:
            flush_paragraph()
            flush_list()
            continue

        if stripped.startswith("- "):
            flush_paragraph()
            if list_kind != "bullet":
                flush_list()
                list_kind = "bullet"
            items.append(stripped[2:].strip())
            continue

        match = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if match:
            flush_paragraph()
            if list_kind != "ordered":
                flush_list()
                list_kind = "ordered"
            items.append(match.group(2).strip())
            continue

        if list_kind:
            # A plain line after a list item continues that item.
            items[-1] = items[-1] + " " + stripped
            continue

        paragraph.append(stripped)

    flush_paragraph()
    flush_list()
    if in_code:
        raise SystemExit("unterminated code block in %s" % path)
    return blocks, abstract


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------


def cover_story():
    story = [Spacer(1, 42)]
    story.append(Paragraph(INSTITUTION, ParagraphStyle(
        "inst", parent=CENTER_BOLD, fontSize=15.5, leading=20)))
    story.append(Spacer(1, 8))
    story.append(Paragraph(SCHOOL, ParagraphStyle(
        "school", parent=CENTER_BOLD, fontSize=12.3, leading=16)))
    story.append(Spacer(1, 78))
    story.append(Paragraph(COURSE, ParagraphStyle(
        "course", parent=CENTER_BOLD, fontSize=13, leading=18)))
    story.append(Spacer(1, 2))
    story.append(Paragraph("PROJECT REPORT", ParagraphStyle(
        "proj", parent=CENTER_BOLD, fontSize=13, leading=18)))
    story.append(Spacer(1, 74))
    story.append(Paragraph(TITLE, ParagraphStyle(
        "title", parent=CENTER_BOLD, fontSize=17, leading=23)))
    story.append(Spacer(1, 54))
    story.append(Paragraph("Submitted by", CENTER_SMALL))
    story.append(Spacer(1, 8))
    for name, register in TEAM:
        story.append(Paragraph("%s - %s" % (name, register), CENTER_SMALL))
    story.append(Spacer(1, 40))
    story.append(Paragraph("Under the guidance of", CENTER_SMALL))
    story.append(Spacer(1, 6))
    story.append(Paragraph(GUIDE + ",", ParagraphStyle(
        "guide", parent=CENTER_BOLD, fontSize=12.3, leading=17)))
    story.append(Spacer(1, 3))
    story.append(Paragraph(GUIDE_TITLE, ParagraphStyle(
        "guidetitle", parent=CENTER_BOLD, fontSize=11.5, leading=16)))
    story.append(Spacer(1, 62))
    story.append(Paragraph(SUBMISSION, ParagraphStyle(
        "month", parent=CENTER_BOLD, fontSize=12.5, leading=17)))
    return story


def certificate_story():
    body = ParagraphStyle("cert", parent=BODY, fontSize=11.3, leading=17.4,
                          alignment=TA_JUSTIFY, spaceAfter=10)
    return [
        Spacer(1, 26),
        Paragraph("BONAFIDE CERTIFICATE", FRONT_HEADING),
        Paragraph(
            "This is to certify that the project report titled "
            "<i>%s</i> is a bonafide record of work carried out by "
            "Srikiran (24BCE2215), Dhruv (24BCE2211) and Prince (24BDS0153), "
            "submitted in partial fulfilment of the requirements for the course "
            "BCSE307P - Compiler Design Lab, School of Computer Science and "
            "Engineering, Vellore Institute of Technology, Vellore, during the "
            "academic year 2026 - 2027." % TITLE,
            body),
        Paragraph(
            "The report documents the implementation present in the project "
            "repository on the date of submission. Every measurement quoted in "
            "the report was produced by the commands named in Chapter 4, on "
            "that checkout, and is reproduced by the generation script rather "
            "than transcribed by hand.",
            body),
        Spacer(1, 84),
        Paragraph("Faculty Guide: ______________________________", BODY),
        Spacer(1, 22),
        Paragraph("Date: ______________________________", BODY),
    ]


def declaration_story():
    body = ParagraphStyle("decl", parent=BODY, fontSize=11.3, leading=17.4,
                          alignment=TA_JUSTIFY, spaceAfter=10)
    return [
        Spacer(1, 26),
        Paragraph("DECLARATION", FRONT_HEADING),
        Paragraph(
            "We hereby declare that the project report titled <i>%s</i>, "
            "submitted by us to Vellore Institute of Technology, Vellore in "
            "partial fulfilment of the requirement for the course BCSE307P - "
            "Compiler Design Lab, is a record of bona fide work carried out by "
            "us under the supervision of %s. The contents of this report, in "
            "full or in part, have not been submitted to any other institute or "
            "university for the award of any degree or diploma."
            % (TITLE, GUIDE),
            body),
        Paragraph(
            "The source code, test suites, example corpus and measurement "
            "scripts described in this report are part of the project "
            "repository, and this document is generated from its maintained "
            "source rather than assembled by hand.",
            body),
        Spacer(1, 78),
        Paragraph("Place: ______________________________", BODY),
        Spacer(1, 22),
        Paragraph("Date: ______________________________", BODY),
        Spacer(1, 34),
        Paragraph("Signature of the candidate(s): "
                  "______________________________", BODY),
    ]


# ---------------------------------------------------------------------------
# Story construction
# ---------------------------------------------------------------------------


def render_block(block):
    if block.kind == "pagebreak":
        return [PageBreak()]
    if block.kind == "para":
        return [Paragraph(inline(block.text), BODY)]
    if block.kind == "code":
        for number, line in enumerate(block.text.split("\n"), start=1):
            if len(line) > 84:
                raise SystemExit(
                    "code line %d is too long for the A4 text column: %r"
                    % (number, line))
        # A code listing is one unit: splitting it across a page boundary
        # makes the indentation unreadable and orphans its last lines.
        return [KeepTogether(Preformatted(block.text, CODE))]
    if block.kind == "list":
        flows = []
        for number, item in enumerate(block.items, start=1):
            bullet = ("%d." % number) if block.ordered else "-"
            flows.append(Paragraph(inline(item), LIST, bulletText=bullet))
        return flows
    if block.kind == "references":
        return [Paragraph(inline(item), REFERENCE) for item in block.items]
    raise SystemExit("unhandled block %r" % block.kind)


def build_story(blocks, abstract, page_map):
    story = []
    entries = []
    counter = [0]

    def next_id():
        counter[0] += 1
        return counter[0]

    # --- front matter ----------------------------------------------------
    story.extend(cover_story())
    story.append(PageBreak())
    story.extend(certificate_story())
    story.append(PageBreak())
    story.extend(declaration_story())
    story.append(PageBreak())

    abstract_id = next_id()
    story.append(Heading("ABSTRACT", FRONT_HEADING, abstract_id, 1))
    entries.append((abstract_id, "ABSTRACT", 1, True))
    for block in abstract:
        story.extend(render_block(block))
    story.append(PageBreak())

    # --- body ------------------------------------------------------------
    body = []
    for block in blocks:
        if block.kind == "chapter":
            story_id = next_id()
            text = ("%s %s" % (block.label, block.title)).strip()
            entries.append((story_id, text, 1, True))
            body.append(("chapter", block, story_id))
        elif block.kind == "section":
            story_id = next_id()
            entries.append((story_id, block.title, 2, False))
            body.append(("section", block, story_id))
        elif block.kind == "subsection":
            body.append(("subsection", block, None))
        elif block.kind == "toc":
            body.append(("toc", block, None))
        else:
            body.append(("flow", block, None))

    rendered = []
    for kind, block, story_id in body:
        if kind == "toc":
            rendered.append(("toc", None))
        elif kind == "chapter":
            rendered.append(("flow", Spacer(1, 4)))
            if block.label:
                rendered.append(("flow", Heading(
                    block.label, CHAPTER_LABEL, story_id, 1)))
            rendered.append(("flow", Heading(
                block.title, CHAPTER_TITLE, story_id, 1)))
        elif kind == "section":
            rendered.append(("flow", Heading(
                block.title, SECTION, story_id, 2)))
        elif kind == "subsection":
            rendered.append(("flow", Heading(
                block.title, SUBSECTION, story_id, 3)))
        elif kind == "references":
            for flow in render_block(block):
                rendered.append(("flow", flow))
        else:
            for flow in render_block(block):
                rendered.append(("flow", flow))

    # The reference list needs hanging indents rather than body paragraphs;
    # it is recognised by the heading that precedes it.
    fixed = []
    in_references = False
    for kind, flow in rendered:
        if kind == "toc":
            fixed.append(("toc", None))
            continue
        if isinstance(flow, Heading) and \
                flow.getPlainText().strip() == "REFERENCES":
            in_references = True
        if in_references and isinstance(flow, Paragraph) and \
                not isinstance(flow, Heading):
            flow = Paragraph(flow.text, REFERENCE)
        fixed.append(("flow", flow))

    toc_flow = [
        TocLine(text, page_map.get(story_id, 0), level, bold)
        for story_id, text, level, bold in entries
    ]

    for kind, flow in fixed:
        if kind == "toc":
            story.extend(toc_flow)
        else:
            story.append(flow)
    return story, entries


# ---------------------------------------------------------------------------
# Document template
# ---------------------------------------------------------------------------


class ReportDoc(BaseDocTemplate):
    def __init__(self, filename, **kwargs):
        BaseDocTemplate.__init__(
            self,
            filename,
            pagesize=A4,
            leftMargin=LEFT,
            rightMargin=RIGHT,
            topMargin=TOP,
            bottomMargin=BOTTOM,
            title=TITLE,
            author="Srikiran, Dhruv, Prince",
            subject="BCSE307P Compiler Design Lab - project report",
            creator="scripts/build_project_report.py",
            # No creation timestamp or random document id: two builds of the
            # same source produce the same bytes, so the PDF can be checked in
            # and diffed.
            invariant=1,
            **kwargs
        )
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="body",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates([
            PageTemplate(id="page", frames=[frame], onPage=self._footer)
        ])
        self.heading_pages = {}

    def _footer(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(BLACK)
        canvas.setFont("Times-Roman", 10)
        canvas.drawCentredString(PAGE_WIDTH / 2.0, 16 * mm, str(doc.page))
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Heading):
            self.heading_pages.setdefault(flowable.toc_id, self.page)


def build(blocks, abstract, page_map, out_path):
    doc = ReportDoc(out_path)
    story, entries = build_story(blocks, abstract, page_map)
    doc.build(story)
    return doc.heading_pages, entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=DEFAULT_OUT, help="output PDF path")
    parser.add_argument("--check", action="store_true",
                        help="rebuild and confirm that pagination is stable")
    args = parser.parse_args(argv)

    blocks, abstract = parse_source(SOURCE)

    # Pass 1: paginate with placeholder page numbers.
    pages, entries = build(blocks, abstract, {}, os.devnull)
    missing = [sid for sid, _t, _l, _b in entries if sid not in pages]
    if missing:
        raise SystemExit("headings never reached a page: %r" % (missing,))

    # Pass 2: the same flowables, with real numbers on the contents page.
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    pages2, _ = build(blocks, abstract, pages, args.out)
    if pages != pages2:
        raise SystemExit(
            "pagination changed between passes; the contents page would be "
            "stale")

    # A page holding only one or two lines is almost always the tail of a
    # paragraph that could have fitted on the previous page; report it so the
    # source can be tightened rather than leaving the gap unnoticed.
    import pymupdf  # optional, build-time only

    document = pymupdf.open(args.out)
    for number, page in enumerate(document, start=1):
        text = page.get_text().strip()
        body = "\n".join(text.split("\n")[:-1]).strip()  # drop the folio
        if len(body.split()) < 12:
            print("warning: page %d has only %d words"
                  % (number, len(body.split())))
    document.close()

    print("wrote %s" % args.out)
    print("pages: %d   contents entries: %d" % (max(pages.values()), len(entries)))
    for sid, text, _level, _bold in entries:
        print("  p.%-3d %s" % (pages[sid], text))

    if args.check:
        import hashlib
        import tempfile

        handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        handle.close()
        try:
            pages3, _ = build(blocks, abstract, pages, handle.name)
            if pages3 != pages2:
                raise SystemExit("a rebuild produced different pagination")
            first = open(args.out, "rb").read()
            second = open(handle.name, "rb").read()
            print("rebuild: %d pages, %d bytes, sha256 %s" % (
                max(pages3.values()), len(second),
                hashlib.sha256(second).hexdigest()[:16]))
            print("same page count: %s; byte-identical: %s"
                  % (len(first) == len(second), first == second))
        finally:
            os.unlink(handle.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
