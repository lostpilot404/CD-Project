#!/usr/bin/env python3
"""Build the Review 3 project report as a .docx on the institutional template.

The document follows Template.pdf page for page (cover with the institute mark,
bonafide certificate, declaration, abstract, table of contents, numbered chapters,
references) and adds a list of figures and a list of tables for Review 3.

Typography, as required for this submission:

* chapter headings 18 pt bold, section headings 16 pt bold, sub-sections 14 pt bold
  italic, body text 12 pt, all in Times New Roman and all in black (no coloured
  headings, no coloured text anywhere in the document);
* tables at 11 pt with generous cell padding so that they can be read on paper;
* one column of text, wide figures, and no bullet-list clutter in the prose.

Page numbers in the contents, the list of figures and the list of tables are
*measured*: the body is laid out with the same metrics Word uses for Times New
Roman (``reportlab.pdfbase.pdfmetrics`` with the standard Type 1 Times metrics),
so line breaking and page heights match the rendered document closely. The
measured map can be passed with ``--page-map``; without it the estimates from the
layout model are used.

Usage
-----
    python3 scripts/build_review3_docx.py [-o docs/Review3_CodeTrace_Report.docx]

Requires python-docx and reportlab at build time. Neither is a dependency of
CodeTrace itself.
"""

from __future__ import annotations

import argparse
import math
import os
import sys

try:
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING, WD_TAB_ALIGNMENT, WD_TAB_LEADER
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor
except ImportError:  # pragma: no cover - build-time dependency
    sys.exit("python-docx is required to build the report: pip install python-docx")

try:
    from reportlab.pdfbase.pdfmetrics import stringWidth
except ImportError:  # pragma: no cover - build-time dependency
    sys.exit("reportlab is required for text metrics: pip install reportlab")

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Figure assets, searched in order: the Review 3 drawings first, then the diagrams
#: carried over from the Review 2 report (the architecture and pipeline figures).
ASSETS = os.path.join(ROOT, "docs", "review3_report_assets")
FALLBACK_ASSETS = os.path.join(ROOT, "docs", "review2_report_assets")
SHOTS = os.path.join(ROOT, "docs", "review3_screenshots")

# ---------------------------------------------------------------- project facts
PROJECT_TITLE = "CodeTrace: Compiler-Driven Program and Security Analysis for a C Subset"
REPO_URL = "https://github.com/lostpilot404/CD-Project"
TEAM = [
    ("Srikiran", "24BCE2215"),
    ("Dhruv", "24BCE2211"),
    ("Prince", "24BDS0153"),
]
GUIDE = "Nithya K"
GUIDE_TITLE = "Assistant Professor Senior Grade II"
MONTH_YEAR = "OCTOBER, 2026"

# ------------------------------------------------------------------- typography
BODY_PT = 12.0
LINE_PITCH = 20.7            # 1.5 line spacing of Times New Roman 12 pt
PAGE_TEXT_HEIGHT = 648.0     # 9 in
PAGE_TEXT_WIDTH = 468.0      # 6.5 in
BULLET_INDENT_PT = 20.0
BODY_FONT = "Times New Roman"
MONO_FONT = "Consolas"
INK = RGBColor(0x00, 0x00, 0x00)
RULE_GREY = RGBColor(0x33, 0x33, 0x33)
GREY = RGBColor(0x33, 0x33, 0x33)

# reportlab font names used for measurement (Times metrics == Times New Roman)
METRIC_FONT = {
    "regular": "Times-Roman",
    "bold": "Times-Bold",
    "italic": "Times-Italic",
    "bolditalic": "Times-BoldItalic",
    "code": "Courier",
}


# --------------------------------------------------------------------- measuring
def _tokens_of(text, bold=False, italic=False):
    """Split inline markup into (word, font-key) tokens that keep the spaces."""
    runs = []
    buf = ""
    i = 0
    state = (bold, italic, False)
    while i < len(text):
        if state[2]:                     # inside a code span: literal text only
            if text.startswith("`", i):
                if buf:
                    runs.append((buf, state))
                    buf = ""
                state = (state[0], state[1], False)
                i += 1
            else:
                buf += text[i]
                i += 1
        elif text.startswith("**", i):
            if buf:
                runs.append((buf, state))
                buf = ""
            state = (not state[0], state[1], False)
            i += 2
        elif text.startswith("`", i):
            if buf:
                runs.append((buf, state))
                buf = ""
            state = (state[0], state[1], not state[2])
            i += 1
        elif text.startswith("*", i):
            if buf:
                runs.append((buf, state))
                buf = ""
            state = (state[0], not state[1], False)
            i += 1
        else:
            buf += text[i]
            i += 1
    if buf:
        runs.append((buf, state))

    words = []
    for chunk, (b, it, code) in runs:
        if code:
            font = "code"
        elif b and it:
            font = "bolditalic"
        elif b:
            font = "bold"
        elif it:
            font = "italic"
        else:
            font = "regular"
        # keep the trailing space attached to the word before it
        parts = chunk.split(" ")
        for index, part in enumerate(parts):
            if part == "" and index != len(parts) - 1:
                continue
            word = part + (" " if index < len(parts) - 1 else "")
            if word:
                words.append((word, font))
    return words


