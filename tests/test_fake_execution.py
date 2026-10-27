from __future__ import annotations

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


class FakeSystem:
    def __init__(self):
        self.Bus = FakeModel([1, 2], name=["BUS1", "BUS2"], v=[1.0, 0.98], a=[0.0, -0.1], u=[1, 1])
        self.models = OrderedDict([("Bus", self.Bus)])
        self.groups = OrderedDict()
        self.routines = OrderedDict()
        self.PFlow = FakePFlow()
        self.files = types.SimpleNamespace(txt="fake_out.txt")
        self.dae = types.SimpleNamespace(x=np.array([]), y=np.array([1.0, 0.98]), f=np.array([]), g=np.array([0.0, 0.0]))

    def setup(self):
        return True


class FakeAndes:
    __version__ = "2.0.0"
    __file__ = __file__

    def config_logger(self, **kwargs):
        return None

    def load(self, case, **kwargs):
        return FakeSystem()


class FakeExecutionTests(unittest.TestCase):
    def test_end_to_end_pflow_with_fake_andes(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tmp_path = Path(tmp)
            case = tmp_path / "case.json"
            case.write_text("{}", encoding="utf-8")
            spec = {
                "schema_version": "1.0",
                "study_name": "fake-pflow",
                "defaults": {"strict": True, "copy_inputs": True, "overwrite": False, "log_level": 20, "seed": 42},
                "jobs": [
                    {
                        "id": "pflow",
                        "case": {"path": str(case)},
                        "routine": "pflow",
                        "outputs": {"tables": [{"model": "Bus", "fields": ["idx", "name", "v", "a"], "file": "bus.csv"}]},
                        "checks": {
                            "require_convergence": True,
                            "finite": True,
                            "criteria": [
                                {"name": "vmin", "model": "Bus", "variable": "v", "source": "current", "aggregate": "min", "operator": ">=", "threshold": 0.95, "basis": "unit test"}
                            ]
                        }
                    }
                ]
            }
            output = tmp_path / "results"
            fake = FakeAndes()
            with patch.object(andes_runtime, "import_andes", return_value=fake):
                result = andes_runtime.execute_study(spec, output, live_preflight=True)
            self.assertEqual(result["state"], "completed")
            job_dir = next(path for path in output.iterdir() if path.is_dir() and path.name.startswith("001-"))
            self.assertTrue((job_dir / "tables" / "bus.csv").is_file())
            checks = json.loads((job_dir / "checks.json").read_text(encoding="utf-8"))
            self.assertTrue(checks["passed"])
            self.assertTrue((output / "study_manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
