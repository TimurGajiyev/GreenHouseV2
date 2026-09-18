"""Check the local REopt.jl install, then use it as the reference for this calculator.

Step 1 runs REopt's own test scenarios through the local REopt.jl and asserts
what runtests.jl asserts, at runtests.jl's solver settings. If these pass, the
install is REopt as its authors test it.

Step 2 poses the same scenarios to this calculator (tools/test_reopt_jl_suite.py)
and prints the three numbers side by side: runtests expectation, REopt.jl here,
this calculator.

    python tools/check_reopt_jl.py            both steps
    python tools/check_reopt_jl.py --jl-only  step 1 only
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import test_reopt_jl_suite as S          # noqa: E402
from tools.reopt_jl import run_reopt_jl             # noqa: E402

FAIL: list[str] = []


def check(name, got, want, *, atol=None, rtol=None):
    tol = atol if atol is not None else abs(want) * rtol
    ok = abs(got - want) <= tol + 1e-12
    print(f"  {'OK' if ok else 'XX'}  {name:<48} {got:>16,.4f}   runtests {want:>16,.4f}")
    if not ok:
        FAIL.append(name)
    return got


def jl_pv_storage():
    print("\nSolar and Storage (runtests.jl:394) -- HiGHS defaults, no BAU")
    r = run_reopt_jl(S.scenario("pv_storage.json"), bau=False, gap=1e-4, time_limit=1800)
    return {"pv": check("PV size_kw", r["PV"]["size_kw"], 216.6667, atol=0.01),
            "lcc": check("Financial lcc", r["Financial"]["lcc"], 1.2391786e7, rtol=1e-5),
            "kw": check("ElectricStorage size_kw", r["ElectricStorage"]["size_kw"], 49.0, atol=0.1),
            "kwh": check("ElectricStorage size_kwh", r["ElectricStorage"]["size_kwh"], 83.3, atol=0.1)}


def jl_chp_payback():
    print("\nCHP Proforma Metrics (runtests.jl:1501) -- mip_rel_gap 0.01, with BAU")
    r = run_reopt_jl(S.scenario("chp_payback.json"), bau=True, gap=0.01, time_limit=1800)
    return {"payback": check("Financial simple_payback_years", r["Financial"]["simple_payback_years"],
                             8.31, atol=0.02),
            "irr": r["Financial"].get("internal_rate_of_return", float("nan"))}


def jl_chp_supp():
    print("\nCHP Supplementary firing and standby, part 1 (runtests.jl:1293)")
    d = S.scenario("chp_supplementary_firing.json")
    d["CHP"]["supplementary_firing_capital_cost_per_kw"] = 10000
    d["ElectricLoad"]["loads_kw"] = [800.0] * 8760
    d["ElectricLoad"]["year"] = 2022
    d["DomesticHotWaterLoad"]["fuel_loads_mmbtu_per_hour"] = [6.0] * 8760
    d["SpaceHeatingLoad"]["fuel_loads_mmbtu_per_hour"] = [6.0] * 8760
    r = run_reopt_jl(d, bau=False, gap=1e-4, time_limit=1800)
    check("CHP size_kw", r["CHP"]["size_kw"], 800.0, atol=1e-6)
    check("CHP size_supplemental_firing_kw", r["CHP"]["size_supplemental_firing_kw"], 0.0, atol=1e-6)
    check("CHP annual_electric_production_kwh", r["CHP"]["annual_electric_production_kwh"], 800 * 8760, rtol=1e-5)
    check("CHP annual_thermal_production_mmbtu", r["CHP"]["annual_thermal_production_mmbtu"],
          800 * (0.4418 / 0.3573) * 8760 / 293.07107, rtol=1e-5)
    check("lifecycle_demand_cost_after_tax", r["ElectricTariff"]["lifecycle_demand_cost_after_tax"], 0.0, atol=1e-6)


def main():
    jl = {"pv_storage": jl_pv_storage(), "chp_payback": jl_chp_payback()}
    jl_chp_supp()
    if "--jl-only" not in sys.argv:
        print("\n" + "=" * 100 + "\nThis calculator on the same scenarios")
        S.case_pv_storage()
        S.case_chp_payback()
        o = S.RESULTS
        print("\n" + "=" * 100)
        print(f"  {'':<34}{'REopt.jl (local)':>20}{'this calculator':>20}{'diff':>14}")
        rows = [("pv_storage  PV kW", jl["pv_storage"]["pv"], o["pv_storage"]["pv"]),
                ("pv_storage  battery kW", jl["pv_storage"]["kw"], o["pv_storage"]["kw"]),
                ("pv_storage  battery kWh", jl["pv_storage"]["kwh"], o["pv_storage"]["kwh"]),
                ("pv_storage  LCC $", jl["pv_storage"]["lcc"], o["pv_storage"]["lcc"]),
                ("chp_payback payback yrs", jl["chp_payback"]["payback"], o["chp_payback"]["payback"]),
                ("chp_payback IRR", jl["chp_payback"]["irr"], o["chp_payback"]["irr"])]
        for lab, a, b in rows:
            print(f"  {lab:<34}{a:>20,.4f}{b:>20,.4f}{b - a:>+14,.4f}")
        FAIL.extend(S.FAIL)
    print("\n" + ("all checks passed" if not FAIL else f"{len(FAIL)} FAILURE(S): {FAIL}"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
