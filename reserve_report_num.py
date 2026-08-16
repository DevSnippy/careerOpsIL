#!/usr/bin/env python3
"""reserve_report_num: hand out unique report numbers to parallel workers.

CAUTION: any unrecognized flag, including --help, falls through to a real
bare reservation rather than printing usage. Deliberate, not a bug.
"""
import os
import re
import sys

from applications_table import parse_report_cell, read_table_rows

MD_PATH = os.path.join("data", "applications.md")
REPORTS_DIR = "reports"
COUNTER_PATH = os.path.join(REPORTS_DIR, ".reserve-counter")

RELEASE_USAGE = "Usage: python3 reserve_report_num.py --release <NNN>[-<MMM>]"


def load_rows():
    if not os.path.exists(MD_PATH):
        return []
    return read_table_rows(open(MD_PATH, encoding="utf-8").read())


def occupied_numbers():
    occupied = set()
    if os.path.isdir(REPORTS_DIR):
        for fname in os.listdir(REPORTS_DIR):
            m = re.match(r"^(\d+)-", fname)
            if m:
                occupied.add(int(m.group(1)))
    for r in load_rows():
        rid = r["id"].strip()
        if rid.lstrip("-").isdigit():
            occupied.add(int(rid))
        rn, _ = parse_report_cell(r["report"])
        if rn is not None:
            occupied.add(int(rn))
    return occupied


def read_counter():
    if os.path.exists(COUNTER_PATH):
        try:
            return int(open(COUNTER_PATH).read().strip())
        except ValueError:
            return 0
    return 0


def write_counter(n):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(COUNTER_PATH, "w") as f:
        f.write(str(n))


def reserve_one(occupied, counter):
    candidate = counter + 1
    while candidate in occupied:
        candidate += 1
    occupied.add(candidate)
    with open(os.path.join(REPORTS_DIR, f"{candidate:03d}-RESERVED.md"), "w") as f:
        f.write("")
    return candidate


def cmd_release(argv):
    if not argv:
        print(RELEASE_USAGE, file=sys.stderr)
        sys.exit(1)
    spec = argv[0]
    if "-" in spec:
        start_s, end_s = spec.split("-", 1)
        start, end = int(start_s), int(end_s)
    else:
        start = end = int(spec)
    for n in range(start, end + 1):
        path = os.path.join(REPORTS_DIR, f"{n:03d}-RESERVED.md")
        if os.path.exists(path):
            os.remove(path)
    sys.exit(0)


def main(argv):
    if argv and argv[0] == "--release":
        cmd_release(argv[1:])
        return

    count = 1
    if argv and argv[0] == "--count" and len(argv) > 1:
        count = int(argv[1])
    # Any other/unrecognized flag combination (including --help) falls
    # through to a bare single reservation — confirmed original behavior.

    occupied = occupied_numbers()
    counter = read_counter()
    reserved = []
    for _ in range(count):
        n = reserve_one(occupied, counter)
        counter = n
        reserved.append(n)
    write_counter(counter)

    if len(reserved) == 1:
        print(f"{reserved[0]:03d}")
    else:
        print(f"{reserved[0]:03d}-{reserved[-1]:03d}")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
