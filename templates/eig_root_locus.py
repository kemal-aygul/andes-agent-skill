"""Eigenvalue and parameter-sweep template.

Eigenvalue ordering is solver- and case-dependent.  ``EIG_INDICES`` is therefore
intentionally empty: run the EIG report first, inspect it, and fill in the exact
indices you want on the root locus.  Hard-coded ranges from another case/version
are not silently reused.

Run from a fresh, empty working folder; creates ``eig-output``.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import andes

from _checks import assert_pflow, case_record, write_run_record

CASE = andes.get_case("kundur/kundur_full.xlsx")

# Fill after reviewing the generated EIG report for THIS case and ANDES version,
# e.g. EIG_INDICES = [4, 7, 12].  Positional indices into ss.EIG.mu are fragile.
EIG_INDICES: list[int] = []

OUT = Path("eig-output")
OUT.mkdir(exist_ok=False)

case = case_record(CASE)
ss = andes.load(CASE, output_path=str(OUT / "andes"))
ss.PFlow.run()
pflow = assert_pflow(ss)

ss.EIG.run()
mu = np.asarray(ss.EIG.mu, dtype=complex).reshape(-1)
if mu.size == 0:
    raise RuntimeError("EIG ran but produced no eigenvalues; inspect the EIG report before continuing.")

fig, _ = ss.EIG.plot(show=False)
fig.savefig(OUT / "s-plane.png", dpi=300, bbox_inches="tight")

checks = {
    "pflow": pflow,
    "eigenvalue_count": int(mu.size),
    "max_real_part": float(mu.real.max()),
    "eig_indices": list(EIG_INDICES),
}

if not EIG_INDICES:
    # Deliberate stop: do not guess which eigenvalues belong to the mode of interest.
    report_hint = str((OUT / "andes").resolve())
    write_run_record(
        OUT,
        case=case,
        checks=checks,
        status="blocked",
        notes=[
            "EIG_INDICES is empty. Review the generated EIG report in "
            f"{report_hint}, then fill the module-level EIG_INDICES list with the "
            "exact indices for this case and ANDES version.",
        ],
    )
    raise RuntimeError(
        "EIG_INDICES is empty. Inspect the EIG report generated for this case and set "
        "the module-level EIG_INDICES list before requesting a root-locus plot."
    )

invalid = [idx for idx in EIG_INDICES if not (0 <= int(idx) < mu.size)]
if invalid:
    raise RuntimeError(
        f"EIG_INDICES {invalid} are outside the available eigenvalue range 0..{mu.size - 1}."
    )

# Confirm model/parameter/idx against this exact case before reusing elsewhere.
ret = ss.EIG.sweep(ss.EXDC2.KA, 1, np.linspace(20, 200, 10))
fig, _ = ss.EIG.plot_root_loci(ret, EIG_INDICES)  # ANDES passes show=False internally
fig.savefig(OUT / "root-locus.png", dpi=300, bbox_inches="tight")

write_run_record(OUT, case=case, checks={**checks, "sweep_points": len(ret)})
print({"output": str(OUT.resolve()), "eigenvalue_count": int(mu.size), "eig_indices": EIG_INDICES})
