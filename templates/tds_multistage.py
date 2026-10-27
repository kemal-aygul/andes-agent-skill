"""Multi-stage setpoint template using the SynGen group API.

Each stage is a separate ``TDS.run()`` that resumes from the previous stage.
The helper is called after every stage so an incomplete continuation cannot be
mistaken for a finished study.

Run from a fresh, empty working folder; creates ``tds-multistage-output``.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import andes

from _checks import assert_pflow, assert_tds_complete, case_record, write_run_record

CASE = andes.get_case("kundur/kundur_full.xlsx")
OUT = Path("tds-multistage-output")
OUT.mkdir(exist_ok=False)

case = case_record(CASE)
ss = andes.load(CASE, setup=False, output_path=str(OUT / "andes"))

for idx in list(ss.Toggle.idx.v):
    ss.Toggle.set("u", idx, 0)
ss.setup()

ss.PFlow.run()
pflow = assert_pflow(ss)

# Resolve a generator with a turbine governor after setup; do not assume an idx.
governed = [
    idx
    for idx in ss.SynGen.uid
    if idx in getattr(ss.TurbineGov, "uid", {})
]
if not governed:
    raise RuntimeError("No SynGen device with a TurbineGov governor; set_paux cannot be applied.")
GEN_IDX = governed[0]

stages = []


def run_stage(until: float) -> dict:
    ss.TDS.config.tf = float(until)
    ss.TDS.config.no_tqdm = 1
    ss.TDS.run()
    summary = assert_tds_complete(ss, until)
    stages.append({"until": float(until), **summary})
    return summary


# Stage 1: pre-disturbance baseline.
ss.SynGen.set_paux(ss, GEN_IDX, 0.0)
run_stage(1.0)

# Stage 2: add a 0.05 pu auxiliary power step on the governed generator.
ss.SynGen.set_paux(ss, GEN_IDX, 0.05)
run_stage(2.0)

# Stage 3: remove the auxiliary signal and let the system settle.
ss.SynGen.set_paux(ss, GEN_IDX, 0.0)
run_stage(10.0)

ss.TDS.get_timeseries(ss.GENROU.omega).to_csv(OUT / "omega.csv", index_label="time_s")
write_run_record(OUT, case=case, checks={"pflow": pflow, "stages": stages},
                 extra={"generator_idx": GEN_IDX})
print({"output": str(OUT.resolve()), "generator_idx": GEN_IDX, "pflow": pflow, "stages": stages})
