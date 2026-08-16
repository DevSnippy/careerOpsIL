#!/usr/bin/env python3
"""evaluate: score a job posting against your CV using an LLM, then write a
full report (Blocks A-G), a tailored PDF, and a tracker row — the "paste a
job, get an evaluation back" flow. The analysis in each block comes from
this module's own prompt to Gemini.
"""
import html
import json
import os
import re
import sys
from datetime import date

from llm_providers import LLMError, llm_generate, load_env
from pdf_backend import render_html_to_pdf

EVAL_PROMPT_TEMPLATE = """You are evaluating a job posting against a candidate's CV for a job-search \
tracking tool. Read the job description and the CV below, then return ONLY a JSON object \
(no markdown fences, no commentary) with exactly these keys:

{{
  "company": "company name extracted from the JD",
  "role_title": "job title extracted from the JD",
  "score": 0.0,
  "role_summary": "plain-English summary of the role, 2-4 sentences",
  "cv_matches": ["bullet points on how the CV matches JD requirements"],
  "cv_gaps": ["bullet points on gaps between the CV and JD requirements"],
  "positioning_strategy": "how the candidate should position themselves for this role",
  "comp_research": "compensation context - if a range is in the JD, comment on how it \
compares to typical market rates for this role/location; otherwise say none was found",
  "personalization_notes": "specific angles/talking points for this application, grounded \
only in facts present in the CV below - never invent achievements",
  "interview_prep": ["2-4 short STAR-style story angles from the CV relevant to this role"],
  "legitimacy_tier": "one of: high, medium, low, suspicious",
  "legitimacy_notes": "why you picked that tier - vague/generic postings, missing company \
info, or classic ghost-job signals should lower the tier"
}}

Scoring rubric: 0.0-5.0, where 4.0+ means a strong fit worth applying to. Weigh role fit, \
compensation signal, and remote/location policy. Do not fabricate CV content that isn't \
actually present in the CV text below - if information needed to judge a dimension is \
missing, say so rather than guessing.

--- JOB DESCRIPTION ---
{jd_text}
--- END JOB DESCRIPTION ---

--- CANDIDATE CV ---
{cv_text}
--- END CV ---
"""

TAILOR_PROMPT_TEMPLATE = """Rewrite the CV below as a tailored one-page resume for the specific \
job description provided, emphasizing the most relevant experience and re-ordering/reframing \
(never inventing) content to match the role. Output clean HTML for direct PDF rendering: a full \
<html><body> document, simple inline CSS, headings for Name/Summary/Experience/Education/Skills \
as appropriate. Use only facts present in the source CV - reframe and reorder, never fabricate.

--- JOB DESCRIPTION ---
{jd_text}
--- END JOB DESCRIPTION ---

--- SOURCE CV ---
{cv_text}
--- END SOURCE CV ---
"""


def looks_like_url(text):
    return bool(re.match(r"^https?://\S+$", text.strip()))


def fetch_jd_from_url(url, timeout=30000):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        text = page.inner_text("body")
        browser.close()
    return text


def resolve_jd_text(jd_input):
    if looks_like_url(jd_input):
        return fetch_jd_from_url(jd_input), jd_input
    return jd_input, ""


CLOSED_SIGNALS = [
    "no longer accepting applications", "position has been filled", "job has been filled",
    "posting has expired", "this job is no longer available", "job not found",
    "position is closed", "applications are closed", "this position has been closed",
    "we are no longer accepting", "role has been filled", "404", "page not found",
]


def check_posting_liveness(jd_text, min_length=200):
    """Best-effort liveness heuristic: flags obvious closed/removed
    signals or suspiciously thin extracted content (usually means the
    page didn't actually load a real posting). Not a replacement for a
    real browser-rendered visual check — a text heuristic only."""
    text_lower = jd_text.lower()
    for signal in CLOSED_SIGNALS:
        if signal in text_lower:
            return False, f'found closing signal: "{signal}"'
    if len(jd_text.strip()) < min_length:
        return False, f"extracted content is only {len(jd_text.strip())} chars — likely not a real posting"
    return True, ""


def parse_llm_json(text):
    text = text.strip()
    # Gemini sometimes wraps JSON in ```json ... ``` even when told not to.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    return json.loads(text)


