#!/usr/bin/env python3
"""Rebuild the encrypted Pipeline tracker page.

The Pipeline page holds client names, contacts, and contract values, so the raw
data.json must never be served publicly. This mirrors rebuild_pnl.py: it bakes
the local data.json into templates/index.template.html as
window.BAKED_PIPELINE_DATA, StaticCrypt-encrypts the whole page with the same
password as the P&L dashboard, and pushes the encrypted index.html. data.json
itself is gitignored and never committed or served.

Every writer of data.json (the /pipeline-tracker skill, sync_ytd_revenue.py,
and the daily reconcile wrapper) deploys through this script instead of
committing data.json. The script is idempotent: if the encrypted page is
unchanged it skips the commit, so it is safe to run on every refresh.

Steps:
  1. Read the local data.json (the single source of truth, gitignored).
  2. Inline it into templates/index.template.html at {{EMBEDDED_PIPELINE}}.
  3. Run staticrypt to produce the encrypted index.html.
  4. If index.html changed, git add + commit + (rebase) + push.

CLI:
    python rebuild_pipeline.py [--dry-run] [--message "commit message"]
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "templates" / "index.template.html"
DATA = REPO / "data.json"
OUTPUT = REPO / "index.html"
PLAIN_TMP = REPO / ".pipeline.plain.tmp.html"

# Reuse the P&L dashboard password so all gated business trackers share one
# passphrase; fall back to the same default rebuild_pnl.py uses.
PASSWORD = os.environ.get("PNL_DASHBOARD_PASSWORD", "lpm2026")


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Command failed: {' '.join(cmd)}", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)
    return result


def inline_payload(raw: dict) -> str:
    template = TEMPLATE.read_text()
    # Compact JSON; guard against a literal </script> ever appearing in the data
    # so the inline script stays un-terminatable.
    blob = json.dumps(raw, separators=(",", ":")).replace("</", "<\\/")
    script = f"<script>window.BAKED_PIPELINE_DATA = {blob};</script>"
    return template.replace("{{EMBEDDED_PIPELINE}}", script)


def encrypt_with_staticrypt(raw: dict) -> None:
    PLAIN_TMP.write_text(inline_payload(raw))
    tmp_dir = REPO / ".staticrypt_out"
    tmp_dir.mkdir(exist_ok=True)
    run([
        "npx", "staticrypt", str(PLAIN_TMP),
        "-p", PASSWORD,
        "--short",
        "-d", str(tmp_dir),
        "--template-title", "LPM Pipeline Tracker",
        "--template-color-primary", "#384BCF",
        "--template-color-secondary", "#FFFFF6",
    ], cwd=REPO)
    encrypted = tmp_dir / PLAIN_TMP.name
    shutil.move(str(encrypted), str(OUTPUT))
    shutil.rmtree(tmp_dir)
    PLAIN_TMP.unlink(missing_ok=True)


def git_commit_and_push(message: str | None) -> None:
    status = run(["git", "status", "--porcelain", "index.html",
                  "templates/index.template.html", ".staticrypt.json"],
                 cwd=REPO, check=False)
    if not status.stdout.strip():
        print("No changes to the Pipeline page — skipping commit.")
        return
    run(["git", "add", "index.html", "templates/index.template.html", ".staticrypt.json"], cwd=REPO)
    msg = message or f"Refresh Pipeline tracker ({date.today().isoformat()})"
    run(["git", "commit", "-m", msg], cwd=REPO)
    # The pipeline-tracker repo has several writers (this script via the skill,
    # ytd-revenue-sync, pnl-rebuild), so a push can be rejected if another writer
    # pushed first. Rebase the fresh commit onto the remote before pushing.
    run(["git", "pull", "--rebase", "--autostash"], cwd=REPO)
    run(["git", "push"], cwd=REPO)
    print(f"Pushed: {msg}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Skip git commit+push")
    parser.add_argument("--message", help="Commit message (defaults to a dated refresh message)")
    args = parser.parse_args()

    if not DATA.exists():
        print(f"No data.json at {DATA}; nothing to bake.", file=sys.stderr)
        sys.exit(1)

    raw = json.loads(DATA.read_text())
    print(f"Baking pipeline data (lastUpdated {raw.get('lastUpdated')}, "
          f"{len(raw.get('clients', []))} clients, {len(raw.get('pipeline', []))} deals) "
          f"into encrypted page...")
    encrypt_with_staticrypt(raw)
    print(f"Encrypted -> {OUTPUT}")
    if args.dry_run:
        print("Dry run — skipping git commit+push.")
    else:
        git_commit_and_push(args.message)
