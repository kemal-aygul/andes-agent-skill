"""WLS/LAV state-estimation template with reproducible measurements.

The chi-squared test is defined for the weighted-least-squares (WLS) residual
model.  It is called only for the WLS run, never after LAV.

Run from a fresh, empty working folder; creates ``se-output``.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import andes
from andes.se import Measurements, lav

from _checks import assert_pflow, case_record, write_run_record

CASE = andes.get_case("ieee14/ieee14.json")
OUT = Path("se-output")
OUT.mkdir(exist_ok=False)

case = case_record(CASE)


def make_measurements(system, seed=42):
    measurements = Measurements(system)
    measurements.add_bus_voltage(sigma=0.01)
    measurements.add_bus_injection(sigma_p=0.02, sigma_q=0.03)
    measurements.generate_from_pflow(seed=seed)
    return measurements


# --- WLS ----------------------------------------------------------------------
ss = andes.load(CASE, output_path=str(OUT / "andes-wls"))
ss.PFlow.run()
pflow_wls = assert_pflow(ss)
measurements = make_measurements(ss)
# Optional controlled outlier: measurements.z[0] += 10 * measurements.sigma[0]
ss.SE.run(measurements=measurements)
if not bool(ss.SE.converged):
    raise RuntimeError("WLS state estimation did not converge; chi-squared results would be invalid.")
wls_chi = ss.SE.chi_squared_test()
wls_passed, wls_J, wls_threshold, wls_dof = wls_chi
pd.DataFrame({"bus_idx": ss.Bus.idx.v, "v_est": ss.SE.v_est, "a_est_rad": ss.SE.a_est}).to_csv(
    OUT / "state-wls.csv", index=False
)

# --- LAV (fresh System and fresh measurements) --------------------------------
ss_lav = andes.load(CASE, output_path=str(OUT / "andes-lav"))
ss_lav.PFlow.run()
pflow_lav = assert_pflow(ss_lav)
measurements_lav = make_measurements(ss_lav)
ss_lav.SE.run(measurements=measurements_lav, algorithm=lav)
if not bool(ss_lav.SE.converged):
    raise RuntimeError("LAV state estimation did not converge; review observability and measurement placement.")
pd.DataFrame({"bus_idx": ss_lav.Bus.idx.v, "v_est": ss_lav.SE.v_est, "a_est_rad": ss_lav.SE.a_est}).to_csv(
    OUT / "state-lav.csv", index=False
)

checks = {
    "pflow_wls": pflow_wls,
    "pflow_lav": pflow_lav,
    "wls": {
        "converged": True,
        "measurement_count": int(len(measurements.z)),
        "chi_squared_passed": bool(wls_passed),
        "J": float(wls_J),
        "threshold": float(wls_threshold),
        "dof": int(wls_dof),
    },
    "lav": {"converged": True, "measurement_count": int(len(measurements_lav.z))},
}
write_run_record(OUT, case=case, checks=checks)
print({"output": str(OUT.resolve()), "wls": checks["wls"], "lav": checks["lav"]})
