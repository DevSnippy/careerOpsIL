"""Shared parsing/rendering for the data/applications.md tracker table.

Used by both tracker.py and find.py (spec: tracker-cli.md, find-cli.md).
"""
import re

HEADER_LINE = "| # | Date | Company | Role | Score | Status | PDF | Report | Notes |"
SEP_LINE = "|---|------|---------|------|-------|--------|-----|--------|-------|"
VIA_HEADER_LINE = "| # | Date | Company | Via | Role | Score | Status | PDF | Report | Notes |"
VIA_SEP_LINE = "|---|------|---------|-----|------|-------|--------|-----|--------|-------|"
TITLE_LINE = "# Applications Tracker"
COLUMNS = ["id", "date", "company", "role", "score", "status", "pdf", "report", "notes"]
VIA_COLUMNS = ["id", "date", "company", "via", "role", "score", "status", "pdf", "report", "notes"]


def split_row(line):
    parts = line.split("|")
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def read_table_rows(text):
    lines = text.splitlines()
    rows = []
    in_table = False
    columns = COLUMNS
    for line in lines:
        stripped = line.strip()
        if stripped == HEADER_LINE:
            in_table = True
            columns = COLUMNS
            continue
        if stripped == VIA_HEADER_LINE:
            in_table = True
            columns = VIA_COLUMNS
            continue
        if in_table and re.match(r"^\|[-:| ]+\|$", stripped):
            continue
        if in_table:
            if not stripped.startswith("|"):
                break
            cells = split_row(stripped)
            if len(cells) != len(columns):
                continue
            rows.append(dict(zip(columns, cells)))
    return rows


def has_via_column(text):
    return VIA_HEADER_LINE in text.splitlines()


def render_table(rows, with_via=None):
    """with_via=None auto-detects from the rows themselves (present if any
    row dict carries a "via" key, e.g. because it round-tripped through
    read_table_rows from a tracker that already has the column) — so tools
    that don't know about Via still preserve it rather than silently
    dropping it on rewrite."""
    if with_via is None:
        with_via = any("via" in r for r in rows)
    if with_via:
        out = [TITLE_LINE, "", VIA_HEADER_LINE, VIA_SEP_LINE]
        columns = VIA_COLUMNS
    else:
        out = [TITLE_LINE, "", HEADER_LINE, SEP_LINE]
        columns = COLUMNS
    for r in rows:
        out.append("| " + " | ".join(r.get(c, "") for c in columns) + " |")
    return "\n".join(out) + "\n"


REPORT_LINK_RE = re.compile(r"^\[(\d+)\]\(([^)]+)\)$")


def parse_report_cell(cell):
    """Returns (report_num_str_or_None, report_path_or_None)."""
    cell = cell.strip()
    m = REPORT_LINK_RE.match(cell)
    if m:
        return m.group(1), m.group(2)
    return None, None
