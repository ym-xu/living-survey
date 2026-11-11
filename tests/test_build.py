"""Tests for scripts/build.py: finding fields, the catalog data and the subfield feeds."""
import json
import os
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

import _env  # noqa: F401  (must come first: isolates data/)
import build as S  # noqa: E402

MAP = """[map]
title = "{title}: A Living Map"
description = "About {title}."
[arxiv]
categories = ["cs.CL"]
queries = ["ti:x"]
[filter]
topic = ["x"]
[[subfield]]
id = "a"
name = "Alpha"
match = ["a"]
"""


def survey(today="2026-11-11"):
    paper = lambda i, date, tags, app=False: {"id": i, "title": f"Paper {i}", "date": date, "tags": tags, "authors": ["A", "B", "C", "D"],
                                              "venue": "", "abs": "An abstract.", "app": app}
    return {"today": today, "updated": "2026-11-11 06:00 UTC", "total": 3, "last4w": 2,
            "subfields": [{"id": "a", "name": "Alpha", "short": "A", "desc": "Alpha papers", "count": 2, "last4w": 2, "trend": None},
                          {"id": "b", "name": "Beta", "short": "B", "desc": "", "count": 1, "last4w": 0, "trend": None}],
            "papers": [paper("1", "2026-11-10", ["a"]), paper("2", "2026-11-09", ["a", "b"]),
                       paper("3", "2026-11-08", ["a"], app=True), paper("4", "2026-10-01", ["b"])]}


class SiteTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ls-site-")
        self.addCleanup(shutil.rmtree, self.root)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_single_field_without_fields_dir(self):
        fs = S.fields(self.root)
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0]["id"], "")
        self.assertEqual(fs[0]["out"], "")
        self.assertEqual(fs[0]["data"], os.path.join(self.root, "data"))

    def test_many_fields_in_catalog_order(self):
        for f in ("zeta", "alpha", "mid"):
            self.write(f"fields/{f}/map.toml", MAP.format(title=f))
        os.makedirs(os.path.join(self.root, "fields", "not-a-field"))           # no map.toml: ignored
        self.write("fields/catalog.toml", 'order = ["mid"]\n')
        self.assertEqual([f["id"] for f in S.fields(self.root)], ["mid", "alpha", "zeta"])
        f = S.fields(self.root)[0]
        self.assertEqual(f["out"], "fields/mid/")
        self.assertEqual(f["data"], os.path.join(self.root, "data", "fields", "mid"))

    def test_catalog_data_recent_and_research_only(self):
        self.write("fields/one/map.toml", MAP.format(title="One"))
        self.write("fields/two/map.toml", MAP.format(title="Two"))                # no data yet
        self.write("data/fields/one/survey.json", json.dumps(survey()))
        c = S.catalog_data(self.root)
        one, two = c["fields"]
        self.assertEqual(one["title"], "One: A Living Map")
        self.assertEqual([p["id"] for p in one["recent"]], ["1", "2"])          # not the application, not the old one
        self.assertEqual(one["recent"][0]["authors"], ["A", "B", "C"])
        self.assertEqual(two["recent"], [])
        self.assertEqual(two["updated"], "")

    def test_feeds(self):
        self.write("fields/one/map.toml", MAP.format(title="One"))
        self.write("data/fields/one/survey.json", json.dumps(survey()))
        f = S.fields(self.root)[0]
        out = os.path.join(self.root, "public", f["out"])
        self.assertEqual(S.write_feeds(f, out, "https://x.org/site"), 2)
        ch = ET.parse(os.path.join(out, "feeds", "a.xml")).getroot().find("channel")
        self.assertEqual(ch.find("link").text, "https://x.org/site/fields/one/#tag=a")
        self.assertEqual([i.find("link").text for i in ch.findall("item")],
                         ["https://arxiv.org/abs/1", "https://arxiv.org/abs/2"])            # application left out
        b = ET.parse(os.path.join(out, "feeds", "b.xml")).getroot().find("channel")
        self.assertEqual(len(b.findall("item")), 2)

    def test_hugo_config_quotes_paths(self):
        path = S.hugo_config(self.root, "x", "https://x.org/", '/tmp/a "b"', "/d", "/m.toml", None, params={"catalog": True})
        import tomllib
        with open(path, "rb") as fh:
            cfg = tomllib.load(fh)
        self.assertEqual(cfg["publishDir"], '/tmp/a "b"')
        self.assertTrue(cfg["params"]["catalog"])
        self.assertEqual([m["target"] for m in cfg["module"]["mounts"]], ["data", "data/map.toml"])


if __name__ == "__main__":
    unittest.main()
