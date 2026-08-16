#!/usr/bin/env python3
"""portfolio: compile a polished portfolio PDF from cv.md — a narrative,
proof-points-forward document distinct from an ATS-tailored resume.
"""
import os
import re
import sys

from evaluate import resolve_llm_config
from llm_providers import LLMError, llm_generate, load_env
from pdf_backend import render_html_to_pdf

PORTFOLIO_PROMPT_TEMPLATE = """Turn the CV below into a polished, narrative-style personal \
portfolio page (not a resume/ATS document) — the kind of page you'd send someone to make a strong \
impression, emphasizing standout projects, measurable impact, and a personal narrative arc. Output \
clean HTML for direct PDF rendering: a full <html><body> document, simple inline CSS, clear \
visual hierarchy (name/tagline, About, Highlighted Projects with impact framing, Experience \
summary, Skills). Ground everything in facts from the CV below - reframe and emphasize, but \
never invent achievements, numbers, or projects not present in the source.

--- SOURCE CV ---
{cv_text}
--- END SOURCE CV ---
"""


def generate_portfolio_html(cv_text, provider="gemini", **llm_kwargs):
    prompt = PORTFOLIO_PROMPT_TEMPLATE.format(cv_text=cv_text[:20000])
    raw = llm_generate(prompt, provider=provider, **llm_kwargs)
    fence = re.match(r"^```(?:html)?\s*(.*?)\s*```$", raw.strip(), re.DOTALL)
    return fence.group(1) if fence else raw.strip()


def run_portfolio(base_path, provider="gemini", llm_kwargs=None):
    llm_kwargs = llm_kwargs or {}
    cv_path = os.path.join(base_path, "cv.md")
    if not os.path.exists(cv_path):
        raise LLMError("No cv.md found — nothing to build a portfolio from.")
    with open(cv_path, encoding="utf-8") as f:
        cv_text = f.read()

    html_content = generate_portfolio_html(cv_text, provider=provider, **llm_kwargs)
    output_dir = os.path.join(base_path, "output")
    os.makedirs(output_dir, exist_ok=True)
    html_path = os.path.join(output_dir, "portfolio.html")
    pdf_path = os.path.join(output_dir, "portfolio.pdf")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    render_html_to_pdf(html_path, pdf_path)
    return pdf_path


def main(argv):
    import json
    json_mode = "--json" in argv
    env = load_env()
    provider, llm_kwargs = resolve_llm_config(env)
    if provider == "gemini" and not llm_kwargs.get("api_key"):
        msg = "no GEMINI_API_KEY configured (.env)"
        print(json.dumps({"error": msg}) if json_mode else f"Error: {msg}",
              file=None if json_mode else sys.stderr)
        return 1
    try:
        pdf_path = run_portfolio(".", provider=provider, llm_kwargs=llm_kwargs)
    except LLMError as e:
        print(json.dumps({"error": str(e)}) if json_mode else f"Error: {e}",
              file=None if json_mode else sys.stderr)
        return 1
    print(json.dumps({"pdf_path": pdf_path}) if json_mode else f"Portfolio PDF: {pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
