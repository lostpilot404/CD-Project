# CodeTrace — Demo Script (about 6 minutes)

Goal: show that the analysis finds a real flow, explains it, stays silent on a safe counterpart, and says so when the input is unsupported or broken.

## Setup (before the demo)

```
cd CD-Project
scripts/serve.sh --port 8000
```

Open the app at the preview URL for port 8000 (or `http://localhost:8000` locally). Check that the top bar shows `engine 1.0.0`, `rules builtin-…`, and `167 states / 0 conflicts`.

## 1. Overview (30 s) — screenshot 01

- "CodeTrace parses a C-like language with its own canonical LR(1) parser generator, then runs classical analyses on the tree."
- Point at the pipeline list (lexer → parser → semantics → CFG → data-flow → taint → dependency graph → slicing → findings and reports).
- Point at the top bar: the grammar has 102 productions and 0 conflicts.

## 2. Vulnerable program (2 min) — screenshots 02, 03

1. Go to **Analyze Code**. Load the bundled example `vulnerable/command_injection.ctc`.
2. Click **Run analysis**.
3. Say: "The source is `input()`, untrusted standard input. It flows through `build_command()`, is concatenated into a shell string, and reaches `system()`. The analysis reports one finding."
4. Open the finding. Show:
   - severity HIGH, certainty **approximate** (not "confirmed"), with the explanation shown on the finding;
   - the 8-step evidence path from source to sink;
   - the remediation hint.
5. Say: "A finding is a path through the program, not a proof that it can be exploited. The page states that on every view."

## 3. Graph and data-flow (1 min) — screenshots 04, 05

- **Program Graph**: show the typed dependency edges; each edge carries the analysis result that justifies it.
- **Data-Flow Analysis**: choose `build_command` and *Reaching definitions*. Show the equations, the worklist count (2 iterations, converged) and the per-statement IN/OUT sets.

## 4. Safe counterpart (45 s) — screenshot 08

- Load `safe/constant_command.ctc` and run the analysis.
- Show: **0 findings**, with the message "That means no configured source-to-sink flow was detected — not that the program is safe."
- Say: "We do not claim safety from silence. The Analyze Code page lists each sink that was inspected and not reported, with a reason."

## 5. Unsupported and broken input (1 min) — screenshots 09, 10

1. Load `syntax_errors/missing_semicolon.ctc`. Show the diagnostics:
   - `SYN001 4:3 unexpected identifier 'system'` with **the parser expected one of: …** (a real list, not "nothing");
   - the note that the analysis is partial.
2. Load `unsupported/switch_statement.ctc` (from the bundled examples). Show `LEX100`/`SYN100`: "switch is outside the supported subset. The enclosing statement was skipped and marked as not analysed; CodeTrace does not guess what it means."

## 6. Reports (30 s) — screenshot 07

- Open **Reports**. Click **Download JSON report** (schema 1.0, `schema_version` in the payload) and **Open HTML report** (self-contained, escapes all analysed source).
- Mention the run comparison: findings are matched by a stable identity, so inserting a line above a finding does not make it look new.

## 7. Verification (1 min) — optional, if time allows

```
python3 -m unittest discover -s tests -t . -v   # 304 tests
python3 scripts/evaluate.sh                      # TP 20, FP 0, FN 0; TN 9/9
python3 scripts/mutation_check.py                # 18/18 mutations caught
```

Point at `submission/VERIFICATION_REPORT.md` for the full logs.

## Questions to expect, with short answers

- **Is this sound?** No. It is a conservative static analysis over a small C-like language. Limits are listed in `docs/LIMITATIONS.md` and `VERIFICATION_REPORT.md` §6. Implicit flows, context-sensitive interprocedural analysis and interval reasoning are not implemented.
- **How do you know the parser is right?** The LR(1) tables are checked against textbook FIRST/FOLLOW sets, the Dragon-book state counts, and an independent LR(0)/canonical LR(1) builder in the tests.
- **Why "approximate" on a finding?** The analysis over-approximates loops and some branches. A finding that depends on such an approximation is labelled approximate, not confirmed.
- **Is the 82.75% figure the milestone?** The core milestone (75 points) is fully verified. The 82.75% total includes 7.75 points of extension work that is already implemented and tested; the instructor should decide how to report it.
