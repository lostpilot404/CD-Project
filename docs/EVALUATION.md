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
  change to the engine that alters an outcome is visible in the comparison, which
  is the point: the corpus is a reference measurement, not a fixture that follows
  the implementation.
* The corpus is **independent of the engine internals**: the labels describe what a
  reader of the C source expects, not what the current code happens to print.

### Corpus contents (corpus_version 1.0, 33 cases, 20 expected findings)

| Label | Cases | What it covers |
| --- | --- | --- |
| `vulnerable` | 17 | direct flows, multiple assignments, expressions, branch-taken flows, helpers, argument/return flows, multiple sources and sinks, loop-carried taint, array-element taint, unknown externals that keep taint, wrong-context sanitisers, sink-looking text in comments and strings, a negated validator guard, a shadowed variable |
| `safe` | 5 | constant to sink, unrelated tainted variable, a source that never reaches the sink, a sink in a statically dead branch, taint killed by a later constant |
| `sanitized` | 4 | `shell_escape`, `sql_escape`, `to_int` (all contexts) and a validator guard (see §2.1) |
| `unsupported` | 3 | `switch`, a preprocessor directive, pointer syntax — each must produce an explicit diagnostic |
| `syntax_error` | 3 | missing semicolon, unbalanced braces, broken expression — each must produce `SYN001` and a partial-analysis flag |
| `custom_rule` | 1 | a program analysed with a user rule file from `examples/custom_rules/strict_rules.ctrule` |

## 2. Per-case accounting (why 33 files are not 33 precision measurements)

The corpus mixes three kinds of case, and they enter the metrics differently. The
three groups are disjoint and together account for every file in the corpus:

| Group | Files | Enters which metric | Second requirement |
| --- | --- | --- | --- |
| finding-level | 18 | TP/FN for each declared expectation (`20` in total) | no extra finding |
| file-level | 9 | file-level TN/FP for `safe` and `sanitized` | no finding at all |
| diagnostic-only | 6 | no precision/recall denominator | the declared diagnostic codes must appear, and no finding may appear |

**18 + 9 + 6 = 33.** Only the first two groups carry a
precision/recall/specificity denominator; the 6 `unsupported` and `syntax_error`
cases are deliberately outside it, because a program that is rejected before
analysis is not a detection opportunity and counting it as a true negative would
inflate specificity. A finding reported in one of those 6 files is still counted
as a false positive and still fails the case — the harness computes
`false_positives = reported findings − findings matched by a declared
expectation` for **every** case, not only for cases that declare expectations.

| Case | Label | Declared expectations | Counted as | Also required |
| --- | --- | --- | --- | --- |
| `vulnerable/command_injection.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `vulnerable/sql_injection.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `vulnerable/path_traversal.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `vulnerable/format_string.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `vulnerable/two_step_command.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `safe/constant_command.ctc` | safe | 0 | file-level TN/FP + FP | must report no finding |
| `safe/unrelated_variable.ctc` | safe | 0 | file-level TN/FP + FP | must report no finding |
| `safe/source_never_reaches_sink.ctc` | safe | 0 | file-level TN/FP + FP | must report no finding |
| `safe/dead_branch_sink.ctc` | safe | 0 | file-level TN/FP + FP | must report no finding |
| `sanitized/shell_escape.ctc` | sanitized | 0 | file-level TN/FP + FP | must report no finding |
| `sanitized/sql_escape.ctc` | sanitized | 0 | file-level TN/FP + FP | must report no finding |
| `sanitized/parse_to_int.ctc` | sanitized | 0 | file-level TN/FP + FP | must report no finding |
| `sanitized/validated_command.ctc` | sanitized | 0 | file-level TN/FP + FP | must report no finding |
| `interprocedural/return_value.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `interprocedural/argument_flow.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `interprocedural/recursion.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `challenges/wrong_context_sanitizer.ctc` | vulnerable | 2 | TP/FN (2 expectations) + FP | — |
| `challenges/unknown_external_keeps_taint.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `challenges/array_element_taint.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `challenges/guarded_and_checked.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `challenges/multiple_sources_two_sinks.ctc` | vulnerable | 2 | TP/FN (2 expectations) + FP | — |
| `challenges/loop_carried.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `unsupported/switch_statement.ctc` | unsupported | 0 | diagnostics only (excluded from P/R) + FP | no finding may appear |
| `unsupported/preprocessor_directive.ctc` | unsupported | 0 | diagnostics only (excluded from P/R) + FP | no finding may appear |
| `unsupported/pointer_type.ctc` | unsupported | 0 | diagnostics only (excluded from P/R) + FP | no finding may appear |
| `syntax_errors/missing_semicolon.ctc` | syntax_error | 0 | diagnostics only (excluded from P/R) + FP | no finding may appear |
| `syntax_errors/unbalanced_braces.ctc` | syntax_error | 0 | diagnostics only (excluded from P/R) + FP | no finding may appear |
| `syntax_errors/broken_expression.ctc` | syntax_error | 0 | diagnostics only (excluded from P/R) + FP | no finding may appear |
| `custom_rules/custom_rule_demo.ctc` | custom_rule | 1 | TP/FN (1 expectation) + FP | — |
| `challenges/decoy_in_comment_and_string.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `challenges/negated_validator_guard.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `challenges/shadowed_variable.ctc` | vulnerable | 1 | TP/FN (1 expectation) + FP | — |
| `safe/killed_by_constant.ctc` | safe | 0 | file-level TN/FP + FP | must report no finding |

