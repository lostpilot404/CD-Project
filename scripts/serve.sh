#!/usr/bin/env bash
# Start the CodeTrace server with the bundled frontend.
#
#   scripts/serve.sh                 # http://0.0.0.0:8000
#   scripts/serve.sh --port 9000     # any flag accepted by python3 -m codetrace.api
#
# The engine has no third-party dependencies: Python 3.11+ and the standard
# library are enough.  The browser frontend is plain ES modules served by the
# same process, so no build step and no npm install are required to use the app.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if [[ $# -eq 0 ]]; then
  exec python3 -m codetrace.api --host 0.0.0.0 --port 8000
fi
exec python3 -m codetrace.api "$@"