def measure_width(text, size, bold=False, italic=False):
    total = 0.0
    for word, font in _tokens_of(text, bold, italic):
        total += stringWidth(word, METRIC_FONT[font], size)
    return total


def wrap_lines(text, size, width, bold=False, italic=False):
    """Greedy line breaking, the same rule Word uses without hyphenation."""
    if not text:
        return 1
    words = _tokens_of(text, bold, italic)
    lines = 1
    current = 0.0
    space = stringWidth(" ", METRIC_FONT["regular"], size)
    for word, font in words:
        w = stringWidth(word, METRIC_FONT[font], size)
        trailing = word.endswith(" ")
        core = w - (space if trailing else 0.0)
        if current == 0.0:
            current = core
        elif current + space + core <= width:
            current += space + core
        else:
            lines += 1
            current = core
        if trailing and current > 0:
            current += space
    return lines


def image_aspect(path):
    if Image is None:
        return 0.5
    with Image.open(path) as im:
        return im.height / im.width


# ---------------------------------------------------------------------- blocks
class Composer:
    """Collects the report as a list of layout blocks."""

    def __init__(self):
        self.blocks = []
        self.figure_no = 0
        self.table_no = 0
        self.chapter = 0
        self.section = 0

    # -- structure ---------------------------------------------------------
    def front_heading(self, title):
        self.blocks.append({"kind": "front_heading", "text": title, "toc_label": title})
        self.blocks.append({"kind": "toc", "level": 1, "text": title, "page": None})

    def chapter_start(self, title):
        self.chapter += 1
        self.section = 0
        self.figure_no = 0          # figure and table numbers restart in every chapter
        self.table_no = 0
        label = f"CHAPTER {self.chapter}  {title.upper()}"
        self.blocks.append({"kind": "chapter", "number": self.chapter, "title": title.upper(),
                            "toc_label": label})
        self.blocks.append({"kind": "toc", "level": 1, "text": label, "page": None})

    def section_start(self, title, level=2):
        if level == 2:
            self.section += 1
            number = f"{self.chapter}.{self.section}"
        else:
            number = None
        label = f"{number} {title}" if number else title
        self.blocks.append({"kind": f"h{level}", "text": label, "toc_label": label})
        self.blocks.append({"kind": "toc", "level": level, "text": label, "page": None})
        return label

    def h3(self, title):
        """Third-level heading; not listed in the table of contents."""
        self.blocks.append({"kind": "h3", "text": title})

    # -- content -----------------------------------------------------------
    def p(self, text, align="justify", space_after=4, keep_with_next=False, size=BODY_PT, italic=False):
        self.blocks.append(
            {
                "kind": "p",
                "text": text,
                "align": align,
                "space_after": space_after,
                "keep_with_next": keep_with_next,
                "size": size,
                "italic": italic,
            }
        )

    def bullets(self, items, numbered=False, size=BODY_PT):
        self.blocks.append({"kind": "bullets", "items": items, "numbered": numbered, "size": size})

    def note(self, text):
        self.blocks.append({"kind": "note", "text": text})

    def table(self, caption, headers, rows, widths, size=11.0, note=None):
        size = max(size, 11.0)          # tables must stay readable on paper
        widths = fitting_widths(headers, rows, widths, size)
        self.table_no += 1
        self.blocks.append(
            {
                "kind": "table",
                "caption": f"Table {self.chapter}.{self.table_no}: {caption}",
                "headers": headers,
                "rows": rows,
                "widths": widths,
                "size": size,
                "note": note,
            }
        )

    def figure(self, filename, caption, width_in=6.0, caption_short=False):
        self.figure_no += 1
        if os.path.isabs(filename):
            path = filename
        elif filename.startswith("shot:"):
            path = os.path.join(SHOTS, filename[len("shot:"):])
        else:
            path = os.path.join(ASSETS, filename)
            if not os.path.exists(path):
                path = os.path.join(FALLBACK_ASSETS, filename)
        self.blocks.append(
            {
                "kind": "figure",
                "path": path,
                "caption": (caption if caption_short
                            else f"Figure {self.chapter}.{self.figure_no}: {caption}"),
                "numbered_caption": f"Figure {self.chapter}.{self.figure_no}: {caption}",
                "width_in": width_in,
            }
        )

    def code(self, text, caption=None):
        self.blocks.append({"kind": "code", "text": text.rstrip("\n"), "caption": caption})

    def references(self, entries):
        """Numbered reference list, hung from the left margin."""
        self.blocks.append({"kind": "references", "items": entries})

    def pagebreak(self):
        self.blocks.append({"kind": "pagebreak"})

    def spacer(self, pts=6):
        self.blocks.append({"kind": "spacer", "pts": pts})


