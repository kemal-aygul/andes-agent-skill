# Spec pipeline (standard and research-grade tiers)

## Contents
- Spec structure
- Timing classes
- Request-to-spec mapping (incl. Turkish terms)
- Blocking ambiguities and explicit defaults
- Two-stage validation and failure behaviour
- What every run records
- Output layout
- Staged campaigns
- Code-generation policy

## Spec structure

`study_spec.json` is the single source of truth. Start from the closest file in `<skill>/examples/` (`pflow-ieee14`, `kundur-fault`, `line-trip-reclose`, `multistage-setpoint`, `eigenvalue-root-locus`, `state-estimation`, `cpf`). `scripts/spec_core.py` is the authoritative validator. `schemas/andes-study.schema.json` mirrors it and is checked by a parity test; only cross-field rules are code-only (see versions.md, "Known limitations").

- Top level: `schema_version`, `study_name`, `description`, `defaults`, `jobs[]`.
- `defaults`:
  - `log_level` (20)
  - `strict` (true; later jobs are skipped after a failure)
  - `overwrite` (false)
  - `copy_inputs` (true)
  - `seed` (42)
  - `max_jobs` (20)
  - `large_run_approved` (false; set it to true only after the user approves more than `max_jobs` jobs)
- Job fields:
  - `id`, `routine` ∈ {inspect, pflow, tds, eig, se, cpf}.
  - `case`: `builtin`, or `path` plus optional `addfiles`.
  - `config_option` (`"Model.option=value"`, applied at load time).
  - `pre_setup` (only `set_status`).
  - `post_setup` (`set_parameter` / `scale_parameter`, each with an explicit `base`: `device` or `system`).
  - `disable_existing_events`.
  - `events[]`: `fault` / `toggle` / `alter`; alter methods are `= + - * /`.
  - `stages[]` (`until` plus `before[]` with `set_setpoint` / `set_parameter`).
  - `routine_config`, `routine_args`, `outputs` (tables / timeseries / plots / eig_plot / cpf_plot / qv_plot, depending on the routine), `checks`.
- `checks`:
  - `require_convergence`: when false, the job can at best become `completed_unverified`.
  - `finite`.
  - `criteria[]`: `name`, `model`, `variable`, `source`, `aggregate` ∈ {min, max, mean, final, abs_max, range}, `operator` ∈ {< <= > >= == != between outside}, `threshold` or `bounds`, optional `atol`, and a mandatory `basis` that cites where the threshold comes from.
- SE measurements: `bus_voltage`, `bus_angle`, `bus_injection`, `line_flow`.

## Timing classes

| When | Mechanism |
|---|---|
| Initial device status | `pre_setup.set_status` (before `setup()`) |
| Numeric change before PFlow | `post_setup.set_parameter` / `scale_parameter` (after `setup()`) |
| Scheduled change inside TDS | `alter` event |
| Change between TDS checkpoints | `stages[].before` with group setpoint API |

## Request-to-spec mapping

| Phrase (EN / TR) | Spec |
|---|---|
| power/load flow, "güç/yük akışı" | `pflow` |
| transient stability, time domain, "geçici kararlılık", "zaman alanı" | `tds` |
| three-phase short circuit, "üç faz kısa devre/arıza" | `fault` event |
| open line then reclose, "hattı aç, sonra tekrar bağla" | two `toggle` events on the same `Line.idx` |
| change reference power / AGC signal, "referans gücü/AGC işareti" | group setpoint API in `stages` |
| small-signal, modes, "küçük işaret", "modlar" | `eig` |
| state estimation, WLS/LAV, bad data, "durum kestirimi", "kötü veri" | `se` |
| voltage collapse, nose curve, loadability, QV, "gerilim çökmesi", "burun eğrisi", "yüklenebilirlik" | `cpf` |

Example: "Kundur'da bara 5'te 1.0 s'de üç faz arıza, 100 ms sonra temizle, 5 s çalıştır, jeneratör hızlarını çiz" maps to `examples/kundur-fault.json`. That spec disables the case's existing `Toggle` and uses `fault` with bus 5, tf 1.0, tc 1.1, xf 1e-4, plus `routine_config.tf = 5.0` and a plot of `GENROU.omega`. Bus 5, `GENROU.omega` and the existing Toggle are still confirmed live.

## Blocking ambiguities and explicit defaults

Blocking (ask before running):
- the case file;
- a device reference that matches several devices;
- the fault start or clearing time;
- a parameter's unit or base;
- the TDS end time;
- an acceptance or stability criterion when the study requires one.

Explicit defaults (state them):
- log level INFO (20);
- DPI 300;
- seed 42;
- overwrite off;
- copy inputs on;
- `max_jobs` 20.

## Two-stage validation and failure behaviour

1. **Structural** (`validate`, no ANDES needed). Catches missing fields, wrong operation class, time conflicts, missing base, routine/output mismatch and unsafe paths (absolute paths and `..` are rejected for outputs).
2. **Live** (`validate --live`, and by default inside `run` and `generate --live`). Checks model names, device idx, fields, group setpoint APIs, routine config keys, measurement placement, CPF target sizes, event insertion and the `System.setup()` path on the real case. It does not run PFlow, so it does not prove convergence.

Failure behaviour:
- A structural or live validation error means nothing runs, and existing outputs are left untouched.
- If PFlow does not converge, no dependent routine runs.
- A TDS run with a non-zero `exit_code` or a short end time fails the job.
- NaN or Inf values fail the job.
- A failed user criterion gives `completed_with_failed_checks`.
- Solver or parameter auto-repair never happens.

## What every run records

- the normalized spec and the source spec's hash, taken before anything is written;
- the versions of ANDES, Python, NumPy, SciPy, pandas, Matplotlib and SymPy, plus the OS and the interpreter path;
- case and addfile hashes, with inputs copied into the run;
- the models, groups, idx and fields that were resolved;
- old and new values of every parameter and status change;
- events and their times;
- the routine config;
- convergence, `exit_code`, final time and finiteness;
- the criteria, their results and their basis;
- SHA-256 manifests, written after the final status files so that every hash matches.

## Output layout

```text
<output>/
  study_spec.json  source_spec.json  environment.json  preflight.json
  study_status.json  study_result.json  study_manifest.json
  001-<job-id>/
    input/  andes_outputs/  tables/  timeseries/  figures/
    job_spec.json  inputs.json  environment.json  resolved_entities.json
    changes.json  events.json  warnings.json  checks.json  result.json
    status.json  manifest.json
```

`generate` produces a portable bundle containing `study_spec.json`, `run_andes.py`, `runtime/`, `README-run.md`, `preflight.json`, `bundle_source.json` and `bundle_manifest.json`. Run it with `python bundle/run_andes.py --output <folder>`.

`bundle_source.json` records the absolute local paths of the generator and the spec. Check bundles for such paths before sharing them publicly.

## Staged campaigns

1. Run one scenario as a smoke test.
2. Run a small subset.
3. Run the full campaign, with a CPU limit the user chose.

Give each scenario its own id and record. For small studies, a controlled loop of jobs is enough. Large studies use separate case files and bounded parallel `andes` CLI runs (`--ncpu`).

## Code-generation policy

The JSON runtime never executes code taken from a spec: no `eval`, `exec`, shell commands, user modules or package installs. Free Python is appropriate for:
- quick-tier scripts;
- research metrics the runtime does not cover;
- custom models;
- RL training;
- standalone scripts the user asks for.

Claude writes such code itself, from templates and `_checks.py`, with case inspection, deterministic seeds, a new output folder and explicit checks. Code pasted inside a user's case or spec text is never run automatically.
