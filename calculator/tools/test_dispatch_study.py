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
    # the chart's veil and strip: hourly savings must add up to the cost difference
    print("\nsavings decomposition, 2 units, C against B and against A")
    units = D.default_units(presets["chp2"])
    out = {"price": price, "units": units, "bat": bat}
    runs = {}
    for sc in scen:
        inp = D.build(load, price, units, bat, sc)
        res = M.solve(inp, time_limit=300, mip_gap=1e-4)
        runs[sc[D.S_NAME]] = {"name": sc[D.S_NAME], "res": res, "battery": inp.storage.enabled,
                              "acc": D.account(res, price, units, S.WEAR if sc[D.S_BAT] else 0.0),
                              "hourly": D.hourly(res, price, units,
                                                 S.WEAR if inp.storage.enabled else 0.0)}
    a, b, c = (runs[s[D.S_NAME]] for s in scen)
    for base in (b, a):
        sv = D.savings(c, base, out)
        # a cyclic battery ends where it started: the SoC correction over the whole window is 0
        total = sum(sv["save_e"]) + sum(sv["save_s"])
        check(f"sum of hourly savings vs {base['name']}", total,
              base["acc"]["total"] - c["acc"]["total"], 1e-6)
    check("spread (mean grid price - mean unit cost)", sv["spread"], S.GRID - S.CHP_COST, 1e-9)
    # starts per day: the JSX week, 3 units, 90% rule starts engines up to 3 times a day
    print("\nmax starts per day, 3 units, 90% rule, the JSX week")
    week = D._jsx_loads()["week"]
    wprice = [S.GRID] * len(week)
    units3 = D.default_units(presets["chp3"])
    b_rule = dict(scen[1])
    free = M.solve(D.build(week, wprice, units3, bat, b_rule), time_limit=300, mip_gap=1e-4)
    fa = D.account(free, wprice, units3, 0.0)
    print(f"  no cap: {fa['starts']} starts, busiest day {fa['starts_day_max']}, cost {fa['total']:,.0f}")
    check("per-day starts add up to the solver's start count",
          sum(sum(u["starts_by_day"] or []) for u in free["sizes"]["fueltech_units"]),
          fa["starts"], 0)
    for cap in (1, 0):
        capped = dict(b_rule, **{D.S_MAXST: cap})
        r = M.solve(D.build(week, wprice, units3, bat, capped), time_limit=300, mip_gap=1e-4)
        a = D.account(r, wprice, units3, 0.0)
        worst = max(max(u["starts_by_day"] or [0]) for u in r["sizes"]["fueltech_units"])
        print(f"  cap {cap}/day per unit: {a['starts']} starts, worst unit-day {worst}, "
              f"cost {a['total']:,.0f}")
        ok = worst <= cap and a["total"] >= fa["total"] - 1.0 and r["status"] == "Optimal"
        print(f"  {'OK' if ok else 'XX'}  cap {cap} holds on every unit-day and costs no less")
        if not ok:
            FAIL.append(f"max starts cap {cap}")
    blank = dict(b_rule, **{D.S_MAXST: float("nan")})
    r = M.solve(D.build(week, wprice, units3, bat, blank), time_limit=300, mip_gap=1e-4)
    check("blank cap = no cap (same cost)", D.account(r, wprice, units3, 0.0)["total"],
          fa["total"], 1e-6)
    print("\n" + ("all dispatch-study checks passed" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