### 2.1 `sanitized/validated_command.ctc` is not a silent true negative

This case is labelled `sanitized` because a declared validator guards the sink:

```c
int main() {
  string name = input();
  if (is_safe_command(name)) { system(name); }   // validate_command context "command"
  return 0;
}
```

Taint **does** reach `system(name)`; what stops the report is the guard. The
engine therefore records a suppression — the symbol, context, validator rule,
source position, guarded edge and the atoms removed (`guard_suppressions` /
`summary.dispositions.validator_guards`) — and the run's own `limitations` and
`notes` say that the validator's body was not analysed and is *assumed* to reject
unsafe values. The case counts as a file-level true negative only because that
assumption holds, which is stated in the report rather than left implicit. The
companion cases — a negated guard, a guard on another symbol and a guard on a
compound argument — behave the same way and are part of the corpus.

### 2.2 The adversarial cases added in corpus version 1.0

Four files exist to attack the analysis rather than to confirm it, and each one
targets a different way a scanner-style tool goes wrong:

| Case | What it attacks | Engine result |
| --- | --- | --- |
| `challenges/decoy_in_comment_and_string.ctc` | text that *looks* like a sink call, inside a comment and inside a string literal | 1 finding, at the real `system(command);` only — the analysis parses and resolves calls, it does not search text |
| `challenges/negated_validator_guard.ctc` | treating a declared validator as blanket silence | 1 finding: the guard covers the *false* edge of `if (!is_safe_command(name))`, and the sink runs on the true edge, i.e. exactly where the value was not validated |
| `challenges/shadowed_variable.ctc` | conflating two variables that share a name | 1 finding, at the outer symbol only; the inner `name` is a constant, and the shadowing itself is reported as `SEM018` |
| `safe/killed_by_constant.ctc` | reporting a flow whose value was overwritten | 0 findings: the reaching definition of the sink argument is the constant, not the source |

The first three are labelled `vulnerable` (they must produce a finding, and the
one they must *not* produce is the interesting half); the fourth is labelled
`safe` and is part of the file-level true-negative count.

## 3. What the harness measures

**Finding level** — an expectation is satisfied when a reported finding agrees on
the rule id, the category, the severity, the source rule, the certainty (where the
expectation declares one) and the normalised text of the sink statement. Line
numbers are recorded in the expectation for readability and are **not** part of
the match, so moving a sink down a line does not fail a case:

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

## 4. Measured results

Date of the run recorded in the JSON (`evaluated_at`), engine 1.0.0, rules
`builtin-3387b7dcd97a95f3`:

```
cases                33        cases passed        33        cases failed  0
expected findings    20        reported findings   20
true positives       20        false positives      0        false negatives 0
file-level TN         9        file-level FP        0        (9 safe/sanitized cases)
diagnostic mismatches 0
precision 1.0                 recall 1.0                    F1 1.0
analysis time: 1.14 s for 33 files (median 10 ms, first case 0.79 s incl. table build)
environment: Python 3.11.2, Linux x86_64, 2 processors
```

The harness exits non-zero on any mismatch, so these numbers are reproducible
rather than remembered: `python3 evaluation/run_evaluation.py; echo $?` prints 0
today and would print 1 after any regression.

Wall-clock figures vary with the machine and with what else is running: the same
corpus has measured between 0.8 s and 1.3 s here across runs, which is why the
per-case times and the environment are written into
`var/evaluation.json` (`evaluated_at`, `analysis_seconds`, `environment`) instead
of being quoted as a fixed result. Every other number above is deterministic for
a given corpus and engine version.

## 5. What these numbers mean — and what they do not

They mean: **on this corpus, with this rule set, every one of the 20 declared
expectations (in 18 files) is reported exactly once, none of the 9 `safe` /
`sanitized` files produces a finding, no file in the corpus produces an undeclared
finding, and every malformed or unsupported file produces the diagnostic it is
supposed to produce.** The `safe` and
`sanitized` cases are a deliberate guard against a tool that reports everything:
constants, unrelated variables, unreachable sinks and correctly-sanitised flows
must stay silent, and they do.

They do **not** mean:

* that precision, recall or F1 generalise, or that "100 %" describes anything
  other than this corpus. The recall denominator is 20 expectations, all of them
  written for this project; the precision denominator is those 20 findings plus
  whatever the engine reports on the other 13 files, and the specificity
  denominator is 9 files. The 6 `unsupported` / `syntax_error` files are outside
  all three by construction (§2);
* that CodeTrace detects 100 % of command injection in real C programs — the
  corpus is 33 hand-written files written for this project;
* that precision or recall would stay at 1.0 on arbitrary code: the corpus has
  no large functions, no macros, no aliasing and no library-heavy code, all of
  which the analysis handles approximately or not at all
  (`docs/LIMITATIONS.md`);
* that a clean report on an arbitrary file means "safe". The tool never makes
  that claim, and the report says so in its own words.

The JSON written by `scripts/evaluate.sh` records this interpretation alongside
the numbers, so the numbers cannot be quoted without it.

## 6. Extending the corpus

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
