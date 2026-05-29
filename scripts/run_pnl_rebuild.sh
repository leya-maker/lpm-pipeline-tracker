#!/bin/bash
# pnl-rebuild wrapper — runs the daily P&L rebuild and emails Leya on failure.
#
# Path (c) update (2026-05-28): ledger_writer.py runs first to rebuild
# pnl-actuals.json from bank-truth + statement ledger data. Then rebuild_pnl.py
# runs with --skip-actuals so it uses that statement-driven file instead of
# fetching stale Xero data.
set -uo pipefail

NOTIFY="${HOME}/LPM-AI-coding-projects/agent-implementations/rose/lib/notify.py"
LEDGER="${HOME}/LPM-AI-coding-projects/agent-implementations/cfo/ledger_writer.py"
SCRIPT="${HOME}/LPM-AI-coding-projects/websites/pipeline-tracker/scripts/rebuild_pnl.py"
STDERR_LOG="${HOME}/LPM-AI-coding-projects/lpm-agents-core/pipeline-reports/logs/stderr.log"

# Step 1: rebuild pnl-actuals.json from statement ledger + bank-truth
/usr/bin/python3 "${LEDGER}" --rebuild-pnl
LEDGER_EXIT=$?
if [ "${LEDGER_EXIT}" -ne 0 ]; then
  /usr/bin/python3 "${NOTIFY}" "pnl-rebuild" "P&L ledger rebuild" \
    "ledger_writer.py --rebuild-pnl failed (exit ${LEDGER_EXIT}). Dashboard will use existing pnl-actuals.json." \
    "${STDERR_LOG}"
fi

# Step 2: encrypt and push the dashboard (skip Xero fetch; use what ledger_writer wrote)
/usr/bin/python3 "${SCRIPT}" --skip-actuals
EXIT=$?

if [ "${EXIT}" -ne 0 ]; then
  /usr/bin/python3 "${NOTIFY}" "pnl-rebuild" "P&L dashboard rebuild" \
    "The daily P&L rebuild for the pipeline tracker failed (exit ${EXIT}). The live P&L figures on the tracker may be stale until it runs cleanly." \
    "${STDERR_LOG}"
fi

exit ${EXIT}
