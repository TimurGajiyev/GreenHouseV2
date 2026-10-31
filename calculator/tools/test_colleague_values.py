"""The colleague's values on the dispatch page, and our own values left as they were.

    python calculator/tools/test_colleague_values.py                  every check, about a minute
    python calculator/tools/test_colleague_values.py --compare=K      and one plant solved in full
                                                                      against his run (K, M or KM)

  A. our study     the page's own values and tables did not move, and the three new
                   inputs at their defaults change nothing in the model
  B. his values    each one, by its own arithmetic and against his files
  C. new inputs    the charge ceiling, the battery's own use and the running-hour service
                   do what they say, and the accounts still add up to the solver's objective
  D. his year      year_study.month_mean, by hand and against the rebuild of his method
  E. the page      the real page run headless: switch, values, a solve, switch back

The comparison needs his files in .playwright/output/zharkent (git-ignored); a check that
reads them says so and passes without them, and every check on the plants needs the
measured table (real_data/zharkent/data) in the same way.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import logging
import os
import sys
import time
import warnings

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")

import numpy as np              # noqa: E402
import pandas as pd             # noqa: E402

import app_dispatch as D        # noqa: E402
import real_data as RD          # noqa: E402
import year_study as Y          # noqa: E402
from reopt_core import model as M   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
HIS = os.path.join(ROOT, ".playwright", "output", "zharkent", "runs_c1621a84d5f54a63_results.csv")
RECREATE = os.path.join(ROOT, "docs", "zharkent-app", "recreate.py")
FAIL: list[str] = []
Z = D.VALUES[D.VALUES_ZH]
PLANTS = {"K": RD.ZHKPZ, "M": RD.SITE3, "KM": RD.ALL3}
RULES = ["A · ГПУ от 50%, без батареи", "C · ГПУ от 90%, без батареи", "B · ГПУ от 90% + батарея"]


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK' if ok else 'XX'}  {name}{('   ' + detail) if detail else ''}")
    if not ok:
        FAIL.append(name)


def head(t: str) -> None:
    print(f"\n{t}\n{'-' * len(t)}")


def close(a: float, b: float, rel: float = 1e-9) -> bool:
    return abs(a - b) <= rel * max(abs(a), abs(b), 1.0)


def bat_of(v: dict) -> dict:
    """The page's battery dictionary at a set of values."""
    return dict(kw=v["b_kw"], kwh=v["b_kwh"], rte=0.88, soc_min=v["soc_min"] / 100.0,
                soc_init=0.5, cyclic=True, wear=v["wear"], grid_charge=False, capex=v["capex"],
                om_fraction=v["bat_om"] / 100.0, replace_year=v["rep_year"],
                replace_fraction=v["rep_cost"] / 100.0, soc_max=v["soc_max"] / 100.0,
                own_kw=v["own_kw"])


def day_load() -> list[float]:
    return [1500.0 + 700.0 * ((h % 24) in range(8, 20)) + 300.0 * ((h % 24) in (11, 12, 18))
            for h in range(48)]


