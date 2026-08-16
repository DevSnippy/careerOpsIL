#!/usr/bin/env python3
"""ai_setup: natural-language setup assistant. Describe what you're looking
for and/or your background in plain text; this parses it into portals.yml
(target roles, location filters, jobspy config) and/or cv.md, using
whichever LLM provider is configured.

Only ever writes portals.yml and cv.md — never touches the tracker, never
adds companies by guessing a URL (that would risk a hallucinated slug
pointing at the wrong place), and always reports back exactly what changed
so nothing is silently overwritten.
"""
import json
import os
import sys

from llm_providers import LLMError, llm_generate
from portals_config import load_portals, save_portals

SETUP_PROMPT_TEMPLATE = """A user is setting up a job-search tool by describing what they want in \
plain language. Read their message below and return ONLY a JSON object (no markdown fences) with \
this shape - include a key only if the message actually gives you something for it, omit keys \
entirely if not mentioned:

{{
  "target_roles": ["keyword", "..."],
  "exclude_keywords": ["keyword", "..."],
  "always_allow_locations": ["..."],
  "block_locations": ["..."],
  "allow_locations": ["..."],
  "cv_background": "if the message describes the user's own background/experience/skills, \
rewrite it as clean CV-style markdown (Summary/Experience/Skills sections as applicable) - \
otherwise omit this key entirely. Never invent details beyond what's stated.",
  "summary": "one sentence describing what you're about to configure, for the user to confirm"
}}

Do not invent target roles, locations, or CV content the user didn't actually mention.

--- USER MESSAGE ---
{message}
--- END USER MESSAGE ---
"""


def parse_setup_request(message, provider="gemini", **llm_kwargs):
    prompt = SETUP_PROMPT_TEMPLATE.format(message=message[:8000])
    raw = llm_generate(prompt, provider=provider, **llm_kwargs)
    raw = raw.strip()
    import re
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise LLMError(f"{provider} didn't return valid JSON: {e}\nRaw: {raw[:500]}") from e


def apply_setup(base_path, parsed):
    """Applies the parsed setup dict to portals.yml and/or cv.md. Returns a
    list of human-readable change descriptions."""
    changes = []
    portals_path = os.path.join(base_path, "portals.yml")
    data = load_portals(portals_path)

    if parsed.get("target_roles"):
        for kw in parsed["target_roles"]:
            if kw not in data["title_filter"]["positive"]:
                data["title_filter"]["positive"].append(kw)
        changes.append(f"Added target roles: {', '.join(parsed['target_roles'])}")

    if parsed.get("exclude_keywords"):
        for kw in parsed["exclude_keywords"]:
            if kw not in data["title_filter"]["negative"]:
                data["title_filter"]["negative"].append(kw)
        changes.append(f"Added exclude keywords: {', '.join(parsed['exclude_keywords'])}")

    for json_key, yaml_key, label in [
        ("always_allow_locations", "always_allow", "Always-allow locations"),
        ("block_locations", "block", "Blocked locations"),
        ("allow_locations", "allow", "Allowed locations"),
    ]:
        if parsed.get(json_key):
            for loc in parsed[json_key]:
                if loc not in data["location_filter"][yaml_key]:
                    data["location_filter"][yaml_key].append(loc)
            changes.append(f"{label}: {', '.join(parsed[json_key])}")

    if changes:
        save_portals(portals_path, data)

    if parsed.get("cv_background"):
        cv_path = os.path.join(base_path, "cv.md")
        mode = "a" if os.path.exists(cv_path) else "w"
        with open(cv_path, mode, encoding="utf-8") as f:
            if mode == "a":
                f.write("\n\n" + parsed["cv_background"])
            else:
                f.write(parsed["cv_background"])
        changes.append(f"{'Appended to' if mode == 'a' else 'Created'} cv.md")

    return changes


def run_ai_setup(base_path, message, provider="gemini", llm_kwargs=None):
    llm_kwargs = llm_kwargs or {}
    parsed = parse_setup_request(message, provider=provider, **llm_kwargs)
    changes = apply_setup(base_path, parsed)
    return {"summary": parsed.get("summary", ""), "changes": changes}


def main(argv):
    from evaluate import resolve_llm_config
    from llm_providers import load_env

    json_mode = "--json" in argv
    positional = [a for a in argv if a != "--json"]
    if not positional:
        print("Usage: python ai_setup.py <description> [--json]", file=sys.stderr)
        return 1
    env = load_env()
    provider, llm_kwargs = resolve_llm_config(env)
    if provider == "gemini" and not llm_kwargs.get("api_key"):
        msg = "no GEMINI_API_KEY configured (.env)"
        print(json.dumps({"error": msg}) if json_mode else f"Error: {msg}", file=sys.stderr)
        return 1
    try:
        result = run_ai_setup(".", " ".join(positional), provider=provider, llm_kwargs=llm_kwargs)
    except LLMError as e:
        print(json.dumps({"error": str(e)}) if json_mode else f"Error: {e}", file=sys.stderr)
        return 1
    if json_mode:
        print(json.dumps(result))
    else:
        print(result["summary"])
        for c in result["changes"]:
            print(f"  - {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
