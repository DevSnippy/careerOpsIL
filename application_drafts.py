#!/usr/bin/env python3
"""application_drafts: multi-angle cover letter drafts (with an approval
gate before final PDF generation) and draft-only application emails.

Emails are drafts only — this module never sends anything. The human
always reviews and decides before anything goes out.
"""
import json
import re
import sys

from evaluate import parse_llm_json, resolve_jd_text, resolve_llm_config
from llm_providers import LLMError, llm_generate, load_env

ANGLES_PROMPT_TEMPLATE = """You are drafting cover letter options for a job application. Read the \
job description and CV below, then return ONLY a JSON object (no markdown fences) with this shape:

{{
  "candidate": {{"name": "...", "email": "...", "phone": "...", "location": "..."}},
  "angles": [
    {{
      "label": "short theme name, e.g. 'Technical depth' or 'Career narrative'",
      "company": "...", "role_title": "...", "date": "{today}",
      "greeting": "...", "opening": "1-2 sentences", "profile_intro": "2-3 sentences",
      "closing": "..."
    }}
  ]
}}

Generate exactly {n} distinctly different angles (different opening hooks/emphasis), each \
grounded ONLY in facts present in the CV - never invent achievements, employers, or numbers. \
candidate fields should be extracted from the CV text (leave a field "" if genuinely absent).

--- JOB DESCRIPTION ---
{jd_text}
--- END JOB DESCRIPTION ---

--- CV ---
{cv_text}
--- END CV ---
"""

EMAIL_PROMPT_TEMPLATE = """Draft a formal job application email for the posting below, based on the \
candidate's CV. Return ONLY a JSON object (no markdown fences):

{{
  "subject": "...",
  "body": "full email body, plain text, professional tone, grounded only in CV facts",
  "attachments": ["checklist of what to attach, e.g. 'Tailored CV (PDF)', 'Cover letter (PDF)'"]
}}

This is a DRAFT ONLY - it will never be sent automatically. Do not invent facts not present \
in the CV.

--- JOB DESCRIPTION ---
{jd_text}
--- END JOB DESCRIPTION ---

--- CV ---
{cv_text}
--- END CV ---
"""


def generate_cover_letter_angles(jd_text, cv_text, provider="gemini", n=3, **llm_kwargs):
    from datetime import date
    prompt = ANGLES_PROMPT_TEMPLATE.format(
        jd_text=jd_text[:20000], cv_text=cv_text[:20000], n=n, today=date.today().isoformat()
    )
    raw = llm_generate(prompt, provider=provider, **llm_kwargs)
    try:
        return parse_llm_json(raw)
    except json.JSONDecodeError as e:
        raise LLMError(f"{provider} didn't return valid JSON: {e}\nRaw: {raw[:500]}") from e


def generate_email_draft(jd_text, cv_text, provider="gemini", **llm_kwargs):
    prompt = EMAIL_PROMPT_TEMPLATE.format(jd_text=jd_text[:20000], cv_text=cv_text[:20000])
    raw = llm_generate(prompt, provider=provider, **llm_kwargs)
    try:
        return parse_llm_json(raw)
    except json.JSONDecodeError as e:
        raise LLMError(f"{provider} didn't return valid JSON: {e}\nRaw: {raw[:500]}") from e


def angle_to_payload(angle_data, angle_index):
    """Builds the exact payload shape generate_cover_letter.py expects."""
    angle = angle_data["angles"][angle_index]
    return {"candidate": angle_data["candidate"], "letter": {
        "company": angle["company"], "role_title": angle["role_title"], "date": angle["date"],
        "greeting": angle.get("greeting", ""), "opening": angle["opening"],
        "profile_intro": angle["profile_intro"], "closing": angle.get("closing", ""),
    }}


def main(argv):
    json_mode = "--json" in argv
    mode = "cover-letter"
    if "--email" in argv:
        mode = "email"
    positional = [a for a in argv if a not in ("--json", "--email", "--cover-letter")]

    def emit_error(msg):
        if json_mode:
            print(json.dumps({"error": msg}))
        else:
            print(f"Error: {msg}", file=sys.stderr)

    if not positional:
        emit_error("no job URL/text given")
        return 1

    env = load_env()
    provider, llm_kwargs = resolve_llm_config(env)
    if provider == "gemini" and not llm_kwargs.get("api_key"):
        emit_error("no GEMINI_API_KEY configured (.env)")
        return 1

    jd_input = " ".join(positional)
    try:
        jd_text, _url = resolve_jd_text(jd_input)
        import os
        cv_text = ""
        if os.path.exists("cv.md"):
            with open("cv.md", encoding="utf-8") as f:
                cv_text = f.read()

        if mode == "email":
            result = generate_email_draft(jd_text, cv_text, provider=provider, **llm_kwargs)
        else:
            result = generate_cover_letter_angles(jd_text, cv_text, provider=provider, **llm_kwargs)
    except LLMError as e:
        emit_error(str(e))
        return 1

    if json_mode:
        print(json.dumps(result))
    elif mode == "email":
        print(f"Subject: {result['subject']}\n")
        print(result["body"])
        print("\nAttachments checklist:")
        for a in result.get("attachments", []):
            print(f"  - {a}")
    else:
        for i, angle in enumerate(result["angles"]):
            print(f"[{i}] {angle['label']}")
            print(f"    {angle['opening']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
