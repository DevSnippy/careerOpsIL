#!/usr/bin/env python3
"""set_status: canonical write path for a tracker row's status/notes.

See canonical_states.py for a note on the alias table's (intentional) coverage.
"""
import json
import os
import re
import sys
from datetime import date

from applications_table import parse_report_cell, read_table_rows, render_table
from canonical_states import CANONICAL_STATES, CANONICAL_LOOKUP, ALIASES

MD_PATH = os.path.join("data", "applications.md")
STATUS_LOG_PATH = os.path.join("data", "status-log.tsv")
SOURCE_TAG = "set-status"

VALUED_FLAGS = {"row", "report", "role", "note", "on"}
BOOL_FLAGS = {"force", "dry-run", "json"}

USAGE = (
    'Usage: python set_status.py <report#|company> <state> [--note "..."] '
    '[--role "..."] [--on YYYY-MM-DD] [--force] [--dry-run] [--json]\n'
    "       python set_status.py --row N <state> [...]        "
    "(explicit tracker row ID)\n"
    "       python set_status.py --report N <state> [...]     "
    "(explicit report ID)\n\n"
    "  <report#|company>  Row selector: tracker # (exact) or company name (normalized match)\n"
    "  <state>            Canonical state from templates/states.yml (aliases accepted)\n"
    "  --row N            Select by tracker # explicitly (unambiguous; skips the mismatch guard)\n"
    "  --report N         Select the row whose Report cell links report #N\n"
    '  --note "..."       Append to the Notes cell ("; "-separated, idempotent)\n'
    '  --role "..."       Disambiguate when several rows share the company (fuzzy match)\n'
    "  --on YYYY-MM-DD    Real event date for the status-log entry (defaults to today —\n"
    "                     pass it when the transition happened earlier than it's recorded)\n"
    "  --force            Allow a numeric selector despite a report-link mismatch, or despite a\n"
    "                     report-less row whose number another row claims as its report link\n"
    "  --dry-run          Resolve and validate, but write nothing\n"
    "  --json             Machine-readable output on stdout (errors included)\n\n"
    "  Tracker row IDs and report IDs are separate counters that diverge permanently\n"
    "  once any row exists without a report. Prefer --row/--report (or the company\n"
    "  name) over a bare number, and prefer any of them over --force."
)


def die_usage():
    print(USAGE, file=sys.stderr)
    sys.exit(1)


def normalize(text):
    return re.sub(r"\s+", " ", text.strip()).lower()


def fail(reason, code, json_mode, candidates=None, exit_code=1):
    print(f"❌ {reason}", file=sys.stderr)
    if json_mode:
        payload = {"error": reason, "code": code}
        if candidates is not None:
            payload["candidates"] = candidates
        print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    sys.exit(exit_code)


def parse_args(argv):
    flags = {}
    positional = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("--"):
            name = tok[2:]
            if name in VALUED_FLAGS:
                if i + 1 >= len(argv):
                    die_usage()
                flags[name] = argv[i + 1]
                i += 1
            elif name in BOOL_FLAGS:
                flags[name] = True
            else:
                print(f"❌ Unknown flag: {tok}", file=sys.stderr)
                die_usage()
        else:
            positional.append(tok)
        i += 1
    return flags, positional


def load_rows():
    if not os.path.exists(MD_PATH):
        return []
    return read_table_rows(open(MD_PATH, encoding="utf-8").read())


def resolve_state(raw_state, json_mode):
    key = raw_state.strip().lower()
    if key in CANONICAL_LOOKUP:
        return CANONICAL_LOOKUP[key]
    if key in ALIASES:
        return ALIASES[key]
    valid = " · ".join(CANONICAL_STATES)
    fail(f'"{raw_state}" is not a canonical state. Valid states: {valid}', "invalid-state", json_mode)


