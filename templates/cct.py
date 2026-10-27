"""Critical-clearing-time search with explicit outcome classification.

Every trial returns exactly one of:

``stable``
    PFlow and TDS both completed and the caller-supplied criterion says stable.
``unstable``
    PFlow and TDS both completed and the caller-supplied criterion says unstable.
``numerical_failure``
    PFlow or TDS did not complete (non-zero ``System.exit_code``, short final
    time, non-finite state, or an exception).  This is *never* treated as stable
    and never used to update the search bounds as if it were a physical result.

The shipped ``__main__`` demo uses an illustrative rotor-angle-spread criterion
for the Kundur case.  Replace ``demo_stability`` with a study-specific criterion
and inspect ``FAULT_BUS``/times before using the result scientifically.

Run from a fresh, empty working folder; creates ``cct-output``.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import andes

from _checks import assert_pflow, assert_tds_complete, case_record, write_run_record

CASE = andes.get_case("kundur/kundur_full.xlsx")
FAULT_BUS = 5  # Inspect the case; do not assume for another network.
OUT = Path("cct-output")

STABLE = "stable"
UNSTABLE = "unstable"
NUMERICAL_FAILURE = "numerical_failure"


def _tds_state(ss) -> dict:
    return {
        "exit_code": getattr(ss, "exit_code", None),
        "t_end": float(getattr(getattr(ss, "dae", None), "t", float("nan"))),
    }


def run_fault(case_file, bus_idx, t_fault, duration, final_time, stability_fn, *, output_path=None):
    """Run one fault trial and classify it without conflating failure and instability."""
    ss = andes.load(case_file, setup=False, output_path=str(output_path) if output_path else None)
    for idx in list(ss.Toggle.idx.v):
        ss.Toggle.set("u", idx, 0)
    ss.add("Fault", bus=bus_idx, tf=t_fault, tc=t_fault + duration, xf=1e-4)
    ss.setup()

    record = {"duration_s": float(duration), "classification": NUMERICAL_FAILURE}
    try:
        ss.PFlow.run()
        assert_pflow(ss)
    except Exception as exc:
        record.update(stage="pflow", reason=f"{type(exc).__name__}: {exc}", **_tds_state(ss))
        return record

    ss.TDS.config.tf = float(final_time)
    ss.TDS.config.no_tqdm = 1
    # Disable ANDES's built-in automatic criteria: this template classifies every
    # trial explicitly, and a criterion-triggered stop is a numerical failure.
    ss.TDS.config.criteria = 0
    try:
        ss.TDS.run()
        tds = assert_tds_complete(ss, final_time)
    except Exception as exc:
        record.update(stage="tds", reason=f"{type(exc).__name__}: {exc}", **_tds_state(ss))
        return record

    verdict = stability_fn(ss)
    record.update(
        classification=STABLE if bool(verdict) else UNSTABLE,
        stage="completed",
        t_end=tds["t_end"],
        exit_code=tds["exit_code"],
        stable=bool(verdict),
    )
    return record


def binary_search_cct(case_file, bus_idx, stability_fn, *, low=0.05, high=0.50, tol=0.01, max_iter=12,
                      t_fault=1.0, final_time=5.0, output_root=None):
    """Bisect the clearing time between tested bounds.

    The bracket is accepted only after ``low`` was observed stable and ``high``
    unstable.  The result is conclusive only when no numerical failure occurred
    and the final bracket is within ``tol``; otherwise ``cct_s`` is None.
    """
    history = []
    reason = None

    def trial(duration, tag):
        trial_out = None if output_root is None else Path(output_root) / f"trial-{tag}-{duration:.4f}"
        record = run_fault(case_file, bus_idx, t_fault, duration, final_time, stability_fn, output_path=trial_out)
        history.append(record)
        return record["classification"]

    low_class = trial(low, "low")
    if low_class != STABLE:
        reason = f"lower bound {low} s is {low_class}, not stable; widen the bracket downwards"
    else:
        high_class = trial(high, "high")
        if high_class != UNSTABLE:
            reason = f"upper bound {high} s is {high_class}, not unstable; widen the bracket upwards"
    if reason is None:
        for iteration in range(max_iter):
            if high - low <= tol:
                break
            mid = (low + high) / 2
            classification = trial(mid, f"{iteration:03d}")
            if classification == NUMERICAL_FAILURE:
                # Do not move either bound and do not report a CCT.
                reason = f"numerical failure at {mid:.4f} s"
                break
            if classification == STABLE:
                low = mid
            else:
                high = mid
    if reason is None and high - low > tol:
        reason = f"bracket {high - low:.4f} s still wider than tol={tol} s after max_iter={max_iter}"
    conclusive = reason is None
    return {
        "cct_s": float(low) if conclusive else None,
        "conclusive": conclusive,
        "inconclusive_reason": reason,
        "lower_bound_s": float(low),
        "upper_bound_s": float(high),
        "history": history,
        "counts": {
            "stable": sum(item["classification"] == STABLE for item in history),
            "unstable": sum(item["classification"] == UNSTABLE for item in history),
            "numerical_failure": sum(item["classification"] == NUMERICAL_FAILURE for item in history),
        },
    }


def demo_stability(ss) -> bool:
    """Illustrative criterion only: final rotor-angle spread below 2 rad.

    This is *not* a general transient-stability definition.  Replace it with a
    criterion justified by the study (for example, angle separation from a
    reference machine, frequency nadir, or a verified critical-machine pair).
    """
    delta = np.asarray(ss.TDS.get_timeseries(ss.GENROU.delta), dtype=float)
    return bool(np.max(delta[-1]) - np.min(delta[-1]) <= 2.0)


def main() -> int:
    OUT.mkdir(exist_ok=False)
    case = case_record(CASE)
    result = binary_search_cct(
        CASE,
        FAULT_BUS,
        demo_stability,
        tol=0.01,
        max_iter=6,
        output_root=OUT,
    )
    write_run_record(
        OUT,
        case=case,
        status="completed" if result["conclusive"] else "inconclusive",
        checks={
            "search": result,
            "criterion": "demo_stability: final rotor-angle spread <= 2 rad (illustrative only)",
        },
    )
    print({"output": str(OUT.resolve()), "cct_s": result["cct_s"], "conclusive": result["conclusive"],
           "counts": result["counts"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
