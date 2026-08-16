#!/usr/bin/env python3
"""pdf_backend: shared HTML->PDF rendering + manifest logic for the PDF suite.
Uses Playwright's headless Chromium for consistent page-count/sizing behavior.
"""
import os
import re
from datetime import date

PAGE_FORMATS = {"a4": "A4", "letter": "Letter"}
PDF_INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pdf-index.tsv")


def render_html_to_pdf(html_path, output_path, page_format="a4"):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto("file://" + os.path.abspath(html_path))
        page.pdf(path=output_path, format=PAGE_FORMATS.get(page_format.lower(), "A4"),
                 print_background=True)
        browser.close()


def count_pdf_pages(pdf_path):
    with open(pdf_path, "rb") as f:
        data = f.read()
    return len(re.findall(rb"/Type\s*/Page[^s]", data)) or 1


def append_pdf_index(report, pdf_path, html_path, page_format, report_given):
    os.makedirs(os.path.dirname(PDF_INDEX_PATH), exist_ok=True)
    is_new = not os.path.exists(PDF_INDEX_PATH)
    with open(PDF_INDEX_PATH, "a", encoding="utf-8") as f:
        if is_new:
            f.write("# report\tpdf\thtml\tformat\tdate — written by generate-pdf, do not edit\n")
        f.write(f"{report or ''}\t{pdf_path}\t{html_path or ''}\t{page_format.lower()}\t"
                f"{date.today().isoformat()}\n")
    suffix = "" if report_given else " (no --report given)"
    print(f"🔗 Manifest: data/pdf-index.tsv updated{suffix}")
