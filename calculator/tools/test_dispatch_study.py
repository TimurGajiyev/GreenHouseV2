"""The custom dispatch study (app_dispatch) against the validated JSX runner.

app_dispatch.build() poses a scenario from the section's tables; chp_bess_suite
.scenario() is the builder jsx_case.py / jsx_render_check.py were checked with.
Fed the JSX's own day, units and rules, both must give the same operating cost
(within the MIP gap), and app_dispatch.account() must rebuild the solver's
objective line by line.

    python tools/test_dispatch_study.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app_dispatch as D
import chp_bess_suite as S
from reopt_core import model as M

FAIL: list[str] = []


def check(name, got, want, rtol):
    ok = abs(got - want) <= rtol * max(1.0, abs(want))
    print(f"  {'OK' if ok else 'XX'}  {name:<52} {got:>14,.0f}   vs {want:>14,.0f}")
    if not ok:
        FAIL.append(name)


def main():
    load = D._jsx_loads()["day"]
    price = [S.GRID] * len(load)
    bat = dict(kw=S.BESS_KW, kwh=S.BESS_KWH, rte=S.RTE, soc_min=S.SOC_MIN, soc_init=0.5,
               cyclic=True, wear=S.WEAR, grid_charge=False)
    presets = {"chp2": "2 units (Jenbacher + TEDOM)", "chp3": "3 units (+ КГУ-3)"}
    scen = D.default_scenarios().to_dict("records")
    for fk, preset in presets.items():
        units = D.default_units(preset)
        for sc, mode in zip(scen, "ABC"):
            print(f"\n{preset} · {sc[D.S_NAME]}")
            ours = M.solve(D.build(load, price, units, bat, sc), time_limit=300, mip_gap=1e-4)
            ref = M.solve(S.scenario(load, fk, mode), time_limit=300, mip_gap=1e-4)
            a = D.account(ours, price, units, S.WEAR if sc[D.S_BAT] else 0.0)
            r = S.account(ref, load)
            check("operating cost: section vs validated runner", a["total"], r["cost"], 1e-4)
            check("section's line-by-line cost vs its objective", a["total"], a["objective"], 1e-6)
            check("grid purchase kWh", a["grid_kwh"], r["grid_kwh"], 0.05)
    print("\n" + ("all dispatch-study checks passed" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
