#!/usr/bin/env python3
"""match_star: match a behavioural question to a STAR story.

Only the two error paths are implemented. The story-bank.md format hasn't
been pinned down yet (several plausible markdown structures were tried and
none parsed cleanly), so the actual matching/scoring logic is a known gap
rather than a guess. Do not extend this file to guess at a parser without
first confirming the real format.
"""
import os
import sys

STORY_BANK_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "interview-prep", "story-bank.md"
)


def main(argv):
    if not os.path.exists(STORY_BANK_PATH):
        print("Error: interview-prep/story-bank.md not found.")
        print("Run /careeropsil interview-prep on a role first to populate your story bank.")
        return 1

    # Real story parsing/scoring is unimplemented (unresolved file format —
    # see module docstring). Every existing file currently falls through to
    # the same "no stories found" response as an empty/unparseable one.
    print("No stories found in story-bank.md yet.")
    print("Run /careeropsil interview-prep on a role to add your first stories.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
