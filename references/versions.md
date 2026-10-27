# Versions, sources and known limitations

## Version policy

- The runtime was **verified on ANDES 2.0.0** (Python 3.11, NumPy 2.4) on 2026-10-26. All 7 example specs ran end-to-end, and 8 templates completed. `rl_environment` needs `andes[rl]` (gymnasium), and `custom_model` and `case_convert` need user input.
- **The manual is the v2.0.0 manual.** Its label `1.10.1.post50+geda5163c9` is a pre-tag build name. Commit `eda5163c9ee8` is exactly the `v2.0.0` tag of `CURENT/andes` (GitHub compare: 0 ahead, 0 behind, checked 2026-10-26), and v2.0.0 is the latest PyPI release. An installed version string with that label is therefore treated as 2.0.0.
- Other 2.x releases are allowed only after `doctor` capability probes and live preflight pass. Record the difference in the manifest.
- Package version 1.10.1 and versions 3.x and later are rejected, because the required API surface is missing or unverified.
- If an API is missing, stop. Never substitute an invented name or call.
- Version-sensitive areas:
  - `System.set_status()`
  - `Model.set(..., base='device')` (`Model.alter()` is deprecated in 2.0)
  - `System.add()`
  - SE/LAV
  - CPF/QV
  - TDS adaptive methods and `get_timeseries()`
  - the plotter
  - the PSS/E parser
  - EIG reduction
  - renewable models
  - `AndesEnv`
- `andes selftest` / `doctor --selftest` is not evidence:
  - pip installs ship without the test suite;
  - `andes.main.selftest()` discards the result;
  - `doctor` therefore reports it as `unavailable` or `unverified`.
  - Use an ieee14 PFlow smoke run instead.

## Manual map

Use the sources in this order:

1. **Docs cache (primary).** `$ANDES_DOCS_DIR`, or by default `~/.claude/skills-cache/andes-docs-v2.0.0/`, holds `docs/source/` of the `v2.0.0` tag. `SOURCE.json` records the commit and the archive SHA-256.
   - Read notebooks through their output-free Markdown copies under `text/docs/source/...` (about 6–20 KB each). Grep the `.md` and `.rst` files directly.
   - If the cache is missing, rebuild it with `python -I <skill>/scripts/fetch_andes_docs.py`. This downloads only from github.com/CURENT/andes and needs network access.
2. **Installed package.** The API and model reference (PDF chapters 5.3 and 5.5) is generated from code and is not in `docs/source`. Use `model.doc()`, `help(ss.TDS.run)`, `inspect.signature(...)` and `ss.models` / `ss.groups` / `ss.routines` instead.
3. **PDF (fallback, optional).** Use a path the user gives, or `$ANDES_MANUAL_PDF`. The matching build is about 6.8 MB and its title page reads "Release 1.10.1.post50+geda5163c9, Mar 11, 2026". The "latest" PDF on docs.andes.app can move past 2.0, so check the title page. Pages in the table are printed numbers, and **PDF page = printed + 18** for that build (checked: printed 125 = PDF 143, printed 86 = PDF 104). Read at most 20 PDF pages per call.

Never use manuals older than 2.0 (e.g. the online v1.2.5 PDF) as an API source.

In the table, `T/` = `text/docs/source/tutorials/`, `G/` = `text/docs/source/gallery/`, `V/` = `text/docs/source/verification/`; the other files are relative to `docs/source/`.

| Topic | Docs cache file | PDF section / printed pages |
|---|---|---|
| Install, environment, selftest | `tutorials/01-installation.md` | 2.2, 5.1; pp. 4–7, 469–476 |
| First simulation, System/PFlow/TDS/EIG | `T/02-first-simulation.md` | 2.3; pp. 7–14 |
| Power flow, results, convergence | `T/03-power-flow.md` | 2.4; pp. 15–23 |
| TDS, Fault/Toggle/Alter, results | `T/04-time-domain.md` | 2.5; pp. 24–42 |
| File formats, get/set, base and idx | `T/05-data-and-formats.md` | 2.6; pp. 42–52 |
| Plotting and CSV | `T/06-plotting-results.md` | 2.7; pp. 52–66 |
| EIG and root locus | `T/07-eigenvalue-analysis.md` | 2.8; pp. 66–73 |
| Parameter sweeps and parallel runs | `T/08-parameter-sweeps.md` | 2.9; pp. 73–86 |
| Contingency and CCT | `T/09-contingency-analysis.md`, `G/critical-clearing-time.md` | 2.10; pp. 86–96 |
| Multi-stage control and setpoints | `T/10-dynamic-control.md` | 2.11; pp. 96–105 |
| Frequency and load shedding | `T/11-frequency-response.md`, `G/low-inertia-freq.md` | 2.12; pp. 105–113 |
| WLS/LAV state estimation | `T/12-state-estimation.md` | 2.13; pp. 113–125 |
| CPF, PV/QV, Q limits | `T/13-continuation-power-flow.md` | 2.14; pp. 125–144 |
| Inspecting model equations | `T/14-inspecting-models.md` | 2.15; pp. 144–153 |
| AndesEnv / RL | `T/15-reinforcement-learning.md` | 2.16; pp. 153–162 |
| Oscillation examples (SMIB, forced) | `G/smib-oscillation.md`, `G/forced-oscillation.md` | gallery |
| Modelling concepts and components | `modeling/concepts/*.md`, `modeling/components/*.md` | 4.2–4.3 |
| Creating and testing models | `modeling/creating-models/*.md` (TGOV1, IEEEST, static and dynamic examples, `testing-models.md`) | 4.4; to p. 467 |
| CLI and configuration | `reference/cli.md`, `reference/configuration.md` | 5.1–5.2; pp. 469–482 |
| Release notes, version changes | `reference/release-notes.md` | — |
| Model reference | installed package: `model.doc()` | 5.3; pp. 483–876 |
| API reference | installed package: `help()`, `inspect.signature()` | 5.5; pp. 880–952 |
| Verification cases | `V/andes-ieee14-verification.md`, `V/andes-npcc-...`, `V/andes-wecc-...` | 6; pp. 985–1066 |

Tutorial code is illustration, not authority: when it conflicts with the installed package, the installed package wins and the conflict is reported.

## Known limitations

- `schemas/andes-study.schema.json` now matches `scripts/spec_core.py`, which `tests/test_schema_parity.py` checks with 110 mutations. Rules that JSON Schema cannot express are enforced only by `validate`, so a schema-valid spec can still fail it on these points (they are listed in the schema's `$comment`):
  - stage times must strictly increase;
  - the TDS end time must cover every event;
  - `max_jobs` caps the number of jobs unless `large_run_approved` is set;
  - job ids must be unique;
  - `fault.tc > fault.tf`;
  - `bounds[0] <= bounds[1]`;
  - integers must be true ints;
  - NaN and Infinity are rejected.
- The schema tests need `jsonschema`, which is a developer-only dependency; they are skipped when it is absent.
- `validate --live` checks names, idx and setup, but not numerical convergence.
