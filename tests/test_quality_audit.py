from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from quality_audit import audit


class QualityAuditTest(unittest.TestCase):
    def test_enterprise_quality_floor_is_explicit_and_met(self):
        report = audit()
        self.assertEqual(report["possible"], 100)
        self.assertGreaterEqual(report["score"], 95, report["failed_checks"])
        self.assertTrue(report["passed"])


if __name__ == "__main__":
    unittest.main()
