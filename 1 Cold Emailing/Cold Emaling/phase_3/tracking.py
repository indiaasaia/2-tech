#!/usr/bin/env python3
"""tracking.py — Show campaign tracking summary.

Displays:
  - All companies applied to (with dates, times, emails sent)
  - Total companies, total emails
  - Per-day breakdown
  - Phase 2 status (pending / errored companies)

Usage:
  python tracking.py              # full summary
  python tracking.py --today      # only today's activity
  python tracking.py --csv        # export to tracking_export.csv
"""
import argparse
import csv
import json
import os
import sys

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(errors="replace")
    except Exception:
        pass

from collections import defaultdict
from datetime import datetime, date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
TRACKING_CSV = os.path.join(HERE, "data", "tracking.csv")
STATE_FILE = os.path.join(HERE, "state.json")
SENT_HISTORY = os.path.join(HERE, "sent_history.csv")
PHASE1_CSV = os.path.join(ROOT, "phase_1", "data", "discovered_companies.csv")
PHASE2_OUTCOMES = os.path.join(ROOT, "phase_2", "data", "contact_discovery_outcomes.csv")


def read_tracking():
    if not os.path.exists(TRACKING_CSV):
        return []
    with open(TRACKING_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_sent_history():
    if not os.path.exists(SENT_HISTORY):
        return []
    with open(SENT_HISTORY, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_phase2_outcomes():
    if not os.path.exists(PHASE2_OUTCOMES):
        return []
    with open(PHASE2_OUTCOMES, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser(description="Campaign tracking summary")
    ap.add_argument("--today", action="store_true", help="show only today's activity")
    ap.add_argument("--csv", action="store_true", help="export to tracking_export.csv")
    args = ap.parse_args()

    tracking = read_tracking()
    history = read_sent_history()
    outcomes = read_phase2_outcomes()

    today_str = date.today().isoformat()

    print("=" * 70)
    print("  COLD EMAIL CAMPAIGN — TRACKING SUMMARY")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # --- Overall stats ---
    total_emails_sent = len(history)
    total_companies_emailed = len(set(r.get("company", "") for r in history))
    total_unique_recipients = len(set(r.get("to", "") for r in history))

    print(f"\n  📊 OVERALL STATS")
    print(f"  {'─' * 50}")
    print(f"  Total emails sent:        {total_emails_sent}")
    print(f"  Companies emailed:        {total_companies_emailed}")
    print(f"  Unique recipients:        {total_unique_recipients}")

    # --- Phase 1 & 2 status ---
    if os.path.exists(PHASE1_CSV):
        with open(PHASE1_CSV, encoding="utf-8-sig") as f:
            phase1 = list(csv.DictReader(f))
        print(f"  Companies discovered:     {len(phase1)}")

    done_outcomes = [o for o in outcomes if o.get("status") in ("CONTACTS_FOUND", "done")]
    no_email = [o for o in outcomes if o.get("status") in ("NO_PUBLIC_EMAIL_FOUND", "no_email")]
    errors = [o for o in outcomes if o.get("status") == "ERROR"]
    pending_names = set()
    for o in outcomes:
        if o.get("status") not in ("CONTACTS_FOUND", "done", "NO_PUBLIC_EMAIL_FOUND", "no_email"):
            pending_names.add(o.get("company_name", ""))

    print(f"  Phase 2 completed:        {len(done_outcomes)}")
    print(f"  Phase 2 no-email:         {len(no_email)}")
    print(f"  Phase 2 errors/pending:   {len(errors) + len(pending_names)}")

    # --- Per-day breakdown ---
    print(f"\n  📅 EMAILS PER DAY")
    print(f"  {'─' * 50}")
    daily = defaultdict(lambda: {"emails": 0, "companies": set()})
    for r in history:
        ts = r.get("timestamp", "")
        day = ts[:10] if ts else "unknown"
        daily[day]["emails"] += 1
        daily[day]["companies"].add(r.get("company", ""))

    for day in sorted(daily.keys()):
        if args.today and day != today_str:
            continue
        d = daily[day]
        marker = " ← TODAY" if day == today_str else ""
        print(f"  {day}:  {d['emails']:3d} emails  |  {len(d['companies']):2d} companies{marker}")

    # --- Company-by-company tracking ---
    print(f"\n  📋 COMPANIES APPLIED (tracking.csv)")
    print(f"  {'─' * 50}")

    if tracking:
        print(f"  {'Company':<40} {'Date':<12} {'Time':<10} {'Emails':<8}")
        print(f"  {'─'*40} {'─'*12} {'─'*10} {'─'*8}")
        for row in tracking:
            company = row.get("company", "")[:40]
            date_applied = row.get("date_applied", "")
            time_applied = row.get("time_applied", "")
            emails = row.get("emails_sent", "0")
            if args.today and date_applied != today_str:
                continue
            print(f"  {company:<40} {date_applied:<12} {time_applied:<10} {emails:<8}")
        print(f"\n  Total tracked: {len(tracking)} companies")
    else:
        # Fallback: build from sent_history
        print("  (No tracking.csv yet — showing from sent_history.csv)")
        company_stats = defaultdict(lambda: {"emails": 0, "first": "", "last": ""})
        for r in history:
            c = r.get("company", "")
            ts = r.get("timestamp", "")
            company_stats[c]["emails"] += 1
            if not company_stats[c]["first"] or ts < company_stats[c]["first"]:
                company_stats[c]["first"] = ts
            if not company_stats[c]["last"] or ts > company_stats[c]["last"]:
                company_stats[c]["last"] = ts

        print(f"  {'Company':<40} {'First Sent':<22} {'Last Sent':<22} {'Emails':<8}")
        print(f"  {'─'*40} {'─'*22} {'─'*22} {'─'*8}")
        for c in sorted(company_stats.keys()):
            s = company_stats[c]
            print(f"  {c[:40]:<40} {s['first'][:19]:<22} {s['last'][:19]:<22} {s['emails']:<8}")
        print(f"\n  Total: {len(company_stats)} companies")

    # --- Today's activity ---
    if not args.today:
        today_emails = [r for r in history if r.get("timestamp", "").startswith(today_str)]
        print(f"\n  🕐 TODAY ({today_str})")
        print(f"  {'─' * 50}")
        print(f"  Emails sent today: {len(today_emails)}")

    print(f"\n  {'=' * 50}")
    print(f"  Data files:")
    print(f"    Tracking:    {TRACKING_CSV}")
    print(f"    History:     {SENT_HISTORY}")
    print(f"    Campaign:    {os.path.join(HERE, 'data', 'campaign_log.csv')}")
    print(f"    State:       {STATE_FILE}")
    print(f"  {'=' * 50}")

    if args.csv:
        export = os.path.join(HERE, "data", "tracking_export.csv")
        if tracking:
            with open(export, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=tracking[0].keys())
                w.writeheader()
                w.writerows(tracking)
            print(f"\n  Exported to {export}")
        else:
            print("\n  No tracking.csv to export yet.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