# ------------------------------------------------------------------- measuring
def block_height(block):
    """Height in points that a block occupies on the page."""
    kind = block["kind"]
    if kind == "chapter":
        return 2 * 22.0 + 20.0          # number, line break, title, space after
    if kind == "front_heading":
        return 20 + 20
    if kind == "h2":
        return 19.5 * wrap_lines(block["text"], 16, PAGE_TEXT_WIDTH, bold=True) + 22
    if kind == "h3":
        return 17.0 * wrap_lines(block["text"], 14, PAGE_TEXT_WIDTH, bold=True) + 16
    if kind == "p":
        lines = wrap_lines(block["text"], block["size"], PAGE_TEXT_WIDTH, italic=block["italic"])
        return lines * LINE_PITCH + block["space_after"]
    if kind == "bullets":
        total = 0.0
        for item in block["items"]:
            lines = wrap_lines(item, block["size"], PAGE_TEXT_WIDTH - BULLET_INDENT_PT, bold=False)
            total += lines * LINE_PITCH + 2
        return total + 4
    if kind == "note":
        lines = wrap_lines(block["text"], 10.5, PAGE_TEXT_WIDTH - 12, italic=True)
        return lines * 12.0 + 8
    if kind == "table":
        return table_height(block) + 6
    if kind == "figure":
        height_pt = block["width_in"] * 72.0 * image_aspect(block["path"])
        caption_lines = wrap_lines(block["caption"], 11, PAGE_TEXT_WIDTH, italic=True)
        return height_pt + 16 + caption_lines * 12.5 + 12
    if kind == "code":
        cap = (13.0 if block["caption"] else 0.0)
        return len(block["text"].splitlines()) * 12.0 + 14 + cap
    if kind == "spacer":
        return block["pts"]
    if kind == "references":
        total = 0.0
        for index, entry in enumerate(block["items"], start=1):
            text = f"[{index}]\t{entry}"
            lines = wrap_lines(text, BODY_PT, PAGE_TEXT_WIDTH - 30, bold=False)
            total += lines * LINE_PITCH + 8
        return total
    if kind == "pagebreak":
        return 0.0
    if kind == "toc":
        return 0.0
    return 0.0


def table_height(block):
    size = block["size"]
    widths = [w * 72.0 for w in block["widths"]]
    pad = 0.134 * 72.0         # both cell margins (96 twips = 0.0667 in each side)
    total = 0.0
    for r_index, row in enumerate([block["headers"]] + list(block["rows"])):
        lines = 1
        for cell, width in zip(row, widths):
            avail = width - pad
            n = wrap_lines(str(cell), size, avail, bold=(r_index == 0))
            lines = max(lines, n)
        total += lines * (size * 1.15) + 6.0      # cell padding and the 5 pt row gap
    total += 4.0
    caption_lines = wrap_lines(block["caption"], 11, PAGE_TEXT_WIDTH, bold=True)
    total += caption_lines * 12.5 + 16
    if block.get("note"):
        total += wrap_lines(block["note"], 10.5, PAGE_TEXT_WIDTH, italic=True) * 11.5 + 6
    return total


def paginate(blocks, start_page):
    """Assign a page number to every heading (and therefore to the TOC)."""
    page = start_page
    used = 0.0
    for block in blocks:
        kind = block["kind"]
        if kind == "pagebreak":
            page += 1
            used = 0.0
            continue
        if kind in ("chapter", "front_heading"):
            if used > 0:
                page += 1
            used = 0.0
            block["_page"] = page
            used += block_height(block)
            continue
        h = block_height(block)
        if used + h > PAGE_TEXT_HEIGHT and h < PAGE_TEXT_HEIGHT:
            page += 1
            used = 0.0
        used += h
        block["_page"] = page
    # propagate the heading page onto the TOC rows that follow them
    pending = None
    for block in blocks:
        if block["kind"] in ("chapter", "front_heading", "h2", "h3"):
            pending = block.get("_page")
        elif block["kind"] == "toc":
            block["page"] = pending
    return page


# --------------------------------------------------------------- docx helpers
def set_run_font(run, name=BODY_FONT, size=BODY_PT, bold=False, italic=False, color=INK):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), name)


# Word validates the child order of the property elements; insert, never append.
TBLPR_ORDER = (
    "tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
    "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders", "shd",
    "tblLayout", "tblCellMar", "tblLook", "tblCaption", "tblDescription",
)
PPR_ORDER = (
    "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
    "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
    "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
    "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc",
    "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr",
    "sectPr", "pPrChange",
)
TRPR_ORDER = (
    "cnfStyle", "divId", "gridBefore", "gridAfter", "wBefore", "wAfter", "cantSplit", "trHeight",
    "tblHeader", "tblCellSpacing", "jc", "hidden", "ins", "del", "trPrChange",
)
TCPR_ORDER = (
    "cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap", "tcMar",
    "textDirection", "tcFitText", "vAlign", "hideMark", "headers", "cellIns", "cellDel", "cellMerge",
    "tcPrChange",
)