def recreate():
    """docs/zharkent-app/recreate.py, the rebuild of his method, or None."""
    if not os.path.exists(RECREATE):
        return None
    spec = importlib.util.spec_from_file_location("zh_recreate", RECREATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------- our study
def a_ours() -> None:
    head("A. our study has not moved")
    v = D.VALUES[D.VALUES_OURS]
    was = dict(grid=60.0, wear_h=15.0, avail=0, b_kw=2500.0, b_kwh=5500.0, soc_min=30.0,
               wear=0.5, capex=391e6, bat_om=2.5, rep_year=10, rep_cost=100.0, years=25,
               esc=3.4, disc=6.24)
    check("every value the page used to hard-code", all(v[k] == x for k, x in was.items()),
          ", ".join(k for k, x in was.items() if v[k] != x))
    check("the new inputs default to off", v["soc_max"] == 100.0 and v["own_kw"] == 0.0)
    check("still the two rules, and only these two",
          list(v["library"]) == D.SCENARIO_DEFAULT == v["rules"] and len(v["rules"]) == 2)
    check("the page's first option is our study", list(D.VALUES)[0] == D.VALUES_OURS)
    u = D.default_units("2 units (Jenbacher + TEDOM)")
    check("a units table keeps its figures, the new column at 0",
          (u[D.U_OMH] == 0).all() and (u[D.U_COST] == 22.0).all()
          and (u[D.U_START] == 15_000.0).all() and (u[D.U_UP] == 4).all()
          and (u[D.U_DOWN] == 5).all())

    # the same day, with and without the new keys: the same model to the last digit
    old = {k: x for k, x in bat_of(v).items() if k not in ("soc_max", "own_kw")}
    load, price = day_load(), [60.0] * 48
    sc = D._rule("B", minload=90.0, bat=True)
    a = D.build(load, price, u, old, sc)
    b = D.build(load, price, u, bat_of(v), sc)
    fa, fb = a.fuel_techs, b.fuel_techs
    check("the model's inputs are the same", a.loads_kw == b.loads_kw
          and a.storage.soc_max_fraction == 1.0 == b.storage.soc_max_fraction
          and all(f.om_cost_per_running_hour == 0.0 for f in [*fa, *fb]))
    ra, rb = M.solve(a, time_limit=60, mip_gap=1e-4), M.solve(b, time_limit=60, mip_gap=1e-4)
    check("and so is the answer", ra["status"] == rb["status"] and close(
        ra["objective_lifecycle_cost"], rb["objective_lifecycle_cost"], 1e-9),
        f"{ra['objective_lifecycle_cost']:,.0f}")


# ------------------------------------------------------------------- his values
def b_his() -> None:
    head("B. his values")
    check("grid 50 incl. VAT is 44.64 ex VAT", round(Z["grid"], 2) == 44.64)
    check("gas 75 ₸/m³ incl. VAT is 7.094 ₸ per kWh of gas", round(D.ZH_GAS, 3) == 7.094)
    check("battery 3 MWh at 0.33 C", Z["b_kwh"] == 3000.0 and Z["b_kw"] == 990.0)
    check("price (kWh × 150 + kW × 120) USD × 480 = 273,024,000 ₸", Z["capex"] == 273_024_000.0)
    check("SoC 10–95 %, 15 kW own use, no wear per kWh",
          (Z["soc_min"], Z["soc_max"], Z["own_kw"], Z["wear"]) == (10.0, 95.0, 15.0, 0.0))
    check("no O&M, no replacement, no escalation, no discount",
          (Z["bat_om"], Z["rep_year"], Z["rep_cost"], Z["esc"], Z["disc"]) == (0.0, 0, 0.0, 0.0, 0.0))
    check("engines always available", [D.AV_MEASURED, D.AV_FREE][Z["avail"]] == D.AV_FREE)
    check("rules: ours, and the 90 % rule without the battery",
          list(Z["library"]) == [*D.SCENARIO_DEFAULT, RULES[1]] and Z["rules"] == list(Z["library"]))

    if not RD.available():
        print("  --  the measured table is not here: the plants' tables are not checked")
        return
    u = D.default_units(D.REAL_PRESET + RD.ALL3, D.VALUES_ZH)
    t, j = u.iloc[0], u.iloc[1]
    check("TEDOM 1,200 kW at 43.6 / 40.2 %, J320 1,066 kW at 43.2 / 39.6 %",
          (t[D.U_KW], t[D.U_EFF100], t[D.U_EFF50], j[D.U_KW], j[D.U_EFF100], j[D.U_EFF50])
          == (1200.0, 43.6, 40.2, 1066.0, 43.2, 39.6))
    check("service 7,200 and 6,396 ₸ per engine hour",
          close(t[D.U_OMH], 7200.0) and close(j[D.U_OMH], 6396.0))
    check("a start is 4 such hours", close(t[D.U_START], 28_800.0) and close(j[D.U_START], 25_584.0))
    check("full-load fuel × efficiency gives the gas price back",
          all(close(r[D.U_COST] * r[D.U_EFF100] / 100.0, D.ZH_GAS) for _, r in u.iterrows()))
    check("per-kWh O&M stays 0, so service is not paid twice", (u[D.U_OM] == 0).all())
    jsx = D.default_units("3 units (+ КГУ-3)", D.VALUES_ZH)
    check("a row that is not one of his engines is left as it was",
          jsx.iloc[2][D.U_COST] == 22.0 and jsx.iloc[2][D.U_OMH] == 0.0)
    check("his service and start on our own values stay 0 and 15,000",
          (D.default_units(D.REAL_PRESET + RD.ALL3)[D.U_OMH] == 0).all())

    r = recreate()
    if r is None:
        print("  --  recreate.py is not here: not checked against the rebuild")
        return
    # a second route: the constants the rebuild reproduced his 5-minute steps with
    check("the same numbers as the rebuild of his method",
          close(D.ZH_GAS, r.GAS) and close(D.ZH_GRID, r.GRID)
          and close(t[D.U_OMH], r.OM_H["mwm"]) and close(j[D.U_OMH], r.OM_H["zh2"])
          and D.ZH_START_H == r.START_H
          and Z["soc_min"] / 100.0 == r.LO and Z["soc_max"] / 100.0 == r.HI
          and Z["own_kw"] == r.AUX)
    if os.path.exists(HIS):
        h = pd.read_csv(HIS)
        h = h[(h.seq == 4) & (h.case == "RULES") & (h.e_mwh == 3.0) & ((h.c_rate - 0.33).abs() < 1e-9)]
        check("the price is the one on his run", close(h.capex_kzt.iloc[0], Z["capex"]))
    else:
        print("  --  his run's file is not here: not checked against it")


# ------------------------------------------------------------------- new inputs
def c_inputs() -> None:
    head("C. the new inputs")
    if not RD.available():
        print("  --  the measured table is not here")
        return
    load, price = day_load(), [Z["grid"]] * 48
    u = D.default_units(D.REAL_PRESET + RD.ZHKPZ, D.VALUES_ZH)
    bat = bat_of(Z)
    sc = D._rule("B", minload=90.0, bat=True)
    inp = D.build(load, price, u, bat, sc)
    check("own use is on the load of a battery row", close(inp.loads_kw[0], load[0] + 15.0))
    nob = D.build(load, price, u, bat, D._rule("C", minload=90.0))
    check("and not on a row without the battery", close(nob.loads_kw[0], load[0]))
    check("each engine carries its service per running hour",
          [f.om_cost_per_running_hour for f in inp.fuel_techs] == [7200.0, 1066.0 * 6.0])
    res = M.solve(inp, time_limit=60, mip_gap=1e-4)
    soc = res["series"]["soc_kwh"]
    check("the battery is never filled above 95 %",
          max(soc) <= 0.95 * bat["kwh"] + 1e-6, f"highest {max(soc):,.1f} kWh")
    check("and it does reach the ceiling", max(soc) > 0.9 * bat["kwh"], f"{max(soc):,.1f} kWh")
    check("nor drained under 10 %", min(soc) >= 0.10 * bat["kwh"] - 1e-6)
    a = D.account(res, price, u, bat["wear"])
    check("the accounts add up to the solver's objective",
          close(a["total"], res["objective_lifecycle_cost"], 1e-6),
          f"{a['total']:,.0f} against {res['objective_lifecycle_cost']:,.0f}")
    h = D.hourly(res, price, u, bat["wear"])
    check("and so do the hours", close(sum(h["energy"]) + sum(h["ops"]), a["total"], 1e-6))
    on = res["series"]["fueltech_unit_on"]
    hours = {k: sum(1 for x in v if x > 0.5) for k, v in on.items()}
    plain = u.copy()
    plain[D.U_OMH] = 0.0
    p = D.account(res, price, plain, bat["wear"])
    want = sum(hours[str(r[D.U_NAME])] * r[D.U_OMH] for _, r in u.iterrows())
    check("the service in them is its rate × the hours each engine ran",
          close(a["total"] - p["total"], want, 1e-9), f"{want:,.0f} ₸")

    # a unit with one flat price per kWh, no efficiency curve, the same service
    flat = u.copy()
    flat[D.U_EFF100] = None
    flat[D.U_EFF50] = None
    res = M.solve(D.build(load, price, flat, bat, sc), time_limit=60, mip_gap=1e-4)
    a = D.account(res, price, flat, bat["wear"])
    h = D.hourly(res, price, flat, bat["wear"])
    check("a flat-priced row adds up as well",
          close(a["total"], res["objective_lifecycle_cost"], 1e-6)
          and close(sum(h["energy"]) + sum(h["ops"]), a["total"], 1e-6))

    # the logger priced the same way: by the hour and in total, service included
    kw = [1000.0 if t % 5 else 0.0 for t in range(48)]
    meas = {"gpu": [2 * x for x in kw], "grid": [100.0] * 48, "gpu_units": [kw, kw]}
    m = D.measured_account(meas, price, u)
    hh = D.measured_hourly(meas, price, u)
    run_h = sum(1 for x in kw if x > D.ON_KW)
    check("the logger's hours add up to its total", close(sum(hh), m["total"], 1e-9))
    check("the logger's service is the rate × the hours above 50 kW",
          close(sum(D.unit_hour_cost(r, 0.0, 1.0) - D.unit_hour_cost(plain.iloc[i], 0.0, 1.0)
                    for i, r in u.iterrows()) * run_h, (7200.0 + 6396.0) * run_h, 1e-9))
    one = {"gpu": meas["gpu"], "grid": meas["grid"]}      # no per-engine series
    check("and on the path with no engine series too",
          close(sum(D.measured_hourly(one, price, u)), D.measured_account(one, price, u)["total"], 1e-9))


# ------------------------------------------------------------------- his year
def d_year() -> None:
    head("D. his year")
    t0 = dt.datetime(2026, 1, 1)
    year = [t0 + dt.timedelta(hours=h) for h in range(8760)]
    check("one per hour over a calendar year", close(Y.month_mean(year, [1.0] * 8760), 8760.0))
    jan = [t for t in year if t.month == 1][:372]               # half of January
    check("half a month counts as the whole month, times 12",
          close(Y.month_mean(jan, [2.0] * 372), 2.0 * 744 * 12))
    few = jan + [t for t in year if t.month == 2][:100]         # 15 % of February
    check("a month under 25 % of its hours is dropped",
          close(Y.month_mean(few, [2.0] * 372 + [99.0] * 100), 2.0 * 744 * 12))
    sep = [dt.datetime(2025, 9, 1) + dt.timedelta(hours=h) for h in range(720)]
    sep2 = [dt.datetime(2026, 9, 1) + dt.timedelta(hours=h) for h in range(720)]
    check("September of two years is two months",
          close(Y.month_mean(sep + sep2, [1.0] * 720 + [3.0] * 720), 2.0 * 720 * 12))
    check("no month is nothing, not an error", Y.month_mean([], []) == 0.0)
    t = [dt.datetime(2025, 9, 28) + dt.timedelta(hours=h) for h in range(240)]
    check("his window keeps to whole days", D.zh_window(t) == (72, 168), str(D.zh_window(t)))
    t = [dt.datetime(2025, 9, 30, 9) + dt.timedelta(hours=h) for h in range(240)]
    check("a day his period cuts in two is left out", D.zh_window(t) == (24, 216), str(D.zh_window(t)))
    old = [dt.datetime(2024, 1, 1) + dt.timedelta(hours=h) for h in range(48)]
    check("hours all outside it are left as they are", D.zh_window(old) == (0, 48))
    try:
        Y.month_mean(year, [1.0])
        check("timestamps and values of different lengths are refused", False)
    except ValueError:
        check("timestamps and values of different lengths are refused", True)
    out = {"time": year, "values": D.VALUES_ZH}
    a = D._annual(out, 8760, 8760.0, [1.0] * 8760)
    check("the page's year on his values is that one figure", a == (8760.0, 8760.0))
    miss = [t for t in year if t.month != 12]
    v = [float(t.month) for t in miss]
    a = D._annual({"time": miss, "values": D.VALUES_ZH}, len(miss), 0.0, v)
    b = D._annual({"time": miss, "values": D.VALUES_OURS}, len(miss), 0.0, v)
    check("on ours a month not measured is still a range", b[0] < b[1] and a[0] == a[1])
    check("and that range holds his figure", b[0] <= a[0] <= b[1], f"{a[0]:,.0f}")
    check("the months not measured are named only on ours",
          D._year_gap({"time": miss}, len(miss)) == [12]
          and D._year_gap({"time": miss, "values": D.VALUES_ZH}, len(miss)) == [])

    r = recreate()
    if r is None or not os.path.exists(os.path.join(r.DATA, f"runs_{r.RUN}_decisions.csv.gz")):
        print("  --  his steps are not here: not checked against the rebuild")
        return
    x = r.steps("K")
    want = float(r.year(x, pd.DataFrame({"v": x["load"].values * r.DT}))["v"])
    # his 25 % counts hours and month_mean counts values: 12 of them an hour here
    got = Y.month_mean(x["time"].tolist(), x["load"].tolist(), coverage=0.25 * 12)
    check("the same year as the rebuild, on his own steps", close(got, want, 1e-9),
          f"{got:,.0f} kWh a year against {want:,.0f}")


# ------------------------------------------------------------------- the page
def _page() -> None:
    import app_dispatch
    app_dispatch.render()


def e_page() -> None:
    head("E. the page, run headless")
    if not RD.available():
        print("  --  the measured table is not here")
        return
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_function(_page, default_timeout=120).run()
    check("the page opens", not at.exception, str([e.value for e in at.exception][:1]))
    check("on our study", at.radio(key="gd_values").value == D.VALUES_OURS)
    val = lambda k: at.number_input(key=k).value
    check("with our grid price, battery and finance",
          (val("gd_grid"), val("gd_bkwh"), val("gd_capex"), val("gd_disc"), val("gd_years"))
          == (60.0, 5500.0, 391e6, 6.24, 25))
    check("the new inputs at off", val("gd_socmax") == 100.0 and val("gd_bown") == 0.0)
    check("engines as measured", at.radio(key="gd_avail").value == D.AV_MEASURED)
    check("the units table is the plant's own",
          float(at.session_state["gd_units_df"][D.U_COST].iloc[0]) == 22.0)

    # something typed on our study, to see what a switch does to it
    at.number_input(key="gd_grid").set_value(61.0).run()
    at.radio(key="gd_values").set_value(D.VALUES_ZH).run()
    check("the switch raises no error", not at.exception, str([e.value for e in at.exception][:1]))
    want = dict(gd_grid_zh=Z["grid"], gd_bkw_zh=990.0, gd_bkwh_zh=3000.0, gd_socmin_zh=10.0,
                gd_socmax_zh=95.0, gd_bown_zh=15.0, gd_wear_zh=0.0, gd_capex_zh=273_024_000.0,
                gd_bat_om_zh=0.0, gd_bat_rep_year_zh=0, gd_bat_rep_cost_zh=0.0, gd_years_zh=15,
                gd_esc_zh=0.0, gd_disc_zh=0.0, gd_wear_h_zh=4.0)
    bad = {k: val(k) for k, x in want.items() if not close(val(k), x, 1e-9)}
    check("every input shows his value", not bad, str(bad))
    check("engines always available", at.radio(key="gd_avail_zh").value == D.AV_FREE)
    u = at.session_state["gd_units_df"]
    check("the units table takes his engines",
          close(float(u[D.U_OMH].iloc[0]), 7200.0) and float(u[D.U_UP].iloc[0]) == 1)
    check("his meters are netted", "buy" not in at.session_state["gd_measured"])
    check("Streamlit shows no warning about the defaults",
          not any("default value" in w.value for w in at.warning))
    picked = at.session_state["gd_scen_df"][D.S_NAME].tolist()
    check("three rules picked", picked == list(Z["library"]), str(picked))

    y = RD.year(RD.ZHKPZ)
    w0, wn = D.zh_window(list(y["time"]))
    check("the window is his twelve months",
          next(w for w in at.number_input if (w.key or "").startswith("gd_start_")).value == w0
          and next(w for w in at.number_input if (w.key or "").startswith("gd_len_")).value == wn,
          f"hours {w0:,} to {w0 + wn:,} of {len(y['load']):,}")

    # a four-day window: the whole path to the results, on his values
    ln = next(w for w in at.number_input if (w.key or "").startswith("gd_len_"))
    ln.set_value(96).run()
    at.button(key="gd_run").click().run(timeout=300)
    check("a solve raises no error", not at.exception and not at.error,
          str([e.value for e in [*at.exception, *at.error]][:1]))
    out = at.session_state["gd_results"]
    check("all three rules solved", out is not None and len(out["runs"]) == 3 and not out["unsolved"])
    check("the results remember their values", out["values"] == D.VALUES_ZH)
    html = " ".join(h.proto.body for h in at.get("html"))
    check("the payback against measured is on the page",
          "Battery price ÷ saving against measured" in html)
    check("no NaN or None reached a table", ">nan<" not in html and ">None<" not in html)

    at.radio(key="gd_values").set_value(D.VALUES_OURS).run()
    check("back on our study, the inputs start over from our values", val("gd_grid") == 60.0)
    check("our battery is back", val("gd_bkwh") == 5500.0 and val("gd_capex") == 391e6)
    check("our units are back", float(at.session_state["gd_units_df"][D.U_COST].iloc[0]) == 22.0)
    check("our meters are each plant's own again", "buy" in at.session_state["gd_measured"])
    check("the old results say whose they are",
          any(D.VALUES_ZH in w.value for w in at.warning))
    check("no error on the way back", not at.exception, str([e.value for e in at.exception][:1]))


# ------------------------------------------------------------------- comparison
def _his(group: str, seq: int = 4) -> dict | None:
    if not os.path.exists(HIS):
        return None
    r = pd.read_csv(HIS)
    r = r[(r.group == group) & (r.seq == seq)]
    base = r[r.case == "BASE"].iloc[0]
    bat = r[(r.case == "RULES") & (r.e_mwh == 3.0) & ((r.c_rate - 0.33).abs() < 1e-9)].iloc[0]
    return {"today": base.cost_kzt, "with": bat.cost_kzt, "saving": bat.saving_kzt,
            "payback": bat.payback_y, "life": bat.life_y, "starts": bat.starts,
            "import": bat.imp_kwh, "today_import": base.imp_kwh, "gen": bat.gen_kwh,
            "throughput": bat.throughput_kwh}


def _his_hours(r, group: str) -> tuple[pd.Series, pd.Series]:
    """His cost hour by hour, today and with his 3 MWh, over the hours he has in full."""
    x = r.steps(group)
    new = x["new"].values

    def cost(engine: str, imports) -> pd.Series:
        c = imports * r.DT * r.GRID
        for u in r.UNITS[group]:
            p = x[f"{u}{engine}"].fillna(0).values
            meas = x[f"{u}_measured"].fillna(0).values > r.RUN_KW
            run = p > r.RUN_KW
            start = (run & ~np.r_[False, run[:-1]] & ~new) | (new & run & ~meas)
            c = c + r.fuel_kw(u, p) * r.DT * r.GAS + (run * r.DT + r.START_H * start) * r.OM_H[u]
        s = pd.Series(c, index=x["time"]).resample("h")
        return s.sum()[s.count() == 12]

    return cost("_measured", np.maximum(x["grid_measured"].values, 0)), cost("", x["imp"].values)


def compare(group: str) -> None:
    head(f"F. {group}: a year solved on his values, against his run")
    site = PLANTS[group]
    y = RD.year(site)
    w0, wn = D.zh_window(list(y["time"]))           # his twelve months, as the page opens
    cut = lambda v: list(v)[w0:w0 + wn]
    load, times = cut(y["load"]), cut(y["time"])
    price = [Z["grid"]] * len(load)
    units = D.default_units(D.REAL_PRESET + site, D.VALUES_ZH)
    bat = bat_of(Z)
    # no buy or sell: on his values the meters are netted, as the page does
    meas = {"gpu": cut(y["gpu"]), "grid": cut(y["grid"]), "gpu_units": [cut(g) for g in y["gpu_units"]]}
    out = {"time": times, "values": D.VALUES_ZH, "bat": bat}
    typ = Y.every_day(load, price)
    H = len(load)
    m_hour = D.measured_hourly(meas, price, units)
    today = D._annual(out, H, 0.0, m_hour)[0]
    runs = {}
    for name in RULES:
        sc = Z["library"][name]
        t0 = time.time()
        res = Y.solve_year(None, load, price, typ.k, typical=typ,
                           day_pose=lambda c, dl, dp, _s=sc: D.build(dl, dp, units, bat, _s),
                           time_limit=120, mip_gap=D.GAP_DEFAULT / 100.0)
        acc = D.account(res, price, units, 0.0)
        hourly = D.hourly(res, price, units, 0.0)
        c = [e + o for e, o in zip(hourly["energy"], hourly["ops"])]
        runs[name] = dict(acc=acc, cost=D._annual(out, H, 0.0, c)[0], hourly=c,
                          grid=D._annual(out, H, 0.0, res["series"]["grid_kw"])[0],
                          gen=D._annual(out, H, 0.0, res["series"]["load_kw"])[0],
                          dis=D._annual(out, H, 0.0, res["series"]["battery_discharge_kw"])[0],
                          starts=D._annual(out, H, 0.0, hourly["starts"])[0])
        print(f"  solved {name}: {time.time() - t0:,.0f} s", flush=True)
    a, c, b = (runs[n] for n in RULES)
    saving = today - b["cost"]
    cycles = b["dis"] / (0.85 * bat["kwh"])
    life = min(6000.0 / cycles, 15.0) if cycles else 15.0
    h = _his(group)
    mln = lambda v: f"{v / 1e6:,.1f}"
    print(f"\n  {H // 24} days, {H:,} h, {times[0]:%d.%m.%Y} – {times[-1]:%d.%m.%Y} · per year, million ₸")
    print(f"  today (the meters)            ours {mln(today):>7}   his {mln(h['today']) if h else '—':>7}")
    print(f"  rule, no battery (C)          ours {mln(c['cost']):>7}")
    print(f"  engines from 50 %, no battery ours {mln(a['cost']):>7}")
    print(f"  rule + battery (B)            ours {mln(b['cost']):>7}   his {mln(h['with']) if h else '—':>7}")
    print(f"  saving against today          ours {mln(saving):>7}   his {mln(h['saving']) if h else '—':>7}")
    print(f"  battery price ÷ saving, years ours {Z['capex'] / saving:>7.1f}   his {h['payback'] if h else 0:>7.1f}")
    print(f"  of which the rule (C)         ours {mln(today - c['cost']):>7}")
    print(f"  of which the battery (C − B)  ours {mln(c['cost'] - b['cost']):>7}")
    print(f"  grid bought, GWh              ours {b['grid'] / 1e6:>7.2f}   his {h['import'] / 1e6 if h else 0:>7.2f}")
    print(f"  starts a year                 ours {b['starts']:>7,.0f}   his {h['starts'] if h else 0:>7,.0f}")
    print(f"  discharged, MWh a year        ours {b['dis'] / 1e3:>7,.0f}   his {h['throughput'] / 1e3 if h else 0:>7,.0f}")
    print(f"  battery life by cycles, years ours {life:>7.1f}   his {h['life'] if h else 0:>7.1f}")
    print(f"  battery against 50 % engines  ours {mln(a['cost'] - b['cost']):>7}")
    check("every day solved", all(r["acc"]["status"] == "Optimal" for r in runs.values()),
          ", ".join(str(r["acc"]["status"]) for r in runs.values()))
    check("the battery rule costs no more than the rule alone", b["cost"] <= c["cost"] + 1.0)
    if not h:
        return
    # A year apart: his hours are not ours. He bridges gaps of up to 3 h and we keep only
    # unbroken days, so a month holds other hours and its year another level.
    check("the year's cost with the battery within 5 % of his",
          abs(b["cost"] / h["with"] - 1) < 0.05, f"{100 * (b['cost'] / h['with'] - 1):+.1f} %")
    check("the battery price ÷ saving within half a year of his",
          abs(Z["capex"] / saving - h["payback"]) < 0.5,
          f"{Z['capex'] / saving:.1f} against {h['payback']:.1f}")
    # The same hours, cost for cost: nothing left but the meters and the method.
    r = recreate()
    if r is None or not os.path.exists(os.path.join(r.DATA, f"runs_{r.RUN}_decisions.csv.gz")):
        print("  --  his steps are not here: not compared hour for hour")
        return
    his_t, his_b = _his_hours(r, group)
    idx = pd.DatetimeIndex(times)
    ours_t, ours_b = pd.Series(m_hour, index=idx), pd.Series(b["hourly"], index=idx)
    both = idx.intersection(his_t.index)
    t_o, t_h, b_o, b_h = (s[both].sum() for s in (ours_t, his_t, ours_b, his_b))
    print(f"\n  on the same {len(both):,} hours, million ₸")
    print(f"  today (the meters)            ours {mln(t_o):>7}   his {mln(t_h):>7}   {100 * (t_o / t_h - 1):+.1f} %")
    print(f"  with the battery              ours {mln(b_o):>7}   his {mln(b_h):>7}   {100 * (b_o / b_h - 1):+.1f} %")
    check("today within 2 % of his, hour for hour", abs(t_o / t_h - 1) < 0.02,
          f"{100 * (t_o / t_h - 1):+.1f} %")
    # Not "ours is cheaper". It is on K and KM (-3.0, -2.3 %), where the optimiser has engines
    # to choose between. On M (+0.5 %) one engine under its 90 % floor must cycle, which he
    # does in 5-minute steps with charge carried overnight, and hours and closed days cannot.
    check("with the battery within 5 % of his, hour for hour", abs(b_o / b_h - 1) < 0.05,
          f"{100 * (b_o / b_h - 1):+.1f} %")


if __name__ == "__main__":
    picks = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--compare=")]
    if picks:
        for g in picks:
            compare(g)
    else:
        a_ours()
        b_his()
        c_inputs()
        d_year()
        e_page()
    print(f"\n{'ALL OK' if not FAIL else str(len(FAIL)) + ' FAILED: ' + '; '.join(FAIL)}")
    sys.exit(1 if FAIL else 0)
