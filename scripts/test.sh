#!/usr/bin/env bash
# Run the permanent regression tests (standard library unittest, no deps).
#
#   scripts/test.sh                       # everything under tests/
#   scripts/test.sh -k parser             # unittest selection flags work too
#
# The evaluation corpus gate is a separate script: scripts/evaluate.sh.
# The frontend suite needs Node and lives in frontend-tests/ (see its README).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

exec python3 -m unittest discover -s tests -t . -v "$@"
