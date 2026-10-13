# Report schema

`GET /api/runs/{id}/report?format=json` returns the canonical dictionary built by
`codetrace/reporting/json_report.py`; `?format=html` renders the same dictionary
with `codetrace/reporting/html_report.py`. The two can never disagree, because
the HTML renderer takes its numbers and text from the JSON builder.

The report describes **one run**: the source it analysed (by content hash), the
rule set, the grammar and engine versions, the findings and their evidence, the
diagnostics, the measured metrics and the limitations that apply. Reports are
generated on demand and never stored on disk by the server.

## 1. Top level

| Key | Type | Meaning |
| --- | --- | --- |
| `schema_version` | string | `"1.0"`; changes only when the shape below changes incompatibly |
| `tool` | object | `name`, `version`, `description` |
| `run` | object | `run_id`, `timestamp` (UTC, `YYYY-MM-DDTHH:MM:SSZ`), `engine_version`, `rules_version`, `rule_set` (counts + fingerprint + label + origin), `parser_mode`, `grammar` (`productions`, `lalr_states`, `conflicts`) |
| `input` | object | `filename`, `lines`, `bytes`, `sha256` of the analysed text |
| `language` | object | the analysed language mode and dialect |
| `summary` | object | `findings`, `by_severity`, `by_category`, `by_certainty`, `errors`, `warnings`, `unsupported_constructs`, `analysis_complete`, `analysis_converged`, `partial_reasons`, `dispositions` |
| `findings` | array | the findings (§2) |
| `diagnostics` | array | every diagnostic: `code`, `severity`, `message`, `line`, `col`, `phase`, `detail` |
| `unsupported` | object | `offsets` and `features` (deduplicated descriptions) of constructs outside the subset |
| `unknown_values` | array | values the analysis could not determine (kept empty rather than guessed) |
| `analysis` | object | `order` (the pipeline stages that ran), `functions` (per-function CFG and fixpoint statistics), `taint` (engine version, iterations, convergence, per-function summaries, infeasible branches, notes), `dependency_graph` (node/edge counts and edge kinds) |
| `metrics` | object | measured counts and per-phase timings (§3) |
| `notes` | array | the run's own notes (engine version of each analysis stage, context-insensitivity, cleared guard atoms, iteration limits) |
| `limitations` | array | strings that apply to the whole run, including any validator-guard suppression that hid a sink call |
| `evaluation` | object | `{"available": false, "note": …}` unless a corpus label was supplied for this file, in which case the label is echoed here |

The `summary.dispositions` block is the honesty mechanism for unreported sinks:

```json
{"sink_calls_seen": 1, "reported": 1, "unreported_sink_calls": [],
 "unreported_count": 0, "statically_pruned_branches": [], "validator_guards": [],
 "note": "A sink call appears here when no enabled flow connects a configured source to it …"}
```

Every sink call the analysis encountered is either reported or listed in
`unreported_sink_calls` with its enclosing function, line and the reason. Three
reasons are distinguished, because they are not the same claim:

| Reason | What it means |
| --- | --- |
| no taint of the required context reached this sink argument | the configured sources do not flow here under the active rules |
| the statement sits in a branch whose condition is a literal constant | the branch cannot execute; the statement was not analysed as reachable |
| taint did reach this sink's data, but the flow was cleared on the guarded edge … by the rule-declared validator `X` | the flow exists and would be reported, but a declared validator on the guarding branch is assumed to reject it |

### 1.1 `summary.dispositions.validator_guards`

