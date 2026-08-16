#!/usr/bin/env python3
"""dashboard: interactive terminal browser for the tracker, built with Textual.

Degrades gracefully at any terminal size instead of crashing — Textual's
layout engine handles this natively as long as we avoid any manual
"width - content_len" padding that could go negative.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import webbrowser
from collections import Counter
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from applications_table import parse_report_cell, read_table_rows  # noqa: E402
from canonical_states import CANONICAL_STATES  # noqa: E402
import set_status  # noqa: E402
from cv_intake import build_cv_markdown, extract_pdf_text  # noqa: E402
from llm_providers import LLMError, load_env, save_env_var  # noqa: E402
from portals_config import load_portals, save_portals  # noqa: E402
from scan import load_pending_pipeline, remove_pipeline_entry, run_scan, title_matches  # noqa: E402

from rich.markdown import Markdown  # noqa: E402
from textual import work  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.containers import Vertical, VerticalScroll  # noqa: E402
from textual.widgets import Input, Static  # noqa: E402

# Confirmed: Applied counts a row if its status is Applied or any later
# lifecycle stage; Responded/Interview/Offer likewise cumulative. Rejected
# counts toward Applied (a rejection presupposes an application existed) but
# NOT toward Responded/Interview/Offer (a rejection doesn't imply a response
# was ever received) — confirmed via spec analysis. Discarded is assumed to
# behave the same as Rejected (untested). SKIP is assumed to count toward
# neither (a skip means "never applied") — also untested; both are best-effort
# extrapolations flagged in the progress-screen spec, not confirmed facts.
LIFECYCLE_ORDER = ["Evaluated", "Applied", "Responded", "Interview", "Offer", "Hired"]
APPLIED_ONLY_STATUSES = {"Rejected", "Discarded"}
EVALUATED_ONLY_STATUSES = {"SKIP"}

SCORE_BUCKETS = [
    ("4.5-5.0", 4.5, 5.01),
    ("4.0-4.4", 4.0, 4.5),
    ("3.5-3.9", 3.5, 4.0),
    ("3.0-3.4", 3.0, 3.5),
    ("<3.0", -1.0, 3.0),
]

# Rename this to rebrand the header — the only place the app's display name lives.
APP_TITLE = "APPLICATION PIPELINE"

TABS = ["ALL", "EVALUATED", "INTERVIEW", "RESPONDED", "APPLIED",
        "TOP ≥4", "SKIP", "REJECTED", "DISCARDED"]

# Confirmed via a real 6-status grouped-view fixture (dashboard-pdf-open-
# regen-lang round): Interview < Offer < Applied < Evaluated < Rejected <
# Discarded, in that exact relative order — this corrects an earlier
# placeholder guess that had Offer near the end. SKIP, Responded, and Hired
# were still never observed in a grouped fixture; their positions below are
# still a reasonable placeholder, not verified, inserted without disturbing
# the six confirmed anchors' relative order.
GROUP_ORDER = ["Interview", "Offer", "Applied", "Responded", "Evaluated",
               "SKIP", "Rejected", "Discarded", "Hired"]

# Confirmed cyclic order via testing; sort *direction* per mode was not
# independently verified (each test fixture's groups only had 1 row).
SORT_MODES = ["score", "date", "company", "status", "location", "pay", "last"]

OPTIONAL_COLUMNS = ["APPLIED", "LOCATION", "PAY", "RPT", "PDF", "LAST"]
DEFAULT_VISIBLE_COLUMNS = {"APPLIED", "LOCATION", "PAY"}

def load_pdf_index(path):
    """Reads data/pdf-index.tsv, keyed by report number (the tracker row id)."""
    index_path = os.path.join(path, "data", "pdf-index.tsv")
    index = {}
    if not os.path.exists(index_path):
        return index
    with open(index_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5:
                continue
            report, pdf, html, fmt, date_str = parts[:5]
            if report:
                index[report] = {"pdf": pdf, "html": html, "format": fmt, "date": date_str}
    return index


def shell_open(path):
    if sys.platform == "darwin":
        subprocess.run(["open", path])
    elif sys.platform.startswith("win"):
        os.startfile(path)  # noqa: SC200 - Windows-only API
    else:
        subprocess.run(["xdg-open", path])


def load_rows(path):
    for candidate in (os.path.join(path, "applications.md"),
                      os.path.join(path, "data", "applications.md")):
        if os.path.exists(candidate):
            return read_table_rows(open(candidate, encoding="utf-8").read())
    return []


def score_num(score):
    try:
        return float(score.split("/")[0])
    except (ValueError, IndexError):
        return -1.0


def days_ago(date_str):
    try:
        y, m, d = (int(x) for x in date_str.split("-"))
        return (date.today() - date(y, m, d)).days
    except ValueError:
        return None


class Dashboard(App):
    BINDINGS = [
        ("j,down", "nav_down", "nav"),
        ("k,up", "nav_up", "nav"),
        ("h,left", "prev_tab", "tabs"),
        ("l,right", "next_tab", "tabs"),
        ("s", "cycle_sort", "sort"),
        ("v", "toggle_view", "view"),
        ("slash", "start_search", "search"),
        ("C", "toggle_columns", "columns"),
        ("enter", "open_row_menu", "actions"),
        ("p", "open_progress", "progress"),
        ("c", "open_status_overlay", "change"),
        ("o", "open_url", "url"),
        ("d", "open_pdf", "pdf"),
        ("D", "regen_pdf", "regen"),
        ("P", "open_portals", "portals"),
        ("S", "run_scan", "scan"),
        ("Q", "open_pending_queue", "pending queue"),
        ("E", "open_evaluate", "evaluate"),
        ("L", "open_cover_letter", "cover letter"),
        ("F", "run_portfolio", "portfolio"),
        ("A", "open_ai_setup", "ai setup"),
        ("question_mark", "open_help", "help"),
        ("q", "quit_app", "quit"),
    ]

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.rows = load_rows(path)
        self.tab_index = 0
        self.sort_index = 0
        self.grouped = True
        self.selected = 0
        self.search_mode = False
        self.search_query = ""
        self.columns_open = False
        self.visible_columns = set(DEFAULT_VISIBLE_COLUMNS)
        self.columns_cursor = 0

        self.screen_mode = "pipeline"  # pipeline | report | progress
        self.report_row = None
        self.status_overlay_open = False
        self.status_overlay_return = "pipeline"
        self.status_cursor = 0

        # Row actions menu (new feature — Enter on a pipeline row opens a
        # menu of what to do with it, instead of jumping straight to the
        # report).
        self.row_menu_open = False
        self.row_menu_row = None
        self.row_menu_options = []
        self.row_menu_cursor = 0

        self.toast = None  # transient status-line message; cleared on next keypress
        # NOTE: Textual dispatches a keypress to both the matching global
        # BINDINGS action *and* this app's on_key() handler — event.stop()
        # inside on_key does not suppress the BINDINGS side (confirmed by
        # testing: pressing j/enter while an overlay was open also moved
        # the pipeline's row selection / reopened the pipeline action
        # underneath it). Every pipeline-scoped action must therefore
        # explicitly no-op while either overlay is open — see overlay_open.
        self._cv_parse_done = False
        self.provider_setup_cursor = 0
        self.selected_provider = "gemini"

        # Portals editor — see portals_config.py.
        self.portals_data = None
        self.portals_items = []  # flat nav list: ("positive"|"negative"|"company", index_or_None)
        self.portals_cursor = 0
        self.portals_edit_mode = None  # None | "add_positive" | "add_negative" | "add_company" | "edit"
        self.portals_edit_target = None  # ("positive"|"negative"|"company", index) being edited
        self.portals_dirty = False

        # Scan results — see scan.py's run_scan().
        self.scan_results = []
        self.scan_summary = None
        self.scan_cursor = 0
        self.scan_categories = ["ALL"]  # ["ALL"] + portals.yml's title_filter.positive
        self.scan_category_index = 0

        # Cover letter drafts + approval gate (new feature — see application_drafts.py).
        self.cl_jd_input = None
        self.cl_angles_data = None
        self.cl_angles_cursor = 0
        self.cl_email_draft = None

    @property
    def overlay_open(self):
        return self.status_overlay_open or self.row_menu_open

    def check_action(self, action, parameters):
        # Belt-and-suspenders alongside the per-action overlay_open guards:
        # Textual dispatches a keypress to the matching global BINDINGS
        # action independently of on_key(), so without this, keys handled
        # by the status/row-actions overlay (j/k/enter/escape/q) also leak
        # through to whatever they're bound to underneath (moving the
        # pipeline cursor, reopening a menu, even quitting the app on
        # "q"). While an overlay is open, on_key() is the sole handler.
        if self.overlay_open:
            return False
        return True

    def compose(self) -> ComposeResult:
        with Vertical(id="pipeline_screen"):
            yield Static(id="title")
            yield Static(id="tabs")
            yield Static(id="status_line")
            yield Static(id="sort_line")
            yield Static(id="table")
            yield Static(id="preview")
            yield Static(id="footer")
        with Vertical(id="report_screen"):
            yield Static(id="report_header")
            with VerticalScroll(id="report_scroll"):
                yield Static(id="report_body")
            yield Static(id="report_footer")
        with Vertical(id="progress_screen"):
            yield Static(id="progress_header")
            with VerticalScroll(id="progress_scroll"):
                yield Static(id="progress_body")
            yield Static(id="progress_footer")
        with Vertical(id="setup_provider_screen"):
            yield Static(id="setup_provider_header")
            yield Static(id="setup_provider_body")
            yield Static(id="setup_provider_footer")
        with Vertical(id="setup_key_screen"):
            yield Static(id="setup_key_header")
            yield Input(placeholder="Gemini API key", password=True, id="api_key_input")
            yield Static(id="setup_key_footer")
        with Vertical(id="setup_cv_screen"):
            yield Static(id="setup_cv_header")
            yield Input(placeholder="/path/to/resume.pdf", id="pdf_path_input")
            yield Static(id="setup_cv_status")
            yield Static(id="setup_cv_footer")
        with Vertical(id="portals_screen"):
            yield Static(id="portals_header")
            with VerticalScroll(id="portals_scroll"):
                yield Static(id="portals_body")
            yield Input(placeholder="", id="portals_input")
            yield Static(id="portals_footer")
        with Vertical(id="scan_results_screen"):
            yield Static(id="scan_header")
            with VerticalScroll(id="scan_scroll"):
                yield Static(id="scan_body")
            yield Static(id="scan_footer")
        with Vertical(id="evaluate_input_screen"):
            yield Static(id="eval_input_header")
            yield Input(placeholder="Paste a job URL or the full job description text",
                        id="eval_input")
            yield Static(id="eval_input_footer")
        with Vertical(id="evaluate_result_screen"):
            yield Static(id="eval_result_header")
            with VerticalScroll(id="eval_result_scroll"):
                yield Static(id="eval_result_body")
            yield Static(id="eval_result_footer")
        with Vertical(id="cover_letter_input_screen"):
            yield Static(id="cl_input_header")
            yield Input(placeholder="Paste a job URL or the full job description text",
                        id="cl_input")
            yield Static(id="cl_input_footer")
        with Vertical(id="cover_letter_angles_screen"):
            yield Static(id="cl_angles_header")
            with VerticalScroll(id="cl_angles_scroll"):
                yield Static(id="cl_angles_body")
            yield Static(id="cl_angles_footer")
        with Vertical(id="help_screen"):
            yield Static(id="help_header")
            with VerticalScroll(id="help_scroll"):
                yield Static(id="help_body")
            yield Static(id="help_footer")
        with Vertical(id="ai_setup_screen"):
            yield Static(id="ai_setup_header")
            yield Input(placeholder="Describe what you want set up (roles, locations, "
                        "companies, your background...)", id="ai_setup_input")
            with VerticalScroll(id="ai_setup_scroll"):
                yield Static(id="ai_setup_body")
            yield Static(id="ai_setup_footer")
        yield Static(id="status_overlay")
        yield Static(id="row_menu_overlay")

    PROVIDER_CHOICES = [
        ("gemini", "Gemini", "Free tier, needs an API key from aistudio.google.com/apikey"),
        ("ollama", "Ollama (local)", "Free, runs on your machine, no API key needed"),
        ("openai", "OpenAI / compatible", "Needs an API key; also works with any "
                                           "OpenAI-compatible endpoint (Groq, Together, etc.)"),
    ]

    def has_configured_provider(self, env):
        provider = (env.get("LLM_PROVIDER") or "gemini").strip().lower()
        if provider == "ollama":
            return True  # no key required
        if provider == "openai":
            return bool(env.get("OPENAI_API_KEY"))
        return bool(env.get("GEMINI_API_KEY"))

    def on_mount(self):
        self.query_one("#status_overlay").display = False
        self.query_one("#row_menu_overlay").display = False
        env = load_env()
        has_cv = os.path.exists(os.path.join(self.path, "cv.md"))
        if not self.has_configured_provider(env):
            self.provider_setup_cursor = 0
            self.set_screen("setup_provider")
            self.render_setup_provider()
        elif not has_cv:
            self.set_screen("setup_cv")
            self.render_setup_cv()
        else:
            self.set_screen("pipeline")
            self.render_all()

    def set_screen(self, mode):
        self.screen_mode = mode
        self.query_one("#pipeline_screen").display = mode == "pipeline"
        self.query_one("#report_screen").display = mode == "report"
        self.query_one("#progress_screen").display = mode == "progress"
        self.query_one("#setup_provider_screen").display = mode == "setup_provider"
        self.query_one("#setup_key_screen").display = mode == "setup_key"
        self.query_one("#setup_cv_screen").display = mode == "setup_cv"
        self.query_one("#portals_screen").display = mode == "portals"
        self.query_one("#scan_results_screen").display = mode == "scan_results"
        self.query_one("#evaluate_input_screen").display = mode == "evaluate_input"
        self.query_one("#evaluate_result_screen").display = mode == "evaluate_result"
        self.query_one("#cover_letter_input_screen").display = mode == "cover_letter_input"
        self.query_one("#cover_letter_angles_screen").display = mode == "cover_letter_angles"
        self.query_one("#help_screen").display = mode == "help"
        self.query_one("#ai_setup_screen").display = mode == "ai_setup"
        if mode == "setup_key":
            self.query_one("#api_key_input", Input).focus()
        elif mode == "evaluate_input":
            self.query_one("#eval_input", Input).focus()
        elif mode == "cover_letter_input":
            self.query_one("#cl_input", Input).focus()
        elif mode == "setup_cv":
            self.query_one("#pdf_path_input", Input).focus()
        elif mode == "ai_setup":
            self.query_one("#ai_setup_input", Input).focus()

    # ---- data helpers ----

    def rows_for_tab(self, tab_name, rows):
        if tab_name == "ALL":
            return rows
        if tab_name == "TOP ≥4":
            return [r for r in rows if score_num(r["score"]) >= 4.0]
        return [r for r in rows if r["status"].upper() == tab_name.upper()]

    def visible_rows(self):
        rows = self.rows_for_tab(TABS[self.tab_index], self.rows)
        if self.search_query:
            q = self.search_query.lower()
            rows = [r for r in rows
                    if q in r["company"].lower() or q in r["role"].lower()
                    or q in r["notes"].lower()]
        mode = SORT_MODES[self.sort_index]
        if mode == "score":
            rows = sorted(rows, key=lambda r: score_num(r["score"]), reverse=True)
        elif mode in ("date", "last"):
            rows = sorted(rows, key=lambda r: r["date"], reverse=True)
        elif mode == "company":
            rows = sorted(rows, key=lambda r: r["company"].lower())
        elif mode == "status":
            rows = sorted(rows, key=lambda r: GROUP_ORDER.index(r["status"])
                          if r["status"] in GROUP_ORDER else len(GROUP_ORDER))
        # location/pay: no data source confirmed yet (spec §6) — no-op sort.
        return rows

    # ---- rendering ----

    def render_all(self):
        rows = self.visible_rows()
        total = len(self.rows)

        scored = [score_num(r["score"]) for r in self.rows if score_num(r["score"]) >= 0]
        avg = sum(scored) / len(scored) if scored else 0.0
        self.query_one("#title", Static).update(
            f"{APP_TITLE}{' ' * 4}{total} offers | Avg {avg:.1f}/5"
        )

        tab_bits = []
        for name in TABS:
            count = len(self.rows_for_tab(name, self.rows))
            tab_bits.append(f"{name} ({count})")
        self.query_one("#tabs", Static).update("  ".join(tab_bits))

        breakdown = {}
        for r in self.rows:
            breakdown[r["status"]] = breakdown.get(r["status"], 0) + 1
        ordered_statuses = sorted(
            breakdown, key=lambda s: GROUP_ORDER.index(s) if s in GROUP_ORDER else len(GROUP_ORDER)
        )
        self.query_one("#status_line", Static).update(
            "  ".join(f"{s}:{breakdown[s]}" for s in ordered_statuses)
        )

        if self.search_mode:
            matches = len(rows)
            self.query_one("#sort_line", Static).update(
                f"/ {self.search_query.lower()}█  {matches}/{total} matching   "
                f"Enter: keep   Esc: cancel   Ctrl+U: clear"
            )
        else:
            sort_mode_name = SORT_MODES[self.sort_index]
            view = "grouped" if self.grouped else "flat"
            self.query_one("#sort_line", Static).update(
                f"[Sort: {sort_mode_name}]  [View: {view}]  {len(rows)} shown"
            )

        table_text = self.render_table(rows)
        if self.columns_open:
            lines = [table_text, "─── Columns (SPACE toggle · ESC close) ───"]
            for col in OPTIONAL_COLUMNS:
                mark = "✓" if col in self.visible_columns else " "
                suffix = "  ✓/—" if col in ("RPT", "PDF") else ""
                lines.append(f"[{mark}] {col}{suffix}")
            self.query_one("#table", Static).update("\n".join(lines))
            self.query_one("#footer", Static).update(
                "↑↓/jk navigate  SPACE toggle  Esc/C close"
            )
        else:
            self.query_one("#table", Static).update(table_text)
            if self.toast:
                self.query_one("#footer", Static).update(self.toast)
            elif self.search_mode:
                self.query_one("#footer", Static).update(
                    "type filter live  Enter keep  Ctrl+U clear  Esc cancel"
                )
            else:
                self.query_one("#footer", Static).update(
                    "↑↓/jk nav  ←→/hl tabs  / search  s sort  r refresh  "
                    "Enter actions  o open URL  d open PDF  D regen PDF  c change  C columns  "
                    "v view  p progress  q quit"
                )

        self.render_preview(rows)

    def render_table(self, rows):
        # Keep base-column order matching the spec's fixed header shape.
        header = "  #     FIT " + "  ".join(
            c for c in ["APPLIED", "COMPANY", "ROLE", "STATUS", "LOCATION", "PAY"]
            if c not in OPTIONAL_COLUMNS or c in self.visible_columns
        )
        lines = [header]

        if not rows:
            return "\n".join(lines)

        selected_row = rows[min(self.selected, len(rows) - 1)]

        if self.grouped:
            groups = {}
            order = []
            for r in rows:
                if r["status"] not in groups:
                    groups[r["status"]] = []
                    order.append(r["status"])
                groups[r["status"]].append(r)
            order.sort(key=lambda s: GROUP_ORDER.index(s) if s in GROUP_ORDER else len(GROUP_ORDER))
            for status in order:
                group_rows = groups[status]
                lines.append(f"── {status.upper()} ({len(group_rows)}) ──")
                for r in group_rows:
                    lines.append(self.render_row(r, r is selected_row))
        else:
            for r in rows:
                lines.append(self.render_row(r, r is selected_row))
        return "\n".join(lines)

    def render_row(self, r, is_selected=False):
        applied = r["date"] if "APPLIED" in self.visible_columns else ""
        location = "—" if "LOCATION" in self.visible_columns else ""
        pay = "—" if "PAY" in self.visible_columns else ""
        sn = score_num(r["score"])
        fit = f"{sn:.1f}" if sn >= 0 else "N/A"
        marker = ">" if is_selected else " "
        return (f"{marker}#{r['id']:<4} {fit:<4} {applied:<10} "
                f"{r['company']:<16} {r['role']:<18} {r['status']:<16} {location:<8} {pay}")

    def render_preview(self, rows):
        if not rows or self.columns_open:
            self.query_one("#preview", Static).update("")
            return
        idx = min(self.selected, len(rows) - 1)
        r = rows[idx]
        d = days_ago(r["date"])
        suffix = f" ({d}d ago)" if d is not None else ""
        line = f"Last contact: {r['date']}" + suffix
        if r["notes"]:
            line += "\n" + r["notes"]
        self.query_one("#preview", Static).update(line)

    def resolve_report_file(self, row):
        _, report_path = parse_report_cell(row["report"])
        if not report_path:
            return None
        full_path = os.path.join(self.path, "data", report_path)
        if not os.path.exists(full_path):
            full_path = os.path.join(self.path, report_path)
        return full_path if os.path.exists(full_path) else None

    def render_report(self):
        r = self.report_row
        if r is None:
            return
        self.query_one("#report_header", Static).update(f"{r['company']} — {r['role']}")
        _, report_path = parse_report_cell(r["report"])
        body = "(no report on file)"
        if report_path:
            full_path = self.resolve_report_file(r)
            if full_path:
                text = open(full_path, encoding="utf-8").read()
                body = "(empty file)" if not text.strip() else Markdown(text)
        self.query_one("#report_body", Static).update(body)
        self.query_one("#report_footer", Static).update(
            "↑↓ scroll  PgUp/Dn page  g/G top/end  c change  Esc back"
        )

    def render_progress(self):
        total = len(self.rows)
        avg = sum(score_num(r["score"]) for r in self.rows) / total if total else 0.0
        self.query_one("#progress_header", Static).update(
            f"SEARCH PROGRESS{' ' * 4}{total} evaluated | {avg:.1f} avg score"
        )

        def stage_index(status):
            if status in LIFECYCLE_ORDER:
                return LIFECYCLE_ORDER.index(status)
            if status in APPLIED_ONLY_STATUSES:
                return 1
            return 0  # EVALUATED_ONLY_STATUSES and anything unrecognized

        indices = [stage_index(r["status"]) for r in self.rows]
        evaluated_count = total
        applied_count = sum(1 for i in indices if i >= 1)

        lines = ["Pipeline Funnel"]
        for stage_name, stage_i in [("Evaluated", 0), ("Applied", 1), ("Responded", 2),
                                     ("Interview", 3), ("Offer", 4)]:
            count = sum(1 for i in indices if i >= stage_i)
            bar = "█" * (count * 4)
            if stage_i == 0:
                lines.append(f"{stage_name:<10}{bar}  {count}")
            else:
                base = evaluated_count if stage_i == 1 else applied_count
                pct = (count / base * 100) if base else 0.0
                lines.append(f"{stage_name:<10}{bar}  {count} ({pct:.0f}%)")

        lines.append("")
        lines.append("Score Distribution")
        for label, lo, hi in SCORE_BUCKETS:
            count = sum(1 for r in self.rows if lo <= score_num(r["score"]) < hi)
            bar = "█" * (count * 4)
            lines.append(f"{label:<8}{bar}  {count}")

        lines.append("")
        lines.append("Conversion Rates")
        resp = sum(1 for i in indices if i >= 2)
        interview = sum(1 for i in indices if i >= 3)
        offer = sum(1 for i in indices if i >= 4)
        resp_pct = (resp / applied_count * 100) if applied_count else 0.0
        int_pct = (interview / applied_count * 100) if applied_count else 0.0
        offer_pct = (offer / applied_count * 100) if applied_count else 0.0
        lines.append(f"Response Rate: {resp_pct:.1f}%  |  Interview Rate: {int_pct:.1f}%  "
                      f"|  Offer Rate: {offer_pct:.1f}%")
        lines.append(f"{applied_count} active applications | {offer} total offers")

        lines.append("")
        lines.append("Weekly Activity")
        weeks = Counter()
        for r in self.rows:
            try:
                y, m, d = (int(x) for x in r["date"].split("-"))
                weeks[date(y, m, d).isocalendar()[1]] += 1
            except ValueError:
                pass
        for week in sorted(weeks):
            count = weeks[week]
            bar = "█" * (count * 4)
            lines.append(f"W{week:<9}{bar}  {count}")

        self.query_one("#progress_body", Static).update("\n".join(lines))
        self.query_one("#progress_footer", Static).update(
            "↑↓ scroll  PgUp/Dn page  Esc back"
        )

    def write_status(self, row, new_status):
        """apply_status_change() writes to a path hardcoded relative to the
        process CWD; temporarily repoint it at self.path so --path works."""
        old_md, old_log = set_status.MD_PATH, set_status.STATUS_LOG_PATH
        set_status.MD_PATH = os.path.join(self.path, "data", "applications.md")
        set_status.STATUS_LOG_PATH = os.path.join(self.path, "data", "status-log.tsv")
        try:
            return set_status.apply_status_change(self.rows, row, new_status)
        finally:
            set_status.MD_PATH, set_status.STATUS_LOG_PATH = old_md, old_log

    def render_status_overlay(self):
        lines = ["Change status:"]
        for i, state in enumerate(CANONICAL_STATES):
            marker = ">" if i == self.status_cursor else " "
            lines.append(f"{marker}{state}")
        lines.append("")
        lines.append("↑/↓/j/k nav  Enter confirm  Esc/q cancel")
        self.query_one("#status_overlay", Static).update("\n".join(lines))

    # ---- row actions menu (new feature — Enter on a pipeline row) ----

    def resolve_row_url(self, row):
        """Best-effort source URL for a tracked row: a bare URL stashed in
        the Notes column (how rows added straight from a scan result store
        it, since they have no report file yet), else the **URL:** line in
        the row's own report (how rows added via full evaluation store
        it)."""
        notes = (row.get("notes") or "").strip()
        if notes.startswith("http://") or notes.startswith("https://"):
            return notes
        report_file = self.resolve_report_file(row)
        if report_file:
            text = open(report_file, encoding="utf-8").read()
            m = re.search(r"\*\*URL:\*\*\s*(\S+)", text)
            if m:
                return m.group(1)
        return None

    def _build_row_menu_options(self, row):
        options = []
        if self.resolve_report_file(row):
            options.append(("View report", "report"))
        url = self.resolve_row_url(row)
        if url:
            options.append(("Open URL", "url"))
        pdf_entry = load_pdf_index(self.path).get(str(row["id"]))
        if pdf_entry and pdf_entry.get("pdf"):
            options.append(("Regenerate resume PDF", "resume"))
        if url:
            options.append(("Evaluate / re-evaluate this posting", "evaluate"))
        options.append(("Change status", "status"))
        options.append(("Cancel", "cancel"))
        return options

    def render_row_menu(self):
        row = self.row_menu_row
        lines = [f"{row['company']} — {row['role']}", ""]
        for i, (label, _key) in enumerate(self.row_menu_options):
            marker = ">" if i == self.row_menu_cursor else " "
            lines.append(f"{marker}{label}")
        lines.append("")
        lines.append("↑/↓/j/k nav  Enter select  Esc/q cancel")
        self.query_one("#row_menu_overlay", Static).update("\n".join(lines))

    # ---- onboarding ----

    def render_setup_provider(self):
        lines = ["Welcome — let's get set up. Pick an AI provider (Gemini is the default):", ""]
        for i, (key, label, desc) in enumerate(self.PROVIDER_CHOICES):
            marker = ">" if i == self.provider_setup_cursor else " "
            lines.append(f"{marker}{label}")
            lines.append(f"    {desc}")
        self.query_one("#setup_provider_header", Static).update("AI provider setup")
        self.query_one("#setup_provider_body", Static).update("\n".join(lines))
        self.query_one("#setup_provider_footer", Static).update(
            "↑↓ choose   Enter continue   Esc skip for now"
        )

    def render_setup_key(self):
        provider_key, provider_label, _ = self.PROVIDER_CHOICES[self.provider_setup_cursor]
        self.selected_provider = provider_key
        if provider_key == "ollama":
            self.query_one("#setup_key_header", Static).update(
                "Ollama needs no API key — just make sure `ollama serve` is running "
                "locally.\nPress Enter to confirm and continue (or type a custom model "
                "name, e.g. llama3.3)."
            )
            self.query_one("#api_key_input", Input).placeholder = "model name (optional, Enter to use default)"
            self.query_one("#api_key_input", Input).password = False
        else:
            label = "Gemini" if provider_key == "gemini" else "OpenAI (or compatible)"
            self.query_one("#setup_key_header", Static).update(
                f"Paste your {label} API key.\nSaved to a local .env file, never committed to git."
            )
            self.query_one("#api_key_input", Input).placeholder = f"{label} API key"
            self.query_one("#api_key_input", Input).password = True
        self.query_one("#setup_key_footer", Static).update(
            "Enter save & continue   Esc skip for now"
        )

    def render_setup_cv(self):
        self.query_one("#setup_cv_header", Static).update(
            "No cv.md yet. Point me at a PDF resume and I'll parse it with "
            "Gemini.\nOr press Esc to skip and write cv.md yourself later."
        )
        self.query_one("#setup_cv_status", Static).update("")
        self.query_one("#setup_cv_footer", Static).update(
            "Enter parse PDF   Esc skip"
        )

    def on_input_submitted(self, event: Input.Submitted):
        if self.screen_mode == "setup_key" and event.input.id == "api_key_input":
            value = event.value.strip()
            provider = getattr(self, "selected_provider", "gemini")
            if provider == "gemini":
                if value:
                    save_env_var("GEMINI_API_KEY", value)
            elif provider == "ollama":
                save_env_var("LLM_PROVIDER", "ollama")
                if value:
                    save_env_var("OLLAMA_MODEL", value)
            elif provider == "openai":
                save_env_var("LLM_PROVIDER", "openai")
                if value:
                    save_env_var("OPENAI_API_KEY", value)
            has_cv = os.path.exists(os.path.join(self.path, "cv.md"))
            if has_cv:
                self.set_screen("pipeline")
                self.render_all()
            else:
                self.set_screen("setup_cv")
                self.render_setup_cv()
        elif self.screen_mode == "setup_cv" and event.input.id == "pdf_path_input":
            self.run_cv_parse(event.value.strip())
        elif self.screen_mode == "portals" and event.input.id == "portals_input":
            self.submit_portals_edit(event.value.strip())
        elif self.screen_mode == "evaluate_input" and event.input.id == "eval_input":
            self.start_evaluation(event.value.strip())
        elif self.screen_mode == "cover_letter_input" and event.input.id == "cl_input":
            self.start_cover_letter_drafts(event.value.strip())
        elif self.screen_mode == "ai_setup" and event.input.id == "ai_setup_input":
            self.start_ai_setup(event.value.strip())

    def run_cv_parse(self, pdf_path):
        status = self.query_one("#setup_cv_status", Static)
        if not pdf_path:
            status.update("Enter a path to a PDF file, or press Esc to skip.")
            return
        pdf_path = os.path.expanduser(pdf_path)
        if not os.path.exists(pdf_path):
            status.update(f"File not found: {pdf_path}")
            return

        status.update("Parsing... this may take a few seconds (Gemini API call in progress).")
        env = load_env()
        api_key = env.get("GEMINI_API_KEY")
        if not api_key:
            status.update("No API key on file — press Esc to skip and write cv.md by hand, "
                           "or restart to enter a key.")
            return
        try:
            text = extract_pdf_text(pdf_path)
            cv_markdown = build_cv_markdown(text, api_key)
        except LLMError as e:
            status.update(f"Parse failed: {e}\nTry another path, or Esc to skip.")
            return
        except Exception as e:  # PDF read errors etc. — surface, don't guess
            status.update(f"Couldn't read that PDF: {e}\nTry another path, or Esc to skip.")
            return

        cv_path = os.path.join(self.path, "cv.md")
        with open(cv_path, "w", encoding="utf-8") as f:
            f.write(cv_markdown)
        status.update(f"cv.md written to {cv_path} ✓ — press any key to continue.")
        self._cv_parse_done = True

    # ---- portals editor — see portals_config.py ----

    # Section keys that hold a simple list of strings, mapped to their
    # (top-level key, sub-key) path in the loaded portals.yml dict, and the
    # header label shown for each. "company" is handled separately since
    # each entry is a dict, not a string.
    # (top-level key, sub-key, header label, add-placeholder)
    PORTALS_LIST_SECTIONS = {
        "positive": ("title_filter", "positive", "Target roles (title_filter.positive)",
                     "e.g. Backend, Full Stack, AI"),
        "negative": ("title_filter", "negative", "Exclude (title_filter.negative)",
                     "e.g. Intern, Junior"),
        "always_allow": ("location_filter", "always_allow",
                          "Always allow — location/country (location_filter.always_allow)",
                          "e.g. Remote"),
        "block": ("location_filter", "block",
                  "Block — location/country (location_filter.block)",
                  "e.g. India"),
        "allow": ("location_filter", "allow",
                  "Allow if not blocked — location/country (location_filter.allow)",
                  "e.g. United States, Germany"),
    }

    # Fixed site list for the jobspy section — factual product/site names
    # from jobspy's own public module (Indeed/LinkedIn/Glassdoor/Google/
    # ZipRecruiter/Bayt/Naukri/BDJobs), not an editable free-text list, so
    # typos can't silently break scan.py's `sites:` config.
    FIXED_JOBSPY_SITES = ["indeed", "linkedin", "glassdoor", "google",
                           "zip_recruiter", "bayt", "naukri", "bdjobs"]

    @property
    def portals_yml_path(self):
        return os.path.join(self.path, "portals.yml")

    def portals_list_for(self, section):
        top, sub, _, _ = self.PORTALS_LIST_SECTIONS[section]
        return self.portals_data[top][sub]

    def rebuild_portals_items(self):
        """Flat nav list; a None index marks the section's own header row."""
        items = []
        for section in self.PORTALS_LIST_SECTIONS:
            items.append((section, None))
            for i in range(len(self.portals_list_for(section))):
                items.append((section, i))
        items.append(("company", None))
        for i in range(len(self.portals_data["tracked_companies"])):
            items.append(("company", i))
        items.append(("jobspy_header", None))
        items.append(("jobspy_enabled", None))
        items.append(("jobspy_country", None))
        items.append(("jobspy_location", None))
        items.append(("jobspy_results", None))
        for i in range(len(self.FIXED_JOBSPY_SITES)):
            items.append(("jobspy_site", i))
        self.portals_items = items
        self.portals_cursor = min(self.portals_cursor, len(items) - 1)

    def render_portals(self):
        lines = []
        for row, (section, idx) in enumerate(self.portals_items):
            marker = ">" if row == self.portals_cursor else " "
            if section == "jobspy_header":
                lines.append(f"{marker}── Job board search (jobspy — needs Python 3.10+, "
                              f"see requirements.txt) ──")
            elif section == "jobspy_enabled":
                check = "✓" if self.portals_data["jobspy"].get("enabled") else " "
                lines.append(f"{marker}    [{check}] Enabled")
            elif section == "jobspy_country":
                c = self.portals_data["jobspy"].get("country_indeed", "usa")
                lines.append(f"{marker}    Indeed country: {c}")
            elif section == "jobspy_location":
                loc = self.portals_data["jobspy"].get("location", "")
                lines.append(f"{marker}    Search location: {loc or '(none)'}")
            elif section == "jobspy_results":
                n = self.portals_data["jobspy"].get("results_wanted", 20)
                lines.append(f"{marker}    Results per search: {n}")
            elif section == "jobspy_site":
                site = self.FIXED_JOBSPY_SITES[idx]
                check = "✓" if site in (self.portals_data["jobspy"].get("sites") or []) else " "
                lines.append(f"{marker}    [{check}] {site}")
            elif idx is None:
                if section == "company":
                    label = "Companies (tracked_companies)"
                else:
                    label = self.PORTALS_LIST_SECTIONS[section][2]
                lines.append(f"{marker}── {label} ──")
            elif section == "company":
                c = self.portals_data["tracked_companies"][idx]
                check = "✓" if c.get("enabled", True) else " "
                lines.append(f"{marker}   [{check}] {c.get('name', '?')}  "
                              f"{c.get('careers_url', '')}")
            else:
                kw = self.portals_list_for(section)[idx]
                lines.append(f"{marker}    {kw}")
        dirty = " (unsaved changes)" if self.portals_dirty else ""
        self.query_one("#portals_header", Static).update(f"Portals Config — portals.yml{dirty}")
        self.query_one("#portals_body", Static).update("\n".join(lines))
        self.query_one("#portals_footer", Static).update(
            "↑↓ nav  a add  Enter edit  x delete  Space toggle  s save  Esc back"
        )

    def start_portals_add(self):
        section, _ = self.portals_items[self.portals_cursor]
        if section.startswith("jobspy_"):
            return  # fixed rows — nothing to add here
        self.portals_edit_mode = f"add_{section}"
        if section == "company":
            placeholder = "Company Name | https://job-boards.greenhouse.io/slug"
        else:
            placeholder = self.PORTALS_LIST_SECTIONS[section][3]
        inp = self.query_one("#portals_input", Input)
        inp.placeholder = placeholder
        inp.value = ""
        inp.focus()

    def start_portals_edit(self):
        section, idx = self.portals_items[self.portals_cursor]
        if section == "jobspy_results":
            self.portals_edit_mode = "edit"
            self.portals_edit_target = (section, None)
            inp = self.query_one("#portals_input", Input)
            inp.value = str(self.portals_data["jobspy"].get("results_wanted", 20))
            inp.focus()
            return
        if section == "jobspy_country":
            self.portals_edit_mode = "edit"
            self.portals_edit_target = (section, None)
            inp = self.query_one("#portals_input", Input)
            inp.placeholder = "e.g. usa, israel, uk, germany (jobspy Country name)"
            inp.value = self.portals_data["jobspy"].get("country_indeed", "usa")
            inp.focus()
            return
        if section == "jobspy_location":
            self.portals_edit_mode = "edit"
            self.portals_edit_target = (section, None)
            inp = self.query_one("#portals_input", Input)
            inp.placeholder = "e.g. Tel Aviv, Israel"
            inp.value = self.portals_data["jobspy"].get("location", "")
            inp.focus()
            return
        if idx is None or section in ("jobspy_header", "jobspy_enabled", "jobspy_site"):
            return  # jobspy_enabled/jobspy_site toggle via Space, not edit
        self.portals_edit_mode = "edit"
        self.portals_edit_target = (section, idx)
        inp = self.query_one("#portals_input", Input)
        if section == "company":
            c = self.portals_data["tracked_companies"][idx]
            inp.value = f"{c.get('name', '')} | {c.get('careers_url', '')}"
        else:
            inp.value = self.portals_list_for(section)[idx]
        inp.focus()

    def delete_portals_item(self):
        section, idx = self.portals_items[self.portals_cursor]
        if idx is None or section.startswith("jobspy_"):
            return
        if section == "company":
            del self.portals_data["tracked_companies"][idx]
        else:
            del self.portals_list_for(section)[idx]
        self.portals_dirty = True
        self.rebuild_portals_items()
        self.render_portals()

    def toggle_portals_company(self):
        section, idx = self.portals_items[self.portals_cursor]
        if section == "jobspy_enabled":
            j = self.portals_data["jobspy"]
            j["enabled"] = not j.get("enabled", False)
            self.portals_dirty = True
            self.render_portals()
            return
        if section == "jobspy_site":
            sites = self.portals_data["jobspy"].setdefault("sites", [])
            site = self.FIXED_JOBSPY_SITES[idx]
            if site in sites:
                sites.remove(site)
            else:
                sites.append(site)
            self.portals_dirty = True
            self.render_portals()
            return
        if section != "company" or idx is None:
            return
        c = self.portals_data["tracked_companies"][idx]
        c["enabled"] = not c.get("enabled", True)
        self.portals_dirty = True
        self.render_portals()

    def submit_portals_edit(self, value):
        mode = self.portals_edit_mode
        if mode is None:
            # Defensive: a duplicate/stray Input.Submitted event (observed in
            # practice — some terminals appear to deliver Enter twice) with
            # nothing active to submit. Ignore rather than crash.
            return
        self.portals_edit_mode = None
        inp = self.query_one("#portals_input", Input)
        inp.value = ""
        self.screen.set_focus(None)
        if not value:
            self.render_portals()
            return

        if mode == "add_company":
            name, _, url = value.partition("|")
            self.portals_data["tracked_companies"].append(
                {"name": name.strip(), "careers_url": url.strip(), "enabled": True}
            )
        elif mode.startswith("add_"):
            section = mode[len("add_"):]
            self.portals_list_for(section).append(value)
        elif mode == "edit":
            section, idx = self.portals_edit_target
            if section == "jobspy_results":
                try:
                    self.portals_data["jobspy"]["results_wanted"] = max(1, int(value))
                except ValueError:
                    pass
            elif section == "jobspy_country":
                self.portals_data["jobspy"]["country_indeed"] = value.strip().lower()
            elif section == "jobspy_location":
                self.portals_data["jobspy"]["location"] = value.strip()
            elif section == "company":
                name, _, url = value.partition("|")
                c = self.portals_data["tracked_companies"][idx]
                c["name"] = name.strip()
                if url.strip():
                    c["careers_url"] = url.strip()
            else:
                self.portals_list_for(section)[idx] = value

        self.portals_dirty = True
        self.rebuild_portals_items()
        self.render_portals()

    def save_portals_file(self):
        save_portals(self.portals_yml_path, self.portals_data)
        self.portals_dirty = False
        self.render_portals()

    # ---- actions ----

    def action_nav_down(self):
        if self.screen_mode != "pipeline" or self.overlay_open:
            return
        self.toast = None
        rows = self.visible_rows()
        if rows:
            self.selected = min(self.selected + 1, len(rows) - 1)
        self.render_all()

    def action_nav_up(self):
        if self.screen_mode != "pipeline" or self.overlay_open:
            return
        self.toast = None
        self.selected = max(self.selected - 1, 0)
        self.render_all()

    def action_prev_tab(self):
        if self.screen_mode != "pipeline" or self.overlay_open:
            return
        self.toast = None
        self.tab_index = (self.tab_index - 1) % len(TABS)
        self.selected = 0
        self.render_all()

    def action_next_tab(self):
        if self.screen_mode != "pipeline" or self.overlay_open:
            return
        self.toast = None
        self.tab_index = (self.tab_index + 1) % len(TABS)
        self.selected = 0
        self.render_all()

    def open_report_for_row(self, row):
        self.toast = None
        self.report_row = row
        self.set_screen("report")
        self.render_report()

    def action_open_row_menu(self):
        if self.row_menu_open or self.status_overlay_open or self.screen_mode != "pipeline" \
                or self.search_mode or self.columns_open:
            return
        rows = self.visible_rows()
        if not rows:
            return
        self.toast = None
        self.row_menu_row = rows[min(self.selected, len(rows) - 1)]
        self.row_menu_options = self._build_row_menu_options(self.row_menu_row)
        self.row_menu_cursor = 0
        self.row_menu_open = True
        self.query_one("#row_menu_overlay").display = True
        self.render_row_menu()

    def action_open_progress(self):
        if self.screen_mode != "pipeline" or self.search_mode or self.columns_open \
                or self.overlay_open:
            return
        self.toast = None
        self.set_screen("progress")
        self.render_progress()

    def action_open_portals(self):
        if self.screen_mode != "pipeline" or self.search_mode or self.columns_open \
                or self.overlay_open:
            return
        self.toast = None
        self.portals_data = load_portals(self.portals_yml_path)
        self.portals_cursor = 0
        self.portals_dirty = False
        self.rebuild_portals_items()
        self.set_screen("portals")
        self.render_portals()

    HELP_TEXT = """PIPELINE SCREEN
  ↑↓ / j k        navigate rows
  ←→ / h l        switch tabs
  /               search/filter (Enter keep, Esc cancel, Ctrl+U clear)
  s               cycle sort mode
  v               toggle grouped/flat view
  C               toggle optional columns
  Enter           actions menu for the selected row (report, URL, resume, evaluate, status)
  c               change status
  o               open the report's URL in your browser
  d               open the row's generated PDF
  D               regenerate the row's PDF
  p               progress/funnel screen
  q               quit

FEATURES
  P               portals editor — target roles, locations, companies, job-board search
  S               scan — fetch new postings from tracked companies + configured job boards
  Q               reopen your pending list (data/pipeline.md) without scanning again
  E               evaluate a job (paste URL or JD text) — score, report, tailored PDF, tracker entry
  L               cover letter drafts — multiple angles with an approval gate before rendering
  F               portfolio PDF — narrative proof-points page built from your CV
  A               AI setup assistant — describe what you want configured in plain language
  ?               this help screen

Full command reference and file layout: see README.md in this folder."""

    def action_open_help(self):
        if self.screen_mode != "pipeline" or self.search_mode or self.columns_open \
                or self.overlay_open:
            return
        self.toast = None
        self.set_screen("help")
        self.query_one("#help_header", Static).update("Help — available commands")
        self.query_one("#help_body", Static).update(self.HELP_TEXT)
        self.query_one("#help_footer", Static).update("Esc back to pipeline")

    def action_open_ai_setup(self):
        if self.screen_mode != "pipeline" or self.search_mode or self.columns_open \
                or self.overlay_open:
            return
        env = load_env()
        if not env.get("GEMINI_API_KEY") and not env.get("LLM_PROVIDER"):
            self.toast = "No AI provider configured — set one up first."
            self.render_all()
            return
        self.toast = None
        self.set_screen("ai_setup")
        self.query_one("#ai_setup_header", Static).update(
            "AI Setup Assistant — describe what you want, then Enter"
        )
        self.query_one("#ai_setup_input", Input).value = ""
        self.query_one("#ai_setup_body", Static).update(
            "Examples:\n"
            '  "I want senior backend roles in Tel Aviv or remote, not junior"\n'
            '  "Exclude anything mentioning unpaid or internship"\n'
            '  "I\'m a data engineer with 6 years in Python and Spark, based in Haifa"\n\n'
            "This only ever writes portals.yml / cv.md, and shows you exactly what changed — "
            "it never adds a company by guessing its URL."
        )
        self.query_one("#ai_setup_footer", Static).update("Enter submit   Esc back")

    def start_ai_setup(self, message):
        if not message:
            return
        self.query_one("#ai_setup_body", Static).update("Thinking...")
        self.query_one("#ai_setup_footer", Static).update("Esc back to pipeline (keeps running)")
        self._ai_setup_worker(self.path, message)

    @work(thread=True)
    def _ai_setup_worker(self, base_path, message):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_setup.py")
        try:
            proc = subprocess.run(
                [sys.executable, script, message, "--json"], cwd=base_path,
                capture_output=True, text=True, timeout=120,
            )
            result = json.loads(proc.stdout)
        except Exception as e:
            self.call_from_thread(self._on_ai_setup_done, f"Failed: {e}")
            return
        if "error" in result:
            self.call_from_thread(self._on_ai_setup_done, f"Failed: {result['error']}")
            return
        lines = [result["summary"], ""] if result.get("summary") else []
        if result["changes"]:
            lines.append("Changes made:")
            for c in result["changes"]:
                lines.append(f"  + {c}")
        else:
            lines.append("Nothing to change — try describing target roles, locations, "
                          "or your background more specifically.")
        self.call_from_thread(self._on_ai_setup_done, "\n".join(lines))

    def _on_ai_setup_done(self, message):
        if self.screen_mode != "ai_setup":
            return
        self.query_one("#ai_setup_body", Static).update(message)
        self.query_one("#ai_setup_footer", Static).update(
            "Enter submit another   Esc back to pipeline"
        )

    def action_run_portfolio(self):
        if self.screen_mode != "pipeline" or self.search_mode or self.columns_open \
                or self.overlay_open:
            return
        env = load_env()
        if not env.get("GEMINI_API_KEY"):
            self.toast = "No Gemini API key configured — set one up first."
            self.render_all()
            return
        self.toast = "Generating portfolio PDF..."
        self.render_all()
        self._portfolio_worker(self.path)

    @work(thread=True)
    def _portfolio_worker(self, base_path):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio.py")
        try:
            proc = subprocess.run(
                [sys.executable, script, "--json"], cwd=base_path,
                capture_output=True, text=True, timeout=120,
            )
            result = json.loads(proc.stdout)
        except Exception as e:
            self.call_from_thread(self._on_portfolio_done, f"Portfolio generation failed: {e}")
            return
        if "error" in result:
            self.call_from_thread(self._on_portfolio_done, f"Portfolio generation failed: {result['error']}")
        else:
            self.call_from_thread(self._on_portfolio_done, f"Portfolio PDF saved: {result['pdf_path']}")

    def _on_portfolio_done(self, message):
        if self.screen_mode == "pipeline":
            self.toast = message
            self.render_all()

    def action_open_evaluate(self):
        if self.screen_mode != "pipeline" or self.search_mode or self.columns_open \
                or self.overlay_open:
            return
        self.toast = None
        env = load_env()
        if not env.get("GEMINI_API_KEY"):
            self.toast = "No Gemini API key configured — set one up first."
            self.render_all()
            return
        self.set_screen("evaluate_input")
        self.query_one("#eval_input_header", Static).update(
            "Paste a job URL or the full job description text, then Enter."
        )
        self.query_one("#eval_input", Input).value = ""
        self.query_one("#eval_input_footer", Static).update("Enter evaluate   Esc cancel")

    EVAL_TIMEOUT_SECONDS = 300

    def start_evaluation(self, jd_input):
        if not jd_input:
            return
        self.set_screen("evaluate_result")
        self.query_one("#eval_result_header", Static).update("Evaluating...")
        self.query_one("#eval_result_body", Static).update(
            "Fetching the posting (if a URL) and scoring it against your CV via Gemini. "
            "This usually takes 10-30 seconds."
        )
        self.query_one("#eval_result_footer", Static).update("Esc back to pipeline (keeps running)")
        self._eval_worker(self.path, jd_input)

    @work(thread=True)
    def _eval_worker(self, base_path, jd_input):
        # Subprocess, not an in-process worker thread — same reasoning as
        # _scan_worker: this also does network I/O (Playwright for URL
        # fetch, Gemini API call) and a real process avoids any repeat of
        # the thread-hang interaction found with jobspy.
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evaluate.py")
        try:
            proc = subprocess.run(
                [sys.executable, script, jd_input, "--json"], cwd=base_path,
                capture_output=True, text=True, timeout=self.EVAL_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            self.call_from_thread(self._on_eval_error,
                                   f"timed out after {self.EVAL_TIMEOUT_SECONDS}s")
            return
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            self.call_from_thread(self._on_eval_error, proc.stderr.strip()[-500:] or "bad output")
            return
        if "error" in result:
            self.call_from_thread(self._on_eval_error, result["error"])
            return
        merge_error = self._run_merge_tracker(base_path)
        result["merge_error"] = merge_error
        self.call_from_thread(self._on_eval_complete, result)

    APPLICATIONS_HEADER = (
        "# Applications Tracker\n\n"
        "| # | Date | Company | Role | Score | Status | PDF | Report | Notes |\n"
        "|---|------|---------|------|-------|--------|-----|--------|-------|\n"
    )

    def _run_merge_tracker(self, base_path):
        """Folds the tracker addition evaluate.py just staged into
        data/applications.md, so it actually shows up on the pipeline
        screen without a separate manual step. Returns an error string on
        failure, or None on success (evaluate.py's own outputs — the
        report/PDF — are already written either way, so a merge failure
        here is reported but doesn't undo anything).

        Bootstraps data/applications.md first if it's missing — confirmed
        by testing that merge_tracker.py silently no-ops (exit 0, "No
        applications.md found. Nothing to merge into.") rather than
        failing when the tracker file doesn't exist yet, which would
        otherwise look like a successful merge that actually did nothing."""
        md_path = os.path.join(base_path, "data", "applications.md")
        if not os.path.exists(md_path):
            os.makedirs(os.path.dirname(md_path), exist_ok=True)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(self.APPLICATIONS_HEADER)

        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "merge_tracker.py")
        try:
            proc = subprocess.run([sys.executable, script], cwd=base_path,
                                   capture_output=True, text=True, timeout=30)
        except Exception as e:
            return str(e)
        if proc.returncode != 0:
            return proc.stdout.strip()[-300:] or proc.stderr.strip()[-300:] or "unknown error"
        return None

    def _on_eval_complete(self, result):
        data = result["data"]
        lines = [
            f"Score: {data.get('score')}/5    Legitimacy: {data.get('legitimacy_tier', '?')}",
            f"{data.get('company', '?')} — {data.get('role_title', '?')}",
            "",
            "Role summary:",
            data.get("role_summary", ""),
            "",
            "CV matches:",
        ]
        for m in data.get("cv_matches", []):
            lines.append(f"  + {m}")
        lines.append("")
        lines.append("CV gaps:")
        for g in data.get("cv_gaps", []):
            lines.append(f"  - {g}")
        lines.append("")
        lines.append(f"Report saved: {result['report_path']}")
        if result.get("pdf_path"):
            lines.append(f"Tailored PDF: {result['pdf_path']}")
        if result.get("merge_error"):
            lines.append(f"⚠ Added to tracker addition but merge failed: {result['merge_error']}")
            lines.append(f"  Run merge_tracker.py by hand to fold {result['addition_path']} in.")
        else:
            lines.append("✓ Added to your tracker — it'll show on the pipeline screen.")
        self.query_one("#eval_result_header", Static).update("Evaluation complete")
        self.query_one("#eval_result_body", Static).update("\n".join(lines))
        self.query_one("#eval_result_footer", Static).update("Esc back to pipeline")
        self.rows = load_rows(self.path)

    def _on_eval_error(self, message):
        self.query_one("#eval_result_header", Static).update("Evaluation failed")
        self.query_one("#eval_result_body", Static).update(message)
        self.query_one("#eval_result_footer", Static).update("Esc back to pipeline")

    # ---- cover letter drafts + approval gate — see application_drafts.py ----

    def action_open_cover_letter(self):
        if self.screen_mode != "pipeline" or self.search_mode or self.columns_open \
                or self.overlay_open:
            return
        self.toast = None
        env = load_env()
        if not env.get("GEMINI_API_KEY"):
            self.toast = "No Gemini API key configured — set one up first."
            self.render_all()
            return
        self.set_screen("cover_letter_input")
        self.query_one("#cl_input_header", Static).update(
            "Paste a job URL or the full job description text, then Enter."
        )
        self.query_one("#cl_input", Input).value = ""
        self.query_one("#cl_input_footer", Static).update("Enter draft angles   Esc cancel")

    def start_cover_letter_drafts(self, jd_input):
        if not jd_input:
            return
        self.cl_jd_input = jd_input
        self.set_screen("cover_letter_angles")
        self.query_one("#cl_angles_header", Static).update("Drafting cover letter angles...")
        self.query_one("#cl_angles_body", Static).update(
            "Generating a few distinct angles via Gemini — usually 10-20 seconds."
        )
        self.query_one("#cl_angles_footer", Static).update("Esc back to pipeline (keeps running)")
        self._cl_worker(self.path, jd_input)

    @work(thread=True)
    def _cl_worker(self, base_path, jd_input):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "application_drafts.py")
        try:
            proc = subprocess.run(
                [sys.executable, script, jd_input, "--json"], cwd=base_path,
                capture_output=True, text=True, timeout=180,
            )
        except subprocess.TimeoutExpired:
            self.call_from_thread(self._on_cl_error, "timed out after 180s")
            return
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            self.call_from_thread(self._on_cl_error, proc.stderr.strip()[-500:] or "bad output")
            return
        if "error" in result:
            self.call_from_thread(self._on_cl_error, result["error"])
            return
        self.call_from_thread(self._on_cl_angles_ready, result)

    def _on_cl_angles_ready(self, result):
        self.cl_angles_data = result
        self.cl_angles_cursor = 0
        self.cl_email_draft = None
        self.render_cl_angles()

    def render_cl_angles(self):
        angles = self.cl_angles_data["angles"]
        lines = []
        for i, angle in enumerate(angles):
            marker = ">" if i == self.cl_angles_cursor else " "
            lines.append(f"{marker}[{i}] {angle['label']}")
            lines.append(f"      {angle['opening']}")
            lines.append("")
        if self.cl_email_draft:
            lines.append("── Email draft ──")
            lines.append(f"Subject: {self.cl_email_draft['subject']}")
            lines.append("")
            lines.append(self.cl_email_draft["body"])
        self.query_one("#cl_angles_header", Static).update(
            f"{len(angles)} cover letter angle(s) — pick one to render (approval gate)"
        )
        self.query_one("#cl_angles_body", Static).update("\n".join(lines))
        self.query_one("#cl_angles_footer", Static).update(
            "↑↓ nav  Enter approve & render PDF  m draft email  Esc back to pipeline"
        )

    def _on_cl_error(self, message):
        self.query_one("#cl_angles_header", Static).update("Cover letter drafting failed")
        self.query_one("#cl_angles_body", Static).update(message)
        self.query_one("#cl_angles_footer", Static).update("Esc back to pipeline")

    def approve_cl_angle(self):
        from application_drafts import angle_to_payload
        from generate_cover_letter import check_required

        payload = angle_to_payload(self.cl_angles_data, self.cl_angles_cursor)
        missing = check_required(payload)
        if missing:
            self.query_one("#cl_angles_body", Static).update(
                f"Can't render — missing field: {missing}"
            )
            return
        self.query_one("#cl_angles_footer", Static).update("Rendering PDF...")
        self._cl_pdf_worker(self.path, payload)

    @work(thread=True)
    def _cl_pdf_worker(self, base_path, payload):
        # Playwright's sync API (used by generate_cover_letter.py's PDF
        # render step) refuses to run inside an already-active asyncio
        # loop — confirmed by testing: calling it in-process from a
        # Textual key handler raised exactly that error. A real
        # subprocess (like scan/eval already use) sidesteps it.
        import tempfile
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "generate_cover_letter.py")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(payload, f)
            payload_path = f.name
        try:
            proc = subprocess.run(
                [sys.executable, script, "--payload", payload_path], cwd=base_path,
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            self.call_from_thread(self._on_cl_pdf_error, "PDF render timed out after 120s")
            return
        finally:
            os.unlink(payload_path)
        if proc.returncode != 0:
            self.call_from_thread(self._on_cl_pdf_error, proc.stdout.strip()[-500:]
                                   or proc.stderr.strip()[-500:] or "unknown error")
            return
        m = re.search(r"Cover letter PDF: (.+)", proc.stdout)
        self.call_from_thread(self._on_cl_pdf_done, m.group(1) if m else proc.stdout.strip())

    def _on_cl_pdf_done(self, pdf_path):
        self.query_one("#cl_angles_header", Static).update("Cover letter approved and rendered")
        self.query_one("#cl_angles_body", Static).update(f"Saved: {pdf_path}")
        self.query_one("#cl_angles_footer", Static).update("Esc back to pipeline")

    def _on_cl_pdf_error(self, message):
        self.query_one("#cl_angles_body", Static).update(f"PDF generation failed: {message}")
        self.query_one("#cl_angles_footer", Static).update("Esc back to pipeline")

    def start_email_draft(self):
        self.query_one("#cl_angles_footer", Static).update("Drafting email...")
        self._email_worker(self.path, self.cl_jd_input)

    @work(thread=True)
    def _email_worker(self, base_path, jd_input):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "application_drafts.py")
        try:
            proc = subprocess.run(
                [sys.executable, script, "--email", jd_input, "--json"], cwd=base_path,
                capture_output=True, text=True, timeout=180,
            )
            result = json.loads(proc.stdout)
        except Exception:
            return
        if "error" not in result:
            self.call_from_thread(self._on_email_ready, result)

    def _on_email_ready(self, result):
        self.cl_email_draft = result
        self.render_cl_angles()

    def action_run_scan(self):
        if self.screen_mode != "pipeline" or self.search_mode or self.columns_open \
                or self.overlay_open:
            return
        self.toast = None
        if not os.path.exists(self.portals_yml_path):
            self.toast = "No portals.yml found — press P to set up target roles/companies first."
            self.render_all()
            return

        self.set_screen("scan_results")
        self.query_one("#scan_header", Static).update(
            "Scanning your tracked companies and job boards..."
        )
        self.query_one("#scan_body", Static).update(
            "This can take a few minutes if jobspy is enabled — some sites (Glassdoor "
            "especially) rate-limit and get retried per search keyword. The scan keeps "
            "running even if you press Esc to go back; results land here when it's done."
        )
        self.query_one("#scan_footer", Static).update("Esc back to pipeline (scan continues)")
        self._scan_worker(self.path)

    SCAN_TIMEOUT_SECONDS = 300

    @work(thread=True)
    def _scan_worker(self, base_path):
        # Runs scan.py as a real subprocess, not just an in-process worker
        # thread. Confirmed by direct testing: the identical jobspy call
        # that finishes in ~2s standalone hung indefinitely (9+ minutes,
        # never erroring, near-zero CPU — a genuine block, not a slow
        # network call) when run inside a Textual @work(thread=True) worker
        # thread instead of a process's own main thread — an interaction
        # with jobspy's tls_client dependency, not a network issue. A
        # subprocess sidesteps it entirely and lets us enforce a hard
        # timeout so a hang can never freeze the scan feature again.
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan.py")
        try:
            proc = subprocess.run(
                [sys.executable, script, "--json"], cwd=base_path,
                capture_output=True, text=True, timeout=self.SCAN_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            self.call_from_thread(
                self._on_scan_error,
                f"timed out after {self.SCAN_TIMEOUT_SECONDS}s — try disabling slower "
                f"jobspy sites (Glassdoor in particular) in the P portals editor"
            )
            return

        if proc.returncode != 0 and not proc.stdout.strip():
            self.call_from_thread(self._on_scan_error, proc.stderr.strip()[-500:] or "unknown error")
            return
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            self.call_from_thread(self._on_scan_error, proc.stderr.strip()[-500:] or "bad scan output")
            return
        if "error" in result:
            self.call_from_thread(self._on_scan_error, result["error"])
            return
        self.call_from_thread(self._on_scan_complete, result)

    def _load_scan_categories(self):
        """Category tabs on the scan results screen come straight from
        portals.yml's title_filter.positive — the same keywords already
        driving what gets matched in the first place, so tabs always
        reflect whatever roles are actually configured, not a fixed list."""
        try:
            data = load_portals(self.portals_yml_path)
            positive = data["title_filter"]["positive"]
        except Exception:
            positive = []
        self.scan_categories = ["ALL"] + positive
        self.scan_category_index = 0

    def filtered_scan_results(self):
        if self.scan_category_index == 0:
            return self.scan_results
        keyword = self.scan_categories[self.scan_category_index]
        return [e for e in self.scan_results if title_matches(e["title"], [keyword])]

    def _on_scan_complete(self, result):
        self.scan_summary = result
        # Show the full persisted pending list (data/pipeline.md), not just
        # this run's new additions — that file is the durable, reopenable
        # store; a scan just adds to it. Anything still pending from an
        # earlier session shows up here too, not only what changed today.
        self.scan_results = sorted(load_pending_pipeline(self.path),
                                    key=lambda e: e["posted_at"], reverse=True)
        self._load_scan_categories()
        self.scan_cursor = 0
        self.set_screen("scan_results")
        self.render_scan_results()

    def action_open_pending_queue(self):
        """Reopens the persisted pending list (data/pipeline.md) without
        running a new scan — free, instant, works across sessions."""
        if self.screen_mode != "pipeline" or self.search_mode or self.columns_open \
                or self.overlay_open:
            return
        self.toast = None
        self.scan_summary = {"scanned_companies": 0, "total_found": 0, "unreachable": []}
        self.scan_results = sorted(load_pending_pipeline(self.path),
                                    key=lambda e: e["posted_at"], reverse=True)
        self._load_scan_categories()
        self.scan_cursor = 0
        self.set_screen("scan_results")
        self.render_scan_results()

    def _on_scan_error(self, message):
        self.set_screen("pipeline")
        self.toast = f"Scan failed: {message}"
        self.render_all()

    def render_scan_results(self):
        s = self.scan_summary
        header = (f"Scan results — {s['scanned_companies']} companies scanned, "
                  f"{s['total_found']} jobs found, {len(self.scan_results)} pending")
        if s["unreachable"]:
            header += f"\n⚠ unreachable: {', '.join(s['unreachable'])}"

        tab_bits = []
        for i, cat in enumerate(self.scan_categories):
            count = len(self.scan_results) if cat == "ALL" else len(
                [e for e in self.scan_results if title_matches(e["title"], [cat])]
            )
            marker = "[" if i == self.scan_category_index else " "
            end = "]" if i == self.scan_category_index else " "
            tab_bits.append(f"{marker}{cat} ({count}){end}")
        header += "\n" + " ".join(tab_bits)
        self.query_one("#scan_header", Static).update(header)

        rows = self.filtered_scan_results()
        self.scan_cursor = min(self.scan_cursor, max(len(rows) - 1, 0))
        if not rows:
            body = "Nothing in this category."
        else:
            lines = []
            for row, e in enumerate(rows):
                marker = ">" if row == self.scan_cursor else " "
                posted = f" | posted: {e['posted_at']}" if e["posted_at"] else ""
                lines.append(f"{marker} {e['company']} | {e['title']} | {e['location']}{posted}")
            body = "\n".join(lines)
        self.query_one("#scan_body", Static).update(body)
        self.query_one("#scan_footer", Static).update(
            "←→/hl category  ↑↓/jk nav  Enter/o open URL  e evaluate  a add to tracker  "
            "x discard  Esc back"
        )

    def discard_scan_result(self):
        rows = self.filtered_scan_results()
        if not rows:
            return
        entry = rows[self.scan_cursor]
        remove_pipeline_entry(self.path, entry["url"])
        self.scan_results = [e for e in self.scan_results if e["url"] != entry["url"]]
        self.render_scan_results()

    def _remove_scan_result_by_url(self, url):
        """Shared by add/evaluate: once an entry has been promoted into
        the tracker, it should disappear from the pending list — both the
        in-memory one shown right now, and the persisted pipeline.md, so
        it doesn't come back next time the queue is reopened."""
        remove_pipeline_entry(self.path, url)
        for i, e in enumerate(self.scan_results):
            if e["url"] == url:
                del self.scan_results[i]
                break
        self.scan_cursor = min(self.scan_cursor, max(len(self.scan_results) - 1, 0))

    def open_scan_result(self):
        rows = self.filtered_scan_results()
        if not rows:
            return
        webbrowser.open(rows[self.scan_cursor]["url"])

    def evaluate_scan_result(self):
        """Evaluating a scan result is the actual step that promotes it
        into the real tracker (data/applications.md) — being in
        data/pipeline.md alone (what a scan writes) never shows up on the
        pipeline screen, which only ever reads applications.md."""
        rows = self.filtered_scan_results()
        if not rows:
            return
        env = load_env()
        if not self.has_configured_provider(env):
            self.query_one("#scan_footer", Static).update(
                "No AI provider configured — press Esc, then set one up first."
            )
            return
        entry = rows[self.scan_cursor]
        self.query_one("#scan_footer", Static).update(f"Evaluating {entry['company']}...")
        self._scan_eval_worker(self.path, entry["url"])

    def add_scan_result_to_tracker(self):
        """Lightweight alternative to evaluate_scan_result: adds the row
        straight to the tracker with no AI call — free, instant, no rate
        limit risk. Score is the "N/A" sentinel merge_tracker.py already
        recognizes for backfilled/no-evaluation entries; status Evaluated
        (there's no better canonical fit for "on my radar, not scored")."""
        rows = self.filtered_scan_results()
        if not rows:
            return
        entry = rows[self.scan_cursor]
        report_num = self._next_report_number(self.path)
        # The URL itself never contains "|" — the earlier bug was a "|"
        # *separator* character added around it, which is what broke the
        # markdown table's column count (confirmed by testing: the row
        # wrote fine but then failed to parse back out, showing 0 offers
        # on the pipeline screen). Storing the bare URL is safe, and keeps
        # it retrievable later for the row-actions menu's Evaluate option.
        notes = entry["url"]
        fields = [str(report_num), entry.get("posted_at") or "", entry["company"],
                  entry["title"], "Evaluated", "N/A", "❌", "", notes]
        additions_dir = os.path.join(self.path, "batch", "tracker-additions")
        os.makedirs(additions_dir, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", entry["company"].lower()).strip("-") or "unknown"
        with open(os.path.join(additions_dir, f"{report_num}-{slug}.tsv"), "w", encoding="utf-8") as f:
            f.write("\t".join(fields) + "\n")

        merge_error = self._run_merge_tracker(self.path)
        self.rows = load_rows(self.path)
        if merge_error:
            self.query_one("#scan_footer", Static).update(f"Added but merge failed: {merge_error}")
        else:
            self._remove_scan_result_by_url(entry["url"])
            self.query_one("#scan_footer", Static).update(
                f"Added to tracker: {entry['company']} — {entry['title']} (no score yet)"
            )
        self.render_scan_results()

    def _next_report_number(self, base_path):
        reports_dir = os.path.join(base_path, "reports")
        numbers = []
        if os.path.exists(reports_dir):
            for name in os.listdir(reports_dir):
                m = re.match(r"^(\d+)-", name)
                if m:
                    numbers.append(int(m.group(1)))
        additions_dir = os.path.join(base_path, "batch", "tracker-additions")
        if os.path.exists(additions_dir):
            for name in os.listdir(additions_dir):
                m = re.match(r"^(\d+)-", name)
                if m:
                    numbers.append(int(m.group(1)))
        return (max(numbers) + 1) if numbers else 1

    @work(thread=True)
    def _scan_eval_worker(self, base_path, url):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evaluate.py")
        try:
            proc = subprocess.run(
                [sys.executable, script, url, "--json"], cwd=base_path,
                capture_output=True, text=True, timeout=self.EVAL_TIMEOUT_SECONDS,
            )
            result = json.loads(proc.stdout)
        except Exception as e:
            self.call_from_thread(self._on_scan_eval_done, f"Evaluation failed: {e}")
            return
        if "error" in result:
            self.call_from_thread(self._on_scan_eval_done, f"Evaluation failed: {result['error']}")
            return
        data = result["data"]
        merge_error = self._run_merge_tracker(base_path)
        if merge_error:
            message = f"Evaluated ({data.get('score')}/5) but merge into tracker failed: {merge_error}"
        else:
            message = f"Added to tracker: {data.get('company')} — {data.get('score')}/5"
        self.call_from_thread(self._on_scan_eval_done, message, url if not merge_error else None)

    def _on_scan_eval_done(self, message, processed_url=None):
        self.rows = load_rows(self.path)
        if processed_url:
            self._remove_scan_result_by_url(processed_url)
        if self.screen_mode == "scan_results":
            if processed_url:
                self.render_scan_results()
            self.query_one("#scan_footer", Static).update(message)

    def action_open_status_overlay(self):
        if self.status_overlay_open or self.row_menu_open \
                or self.screen_mode not in ("pipeline", "report"):
            return
        self.toast = None
        if self.screen_mode == "pipeline":
            rows = self.visible_rows()
            if not rows:
                return
            current_row = rows[min(self.selected, len(rows) - 1)]
        else:
            current_row = self.report_row
        self.status_overlay_return = self.screen_mode
        self.status_cursor = (CANONICAL_STATES.index(current_row["status"])
                               if current_row["status"] in CANONICAL_STATES else 0)
        self.status_overlay_open = True
        self.query_one("#status_overlay").display = True
        self.render_status_overlay()

    def open_url_for_row(self, row):
        url = self.resolve_row_url(row)
        if url:
            webbrowser.open(url)

    def action_open_url(self):
        if self.screen_mode != "pipeline" or self.search_mode or self.columns_open \
                or self.overlay_open:
            return
        self.toast = None
        rows = self.visible_rows()
        if not rows:
            return
        self.open_url_for_row(rows[min(self.selected, len(rows) - 1)])

    def action_cycle_sort(self):
        if self.screen_mode != "pipeline" or self.overlay_open:
            return
        self.toast = None
        self.sort_index = (self.sort_index + 1) % len(SORT_MODES)
        self.render_all()

    def action_toggle_view(self):
        if self.screen_mode != "pipeline" or self.overlay_open:
            return
        self.toast = None
        self.grouped = not self.grouped
        self.render_all()

    def action_start_search(self):
        if self.screen_mode != "pipeline" or self.overlay_open:
            return
        self.toast = None
        self.search_mode = True
        self.search_query = ""
        self.render_all()

    def action_toggle_columns(self):
        if self.screen_mode != "pipeline" or self.overlay_open:
            return
        self.toast = None
        self.columns_open = not self.columns_open
        self.render_all()

    def action_open_pdf(self):
        if self.screen_mode != "pipeline" or self.search_mode or self.columns_open \
                or self.overlay_open:
            return
        rows = self.visible_rows()
        if not rows:
            return
        row = rows[min(self.selected, len(rows) - 1)]
        entry = load_pdf_index(self.path).get(str(row["id"]))
        if not entry or not entry["pdf"]:
            self.toast = "No CV PDF found for this application — generate one with /careeropsil pdf"
            self.render_all()
            return
        self.toast = None
        shell_open(os.path.join(self.path, entry["pdf"]))
        self.render_all()

    def regen_pdf_for_row(self, row):
        entry = load_pdf_index(self.path).get(str(row["id"]))
        if not entry or not entry.get("html"):
            self.toast = "No source HTML found for this application — run /careeropsil pdf first"
            self.render_all()
            return

        html_path = os.path.join(self.path, entry["html"])
        pdf_path = os.path.join(self.path, entry["pdf"])
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generate_pdf.py")
        result = subprocess.run(
            [sys.executable, script, html_path, pdf_path,
             f"--format={entry['format']}", f"--report={row['id']}"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            shell_open(pdf_path)
            self.toast = f"PDF regenerated and opened: {os.path.basename(pdf_path)}"
        else:
            stderr_line = result.stderr.strip().splitlines()[0] if result.stderr.strip() else "unknown error"
            self.toast = f"PDF regeneration failed: {stderr_line}"
        self.render_all()

    def action_regen_pdf(self):
        if self.screen_mode != "pipeline" or self.search_mode or self.columns_open \
                or self.overlay_open:
            return
        rows = self.visible_rows()
        if not rows:
            return
        self.regen_pdf_for_row(rows[min(self.selected, len(rows) - 1)])

    def action_quit_app(self):
        if self.overlay_open:
            return
        self.exit()

    def on_key(self, event):
        if self.status_overlay_open:
            # prevent_default() is essential here, not just event.stop():
            # Textual calls both this on_key() (Dashboard, the subclass)
            # and App's own _on_key() (the base class, which resolves
            # BINDINGS) for the same keypress. Without prevent_default(),
            # confirmed by testing that e.g. "enter" here would ALSO fire
            # the globally-bound enter action afterward, using whatever
            # state this handler just left behind.
            event.prevent_default()
            if event.key in ("escape", "q"):
                self.status_overlay_open = False
                self.query_one("#status_overlay").display = False
            elif event.key in ("j", "down"):
                self.status_cursor = min(self.status_cursor + 1, len(CANONICAL_STATES) - 1)
                self.render_status_overlay()
            elif event.key in ("k", "up"):
                self.status_cursor = max(self.status_cursor - 1, 0)
                self.render_status_overlay()
            elif event.key == "enter":
                new_status = CANONICAL_STATES[self.status_cursor]
                if self.status_overlay_return == "pipeline":
                    rows = self.visible_rows()
                    target = rows[min(self.selected, len(rows) - 1)]
                else:
                    target = self.report_row
                self.write_status(target, new_status)
                self.rows = load_rows(self.path)
                if self.status_overlay_return == "report":
                    self.report_row = next(
                        (r for r in self.rows if r["id"] == target["id"]), target
                    )
                self.status_overlay_open = False
                self.query_one("#status_overlay").display = False
            else:
                return
            if not self.status_overlay_open:
                if self.status_overlay_return == "pipeline":
                    self.render_all()
                else:
                    self.render_report()
            event.stop()
        elif self.row_menu_open:
            event.prevent_default()
            if event.key in ("escape", "q"):
                self.row_menu_open = False
                self.query_one("#row_menu_overlay").display = False
                self.render_all()
            elif event.key in ("j", "down"):
                self.row_menu_cursor = min(self.row_menu_cursor + 1, len(self.row_menu_options) - 1)
                self.render_row_menu()
            elif event.key in ("k", "up"):
                self.row_menu_cursor = max(self.row_menu_cursor - 1, 0)
                self.render_row_menu()
            elif event.key == "enter":
                row = self.row_menu_row
                _label, action_key = self.row_menu_options[self.row_menu_cursor]
                self.row_menu_open = False
                self.query_one("#row_menu_overlay").display = False
                if action_key == "report":
                    self.open_report_for_row(row)
                elif action_key == "url":
                    self.open_url_for_row(row)
                    self.render_all()
                elif action_key == "resume":
                    self.regen_pdf_for_row(row)
                elif action_key == "evaluate":
                    self.start_evaluation(self.resolve_row_url(row))
                elif action_key == "status":
                    self.action_open_status_overlay()
                else:
                    self.render_all()
            event.stop()
        elif self.screen_mode == "setup_provider":
            if event.key == "escape":
                has_cv = os.path.exists(os.path.join(self.path, "cv.md"))
                if has_cv:
                    self.set_screen("pipeline")
                    self.render_all()
                else:
                    self.set_screen("setup_cv")
                    self.render_setup_cv()
            elif event.key in ("j", "down"):
                self.provider_setup_cursor = min(self.provider_setup_cursor + 1,
                                                  len(self.PROVIDER_CHOICES) - 1)
                self.render_setup_provider()
            elif event.key in ("k", "up"):
                self.provider_setup_cursor = max(self.provider_setup_cursor - 1, 0)
                self.render_setup_provider()
            elif event.key == "enter":
                self.set_screen("setup_key")
                self.render_setup_key()
            event.stop()
        elif self.screen_mode == "setup_key":
            if event.key == "escape":
                has_cv = os.path.exists(os.path.join(self.path, "cv.md"))
                if has_cv:
                    self.set_screen("pipeline")
                    self.render_all()
                else:
                    self.set_screen("setup_cv")
                    self.render_setup_cv()
                event.stop()
            # all other keys fall through to the focused Input widget normally
        elif self.screen_mode == "setup_cv":
            if event.key == "escape":
                self.set_screen("pipeline")
                self.rows = load_rows(self.path)
                self.render_all()
                event.stop()
            elif getattr(self, "_cv_parse_done", False):
                self._cv_parse_done = False
                self.set_screen("pipeline")
                self.rows = load_rows(self.path)
                self.render_all()
                event.stop()
            # otherwise fall through to the focused Input widget normally
        elif self.screen_mode == "portals":
            if self.portals_edit_mode is not None:
                if event.key == "escape":
                    self.portals_edit_mode = None
                    self.portals_edit_target = None
                    inp = self.query_one("#portals_input", Input)
                    inp.value = ""
                    self.screen.set_focus(None)
                    self.render_portals()
                    event.stop()
                # otherwise fall through to the focused Input widget normally
            else:
                if event.key == "escape":
                    self.set_screen("pipeline")
                    self.render_all()
                elif event.key in ("j", "down"):
                    self.portals_cursor = min(self.portals_cursor + 1, len(self.portals_items) - 1)
                    self.render_portals()
                elif event.key in ("k", "up"):
                    self.portals_cursor = max(self.portals_cursor - 1, 0)
                    self.render_portals()
                elif event.key == "a":
                    self.start_portals_add()
                elif event.key == "enter":
                    self.start_portals_edit()
                elif event.key == "x":
                    self.delete_portals_item()
                elif event.key == "space":
                    self.toggle_portals_company()
                elif event.key == "s":
                    self.save_portals_file()
                event.stop()
        elif self.screen_mode == "scan_results":
            if event.key == "escape":
                self.set_screen("pipeline")
                self.rows = load_rows(self.path)
                self.render_all()
            elif event.key in ("j", "down"):
                rows = self.filtered_scan_results()
                if rows:
                    self.scan_cursor = min(self.scan_cursor + 1, len(rows) - 1)
                self.render_scan_results()
            elif event.key in ("k", "up"):
                self.scan_cursor = max(self.scan_cursor - 1, 0)
                self.render_scan_results()
            elif event.key in ("h", "left"):
                self.scan_category_index = (self.scan_category_index - 1) % len(self.scan_categories)
                self.scan_cursor = 0
                self.render_scan_results()
            elif event.key in ("l", "right"):
                self.scan_category_index = (self.scan_category_index + 1) % len(self.scan_categories)
                self.scan_cursor = 0
                self.render_scan_results()
            elif event.key in ("enter", "o"):
                self.open_scan_result()
            elif event.key == "e":
                self.evaluate_scan_result()
            elif event.key == "a":
                self.add_scan_result_to_tracker()
            elif event.key == "x":
                self.discard_scan_result()
            event.stop()
        elif self.screen_mode == "evaluate_input":
            if event.key == "escape":
                self.set_screen("pipeline")
                self.render_all()
                event.stop()
            # otherwise fall through to the focused Input widget normally
        elif self.screen_mode == "evaluate_result":
            if event.key == "escape":
                self.set_screen("pipeline")
                self.rows = load_rows(self.path)
                self.render_all()
            event.stop()
        elif self.screen_mode == "cover_letter_input":
            if event.key == "escape":
                self.set_screen("pipeline")
                self.render_all()
                event.stop()
            # otherwise fall through to the focused Input widget normally
        elif self.screen_mode == "cover_letter_angles":
            if event.key == "escape":
                self.set_screen("pipeline")
                self.rows = load_rows(self.path)
                self.render_all()
            elif self.cl_angles_data and event.key in ("j", "down"):
                n = len(self.cl_angles_data["angles"])
                self.cl_angles_cursor = min(self.cl_angles_cursor + 1, n - 1)
                self.render_cl_angles()
            elif self.cl_angles_data and event.key in ("k", "up"):
                self.cl_angles_cursor = max(self.cl_angles_cursor - 1, 0)
                self.render_cl_angles()
            elif self.cl_angles_data and event.key == "enter":
                self.approve_cl_angle()
            elif self.cl_angles_data and event.key == "m":
                self.start_email_draft()
            event.stop()
        elif self.screen_mode == "help":
            if event.key == "escape":
                self.set_screen("pipeline")
                self.render_all()
            event.stop()
        elif self.screen_mode == "ai_setup":
            if event.key == "escape":
                self.set_screen("pipeline")
                self.rows = load_rows(self.path)
                self.render_all()
                event.stop()
            # otherwise fall through to the focused Input widget normally
        elif self.screen_mode == "report":
            if event.key == "escape":
                self.set_screen("pipeline")
                self.render_all()
            elif event.key == "g":
                self.query_one("#report_scroll").scroll_home()
            elif event.key == "G":
                self.query_one("#report_scroll").scroll_end()
            elif event.key == "pageup":
                self.query_one("#report_scroll").scroll_page_up()
            elif event.key == "pagedown":
                self.query_one("#report_scroll").scroll_page_down()
            else:
                return
            event.stop()
        elif self.screen_mode == "progress":
            if event.key == "escape":
                self.set_screen("pipeline")
                self.render_all()
            elif event.key == "pageup":
                self.query_one("#progress_scroll").scroll_page_up()
            elif event.key == "pagedown":
                self.query_one("#progress_scroll").scroll_page_down()
            else:
                return
            event.stop()
        elif self.search_mode:
            if event.key == "escape":
                self.search_mode = False
                self.search_query = ""
            elif event.key == "enter":
                self.search_mode = False
            elif event.key == "ctrl+u":
                self.search_query = ""
            elif event.key == "backspace":
                self.search_query = self.search_query[:-1]
            elif event.character and event.character.isprintable():
                self.search_query += event.character
            else:
                return
            self.render_all()
            event.stop()
        elif self.columns_open:
            if event.key in ("escape", "C"):
                self.columns_open = False
            elif event.key == "space":
                col = OPTIONAL_COLUMNS[self.columns_cursor]
                if col in self.visible_columns:
                    self.visible_columns.discard(col)
                else:
                    self.visible_columns.add(col)
            elif event.key in ("j", "down"):
                self.columns_cursor = min(self.columns_cursor + 1, len(OPTIONAL_COLUMNS) - 1)
            elif event.key in ("k", "up"):
                self.columns_cursor = max(self.columns_cursor - 1, 0)
            else:
                return
            self.render_all()
            event.stop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=".")
    parser.add_argument("--lang", default="en")
    args = parser.parse_args()
    Dashboard(args.path).run()


if __name__ == "__main__":
    main()
