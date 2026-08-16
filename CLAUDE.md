# careerOpsIL

A self-hosted, terminal-based job-search command center: track applications in
plain-text Markdown, scan job boards, evaluate postings against a CV with AI, and
draft tailored application materials. Full command/tool reference: `README.md`.
Interactive slash-command entry point: `/careeropsil` (see
`.claude/skills/careeropsil/SKILL.md`).

## How to invoke

- **Interactive:** `claude` in this directory, then `/careeropsil`.
- **Headless/batch:** `claude -p "prompt"` — e.g. `claude -p "scan for new jobs and
  evaluate the top 3"`. This file is loaded automatically either way, so a plain
  natural-language prompt works without invoking the skill explicitly.

## Operating rules (apply in every mode)

- **Never auto-submit an application, send an email, or drive a real browser to
  fill out a form.** Everything this tool produces (cover letters, emails, form
  answers) is a draft the human reviews and sends themselves. This is a hard
  product boundary, not a missing feature — don't try to work around it.
- **`dashboard.py` is an interactive TUI** (Textual) — don't try to drive it
  programmatically. For anything scriptable, call the underlying single-purpose
  script directly with `--json` where supported (`scan.py`, `evaluate.py`,
  `tracker.py query --json`, etc.) and parse the output. Point the user at
  `python3 dashboard.py --path .` when they want the interactive view.
- **`data/applications.md` is the only source of truth** for the tracker. Don't
  hand-edit it — go through `merge_tracker.py` (via a TSV in
  `batch/tracker-additions/`) or `set_status.py` for status changes.
- **Respect existing config before changing it.** `portals.yml` (target
  roles/locations/companies/job-board search) and `cv.md` (the CV every AI
  feature reads from) are user-owned; when asked to update them, report exactly
  what changed rather than silently overwriting.
- **`.env` holds the LLM provider config** (`GEMINI_API_KEY`, or
  `LLM_PROVIDER=ollama`/`openai` plus that provider's own vars) — never print its
  contents back to the user, and never commit it.
- If asked to do something that isn't wired up yet (see README's "Known gaps"),
  say so rather than improvising a workaround that touches the tracker or sends
  anything externally.
