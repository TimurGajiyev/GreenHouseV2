"""The six service columns as they were, and the two that replace them, on ЖКПЗ.

    python calculator/tools/service_columns_study.py      # about 45 min: eight cases
                                                          # run to the solver's 300 s limit

Part 1 poses the old six columns exactly as the page did (SERVICE_IN_CORE =
True) on 14 measured days, both value sets, in one window and day by day, and
prints what each did: the objective, how far it is from the accounts, running
hours, starts and the services the solver placed. REPORT.md, "Revised
02.11.2026 (3)", quotes it. Part 2 sets the two columns (one service every N
running hours at C, priced C / N per running hour) against the core's own
running-hour trigger on windows short enough for the trigger to solve.
"""

import os, sys, time, warnings, logging
warnings.filterwarnings("ignore"); logging.disable(logging.WARNING)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app_dispatch as D
import real_data as RD
import year_study as Y
from reopt_core import model as M

PRESET = next(p for p in D.unit_presets() if "ЖКПЗ" in p)
Y_ = RD.year(RD.ZHKPZ)


def setup(values, start=0, hours=24 * 14):
    V = D.VALUES[values]
    if values == D.VALUES_ZH:
        w0, _ = D.zh_window(list(Y_["time"]))
        start += w0
    load = Y_["load"][start:start + hours]
    meas = {"gpu_units": [g[start:start + hours] for g in Y_["gpu_units"]]}
    units = D.default_units(PRESET, values)
    bat = dict(kw=V["b_kw"], kwh=V["b_kwh"], rte=0.88, soc_min=V["soc_min"] / 100.0,
               soc_init=0.5, cyclic=True, wear=V["wear"], grid_charge=False,
               capex=V["capex"], om_fraction=0.0, replace_year=0, replace_fraction=0.0,
               own_kw=V["own_kw"])
    avail = D.measured_availability(meas, units) if V["avail"] == 0 else None
    sc = dict(D.SCENARIO_LIBRARY["A · ГПУ от 50%, без батареи"])
    return dict(load=load, price=[V["grid"]] * len(load), units=units, bat=bat,
                avail=avail, sc=sc, values=values)


def solve(c, units, mode="window", gap=0.0005):
    t0 = time.time()
    try:
        if mode == "window":
            inp = D.build(c["load"], c["price"], units, c["bat"], c["sc"], avail=c["avail"])
            res = M.solve(inp, time_limit=300, mip_gap=gap)
        else:
            typ = Y.every_day(c["load"], c["price"])
            res = Y.solve_year(None, c["load"], c["price"], typ.k, typical=typ,
                               day_pose=lambda k, dl, dp: D.build(
                                   dl, dp, units, c["bat"], c["sc"],
                                   avail=D.day_availability(c["avail"], typ, k)),
                               time_limit=300, mip_gap=gap)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:160]}", "sec": time.time() - t0}
    acc = D.account(res, c["price"], units, c["bat"]["wear"])
    rows = res["sizes"]["fueltech_units"]
    return {"obj": res["objective_lifecycle_cost"], "acc": acc["total"],
            "run_h": acc["unit_hours"], "starts": acc["starts"],
            "services": {r["name"][:6]: (len(r["maintenance_starts"])
                                         if r.get("maintenance_starts") is not None else None)
                         for r in rows},
            "sec": time.time() - t0, "status": res["status"]}


def with_(units, **kw):
    u = units.copy()
    for k, v in kw.items():
        u.loc[:, k] = v
    return u


def show(tag, r, base=None):
    if "error" in r:
        print(f"  {tag:<58} ERROR  {r['error']}")
        return
    d = "" if base is None or "obj" not in base else f"  Δobj {r['obj'] - base['obj']:+13,.0f}"
    gap = r["obj"] - r["acc"]
    print(f"  {tag:<58} obj {r['obj']:14,.0f}{d}  obj−account {gap:+11,.0f}  run_h {r['run_h']:6,.0f}"
          f"  starts {r['starts']:4.0f}  services {r['services']}  {r['sec']:5.1f}s")


print("Part 1: the six columns as they were (SERVICE_IN_CORE = True)")
D.SERVICE_IN_CORE = True
for values in (D.VALUES_OURS, D.VALUES_ZH):
    c = setup(values)
    U = c["units"]
    print(f"\n=== {values}: ЖКПЗ, 14 measured days ({len(c['load'])} h), availability "
          f"{'as measured' if c['avail'] else 'always'}; scenario A")
    for mode in ("window", "every"):
        print(f"-- {'one window (Solve the window as posed)' if mode == 'window' else 'every day on its own (the default for a measured plant)'}")
        b = solve(c, U, mode); show("no maintenance", b)
        show("count 2 × 8 h, 100 %", solve(c, with_(U, **{D.U_MEV: 2}), mode), b)
        show("count 1 × 8 h, 100 %", solve(c, with_(U, **{D.U_MEV: 1}), mode), b)
        show("count 4 × 8 h, 100 %", solve(c, with_(U, **{D.U_MEV: 4}), mode), b)
        show("count 2 × 8 h, 50 % (a derate)", solve(c, with_(U, **{D.U_MEV: 2, D.U_MPU: 50.0}), mode), b)
        show("count 2 × 8 h + cost 500,000 each", solve(c, with_(U, **{D.U_MEV: 2, D.U_MCOST: 500_000.0}), mode), b)
        show("interval 100 run h × 8 h, no cost", solve(c, with_(U, **{D.U_MINT: 100}), mode), b)
        show("interval 100 run h × 8 h + 500,000 each", solve(c, with_(U, **{D.U_MINT: 100, D.U_MCOST: 500_000.0}), mode), b)
        show("interval 2,000 run h × 8 h + 500,000 (OEM)", solve(c, with_(U, **{D.U_MINT: 2000, D.U_MCOST: 500_000.0}), mode), b)
        show("count 3 AND interval 100 (+ cost) — which wins?", solve(c, with_(U, **{D.U_MEV: 3, D.U_MINT: 100, D.U_MCOST: 500_000.0}), mode), b)

D.SERVICE_IN_CORE = False

print("\nPart 2: two columns, priced per running hour, against the core's running-hour trigger")
for values in (D.VALUES_ZH, D.VALUES_OURS):
    for hours, n, dur, cost in ((96, 30, 2, 150_000.0), (168, 50, 4, 400_000.0)):
        c = setup(values, hours=hours)
        U = with_(c["units"], **{D.U_MINT: n, D.U_MCOST: cost, D.U_MDUR: dur})
        out = {}
        for core in (False, True):
            D.SERVICE_IN_CORE = core
            out[core] = solve(c, U)
        D.SERVICE_IN_CORE = False
        f, k = out[False], out[True]
        print(f"  {values[:4]} {hours} h, a {dur} h service every {n} run h at {cost:,.0f}: "
              f"per running hour {f['obj']:,.0f} ({f['run_h']:.0f} run h ≈ {f['run_h'] / n:.1f} "
              f"services, {f['sec']:.1f}s) | core trigger {k['obj']:,.0f} ({k['run_h']:.0f} run h, "
              f"services {k['services']}, {k['sec']:.0f}s) | {100 * (f['obj'] - k['obj']) / k['obj']:+.1f} %")
