"""Validated ANDES study runtime.

The runtime executes only the structured operations accepted by ``spec_core``.
It intentionally avoids ``eval``, ``exec``, arbitrary imports, shell commands,
and automatic package installation.

The implementation targets the public interfaces of ANDES 2.0.0. The manual
build label 1.10.1.post50+geda5163c9 is the pre-tag name of the v2.0.0 commit
(eda5163c9ee8). Defensive reflection is used so that API drift is reported
instead of hidden.
"""

from __future__ import annotations

import csv
import importlib
import importlib.metadata
import json
import math
import os
import platform
import re
import shutil
import sys
import tempfile
import traceback
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

try:  # Supports both package and copied-bundle execution.
    from .spec_core import (
        SpecError,
        copy_with_hash,
        dump_json,
        find_index,
        flatten_files,
        json_default,
        load_json,
        safe_relative_path,
        sha256_file,
        slugify,
        validate_spec,
        values_equal,
    )
except ImportError:  # pragma: no cover - exercised by generated bundles
    from spec_core import (  # type: ignore
        SpecError,
        copy_with_hash,
        dump_json,
        find_index,
        flatten_files,
        json_default,
        load_json,
        safe_relative_path,
        sha256_file,
        slugify,
        validate_spec,
        values_equal,
    )

MANUAL_BUILD = "1.10.1.post50+geda5163c9"  # pre-tag build name of commit eda5163c9 == tag v2.0.0
TARGET_ANDES_RELEASE = "2.0.0"
RUNTIME_VERSION = "1.2.0"
EVENT_MODELS = {"Fault", "Toggle", "Alter"}


class AndesUnavailableError(RuntimeError):
    """Raised when ANDES cannot be imported in the active Python environment."""


class LiveValidationError(RuntimeError):
    """Raised when a structurally valid specification does not match a live case."""


