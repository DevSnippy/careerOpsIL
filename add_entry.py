#!/usr/bin/env python3
"""add_entry: append a CV / article-digest entry from a JSON payload.
"""
import json
import os
import re
import sys

CV_PATH = "cv.md"
ARTICLE_DIGEST_PATH = "article-digest.md"

VALID_FLAGS = {"--dry-run", "--stdin", "--help", "-h"}

USAGE = (
    "Usage:\n"
    "  python add_entry.py <payload.json> [--dry-run]\n"
    "  python add_entry.py --stdin [--dry-run]\n"
    "  python add_entry.py --help                    "
    "# print this usage block and exit (-h is an alias)"
)

ARTICLE_DIGEST_HEADER = (
    "# Article Digest -- Proof Points\n\n"
    "Compact proof points from portfolio projects. Read at evaluation time.\n\n"
    "---\n\n"
)


def die_usage(code=1):
    print(USAGE, file=sys.stderr if code else sys.stdout)
    sys.exit(code)


def die(reason):
    print(f"add-entry: {reason}", file=sys.stderr)
    sys.exit(1)


def parse_args(argv):
    flags = set()
    positional = None
    unrecognized = []
    for tok in argv:
        if tok.startswith("-"):
            if tok in VALID_FLAGS:
                flags.add(tok)
            else:
                unrecognized.append(tok)
        else:
            positional = tok
    return flags, positional, unrecognized


def load_payload(flags, positional):
    if "--stdin" in flags:
        raw = sys.stdin.read()
    else:
        if positional is None:
            raw = sys.stdin.read()
        else:
            with open(positional, encoding="utf-8") as f:
                raw = f.read()
    return json.loads(raw)


def add_cv_entry(section, entry):
    text = open(CV_PATH, encoding="utf-8").read()
    lines = text.splitlines()
    heading_re = re.compile(r"^#+\s+" + re.escape(section) + r"\s*$")
    start = next((i for i, l in enumerate(lines) if heading_re.match(l.strip())), None)
    if start is None:
        die(f"payload.cv section not found in cv.md: {section}")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^#+\s+\S", lines[i].strip()):
            end = i
            break
    # insert before any trailing blank lines that precede the next heading
    insert_at = end
    while insert_at > start + 1 and lines[insert_at - 1].strip() == "":
        insert_at -= 1
    lines[insert_at:insert_at] = [entry]
    with open(CV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def add_article_digest_entry(entry):
    if not os.path.exists(ARTICLE_DIGEST_PATH):
        with open(ARTICLE_DIGEST_PATH, "w", encoding="utf-8") as f:
            f.write(ARTICLE_DIGEST_HEADER + entry + "\n")
        return "created"
    with open(ARTICLE_DIGEST_PATH, "a", encoding="utf-8") as f:
        f.write("\n---\n\n" + entry)
    return "added"


def main(argv):
    if not argv:
        die_usage(1)

    flags, positional, unrecognized = parse_args(argv)

    if "--help" in flags or "-h" in flags:
        die_usage(0)

    if unrecognized:
        print(
            f"add-entry: unrecognized flag(s): {', '.join(unrecognized)}. "
            f"Valid flags: --dry-run, --stdin, --help, -h",
            file=sys.stderr,
        )
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    dry_run = "--dry-run" in flags

    try:
        payload = load_payload(flags, positional)
    except Exception as exc:
        die(f"could not read/parse payload: {exc}")
        return

    if not isinstance(payload, dict) or not ("cv" in payload or "articleDigest" in payload):
        die("payload must include at least one of: cv, articleDigest")

    result = {"dryRun": dry_run}

    if "cv" in payload:
        cv = payload["cv"] if isinstance(payload["cv"], dict) else {}
        section = cv.get("section")
        entry = cv.get("entry")
        if not section or not entry:
            die("payload.cv requires { section, entry }")
        dedup_key = cv.get("dedupKey")
        if not dedup_key:
            die("payload.cv requires a non-empty dedupKey (used for dedup/idempotency)")
        if not os.path.exists(CV_PATH):
            die("cv.md not found — cannot add to a CV that does not exist")
        if not dry_run:
            add_cv_entry(section, entry)
        result["cv"] = {"status": "added", "section": section}

    if "articleDigest" in payload:
        ad = payload["articleDigest"] if isinstance(payload["articleDigest"], dict) else {}
        entry = ad.get("entry")
        if not entry:
            die("payload.articleDigest requires { entry }")
        dedup_key = ad.get("dedupKey")
        if not dedup_key:
            die("payload.articleDigest requires a non-empty dedupKey (used for dedup/idempotency)")
        exists = os.path.exists(ARTICLE_DIGEST_PATH)
        status = "added" if exists else "created"
        if not dry_run:
            status = add_article_digest_entry(entry)
        result["articleDigest"] = {"status": status}

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
