#!/usr/bin/env python3
"""paste_reply: normalize a pasted/file-provided email into a reply candidate.
"""
import json
import os
import random
import sys
import time

CANDIDATES_PATH = os.path.join("data", "reply-candidates.json")


def parse_email(text):
    lines = text.split("\n")
    subject = ""
    sender = ""
    body_start = 0
    i = 0
    while i < len(lines) and (lines[i].startswith("Subject:") or lines[i].startswith("From:")):
        if lines[i].startswith("Subject:"):
            subject = lines[i][len("Subject:"):].strip()
        elif lines[i].startswith("From:"):
            sender = lines[i][len("From:"):].strip()
        i += 1
        body_start = i

    if subject or sender:
        while body_start < len(lines) and not lines[body_start].strip():
            body_start += 1
        body = "\n".join(lines[body_start:]).strip()
    else:
        body = text.strip()

    return subject, sender, body


def main(argv):
    if "--file" not in argv:
        print("Error: interactive mode requires a terminal (use --file <path> instead)",
              file=sys.stderr)
        sys.exit(1)

    path = argv[argv.index("--file") + 1]
    if not os.path.exists(path):
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    text = open(path, encoding="utf-8").read()
    subject, sender, body = parse_email(text)

    message_id = f"pasted-{int(time.time() * 1000)}-{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))}"
    snippet = body[:200]

    record = {"message_id": message_id, "from": sender, "subject": subject,
              "body_snippet": snippet, "signal": None}

    candidates = []
    if os.path.exists(CANDIDATES_PATH):
        candidates = json.loads(open(CANDIDATES_PATH, encoding="utf-8").read())
    candidates.append(record)
    os.makedirs(os.path.dirname(CANDIDATES_PATH), exist_ok=True)
    with open(CANDIDATES_PATH, "w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2, ensure_ascii=False)

    print("Appended a new reply candidate:")
    print(f"  message_id:   {message_id}")
    print(f"  from:         {sender or '(none)'}")
    print(f"  subject:      {subject or '(none)'}")
    print(f"  body_snippet: {snippet}")
    print()
    print(f"{CANDIDATES_PATH} now has {len(candidates)} candidate(s).")
    print("Next: run `python reply_watch.py` to classify and review this reply.")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
