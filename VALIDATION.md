# Validation record

- Skill package version: **1.2.0** (runtime `RUNTIME_VERSION = "1.2.0"`)
- Validated against: **ANDES 2.0.0**, Python 3.11.9, NumPy 2.4.6, on Windows 11
- Date: 2026-10-26

## Real-ANDES checks (all passed)

- **Unit tests:** `python -m unittest discover -s tests -t .` ran 44 tests with no skips and passed (40 of them 5 times in a row; the 4 new `test_fetch_docs` tests are offline). The 16 job, study and bundle manifests from the real runs also validate against `run-manifest.schema.json`, and a test now checks the bundle manifest. The environment has jsonschema 4.26.
  - The schema is valid Draft 2020-12, and every example passes both validators.
  - 110 mutations get the same verdict from the schema and from `spec_core`, apart from the documented code-only rules.
- **Example specs:** all 7 specs in `examples/` were run with `andes_workflow.py run`. Every one reached state `completed` with exit 0: cpf, eigenvalue-root-locus, kundur-fault, line-trip-reclose, multistage-setpoint, pflow-ieee14 and state-estimation.
- **Negative control:** `kundur-fault` was re-run with `xf=1e-6`. The job ended `completed_with_failed_checks` (TDS exit_code 1, stopped at t=1.0), the study ended `failed`, and the CLI exited 2. No silent recovery was attempted.
- **Manifest integrity:** every manifest from the runs above was re-hashed. All 362 file entries matched their SHA-256.
- **Output guard:** `run` and `generate --force` were pointed at the folder holding the spec. Both refused with exit 2, and both the spec and a sibling file survived.
- **`doctor`:** every capability probe is true except `RL.AndesEnv`, which needs the optional `andes[rl]` / gymnasium. `--selftest` reports `unavailable`, because a pip install ships without the ANDES test suite.
- **Templates:** each was run from an empty folder.
  - Completed with `run_record.json`: pflow, tds_fault, tds_toggle, tds_multistage, cct (CCT ≈ 0.3875 s, conclusive, both bounds tested), contingency, cpf and state_estimation.
  - eig_root_locus stops when `EIG_INDICES` is empty (status `blocked`). With `EIG_INDICES = [4, 7]` it completes and writes `root-locus.png`.
  - Stopped by design: case_convert (needs RAW/DYR), custom_model (a skeleton) and rl_environment (needs gymnasium).
- **CCT bracket logic, checked with a stubbed trial function:**
  - All trials unstable → inconclusive (the lower bound is not stable).
  - All trials stable → inconclusive (the upper bound is not unstable).
  - True CCT of 0.2 s → 0.1977 s, conclusive.
- **Consumer test:** a fresh Sonnet 5.5 agent used only SKILL.md on four Turkish prompts.
  - It chose the expected tier for each: quick, quick, research-grade, research-grade.
  - On the quick-tier `xf=1e-6` request it ran the fault as asked. It reported exit_code 1 at t=1.0 as a failure and asked before running the `xf=1e-4` variant.
  - For CCT and N-1 it asked for the stability criterion and its source, and for approval to run more than 20 jobs.
  - Its clarity suggestions were applied: bus idx vs name, the default Kundur file, requested known-failing values, how runs are counted against the gate, a short quick-tier report, and script names that don't clash with the standard library.

- **Docs cache:** `fetch_andes_docs.py` fetched tag v2.0.0 and extracted 91 files.
  - It resolved commit `eda5163c9ee8`, the same commit as the manual's build label, with archive SHA-256 `e4bbb73d…8d9c`.
  - All 23 files named in the `versions.md` manual map exist in the cache.

- **Clean-install simulation:** the skill was copied to a neutral folder and installed into a fresh Python 3.11 venv using only `requirements-dev.txt`.
  - The 44 tests passed.
  - `doctor --smoke` converged.
  - pflow-ieee14, kundur-fault and state-estimation ran with exit 0.
  - `fetch_andes_docs.py` with `ANDES_DOCS_DIR` set fetched commit `eda5163c9ee8` (91 files).
  - No machine-specific paths remain, and `.gitignore` excludes none of the 55 skill files.

- **Pre-publication review:** found a Windows tar-path traversal gap in `fetch_andes_docs.py` (backslash member names); it is now fixed and tested.

## Not verified

- ANDES versions other than 2.0.0, PSS/E RAW/DYR imports, and RL training.
