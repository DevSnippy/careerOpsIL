#!/usr/bin/env python3
"""followup_seed: seed the first pinned follow-up date for a tracker row.
"""
import json
import os
import sys
from datetime import date, timedelta

FOLLOWUPS_PATH = os.path.join("data", "follow-ups.md")
APPLIED_FIRST_DAYS = 7  # matches followup_cadence.py's default

HEADER = "# Follow-ups\n\n| num | appNum | date | company | role | channel | contact | notes |\n|---|---|---|---|---|---|---|---|\n"

USAGE = "Usage: python followup_seed.py <appNum> [--date YYYY-MM-DD] [--force] [--dry-run] [--json]"


def find_existing_seed(app_num):
    if not os.path.exists(FOLLOWUPS_PATH):
        return None
    prefix = f"- next #{app_num} "
    for line in open(FOLLOWUPS_PATH, encoding="utf-8"):
        if line.startswith(prefix):
            rest = line[len(prefix):].strip()
            next_date = rest.split(" ")[0]
            return next_date
    return None


def main(argv):
    positional = [a for a in argv if not a.startswith("--")]
    if not positional:
        print(f"❌ {USAGE}", file=sys.stderr)
        sys.exit(1)
    app_num = int(positional[0])

    applied_date_str = None
    if "--date" in argv:
        applied_date_str = argv[argv.index("--date") + 1]
    applied_date = (date.fromisoformat(applied_date_str) if applied_date_str
                     else date.today())

    force = "--force" in argv
    dry_run = "--dry-run" in argv
    json_mode = "--json" in argv
    today = date.today().isoformat()

    existing = find_existing_seed(app_num)
    if existing is not None and not force:
        print(f"⏭️  #{app_num} already seeded — no-op (already-seeded)")
        if json_mode:
            print(json.dumps({
                "seeded": False, "appNum": app_num, "pin": None,
                "nextDate": existing, "appliedDate": applied_date.isoformat(),
                "setDate": today, "reason": "already-seeded",
            }))
        sys.exit(0)

    next_date = applied_date + timedelta(days=APPLIED_FIRST_DAYS)
    suffix = " [dry-run]" if dry_run else ""
    print(f"✅ Seeded #{app_num}: next follow-up {next_date.isoformat()} "
          f"(applied {applied_date.isoformat()}, set {today}){suffix}")

    if not dry_run:
        if not os.path.exists(FOLLOWUPS_PATH):
            os.makedirs(os.path.dirname(FOLLOWUPS_PATH), exist_ok=True)
            with open(FOLLOWUPS_PATH, "w", encoding="utf-8") as f:
                f.write(HEADER)
        with open(FOLLOWUPS_PATH, "a", encoding="utf-8") as f:
            f.write(f"- next #{app_num} {next_date.isoformat()} (set {today})\n")

    if json_mode:
        print(json.dumps({
            "seeded": not dry_run, "appNum": app_num, "pin": None,
            "nextDate": next_date.isoformat(), "appliedDate": applied_date.isoformat(),
            "setDate": today, "reason": None,
        }))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
