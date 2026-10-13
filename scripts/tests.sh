#!/usr/bin/env bash
# Run every test suite in the repository.
#
#   scripts/tests.sh              # Python engine + API + browser suites
#   scripts/tests.sh engine       # Python suites only (no Node needed)
#
# The engine suite is pure unittest and needs no dependencies.  The frontend
# suite uses the Node test runner that ships with Node 18+; if Node is missing
# the script says so and still fails, because a suite that cannot run is not a
# suite that passed.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

mode="${1:-all}"
log="$(mktemp)"

echo "== engine: unit, API, reporting and workflow suites =="
if ! python3 -m unittest discover -s tests -t . >"$log" 2>&1; then
  tail -n 40 "$log"
  rm -f "$log"
  exit 1
fi
grep -E "^(Ran|OK)" "$log"
rm -f "$log"

if [[ "$mode" == "engine" ]]; then
  exit 0
fi

echo
echo "== frontend: browser-side modules and views =="
if ! command -v npm >/dev/null 2>&1; then
  echo "npm is not installed; the frontend suite cannot run here." >&2
  exit 1
fi
(cd frontend && npm test)

echo
echo "all suites passed"
