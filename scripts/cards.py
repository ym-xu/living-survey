#!/usr/bin/env python3
"""Paper cards and Figure 4 (methods x tasks): data/survey_cards.json.

For each paper in data/survey.json a language model reads the title and abstract and
fills in a small card: a one-line summary, the contribution type, the task(s), and the
methods it proposes or merely uses — chosen from the lists in map.toml [cards], each
with a quote from the abstract as evidence. A tag is kept only if its quote is found
word for word in the abstract. From the cards it builds the methods x tasks matrix,
including "quiet" pairs: common on their own, rarely together.

    python3 scripts/cards.py                # cards for new papers, then rebuild
    python3 scripts/cards.py --no-extract   # rebuild the matrix only
    python3 scripts/cards.py --limit 600    # a bigger backfill (default 150 per run)

Without an API key (see llm.py) it only rebuilds from the cards it has, so new papers
appear without tags until a key is set. Only public arXiv abstracts are sent.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import arxiv
import llm
import mapconfig as mc
import pool as shared

SURVEY = os.path.join(mc.DATA, "survey.json")
OUT = os.path.join(mc.DATA, "survey_cards.json")
ABSTRACTS = os.path.join(mc.CACHE, "abstracts.json")
PROMPT = "c1"            # bump when the prompt below changes, so cards are redone
LIMIT = 150              # new cards per run at most
NS = {"a": "http://www.w3.org/2005/Atom"}
CONTRIBUTIONS = ["method", "benchmark / dataset", "analysis / evaluation", "system / tool",
                 "model release / technical report", "survey", "application study"]
RESOURCES = ["none", "benchmark", "dataset", "model", "code / tool"]

SYSTEM = """You fill in a short structured card for a research paper in {topic}, using only its title and abstract.

Rules:
- Use only what the abstract states. If something is not stated, leave the list empty or the string empty — never guess.
- Every "evidence" field is an exact, contiguous quote copied from the abstract (or title): same words, same order, 5–30 words.
- one_line: what the paper does, at most 25 words, plain language.
- contribution: one of {contributions}. A paper that applies existing techniques to a domain task (clinical, legal, grading…) is "application study".
- tasks: the task(s) the paper is about, usually 1–2, at most 3, most central first. Choose from the task list; use "other" only when nothing fits.
- methods: the techniques the abstract presents as central, usually 1–3, at most 4. Choose from the method list; use "other" only when nothing fits. Never repeat a value.
  role "proposed" = part of this paper's own contribution; role "used" = an existing backbone, tool, model or standard step it relies on
  (the base model it fine-tunes, an off-the-shelf engine, a model that merely powers an agent).
- new_resource: a benchmark, dataset, model or code the paper itself releases, with its name; kind "none" otherwise.

Task list: {tasks}
Method list: {methods}