def insert_ordered(parent, child, order):
    """Insert `child` into `parent` at the position Word expects for its tag."""
    tag = child.tag.split("}")[-1]
    index = order.index(tag) if tag in order else len(order)
    for position, existing in enumerate(list(parent)):
        name = existing.tag.split("}")[-1]
        existing_index = order.index(name) if name in order else len(order)
        if existing_index > index:
            parent.insert(position, child)
            return child
    parent.append(child)
    return child


def shade(pr, fill):
    """Apply a background fill to a `w:pPr` or `w:tcPr` element."""
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    order = TCPR_ORDER if pr.tag.endswith("tcPr") else PPR_ORDER
    insert_ordered(pr, shd, order)


def add_field(paragraph, instruction, placeholder="1"):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = placeholder
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(separate)
    run._r.append(text)
    run._r.append(end)
    return run


def strip_markup(text):
    """Plain text of a marked-up string, for places that cannot carry runs."""
    return text.replace("**", "").replace("`", "").replace("*", "")


def add_inline(paragraph, text, size=BODY_PT, color=INK, base_bold=False, base_italic=False):
    """Write `text` into `paragraph`, honouring **bold**, *italic* and `code`."""
    bold, italic, code = base_bold, base_italic, False
    buf = ""
    i = 0

    def flush():
        nonlocal buf
        if buf:
            run = paragraph.add_run(buf)
            set_run_font(
                run,
                name=MONO_FONT if code else BODY_FONT,
                size=size - (0.5 if code else 0.0),
                bold=bold,
                italic=italic,
                color=color,
            )
            buf = ""

    while i < len(text):
        if code:                          # inside a code span: literal text only
            if text.startswith("`", i):
                flush()
                code = False
                i += 1
            else:
                buf += text[i]
                i += 1
        elif text.startswith("**", i):
            flush()
            bold = not bold
            i += 2
        elif text.startswith("`", i):
            flush()
            code = True
            i += 1
        elif text.startswith("*", i):
            flush()
            italic = not italic
            i += 1
        else:
            buf += text[i]
            i += 1
    flush()


def paragraph_format(paragraph, align="justify", space_before=0, space_after=4,
                     line_spacing=1.5, keep_with_next=False, keep_together=False,
                     left_indent=None, first_line=None, exact_spacing=None):
    pf = paragraph.paragraph_format
    pf.alignment = {
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
    }[align]
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    if exact_spacing:
        pf.line_spacing = Pt(exact_spacing)
        pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    else:
        pf.line_spacing = line_spacing
    pf.keep_with_next = keep_with_next
    pf.keep_together = keep_together or keep_with_next
    if left_indent is not None:
        pf.left_indent = Pt(left_indent)
    if first_line is not None:
        pf.first_line_indent = Pt(first_line)
    pf.widow_control = True
    return paragraph


# ---------------------------------------------------------------- document setup
def new_document():
    doc = Document()

    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.header_distance = Inches(0.5)
    section.footer_distance = Inches(0.5)

    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(BODY_PT)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.line_spacing = 1.5

    for name, size in (("Heading 1", 18), ("Heading 2", 16), ("Heading 3", 14)):
        try:
            style = doc.styles[name]
        except KeyError:  # pragma: no cover - the default template always has them
            continue
        style.font.name = BODY_FONT
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.italic = False
        style.font.color.rgb = INK
        rpr = style.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rfonts.set(qn(attr), BODY_FONT)
        style.paragraph_format.space_before = Pt(0)
        style.paragraph_format.line_spacing = 1.0

    # ask Word to refresh fields (table of contents, page numbers) when the file opens,
    # so the cached page numbers cannot go stale if the text is edited later
    settings = doc.settings.element
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    settings.append(update)

    # footer: centred page number, as in the template
    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fp.paragraph_format.space_before = Pt(0)
    fp.paragraph_format.space_after = Pt(0)
    fp.paragraph_format.line_spacing = 1.0
    run = add_field(fp, "PAGE")
    set_run_font(run, size=10)

    return doc


# --------------------------------------------------------------- front matter
def render_cover(doc):
    def line(text, size, bold=False, space_before=0, space_after=0, italic=False, color=INK):
        para = doc.add_paragraph()
        paragraph_format(para, align="center", space_before=space_before, space_after=space_after,
                         line_spacing=1.0)
        run = para.add_run(text)
        set_run_font(run, size=size, bold=bold, italic=italic, color=color)
        return para

    line("VELLORE INSTITUTE OF TECHNOLOGY, VELLORE", 18, bold=True, space_before=10)
    line("SCHOOL OF COMPUTER SCIENCE AND ENGINEERING", 14, bold=True, space_before=6)

    logo = os.path.join(ASSETS, "vit_logo.png")
    if os.path.exists(logo):
        para = doc.add_paragraph()
        paragraph_format(para, align="center", space_before=26, space_after=10, line_spacing=1.0)
        para.add_run().add_picture(logo, width=Inches(2.0))

    line("BCSE307P – COMPILER DESIGN LAB", 15, bold=True, space_before=18)
    line("PROJECT REPORT — REVIEW 3", 15, bold=True, space_before=6)
    line(PROJECT_TITLE, 16, bold=True, space_before=34)
    line("Submitted by", 12, space_before=30)
    for name, register in TEAM:
        line(f"{name} – {register}", 12, italic=True, space_before=3)
    line("Under the guidance of", 12, space_before=22)
    line(GUIDE, 12, bold=True, space_before=4)
    line(GUIDE_TITLE, 12, bold=True, space_before=3)
    line(MONTH_YEAR, 15, bold=True, space_before=22)


