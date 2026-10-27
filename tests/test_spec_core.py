from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from spec_core import SpecError, load_json, safe_relative_path, validate_spec


class SpecCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.example = load_json(ROOT / "examples" / "kundur-fault.json")

    def test_all_examples_validate(self) -> None:
        for path in sorted((ROOT / "examples").glob("*.json")):
            with self.subTest(path=path.name):
                validate_spec(load_json(path))

    def test_unknown_field_is_rejected(self) -> None:
        spec = copy.deepcopy(self.example)
        spec["jobs"][0]["surprise"] = 1
        with self.assertRaisesRegex(SpecError, "unknown field"):
            validate_spec(spec)

    def test_tds_requires_final_time_or_stages(self) -> None:
        spec = copy.deepcopy(self.example)
        spec["jobs"][0]["routine_config"].pop("tf")
        with self.assertRaisesRegex(SpecError, "TDS requires"):
            validate_spec(spec)

    def test_final_time_must_cover_event(self) -> None:
        spec = copy.deepcopy(self.example)
        spec["jobs"][0]["routine_config"]["tf"] = 1.05
        with self.assertRaisesRegex(SpecError, "cover all event times"):
            validate_spec(spec)

    def test_pre_setup_numerical_change_is_rejected(self) -> None:
        spec = copy.deepcopy(self.example)
        spec["jobs"][0]["pre_setup"] = [
            {"op": "set_parameter", "model": "GENROU", "field": "M", "idx": 1, "value": 10, "base": "device"}
        ]
        with self.assertRaisesRegex(SpecError, "allowed operations"):
            validate_spec(spec)

    def test_set_parameter_requires_base(self) -> None:
        spec = copy.deepcopy(self.example)
        spec["jobs"][0]["post_setup"] = [
            {"op": "set_parameter", "model": "GENROU", "field": "M", "idx": 1, "value": 10}
        ]
        with self.assertRaisesRegex(SpecError, "base"):
            validate_spec(spec)

    def test_output_path_escape_is_rejected(self) -> None:
        spec = copy.deepcopy(self.example)
        spec["jobs"][0]["outputs"]["plots"][0]["file"] = "../escape.png"
        with self.assertRaisesRegex(SpecError, "relative path inside the output root"):
            validate_spec(spec)

    def test_pflow_routine_args_are_empty(self) -> None:
        spec = load_json(ROOT / "examples" / "pflow-ieee14.json")
        spec["jobs"][0]["routine_args"] = {"unknown": 1}
        with self.assertRaisesRegex(SpecError, "unknown field"):
            validate_spec(spec)

    def test_cpf_requires_a_target(self) -> None:
        spec = load_json(ROOT / "examples" / "cpf.json")
        spec["jobs"][0]["routine_args"] = {}
        with self.assertRaisesRegex(SpecError, "CPF requires"):
            validate_spec(spec)

    def test_lav_rejects_chi_square(self) -> None:
        spec = load_json(ROOT / "examples" / "state-estimation.json")
        spec["jobs"][1]["routine_args"]["chi_squared"] = True
        with self.assertRaisesRegex(SpecError, "only to WLS"):
            validate_spec(spec)

    def test_generic_state_estimation_measurement_is_rejected(self) -> None:
        spec = load_json(ROOT / "examples" / "state-estimation.json")
        spec["jobs"][0]["routine_args"]["measurements"] = [
            {"type": "generic", "model": "Bus", "variable": "v", "sigma": 0.01}
        ]
        with self.assertRaisesRegex(SpecError, "allowed values"):
            validate_spec(spec)

    def test_large_run_requires_explicit_approval(self) -> None:
        spec = load_json(ROOT / "examples" / "pflow-ieee14.json")
        spec["defaults"] = {"max_jobs": 1}
        spec["jobs"] = [copy.deepcopy(spec["jobs"][0]), copy.deepcopy(spec["jobs"][0])]
        spec["jobs"][0]["id"] = "a"
        spec["jobs"][1]["id"] = "b"
        with self.assertRaisesRegex(SpecError, "large_run_approved"):
            validate_spec(spec)
        spec["defaults"]["large_run_approved"] = True
        validate_spec(spec)

    def test_criterion_requires_basis(self) -> None:
        spec = load_json(ROOT / "examples" / "pflow-ieee14.json")
        del spec["jobs"][0]["checks"]["criteria"][0]["basis"]
        with self.assertRaisesRegex(SpecError, "basis"):
            validate_spec(spec)

    def test_safe_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(safe_relative_path(root, "a/b.csv"), (root / "a/b.csv").resolve())
            with self.assertRaises(SpecError):
                safe_relative_path(root, "../outside")


if __name__ == "__main__":
    unittest.main()
