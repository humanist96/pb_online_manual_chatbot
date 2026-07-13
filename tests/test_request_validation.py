from __future__ import annotations

import math
import pathlib
import sys
import unittest
import urllib.parse


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from request_validation import MAX_QUERY_CHARS, parse_query_params  # noqa: E402


class QueryValidationTests(unittest.TestCase):
    def test_valid_query(self):
        raw = urllib.parse.urlencode({
            "q": "약정 해지 절차", "alpha": "0.4", "topk": "10", "tau": "0.7",
            "types": "qa,description", "rerank": "on", "scope": "화면>계좌",
            "src": "chip",
        })
        p = parse_query_params(raw)
        self.assertEqual(p.q, "약정 해지 절차")
        self.assertEqual(p.topk, 10)
        self.assertEqual(p.types, {"qa", "description"})
        self.assertEqual(p.scope, ["화면", "계좌"])
        self.assertTrue(p.use_rerank)

    def test_defaults(self):
        p = parse_query_params("q=test")
        self.assertEqual((p.alpha, p.topk, p.tau, p.types, p.src),
                         (0.5, 5, None, None, ""))

    def test_rejects_unbounded_or_nonfinite_numbers(self):
        bad = [
            "q=x&topk=0", "q=x&topk=31", "q=x&topk=1000000000",
            "q=x&alpha=nan", "q=x&alpha=inf", "q=x&alpha=-0.1",
            "q=x&tau=NaN", "q=x&tau=1.1",
        ]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_query_params(raw)

    def test_rejects_oversized_duplicate_and_unknown_values(self):
        bad = [
            "q=" + "x" * (MAX_QUERY_CHARS + 1),
            "q=x&q=y", "q=x&types=qa,secret", "q=x&types=qa,qa",
            "q=x&rerank=maybe", "q=x&src=admin",
            "q=x&scope=" + ">".join(["s"] * 9),
            "q=account+123456789012+lookup", "q=test%40example.com",
        ]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_query_params(raw)


if __name__ == "__main__":
    unittest.main()
