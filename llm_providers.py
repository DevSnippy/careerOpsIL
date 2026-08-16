#!/usr/bin/env python3
"""llm_providers: minimal client(s) for Gemini / Ollama / any
OpenAI-compatible endpoint, dispatched via LLM_PROVIDER in a project-root
.env file (GEMINI_API_KEY / OLLAMA_* / OPENAI_API_KEY as applicable).

Uses only the stdlib (urllib) against Google's public Generative Language
API — no new HTTP dependency needed for this.
"""
import json
import os
import urllib.error
import urllib.request

DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
DEFAULT_OLLAMA_MODEL = "llama3.3"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_URL = "https://api.openai.com/v1"
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env():
    env = dict(os.environ)
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env.setdefault(key.strip(), value.strip())
    return env


def save_env_var(key, value):
    lines = []
    found = False
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith(f"{key}="):
                    lines.append(f"{key}={value}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"{key}={value}\n")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)


class LLMError(Exception):
    pass


def gemini_generate(prompt, api_key, model=None, timeout=60):
    model = model or DEFAULT_GEMINI_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise LLMError(f"Gemini API error {e.code}: {detail[:300]}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"Gemini API unreachable: {e.reason}") from e

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise LLMError(f"Unexpected Gemini API response shape: {data}") from e


def ollama_generate(prompt, model=None, base_url=None, timeout=120):
    """Local Ollama server — no API key, no cost. NOT independently
    live-tested (no local Ollama instance available in this environment);
    implemented against Ollama's own documented /api/generate endpoint
    shape (public API, not from any project's source)."""
    model = model or DEFAULT_OLLAMA_MODEL
    base_url = (base_url or DEFAULT_OLLAMA_URL).rstrip("/")
    body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/generate", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise LLMError(f"Ollama unreachable at {base_url} (is `ollama serve` running?): "
                        f"{e.reason if hasattr(e, 'reason') else e}") from e
    try:
        return data["response"]
    except KeyError as e:
        raise LLMError(f"Unexpected Ollama response shape: {data}") from e


def openai_generate(prompt, api_key=None, model=None, base_url=None, timeout=60):
    """Any OpenAI-compatible chat completions endpoint (OpenAI itself, or
    a compatible one like Groq/Together/local vLLM). NOT independently
    live-tested (no API key configured in this environment); implemented
    against the standard OpenAI chat/completions request/response shape."""
    model = model or DEFAULT_OPENAI_MODEL
    base_url = (base_url or DEFAULT_OPENAI_URL).rstrip("/")
    body = json.dumps({
        "model": model, "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{base_url}/chat/completions", data=body, method="POST",
                                  headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise LLMError(f"OpenAI-compatible API error {e.code}: {detail[:300]}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"OpenAI-compatible endpoint unreachable at {base_url}: {e.reason}") from e
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise LLMError(f"Unexpected OpenAI-compatible response shape: {data}") from e


PROVIDERS = {"gemini": gemini_generate, "ollama": ollama_generate, "openai": openai_generate}


def llm_generate(prompt, provider="gemini", **kwargs):
    """Unified dispatcher. kwargs are passed through to the chosen
    provider's function (api_key/model/base_url as applicable)."""
    if provider not in PROVIDERS:
        raise LLMError(f"Unknown provider: {provider} (choices: {', '.join(PROVIDERS)})")
    fn = PROVIDERS[provider]
    accepted = fn.__code__.co_varnames[:fn.__code__.co_argcount]
    filtered = {k: v for k, v in kwargs.items() if k in accepted}
    return fn(prompt, **filtered)
