#!/usr/bin/env bash
# Hardware-independent reproduction driver for the NDT WCET paper (tiers T0/T1).
#
#   T1  regenerate tables/*.tex from the frozen data/*.json and assert the
#       committed tables match (i.e. the paper's numbers still follow from the
#       committed measurements; gen_tables.py also re-verifies every claim and
#       the raspi4 serial-log SHA-256 internally).
#   T0  build main.pdf from the (regenerated) tables.
#
# This driver deliberately covers only the tiers that run on any machine with
# python3 + latexmk. Re-running the WCET campaign (T2), the stack replay (T3),
# or the Raspberry Pi 4 timing (T4) needs specific hardware -- see REPRODUCE.md.
#
# Usage:
#   scripts/reproduce.sh            # T1 (verify) then T0 (build main.pdf)
#   scripts/reproduce.sh --tables   # T1 only: regenerate + drift-check tables
#   scripts/reproduce.sh --pdf      # T0 only: build main.pdf from current tables
#   scripts/reproduce.sh --help
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAPER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

do_tables=1
do_pdf=1
case "${1:-}" in
  --tables) do_pdf=0 ;;
  --pdf)    do_tables=0 ;;
  --help|-h)
    # Print the leading comment block (stop at the first non-comment line).
    awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "${BASH_SOURCE[0]}"
    exit 0
    ;;
  "") ;;
  *)
    echo "reproduce.sh: unknown argument '$1' (try --help)" >&2
    exit 2
    ;;
esac

cd "${PAPER_DIR}"

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "reproduce.sh: required tool '$1' not found on PATH" >&2
    exit 1
  }
}

require python3
[ "${do_pdf}" -eq 1 ] && require latexmk

if [ "${do_tables}" -eq 1 ]; then
  echo "== T1: regenerating tables/*.tex from data/*.json =="
  python3 scripts/gen_tables.py
  python3 scripts/evt.py

  # Drift check: committed tables/figures must equal what data/ regenerates.
  # Any diff means the committed paper no longer matches its committed data.
  if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
    drift="$(git status --porcelain -- tables figures 2>/dev/null || true)"
    if [ -n "${drift}" ]; then
      echo "reproduce.sh: regenerated tables/figures differ from the committed copy:" >&2
      echo "${drift}" >&2
      echo "  inspect with: git -C '$(git rev-parse --show-toplevel)' diff -- $(pwd)/tables $(pwd)/figures" >&2
      exit 1
    fi
    echo "   tables/ and figures/ match the committed copy (no drift)."
  else
    echo "   (not a git checkout -- skipped the drift check)"
  fi
fi

if [ "${do_pdf}" -eq 1 ]; then
  echo "== T0: building main.pdf =="
  latexmk -pdf -interaction=nonstopmode -halt-on-error main >/dev/null
  echo "   built: ${PAPER_DIR}/main.pdf"
fi

echo "reproduce.sh: done."
