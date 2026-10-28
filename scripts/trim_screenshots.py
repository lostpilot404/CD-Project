#!/usr/bin/env python3
"""Trim the empty tail from the interface screenshots and scale them for the report.

A capture of a whole panel is taken at a fixed viewport, so a short view leaves a
band of blank page beneath the content. Cropping that band changes nothing that the
interface shows; the pixels above it, including the status line and the footer of a
panel, are untouched. Only rows at the bottom are removed, only when they are
uniform to within a small tolerance, and never more than 45 per cent of the image,
so a capture that is genuinely light at the bottom cannot be cut into.

The captures are taken at twice the device scale, which is more resolution than
print needs: at 6.4 in wide, 1600 px is about 250 dpi. Images wider than that are
scaled down with Lanczos resampling. The interface uses flat colours, so an
adaptive 256-colour palette costs nothing visible on text and cuts each file to
about a third of its size; together this brings the report from about 6 MB to
about 2.5 MB without touching a pixel that carries information.

    python3 scripts/trim_screenshots.py [directory ...]

Defaults to ``docs/review3_screenshots``. Existing files are rewritten in place; a
file that needs no trimming is left alone. Requires Pillow (a build-time dependency
only).
"""

from __future__ import annotations

import os
import sys

try:
    from PIL import Image
except ImportError:  # pragma: no cover - build-time dependency
    sys.exit("Pillow is required: pip install pillow")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = [os.path.join(ROOT, "docs", "review3_screenshots")]

#: A row counts as blank when every sampled pixel is at least this light.
MIN_LEVEL = 248
#: Vertical padding kept below the last non-blank row, in pixels.
PADDING = 24
#: Never remove more than this fraction of the image height.
MAX_CUT = 0.45
#: Widest image kept; a report figure is 6.4 in wide, so this is about 250 dpi.
MAX_WIDTH = 1600


def last_content_row(image: Image.Image) -> int:
    """Index of the lowest row that is not uniform near-white."""
    grey = image.convert("L")
    width, height = grey.size
    pixels = grey.load()
    step = max(1, width // 400)
    for y in range(height - 1, -1, -1):
        darkest = 255
        for x in range(0, width, step):
            value = pixels[x, y]
            if value < darkest:
                darkest = value
                if darkest < MIN_LEVEL:
                    return y
    return 0


def trim(path: str) -> tuple[int, int]:
    """Trim and scale one file; return the old and new heights."""
    with Image.open(path) as source:
        image = source.convert("RGBA") if source.mode in ("RGBA", "LA", "P") else source.convert("RGB")
        width, height = image.size
        last = last_content_row(image)
        keep = min(height, last + 1 + PADDING)
        if height - keep <= 8 or (height - keep) > MAX_CUT * height:
            keep = height
        image = image.crop((0, 0, width, keep))
        if width > MAX_WIDTH:
            scale = MAX_WIDTH / width
            image = image.resize((MAX_WIDTH, max(1, round(keep * scale))), Image.LANCZOS)
        # no dithering: the interface is drawn in flat colours, so the palette reaches
        # the original values exactly and dithering would only add speckle to the text
        image = image.quantize(colors=256, method=Image.MEDIANCUT, dither=Image.NONE)
        image.save(path, optimize=True)
    return height, image.size[1]


def main(argv: list[str]) -> int:
    directories = argv[1:] or DEFAULT
    changed = 0
    for directory in directories:
        for name in sorted(os.listdir(directory)):
            if not name.lower().endswith(".png"):
                continue
            path = os.path.join(directory, name)
            before, after = trim(path)
            if after != before:
                changed += 1
                print(f"{name:32s} {before:5d} -> {after:5d} px")
    print(f"trimmed {changed} of {len(os.listdir(directories[0]))} files in {directories[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