def resolve_row(flags, positional, rows, json_mode):
    if "row" in flags and "report" in flags:
        print(
            "❌ --row and --report are mutually exclusive — "
            "they name different number spaces\n",
            file=sys.stderr,
        )
        die_usage()

    if "row" in flags:
        n = int(flags["row"])
        for r in rows:
            if int(r["id"]) == n:
                return r
        fail(f"No tracker row with #{n}", "not-found", json_mode, exit_code=2)

    if "report" in flags:
        n = flags["report"]
        for r in rows:
            report_num, _ = parse_report_cell(r["report"])
            if report_num is not None and int(report_num) == int(n):
                return r
        fail(f"No tracker row with report #{n}", "not-found", json_mode, exit_code=2)

    if not positional:
        die_usage()
    selector = positional[0]

    if selector.lstrip("-").isdigit():
        n = int(selector)
        match = next((r for r in rows if int(r["id"]) == n), None)
        if match is None:
            fail(f"No tracker row with #{n}", "not-found", json_mode, exit_code=2)
        report_num, _ = parse_report_cell(match["report"])
        mismatch = False
        claimed_by_other = None
        if report_num is not None and int(report_num) != n:
            mismatch = True
            claimed = report_num
        else:
            for r in rows:
                if r is match:
                    continue
                other_report_num, _ = parse_report_cell(r["report"])
                if other_report_num is not None and int(other_report_num) == n and report_num is None:
                    mismatch = True
                    claimed = other_report_num
                    break
        if mismatch and "force" not in flags:
            fail(
                f"Tracker #{n} points to report ID(s) #{claimed}. Say which you meant: "
                f"--row {n} (tracker row) or --report {claimed} (report ID). "
                f"The company selector also works; --force overrides the check instead of answering it.",
                "report-number-mismatch",
                json_mode,
                exit_code=3,
            )
        return match

    matches = [r for r in rows if normalize(r["company"]) == normalize(selector)]
    if "role" in flags:
        matches = [r for r in matches if normalize(r["role"]) == normalize(flags["role"])]

    if not matches:
        fail(f'No tracker row with company matching "{selector}"', "not-found", json_mode, exit_code=2)
    if len(matches) > 1:
        candidate_lines = "\n".join(f"#{r['id']}\t{r['company']}\t{r['role']}" for r in matches)
        candidates = [{"num": int(r["id"]), "company": r["company"], "role": r["role"]} for r in matches]
        fail(
            f'Company "{selector}" matches {len(matches)} rows — pass the # or narrow with --role:\n'
            f"{candidate_lines}",
            "ambiguous",
            json_mode,
            candidates=candidates,
            exit_code=3,
        )
    return matches[0]


def apply_status_change(rows, row, new_status, note_text=None, on_date=None, dry_run=False):
    """Applies (or, if dry_run, previews) a status/note change to `row`.

    Shared by set_status.main() and outcome.py — same JSON shape, same
    idempotency rules. Writes MD_PATH and appends to STATUS_LOG_PATH on a
    real, changed run. Returns a dict with the same keys as the CLI's JSON
    success output, plus a "message" key holding the human-readable
    confirmation line.
    """
    old_status = row["status"]
    existing_notes = [n.strip() for n in row["notes"].split(";") if n.strip()] if row["notes"] else []
    note_is_new = bool(note_text) and note_text not in existing_notes
    status_changing = old_status != new_status
    changed = status_changing or note_is_new
    verb = "would set" if dry_run else "set"

    if not changed:
        msg = f"✅ #{row['id']} {row['company']} — {row['role']}: already {old_status} → {old_status}"
        if note_text:
            msg += f" (note: {note_text})"
        return {
            "changed": False, "num": int(row["id"]), "company": row["company"],
            "role": row["role"], "oldStatus": old_status, "newStatus": old_status,
            "tracker": os.path.abspath(MD_PATH), "message": msg,
        }

    msg = f"✅ #{row['id']} {row['company']} — {row['role']}: {verb} {old_status} → {new_status}"
    if note_is_new:
        msg += f" (note: {note_text})"

    if dry_run:
        return {
            "changed": True, "num": int(row["id"]), "company": row["company"],
            "role": row["role"], "oldStatus": old_status, "newStatus": new_status,
            "dryRun": True, "tracker": os.path.abspath(MD_PATH), "message": msg,
        }

    row["status"] = new_status
    if note_is_new:
        row["notes"] = "; ".join(existing_notes + [note_text])

    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write(render_table(rows))

    status_logged = False
    if status_changing:
        log_date = on_date or date.today().isoformat()
        os.makedirs(os.path.dirname(STATUS_LOG_PATH), exist_ok=True)
        with open(STATUS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{row['id']}\t{log_date}\t{old_status}\t{new_status}\t{SOURCE_TAG}\t{note_text or ''}\n")
        status_logged = True

    result = {
        "changed": True, "num": int(row["id"]), "company": row["company"],
        "role": row["role"], "oldStatus": old_status, "newStatus": new_status,
        "tracker": os.path.abspath(MD_PATH), "message": msg,
    }
    if status_logged:
        result["statusLogged"] = True
    return result


def main(argv):
    flags, positional = parse_args(argv)
    json_mode = "json" in flags

    explicit_selector = "row" in flags or "report" in flags
    min_positional = 1 if explicit_selector else 2
    if len(positional) < min_positional:
        die_usage()
    state_positional = positional[0] if explicit_selector else positional[1]

    rows = load_rows()
    row = resolve_row(flags, positional, rows, json_mode)
    new_status = resolve_state(state_positional, json_mode)

    result = apply_status_change(
        rows, row, new_status,
        note_text=flags.get("note"), on_date=flags.get("on"), dry_run="dry-run" in flags,
    )
    print(result.pop("message"))
    if json_mode:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
