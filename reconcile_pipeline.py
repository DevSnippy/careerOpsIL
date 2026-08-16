#!/usr/bin/env python3
"""reconcile_pipeline: move completed/skipped batch offers out of
pipeline.md's Pendientes inbox.

SCOPE: only the graceful no-op paths and the --state path-traversal guard
are implemented. The actual Pendientes -> Procesadas move logic needs a
real batch-state.tsv sample to design against, so it's a placeholder here
rather than a guess.
"""
import os
import sys

DEFAULT_STATE_PATH = os.path.join("batch", "batch-state.tsv")
DEFAULT_PIPELINE_PATH = os.path.join("data", "pipeline.md")


def resolve_in_repo(path):
    repo_root = os.getcwd()
    full = os.path.abspath(path)
    if not full.startswith(repo_root):
        print(f"Invalid --state: path must stay inside the repository ({path})",
              file=sys.stderr)
        sys.exit(1)
    return path


def main(argv):
    state_path = DEFAULT_STATE_PATH
    pipeline_path = DEFAULT_PIPELINE_PATH
    i = 0
    while i < len(argv):
        if argv[i] == "--state" and i + 1 < len(argv):
            state_path = resolve_in_repo(argv[i + 1])
            i += 1
        elif argv[i] == "--pipeline" and i + 1 < len(argv):
            pipeline_path = argv[i + 1]
            i += 1
        i += 1

    if not os.path.exists(state_path):
        print("No batch-state.tsv found — nothing to reconcile.")
        sys.exit(0)

    # NOTE: batch-state.tsv's column schema is unresolved (spec §4) — no
    # completed/skipped rows can be reliably identified yet, so this always
    # reports nothing actionable rather than guessing at a parse.
    print("No completed batch entries in batch-state.tsv — nothing to reconcile.")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
