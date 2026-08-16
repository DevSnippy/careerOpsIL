#!/usr/bin/env python3
"""generate_pdf: render an already-built HTML file to PDF."""
import os
import sys

from pdf_backend import append_pdf_index, count_pdf_pages, render_html_to_pdf

USAGE = ("Usage: python generate_pdf.py <input.html> <output.pdf> "
         "[--format=letter|a4] [--report=NNN] [--allow-reorder] [--max-pages=N] "
         "[--strict-pages]")

DEFAULT_PAGE_BUDGET = 2


def main(argv):
    if not argv:
        print(USAGE)
        return 0

    positional = [a for a in argv if not a.startswith("--")]
    flags = {}
    for a in argv:
        if a.startswith("--") and "=" in a:
            k, v = a[2:].split("=", 1)
            flags[k] = v
        elif a.startswith("--"):
            flags[a[2:]] = True

    if len(positional) < 2:
        print(USAGE)
        return 0

    input_html, output_pdf = positional[0], positional[1]
    page_format = flags.get("format", "a4")
    report = flags.get("report")
    max_pages = int(flags["max-pages"]) if "max-pages" in flags else DEFAULT_PAGE_BUDGET

    project_root = os.path.dirname(os.path.abspath(__file__))
    resolved_output = os.path.abspath(output_pdf)
    if os.path.commonpath([project_root, resolved_output]) != project_root:
        print(f"Refusing to write the PDF outside the project directory: {resolved_output}")
        return 1

    print(f"📄 Input:  {os.path.abspath(input_html)}")
    print(f"📁 Output: {resolved_output}")
    print(f"📏 Format: {page_format.upper()}")
    print(f"📐 Page budget: {max_pages} (warning only)")

    if not os.path.exists(input_html):
        print(f"❌ PDF generation failed: ENOENT: no such file or directory, "
              f"open '{input_html}'")
        return 1

    try:
        os.makedirs(os.path.dirname(resolved_output) or ".", exist_ok=True)
        render_html_to_pdf(input_html, resolved_output, page_format)
    except Exception as e:
        print(f"❌ PDF generation failed: {e}")
        return 1

    pages = count_pdf_pages(resolved_output)
    size_kb = os.path.getsize(resolved_output) / 1024
    print(f"✅ PDF generated: {resolved_output}")
    print(f"📊 Pages: {pages}")
    print(f"📦 Size: {size_kb:.1f} KB")
    append_pdf_index(report, resolved_output, os.path.abspath(input_html), page_format,
                      report_given=report is not None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
