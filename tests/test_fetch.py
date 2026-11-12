"""End-to-end tests for scripts/fetch.py, with arXiv and Semantic Scholar faked.

Run: python3 -m unittest discover -s tests
"""
import datetime as dt
import io
import json
import os
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr
from unittest import mock

from _env import TMP, TODAY, pid  # noqa: E402  (must come first: isolates data/)
import fetch  # noqa: E402


def entry(n, title, abstract="", days_ago=1, comment="", authors=("A. Author",), cats=("cs.CV",)):
    date = (TODAY - dt.timedelta(days=days_ago)).isoformat()
    who = "".join(f"<author><name>{a}</name></author>" for a in authors)
    return (f"<entry><id>http://arxiv.org/abs/{pid(n)}v1</id><published>{date}T00:00:00Z</published>"
            f"<title>{title}</title><summary>{abstract}</summary>{who}"
            f"<arxiv:comment>{comment}</arxiv:comment><arxiv:primary_category term='{cats[0]}'/>"
            + "".join(f"<category term='{c}'/>" for c in cats) + "</entry>")


def feed(entries):
    return ET.fromstring('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">'
                         + "".join(entries) + "</feed>")


QUERY = [  # what the search query returns, newest first
    entry(1, "Table recognition with tables", "We study table structure.", comment="ICML 2026",
          authors=("Ada Lovelace", "B. Other")),
    entry(2, "Charts and tables together", "We introduce a new chart benchmark with tables and charts.",
          comment="Code released; we compare with methods in CVPR"),
    entry(3, "Table parsing that a human excluded", "Tables tables."),
    entry(4, "The periodic table of elements", "A periodic table chart."),
    entry(5, "Cooking recipes", "Nothing about the field."),
    entry(6, "Chart reasoning", "Charts.", comment="Submitted to NeurIPS 2026"),
    entry(7, "An old table paper", "Tables.", days_ago=60),
]
BY_ID = {  # what an id_list lookup returns
    pid(9): entry(9, "Visual reasoning over figures", "No rule matches this one.", days_ago=2),
}


def fake_arxiv(params, timeout=60):
    if "id_list" in params:
        return feed([BY_ID[i] for i in params["id_list"].split(",") if i in BY_ID])
    start, size = params["start"], params["max_results"]
    return feed(QUERY[start:start + size])


def run(**patches):
    assert os.path.realpath(fetch.mc.DATA) == os.path.realpath(TMP)
    err = io.StringIO()
    with mock.patch.object(fetch, "arxiv_get", fake_arxiv), mock.patch.object(fetch, "s2_enrich", lambda p: None), \
            mock.patch.object(fetch.time, "sleep", lambda s: None), redirect_stderr(err):
        for k, v in patches.items():
            setattr(fetch, k, v)
        try:
            fetch.main()
        finally:
            fetch.PAGE, fetch.MAX_RESULTS = 400, 3200
    with open(os.path.join(TMP, "survey.json"), encoding="utf-8") as f:
        return json.load(f), err.getvalue()


class FetchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, cls.log = run()
        cls.p = {p["id"]: p for p in cls.out["papers"]}

    def test_filing(self):
        self.assertEqual(self.p[pid(1)]["tags"], ["tables"])
        self.assertEqual(set(self.p[pid(2)]["tags"]), {"tables", "charts"})   # several subfields

    def test_gates(self):
        self.assertNotIn(pid(3), self.p, "notes.toml exclude")
        self.assertNotIn(pid(4), self.p, "[filter] exclude")
        self.assertNotIn(pid(5), self.p, "off-topic")
        self.assertNotIn(pid(7), self.p, "outside the window")

    def test_include_fetched_by_id_with_tag(self):
        self.assertIn(pid(9), self.p)
        self.assertEqual(self.p[pid(9)]["tags"], ["charts"])

    def test_venue(self):
        self.assertEqual(self.p[pid(1)]["venue"], "ICML 2026")      # bare venue + year
        self.assertEqual(self.p[pid(2)]["venue"], "")               # "methods in CVPR" is no acceptance
        self.assertEqual(self.p[pid(6)]["venue"], "")               # under review

    def test_flags(self):
        self.assertTrue(self.p[pid(1)]["watch"])
        self.assertTrue(self.p[pid(2)]["bench"])
        self.assertEqual(self.out["accepted"], 1)

    def test_no_cap_warning_when_window_covered(self):
        self.assertNotIn("WARNING", self.log)

    def test_cap_warning(self):
        _, log = run(PAGE=2, MAX_RESULTS=2)          # stops after 2 results, window not reached
        self.assertIn("WARNING", log)


if __name__ == "__main__":
    unittest.main()


class UnreachableTest(unittest.TestCase):
    """arXiv answers 429 to every call: the old data stays, and the run says it failed."""

    def test_429_everywhere_keeps_data_and_exits_unreachable(self):
        run()                                        # a good snapshot to keep
        path = os.path.join(TMP, "survey.json")
        with open(path, "rb") as f:
            before = f.read()

        def refuse(params, timeout=60):
            raise urllib.error.HTTPError("https://export.arxiv.org/api/query", 429, "Too Many Requests", {}, None)

        with mock.patch.object(fetch, "arxiv_get", refuse), mock.patch.object(fetch.time, "sleep", lambda s: None), \
                redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as cm:
                fetch.cli()
        self.assertEqual(cm.exception.code, fetch.UNREACHABLE)
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("keeping the existing data", err.getvalue())
        with open(path, "rb") as f:
            self.assertEqual(f.read(), before)
