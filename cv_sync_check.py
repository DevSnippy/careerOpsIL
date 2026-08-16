#!/usr/bin/env python3
"""cv_sync_check: sanity-check cv.md / config/profile.yml setup.
"""
import os
import sys

CV_PATH = "cv.md"
PROFILE_PATH = os.path.join("config", "profile.yml")
PROFILE_EXAMPLE_PATH = os.path.join("config", "profile.example.yml")

MIN_CV_LENGTH = 500  # confirmed a ~60-char file is "too short"; a ~50-line CV is not


def main(argv):
    errors = []
    warnings = []

    if not os.path.exists(CV_PATH):
        errors.append("cv.md not found in project root. Create it with your CV in markdown format.")
    else:
        content = open(CV_PATH, encoding="utf-8").read()
        if len(content) < MIN_CV_LENGTH:
            warnings.append("cv.md seems too short. Make sure it contains your full CV.")

    if not os.path.exists(PROFILE_PATH):
        errors.append("config/profile.yml not found. Copy from config/profile.example.yml "
                       "and fill in your details.")
    elif os.path.exists(PROFILE_EXAMPLE_PATH):
        profile = open(PROFILE_PATH, encoding="utf-8").read()
        example = open(PROFILE_EXAMPLE_PATH, encoding="utf-8").read()
        for line in example.splitlines():
            if line.strip().startswith("full_name:") and line in profile:
                warnings.append("config/profile.yml may still have example data. "
                                 "Check field: full_name")
                break

    print()
    print("=== sync check ===")
    print()
    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  ERROR: {e}")
        print()
    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  WARN: {w}")
        print()

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