The third reason above is an **assumption, not an absence**, so it is reported
explicitly. Each entry names the guard: `function`, `symbol`, `symbol_id`,
`context`, `validator` (the rule id), `validator_function` (the called
function), `line`, `col`, `statement_text`, `condition`, `guard_edge`
(`true`/`false`), `from_block`, `to_block`, `removed_atoms` and the `assumption`
sentence. The same records appear in the run's `notes` (as cleared-atom counts)
and in `limitations` (as "N unreported sink call(s) were cleared by a
rule-declared validator guard"). The interface shows them on the Analyze Code
page under "What the engine saw but did not report".

## 2. Findings

| Key | Meaning |
| --- | --- |
| `id` | stable identity, `F` + 12 hex characters; independent of line numbers |
| `rule_id`, `flow_id` | the flow rule that produced the finding |
| `category`, `severity`, `confidence`, `certainty` | `high`/`medium`/`low` confidence and `confirmed`/`approximate`/`unproven` certainty |
| `source` | `rule`, `function`, `description`, `line`, `col`, `sid`, `contexts` |
| `sink` | `rule`, `function`, `category`, `severity`, `context`, `argument_index`, `description`, `sid`, `line`, `col`, `statement_text`, `enclosing_function`, `block`, `expression` |
| `path` | the ordered evidence path (below) |
| `path_atoms` | the taint atoms that travelled (for example `src:stdin@command`) |
| `path_length` | number of path steps |
| `statement_ids` | statements on the flow, in traversal order |
| `branch_conditions` | conditions the path passes through, with their guard status |
| `sanitizers_seen` | `rule`, `context`, `detail`, `line` — and why each one did *not* neutralise the flow |
| `feasibility`, `feasibility_note` | `unconditional`, `guarded` or `conditionally-infeasible`, with the reason |
| `interprocedural` | whether the flow crosses a function boundary |
| `explanation` | the "why matched" text: source, sink, atoms, steps, rule reasoning, certainty |
| `limitations` | the limitations that apply *to this finding* |
| `remediation` | what to change, and how to confirm the change |
| `evidence` | `engine_version`, `rules_version`, `taint_engine`, `reaching_definitions`, `analyses`, `atoms`, `flow_rule`, `sink_statement_span` |

Path steps:

```json
{"kind": "sanitizer", "sid": 1, "function": "main", "line": 1, "col": 41,
 "symbol": "sql_escape", "label": "sql_escape() applied (sanitizer for context 'sql')",
 "detail": "the rule 'sql_escape' removes taint atoms for context 'sql'; atoms of other contexts survive",
 "atoms": ["src:stdin@command"], "from_sid": 0, "context": "sql", "index": 2}
```

`kind` is one of `source`, `declaration`, `assignment`, `parameter`, `argument`,
`call`, `return`, `sanitizer`, `validator`, `unknown-call`, `pruned`,
`unresolved`, `sink`. An `unresolved` step means the tracer could not follow the
value any further — it is reported rather than papered over, and it lowers the
certainty to `unproven`.

## 3. Metrics

Counts measured during the run (never estimated):

```
grammar_states, grammar_productions, grammar_conflicts,
source_lines, source_bytes, tokens, ast_nodes, statements, functions, symbols,
scopes, calls, basic_blocks, cfg_edges, definitions, unreachable_blocks,
dependency_edges, dependency_nodes, taint_hits, findings, dataflow_iterations,
parser_mode, engine_version, rules_version, limits_hit, analysis_complete,
partial_reasons, timings
```

`timings` is wall clock in seconds for this process: `lex_seconds`,
`parse_seconds`, `grammar_tables_seconds` (nonzero only when the tables are built
during this run), `semantic_seconds`, `cfg_seconds`, `dataflow_seconds`,
`taint_seconds`, `dependencies_seconds`, `slicing_setup_seconds`,
`findings_seconds`. Because timings and the timestamp vary, two reports of the
same source are not byte-identical; everything else is, and
`tests/test_reporting.py` asserts exactly that by freezing those fields.

## 4. HTML report

The HTML report is a single self-contained file (`write_html_report` writes it
to disk for the CLI/evaluation path):

* **no `<script>` tags, no external references** — it works offline and cannot
  pull anything in when it is opened;
* the analysed source is escaped and every line is numbered; lines that take part
  in a finding are highlighted;
* sections: *Summary*, *Findings* (severity badge, rule, sink, source, certainty,
  path feasibility, why-matched explanation, evidence path, remediation,
  limitations, sanitizers seen), *Diagnostics*, *Analysed source*, *Measured
  metrics*, *Analysis limitations*, and a footer stating that the report is not a
  proof of exploitability;
* the filename, the run id and every finding field go through an escaper, so a
  filename such as `<test>` is rendered as `&lt;test&gt;`
  (`tests/test_reporting.py::HtmlReportTests`).

There is deliberately **no PDF export**: producing a PDF would require a
third-party dependency, and the project's rule is that a format is only offered
when it is reliable. Print-to-PDF from the browser works because the HTML report
is self-contained.

## 5. Stability guarantees

* `schema_version` is versioned with the engine (`codetrace/version.py`).
* Field names are additive: removing or renaming a field changes the schema
  version.
* Finding ids are stable for the same source and rule set; the comparison
  endpoint documents what counts as *new*, *resolved*, *moved* and *persistent*
  (`docs/COMPILER_THEORY.md` §19).
* The report of a run always names the rule set, grammar statistics and engine
  version it came from, so a report can be reproduced by analysing the same
  `sha256` with the same `rules_version`.
