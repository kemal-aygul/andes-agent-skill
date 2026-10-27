#!/usr/bin/env python3
"""Command-line workflow for the ANDES Agent Skill."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import textwrap
import traceback
from pathlib import Path
from typing import Any, Sequence

try:
    from .andes_runtime import (
        AndesUnavailableError,
        LiveValidationError,
        StudyExecutionError,
        andes_capabilities,
        environment_snapshot,
        execute_study,
        guard_output_destination,
        import_andes,
        inspect_case,
        inspect_connections,
        inspect_model_data,
        preflight_spec,
        protected_paths_for_spec,
        require_supported_andes,
        utc_now,
    )
    from .spec_core import SpecError, dump_json, flatten_files, load_json, sha256_file, validate_spec
except ImportError:  # direct script execution
    from andes_runtime import (  # type: ignore
        AndesUnavailableError,
        LiveValidationError,
        StudyExecutionError,
        andes_capabilities,
        environment_snapshot,
        execute_study,
        guard_output_destination,
        import_andes,
        inspect_case,
        inspect_connections,
        inspect_model_data,
        preflight_spec,
        protected_paths_for_spec,
        require_supported_andes,
        utc_now,
    )
    from spec_core import SpecError, dump_json, flatten_files, load_json, sha256_file, validate_spec  # type: ignore

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent


def parse_atom(value: str) -> Any:
    """Parse a CLI token as JSON scalar when possible, otherwise keep text."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    if isinstance(parsed, (dict, list)):
        return value
    return parsed


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def write_or_print(data: Any, output: str | None) -> None:
    if output:
        destination = Path(output).expanduser().resolve()
        dump_json(destination, data)
        print(f"Written: {destination}")
    else:
        print_json(data)


