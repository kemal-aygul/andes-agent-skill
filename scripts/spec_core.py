"""Structural validation and deterministic file helpers for ANDES studies.

This module deliberately has no ANDES dependency. It can validate a proposed
study, create bundles, and run unit tests before an ANDES environment is active.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Sequence

SCHEMA_VERSION = "1.0"
ALLOWED_ROUTINES = {"inspect", "pflow", "tds", "eig", "se", "cpf"}
ALLOWED_BASES = {"device", "system"}
ALLOWED_PRE_SETUP_OPS = {"set_status"}
ALLOWED_POST_SETUP_OPS = {"set_parameter", "scale_parameter"}
ALLOWED_STAGE_OPS = {"set_setpoint", "set_parameter"}
ALLOWED_EVENTS = {"fault", "toggle", "alter"}
ALLOWED_ALTER_METHODS = {"=", "+", "-", "*", "/"}
ALLOWED_MEASUREMENTS = {"bus_voltage", "bus_angle", "bus_injection", "line_flow"}
ALLOWED_OPERATORS = {"<", "<=", ">", ">=", "==", "!=", "between", "outside"}
ALLOWED_AGGREGATES = {"min", "max", "mean", "final", "abs_max", "range"}


class SpecError(ValueError):
    """Raised when a study specification or safe path is invalid."""


def load_json(path: str | os.PathLike[str]) -> dict[str, Any]:
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise SpecError(f"Specification file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise SpecError(
            f"Invalid JSON: {source} (line {exc.lineno}, column {exc.colno}): {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise SpecError("The top level of the specification must be a JSON object.")
    return data


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass
    if isinstance(value, set):
        return sorted(value, key=str)
    return repr(value)


def dump_json(
    path: str | os.PathLike[str],
    data: Any,
    *,
    overwrite: bool = True,
) -> Path:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"File already exists: {destination}")
    payload = json.dumps(data, ensure_ascii=False, indent=2, default=json_default)
    _atomic_write_text(destination, payload + "\n")
    return destination


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def sha256_file(path: str | os.PathLike[str], *, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def copy_with_hash(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    src = Path(source).expanduser().resolve()
    dst = Path(destination)
    if not src.is_file():
        raise FileNotFoundError(f"Input file not found: {src}")
    if dst.exists() and not overwrite:
        raise FileExistsError(f"Destination already exists: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return {
        "source": str(src),
        "copied_to": str(dst.resolve()),
        "size_bytes": dst.stat().st_size,
        "sha256": sha256_file(dst),
    }


def slugify(value: Any, *, default: str = "job", max_length: int = 80) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = re.sub(r"[-_.]{2,}", "-", text).strip("-._")
    text = text or default
    return text[:max_length].rstrip("-._") or default


def _escapes_root(value: str) -> bool:
    """True for paths that are absolute, rooted ("/x"), drive-relative ("C:x") or contain "..", on any OS."""
    for flavour in (PureWindowsPath(value), PurePosixPath(value)):
        if flavour.drive or flavour.root or ".." in flavour.parts:
            return True
    return False


def safe_relative_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    if _escapes_root(value) or not value.strip():
        raise SpecError(f"A relative file path inside the output root is required: {value!r}")
    base = root.resolve()
    target = (base / candidate).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise SpecError(f"Attempt to write outside the safe output root: {target}") from exc
    return target


def flatten_files(root: Path) -> list[dict[str, Any]]:
    base = root.resolve()
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in base.rglob("*") if item.is_file()):
        records.append(
            {
                "path": path.relative_to(base).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def deep_merge(base: MutableMapping[str, Any], update: Mapping[str, Any]) -> MutableMapping[str, Any]:
    for key, value in update.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), MutableMapping):
            deep_merge(base[key], value)  # type: ignore[index]
        else:
            base[key] = value
    return base


def values_equal(left: Any, right: Any) -> bool:
    if left == right:
        return True
    return str(left) == str(right)


def find_index(values: Sequence[Any], requested: Any) -> int:
    exact = [position for position, value in enumerate(values) if value == requested]
    if len(exact) == 1:
        return exact[0]
    string_matches = [position for position, value in enumerate(values) if str(value) == str(requested)]
    if len(string_matches) == 1:
        return string_matches[0]
    if len(exact) > 1 or len(string_matches) > 1:
        raise KeyError(f"Belirsiz idx: {requested!r}")
    raise KeyError(requested)


def canonical_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    raw = json.loads(json.dumps(spec, ensure_ascii=False, default=json_default))
    defaults: dict[str, Any] = {
        "log_level": 20,
        "strict": True,
        "overwrite": False,
        "copy_inputs": True,
        "seed": 42,
        "max_jobs": 20,
        "large_run_approved": False,
    }
    # Wrong types are kept as given so that validate_spec reports them instead of coercing.
    if isinstance(raw.get("defaults"), dict):
        defaults.update(raw["defaults"])
        raw["defaults"] = defaults
    elif "defaults" not in raw:
        raw["defaults"] = defaults
    raw.setdefault("schema_version", SCHEMA_VERSION)
    raw.setdefault("study_name", "andes-study")
    jobs = raw.get("jobs", [])
    if isinstance(jobs, list):
        for position, job in enumerate(jobs, start=1):
            if not isinstance(job, dict):
                continue
            job.setdefault("id", f"job-{position}")
            job.setdefault("routine", "pflow")
            job.setdefault("case", {})
            job.setdefault("disable_existing_events", [])
            job.setdefault("pre_setup", [])
            job.setdefault("post_setup", [])
            job.setdefault("events", [])
            job.setdefault("routine_config", {})
            job.setdefault("routine_args", {})
            job.setdefault("stages", [])
            job.setdefault("outputs", {})
            job.setdefault(
                "checks",
                {"require_convergence": True, "finite": True, "criteria": []},
            )
    return raw


def validate_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return _validate_spec(spec)
    except (TypeError, AttributeError) as exc:
        # e.g. an object where an enum string is expected (unhashable in a set lookup)
        raise SpecError(f"Unexpected value type in specification: {type(exc).__name__}: {exc}") from exc


def _validate_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    normalized = canonical_spec(spec)
    issues: list[str] = []

    def issue(path: str, message: str) -> None:
        issues.append(f"{path}: {message}")

    _reject_unknown(
        normalized,
        {"schema_version", "study_name", "description", "defaults", "jobs"},
        "$",
        issue,
    )
    if normalized.get("schema_version") != SCHEMA_VERSION:
        issue("schema_version", f"must be the supported version {SCHEMA_VERSION}")
    _nonempty_string(normalized.get("study_name"), "study_name", issue)
    if "description" in normalized:
        _string(normalized.get("description"), "description", issue)

    defaults = normalized.get("defaults")
    if not isinstance(defaults, dict):
        issue("defaults", "must be a JSON object")
        defaults = {}
    else:
        _reject_unknown(
            defaults,
            {"log_level", "strict", "overwrite", "copy_inputs", "seed", "max_jobs", "large_run_approved"},
            "defaults",
            issue,
        )
        if not _is_int(defaults.get("log_level")) or int(defaults["log_level"]) not in {10, 20, 30, 40, 50}:
            issue("defaults.log_level", "must be 10, 20, 30, 40, or 50")
        if not _is_int(defaults.get("seed")):
            issue("defaults.seed", "must be an integer")
        if not _is_int(defaults.get("max_jobs")) or int(defaults.get("max_jobs", 0)) <= 0:
            issue("defaults.max_jobs", "must be a positive integer")
        for field in ("strict", "overwrite", "copy_inputs", "large_run_approved"):
            if not isinstance(defaults.get(field), bool):
                issue(f"defaults.{field}", "must be true/false")

    jobs = normalized.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        issue("jobs", "must be an array with at least one job")
        jobs = []
    elif (
        isinstance(defaults, dict)
        and _is_int(defaults.get("max_jobs"))
        and len(jobs) > int(defaults["max_jobs"])
        and not bool(defaults.get("large_run_approved", False))
    ):
        issue(
            "jobs",
            f"{len(jobs)} jobs exceed the unapproved safety limit defaults.max_jobs={defaults['max_jobs']}; "
            "if the user explicitly approved this, set defaults.large_run_approved=true",
        )

    seen_ids: set[str] = set()
    for position, job in enumerate(jobs):
        path = f"jobs[{position}]"
        if not isinstance(job, dict):
            issue(path, "must be a JSON object")
            continue
        _reject_unknown(
            job,
            {
                "id", "description", "case", "routine", "disable_existing_events",
                "pre_setup", "post_setup", "events", "routine_config", "routine_args",
                "stages", "outputs", "checks",
            },
            path,
            issue,
        )
        job_id = job.get("id")
        _nonempty_string(job_id, f"{path}.id", issue)
        if isinstance(job_id, str):
            if job_id in seen_ids:
                issue(f"{path}.id", f"duplicate job id: {job_id}")
            seen_ids.add(job_id)
        if "description" in job:
            _string(job.get("description"), f"{path}.description", issue)

        routine = str(job.get("routine", "")).lower()
        if routine not in ALLOWED_ROUTINES:
            issue(f"{path}.routine", f"allowed values: {sorted(ALLOWED_ROUTINES)}")
        else:
            job["routine"] = routine

        _validate_case(job.get("case"), f"{path}.case", issue)
        _validate_name_list(job.get("disable_existing_events"), f"{path}.disable_existing_events", issue)
        _validate_operations(job.get("pre_setup"), f"{path}.pre_setup", ALLOWED_PRE_SETUP_OPS, issue)
        _validate_operations(job.get("post_setup"), f"{path}.post_setup", ALLOWED_POST_SETUP_OPS, issue)
        _validate_events(job.get("events"), f"{path}.events", issue)
        _validate_config(job.get("routine_config"), f"{path}.routine_config", issue)
        _validate_routine_args(routine, job.get("routine_args"), f"{path}.routine_args", issue)
        _validate_stages(job.get("stages"), f"{path}.stages", issue)
        _validate_outputs(job.get("outputs"), f"{path}.outputs", issue)
        _validate_checks(job.get("checks"), f"{path}.checks", issue)
        _validate_cross(job, path, issue)

    if issues:
        raise SpecError("ANDES study specification is invalid:\n" + "\n".join(f"- {item}" for item in issues))
    return normalized


Issue = Callable[[str, str], None]


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], path: str, issue: Issue) -> None:
    for key in value:
        if key not in allowed:
            issue(f"{path}.{key}", "unknown field")


def _require(value: Mapping[str, Any], fields: Iterable[str], path: str, issue: Issue) -> None:
    for field in fields:
        if field not in value:
            issue(f"{path}.{field}", "required field")


def _string(value: Any, path: str, issue: Issue) -> None:
    if not isinstance(value, str):
        issue(path, "must be a string")


def _nonempty_string(value: Any, path: str, issue: Issue) -> None:
    if not isinstance(value, str) or not value.strip():
        issue(path, "must be a non-empty string")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _finite(value: Any, path: str, issue: Issue) -> None:
    if not _is_finite_number(value):
        issue(path, "must be a finite number")


def _positive(value: Any, path: str, issue: Issue, *, allow_zero: bool = False) -> None:
    if not _is_finite_number(value) or (float(value) < 0 if allow_zero else float(value) <= 0):
        issue(path, "must be a non-negative finite number" if allow_zero else "must be a positive finite number")


def _validate_case(value: Any, path: str, issue: Issue) -> None:
    if not isinstance(value, dict):
        issue(path, "must be a JSON object")
        return
    _reject_unknown(value, {"path", "builtin", "addfiles", "config_option", "default_config"}, path, issue)
    local = value.get("path")
    builtin = value.get("builtin")
    if bool(local) == bool(builtin):
        issue(path, "exactly one of `path` or `builtin` must be given")
    for field in ("path", "builtin"):
        if value.get(field) is not None and (not isinstance(value[field], str) or not value[field].strip()):
            issue(f"{path}.{field}", "must be a non-empty string or null")
    addfiles = value.get("addfiles", [])
    if not isinstance(addfiles, list) or any(not isinstance(item, str) or not item.strip() for item in addfiles):
        issue(f"{path}.addfiles", "must be an array of non-empty file-path strings")
    options = value.get("config_option", [])
    if not isinstance(options, list) or any(not isinstance(item, str) or "=" not in item for item in options):
        issue(f"{path}.config_option", "must be an array of `Model.option=value` strings")
    if "default_config" in value and not isinstance(value["default_config"], bool):
        issue(f"{path}.default_config", "must be true/false")


def _validate_name_list(value: Any, path: str, issue: Issue) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        issue(path, "must be an array of non-empty model names")


def _validate_operations(value: Any, path: str, allowed: set[str], issue: Issue) -> None:
    if not isinstance(value, list):
        issue(path, "must be an array")
        return
    for position, operation in enumerate(value):
        _validate_operation(operation, f"{path}[{position}]", allowed, issue)


def _validate_operation(value: Any, path: str, allowed: set[str], issue: Issue) -> None:
    if not isinstance(value, dict):
        issue(path, "must be a JSON object")
        return
    name = str(value.get("op", "")).lower()
    if name not in allowed:
        issue(f"{path}.op", f"allowed operations: {sorted(allowed)}")
        return
    value["op"] = name
    fields = {
        "set_status": {"op", "model", "idx", "value", "note"},
        "set_parameter": {"op", "model", "field", "idx", "value", "base", "note"},
        "scale_parameter": {"op", "model", "field", "factor", "base", "indices", "note"},
        "set_setpoint": {"op", "group", "idx", "name", "value", "note"},
    }
    _reject_unknown(value, fields[name], path, issue)
    if name == "set_status":
        _require(value, ("model", "idx", "value"), path, issue)
        _nonempty_string(value.get("model"), f"{path}.model", issue)
        if value.get("value") not in (0, 1, False, True):
            issue(f"{path}.value", "must be 0 or 1")
    elif name == "set_parameter":
        _require(value, ("model", "field", "idx", "value", "base"), path, issue)
        _nonempty_string(value.get("model"), f"{path}.model", issue)
        _nonempty_string(value.get("field"), f"{path}.field", issue)
        if value.get("base") not in ALLOWED_BASES:
            issue(f"{path}.base", f"must be one of {sorted(ALLOWED_BASES)}")
    elif name == "scale_parameter":
        _require(value, ("model", "field", "factor", "base"), path, issue)
        _nonempty_string(value.get("model"), f"{path}.model", issue)
        _nonempty_string(value.get("field"), f"{path}.field", issue)
        _finite(value.get("factor"), f"{path}.factor", issue)
        if value.get("base") not in ALLOWED_BASES:
            issue(f"{path}.base", f"must be one of {sorted(ALLOWED_BASES)}")
        if "indices" in value and not isinstance(value["indices"], list):
            issue(f"{path}.indices", "must be an array")
    elif name == "set_setpoint":
        _require(value, ("group", "idx", "name", "value"), path, issue)
        _nonempty_string(value.get("group"), f"{path}.group", issue)
        _nonempty_string(value.get("name"), f"{path}.name", issue)
    if "note" in value:
        _string(value.get("note"), f"{path}.note", issue)


def _validate_events(value: Any, path: str, issue: Issue) -> None:
    if not isinstance(value, list):
        issue(path, "must be an array")
        return
    fields = {
        "fault": {"type", "bus", "tf", "tc", "rf", "xf", "note"},
        "toggle": {"type", "model", "dev", "t", "note"},
        "alter": {"type", "model", "dev", "src", "t", "method", "amount", "note"},
    }
    for position, event in enumerate(value):
        event_path = f"{path}[{position}]"
        if not isinstance(event, dict):
            issue(event_path, "must be a JSON object")
            continue
        kind = str(event.get("type", "")).lower()
        if kind not in ALLOWED_EVENTS:
            issue(f"{event_path}.type", f"allowed events: {sorted(ALLOWED_EVENTS)}")
            continue
        event["type"] = kind
        _reject_unknown(event, fields[kind], event_path, issue)
        if kind == "fault":
            _require(event, ("bus", "tf", "tc"), event_path, issue)
            for field in ("tf", "tc"):
                _positive(event.get(field), f"{event_path}.{field}", issue, allow_zero=True)
            for field in ("rf", "xf"):
                if field in event:
                    _finite(event[field], f"{event_path}.{field}", issue)
            if _is_finite_number(event.get("tf")) and _is_finite_number(event.get("tc")):
                if float(event["tc"]) <= float(event["tf"]):
                    issue(f"{event_path}.tc", "must be greater than `tf`")
        elif kind == "toggle":
            _require(event, ("model", "dev", "t"), event_path, issue)
            _nonempty_string(event.get("model"), f"{event_path}.model", issue)
            _positive(event.get("t"), f"{event_path}.t", issue, allow_zero=True)
        else:
            _require(event, ("model", "dev", "src", "t", "method", "amount"), event_path, issue)
            _nonempty_string(event.get("model"), f"{event_path}.model", issue)
            _nonempty_string(event.get("src"), f"{event_path}.src", issue)
            _positive(event.get("t"), f"{event_path}.t", issue, allow_zero=True)
            _finite(event.get("amount"), f"{event_path}.amount", issue)
            if event.get("method") not in ALLOWED_ALTER_METHODS:
                issue(f"{event_path}.method", f"allowed values: {sorted(ALLOWED_ALTER_METHODS)}")
        if "note" in event:
            _string(event.get("note"), f"{event_path}.note", issue)


def _validate_config(value: Any, path: str, issue: Issue) -> None:
    if not isinstance(value, dict):
        issue(path, "must be a JSON object")
        return
    for key, item in value.items():
        if not isinstance(key, str) or not key or key.startswith("_"):
            issue(path, "config keys must be non-empty generic field names")
        if isinstance(item, float) and not math.isfinite(item):
            issue(f"{path}.{key}", "must be a finite value")


def _validate_stages(value: Any, path: str, issue: Issue) -> None:
    if not isinstance(value, list):
        issue(path, "must be an array")
        return
    previous = -math.inf
    for position, stage in enumerate(value):
        stage_path = f"{path}[{position}]"
        if not isinstance(stage, dict):
            issue(stage_path, "must be a JSON object")
            continue
        _reject_unknown(stage, {"until", "before"}, stage_path, issue)
        _require(stage, ("until",), stage_path, issue)
        _positive(stage.get("until"), f"{stage_path}.until", issue)
        if _is_finite_number(stage.get("until")):
            current = float(stage["until"])
            if current <= previous:
                issue(f"{stage_path}.until", "stage times must be strictly increasing")
            previous = current
        _validate_operations(stage.get("before", []), f"{stage_path}.before", ALLOWED_STAGE_OPS, issue)


def _validate_relative_file(value: Any, path: str, issue: Issue) -> None:
    if not isinstance(value, str) or not value.strip():
        issue(path, "must be a non-empty relative file name")
        return
    if _escapes_root(value):
        issue(path, "must be a relative path inside the output root")


def _validate_outputs(value: Any, path: str, issue: Issue) -> None:
    if not isinstance(value, dict):
        issue(path, "must be a JSON object")
        return
    _reject_unknown(value, {"tables", "timeseries", "plots", "eig_plot", "cpf_plot", "qv_plot"}, path, issue)
    for collection in ("tables", "timeseries", "plots"):
        items = value.get(collection, [])
        if not isinstance(items, list):
            issue(f"{path}.{collection}", "must be an array")
            continue
        for position, item in enumerate(items):
            item_path = f"{path}.{collection}[{position}]"
            if not isinstance(item, dict):
                issue(item_path, "must be a JSON object")
                continue
            if collection == "tables":
                _reject_unknown(item, {"model", "fields", "indices", "source", "file"}, item_path, issue)
                _require(item, ("model", "fields", "file"), item_path, issue)
                _nonempty_string(item.get("model"), f"{item_path}.model", issue)
                fields = item.get("fields")
                if not isinstance(fields, list) or not fields or any(not isinstance(field, str) or not field for field in fields):
                    issue(f"{item_path}.fields", "must contain at least one valid field name")
                if item.get("source", "v") not in {"v", "vin"}:
                    issue(f"{item_path}.source", "must be `v` or `vin`")
            else:
                allowed = {"model", "variable", "indices", "factor", "offset", "file"}
                if collection == "plots":
                    allowed |= {"xlabel", "ylabel", "title", "grid", "legend", "dpi", "xlim", "ylim"}
                _reject_unknown(item, allowed, item_path, issue)
                _require(item, ("model", "variable", "file"), item_path, issue)
                _nonempty_string(item.get("model"), f"{item_path}.model", issue)
                _nonempty_string(item.get("variable"), f"{item_path}.variable", issue)
                for field in ("factor", "offset"):
                    if field in item:
                        _finite(item[field], f"{item_path}.{field}", issue)
                if collection == "plots":
                    for field in ("xlabel", "ylabel", "title"):
                        if field in item:
                            _string(item[field], f"{item_path}.{field}", issue)
                    for field in ("grid", "legend"):
                        if field in item and not isinstance(item[field], bool):
                            issue(f"{item_path}.{field}", "must be true/false")
                    if "dpi" in item and (not _is_int(item["dpi"]) or int(item["dpi"]) < 72):
                        issue(f"{item_path}.dpi", "must be an integer of at least 72")
                    for field in ("xlim", "ylim"):
                        if field in item and (
                            not isinstance(item[field], list)
                            or len(item[field]) != 2
                            or not all(_is_finite_number(number) for number in item[field])
                        ):
                            issue(f"{item_path}.{field}", "must contain two finite numbers")
            if "indices" in item and not isinstance(item["indices"], list):
                issue(f"{item_path}.indices", "must be an array")
            _validate_relative_file(item.get("file"), f"{item_path}.file", issue)

    if "eig_plot" in value and value["eig_plot"] is not None:
        _validate_relative_file(value["eig_plot"], f"{path}.eig_plot", issue)
    if "cpf_plot" in value and value["cpf_plot"] is not None:
        cpf = value["cpf_plot"]
        if not isinstance(cpf, dict):
            issue(f"{path}.cpf_plot", "must be a JSON object")
        else:
            _reject_unknown(cpf, {"bus_idx", "file"}, f"{path}.cpf_plot", issue)
            _require(cpf, ("bus_idx", "file"), f"{path}.cpf_plot", issue)
            _validate_relative_file(cpf.get("file"), f"{path}.cpf_plot.file", issue)
    if "qv_plot" in value and value["qv_plot"] is not None:
        _validate_relative_file(value["qv_plot"], f"{path}.qv_plot", issue)


def _validate_checks(value: Any, path: str, issue: Issue) -> None:
    if not isinstance(value, dict):
        issue(path, "must be a JSON object")
        return
    _reject_unknown(value, {"require_convergence", "finite", "criteria"}, path, issue)
    for field in ("require_convergence", "finite"):
        if field in value and not isinstance(value[field], bool):
            issue(f"{path}.{field}", "must be true/false")
    criteria = value.get("criteria", [])
    if not isinstance(criteria, list):
        issue(f"{path}.criteria", "must be an array")
        return
    for position, criterion in enumerate(criteria):
        cpath = f"{path}.criteria[{position}]"
        if not isinstance(criterion, dict):
            issue(cpath, "must be a JSON object")
            continue
        _reject_unknown(
            criterion,
            {"name", "model", "variable", "indices", "source", "aggregate", "operator", "threshold", "bounds", "atol", "basis"},
            cpath,
            issue,
        )
        _require(criterion, ("name", "model", "variable", "source", "aggregate", "operator", "basis"), cpath, issue)
        for field in ("name", "model", "variable"):
            _nonempty_string(criterion.get(field), f"{cpath}.{field}", issue)
        if criterion.get("source") not in {"timeseries", "current"}:
            issue(f"{cpath}.source", "must be `timeseries` or `current`")
        if criterion.get("aggregate") not in ALLOWED_AGGREGATES:
            issue(f"{cpath}.aggregate", f"allowed values: {sorted(ALLOWED_AGGREGATES)}")
        operator = criterion.get("operator")
        if operator not in ALLOWED_OPERATORS:
            issue(f"{cpath}.operator", f"allowed values: {sorted(ALLOWED_OPERATORS)}")
        elif operator in {"between", "outside"}:
            bounds = criterion.get("bounds")
            if not isinstance(bounds, list) or len(bounds) != 2 or not all(_is_finite_number(item) for item in bounds):
                issue(f"{cpath}.bounds", "must contain two finite numbers")
            elif float(bounds[0]) > float(bounds[1]):
                issue(f"{cpath}.bounds", "the lower bound cannot exceed the upper bound")
        else:
            _finite(criterion.get("threshold"), f"{cpath}.threshold", issue)
        if "indices" in criterion and not isinstance(criterion["indices"], list):
            issue(f"{cpath}.indices", "must be an array")
        if "atol" in criterion:
            _positive(criterion["atol"], f"{cpath}.atol", issue, allow_zero=True)
        if "basis" in criterion:
            _nonempty_string(criterion["basis"], f"{cpath}.basis", issue)


def _validate_routine_args(routine: str, value: Any, path: str, issue: Issue) -> None:
    if not isinstance(value, dict):
        issue(path, "must be a JSON object")
        return
    if routine in {"inspect", "pflow", "tds"}:
        _reject_unknown(value, set(), path, issue)
        return

    if routine == "eig":
        _reject_unknown(value, {"sweep"}, path, issue)
        sweep = value.get("sweep")
        if sweep is None:
            return
        if not isinstance(sweep, dict):
            issue(f"{path}.sweep", "must be a JSON object")
            return
        spath = f"{path}.sweep"
        _reject_unknown(sweep, {"model", "parameter", "idx", "values", "eig_indices", "plot_file"}, spath, issue)
        _require(sweep, ("model", "parameter", "idx", "values"), spath, issue)
        _nonempty_string(sweep.get("model"), f"{spath}.model", issue)
        _nonempty_string(sweep.get("parameter"), f"{spath}.parameter", issue)
        values = sweep.get("values")
        if not isinstance(values, list) or len(values) < 2 or not all(_is_finite_number(item) for item in values):
            issue(f"{spath}.values", "must contain at least two finite numbers")
        eig_indices = sweep.get("eig_indices")
        if eig_indices is not None and (
            not isinstance(eig_indices, list)
            or not eig_indices
            or not all(_is_int(item) and item >= 0 for item in eig_indices)
        ):
            issue(f"{spath}.eig_indices", "must be an array of non-negative integers")
        if "plot_file" in sweep:
            _validate_relative_file(sweep["plot_file"], f"{spath}.plot_file", issue)
            if not eig_indices:
                issue(f"{spath}.eig_indices", "is required for a root-locus plot")
        return

    if routine == "se":
        _reject_unknown(value, {"algorithm", "measurements", "seed", "gross_errors", "chi_squared", "confidence"}, path, issue)
        algorithm = str(value.get("algorithm", "wls")).lower()
        if algorithm not in {"wls", "lav"}:
            issue(f"{path}.algorithm", "must be `wls` or `lav`")
        if "seed" in value and not _is_int(value["seed"]):
            issue(f"{path}.seed", "must be an integer")
        if "chi_squared" in value and not isinstance(value["chi_squared"], bool):
            issue(f"{path}.chi_squared", "must be true/false")
        if algorithm == "lav" and bool(value.get("chi_squared", False)):
            issue(f"{path}.chi_squared", "the chi-square test applies only to WLS")
        if "confidence" in value:
            confidence = value["confidence"]
            if not _is_finite_number(confidence) or not 0 < float(confidence) < 1:
                issue(f"{path}.confidence", "must be between 0 and 1")

        measurements = value.get("measurements", [])
        if not isinstance(measurements, list):
            issue(f"{path}.measurements", "must be an array")
        else:
            measurement_fields = {
                "bus_voltage": {"type", "bus_idx", "sigma", "note"},
                "bus_angle": {"type", "bus_idx", "sigma", "note"},
                "bus_injection": {"type", "bus_idx", "sigma_p", "sigma_q", "note"},
                "line_flow": {"type", "line_idx", "sigma_p", "sigma_q", "note"},
            }
            for position, measurement in enumerate(measurements):
                mpath = f"{path}.measurements[{position}]"
                if not isinstance(measurement, dict):
                    issue(mpath, "must be a JSON object")
                    continue
                kind = measurement.get("type")
                if kind not in ALLOWED_MEASUREMENTS:
                    issue(f"{mpath}.type", f"allowed values: {sorted(ALLOWED_MEASUREMENTS)}")
                    continue
                _reject_unknown(measurement, measurement_fields[str(kind)], mpath, issue)
                if kind in {"bus_voltage", "bus_angle"}:
                    _require(measurement, ("sigma",), mpath, issue)
                    _positive(measurement.get("sigma"), f"{mpath}.sigma", issue)
                    _optional_list(measurement, "bus_idx", mpath, issue)
                elif kind in {"bus_injection", "line_flow"}:
                    _require(measurement, ("sigma_p", "sigma_q"), mpath, issue)
                    _positive(measurement.get("sigma_p"), f"{mpath}.sigma_p", issue)
                    _positive(measurement.get("sigma_q"), f"{mpath}.sigma_q", issue)
                    _optional_list(measurement, "bus_idx" if kind == "bus_injection" else "line_idx", mpath, issue)
                if "note" in measurement:
                    _string(measurement["note"], f"{mpath}.note", issue)

        errors = value.get("gross_errors", [])
        if errors and not measurements:
            issue(f"{path}.gross_errors", "adding gross errors requires an explicit measurement set")
        if not isinstance(errors, list):
            issue(f"{path}.gross_errors", "must be an array")
        else:
            for position, error in enumerate(errors):
                epath = f"{path}.gross_errors[{position}]"
                if not isinstance(error, dict):
                    issue(epath, "must be a JSON object")
                    continue
                _reject_unknown(error, {"measurement_index", "sigma_multiplier", "note"}, epath, issue)
                _require(error, ("measurement_index", "sigma_multiplier"), epath, issue)
                if not _is_int(error.get("measurement_index")) or int(error.get("measurement_index", -1)) < 0:
                    issue(f"{epath}.measurement_index", "must be a non-negative integer")
                _finite(error.get("sigma_multiplier"), f"{epath}.sigma_multiplier", issue)
        return

    if routine == "cpf":
        _reject_unknown(value, {"qv", "load_scale", "p0_target", "q0_target", "pg_target"}, path, issue)
        qv = value.get("qv")
        if qv is not None:
            if not isinstance(qv, dict):
                issue(f"{path}.qv", "must be a JSON object")
            else:
                qpath = f"{path}.qv"
                _reject_unknown(qv, {"bus_idx", "q_range"}, qpath, issue)
                _require(qv, ("bus_idx", "q_range"), qpath, issue)
                _positive(qv.get("q_range"), f"{qpath}.q_range", issue)
            conflicts = [field for field in ("load_scale", "p0_target", "q0_target", "pg_target") if field in value]
            if conflicts:
                issue(path, f"fields that cannot be used with `qv`: {conflicts}")
        if "load_scale" in value:
            _positive(value["load_scale"], f"{path}.load_scale", issue)
        for field in ("p0_target", "q0_target", "pg_target"):
            if field in value:
                targets = value[field]
                if not isinstance(targets, list) or not targets or not all(_is_finite_number(item) for item in targets):
                    issue(f"{path}.{field}", "must be an array containing at least one finite number")
        if qv is None and not any(field in value for field in ("load_scale", "p0_target", "q0_target", "pg_target")):
            issue(path, "CPF requires `load_scale`, target arrays, or `qv`")


def _optional_list(value: Mapping[str, Any], field: str, path: str, issue: Issue) -> None:
    if field in value and not isinstance(value[field], list):
        issue(f"{path}.{field}", "must be an array")


def _validate_cross(job: Mapping[str, Any], path: str, issue: Issue) -> None:
    routine = job.get("routine")
    events = job.get("events", [])
    stages = job.get("stages", [])
    config = job.get("routine_config", {})
    outputs = job.get("outputs", {})
    args = job.get("routine_args", {})

    if (events or stages) and routine != "tds":
        issue(path, "`events` and `stages` are only available for `tds`")
    if routine == "tds":
        final_time: float | None = None
        if isinstance(stages, list) and stages:
            last = stages[-1]
            if isinstance(last, dict) and _is_finite_number(last.get("until")):
                final_time = float(last["until"])
        elif isinstance(config, dict) and _is_finite_number(config.get("tf")):
            final_time = float(config["tf"])
        if final_time is None:
            issue(f"{path}.routine_config.tf", "TDS requires `tf` or at least one `stages[].until`")
        else:
            event_times: list[float] = []
            if isinstance(events, list):
                for event in events:
                    if isinstance(event, dict):
                        for field in ("t", "tf", "tc"):
                            if _is_finite_number(event.get(field)):
                                event_times.append(float(event[field]))
            if event_times and final_time < max(event_times):
                issue(path, "the TDS final time must cover all event times")

    if isinstance(outputs, dict):
        if (outputs.get("timeseries") or outputs.get("plots")) and routine != "tds":
            issue(f"{path}.outputs", "time series and TDS plots are only valid for `tds`")
        if outputs.get("eig_plot") and routine != "eig":
            issue(f"{path}.outputs.eig_plot", "is only valid for `eig`")
        if (outputs.get("cpf_plot") or outputs.get("qv_plot")) and routine != "cpf":
            issue(f"{path}.outputs", "CPF/QV plots are only valid for `cpf`")
        if outputs.get("qv_plot") and not (isinstance(args, dict) and args.get("qv")):
            issue(f"{path}.outputs.qv_plot", "cannot be used without `routine_args.qv`")

    checks = job.get("checks", {})
    if isinstance(checks, dict):
        for position, criterion in enumerate(checks.get("criteria", []) if isinstance(checks.get("criteria", []), list) else []):
            if isinstance(criterion, dict) and criterion.get("source") == "timeseries" and routine != "tds":
                issue(f"{path}.checks.criteria[{position}].source", "a time-series criterion is only valid for TDS")
