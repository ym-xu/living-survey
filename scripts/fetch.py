#!/usr/bin/env python3
"""Fetch recent papers from arXiv, file them into subfields, write data/survey.json.

Runs every morning in the GitHub Action (and by hand: python3 scripts/fetch.py).
What to fetch and how to file it is all in map.toml; hand corrections in notes.toml.
Standard library only. How a paper is filed:
  * every subfield rule is counted in the title (x3) and the abstract (x1, capped);
  * a subfield is tagged when its score >= 2 — a title hit, or two mentions in the
    abstract — so a single passing mention doesn't count;
  * the highest-scoring subfield is the paper's *main* one (ties: earlier in map.toml);
  * the paper must be about the topic ([filter] topic, scored the same way), may need
    a required cue ([filter] require) and must not hit [filter] exclude.
If arXiv can't be reached the existing data file is left untouched, so the site
still builds with the last good snapshot — but the run exits with UNREACHABLE (3), so
the failure is reported rather than hidden. Exit codes: 0 written, 1 a problem in
map.toml, 3 nothing fetched (old data kept).

Thank you to arXiv for use of its open access interoperability.
"""
import collections
import datetime as dt
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import arxiv
import mapconfig as mc
import pool as shared

OUT = os.path.join(mc.DATA, "survey.json")
S2_URL = "https://api.semanticscholar.org/graph/v1/paper/batch?fields=venue,publicationVenue,year,citationCount,authors"
MIN_FOR_TREND = 10        # show a 4-week change only when both windows have at least this many papers
PAGE = 400                # results per arXiv call
MAX_RESULTS = 3200        # hard cap per run
RISE_WEEKS = 8            # rising terms: the last 8 weeks against the rest of the window
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

# Where a paper was accepted, from arXiv's author comment / journal ref ([map] venues adds more).
VENUES = ["CVPR", "ICCV", "ECCV", "NeurIPS", "ICLR", "ICML", "ACL", "EMNLP", "NAACL", "COLING", "EACL", "AAAI", "IJCAI",
          "ICDAR", "WACV", "BMVC", "ACM MM", "KDD", "SIGIR", "WWW", "CIKM", "WSDM", "ICASSP", "ICPR", "DAS", "LREC",
          "TPAMI", "IJCV", "TIP", "TACL", "Pattern Recognition", "ICME", "ACCV", "MICCAI", "JCDL", "TPDL", "RecSys",
          "Interspeech", "CoRL", "ICRA", "IROS", "UAI", "AISTATS", "COLT", "TMLR", "JMLR", "TKDE", "TOIS", "CHI", "UIST"]
ACCEPT_RX = re.compile(r"accept|to appear|published|camera[- ]ready|proceedings|main conference|findings|oral|spotlight|poster|workshop", re.I)
# Without an acceptance word, a venue counts only with a year and in a telling spot: "in CVPR 2026",
# "at ICDAR 2025", or opening the comment or a clause ("12 pages, WACV 2026"). So "compared with
# methods in CVPR" is not an acceptance.
VENUE_LEAD = re.compile(r"(?:^|[,;:(]|\b(?:in|at)(?:\s+the)?)$", re.I)
UNDER_REVIEW = re.compile(r"submitted|under review|in submission|under submission|preprint|extended version of", re.I)
CODE_RX = re.compile(r"https?://(?:www\.)?(?:github\.com|gitlab\.com|huggingface\.co)/[\w.\-/]+[\w/]", re.I)
BENCH_TITLE = re.compile(r"\b(benchmark\w*|dataset|corpus)s?\b|\bbench\b|bench\b", re.I)
# technical reports and versioned model releases ("PP-OCRv6: …", "Model-1.5: …")
RELEASE = re.compile(r"technical report|^[^:]{0,40}?(v\d+(\.\d+)*|[-\s]\d+(\.\d+)+)\s*:", re.I)
BENCH_ABS = re.compile(r"\b(introduce|present|release|construct|propose|curate|build|collect)\w*\s+(a|an|the)?\s*((new|novel|large[- ]scale|first|comprehensive|challenging|multilingual|synthetic)\s+)*([\w-]+\s+){0,3}(benchmark|dataset|corpus)\b", re.I)

