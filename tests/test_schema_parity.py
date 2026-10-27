"""Parity tests between ``schemas/andes-study.schema.json`` and ``validate_spec``.

The authoritative validator is ``scripts/spec_core.py::validate_spec``.  Every
mutation below is a small patch applied to a fresh copy of an example spec.
``code`` and ``schema`` are the expected verdicts (True = accepted).  They must
agree except for entries marked ``code_only``: rules that JSON Schema cannot
express (cross-field comparisons, uniqueness, run-size limits) or Python-only
checks (true ``int`` vs integer-valued float).  Those are documented in the
schema's top-level ``$comment`` and are asserted explicitly in the other
direction (schema accepts, spec_core rejects).
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from spec_core import SpecError, validate_spec

try:  # jsonschema is an optional developer dependency.
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised in environments without the extra
    Draft202012Validator = None

EXAMPLES = ROOT / "examples"
SCHEMA_PATH = ROOT / "schemas" / "andes-study.schema.json"

DELETE = object()


def load_example(name: str) -> dict:
    with (EXAMPLES / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def patch(spec: dict, path: tuple, value=DELETE) -> None:
    """Patch a nested value; ``DELETE`` removes the key instead of setting it."""
    target = spec
    for key in path[:-1]:
        target = target[key]
    if value is DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value


def append(spec: dict, path: tuple, value) -> None:
    target = spec
    for key in path:
        target = target[key]
    target.append(value)


def code_accepts(spec: dict) -> bool:
    try:
        validate_spec(spec)
    except SpecError:
        return False
    return True


# ---------------------------------------------------------------------------
# Mutation table
# ---------------------------------------------------------------------------
# Each entry: label, source example, mutator, expected code verdict, expected
# schema verdict, tags used by the coverage test, and an optional code_only
# explanation for rules that JSON Schema cannot express.

PFLOW = "pflow-ieee14.json"
KUNDUR = "kundur-fault.json"
LINE = "line-trip-reclose.json"
MULTI = "multistage-setpoint.json"
EIG = "eigenvalue-root-locus.json"
SE = "state-estimation.json"
CPF = "cpf.json"

MUTATIONS = [
    # ---- required / defaulted top-level and job fields -------------------
    {
        "label": "top level may omit defaulted schema_version and study_name",
        "example": PFLOW,
        "mutate": lambda s: (patch(s, ("schema_version",)), patch(s, ("study_name",))),
        "code": True,
        "schema": True,
        "tags": ("required_fields",),
    },
    {
        "label": "job id is optional (canonical_spec assigns job-N)",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "id")),
        "code": True,
        "schema": True,
        "tags": ("required_fields",),
    },
    {
        "label": "job routine is optional (canonical_spec assigns pflow)",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine")),
        "code": True,
        "schema": True,
        "tags": ("required_fields",),
    },
    {
        "label": "omitted routine behaves like pflow for events",
        "example": PFLOW,
        "mutate": lambda s: (
            patch(s, ("jobs", 0, "routine")),
            patch(s, ("jobs", 0, "events"), [{"type": "fault", "bus": 5, "tf": 1.0, "tc": 1.1}]),
        ),
        "code": False,
        "schema": False,
        "tags": ("required_fields", "events"),
    },
    {
        "label": "omitted routine behaves like pflow for routine_args",
        "example": PFLOW,
        "mutate": lambda s: (
            patch(s, ("jobs", 0, "routine")),
            patch(s, ("jobs", 0, "routine_args"), {"unexpected": 1}),
        ),
        "code": False,
        "schema": False,
        "tags": ("required_fields",),
    },
    {
        "label": "job case is effectively required",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "case")),
        "code": False,
        "schema": False,
        "tags": ("required_fields",),
    },
    {
        "label": "job id must contain a non-space character",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "id"), "   "),
        "code": False,
        "schema": False,
        "tags": ("required_fields",),
    },
    {
        "label": "duplicate job ids are rejected by code only",
        "example": PFLOW,
        "mutate": lambda s: s["jobs"].append(copy.deepcopy(s["jobs"][0])),
        "code": False,
        "schema": True,
        "code_only": "job ids must be unique",
        "tags": ("required_fields",),
    },
    {
        "label": "unknown job field is rejected",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "surprise"), 1),
        "code": False,
        "schema": False,
        "tags": ("required_fields",),
    },
    {
        "label": "unknown top-level field is rejected",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("surprise",), 1),
        "code": False,
        "schema": False,
        "tags": ("required_fields",),
    },
    # ---- case -------------------------------------------------------------
    {
        "label": "case accepts a string containing '=' as config_option",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "case", "config_option"), ["max_iter=12"]),
        "code": True,
        "schema": True,
        "tags": ("config_option", "case"),
    },
    {
        "label": "case config_option without '=' is rejected",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "case", "config_option"), ["max_iter"]),
        "code": False,
        "schema": False,
        "tags": ("config_option", "case"),
    },
    {
        "label": "case with both path and builtin is rejected",
        "example": PFLOW,
        "mutate": lambda s: patch(
            s, ("jobs", 0, "case"), {"path": "case.json", "builtin": "ieee14/ieee14.json"}
        ),
        "code": False,
        "schema": False,
        "tags": ("case",),
    },
    {
        "label": "case with neither path nor builtin is rejected",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "case"), {}),
        "code": False,
        "schema": False,
        "tags": ("case",),
    },
    {
        "label": "case allows an explicit null beside the active source",
        "example": PFLOW,
        "mutate": lambda s: patch(
            s, ("jobs", 0, "case"), {"path": None, "builtin": "ieee14/ieee14.json"}
        ),
        "code": True,
        "schema": True,
        "tags": ("case",),
    },
    {
        "label": "case path must contain a non-space character",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "case"), {"path": "   "}),
        "code": False,
        "schema": False,
        "tags": ("case",),
    },
    # ---- operations -------------------------------------------------------
    {
        "label": "pre_setup set_status is accepted",
        "example": LINE,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "pre_setup"),
            [{"op": "set_status", "model": "Line", "idx": "Line_5", "value": 1}],
        ),
        "code": True,
        "schema": True,
        "tags": ("ops",),
    },
    {
        "label": "set_status may not carry field",
        "example": LINE,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "pre_setup"),
            [{"op": "set_status", "model": "Line", "idx": "Line_5", "value": 1, "field": "status"}],
        ),
        "code": False,
        "schema": False,
        "tags": ("ops",),
    },
    {
        "label": "set_status value must be 0/1",
        "example": LINE,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "pre_setup"),
            [{"op": "set_status", "model": "Line", "idx": "Line_5", "value": 2}],
        ),
        "code": False,
        "schema": False,
        "tags": ("ops",),
    },
    {
        "label": "post_setup scale_parameter with indices is accepted",
        "example": PFLOW,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "post_setup"),
            [
                {
                    "op": "scale_parameter",
                    "model": "Load",
                    "field": "p0",
                    "factor": 1.1,
                    "base": "system",
                    "indices": [1, 2],
                }
            ],
        ),
        "code": True,
        "schema": True,
        "tags": ("ops", "base_enum"),
    },
    {
        "label": "set_parameter requires base",
        "example": PFLOW,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "post_setup"),
            [{"op": "set_parameter", "model": "GENROU", "field": "M", "idx": 1, "value": 10}],
        ),
        "code": False,
        "schema": False,
        "tags": ("ops",),
    },
    {
        "label": "set_parameter base must be device or system",
        "example": PFLOW,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "post_setup"),
            [
                {
                    "op": "set_parameter",
                    "model": "GENROU",
                    "field": "M",
                    "idx": 1,
                    "value": 10,
                    "base": "pu",
                }
            ],
        ),
        "code": False,
        "schema": False,
        "tags": ("base_enum", "ops"),
    },
    {
        "label": "set_parameter with device base is accepted",
        "example": PFLOW,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "post_setup"),
            [
                {
                    "op": "set_parameter",
                    "model": "GENROU",
                    "field": "M",
                    "idx": 1,
                    "value": 10,
                    "base": "device",
                }
            ],
        ),
        "code": True,
        "schema": True,
        "tags": ("base_enum",),
    },
    {
        "label": "pre_setup may not use set_parameter",
        "example": KUNDUR,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "pre_setup"),
            [
                {
                    "op": "set_parameter",
                    "model": "GENROU",
                    "field": "M",
                    "idx": 1,
                    "value": 10,
                    "base": "device",
                }
            ],
        ),
        "code": False,
        "schema": False,
        "tags": ("ops",),
    },
    {
        "label": "stage before accepts set_parameter",
        "example": MULTI,
        "mutate": lambda s: append(
            s,
            ("jobs", 0, "stages", 1, "before"),
            {"op": "set_parameter", "model": "GENROU", "field": "M", "idx": 1, "value": 10, "base": "device"},
        ),
        "code": True,
        "schema": True,
        "tags": ("stages", "ops"),
    },
    {
        "label": "stage before may not use set_status",
        "example": MULTI,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "stages", 0, "before"),
            [{"op": "set_status", "model": "Line", "idx": "Line_5", "value": 1}],
        ),
        "code": False,
        "schema": False,
        "tags": ("stages", "ops"),
    },
    # ---- events -----------------------------------------------------------
    {
        "label": "toggle event at a later time is accepted",
        "example": LINE,
        "mutate": lambda s: patch(s, ("jobs", 0, "events", 0, "t"), 2.0),
        "code": True,
        "schema": True,
        "tags": ("events",),
    },
    {
        "label": "toggle event may not carry bus",
        "example": LINE,
        "mutate": lambda s: patch(s, ("jobs", 0, "events", 0, "bus"), 5),
        "code": False,
        "schema": False,
        "tags": ("events",),
    },
    {
        "label": "toggle event time must be non-negative",
        "example": LINE,
        "mutate": lambda s: patch(s, ("jobs", 0, "events", 0, "t"), -1.0),
        "code": False,
        "schema": False,
        "tags": ("events",),
    },
    {
        "label": "fault event may not carry dev",
        "example": KUNDUR,
        "mutate": lambda s: patch(s, ("jobs", 0, "events", 0, "dev"), "Line_5"),
        "code": False,
        "schema": False,
        "tags": ("events",),
    },
    {
        "label": "fault clearing time must be greater than fault time (code only)",
        "example": KUNDUR,
        "mutate": lambda s: patch(s, ("jobs", 0, "events", 0, "tc"), 1.0),
        "code": False,
        "schema": True,
        "code_only": "fault events require tc > tf",
        "tags": ("events", "tds_time"),
    },
    {
        "label": "TDS final time must cover every event (code only)",
        "example": KUNDUR,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_config", "tf"), 1.05),
        "code": False,
        "schema": True,
        "code_only": "TDS final time >= every event time",
        "tags": ("events", "tds_time"),
    },
    {
        "label": "alter method must be a known operator",
        "example": LINE,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "events"),
            [{"type": "alter", "model": "Load", "dev": 1, "src": "p0", "t": 1.0, "method": "^", "amount": 0.1}],
        ),
        "code": False,
        "schema": False,
        "tags": ("alter_method",),
    },
    {
        "label": "alter method '*' is accepted",
        "example": LINE,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "events"),
            [{"type": "alter", "model": "Load", "dev": 1, "src": "p0", "t": 1.0, "method": "*", "amount": 0.1}],
        ),
        "code": True,
        "schema": True,
        "tags": ("alter_method",),
    },
    {
        "label": "unknown event type is rejected",
        "example": KUNDUR,
        "mutate": lambda s: patch(s, ("jobs", 0, "events", 0, "type"), "breaker"),
        "code": False,
        "schema": False,
        "tags": ("events",),
    },
    {
        "label": "events are rejected on a non-TDS routine",
        "example": PFLOW,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "events"),
            [{"type": "fault", "bus": 5, "tf": 1.0, "tc": 1.1}],
        ),
        "code": False,
        "schema": False,
        "tags": ("events",),
    },
    {
        "label": "TDS requires tf or a non-empty stages list",
        "example": KUNDUR,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_config", "tf")),
        "code": False,
        "schema": False,
        "tags": ("tds_time",),
    },
    {
        "label": "TDS tf must be numeric",
        "example": KUNDUR,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_config", "tf"), "5"),
        "code": False,
        "schema": False,
        "tags": ("tds_time",),
    },
    # ---- state-estimation measurements -----------------------------------
    {
        "label": "bus_voltage may carry an optional bus_idx list",
        "example": SE,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args", "measurements", 0, "bus_idx"), [1, 2]),
        "code": True,
        "schema": True,
        "tags": ("measurements",),
    },
    {
        "label": "bus_voltage may not carry line_idx",
        "example": SE,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args", "measurements", 0, "line_idx"), [1]),
        "code": False,
        "schema": False,
        "tags": ("measurements",),
    },
    {
        "label": "line_flow may not carry bus_idx",
        "example": SE,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "routine_args", "measurements", 0),
            {"type": "line_flow", "bus_idx": [1], "sigma_p": 0.1, "sigma_q": 0.1},
        ),
        "code": False,
        "schema": False,
        "tags": ("measurements",),
    },
    {
        "label": "line_flow with line_idx is accepted",
        "example": SE,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "routine_args", "measurements", 0),
            {"type": "line_flow", "line_idx": [1], "sigma_p": 0.1, "sigma_q": 0.1},
        ),
        "code": True,
        "schema": True,
        "tags": ("measurements",),
    },
    {
        "label": "bus_injection requires both sigma_p and sigma_q",
        "example": SE,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "routine_args", "measurements", 0),
            {"type": "bus_injection", "sigma_p": 0.1},
        ),
        "code": False,
        "schema": False,
        "tags": ("measurements",),
    },
    {
        "label": "LAV rejects chi_squared",
        "example": SE,
        "mutate": lambda s: patch(s, ("jobs", 1, "routine_args", "chi_squared"), True),
        "code": False,
        "schema": False,
        "tags": ("measurements",),
    },
    {
        "label": "SE defaults to WLS when algorithm is omitted",
        "example": SE,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args", "algorithm")),
        "code": True,
        "schema": True,
        "tags": ("measurements",),
    },
    {
        "label": "gross_errors require an explicit measurement set",
        "example": SE,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args", "measurements")),
        "code": False,
        "schema": False,
        "tags": ("measurements",),
    },
    {
        "label": "confidence must stay between 0 and 1",
        "example": SE,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args", "confidence"), 1.5),
        "code": False,
        "schema": False,
        "tags": ("measurements",),
    },
    {
        "label": "measurement sigma must be positive",
        "example": SE,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args", "measurements", 0, "sigma"), 0),
        "code": False,
        "schema": False,
        "tags": ("measurements",),
    },
    {
        "label": "gross_errors note is not type-checked",
        "example": SE,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args", "gross_errors", 0, "note"), {"source": "x"}),
        "code": True,
        "schema": True,
        "tags": ("measurements",),
    },
    # ---- eigenvalue sweep -------------------------------------------------
    {
        "label": "eig plot_file requires eig_indices",
        "example": EIG,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args", "sweep", "eig_indices")),
        "code": False,
        "schema": False,
        "tags": ("eig_plot",),
    },
    {
        "label": "eig plot_file with eig_indices is accepted",
        "example": EIG,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args", "sweep", "eig_indices"), [4, 7]),
        "code": True,
        "schema": True,
        "tags": ("eig_plot",),
    },
    {
        "label": "eig sweep without plot_file needs no eig_indices",
        "example": EIG,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args", "sweep", "plot_file")),
        "code": True,
        "schema": True,
        "tags": ("eig_plot",),
    },
    {
        "label": "eig sweep values need at least two samples",
        "example": EIG,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args", "sweep", "values"), [20]),
        "code": False,
        "schema": False,
        "tags": ("eig_plot",),
    },
    {
        "label": "eig_indices may not be an empty list",
        "example": EIG,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args", "sweep", "eig_indices"), []),
        "code": False,
        "schema": False,
        "tags": ("eig_plot",),
    },
    {
        "label": "eig sweep may be null (treated as absent)",
        "example": EIG,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args", "sweep"), None),
        "code": True,
        "schema": True,
        "tags": ("eig_plot",),
    },
    # ---- CPF / QV ---------------------------------------------------------
    {
        "label": "qv may not be combined with load_scale",
        "example": CPF,
        "mutate": lambda s: patch(s, ("jobs", 1, "routine_args", "load_scale"), 2.0),
        "code": False,
        "schema": False,
        "tags": ("cpf_qv",),
    },
    {
        "label": "qv may not be combined with p0_target",
        "example": CPF,
        "mutate": lambda s: patch(s, ("jobs", 1, "routine_args", "p0_target"), [1.0]),
        "code": False,
        "schema": False,
        "tags": ("cpf_qv",),
    },
    {
        "label": "qv job with a different q_range is accepted",
        "example": CPF,
        "mutate": lambda s: patch(s, ("jobs", 1, "routine_args", "qv", "q_range"), 4.0),
        "code": True,
        "schema": True,
        "tags": ("cpf_qv",),
    },
    {
        "label": "null qv beside load_scale means 'no QV mode'",
        "example": CPF,
        "mutate": lambda s: (
            patch(s, ("jobs", 1, "routine_args"), {"qv": None, "load_scale": 2.0}),
            patch(s, ("jobs", 1, "outputs", "qv_plot")),
        ),
        "code": True,
        "schema": True,
        "tags": ("cpf_qv",),
    },
    {
        "label": "qv_plot cannot rely on a null qv",
        "example": CPF,
        "mutate": lambda s: patch(s, ("jobs", 1, "routine_args"), {"qv": None, "load_scale": 2.0}),
        "code": False,
        "schema": False,
        "tags": ("outputs", "cpf_qv"),
    },
    {
        "label": "cpf needs at least one target",
        "example": CPF,
        "mutate": lambda s: patch(s, ("jobs", 1, "routine_args"), {}),
        "code": False,
        "schema": False,
        "tags": ("cpf_qv",),
    },
    {
        "label": "cpf routine_args may not be omitted",
        "example": CPF,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_args")),
        "code": False,
        "schema": False,
        "tags": ("cpf_qv",),
    },
    {
        "label": "qv q_range must be positive",
        "example": CPF,
        "mutate": lambda s: patch(s, ("jobs", 1, "routine_args", "qv", "q_range"), -1.0),
        "code": False,
        "schema": False,
        "tags": ("cpf_qv",),
    },
    # ---- routine_config ---------------------------------------------------
    {
        "label": "routine_config accepts nested values and non-identifier keys",
        "example": KUNDUR,
        "mutate": lambda s: patch(
            s, ("jobs", 0, "routine_config", "solver name"), {"type": "x", "tolerance": 1e-06}
        ),
        "code": True,
        "schema": True,
        "tags": ("routine_config",),
    },
    {
        "label": "routine_config accepts lists, objects and null values",
        "example": PFLOW,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "routine_config"),
            {"newton max iter": [10, 20], "cfg": {"a": 1}, "flag": None},
        ),
        "code": True,
        "schema": True,
        "tags": ("routine_config",),
    },
    {
        "label": "routine_config rejects underscore-prefixed keys",
        "example": KUNDUR,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_config", "_private"), 1),
        "code": False,
        "schema": False,
        "tags": ("routine_config",),
    },
    {
        "label": "routine_config rejects empty keys",
        "example": KUNDUR,
        "mutate": lambda s: patch(s, ("jobs", 0, "routine_config", ""), 1),
        "code": False,
        "schema": False,
        "tags": ("routine_config",),
    },
    # ---- outputs ----------------------------------------------------------
    {
        "label": "timeseries is rejected on pflow",
        "example": PFLOW,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "outputs", "timeseries"),
            [{"model": "Bus", "variable": "v", "file": "bus.csv"}],
        ),
        "code": False,
        "schema": False,
        "tags": ("outputs",),
    },
    {
        "label": "plots are rejected on se",
        "example": SE,
        "mutate": lambda s: patch(
            s,
            ("jobs", 0, "outputs"),
            {"plots": [{"model": "Bus", "variable": "v", "file": "bus.png"}]},
        ),
        "code": False,
        "schema": False,
        "tags": ("outputs",),
    },
    {
        "label": "eig_plot is rejected on tds",
        "example": KUNDUR,
        "mutate": lambda s: patch(s, ("jobs", 0, "outputs", "eig_plot"), "s-plane.png"),
        "code": False,
        "schema": False,
        "tags": ("outputs",),
    },
    {
        "label": "cpf_plot is rejected on eig",
        "example": EIG,
        "mutate": lambda s: patch(
            s, ("jobs", 0, "outputs", "cpf_plot"), {"bus_idx": 1, "file": "pv.png"}
        ),
        "code": False,
        "schema": False,
        "tags": ("outputs",),
    },
    {
        "label": "qv_plot requires routine_args.qv",
        "example": CPF,
        "mutate": lambda s: patch(s, ("jobs", 0, "outputs", "qv_plot"), "qv.png"),
        "code": False,
        "schema": False,
        "tags": ("outputs",),
    },
    {
        "label": "eig_plot on eig is accepted",
        "example": EIG,
        "mutate": lambda s: patch(s, ("jobs", 0, "outputs", "eig_plot"), "s-plane-2.png"),
        "code": True,
        "schema": True,
        "tags": ("outputs",),
    },
    {
        "label": "timeseries on tds is accepted",
        "example": LINE,
        "mutate": lambda s: append(
            s,
            ("jobs", 0, "outputs", "timeseries"),
            {"model": "Bus", "variable": "v", "file": "bus.csv"},
        ),
        "code": True,
        "schema": True,
        "tags": ("outputs",),
    },
    {
        "label": "null eig_plot is allowed on any routine",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "outputs", "eig_plot"), None),
        "code": True,
        "schema": True,
        "tags": ("outputs",),
    },
    {
        "label": "null qv_plot is allowed on any routine",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "outputs", "qv_plot"), None),
        "code": True,
        "schema": True,
        "tags": ("outputs",),
    },
    # ---- safe relative output names --------------------------------------
    {
        "label": "absolute windows output path is rejected",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "outputs", "tables", 0, "file"), "C:/tmp/bus.csv"),
        "code": False,
        "schema": False,
        "tags": ("relative_file",),
    },
    {
        "label": "parent traversal output path is rejected",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "outputs", "tables", 0, "file"), "../bus.csv"),
        "code": False,
        "schema": False,
        "tags": ("relative_file",),
    },
    {
        "label": "UNC output path is rejected",
        "example": KUNDUR,
        "mutate": lambda s: patch(
            s, ("jobs", 0, "outputs", "timeseries", 0, "file"), r"\\server\share\omega.csv"
        ),
        "code": False,
        "schema": False,
        "tags": ("relative_file",),
    },
    {
        "label": "whitespace-only output name is rejected",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "outputs", "tables", 0, "file"), "   "),
        "code": False,
        "schema": False,
        "tags": ("relative_file",),
    },
    {
        "label": "non-string output name is rejected",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "outputs", "tables", 0, "file"), 5),
        "code": False,
        "schema": False,
        "tags": ("relative_file",),
    },
    {
        "label": "nested relative output path is accepted",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "outputs", "tables", 0, "file"), "csv/bus.csv"),
        "code": True,
        "schema": True,
        "tags": ("relative_file",),
    },
    # ---- defaults ---------------------------------------------------------
    {
        "label": "defaults.max_jobs must be positive",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("defaults", "max_jobs"), 0),
        "code": False,
        "schema": False,
        "tags": ("defaults",),
    },
    {
        "label": "defaults may be omitted entirely",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("defaults",)),
        "code": True,
        "schema": True,
        "tags": ("defaults",),
    },
    {
        "label": "defaults.log_level must be one of 10..50",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("defaults", "log_level"), 15),
        "code": False,
        "schema": False,
        "tags": ("defaults",),
    },
    {
        "label": "defaults.strict must be boolean",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("defaults", "strict"), "yes"),
        "code": False,
        "schema": False,
        "tags": ("defaults",),
    },
    {
        "label": "defaults reject unknown keys",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("defaults", "bogus"), 1),
        "code": False,
        "schema": False,
        "tags": ("defaults",),
    },
    {
        "label": "spec_core requires a true int for seed (code only)",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("defaults", "seed"), 42.0),
        "code": False,
        "schema": True,
        "code_only": "spec_core requires a true Python int; JSON Schema treats 42.0 as integer",
        "tags": ("defaults",),
    },
    {
        "label": "job count over max_jobs needs approval (code only)",
        "example": PFLOW,
        "mutate": lambda s: (
            patch(s, ("defaults", "max_jobs"), 1),
            s["jobs"].append(copy.deepcopy(s["jobs"][0])),
            patch(s, ("jobs", 1, "id"), "copy"),
        ),
        "code": False,
        "schema": True,
        "code_only": "defaults.max_jobs caps job count unless large_run_approved",
        "tags": ("defaults",),
    },
    {
        "label": "approved large run over max_jobs is accepted",
        "example": PFLOW,
        "mutate": lambda s: (
            patch(s, ("defaults", "max_jobs"), 1),
            patch(s, ("defaults", "large_run_approved"), True),
            s["jobs"].append(copy.deepcopy(s["jobs"][0])),
            patch(s, ("jobs", 1, "id"), "copy"),
        ),
        "code": True,
        "schema": True,
        "tags": ("defaults",),
    },
    # ---- checks criteria --------------------------------------------------
    {
        "label": "between criterion without bounds is rejected",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "checks", "criteria", 0, "operator"), "between"),
        "code": False,
        "schema": False,
        "tags": ("criteria",),
    },
    {
        "label": "between criterion with bounds is accepted",
        "example": PFLOW,
        "mutate": lambda s: (
            patch(s, ("jobs", 0, "checks", "criteria", 0, "operator"), "between"),
            patch(s, ("jobs", 0, "checks", "criteria", 0, "bounds"), [0.9, 1.1]),
        ),
        "code": True,
        "schema": True,
        "tags": ("criteria",),
    },
    {
        "label": "non-between criterion requires threshold",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "checks", "criteria", 0, "threshold")),
        "code": False,
        "schema": False,
        "tags": ("criteria",),
    },
    {
        "label": "criterion requires basis",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "checks", "criteria", 0, "basis")),
        "code": False,
        "schema": False,
        "tags": ("criteria",),
    },
    {
        "label": "criterion aggregate enum is enforced",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "checks", "criteria", 0, "aggregate"), "median"),
        "code": False,
        "schema": False,
        "tags": ("criteria",),
    },
    {
        "label": "criterion operator enum is enforced",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "checks", "criteria", 0, "operator"), "~"),
        "code": False,
        "schema": False,
        "tags": ("criteria",),
    },
    {
        "label": "criterion bounds must be ordered (code only)",
        "example": PFLOW,
        "mutate": lambda s: (
            patch(s, ("jobs", 0, "checks", "criteria", 0, "operator"), "between"),
            patch(s, ("jobs", 0, "checks", "criteria", 0, "bounds"), [1.1, 0.9]),
        ),
        "code": False,
        "schema": True,
        "code_only": "criterion bounds[0] <= bounds[1]",
        "tags": ("criteria",),
    },
    {
        "label": "timeseries criterion is rejected on pflow",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "checks", "criteria", 0, "source"), "timeseries"),
        "code": False,
        "schema": False,
        "tags": ("criteria",),
    },
    {
        "label": "criterion atol must be non-negative",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "checks", "criteria", 0, "atol"), -0.1),
        "code": False,
        "schema": False,
        "tags": ("criteria",),
    },
    # ---- stages -----------------------------------------------------------
    {
        "label": "stage times must strictly increase (code only)",
        "example": MULTI,
        "mutate": lambda s: patch(s, ("jobs", 0, "stages", 2, "until"), 0.5),
        "code": False,
        "schema": True,
        "code_only": "stages[].until strictly increasing",
        "tags": ("stages",),
    },
    {
        "label": "stage until must be positive",
        "example": MULTI,
        "mutate": lambda s: patch(s, ("jobs", 0, "stages", 0, "until"), 0),
        "code": False,
        "schema": False,
        "tags": ("stages",),
    },
    {
        "label": "stages are rejected on a non-TDS routine",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "stages"), [{"until": 1.0}]),
        "code": False,
        "schema": False,
        "tags": ("stages",),
    },
    {
        "label": "stage unknown field is rejected",
        "example": MULTI,
        "mutate": lambda s: patch(s, ("jobs", 0, "stages", 0, "after"), []),
        "code": False,
        "schema": False,
        "tags": ("stages",),
    },
    {
        "label": "monotonic stages without routine_config.tf are accepted",
        "example": MULTI,
        "mutate": lambda s: patch(s, ("jobs", 0, "stages", 0, "until"), 1.5),
        "code": True,
        "schema": True,
        "tags": ("stages", "tds_time"),
    },
    # ---- spec_core fixes (2026-10-26): previously accepted by code only ------
    {
        "label": "rooted output file '/bus.csv' is rejected on every OS",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "outputs", "tables", 0, "file"), "/bus.csv"),
        "code": False,
        "schema": False,
        "tags": ("relative_file",),
    },
    {
        "label": "drive-relative output file 'C:bus.csv' is rejected",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "outputs", "tables", 0, "file"), "C:bus.csv"),
        "code": False,
        "schema": False,
        "tags": ("relative_file",),
    },
    {
        "label": "non-object defaults is rejected instead of silently replaced",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("defaults",), "x"),
        "code": False,
        "schema": False,
        "tags": ("defaults",),
    },
    {
        "label": "numeric schema_version is rejected instead of coerced",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("schema_version",), 1.0),
        "code": False,
        "schema": False,
        "tags": ("required_fields",),
    },
    {
        "label": "non-string study_name is rejected instead of coerced",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("study_name",), {}),
        "code": False,
        "schema": False,
        "tags": ("required_fields",),
    },
    {
        "label": "object in an enum field raises SpecError, not TypeError",
        "example": PFLOW,
        "mutate": lambda s: patch(s, ("jobs", 0, "checks", "criteria", 0, "operator"), {}),
        "code": False,
        "schema": False,
        "tags": ("criteria",),
    },
]


REQUIRED_TAGS = {
    "required_fields",
    "config_option",
    "case",
    "ops",
    "base_enum",
    "events",
    "alter_method",
    "measurements",
    "eig_plot",
    "cpf_qv",
    "routine_config",
    "outputs",
    "relative_file",
    "defaults",
    "criteria",
    "stages",
    "tds_time",
}


@unittest.skipUnless(Draft202012Validator is not None, "jsonschema is not installed")
class SchemaParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.validator = Draft202012Validator(cls.schema)

    def assertValid(self, spec: dict, label: str) -> None:
        errors = sorted(self.validator.iter_errors(spec), key=lambda error: list(error.path))
        self.assertEqual(
            [],
            [f"{list(error.path)}: {error.message}" for error in errors],
            f"{label}: schema rejected a spec that spec_core accepts",
        )

    def test_schema_is_a_valid_draft_2020_12_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)

    def test_every_example_is_valid_under_both_validators(self) -> None:
        examples = sorted(EXAMPLES.glob("*.json"))
        self.assertTrue(examples)
        for path in examples:
            spec = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(example=path.name):
                self.assertTrue(code_accepts(spec), f"{path.name}: spec_core rejected an example")
                self.assertValid(spec, path.name)

    def test_mutation_table_matches_spec_core(self) -> None:
        self.assertGreaterEqual(len(MUTATIONS), 25)
        for mutation in MUTATIONS:
            with self.subTest(mutation=mutation["label"]):
                spec = load_example(mutation["example"])
                mutation["mutate"](spec)
                code_ok = code_accepts(spec)
                errors = sorted(self.validator.iter_errors(spec), key=lambda error: list(error.path))
                schema_ok = not errors
                self.assertEqual(
                    mutation["code"],
                    code_ok,
                    f"{mutation['label']}: unexpected spec_core verdict "
                    f"(expected {'accept' if mutation['code'] else 'reject'})",
                )
                self.assertEqual(
                    mutation["schema"],
                    schema_ok,
                    f"{mutation['label']}: unexpected schema verdict "
                    f"(expected {'accept' if mutation['schema'] else 'reject'}); "
                    + "; ".join(f"{list(error.path)}: {error.message}" for error in errors),
                )
                if mutation.get("code_only"):
                    self.assertNotEqual(code_ok, schema_ok, f"{mutation['label']}: code-only rule is not code-only")
                else:
                    self.assertEqual(code_ok, schema_ok, f"{mutation['label']}: schema and spec_core disagree")

    def test_every_tag_has_both_directions(self) -> None:
        labels = [mutation.get("label") for mutation in MUTATIONS]
        self.assertEqual(len(labels), len(set(labels)), "duplicate mutation labels")
        for mutation in MUTATIONS:
            self.assertTrue(mutation["tags"], f"{mutation['label']}: missing tags")
        seen = {tag for mutation in MUTATIONS for tag in mutation["tags"]}
        self.assertEqual(REQUIRED_TAGS, seen, "mutation tags drifted from the documented drift list")
        for tag in sorted(REQUIRED_TAGS):
            verdicts = {
                mutation["schema"]
                for mutation in MUTATIONS
                if tag in mutation["tags"]
            }
            self.assertEqual(
                {True, False},
                verdicts,
                f"tag {tag!r} needs at least one schema-accepted and one schema-rejected mutation",
            )

    def test_schema_comment_documents_the_code_only_rules(self) -> None:
        comment = self.schema.get("$comment", "")
        self.assertTrue(comment)
        for token in (
            "stages[].until",
            "final time",
            "max_jobs",
            "unique",
            "tc > tf",
            "bounds[0]",
        ):
            self.assertIn(token, comment)

    def test_code_only_entries_have_an_explanation(self) -> None:
        for mutation in MUTATIONS:
            if mutation.get("code_only"):
                self.assertTrue(mutation.get("code_only").strip(), mutation["label"])
                self.assertFalse(mutation["code"], mutation["label"])
                self.assertTrue(mutation["schema"], mutation["label"])


if __name__ == "__main__":
    unittest.main()
