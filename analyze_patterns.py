#!/usr/bin/env python3
"""analyze_patterns: outcome pattern analysis over the tracker.

SCOPE: outcome classification, funnel, and scoreComparison are confirmed and
implemented precisely. archetypeBreakdown/blockerAnalysis/remotePolicy/
companySizeBreakdown/vendorAnalysis/viaChannelAnalysis/techStackGaps/
discardReasonStats depend on report Machine Summary YAML content that was
never reverse-engineered (see spec §4) — implemented here as correctly-shaped
but content-empty stubs, not guessed extraction logic.
"""
import json
import os
import sys
from datetime import date

from applications_table import read_table_rows

MD_PATH = os.path.join("data", "applications.md")
DEFAULT_THRESHOLD = 5

OUTCOME_MAP = {
    "Applied": "positive", "Responded": "positive", "Interview": "positive",
    "Offer": "positive", "Hired": "positive",
    "Rejected": "negative", "Discarded": "negative",
    "SKIP": "self_filtered",
    "Evaluated": "pending",
}
OUTCOME_BUCKETS = ["positive", "negative", "self_filtered", "pending"]
FUNNEL_STATUSES = ["Applied", "Interview", "Offer", "Hired", "Rejected",
                    "Discarded", "SKIP", "Responded", "Evaluated"]

VENDOR_SCOPE = ["greenhouse", "lever", "ashby", "workday", "icims"]
VENDOR_CITATION = ("Bommasani et al., Algorithmic Monocultures in Hiring, "
                    "FAccT 2026 (arXiv:2605.27371)")


def score_num(score):
    try:
        return float(score.split("/")[0])
    except (ValueError, IndexError):
        return None


def load_rows():
    if not os.path.exists(MD_PATH):
        return None
    return read_table_rows(open(MD_PATH, encoding="utf-8").read())


def bucket_stats(rows):
    stats = {}
    for bucket in OUTCOME_BUCKETS:
        scores = [score_num(r["score"]) for r in rows if OUTCOME_MAP.get(r["status"]) == bucket]
        scores = [s for s in scores if s is not None]
        stats[bucket] = {
            "avg": round(sum(scores) / len(scores), 2) if scores else 0,
            "min": min(scores) if scores else 0,
            "max": max(scores) if scores else 0,
            "count": len(scores),
        }
    return stats


def score_threshold(rows):
    positive_scores = [score_num(r["score"]) for r in rows
                        if OUTCOME_MAP.get(r["status"]) == "positive"]
    positive_scores = [s for s in positive_scores if s is not None]
    if not positive_scores:
        return {"recommended": None, "reasoning": "No positive outcomes yet.", "positiveRange": None}
    lo, hi = min(positive_scores), max(positive_scores)
    return {
        "recommended": lo,
        "reasoning": (f"Lowest score among positive outcomes is {lo}. "
                      f"No applications below this score led to progress."),
        "positiveRange": f"{lo} - {hi}",
    }


def build_report(rows, threshold):
    beyond_evaluated = [r for r in rows if r["status"] != "Evaluated"]
    if len(beyond_evaluated) < threshold:
        return {
            "error": (f"Not enough data: {len(beyond_evaluated)}/{threshold} applications "
                      f'beyond "Evaluated". Keep applying and come back later.'),
            "current": len(beyond_evaluated), "threshold": threshold,
        }, 1

    by_outcome = {b: 0 for b in OUTCOME_BUCKETS}
    for r in rows:
        bucket = OUTCOME_MAP.get(r["status"])
        if bucket:
            by_outcome[bucket] += 1

    dates = sorted(r["date"] for r in rows if r["date"])
    funnel = {s.lower(): sum(1 for r in rows if r["status"] == s) for s in FUNNEL_STATUSES}

    report = {
        "metadata": {
            "total": len(rows),
            "dateRange": {"from": dates[0], "to": dates[-1]} if dates else None,
            "analysisDate": date.today().isoformat(),
            "byOutcome": by_outcome,
        },
        "funnel": funnel,
        "scoreComparison": bucket_stats(rows),
        "archetypeBreakdown": [], "blockerAnalysis": [], "remotePolicy": [],
        "companySizeBreakdown": [],
        "vendorAnalysis": {
            "scope": VENDOR_SCOPE, "minSampleForClaim": 8, "submitted": len(rows),
            "identified": 0, "coveragePct": 0, "overallAdvanceRate": 0,
            "breakdown": [], "citation": VENDOR_CITATION,
        },
        "viaChannelAnalysis": {
            "minSampleForClaim": 8, "agencySubmitted": 0, "directSubmitted": 0,
            "unknownVia": len(rows), "agencyAdvanceRate": 0, "directAdvanceRate": 0,
            "breakdown": [],
        },
        "scoreThreshold": score_threshold(rows),
        "techStackGaps": [], "discardReasonStats": [], "recommendations": [],
    }
    return report, 0


def main(argv):
    threshold = DEFAULT_THRESHOLD
    if "--min-threshold" in argv:
        threshold = int(argv[argv.index("--min-threshold") + 1])

    rows = load_rows()
    if rows is None:
        print(json.dumps({"error": "No applications found in tracker."}, indent=2))
        sys.exit(1)

    report, exit_code = build_report(rows, threshold)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(exit_code)


if __name__ == "__main__":
    main(sys.argv[1:])