def resolve_llm_config(env):
    """Reads LLM_PROVIDER (default gemini) plus that provider's own
    settings from the .env-loaded dict. Same env-var naming convention as
    the rest of this project's .env.example (GEMINI_API_KEY etc.)."""
    provider = (env.get("LLM_PROVIDER") or "gemini").strip().lower()
    if provider == "ollama":
        return provider, {"model": env.get("OLLAMA_MODEL"), "base_url": env.get("OLLAMA_URL")}
    if provider == "openai":
        return provider, {"api_key": env.get("OPENAI_API_KEY"), "model": env.get("OPENAI_MODEL"),
                           "base_url": env.get("OPENAI_BASE_URL")}
    return "gemini", {"api_key": env.get("GEMINI_API_KEY"), "model": env.get("GEMINI_MODEL")}


def evaluate_jd(jd_text, cv_text, provider="gemini", **llm_kwargs):
    prompt = EVAL_PROMPT_TEMPLATE.format(jd_text=jd_text[:20000], cv_text=cv_text[:20000])
    raw = llm_generate(prompt, provider=provider, **llm_kwargs)
    try:
        return parse_llm_json(raw)
    except json.JSONDecodeError as e:
        raise LLMError(f"{provider} didn't return valid JSON: {e}\nRaw response: {raw[:500]}") from e


def build_tailored_cv_html(jd_text, cv_text, provider="gemini", **llm_kwargs):
    prompt = TAILOR_PROMPT_TEMPLATE.format(jd_text=jd_text[:20000], cv_text=cv_text[:20000])
    raw = llm_generate(prompt, provider=provider, **llm_kwargs)
    fence = re.match(r"^```(?:html)?\s*(.*?)\s*```$", raw.strip(), re.DOTALL)
    return fence.group(1) if fence else raw.strip()


def next_report_number(base_path):
    reports_dir = os.path.join(base_path, "reports")
    if not os.path.exists(reports_dir):
        return 1
    numbers = []
    for name in os.listdir(reports_dir):
        m = re.match(r"^(\d+)-", name)
        if m:
            numbers.append(int(m.group(1)))
    return (max(numbers) + 1) if numbers else 1


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unknown"


def render_report_markdown(report_num, data, url):
    score = data.get("score", 0)
    lines = [
        f"# Report: {data.get('company', '?')} — {data.get('role_title', '?')}",
        "",
        f"**Score:** {score:.2f}/5" if isinstance(score, (int, float)) else f"**Score:** {score}/5",
    ]
    if url:
        lines.append(f"**URL:** {url}")
    lines.append(f"**Legitimacy:** {data.get('legitimacy_tier', 'unknown')}")
    lines.append("")
    lines.append("## Block A: Role Fit")
    lines.append("")
    lines.append(data.get("role_summary", ""))
    lines.append("")
    lines.append("## Block B: CV Match")
    lines.append("")
    lines.append("**Matches:**")
    for m in data.get("cv_matches", []):
        lines.append(f"- {m}")
    lines.append("")
    lines.append("**Gaps:**")
    for g in data.get("cv_gaps", []):
        lines.append(f"- {g}")
    lines.append("")
    lines.append("## Block C: Positioning Strategy")
    lines.append("")
    lines.append(data.get("positioning_strategy", ""))
    lines.append("")
    lines.append("## Block D: Compensation Research")
    lines.append("")
    lines.append(data.get("comp_research", ""))
    lines.append("")
    lines.append("## Block E: Personalization Notes")
    lines.append("")
    lines.append(data.get("personalization_notes", ""))
    lines.append("")
    lines.append("## Block F: Interview Prep")
    lines.append("")
    for s in data.get("interview_prep", []):
        lines.append(f"- {s}")
    lines.append("")
    lines.append("## Block G: Posting Legitimacy")
    lines.append("")
    lines.append(f"**Tier:** {data.get('legitimacy_tier', 'unknown')}")
    lines.append("")
    lines.append(data.get("legitimacy_notes", ""))
    lines.append("")
    lines.append("## Machine Summary")
    lines.append("")
    lines.append("```yaml")
    lines.append(f"score: {score}")
    lines.append(f"company: {data.get('company', '?')}")
    lines.append(f"role_title: {data.get('role_title', '?')}")
    lines.append(f"legitimacy: {data.get('legitimacy_tier', 'unknown')}")
    lines.append("```")
    return "\n".join(lines)


