from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from quality_audit import audit


class QualityAuditTest(unittest.TestCase):
    def test_structure_checks_pass_without_a_score(self):
        report = audit()
        self.assertTrue(report["passed"], report["failed"])
        self.assertNotIn("score", report)


if __name__ == "__main__":
    unittest.main()
