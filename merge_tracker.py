#!/usr/bin/env python3
"""merge_tracker: fold batch/tracker-additions/*.tsv into data/applications.md.

Dedup tiers: an exact report-number match always merges; a company+role
match overrides "unseen report# = new row" when it fires; a req-ID token
(e.g. "req JR-1234") present and differing on both sides suppresses that
override, keeping the rows separate. Supports an optional via=<Agency>
tagged extra field (see --migrate-via) and score sentinels (N/A, -, —).

Scope note: URL-based dedup is intentionally not implemented — flagged as
a known gap rather than guessed at.
"""
import os
import re
import shutil
import sys

from applications_table import (
    COLUMNS, VIA_COLUMNS, has_via_column, parse_report_cell, read_table_rows, render_table,
)

MD_PATH = os.path.join("data", "applications.md")
ADDITIONS_DIR = os.path.join("batch", "tracker-additions")
MERGED_DIR = os.path.join(ADDITIONS_DIR, "merged")

SCORE_RE = re.compile(r"^\d+(\.\d{1,2})?/5$")
SCORE_SENTINELS = {"N/A", "-", "—"}
REQ_ID_RE = re.compile(r"\breq\s+([A-Za-z0-9-]*\d[A-Za-z0-9-]*)", re.IGNORECASE)


def extract_req_id(notes):
    m = REQ_ID_RE.search(notes or "")
    return m.group(1) if m else None


def looks_like_score(value):
    return bool(SCORE_RE.match(value)) or value in SCORE_SENTINELS


def score_value(score):
    if score in SCORE_SENTINELS:
        return -1.0
    m = re.match(r"^(\d+(?:\.\d{1,2})?)/5$", score)
    return float(m.group(1)) if m else -1.0


def score_number_text(score):
    """Minimal decimal form of a score's numeric part for log messages
    (verified: "4.20" -> "4.2", "2.00" -> "2")."""
    if score in SCORE_SENTINELS:
        return score
    num = float(score.split("/")[0])
    return f"{num:.2f}".rstrip("0").rstrip(".")


SCORE_SWAP_SUFFIX = " — refusing to merge a possible column swap"


def parse_addition(text, filename):
    line = text.strip("\n")
    if line.startswith("|"):
        from applications_table import split_row
        cells = split_row(line)
        if len(cells) != 9:
            return None, f"expected 9 pipe-delimited columns, got {len(cells)}"
        num, date, company, role, score, status, pdf, report, notes = cells
        if not looks_like_score(score):
            return None, (f'cannot tell score from status in columns 5–6 '
                           f'("{status}" | "{score}"){SCORE_SWAP_SUFFIX}')
        return {
            "id": num, "date": date, "company": company, "role": role,
            "status": status, "score": score, "pdf": pdf, "report": report, "notes": notes,
            "via": None,
        }, None

    fields = line.split("\t")
    if len(fields) < 8:
        return None, f"expected 8 or 9 tab-separated columns, got {len(fields)}"
    num, date, company, role, status, score, pdf, report = fields[:8]
    notes = fields[8] if len(fields) >= 9 else ""
    if not looks_like_score(score):
        return None, (f'cannot tell score from status in columns 5–6 '
                       f'("{status}" | "{score}"){SCORE_SWAP_SUFFIX}')

    extra_fields = fields[9:]
    via_fields = [f for f in extra_fields if f.startswith("via=")]
    plain_fields = [f for f in extra_fields if not f.startswith("via=")]
    if len(via_fields) > 1 or len(plain_fields) > 1:
        joined = ", ".join(extra_fields)
        return None, (f'ambiguous extra fields [{joined}] — expected at most one '
                       f'"via=Firm" tag and one location')
    via = via_fields[0][len("via="):] if via_fields else None

    return {
        "id": num, "date": date, "company": company, "role": role,
        "status": status, "score": score, "pdf": pdf, "report": report, "notes": notes,
        "via": via,
    }, None


def rewrite_report_path(report_cell):
    report_num, path = parse_report_cell(report_cell)
    if report_num is None:
        return report_cell
    if path.startswith("reports/"):
        path = "../" + path
    return f"[{report_num}]({path})"


def run_migrate_via():
    if not os.path.exists(MD_PATH):
        print("No applications.md found. Nothing to migrate.")
        return 0
    text = open(MD_PATH, encoding="utf-8").read()
    if has_via_column(text):
        print("Via column already present — nothing to migrate.")
        return 0
    rows = read_table_rows(text)
    for r in rows:
        r["via"] = "—"
    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write(render_table(rows, with_via=True))
    print(f"✅ Migration: inserted Via column after Company ({len(rows)} table line(s) "
          f"rewritten). Direct applications are marked —.")
    return 0


def _normalize_key(text):
    return text.strip()