def render_certificate(doc):
    para = doc.add_paragraph()
    paragraph_format(para, align="center", space_after=18, line_spacing=1.0)
    run = para.add_run("BONAFIDE CERTIFICATE")
    set_run_font(run, size=16, bold=True)

    names = ", ".join(f"{n} ({r})" for n, r in TEAM)
    body = (
        f"This is to certify that the project work titled **{PROJECT_TITLE}** is a bonafide record of "
        f"work carried out by **{names}**, submitted in partial fulfilment of the requirements for the "
        "course BCSE307P – Compiler Design Lab, School of Computer Science and Engineering, VIT Vellore, "
        "during the academic year 2026 - 2027."
    )
    para = doc.add_paragraph()
    paragraph_format(para, align="justify", space_after=26, line_spacing=1.5)
    add_inline(para, body)

    for label in ("Faculty Guide: ", "Date: "):
        para = doc.add_paragraph()
        paragraph_format(para, align="left", space_after=14, line_spacing=1.5)
        run = para.add_run(label)
        set_run_font(run, size=11, bold=True)
        run = para.add_run("________________________________")
        set_run_font(run, size=11)


def render_declaration(doc):
    para = doc.add_paragraph()
    paragraph_format(para, align="center", space_after=18, line_spacing=1.0)
    run = para.add_run("DECLARATION")
    set_run_font(run, size=16, bold=True)

    body = (
        f"We hereby declare that the project report titled **{PROJECT_TITLE}** submitted by us to "
        "VIT Vellore in partial fulfilment of the requirement for the award of the degree/course "
        "BCSE307P – Compiler Design Lab is a record of bona fide work carried out by us under the "
        f"supervision of {GUIDE}. The contents of this report, in full or in part, have not been "
        "submitted to any other institute or university for the award of any degree or diploma."
    )
    para = doc.add_paragraph()
    paragraph_format(para, align="justify", space_after=26, line_spacing=1.5)
    add_inline(para, body)

    for label in ("Place: ", "Date: "):
        para = doc.add_paragraph()
        paragraph_format(para, align="left", space_after=14, line_spacing=1.5)
        run = para.add_run(label)
        set_run_font(run, size=11, bold=True)
        run = para.add_run("________________________________")
        set_run_font(run, size=11)

    para = doc.add_paragraph()
    paragraph_format(para, align="left", space_before=18, line_spacing=1.5)
    run = para.add_run("Signatures of all team members")
    set_run_font(run, size=11, italic=True)


def render_abstract(doc, abstract):
    para = doc.add_paragraph()
    paragraph_format(para, align="center", space_after=18, line_spacing=1.0)
    run = para.add_run("ABSTRACT")
    set_run_font(run, size=16, bold=True)

    para = doc.add_paragraph()
    paragraph_format(para, align="justify", space_after=6, line_spacing=1.5)
    add_inline(para, abstract)


def split_list_rows(rows, capacity_lines=35, size=12.0):
    """Split a front-matter list into the pages it needs, as evenly as possible.

    A row that is too long for one line costs two lines, so the count comes from the
    same text metrics that break the body text. Pages are then filled evenly, because a
    second page holding one row looks like a mistake.
    """
    if not rows:
        return [[]]

    def lines_of(row):
        indent = 24 if row.get("level", 1) > 1 else 0
        return wrap_lines(row["text"], size, PAGE_TEXT_WIDTH - indent, bold=(row.get("level", 1) == 1))

    pages, used = [[]], 0
    for row in rows:
        need = lines_of(row)
        if pages[-1] and used + need > capacity_lines:
            pages.append([])
            used = 0
        pages[-1].append(row)
        used += need
    if len(pages) == 1:
        return pages
    # even distribution over the pages the greedy pass needed
    count = len(pages)
    per_page = math.ceil(len(rows) / count)
    return [rows[index:index + per_page] for index in range(0, len(rows), per_page)]


