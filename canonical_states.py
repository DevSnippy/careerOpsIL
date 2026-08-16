"""Canonical tracker states, shared by set_status.py, normalize_statuses.py,
and dedup_tracker.py.

NOTE: the alias table is intentionally partial (see set_status.py's module
docstring) — only `aplicado` -> `Applied` was empirically confirmed.
"""

CANONICAL_STATES = [
    "Evaluated", "Applied", "Responded", "Interview",
    "Offer", "Rejected", "Discarded", "SKIP", "Hired",
]
CANONICAL_LOOKUP = {s.lower(): s for s in CANONICAL_STATES}
ALIASES = {"aplicado": "Applied"}

# Verified boundary for dedup-tracker's fuzzy-merge gate: "Evaluated" is the
# only status confirmed to allow a company+role fuzzy merge across different
# report numbers; every other canonical status was confirmed (via "Applied")
# to require an exact report-number match instead.
EARLY_STATUSES = {"evaluated"}


def resolve_status(raw):
    """Returns the canonical label for raw text (case-insensitive, alias-aware,
    tolerant of **bold** wrapping), or None if unrecognized."""
    text = raw.strip()
    if text.startswith("**") and text.endswith("**") and len(text) > 4:
        text = text[2:-2].strip()
    key = text.lower()
    if key in CANONICAL_LOOKUP:
        return CANONICAL_LOOKUP[key]
    if key in ALIASES:
        return ALIASES[key]
    return None
