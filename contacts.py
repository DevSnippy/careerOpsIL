#!/usr/bin/env python3
"""contacts: job-search phonebook / vCard exporter.

UID_PREFIX/CATEGORY_TAG are the branding constants for generated vCards —
change them here to rebrand.
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

CONTACTS_PATH = os.path.join("data", "contacts.tsv")
DEFAULT_VCF_PATH = os.path.join("output", "contacts.vcf")

UID_PREFIX = "contact"
CATEGORY_TAG = "job-search"

VALID_TYPES = {"recruiter", "hiring-manager", "peer", "interviewer", "other"}
FIELDS = ["name", "company", "type", "title", "phone", "email", "linkedin", "tracker", "notes"]


def slug(value):
    s = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return s


def uid_part(value):
    h = hashlib.sha1(value.lower().encode()).hexdigest()[:8]
    s = slug(value)
    return f"{s}-{h}" if s else h


def load_contacts():
    contacts = []
    quality = {"shortRows": [], "missingRequired": [], "invalidTypes": [], "duplicates": []}
    if not os.path.exists(CONTACTS_PATH):
        return contacts, quality

    seen_uids = {}
    with open(CONTACTS_PATH, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            stripped = line.rstrip("\n")
            if not stripped.strip() or stripped.lstrip().startswith("#"):
                continue
            cells = stripped.split("\t")
            if len(cells) < 4:
                quality["shortRows"].append({"line": lineno, "cells": len(cells)})
                continue
            cells = cells + [""] * (9 - len(cells))
            row = dict(zip(FIELDS, cells[:9]))

            if not row["name"].strip() or not row["company"].strip():
                quality["missingRequired"].append({"line": lineno, "name": row["name"]})
                continue

            if row["type"].strip() and row["type"].strip() not in VALID_TYPES:
                quality["invalidTypes"].append(
                    {"line": lineno, "name": row["name"], "type": row["type"]})

            row["tracker"] = None if row["tracker"].strip() in ("", "-") else row["tracker"].strip()

            uid = f"{UID_PREFIX}-{uid_part(row['name'])}--{uid_part(row['company'])}"
            if uid in seen_uids:
                quality["duplicates"].append(
                    {"uid": uid, "name": row["name"], "company": row["company"], "line": lineno})
            seen_uids[uid] = row

            contacts.append(row)

    return contacts, quality


def build_note(contact):
    parts = []
    if contact["type"].strip():
        parts.append(contact["type"].strip())
    if contact["tracker"]:
        parts.append(f"tracker #{contact['tracker']}")
    if contact["notes"].strip():
        parts.append(contact["notes"].strip())
    return " — ".join(parts)


def vcard_for(contact, caller_id):
    name = contact["name"]
    if caller_id and contact["type"].strip():
        fn = f"{name} ({contact['company']} {contact['type']})"
    else:
        fn = name
    space = name.find(" ")
    first, last = (name, "") if space == -1 else (name[:space], name[space + 1:])

    lines = [
        "BEGIN:VCARD", "VERSION:3.0",
        f"UID:{UID_PREFIX}-{uid_part(contact['name'])}--{uid_part(contact['company'])}",
        f"FN:{fn}", f"N:{last};{first};;;", f"ORG:{contact['company']}",
    ]
    if contact["title"].strip():
        lines.append(f"TITLE:{contact['title']}")
    if contact["phone"].strip():
        lines.append(f"TEL;TYPE=CELL:{contact['phone']}")
    if contact["email"].strip():
        lines.append(f"EMAIL;TYPE=INTERNET:{contact['email']}")
    if contact["linkedin"].strip():
        lines.append(f"URL:{contact['linkedin']}")
    note = build_note(contact)
    if note:
        lines.append(f"NOTE:{note}")
    lines.append(f"CATEGORIES:{CATEGORY_TAG}")
    rev = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
    lines.append(f"REV:{rev}")
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


def print_quality_warning(quality):
    total_issues = sum(len(v) for v in quality.values())
    if total_issues == 0:
        return
    print(f"⚠ {total_issues} data-quality issue(s) in {CONTACTS_PATH} (details: "
          f"python contacts.py --summary):")
    if quality["shortRows"]:
        print(f"    {len(quality['shortRows'])} row(s) with too few columns")
    if quality["missingRequired"]:
        print(f"    {len(quality['missingRequired'])} row(s) missing name/company")
    if quality["invalidTypes"]:
        print(f"    {len(quality['invalidTypes'])} contact with off-enum type (kept)")
    if quality["duplicates"]:
        print(f"    {len(quality['duplicates'])} duplicate UID(s)")


def main(argv):
    contacts, quality = load_contacts()

    if "--vcf" in argv:
        idx = argv.index("--vcf")
        path = argv[idx + 1] if idx + 1 < len(argv) and not argv[idx + 1].startswith("--") else DEFAULT_VCF_PATH
        caller_id = "--caller-id" in argv

        abs_path = os.path.abspath(path)
        if not abs_path.startswith(os.getcwd()):
            print(f"Refusing to write the vCard outside the project directory: {path}",
                  file=sys.stderr)
            sys.exit(1)

        print_quality_warning(quality)
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        with open(abs_path, "w", encoding="utf-8", newline="") as f:
            for c in contacts:
                f.write(vcard_for(c, caller_id))
        print(f"Wrote {len(contacts)} contacts → {abs_path}")
        sys.exit(0)

    if "--summary" in argv:
        if not contacts:
            print()
            print("CONTACTS — job-search phonebook")
            print()
            print("  No contacts yet.")
            print("  Add lines to data/contacts.tsv:")
            print("  {name}\\t{company}\\t{type}\\t{title}\\t{phone}\\t{email}\\t"
                  "{linkedin}\\t{tracker#|-}\\t{notes}")
            print("  Export to your phone with: python contacts.py --vcf")
            print()
        print("  Data quality:")
        for label, key in [("short rows", "shortRows"), ("missing name/company", "missingRequired"),
                            ("off-enum types", "invalidTypes"), ("duplicates", "duplicates")]:
            n = len(quality[key])
            print(f"  {label}: {'none' if n == 0 else n}")
        print(f"  total: {len(contacts)} contacts")
        print()
        sys.exit(0)

    print(json.dumps({"contacts": contacts, "quality": quality, "total": len(contacts)},
                      indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
