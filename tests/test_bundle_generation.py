from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from andes_workflow import generate_bundle
from andes_runtime import StudyExecutionError


class BundleGenerationTests(unittest.TestCase):
    def test_generate_without_andes(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            destination = Path(tmp) / "bundle"
            result = generate_bundle(ROOT / "examples" / "pflow-ieee14.json", destination, live=False, force=False)
            self.assertTrue(result["ok"])
            for name in ("study_spec.json", "run_andes.py", "README-run.md", "preflight.json", "bundle_manifest.json"):
                self.assertTrue((destination / name).is_file(), name)
            self.assertTrue((destination / "runtime" / "andes_runtime.py").is_file())
            self.assertTrue((destination / "runtime" / "spec_core.py").is_file())

    def test_nonempty_destination_requires_force(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            destination = Path(tmp) / "bundle"
            destination.mkdir()
            (destination / "keep.txt").write_text("keep")
            with self.assertRaises(StudyExecutionError):
                generate_bundle(ROOT / "examples" / "pflow-ieee14.json", destination, live=False, force=False)
            self.assertTrue((destination / "keep.txt").is_file())
            generate_bundle(ROOT / "examples" / "pflow-ieee14.json", destination, live=False, force=True)
            self.assertFalse((destination / "keep.txt").exists())


if __name__ == "__main__":
    unittest.main()
