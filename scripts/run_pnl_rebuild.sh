#!/bin/bash
# pnl-rebuild wrapper — runs the daily P&L rebuild and emails Leya on failure.
#
# Added 2026-05-22 (scheduled-job reliability rollout). The launchd plist points
# here instead of straight at rebuild_pnl.py so a failure is not silent. The
# Python script's stdout/stderr flow through to the plist's StandardOut/Error
# paths unchanged; this wrapper only adds the failure notification.
set -uo pipefail

NOTIFY="${HOME}/Library/Application Support/LPM-Rose/lib/notify.py"
SCRIPT="${HOME}/LPM-AI-coding-projects/websites/pipeline-tracker/scripts/rebuild_pnl.py"
STDERR_LOG="${HOME}/LPM-AI-coding-projects/lpm-agents-core/pipeline-reports/logs/stderr.log"

/usr/bin/python3 "${SCRIPT}"
EXIT=$?

if [ "${EXIT}" -ne 0 ]; then
  /usr/bin/python3 "${NOTIFY}" "pnl-rebuild" "P&L dashboard rebuild" \
    "The daily P&L rebuild for the pipeline tracker failed (exit ${EXIT}). The live P&L figures on the tracker may be stale until it runs cleanly." \
    "${STDERR_LOG}"
fi

exit ${EXIT}
