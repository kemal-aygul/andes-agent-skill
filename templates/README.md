# Standalone templates

These files illustrate ANDES APIs documented in the supplied manual. They are **not** natural-language parsers and are not executed by the fixed JSON runtime. Copy a template into a research project only after:

1. inspecting the actual case and installed ANDES version;
2. resolving every model, field, group, device index, unit, and controller chain;
3. writing explicit acceptance criteria and their basis;
4. preserving the original input files and recording hashes; and
5. running a one-scenario smoke test before a batch, CCT search, RL training, or model-development campaign.

The skill should prefer `scripts/andes_workflow.py` and `study_spec.json` for routine PFlow/TDS/EIG/SE/CPF tasks. The contingency, CCT, RL, and custom-model templates require additional study-specific scientific decisions.

## Verification helpers and run records

`_checks.py` provides `assert_pflow`, `assert_tds_complete`, `assert_finite`, `case_record`, and `write_run_record`. Templates call these helpers so that a non-zero `System.exit_code`, a short TDS final time, or a non-finite state raises instead of looking successful.

Run each template from a **new, empty working folder**. Every runnable template creates a new output directory with `mkdir(exist_ok=False)` and writes `run_record.json` containing the resolved case SHA-256, the installed ANDES version, and the real check summary. `eig_root_locus.py` intentionally stops with a clear error until its module-level `EIG_INDICES` list is filled from the generated EIG report; `custom_model.py` and `rl_environment.py` are marked skeletons.

`case_convert.py` is a guarded file-conversion example. Confirm parser warnings, imported model coverage, power-flow convergence, and the new output path before treating a converted case as equivalent to its source.
