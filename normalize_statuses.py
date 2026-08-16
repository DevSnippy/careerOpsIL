#!/usr/bin/env python3
"""normalize_statuses: rewrite non-canonical Status text in data/applications.md.
"""
import os
import re
import shutil
import sys

from applications_table import HEADER_LINE
from canonical_states import CANONICAL_STATES, resolve_status

MD_PATH = os.path.join("data", "applications.md")


def find_data_row_indices(lines):
    indices = []
    in_table = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == HEADER_LINE:
            in_table = True
            continue
        if in_table and re.match(r"^\|[-:| ]+\|$", stripped):
            continue
        if in_table:
            if not stripped.startswith("|"):
                break
            indices.append(i)
    return indices


def main(argv):
    dry_run = "--dry-run" in argv

    if not os.path.exists(MD_PATH):
        print("No applications.md found. Nothing to normalize.")
        sys.exit(0)

    text = open(MD_PATH, encoding="utf-8").read()
    lines = text.split("\n")
    row_indices = find_data_row_indices(lines)

    normalized = 0
    unknown = []
    row_number = 0

    for idx in row_indices:
        row_number += 1
        line = lines[idx]
        segments = line.split("|")
        if len(segments) < 8:
            continue
        status_cell = segments[6]
        trimmed = status_cell.strip()

        if trimmed in CANONICAL_STATES:
            continue

        resolved = resolve_status(trimmed)
        if resolved is None:
            unknown.append((row_number, idx + 1, trimmed))
            continue

        print(f'#{row_number}: "{trimmed}" → "{resolved}"')
        segments[6] = f" {resolved} "
        lines[idx] = "|".join(segments)
        normalized += 1

    if unknown:
        print()
        print(f"⚠️  {len(unknown)} unknown statuses:")
        for row_number, line_number, value in unknown:
            print(f'  #{row_number} (line {line_number}): "{value}"')

    print()
    print(f"📊 {normalized} statuses normalized")

    if dry_run:
        print("(dry-run — no changes written)")
        sys.exit(0)

    if normalized == 0:
        print("✅ No changes needed")
        sys.exit(0)

    shutil.copyfile(MD_PATH, MD_PATH + ".bak")
    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ Written to {os.path.abspath(MD_PATH)} (backup: {os.path.abspath(MD_PATH)}.bak)")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