def command_doctor(args: argparse.Namespace) -> int:
    report: dict[str, Any] = {"ok": False, "environment": environment_snapshot(None)}
    try:
        andes = import_andes()
        report["environment"] = environment_snapshot(andes)
        report["import_ok"] = True
        report["compatibility"] = require_supported_andes(andes)
        report["capabilities"] = andes_capabilities(andes)
        if args.selftest:
            # andes.main.selftest() discards the unittest result and returns None, and a pip
            # install ships no tests directory. It can therefore never prove success here.
            tests_dir = Path(andes.__file__).resolve().parent.parent / "tests"
            saved_streams = (sys.stdout, sys.stderr)
            try:
                if not tests_dir.is_dir():
                    report["selftest"] = {
                        "requested": True,
                        "status": "unavailable",
                        "reason": f"ANDES test suite not installed ({tests_dir} missing; typical for pip installs)",
                    }
                else:
                    main = __import__("andes.main", fromlist=["selftest"])
                    main.selftest(quick=bool(args.quick))
                    report["selftest"] = {
                        "requested": True,
                        "quick": bool(args.quick),
                        "status": "unverified",
                        "reason": "andes selftest ran without raising but does not report a pass/fail result",
                    }
            except Exception as exc:
                report["selftest"] = {
                    "requested": True,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            finally:
                sys.stdout, sys.stderr = saved_streams
            report["note"] = "Use `doctor --smoke` (ieee14 PFlow), not selftest, as numerical evidence."
        if args.smoke:
            # Numerical evidence that the installation works: a real ieee14 power flow.
            ss = andes.load(andes.get_case("ieee14/ieee14.json"), no_output=True, default_config=True)
            ss.PFlow.run()
            converged = bool(ss.PFlow.converged)
            report["smoke"] = {"case": "ieee14/ieee14.json", "routine": "pflow", "converged": converged}
            if not converged:
                report["ok"] = False
                write_or_print(report, args.output)
                return 2
        report["ok"] = True
    except Exception as exc:
        report["import_ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        write_or_print(report, args.output)
        return 2
    write_or_print(report, args.output)
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    result = inspect_case(
        args.case,
        addfiles=args.addfile,
        builtin=args.builtin,
        include_empty=args.include_empty,
        max_indices=args.max_indices,
    )
    write_or_print(result, args.output)
    return 0


def command_model_data(args: argparse.Namespace) -> int:
    result = inspect_model_data(
        args.case,
        args.model,
        fields=args.field or ["idx"],
        indices=[parse_atom(item) for item in args.idx] if args.idx else None,
        source=args.source,
        addfiles=args.addfile,
        builtin=args.builtin,
        include_doc=args.doc,
    )
    write_or_print(result, args.output)
    return 0


def command_connected(args: argparse.Namespace) -> int:
    result = inspect_connections(
        args.case,
        args.model,
        parse_atom(args.idx),
        addfiles=args.addfile,
        builtin=args.builtin,
        details=args.details,
    )
    write_or_print(result, args.output)
    return 0


def command_validate(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec).expanduser().resolve()
    normalized = validate_spec(load_json(spec_path))
    result: dict[str, Any] = {
        "ok": True,
        "mode": "structural",
        "spec": str(spec_path),
        "normalized": normalized,
    }
    if args.live:
        result["mode"] = "structural+live"
        result["preflight"] = preflight_spec(spec_path, raise_on_error=True)
    write_or_print(result, args.output)
    return 0


def _bundle_runner_text() -> str:
    return textwrap.dedent(
        """\
        #!/usr/bin/env python3
        from __future__ import annotations

        import argparse
        import json
        import sys
        from pathlib import Path

        HERE = Path(__file__).resolve().parent
        sys.path.insert(0, str(HERE / "runtime"))

        from andes_runtime import execute_study

        def main() -> int:
            parser = argparse.ArgumentParser(description="Run a validated ANDES study bundle")
            parser.add_argument("--output", default="results", help="Result directory inside or outside the bundle")
            parser.add_argument("--no-live", action="store_true", help="Skip live preflight only for an already validated bundle")
            parser.add_argument("--force", action="store_true", help="Replace a non-empty output directory")
            args = parser.parse_args()
            result = execute_study(
                HERE / "study_spec.json",
                Path(args.output),
                live_preflight=not args.no_live,
                overwrite=args.force,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("state") == "completed" else 2

        if __name__ == "__main__":
            raise SystemExit(main())
        """
    )


def _bundle_readme_text() -> str:
    return textwrap.dedent(
        """\
        # ANDES study bundle

        This folder contains a structurally validated `study_spec.json` and the fixed runner modules.

        ## Running

        In the active ANDES environment:

        ```powershell
        python run_andes.py --output results
        ```

        By default the command runs a live preflight on the real case. Use `--no-live` only if this bundle
        was previously validated live in the same ANDES environment.

        Replacing a non-empty results folder requires an explicit `--force`. The original case files are
        copied into `input/` under the results folder during the run, and their SHA-256 values are recorded.

        ## Output evidence

        Each job produces `inputs.json`, `environment.json`, `resolved_entities.json`, `changes.json`,
        `events.json`, `checks.json`, `result.json`, `status.json`, and `manifest.json`.
        """
    )


def generate_bundle(
    spec_path: Path,
    destination: Path,
    *,
    live: bool,
    force: bool,
) -> dict[str, Any]:
    normalized = validate_spec(load_json(spec_path))
    source_sha256 = sha256_file(spec_path)
    protected = protected_paths_for_spec(normalized, spec_dir=spec_path.parent, spec_path=spec_path)
    andes_spec = importlib.util.find_spec("andes")
    if andes_spec is not None and andes_spec.origin:
        protected.append(Path(andes_spec.origin).resolve().parent)  # built-in cases live here
    destination = guard_output_destination(destination, protected)
    # Preflight before any existing bundle is removed.
    preflight = preflight_spec(spec_path, raise_on_error=True) if live else {
        "ok": None,
        "mode": "not_run",
        "reason": "generate called without --live",
    }
    if destination.exists() and any(destination.iterdir() if destination.is_dir() else [destination]):
        if not force:
            raise StudyExecutionError(f"Bundle destination is not empty: {destination}")
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.mkdir(parents=True, exist_ok=True)
    dump_json(destination / "study_spec.json", normalized)
    dump_json(destination / "preflight.json", preflight)
    (destination / "run_andes.py").write_text(_bundle_runner_text(), encoding="utf-8", newline="\n")
    (destination / "README-run.md").write_text(_bundle_readme_text(), encoding="utf-8", newline="\n")
    runtime_dir = destination / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for name in ("andes_runtime.py", "spec_core.py"):
        shutil.copy2(SCRIPT_DIR / name, runtime_dir / name)
    source_record = {
        "source_spec": str(spec_path),
        "source_spec_sha256": source_sha256,
        "generated_by": str(Path(__file__).resolve()),
        "live_preflight": live,
    }
    dump_json(destination / "bundle_source.json", source_record)
    manifest = {
        "generated_at_utc": utc_now(),
        "generated_bundle": str(destination),
        "files": [item for item in flatten_files(destination) if item["path"] != "bundle_manifest.json"],
    }
    dump_json(destination / "bundle_manifest.json", manifest)
    return {
        "ok": True,
        "destination": str(destination),
        "live_preflight": live,
        "file_count": len(manifest["files"]) + 1,
        "manifest": str(destination / "bundle_manifest.json"),
    }


def command_generate(args: argparse.Namespace) -> int:
    result = generate_bundle(
        Path(args.spec).expanduser().resolve(),
        Path(args.output),
        live=args.live,
        force=args.force,
    )
    print_json(result)
    return 0


def command_run(args: argparse.Namespace) -> int:
    result = execute_study(
        Path(args.spec).expanduser().resolve(),
        Path(args.output),
        live_preflight=not args.no_live,
        overwrite=args.force,
    )
    print_json(result)
    return 0 if result.get("state") == "completed" else 2


def add_case_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--case", required=True, help="Local case path or built-in case name")
    parser.add_argument("--builtin", action="store_true", help="Interpret --case as an ANDES built-in case")
    parser.add_argument("--addfile", action="append", default=[], help="Additional DYR/XLSX/JSON file; repeatable")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="andes_workflow.py",
        description="Inspect, validate, bundle and execute reproducible ANDES studies",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check active Python/ANDES environment")
    doctor.add_argument("--selftest", action="store_true", help="Run ANDES selftest through andes.main.selftest")
    doctor.add_argument("--quick", action="store_true", help="Use quick selftest")
    doctor.add_argument("--smoke", action="store_true", help="Run an ieee14 power flow as installation evidence")
    doctor.add_argument("--output", help="Write JSON report")
    doctor.set_defaults(func=command_doctor)

    inspect_p = sub.add_parser("inspect", help="Inventory models, groups, routines and device indices")
    add_case_arguments(inspect_p)
    inspect_p.add_argument("--include-empty", action="store_true")
    inspect_p.add_argument("--max-indices", type=int, default=200)
    inspect_p.add_argument("--output")
    inspect_p.set_defaults(func=command_inspect)

    model_p = sub.add_parser("model-data", help="Read selected fields from a real model")
    add_case_arguments(model_p)
    model_p.add_argument("--model", required=True)
    model_p.add_argument("--field", action="append", default=[])
    model_p.add_argument("--idx", action="append", default=[])
    model_p.add_argument("--source", choices=("v", "vin"), default="v")
    model_p.add_argument("--doc", action="store_true")
    model_p.add_argument("--output")
    model_p.set_defaults(func=command_model_data)

    connected = sub.add_parser("connected", help="Resolve devices connected to an indexed device")
    add_case_arguments(connected)
    connected.add_argument("--model", required=True)
    connected.add_argument("--idx", required=True)
    connected.add_argument("--details", action="store_true")
    connected.add_argument("--output")
    connected.set_defaults(func=command_connected)

    validate = sub.add_parser("validate", help="Validate study specification")
    validate.add_argument("spec")
    validate.add_argument("--live", action="store_true", help="Also load the case and validate real ANDES entities")
    validate.add_argument("--output")
    validate.set_defaults(func=command_validate)

    generate = sub.add_parser("generate", help="Create a self-contained runtime bundle")
    generate.add_argument("spec")
    generate.add_argument("--output", required=True)
    generate.add_argument("--live", action="store_true", help="Require live preflight before bundle generation")
    generate.add_argument("--force", action="store_true")
    generate.set_defaults(func=command_generate)

    run = sub.add_parser("run", help="Validate and execute a study")
    run.add_argument("spec")
    run.add_argument("--output", required=True)
    run.add_argument("--no-live", action="store_true", help="Skip live preflight only for a prevalidated portable bundle")
    run.add_argument("--force", action="store_true")
    run.set_defaults(func=command_run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (SpecError, AndesUnavailableError, LiveValidationError, StudyExecutionError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ERROR: Interrupted by user", file=sys.stderr)
        return 130
    except Exception as exc:  # Fail with an auditable traceback for unexpected API drift.
        print(f"UNEXPECTED ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