def render_list(doc, title, rows, field=None, page_size=12, indent=24):
    """A front-matter list: contents, list of figures or list of tables.

    ``rows`` are dicts with ``text``, ``page`` and an optional ``level``. ``field`` adds a
    Word field around the rows so that Word can refresh the list if the text is edited.
    """
    para = doc.add_paragraph()
    paragraph_format(para, align="center", space_after=18, line_spacing=1.0)
    run = para.add_run(title)
    set_run_font(run, size=16, bold=True)

    first = True
    paragraphs = []
    for entry in rows:
        if entry.get("new_page") and not first:
            doc.add_page_break()
        level = entry.get("level", 1)
        p = doc.add_paragraph()
        paragraph_format(p, align="left", space_after=4, line_spacing=1.0,
                         left_indent=indent * (level - 1))
        p.paragraph_format.tab_stops.add_tab_stop(
            Inches(6.5), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        paragraphs.append(p)

        if first and field:
            run = p.add_run()
            begin = OxmlElement("w:fldChar")
            begin.set(qn("w:fldCharType"), "begin")
            instr = OxmlElement("w:instrText")
            instr.set(qn("xml:space"), "preserve")
            instr.text = field
            separate = OxmlElement("w:fldChar")
            separate.set(qn("w:fldCharType"), "separate")
            run._r.append(begin)
            run._r.append(instr)
            run._r.append(separate)
            first = False

        text_run = p.add_run(strip_markup(entry["text"]))
        set_run_font(text_run, size=page_size, bold=(level == 1 and title == "TABLE OF CONTENTS"))
        tab_run = p.add_run("\t")
        set_run_font(tab_run, size=page_size)
        page_run = p.add_run(str(entry["page"] if entry["page"] is not None else ""))
        set_run_font(page_run, size=page_size, bold=(level == 1 and title == "TABLE OF CONTENTS"))

    if field and paragraphs:
        run = paragraphs[-1].add_run()
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        run._r.append(end)
    # no trailing page break: the first chapter opens with its own


# -------------------------------------------------------------------- rendering
def render_blocks(doc, blocks):
    for block in blocks:
        kind = block["kind"]
        if kind == "toc":
            continue
        if kind == "pagebreak":
            doc.add_page_break()
            continue
        if kind == "chapter":
            doc.add_page_break()
            # One Heading 1 paragraph carries both lines: the number, a line break, then
            # the title. Word then lists the chapter in a refreshed table of contents with
            # its number, which two separate paragraphs would not do.
            title = doc.add_paragraph(style="Heading 1")
            paragraph_format(title, align="center", space_before=0, space_after=20, line_spacing=1.0,
                             keep_with_next=True)
            label = title.add_run(f"CHAPTER {block['number']}")
            set_run_font(label, size=18, bold=True)
            label.add_break()
            run = title.add_run(block["title"])
            set_run_font(run, size=18, bold=True)
            continue
        if kind == "front_heading":
            doc.add_page_break()
            para = doc.add_paragraph(style="Heading 1")
            paragraph_format(para, align="center", space_before=0, space_after=18, line_spacing=1.0,
                             keep_with_next=True)
            run = para.add_run(block["text"])
            set_run_font(run, size=18, bold=True)
            continue
        if kind == "h2":
            para = doc.add_paragraph(style="Heading 2")
            paragraph_format(para, align="left", space_before=14, space_after=6, line_spacing=1.15,
                             keep_with_next=True)
            add_inline(para, block["text"], size=16, base_bold=True)
            continue
        if kind == "h3":
            para = doc.add_paragraph()
            paragraph_format(para, align="left", space_before=10, space_after=4, line_spacing=1.15,
                             keep_with_next=True)
            add_inline(para, block["text"], size=14, base_bold=True, base_italic=True)
            continue
        if kind == "p":
            para = doc.add_paragraph()
            paragraph_format(
                para,
                align=block["align"],
                space_before=0,
                space_after=block["space_after"],
                line_spacing=1.5,
                keep_with_next=block["keep_with_next"],
            )
            add_inline(para, block["text"], size=block["size"], base_italic=block["italic"])
            continue
        if kind == "bullets":
            for index, item in enumerate(block["items"], start=1):
                para = doc.add_paragraph()
                paragraph_format(
                    para,
                    align="justify",
                    space_after=2,
                    line_spacing=1.5,
                    left_indent=BULLET_INDENT_PT,
                    first_line=-12,
                )
                mark = f"{index}. " if block["numbered"] else "\u2022 "
                run = para.add_run(mark)
                set_run_font(run, size=block["size"])
                add_inline(para, item, size=block["size"])
            continue
        if kind == "note":
            para = doc.add_paragraph()
            paragraph_format(para, align="justify", space_before=2, space_after=8, line_spacing=1.0,
                             left_indent=6)
            add_inline(para, block["text"], size=10.5, base_italic=True)
            continue
        if kind == "code":
            if block["caption"]:
                para = doc.add_paragraph()
                paragraph_format(para, align="left", space_before=8, space_after=2, line_spacing=1.0,
                                 keep_with_next=True)
                add_inline(para, block["caption"], size=11, base_bold=True)
            lines = block["text"].splitlines() or [""]
            for index, line in enumerate(lines):
                para = doc.add_paragraph()
                paragraph_format(para, align="left", space_before=0 if index else 6,
                                 space_after=0, line_spacing=1.0, left_indent=6,
                                 keep_with_next=index < len(lines) - 1)
                if index == 0:
                    shade(para._p.get_or_add_pPr(), "F2F4F7")
                run = para.add_run(line if line else " ")
                set_run_font(run, name=MONO_FONT, size=10)
            spacer = doc.add_paragraph()
            paragraph_format(spacer, align="left", space_after=0, line_spacing=1.0)
            spacer.paragraph_format.space_before = Pt(0)
            continue
        if kind == "references":
            for index, entry in enumerate(block["items"], start=1):
                para = doc.add_paragraph()
                paragraph_format(para, align="justify", space_after=8, line_spacing=1.5,
                                 left_indent=30, first_line=-30)
                para.paragraph_format.tab_stops.add_tab_stop(Inches(0.42))
                run = para.add_run(f"[{index}]")
                set_run_font(run, size=BODY_PT)
                tab = para.add_run("\t")
                set_run_font(tab, size=BODY_PT)
                add_inline(para, entry, size=BODY_PT)
            continue
        if kind == "table":
            render_table(doc, block)
            continue
        if kind == "figure":
            para = doc.add_paragraph()
            paragraph_format(para, align="center", space_before=10, space_after=4, line_spacing=1.0,
                             keep_with_next=True)
            para.add_run().add_picture(block["path"], width=Inches(block["width_in"]))
            cap = doc.add_paragraph()
            paragraph_format(cap, align="center", space_after=10, line_spacing=1.0)
            add_inline(cap, block["caption"], size=11, base_italic=True)
            continue
        if kind == "spacer":
            para = doc.add_paragraph()
            paragraph_format(para, align="left", space_after=0, line_spacing=1.0)
            para.paragraph_format.space_after = Pt(block["pts"])
            continue


def fitting_widths(headers, rows, widths, size):
    """Widen any column that is narrower than its longest unbreakable word.

    A path such as ``codetrace/reporting/html_report.py`` cannot wrap at a space, so a
    column narrower than the path breaks the word across two lines. The requested
    widths are therefore raised to fit the longest word of each column, and the extra
    space is taken from the columns that have the most slack, keeping the total within
    the text width. If the words cannot fit even then, the requested widths are kept.
    """
    pad = 0.134                     # both cell margins, in inches
    need = []
    for column in range(len(widths)):
        longest = 0.0
        for row in [headers] + list(rows):
            for token in str(row[column]).split():
                longest = max(longest, stringWidth(token, "Times-Roman", size))
        # a word that is only slightly wider than the column may hyphenate, so the
        # column is not forced to its exact width for a single long token
        need.append(min(longest / 72.0 + pad, widths[column] + 0.25))

    limit = PAGE_TEXT_WIDTH / 72.0
    if sum(need) > limit:
        return widths

    # start at the minimum that keeps every word whole, then grow towards the widths
    # that were asked for, and finally share out anything still unused
    spare = limit - sum(need)
    growth = [max(0.0, w - n) for w, n in zip(widths, need)]
    result = list(need)
    if spare > 0 and sum(growth) > 0:
        take = min(spare, sum(growth))
        result = [n + take * g / sum(growth) for n, g in zip(need, growth)]
        spare -= take
    if spare > 0:
        result = [w + spare * w / sum(result) for w in result]
    return [round(w, 2) for w in result]


def render_table(doc, block):
    cap = doc.add_paragraph()
    paragraph_format(cap, align="left", space_before=12, space_after=4, line_spacing=1.0,
                     keep_with_next=True)
    add_inline(cap, block["caption"], size=11, base_bold=True)

    table = doc.add_table(rows=1, cols=len(block["headers"]))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False          # python-docx writes w:tblLayout w:type="fixed"
    cell_margins = OxmlElement("w:tblCellMar")
    for side, value in (("left", 96), ("right", 96), ("top", 40), ("bottom", 40)):
        element = OxmlElement(f"w:{side}")
        element.set(qn("w:w"), str(value))
        element.set(qn("w:type"), "dxa")
        cell_margins.append(element)
    insert_ordered(table._tbl.tblPr, cell_margins, TBLPR_ORDER)

    for index, width in enumerate(block["widths"]):
        table.columns[index].width = Inches(width)

    header_cells = table.rows[0].cells
    for index, text in enumerate(block["headers"]):
        cell = header_cells[index]
        cell.width = Inches(block["widths"][index])
        cell.text = ""
        para = cell.paragraphs[0]
        paragraph_format(para, align="left", space_before=2, space_after=3, line_spacing=1.0)
        add_inline(para, text, size=block["size"], base_bold=True)
        shade(cell._tc.get_or_add_tcPr(), "D9D9D9")
    trpr = table.rows[0]._tr.get_or_add_trPr()
    mark = OxmlElement("w:tblHeader")
    insert_ordered(trpr, mark, TRPR_ORDER)

    for row in block["rows"]:
        cells = table.add_row().cells
        for index, text in enumerate(row):
            cells[index].width = Inches(block["widths"][index])
            para = cells[index].paragraphs[0]
            paragraph_format(para, align="left", space_before=2, space_after=3, line_spacing=1.0)
            add_inline(para, str(text), size=block["size"])
        no_split = OxmlElement("w:cantSplit")
        insert_ordered(table.rows[-1]._tr.get_or_add_trPr(), no_split, TRPR_ORDER)

    if block.get("note"):
        note = doc.add_paragraph()
        paragraph_format(note, align="left", space_before=3, space_after=10, line_spacing=1.0)
        add_inline(note, block["note"], size=10.5, base_italic=True)
    else:
        gap = doc.add_paragraph()
        paragraph_format(gap, align="left", space_after=0, line_spacing=1.0)
        gap.paragraph_format.space_after = Pt(8)


# ------------------------------------------------------------------------ build
def collect_facts(content):
    """Numbers the report quotes, measured from the checkout at build time."""
    layout = []
    total_files = total_lines = 0
    for label, paths in content.GROUPS:
        count, lines = content.totals(paths)
        description = getattr(content, "GROUP_DESCRIPTIONS", {}).get(label, "")
        layout.append((label, count, lines, description))
        total_files += count
        total_lines += lines
    return {
        "layout": layout,
        "total_files": total_files,
        "total_lines": total_lines,
    }


def build(output, abstract=None, start_page_override=None, page_map=None):
    import review3_content as content

    facts = collect_facts(content)
    composer = Composer()
    content.add(composer, facts)
    blocks = composer.blocks

    entries = [b for b in blocks if b["kind"] == "toc"]
    figure_rows = [{"kind": "figure", "text": b["numbered_caption"], "block": b}
                   for b in blocks if b["kind"] == "figure"]
    table_rows = [{"kind": "table", "text": b["caption"], "block": b}
                  for b in blocks if b["kind"] == "table"]

    front_pages = 4                      # cover, certificate, declaration, abstract
    page_counts = [len(split_list_rows(rows))
                   for rows in (entries, figure_rows, table_rows)]
    start_page = front_pages + sum(page_counts) + 1   # +1: the first body page follows the lists
    if start_page_override:
        start_page = start_page_override
    last_page = paginate(blocks, start_page)

    if page_map:
        # measured page numbers (from a rendered proof) win over the estimate
        for entry in entries:
            measured = page_map.get(strip_markup(entry["text"]))
            if measured:
                entry["page"] = measured
        for row in figure_rows + table_rows:
            measured = page_map.get(strip_markup(row["text"]))
            if measured:
                row["page"] = measured

    for row in figure_rows + table_rows:
        if row.get("page") is None:
            row["page"] = row["block"].get("_page")

    def chunk(rows):
        """Tag the first row of every page so the renderer can force the break."""
        pages = split_list_rows(rows)
        marked = []
        for index, page in enumerate(pages):
            for position, row in enumerate(page):
                item = dict(row)
                item["new_page"] = index > 0 and position == 0
                marked.append(item)
        return pages, marked

    toc_pages, toc_rows = chunk(entries)
    lof_pages, lof_rows = chunk(figure_rows)
    lot_pages, lot_rows = chunk(table_rows)

    doc = new_document()
    render_cover(doc)
    doc.add_page_break()
    render_certificate(doc)
    doc.add_page_break()
    render_declaration(doc)
    doc.add_page_break()
    render_abstract(doc, abstract or content.ABSTRACT)
    doc.add_page_break()
    render_list(doc, "TABLE OF CONTENTS", toc_rows,
                field=' TOC \\o "1-2" \\h \\z \\u ')
    doc.add_page_break()
    # the figure and table lists are written as plain text: the captions are not SEQ
    # fields, so a Word field here would be emptied the first time it was refreshed
    render_list(doc, "LIST OF FIGURES", lof_rows)
    doc.add_page_break()
    render_list(doc, "LIST OF TABLES", lot_rows)
    render_blocks(doc, blocks)

    props = doc.core_properties
    props.title = f"Review 3 — {PROJECT_TITLE}"
    props.subject = "BCSE307P – Compiler Design Lab, Review 3 project report"
    props.author = ", ".join(f"{name} ({register})" for name, register in TEAM)
    props.keywords = ("CodeTrace, compiler design, LR parsing, data-flow analysis, "
                      "taint analysis, program slicing")
    props.comments = f"Repository: {REPO_URL}"

    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    doc.save(output)

    print(f"wrote {output}")
    print(f"  tables  : {len(table_rows)}")
    print(f"  figures : {len(figure_rows)}")
    print(f"  toc rows: {len(entries)} ({len(toc_pages)} page(s))")
    print(f"  lof/lot : {len(figure_rows)} figures, {len(table_rows)} tables "
          f"({len(lof_pages)}+{len(lot_pages)} page(s))")
    # the estimate is only a fallback; when a measured map is supplied, report the page
    # numbers the document actually carries
    pages = max((b["page"] for b in entries if b.get("page")), default=last_page)
    print(f"  pages   : about {pages}")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output",
                        default=os.path.join(ROOT, "docs", "Review3_CodeTrace_Report.docx"))
    parser.add_argument("--start-page", type=int, default=None,
                        help="override the first body page number")
    parser.add_argument("--page-map", default=None,
                        help="JSON file mapping a heading label to a measured page number; "
                             "used to fill the table of contents from a rendered proof")
    args = parser.parse_args(argv)
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    page_map = None
    if args.page_map:
        import json
        with open(args.page_map, encoding="utf-8") as handle:
            page_map = json.load(handle)
    build(args.output, start_page_override=args.start_page, page_map=page_map)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
