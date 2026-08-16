#!/usr/bin/env python3
"""generate_latex: validate and compile a .tex CV file.

Structural validation (>=4 \\section{} blocks) runs and gates compilation,
with a JSON issue report on failure. The LaTeX macros counted here
(\\resumeItem, \\resumeSubheading, \\resumeProjectHeading) are common,
publicly-documented resume-template conventions, used as a best-effort
match for the resumeItems/subheadings/projectHeadings count fields.
Compilation uses the external `tectonic` binary; the JSON output shape on
a successful compile is unconfirmed.
"""
import json
import os
import re
import subprocess
import sys

MIN_SECTIONS = 4


def main(argv):
    if not argv:
        print("Usage: python generate_latex.py <input.tex> [output.pdf]")
        return 1

    input_tex = argv[0]
    output_pdf = argv[1] if len(argv) > 1 else os.path.splitext(input_tex)[0] + ".pdf"

    try:
        with open(input_tex, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        print(f"Error reading {input_tex}: {e}")
        return 1

    sections = len(re.findall(r"\\section\{", content))
    counts = {
        "resumeItems": len(re.findall(r"\\resumeItem\{", content)),
        "subheadings": len(re.findall(r"\\resumeSubheading\{", content)),
        "projectHeadings": len(re.findall(r"\\resumeProjectHeading\{", content)),
    }
    size_kb = os.path.getsize(input_tex) / 1024

    issues = []
    if sections < MIN_SECTIONS:
        issues.append(
            f"Expected at least {MIN_SECTIONS} \\section{{}} blocks (Education, Work "
            f"Experience, Projects, Skills — or localized equivalents), found {sections}"
        )

    if issues:
        print(json.dumps({
            "file": os.path.basename(input_tex),
            "path": os.path.abspath(input_tex),
            "sizeKB": round(size_kb, 1),
            "counts": counts,
            "issues": issues,
            "valid": False,
            "compileOnly": False,
        }, indent=2))
        return 1

    try:
        result = subprocess.run(
            ["tectonic", "--outdir", os.path.dirname(os.path.abspath(output_pdf)) or ".",
             input_tex],
            capture_output=True, text=True, timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(json.dumps({
            "file": os.path.basename(input_tex),
            "path": os.path.abspath(input_tex),
            "sizeKB": round(size_kb, 1),
            "counts": counts,
            "issues": [f"compilation unavailable: {e}"],
            "valid": True,
            "compileOnly": False,
        }, indent=2))
        return 1

    ok = result.returncode == 0
    print(json.dumps({
        "file": os.path.basename(input_tex),
        "path": os.path.abspath(input_tex),
        "sizeKB": round(size_kb, 1),
        "counts": counts,
        "issues": [] if ok else [result.stderr.strip()[-500:]],
        "valid": True,
        "compileOnly": True,
    }, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
