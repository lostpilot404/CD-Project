#!/usr/bin/env python3
"""Mutation check: does the test suite actually notice when the engine breaks?

A passing suite proves that the tests agree with the code, not that the tests
would object to a *wrong* engine.  This script answers the second question the
only way that is honest about it: it breaks the engine on purpose, one semantic
change at a time, and records whether the suite fails.

Each mutation below is a small, plausible defect of the kind a real bug produces
-- an analysis seeded at the wrong lattice end, a kill set dropped, a sanitizer
context ignored, a validator guard removed, a lookup that stops walking the
scope chain.  For every one of them the script

1. asserts the anchor text occurs exactly once (so a mutation that silently
   stops applying is an error, not a pass),
2. applies the edit in place,
3. runs the test modules that are supposed to catch it,
4. restores the file byte-for-byte from an in-memory copy, and
5. reports *caught* (the suite failed) or **ESCAPED** (the suite passed, which
   is a hole in the tests).

Only *behavioural* mutations belong in the catalogue.  A mutation that cannot
change any result proves nothing about the tests, so one candidate was measured
and dropped: passing ``kinds=None`` to a slice traversal (following every edge
kind instead of ``SLICE_KINDS``) produced byte-identical slices for every
statement of every example, because ``SLICE_KINDS`` already names all eight edge
kinds the dependency graph defines (``dependencies.EDGE_KINDS``).  It is an
equivalent program, not an untested one.  The catalogue keeps the three slicing
mutations that do change slices.

The script exits non-zero if any mutation escapes, because a suite that cannot
fail is not evidence.  It does not change the anchor comments or the file
permissions, and it refuses to run if any target file has uncommitted changes,
so a crash in the middle cannot lose work that was not already saved elsewhere.

    python3 scripts/mutation_check.py            # run every mutation
    python3 scripts/mutation_check.py -v         # show the failing test detail
    python3 scripts/mutation_check.py --list     # list the catalogue
    python3 scripts/mutation_check.py --only taint
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@dataclass
class Mutation:
    """One deliberate defect and the tests that are supposed to notice it."""

    key: str
    area: str
    description: str
    path: str
    old: str
    new: str
    tests: List[str]


MUTATIONS: List[Mutation] = [
    # -- parser ------------------------------------------------------------
    Mutation(
        key="lr1-lookahead-not-propagated",
        area="parser",
        description="LR(1) closure adds items with an empty lookahead (SLR-style follow set lost)",
        path="codetrace/frontend/grammar.py",
        old="""            lookaheads = self.first_of_sequence_with_lookahead(beta, lookahead)""",
        new="""            lookaheads = {""}""",
        tests=["tests.test_parser"],
    ),
    Mutation(
        key="lr1-closure-drops-beta",
        area="parser",
        description="LR(1) closure uses FIRST(beta) without the item's own lookahead",
        path="codetrace/frontend/grammar.py",
        old="""            lookaheads = self.first_of_sequence_with_lookahead(beta, lookahead)""",
        new="""            lookaheads = self.first_of_sequence_with_lookahead(beta, "")""",
        tests=["tests.test_parser"],
    ),
    # -- semantics ---------------------------------------------------------
    Mutation(
        key="lookup-stops-at-first-scope",
        area="semantics",
        description="name lookup stops after the innermost scope (no outer scopes)",
        path="codetrace/semantics/symbol_table.py",
        old="""            if name in scope.symbols:
                return scope.symbols[name]
            current = scope.parent""",
        new="""            if name in scope.symbols:
                return scope.symbols[name]
            break
            current = scope.parent""",
        tests=["tests.test_semantics"],
    ),
    # -- CFG ---------------------------------------------------------------
    Mutation(
        key="no-loop-back-edge",
        area="cfg",
        description="the loop back edge is not added, so the loop body never repeats",
        path="codetrace/analysis/cfg.py",
        old="""            body_end.add_edge(header, "loop-back", label="loop back edge")""",
        new="""            pass""",
        tests=["tests.test_cfg"],
    ),
    # -- reaching definitions ---------------------------------------------
    Mutation(
        key="reaching-kill-dropped",
        area="dataflow",
        description="reaching definitions forgets to kill the definitions it overwrites",
        path="codetrace/analysis/reaching_definitions.py",
        old="""        return (in_value & ~self.kill.get(block_id, 0)) | self.gen.get(block_id, 0)""",
        new="""        return in_value | self.gen.get(block_id, 0)""",
        tests=["tests.test_dataflow"],
    ),
    Mutation(
        key="reaching-may-becomes-must",
        area="dataflow",
        description="reaching definitions intersects instead of unioning (may becomes must)",
        path="codetrace/analysis/reaching_definitions.py",
        old="""        result = 0
        for value in values:
            result |= value
        return result""",
        new="""        if not values:
            return 0
        result = values[0]
        for value in values[1:]:
            result &= value
        return result""",
        tests=["tests.test_dataflow"],
    ),
    # -- liveness ----------------------------------------------------------
    Mutation(
        key="liveness-defs-not-killed",
        area="dataflow",
        description="liveness ignores the definitions in a block (IN = USE + OUT)",
        path="codetrace/analysis/liveness.py",
        old="""        return self.use.get(block_id, 0) | (out_value & ~self.defs.get(block_id, 0))""",
        new="""        return self.use.get(block_id, 0) | out_value""",
        tests=["tests.test_dataflow"],
    ),
    # -- definite assignment (must analysis) -------------------------------
    Mutation(
        key="definite-meet-union",
        area="dataflow",
        description="definite assignment unions instead of intersecting (must becomes may)",
        path="codetrace/analysis/definite_assignment.py",
        old="""        result = values[0]
        for value in values[1:]:
            result &= value
        return result""",
        new="""        result = 0
        for value in values:
            result |= value
        return result""",
        tests=["tests.test_dataflow"],
    ),
    Mutation(
        key="definite-initial-bottom",
        area="dataflow",
        description="must-analysis seeds every block at the lattice bottom, not the top",
        path="codetrace/analysis/definite_assignment.py",
        old="""        if block_id == self.cfg.entry:
            return self.domain.empty()""",
        new="""        if True:
            return self.domain.empty()""",
        tests=["tests.test_dataflow"],
    ),
    # -- taint -------------------------------------------------------------
    Mutation(
        key="sanitizer-ignores-context",
        area="taint",
        description="a sanitizer clears every context, not only the one it declares",
        path="codetrace/analysis/taint.py",
        old="""        for text in problem.atom_texts(atoms):
            if atom_context(text) == context:""",
        new="""        for text in problem.atom_texts(atoms):
            if True:""",
        tests=["tests.test_taint"],
    ),
    Mutation(
        key="unknown-call-assumed-safe",
        area="taint",
        description="an unknown function's result is assumed untainted (assumed safe)",
        path="codetrace/analysis/taint.py",
        old="""            for atoms in argument_atoms:
                result_atoms |= atoms
            if any(argument_atoms):""",
        new="""            if any(argument_atoms):""",
        tests=["tests.test_taint"],
    ),
    Mutation(
        key="validator-guard-ignored",
        area="taint",
        description="a validator guard no longer clears the flow crossing its branch",
        path="codetrace/analysis/taint.py",
        old="""        validators = [r for r in rules if r.kind == "validator"]""",
        new="""        validators = []""",
        tests=["tests.test_taint", "tests.test_reporting"],
    ),
    Mutation(
        key="guard-suppression-not-reported",
        area="reporting",
        description="a cleared flow is recorded but never reaches the report (silence instead of evidence)",
        path="codetrace/reporting/json_report.py",
        old="""    out = []
    for entry in getattr(program.taint, "guard_suppressions", None) or []:""",
        new="""    out = []
    for entry in []:""",
        tests=["tests.test_reporting"],
    ),
    # -- dependency graph and slicing --------------------------------------
    Mutation(
        key="slice-not-transitive",
        area="slicing",
        description="a slice stops at the sink's immediate neighbours instead of walking",
        path="codetrace/analysis/slicing.py",
        old="""                if neighbour not in visited:
                    queue.append(neighbour)""",
        new="""                if neighbour not in visited:
                    pass""",
        tests=["tests.test_slicing"],
    ),
    Mutation(
        key="slice-backward-walks-forward",
        area="slicing",
        description="a backward slice follows the wrong edge direction",
        path="codetrace/analysis/slicing.py",
        old="""                self.graph.incoming(node, kinds)
                if direction == "backward"
                else self.graph.outgoing(node, kinds)""",
        new="""                self.graph.outgoing(node, kinds)
                if direction == "backward"
                else self.graph.incoming(node, kinds)""",
        tests=["tests.test_slicing"],
    ),
    Mutation(
        key="slice-data-edges-dropped",
        area="slicing",
        description="data edges are not followed, so a slice misses the taint's origin",
        path="codetrace/analysis/slicing.py",
        old="""SLICE_KINDS = (DATA, CONTROL, CALL, RETURN, TAINT, SANITIZE, DEFINE, SOURCE_SINK)""",
        new="""SLICE_KINDS = (CONTROL, CALL, RETURN, TAINT, SANITIZE, DEFINE, SOURCE_SINK)""",
        tests=["tests.test_slicing"],
    ),
    # -- rule language -----------------------------------------------------
    Mutation(
        key="rule-unknown-selector-allowed",
        area="rules",
        description="the rule validator accepts an item it does not implement",
        path="codetrace/rules/rule_language.py",
        old="""        return [d for d in self.diagnostics if d.severity == "error"]""",
        new="""        return []""",
        tests=["tests.test_rules"],
    ),
    # -- reporting ---------------------------------------------------------
    Mutation(
        key="report-limitations-dropped",
        area="reporting",
        description="the report stops carrying the analysis limitations",
        path="codetrace/reporting/json_report.py",
        old="""        "limitations": list(STANDING_LIMITATIONS)""",
        new="""        "limitations": []  # mutation: list(STANDING_LIMITATIONS)""",
        tests=["tests.test_reporting"],
    ),
]


