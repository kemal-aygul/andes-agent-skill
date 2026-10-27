"""Standalone PFlow template. Inspect model fields before adapting to another case.

Run from a fresh, empty working folder; creates ``pflow-output``.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import math

import pandas as pd
import andes

from _checks import assert_pflow, case_record, write_run_record

CASE = andes.get_case("ieee14/ieee14.json")
OUT = Path("pflow-output")
OUT.mkdir(exist_ok=False)

andes.config_logger(stream_level=20)
case = case_record(CASE)
ss = andes.load(CASE, output_path=str(OUT / "andes"))

ss.PFlow.run()
pflow = assert_pflow(ss)

rows = [
    {"idx": idx, "name": name, "v_pu": float(v), "a_rad": float(a), "a_deg": math.degrees(float(a))}
    for idx, name, v, a in zip(ss.Bus.idx.v, ss.Bus.name.v, ss.Bus.v.v, ss.Bus.a.v)
]
pd.DataFrame(rows).to_csv(OUT / "bus-results.csv", index=False)
write_run_record(OUT, case=case, checks={"pflow": pflow},
                 extra={"bus_count": len(rows), "min_voltage_pu": min(row["v_pu"] for row in rows)})
print({"output": str(OUT.resolve()), "pflow": pflow, "bus_count": len(rows)})