class StudyExecutionError(RuntimeError):
    """Raised when an ANDES job fails or cannot be verified."""


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def as_jsonable(value: Any) -> Any:
    """Recursively convert common scientific Python values to JSON values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): as_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [as_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return as_jsonable(value.item())
        except Exception:
            pass
    if hasattr(value, "tolist"):
        try:
            return as_jsonable(value.tolist())
        except Exception:
            pass
    return repr(value)


def _is_same_or_ancestor(candidate: Path, target: Path) -> bool:
    try:
        target.relative_to(candidate)
        return True
    except ValueError:
        return False


def protected_paths_for_spec(
    normalized: Mapping[str, Any] | None,
    *,
    spec_dir: Path | None = None,
    spec_path: Path | None = None,
) -> list[Path]:
    """Paths an output directory must never equal or contain (inputs, skill, cwd, home)."""
    protected: list[Path] = [Path(__file__).resolve().parent.parent, Path.cwd().resolve(), Path.home().resolve()]
    if spec_path is not None:
        protected.append(Path(spec_path).expanduser().resolve())
    base = Path(spec_dir) if spec_dir is not None else Path.cwd()
    for job in (normalized or {}).get("jobs", []):
        case = job.get("case", {}) if isinstance(job, Mapping) else {}
        for raw in [case.get("path"), *case.get("addfiles", [])]:
            if raw:
                candidate = Path(str(raw)).expanduser()
                protected.append((candidate if candidate.is_absolute() else base / candidate).resolve())
    return protected


def guard_output_destination(path: Path, protected: Sequence[Path]) -> Path:
    """Refuse an output directory that is a drive root or equals/contains a protected path."""
    path = path.expanduser().resolve()
    if path == Path(path.anchor):
        raise StudyExecutionError(f"Output directory must not be a drive/filesystem root: {path}")
    for item in protected:
        if _is_same_or_ancestor(path, Path(item)):
            raise StudyExecutionError(
                f"Output directory {path} equals or contains a protected path ({item}); choose a new, dedicated folder."
            )
    return path


def ensure_empty_destination(path: Path, *, overwrite: bool, protected: Sequence[Path] = ()) -> Path:
    path = guard_output_destination(path, protected)
    if path.exists():
        if not path.is_dir():
            raise StudyExecutionError(f"Output destination is not a directory: {path}")
        if any(path.iterdir()):
            if not overwrite:
                raise StudyExecutionError(
                    f"Output directory is not empty: {path}. Use the explicit overwrite option."
                )
            shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception as exc:  # pragma: no cover - environment specific
        return f"unavailable: {exc}"


def import_andes() -> Any:
    try:
        return importlib.import_module("andes")
    except Exception as exc:
        raise AndesUnavailableError(
            "ANDES could not be imported in the active Python environment. Activate the correct "
            "conda/venv environment and verify it with `python -c \"import andes; print(andes.__version__)\"`. "
            f"Underlying error: {type(exc).__name__}: {exc}"
        ) from exc


def _release_tuple(version: str | None) -> tuple[int, int, int] | None:
    if not version:
        return None
    match = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)", str(version))
    if not match:
        return None
    return tuple(int(item) for item in match.groups())  # type: ignore[return-value]


def andes_compatibility(version: str | None) -> dict[str, Any]:
    """Classify an installed ANDES version against the documented API surface."""
    raw = str(version or "").strip()
    parsed = _release_tuple(raw)
    if raw.startswith(MANUAL_BUILD):
        return {
            "supported": True,
            "level": "manual-development-build",
            "installed": raw,
            "target": TARGET_ANDES_RELEASE,
            "message": "The installed build is the commit behind the v2.0.0 tag (eda5163c9); same code as 2.0.0.",
        }
    if parsed == (2, 0, 0):
        return {
            "supported": True,
            "level": "exact",
            "installed": raw,
            "target": TARGET_ANDES_RELEASE,
            "message": "The installed ANDES version exactly matches the skill's verified target version.",
        }
    if parsed and parsed[0] == 2:
        return {
            "supported": True,
            "level": "capability-checked-2.x",
            "installed": raw,
            "target": TARGET_ANDES_RELEASE,
            "message": (
                "The installed version is in the same major version family. Every study must pass a live "
                "case/API preflight; the version difference is recorded in the manifest as a warning."
            ),
        }
    if parsed == (1, 10, 1):
        message = (
            "Package version 1.10.1 does not guarantee the full SE-LAV, CPF-QV, "
            "TDS.get_timeseries, AndesEnv, and new status/setpoint API surface documented in "
            "the post50 development build of the loaded manual. Use ANDES 2.0.0."
        )
    elif parsed and parsed[0] >= 3:
        message = "The ANDES 3.x API surface has not yet been verified for this skill version."
    else:
        message = "The installed ANDES version is not within this skill's verified API range."
    return {
        "supported": False,
        "level": "unsupported",
        "installed": raw or None,
        "target": TARGET_ANDES_RELEASE,
        "message": message,
    }


def require_supported_andes(andes: Any) -> dict[str, Any]:
    version = getattr(andes, "__version__", package_version("andes"))
    report = andes_compatibility(version)
    if not report["supported"]:
        raise AndesUnavailableError(
            f"Incompatible ANDES version `{version}`. {report['message']} Target: {TARGET_ANDES_RELEASE}."
        )
    return report


def andes_capabilities(andes: Any) -> dict[str, Any]:
    """Probe documented APIs without loading or running a power-system case."""
    probes: dict[str, bool] = {
        "andes.load": callable(getattr(andes, "load", None)),
        "andes.get_case": callable(getattr(andes, "get_case", None)),
    }
    errors: dict[str, str] = {}
    targets = {
        "System.add": ("andes.system", "System", "add"),
        "System.setup": ("andes.system", "System", "setup"),
        "System.set_status": ("andes.system", "System", "set_status"),
        "TDS.get_timeseries": ("andes.routines.tds", "TDS", "get_timeseries"),
        "TDS.reinit": ("andes.routines.tds", "TDS", "reinit"),
        "EIG.sweep": ("andes.routines.eig", "EIG", "sweep"),
        "EIG.plot_root_loci": ("andes.routines.eig", "EIG", "plot_root_loci"),
        "SE.run": ("andes.routines.se", "SE", "run"),
        "CPF.run_qv": ("andes.routines.cpf", "CPF", "run_qv"),
        "CPF.plot_qv": ("andes.routines.cpf", "CPF", "plot_qv"),
    }
    for label, (module_name, class_name, method_name) in targets.items():
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
            probes[label] = callable(getattr(cls, method_name, None))
        except Exception as exc:
            probes[label] = False
            errors[label] = f"{type(exc).__name__}: {exc}"
    for label, module_name, attribute in (
        ("SE.Measurements", "andes.se", "Measurements"),
        ("SE.lav", "andes.se", "lav"),
        ("RL.AndesEnv", "andes.rl", "AndesEnv"),
    ):
        try:
            module = importlib.import_module(module_name)
            probes[label] = getattr(module, attribute, None) is not None
        except Exception as exc:
            probes[label] = False
            errors[label] = f"{type(exc).__name__}: {exc}"
    core = [key for key in probes if key != "RL.AndesEnv"]
    return {
        "core_ok": all(probes[key] for key in core),
        "probes": probes,
        "errors": errors,
        "optional": {"RL.AndesEnv": probes.get("RL.AndesEnv", False)},
    }


def environment_snapshot(andes: Any | None = None) -> dict[str, Any]:
    if andes is None:
        try:
            andes = import_andes()
        except AndesUnavailableError:
            andes = None
    packages = ["andes", "numpy", "scipy", "pandas", "matplotlib", "sympy", "numba"]
    version = getattr(andes, "__version__", package_version("andes")) if andes else None
    return {
        "captured_at_utc": utc_now(),
        "runtime_version": RUNTIME_VERSION,
        "manual_build": MANUAL_BUILD,
        "target_andes_release": TARGET_ANDES_RELEASE,
        "python": {
            "version": sys.version,
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "andes": {
            "imported": andes is not None,
            "version": version,
            "module_path": str(Path(getattr(andes, "__file__", "")).resolve()) if andes and getattr(andes, "__file__", None) else None,
            "compatibility": andes_compatibility(version),
        },
        "packages": {name: package_version(name) for name in packages},
    }


def _numpy() -> Any:
    try:
        return importlib.import_module("numpy")
    except Exception as exc:
        raise StudyExecutionError(f"NumPy could not be imported: {exc}") from exc


def _pandas() -> Any:
    try:
        return importlib.import_module("pandas")
    except Exception as exc:
        raise StudyExecutionError(f"pandas could not be imported: {exc}") from exc


def _pyplot() -> Any:
    try:
        matplotlib = importlib.import_module("matplotlib")
        try:
            matplotlib.use("Agg", force=True)
        except Exception:
            pass
        plt = importlib.import_module("matplotlib.pyplot")
        try:
            plt.rcParams["text.usetex"] = False
        except Exception:
            pass
        return plt
    except Exception as exc:
        raise StudyExecutionError(f"Matplotlib could not be imported: {exc}") from exc


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "tolist"):
        converted = value.tolist()
        return converted if isinstance(converted, list) else [converted]
    try:
        return list(value)
    except TypeError:
        return [value]


def _scalar(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _get_mapping_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return {str(item) for item in value.keys()}
    if hasattr(value, "keys"):
        try:
            return {str(item) for item in value.keys()}
        except Exception:
            pass
    for attr in ("_dict", "_fields", "fields"):
        candidate = getattr(value, attr, None)
        if isinstance(candidate, Mapping):
            return {str(item) for item in candidate.keys()}
        if isinstance(candidate, (list, tuple, set)):
            return {str(item) for item in candidate}
    return {
        name
        for name in dir(value)
        if not name.startswith("_") and not callable(getattr(value, name, None))
    }


def _config_value(config: Any, key: str) -> Any:
    if hasattr(config, key):
        return getattr(config, key)
    try:
        return config[key]
    except Exception as exc:
        raise LiveValidationError(f"Could not read configuration field: {key}") from exc


def apply_config(config: Any, values: Mapping[str, Any], *, owner: str) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    available = _get_mapping_keys(config)
    for key, value in values.items():
        if key.startswith("_") or (key not in available and not hasattr(config, key)):
            suggestions = sorted(item for item in available if key.lower() in item.lower() or item.lower() in key.lower())[:8]
            hint = f" Similar fields: {suggestions}" if suggestions else ""
            raise LiveValidationError(f"Unknown config field for {owner}: `{key}`.{hint}")
        before = _config_value(config, key)
        try:
            setattr(config, key, value)
        except Exception:
            try:
                config[key] = value
            except Exception as exc:
                raise LiveValidationError(f"Could not set {owner}.{key}: {exc}") from exc
        after = _config_value(config, key)
        changes.append({"owner": owner, "field": key, "before": as_jsonable(before), "after": as_jsonable(after)})
    return changes


# ---------------------------------------------------------------------------
# Case resolution and loading
# ---------------------------------------------------------------------------


def _resolve_local_path(value: str, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _resolve_case_item(andes: Any, value: str, base_dir: Path, *, allow_builtin_fallback: bool) -> tuple[Path, str]:
    local = _resolve_local_path(value, base_dir)
    if local.is_file():
        return local, "path"
    if allow_builtin_fallback:
        try:
            built = Path(andes.get_case(value)).resolve()
            if built.is_file():
                return built, "builtin"
        except Exception:
            pass
    raise LiveValidationError(f"Case/addfile not found: {value}")


def resolve_case_spec(andes: Any, case_spec: Mapping[str, Any], spec_dir: Path) -> dict[str, Any]:
    if case_spec.get("builtin"):
        name = str(case_spec["builtin"])
        try:
            case_path = Path(andes.get_case(name)).resolve()
        except Exception as exc:
            raise LiveValidationError(f"Could not resolve the ANDES built-in case: {name}: {exc}") from exc
        if not case_path.is_file():
            raise LiveValidationError(f"ANDES built-in case path is not a file: {case_path}")
        case_origin = "builtin"
    else:
        case_path, case_origin = _resolve_case_item(
            andes,
            str(case_spec.get("path", "")),
            spec_dir,
            allow_builtin_fallback=False,
        )

    addfiles: list[dict[str, Any]] = []
    for raw in case_spec.get("addfiles", []):
        path, origin = _resolve_case_item(andes, str(raw), spec_dir, allow_builtin_fallback=True)
        addfiles.append({"requested": str(raw), "resolved": str(path), "origin": origin})

    return {
        "case": {
            "requested": case_spec.get("builtin") or case_spec.get("path"),
            "resolved": str(case_path),
            "origin": case_origin,
        },
        "addfiles": addfiles,
        "config_option": list(case_spec.get("config_option", [])),
        "default_config": bool(case_spec.get("default_config", False)),
    }


def _unique_input_name(path: Path, used: set[str]) -> str:
    candidate = path.name
    if candidate not in used:
        used.add(candidate)
        return candidate
    prefix = sha256_file(path)[:10]
    candidate = f"{prefix}-{path.name}"
    used.add(candidate)
    return candidate


def prepare_input_files(
    resolved: Mapping[str, Any],
    input_dir: Path,
    *,
    copy_inputs: bool,
) -> tuple[str, list[str], dict[str, Any]]:
    input_dir.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    records: list[dict[str, Any]] = []

    source_case = Path(str(resolved["case"]["resolved"]))
    if copy_inputs:
        name = _unique_input_name(source_case, used)
        record = copy_with_hash(source_case, input_dir / name)
        record.update({"role": "case", "origin": resolved["case"]["origin"], "requested": resolved["case"]["requested"]})
        case_path = record["copied_to"]
    else:
        record = {
            "role": "case",
            "source": str(source_case),
            "used_path": str(source_case),
            "origin": resolved["case"]["origin"],
            "requested": resolved["case"]["requested"],
            "size_bytes": source_case.stat().st_size,
            "sha256": sha256_file(source_case),
        }
        case_path = str(source_case)
    records.append(record)

    add_paths: list[str] = []
    for item in resolved.get("addfiles", []):
        source = Path(str(item["resolved"]))
        if copy_inputs:
            name = _unique_input_name(source, used)
            copied = copy_with_hash(source, input_dir / name)
            copied.update({"role": "addfile", "origin": item["origin"], "requested": item["requested"]})
            used_path = copied["copied_to"]
            records.append(copied)
        else:
            used_path = str(source)
            records.append(
                {
                    "role": "addfile",
                    "source": str(source),
                    "used_path": str(source),
                    "origin": item["origin"],
                    "requested": item["requested"],
                    "size_bytes": source.stat().st_size,
                    "sha256": sha256_file(source),
                }
            )
        add_paths.append(str(used_path))

    manifest = {
        "copy_inputs": copy_inputs,
        "case": case_path,
        "addfiles": add_paths,
        "files": records,
    }
    return str(case_path), add_paths, manifest


def load_system(
    andes: Any,
    case_path: str,
    addfiles: Sequence[str],
    *,
    setup: bool,
    output_path: Path | None,
    config_option: Sequence[str] | None = None,
    default_config: bool = False,
) -> Any:
    kwargs: dict[str, Any] = {
        "setup": setup,
        "default_config": bool(default_config),
    }
    if addfiles:
        kwargs["addfile"] = list(addfiles) if len(addfiles) > 1 else addfiles[0]
    if config_option:
        kwargs["config_option"] = list(config_option)
    if output_path is not None:
        output_path.mkdir(parents=True, exist_ok=True)
        kwargs["output_path"] = str(output_path)
    try:
        return andes.load(case_path, **kwargs)
    except Exception as exc:
        raise LiveValidationError(
            f"ANDES could not load the case: {case_path}. {type(exc).__name__}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Live model/group introspection
# ---------------------------------------------------------------------------


def require_model(system: Any, name: str) -> Any:
    models = getattr(system, "models", {})
    if isinstance(models, Mapping) and name in models:
        return models[name]
    if hasattr(system, name):
        candidate = getattr(system, name)
        if hasattr(candidate, "idx") or hasattr(candidate, "n"):
            return candidate
    available = sorted(str(item) for item in getattr(models, "keys", lambda: [])()) if hasattr(models, "keys") else []
    suggestions = [item for item in available if name.lower() in item.lower() or item.lower() in name.lower()][:10]
    raise LiveValidationError(f"`{name}` not found in the case or model registry. Similar models: {suggestions}")


def require_group(system: Any, name: str) -> Any:
    groups = getattr(system, "groups", {})
    if isinstance(groups, Mapping) and name in groups:
        return groups[name]
    if hasattr(system, name):
        candidate = getattr(system, name)
        if hasattr(candidate, "get_all_idxes") or hasattr(candidate, "idx2model"):
            return candidate
    available = sorted(str(item) for item in getattr(groups, "keys", lambda: [])()) if hasattr(groups, "keys") else []
    suggestions = [item for item in available if name.lower() in item.lower() or item.lower() in name.lower()][:10]
    raise LiveValidationError(f"ANDES group `{name}` not found. Similar groups: {suggestions}")


def model_indices(model: Any) -> list[Any]:
    idx = getattr(model, "idx", None)
    values = getattr(idx, "v", None)
    if values is None:
        return []
    return _sequence(values)


def group_indices(group: Any) -> list[Any]:
    if hasattr(group, "get_all_idxes"):
        try:
            return _sequence(group.get_all_idxes())
        except Exception:
            pass
    for attr in ("idx", "_idx2model", "models"):
        candidate = getattr(group, attr, None)
        if isinstance(candidate, Mapping):
            return list(candidate.keys())
        values = getattr(candidate, "v", None)
        if values is not None:
            return _sequence(values)
    return []


def require_model_idx(model: Any, idx: Any, *, model_name: str) -> int:
    values = model_indices(model)
    try:
        return find_index(values, idx)
    except KeyError as exc:
        preview = values[:30]
        suffix = " ..." if len(values) > 30 else ""
        raise LiveValidationError(
            f"idx `{idx}` not found in model {model_name}. Sample existing idx: {preview}{suffix}"
        ) from exc


def require_group_idx(group: Any, idx: Any, *, group_name: str) -> Any:
    values = group_indices(group)
    if values:
        try:
            position = find_index(values, idx)
            return values[position]
        except KeyError as exc:
            raise LiveValidationError(
                f"idx `{idx}` not found in group {group_name}. Sample existing idx: {values[:30]}"
            ) from exc
    if hasattr(group, "idx2model"):
        try:
            group.idx2model(idx)
            return idx
        except Exception as exc:
            raise LiveValidationError(f"Could not resolve idx `{idx}` in group {group_name}: {exc}") from exc
    raise LiveValidationError(f"Could not read device indices for group {group_name}")


def require_field(model: Any, field: str, *, model_name: str) -> Any:
    if not field or field.startswith("_") or not hasattr(model, field):
        available = discover_model_fields(model)
        flat = sorted({name for names in available.values() for name in names})
        suggestions = [item for item in flat if field.lower() in item.lower() or item.lower() in field.lower()][:12]
        raise LiveValidationError(f"{model_name}.{field} not found. Similar fields: {suggestions}")
    value = getattr(model, field)
    if callable(value):
        raise LiveValidationError(f"{model_name}.{field} is a callable object, not a data field")
    return value


def discover_model_fields(model: Any) -> dict[str, list[str]]:
    categories: dict[str, set[str]] = {
        "parameters": set(),
        "variables": set(),
        "services": set(),
        "discretes": set(),
        "blocks": set(),
        "other_value_providers": set(),
    }
    source_names = {
        "parameters": ("params", "parameters", "num_params", "idx_params"),
        "variables": ("vars", "variables", "states", "algebs"),
        "services": ("services",),
        "discretes": ("discrete", "discretes"),
        "blocks": ("blocks",),
    }
    for category, attrs in source_names.items():
        for attr in attrs:
            value = getattr(model, attr, None)
            if isinstance(value, Mapping):
                categories[category].update(str(item) for item in value.keys())

    for name in dir(model):
        if name.startswith("_"):
            continue
        try:
            value = getattr(model, name)
        except Exception:
            continue
        if callable(value):
            continue
        type_name = type(value).__name__.lower()
        if "param" in type_name:
            categories["parameters"].add(name)
        elif any(token in type_name for token in ("state", "algeb", "var")) and hasattr(value, "v"):
            categories["variables"].add(name)
        elif "service" in type_name:
            categories["services"].add(name)
        elif any(token in type_name for token in ("limiter", "switch", "discrete", "deadband", "comparer")):
            categories["discretes"].add(name)
        elif "block" in type_name or hasattr(value, "vars"):
            categories["blocks"].add(name)
        elif hasattr(value, "v") or hasattr(value, "vin"):
            categories["other_value_providers"].add(name)

    categories["parameters"].add("idx")
    return {key: sorted(values) for key, values in categories.items() if values}


def _field_values(model: Any, field: str, *, source: str = "v") -> list[Any]:
    provider = require_field(model, field, model_name=type(model).__name__)
    attr = "vin" if source == "vin" else "v"
    if field == "idx":
        values = model_indices(model)
    elif hasattr(provider, attr):
        values = _sequence(getattr(provider, attr))
    elif source == "vin" and hasattr(provider, "v"):
        raise LiveValidationError(f"`vin` is not available for {type(model).__name__}.{field}")
    else:
        values = _sequence(provider)
    n = len(model_indices(model))
    if n and len(values) not in {1, n}:
        raise LiveValidationError(
            f"Length of {type(model).__name__}.{field} ({len(values)}) does not match the model device count ({n})"
        )
    if n and len(values) == 1:
        values = values * n
    return [_scalar(item) for item in values]


def model_rows(
    model: Any,
    *,
    model_name: str,
    fields: Sequence[str] | None = None,
    indices: Sequence[Any] | None = None,
    source: str = "v",
) -> list[dict[str, Any]]:
    idx_values = model_indices(model)
    requested_fields = list(fields or ["idx"])
    if "idx" not in requested_fields:
        requested_fields.insert(0, "idx")
    columns = {field: _field_values(model, field, source=source) for field in requested_fields}
    selected_positions = list(range(len(idx_values)))
    if indices is not None:
        selected_positions = [require_model_idx(model, idx, model_name=model_name) for idx in indices]
    rows: list[dict[str, Any]] = []
    for position in selected_positions:
        row = {field: as_jsonable(columns[field][position]) for field in requested_fields}
        rows.append(row)
    return rows


def _compact_doc(obj: Any, *, max_chars: int = 12000) -> str | None:
    if not hasattr(obj, "doc"):
        return None
    try:
        text = str(obj.doc())
    except Exception:
        return None
    return text[:max_chars] + ("\n...[truncated]" if len(text) > max_chars else "")


def inspect_system(system: Any, *, include_empty: bool = False, max_indices: int = 200) -> dict[str, Any]:
    models = getattr(system, "models", {})
    model_records: list[dict[str, Any]] = []
    if isinstance(models, Mapping):
        items = models.items()
    else:
        items = []
    for name, model in items:
        idxes = model_indices(model)
        if not include_empty and not idxes:
            continue
        model_records.append(
            {
                "name": str(name),
                "group": getattr(model, "group", None),
                "count": int(getattr(model, "n", len(idxes)) or 0),
                "indices": as_jsonable(idxes[:max_indices]),
                "indices_truncated": len(idxes) > max_indices,
                "fields": discover_model_fields(model),
            }
        )
    groups = getattr(system, "groups", {})
    group_records: list[dict[str, Any]] = []
    if isinstance(groups, Mapping):
        for name, group in groups.items():
            idxes = group_indices(group)
            if not include_empty and not idxes:
                continue
            group_records.append(
                {
                    "name": str(name),
                    "count": int(getattr(group, "n", len(idxes)) or 0),
                    "indices": as_jsonable(idxes[:max_indices]),
                    "indices_truncated": len(idxes) > max_indices,
                }
            )
    routines = getattr(system, "routines", {})
    routine_names = sorted(str(item) for item in routines.keys()) if isinstance(routines, Mapping) else []
    bus = getattr(system, "Bus", None)
    islands = getattr(bus, "island_sets", None) if bus is not None else None
    return {
        "system_class": type(system).__name__,
        "models": model_records,
        "groups": group_records,
        "routines": routine_names,
        "counts": {
            "models_nonempty": len(model_records),
            "devices": sum(item["count"] for item in model_records),
            "buses": int(getattr(bus, "n", 0) or 0) if bus is not None else None,
            "islands": len(islands) if islands is not None else None,
        },
    }


def find_connected(system: Any, model_name: str, idx: Any, *, details: bool = False) -> dict[str, Any]:
    model = require_model(system, model_name)
    require_model_idx(model, idx, model_name=model_name)
    if not hasattr(system, "find_connected"):
        raise LiveValidationError("System.find_connected() not found in the installed ANDES version")
    try:
        connected = system.find_connected(model_name, idx)
    except Exception as exc:
        raise LiveValidationError(f"Could not resolve connected devices: {model_name}.{idx}: {exc}") from exc
    result: dict[str, Any] = {
        "query": {"model": model_name, "idx": as_jsonable(idx)},
        "connected": as_jsonable(connected),
    }
    if details and isinstance(connected, Mapping):
        expanded: dict[str, Any] = {}
        for target_name, target_indices in connected.items():
            try:
                target_model = require_model(system, str(target_name))
                available_fields = discover_model_fields(target_model)
                flat = {item for values in available_fields.values() for item in values}
                preferred = [item for item in ("idx", "name", "bus", "gen", "syn", "u", "Sn", "Vn") if item in flat]
                expanded[str(target_name)] = model_rows(
                    target_model,
                    model_name=str(target_name),
                    fields=preferred or ["idx"],
                    indices=_sequence(target_indices),
                    source="v",
                )
            except Exception as exc:
                expanded[str(target_name)] = {"error": str(exc), "indices": as_jsonable(target_indices)}
        result["details"] = expanded
    return result


# ---------------------------------------------------------------------------
# Operations, events and live validation
# ---------------------------------------------------------------------------


def _provider_value_at(model: Any, field: str, idx: Any, *, base: str = "system") -> Any:
    provider = require_field(model, field, model_name=type(model).__name__)
    position = require_model_idx(model, idx, model_name=type(model).__name__)
    attr = "vin" if base == "device" else "v"
    if hasattr(provider, attr):
        values = _sequence(getattr(provider, attr))
        if len(values) == 1:
            return _scalar(values[0])
        return _scalar(values[position])
    if hasattr(model, "get"):
        try:
            return model.get(field, idx, attr=attr)
        except Exception:
            pass
    raise LiveValidationError(f"Could not read value of {type(model).__name__}.{field}")


def _model_set(model: Any, field: str, idx: Any, value: Any, *, base: str = "system") -> None:
    require_field(model, field, model_name=type(model).__name__)
    require_model_idx(model, idx, model_name=type(model).__name__)
    if not hasattr(model, "set"):
        raise LiveValidationError(f"{type(model).__name__}.set() not found")
    try:
        if base == "device":
            model.set(field, idx, value, base="device")
        else:
            model.set(field, idx, value)
    except TypeError as exc:
        # Older-compatible fallback only for system-base writes. Device-base writes
        # are never silently downgraded because that would change unit semantics.
        if base == "system":
            try:
                model.set(field, idx, value=value)
                return
            except Exception:
                pass
        raise LiveValidationError(
            f"Could not write {type(model).__name__}.{field} idx={idx} (base={base}): {exc}"
        ) from exc
    except Exception as exc:
        raise LiveValidationError(
            f"Could not write {type(model).__name__}.{field} idx={idx} (base={base}): {exc}"
        ) from exc


def _system_setup_complete(system: Any) -> bool:
    for name in ("is_setup", "setup_done", "_is_setup"):
        value = getattr(system, name, None)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
    return False


def _status_value(model: Any, idx: Any, field: str) -> Any:
    if not hasattr(model, field):
        return None
    try:
        return _provider_value_at(model, field, idx)
    except Exception:
        return None


def _set_device_status(system: Any, model_name: str, idx: Any, value: int) -> str:
    """Use the v2 recursive status API after setup; use model.u before setup."""
    model = require_model(system, model_name)
    require_model_idx(model, idx, model_name=model_name)
    if _system_setup_complete(system) and callable(getattr(system, "set_status", None)):
        try:
            system.set_status(model_name, idx, value)
            return "System.set_status"
        except Exception as exc:
            raise LiveValidationError(
                f"System.set_status({model_name}, {idx}, {value}) failed: {exc}"
            ) from exc
    _model_set(model, "u", idx, value)
    return f"{model_name}.set('u')"


def apply_set_status(system: Any, operation: Mapping[str, Any]) -> dict[str, Any]:
    model_name = str(operation["model"])
    model = require_model(system, model_name)
    idx = operation["idx"]
    before = _provider_value_at(model, "u", idx)
    effective_before = _status_value(model, idx, "ue")
    api = _set_device_status(system, model_name, idx, int(bool(operation["value"])))
    after = _provider_value_at(model, "u", idx)
    effective_after = _status_value(model, idx, "ue")
    return {
        "op": "set_status",
        "model": model_name,
        "idx": as_jsonable(idx),
        "before": as_jsonable(before),
        "after": as_jsonable(after),
        "effective_before": as_jsonable(effective_before),
        "effective_after": as_jsonable(effective_after),
        "api": api,
        "note": operation.get("note"),
    }


def apply_set_parameter(system: Any, operation: Mapping[str, Any]) -> dict[str, Any]:
    model_name = str(operation["model"])
    field = str(operation["field"])
    idx = operation["idx"]
    base = str(operation["base"])
    model = require_model(system, model_name)
    before = _provider_value_at(model, field, idx, base=base)
    _model_set(model, field, idx, operation["value"], base=base)
    after = _provider_value_at(model, field, idx, base=base)
    return {
        "op": "set_parameter",
        "model": model_name,
        "field": field,
        "idx": as_jsonable(idx),
        "base": base,
        "before": as_jsonable(before),
        "after": as_jsonable(after),
        "requested": as_jsonable(operation["value"]),
        "note": operation.get("note"),
    }


def apply_scale_parameter(system: Any, operation: Mapping[str, Any]) -> list[dict[str, Any]]:
    model_name = str(operation["model"])
    field = str(operation["field"])
    base = str(operation["base"])
    factor = float(operation["factor"])
    model = require_model(system, model_name)
    indices = list(operation.get("indices") or model_indices(model))
    records: list[dict[str, Any]] = []
    for idx in indices:
        before = _provider_value_at(model, field, idx, base=base)
        if not isinstance(before, (int, float)) or isinstance(before, bool):
            raise LiveValidationError(
                f"Scaling is only possible on a numeric field: {model_name}.{field} idx={idx}: {before!r}"
            )
        requested = float(before) * factor
        _model_set(model, field, idx, requested, base=base)
        after = _provider_value_at(model, field, idx, base=base)
        records.append(
            {
                "op": "scale_parameter",
                "model": model_name,
                "field": field,
                "idx": as_jsonable(idx),
                "base": base,
                "factor": factor,
                "before": as_jsonable(before),
                "after": as_jsonable(after),
                "note": operation.get("note"),
            }
        )
    return records


def _get_group_setpoint(group: Any, system: Any, idx: Any, name: str) -> Any:
    getter = getattr(group, f"get_{name}", None)
    if callable(getter):
        try:
            return getter(system, idx)
        except TypeError:
            return getter(idx)
    generic = getattr(group, "get_setpoint", None)
    if callable(generic):
        return generic(system, idx, name)
    return None


def apply_setpoint(system: Any, operation: Mapping[str, Any]) -> dict[str, Any]:
    group_name = str(operation["group"])
    idx = operation["idx"]
    name = str(operation["name"])
    value = operation["value"]
    group = require_group(system, group_name)
    resolved_idx = require_group_idx(group, idx, group_name=group_name)
    before = _get_group_setpoint(group, system, resolved_idx, name)
    setter = getattr(group, f"set_{name}", None)
    try:
        if callable(setter):
            setter(system, resolved_idx, value)
        elif callable(getattr(group, "set_setpoint", None)):
            group.set_setpoint(system, resolved_idx, name, value)
        else:
            raise LiveValidationError(
                f"setpoint API `{name}` not found in group {group_name}"
            )
    except LiveValidationError:
        raise
    except Exception as exc:
        raise LiveValidationError(
            f"Could not set setpoint {group_name}.{name} for idx={idx}: {exc}"
        ) from exc
    after = _get_group_setpoint(group, system, resolved_idx, name)
    return {
        "op": "set_setpoint",
        "group": group_name,
        "idx": as_jsonable(resolved_idx),
        "name": name,
        "before": as_jsonable(before),
        "after": as_jsonable(after if after is not None else value),
        "requested": as_jsonable(value),
        "note": operation.get("note"),
    }


def apply_operation(system: Any, operation: Mapping[str, Any]) -> list[dict[str, Any]]:
    name = operation["op"]
    if name == "set_status":
        return [apply_set_status(system, operation)]
    if name == "set_parameter":
        return [apply_set_parameter(system, operation)]
    if name == "scale_parameter":
        return apply_scale_parameter(system, operation)
    if name == "set_setpoint":
        return [apply_setpoint(system, operation)]
    raise LiveValidationError(f"Unsupported operation: {name}")


def disable_existing_event_model(system: Any, model_name: str) -> list[dict[str, Any]]:
    model = require_model(system, model_name)
    records: list[dict[str, Any]] = []
    for idx in model_indices(model):
        before = _provider_value_at(model, "u", idx)
        api = _set_device_status(system, model_name, idx, 0)
        after = _provider_value_at(model, "u", idx)
        records.append(
            {
                "op": "disable_existing_event",
                "model": model_name,
                "idx": as_jsonable(idx),
                "before": as_jsonable(before),
                "after": as_jsonable(after),
                "api": api,
            }
        )
    return records


def validate_event_reference(system: Any, event: Mapping[str, Any]) -> None:
    kind = event["type"]
    if kind == "fault":
        bus_model = require_model(system, "Bus")
        require_model_idx(bus_model, event["bus"], model_name="Bus")
    elif kind == "toggle":
        model_name = str(event["model"])
        model = require_model(system, model_name)
        require_model_idx(model, event["dev"], model_name=model_name)
    elif kind == "alter":
        model_name = str(event["model"])
        model = require_model(system, model_name)
        require_model_idx(model, event["dev"], model_name=model_name)
        require_field(model, str(event["src"]), model_name=model_name)


def add_event(system: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    validate_event_reference(system, event)
    kind = event["type"]
    kwargs: dict[str, Any]
    model_name: str
    if kind == "fault":
        model_name = "Fault"
        kwargs = {key: event[key] for key in ("bus", "tf", "tc", "rf", "xf") if key in event}
    elif kind == "toggle":
        model_name = "Toggle"
        kwargs = {"model": event["model"], "dev": event["dev"], "t": event["t"]}
    else:
        model_name = "Alter"
        kwargs = {
            "model": event["model"],
            "dev": event["dev"],
            "src": event["src"],
            "t": event["t"],
            "method": event["method"],
            "amount": event["amount"],
        }
    try:
        assigned_idx = system.add(model_name, **kwargs)
    except Exception as exc:
        raise LiveValidationError(f"Could not add {model_name} event: {kwargs}: {exc}") from exc
    return {
        "type": kind,
        "andes_model": model_name,
        "assigned_idx": as_jsonable(assigned_idx),
        "arguments": as_jsonable(kwargs),
        "note": event.get("note"),
    }


def _connected_names_at_device_bus(system: Any, model_name: str, idx: Any) -> set[str]:
    model = require_model(system, model_name)
    if not hasattr(model, "bus"):
        return set()
    try:
        bus = _provider_value_at(model, "bus", idx)
        result = system.find_connected("Bus", bus)
        return {str(item) for item in result.keys()} if isinstance(result, Mapping) else set()
    except Exception:
        return set()


def guard_dynamic_static_alter_targets(system: Any, events: Sequence[Mapping[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for event in events:
        if event.get("type") != "alter":
            continue
        model_name = str(event.get("model"))
        field = str(event.get("src"))
        idx = event.get("dev")
        connected = _connected_names_at_device_bus(system, model_name, idx)
        if model_name in {"PV", "Slack"} and field in {"p0", "p", "q0", "q"}:
            dynamic_generators = sorted(connected.intersection({"GENROU", "GENCLS", "GENSAL"}))
            if dynamic_generators:
                raise LiveValidationError(
                    f"During TDS the {model_name}.{field} target may have no effect; dynamic generator(s) "
                    f"are on the same bus: {dynamic_generators}. Use the group-level SynGen setpoint API "
                    "or the connected governor/exciter target."
                )
        if model_name == "PQ" and field in {"Ppf", "Qpf", "p0", "q0"}:
            dynamic_loads = sorted(connected.intersection({"FLoad", "ZIP"}))
            if dynamic_loads:
                raise LiveValidationError(
                    f"During TDS the PQ.{field} target may have no effect; a dynamic load model is on the same bus: "
                    f"{dynamic_loads}. Use the appropriate target of the connected dynamic load model."
                )
        if model_name not in {"PV", "Slack", "PQ"}:
            warnings.append(
                f"Alter target {model_name}.{field} exists live; its physical effect must be verified against the model equations and operating state."
            )
    return warnings


def validate_stage_operation_live(system: Any, operation: Mapping[str, Any]) -> dict[str, Any]:
    if operation["op"] == "set_setpoint":
        group_name = str(operation["group"])
        group = require_group(system, group_name)
        idx = require_group_idx(group, operation["idx"], group_name=group_name)
        name = str(operation["name"])
        if not callable(getattr(group, f"set_{name}", None)) and not callable(getattr(group, "set_setpoint", None)):
            raise LiveValidationError(f"setpoint API `{name}` not found in group {group_name}")
        return {"op": "set_setpoint", "group": group_name, "idx": as_jsonable(idx), "name": name}
    if operation["op"] == "set_parameter":
        model_name = str(operation["model"])
        model = require_model(system, model_name)
        require_model_idx(model, operation["idx"], model_name=model_name)
        provider = require_field(model, str(operation["field"]), model_name=model_name)
        base = str(operation["base"])
        if base == "device" and not hasattr(provider, "vin"):
            raise LiveValidationError(f"device/input base (`vin`) not found for {model_name}.{operation['field']}")
        return {
            "op": "set_parameter",
            "model": model_name,
            "field": operation["field"],
            "idx": as_jsonable(operation["idx"]),
            "base": base,
        }
    raise LiveValidationError(f"Unsupported stage operation: {operation['op']}")


def validate_output_reference_live(system: Any, job: Mapping[str, Any]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    outputs = job.get("outputs", {})
    for collection in ("tables", "timeseries", "plots"):
        for item in outputs.get(collection, []):
            model_name = str(item["model"])
            model = require_model(system, model_name)
            if collection == "tables":
                for field in item["fields"]:
                    provider = require_field(model, str(field), model_name=model_name)
                    if item.get("source", "v") == "vin" and field != "idx" and not hasattr(provider, "vin"):
                        raise LiveValidationError(f"`vin` not found for {model_name}.{field}")
            else:
                require_field(model, str(item["variable"]), model_name=model_name)
            for idx in item.get("indices", []):
                require_model_idx(model, idx, model_name=model_name)
            resolved.append(
                {
                    "collection": collection,
                    "model": model_name,
                    "fields": item.get("fields"),
                    "variable": item.get("variable"),
                    "indices": as_jsonable(item.get("indices")),
                    "file": item.get("file"),
                }
            )
    for criterion in job.get("checks", {}).get("criteria", []):
        model_name = str(criterion["model"])
        model = require_model(system, model_name)
        require_field(model, str(criterion["variable"]), model_name=model_name)
        for idx in criterion.get("indices", []):
            require_model_idx(model, idx, model_name=model_name)
        resolved.append(
            {
                "collection": "criterion",
                "name": criterion["name"],
                "model": model_name,
                "variable": criterion["variable"],
                "indices": as_jsonable(criterion.get("indices")),
            }
        )
    return resolved


def validate_routine_args_live(system: Any, job: Mapping[str, Any]) -> dict[str, Any]:
    routine = job["routine"]
    args = job.get("routine_args", {})
    report: dict[str, Any] = {"routine": routine}
    if routine == "eig" and args.get("sweep"):
        sweep = args["sweep"]
        model_name = str(sweep["model"])
        model = require_model(system, model_name)
        require_model_idx(model, sweep["idx"], model_name=model_name)
        require_field(model, str(sweep["parameter"]), model_name=model_name)
        report["sweep"] = as_jsonable(sweep)
    elif routine == "se":
        for measurement in args.get("measurements", []):
            kind = measurement["type"]
            if kind in {"bus_voltage", "bus_angle", "bus_injection"}:
                model = require_model(system, "Bus")
                for idx in measurement.get("bus_idx", []):
                    require_model_idx(model, idx, model_name="Bus")
            elif kind == "line_flow":
                model = require_model(system, "Line")
                for idx in measurement.get("line_idx", []):
                    require_model_idx(model, idx, model_name="Line")
            else:
                raise LiveValidationError(
                    f"Unsupported state-estimation measurement type: {kind}. "
                    "The ANDES 2.0.0 runner supports Bus v/a, bus injection, and line flow measurements."
                )
        report["measurement_count_specs"] = len(args.get("measurements", []))
    elif routine == "cpf":
        if args.get("qv"):
            bus = require_model(system, "Bus")
            require_model_idx(bus, args["qv"]["bus_idx"], model_name="Bus")
        pq_count = int(getattr(require_model(system, "PQ"), "n", 0) or 0)
        pv_count = int(getattr(require_model(system, "PV"), "n", 0) or 0)
        for field in ("p0_target", "q0_target"):
            if field in args and len(args[field]) != pq_count:
                raise LiveValidationError(
                    f"CPF `{field}` length is {len(args[field])}; case PQ device count is {pq_count}"
                )
        if "pg_target" in args and len(args["pg_target"]) != pv_count:
            raise LiveValidationError(
                f"CPF `pg_target` length is {len(args['pg_target'])}; case PV device count is {pv_count}"
            )
        report["pq_count"] = pq_count
        report["pv_count"] = pv_count
    return report


def build_system_for_job(
    andes: Any,
    job: Mapping[str, Any],
    *,
    spec_dir: Path,
    job_dir: Path,
    copy_inputs: bool,
) -> tuple[Any, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    resolved = resolve_case_spec(andes, job["case"], spec_dir)
    case_path, addfiles, input_manifest = prepare_input_files(
        resolved,
        job_dir / "input",
        copy_inputs=copy_inputs,
    )
    system = load_system(
        andes,
        case_path,
        addfiles,
        setup=False,
        output_path=job_dir / "andes_outputs",
        config_option=resolved.get("config_option", []),
        default_config=resolved.get("default_config", False),
    )
    changes: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    for name in job.get("disable_existing_events", []):
        changes.extend(disable_existing_event_model(system, str(name)))
    for operation in job.get("pre_setup", []):
        changes.extend(apply_operation(system, operation))
    for event in job.get("events", []):
        events.append(add_event(system, event))
    try:
        setup_result = system.setup()
    except Exception as exc:
        raise LiveValidationError(f"System.setup() failed: {type(exc).__name__}: {exc}") from exc
    if setup_result is False:
        raise LiveValidationError("System.setup() returned False")
    warnings.extend(guard_dynamic_static_alter_targets(system, job.get("events", [])))
    for operation in job.get("post_setup", []):
        changes.extend(apply_operation(system, operation))
    routine_obj = getattr(system, str(job["routine"]).upper(), None)
    routine_attr = {
        "pflow": "PFlow",
        "tds": "TDS",
        "eig": "EIG",
        "se": "SE",
        "cpf": "CPF",
        "inspect": None,
    }[str(job["routine"])]
    if routine_attr:
        routine_obj = getattr(system, routine_attr, None)
        if routine_obj is None:
            raise LiveValidationError(f"Routine `{routine_attr}` not found in the installed ANDES version")
        changes.extend(apply_config(routine_obj.config, job.get("routine_config", {}), owner=routine_attr))
    return system, input_manifest, changes, events, warnings


def preflight_spec(
    spec: Mapping[str, Any] | str | os.PathLike[str],
    *,
    spec_dir: Path | None = None,
    raise_on_error: bool = True,
) -> dict[str, Any]:
    if isinstance(spec, (str, os.PathLike)):
        spec_path = Path(spec).expanduser().resolve()
        normalized = validate_spec(load_json(spec_path))
        base_dir = spec_path.parent
    else:
        normalized = validate_spec(spec)
        base_dir = (spec_dir or Path.cwd()).resolve()
    andes = import_andes()
    compatibility = require_supported_andes(andes)
    report: dict[str, Any] = {
        "started_at_utc": utc_now(),
        "environment": environment_snapshot(andes),
        "compatibility": compatibility,
        "study_name": normalized["study_name"],
        "ok": True,
        "jobs": [],
    }
    with tempfile.TemporaryDirectory(prefix="andes-preflight-") as temp:
        root = Path(temp)
        for position, job in enumerate(normalized["jobs"]):
            job_report: dict[str, Any] = {"id": job["id"], "routine": job["routine"], "ok": False}
            try:
                system, inputs, changes, events, warnings = build_system_for_job(
                    andes,
                    job,
                    spec_dir=base_dir,
                    job_dir=root / f"{position:03d}-{slugify(job['id'])}",
                    copy_inputs=False,
                )
                stage_refs = []
                for stage in job.get("stages", []):
                    stage_refs.append(
                        {
                            "until": stage["until"],
                            "before": [validate_stage_operation_live(system, op) for op in stage.get("before", [])],
                        }
                    )
                output_refs = validate_output_reference_live(system, job)
                routine_refs = validate_routine_args_live(system, job)
                job_report.update(
                    {
                        "ok": True,
                        "inputs": inputs,
                        "changes": changes,
                        "events": events,
                        "warnings": warnings,
                        "stages": stage_refs,
                        "output_references": output_refs,
                        "routine_references": routine_refs,
                        "inventory_summary": inspect_system(system, max_indices=20)["counts"],
                    }
                )
            except Exception as exc:
                report["ok"] = False
                job_report["error"] = f"{type(exc).__name__}: {exc}"
                job_report["traceback"] = traceback.format_exc()
                if raise_on_error:
                    report["jobs"].append(job_report)
                    report["finished_at_utc"] = utc_now()
                    raise LiveValidationError(
                        f"Live preflight failed (job `{job.get('id')}`): {exc}"
                    ) from exc
            report["jobs"].append(job_report)
    report["finished_at_utc"] = utc_now()
    return report


# ---------------------------------------------------------------------------
# Numerical routines and outputs
# ---------------------------------------------------------------------------


def _run_pflow(system: Any) -> dict[str, Any]:
    try:
        returned = system.PFlow.run()
    except Exception as exc:
        raise StudyExecutionError(f"PFlow execution error: {type(exc).__name__}: {exc}") from exc
    converged = bool(getattr(system.PFlow, "converged", returned is True))
    return {
        "returned": as_jsonable(returned),
        "converged": converged,
        "iterations": as_jsonable(getattr(system.PFlow, "niter", None)),
        "execution_time": as_jsonable(getattr(system.PFlow, "execution_time", None)),
        "report_file": as_jsonable(getattr(getattr(system, "files", None), "txt", None)),
    }


def require_pflow(system: Any) -> dict[str, Any]:
    result = _run_pflow(system)
    if not result["converged"]:
        raise StudyExecutionError("Power flow did not converge; dependent routine was not run")
    return result


def _actual_tds_time(system: Any) -> float | None:
    np = _numpy()
    try:
        values = np.asarray(system.dae.ts.t, dtype=float)
        if values.size:
            return float(values[-1])
    except Exception:
        pass
    try:
        return float(_scalar(system.dae.t))
    except Exception:
        return None


def _tds_exit_code(system: Any) -> int | None:
    for owner in (getattr(system, "TDS", None), system):
        if owner is not None and hasattr(owner, "exit_code"):
            try:
                return int(getattr(owner, "exit_code"))
            except Exception:
                pass
    return None


def _run_tds(system: Any, job: Mapping[str, Any]) -> dict[str, Any]:
    stages = job.get("stages", [])
    changes: list[dict[str, Any]] = []
    stage_results: list[dict[str, Any]] = []
    if stages:
        for stage_index, stage in enumerate(stages):
            stage_changes: list[dict[str, Any]] = []
            for operation in stage.get("before", []):
                stage_changes.extend(apply_operation(system, operation))
            changes.extend(stage_changes)
            system.TDS.config.tf = float(stage["until"])
            try:
                returned = system.TDS.run()
            except Exception as exc:
                raise StudyExecutionError(
                    f"TDS stage {stage_index + 1} (tf={stage['until']}) failed: {type(exc).__name__}: {exc}"
                ) from exc
            stage_results.append(
                {
                    "stage": stage_index + 1,
                    "requested_until": float(stage["until"]),
                    "actual_time": _actual_tds_time(system),
                    "returned": as_jsonable(returned),
                    "exit_code": _tds_exit_code(system),
                    "changes": stage_changes,
                }
            )
    else:
        requested_tf = float(job["routine_config"]["tf"])
        try:
            returned = system.TDS.run()
        except Exception as exc:
            raise StudyExecutionError(f"TDS failed: {type(exc).__name__}: {exc}") from exc
        stage_results.append(
            {
                "stage": 1,
                "requested_until": requested_tf,
                "actual_time": _actual_tds_time(system),
                "returned": as_jsonable(returned),
                "exit_code": _tds_exit_code(system),
                "changes": [],
            }
        )
    final_requested = float(stages[-1]["until"] if stages else job["routine_config"]["tf"])
    actual = _actual_tds_time(system)
    exit_code = _tds_exit_code(system)
    reached = actual is not None and actual + max(1e-9, abs(final_requested) * 1e-8) >= final_requested
    return {
        "stages": stage_results,
        "stage_changes": changes,
        "requested_final_time": final_requested,
        "actual_final_time": actual,
        "reached_final_time": reached,
        "exit_code": exit_code,
        "execution_time": as_jsonable(getattr(system.TDS, "execution_time", None)),
        "output_list": as_jsonable(getattr(getattr(system, "files", None), "lst", None)),
        "output_npz": as_jsonable(getattr(getattr(system, "files", None), "npz", None)),
    }


def _extract_eigenvalues(system: Any) -> Any:
    np = _numpy()
    eig = system.EIG
    for name in ("mu", "eigvals", "eigenvalues", "eig_values"):
        if hasattr(eig, name):
            value = getattr(eig, name)
            if value is not None:
                array = np.asarray(value, dtype=complex).reshape(-1)
                if array.size:
                    return array
    try:
        returned = eig.calc_eig()
        if isinstance(returned, tuple):
            returned = returned[0]
        array = np.asarray(returned, dtype=complex).reshape(-1)
        if array.size:
            return array
    except Exception:
        pass
    raise StudyExecutionError(
        "EIG ran but the eigenvalue array was not found in the accessible API of the installed version; "
        "inspect the generated *_eig.txt report."
    )


def _run_eig(system: Any, job: Mapping[str, Any], figures_dir: Path) -> dict[str, Any]:
    try:
        returned = system.EIG.run()
    except Exception as exc:
        raise StudyExecutionError(f"EIG failed: {type(exc).__name__}: {exc}") from exc
    eigenvalues = _extract_eigenvalues(system)
    sweep_result: dict[str, Any] | None = None
    sweep = job.get("routine_args", {}).get("sweep")
    if sweep:
        model = require_model(system, str(sweep["model"]))
        parameter = require_field(model, str(sweep["parameter"]), model_name=str(sweep["model"]))
        try:
            raw = system.EIG.sweep(parameter, sweep["idx"], sweep["values"])
        except Exception as exc:
            raise StudyExecutionError(f"EIG parameter sweep failed: {exc}") from exc
        sweep_result = {
            "model": sweep["model"],
            "parameter": sweep["parameter"],
            "idx": as_jsonable(sweep["idx"]),
            "values": as_jsonable(sweep["values"]),
            "raw_summary": _summarize_sweep_result(raw),
        }
        if sweep.get("plot_file"):
            target = safe_relative_path(figures_dir, str(sweep["plot_file"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                plotted = system.EIG.plot_root_loci(raw, sweep["eig_indices"])
                fig = plotted[0] if isinstance(plotted, tuple) else plotted
                fig.savefig(target, dpi=300, bbox_inches="tight")
                _pyplot().close(fig)
                sweep_result["plot_file"] = str(target)
            except Exception as exc:
                raise StudyExecutionError(f"Could not save the root-locus plot: {exc}") from exc
    return {
        "returned": as_jsonable(returned),
        "eigenvalues": eigenvalues,
        "counts": {
            "positive_real": int((eigenvalues.real > 1e-9).sum()),
            "near_zero_real": int((abs(eigenvalues.real) <= 1e-9).sum()),
            "negative_real": int((eigenvalues.real < -1e-9).sum()),
        },
        "execution_time": as_jsonable(getattr(system.EIG, "execution_time", None)),
        "report_file": as_jsonable(getattr(getattr(system, "files", None), "eig", None)),
        "sweep": sweep_result,
    }


def _summarize_sweep_result(raw: Any) -> Any:
    if isinstance(raw, Mapping):
        return {str(key): as_jsonable(value) for key, value in raw.items()}
    return as_jsonable(raw)


def _build_measurements(system: Any, args: Mapping[str, Any], default_seed: int) -> tuple[Any | None, dict[str, Any]]:
    specs = args.get("measurements", [])
    if not specs:
        if args.get("gross_errors"):
            raise StudyExecutionError("Adding gross errors requires an explicit measurement set")
        return None, {"mode": "andes_default"}
    try:
        se_module = importlib.import_module("andes.se")
        Measurements = getattr(se_module, "Measurements")
    except Exception as exc:
        raise StudyExecutionError(f"Could not import andes.se.Measurements: {exc}") from exc
    measurements = Measurements(system)
    for spec in specs:
        kind = spec["type"]
        if kind == "bus_voltage":
            kwargs = {"sigma": spec["sigma"]}
            if "bus_idx" in spec:
                kwargs["bus_idx"] = spec["bus_idx"]
            measurements.add_bus_voltage(**kwargs)
        elif kind == "bus_angle":
            kwargs = {"sigma": spec["sigma"]}
            if "bus_idx" in spec:
                kwargs["bus_idx"] = spec["bus_idx"]
            measurements.add_bus_angle(**kwargs)
        elif kind == "bus_injection":
            kwargs = {"sigma_p": spec["sigma_p"], "sigma_q": spec["sigma_q"]}
            if "bus_idx" in spec:
                kwargs["bus_idx"] = spec["bus_idx"]
            measurements.add_bus_injection(**kwargs)
        elif kind == "line_flow":
            kwargs = {"sigma_p": spec["sigma_p"], "sigma_q": spec["sigma_q"]}
            if "line_idx" in spec:
                kwargs["line_idx"] = spec["line_idx"]
            measurements.add_line_flow(**kwargs)
        else:
            raise StudyExecutionError(f"Unsupported SE measurement type: {kind}")
    seed = int(args.get("seed", default_seed))
    measurements.generate_from_pflow(seed=seed)
    gross_records: list[dict[str, Any]] = []
    for error in args.get("gross_errors", []):
        index = int(error["measurement_index"])
        if index >= int(getattr(measurements, "nm", len(measurements.z))):
            raise StudyExecutionError(
                f"Gross-error measurement index {index} is outside the total measurement count"
            )
        before = float(measurements.z[index])
        delta = float(error["sigma_multiplier"]) * float(measurements.sigma[index])
        measurements.z[index] += delta
        gross_records.append(
            {
                "measurement_index": index,
                "sigma_multiplier": error["sigma_multiplier"],
                "before": before,
                "after": float(measurements.z[index]),
                "sigma": float(measurements.sigma[index]),
                "note": error.get("note"),
            }
        )
    return measurements, {
        "mode": "custom",
        "seed": seed,
        "measurement_specs": as_jsonable(specs),
        "measurement_count": int(getattr(measurements, "nm", 0)),
        "gross_errors": gross_records,
    }


def _run_se(system: Any, job: Mapping[str, Any], default_seed: int) -> dict[str, Any]:
    args = job.get("routine_args", {})
    measurements, measurement_report = _build_measurements(system, args, default_seed)
    algorithm_name = str(args.get("algorithm", "wls")).lower()
    kwargs: dict[str, Any] = {}
    if measurements is not None:
        kwargs["measurements"] = measurements
    if algorithm_name == "lav":
        try:
            kwargs["algorithm"] = getattr(importlib.import_module("andes.se"), "lav")
        except Exception as exc:
            raise StudyExecutionError(f"Could not import the LAV algorithm: {exc}") from exc
    try:
        returned = system.SE.run(**kwargs)
    except Exception as exc:
        raise StudyExecutionError(f"SE failed: {type(exc).__name__}: {exc}") from exc
    chi_squared: dict[str, Any] | None = None
    if bool(args.get("chi_squared", False)):
        try:
            passed, objective, threshold, dof = system.SE.chi_squared_test(
                confidence=float(args.get("confidence", 0.95))
            )
        except TypeError:
            passed, objective, threshold, dof = system.SE.chi_squared_test()
        chi_squared = {
            "passed": bool(passed),
            "objective": as_jsonable(objective),
            "threshold": as_jsonable(threshold),
            "dof": as_jsonable(dof),
            "confidence": float(args.get("confidence", 0.95)),
        }
    return {
        "returned": as_jsonable(returned),
        "algorithm": algorithm_name,
        "converged": bool(getattr(system.SE, "converged", returned is True)),
        "iterations": as_jsonable(getattr(system.SE, "niter", None)),
        "objective": as_jsonable(getattr(system.SE, "J", getattr(system.SE, "objective", None))),
        "v_est": getattr(system.SE, "v_est", None),
        "a_est": getattr(system.SE, "a_est", None),
        "measurements": measurement_report,
        "chi_squared": chi_squared,
        "execution_time": as_jsonable(getattr(system.SE, "execution_time", None)),
    }


def _run_cpf(system: Any, job: Mapping[str, Any]) -> dict[str, Any]:
    args = job.get("routine_args", {})
    try:
        if args.get("qv"):
            qv = args["qv"]
            returned = system.CPF.run_qv(bus_idx=qv["bus_idx"], q_range=qv["q_range"])
            mode = "qv"
        else:
            kwargs = {key: args[key] for key in ("load_scale", "p0_target", "q0_target", "pg_target") if key in args}
            returned = system.CPF.run(**kwargs)
            mode = "pv"
    except Exception as exc:
        raise StudyExecutionError(f"CPF failed: {type(exc).__name__}: {exc}") from exc
    return {
        "returned": as_jsonable(returned),
        "mode": mode,
        "converged": bool(getattr(system.CPF, "converged", returned is True)),
        "max_lam": as_jsonable(getattr(system.CPF, "max_lam", None)),
        "lam": getattr(system.CPF, "lam", None),
        "V": getattr(system.CPF, "V", None),
        "theta": getattr(system.CPF, "theta", None),
        "steps": getattr(system.CPF, "steps", None),
        "qv_q": getattr(system.CPF, "qv_q", None),
        "qv_v": getattr(system.CPF, "qv_v", None),
        "qv_bus": as_jsonable(getattr(system.CPF, "qv_bus", None)),
        "execution_time": as_jsonable(getattr(system.CPF, "execution_time", None)),
    }


def _select_dataframe_columns(frame: Any, indices: Sequence[Any] | None) -> Any:
    if not indices:
        return frame
    columns = list(frame.columns)
    selected = []
    for requested in indices:
        try:
            selected.append(columns[find_index(columns, requested)])
        except KeyError as exc:
            raise LiveValidationError(
                f"Time-series column idx={requested} not found. Columns: {columns[:30]}"
            ) from exc
    return frame.loc[:, selected]


def get_timeseries(system: Any, model_name: str, variable: str, indices: Sequence[Any] | None = None) -> Any:
    model = require_model(system, model_name)
    provider = require_field(model, variable, model_name=model_name)
    try:
        frame = system.TDS.get_timeseries(provider)
    except Exception as exc:
        raise StudyExecutionError(f"Could not extract time series: {model_name}.{variable}: {exc}") from exc
    return _select_dataframe_columns(frame, indices)


def write_requested_outputs(
    system: Any,
    job: Mapping[str, Any],
    routine_result: MutableMapping[str, Any],
    job_dir: Path,
) -> dict[str, Any]:
    pd = _pandas()
    np = _numpy()
    outputs = job.get("outputs", {})
    written: list[dict[str, Any]] = []
    cached_series: dict[tuple[str, str, str], Any] = {}

    for item in outputs.get("tables", []):
        model_name = str(item["model"])
        model = require_model(system, model_name)
        rows = model_rows(
            model,
            model_name=model_name,
            fields=item["fields"],
            indices=item.get("indices"),
            source=item.get("source", "v"),
        )
        target = safe_relative_path(job_dir / "tables", str(item["file"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(target, index=False)
        written.append({"kind": "table", "path": str(target), "rows": len(rows)})

    for item in outputs.get("timeseries", []):
        key = (str(item["model"]), str(item["variable"]), json.dumps(item.get("indices", []), default=json_default))
        frame = get_timeseries(system, key[0], key[1], item.get("indices"))
        factor = float(item.get("factor", 1.0))
        offset = float(item.get("offset", 0.0))
        transformed = frame * factor + offset
        cached_series[key] = transformed
        target = safe_relative_path(job_dir / "timeseries", str(item["file"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        transformed.to_csv(target, index=True, index_label="time_s")
        written.append({"kind": "timeseries", "path": str(target), "shape": list(transformed.shape)})

    for item in outputs.get("plots", []):
        key = (str(item["model"]), str(item["variable"]), json.dumps(item.get("indices", []), default=json_default))
        if key not in cached_series:
            frame = get_timeseries(system, key[0], key[1], item.get("indices"))
            cached_series[key] = frame * float(item.get("factor", 1.0)) + float(item.get("offset", 0.0))
        frame = cached_series[key]
        plt = _pyplot()
        fig, ax = plt.subplots()
        ax.plot(frame.index.to_numpy(), frame.to_numpy())
        ax.set_xlabel(item.get("xlabel", "Time [s]"))
        ax.set_ylabel(item.get("ylabel", f"{key[0]}.{key[1]}"))
        if item.get("title"):
            ax.set_title(item["title"])
        if item.get("grid", True):
            ax.grid(True)
        if item.get("legend", True):
            ax.legend([str(column) for column in frame.columns])
        if item.get("xlim"):
            ax.set_xlim(item["xlim"])
        if item.get("ylim"):
            ax.set_ylim(item["ylim"])
        fig.tight_layout()
        target = safe_relative_path(job_dir / "figures", str(item["file"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, dpi=int(item.get("dpi", 300)), bbox_inches="tight")
        plt.close(fig)
        written.append({"kind": "plot", "path": str(target), "curves": int(frame.shape[1])})

    if job["routine"] == "eig":
        eigenvalues = np.asarray(routine_result["eigenvalues"], dtype=complex).reshape(-1)
        table = pd.DataFrame(
            {
                "index": np.arange(eigenvalues.size),
                "real_per_s": eigenvalues.real,
                "imag_per_s": eigenvalues.imag,
                "frequency_hz": np.abs(eigenvalues.imag) / (2 * np.pi),
                "damping_ratio": np.divide(
                    -eigenvalues.real,
                    np.abs(eigenvalues),
                    out=np.full(eigenvalues.size, np.nan, dtype=float),
                    where=np.abs(eigenvalues) > 0,
                ),
            }
        )
        target = job_dir / "tables" / "eigenvalues.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(target, index=False)
        written.append({"kind": "eig_table", "path": str(target), "rows": len(table)})
        if outputs.get("eig_plot"):
            plt = _pyplot()
            fig, ax = plt.subplots()
            ax.scatter(eigenvalues.real, eigenvalues.imag, marker="x")
            ax.axvline(0.0, linewidth=0.8)
            ax.axhline(0.0, linewidth=0.8)
            ax.set_xlabel("Real [s^-1]")
            ax.set_ylabel("Imaginary [s^-1]")
            ax.grid(True)
            fig.tight_layout()
            plot_target = safe_relative_path(job_dir / "figures", str(outputs["eig_plot"]))
            plot_target.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(plot_target, dpi=300, bbox_inches="tight")
            plt.close(fig)
            written.append({"kind": "eig_plot", "path": str(plot_target)})
        routine_result["eigenvalues"] = as_jsonable(eigenvalues)

    if job["routine"] == "se":
        v_est = routine_result.get("v_est")
        a_est = routine_result.get("a_est")
        bus_idx = model_indices(require_model(system, "Bus"))
        if v_est is not None and a_est is not None:
            table = pd.DataFrame(
                {
                    "bus_idx": bus_idx,
                    "v_est_pu": np.asarray(v_est).reshape(-1),
                    "a_est_rad": np.asarray(a_est).reshape(-1),
                    "a_est_deg": np.degrees(np.asarray(a_est).reshape(-1)),
                }
            )
            target = job_dir / "tables" / "state_estimate.csv"
            target.parent.mkdir(parents=True, exist_ok=True)
            table.to_csv(target, index=False)
            written.append({"kind": "se_table", "path": str(target), "rows": len(table)})
        routine_result["v_est"] = as_jsonable(v_est)
        routine_result["a_est"] = as_jsonable(a_est)

    if job["routine"] == "cpf":
        lam = np.asarray(routine_result.get("lam"), dtype=float).reshape(-1)
        if routine_result.get("mode") == "qv":
            q = np.asarray(routine_result.get("qv_q"), dtype=float).reshape(-1)
            v = np.asarray(routine_result.get("qv_v"), dtype=float).reshape(-1)
            table = pd.DataFrame({"lambda": lam, "q_load_convention_pu": q, "q_injection_convention_pu": -q, "v_pu": v})
            target = job_dir / "tables" / "qv_curve.csv"
            target.parent.mkdir(parents=True, exist_ok=True)
            table.to_csv(target, index=False)
            written.append({"kind": "qv_table", "path": str(target), "rows": len(table)})
            if outputs.get("qv_plot"):
                plt = _pyplot()
                fig, ax = plt.subplots()
                ax.plot(-q, v)
                ax.set_xlabel("Reactive power injection [pu]")
                ax.set_ylabel("Voltage [pu]")
                ax.grid(True)
                fig.tight_layout()
                plot_target = safe_relative_path(job_dir / "figures", str(outputs["qv_plot"]))
                plot_target.parent.mkdir(parents=True, exist_ok=True)
                fig.savefig(plot_target, dpi=300, bbox_inches="tight")
                plt.close(fig)
                written.append({"kind": "qv_plot", "path": str(plot_target)})
        else:
            V = np.asarray(routine_result.get("V"), dtype=float)
            bus_idx = model_indices(require_model(system, "Bus"))
            if V.ndim != 2:
                raise StudyExecutionError(f"CPF.V is not the expected 2-D array: shape={V.shape}")
            data: dict[str, Any] = {"lambda": lam}
            for position, idx in enumerate(bus_idx):
                data[f"bus_{idx}_v_pu"] = V[position, :]
            table = pd.DataFrame(data)
            target = job_dir / "tables" / "pv_curve.csv"
            target.parent.mkdir(parents=True, exist_ok=True)
            table.to_csv(target, index=False)
            written.append({"kind": "cpf_table", "path": str(target), "rows": len(table)})
            if outputs.get("cpf_plot"):
                plot_spec = outputs["cpf_plot"]
                position = require_model_idx(require_model(system, "Bus"), plot_spec["bus_idx"], model_name="Bus")
                plt = _pyplot()
                fig, ax = plt.subplots()
                ax.plot(lam, V[position, :])
                if lam.size:
                    nose = int(np.argmax(lam))
                    ax.scatter([lam[nose]], [V[position, nose]], marker="*")
                ax.set_xlabel("lambda")
                ax.set_ylabel(f"Bus {plot_spec['bus_idx']} voltage [pu]")
                ax.grid(True)
                fig.tight_layout()
                plot_target = safe_relative_path(job_dir / "figures", str(plot_spec["file"]))
                plot_target.parent.mkdir(parents=True, exist_ok=True)
                fig.savefig(plot_target, dpi=300, bbox_inches="tight")
                plt.close(fig)
                written.append({"kind": "cpf_plot", "path": str(plot_target)})
        for field in ("lam", "V", "theta", "steps", "qv_q", "qv_v"):
            routine_result[field] = as_jsonable(routine_result.get(field))

    return {"written": written}


# ---------------------------------------------------------------------------
# Verification and criteria
# ---------------------------------------------------------------------------


def aggregate_values(values: Any, aggregate: str) -> Any:
    np = _numpy()
    array = np.asarray(values, dtype=float)
    if array.size == 0:
        raise StudyExecutionError("Empty data array for criterion")
    if aggregate == "min":
        return float(np.nanmin(array))
    if aggregate == "max":
        return float(np.nanmax(array))
    if aggregate == "mean":
        return float(np.nanmean(array))
    if aggregate == "abs_max":
        return float(np.nanmax(np.abs(array)))
    if aggregate == "range":
        return float(np.nanmax(array) - np.nanmin(array))
    if aggregate == "final":
        if array.ndim == 0:
            return float(array)
        if array.ndim == 1:
            return float(array[-1])
        return array[-1, :].astype(float).tolist()
    raise StudyExecutionError(f"Unsupported aggregate: {aggregate}")


def compare_value(actual: Any, operator: str, *, threshold: float | None = None, bounds: Sequence[float] | None = None, atol: float = 0.0) -> bool:
    np = _numpy()
    values = np.asarray(actual, dtype=float)
    if operator == "<":
        result = values < float(threshold)
    elif operator == "<=":
        result = values <= float(threshold) + atol
    elif operator == ">":
        result = values > float(threshold)
    elif operator == ">=":
        result = values + atol >= float(threshold)
    elif operator == "==":
        result = np.isclose(values, float(threshold), atol=atol, rtol=0.0)
    elif operator == "!=":
        result = ~np.isclose(values, float(threshold), atol=atol, rtol=0.0)
    elif operator == "between":
        assert bounds is not None
        result = (values + atol >= float(bounds[0])) & (values <= float(bounds[1]) + atol)
    elif operator == "outside":
        assert bounds is not None
        result = (values < float(bounds[0]) - atol) | (values > float(bounds[1]) + atol)
    else:
        raise StudyExecutionError(f"Unsupported comparison: {operator}")
    return bool(np.all(result))


def _criterion_values(system: Any, criterion: Mapping[str, Any]) -> Any:
    model_name = str(criterion["model"])
    variable = str(criterion["variable"])
    if criterion["source"] == "timeseries":
        frame = get_timeseries(system, model_name, variable, criterion.get("indices"))
        return frame.to_numpy()
    model = require_model(system, model_name)
    provider = require_field(model, variable, model_name=model_name)
    if hasattr(provider, "v"):
        values = _sequence(provider.v)
    else:
        values = _sequence(provider)
    if criterion.get("indices"):
        positions = [require_model_idx(model, idx, model_name=model_name) for idx in criterion["indices"]]
        values = [values[position] for position in positions]
    return values


def _routine_success(job: Mapping[str, Any], pflow: Mapping[str, Any] | None, routine: Mapping[str, Any]) -> dict[str, Any]:
    routine_name = job["routine"]
    if routine_name == "inspect":
        return {"passed": True, "reason": "inspection_completed"}
    if pflow is not None and not bool(pflow.get("converged")):
        return {"passed": False, "reason": "pflow_not_converged"}
    if routine_name == "pflow":
        return {"passed": bool(routine.get("converged")), "reason": "pflow_convergence"}
    if routine_name == "tds":
        exit_code = routine.get("exit_code")
        # An unknown exit code is not evidence of success; every stage must also have exited cleanly.
        stage_codes = [stage.get("exit_code") for stage in routine.get("stages", [])]
        passed = (
            bool(routine.get("reached_final_time"))
            and exit_code == 0
            and all(code == 0 for code in stage_codes)
        )
        return {
            "passed": passed,
            "reason": "tds_exit_code_and_final_time",
            "exit_code": exit_code,
            "stage_exit_codes": stage_codes,
        }
    if routine_name in {"se", "cpf"}:
        return {"passed": bool(routine.get("converged")), "reason": f"{routine_name}_convergence"}
    if routine_name == "eig":
        return {"passed": bool(routine.get("eigenvalues")), "reason": "eigenvalues_available"}
    return {"passed": False, "reason": "unknown_routine"}


def _finite_system_data(system: Any, routine_name: str) -> dict[str, Any]:
    np = _numpy()
    arrays: dict[str, Any] = {}
    for name in ("x", "y", "f", "g"):
        value = getattr(getattr(system, "dae", None), name, None)
        if value is not None:
            arrays[f"dae.{name}"] = value
    if routine_name == "tds":
        ts = getattr(getattr(system, "dae", None), "ts", None)
        for name in ("t", "x", "y"):
            value = getattr(ts, name, None) if ts is not None else None
            if value is not None:
                arrays[f"dae.ts.{name}"] = value
    failures = []
    checked = []
    for name, value in arrays.items():
        try:
            array = np.asarray(value, dtype=float)
        except Exception:
            continue
        checked.append({"name": name, "shape": list(array.shape)})
        if array.size and not bool(np.isfinite(array).all()):
            failures.append(name)
    return {"passed": not failures, "checked": checked, "nonfinite_arrays": failures}


def evaluate_checks(
    system: Any,
    job: Mapping[str, Any],
    *,
    pflow_result: Mapping[str, Any] | None,
    routine_result: Mapping[str, Any],
) -> dict[str, Any]:
    checks = job.get("checks", {})
    records: list[dict[str, Any]] = []
    # Routine success is always evaluated; require_convergence=false only stops it from
    # failing the checks, and the job is then reported as completed_unverified.
    routine_check = _routine_success(job, pflow_result, routine_result)
    records.append(
        {"name": "routine_success", "enforced": bool(checks.get("require_convergence", True)), **routine_check}
    )
    if checks.get("finite", True):
        finite = _finite_system_data(system, str(job["routine"]))
        records.append({"name": "finite_values", **finite})
    for criterion in checks.get("criteria", []):
        values = _criterion_values(system, criterion)
        actual = aggregate_values(values, str(criterion["aggregate"]))
        passed = compare_value(
            actual,
            str(criterion["operator"]),
            threshold=criterion.get("threshold"),
            bounds=criterion.get("bounds"),
            atol=float(criterion.get("atol", 0.0)),
        )
        records.append(
            {
                "name": criterion["name"],
                "passed": passed,
                "model": criterion["model"],
                "variable": criterion["variable"],
                "indices": as_jsonable(criterion.get("indices")),
                "source": criterion["source"],
                "aggregate": criterion["aggregate"],
                "actual": as_jsonable(actual),
                "operator": criterion["operator"],
                "threshold": as_jsonable(criterion.get("threshold")),
                "bounds": as_jsonable(criterion.get("bounds")),
                "atol": criterion.get("atol", 0.0),
                "basis": criterion["basis"],
            }
        )
    return {
        "passed": all(bool(record.get("passed")) for record in records if record.get("enforced", True)),
        "routine_verified": bool(routine_check.get("passed")),
        "records": records,
    }


# ---------------------------------------------------------------------------
# Job/study execution
# ---------------------------------------------------------------------------


def _status(path: Path, state: str, **extra: Any) -> None:
    dump_json(path, {"state": state, "updated_at_utc": utc_now(), **as_jsonable(extra)})


def _run_single_job(
    andes: Any,
    job: Mapping[str, Any],
    *,
    defaults: Mapping[str, Any],
    spec_dir: Path,
    job_dir: Path,
) -> dict[str, Any]:
    job_dir.mkdir(parents=True, exist_ok=False)
    for subdir in ("input", "andes_outputs", "tables", "timeseries", "figures"):
        (job_dir / subdir).mkdir(parents=True, exist_ok=True)
    status_path = job_dir / "status.json"
    _status(status_path, "running", job_id=job["id"], routine=job["routine"])
    dump_json(job_dir / "job_spec.json", job)
    dump_json(job_dir / "environment.json", environment_snapshot(andes))

    system, input_manifest, changes, events, warnings = build_system_for_job(
        andes,
        job,
        spec_dir=spec_dir,
        job_dir=job_dir,
        copy_inputs=bool(defaults.get("copy_inputs", True)),
    )
    dump_json(job_dir / "inputs.json", input_manifest)
    resolved = {
        "inventory_summary": inspect_system(system, max_indices=30)["counts"],
        "stages": [
            {
                "until": stage["until"],
                "before": [validate_stage_operation_live(system, op) for op in stage.get("before", [])],
            }
            for stage in job.get("stages", [])
        ],
        "outputs_and_checks": validate_output_reference_live(system, job),
        "routine_args": validate_routine_args_live(system, job),
    }
    dump_json(job_dir / "resolved_entities.json", resolved)
    dump_json(job_dir / "changes.json", changes)
    dump_json(job_dir / "events.json", events)
    dump_json(job_dir / "warnings.json", warnings)

    routine_name = job["routine"]
    pflow_result: dict[str, Any] | None = None
    routine_result: dict[str, Any]
    if routine_name == "inspect":
        routine_result = {"inventory": inspect_system(system, include_empty=False)}
        dump_json(job_dir / "case_inventory.json", routine_result["inventory"])
    elif routine_name == "pflow":
        pflow_result = _run_pflow(system)
        routine_result = dict(pflow_result)
    elif routine_name == "tds":
        pflow_result = require_pflow(system)
        routine_result = _run_tds(system, job)
        if routine_result.get("stage_changes"):
            changes.extend(routine_result["stage_changes"])
            dump_json(job_dir / "changes.json", changes)
    elif routine_name == "eig":
        pflow_result = require_pflow(system)
        routine_result = _run_eig(system, job, job_dir / "figures")
    elif routine_name == "se":
        pflow_result = require_pflow(system)
        routine_result = _run_se(system, job, int(job.get("routine_args", {}).get("seed", defaults.get("seed", 42))))
    elif routine_name == "cpf":
        pflow_result = require_pflow(system)
        routine_result = _run_cpf(system, job)
    else:  # structural validation should make this unreachable
        raise StudyExecutionError(f"Unsupported routine: {routine_name}")

    outputs = write_requested_outputs(system, job, routine_result, job_dir)
    checks = evaluate_checks(system, job, pflow_result=pflow_result, routine_result=routine_result)
    dump_json(job_dir / "checks.json", checks)

    result = {
        "job_id": job["id"],
        "routine": routine_name,
        "started_and_completed": True,
        "pflow": as_jsonable(pflow_result),
        "routine_result": as_jsonable(routine_result),
        "outputs": outputs,
        "checks_passed": checks["passed"],
        "warnings": warnings,
    }
    dump_json(job_dir / "result.json", result)
    if not checks["passed"]:
        state = "completed_with_failed_checks"
    elif not checks["routine_verified"]:
        state = "completed_unverified"
    else:
        state = "completed"
    # Final status is written before the manifest so that every hashed file is final.
    _status(status_path, state, job_id=job["id"], routine=routine_name, checks_passed=checks["passed"])
    manifest = {
        "generated_at_utc": utc_now(),
        "job_id": job["id"],
        "files": [item for item in flatten_files(job_dir) if item["path"] != "manifest.json"],
    }
    dump_json(job_dir / "manifest.json", manifest)
    return {
        "id": job["id"],
        "routine": routine_name,
        "state": state,
        "directory": str(job_dir),
        "checks_passed": checks["passed"],
        "result_file": str(job_dir / "result.json"),
    }


def execute_study(
    spec: Mapping[str, Any] | str | os.PathLike[str],
    output_root: str | os.PathLike[str],
    *,
    live_preflight: bool = True,
    overwrite: bool | None = None,
) -> dict[str, Any]:
    started_at_utc = utc_now()
    if isinstance(spec, (str, os.PathLike)):
        spec_path = Path(spec).expanduser().resolve()
        normalized = validate_spec(load_json(spec_path))
        spec_dir = spec_path.parent
    else:
        normalized = validate_spec(spec)
        spec_path = None
        spec_dir = Path.cwd().resolve()
    defaults = normalized["defaults"]
    effective_overwrite = bool(defaults.get("overwrite", False) if overwrite is None else overwrite)
    # Record the source spec before anything is written, so its hash describes the user's file.
    source_record = (
        {"path": str(spec_path), "sha256": sha256_file(spec_path), "size_bytes": spec_path.stat().st_size}
        if spec_path
        else None
    )
    protected = protected_paths_for_spec(normalized, spec_dir=spec_dir, spec_path=spec_path)
    guard_output_destination(Path(output_root), protected)
    # Import and live preflight run before any existing output is removed.
    andes = import_andes()
    require_supported_andes(andes)
    protected.append(Path(andes.__file__).resolve().parent)  # built-in cases live here
    guard_output_destination(Path(output_root), protected)
    try:
        andes.config_logger(stream_level=int(defaults.get("log_level", 20)))
    except Exception:
        pass
    preflight = preflight_spec(normalized, spec_dir=spec_dir, raise_on_error=True) if live_preflight else None
    root = ensure_empty_destination(Path(output_root), overwrite=effective_overwrite, protected=protected)
    dump_json(root / "study_spec.json", normalized)
    if source_record:
        dump_json(root / "source_spec.json", source_record)
    dump_json(root / "environment.json", environment_snapshot(andes))
    if preflight is not None:
        dump_json(root / "preflight.json", preflight)
    _status(root / "study_status.json", "running", study_name=normalized["study_name"])
    summaries: list[dict[str, Any]] = []
    strict = bool(defaults.get("strict", True))
    failed = False
    for position, job in enumerate(normalized["jobs"], start=1):
        job_dir = root / f"{position:03d}-{slugify(job['id'])}"
        if failed and strict:
            job_dir.mkdir(parents=True, exist_ok=False)
            _status(job_dir / "status.json", "skipped", reason="previous_job_failed_in_strict_mode")
            summaries.append(
                {
                    "id": job["id"],
                    "routine": job["routine"],
                    "state": "skipped",
                    "directory": str(job_dir),
                }
            )
            continue
        try:
            summary = _run_single_job(
                andes,
                job,
                defaults=defaults,
                spec_dir=spec_dir,
                job_dir=job_dir,
            )
            summaries.append(summary)
            if summary["state"] in {"completed_with_failed_checks", "completed_unverified"}:
                failed = True
        except Exception as exc:
            failed = True
            job_dir.mkdir(parents=True, exist_ok=True)
            error = {
                "job_id": job.get("id"),
                "routine": job.get("routine"),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "failed_at_utc": utc_now(),
            }
            dump_json(job_dir / "error.json", error)
            _status(job_dir / "status.json", "failed", error=error["error"], error_type=error["error_type"])
            summaries.append(
                {
                    "id": job["id"],
                    "routine": job["routine"],
                    "state": "failed",
                    "directory": str(job_dir),
                    "error": str(exc),
                }
            )
            if not strict:
                continue
    bad_states = {"failed", "completed_with_failed_checks", "completed_unverified"}
    state = "failed" if any(item["state"] in bad_states for item in summaries) else "completed"
    study_result = {
        "study_name": normalized["study_name"],
        "state": state,
        "started_at_utc": started_at_utc,
        "finished_at_utc": utc_now(),
        "strict": strict,
        "jobs": summaries,
    }
    dump_json(root / "study_result.json", study_result)
    _status(root / "study_status.json", state, study_name=normalized["study_name"], jobs=summaries)
    manifest = {
        "generated_at_utc": utc_now(),
        "study_name": normalized["study_name"],
        "files": [item for item in flatten_files(root) if item["path"] != "study_manifest.json"],
    }
    dump_json(root / "study_manifest.json", manifest)
    return study_result


# ---------------------------------------------------------------------------
# CLI-facing convenience functions
# ---------------------------------------------------------------------------


def inspect_case(
    case: str,
    *,
    addfiles: Sequence[str] = (),
    builtin: bool = False,
    include_empty: bool = False,
    max_indices: int = 200,
) -> dict[str, Any]:
    andes = import_andes()
    require_supported_andes(andes)
    base = Path.cwd().resolve()
    case_spec: dict[str, Any] = {"builtin": case} if builtin else {"path": case}
    case_spec["addfiles"] = list(addfiles)
    resolved = resolve_case_spec(andes, case_spec, base)
    system = load_system(
        andes,
        resolved["case"]["resolved"],
        [item["resolved"] for item in resolved["addfiles"]],
        setup=True,
        output_path=None,
        config_option=resolved.get("config_option", []),
        default_config=resolved.get("default_config", False),
    )
    return {
        "environment": environment_snapshot(andes),
        "inputs": resolved,
        "inventory": inspect_system(system, include_empty=include_empty, max_indices=max_indices),
    }


def inspect_model_data(
    case: str,
    model_name: str,
    *,
    fields: Sequence[str],
    indices: Sequence[Any] | None = None,
    source: str = "v",
    addfiles: Sequence[str] = (),
    builtin: bool = False,
    include_doc: bool = False,
) -> dict[str, Any]:
    andes = import_andes()
    require_supported_andes(andes)
    case_spec: dict[str, Any] = {"builtin": case} if builtin else {"path": case}
    case_spec["addfiles"] = list(addfiles)
    resolved = resolve_case_spec(andes, case_spec, Path.cwd())
    system = load_system(
        andes,
        resolved["case"]["resolved"],
        [item["resolved"] for item in resolved["addfiles"]],
        setup=True,
        output_path=None,
    )
    model = require_model(system, model_name)
    result = {
        "inputs": resolved,
        "model": model_name,
        "count": int(getattr(model, "n", len(model_indices(model))) or 0),
        "fields": discover_model_fields(model),
        "rows": model_rows(model, model_name=model_name, fields=fields, indices=indices, source=source),
    }
    if include_doc:
        result["documentation"] = _compact_doc(model)
    return result


def inspect_connections(
    case: str,
    model_name: str,
    idx: Any,
    *,
    addfiles: Sequence[str] = (),
    builtin: bool = False,
    details: bool = False,
) -> dict[str, Any]:
    andes = import_andes()
    require_supported_andes(andes)
    case_spec: dict[str, Any] = {"builtin": case} if builtin else {"path": case}
    case_spec["addfiles"] = list(addfiles)
    resolved = resolve_case_spec(andes, case_spec, Path.cwd())
    system = load_system(
        andes,
        resolved["case"]["resolved"],
        [item["resolved"] for item in resolved["addfiles"]],
        setup=True,
        output_path=None,
    )
    return {
        "inputs": resolved,
        **find_connected(system, model_name, idx, details=details),
    }


__all__ = [
    "AndesUnavailableError",
    "LiveValidationError",
    "StudyExecutionError",
    "RUNTIME_VERSION",
    "MANUAL_BUILD",
    "TARGET_ANDES_RELEASE",
    "andes_capabilities",
    "andes_compatibility",
    "aggregate_values",
    "compare_value",
    "environment_snapshot",
    "execute_study",
    "find_connected",
    "import_andes",
    "inspect_case",
    "inspect_connections",
    "inspect_model_data",
    "preflight_spec",
    "require_supported_andes",
]
