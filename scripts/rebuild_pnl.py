#!/usr/bin/env python3
"""Rebuild the encrypted P&L dashboard.

Steps:
  1. Run bookkeeper-ai pnl-export to refresh pnl-actuals.json (Xero YTD).
  2. Compute next-year forecast from data.json (signed-contracts only).
  3. Inline the combined payload into templates/pnl.template.html.
  4. Run staticrypt to produce encrypted pnl.html.
  5. If pnl.html content changed, git add + commit + push.
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
TEMPLATE = REPO / "templates" / "pnl.template.html"
ACTUALS = REPO / "pnl-actuals.json"
DATA = REPO / "data.json"
STATICRYPT_CONFIG = REPO / ".staticrypt.json"
OUTPUT = REPO / "pnl.html"
PLAIN_TMP = REPO / ".pnl.plain.tmp.html"

BOOKKEEPER = Path.home() / "dev" / "bookkeeper-ai"
PASSWORD = os.environ.get("PNL_DASHBOARD_PASSWORD", "lpm2026")


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Command failed: {' '.join(cmd)}", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)
    return result


def refresh_actuals(year: int) -> None:
    venv_python = BOOKKEEPER / ".venv" / "bin" / "python"
    run(
        [str(venv_python), "-m", "src.main", "pnl-export", "--year", str(year), "--output", str(ACTUALS)],
        cwd=BOOKKEEPER,
    )


def months_in_year(start_ym: str, end_ym: str, year: int) -> int:
    """Count calendar months of overlap between [start_ym, end_ym] and `year`."""
    try:
        sy, sm = map(int, start_ym.split("-")[:2])
        ey, em = map(int, end_ym.split("-")[:2])
    except (ValueError, AttributeError):
        return 0
    start_month = max(sy * 12 + sm, year * 12 + 1)
    end_month = min(ey * 12 + em, year * 12 + 12)
    return max(0, end_month - start_month + 1)


def contract_entry(src: dict, monthly: float, start: str, end: str, year: int, label_suffix: str = "") -> dict | None:
    months = months_in_year(start, end, year)
    if months <= 0:
        return None
    revenue = round(months * monthly, 2)
    subs = []
    for s in src.get("subcontractors", []):
        sub_months = months
        if "startDate" in s and "endDate" in s:
            sub_months = months_in_year(s["startDate"], s["endDate"], year)
        if sub_months <= 0:
            continue
        subs.append({
            "name": s.get("name", "Subcontractor"),
            "role": s.get("role", ""),
            "monthlyRate": s.get("monthlyRate", 0),
            "totalCost": round(sub_months * s.get("monthlyRate", 0), 2),
        })
    return {
        "name": src.get("name", "Unnamed") + label_suffix,
        "revenue": revenue,
        "monthlyValue": monthly,
        "monthsInYear": months,
        "startDate": start,
        "endDate": end,
        "notes": src.get("notes", "")[:140] if src.get("notes") else "",
        "subcontractors": subs,
    }


def build_forecast(pipeline_data: dict, year: int) -> dict:
    contracts = []
    for c in pipeline_data.get("clients", []):
        entry = contract_entry(c, c.get("monthlyValue", 0), c.get("startDate", ""), c.get("endDate", ""), year, " (active)")
        if entry:
            contracts.append(entry)
    for p in pipeline_data.get("pipeline", []):
        if p.get("stage") != "closed-won":
            continue
        entry = contract_entry(p, p.get("monthlyValue", 0), p.get("proposalStartDate", ""), p.get("proposalEndDate", ""), year)
        if entry:
            contracts.append(entry)

    total_revenue = sum(c["revenue"] for c in contracts)
    total_sub_costs = sum(s["totalCost"] for c in contracts for s in c["subcontractors"])
    return {
        "year": year,
        "contracts": contracts,
        "totals": {
            "revenue": round(total_revenue, 2),
            "subcontractorCosts": round(total_sub_costs, 2),
            "grossProfit": round(total_revenue - total_sub_costs, 2),
        },
    }


def inline_payload(payload: dict) -> str:
    template = TEMPLATE.read_text()
    return template.replace("{{EMBEDDED_DATA}}", json.dumps(payload, separators=(",", ":")))


def encrypt_with_staticrypt() -> None:
    PLAIN_TMP.write_text(inline_payload(PAYLOAD))
    tmp_dir = REPO / ".staticrypt_out"
    tmp_dir.mkdir(exist_ok=True)
    run([
        "npx", "staticrypt", str(PLAIN_TMP),
        "-p", PASSWORD,
        "--short",
        "-d", str(tmp_dir),
        "--template-title", "LPM P&L Dashboard",
        "--template-color-primary", "#384BCF",
        "--template-color-secondary", "#FFFFF6",
    ], cwd=REPO)
    encrypted = tmp_dir / PLAIN_TMP.name
    shutil.move(str(encrypted), str(OUTPUT))
    shutil.rmtree(tmp_dir)
    PLAIN_TMP.unlink(missing_ok=True)


def git_commit_and_push(year: int) -> None:
    status = run(["git", "status", "--porcelain", "pnl.html", ".staticrypt.json"], cwd=REPO, check=False)
    if not status.stdout.strip():
        print("No changes to pnl.html — skipping commit.")
        return
    run(["git", "add", "pnl.html", ".staticrypt.json"], cwd=REPO)
    msg = f"Refresh P&L dashboard ({date.today().isoformat()})"
    run(["git", "commit", "-m", msg], cwd=REPO)
    run(["git", "push"], cwd=REPO)
    print(f"Pushed: {msg}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Skip git commit+push")
    parser.add_argument("--skip-actuals", action="store_true", help="Skip Xero fetch (reuse existing pnl-actuals.json)")
    args = parser.parse_args()

    today = date.today()
    current_year = today.year
    forecast_year = current_year + 1

    if not args.skip_actuals:
        print(f"Refreshing actuals for {current_year}...")
        refresh_actuals(current_year)

    actuals = json.loads(ACTUALS.read_text())
    pipeline_data = json.loads(DATA.read_text())
    forecast = build_forecast(pipeline_data, forecast_year)

    PAYLOAD = {
        "lastUpdated": today.isoformat(),
        "actuals": actuals,
        "forecast": forecast,
    }

    print(f"Forecast for {forecast_year}: {len(forecast['contracts'])} signed contracts, ${forecast['totals']['revenue']:,.0f} revenue")
    encrypt_with_staticrypt()
    print(f"Encrypted → {OUTPUT}")
    if args.dry_run:
        print("Dry run — skipping git commit+push.")
    else:
        git_commit_and_push(current_year)
