"""A minimal client for any OpenAI-compatible chat API, JSON output. Standard library only.

    LLM_API_KEY    the key (DEEPSEEK_API_KEY is accepted too)
    LLM_BASE_URL   default https://api.deepseek.com  (e.g. https://api.openai.com/v1,
                   https://openrouter.ai/api/v1, http://localhost:11434/v1 for Ollama)
    LLM_MODEL      default deepseek-chat
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

BASE = (os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com").rstrip("/")
MODEL = os.environ.get("LLM_MODEL") or "deepseek-chat"


class LLMError(RuntimeError):
    pass


def api_key():
    return (os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()


def _post(key, body):
    req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def _parse(content):
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)          # some models wrap the object in prose
        if m:
            return json.loads(m.group(0))
        raise


def chat_json(key, system, user, max_tokens=1500, retries=4):
    """One chat call that should return a JSON object. Returns (object, meta).
    Retries rate limits and server errors; drops JSON mode if the provider rejects it."""
    body = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    for attempt in range(retries + 1):
        try:
            resp = _post(key, body)
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code == 400 and "response_format" in body and "response_format" in detail:
                body.pop("response_format")
                continue
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** attempt * 3)
                continue
            raise LLMError(f"HTTP {e.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(2 ** attempt * 3)
                continue
            raise LLMError(str(e)) from None
    else:
        raise LLMError("no response")
    choice = resp["choices"][0]
    if choice.get("finish_reason") == "length":
        raise LLMError("output hit max_tokens")
    content = choice["message"].get("content") or ""
    try:
        obj = _parse(content)
    except (json.JSONDecodeError, ValueError):
        raise LLMError(f"not JSON: {content[:200]}") from None
    return obj, {"model": resp.get("model", MODEL), "usage": resp.get("usage", {})}
