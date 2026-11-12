"""scripts/pool.py and fetch.py from the pool: one download, the same survey.json."""
import datetime as dt
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

from _env import HERE, TMP, TODAY, pid  # noqa: E402  (must come first)
import arxiv  # noqa: E402
import fetch  # noqa: E402
import pool  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402
from test_fetch import BY_ID, QUERY, entry, feed  # noqa: E402

# The corpus "arXiv" holds: the fetch tests' papers, plus papers only another field wants
CORPUS = QUERY + [
    entry(20, "A chart of tables in cs.CL", "Tables and charts.", cats=("cs.CL",)),   # wrong category for the test field
    entry(21, "Speech translation", "Spoken language.", cats=("cs.CL",)),
    entry(22, "Speech corpus", "We introduce a dataset of tables.", cats=("cs.CV",)),  # other field's term, our category
]


class Engine:
    """A fake arXiv search: (cat:… OR …) AND (term OR …), newest first, paged — matching
    with arxiv.Query, which is what the real search was checked against."""

    def __init__(self):
        self.calls = []

    def __call__(self, params, timeout=60):
        self.calls.append(params)
        if "id_list" in params:
            return feed([BY_ID[i] for i in params["id_list"].split(",") if i in BY_ID])
        q = params["search_query"]
        cats = re.findall(r"cat:(\S+?)[) ]", q)
        terms = re.findall(r'(?:ti|abs|all):(?:"[^"]+"|[^\s()"]+)', q)
        rx = arxiv.Query.parse(cats, terms)
        hits = sorted((x for x in CORPUS if rx.matches(ET.fromstring(feed_entry(x)))),
                      key=lambda x: re.search(r"<published>([^<]+)", x).group(1), reverse=True)
        s, n = params["start"], params["max_results"]
        return feed(hits[s:s + n])


def feed_entry(x):
    return ET.tostring(feed([x]).find("{http://www.w3.org/2005/Atom}entry"))


OTHER = """[map]
title = "Speech: A Living Map"
weeks = 4
[arxiv]
categories = ["cs.CL", "cs.CV"]
queries = ['ti:speech']
[filter]
topic = ['speech']
[[subfield]]
id = "s"
name = "S"
match = ['speech']
"""


class PoolTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ls-pool-")
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = os.path.join(self.dir, "pool.json")
        self.other = os.path.join(self.dir, "other.toml")
        with open(self.other, "w") as f:
            f.write(OTHER)
        self.maps = [os.path.join(HERE, "fixtures", "map.toml"), self.other]
        self.engine = Engine()

    def refresh(self, today=TODAY, maps=None):
        with mock.patch.object(pool.arxiv, "get", self.engine), redirect_stderr(io.StringIO()):
            return pool.refresh(maps or self.maps, self.path, today)

    def test_one_stream_for_the_union(self):
        st = self.refresh()
        self.assertEqual(st["mode"], "full")
        self.assertEqual(st["streams"], 1)
        self.assertEqual(len(self.engine.calls), 1)
        q = self.engine.calls[0]["search_query"]
        for t in ("cat:cs.CL", "cat:cs.CV", "ti:speech", "ti:table", "ti:chart"):
            self.assertIn(t, q)
        with open(self.path) as f:
            ids = set(json.load(f)["entries"])
        self.assertIn(pid(21), ids)            # wanted by the other field only
        self.assertIn(pid(1), ids)
        self.assertNotIn(pid(5), ids)          # wanted by nobody

    def test_incremental_then_weekly_full(self):
        self.refresh()
        self.assertEqual(self.refresh(TODAY + dt.timedelta(days=1))["mode"], "incremental")
        self.assertEqual(self.refresh(TODAY + dt.timedelta(days=pool.FULL_EVERY))["mode"], "full")

    def test_new_terms_mean_a_full_refresh(self):
        self.refresh(maps=self.maps[:1])
        self.assertEqual(self.refresh()["mode"], "full")

    def test_long_unions_are_split(self):
        maps = [(None, {"arxiv": {"categories": ["cs.CL"], "queries": [f'abs:"term number {i}"' for i in range(400)]}})]
        qs = pool.streams(maps)
        self.assertGreater(len(qs), 1)
        self.assertTrue(all(len(q) < pool.MAX_QUERY + 100 for q in qs))
        self.assertEqual(sum(q.count("abs:") for q in qs), 400)

    def test_unreachable_leaves_the_pool(self):
        self.refresh()
        with open(self.path) as f:
            before = f.read()

        def down(params):
            raise arxiv.Unreachable("429")
        with mock.patch.object(pool.arxiv, "get", down), self.assertRaises(arxiv.Unreachable):
            pool.refresh(self.maps, self.path, TODAY + dt.timedelta(days=1))
        with open(self.path) as f:
            self.assertEqual(f.read(), before)

    def test_broken_map_is_skipped(self):
        bad = os.path.join(self.dir, "bad.toml")
        with open(bad, "w") as f:
            f.write("[arxiv\n")
        self.assertEqual(self.refresh(maps=self.maps + [bad])["streams"], 1)


class SameSurveyTest(unittest.TestCase):
    """The point of it all: filing from the pool gives the same survey.json as asking arXiv."""

    def survey(self, use_pool):
        engine = Engine()
        d = tempfile.mkdtemp(prefix="ls-same-")
        self.addCleanup(shutil.rmtree, d)
        other = os.path.join(d, "other.toml")
        with open(other, "w") as f:
            f.write(OTHER)
        path = os.path.join(d, "pool.json")
        with mock.patch.object(pool.arxiv, "get", engine), mock.patch.object(fetch, "arxiv_get", engine), \
                mock.patch.object(fetch, "s2_enrich", lambda p: None), mock.patch.object(fetch, "POOL", path if use_pool else ""), \
                redirect_stderr(io.StringIO()):
            if use_pool:
                pool.refresh([os.path.join(HERE, "fixtures", "map.toml"), other], path)
            fetch.main()
        with open(os.path.join(TMP, "survey.json")) as f:
            out = json.load(f)
        for k in ("updated",):
            out.pop(k)
        return out, engine.calls

    def test_identical(self):
        live, live_calls = self.survey(False)
        shared, _ = self.survey(True)
        self.assertEqual(shared, live)
        self.assertIn(pid(2), {p["id"] for p in shared["papers"]})
        self.assertNotIn(pid(22), {p["id"] for p in shared["papers"]})   # the other field's term, not ours


if __name__ == "__main__":
    unittest.main()
