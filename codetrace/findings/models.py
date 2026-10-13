"""Finding model.

A finding is the *product* of the analysis: it must be traceable back to
concrete analysis results, must never overstate what was proven, and must carry
enough evidence for a reviewer to check the claim by hand.

Every finding therefore records

* a stable identity (see :func:`stable_finding_id`) that survives unrelevant
  edits such as insertions that shift line numbers,
* where the untrusted data enters (:attr:`source`) and where it is consumed
  (:attr:`sink`),
* the ordered :attr:`path` of program points that connect them,
* the conditions that must hold for the path to execute,
* the sanitizers that were seen and *why they did not stop the flow*,
* the analysis certainty (confirmed / approximate / unproven) and the concrete
  limitations that apply.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# Certainty levels.
CONFIRMED = "confirmed"
APPROXIMATE = "approximate"
UNPROVEN = "unproven"

# Confidence levels.
HIGH = "high"
MEDIUM = "medium"
LOW = "low"

CERTAINTY_RANK = {CONFIRMED: 0, APPROXIMATE: 1, UNPROVEN: 2}
CONFIDENCE_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2}

SEVERITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def stable_finding_id(
    rule_id: str,
    sink_function: str,
    sink_rule: str,
    argument_index: int,
    source_rules: Sequence[str],
    sink_text: str,
) -> str:
    """Deterministic finding identity that does not depend on line numbers.

    The identity is derived from the rule, the sink operation, the *text* of
    the sink statement and the contributing source rules.  Inserting code above
    the sink therefore keeps the identity stable (the finding is recognised as
    "the same finding, moved"), while changing the flow itself changes it.
    """
    payload = "|".join(
        [
            rule_id,
            sink_function,
            sink_rule,
            str(argument_index),
            ",".join(sorted(source_rules)),
            " ".join(sink_text.split()),
        ]
    )
    return "F" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12].upper()


@dataclass
class Finding:
    """One reported potential vulnerability flow."""

    id: str
    rule_id: str
    flow_id: str
    category: str
    severity: str
    confidence: str
    certainty: str
    sink: Dict[str, object]
    source: Dict[str, object]
    path: List[dict] = field(default_factory=list)
    sanitizers_seen: List[dict] = field(default_factory=list)
    branch_conditions: List[dict] = field(default_factory=list)
    #: Overall feasibility of the reported path: ``unconditional``, ``guarded``
    #: or ``conditionally-infeasible`` (see findings.explain._path_feasibility).
    feasibility: str = "unconditional"
    feasibility_note: str = ""
    interprocedural: bool = False
    explanation: str = ""
    limitations: List[str] = field(default_factory=list)
    remediation: str = ""
    evidence: Dict[str, object] = field(default_factory=dict)
    statement_ids: List[int] = field(default_factory=list)
    path_atoms: List[str] = field(default_factory=list)

    # -- ordering and display -------------------------------------------
    @property
    def sort_key(self) -> Tuple[int, int, int, int]:
        return (
            SEVERITY_RANK.get(self.severity, 9),
            CERTAINTY_RANK.get(self.certainty, 9),
            int(self.sink.get("line", 0) or 0),
            int(self.sink.get("col", 0) or 0),
        )

    @property
    def location(self) -> str:
        return f"{self.sink.get('line', 0)}:{self.sink.get('col', 0)}"

    def summary_line(self) -> str:
        return (
            f"{self.severity} {self.category} in {self.sink.get('function', '?')}() "
            f"at line {self.sink.get('line', 0)}: "
            f"{self.source.get('description', self.source.get('rule', 'source'))} -> "
            f"{self.sink.get('description', self.sink.get('rule', 'sink'))}"
        )

    def to_json(self, include_path: bool = True) -> dict:
        payload = {
            "id": self.id,
            "rule_id": self.rule_id,
            "flow_id": self.flow_id,
            "category": self.category,
            "severity": self.severity,
            "confidence": self.confidence,
            "certainty": self.certainty,
            "sink": self.sink,
            "source": self.source,
            "sanitizers_seen": self.sanitizers_seen,
            "branch_conditions": self.branch_conditions,
            "feasibility": self.feasibility,
            "feasibility_note": self.feasibility_note,
            "interprocedural": self.interprocedural,
            "explanation": self.explanation,
            "limitations": self.limitations,
            "remediation": self.remediation,
            "evidence": self.evidence,
            "statement_ids": self.statement_ids,
            "path_atoms": self.path_atoms,
            "path_length": len(self.path),
        }
        if include_path:
            payload["path"] = self.path
        return payload


def compare_findings(
    before: Sequence[Finding], after: Sequence[Finding]
) -> dict:
    """Compare two analysis runs using stable finding identity.

    Returns new / resolved / persistent / moved buckets.  A finding counts as
    *moved* when its identity (rule, sink text, source rules) is unchanged but
    its reported location changed.
    """
    before_by_id = {f.id: f for f in before}
    after_by_id = {f.id: f for f in after}
    new = [after_by_id[i] for i in sorted(after_by_id) if i not in before_by_id]
    resolved = [before_by_id[i] for i in sorted(before_by_id) if i not in after_by_id]
    persistent = []
    moved = []
    for identifier in sorted(set(before_by_id) & set(after_by_id)):
        old = before_by_id[identifier]
        new_finding = after_by_id[identifier]
        entry = {
            "id": identifier,
            "before": {"line": old.sink.get("line"), "col": old.sink.get("col"), "severity": old.severity},
            "after": {
                "line": new_finding.sink.get("line"),
                "col": new_finding.sink.get("col"),
                "severity": new_finding.severity,
            },
        }
        if old.location != new_finding.location:
            moved.append(entry)
        else:
            persistent.append(entry)
    return {
        "new": [f.to_json(include_path=False) for f in new],
        "resolved": [f.to_json(include_path=False) for f in resolved],
        "persistent": persistent,
        "moved": moved,
        # Id lists are what the interface filters on: a finding is "fixed" when
        # its id is in ``resolved_ids`` and "open" otherwise.
        "new_ids": sorted(f.id for f in new),
        "resolved_ids": sorted(f.id for f in resolved),
        "moved_ids": sorted(entry["id"] for entry in moved),
        "persistent_ids": sorted(entry["id"] for entry in persistent),
        "summary": {
            "before": len(before),
            "after": len(after),
            "new": len(new),
            "resolved": len(resolved),
            "persistent": len(persistent),
            "moved": len(moved),
        },
    }
