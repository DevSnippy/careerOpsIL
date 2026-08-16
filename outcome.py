#!/usr/bin/env python3
"""outcome: record an application outcome, archive artifacts, sync the tracker.
"""
import json
import os
import re
import shutil
import sys
from datetime import date

from applications_table import parse_report_cell
from jd_capture import resolve_jd_capture
from set_status import apply_status_change, load_rows, normalize

CV_DEFAULT = "cv.md"
OUTCOMES_DIR = os.path.join("data", "outcomes")

VALUED_FLAGS = {"stage", "feedback", "note", "role", "cv", "cover", "url"}
BOOL_FLAGS = {"dry-run", "json"}

# Primary types confirmed via --help; the full alias list (14 tokens) was
# captured verbatim from the tool's own invalid-type error message. Only the
# 4 mappings marked "verified" below were individually confirmed by testing;
# the rest are a reasonable best-effort grouping.
OUTCOME_TYPES = {
    "interview_progress": ("Interview", "Stage updated"),      # verified
    "stage_reached": ("Interview", "Stage updated"),
    "interview": ("Interview", "Stage updated"),
    "offer_received": ("Offer", "Offer received"),
    "offer": ("Offer", "Offer received"),
    "hired": ("Hired", "Offer accepted"),                      # verified
    "accepted": ("Hired", "Offer accepted"),
    "offer_declined": ("Discarded", "Offer declined"),
    "declined": ("Discarded", "Offer declined"),
    "rejected": ("Rejected", "Application rejected"),          # verified
    "rejection": ("Rejected", "Application rejected"),
    "no_response": ("Discarded", "No response received"),      # state verified
    "ghosted": ("Discarded", "No response received"),
    "interview_only": ("Interview", "Interview stage reached"),
}

USAGE = (
    "Usage: python outcome.py <report#|company> <outcome_type> [options]\n\n"
    "  <report#|company>  Tracker selector (# or company name)\n"
    "  <outcome_type>     " + " | ".join(OUTCOME_TYPES) + "\n"
    '  --stage "..."      Stage reached (e.g. "Tech Screen", "Final Round")\n'
    '  --feedback "..."   Verbatim candidate/recruiter feedback\n'
    '  --note "..."       Custom note to append to tracker\n'
    '  --role "..."       Disambiguate company match\n'
    '  --cv "..."         Path to submitted CV (defaults to cv.md)\n'
    '  --cover "..."      Path to submitted cover letter\n'
    '  --url "..."        Job posting URL (overrides auto-detection from tracker notes)\n'
    "  --dry-run          Preview outcome logging without writing\n"
    "  --json             Machine-readable JSON output"
)


def die_usage(code=0):
    print(USAGE)
    sys.exit(code)


def fail(reason, exit_code=1):
    print(f"❌ {reason}", file=sys.stderr)
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
                flags[name] = argv[i + 1] if i + 1 < len(argv) else ""
                i += 1
            elif name in BOOL_FLAGS:
                flags[name] = True
        else:
            positional.append(tok)
        i += 1
    return flags, positional


def resolve_row(selector, role_filter, rows):
    if selector.lstrip("-").isdigit():
        n = int(selector)
        match = next((r for r in rows if int(r["id"]) == n), None)
        if match is None:
            fail(f"No tracker row with #{n}", exit_code=2)
        return match

    matches = [r for r in rows if normalize(r["company"]) == normalize(selector)]
    if role_filter:
        matches = [r for r in matches if normalize(r["role"]) == normalize(role_filter)]

    if not matches:
        fail(f'No tracker row with company matching "{selector}"', exit_code=2)
    if len(matches) > 1:
        listing = ", ".join(f"#{r['id']}: {r['company']} ({r['role']})" for r in matches)
        fail(f'Multiple tracker rows matched "{selector}" ({listing}) — pass --role or row #',
             exit_code=3)
    return matches[0]


