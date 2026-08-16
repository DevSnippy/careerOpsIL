#!/usr/bin/env python3
"""assessment_log: log skills-assessment events per application.
"""
import json
import os
import sys
from datetime import date

ASSESSMENTS_PATH = os.path.join("data", "assessments.tsv")
HEADER = (
    "# assessments.tsv — append-only skills-assessment log (user layer). "
    "Never rewrite rows.\n"
    "# {YYYY-MM-DD}\\t{company}\\t{report#|-}\\t{platform}\\t{subject}\\t"
    "{threshold%|-}\\t{score%|-}\\t{stale_note}\n"
)

USAGE = ('Usage: python assessment_log.py add --company <name> [--report <num>] '
         '--platform <vendor> --subject <topic> [--threshold <pct>] [--score <pct>] '
         '[--stale "<note>"]')


def get_flag(argv, name):
    if name in argv:
        idx = argv.index(name)
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return None


def cmd_add(argv):
    company = get_flag(argv, "--company")
    platform = get_flag(argv, "--platform")
    subject = get_flag(argv, "--subject")

    for flag, val in [("--company", company), ("--platform", platform), ("--subject", subject)]:
        if not val:
            print(f"assessment-log: {flag} is required", file=sys.stderr)
            print(USAGE, file=sys.stderr)
            sys.exit(1)

    report = get_flag(argv, "--report") or "-"
    threshold = get_flag(argv, "--threshold") or "-"
    score = get_flag(argv, "--score") or "-"
    stale = get_flag(argv, "--stale") or ""

    row = [date.today().isoformat(), company, report, platform, subject, threshold, score, stale]

    is_new = not os.path.exists(ASSESSMENTS_PATH)
    os.makedirs(os.path.dirname(ASSESSMENTS_PATH), exist_ok=True)
    with open(ASSESSMENTS_PATH, "a", encoding="utf-8") as f:
        if is_new:
            f.write(HEADER)
        f.write("\t".join(row) + "\n")

    print(json.dumps({"added": True, "row": row}, indent=2))
    sys.exit(0)


def load_assessments():
    if not os.path.exists(ASSESSMENTS_PATH):
        return []
    assessments = []
    for line in open(ASSESSMENTS_PATH, encoding="utf-8"):
        if not line.strip() or line.startswith("#"):
            continue
        cells = line.rstrip("\n").split("\t")
        if len(cells) != 8:
            continue
        date_, company, report, platform, subject, threshold, score, stale = cells
        assessments.append({
            "date": date_, "company": company,
            "reportNum": None if report == "-" else report,
            "platform": platform, "subject": subject,
            "threshold": None if threshold == "-" else int(threshold),
            "score": None if score == "-" else int(score),
            "staleNote": stale,
        })
    return assessments


def build_report():
    assessments = load_assessments()
    by_platform = {}
    for a in assessments:
        p = by_platform.setdefault(a["platform"], {
            "count": 0, "staleFlagged": 0, "passed": 0, "failed": 0, "unknownOutcome": 0,
        })
        p["count"] += 1
        if a["staleNote"]:
            p["staleFlagged"] += 1
        if a["threshold"] is not None and a["score"] is not None:
            if a["score"] >= a["threshold"]:
                p["passed"] += 1
            else:
                p["failed"] += 1
        else:
            p["unknownOutcome"] += 1

    return {
        "assessments": assessments,
        "aggregates": {"byPlatform": by_platform},
        "quality": {
            "total": len(assessments),
            "staleFlagged": sum(1 for a in assessments if a["staleNote"]),
            "withoutScore": sum(1 for a in assessments if a["score"] is None),
            "withoutThreshold": sum(1 for a in assessments if a["threshold"] is None),
            "malformedLines": [],
        },
    }


def main(argv):
    if argv and argv[0] == "add":
        cmd_add(argv[1:])
        return
    print(json.dumps(build_report(), indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
