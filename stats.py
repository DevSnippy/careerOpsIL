#!/usr/bin/env python3
"""stats: lifetime pipeline statistics rollup.

Shares its funnel formula with dashboard.py's Progress screen — see
funnel_stats() below, used by both.
"""
import json
import os
import sys
from datetime import date

from applications_table import read_table_rows

MD_PATH = os.path.join("data", "applications.md")
SCAN_HISTORY_PATH = os.path.join("data", "scan-history.tsv")
PORTALS_PATH = "portals.yml"
FOLLOWUPS_PATH = os.path.join("data", "follow-ups.md")
SCAN_RUNS_PATH = os.path.join("data", "scan-runs.tsv")

LIFECYCLE_ORDER = ["Evaluated", "Applied", "Responded", "Interview", "Offer", "Hired"]
APPLIED_ONLY_STATUSES = {"Rejected", "Discarded"}

# byStatus key order is specific to this tool — differs from
# CANONICAL_STATES (set_status.py has Hired last; stats.py puts it right
# after Offer). Not a contradiction: two independent display orders.
STATS_STATUS_ORDER = ["Evaluated", "Applied", "Responded", "Interview", "Offer",
                       "Hired", "Rejected", "Discarded", "SKIP"]

USAGE = (
    "Usage:\n"
    "  python stats.py             # full JSON stats to stdout\n"
    "  python stats.py --summary   # human-readable table\n"
    "  python stats.py --help|-h   # print this usage block and exit"
)


def score_num(score):
    try:
        return float(score.split("/")[0])
    except (ValueError, IndexError):
        return None


def stage_index(status):
    if status in LIFECYCLE_ORDER:
        return LIFECYCLE_ORDER.index(status)
    if status in APPLIED_ONLY_STATUSES:
        return 1
    return 0


def funnel_stats(rows):
    """Shared with dashboard.py's Progress screen — same confirmed formula:
    Applied% relative to Evaluated; Responded/Interview/Offer% relative to
    Applied; Rejected/Discarded excluded from Responded+."""
    indices = [stage_index(r["status"]) for r in rows]
    applied = sum(1 for i in indices if i >= 1)
    responded = sum(1 for i in indices if i >= 2)
    interview = sum(1 for i in indices if i >= 3)
    offer = sum(1 for i in indices if i >= 4)
    pct = lambda n, base: round(n / base * 100) if base else 0
    return {
        "everApplied": applied, "everResponded": responded,
        "everInterview": interview, "everOffer": offer,
        "responseRate": pct(responded, applied), "interviewRate": pct(interview, applied),
        "offerRate": pct(offer, applied), "smallSample": applied < 20,
    }


def tracker_stats(rows):
    total = len(rows)
    by_status = {s: 0 for s in STATS_STATUS_ORDER}
    for r in rows:
        if r["status"] in by_status:
            by_status[r["status"]] += 1
    scores = [s for s in (score_num(r["score"]) for r in rows) if s is not None]
    applied_scores = [score_num(r["score"]) for r in rows
                       if stage_index(r["status"]) >= 1 and score_num(r["score"]) is not None]
    active = [r for r in rows if stage_index(r["status"]) >= 1
              and r["status"] not in ("Rejected", "Discarded", "Hired")]
    pdf_ready = sum(1 for r in rows if r["pdf"].strip() == "✅")
    with_report = sum(1 for r in rows if r["report"].strip() not in ("", "-", "—"))
    return {
        "total": total, "byStatus": by_status,
        "avgScore": round(sum(scores) / len(scores), 1) if scores else 0,
        "avgScoreApplied": round(sum(applied_scores) / len(applied_scores), 1)
                            if applied_scores else 0,
        "topScore": max(scores) if scores else 0,
        "pdfPct": round(pdf_ready / total * 100) if total else 0,
        "reportPct": round(with_report / total * 100) if total else 0,
        "activeApps": len(active), "activeAppsLive": len(active), "activeAppsCold": 0,
    }


def build_report():
    tracker_present = os.path.exists(MD_PATH)
    rows = read_table_rows(open(MD_PATH, encoding="utf-8").read()) if tracker_present else []

    return {
        "metadata": {
            "generatedAt": date.today().isoformat(),
            "sources": {
                "tracker": tracker_present,
                "scanHistory": os.path.exists(SCAN_HISTORY_PATH),
                "followups": os.path.exists(FOLLOWUPS_PATH),
                "portals": os.path.exists(PORTALS_PATH),
                "scanRuns": os.path.exists(SCAN_RUNS_PATH),
                "portalHealth": False,
            },
        },
        "tracker": tracker_stats(rows) if tracker_present else None,
        "funnel": funnel_stats(rows) if tracker_present else None,
        "scan": None, "portals": None, "followups": None, "runs": None,
    }


def print_summary(report):
    today = report["metadata"]["generatedAt"]
    print("━" * 45)
    print(f"Pipeline Stats — {today}")
    print("━" * 45)

    t = report["tracker"]
    if t:
        print(f"Tracker:    {t['total']} total | {t['activeApps']} active | "
              f"avg fit {t['avgScore']}/5 (pursued roles {t['avgScoreApplied']}/5) | "
              f"top {t['topScore']}")
        nonzero = [f"{s} {n}" for s, n in t["byStatus"].items() if n]
        print("Status:     " + " · ".join(nonzero))
    else:
        print("Tracker:    — no data (data/applications.md missing)")

    f = report["funnel"]
    if f:
        note = " (small sample — rates indicative only)" if f["smallSample"] else ""
        print(f"Funnel:     ever applied {f['everApplied']} → "
              f"responded {f['everResponded']} ({f['responseRate']}%) → "
              f"interview {f['everInterview']} ({f['interviewRate']}%) → "
              f"offer {f['everOffer']} ({f['offerRate']}%){note}")

    print("Scanner:    — no data (data/scan-history.tsv missing)"
          if not report["metadata"]["sources"]["scanHistory"] else "Scanner: (data present)")
    print("Portals:    — no data (portals.yml missing)"
          if not report["metadata"]["sources"]["portals"] else "Portals: (data present)")
    print("Follow-ups: — no data (data/follow-ups.md missing)"
          if not report["metadata"]["sources"]["followups"] else "Follow-ups: (data present)")
    print("Runs:       — no data (data/scan-runs.tsv missing; created by the next scan)"
          if not report["metadata"]["sources"]["scanRuns"] else "Runs: (data present)")


def main(argv):
    if "--help" in argv or "-h" in argv:
        print(USAGE)
        sys.exit(0)
    report = build_report()
    if "--summary" in argv:
        print_summary(report)
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
