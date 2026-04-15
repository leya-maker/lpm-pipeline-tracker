#!/usr/bin/env python3
"""Sync LPM Consulting YTD revenue from Xero into the pipeline tracker.

Flow:
    1. Shell out to bookkeeper-ai's `revenue-ytd --org lpm --json` command
    2. Parse the JSON result (amount + timestamp + basis)
    3. Read lpm-pipeline-tracker/data.json
    4. Upsert `ytdRevenue` field
    5. Commit and push so GitHub Pages picks it up
    6. Print a one-line summary for logs

Invoked weekly by launchd (~/Library/LaunchAgents/com.lpm.ytd-revenue-sync.plist).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path("/Users/leyapetrovanimiller/dev/lpm-pipeline-tracker")
DATA_FILE = REPO / "data.json"
BOOKKEEPER = Path("/Users/leyapetrovanimiller/dev/bookkeeper-ai")
PYTHON = BOOKKEEPER / ".venv" / "bin" / "python"


def fetch_ytd_from_xero() -> dict:
    result = subprocess.run(
        [str(PYTHON), "-m", "src.main", "revenue-ytd", "--org", "lpm", "--json"],
        cwd=str(BOOKKEEPER),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def update_data_json(payload: dict) -> tuple[float | None, float | None]:
    """Write ytdRevenue into data.json. Returns (previous_amount, new_amount)."""
    data = json.loads(DATA_FILE.read_text())

    previous = None
    if isinstance(data.get("ytdRevenue"), dict):
        previous = data["ytdRevenue"].get("amount")

    data["ytdRevenue"] = {
        "amount": payload["amount"],
        "year": payload["year"],
        "asOf": payload["asOf"],
        "fromDate": payload["fromDate"],
        "toDate": payload["toDate"],
        "basis": payload["basis"],
        "source": payload["source"],
        "org": payload["org"],
    }
    data["lastUpdated"] = datetime.now().date().isoformat()

    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return previous, payload["amount"]


def git_commit_and_push(previous: float | None, new: float | None) -> None:
    if previous == new:
        print("[{}] No change ($ {:,.2f}) — skipping commit.".format(
            datetime.now().isoformat(timespec="seconds"),
            new or 0,
        ))
        return

    delta_note = ""
    if previous is not None and new is not None:
        delta = new - previous
        delta_note = " (was ${:,.2f}, +${:,.2f})".format(previous, delta)

    message = "Sync YTD revenue: ${:,.2f}{}".format(new or 0, delta_note)

    subprocess.run(["git", "add", "data.json"], cwd=str(REPO), check=True)
    subprocess.run(
        ["git", "commit", "-m", message + "\n\nCo-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"],
        cwd=str(REPO),
        check=True,
    )
    subprocess.run(["git", "push"], cwd=str(REPO), check=True)
    print("[{}] {}".format(datetime.now().isoformat(timespec="seconds"), message))


def main() -> int:
    try:
        payload = fetch_ytd_from_xero()
    except subprocess.CalledProcessError as e:
        print("ERROR: bookkeeper-ai revenue-ytd failed.", file=sys.stderr)
        print("stdout:", e.stdout, file=sys.stderr)
        print("stderr:", e.stderr, file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print("ERROR: could not parse bookkeeper-ai output: {}".format(e), file=sys.stderr)
        return 1

    if payload.get("amount") is None:
        print("ERROR: Xero returned no income total. Raw payload: {}".format(payload), file=sys.stderr)
        return 1

    previous, new = update_data_json(payload)
    git_commit_and_push(previous, new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
