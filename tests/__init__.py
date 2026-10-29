"""Permanent regression tests for CodeTrace — standard-library ``unittest`` only.

Run from anywhere:

    python3 -m unittest discover -s tests -v      # from the repository root
    scripts/test.sh                               # wrapper for the same

Every test in this package pins a contract that is documented in ``docs/`` or
that was fixed during the 2026-10 full-stack audit; each test's docstring says
which one, so a failure names the regression instead of merely a number.

The frontend has its own (Node/jsdom) suite in ``frontend-tests/``; nothing
here needs Node, and nothing there needs these files.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
