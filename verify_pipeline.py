#!/usr/bin/env python3
"""verify_pipeline: read-only tracker data-integrity health check.

Scope note: implements 9 integrity checks. Four more (stale reservation
sentinels, duplicate report files by content, via-channel consistency,
active-interviews.md sync) are a known, flagged gap rather than guessed at.
"""
import os
import re
import sys
from collections import defaultdict

from applications_table import HEADER_LINE, parse_report_cell, read_table_rows, split_row
from canonical_states import CANONICAL_STATES

MD_PATH = os.path.join("data", "applications.md")
ADDITIONS_DIR = os.path.join("batch", "tracker-additions")
REPORTS_DIR = "reports"

SCORE_RE = re.compile(r"^\d+(\.\d{1,2})?/5$")
SCORE_SENTINELS = {"N/A", "DUP", "-", "—"}


def normalize(text):
    return re.sub(r"\s+", " ", text.strip()).lower()


def strip_bold(text):
    if text.startswith("**") and text.endswith("**") and len(text) > 4:
        return text[2:-2]
    return text


def raw_row_line_count(text):
    """Cell counts for every '|'-led line after the header, including
    malformed ones read_table_rows would silently skip."""
    lines = text.splitlines()
    in_table = False
    counts = []
    for line in lines:
        stripped = line.strip()
        if stripped == HEADER_LINE:
            in_table = True
            continue
        if in_table and re.match(r"^\|[-:| ]+\|$", stripped):
            continue
        if in_table:
            if not stripped.startswith("|"):
                break
            counts.append(len(split_row(stripped)))
    return counts


def report(ok, ok_message, problem_lines):
    if not problem_lines:
        print(f"✅ {ok_message}")
    else:
        for line in problem_lines:
            print(line)


def main(argv):
    if not os.path.exists(MD_PATH):
        print("📊 No applications.md found. This is normal for a fresh setup.")
        print("   The file will be created when you evaluate your first offer.")
        sys.exit(0)

    text = open(MD_PATH, encoding="utf-8").read()
    rows = read_table_rows(text)
    print(f"📊 Checking {len(rows)} entries in applications.md")
    print()

    errors = 0
    warnings = 0

    # 1. Canonical statuses
    lines = [f'❌ #{r["id"]}: Non-canonical status "{r["status"]}"'
             for r in rows if r["status"] not in CANONICAL_STATES]
    report(not lines, "All statuses are canonical", lines)
    errors += len(lines)

    # 2. Exact duplicates (company+role) — warning
    seen = {}
    lines = []
    for r in rows:
        key = (normalize(r["company"]), normalize(r["role"]))
        if key in seen:
            lines.append(f'⚠️  Possible duplicates: #{seen[key]["id"]}, #{r["id"]} '
                          f'({r["company"]} — {r["role"]})')
        else:
            seen[key] = r
    report(not lines, "No exact duplicates found", lines)
    warnings += len(lines)

    # 3. Report links valid
    # Report-cell paths are relative to applications.md's own directory
    # (confirmed: merge_tracker.py writes "../reports/..." there), not CWD.
    md_dir = os.path.dirname(MD_PATH)
    lines = []
    for r in rows:
        _, path = parse_report_cell(r["report"])
        if path and not os.path.exists(os.path.join(md_dir, path)):
            lines.append(f'❌ #{r["id"]}: Report not found: {path}')
    report(not lines, "All report links valid", lines)
    errors += len(lines)

    # 4. Scores valid
    lines = []
    for r in rows:
        stripped = strip_bold(r["score"])
        if not (SCORE_RE.match(stripped) or stripped in SCORE_SENTINELS):
            lines.append(f'❌ #{r["id"]}: Invalid score format: "{r["score"]}"')
    report(not lines, "All scores valid", lines)
    errors += len(lines)

    # 5. Rows properly formatted (structural; includes rows read_table_rows drops)
    lines = [f"❌ Line has {c} columns, expected 9"
             for c in raw_row_line_count(text) if c != 9]
    report(not lines, "All rows properly formatted", lines)
    errors += len(lines)

    # 6. No pending TSVs
    pending = 0
    if os.path.isdir(ADDITIONS_DIR):
        pending = len([f for f in os.listdir(ADDITIONS_DIR)
                       if f.endswith(".tsv") and os.path.isfile(os.path.join(ADDITIONS_DIR, f))])
    if pending:
        print(f"⚠️  {pending} pending TSVs in tracker-additions/ (not merged)")
        warnings += 1
    else:
        print("✅ No pending TSVs")

    # 7. No bold in scores
    lines = [f'⚠️  #{r["id"]}: Score has markdown bold: "{r["score"]}"'
             for r in rows if r["score"].startswith("**") and r["score"].endswith("**")]
    report(not lines, "No bold in scores", lines)
    warnings += len(lines)

    # 10. No orphan reports
    referenced = set()
    for r in rows:
        num, _ = parse_report_cell(r["report"])
        if num:
            referenced.add(str(int(num)))
    lines = []
    if os.path.isdir(REPORTS_DIR):
        for fname in sorted(os.listdir(REPORTS_DIR)):
            m = re.match(r"^(\d+)-", fname)
            if m and str(int(m.group(1))) not in referenced:
                lines.append(f'⚠️  Orphan report — no tracker row references '
                              f'#{int(m.group(1))}: {REPORTS_DIR}/{fname}')
    report(not lines, "No orphan reports", lines)
    warnings += len(lines)

    # 12. No duplicate tracker numbers
    by_id = defaultdict(list)
    for r in rows:
        by_id[r["id"]].append(r)
    lines = []
    for rid, group in by_id.items():
        if len(group) > 1:
            listing = " | ".join(f'{g["company"]} — {g["role"]}' for g in group)
            lines.append(f"❌ Duplicate tracker number #{rid} used by {len(group)} rows: {listing}")
    report(not lines, "No duplicate tracker numbers", lines)
    errors += len(lines)

    print()
    print("=" * 50)
    print(f"📊 Pipeline Health: {errors} errors, {warnings} warnings")
    if errors:
        print("🔴 Pipeline has errors — fix before proceeding")
        sys.exit(1)
    elif warnings:
        print("🟡 Pipeline OK with warnings")
    else:
        print("🟢 Pipeline is clean!")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
