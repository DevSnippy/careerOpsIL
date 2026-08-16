#!/usr/bin/env python3
"""build_cv_latex: build a .tex file from structured JSON.

No required-field validation — an empty `{}` payload produces a
mostly-empty document rather than erroring. The top-level JSON key names
below (education/experience/projects/awards/skills) are a best-effort
input schema, only lightly tested against a non-empty payload.
"""
import json
import os
import sys
import tempfile

LATEX_ESCAPE = str.maketrans({
    "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
})


def escape(s):
    return str(s).translate(LATEX_ESCAPE)


def build_tex(data):
    education = data.get("education", [])
    experience = data.get("experience", [])
    projects = data.get("projects", [])
    awards = data.get("awards", [])
    skills = data.get("skills", {})

    total_bullets = sum(len(e.get("bullets", [])) for e in experience)
    total_bullets += sum(len(p.get("bullets", [])) for p in projects)

    lines = [r"\documentclass{article}", r"\begin{document}"]
    lines.append(r"\section{Education}")
    for e in education:
        lines.append(escape(e.get("institution", "")))
    lines.append(r"\section{Work Experience}")
    for e in experience:
        lines.append(escape(e.get("title", "")))
        for b in e.get("bullets", []):
            lines.append(r"\resumeItem{" + escape(b) + "}")
    lines.append(r"\section{Projects}")
    for p in projects:
        lines.append(escape(p.get("name", "")))
        for b in p.get("bullets", []):
            lines.append(r"\resumeItem{" + escape(b) + "}")
    lines.append(r"\section{Skills}")
    for category, items in skills.items():
        lines.append(escape(category) + ": " + escape(", ".join(items)))
    for a in awards:
        lines.append(escape(a.get("name", "")))
    lines.append(r"\end{document}")

    counts = {
        "educationEntries": len(education),
        "experienceEntries": len(experience),
        "projectEntries": len(projects),
        "awardEntries": len(awards),
        "skillCategories": len(skills),
        "totalBullets": total_bullets,
    }
    return "\n".join(lines), counts


def main(argv):
    if argv and argv[0] == "--test":
        data = {
            "education": [{"institution": "Test University"}],
            "experience": [{"title": "Engineer", "bullets": ["Did a thing"]}],
            "projects": [{"name": "Test Project", "bullets": ["Built it"]}],
            "awards": [{"name": "Award A"}, {"name": "Award B"}],
            "skills": {"Languages": ["Python"], "Tools": ["Git"]},
        }
        tex, counts = build_tex(data)
        fd, path = tempfile.mkstemp(prefix="build-cv-latex-test", suffix=".tex")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(tex)
        size_kb = os.path.getsize(path) / 1024
        os.remove(path)
        print(json.dumps({
            "status": "self-test-passed",
            "file": "build-cv-latex-test.tex",
            "path": path,
            "sizeKB": round(size_kb, 1),
            "counts": counts,
        }, indent=2))
        return 0

    if len(argv) < 2:
        print("Usage: python build_cv_latex.py <input.json> <output.tex>")
        print("       python build_cv_latex.py --test")
        return 1

    input_json, output_tex = argv[0], argv[1]
    with open(input_json, encoding="utf-8") as f:
        data = json.load(f)

    tex, counts = build_tex(data)
    with open(output_tex, "w", encoding="utf-8") as f:
        f.write(tex)
    size_kb = os.path.getsize(output_tex) / 1024
    print(json.dumps({
        "file": os.path.basename(output_tex),
        "path": os.path.abspath(output_tex),
        "sizeKB": round(size_kb, 1),
        "counts": counts,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
