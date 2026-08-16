#!/usr/bin/env python3
"""invite_match: extract signals from a pasted interview invite/rejection.

SCOPE: date extraction and phrase-based classification are confirmed and
implemented. Company/reqId/platform extraction and candidate ranking were
never successfully triggered during spec analysis (see spec §4) — stubbed
as null/[] rather than a guessed pattern.
"""
import json
import re
import sys

DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

INVITE_PHRASES = [
    "invite you to interview", "invited to interview", "schedule an interview",
    "move forward with your application", "would like to interview",
]
REJECTION_PHRASES = [
    "will not be moving forward", "decided to move forward with other candidates",
    "not selected", "pursue other candidates",
]


def classify(text):
    lower = text.lower()
    for phrase in INVITE_PHRASES:
        if phrase in lower:
            return "invite", [phrase]
    for phrase in REJECTION_PHRASES:
        if phrase in lower:
            return "rejection", [phrase]
    return "unknown", []


def extract_signals(text):
    date_match = DATE_RE.search(text)
    return {
        "company": None,  # not implemented — see module docstring
        "date": date_match.group(1) if date_match else None,
        "reqId": None,     # not implemented
        "platform": None,  # not implemented
    }


def main(argv):
    text = sys.stdin.read()
    signals = extract_signals(text)
    classification, matched = classify(text)

    result = {
        "signals": signals, "classification": classification,
        "matchedPhrases": matched, "phraseStrength": None, "candidates": [],
    }

    if "--summary" in argv:
        print()
        print("=" * 70)
        print("  Interview Invite / Rejection Matcher")
        print("=" * 70)
        print()
        print(f"  Classification:     {classification}")
        print(f"  Matched phrase(s):  {', '.join(matched) if matched else '(none)'}")
        print(f"  Extracted company:  {signals['company'] or '(not found)'}")
        print(f"  Extracted date:     {signals['date'] or '(not found)'}")
        print(f"  Extracted req ID:   {signals['reqId'] or '(not found)'}")
        print(f"  Extracted platform: {signals['platform'] or '(not found)'}")
        print()
        if not signals["company"]:
            print("  Could not find a company name in the invite text — "
                  "paste more context or check manually.")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
