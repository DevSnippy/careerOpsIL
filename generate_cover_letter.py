#!/usr/bin/env python3
"""generate_cover_letter: render a cover-letter JSON payload to PDF.

Note: a `letter.body` payload key is accepted (no validation error) but is
NOT rendered anywhere. Do not "fix" this by guessing what it should do; the
real paragraph-content field was never identified.
"""
import html
import json
import os
import sys

from pdf_backend import append_pdf_index, count_pdf_pages, render_html_to_pdf

USAGE = ("Usage: python generate_cover_letter.py --payload payload.json "
         "[--out output/path.pdf] [--format letter|a4] [--report NNN]")

REQUIRED_LETTER = ["company", "role_title", "date", "opening", "profile_intro"]


def check_required(payload):
    # Confirmed check order: candidate (object) -> candidate.name -> letter
    # (object) -> letter.company -> letter.role_title -> letter.date ->
    # letter.opening -> letter.profile_intro. Interleaved, not grouped by
    # top-level key first.
    if "candidate" not in payload:
        return "payload.candidate"
    if "name" not in payload["candidate"]:
        return "candidate.name"
    if "letter" not in payload:
        return "payload.letter"
    for key in REQUIRED_LETTER:
        if key not in payload["letter"]:
            return f"letter.{key}"
    return None


def build_html(payload):
    c = payload["candidate"]
    letter = payload["letter"]
    e = html.escape

    contact_parts = [c[k] for k in ("location", "email", "phone") if c.get(k)]
    contact_line = f"<p>{e(' | '.join(contact_parts))}</p>" if contact_parts else ""

    lines = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>",
        f"<p><strong>{e(c['name'])}</strong></p>",
        contact_line,
        f"<h2>Cover Letter: {e(letter['role_title'])}</h2>",
        f"<p>{e(letter['company'])}</p>",
        f"<p>{e(letter['date'])}</p>",
    ]
    if letter.get("greeting"):
        lines.append(f"<p>{e(letter['greeting'])}</p>")
    lines.append(f"<p>{e(letter['opening'])}</p>")
    lines.append(f"<p>{e(letter['profile_intro'])}</p>")
    if letter.get("closing"):
        lines.append(f"<p>{e(letter['closing'])}</p>")
    lines.append("</body></html>")
    return "\n".join(l for l in lines if l)


def main(argv):
    payload_path = None
    out_path = None
    page_format = "a4"
    report = None

    i = 0
    while i < len(argv):
        if argv[i] == "--payload" and i + 1 < len(argv):
            payload_path = argv[i + 1]; i += 2
        elif argv[i] == "--out" and i + 1 < len(argv):
            out_path = argv[i + 1]; i += 2
        elif argv[i] == "--format" and i + 1 < len(argv):
            page_format = argv[i + 1]; i += 2
        elif argv[i] == "--report" and i + 1 < len(argv):
            report = argv[i + 1]; i += 2
        else:
            i += 1

    if not payload_path:
        print(USAGE)
        return 1

    with open(payload_path, encoding="utf-8") as f:
        payload = json.load(f)

    missing = check_required(payload)
    if missing:
        print(f"ERROR generating cover letter PDF:\nMissing required field: {missing}")
        return 1

    if not out_path:
        slug = payload["letter"]["company"].lower().replace(" ", "-")
        out_path = os.path.join("output", f"{slug}-cover.pdf")

    project_root = os.path.dirname(os.path.abspath(__file__))
    resolved_output = os.path.abspath(out_path)

    html_content = build_html(payload)
    tmp_html = resolved_output + ".src.html"
    try:
        os.makedirs(os.path.dirname(resolved_output) or ".", exist_ok=True)
        with open(tmp_html, "w", encoding="utf-8") as f:
            f.write(html_content)
        render_html_to_pdf(tmp_html, resolved_output, page_format)
    except Exception as e:
        print(f"ERROR generating cover letter PDF:\n{e}")
        return 1
    finally:
        if os.path.exists(tmp_html):
            os.remove(tmp_html)

    pages = count_pdf_pages(resolved_output)
    size_kb = os.path.getsize(resolved_output) / 1024
    print(f"✅ PDF generated: {resolved_output}")
    print(f"📊 Pages: {pages}")
    print(f"📦 Size: {size_kb:.1f} KB")
    append_pdf_index(report, resolved_output, None, page_format, report_given=report is not None)
    print(f"\nCover letter PDF: {resolved_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