def git_is_clean(paths: List[str]) -> tuple:
    """Are the target files free of uncommitted changes?"""
    dirty = []
    for path in paths:
        result = subprocess.run(
            ["git", "diff", "--quiet", "--", path],
            cwd=ROOT, capture_output=True,
        )
        if result.returncode != 0:
            dirty.append(path)
        # Also catch files git does not track in this checkout.
        untracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", path],
            cwd=ROOT, capture_output=True,
        )
        if untracked.returncode != 0:
            dirty.append(path)
    return (not dirty), dirty


def run_tests(tests: List[str]) -> tuple:
    """Run the named test modules; return (succeeded, output tail)."""
    command = [sys.executable, "-m", "unittest", *tests]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=900)
    tail = (result.stderr or result.stdout).strip().splitlines()
    return result.returncode == 0, "\n".join(tail[-6:])


def apply_mutation(mutation: Mutation) -> None:
    path = os.path.join(ROOT, mutation.path)
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    occurrences = text.count(mutation.old)
    if occurrences != 1:
        raise SystemExit(
            f"mutation {mutation.key!r}: the anchor occurs {occurrences} times in "
            f"{mutation.path}, expected exactly 1 -- fix the catalogue, the mutation "
            f"was not applied"
        )
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text.replace(mutation.old, mutation.new, 1))


