"""Three-phase fault template using the required setup=False -> add -> setup order.

Run this file from a fresh, empty working folder; it creates ``tds-fault-output``
with ANDES outputs and a ``run_record.json`` that proves what actually ran.

``xf`` is the fault reactance in per unit.  Use the ANDES default (1e-4); a
near-zero value such as 1e-6 produced a numerical failure at fault inception on
Kundur in ANDES 2.0.0, which this template would (correctly) reject.
"""
import sys
from pathlib import Path

# Templates are executed directly from any working directory.  Resolve the
# helper module next to this file, not relative to the caller's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import andes

from _checks import assert_pflow, assert_tds_complete, case_record, write_run_record

CASE = andes.get_case("kundur/kundur_full.xlsx")
OUT = Path("tds-fault-output")
OUT.mkdir(exist_ok=False)

case = case_record(CASE)
ss = andes.load(CASE, setup=False, output_path=str(OUT / "andes"))

# kundur_full.xlsx ships a Toggle (Line_8 trip at t=2.0 s). Keep it unless the
# user's scenario excludes it, and state the choice in the report.
DISABLE_EXISTING_TOGGLES = True  # this demo studies the fault alone
if DISABLE_EXISTING_TOGGLES:
    for idx in list(ss.Toggle.idx.v):
        ss.Toggle.set("u", idx, 0)

# ANDES 2.0 default xf is 1e-4 pu.  bus=5 and the clearing times below were
# inspected for kundur_full.xlsx; re-resolve them for any other case.
ss.add("Fault", bus=5, tf=1.0, tc=1.1, rf=0.0, xf=1e-4)
ss.setup()

ss.PFlow.run()
pflow = assert_pflow(ss)

ss.TDS.config.tf = 5.0
ss.TDS.config.no_tqdm = 1
ss.TDS.run()
tds = assert_tds_complete(ss, 5.0)

ss.TDS.get_timeseries(ss.GENROU.omega).to_csv(OUT / "omega.csv", index_label="time_s")
write_run_record(OUT, case=case, checks={"pflow": pflow, "tds": tds})
print({"output": str(OUT.resolve()), "pflow": pflow, "tds": tds})
