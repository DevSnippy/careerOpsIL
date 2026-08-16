#!/usr/bin/env python3
"""update_system: check for / dismiss update notices.

Scope note: only `check` and `dismiss` are implemented. `apply` and
`rollback` (real self-updating, e.g. via git) are a product decision for
later, not implemented here. The remote-version-lookup never makes a
network call yet — this is a best-effort placeholder for the JSON output
shape.
"""
import json
import os
import sys
from datetime import datetime, timezone

LOCAL_VERSION = "0.1.0"
REMOTE_VERSION = "0.1.0"  # unresolved mechanism — see module docstring
DISMISS_MARKER_PATH = ".update-dismissed"

USAGE = "Usage: python update_system.py [check|apply [--force]|rollback|dismiss]"


def cmd_check():
    if os.path.exists(DISMISS_MARKER_PATH):
        print(json.dumps({"status": "dismissed"}))
        return 0

    if REMOTE_VERSION is None:
        print(json.dumps({"status": "no-remote-version"}))
        return 0

    status = "up-to-date" if LOCAL_VERSION == REMOTE_VERSION else "update-available"
    print(json.dumps({"status": status, "local": LOCAL_VERSION, "remote": REMOTE_VERSION}))
    return 0


def cmd_dismiss():
    timestamp = datetime.now(timezone.utc).isoformat()
    with open(DISMISS_MARKER_PATH, "w", encoding="utf-8") as f:
        f.write(timestamp)
    print('Update check dismissed. Run "python update_system.py check" or say '
          '"check for updates" to re-enable.')
    return 0


def main(argv):
    if not argv:
        print(USAGE, file=sys.stderr)
        return 1

    subcommand = argv[0]
    if subcommand == "check":
        return cmd_check()
    if subcommand == "dismiss":
        return cmd_dismiss()
    if subcommand in ("apply", "rollback"):
        print(f"update-system {subcommand}: not implemented in this port "
              "(would perform real repository changes — out of scope; see "
              "module docstring)", file=sys.stderr)
        return 1

    print(USAGE, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