Return one JSON object (json) with exactly these keys:
{{"one_line": "...",
 "contribution": {{"value": "...", "evidence": "..."}},
 "tasks": [{{"value": "...", "evidence": "..."}}],
 "methods": [{{"value": "...", "role": "proposed|used", "evidence": "..."}}],
 "new_resource": {{"kind": "none|benchmark|dataset|model|code / tool", "name": "...", "evidence": "..."}}}}"""


# ---------------------------------------------------------------- abstracts ----
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def clean_tex(s):
    """Strip LaTeX markup some abstracts carry, so quotes can match plain text."""
    s = re.sub(r"\\(?:emph|textbf|textit|texttt|mathrm|mathbf|text)\{([^{}]*)\}", r"\1", s)
    s = s.replace("\\%", "%").replace("\\&", "&").replace("``", '"').replace("''", '"').replace("--", "–")
    return re.sub(r"\s+", " ", s).strip()


def fetch_abstracts(ids):
    """Full abstracts (survey.json keeps an excerpt): from the shared pool when it has
    them, otherwise from arXiv; cached in scripts/.cache."""
    cache = load_json(ABSTRACTS, {})
    todo = [i for i in ids if i not in cache]
    got = shared.entries(os.environ["LS_POOL"]) if todo and os.environ.get("LS_POOL") else None
    if got:
        want = set(todo)
        for e in got[1]:
            i = arxiv.entry_id(e)
            if i in want:
                cache[i] = {"title": clean_tex(e.findtext("a:title", "", NS)), "abstract": clean_tex(e.findtext("a:summary", "", NS))}
        todo = [i for i in todo if i not in cache]
    for k in range(0, len(todo), 100):
        chunk = todo[k:k + 100]
        root = arxiv.get({"id_list": ",".join(chunk), "max_results": len(chunk)})
        for e in root.findall("a:entry", NS):
            i = re.sub(r"v\d+$", "", e.findtext("a:id", "", NS).rsplit("/", 1)[-1])
            cache[i] = {"title": clean_tex(e.findtext("a:title", "", NS)), "abstract": clean_tex(e.findtext("a:summary", "", NS))}
        os.makedirs(os.path.dirname(ABSTRACTS), exist_ok=True)
        with open(ABSTRACTS, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    if got:
        os.makedirs(os.path.dirname(ABSTRACTS), exist_ok=True)
        with open(ABSTRACTS, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    return cache


# ------------------------------------------------------------------- checks ----
def norm(s):
    """Lower-case words; every kind of dash is a word break, punctuation is ignored."""
    s = re.sub(r"[‐-―\-]", " ", s.lower().replace("’", "'"))
    return re.sub(r"[^a-z0-9%.+' ]+", " ", s).split()


def found(quote, source):
    q = " ".join(norm(quote))
    return bool(q) and q in " ".join(norm(source))


def conform(card, tasks, methods):
    """Bring a card into shape; returns (card, problems worth a retry)."""
    if not isinstance(card, dict):
        return None, ["not a JSON object"]
    bad = []
    pair = lambda v: v if isinstance(v, dict) else {}
    out = {"one_line": str(card.get("one_line") or "")[:240]}
    c = pair(card.get("contribution"))
    cv = str(c.get("value") or "").strip().lower()
    alias = {"benchmark": "benchmark / dataset", "dataset": "benchmark / dataset", "analysis": "analysis / evaluation",
             "evaluation": "analysis / evaluation", "evaluation methodology": "analysis / evaluation", "system": "system / tool",
             "tool": "system / tool", "technical report": "model release / technical report", "model release": "model release / technical report"}
    cv = alias.get(cv, cv)
    if cv not in CONTRIBUTIONS:
        bad.append(f"contribution {cv!r} is not one of the options")
    out["contribution"] = {"value": cv, "evidence": str(c.get("evidence") or "")}
    for key, vocab, cap in (("tasks", tasks, 3), ("methods", methods, 4)):
        items, seen = [], set()
        raw = card.get(key)
        if not isinstance(raw, list):
            bad.append(f"{key} is not a list")
            raw = []
        for it in raw:
            it = pair(it)
            v = str(it.get("value") or "")
            v = v if v in vocab else "other"
            if v in seen:
                continue
            seen.add(v)
            row = {"value": v, "evidence": str(it.get("evidence") or "")}
            if key == "methods":
                row["role"] = it.get("role") if it.get("role") in ("proposed", "used") else "proposed"
            items.append(row)
        out[key] = items[:cap]
    r = pair(card.get("new_resource"))
    kind = r.get("kind") if r.get("kind") in RESOURCES else "none"
    out["new_resource"] = {"kind": kind, "name": str(r.get("name") or "")[:60], "evidence": str(r.get("evidence") or "")}
    if not out["one_line"]:
        bad.append("one_line is empty")
    return out, bad


def compact(card, title, abstract, model, sig):
    """The public card: verified tags only, as slugs. Quotes are checked, not stored."""
    src = f"{title}. {abstract}"
    ok = lambda it: it["value"] != "other" and found(it["evidence"], src)
    quotes = [it["evidence"] for it in card["tasks"] + card["methods"] + [card["contribution"]] if it["evidence"]]
    res = card["new_resource"]
    res_ok = res["kind"] != "none" and found(res["evidence"], src)
    return {
        "c": card["contribution"]["value"],
        "o": card["one_line"],
        "t": [mc.slug(t["value"]) for t in card["tasks"] if ok(t)],
        "mp": [mc.slug(m["value"]) for m in card["methods"] if ok(m) and m["role"] == "proposed"],
        "mu": [mc.slug(m["value"]) for m in card["methods"] if ok(m) and m["role"] == "used"],
        "r": res["kind"] if res_ok else "none",
        "rn": res["name"] if res_ok else "",
        "q": [sum(found(q, src) for q in quotes), len(quotes)],
        "m": model,
        "s": sig,
    }


def extract(papers, key, system, tasks, methods, sig, workers=6):
    abstracts = fetch_abstracts([p["id"] for p in papers])
    out, errors, tokens = {}, 0, 0
    lock = threading.Lock()                       # tokens is summed from the worker threads

    def work(p):
        nonlocal tokens
        a = abstracts.get(p["id"]) or {"title": p["title"], "abstract": p.get("abs", "")}
        user = f"Title: {a['title']}\n\nAbstract: {a['abstract']}"
        for attempt in range(2):
            raw, meta = llm.chat_json(key, system, user)
            with lock:
                tokens += int(meta["usage"].get("total_tokens") or 0)
            card, bad = conform(raw, tasks, methods)
            if card and not bad:
                return p["id"], compact(card, a["title"], a["abstract"], meta["model"], sig)
            user += "\n\nYour previous card had these problems: " + "; ".join(bad) + ". Return the full corrected JSON object."
        raise llm.LLMError("; ".join(bad))

    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for fut in cf.as_completed([pool.submit(work, p) for p in papers]):
            try:
                pid, c = fut.result()
                out[pid] = c
            except Exception as e:                 # retried on the next run
                errors += 1
                print(f"  ! card failed: {type(e).__name__}: {e}", file=sys.stderr)
    return out, errors, tokens


def matrix(papers, cards, tasks, methods, rows_n, cols_n):
    """Proposed method x task counts over the counted (non-application) papers."""
    tslug = {mc.slug(t): s for t, s in tasks}
    mslug = {mc.slug(m): s for m, s in methods}
    full = {mc.slug(x): x for x, _ in tasks + methods}
    pool = [cards[p["id"]] for p in papers if p["id"] in cards and not p.get("app")]
    pool = [({m for m in c["mp"] if m in mslug}, {t for t in c["t"] if t in tslug}) for c in pool]
    n = len(pool)
    mech_n, task_n = {}, {}
    for ms, ts in pool:
        for m in ms:
            mech_n[m] = mech_n.get(m, 0) + 1
        for t in ts:
            task_n[t] = task_n.get(t, 0) + 1
    rows = sorted(mech_n, key=lambda k: -mech_n[k])[:rows_n]
    cols = sorted(task_n, key=lambda k: -task_n[k])[:cols_n]
    cells, best, quiet = [], 1, []
    for m in rows:
        line = []
        for t in cols:
            k = sum(1 for ms, ts in pool if m in ms and t in ts)
            e = mech_n[m] * task_n[t] / max(1, n)          # expected if they were unrelated
            cell = {"n": k, "e": round(e, 1)}
            if e >= 3 and k <= e / 4:
                cell["quiet"] = True
                quiet.append({"m": m, "t": t, "n": k, "e": round(e, 1), "mname": mslug[m], "tname": tslug[t]})
            elif k >= 5 and k >= 2 * e:
                cell["hot"] = True
            best = max(best, k)
            line.append(cell)
        cells.append(line)
    quiet.sort(key=lambda q: q["n"] - q["e"])
    return {"rows": [{"id": m, "name": mslug[m], "full": full[m], "n": mech_n[m]} for m in rows],
            "cols": [{"id": t, "name": tslug[t], "full": full[t], "n": task_n[t]} for t in cols],
            "cells": cells, "max": best, "n": n, "quiet": quiet[:8]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-extract", action="store_true")
    ap.add_argument("--limit", type=int, default=LIMIT)
    args = ap.parse_args()

    cfg = mc.load()
    cc = cfg["cards"]
    tasks = mc.labels(cc.get("tasks"), "[cards] tasks")
    methods = mc.labels(cc.get("methods"), "[cards] methods")
    if not tasks or not methods:
        print("cards: no [cards] tasks / methods in map.toml — Figure 4 is off", file=sys.stderr)
        if os.path.exists(OUT):
            os.remove(OUT)
        return
    topic = cc.get("topic") or cfg["map"]["title"].split(":")[0]
    tnames, mnames = [t for t, _ in tasks] + ["other"], [m for m, _ in methods] + ["other"]
    system = SYSTEM.format(topic=topic, contributions=", ".join(f'"{c}"' for c in CONTRIBUTIONS),
                           tasks="; ".join(tnames), methods="; ".join(mnames))
    sig = mc.fingerprint(PROMPT, topic, *tnames, *mnames)

    papers = load_json(SURVEY, {}).get("papers", [])
    current = {p["id"] for p in papers}
    store = {k: v for k, v in load_json(OUT, {}).get("papers", {}).items() if k in current}   # the survey window only
    todo = [p for p in papers if p["id"] not in store] + [p for p in papers if p["id"] in store and store[p["id"]].get("s") != sig]
    errors = tokens = 0
    if todo and not args.no_extract:
        key = llm.api_key()
        if not key:
            print(f"cards: {len(todo)} papers need a card, but no LLM_API_KEY is set — skipped", file=sys.stderr)
        else:
            batch = todo[:args.limit]
            print(f"cards: extracting {len(batch)} of {len(todo)} ({llm.MODEL})", file=sys.stderr)
            new, errors, tokens = extract(batch, key, system, tnames, mnames, sig)
            store.update(new)

    mx = matrix(papers, store, tasks, methods, int(cc.get("rows", 14)), int(cc.get("cols", 10)))
    ver = sum(c["q"][0] for c in store.values())
    tot = sum(c["q"][1] for c in store.values()) or 1
    out = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "models": sorted({c["m"] for c in store.values() if c.get("m")}),
           "n": len(store), "of": len(papers), "quotes": round(100 * ver / tot, 1),
           "names": {mc.slug(x): s for x, s in tasks + methods},
           "matrix": mx, "papers": store}
    os.makedirs(mc.DATA, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"cards: {len(store)}/{len(papers)} papers · matrix {len(mx['rows'])}x{len(mx['cols'])} over {mx['n']} · "
          f"{len(mx['quiet'])} quiet pairs · quotes {out['quotes']}% · errors {errors} · tokens {tokens}", file=sys.stderr)


if __name__ == "__main__":
    main()
