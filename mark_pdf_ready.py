#!/usr/bin/env python3
"""mark_pdf_ready: flip a tracker row's PDF cell to ready, by report number.
"""
import json
import os
import sys

from applications_table import parse_report_cell, read_table_rows, render_table

MD_PATH = os.path.join("data", "applications.md")
READY_MARK = "✅"

USAGE = "Usage: python3 mark_pdf_ready.py <report#> [--dry-run] [--json]"


def die_usage():
    print(USAGE, file=sys.stderr)
    sys.exit(1)


def fail(reason, code, json_mode, candidates=None, exit_code=1):
    print(f"❌ {reason}", file=sys.stderr)
    if json_mode:
        payload = {"error": reason, "code": code}
        if candidates is not None:
            payload["candidates"] = candidates
        print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    sys.exit(exit_code)


def main(argv):
    if not argv:
        die_usage()

    positional = [a for a in argv if not a.startswith("--")]
    json_mode = "--json" in argv
    dry_run = "--dry-run" in argv
    if not positional:
        die_usage()
    report_num = int(positional[0])

    if not os.path.exists(MD_PATH):
        fail("data/applications.md not found", "not-found", json_mode, exit_code=2)
        return

    rows = read_table_rows(open(MD_PATH, encoding="utf-8").read())
    matches = []
    for r in rows:
        rn, _ = parse_report_cell(r["report"])
        if rn is not None and int(rn) == report_num:
            matches.append(r)

    if not matches:
        fail(f"No tracker row links report #{report_num}", "not-found", json_mode, exit_code=2)
        return
    if len(matches) > 1:
        listing = "\n".join(f"#{r['id']}\t{r['company']}\t{r['role']}" for r in matches)
        candidates = [{"num": int(r["id"]), "company": r["company"], "role": r["role"]}
                      for r in matches]
        fail(
            f"Report #{report_num} is linked by {len(matches)} tracker rows — "
            f"repair the Report cells:\n{listing}",
            "ambiguous", json_mode, candidates=candidates, exit_code=3,
        )
        return

    row = matches[0]
    already_ready = row["pdf"].strip() == READY_MARK
    verb = "would mark" if dry_run else "marked"

    if already_ready:
        print(f"✅ #{row['id']} {row['company']} — {row['role']}: already PDF ready")
        changed = False
    else:
        print(f"✅ #{row['id']} {row['company']} — {row['role']}: {verb} PDF ready")
        changed = True
        if not dry_run:
            row["pdf"] = READY_MARK
            with open(MD_PATH, "w", encoding="utf-8") as f:
                f.write(render_table(rows))

    if json_mode:
        print(json.dumps({
            "changed": changed, "num": int(row["id"]), "company": row["company"],
            "role": row["role"], "reportNum": report_num,
            "tracker": os.path.abspath(MD_PATH),
        }, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
