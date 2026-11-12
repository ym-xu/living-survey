"""scripts/arxiv.py: the polite client (gap, Retry-After, giving up) and local search."""
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from unittest import mock

import _env  # noqa: F401  (must come first: isolates data/ and blocks the network)
import arxiv  # noqa: E402

FEED = b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'


def err(code, retry_after=None):
    return urllib.error.HTTPError("https://export.arxiv.org/api/query", code, "x",
                                  {"Retry-After": retry_after} if retry_after else {}, None)


class Ok:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return FEED


class ClientTest(unittest.TestCase):
    def run_get(self, answers):
        """answers: exceptions to raise or None for success, in order. Returns the sleeps."""
        sleeps, it = [], iter(answers)

        def urlopen(req, timeout=0):
            a = next(it)
            if a:
                raise a
            return Ok()
        arxiv._last = 0.0
        with mock.patch.object(arxiv.urllib.request, "urlopen", urlopen), \
                mock.patch.object(arxiv.time, "sleep", sleeps.append), mock.patch.object(arxiv.time, "time", lambda: 1000.0), \
                mock.patch("sys.stderr"):
            try:
                arxiv.get({"id_list": "x"})
            finally:
                arxiv._last = 0.0
        return sleeps

    def test_honours_retry_after_and_backs_off_longer(self):
        sleeps = self.run_get([err(429, "120"), err(429, "5"), err(503), None])
        waits = [s for s in sleeps if s != arxiv.MIN_GAP]
        self.assertEqual(waits, [120, 60, 120])          # Retry-After when longer, else 30 s doubling

    def test_keeps_the_gap_between_calls(self):
        sleeps = self.run_get([err(429, "1"), None])
        self.assertIn(arxiv.MIN_GAP, sleeps)              # the retry still waits out the gap

    def test_gives_up_as_unreachable(self):
        with self.assertRaises(arxiv.Unreachable):
            self.run_get([err(429)] * arxiv.TRIES)

    def test_a_404_is_not_retried(self):
        calls = []

        def urlopen(req, timeout=0):
            calls.append(req)
            raise err(404)
        with mock.patch.object(arxiv.urllib.request, "urlopen", urlopen), mock.patch.object(arxiv.time, "sleep", lambda s: None):
            with self.assertRaises(arxiv.Unreachable):
                arxiv.get({"id_list": "x"})
        self.assertEqual(len(calls), 1)


def e(title, abstract, cats=("cs.CV",)):
    c = "".join(f"<category term='{x}'/>" for x in cats)
    return ET.fromstring(f'<entry xmlns="http://www.w3.org/2005/Atom"><title>{title}</title><summary>{abstract}</summary>{c}</entry>')


class QueryTest(unittest.TestCase):
    def test_porter_like_arxiv(self):
        # what arXiv's search showed (2026-11-12): documents ~ document, augmentation ~ augmented
        for a, b in (("documents", "Document"), ("augmented", "augmentation"), ("augmented", "augments"),
                     ("understanding", "understand"), ("relational", "relate")):
            self.assertEqual(arxiv.stem(a.lower()), arxiv.stem(b.lower()), (a, b))
        self.assertNotEqual(arxiv.stem("table"), arxiv.stem("tablet"))

    def test_terms_phrases_and_categories(self):
        q = arxiv.Query.parse(["cs.CV"], ['ti:documents', 'abs:"retrieval augmented"', "abs:OCR-free"])
        self.assertTrue(q.matches(e("A Document Parser", "x")))
        self.assertTrue(q.matches(e("x", "We study retrieval-augmentation here.")))
        self.assertTrue(q.matches(e("x", "An OCR free model.")))
        self.assertFalse(q.matches(e("x", "augmented retrieval")))               # phrase order matters
        self.assertFalse(q.matches(e("Documents", "x", cats=("cs.CL",))))        # wrong category
        self.assertFalse(q.matches(e("x", "documents")))                         # ti: is the title only
        self.assertTrue(q.matches(e("Documents", "x", cats=("cs.CL", "cs.CV")))) # cross-list counts

    def test_unsupported_syntax_means_live(self):
        for bad in ("au:Smith", "ti:doc*", "ti:a AND ti:b", "(ti:x)"):
            self.assertIsNone(arxiv.Query.parse(["cs.CV"], [bad]), bad)


if __name__ == "__main__":
    unittest.main()
