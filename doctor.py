#!/usr/bin/env python3
"""doctor: onboarding/setup checker.

SCOPE: file-existence/auto-copy/onboarding-status checks. Python/Playwright
version checks and any plugin-environment checks are intentionally not
implemented yet.
"""
import json
import os
import shutil
import sys

NEVER_AUTO_CREATED = ["cv.md", os.path.join("config", "profile.yml"), "portals.yml"]
AUTO_COPY_PAIRS = [
    (os.path.join("modes", "_profile.md"), os.path.join("modes", "_profile.template.md")),
    (os.path.join("modes", "_custom.md"), os.path.join("modes", "_custom.template.md")),
    (os.path.join("modes", "_brief.md"), os.path.join("modes", "_brief.template.md")),
]


def run_checks():
    missing = [f for f in NEVER_AUTO_CREATED if not os.path.exists(f)]
    auto_copied = []
    for dest, template in AUTO_COPY_PAIRS:
        if not os.path.exists(dest):
            if os.path.exists(template):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copyfile(template, dest)
                auto_copied.append(dest)
            else:
                missing.append(dest)
    return {
        "onboardingNeeded": len(missing) > 0,
        "missing": missing,
        "autoCopied": auto_copied,
    }


def print_human(result):
    print()
    print("doctor")
    print("=" * 16)
    print()
    for f in NEVER_AUTO_CREATED:
        if f in result["missing"]:
            print(f"⚠ {f} not found (user setup required)")
        else:
            print(f"✓ {f} found")
    for dest, _ in AUTO_COPY_PAIRS:
        if dest in result["autoCopied"]:
            print(f"✓ {dest} created from template")
        elif dest in result["missing"]:
            print(f"⚠ {dest} not found (user setup required)")
        else:
            print(f"✓ {dest} found")
    print()


def main(argv):
    result = run_checks()
    if "--json" in argv:
        print(json.dumps(result, indent=2))
    else:
        print_human(result)
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
