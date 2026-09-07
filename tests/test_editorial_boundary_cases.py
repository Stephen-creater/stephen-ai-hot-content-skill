from __future__ import annotations

import json
import unittest
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EditorialBoundaryCasesTest(unittest.TestCase):
    def test_each_surface_feature_has_a_positive_and_negative_boundary(self):
        cases = json.loads((ROOT / "tests/fixtures/editorial_boundary_cases.json").read_text(encoding="utf-8"))
        pairs = defaultdict(list)
        for case in cases:
            pairs[case["pair"]].append(case)
            self.assertGreaterEqual(len(case["case"]), 30)
            self.assertGreaterEqual(len(case["decision_driver"]), 8)
        self.assertGreaterEqual(len(pairs), 5)
        for name, rows in pairs.items():
            self.assertEqual({row["expected"] for row in rows}, {"consider", "reject"}, name)
            self.assertEqual(len({row["surface_feature"] for row in rows}), 1, name)


if __name__ == "__main__":
    unittest.main()