def slugify(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def main(argv):
    if not argv:
        die_usage(0)

    flags, positional = parse_args(argv)
    if len(positional) < 2:
        fail("Expected 2 positional arguments: <selector> <outcome_type>")
        return

    selector, outcome_type = positional[0], positional[1]
    json_mode = "json" in flags
    dry_run = "dry-run" in flags

    if outcome_type not in OUTCOME_TYPES:
        fail(f'Invalid outcome_type "{outcome_type}". Valid types: {" · ".join(OUTCOME_TYPES)}')
        return

    canonical_state, default_note = OUTCOME_TYPES[outcome_type]
    stage = flags.get("stage")
    feedback = flags.get("feedback")

    rows = load_rows()
    row = resolve_row(selector, flags.get("role"), rows)

    if flags.get("note"):
        note_text = flags["note"]
    elif stage:
        note_text = f"Stage updated: {stage}"
    else:
        note_text = default_note

    outcome_dir = os.path.join(
        OUTCOMES_DIR, f"{row['id']}_{slugify(row['company'])}_{slugify(row['role'])}"
    )

    if dry_run:
        print(f'🔍 Dry-run: would record outcome "{outcome_type}" for #{row["id"]} '
              f'{row["company"]} ({canonical_state}) in {os.path.abspath(outcome_dir)}')
        if json_mode:
            print(json.dumps({
                "dryRun": True, "num": int(row["id"]), "company": row["company"],
                "role": row["role"], "outcomeType": outcome_type,
                "canonicalState": canonical_state, "stage": stage, "feedback": feedback,
                "note": note_text, "outcomeDir": os.path.abspath(outcome_dir),
            }, indent=2, ensure_ascii=False))
        sys.exit(0)

    os.makedirs(outcome_dir, exist_ok=True)

    cv_path = flags.get("cv", CV_DEFAULT)
    if os.path.exists(cv_path):
        shutil.copyfile(cv_path, os.path.join(outcome_dir, "submitted_cv.md"))

    cover_path = flags.get("cover")
    if cover_path and os.path.exists(cover_path):
        shutil.copyfile(cover_path, os.path.join(outcome_dir, "submitted_cover.md"))

    report_num, _ = parse_report_cell(row["report"])
    posting_archived = False
    if report_num:
        capture = resolve_jd_capture(report_num)
        if capture:
            ext = os.path.splitext(capture)[1]
            shutil.copyfile(capture, os.path.join(outcome_dir, f"posting{ext}"))
            posting_archived = True

    outcome_md_path = os.path.join(outcome_dir, "outcome.md")
    entry = (
        f"## Entry: {date.today().isoformat()}\n"
        f"- **Outcome Type**: {outcome_type}\n"
        f"- **Canonical State**: {canonical_state}\n"
        f"- **Stage Reached**: {stage or 'N/A'}\n"
        f"- **Verbatim Feedback**:\n"
        f"> {feedback or 'None recorded'}\n"
        f"- **Notes**: {note_text}\n"
    )
    if os.path.exists(outcome_md_path):
        with open(outcome_md_path, "a", encoding="utf-8") as f:
            f.write("\n" + entry)
    else:
        header = f"# Application Outcome Log — {row['company']} — {row['role']} (#{row['id']})\n\n"
        with open(outcome_md_path, "w", encoding="utf-8") as f:
            f.write(header + entry)

    status_result = apply_status_change(rows, row, canonical_state, note_text=note_text)
    status_message = status_result.pop("message")

    print(f'✅ Recorded outcome "{outcome_type}" for #{row["id"]} {row["company"]} '
          f'({canonical_state}) in {os.path.abspath(outcome_dir)}')

    if json_mode:
        print(json.dumps({
            "success": True, "num": int(row["id"]), "company": row["company"],
            "role": row["role"], "outcomeType": outcome_type,
            "canonicalState": canonical_state, "stage": stage, "feedback": feedback,
            "note": note_text, "outcomeDir": os.path.abspath(outcome_dir),
            "postingArchived": posting_archived, "setStatusResult": status_result,
        }, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
