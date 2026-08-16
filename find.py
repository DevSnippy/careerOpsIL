#!/usr/bin/env python3
"""find: resolve a report#/tracker#/company/role fragment to its full record.
Strictly read-only.
"""
import json
import os
import sys

from applications_table import parse_report_cell, read_table_rows

MD_PATH = os.path.join("data", "applications.md")
PDF_INDEX_PATH = os.path.join("data", "pdf-index.tsv")

VALID_FLAGS = {"--json", "--help", "-h"}

USAGE = (
    "Usage:\n"
    "  python find.py <report# | tracker# | company/role fragment> [--json]\n"
    "  python find.py --help                            "
    "# print this usage block and exit"
)

TABLE_COLUMNS = ["Tracker#", "Report#", "Company", "Role", "Status", "PDF", "Report"]


def load_pdf_index():
    index = {}
    if os.path.exists(PDF_INDEX_PATH):
        with open(PDF_INDEX_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    index[parts[0].strip()] = parts[1].strip()
    return index


def load_records():
    if not os.path.exists(MD_PATH):
        return []
    raw = read_table_rows(open(MD_PATH, encoding="utf-8").read())
    pdf_index = load_pdf_index()
    records = []
    for r in raw:
        report_num, report_path = parse_report_cell(r["report"])
        records.append({
            "trackerNum": int(r["id"]) if r["id"].strip().lstrip("-").isdigit() else r["id"],
            "date": r["date"],
            "company": r["company"],
            "role": r["role"],
            "score": r["score"],
            "status": r["status"],
            "reportNum": report_num,
            "reportPath": report_path,
            "pdfPath": pdf_index.get(report_num) if report_num else None,
        })
    return records


def role_words(text):
    return [w.lower() for w in text.split() if w]


def fuzzy_role_match(query_tokens, role_tokens):
    qset, rset = set(query_tokens), set(role_tokens)
    if qset == rset:
        return True
    if len(query_tokens) <= len(role_tokens):
        sorted_role_prefix = sorted(role_tokens)[: len(query_tokens)]
        if sorted(query_tokens) == sorted_role_prefix:
            return True
    else:
        if rset <= qset:
            return True
    return False


def matches(record, query):
    query = query.strip()
    if query.lstrip("-").isdigit():
        n = int(query)
        return record["trackerNum"] == n or (
            record["reportNum"] is not None and int(record["reportNum"]) == n
        )
    q_lower = query.lower()
    if q_lower in record["company"].lower() or q_lower in record["role"].lower():
        return True
    q_tokens = role_words(query)
    if len(q_tokens) >= 2:
        return fuzzy_role_match(q_tokens, role_words(record["role"]))
    return False


def render_table_output(records):
    rows = [TABLE_COLUMNS]
    for r in records:
        rows.append([
            str(r["trackerNum"]),
            r["reportNum"] or "—",
            r["company"],
            r["role"],
            r["status"],
            r["pdfPath"] or "—",
            r["reportPath"] or "—",
        ])
    widths = [max(len(row[i]) for row in rows) for i in range(len(TABLE_COLUMNS))]

    def fmt_row(cells):
        parts = []
        for i, cell in enumerate(cells):
            if i == len(cells) - 1:
                parts.append(cell)
            else:
                parts.append(cell.ljust(widths[i]))
        return "  ".join(parts)

    lines = [fmt_row(rows[0]), fmt_row(["-" * w for w in widths])]
    for row in rows[1:]:
        lines.append(fmt_row(row))
    return "\n".join(lines)


def main(argv):
    flags = set()
    positional = []
    unrecognized = []
    for tok in argv:
        if tok.startswith("-"):
            if tok in VALID_FLAGS:
                flags.add(tok)
            else:
                unrecognized.append(tok)
        else:
            positional.append(tok)

    if "--help" in flags or "-h" in flags:
        print(USAGE)
        sys.exit(0)

    if unrecognized:
        print(
            f"Error: unrecognized flag(s): {', '.join(unrecognized)}. "
            f"Valid flags: --json, --help, -h",
            file=sys.stderr,
        )
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    if not positional:
        print(USAGE)
        sys.exit(1)

    query = " ".join(positional)
    records = load_records()
    found = [r for r in records if matches(r, query)]

    json_out = "--json" in flags
    if not found:
        if json_out:
            print("[]")
        else:
            print(f'No application matches "{query}" — try a report #, tracker #, or company fragment.')
        sys.exit(1)

    if json_out:
        print(json.dumps(found, indent=2, ensure_ascii=False))
    else:
        print(render_table_output(found))
        print()
        print(f"{len(found)} match(es)")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
