#!/usr/bin/env python3
"""jd_similarity: compare two text files, decide reuse vs. regenerate.

SCOPE: this implements a word-overlap ratio (not Jaccard/Dice/length-ratio)
as a best-effort scoring approach — reproduces sane 0/1 endpoints and a
reasonable reuse-vs-regenerate threshold, but hasn't been tuned against a
large real-world sample yet.
"""
import json
import re
import sys

THRESHOLD = 0.5  # confirmed reuse at 0.75, regenerate at 0.2857 — unpinned exact boundary


def tokenize(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def similarity(a, b):
    wa, wb = tokenize(a), tokenize(b)
    if not wa and not wb:
        return 1.0
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def main(argv):
    if len(argv) < 2:
        print("Usage: python jd_similarity.py <new-jd.txt> <previous-jd-or-cv.txt>",
              file=sys.stderr)
        sys.exit(1)

    try:
        a = open(argv[0], encoding="utf-8").read()
        b = open(argv[1], encoding="utf-8").read()
    except OSError as e:
        print(f"Unable to read input files: {e}", file=sys.stderr)
        sys.exit(1)

    score = similarity(a, b)
    if score == 1.0:
        decision, reason = "reuse", "high-similarity"
    elif score >= THRESHOLD:
        decision, reason = "reuse", "high-similarity"
    else:
        decision, reason = "regenerate", "low-similarity"

    print(json.dumps({"decision": decision, "score": score, "reason": reason}, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
