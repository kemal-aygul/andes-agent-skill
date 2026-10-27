from __future__ import annotations

import json
import unittest
from pathlib import Path

try:  # jsonschema is an optional developer dependency.
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised in environments without the extra
    Draft202012Validator = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(Draft202012Validator is not None, "jsonschema is not installed")
class JsonSchemaTests(unittest.TestCase):
    def test_examples_match_schema(self) -> None:
        schema = json.loads((ROOT / "schemas" / "andes-study.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        for path in sorted((ROOT / "examples").glob("*.json")):
            with self.subTest(path=path.name):
                errors = sorted(validator.iter_errors(json.loads(path.read_text(encoding="utf-8"))), key=lambda error: list(error.path))
                self.assertEqual([], errors, "\n".join(error.message for error in errors))

    def test_bundle_manifest_matches_run_manifest_schema(self) -> None:
        import sys
        import tempfile

        sys.path.insert(0, str(ROOT / "scripts"))
        from andes_workflow import generate_bundle

        schema = json.loads((ROOT / "schemas" / "run-manifest.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            destination = Path(tmp) / "bundle"
            generate_bundle(ROOT / "examples" / "pflow-ieee14.json", destination, live=False, force=False)
            manifest = json.loads((destination / "bundle_manifest.json").read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(manifest))
        self.assertEqual([], errors, "\n".join(error.message for error in errors))


if __name__ == "__main__":
    unittest.main()
