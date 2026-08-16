#!/usr/bin/env python3
"""tracker: query/maintain the job-application tracker.
"""
import json
import os
import shutil
import sqlite3
import sys
from datetime import date

from applications_table import (
    COLUMNS, HEADER_LINE, SEP_LINE, read_table_rows, render_table,
)

MD_PATH = os.path.join("data", "applications.md")
DB_PATH = os.path.join("data", "applications.db")

CANONICAL_STATUSES = {
    "evaluated", "applied", "responded", "interview",
    "offer", "hired", "rejected", "discarded", "skip",
}
DEFAULT_STATUS_LABEL = "Evaluated"

USAGE = "Usage: python tracker.py <sync|query|history|export|delete> [flags]"


def die_usage():
    print(USAGE, file=sys.stderr)
    sys.exit(1)


def parse_flags(argv, valued):
    """Parse `--flag value` / `--flag` style args. `valued` = set of flags that take a value."""
    flags = {}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("--"):
            name = tok[2:]
            if name in valued:
                if i + 1 >= len(argv):
                    flags[name] = None
                else:
                    flags[name] = argv[i + 1]
                    i += 1
            else:
                flags[name] = True
        i += 1
    return flags


def normalize_rows(raw_rows):
    """Assign clean int ids, flag non-canonical statuses / dup-missing ids.
    Returns (normalized_rows, corruption_counts)."""
    seen_ids = set()
    bad_status_count = 0
    bad_id_count = 0
    max_seen_id = 0
    normalized = []

    for raw in raw_rows:
        row = dict(raw)
        raw_id = raw["id"].strip()
        try:
            rid = int(raw_id)
        except ValueError:
            rid = None
        if rid is None or rid in seen_ids:
            bad_id_count += 1
            rid = max_seen_id + 1
        seen_ids.add(rid)
        max_seen_id = max(max_seen_id, rid)
        row["id"] = rid

        status = raw["status"].strip()
        if status.lower() not in CANONICAL_STATUSES:
            bad_status_count += 1
            note = row["notes"]
            suffix = f'[sync: original status "{status}"]'
            row["notes"] = f"{note} {suffix}" if note else suffix
            row["status"] = DEFAULT_STATUS_LABEL
        else:
            row["status"] = status

        normalized.append(row)

    normalized.sort(key=lambda r: r["id"])
    return normalized, bad_status_count, bad_id_count


def corruption_report_lines(bad_status_count, bad_id_count):
    lines = []
    if bad_status_count or bad_id_count:
        lines.append(
            "Corruption detected in data/applications.md "
            "(normalized in the index only — the markdown is untouched):"
        )
        if bad_status_count:
            lines.append(
                f"  {bad_status_count} non-canonical status(es), "
                f"indexed as {DEFAULT_STATUS_LABEL} (original kept in notes)"
            )
        if bad_id_count:
            lines.append(f"  {bad_id_count} missing/duplicate id(s), reassigned in the index")
    return lines


def db_connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS applications ("
        "id INTEGER PRIMARY KEY, date TEXT, company TEXT, role TEXT, score TEXT, "
        "status TEXT, pdf TEXT, report TEXT, notes TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS status_events (id INTEGER, date TEXT, status TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    return conn


def build_index(rows):
    conn = db_connect()
    conn.execute("DELETE FROM applications")
    for r in rows:
        conn.execute(
            "INSERT INTO applications (id, date, company, role, score, status, pdf, report, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (r["id"], r["date"], r["company"], r["role"], r["score"], r["status"],
             r["pdf"], r["report"], r["notes"]),
        )
        last = conn.execute(
            "SELECT status FROM status_events WHERE id = ? ORDER BY rowid DESC LIMIT 1",
            (r["id"],),
        ).fetchone()
        if last is None:
            conn.execute(
                "INSERT INTO status_events (id, date, status) VALUES (?, ?, ?)",
                (r["id"], r["date"], r["status"]),
            )
        elif last[0] != r["status"]:
            conn.execute(
                "INSERT INTO status_events (id, date, status) VALUES (?, ?, ?)",
                (r["id"], date.today().isoformat(), r["status"]),
            )
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('synced_mtime', ?)",
        (str(os.path.getmtime(MD_PATH)),),
    )
    conn.commit()
    conn.close()


def is_stale():
    if not os.path.exists(DB_PATH):
        return True
    conn = db_connect()
    row = conn.execute("SELECT value FROM meta WHERE key = 'synced_mtime'").fetchone()
    conn.close()
    if row is None:
        return True
    return float(row[0]) != os.path.getmtime(MD_PATH)


def require_md():
    if not os.path.exists(MD_PATH):
        print("Error: data/applications.md not found — nothing to index.", file=sys.stderr)
        sys.exit(1)


def ensure_synced():
    require_md()
    if is_stale():
        raw = read_table_rows(open(MD_PATH, encoding="utf-8").read())
        rows, _, _ = normalize_rows(raw)
        build_index(rows)


