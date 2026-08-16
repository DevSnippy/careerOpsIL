#!/usr/bin/env python3
"""archive_posting: save a live job posting as PDF (--dry-run path only).

SCOPE: only --dry-run is implemented (filename generation, argument
handling, --pipeline's missing-file case). The actual live-URL fetch and
PDF rendering are out of scope — see spec §1/§5.
"""
import os
import re
import sys
from datetime import date

JDS_DIR = "jds"
PIPELINE_PATH = os.path.join("data", "pipeline.md")


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "unknown"


def get_flag(argv, name):
    prefix = f"--{name}="
    for tok in argv:
        if tok.startswith(prefix):
            return tok[len(prefix):]
    return None


def build_filename(company, role, report):
    today = date.today().isoformat()
    company_slug = slug(company) if company else "unknown"
    role_slug = slug(role) if role else "job"
    base = f"{today}_{company_slug}_{role_slug}.pdf"
    if report:
        base = f"{int(report):03d}-{base}"
    return base


def main(argv):
    if "--pipeline" in argv:
        if not os.path.exists(PIPELINE_PATH):
            print(f"{PIPELINE_PATH} not found. Add URLs there first.", file=sys.stderr)
            sys.exit(1)
        print("(--pipeline mode: full URL-list processing not implemented — see spec §1)")
        sys.exit(0)

    positional = [a for a in argv if not a.startswith("--")]
    if not positional:
        print("Usage: python archive_posting.py <url> [--company=X] [--role=Y] "
              "[--report=N] [--dry-run]", file=sys.stderr)
        sys.exit(1)
    url = positional[0]

    company = get_flag(argv, "company")
    role = get_flag(argv, "role")
    report = get_flag(argv, "report")
    dry_run = "--dry-run" in argv

    filename = build_filename(company, role, report)

    if not dry_run:
        print("Live fetch/render not implemented in this port — use --dry-run.",
              file=sys.stderr)
        sys.exit(1)

    print("🔍  Dry-run mode — no files will be saved.")
    print()
    print("Archiving 1 posting(s) to jds/")
    print()
    print(f"🔗  {url}")
    print(f"   Company: {company or 'unknown'}")
    print(f"   Role:    {role or 'job'}")
    print(f"   Output:  {JDS_DIR}/{filename}")
    print("   (dry-run — not saved)")
    print()
    print("─" * 64)
    print(f"  Dry-run: 1 file(s) would be saved to {JDS_DIR}/")
    print()
    print("  References (paste into pipeline.md or a report header):")
    print(f"    local:{JDS_DIR}/{filename}")
    print("─" * 64)
    print()
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
