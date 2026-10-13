"""Source-text helpers shared by the front end and the reporting layer."""

from __future__ import annotations

from bisect import bisect_right
from typing import List, Tuple


class LineIndex:
    """Offset -> (line, column) conversion for one source text.

    Lines and columns are 1-based; columns count characters (not bytes), which
    matches what the API and the UI display.
    """

    def __init__(self, text: str) -> None:
        starts: List[int] = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                starts.append(i + 1)
        self._starts = starts
        self.text = text

    def position(self, offset: int) -> Tuple[int, int]:
        offset = max(0, min(offset, len(self.text)))
        line = bisect_right(self._starts, offset) - 1
        return line + 1, offset - self._starts[line] + 1

    def line_text(self, line: int) -> str:
        if line < 1 or line > len(self._starts):
            return ""
        start = self._starts[line - 1]
        end = self._starts[line] - 1 if line < len(self._starts) else len(self.text)
        return self.text[start:end]

    @property
    def line_count(self) -> int:
        return len(self._starts)


def split_lines(text: str) -> List[str]:
    """Split into lines without trailing newline characters."""
    return text.split("\n")