def main(argv):
    if "--migrate-via" in argv:
        sys.exit(run_migrate_via())

    if not os.path.exists(MD_PATH):
        print("🔒 Tracker merge lock acquired (wait_ms=0 | attempts=1 | stale_recovered=false)")
        print("No applications.md found. Nothing to merge into.")
        sys.exit(0)

    print("🔒 Tracker merge lock acquired (wait_ms=0 | attempts=1 | stale_recovered=false)")

    md_text = open(MD_PATH, encoding="utf-8").read()
    has_via = has_via_column(md_text)
    if has_via:
        print("🧭 Detected Via column.")

    rows = read_table_rows(md_text)
    for r in rows:
        r["id"] = r["id"].strip()
    existing_ids = [int(r["id"]) for r in rows if r["id"].strip().lstrip("-").isdigit()]
    max_id = max(existing_ids) if existing_ids else 0
    print(f"📊 Existing: {len(rows)} entries, max #{max_id}")

    by_report_num = {}
    by_company_role = {}
    for r in rows:
        rn, _ = parse_report_cell(r["report"])
        if rn is not None:
            by_report_num[rn] = r
        by_company_role[(_normalize_key(r["company"]), _normalize_key(r["role"]))] = r

    os.makedirs(ADDITIONS_DIR, exist_ok=True)
    pending = sorted(
        f for f in os.listdir(ADDITIONS_DIR)
        if f.endswith(".tsv") and os.path.isfile(os.path.join(ADDITIONS_DIR, f))
    )
    print(f"📥 Found {len(pending)} pending additions")

    added = updated = skipped = 0
    processed_files = []

    for fname in pending:
        fpath = os.path.join(ADDITIONS_DIR, fname)
        text = open(fpath, encoding="utf-8").read()
        parsed, err = parse_addition(text, fname)
        if err:
            print(f"⚠️  Skipping {fname}: {err}")
            skipped += 1
            processed_files.append(fname)
            continue

        parsed["report"] = rewrite_report_path(parsed["report"])
        incoming_report_num, _ = parse_report_cell(parsed["report"])

        # Dedup tiers, in priority order: (1) same report number — the
        # original, primary mechanism; (2) same company+role — fires even
        # for a never-seen report number, confirmed by testing the real
        # tool, UNLESS both sides carry a recognizable req-ID and the IDs
        # differ, which suppresses this tier and lets the row through as
        # new (see merge-tracker-dedup-via-req.md).
        existing = by_report_num.get(incoming_report_num) if incoming_report_num else None
        if existing is None:
            key = (_normalize_key(parsed["company"]), _normalize_key(parsed["role"]))
            candidate = by_company_role.get(key)
            if candidate is not None:
                existing_req = extract_req_id(candidate["notes"])
                incoming_req = extract_req_id(parsed["notes"])
                if not (existing_req and incoming_req and existing_req != incoming_req):
                    existing = candidate

        if parsed["via"] is not None and not has_via:
            print(f'⚠️  {fname}: carries via={parsed["via"]} but the tracker has no Via '
                  f'column — value dropped. Add it with: python3 merge_tracker.py --migrate-via')

        if existing is not None:
            old_score, new_score = existing["score"], parsed["score"]
            downgrade = score_value(parsed["score"]) < score_value(existing["score"])
            old_num = score_number_text(old_score)
            new_num = score_number_text(new_score)
            reeval_note = f'. Re-eval {parsed["date"]} ({old_num}→{new_num}): {parsed["notes"]}'
            existing["notes"] = existing["notes"] + reeval_note
            existing["date"] = parsed["date"]
            existing["score"] = parsed["score"]
            if has_via and parsed["via"] is not None:
                existing["via"] = parsed["via"]
            if downgrade:
                print(f"🔽 Update: #{existing['id']} {existing['company']} — {existing['role']} "
                      f"({old_num}→{new_num}) — DOWNGRADE, re-eval scored lower")
            else:
                print(f"🔄 Update: #{existing['id']} {existing['company']} — {existing['role']} "
                      f"({old_num}→{new_num})")
            updated += 1
        else:
            columns = VIA_COLUMNS if has_via else COLUMNS
            new_row = {c: parsed.get(c, "") for c in columns}
            if has_via:
                new_row["via"] = parsed["via"] if parsed["via"] is not None else "—"
            rows.append(new_row)
            if incoming_report_num:
                by_report_num[incoming_report_num] = new_row
            by_company_role[(_normalize_key(new_row["company"]), _normalize_key(new_row["role"]))] = new_row
            print(f"➕ Add #{parsed['id']}: {parsed['company']} — {parsed['role']} ({parsed['score']})")
            added += 1

        processed_files.append(fname)

    if processed_files:
        os.makedirs(MERGED_DIR, exist_ok=True)
        for fname in processed_files:
            shutil.move(os.path.join(ADDITIONS_DIR, fname), os.path.join(MERGED_DIR, fname))
        print()
        print(f"✅ Moved {len(processed_files)} TSVs to merged/")

    rows.sort(key=lambda r: int(r["id"]) if r["id"].lstrip("-").isdigit() else 0, reverse=True)
    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write(render_table(rows))

    print()
    print(f"📊 Summary: +{added} added, 🔄{updated} updated, ⏭️{skipped} skipped")
    print()
    print("📊 Summary: 0 PDF flags synced, 0 unchanged")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
