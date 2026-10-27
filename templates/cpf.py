"""PV/QV continuation power-flow template with explicit pre-CPF checks.

Run from a fresh, empty working folder; creates ``cpf-output``.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import andes

from _checks import assert_pflow, case_record, write_run_record

CASE = andes.get_case("ieee14/ieee14.json")
OUT = Path("cpf-output")
OUT.mkdir(exist_ok=False)

case = case_record(CASE)

# --- PV curve -----------------------------------------------------------------
ss = andes.load(CASE, output_path=str(OUT / "andes"))
ss.PFlow.run()
pflow_pv = assert_pflow(ss)
pv_returned = ss.CPF.run(load_scale=2.0)
pv_converged = bool(getattr(ss.CPF, "converged", False))
fig, _ = ss.CPF.plot(bus_idx=14, show=False)
fig.savefig(OUT / "pv-curve.png", dpi=300, bbox_inches="tight")

# --- QV curve: always use a fresh System --------------------------------------
ss_qv = andes.load(CASE, output_path=str(OUT / "andes-qv"))
ss_qv.PFlow.run()
pflow_qv = assert_pflow(ss_qv)
qv_returned = ss_qv.CPF.run_qv(bus_idx=14, q_range=3.0)
qv_converged = bool(getattr(ss_qv.CPF, "converged", False))
fig, _ = ss_qv.CPF.plot_qv(show=False)
fig.savefig(OUT / "qv-curve.png", dpi=300, bbox_inches="tight")

checks = {
    "pflow_pv": pflow_pv,
    "pflow_qv": pflow_qv,
    "cpf_pv": {"returned": pv_returned, "converged": pv_converged},
    "cpf_qv": {"returned": qv_returned, "converged": qv_converged},
}
write_run_record(OUT, case=case, checks=checks)
print({"output": str(OUT.resolve()), "checks": checks})
