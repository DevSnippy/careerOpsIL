#!/usr/bin/env python3
"""form_answers: draft answers to common ATS application-form questions
(why this role, why this company, salary expectations, notice period,
etc.), gated behind a score threshold so low-fit roles don't waste a call.

Draft text only, written to a file for you to copy/paste. Never fills or
submits any real form — no browser automation, by design.
"""
import json
import os
import sys

from evaluate import evaluate_jd, parse_llm_json, resolve_jd_text, resolve_llm_config
from llm_providers import LLMError, llm_generate, load_env

DEFAULT_SCORE_THRESHOLD = 4.0

FORM_ANSWERS_PROMPT_TEMPLATE = """Draft answers to common job-application form questions for the \
posting below, grounded ONLY in facts present in the CV. Return ONLY a JSON object (no markdown \
fences) with this shape:

{{
  "why_this_role": "2-3 sentences",
  "why_this_company": "2-3 sentences - if the JD gives little company detail, keep this general \
and say so rather than inventing company facts",
  "relevant_experience": "2-4 sentences summarizing the most relevant experience for this role",
  "salary_expectations": "a reasonable range/response based on any salary info in the JD, or a \
neutral deferral if none is given - never invent a number",
  "notice_period": "a neutral placeholder noting this is CV/candidate-specific and should be \
filled in by the candidate, since it isn't derivable from a CV",
  "additional_notes": "anything else commonly asked (visa/sponsorship status, relocation, etc.) \
as a neutral placeholder if not derivable from the CV"
}}

--- JOB DESCRIPTION ---
{jd_text}
--- END JOB DESCRIPTION ---

--- CV ---
{cv_text}
--- END CV ---
"""


def generate_form_answers(jd_text, cv_text, provider="gemini", **llm_kwargs):
    prompt = FORM_ANSWERS_PROMPT_TEMPLATE.format(jd_text=jd_text[:20000], cv_text=cv_text[:20000])
    raw = llm_generate(prompt, provider=provider, **llm_kwargs)
    try:
        return parse_llm_json(raw)
    except json.JSONDecodeError as e:
        raise LLMError(f"{provider} didn't return valid JSON: {e}\nRaw: {raw[:500]}") from e


def run_form_answers(base_path, jd_input, score, provider="gemini", llm_kwargs=None,
                      threshold=DEFAULT_SCORE_THRESHOLD):
    """Only generates answers if score >= threshold (token-conservation
    gate, matching the documented Auto-Pipeline behavior). Returns None
    if below threshold, else the answers dict + the path they were saved to."""
    llm_kwargs = llm_kwargs or {}
    if score < threshold:
        return None

    jd_text, _url = resolve_jd_text(jd_input)
    cv_path = os.path.join(base_path, "cv.md")
    cv_text = ""
    if os.path.exists(cv_path):
        with open(cv_path, encoding="utf-8") as f:
            cv_text = f.read()

    answers = generate_form_answers(jd_text, cv_text, provider=provider, **llm_kwargs)

    drafts_dir = os.path.join(base_path, "output", "form-answers")
    os.makedirs(drafts_dir, exist_ok=True)
    import re
    from datetime import date
    slug = re.sub(r"[^a-z0-9]+", "-", jd_text[:40].lower()).strip("-") or "role"
    path = os.path.join(drafts_dir, f"{date.today().isoformat()}-{slug}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Application form answer drafts\n\n")
        for key, value in answers.items():
            label = key.replace("_", " ").title()
            f.write(f"## {label}\n\n{value}\n\n")
    return answers, path


def main(argv):
    json_mode = "--json" in argv
    positional = [a for a in argv if a != "--json"]
    score = 5.0  # CLI usage bypasses the gate by default; --score to override
    threshold = DEFAULT_SCORE_THRESHOLD
    filtered = []
    i = 0
    while i < len(positional):
        if positional[i] == "--score" and i + 1 < len(positional):
            score = float(positional[i + 1]); i += 2
        elif positional[i] == "--threshold" and i + 1 < len(positional):
            threshold = float(positional[i + 1]); i += 2
        else:
            filtered.append(positional[i]); i += 1

    def emit_error(msg):
        if json_mode:
            print(json.dumps({"error": msg}))
        else:
            print(f"Error: {msg}", file=sys.stderr)

    if not filtered:
        emit_error("no job URL/text given")
        return 1

    env = load_env()
    provider, llm_kwargs = resolve_llm_config(env)
    if provider == "gemini" and not llm_kwargs.get("api_key"):
        emit_error("no GEMINI_API_KEY configured (.env)")
        return 1

    try:
        result = run_form_answers(".", " ".join(filtered), score, provider=provider,
                                   llm_kwargs=llm_kwargs, threshold=threshold)
    except LLMError as e:
        emit_error(str(e))
        return 1

    if result is None:
        if json_mode:
            print(json.dumps({"skipped": True, "reason": f"score {score} below threshold {threshold}"}))
        else:
            print(f"Skipped — score {score} is below the {threshold} threshold.")
        return 0

    answers, path = result
    if json_mode:
        print(json.dumps({"answers": answers, "path": path}))
    else:
        print(f"Saved: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
