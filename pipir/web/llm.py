"""LLM access via an OpenAI-compatible chat-completions endpoint.

Configured through environment variables (see .env.example, loaded by the
server at startup):
  PIPIR_LLM_BASE_URL  e.g. https://llm.internal.example.com/v1
  PIPIR_LLM_API_KEY   bearer token (optional for unauthenticated endpoints)
  PIPIR_LLM_MODEL     model name to request
"""

import json
import os
import urllib.error
import urllib.request


class LlmError(RuntimeError):
    pass


def configured():
    return bool(os.environ.get("PIPIR_LLM_BASE_URL"))


def chat(messages, temperature=0.2, max_tokens=1500):
    base = os.environ.get("PIPIR_LLM_BASE_URL", "").rstrip("/")
    if not base:
        raise LlmError(
            "no LLM endpoint configured: set PIPIR_LLM_BASE_URL "
            "(see .env.example)")
    model = os.environ.get("PIPIR_LLM_MODEL", "")
    key = os.environ.get("PIPIR_LLM_API_KEY", "")
    body = {"model": model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens}
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 **({"Authorization": "Bearer " + key} if key else {})},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise LlmError("LLM endpoint returned HTTP %d: %s"
                       % (exc.code, exc.read()[:300])) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise LlmError("cannot reach LLM endpoint: %s" % exc) from exc
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError("unexpected LLM response shape: %s"
                       % json.dumps(data)[:300]) from exc


def load_env(root):
    """Minimal .env loader: KEY=VALUE lines, no quoting rules, no export."""
    path = os.path.join(root, ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))
