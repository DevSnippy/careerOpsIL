#!/usr/bin/env python3
"""init: bootstrap a new tracker in the current directory.

Every tool in this project (tracker.py, merge_tracker.py, add_entry.py, ...)
requires data/applications.md (and add_entry.py's `cv` payload requires
cv.md) to already exist and errors out otherwise. Nothing else creates those
files for a brand-new user, so this does.
"""
import os
import sys

MD_PATH = os.path.join("data", "applications.md")
CV_PATH = "cv.md"

APPLICATIONS_HEADER = (
    "# Applications Tracker\n\n"
    "| # | Date | Company | Role | Score | Status | PDF | Report | Notes |\n"
    "|---|------|---------|------|-------|--------|-----|--------|-------|\n"
)

CV_TEMPLATE = (
    "# CV\n\n"
    "## Summary\n\n"
    "## Experience\n\n"
    "## Projects\n\n"
    "## Education\n\n"
    "## Skills\n"
)


def main(argv):
    force = "--force" in argv
    created = []
    skipped = []

    os.makedirs("data", exist_ok=True)
    if force or not os.path.exists(MD_PATH):
        with open(MD_PATH, "w", encoding="utf-8") as f:
            f.write(APPLICATIONS_HEADER)
        created.append(MD_PATH)
    else:
        skipped.append(MD_PATH)

    if force or not os.path.exists(CV_PATH):
        with open(CV_PATH, "w", encoding="utf-8") as f:
            f.write(CV_TEMPLATE)
        created.append(CV_PATH)
    else:
        skipped.append(CV_PATH)

    if created:
        print("Created:")
        for path in created:
            print(f"  {path}")
    if skipped:
        print("Already present, left untouched (pass --force to overwrite):")
        for path in skipped:
            print(f"  {path}")
    if not created and not skipped:
        print("Nothing to do.")

    print()
    print("Next: fill in cv.md, then use tracker.py / add_entry.py / set_status.py "
          "to start tracking.")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
