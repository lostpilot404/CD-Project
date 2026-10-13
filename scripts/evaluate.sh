#!/usr/bin/env bash
# Run the labelled corpus evaluation and keep the JSON evidence.
#
#   scripts/evaluate.sh                    # table on stdout, JSON in var/
#   scripts/evaluate.sh /tmp/mine.json      # choose where the JSON goes
#
# The script exits non-zero if any case mismatches its hand-written label, so it
# can be used as a regression gate.  The numbers describe this corpus only; see
# docs/EVALUATION.md for what they do and do not mean.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

out="${1:-$root/var/evaluation.json}"
mkdir -p "$(dirname "$out")"

python3 evaluation/run_evaluation.py --json "$out"
echo "wrote $out"
