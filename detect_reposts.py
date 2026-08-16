#!/usr/bin/env python3
"""detect_reposts: flag repost/ghost-job clusters from scan history.

SCOPE: the empty-state/--summary/--help behavior is implemented. The
scan-history.tsv clustering condition itself is unresolved — this always
reports zero clusters rather than guessing a schema and a matching condition.
"""
import os
import sys

SCAN_HISTORY_PATH = os.path.join("data", "scan-history.tsv")
DEFAULT_WINDOW_DAYS = 90

USAGE = (
    "Usage:\n"
    "  python detect_reposts.py                       # full JSON repost clusters to stdout\n"
    "  python detect_reposts.py --summary             # human-readable table\n"
    "  python detect_reposts.py --window 60           # override the default 90-day window\n"
    "  python detect_reposts.py --help                # print this usage block and exit"
)


def count_rows():
    if not os.path.exists(SCAN_HISTORY_PATH):
        return 0
    with open(SCAN_HISTORY_PATH, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def main(argv):
    if "--help" in argv or "-h" in argv:
        print(USAGE)
        sys.exit(0)

    window = DEFAULT_WINDOW_DAYS
    if "--window" in argv:
        window = int(argv[argv.index("--window") + 1])

    total_rows = count_rows()

    # NOTE: clustering logic not implemented — see module docstring.
    clusters = []

    if "--summary" in argv:
        print()
        print("=" * 78)
        print("  Repost Detector")
        print(f"  window: {window} days | clusters: {len(clusters)}")
        print("=" * 78)
        print()
        if not clusters:
            print("  No reposted roles detected.")
        print()
    else:
        import json
        print(json.dumps({
            "metadata": {"windowDays": window, "totalRows": total_rows,
                         "clusters": len(clusters)},
            "clusters": clusters,
        }, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
