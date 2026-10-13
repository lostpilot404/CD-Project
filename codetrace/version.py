"""Single source of truth for the CodeTrace version identifiers.

The version is part of a finding's identity: results are only comparable when
the engine version and the rule-set version match.  Keeping the string here
avoids importing the analysis package (and therefore creating an import cycle)
just to read it.
"""

from __future__ import annotations

#: Engine version.  Bump when analysis behaviour changes in a way that can
#: change findings; the value is recorded in every report.
ENGINE_VERSION = "1.0.0"

#: Report schema version (see :mod:`codetrace.reporting.json_report`).
SCHEMA_VERSION = "1.0"

#: HTTP API version (see :mod:`codetrace.api.schemas`).
API_VERSION = "1.0"

#: Language mode string shown to users and written into reports.
LANGUAGE_MODE = "CT-C subset v1"
