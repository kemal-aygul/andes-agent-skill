"""Regression tests for the execution/generation safety guards.

The numerical routines are faked using the same provider pattern as
``test_fake_execution.py``.  These tests never import a real ANDES case.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import types
import unittest
from collections import OrderedDict
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import andes_runtime
import andes_workflow
from andes_runtime import StudyExecutionError


# ---------------------------------------------------------------------------
# Fake ANDES objects (same shape as tests/test_fake_execution.py)
# ---------------------------------------------------------------------------


class Provider:
    def __init__(self, values, vin=None):
        self.v = np.asarray(values, dtype=object if any(isinstance(x, str) for x in values) else None)
        self.vin = np.asarray(values if vin is None else vin)


class FakeModel:
    def __init__(self, idx, **fields):
        self.idx = Provider(idx)
        self.n = len(idx)
        self.group = None
        for name, value in fields.items():
            setattr(self, name, Provider(value))

    def set(self, field, idx, value, base=None):
        pos = list(self.idx.v).index(idx)
        provider = getattr(self, field)
        provider.v[pos] = value
        if base == "device":
            provider.vin[pos] = value

    def get(self, field, idx, attr="v"):
        pos = list(self.idx.v).index(idx)
        return getattr(getattr(self, field), attr)[pos]


class FakeConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def keys(self):
        return self.__dict__.keys()


class FakePFlow:
    def __init__(self):
        self.config = FakeConfig(tol=1e-6, max_iter=25)
        self.converged = False
        self.niter = 0

    def run(self):
        self.converged = True
        self.niter = 3
        return True


class UnconvergedPFlow(FakePFlow):
    def run(self):
        self.converged = False
        self.niter = 25
        return False


class FakeSystem:
    def __init__(self, pflow=None):
        self.Bus = FakeModel([1, 2], name=["BUS1", "BUS2"], v=[1.0, 0.98], a=[0.0, -0.1], u=[1, 1])
        self.models = OrderedDict([("Bus", self.Bus)])
        self.groups = OrderedDict()
        self.routines = OrderedDict()
        self.PFlow = pflow or FakePFlow()
        self.files = types.SimpleNamespace(txt="fake_out.txt")
        self.dae = types.SimpleNamespace(x=np.array([]), y=np.array([1.0, 0.98]), f=np.array([]), g=np.array([0.0, 0.0]))

    def setup(self):
        return True


class UnconvergedSystem(FakeSystem):
    def __init__(self):
        super().__init__(pflow=UnconvergedPFlow())


class FakeAndes:
    __version__ = "2.0.0"
    __file__ = __file__

    def config_logger(self, **kwargs):
        return None

    def load(self, case, **kwargs):
        return FakeSystem()


class UnconvergedAndes(FakeAndes):
    def load(self, case, **kwargs):
        return UnconvergedSystem()


# ---------------------------------------------------------------------------
# Spec helpers
# ---------------------------------------------------------------------------


def make_fake_andes(tmp_path: Path, cls: type = FakeAndes):
    """Instantiate a fake module with a real ``__file__`` under ``tmp_path``."""
    fake = cls()
    package_dir = tmp_path / "fake_andes"
    package_dir.mkdir(exist_ok=True)
    module_file = package_dir / "__init__.py"
    module_file.write_text("", encoding="utf-8")
    fake.__file__ = str(module_file)
    return fake


def write_spec(tmp_path: Path, *, require_convergence: bool = True, with_outputs: bool = True):
    """Write a valid minimal PFlow spec (and its local case) under ``tmp_path``."""
    case = tmp_path / "case.json"
    case.write_text("{}", encoding="utf-8")
    job = {
        "id": "pflow",
        "case": {"path": str(case)},
        "routine": "pflow",
        "checks": {"require_convergence": require_convergence, "finite": True},
    }
    if with_outputs:
        job["outputs"] = {"tables": [{"model": "Bus", "fields": ["idx", "name", "v", "a"], "file": "bus.csv"}]}
        job["checks"]["criteria"] = [
            {
                "name": "vmin",
                "model": "Bus",
                "variable": "v",
                "source": "current",
                "aggregate": "min",
                "operator": ">=",
                "threshold": 0.95,
                "basis": "unit test",
            }
        ]
    spec = {
        "schema_version": "1.0",
        "study_name": "guard-test",
        "defaults": {"strict": True, "copy_inputs": True, "overwrite": False, "log_level": 20, "seed": 42},
        "jobs": [job],
    }
    path = tmp_path / "study_spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path, case


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_manifest_consistent(test: unittest.TestCase, manifest_path: Path) -> int:
    """Recompute SHA-256 for every entry of a manifest; return the entry count."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = manifest_path.parent
    checked = 0
    for entry in manifest["files"]:
        relative = entry["path"]
        target = base / relative
        test.assertTrue(target.is_file(), f"missing manifest file: {target}")
        test.assertEqual(entry["size_bytes"], target.stat().st_size, f"size mismatch: {relative}")
        test.assertEqual(entry["sha256"], sha256_file(target), f"sha256 mismatch: {relative}")
        checked += 1
    return checked


