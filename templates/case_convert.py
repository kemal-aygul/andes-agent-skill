"""PSS/E RAW + DYR to a new ANDES XLSX case; never overwrites the source files.

Set ``RAW`` and ``DYR`` to inspected existing files before running.  The source
hashes, converted hash, imported model counts, and PFlow result are recorded in
``converted-case/run_record.json``.

Run from a fresh, empty working folder; creates ``converted-case``.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import andes

from _checks import assert_pflow, case_record, write_run_record

RAW = Path("case.raw").resolve()
DYR = Path("case.dyr").resolve()
OUT = Path("converted-case")
TARGET = OUT / "case_converted.xlsx"

if not RAW.is_file() or not DYR.is_file():
    raise FileNotFoundError(
        "Set RAW and DYR to inspected existing files before execution; "
        f"looked for {RAW} and {DYR}."
    )

OUT.mkdir(exist_ok=False)
source_raw = case_record(RAW)
source_dyr = case_record(DYR)

ss = andes.load(str(RAW), addfile=str(DYR), output_path=str(OUT / "andes-output"))
ss.PFlow.run()
pflow = assert_pflow(ss)

model_counts = {name: int(model.n) for name, model in ss.models.items() if getattr(model, "n", 0)}

andes.io.dump(ss, "xlsx", str(TARGET), overwrite=False)
target = case_record(TARGET)

checks = {"pflow": pflow, "imported_models": model_counts}
write_run_record(OUT, case=source_raw, checks=checks,
                 extra={"addfile": source_dyr, "converted": target})
print({"written": str(TARGET), "source_raw": source_raw["path"], "source_dyr": source_dyr["path"],
       "pflow": pflow})