def main() -> int:
    parser = argparse.ArgumentParser(description="check that the suite catches broken engines")
    parser.add_argument("-v", "--verbose", action="store_true", help="print test output per mutation")
    parser.add_argument("--list", action="store_true", help="list the catalogue and exit")
    parser.add_argument("--only", default="", help="run only mutations whose key contains this text")
    args = parser.parse_args()

    if args.list:
        for mutation in MUTATIONS:
            print(f"{mutation.area:10} {mutation.key:34} {mutation.description}")
        return 0

    selected = [m for m in MUTATIONS if args.only in m.key]
    if not selected:
        print(f"no mutation matches {args.only!r}")
        return 2

    # Refuse to start if a target file is dirty: the script rewrites files in
    # place, and an interruption must not be able to lose unsaved work.
    targets = sorted({m.path for m in selected})
    clean, dirty = git_is_clean(targets)
    if not clean:
        print(
            "refusing to run: these files have uncommitted changes, and the mutation "
            "check rewrites them in place:\n  " + "\n  ".join(dirty)
        )
        return 2

    print(f"CodeTrace mutation check — {len(selected)} mutations over {len(targets)} files")
    print("each mutation must make the named tests fail; restoring after each run\n")

    escaped: List[Mutation] = []
    broken: List[Mutation] = []
    notes = []
    for index, mutation in enumerate(selected, start=1):
        path = os.path.join(ROOT, mutation.path)
        backup = path + ".mutation-backup"
        shutil.copy2(path, backup)
        try:
            apply_mutation(mutation)
            passed, output = run_tests(mutation.tests)
        finally:
            shutil.move(backup, path)
        # Confirm the restore is byte-for-byte, not "close enough".
        restored = subprocess.run(
            ["git", "diff", "--quiet", "--", mutation.path], cwd=ROOT, capture_output=True
        ).returncode == 0
        if not restored:
            broken.append(mutation)
            print(f"[{index:2}/{len(selected)}] {mutation.key:34} RESTORE FAILED — file differs from git")
            continue
        status = "escaped" if passed else "caught"
        if passed:
            escaped.append(mutation)
        notes.append(status)
        marker = "ok  " if not passed else "MISS"
        print(f"[{index:2}/{len(selected)}] {marker} {mutation.area:10} {mutation.key:34} {status}")
        if args.verbose or passed:
            for line in output.splitlines():
                print(f"          {line}")

    print()
    caught = len(notes) - len(escaped)
    print(f"{caught}/{len(notes)} mutations were caught by the suite")
    if escaped:
        print("mutations that escaped (the tests did not object):")
        for mutation in escaped:
            print(f"  {mutation.key:34} {mutation.description}")
        print("  tests run: " + ", ".join(sorted({t for m in escaped for t in m.tests})))
    if broken:
        print("restore failures (the working tree needs attention):")
        for mutation in broken:
            print(f"  {mutation.path}")
    if escaped or broken:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