class SafetyGuardTests(unittest.TestCase):
    # --- output-destination guards -----------------------------------------
    def test_run_guard_refuses_spec_directory_and_preserves_files(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tmp_path = Path(tmp)
            spec_path, _ = write_spec(tmp_path)
            keep = tmp_path / "keep.txt"
            keep.write_text("keep", encoding="utf-8")

            with self.assertRaises(StudyExecutionError):
                andes_runtime.execute_study(spec_path, output_root=tmp_path, overwrite=True)

            self.assertTrue(spec_path.is_file())
            self.assertTrue(keep.is_file())
            self.assertEqual("keep", keep.read_text(encoding="utf-8"))

    def test_run_guard_refuses_ancestor_of_spec(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            outer = Path(tmp)
            work = outer / "study"
            work.mkdir()
            spec_path, _ = write_spec(work)
            with self.assertRaises(StudyExecutionError):
                andes_runtime.execute_study(spec_path, output_root=outer, overwrite=True)
            self.assertTrue(spec_path.is_file())

    def test_generate_guard_refuses_spec_directory_and_preserves_files(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tmp_path = Path(tmp)
            spec_path, _ = write_spec(tmp_path)
            keep = tmp_path / "keep.txt"
            keep.write_text("keep", encoding="utf-8")

            with self.assertRaises(StudyExecutionError):
                andes_workflow.generate_bundle(spec_path, tmp_path, live=False, force=True)

            self.assertTrue(spec_path.is_file())
            self.assertTrue(keep.is_file())

    def test_generate_into_fresh_subfolder_records_timestamp(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tmp_path = Path(tmp)
            spec_path, _ = write_spec(tmp_path)
            destination = tmp_path / "bundle"
            result = andes_workflow.generate_bundle(spec_path, destination, live=False, force=True)
            self.assertTrue(result["ok"])
            manifest = json.loads((destination / "bundle_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("generated_at_utc", manifest)
            self.assertTrue(manifest["files"])
            self.assertTrue((destination / "run_andes.py").is_file())

    # --- manifest integrity ------------------------------------------------
    def test_manifests_hash_every_listed_file(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tmp_path = Path(tmp)
            spec_path, _ = write_spec(tmp_path)
            output = tmp_path / "results"
            with patch.object(andes_runtime, "import_andes", return_value=make_fake_andes(tmp_path)):
                result = andes_runtime.execute_study(spec_path, output, live_preflight=True)
            self.assertEqual(result["state"], "completed")

            study_checked = assert_manifest_consistent(self, output / "study_manifest.json")
            self.assertGreater(study_checked, 0)
            job_checked = 0
            for job in result["jobs"]:
                job_dir = Path(job["directory"])
                job_checked += assert_manifest_consistent(self, job_dir / "manifest.json")
            self.assertGreater(job_checked, 0)

    # --- unverified vs failed checks --------------------------------------
    def test_unverified_state_when_convergence_is_not_required(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tmp_path = Path(tmp)
            spec_path, _ = write_spec(tmp_path, require_convergence=False, with_outputs=False)
            output = tmp_path / "results"
            with patch.object(andes_runtime, "import_andes", return_value=make_fake_andes(tmp_path, UnconvergedAndes)):
                result = andes_runtime.execute_study(spec_path, output, live_preflight=True)
            self.assertEqual(result["jobs"][0]["state"], "completed_unverified")
            self.assertEqual(result["state"], "failed")
            status = json.loads((Path(result["jobs"][0]["directory"]) / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "completed_unverified")
            checks = json.loads((Path(result["jobs"][0]["directory"]) / "checks.json").read_text(encoding="utf-8"))
            self.assertFalse(checks["routine_verified"])

    def test_failed_checks_when_convergence_is_required(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tmp_path = Path(tmp)
            spec_path, _ = write_spec(tmp_path, require_convergence=True, with_outputs=False)
            output = tmp_path / "results"
            with patch.object(andes_runtime, "import_andes", return_value=make_fake_andes(tmp_path, UnconvergedAndes)):
                result = andes_runtime.execute_study(spec_path, output, live_preflight=True)
            self.assertIn(result["jobs"][0]["state"], {"completed_with_failed_checks", "failed"})
            self.assertEqual(result["state"], "failed")

    # --- doctor selftest ---------------------------------------------------
    def test_doctor_selftest_unavailable_keeps_stdout(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tmp_path = Path(tmp)
            package_dir = tmp_path / "fake_andes"
            package_dir.mkdir()
            module_file = package_dir / "__init__.py"
            module_file.write_text("", encoding="utf-8")
            fake = types.ModuleType("fake_andes")
            fake.__file__ = str(module_file)
            fake.__version__ = "2.0.0"
            fake.load = lambda case, **kwargs: FakeSystem()
            fake.get_case = lambda name: str(tmp_path / "unused.json")
            fake.config_logger = lambda **kwargs: None
            args = andes_workflow.build_parser().parse_args(["doctor", "--selftest"])
            captured: dict = {}

            def capture(data, output):
                captured.update(data)

            stream = io.StringIO()
            # write_or_print is neutralised so the test observes only the selftest
            # stdout handling; the normal "report written" line is unrelated here.
            with patch.object(andes_workflow, "import_andes", return_value=fake), patch.object(
                andes_workflow, "write_or_print", side_effect=capture
            ):
                with patch.object(sys, "stdout", stream):
                    code = andes_workflow.command_doctor(args)
                    # command_doctor must restore the exact stream it captured and
                    # must not print selftest output to it.
                    self.assertIs(sys.stdout, stream)
                    self.assertEqual("", stream.getvalue())

            self.assertEqual(0, code)
            self.assertEqual("unavailable", captured["selftest"]["status"])


if __name__ == "__main__":
    unittest.main()
