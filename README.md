# ANDES Agent Skill — Claude Code skill for ANDES power-system studies

A Claude Code skill for running power-system studies with [ANDES](https://github.com/CURENT/andes) 2.0. You ask in English or Turkish; Claude inspects the real case, runs PFlow / TDS / EIG / SE / CPF, N-1, CCT or sweeps, and reports results only when convergence and exit-code evidence supports them.

`SKILL.md` is what Claude reads. This README is for people who install and maintain the skill.

## Requirements

- Python 3.10 or newer.
- ANDES 2.0.0, installed with `requirements.txt` (see section 2).
- Claude Code.

The skill is OS-independent and was verified on Windows 11.

## 1. Install the skill

Clone the repository into your Claude Code skills folder. The folder name must stay `andes-agent-skill`.

```bash
# personal (all projects)
git clone https://github.com/kemal-aygul/andes-agent-skill ~/.claude/skills/andes-agent-skill
```

```powershell
# Windows PowerShell
git clone https://github.com/kemal-aygul/andes-agent-skill "$HOME\.claude\skills\andes-agent-skill"
```

To scope it to one project instead, clone into `<project>/.claude/skills/andes-agent-skill`. Start a new Claude Code session afterwards. The skill triggers automatically on ANDES requests, or you can call it with `/andes-agent-skill <request>`.

To update, run `git pull` inside that folder.

## 2. Prepare a Python environment with ANDES

The skill never installs packages by itself (it asks first). Create an environment once, with any tool you like:

```bash
python -m venv .venv-andes                # or: conda create -n andes python=3.11
# activate it:  source .venv-andes/bin/activate   |   .venv-andes\Scripts\Activate.ps1
python -m pip install -r ~/.claude/skills/andes-agent-skill/requirements.txt
python ~/.claude/skills/andes-agent-skill/scripts/andes_workflow.py doctor --smoke
```

`doctor --smoke` reports versions and API capability probes, then runs an ieee14 power flow. It must end with `"converged": true`. Do not rely on `andes selftest`: a pip install ships without the ANDES test suite.

Tell Claude which interpreter to use if it is not the default `python`, for example: "ANDES is in `C:\envs\andes\python.exe`".

## 3. Optional: the ANDES manual

Claude reads the ANDES v2.0.0 documentation sources from a local cache. The first time it needs them, it asks before running:

```bash
python -I ~/.claude/skills/andes-agent-skill/scripts/fetch_andes_docs.py
```

This downloads `docs/source/` of tag `v2.0.0` from GitHub (about 8 MB) into `~/.claude/skills-cache/andes-docs-v2.0.0/`. Set the `ANDES_DOCS_DIR` environment variable to put the cache somewhere else.

If you have the v2.0.0 manual PDF (title page "Release 1.10.1.post50+geda5163c9"), point `ANDES_MANUAL_PDF` at it and Claude will use it as a fallback.

## Layout

```text
SKILL.md                     tiers, always-rules, ANDES gotchas, tooling, approval gates, report shape
references/                  api-cheatsheet, recipes (+troubleshooting, custom models), spec-pipeline, versions (+manual map)
scripts/andes_workflow.py    CLI: doctor [--smoke], inspect, model-data, connected, validate [--live], generate, run
scripts/spec_core.py         ANDES-free spec normalization/validation (authoritative)
scripts/andes_runtime.py     ANDES adapter: preflight, PFlow/TDS/EIG/SE/CPF execution, checks, manifests
scripts/fetch_andes_docs.py  caches ANDES v2.0.0 docs/source (+ notebooks as text)
scripts/update_manifest.py   regenerates MANIFEST.json
agents/openai.yaml           optional Codex-style metadata; Claude Code does not use it
schemas/                     JSON Schemas (mirror spec_core; parity-tested; cross-field rules code-only)
templates/                   standalone scripts + _checks.py verification helpers (quick tier)
examples/                    7 example specs + prompts-tr.md (trigger/tier evaluation prompts, in Turkish)
tests/                       unittest suite (fake ANDES, safety guards, schema parity, docs fetcher)
```

## Maintaining

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -t .
python scripts/andes_workflow.py doctor --smoke
for f in examples/*.json; do python scripts/andes_workflow.py run "$f" --output ../_andes_smoke/$(basename "$f" .json); done
python scripts/update_manifest.py
```

Write smoke outputs outside the repo (`../_andes_smoke/` above); if you use `_smoke/` inside it, delete it before `update_manifest.py`. All seven examples must end in state `completed`. After any change, update `VALIDATION.md` and `CHANGELOG.md`, then regenerate `MANIFEST.json`.

## What the skill may do on your machine

- It reads case files only; it never writes to them.
- It writes results to a new output folder.
- `--force` deletes a non-empty output folder only after its guards pass (no spec, case, skill, cwd, home or drive root inside it).
- `fetch_andes_docs.py` downloads about 8 MB from github.com, and only after asking you.

## Limitations

- Only ANDES 2.0.0 is verified.
- PSS/E RAW/DYR import and RL training are not verified.
- `python -m andes` always exits 0, so the skill never relies on its exit code.

## Contributing and issues

Run the unit tests and `doctor --smoke` (see Maintaining) before sending a change. When you open a GitHub issue, include the `doctor` output and your ANDES version.

## License

This skill is released under the MIT License (see LICENSE). ANDES is a separate GPL-3.0 project by CURENT and is not included; install it yourself and comply with its license and citation request. See `NOTICE.md`.
