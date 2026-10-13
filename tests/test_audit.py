"""Tests for the audit script.

The audit is the repository's own Definition-of-Done check, so it is worth
holding to a standard too: it has to actually pass on this checkout, its module
table writer has to be idempotent (a "fix" that keeps changing the file would be
worse than no fix), and its drift detection has to notice a wrong number rather
than accept whatever it finds.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_audit():
    path = os.path.join(ROOT, "scripts", "audit.py")
    spec = importlib.util.spec_from_file_location("audit_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AuditRunTests(unittest.TestCase):
    def test_the_audit_passes_on_this_checkout(self):
        # The whole point of the script: a reviewer runs it and gets a verdict.
        # If this fails, the failure is real and the message says which check.
        result = subprocess.run(
            [sys.executable, "scripts/audit.py"], cwd=ROOT,
            capture_output=True, text=True, timeout=900,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output[-2000:])
        self.assertIn("checks passed", output)
        self.assertNotIn("[FAIL]", output)


class ModuleTableTests(unittest.TestCase):
    """The module table is checked exactly, so its maintenance must be safe."""

    @classmethod
    def setUpClass(cls):
        cls.audit = load_audit()
        cls.path = os.path.join(ROOT, cls.audit.MODULE_TABLE_PATH)

    def test_writing_the_table_is_idempotent(self):
        with open(self.path, "rb") as handle:
            before = handle.read()
        with contextlib.redirect_stdout(io.StringIO()):
            status = self.audit.write_module_table()
        self.assertEqual(status, 0)
        with open(self.path, "rb") as handle:
            after = handle.read()
        self.assertEqual(before, after, "a refresh with no drift must not touch the file")

    def test_every_measured_row_has_a_line_in_the_table(self):
        self.audit.SILENT = True
        try:
            self.audit.check_claims()
        finally:
            self.audit.SILENT = False
        measured = set(self.audit._MEASURED_MODULES)
        with open(self.path, encoding="utf-8") as handle:
            text = handle.read()
        named = set(re.findall(r"^\| `([^`]+)` \| \d+ \| \d+ \|", text, re.M))
        missing = measured - named
        self.assertEqual(missing, set(), f"rows missing from the table: {sorted(missing)}")

    def test_the_check_notices_a_wrong_number(self):
        # Break the table in a scratch copy, run the audit's own comparison
        # logic over it, and require it to report drift.  The real file is
        # restored in `finally`.
        with open(self.path, encoding="utf-8") as handle:
            original = handle.read()
        broken = re.sub(r"^\| `codetrace/analysis` \| (\d+) \| \d+ \|",
                        lambda m: f"| `codetrace/analysis` | {m.group(1)} | 1 |",
                        original, count=1, flags=re.M)
        self.assertNotEqual(broken, original, "the test found the row to break")
        try:
            with open(self.path, "w", encoding="utf-8") as handle:
                handle.write(broken)
            result = subprocess.run(
                [sys.executable, "scripts/audit.py", "-v"], cwd=ROOT,
                capture_output=True, text=True, timeout=900,
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, "a wrong line count must fail the audit")
            self.assertIn("module table", output)
            self.assertIn("codetrace/analysis", output)
        finally:
            with open(self.path, "w", encoding="utf-8") as handle:
                handle.write(original)
        # And the restore is exact, so the suite can carry on.
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), original.encode("utf-8"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
