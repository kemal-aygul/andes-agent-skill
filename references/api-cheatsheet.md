# ANDES 2.0 API cheatsheet

Every signature below was checked against an installed ANDES 2.0.0 on 2026-10-26. Confirm against the installed version with `inspect.signature` when a different version is in use.

## Contents
- Core objects
- Loading and setup order
- Inspection
- Parameters and status
- PFlow
- TDS and events
- Setpoint APIs
- EIG
- SE
- CPF / QV
- Export and CLI
- Example thresholds

## Core objects

- `System` is the hub for models, groups, routines, the DAE and files.
- Registered objects live in `ss.models`, `ss.groups` and `ss.routines`.
- The routines are `ss.PFlow`, `ss.TDS`, `ss.EIG`, `ss.SE` and `ss.CPF`.
- `ss.dae.x/y/f/g/t` holds the current DAE state, and `ss.dae.ts` holds the time series.
- `ss.exit_code` is the TDS exit status; 0 means success.

## Loading and setup order

```python
import andes
ss = andes.load(andes.get_case("ieee14/ieee14.json"))            # built-in case
ss = andes.load("case.raw", addfile="case.dyr")                  # PSS/E
ss = andes.load("case.xlsx", no_output=True, default_config=True)
ss = andes.load("case.xlsx", config_option=["PV.pv2pq=1"])      # load-time options
```

Adding devices or changing the initial status requires `setup=False`:

```python
ss = andes.load(case, setup=False)
ss.add("Fault", dict(bus=5, tf=1.0, tc=1.1, rf=0.0, xf=1e-4))   # add(model, param_dict=None, **kwargs)
ss.setup()                                                        # once; no ss.add() afterwards
```

## Inspection

```python
ss.find_connected("Bus", 2)        # ieee14 -> {'PQ': ['PQ_1'], 'PV': [2], 'Line': ['Line_3', 'Line_4', 'Line_5', 'Line_1'],
                                   #            'GENROU': ['GENROU_2'], 'BusFreq': ['BusFreq_3']}  (model -> idx list)
ss.GENROU.as_df(vin=True)          # input (device-base) values
ss.GENROU.idx.v; ss.GENROU.idx2uid(1); ss.GENROU.doc()
```

## Parameters and status

```python
ss.GENROU.get("M", idx)                              # get(src, idx, attr='v', allow_none=False, default=0.0)
ss.GENROU.set("M", idx, 10.0, base="device")         # set(src, idx, value, attr='v', base=None)
ss.set_status("Line", "Line_5", 0)                   # System.set_status(model_or_group, idx, value)
ss.GENROU.M.v[:] = new_values                        # in-place array update; never rebind .v
```

`Model.alter()` is deprecated in 2.0 and raises a FutureWarning. Use `set(..., base="device")` for device-base input values.

## PFlow

```python
ss.PFlow.run()
assert ss.PFlow.converged              # the flag is authoritative, not the return value
v, a = ss.Bus.v.v, ss.Bus.a.v
```

## TDS and events

```python
ss.PFlow.run()
ss.TDS.config.tf = 10.0
ss.TDS.config.no_tqdm = 1
ss.TDS.run()
ok = ss.exit_code == 0 and abs(float(ss.dae.t) - 10.0) < 1e-6
omega = ss.TDS.get_timeseries(ss.GENROU.omega)       # DataFrame indexed by time
volts = ss.TDS.get_timeseries(ss.Bus.v)
```

Events are added before `setup()`:

```python
ss.add("Fault", dict(bus=5, tf=1.0, tc=1.1, rf=0.0, xf=1e-4))     # Fault params: bus tf tc xf(default 1e-4) rf u
ss.add("Toggle", dict(model="Line", dev="Line_5", t=1.0))
ss.add("Alter", dict(model="TGOV1", dev=1, src="pref0", t=1.0, method="+", amount=0.05))
```

To disable an existing event, call `ss.Toggle.set("u", idx, 0, base="device")` after `setup=False`, and only when the scenario requires it.

Multi-stage continuation (`TDS.reinit()` restarts from t=0):

```python
ss.TDS.config.tf = 1.0; ss.TDS.run()
ss.SynGen.set_paux(ss, gen_idx, 0.05)
ss.TDS.config.tf = 2.0; ss.TDS.run()
```

## Setpoint APIs

Group methods are called as `ss.<Group>.<method>(ss, idx, value)`.

| Method | Groups |
|---|---|
| `set_pref` | SynGen, RenGen, DG |
| `set_paux` | SynGen, DG |
| `set_vref` | SynGen |
| `set_qref` | RenGen, DG |
| `set_setpoint` | all groups |

When a dynamic model is attached, it can disable its static injection during TDS. With GENROU attached, a change to `PV.p0` has no effect, so target the governor/setpoint chain instead.

## EIG

```python
ss = andes.load(case)                  # fresh System, not one reused after TDS
ss.PFlow.run(); ss.EIG.run()
ret = ss.EIG.sweep(params, idxes, values)              # sweep(params, idxes, values)
ss.EIG.plot_root_loci(ret, eig_indices)                # pick indices after reading the EIG report
```

## SE

```python
from andes.se import Measurements
ss.PFlow.run()
m = Measurements(ss)
m.add_bus_voltage(sigma=0.01); m.add_bus_injection(sigma_p=0.02, sigma_q=0.03)
# also: add_bus_angle, add_line_flow, add
m.generate_from_pflow(seed=42)
ss.SE.run(measurements=m)                              # WLS (default)
ss.SE.chi_squared_test()                               # WLS only
from andes.se import lav
ss2.SE.run(measurements=m2, algorithm=lav)             # LAV on its own System
```

## CPF / QV

```python
ss.PFlow.run()
ss.CPF.run(load_scale=2.0)            # or p0_target=, q0_target=, pg_target= per device
ss.CPF.plot(bus_idx=14, show=False)
ss_qv = andes.load(case); ss_qv.PFlow.run()
ss_qv.CPF.run_qv(bus_idx=14, q_range=3.0)
ss_qv.CPF.plot_qv(show=False)
```

Enable Q limits at load time with `config_option=["PV.pv2pq=1"]`, and run cases with and without limits as separate jobs.

## Export and CLI

```python
andes.io.dump(ss, "xlsx", full_path="new_case.xlsx", overwrite=False)   # never onto the source
```

```text
andes run case.xlsx                      # use the `andes` console script
andes run case.xlsx -r tds --tf 20
andes run case.xlsx -r eig
andes run case.raw --addfile case.dyr -r tds
andes run *.xlsx -r tds --ncpu 4
andes prepare -i                         # regenerate numerical code after model changes
```

`python -m andes ...` always exits 0, whatever the outcome. Confirm results from logs or the output files, or use Python.

## Example thresholds

The manual's contingency tutorial uses speed limits of 0.95–1.05 pu and a voltage limit of 0.8 pu. These are illustrative only. In real work, replace them with values from the user, a grid code, a protection standard or a research protocol, and record that source as `basis`.
