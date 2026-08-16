"""jd_capture: resolve an archived JD capture in jds/ by report number.
Library only, no CLI surface.
"""
import os
import re

JDS_DIR = "jds"

PREFIX_RE = re.compile(r"^(\d+)-")


def resolve_jd_capture(report_num, jds_dir=JDS_DIR):
    """Returns the path to the jds/ file whose leading numeric token (padded
    or not) equals report_num, or None if no match exists.

    Matches on the whole leading number, not a string prefix — confirmed
    during spec analysis that report #1 does not match a "10-..." file.
    """
    if not os.path.isdir(jds_dir):
        return None
    target = str(int(report_num))
    for fname in sorted(os.listdir(jds_dir)):
        m = PREFIX_RE.match(fname)
        if m and str(int(m.group(1))) == target:
            return os.path.join(jds_dir, fname)
    return None
