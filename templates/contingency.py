"""N-1 TDS screening template with recorded per-contingency outcomes.

A contingency is not marked successful just because ``TDS.run()`` returned.
Each record stores the real ``exit_code``, final time, ``completed`` flag, and
the corresponding failure reason.  Define study-specific physical criteria
before treating a completed run as acceptable.

Run from a fresh, empty working folder; creates ``contingency-output``.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import andes

from _checks import assert_pflow, assert_tds_complete, case_record, write_run_record

CASE = andes.get_case("kundur/kundur_full.xlsx")
LINES = ["Line_0"]  # Start with one smoke-test contingency, then expand after review.
FINAL_TIME = 5.0
OUT = Path("contingency-output")
OUT.mkdir(exist_ok=False)

case = case_record(CASE)
records = []
for line_idx in LINES:
    ss = andes.load(CASE, setup=False, output_path=str(OUT / line_idx))
    for idx in list(ss.Toggle.idx.v):
        ss.Toggle.set("u", idx, 0)
    if line_idx not in list(ss.Line.idx.v):
        raise RuntimeError(f"{line_idx!r} is not a Line index in {case['path']}")
    ss.add("Toggle", model="Line", dev=line_idx, t=1.0)
    ss.setup()

    record = {"contingency": line_idx, "pflow": False, "completed": False,
              "exit_code": None, "t_end": None, "reason": None,
              "omega_max": None, "omega_min": None, "v_min": None}
    try:
        ss.PFlow.run()
        assert_pflow(ss)
        record["pflow"] = True
    except Exception as exc:
        record["reason"] = f"pflow: {type(exc).__name__}: {exc}"
        records.append(record)
        continue

    ss.TDS.config.tf = FINAL_TIME
    ss.TDS.config.no_tqdm = 1
    try:
        ss.TDS.run()
        tds = assert_tds_complete(ss, FINAL_TIME)
        record.update(completed=True, exit_code=tds["exit_code"], t_end=tds["t_end"])
        omega = ss.TDS.get_timeseries(ss.GENROU.omega)
        voltage = ss.TDS.get_timeseries(ss.Bus.v)
        record.update(omega_max=float(omega.max().max()), omega_min=float(omega.min().min()),
                      v_min=float(voltage.min().min()))
    except Exception as exc:
        # Record the actual TDS state instead of a hard-coded True/False outcome.
        record.update(
            exit_code=int(getattr(ss, "exit_code", 0)) if getattr(ss, "exit_code", None) is not None else None,
            t_end=float(getattr(ss.dae, "t", float("nan"))),
            reason=f"tds: {type(exc).__name__}: {exc}",
        )
    records.append(record)

pd.DataFrame(records).to_csv(OUT / "screening.csv", index=False)
all_completed = all(item["completed"] for item in records)
write_run_record(OUT, case=case, status="completed" if all_completed else "completed_with_failures",
                 checks={"final_time_s": FINAL_TIME, "contingencies": records})
print({"output": str(OUT.resolve()), "contingencies": records})
