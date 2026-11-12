"""Load map.toml (what to track) and notes.toml (optional hand edits).

Both scripts read the map through here, so a typo shows up as one clear message
instead of a stack trace. Paths can be overridden with LS_MAP / LS_NOTES, which is
how an example map is tried without touching the real one:

    LS_MAP=examples/rag.toml LS_NOTES=none LS_DATA=/tmp/rag python3 scripts/fetch.py
"""
import hashlib
import os
import re
import sys
import tomllib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAP = os.environ.get("LS_MAP") or os.path.join(ROOT, "map.toml")
NOTES = os.environ.get("LS_NOTES") or os.path.join(ROOT, "notes.toml")
DATA = os.environ.get("LS_DATA") or os.path.join(ROOT, "data")
CACHE = os.environ.get("LS_CACHE") or os.path.join(ROOT, "scripts", ".cache")   # shared between fields
UA = "living-survey/1.0 (+https://github.com/ym-xu/living-survey)"


def fail(msg):
    sys.exit(f"{os.path.relpath(MAP, ROOT)}: {msg}")


def regex(value, where, required=False):
    """A rule: one string, or a list of alternatives joined with '|'."""
    if not value:
        if required:
            fail(f"{where} is required")
        return None
    s = "|".join(f"(?:{v})" for v in value) if isinstance(value, list) else value
    try:
        return re.compile(s, re.I)
    except re.error as e:
        fail(f"bad regular expression in {where}: {e}")


def labels(items, where):
    """["long name = Short", "plain name", ...] -> [(long, short), ...]"""
    out = []
    for it in items or []:
        if not isinstance(it, str):
            fail(f"{where}: every entry must be a string")
        long, _, short = it.partition("=")
        long, short = long.strip(), short.strip() or long.strip()
        if long:
            out.append((long, short))
    return out


def load():
    try:
        with open(MAP, "rb") as f:
            m = tomllib.load(f)
    except FileNotFoundError:
        fail("not found — copy one from examples/ to get started"
             + (" (this repository has fields/: run scripts/build.py, or set LS_MAP)" if os.path.isdir(os.path.join(ROOT, "fields")) else ""))
    except tomllib.TOMLDecodeError as e:
        fail(f"not valid TOML: {e}")
    for key in ("map", "arxiv", "filter"):
        m.setdefault(key, {})
    if not m["map"].get("title"):
        fail("[map] title is required")
    if not m["arxiv"].get("categories") or not m["arxiv"].get("queries"):
        fail("[arxiv] needs categories and queries")
    subs = m.get("subfield") or []
    if not subs:
        fail("add at least one [[subfield]]")
    seen = set()
    for i, s in enumerate(subs):
        where = f"[[subfield]] #{i + 1}"
        for k in ("id", "name", "match"):
            if not s.get(k):
                fail(f"{where} needs {k}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", s["id"]):
            fail(f"{where}: id {s['id']!r} must be lower-case letters, digits and dashes")
        if s["id"] in seen:
            fail(f"{where}: id {s['id']!r} used twice")
        seen.add(s["id"])
        s["rx"] = regex(s["match"], f"subfield {s['id']} match")
        s.setdefault("short", s["name"])
        s.setdefault("desc", "")
    f = m["filter"]
    f["topic_rx"] = regex(f.get("topic"), "[filter] topic", required=True)
    f["require_rx"] = regex(f.get("require"), "[filter] require")
    f["strong_rx"] = regex(f.get("strong"), "[filter] strong")
    f["exclude_rx"] = regex(f.get("exclude"), "[filter] exclude")
    f["application_rx"] = regex(f.get("application"), "[filter] application")
    m.setdefault("terms", {})
    m.setdefault("cards", {})
    return m


def notes():
    try:
        with open(NOTES, "rb") as f:
            return tomllib.load(f)
    except (FileNotFoundError, IsADirectoryError):
        return {}
    except tomllib.TOMLDecodeError as e:
        sys.exit(f"{os.path.relpath(NOTES, ROOT)}: not valid TOML: {e}")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def fingerprint(*parts):
    return hashlib.sha1("\n".join(map(str, parts)).encode()).hexdigest()[:8]
