"""The arXiv API, politely, and arXiv's search done locally.

* get(): every call to export.arxiv.org goes through here. At least MIN_GAP seconds
  between calls (arXiv asks for 3); on 429 / 503 it waits what Retry-After says, and
  never less than a backoff that doubles from 30 s. Raises Unreachable when it gives up.
* Query: a field's [arxiv] categories + queries, evaluated on an entry we already have,
  the way arXiv's search does it — words are lower-cased, split at anything that is not
  a letter or digit, and Porter-stemmed ("documents" finds "document", "retrieval
  augmented" finds "retrieval augmentation"); a quoted phrase must appear in order.
  That lets several fields share one download (scripts/pool.py).

Thank you to arXiv for use of its open access interoperability.
"""
import email.utils
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import mapconfig as mc

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
MIN_GAP = 3.5            # seconds between calls
TRIES = 5
BACKOFF = 30             # first wait after a 429 / 503, doubled each time
MAX_WAIT = 600

calls = 0                # calls made by this process (logged by the callers)
_last = 0.0


class Unreachable(RuntimeError):
    pass


def _retry_after(err):
    v = (err.headers or {}).get("Retry-After") if hasattr(err, "headers") else None
    if not v:
        return 0
    try:
        return max(0, int(v))
    except ValueError:                                 # an HTTP date
        when = email.utils.parsedate_to_datetime(v)
        return max(0, int(when.timestamp() - time.time())) if when else 0


def get(params, timeout=90):
    """One API call -> the parsed Atom feed. Rate-limited and retried."""
    global calls, _last
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(TRIES):
        gap = _last + MIN_GAP - time.time()
        if gap > 0:
            time.sleep(gap)
        _last = time.time()
        calls += 1
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": mc.UA}), timeout=timeout) as r:
                return ET.fromstring(r.read())
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise Unreachable(f"HTTP {e.code}") from None
            wait = max(_retry_after(e), BACKOFF * 2 ** attempt) if e.code in (429, 503) else 10 * 2 ** attempt
            why = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ET.ParseError, ConnectionError) as e:
            wait, why = 10 * 2 ** attempt, str(e)
        if attempt == TRIES - 1:
            break
        wait = min(wait, MAX_WAIT)
        print(f"  arXiv: {why}; waiting {wait:.0f} s (try {attempt + 2}/{TRIES})", file=sys.stderr, flush=True)
        time.sleep(wait)
    raise Unreachable(f"arXiv unreachable after {TRIES} tries ({why})")


# ------------------------------------------------------------ entry helpers ----
def clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def entry_id(e):
    return re.sub(r"v\d+$", "", clean(e.findtext("a:id", "", NS)).rsplit("/", 1)[-1])


def published(e):
    return clean(e.findtext("a:published", "", NS))[:10]


def categories(e):
    return {c.get("term") for c in e.findall("a:category", NS)}


# ------------------------------------------------------------- Porter stem ----
# M. F. Porter, "An algorithm for suffix stripping", 1980 — the stemmer behind
# Lucene's PorterStemFilter, which arXiv's search applies.
def _cons(w, i):
    c = w[i]
    if c in "aeiou":
        return False
    if c == "y":
        return i == 0 or not _cons(w, i - 1)
    return True


def _m(stem):
    """Number of VC sequences in stem."""
    n, prev_vowel = 0, False
    for i in range(len(stem)):
        v = not _cons(stem, i)
        if prev_vowel and not v:
            n += 1
        prev_vowel = v
    return n


def _has_vowel(stem):
    return any(not _cons(stem, i) for i in range(len(stem)))


def _double_c(w):
    return len(w) >= 2 and w[-1] == w[-2] and _cons(w, len(w) - 1)


def _cvc(w):
    return (len(w) >= 3 and _cons(w, len(w) - 3) and not _cons(w, len(w) - 2) and _cons(w, len(w) - 1)
            and w[-1] not in "wxy")


