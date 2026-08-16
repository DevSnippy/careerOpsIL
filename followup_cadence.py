#!/usr/bin/env python3
"""followup_cadence: per-application follow-up cadence calculator.

SCOPE: the fresh/no-history/Applied-status cadence formula is confirmed and
implemented precisely. Cadence math for rows with follow-up history or
non-Applied statuses, and the urgent/cold/waiting/retired thresholds beyond
"overdue", are unverified (see spec §4) — implemented as reasonable
extrapolations of the same formula, flagged here rather than in the spec.
"""
import json
import os
import sys
from datetime import date, timedelta

from applications_table import parse_report_cell, read_table_rows

MD_PATH = os.path.join("data", "applications.md")
FOLLOWUPS_PATH = os.path.join("data", "follow-ups.md")

DEFAULT_CADENCE = {
    "applied_first": 7, "applied_subsequent": 7, "applied_max_followups": 2,
    "responded_initial": 1, "responded_subsequent": 3, "interview_thankyou": 1,
}


def parse_date(s):
    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d)


def main(argv):
    cadence = dict(DEFAULT_CADENCE)
    if "--applied-days" in argv:
        cadence["applied_first"] = int(argv[argv.index("--applied-days") + 1])

    if not os.path.exists(MD_PATH):
        print(json.dumps({"error": "No applications found in tracker."}, indent=2))
        sys.exit(1)

    rows = read_table_rows(open(MD_PATH, encoding="utf-8").read())
    today = date.today()

    entries = []
    overdue = urgent = cold = waiting = retired = 0

    for r in rows:
        applied_date = parse_date(r["date"])
        applied_source = "evaluation-date-fallback"
        days_since_application = (today - applied_date).days

        next_followup_date = applied_date + timedelta(days=cadence["applied_first"])
        days_until_next = (next_followup_date - today).days

        if days_until_next < 0:
            urgency = "overdue"
            overdue += 1
        elif days_until_next <= 2:
            urgency = "urgent"
            urgent += 1
        else:
            urgency = "waiting"
            waiting += 1

        _, report_path = parse_report_cell(r["report"])
        entries.append({
            "num": int(r["id"]), "date": r["date"], "appliedDate": applied_date.isoformat(),
            "appDateSource": applied_source, "company": r["company"], "via": None,
            "role": r["role"], "status": r["status"].lower(), "score": r["score"],
            "notes": r["notes"], "reportPath": report_path, "contacts": [],
            "daysSinceApplication": days_since_application, "daysSinceLastFollowup": None,
            "followupCount": 0, "followups": [], "urgency": urgency,
            "nextFollowupDate": next_followup_date.isoformat(), "nextOverride": None,
            "daysUntilNext": days_until_next,
        })

    print(json.dumps({
        "metadata": {
            "analysisDate": today.isoformat(), "totalTracked": len(rows),
            "actionable": len(rows), "overdue": overdue, "urgent": urgent,
            "cold": cold, "waiting": waiting, "retired": retired,
        },
        "entries": entries,
        "cadenceConfig": cadence,
        "cadenceDefaults": DEFAULT_CADENCE,
    }, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
