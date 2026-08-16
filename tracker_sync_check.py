#!/usr/bin/env python3
"""tracker_sync_check: status-drift report between applications.md and
active-interviews.md.

NOTE: the exact data/active-interviews.md column schema is not fully
pinned down — this implementation assumes a `Company | Role | Status |
Notes` Markdown table, and treats "Status" literally where present,
falling back to the Interview stage when it is not confidently resolvable.
Revisit if a real active-interviews.md sample surfaces a different schema.
"""
import json
import os
import re
import sys

from applications_table import read_table_rows, split_row

MD_PATH = os.path.join("data", "applications.md")
ACTIVE_INTERVIEWS_PATH = os.path.join("data", "active-interviews.md")

LIFECYCLE_ORDER = ["Evaluated", "Applied", "Responded", "Interview", "Offer", "Hired"]
TRACKER_REF_RE = re.compile(r"#(\d+)\s+in\s+tracker", re.IGNORECASE)


def normalize(text):
    return re.sub(r"\s+", " ", text.strip()).lower()


def load_tracker_rows():
    if not os.path.exists(MD_PATH):
        return []
    return read_table_rows(open(MD_PATH, encoding="utf-8").read())


def load_active_interviews():
    if not os.path.exists(ACTIVE_INTERVIEWS_PATH):
        return []
    lines = open(ACTIVE_INTERVIEWS_PATH, encoding="utf-8").read().splitlines()
    rows = []
    header_seen = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if re.match(r"^\|[-:| ]+\|$", stripped):
            continue
        cells = split_row(stripped)
        if not header_seen:
            header_seen = True
            continue  # header row itself
        if len(cells) < 3:
            continue
        rows.append({"company": cells[0], "role": cells[1], "status": cells[2],
                      "notes": cells[3] if len(cells) > 3 else ""})
    return rows


def lifecycle_index(status):
    return LIFECYCLE_ORDER.index(status) if status in LIFECYCLE_ORDER else -1


def build_report():
    tracker_rows = load_tracker_rows()
    tracker_by_id = {r["id"].strip(): r for r in tracker_rows}

    mismatches = []
    tier1 = tier2 = matched_no_mismatch = unmatched = 0

    for ai_row in load_active_interviews():
        m = TRACKER_REF_RE.search(ai_row["notes"])
        tracker_row = None
        match_method = None
        match_confidence = 0

        if m and m.group(1) in tracker_by_id:
            tracker_row = tracker_by_id[m.group(1)]
            match_method = "tracker-ref"
            match_confidence = 1
        else:
            for r in tracker_rows:
                if (normalize(r["company"]) == normalize(ai_row["company"]) and
                        normalize(r["role"]) == normalize(ai_row["role"])):
                    tracker_row = r
                    match_method = "fuzzy"
                    match_confidence = 1
                    break

        if tracker_row is None:
            unmatched += 1
            mismatches.append({
                "trackerNum": None, "company": ai_row["company"], "role": ai_row["role"],
                "applicationsStatus": None, "activeInterviewsStatus": ai_row["status"],
                "resolution": "unmatched", "matchMethod": "unmatched", "matchConfidence": 0,
                "note": "No tracker reference in Notes and no confident Company+Role fuzzy match",
            })
            continue

        apps_status = tracker_row["status"]
        # Presence in active-interviews.md implies at least "Interview" stage,
        # per the confirmed anomaly in the spec: a matching literal Status
        # value still produced a mismatch suggesting Interview.
        implied_status = "Interview"
        if apps_status == implied_status:
            matched_no_mismatch += 1
            continue

        apps_idx = lifecycle_index(apps_status)
        implied_idx = lifecycle_index(implied_status)
        if apps_idx != -1 and apps_idx < implied_idx:
            tier1 += 1
            mismatches.append({
                "trackerNum": int(tracker_row["id"]), "company": tracker_row["company"],
                "role": tracker_row["role"], "applicationsStatus": apps_status,
                "activeInterviewsStatus": ai_row["status"], "resolution": "auto-tier1",
                "suggestedStatus": implied_status, "staleIn": "applications.md",
                "matchMethod": match_method, "matchConfidence": match_confidence,
            })
        else:
            tier2 += 1
            mismatches.append({
                "trackerNum": int(tracker_row["id"]), "company": tracker_row["company"],
                "role": tracker_row["role"], "applicationsStatus": apps_status,
                "activeInterviewsStatus": ai_row["status"], "resolution": "tier2",
                "matchMethod": match_method, "matchConfidence": match_confidence,
            })

    return {
        "mismatches": mismatches,
        "summary": {"total": len(mismatches), "tier1": tier1, "tier2": tier2,
                     "matchedNoMismatch": matched_no_mismatch, "unmatched": unmatched},
    }


def print_summary(report):
    print()
    print("=" * 90)
    print(f"  Tracker Sync Check — {report['summary']['total']} rows checked")
    print("  applications.md <-> active-interviews.md")
    print("=" * 90)
    print()
    if report["mismatches"]:
        print(f"  {'Company':<20}{'Role':<28}{'Apps':<12}{'Interviews':<12}Resolution")
        print("  " + "-" * 100)
        for m in report["mismatches"]:
            note = f" ({m['note']})" if "note" in m else ""
            print(f"  {m['company']:<20}{m['role']:<28}"
                  f"{(m['applicationsStatus'] or '—'):<12}{m['activeInterviewsStatus']:<12}"
                  f"{m['resolution']}{note}")
        print()
    s = report["summary"]
    print(f"  Tier 1 (auto-resolvable): {s['tier1']}")
    print(f"  Tier 2 (needs review):    {s['tier2']}")
    print(f"  Matched, no mismatch:     {s['matchedNoMismatch']}")
    print(f"  Unmatched:                {s['unmatched']}")
    print()
    print("  Read-only report — no files were modified. Fix Tier 1 rows by hand for now.")


def main(argv):
    report = build_report()
    if "--summary" in argv:
        print_summary(report)
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
