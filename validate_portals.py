#!/usr/bin/env python3
"""validate_portals: lint portals.yml for syntax and schema issues.
"""
import os
import sys

import yaml

PORTALS_PATH = "portals.yml"


def main(argv):
    abs_path = os.path.abspath(PORTALS_PATH)
    if not os.path.exists(PORTALS_PATH):
        print(f"validate-portals failed: file not found: {abs_path}", file=sys.stderr)
        sys.exit(1)

    print(f"validate-portals: {abs_path}")

    try:
        with open(PORTALS_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"validate-portals failed: {e}", file=sys.stderr)
        sys.exit(1)

    errors = []
    warnings = []

    companies = (data or {}).get("tracked_companies") or []
    seen_names = {}
    for i, company in enumerate(companies):
        name = company.get("name") if isinstance(company, dict) else None
        if name and name in seen_names:
            warnings.append(
                f"tracked_companies[{i}].name: duplicate enabled company name "
                f"also seen at tracked_companies[{seen_names[name]}].name"
            )
        elif name:
            seen_names[name] = i

    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")

    print(f"{len(errors)} errors, {len(warnings)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
