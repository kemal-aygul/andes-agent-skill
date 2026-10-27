# Changelog

## 1.2.0 (2026-10-26)

Adapted for current Claude models and verified for the first time against a real ANDES 2.0.0 install.

- Rewrote `SKILL.md` in English. It adds quick, standard and research-grade tiers with explicit boundaries, a short always-rules list, verified ANDES gotchas, and Turkish trigger cues in the description.
- Merged the ten reference files into four: `api-cheatsheet`, `recipes`, `spec-pipeline` and `versions`. Each signature in the cheatsheet was checked on 2.0.0.
- Fixed the job and study manifests, which hashed the status files before their final write.
- `run` and `generate --force` now hash the source spec and run import and preflight before removing any output. They refuse output folders that contain the spec, a case or addfile, the skill, the cwd, home, the ANDES package, or a drive root.
- Added the `completed_unverified` state for runs whose convergence checks are disabled. Routine success is always evaluated, and the study state and exit code count this state as a failure.
- `doctor --selftest` now reports `unavailable` or `unverified` instead of a false pass, and it restores stdout.
- The bundle manifest now includes `generated_at_utc`.
- The Kundur fault example now uses `xf=1e-4`; `1e-6` failed at fault onset.
- Added `templates/_checks.py`. All templates now check PFlow, TDS completion and finiteness, and write a `run_record.json` with the case SHA-256.
  - CCT separates numerical failure from instability.
  - Contingency records real outcomes.
  - SE runs the chi-square test only after WLS.
  - EIG root locus requires explicit indices.
- Added `tests/test_safety_guards.py`. The `jsonschema` test now skips when that package is absent.
- TDS success now requires `exit_code == 0` at the end and at every stage; an unknown exit code no longer counts as success.
- Fixed `cct.py`: it tests both bounds before bisecting, and reports `inconclusive` (with `cct_s=None`) when a bound is wrong, a trial fails numerically, or the bracket stays wider than `tol`.
- Fixed `eig_root_locus.py`, which crashed when given `show=False`.
- `contingency.py` now reports `completed_with_failures`, and `case_record` also records the Python version.
- Aligned `schemas/andes-study.schema.json` with `spec_core`:
  - operations, events and measurements are now defined per kind;
  - routine-specific outputs and the eig/cpf conditional rules are added;
  - `routine_config`, `config_option` and required fields now match the code;
  - safe relative paths are enforced.
- Added `tests/test_schema_parity.py`, which checks 110 mutations against both validators.
- Fixed `spec_core`:
  - It rejects rooted (`/x`) and drive-relative (`C:x`) output paths on every OS.
  - It reports a non-object `defaults` or a non-string `schema_version`/`study_name` instead of coercing it.
  - It raises `SpecError` instead of `TypeError` for an object in an enum field.
- Linked the skill to the ANDES documentation sources.
  - New `scripts/fetch_andes_docs.py` caches `docs/source/` of tag `v2.0.0` in `~/.claude/skills-cache/andes-docs-v2.0.0/`.
  - The cache records the commit and archive SHA-256, and notebooks are converted to output-free Markdown.
  - The manual map in `versions.md` now points each topic to its docs file, the installed package (for the API and model reference), and the PDF page as a fallback.
  - Added `tests/test_fetch_docs.py`.
- Resolved the version narrative: the manual label `1.10.1.post50+geda5163c9` is commit `eda5163c9`, identical to tag `v2.0.0`.
- Test temp folders now ignore cleanup errors; they failed intermittently on exFAT drives.
- Made the skill portable for team use via GitHub:
  - Removed all machine-specific paths. The docs cache honours `$ANDES_DOCS_DIR`, the manual PDF is optional via `$ANDES_MANUAL_PDF`, and Claude asks before downloading the docs.
  - Replaced the Windows-only `install_windows.ps1` and `setup_andes_env.ps1` with `git clone` instructions, `requirements.txt` / `requirements-dev.txt`, and `doctor --smoke` (an ieee14 PFlow as installation evidence; `andes selftest` cannot verify pip installs).
  - Added `.gitignore` and `scripts/update_manifest.py`.
  - Renamed the skill from `andes-power-system-simulator` to `andes-agent-skill` (repository `kemal-aygul/andes-agent-skill`).
  - Published under the MIT License (LICENSE, README, NOTICE).
- Hardened `fetch_andes_docs.py` tar extraction: members with a backslash in the name are rejected, and each target must resolve inside the destination. It also warns when the `v2.0.0` tag no longer resolves to the verified commit.
- `update_manifest.py` builds the file list from `git ls-files` when the folder is a git repo.
- Translated all runtime, CLI and validation messages to English.

## 1.1.0

- Aligned the runtime target with ANDES 2.0.0 while preserving the uploaded manual build identifier.
- Added explicit installed-version compatibility classification and hard failure for unsupported versions.
- Added post-setup `System.set_status()` support with effective-status audit fields.
- Restricted state-estimation measurements to the measurement types implemented by the documented ANDES 2.0 API.
- Strengthened installation, capability-preflight, provenance, and reproducibility guidance.

## 1.0.0

- Added natural-language-to-structured-study workflow for the uploaded ANDES manual.
- Added case/model/connection introspection commands.
- Added structural JSON validation and live ANDES preflight.
- Added deterministic execution for PFlow, TDS, EIG, SE, and CPF.
- Added Fault, Toggle, Alter, multi-stage setpoint, result export, checks, manifests, and input hashes.
- Added Windows installer, examples, templates, troubleshooting, compatibility, RL, CCT, contingency, and custom-model guidance.
