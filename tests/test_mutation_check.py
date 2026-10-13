"""Tests for the mutation checker itself.

The mutation checker is evidence, so it is held to the same standard as the
engine: the catalogue has to keep applying (an anchor that no longer matches
would silently stop testing anything), it has to refuse to rewrite a file with
unsaved work, and it has to be able to fail -- a checker that reports "caught"
for everything would be worse than no checker at all.

The last of those is checked by running one real mutation through the real
script, in a subprocess, over the real test suite.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_checker():
    """Import scripts/mutation_check.py without making scripts a package."""
    path = os.path.join(ROOT, "scripts", "mutation_check.py")
    spec = importlib.util.spec_from_file_location("mutation_check_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MutationCatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checker = load_checker()

    def test_the_catalogue_is_not_empty_and_covers_the_pipeline(self):
        mutations = self.checker.MUTATIONS
        self.assertGreaterEqual(len(mutations), 12)
        areas = {mutation.area for mutation in mutations}
        for area in ("parser", "semantics", "cfg", "dataflow", "taint", "slicing", "rules",
                     "reporting"):
            self.assertIn(area, areas, f"no mutation covers {area}")
        keys = [mutation.key for mutation in mutations]
        self.assertEqual(len(set(keys)), len(keys), "mutation keys are unique")

    def test_every_anchor_applies_exactly_once(self):
        # An anchor that matches zero or several times would either raise in the
        # middle of a run or mutate the wrong place; both are caught here, before
        # anything is rewritten.
        for mutation in self.checker.MUTATIONS:
            with self.subTest(mutation=mutation.key):
                path = os.path.join(ROOT, mutation.path)
                self.assertTrue(os.path.exists(path), mutation.path)
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                self.assertEqual(
                    text.count(mutation.old), 1,
                    f"{mutation.key}: anchor matches {text.count(mutation.old)} times",
                )
                self.assertNotEqual(mutation.old, mutation.new)

    def test_every_mutation_leaves_a_parseable_program(self):
        # A mutation that produces a syntax error would be caught by any test at
        # all, which would say nothing about the analysis.
        for mutation in self.checker.MUTATIONS:
            with self.subTest(mutation=mutation.key):
                path = os.path.join(ROOT, mutation.path)
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                mutated = text.replace(mutation.old, mutation.new, 1)
                ast.parse(mutated)  # raises if the mutation breaks the file

    def test_every_mutation_names_tests_that_exist(self):
        for mutation in self.checker.MUTATIONS:
            with self.subTest(mutation=mutation.key):
                self.assertTrue(mutation.tests, f"{mutation.key} names no test module")
                for target in mutation.tests:
                    module_path = os.path.join(ROOT, target.replace(".", os.sep) + ".py")
                    self.assertTrue(os.path.exists(module_path), target)


class MutationCheckerSafetyTests(unittest.TestCase):
    """The checker rewrites engine files, so its safety properties are tested."""

    @classmethod
    def setUpClass(cls):
        cls.checker = load_checker()

    def test_an_untracked_file_counts_as_dirty(self):
        with tempfile.NamedTemporaryFile(
            dir=ROOT, prefix="mutation-probe-", suffix=".py", delete=False
        ) as handle:
            probe = handle.name
        try:
            relative = os.path.relpath(probe, ROOT)
            clean, dirty = self.checker.git_is_clean([relative])
            self.assertFalse(clean, "an untracked file must never be rewritten")
            self.assertEqual(dirty, [relative])
        finally:
            os.unlink(probe)

    def test_a_committed_file_counts_as_clean(self):
        clean, dirty = self.checker.git_is_clean(["codetrace/analysis/taint.py"])
        self.assertTrue(clean, f"unexpectedly dirty: {dirty}")

    def test_one_real_mutation_is_caught_by_the_real_suite(self):
        # The strongest check available here: run the checker exactly as a
        # reviewer would, over one mutation whose test module is fast.
        result = subprocess.run(
            [sys.executable, "scripts/mutation_check.py", "--only", "definite-initial-bottom"],
            cwd=ROOT, capture_output=True, text=True, timeout=900,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("caught", output)
        self.assertIn("1/1 mutations were caught", output)
        # And the file it rewrote is byte-identical to the committed version
        # afterwards.
        diff = subprocess.run(
            ["git", "diff", "--quiet", "--", "codetrace/analysis/definite_assignment.py"],
            cwd=ROOT, capture_output=True,
        )
        self.assertEqual(diff.returncode, 0, "the checker left the engine modified")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
