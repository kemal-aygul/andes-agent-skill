"""Small, dependency-free verification helpers for the standalone templates.

This module uses only the ANDES public API, NumPy, and the Python standard
library.  It deliberately contains no imports from the skill's ``scripts``
package so that a template can be copied into a research project on its own.

Usage from a template::

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _checks import assert_pflow, assert_tds_complete, case_record, write_run_record

Every helper raises ``RuntimeError`` (or ``FileNotFoundError`` for inputs) with
an actionable message instead of returning a silent boolean.  That is the point
of this module: a run that did not actually finish must never look successful.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

try:  # ANDES is the whole point of these templates, but keep the message clear.
    import andes
except Exception as exc:  # pragma: no cover - environment specific
    raise RuntimeError(
        "The ANDES package must be importable in the active Python environment before "
        f"using templates/_checks.py. Original error: {type(exc).__name__}: {exc}"
    ) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_pflow(ss: Any) -> dict[str, Any]:
    """Require a converged power flow and return a compact summary.

    ``ss.PFlow.converged`` is set by ``System.PFlow.run()`` in ANDES 2.0.  A
    return value of ``True`` from ``run()`` is not treated as sufficient
    evidence: the solver's own convergence flag is authoritative.
    """
    converged = getattr(getattr(ss, "PFlow", None), "converged", None)
    if converged is not True:
        raise RuntimeError(
            "Power flow did not converge (PFlow.converged=%r). Do not continue with "
            "TDS/EIG/CPF/SE or report downstream results." % (converged,)
        )
    return {
        "converged": True,
        "iterations": getattr(getattr(ss, "PFlow", None), "niter", None),
    }


def assert_finite(*arrays: Any, names: Sequence[str] | None = None) -> dict[str, Any]:
    """Require every supplied array to contain only finite values.

    ``None`` entries are skipped (ANDES leaves some arrays unused for a given
    routine).  ``names`` must match the number of positional arrays when given.
    Returns ``{"finite": True, "checked": [...]}``.
    """
    if names is not None and len(names) != len(arrays):
        raise ValueError("names must have one entry per array")
    labels = list(names) if names is not None else [f"array[{i}]" for i in range(len(arrays))]
    checked: list[str] = []
    bad: list[str] = []
    for label, value in zip(labels, arrays):
        if value is None:
            continue
        try:
            array = np.asarray(value)
        except Exception as exc:  # pragma: no cover - exotic containers
            raise RuntimeError(f"Cannot convert {label} to a NumPy array: {exc}") from exc
        checked.append(label)
        if array.size and not bool(np.isfinite(array).all()):
            bad.append(label)
    if bad:
        raise RuntimeError(
            "Non-finite values detected in: " + ", ".join(bad) + ". The simulation is not usable evidence."
        )
    return {"finite": True, "checked": checked}


def assert_tds_complete(ss: Any, tf: float, atol: float = 1e-6) -> dict[str, Any]:
    """Require a time-domain simulation to have reached ``tf`` cleanly.

    Checks, in this order:

    * ``ss.exit_code == 0`` (ANDES 2.0 ``System.exit_code``),
    * ``abs(ss.dae.t - tf) <= max(atol, 1e-6 * abs(tf))``,
    * ``ss.dae.x``, ``ss.dae.y`` and, when phase ``ts`` exists, ``ss.dae.ts.x`` /
      ``ss.dae.ts.y`` contain only finite values.

    Returns ``{"exit_code": int, "t_end": float, "finite": True}``.
    """
    exit_code = getattr(ss, "exit_code", None)
    if exit_code is None:
        raise RuntimeError(
            "System.exit_code is missing; this template targets ANDES 2.0 where the TDS "
            "routine updates System.exit_code."
        )
    exit_code = int(exit_code)
    if exit_code != 0:
        raise RuntimeError(
            f"TDS returned exit_code={exit_code} (expected 0); the simulation stopped before "
            f"t={float(getattr(getattr(ss, 'dae', None), 't', float('nan'))):g} s."
        )

    dae = getattr(ss, "dae", None)
    t_end = float(dae.t)
    tolerance = max(float(atol), 1e-6 * abs(float(tf)))
    if abs(t_end - float(tf)) > tolerance:
        raise RuntimeError(
            f"TDS ended at t={t_end:g} s but tf={float(tf):g} s was requested "
            f"(tolerance {tolerance:g} s). The run did not complete."
        )

    arrays: list[Any] = [dae.x, dae.y]
    labels: list[str] = ["dae.x", "dae.y"]
    phase = getattr(dae, "ts", None)
    if phase is not None:
        for name in ("x", "y"):
            value = getattr(phase, name, None)
            if value is not None:
                arrays.append(value)
                labels.append(f"dae.ts.{name}")
    assert_finite(*arrays, names=labels)

    return {"exit_code": exit_code, "t_end": t_end, "finite": True, "tolerance": tolerance}


def case_record(path_or_builtin: str | Path) -> dict[str, Any]:
    """Resolve a case path or ANDES built-in name and record its SHA-256.

    The returned dictionary is intentionally JSON-friendly and includes the
    ANDES version so that a run record is tied to the installed API surface.
    """
    requested = str(path_or_builtin)
    candidate = Path(requested).expanduser()
    if candidate.is_file():
        resolved = candidate.resolve()
    else:
        try:
            resolved = Path(andes.get_case(requested)).resolve()
        except Exception as exc:
            raise FileNotFoundError(
                f"Case {requested!r} is neither an existing file nor an ANDES built-in case: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"Resolved case does not exist: {resolved}")
    return {
        "requested": requested,
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": _sha256_file(resolved),
        "andes_version": getattr(andes, "__version__", None),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
    }


def write_run_record(
    output_dir: str | Path,
    *,
    case: dict[str, Any] | None,
    checks: dict[str, Any],
    status: str = "completed",
    notes: Iterable[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write ``run_record.json`` next to the study outputs.

    ``checks`` should contain the summaries returned by the assertion helpers;
    ``status`` lets a template record a deliberate block (for example, an empty
    ``EIG_INDICES``) without pretending the run succeeded.
    """
    payload: dict[str, Any] = {
        "status": status,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case": case,
        "checks": checks,
    }
    if notes:
        payload["notes"] = list(notes)
    if extra:
        payload["extra"] = extra
    path = Path(output_dir) / "run_record.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
