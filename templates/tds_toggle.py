"""Line trip and reclosure template with explicit PFlow/TDS completion checks.

Run from a fresh, empty working folder; creates ``tds-toggle-output``.
``LINE_IDX`` must be a line index that exists in the inspected case
(``kundur_full.xlsx`` contains ``Line_0`` ... ``Line_14``).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import andes

from _checks import assert_pflow, assert_tds_complete, case_record, write_run_record

CASE = andes.get_case("kundur/kundur_full.xlsx")
LINE_IDX = "Line_5"  # Resolve from the real case; do not guess for another case.
OUT = Path("tds-toggle-output")
OUT.mkdir(exist_ok=False)

case = case_record(CASE)
ss = andes.load(CASE, setup=False, output_path=str(OUT / "andes"))

# Suppress pre-existing events only after confirming them in the case.
for idx in list(ss.Toggle.idx.v):
    ss.Toggle.set("u", idx, 0)
if LINE_IDX not in list(ss.Line.idx.v):
    raise RuntimeError(f"{LINE_IDX!r} is not a Line index in {case['path']}")

ss.add("Toggle", model="Line", dev=LINE_IDX, t=1.0)  # trip
ss.add("Toggle", model="Line", dev=LINE_IDX, t=1.5)  # reclose
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