# words that say nothing about a trend ([terms] stop adds the field's own)
STOP = set("""a an and are as at be by can for from has have how in into is it its of on or our over than that the their this
through to toward towards under using via vs we what when where which while with without beyond across based new novel
paper approach method methods framework model models large language vision visual multimodal multi modal
learning efficient towards study analysis data task tasks benchmark benchmarking dataset system systems toward
llm llms mllm mllms vlm vlms lvlm lvlms evaluating evaluation improving improved enhancing robust unified simple
not no one two more all any only just do does you your why aware driven guided
technical report reports survey review case towards""".split())


def clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def base_id(s):
    return re.sub(r"v\d+$", "", clean(s).rsplit("/", 1)[-1])


def curated(notes):
    ids = lambda xs: {re.sub(r"v\d+$", "", e["id"] if isinstance(e, dict) else e) for e in xs}
    include_tag = {re.sub(r"v\d+$", "", e["id"]): e["tag"] for e in notes.get("include", []) if isinstance(e, dict) and e.get("tag")}
    return {"exclude": ids(notes.get("exclude", [])), "include": ids(notes.get("include", [])), "include_tag": include_tag,
            "featured": {k: list(v) for k, v in notes.get("featured", {}).items()},
            "picks": {p["id"]: p.get("note", "") for p in notes.get("picks", [])}}


POOL = os.environ.get("LS_POOL") or ""          # set by build.py fetch: file papers from the shared download
TITLES = os.path.join(mc.CACHE, "arxiv_titles.json")


def arxiv_get(params):
    return arxiv.get(params)          # rate-limited, retried; raises arxiv.Unreachable


