#!/usr/bin/env python3
"""dedup_tracker: remove duplicate rows from data/applications.md.
"""
import os
import re
import shutil
import sys

from applications_table import parse_report_cell, read_table_rows, render_table
from canonical_states import EARLY_STATUSES

MD_PATH = os.path.join("data", "applications.md")

USAGE = "Usage: python dedup_tracker.py [--dry-run]"


def normalize(text):
    return re.sub(r"\s+", " ", text.strip()).lower()


def score_value(score):
    m = re.match(r"^(\d+(?:\.\d{1,2})?)/5$", score)
    return float(m.group(1)) if m else -1.0


def merge_notes(kept, removed):
    if removed["notes"] and removed["notes"] != kept["notes"]:
        if kept["notes"]:
            kept["notes"] = kept["notes"] + "; " + removed["notes"]
        else:
            kept["notes"] = removed["notes"]
        print(f"  📝 #{kept['id']}: notes merged")


def main(argv):
    if "--help" in argv or "-h" in argv:
        print(USAGE)
        sys.exit(0)
    dry_run = "--dry-run" in argv

    if not os.path.exists(MD_PATH):
        print("No applications.md found. Nothing to dedup.")
        sys.exit(0)

    rows = read_table_rows(open(MD_PATH, encoding="utf-8").read())
    for r in rows:
        r["id"] = r["id"].strip()
    print(f"📊 {len(rows)} entries loaded")

    removed_ids = set()
    removed_count = 0

    # Pass 1: exact duplicates, matched by report number.
    seen_report = {}
    for r in rows:
        if id(r) in removed_ids:
            continue
        rn, _ = parse_report_cell(r["report"])
        if rn is None:
            continue
        if rn in seen_report:
            kept = seen_report[rn]
            merge_notes(kept, r)
            print(f"🗑️  Remove #{r['id']} ({r['company']} — {r['role']}, {r['score']}) "
                  f"→ kept #{kept['id']} ({kept['score']})")
            removed_ids.add(id(r))
            removed_count += 1
        else:
            seen_report[rn] = r

    # Pass 2: fuzzy company+role match across different report numbers.
    remaining = [r for r in rows if id(r) not in removed_ids]
    groups = {}
    for r in remaining:
        key = (normalize(r["company"]), normalize(r["role"]))
        groups.setdefault(key, []).append(r)

    for key, group in groups.items():
        if len(group) < 2:
            continue
        report_nums = {parse_report_cell(r["report"])[0] for r in group}
        if len(report_nums) < 2:
            continue  # same report number already handled in pass 1

        if all(r["status"].strip().lower() in EARLY_STATUSES for r in group):
            kept = max(group, key=lambda r: score_value(r["score"]))
            for r in group:
                if r is kept:
                    continue
                merge_notes(kept, r)
                print(f"🗑️  Remove #{r['id']} ({r['company']} — {r['role']}, {r['score']}) "
                      f"→ kept #{kept['id']} ({kept['score']})")
                removed_ids.add(id(r))
                removed_count += 1
        else:
            ids = sorted((r["id"] for r in group), key=lambda x: int(x) if x.lstrip("-").isdigit() else 0)
            print(f"⚠️  Keep #{ids[0]} and #{ids[1]}: exact-title match but "
                  f"advanced status requires exact report identity")

    print()
    print(f"📊 {removed_count} duplicates removed")

    if dry_run:
        print("(dry-run — no changes written)")
        sys.exit(0)

    if removed_count == 0:
        sys.exit(0)

    kept_rows = [r for r in rows if id(r) not in removed_ids]
    shutil.copyfile(MD_PATH, MD_PATH + ".bak")
    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write(render_table(kept_rows))
    print(f"✅ Written to {os.path.abspath(MD_PATH)} (backup: {os.path.abspath(MD_PATH)}.bak)")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
