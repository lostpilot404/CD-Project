"""Request/response schemas of the CodeTrace HTTP API.

The schemas are documented here as data so that the API documentation endpoint
and the tests both read the *same* description: a schema cannot drift away from
the implementation without the tests noticing.
"""

from __future__ import annotations

from typing import Dict, List

from ..version import API_VERSION  # noqa: F401  (re-exported)

SCHEMAS: Dict[str, dict] = {
    "HealthResponse": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["ok"]},
            "engine_version": {"type": "string"},
            "api_version": {"type": "string"},
            "rules_version": {"type": "string"},
            "grammar": {"type": "object", "description": "productions, states, conflicts"},
            "uptime_seconds": {"type": "number"},
        },
        "required": ["status", "engine_version", "api_version"],
    },
    "AnalysisRequest": {
        "type": "object",
        "properties": {
            "source": {"type": "string", "maxLength": 524288, "description": "CT-C source text"},
            "filename": {"type": "string", "default": "<source>"},
            "rules": {
                "type": "string",
                "description": "optional rule file text; validated before use",
            },
            "use_builtin_rules": {"type": "boolean", "default": True},
            "run_dependencies": {
                "type": "boolean",
                "default": True,
                "description": "build the program dependency graph and slices; "
                               "when false, /graph and /slice answer 409",
            },
            "parser_mode": {"type": "string", "enum": ["lalr", "slr", "canonical"], "default": "lalr"},
        },
        "required": ["source"],
    },
    "AnalysisResponse": {
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "status": {"type": "string", "enum": ["completed", "rejected"]},
            "summary": {"type": "object"},
            "diagnostics": {"type": "array"},
            "metrics": {"type": "object"},
            "findings": {"type": "array"},
            "grammar": {"type": "object"},
            "rules": {"type": "object"},
            "limits_hit": {"type": "array"},
        },
    },
    "RuleValidationRequest": {
        "type": "object",
        "properties": {"rules": {"type": "string"}},
        "required": ["rules"],
    },
    "RuleValidationResponse": {
        "type": "object",
        "properties": {
            "valid": {"type": "boolean"},
            "diagnostics": {"type": "array"},
            "stats": {"type": "object"},
            "rules": {"type": "array"},
            "grammar": {"type": "object"},
        },
    },
    "ComparisonRequest": {
        "type": "object",
        "properties": {"before": {"type": "string"}, "after": {"type": "string"}},
        "required": ["before", "after"],
    },
    "ErrorResponse": {
        "type": "object",
        "properties": {
            "error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["code", "message"],
            }
        },
    },
}

ENDPOINTS: List[dict] = [
    {"method": "GET", "path": "/api/health", "response": "HealthResponse",
     "description": "liveness probe plus grammar and rule-set identity"},
    {"method": "GET", "path": "/api/language", "response": "object",
     "description": "supported subset, unsupported keywords, diagnostics catalogue"},
    {"method": "GET", "path": "/api/grammar", "response": "object",
     "description": "grammar productions, NULLABLE/FIRST/FOLLOW sets and LR automaton statistics"},
    {"method": "GET", "path": "/api/rules", "response": "object",
     "description": "the active rule set (built-in plus any session rules)"},
    {"method": "POST", "path": "/api/rules/validate", "request": "RuleValidationRequest",
     "response": "RuleValidationResponse", "description": "parse and validate a rule file"},
    {"method": "GET", "path": "/api/examples", "response": "array",
     "description": "bundled example programs with their expected behaviour"},
    {"method": "GET", "path": "/api/examples/{id}", "response": "object",
     "description": "contents of one bundled example"},
    {"method": "POST", "path": "/api/analyze", "request": "AnalysisRequest",
     "response": "AnalysisResponse", "description": "run the full analysis pipeline"},
    {"method": "GET", "path": "/api/runs/{run_id}", "response": "object",
     "description": "summary, diagnostics and metrics of a stored run"},
    {"method": "GET", "path": "/api/runs/{run_id}/findings", "response": "array",
     "description": "findings with evidence paths, optionally filtered"},
    {"method": "GET", "path": "/api/runs/{run_id}/findings/{finding_id}", "response": "object",
     "description": "one finding, including its dependency evidence"},
    {"method": "GET", "path": "/api/runs/{run_id}/ast", "response": "object",
     "description": "the AST with source spans and resolved symbol ids"},
    {"method": "GET", "path": "/api/runs/{run_id}/cfg", "response": "object",
     "description": "basic blocks, typed edges and definitions (one or all functions)"},
    {"method": "GET", "path": "/api/runs/{run_id}/dataflow", "response": "object",
     "description": "GEN/KILL/USE/DEF, IN/OUT per block and per statement for one analysis"},
    {"method": "GET", "path": "/api/runs/{run_id}/statements/{sid}", "response": "object",
     "description": "everything known about one statement: block, definitions, liveness, taint"},
    {"method": "GET", "path": "/api/runs/{run_id}/graph", "response": "object",
     "description": "program dependency graph, filtered by edge kind"},
    {"method": "GET", "path": "/api/runs/{run_id}/slice", "response": "object",
     "description": "backward or forward slice for a statement"},
    {"method": "GET", "path": "/api/runs/{run_id}/findings/{finding_id}/slice", "response": "object",
     "description": "security slice restricted to a finding"},
    {"method": "GET", "path": "/api/runs/{run_id}/report?format=json|html", "response": "object",
     "description": "the exported report of the run (generated on demand, never stored)"},
    {"method": "POST", "path": "/api/compare", "request": "ComparisonRequest",
     "response": "object", "description": "compare two stored runs by stable finding identity"},
    {"method": "GET", "path": "/api/schemas", "response": "object",
     "description": "these schemas and the endpoint catalogue"},
]
