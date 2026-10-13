# Evaluation

CodeTrace ships a **hand-labelled corpus** and a harness that runs the real
engine over it and measures the outcome. This document explains how the corpus
was built, what the harness measures, the measured numbers, and — just as
importantly — what those numbers do **not** say.

Reproduce everything below with:

```bash
python3 evaluation/run_evaluation.py            # table on stdout, exit 1 on any mismatch
scripts/evaluate.sh                             # same, JSON written to var/evaluation.json
```

## 1. How the corpus was built

* Every case is a small program in `examples/**/*.ctc` with a `// expect:` header
  that states, *before the analysis runs*, what the tool is expected to report.
* The label of each case — `vulnerable`, `safe`, `sanitized`, `unsupported`,
  `syntax_error`, `custom_rule` — together with the expected rules, categories,
  severities, sink statements and diagnostic codes lives in
  `evaluation/expectations.json`. The file also records a one-sentence rationale
  per case explaining *why* that label is correct, so a reviewer can disagree
  with the label rather than having to guess.
* Labels were written from the source by hand; the harness was then run against
  them, and cases where the engine disagreed were investigated one by one. Any
  change to the engine that alters an outcome makes the harness fail, which is
  the point: the corpus is a regression gate, not a fixture that follows the
  implementation.
* The corpus is **separate from the unit tests**: nothing under `tests/` reads
  `examples/`, and `tests/test_reporting.py::test_the_corpus_is_separate_from_the_unit_tests`
  asserts the separation.

### Corpus contents (corpus_version 1.0, 29 cases, 17 expected findings)

| Label | Cases | What it covers |
| --- | --- | --- |
| `vulnerable` | 14 | direct flows, multiple assignments, expressions, branch-taken flows, helpers, argument/return flows, multiple sources and sinks, loop-carried taint, array-element taint, unknown externals that keep taint, wrong-context sanitisers |
| `safe` | 4 | constant to sink, unrelated tainted variable, a source that never reaches the sink, a sink in a statically dead branch |
| `sanitized` | 4 | `shell_escape`, `sql_escape`, `to_int` (all contexts) and a validator guard |
| `unsupported` | 3 | `switch`, a preprocessor directive, pointer syntax — each must produce an explicit diagnostic |
| `syntax_error` | 3 | missing semicolon, unbalanced braces, broken expression — each must produce `SYN001` and a partial-analysis flag |
| `custom_rule` | 1 | a program analysed with a user rule file from `examples/custom_rules/strict_rules.ctrule` |

## 2. What the harness measures

**Finding level** — an expectation is satisfied when a reported finding agrees on
the rule id, the category and the normalised text of the sink statement (line
numbers are compared too, but they are not the identity):

```
TP = expectations satisfied by a distinct reported finding
FN = expectations with no matching finding
FP = reported findings matching no expectation
precision = TP / (TP + FP)      recall = TP / (TP + FN)      F1 = 2PR / (P + R)
```

**File level** — cases labelled `safe` or `sanitized` are expected to be silent,
so a finding in one of them is a file-level false positive, and a clean report in
one of them is a file-level true negative.

**Diagnostics level** — the expected diagnostic codes must appear (and, for the
syntax cases, a minimum number of `SYNxxx` diagnostics), and no *unexpected*
error-severity diagnostic may appear. This is how malformed and unsupported input
is verified: it must be reported, not ignored.

**Zero denominators** are handled explicitly rather than papered over:
`ratio()` returns `null` plus a note such as *"no findings were reported in this
corpus"* when the denominator is 0, and F1 is `null` when both precision and
recall are undefined or zero. A run with no findings and no expectations
therefore reports *undefined*, not 1.0.

## 3. Measured results

Date of the run recorded in the JSON (`evaluated_at`), engine 1.0.0, rules
`builtin-3387b7dcd97a95f3`:

```
cases                29        cases passed        29        cases failed  0
expected findings    17        reported findings   17
true positives       17        false positives      0        false negatives 0
file-level TN         8        file-level FP        0        (8 safe/sanitized cases)
diagnostic mismatches 0
precision 1.0                 recall 1.0                    F1 1.0
analysis time: 0.81 s for 29 files (median 7 ms, first case 0.60 s incl. table build)
environment: Python 3.11.2, Linux x86_64, 2 processors
```

The harness exits non-zero on any mismatch, so these numbers are reproducible
rather than remembered: `python3 evaluation/run_evaluation.py; echo $?` prints 0
today and would print 1 after any regression.

## 4. What these numbers mean — and what they do not

They mean: **on this corpus, with this rule set, every expected flow is reported
exactly once, no extra finding is reported, and every malformed or unsupported
case produces the diagnostic it is supposed to produce.** The `safe` and
`sanitized` cases are a deliberate guard against a tool that reports everything:
constants, unrelated variables, unreachable sinks and correctly-sanitised flows
must stay silent, and they do.

They do **not** mean:

* that CodeTrace detects 100 % of command injection in real C programs — the
  corpus is 29 hand-written files written for this project;
* that precision or recall would stay at 1.0 on arbitrary code: the corpus has
  no large functions, no macros, no aliasing and no library-heavy code, all of
  which the analysis handles approximately or not at all
  (`docs/LIMITATIONS.md`);
* that a clean report on an arbitrary file means "safe". The tool never makes
  that claim, and the report says so in its own words.

The JSON written by `scripts/evaluate.sh` records this interpretation alongside
the numbers, so the numbers cannot be quoted without it.

## 5. Extending the corpus

To add a case:

1. write the program under `examples/<category>/<name>.ctc` with a `// expect:`
   header describing the expected outcome;
2. add an entry to `evaluation/expectations.json` with `file`, `label`,
   `rationale`, `expect` (rule, category, severity, `sink_statement`,
   `source_rule`), `expect_diagnostics` (codes) and, when needed,
   `min_syntax_errors` or `rules`;
3. run `python3 evaluation/run_evaluation.py` — a mismatch is reported with the
   case, the missing expectation and the unexpected finding, and the harness
   exits 1.

A case that the engine gets *wrong* is valuable: it belongs in the corpus as an
`unsupported`, `safe` or `vulnerable` label with a rationale, and it stays red
until the engine is fixed — which is why the corpus is committed together with
its expectations rather than regenerated from the engine's output.