def cmd_sync(args):
    flags = parse_flags(args, valued=set())
    check = "check" in flags
    require_md()
    raw = read_table_rows(open(MD_PATH, encoding="utf-8").read())
    rows, bad_status, bad_id = normalize_rows(raw)
    corruption = corruption_report_lines(bad_status, bad_id)

    if check:
        print(f"Parsed {len(raw)} data rows from data/applications.md")
        if corruption:
            for line in corruption:
                print(line)
            print("(--check — no index written)")
            sys.exit(1)
        else:
            print("No corruption detected — index matches the markdown cleanly.")
            sys.exit(0)

    build_index(rows)
    print(f"Indexed {len(rows)} applications from data/applications.md into data/applications.db")
    if corruption:
        for line in corruption:
            print(line)
    else:
        print("No corruption detected — index matches the markdown cleanly.")
    sys.exit(0)


def cmd_query(args):
    flags = parse_flags(args, valued={"status", "company", "since"})
    ensure_synced()
    conn = db_connect()
    rows = [dict(zip(COLUMNS, r)) for r in conn.execute(
        "SELECT id, date, company, role, score, status, pdf, report, notes "
        "FROM applications ORDER BY id DESC"
    ).fetchall()]
    conn.close()

    if "status" in flags and flags["status"]:
        rows = [r for r in rows if r["status"] == flags["status"]]
    if "company" in flags and flags["company"]:
        needle = flags["company"].lower()
        rows = [r for r in rows if needle in r["company"].lower()]
    if "since" in flags and flags["since"]:
        rows = [r for r in rows if r["date"] >= flags["since"]]

    rows = [{**r, "id": str(r["id"])} for r in rows]

    if "json" in flags:
        out = [{**r, "id": int(r["id"])} for r in rows]
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(HEADER_LINE)
        print(SEP_LINE)
        for r in rows:
            print("| " + " | ".join(r[c] for c in COLUMNS) + " |")
        print()
        print(f"{len(rows)} row(s)")
    sys.exit(0)


def cmd_history(args):
    flags = parse_flags(args, valued={"id"})
    if "id" not in flags or flags["id"] is None:
        print("Error: history requires --id N", file=sys.stderr)
        sys.exit(1)
    target_id = int(flags["id"])
    ensure_synced()
    conn = db_connect()
    app = conn.execute(
        "SELECT company, role FROM applications WHERE id = ?", (target_id,)
    ).fetchone()
    if app is None:
        conn.close()
        print(f"Error: no application with id {target_id}", file=sys.stderr)
        sys.exit(1)
    events = conn.execute(
        "SELECT date, status FROM status_events WHERE id = ? ORDER BY rowid ASC", (target_id,)
    ).fetchall()
    conn.close()
    print(f"#{target_id} {app[0]} — {app[1]}")
    for ev_date, ev_status in events:
        print(f"  {ev_date}  {ev_status}")
    sys.exit(0)


def cmd_export(args):
    flags = parse_flags(args, valued={"out"})
    ensure_synced()
    conn = db_connect()
    rows = [dict(zip(COLUMNS, r)) for r in conn.execute(
        "SELECT id, date, company, role, score, status, pdf, report, notes "
        "FROM applications ORDER BY id ASC"
    ).fetchall()]
    conn.close()
    rows = [{**r, "id": str(r["id"])} for r in rows]
    text = render_table(rows)

    out_path = flags.get("out")
    if out_path:
        if os.path.exists(out_path):
            shutil.copyfile(out_path, out_path + ".bak")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Exported {len(rows)} applications to {out_path}")
    else:
        sys.stdout.write(text)
    sys.exit(0)


def cmd_delete(args):
    flags = parse_flags(args, valued={"num"})
    if "num" not in flags or flags["num"] is None:
        print("Usage: python tracker.py delete --num <N> [--dry-run]   "
              "(remove one application row by its number)", file=sys.stderr)
        sys.exit(1)
    num = int(flags["num"])
    dry_run = "dry-run" in flags

    require_md()
    text = open(MD_PATH, encoding="utf-8").read()
    raw = read_table_rows(text)
    match = next((r for r in raw if r["id"].strip() == str(num)), None)
    if match is None:
        print(f"No application numbered {num} in data/applications.md.")
        sys.exit(1)

    report = match["report"]
    if dry_run:
        print(f"Would remove application {num} (1 row) from data/applications.md.")
        if report:
            print(f"(report file would be orphaned: {report})")
        sys.exit(0)

    remaining = [r for r in raw if r is not match]
    remaining = [{**r, "id": r["id"].strip()} for r in remaining]
    new_text = render_table(remaining)
    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write(new_text)

    rows, _, _ = normalize_rows(remaining)
    build_index(rows)

    print(f"Removed application {num} (1 row) from data/applications.md and reindexed.")
    if report:
        print(f"Note: report file may now be orphaned — {report}")
    sys.exit(0)


SUBCOMMANDS = {
    "sync": cmd_sync,
    "query": cmd_query,
    "history": cmd_history,
    "export": cmd_export,
    "delete": cmd_delete,
}


def main(argv):
    if not argv or argv[0] not in SUBCOMMANDS:
        die_usage()
    SUBCOMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
