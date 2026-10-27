# Recipes and troubleshooting

## Contents
- Study recipes
- Custom model development
- Troubleshooting

## Study recipes

- **RAW/DYR import and saving a new case**
  1. Load the RAW and DYR files together.
  2. Save the parser warnings and the model inventory.
  3. Confirm the import with a PFlow run.
  4. Write the result only to a new file with `andes.io.dump(..., "xlsx", ...)`; never overwrite the source.
  5. Compare dynamic model counts, disabled or unassigned models, and base PFlow results against the source tool (`templates/case_convert.py`).
- **PFlow voltage screening:** take the inventory, run PFlow, build the Bus table, then apply the user's limits as criteria and cite where each limit comes from.
- **Three-phase fault**
  1. Load with `setup=False`.
  2. Disable unwanted existing events.
  3. Add a `Fault` (realistic `xf`).
  4. Call `setup()`.
  5. Run PFlow, then TDS.
  6. Output speed, angle, voltage and power (`templates/tds_fault.py`).
- **Line trip and reclose:** two `Toggle` events on the same `Line.idx` (`templates/tds_toggle.py`).
- **Generator loss and frequency**
  1. Resolve the dynamic generator or group from the connections.
  2. Trip it with `Toggle`.
  3. Confirm the nominal frequency from the case.
  4. Ask the user to define the nadir, RoCoF and recovery criteria.
- **Multi-stage AGC/setpoint:** run an equilibrium stage, apply `SynGen.set_paux` or a group `set_setpoint`, continue the simulation, then run a restore stage (`templates/tds_multistage.py`, `examples/multistage-setpoint.json`).
- **Parameter sweep:** for small sweeps, use multiple jobs or a controlled loop. For large sweeps, use independent case files, bounded parallel CLI runs, hashes, and a staged smoke test. Each point gets a fresh System.
- **EIG root locus:** load a fresh System, run PFlow and then EIG. Check the parameter and idx live, and give an explicit list of values. Never invent which eigenvalue indices to track (`templates/eig_root_locus.py` refuses an empty `EIG_INDICES`).
- **SE**
  - Define the measurement types, placement, sigma and seed.
  - Run a zero-noise sanity check first.
  - Specify the bad-data index and the sigma multiplier.
  - Compare WLS and LAV on the same measurement set, each on its own System.
- **CPF/PV/QV:** start with PFlow. Choose uniform or per-device targets, plus the parameterization and `stop_at`. Run the cases with and without Q limits as separate jobs, and state how a weak bus is defined.
- **N-1:** use a fresh System and a separate scenario for each element. Keep numerical completion (exit code, end time) separate from physical acceptance, which is decided by the user's criteria (`templates/contingency.py`).
- **CCT**
  - Settings: a predefined stability criterion, a search interval, a tolerance, a maximum number of iterations, and a record of every trial.
  - Classification: each trial is classed as stable, unstable or numerical_failure, and a numerical failure never narrows the bracket.
  - Report: say how sensitive the result is to the criterion and the time step (`templates/cct.py`).
- **RL**
  - Define the observation space and its scaling, and the action space with its setpoints and limits.
  - Define the reward and the termination rule.
  - Define the disturbance distribution and how reset and seeding work.
  - Set the training budget, and compare against a baseline controller.
  - Needs `andes[rl]`, and training goes through an approval gate (`templates/rl_environment.py`).

## Custom model development

Use this only when the user explicitly asks for a new model (`templates/custom_model.py` is a skeleton).

1. Study the source and `doc()` output of the closest existing model in the same group.
2. Put the input parameters in `ModelData`. Put the flags, variables, services, discrete elements and blocks in `Model`.
3. Write the equations as ANDES symbolic strings. Never hand-code the Jacobian.
4. Wire references explicitly with `IdxParam`, `ExtParam`, `ExtAlgeb`, `ExtState` and the group requirements.
5. Verify the initialization equations separately.
6. Register the model in the right module and group.
7. Regenerate the numerical code with `andes prepare -i`. This edits the ANDES install, so it goes through an approval gate.
8. Test in this order: import and registration, parameter validation, PFlow, TDS initialization, a flat run, a disturbance, then comparison against a reference.
9. Add a pytest test, a small example case and the expected tolerances.
10. Label equations the manual does not support as the researcher's own definition, not as an ANDES feature.

## Troubleshooting

**ANDES does not import**
- Activate the right conda env or venv.
- Run `python -c "import andes; print(andes.__version__)"`.
- On Windows, compare `where python` with `where andes`.
- For DLL errors, prefer a Conda or Miniforge environment.
- Remove duplicate ANDES copies by hand; the skill never does this itself.

**PFlow does not converge**
- Keep the DEBUG residual history as evidence.
- Likely causes:
  - zero impedance or bad topology;
  - islands or slack problems;
  - an infeasible P/Q balance;
  - a poor initial guess;
  - Q limits.
- Any settings change is a separate variant that the user approves.

**TDS init or step failure**
- Confirm that PFlow converged.
- Test initialization alone with `ss.TDS.init()`.
- Do a flat run without events.
- Check the fault impedance: an `xf` that is too small, such as 1e-6, collapses the step size.
- Try a different step size or iteration count as a separate variant.
- Check the chain between the dynamic and static models.

**An expected change does not show**
- The change may have been written to a static model that TDS disabled.
- With GENROU attached, target the governor/setpoint chain instead of `PV.p0`.
- With FLoad or ZIP attached, target the dynamic load instead of the static PQ.

**Plot errors**
- For LaTeX problems, use `latex=False` in the ANDES plotter.
- The runtime draws its time-series plots with plain Matplotlib.

**EIG problems**
- Load a fresh System and run PFlow first.
- Look for zero time constants or degenerate equations in the model docs.

**SE problems**
- Measurement redundancy does not guarantee observability.
- Each island needs an angle reference.
- Chi-square only tests whether bad data is present.
- LAV is more robust but can be slower.

**CPF problems**
- Confirm the PFlow starting point.
- `natural` parameterization can become singular at the nose; pseudo-arclength is usually more robust.
- Enable Q limits at load time.

**Exit code looks fine but the results are wrong**
- `python -m andes` always exits 0.
- Check `ss.exit_code` and the end time, or use the runtime and its `status.json`.