def append_tracker_addition(base_path, report_num, company, role, score, pdf_ready, report_path,
                             url=""):
    additions_dir = os.path.join(base_path, "batch", "tracker-additions")
    os.makedirs(additions_dir, exist_ok=True)
    today = date.today().isoformat()
    score_text = f"{score:.2f}/5" if isinstance(score, (int, float)) else f"{score}/5"
    pdf_mark = "✅" if pdf_ready else "❌"
    fields = [str(report_num), today, company, role, "Evaluated", score_text, pdf_mark,
              f"[{report_num}](reports/{report_path})", url or ""]
    addition_path = os.path.join(additions_dir, f"{report_num}-{slugify(company)}.tsv")
    with open(addition_path, "w", encoding="utf-8") as f:
        f.write("\t".join(fields) + "\n")
    return addition_path


def run_evaluation(base_path, jd_input, provider="gemini", llm_kwargs=None, generate_pdf=True,
                    check_liveness=True):
    """Runs the full pipeline: fetch JD -> liveness gate -> LLM eval ->
    write report -> tailored PDF -> tracker addition. Returns a dict with
    report_path, pdf_path (or None), addition_path, and the parsed eval
    data. Raises LLMError with a "liveness" marker dict entry if the
    posting looks dead and check_liveness is True."""
    llm_kwargs = llm_kwargs or {}
    jd_text, url = resolve_jd_text(jd_input)
    if not jd_text.strip():
        raise LLMError("No job description text found (empty input or empty page).")

    if check_liveness and url:
        live, reason = check_posting_liveness(jd_text)
        if not live:
            raise LLMError(f"Posting appears closed/removed: {reason}")

    cv_path = os.path.join(base_path, "cv.md")
    cv_text = ""
    if os.path.exists(cv_path):
        with open(cv_path, encoding="utf-8") as f:
            cv_text = f.read()

    data = evaluate_jd(jd_text, cv_text, provider=provider, **llm_kwargs)

    report_num = next_report_number(base_path)
    company_slug = slugify(data.get("company", "unknown"))
    today = date.today().isoformat()
    report_filename = f"{report_num:03d}-{company_slug}-{today}.md"
    reports_dir = os.path.join(base_path, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, report_filename)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(render_report_markdown(report_num, data, url))

    pdf_path = None
    if generate_pdf and cv_text.strip():
        try:
            tailored_html = build_tailored_cv_html(jd_text, cv_text, provider=provider, **llm_kwargs)
            output_dir = os.path.join(base_path, "output")
            os.makedirs(output_dir, exist_ok=True)
            html_path = os.path.join(output_dir, f"{report_num:03d}-{company_slug}.html")
            pdf_path = os.path.join(output_dir, f"{report_num:03d}-{company_slug}.pdf")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(tailored_html)
            render_html_to_pdf(html_path, pdf_path)
        except Exception:
            pdf_path = None  # evaluation itself still succeeded; PDF is best-effort

    addition_path = append_tracker_addition(
        base_path, report_num, data.get("company", "?"), data.get("role_title", "?"),
        data.get("score", 0), pdf_path is not None, report_filename, url=url or "",
    )

    return {
        "report_num": report_num, "report_path": report_path, "pdf_path": pdf_path,
        "addition_path": addition_path, "data": data, "url": url,
    }


def main(argv):
    json_mode = "--json" in argv
    positional = [a for a in argv if a != "--json"]
    if not positional:
        if json_mode:
            print(json.dumps({"error": "no job URL/text given"}))
            return 1
        print("Usage: python evaluate.py <job-url-or-paste-jd-text> [--json]", file=sys.stderr)
        return 1
    jd_input = " ".join(positional)
    env = load_env()
    provider, llm_kwargs = resolve_llm_config(env)
    if provider == "gemini" and not llm_kwargs.get("api_key"):
        if json_mode:
            print(json.dumps({"error": "no GEMINI_API_KEY configured (.env)"}))
            return 1
        print("Error: no GEMINI_API_KEY configured (.env)", file=sys.stderr)
        return 1
    try:
        result = run_evaluation(".", jd_input, provider=provider, llm_kwargs=llm_kwargs)
    except LLMError as e:
        if json_mode:
            print(json.dumps({"error": str(e)}))
            return 1
        print(f"Evaluation failed: {e}", file=sys.stderr)
        return 1

    if json_mode:
        print(json.dumps({
            "report_num": result["report_num"], "report_path": result["report_path"],
            "pdf_path": result["pdf_path"], "addition_path": result["addition_path"],
            "data": result["data"], "url": result["url"],
        }))
        return 0

    data = result["data"]
    print(f"Score: {data.get('score')}/5")
    print(f"Report: {result['report_path']}")
    if result["pdf_path"]:
        print(f"Tailored PDF: {result['pdf_path']}")
    print(f"Tracker addition staged: {result['addition_path']} "
          f"(run merge_tracker.py to fold it into data/applications.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
