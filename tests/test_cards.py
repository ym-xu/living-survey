"""Unit tests for the quote check and the methods x tasks matrix in scripts/cards.py."""
import unittest

import _env  # noqa: F401  (must come first: isolates data/)
import cards  # noqa: E402

TASKS = ["table recognition", "chart question answering", "other"]
METHODS = ["reinforcement learning", "synthetic data generation", "other"]
ABSTRACT = "We train a table recognizer with reinforcement learning on synthetic data — and it works."


class QuoteTest(unittest.TestCase):
    def test_found_ignores_case_dashes_and_punctuation(self):
        self.assertTrue(cards.found("Reinforcement-Learning on synthetic data", ABSTRACT))
        self.assertFalse(cards.found("supervised learning on synthetic data", ABSTRACT))
        self.assertFalse(cards.found("", ABSTRACT))


class ConformTest(unittest.TestCase):
    def raw(self, **kw):
        card = {"one_line": "A table recognizer.", "contribution": {"value": "dataset", "evidence": ""},
                "tasks": [{"value": "table recognition", "evidence": "train a table recognizer"}],
                "methods": [{"value": "reinforcement learning", "role": "proposed", "evidence": "with reinforcement learning"},
                            {"value": "made up", "role": "weird", "evidence": "x"},
                            {"value": "reinforcement learning", "role": "used", "evidence": "dup"}],
                "new_resource": {"kind": "none"}}
        card.update(kw)
        return card

    def test_aliases_unknowns_and_duplicates(self):
        card, bad = cards.conform(self.raw(), TASKS, METHODS)
        self.assertEqual(bad, [])
        self.assertEqual(card["contribution"]["value"], "benchmark / dataset")
        self.assertEqual([m["value"] for m in card["methods"]], ["reinforcement learning", "other"])
        self.assertEqual(card["methods"][1]["role"], "proposed")

    def test_problems_are_reported(self):
        _, bad = cards.conform(self.raw(one_line="", contribution={"value": "poem"}), TASKS, METHODS)
        self.assertEqual(len(bad), 2)
        self.assertEqual(cards.conform("nope", TASKS, METHODS), (None, ["not a JSON object"]))


class CompactTest(unittest.TestCase):
    def test_unverified_quotes_drop_their_tag(self):
        card, _ = cards.conform({
            "one_line": "x", "contribution": {"value": "method", "evidence": "train a table recognizer"},
            "tasks": [{"value": "table recognition", "evidence": "train a table recognizer"},
                      {"value": "chart question answering", "evidence": "answers chart questions"}],   # not in abstract
            "methods": [{"value": "synthetic data generation", "role": "used", "evidence": "on synthetic data"}],
            "new_resource": {"kind": "dataset", "name": "Fake", "evidence": "we release Fake"}}, TASKS, METHODS)
        c = cards.compact(card, "Title", ABSTRACT, "m", "sig")
        self.assertEqual(c["t"], ["table-recognition"])
        self.assertEqual(c["mu"], ["synthetic-data-generation"])
        self.assertEqual(c["r"], "none")                     # resource quote not found
        self.assertEqual(c["q"], [3, 4])


class MatrixTest(unittest.TestCase):
    def test_quiet_cell(self):
        tasks = [("table recognition", "Tables"), ("chart question answering", "ChartQA")]
        methods = [("reinforcement learning", "RL"), ("synthetic data generation", "Synth")]
        papers, store = [], {}
        # RL is common, tables are common, but they never meet
        for i in range(12):
            pid = f"p{i}"
            papers.append({"id": pid})
            m = "reinforcement-learning" if i < 6 else "synthetic-data-generation"
            t = "chart-question-answering" if i < 6 else "table-recognition"
            store[pid] = {"mp": [m], "t": [t]}
        mx = cards.matrix(papers, store, tasks, methods, 5, 5)
        quiet = {(q["m"], q["t"]) for q in mx["quiet"]}
        self.assertIn(("reinforcement-learning", "table-recognition"), quiet)
        self.assertEqual(mx["n"], 12)


if __name__ == "__main__":
    unittest.main()
