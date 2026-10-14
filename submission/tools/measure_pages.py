# -*- coding: utf-8 -*-
"""Locate the report headings in a rendered PDF and write a heading -> page map.

Usage:
    python3 measure_pages.py <report.pdf> <pages.json>

The heading list is taken from report_content.py (chapter numbers, chapter
titles, second-level headings and REFERENCES), i.e. exactly the entries of the
table of contents.  For each heading the *last* page on which its text occurs
is used, because the first occurrence is the TOC itself.
"""
import json
import os
import re
import sys

from pypdf import PdfReader

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import report_content as C  # noqa: E402

CHAPTERS = [
    ("CHAPTER 1", "INTRODUCTION", C.CHAPTER1),
    ("CHAPTER 2", "LITERATURE SURVEY", C.CHAPTER2),
    ("CHAPTER 3", "SYSTEM DESIGN", C.CHAPTER3),
    ("CHAPTER 4", "IMPLEMENTATION DETAILS", C.CHAPTER4),
]


def toc_headings():
    out = []
    for num, title, blocks in CHAPTERS:
        out.append(num)
        out.append(title)
        out.extend(b[1] for b in blocks if b[0] == "h2")
    out.append("REFERENCES")
    return out


def main():
    pdf, out = sys.argv[1], sys.argv[2]
    reader = PdfReader(pdf)
    pages = [re.sub(r"\s+", " ", p.extract_text() or "") for p in reader.pages]
    print("pages:", len(pages))
    result = {}
    last = 0
    for h in toc_headings():
        hn = re.sub(r"\s+", " ", h)
        found = [i + 1 for i, t in enumerate(pages) if hn in t]
        page = found[-1] if found else None
        result[h] = page
        flag = "" if page is not None and page >= last else "  <-- check"
        print(f"{page!s:>4}  {h}{flag}")
        if page is not None:
            last = page
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)


if __name__ == "__main__":
    main()