def _swap(w, rules, cond):
    for suf, rep in rules:
        if w.endswith(suf):
            stem = w[: len(w) - len(suf)]
            return stem + rep if cond(stem) else w
    return w


_STEP2 = [("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"), ("izer", "ize"), ("bli", "ble"),
          ("alli", "al"), ("entli", "ent"), ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
          ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"), ("ousness", "ous"), ("aliti", "al"),
          ("iviti", "ive"), ("biliti", "ble"), ("logi", "log")]
_STEP3 = [("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"), ("ical", "ic"), ("ful", ""), ("ness", "")]
_STEP4 = ["al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment", "ent", "ion", "ou", "ism", "ate",
          "iti", "ous", "ive", "ize"]


def stem(w):
    if len(w) <= 2:
        return w
    # 1a
    if w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("ies"):
        w = w[:-2]
    elif w.endswith("ss"):
        pass
    elif w.endswith("s"):
        w = w[:-1]
    # 1b
    again = False
    if w.endswith("eed"):
        if _m(w[:-3]) > 0:
            w = w[:-1]
    elif w.endswith("ed") and _has_vowel(w[:-2]):
        w, again = w[:-2], True
    elif w.endswith("ing") and _has_vowel(w[:-3]):
        w, again = w[:-3], True
    if again:
        if w.endswith(("at", "bl", "iz")):
            w += "e"
        elif _double_c(w) and w[-1] not in "lsz":
            w = w[:-1]
        elif _m(w) == 1 and _cvc(w):
            w += "e"
    # 1c
    if w.endswith("y") and _has_vowel(w[:-1]):
        w = w[:-1] + "i"
    # 2, 3
    w = _swap(w, sorted(_STEP2, key=lambda r: -len(r[0])), lambda s: _m(s) > 0)
    w = _swap(w, sorted(_STEP3, key=lambda r: -len(r[0])), lambda s: _m(s) > 0)
    # 4
    for suf in sorted(_STEP4, key=len, reverse=True):
        if w.endswith(suf):
            s = w[: len(w) - len(suf)]
            if _m(s) > 1 and (suf != "ion" or s.endswith(("s", "t"))):
                w = s
            break
    # 5
    if w.endswith("e"):
        s = w[:-1]
        if _m(s) > 1 or (_m(s) == 1 and not _cvc(s)):
            w = s
    if _m(w) > 1 and _double_c(w) and w.endswith("l"):
        w = w[:-1]
    return w


def stems(text):
    return [stem(t) for t in re.findall(r"[a-z0-9]+", (text or "").lower())]


# ------------------------------------------------------------------ queries ----
_TERM = re.compile(r'^(ti|abs|all):(?:"([^"]+)"|([^\s"()]+))$', re.I)


class Query:
    """A field's arXiv query, evaluated locally. Query.parse() returns None when a term
    uses syntax this does not reproduce (au:, AND, wildcards…): fetch that field live."""

    def __init__(self, categories, terms):
        self.categories = set(categories)
        self.terms = terms                       # [(field, [stems])]

    @classmethod
    def parse(cls, categories, queries):
        terms = []
        for q in queries:
            m = _TERM.match(q.strip())
            if not m or "*" in q or "?" in q:
                return None
            words = stems(m.group(2) or m.group(3))
            if not words:
                return None
            terms.append((m.group(1).lower(), words))
        return cls(categories, terms)

    @staticmethod
    def _has(seq, words):
        n = len(words)
        return any(seq[i:i + n] == words for i in range(len(seq) - n + 1))

    def matches(self, e):
        if not (categories(e) & self.categories):
            return False
        ti = stems(e.findtext("a:title", "", NS))
        ab = stems(e.findtext("a:summary", "", NS))
        for field, words in self.terms:
            if (field in ("ti", "all") and self._has(ti, words)) or (field in ("abs", "all") and self._has(ab, words)):
                return True
        return False
