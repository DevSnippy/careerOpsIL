#!/usr/bin/env python3
"""upskill: skill-gap aggregation across tracked reports.

SCOPE: the gating logic and outer JSON skeleton are confirmed and
implemented precisely. The actual Machine Summary YAML gap-extraction,
weighting, and tiering logic is NOT implemented — see spec §4. This always
returns an empty gaps/excludedAsKnown/knownSkills result rather than a
guessed extraction.
"""
import json
import os
import sys

from applications_table import read_table_rows, parse_report_cell

MD_PATH = os.path.join("data", "applications.md")
CV_PATH = "cv.md"
DEFAULT_MIN_REPORTS = 5
LOW_FIT_THRESHOLD = 4


def score_num(score):
    try:
        return float(score.split("/")[0])
    except (ValueError, IndexError):
        return None


def main(argv):
    min_reports = DEFAULT_MIN_REPORTS
    if "--min-reports" in argv:
        min_reports = int(argv[argv.index("--min-reports") + 1])

    if not os.path.exists(MD_PATH):
        print(json.dumps({"error": "No applications tracker found. Run some evaluations first."},
                          indent=2))
        sys.exit(0)

    rows = read_table_rows(open(MD_PATH, encoding="utf-8").read())
    linked = [r for r in rows if parse_report_cell(r["report"])[0]]
    scored = [r for r in linked if score_num(r["score"]) is not None]

    if len(scored) < min_reports:
        print(json.dumps({
            "error": (f"Not enough data: {len(scored)}/{min_reports} scored reports. "
                      f"Evaluate more offers and come back."),
            "current": len(scored), "threshold": min_reports,
        }, indent=2))
        sys.exit(0)

    reports_read = 0
    for r in linked:
        _, path = parse_report_cell(r["report"])
        full_path = os.path.join("data", path)
        if not os.path.exists(full_path):
            full_path = path
        if os.path.exists(full_path):
            reports_read += 1

    low_fit = sum(1 for r in scored if score_num(r["score"]) < LOW_FIT_THRESHOLD)
    known_skill_count = 0
    if os.path.exists(CV_PATH):
        known_skill_count = 0  # extraction not implemented — see spec §4

    print(json.dumps({
        "schema_version": 1,
        "metadata": {
            "reportsLinked": len(linked), "reportsRead": reports_read,
            "reportsWithMachineSummary": 0, "reportsScored": len(scored),
            "lowFitReports": low_fit, "lowFitScoreThreshold": LOW_FIT_THRESHOLD,
            "knownSkillCount": known_skill_count,
        },
        "gaps": [], "excludedAsKnown": [], "knownSkills": [],
    }, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
