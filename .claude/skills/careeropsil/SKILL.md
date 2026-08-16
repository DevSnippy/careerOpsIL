---
name: careeropsil
description: Entry point for the careerOpsIL job-search command center. Use when the user wants to search/scan for jobs, evaluate a posting against their CV, manage their application tracker (add/query/change status), draft a cover letter/email/form answers, generate a resume PDF or portfolio, or asks for "/careeropsil" or "careerOpsIL" by name.
---

# careerOpsIL

Route the user's request to the right tool below and run it directly — don't
narrate a plan for simple, single-step requests. All scripts live in this
directory; run them with `python3 <script>.py ...` from here (or `--path .` for
`dashboard.py`/`scan.py`/`evaluate.py`, which accept a base path).

First time in this directory: check whether `.env`, `cv.md`, and `portals.yml`
exist. If any are missing, run `python3 doctor.py` and follow what it reports
instead of guessing at setup — don't fabricate an API key or CV content.

## Routing

| User wants to... | Run |
|---|---|
| The interactive dashboard | Tell them to run `python3 dashboard.py --path .` themselves (it's a TUI — you can't drive it) |
| Find new postings (tracked companies + job boards) | `python3 scan.py --path . --json` |
| Score a posting against their CV | `python3 evaluate.py "<url-or-JD-text>" --json` |
| See/query the tracker | `python3 tracker.py query --json [--status X] [--company Y]` |
| Change an application's status | `python3 set_status.py <id> <Status>` |
| Look up a specific application | `python3 find.py <number-or-fragment>` |
| Cover letter / application email drafts | `python3 application_drafts.py --path .` (draft only — see safety notes) |
| Draft answers to ATS form questions | `python3 form_answers.py --path . "<url-or-JD-text>"` (score-gated) |
| A narrative portfolio PDF | `python3 portfolio.py --path .` |
| Update target roles/locations/companies | Edit `portals.yml` directly, or `python3 ai_setup.py "<description>"` for natural-language setup |
| Funnel/conversion stats | `python3 stats.py` |
| Tracker health check | `python3 verify_pipeline.py` |

Full tool inventory and file layout: `README.md`.

## Safety notes (non-negotiable)

- Never auto-submit an application or send an email. Cover letters, emails, and
  form answers are drafts written to `output/` for the human to review and send
  themselves.
- Never drive a real browser to fill out an application form.
- Never invent CV content, employers, or metrics not present in `cv.md`.
- Never guess a company's careers-page URL when adding a tracked company —
  ask the user for it.
