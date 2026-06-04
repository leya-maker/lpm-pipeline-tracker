#!/bin/bash
# pnl-rebuild wrapper — runs the daily P&L rebuild and emails Leya on failure.
#
# Path (c) update (2026-05-28): ledger_writer.py runs first to rebuild
# pnl-actuals.json from bank-truth + statement ledger data. Then rebuild_pnl.py
# runs with --skip-actuals so it uses that statement-driven file instead of
# fetching stale Xero data.
#
# Resilience (2026-06-04): every step runs under a hard wall-clock watchdog.
# The CFO inputs live on the Google Drive (CloudStorage) mount, which can wedge
# after the laptop sleeps or drops network: a blocking read then hangs forever
# and silently holds the launchd slot (one instance ran 26h once). The watchdog
# SIGKILLs any step that exceeds its limit so the job always exits, leaves the
# last-good pnl-actuals.json in place, and retries on the next schedule.
set -uo pipefail

NOTIFY="${HOME}/LPM-AI-coding-projects/agent-implementations/rose/lib/notify.py"
LEDGER="${HOME}/LPM-AI-coding-projects/agent-implementations/cfo/ledger_writer.py"
SCRIPT="${HOME}/LPM-AI-coding-projects/websites/pipeline-tracker/scripts/rebuild_pnl.py"
STDERR_LOG="${HOME}/LPM-AI-coding-projects/lpm-agents-core/pipeline-reports/logs/stderr.log"

LEDGER_TIMEOUT=240   # reads a few small Drive JSONs + writes one file; seconds normally
DASHBOARD_TIMEOUT=300 # staticrypt encrypt + git push over the network

# Run "$@" but SIGKILL it (and its children) if it runs longer than $1 seconds.
# Returns the command's exit code, or 124 on timeout. No dependency on the
# `timeout(1)` binary, which is not on launchd's PATH.
run_with_timeout() {
  local limit=$1; shift
  "$@" &
  local pid=$!
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "${waited}" -ge "${limit}" ]; then
      pkill -KILL -P "$pid" 2>/dev/null
      kill -KILL "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      return 124
    fi
    sleep 2
    waited=$((waited + 2))
  done
  wait "$pid"
}

# Single-instance lock: if a prior run is still alive (e.g. wedged before the
# watchdog existed), do not pile a second one on top of it.
LOCK="${TMPDIR:-/tmp}/com.lpm.pnl-rebuild.lock"
if ! mkdir "${LOCK}" 2>/dev/null; then
  echo "pnl-rebuild: another instance holds ${LOCK}; exiting" >&2
  exit 0
fi
trap 'rmdir "${LOCK}" 2>/dev/null' EXIT

# Step 1: rebuild pnl-actuals.json from statement ledger + bank-truth
run_with_timeout "${LEDGER_TIMEOUT}" /usr/bin/python3 "${LEDGER}" --rebuild-pnl
LEDGER_EXIT=$?
if [ "${LEDGER_EXIT}" -eq 124 ]; then
  /usr/bin/python3 "${NOTIFY}" "pnl-rebuild" "P&L ledger rebuild timed out" \
    "ledger_writer.py --rebuild-pnl exceeded ${LEDGER_TIMEOUT}s and was killed (likely a wedged Google Drive mount). Dashboard will use the existing pnl-actuals.json; the job will retry on the next run." \
    "${STDERR_LOG}"
elif [ "${LEDGER_EXIT}" -ne 0 ]; then
  /usr/bin/python3 "${NOTIFY}" "pnl-rebuild" "P&L ledger rebuild" \
    "ledger_writer.py --rebuild-pnl failed (exit ${LEDGER_EXIT}). Dashboard will use existing pnl-actuals.json." \
    "${STDERR_LOG}"
fi

# Step 2: encrypt and push the dashboard (skip Xero fetch; use what ledger_writer wrote)
run_with_timeout "${DASHBOARD_TIMEOUT}" /usr/bin/python3 "${SCRIPT}" --skip-actuals
EXIT=$?

if [ "${EXIT}" -eq 124 ]; then
  /usr/bin/python3 "${NOTIFY}" "pnl-rebuild" "P&L dashboard rebuild timed out" \
    "rebuild_pnl.py exceeded ${DASHBOARD_TIMEOUT}s and was killed. The live P&L figures may be stale until the job runs cleanly." \
    "${STDERR_LOG}"
elif [ "${EXIT}" -ne 0 ]; then
  /usr/bin/python3 "${NOTIFY}" "pnl-rebuild" "P&L dashboard rebuild" \
    "The daily P&L rebuild for the pipeline tracker failed (exit ${EXIT}). The live P&L figures on the tracker may be stale until it runs cleanly." \
    "${STDERR_LOG}"
fi

exit ${EXIT}
