"""One arXiv download shared by every field: scripts/.cache/arxiv_pool.json.

The pool is the answer to the union of all fields' queries — every category of any
field, and every search term of any field — so it contains everything each field's own
query would return (and a few papers no field wants, which each field drops again with
arxiv.Query). fetch.py then files papers from the pool instead of asking arXiv itself.
arXiv calls therefore grow with the union of the search terms, not with the number of
fields.

Refreshing it:
  * the first run, or once FULL_EVERY days have passed, or when a field asks for an older
    window or new terms: the whole window is fetched again (picks up new versions,
    comments and journal refs, and drops withdrawn papers);
  * other days: only the newest pages, until OVERLAP days before the newest paper we had
    (papers can be announced days after they were submitted).
If arXiv can't be reached the pool file is left as it was and Unreachable is raised.
"""
import datetime as dt
import hashlib
import json
import os
import sys
import tomllib
import xml.etree.ElementTree as ET

import arxiv

VERSION = 1
PAGE = 400
MAX_RESULTS = 20000      # per stream and run; arXiv will not page much deeper
FULL_EVERY = 7           # days
OVERLAP = 14             # days re-read on an incremental day
MAX_QUERY = 3000         # characters of search terms per stream; longer unions are split


def load_maps(paths):
    """[(path, map)] for the maps that parse; a broken one is skipped (its own fetch reports it)."""
    out = []
    for p in paths:
        try:
            with open(p, "rb") as f:
                m = tomllib.load(f)
            ax = m.get("arxiv") or {}
            if ax.get("categories") and ax.get("queries"):
                out.append((p, m))
        except (OSError, tomllib.TOMLDecodeError) as e:
            print(f"  pool: skipping {p} ({e})", file=sys.stderr)
    return out


def streams(maps):
    """The union of categories and terms, as one or more arXiv search queries."""
    cats, terms = [], []
    for _, m in maps:
        for c in m["arxiv"]["categories"]:
            if c not in cats:
                cats.append(c)
        for q in m["arxiv"]["queries"]:
            if q not in terms:
                terms.append(q)
    cat = " OR ".join(f"cat:{c}" for c in sorted(cats))
    out, chunk = [], []
    for t in terms:
        if chunk and len(" OR ".join(chunk + [t])) > MAX_QUERY:
            out.append(chunk)
            chunk = []
        chunk.append(t)
    if chunk:
        out.append(chunk)
    return [f"({cat}) AND ({' OR '.join(c)})" for c in out]


def window(maps, today):
    weeks = max(int((m.get("map") or {}).get("weeks", 26)) for _, m in maps)
    return today - dt.timedelta(days=weeks * 7 - 1)


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            p = json.load(f)
        return p if p.get("version") == VERSION else None
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _page(query, start):
    return arxiv.get({"search_query": query, "start": start, "max_results": PAGE,
                      "sortBy": "submittedDate", "sortOrder": "descending"})


def _read(query, stop, entries, stats):
    """Pages of one stream, newest first, until a page reaches back past `stop`.
    Returns True if it got there (False: the result cap was hit first)."""
    start = 0
    while start < MAX_RESULTS:
        got = _page(query, start).findall("a:entry", arxiv.NS)
        if not got:
            return True
        oldest = None
        for e in got:
            i, pub = arxiv.entry_id(e), arxiv.published(e)
            if not i or not pub:
                continue
            stats["entries"] += 1
            if i not in entries:
                stats["new"] += 1
            entries[i] = {"d": pub, "x": ET.tostring(e, encoding="unicode")}
            oldest = pub if oldest is None or pub < oldest else oldest
        if oldest and oldest < stop:
            return True
        start += PAGE
    return False


def refresh(map_paths, path, today=None):
    """Bring the pool up to date for these maps. Returns stats; raises arxiv.Unreachable."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    maps = load_maps(map_paths)
    if not maps:
        return None
    qs = streams(maps)
    since = window(maps, today).isoformat()
    old = load(path)
    key = hashlib.sha1("\n".join(qs).encode()).hexdigest()[:12]
    full = (not old or old.get("key") != key or old.get("since", "9") > since
            or (today - dt.date.fromisoformat(old.get("full", "2000-01-01"))).days >= FULL_EVERY)
    entries = {} if full else dict(old["entries"])
    newest = max((v["d"] for v in entries.values()), default=since)
    stop = since if full else (dt.date.fromisoformat(newest) - dt.timedelta(days=OVERLAP)).isoformat()
    stats = {"mode": "full" if full else "incremental", "streams": len(qs), "entries": 0, "new": 0, "calls": arxiv.calls}
    capped = False
    for q in qs:
        capped |= not _read(q, max(stop, since), entries, stats)
    entries = {i: v for i, v in entries.items() if v["d"] >= since}
    stats.update(calls=arxiv.calls - stats["calls"], papers=len(entries), since=since, capped=capped)
    if capped:
        print(f"  WARNING: pool stopped at the {MAX_RESULTS}-result cap before reaching {stop}; split the fields' "
              f"queries or shorten [map] weeks", file=sys.stderr)
    out = {"version": VERSION, "key": key, "since": since, "today": today.isoformat(),
           "full": today.isoformat() if full else old["full"], "streams": qs, "entries": entries}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return stats


def entries(path):
    """The pool's entries as Atom elements, newest first; None if there is no pool."""
    p = load(path)
    if p is None:
        return None
    rows = sorted(p["entries"].items(), key=lambda kv: (kv[1]["d"], kv[0]), reverse=True)
    return p, [ET.fromstring(v["x"]) for _, v in rows]
