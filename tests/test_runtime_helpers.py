from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from andes_runtime import aggregate_values, andes_compatibility, apply_set_status, compare_value


class _Provider:
    def __init__(self, values):
        self.v = list(values)


class _StatusModel:
    def __init__(self):
        self.idx = _Provider(["L1"])
        self.u = _Provider([1])
        self.ue = _Provider([1])
        self.n = 1

    def set(self, field, idx, value, **kwargs):
        self.u.v[0] = value


class _StatusSystem:
    def __init__(self, setup):
        self.is_setup = setup
        self.Line = _StatusModel()
        self.models = {"Line": self.Line}
        self.groups = {}
        self.calls = []

    def set_status(self, model, idx, value):
        self.calls.append((model, idx, value))
        self.Line.u.v[0] = value
        self.Line.ue.v[0] = value


class RuntimeHelperTests(unittest.TestCase):
    def test_aggregates(self) -> None:
        values = [[1.0, 2.0], [3.0, 4.0]]
        self.assertEqual(aggregate_values(values, "min"), 1.0)
        self.assertEqual(aggregate_values(values, "max"), 4.0)
        self.assertEqual(aggregate_values(values, "mean"), 2.5)
        self.assertEqual(aggregate_values(values, "range"), 3.0)
        self.assertEqual(aggregate_values(values, "final"), [3.0, 4.0])

    def test_comparisons_apply_to_all_final_values(self) -> None:
        self.assertTrue(compare_value([0.96, 1.01], ">=", threshold=0.95))
        self.assertFalse(compare_value([0.94, 1.01], ">=", threshold=0.95))
        self.assertTrue(compare_value([0.96, 1.01], "between", bounds=[0.95, 1.05]))
        self.assertTrue(compare_value([0.90, 1.10], "outside", bounds=[0.95, 1.05]))

    def test_equality_uses_absolute_tolerance(self) -> None:
        self.assertTrue(compare_value(1.0001, "==", threshold=1.0, atol=0.001))
        self.assertFalse(compare_value(1.01, "==", threshold=1.0, atol=0.001))

    def test_version_compatibility(self) -> None:
        self.assertTrue(andes_compatibility("2.0.0")["supported"])
        self.assertTrue(andes_compatibility("2.1.0")["supported"])
        self.assertTrue(andes_compatibility("1.10.1.post50+geda5163c9")["supported"])
        self.assertFalse(andes_compatibility("1.10.1")["supported"])
        self.assertFalse(andes_compatibility("3.0.0")["supported"])

    def test_status_api_is_phase_aware(self) -> None:
        pre = _StatusSystem(setup=False)
        record = apply_set_status(pre, {"op": "set_status", "model": "Line", "idx": "L1", "value": 0})
        self.assertEqual(record["api"], "Line.set('u')")
        self.assertEqual(pre.calls, [])

        post = _StatusSystem(setup=True)
        record = apply_set_status(post, {"op": "set_status", "model": "Line", "idx": "L1", "value": 0})
        self.assertEqual(record["api"], "System.set_status")
        self.assertEqual(post.calls, [("Line", "L1", 0)])


if __name__ == "__main__":
    unittest.main()
