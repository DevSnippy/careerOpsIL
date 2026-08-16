#!/usr/bin/env python3
"""eval_golden: offline golden-set eval harness (--replay mode only).

--live mode (calling a real LLM) is intentionally not implemented — it
requires a real API key and cv.md, which is out of scope for this harness.
"""
import glob
import json
import os
import re
import sys

SCORE_GATE_PCT = 80
SCORE_TOLERANCE = 0.5

SCORE_SUMMARY_RE = re.compile(
    r"---SCORE_SUMMARY---\s*(.*?)\s*---END_SUMMARY---", re.DOTALL
)
FIELD_RE = re.compile(r"^(COMPANY|ROLE|SCORE|ARCHETYPE|LEGITIMACY):\s*(.*)$", re.MULTILINE)


def parse_fixture(path):
    with open(path, encoding="utf-8") as f:
        content = f.read()
    m = SCORE_SUMMARY_RE.search(content)
    if not m:
        return None
    fields = dict(FIELD_RE.findall(m.group(1)))
    return fields


def main(argv):
    model = "cheap-stub"
    golden_dir = "evals/golden"
    fixtures_dir = None
    live = False

    i = 0
    while i < len(argv):
        if argv[i] == "--help":
            print("eval_golden.py — golden-set eval harness")
            print()
            print("  --replay         Replay recorded fixtures (default; offline, $0, deterministic)")
            print("  --live           Call the model live (needs key + cv.md)")
            print("  --model <id>     Candidate model id to evaluate (default: cheap-stub)")
            print("  --golden <dir>   Golden-set directory (default: evals/golden)")
            print("  --fixtures <dir> Replay fixtures directory (default: sibling of --golden)")
            print("  --help           Show this help")
            return 0
        if argv[i] == "--replay":
            i += 1
        elif argv[i] == "--live":
            live = True
            i += 1
        elif argv[i] == "--model" and i + 1 < len(argv):
            model = argv[i + 1]; i += 2
        elif argv[i] == "--golden" and i + 1 < len(argv):
            golden_dir = argv[i + 1]; i += 2
        elif argv[i] == "--fixtures" and i + 1 < len(argv):
            fixtures_dir = argv[i + 1]; i += 2
        else:
            i += 1

    if live:
        print("eval-golden --live: not implemented in this port (requires a real "
              "API key + cv.md — out of scope)", file=sys.stderr)
        return 1

    if fixtures_dir is None:
        fixtures_dir = os.path.join(os.path.dirname(golden_dir) or ".", "fixtures")

    golden_files = sorted(glob.glob(os.path.join(golden_dir, "*.json")))
    cases = []
    for gf in golden_files:
        with open(gf, encoding="utf-8") as f:
            cases.append(json.load(f))

    print(f'golden-set eval — model "{model}" (replay), {len(cases)} case(s)')
    print("(row ✅ needs both archetype + score; the gate counts archetype agreement only)")
    print()

    archetype_matches = 0
    scored_deltas = []
    unscored = 0

    for case in cases:
        case_id = case["id"]
        label = case["label"]
        fixture_path = os.path.join(fixtures_dir, f"{case_id}__{model}.txt")
        if not os.path.exists(fixture_path):
            print(f"  ❌ {case_id}: missing replay fixture: "
                  f"{os.path.abspath(fixture_path)} — record it or run --live")
            unscored += 1
            continue

        fields = parse_fixture(fixture_path)
        if not fields or "ARCHETYPE" not in fields or "SCORE" not in fields:
            print(f"  ❌ {case_id}: replay fixture missing SCORE_SUMMARY block: "
                  f"{os.path.abspath(fixture_path)}")
            unscored += 1
            continue

        candidate_archetype = fields["ARCHETYPE"].strip()
        candidate_score = float(fields["SCORE"])
        ref_archetype = label["archetype"]
        ref_score = label["score"]

        archetype_match = candidate_archetype.lower() == ref_archetype.lower()
        delta = abs(candidate_score - ref_score)
        scored_deltas.append(delta)
        if archetype_match:
            archetype_matches += 1

        row_ok = archetype_match and delta <= SCORE_TOLERANCE
        icon = "✅" if row_ok else "❌"
        match_word = "match" if archetype_match else "MISS"
        print(f"  {icon} {case_id}: archetype {candidate_archetype.lower()} vs "
              f"{ref_archetype.lower()} ({match_word}); score {candidate_score:g} vs "
              f"{ref_score:g} (Δ{delta:.2f}); replay")

    total = len(cases)
    agreement_pct = round(100 * archetype_matches / total) if total else 0

    print()
    print("  ── summary ──")
    print(f"  archetype agreement : {agreement_pct}%  (gate ≥ {SCORE_GATE_PCT}%)")
    scored_n = len(scored_deltas)
    if scored_n:
        mean_delta = sum(scored_deltas) / scored_n
        suffix = f" ({unscored} unscored)" if unscored else ""
        print(f"  mean |Δscore|       : {mean_delta:.2f}  over {scored_n}/{total} "
              f"scored{suffix}  (tolerance ±{SCORE_TOLERANCE})")
    else:
        print(f"  mean |Δscore|       : n/a  over 0/{total} scored ({unscored} unscored)  "
              f"(tolerance ±{SCORE_TOLERANCE})")
    print("  est. $/run          : n/a — TODO(#1354)")
    print()

    if agreement_pct >= SCORE_GATE_PCT:
        print("  ✅ PASS — archetype agreement meets gate")
        return 0
    print("  ❌ FAIL — archetype agreement below gate")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