def arxiv_titles(ids):
    """{id: (title, date)} for a few explicit ids (featured papers outside the window).
    Titles don't change, so they are cached and asked for only once."""
    try:
        with open(TITLES, encoding="utf-8") as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    todo = [i for i in ids if i not in cache]
    if todo:
        try:
            root = arxiv_get({"id_list": ",".join(todo), "max_results": len(todo)})
            for e in root.findall("a:entry", NS):
                if clean(e.findtext("a:published", "", NS)):
                    cache[base_id(e.findtext("a:id", "", NS))] = [clean(e.findtext("a:title", "", NS)),
                                                                  clean(e.findtext("a:published", "", NS))[:10]]
            os.makedirs(os.path.dirname(TITLES), exist_ok=True)
            with open(TITLES, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception as e:
            print(f"  featured lookup failed ({e})", file=sys.stderr)
    return {i: tuple(cache[i]) for i in ids if i in cache}


def fetch(query, start):
    return arxiv_get({"search_query": query, "start": start, "max_results": PAGE,
                      "sortBy": "submittedDate", "sortOrder": "descending"})


def s2_enrich(papers):
    """Semantic Scholar, in batches: author IDs (to tell namesakes apart), citation
    counts and published venue. Optional — on any failure the map goes without;
    set S2_API_KEY for a higher rate limit."""
    out = {}
    headers = {"User-Agent": mc.UA, "Content-Type": "application/json"}
    if os.environ.get("S2_API_KEY"):
        headers["x-api-key"] = os.environ["S2_API_KEY"]
    ids = [p["id"] for p in papers]
    for k in range(0, len(ids), 400):
        chunk = ids[k:k + 400]
        body = json.dumps({"ids": [f"ARXIV:{i}" for i in chunk]}).encode()
        for attempt in range(4):
            try:
                req = urllib.request.Request(S2_URL, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=90) as r:
                    rows = json.loads(r.read())
                break
            except Exception as e:
                print(f"  Semantic Scholar failed ({e}); retry {attempt + 1}/4", file=sys.stderr)
                time.sleep(10 * (attempt + 1))
        else:
            return None
        for i, row in zip(chunk, rows):
            if row:
                out[i] = row
        time.sleep(1.5)
    return out


def main():
    cfg = mc.load()
    notes = mc.notes()
    cur = curated(notes)
    m, f = cfg["map"], cfg["filter"]
    subs = cfg["subfield"]
    order = [s["id"] for s in subs]
    weight = {s["id"]: float(s.get("weight", 1.0)) for s in subs}
    by_sid = {s["id"]: s for s in subs}
    weeks = int(m.get("weeks", 26))
    topic_min = int(f.get("topic_min", 2))
    watch = [a for a in m.get("watch", []) if a]
    watch_rx = re.compile("|".join(re.escape(a) for a in watch), re.I) if watch else None
    venues = VENUES + [v for v in m.get("venues", []) if v not in VENUES]
    venue_rx = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(v).replace(r"\ ", r"\s*") for v in venues) + r"|NIPS|ACMMM)(?![A-Za-z])"
                          r"(?:\s*(?:'|’)?\s*(20\d\d|\d\d))?", re.I)
    terms_cfg = cfg["terms"]
    field_words = set(terms_cfg.get("field", []))
    stop = STOP | set(terms_cfg.get("stop", []))
    same = dict(terms_cfg.get("same", {}))
    query = "({}) AND ({})".format(" OR ".join(f"cat:{c}" for c in cfg["arxiv"]["categories"]), " OR ".join(cfg["arxiv"]["queries"]))

    def canon_venue(name):
        return next((v for v in venues if re.fullmatch(re.escape(v).replace(r"\ ", r"\s*"), name.strip(), re.I)), None)

    def venue_of(comment, jref):
        """'CVPR 2026' / 'EMNLP 2025 Findings' / 'ICDAR 2026 Workshop', or ''."""
        for text in (jref, comment):
            if not text:
                continue
            mt = venue_rx.search(text)
            if not mt:
                continue
            if text is comment:
                if UNDER_REVIEW.search(text) and not re.search(r"accept", text, re.I):
                    continue
                lead = bool(mt.group(2)) and VENUE_LEAD.search(text[:mt.start()].rstrip())
                if not ACCEPT_RX.search(text) and not lead:
                    continue
            name = canon_venue(mt.group(1)) or mt.group(1)
            name = {"NIPS": "NeurIPS", "ACMMM": "ACM MM"}.get(name.upper(), name)
            year = mt.group(2) or ""
            if len(year) == 2:
                year = "20" + year
            extra = " Findings" if re.search(r"findings", text, re.I) else (" Workshop" if re.search(r"workshop", text, re.I) else "")
            return f"{name} {year}".strip() + extra
        return ""

    def s2_venue(row):
        pv = row.get("publicationVenue") or {}
        for n in [pv.get("name") or "", row.get("venue") or ""] + list(pv.get("alternate_names") or []):
            v = canon_venue(n)
            if v:
                return f"{v} {row.get('year') or ''}".strip()
        return ""

    def score(title, abstract):
        """{subfield id: score}; title hits weigh 3x."""
        out = {}
        for s in subs:
            sc = 3 * sum(1 for _ in s["rx"].finditer(title)) + min(3, sum(1 for _ in s["rx"].finditer(abstract)))
            if sc >= 2:
                out[s["id"]] = sc
        return out

    def topic_strength(title, abstract):
        rx = f["topic_rx"]
        return 3 * sum(1 for _ in rx.finditer(title)) + min(4, sum(1 for _ in rx.finditer(abstract)))

    def rank(sc):
        return sorted(sc, key=lambda k: (-sc[k] * weight[k], order.index(k)))

    def norm_word(w):
        w = same.get(w, w)
        if len(w) > 4 and w.endswith("s") and not w.endswith(("ss", "us", "is", "ics")):
            w = w[:-1]
        return same.get(w, w)

    def terms_of(title):
        raw = [w for w in re.findall(r"[a-z][a-z0-9-]+", title.lower()) if len(w) > 2]
        words = [None if (w in stop or norm_word(w) in stop) else norm_word(w) for w in raw]
        uni = {w for w in words if w}
        bi = {f"{a} {b}" for a, b in zip(words, words[1:]) if a and b}
        return uni | bi

    today = dt.datetime.now(dt.timezone.utc).date()
    since = today - dt.timedelta(days=weeks * 7 - 1)

    def paper_of(e, base, pub):
        """The paper record for one arXiv entry, or None if it doesn't belong on the map."""
        if pub < since:
            return None
        m_id = re.match(r"(\d{2})(\d{2})\.", base)
        if m_id and (2000 + int(m_id.group(1)), int(m_id.group(2))) < (since.year, since.month):
            return None  # an old paper resurfacing (new version / cross-list): first releases only
        title = clean(e.findtext("a:title", "", NS))
        abstract = clean(e.findtext("a:summary", "", NS))
        text = f"{title} {abstract}"
        sc = score(title, abstract)
        forced = base in cur["include"]       # hand-confirmed: skip the relevance gates
        if not sc and forced:
            tag = cur["include_tag"].get(base)
            if tag not in by_sid:
                if tag:
                    print(f"  notes.toml include {base}: unknown subfield {tag!r}", file=sys.stderr)
                tag = order[-1]
                print(f"  notes.toml include {base}: matches no subfield, filed under {tag!r} "
                      f"(add tag = \"<subfield id>\" to choose)", file=sys.stderr)
            sc = {tag: 2}
        if not forced and (not sc or (f["require_rx"] and not f["require_rx"].search(text))
                           or (f["exclude_rx"] and f["exclude_rx"].search(text))):
            return None
        tags = rank(sc)
        ts = topic_strength(title, abstract)
        main_sub = by_sid[tags[0]]
        if not forced and (ts < max(topic_min, int(main_sub.get("topic_min", 0)))
                           or (main_sub.get("strong") and f["strong_rx"] and not f["strong_rx"].search(text))):
            return None  # not about the topic, or a broad subfield without the strong cue
        prim = e.find("arxiv:primary_category", NS)
        authors = [clean(a.findtext("a:name", "", NS)) for a in e.findall("a:author", NS)]
        comment = clean(e.findtext("arxiv:comment", "", NS))
        jref = clean(e.findtext("arxiv:journal_ref", "", NS))
        code = CODE_RX.search(f"{abstract} {comment}")
        app_rx = f["application_rx"]
        return {
            "id": base, "title": title,
            "authors": authors[:4] + (["et al."] if len(authors) > 4 else []),
            "date": pub.isoformat(),
            "cat": prim.get("term") if prim is not None else "",
            "tags": tags,                      # tags[0] is the main subfield
            "bench": bool(BENCH_TITLE.search(title) or BENCH_ABS.search(abstract)),
            "watch": bool(watch_rx and any(watch_rx.fullmatch(a) for a in authors)),
            "pick": ((cur["picks"][base] or True) if base in cur["picks"] else None),   # note text, or true
            "app": bool(app_rx and app_rx.search(title) and not BENCH_TITLE.search(title)) and not forced,
            "report": bool(RELEASE.search(title)),
            "_sc": sc[tags[0]],
            "venue": venue_of(comment, jref),
            "code": code.group(0).rstrip(".,);") if code else "",
            "abs": abstract[:320] + ("…" if len(abstract) > 320 else ""),
        }

    def add(e):
        """File one entry; returns its first-release date (None if skipped before parsing)."""
        base = base_id(e.findtext("a:id", "", NS))
        if not base or base in seen:
            return None
        seen.add(base)
        if base in cur["exclude"]:
            return None
        published = clean(e.findtext("a:published", "", NS))[:10]
        if not published:
            return None          # an arXiv error entry (e.g. a mistyped id)
        pub = dt.date.fromisoformat(published)
        p = paper_of(e, base, pub)
        if p:
            papers.append(p)
        return pub

    papers, seen, start, reached = [], set(), 0, False
    local = arxiv.Query.parse(cfg["arxiv"]["categories"], cfg["arxiv"]["queries"]) if POOL else None
    got = shared.entries(POOL) if local else None
    if POOL and not local:
        print("  this field's queries use syntax the shared pool can't evaluate: asking arXiv directly", file=sys.stderr)
    by_pool = {}
    if got:                          # the shared download: keep what this field's own query would have returned
        meta, pooled = got
        by_pool = {arxiv.entry_id(e): e for e in pooled}
        n = 0
        for e in pooled:
            if local.matches(e):
                add(e)
                n += 1
        reached = meta["since"] <= since.isoformat()
        start = MAX_RESULTS          # skip the live loop below
        print(f"  from the shared pool: {n} of {len(pooled)} entries match this field's query", file=sys.stderr)
        if not reached:
            print(f"  WARNING: the shared pool only reaches back to {meta['since']}, not {since}", file=sys.stderr)
    while start < MAX_RESULTS:
        root = fetch(query, start)
        entries = root.findall("a:entry", NS)
        if not entries:
            reached = True           # arXiv has nothing older: the whole window is covered
            break
        oldest = None
        for e in entries:
            pub = add(e)
            if pub and (oldest is None or pub < oldest):
                oldest = pub
        print(f"  fetched {start}–{start + len(entries)}; oldest {oldest}", file=sys.stderr)
        if oldest and oldest < since:
            reached = True
            break
        start += PAGE
    if not reached and not by_pool:
        print(f"  WARNING: stopped at the {MAX_RESULTS}-result cap before reaching {since}; the oldest weeks are "
              f"incomplete and their trends understate the field — narrow [arxiv] queries or lower [map] weeks",
              file=sys.stderr)

    # notes.toml include: papers the query never returned are fetched by id
    for i in sorted(cur["include"] - seen):
        if i in by_pool:
            add(by_pool[i])
    missing = sorted(cur["include"] - seen)
    if missing:
        try:
            for e in arxiv_get({"id_list": ",".join(missing), "max_results": len(missing)}).findall("a:entry", NS):
                add(e)
        except Exception as e:
            print(f"  include lookup failed ({e})", file=sys.stderr)

    if not papers:
        mc.fail("no papers matched in the last %d weeks — loosen [arxiv] queries or [filter] topic" % weeks)
    papers.sort(key=lambda p: (p["date"], p["id"]), reverse=True)

    # ---- Semantic Scholar: author IDs, citations, venues it knows about ----
    s2 = s2_enrich(papers)
    active = []
    if s2:
        au, au_name = collections.Counter(), {}
        for p in papers:
            row = s2.get(p["id"])
            if not row:
                continue
            p["cites"] = row.get("citationCount") or 0
            if not p["venue"]:
                p["venue"] = s2_venue(row)
            for a in row.get("authors") or []:
                if a.get("authorId"):
                    au[a["authorId"]] += 1
                    au_name[a["authorId"]] = a.get("name") or ""
        active = [{"name": au_name[i], "id": i, "n": n} for i, n in au.most_common(12) if n >= 3]
        print(f"  Semantic Scholar: {len(s2)}/{len(papers)} papers matched", file=sys.stderr)

    # ---- weekly buckets, oldest first; the last bucket ends today ----
    def week_of(date_iso):
        return (today - dt.date.fromisoformat(date_iso)).days // 7   # 0 = this week

    def weekly(ps):
        w = [0] * weeks
        for p in ps:
            k = week_of(p["date"])
            if 0 <= k < weeks:
                w[weeks - 1 - k] += 1
        return w
    week_starts = [(today - dt.timedelta(days=7 * (weeks - 1 - i) + 6)).isoformat() for i in range(weeks)]

    def growth(ps):
        now = sum(1 for p in ps if week_of(p["date"]) < 4)
        before = sum(1 for p in ps if 4 <= week_of(p["date"]) < 8)
        return now, before, (None if min(now, before) < MIN_FOR_TREND else round(100 * (now - before) / before))

    research = [p for p in papers if not p["app"]]
    total = len(research) or 1
    recent8 = (today - dt.timedelta(days=55)).isoformat()

    def representative(ps):
        """Its own main-subject papers from the last eight weeks, ranked by venue,
        citations, public code, match strength and recency; releases come last."""
        pool = [p for p in ps if p["date"] >= recent8] or ps
        return sorted(pool, key=lambda p: (not p["report"], bool(p["venue"]), p.get("cites") or 0, bool(p["code"]),
                                           p["_sc"], p["date"]), reverse=True)[:2]

    subfields = []
    for s in subs:
        sid = s["id"]
        mine = [p for p in research if sid in p["tags"]]
        primary = [p for p in mine if p["tags"][0] == sid]
        now, before, g = growth(mine)
        prev_weeks = collections.Counter(week_of(p["date"]) for p in mine if 4 <= week_of(p["date"]) < 8)
        burst = None
        if before >= 8 and now < before and prev_weeks:   # only worth saying when it explains a drop
            k, n = prev_weeks.most_common(1)[0]
            if n / before >= 0.4:
                burst = {"n": n, "of": before, "week": (today - dt.timedelta(days=7 * k + 6)).isoformat()}
        subfields.append({
            "id": sid, "name": s["name"], "short": s["short"], "desc": s["desc"],
            "count": len(mine), "primary": len(primary),
            "share": round(100 * len(primary) / total, 1),     # main-subject shares sum to 100%
            "last4w": now, "prev4w": before, "trend": g, "burst": burst,
            "weekly": weekly(mine),
            "auto": [{"id": p["id"], "title": p["title"]} for p in representative(primary)],
            "featured": [],
        })
    subfields.sort(key=lambda s: (-s["primary"], -s["count"]))
    # hand-picked representative papers (notes.toml [featured]) come first
    by_id = {p["id"]: p for p in papers}
    extra = arxiv_titles(sorted({i for ids in cur["featured"].values() for i in ids if i not in by_id}))
    for sf in subfields:
        for i in cur["featured"].get(sf["id"], []):
            if i in by_id:
                sf["featured"].append({"id": i, "title": by_id[i]["title"]})
            elif i in extra:
                sf["featured"].append({"id": i, "title": extra[i][0]})
        pinned = [dict(x, pinned=True) for x in sf["featured"]]
        taken = {x["id"] for x in pinned}
        sf["shown"] = (pinned + [dict(x, pinned=False) for x in sf["auto"] if x["id"] not in taken])[:max(2, len(pinned))]
    names = {s["id"]: s["name"] for s in subs}
    for p in papers:
        p["tagnames"] = [names[t] for t in p["tags"]]

    ven = collections.Counter(re.sub(r"\s+(20\d\d)", "", p["venue"]).replace(" Findings", "").replace(" Workshop", "")
                              for p in research if p["venue"])

    # ---- already being cited, normalised by age; technical reports marked ----
    def per_week(p):
        return (p.get("cites") or 0) / max(1, (today - dt.date.fromisoformat(p["date"])).days / 7)
    cited = sorted((p for p in research if (p.get("cites") or 0) >= 3), key=per_week, reverse=True)[:6]
    cited = [{"id": p["id"], "title": p["title"], "cites": p["cites"], "rate": round(per_week(p), 1), "report": p["report"]} for p in cited]

    # ---- where subfields meet: most common pairs ----
    pairs = collections.Counter()
    for p in research:
        t = sorted(p["tags"])
        for i in range(len(t)):
            for j in range(i + 1, len(t)):
                pairs[(t[i], t[j])] += 1
    top_pairs = [{"a": names[a], "b": names[b], "ida": a, "idb": b, "n": n} for (a, b), n in pairs.most_common(8)]

    # ---- rising terms: title words/bigrams, last 8 weeks vs the rest ----
    # z-scored log-odds ratio with an informative Dirichlet prior (Monroe, Colaresi &
    # Quinn 2008): the field's everyday words get no free ride, and a term must also
    # be clearly more common than before.
    recent = [p for p in research if week_of(p["date"]) < RISE_WEEKS]
    older = [p for p in research if week_of(p["date"]) >= RISE_WEEKS]
    rc, bc = collections.Counter(), collections.Counter()
    for p in recent:
        rc.update(terms_of(p["title"]))
    for p in older:
        bc.update(terms_of(p["title"]))
    allc = rc + bc
    n_all = sum(allc.values()) or 1
    a0 = 500.0
    n_r, n_b = sum(rc.values()) or 1, sum(bc.values()) or 1
    nr, nb = max(len(recent), 1), max(len(older), 1)
    rising = []
    for term, c in rc.items():
        if c < 4 or term in field_words:
            continue
        aw = a0 * allc[term] / n_all
        lr = math.log((c + aw) / (n_r + a0 - c - aw))
        lb = math.log((bc[term] + aw) / (n_b + a0 - bc[term] - aw))
        z = (lr - lb) / math.sqrt(1 / (c + aw) + 1 / (bc[term] + aw))
        lift = (c / nr) / ((bc[term] + 1) / nb)
        if lift >= 1.5 and z >= 1.0:
            rising.append((z, c, term, lift))
    rising.sort(reverse=True)
    picked, words_used = [], set()
    for z, c, term, lift in rising:
        parts = set(term.split())
        if parts & words_used and " " not in term:   # skip a word already shown inside a bigram
            continue
        picked.append({"term": term, "n": c, "lift": round(lift, 1), "z": round(z, 1)})
        words_used |= parts
        if len(picked) == 10:
            break

    for p in papers:
        p.pop("_sc", None)
    out = {
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "weeks": weeks, "since": since.isoformat(), "today": today.isoformat(),
        "total": len(research),
        "applications": sum(1 for p in papers if p["app"]),
        "rise_weeks": RISE_WEEKS,
        "last4w": sum(1 for p in research if week_of(p["date"]) < 4),
        "this_week": sum(1 for p in research if week_of(p["date"]) == 0),
        "benchmarks": sum(1 for p in research if p["bench"]),
        "watch": watch, "watched": sum(1 for p in papers if p["watch"]),
        "week_starts": week_starts,
        "weekly": weekly(research),
        "max_weekly_total": max(weekly(research) or [0]),
        "max_weekly": max([max(s["weekly"]) for s in subfields] or [0]),
        "max_count": max([s["count"] for s in subfields] or [0]),
        "subfields": subfields,
        "pairs": top_pairs,
        "active_authors": active,
        "authors_disambiguated": bool(s2),
        "most_cited": cited,
        "picks": [{"id": p["id"], "title": p["title"], "note": p["pick"] if isinstance(p["pick"], str) else "", "date": p["date"]}
                  for p in papers if p.get("pick") is not None],
        "min_for_trend": MIN_FOR_TREND,
        "venues": [{"name": v, "n": n} for v, n in ven.most_common(10)],
        "accepted": sum(1 for p in research if p["venue"]),
        "with_code": sum(1 for p in research if p["code"]),
        "rising": picked,
        "new_benchmarks": [{"id": p["id"], "title": p["title"], "date": p["date"]} for p in research if p["bench"]][:6],
        "listed_total": len(papers),
        "papers": papers,
    }
    os.makedirs(mc.DATA, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {len(papers)} papers ({weeks} weeks) to {os.path.relpath(OUT, mc.ROOT)}; "
          f"{arxiv.calls} arXiv call(s) by this field", file=sys.stderr)


UNREACHABLE = 3


def cli():
    try:
        main()
    except SystemExit:
        raise                      # a problem in map.toml: say so and fail
    except Exception as exc:
        # keep yesterday's data (the page still builds from it), but don't call it a success
        print(f"fetch failed, keeping the existing data: {exc}", file=sys.stderr)
        sys.exit(UNREACHABLE)


if __name__ == "__main__":
    cli()
