#!/usr/bin/env python3
"""verify_cv_facts: flag unsupported metric/factual claims in a generated doc.

SCOPE: the extraction patterns (percentage/duration for metrics; "at X" /
"as a/the X" for employer/title) are a best-effort heuristic, not a
guaranteed-complete NLP pass — flag anything it misses rather than assuming
silence means clean.
"""
import json
import os
import re
import sys

METRIC_RE = re.compile(r"\b\d+(?:\.\d+)?%|\b\d+\s+(?:years?|months?|weeks?|days?)\b",
                        re.IGNORECASE)
EMPLOYER_RE = re.compile(
    r"\bat\s+([A-Z][A-Za-z0-9&.' -]{1,40}?)(?=[,.]|\s+(?:as|for|from|in)\b|$)")
TITLE_RE = re.compile(
    r"\bas\s+(?:a|an|the)\s+([A-Za-z][A-Za-z/-]{1,40}?)(?=[,.]|\s+(?:at|for|from|in)\b|$)",
    re.IGNORECASE)


def load_sources(paths):
    text = ""
    for p in paths:
        if os.path.exists(p):
            text += open(p, encoding="utf-8").read().lower() + "\n"
    return text


def main(argv):
    if not argv or argv[0].startswith("--"):
        print("Usage: python verify_cv_facts.py <generated-document> "
              "[--source path] [--config path] [--json]", file=sys.stderr)
        sys.exit(1)

    doc_path = argv[0]
    json_mode = "--json" in argv
    sources = ["cv.md", "article-digest.md"]
    if "--source" in argv:
        sources = [argv[argv.index("--source") + 1]]

    doc_text = open(doc_path, encoding="utf-8").read()
    source_text = load_sources(sources)

    invented = []
    for m in METRIC_RE.finditer(doc_text):
        value = m.group(0)
        if value.lower() not in source_text:
            invented.append(value)

    unsupported_facts = []
    for m in EMPLOYER_RE.finditer(doc_text):
        value = m.group(1).strip().lower()
        if value and value not in source_text:
            unsupported_facts.append({"kind": "employer", "value": value})
    for m in TITLE_RE.finditer(doc_text):
        value = m.group(1).strip().lower()
        if value and value not in source_text:
            unsupported_facts.append({"kind": "title", "value": value})

    verdict = "block" if (invented or unsupported_facts) else "pass"

    if json_mode:
        print(json.dumps({
            "verdict": verdict, "invented": invented, "unsupportedFacts": unsupported_facts,
            "forbidden": [], "warnings": [],
        }, indent=2, ensure_ascii=False))
        sys.exit(0 if verdict == "pass" else 1)

    name = os.path.basename(doc_path)
    if verdict == "pass":
        print(f"CV fact check passed: {name}")
        sys.exit(0)

    print(f"CV fact check failed: {name}")
    if invented:
        print()
        print("Metric-like claims absent from sources:")
        for v in invented:
            print(f"  - {v}")
    if unsupported_facts:
        print()
        print("Non-metric facts absent from sources:")
        for f in unsupported_facts:
            print(f"  - {f['kind']}: {f['value']}")
    print()
    print("Add real evidence to cv.md/article-digest.md, or allow a verified "
          "exception in config/cv-facts.json.")
    sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
