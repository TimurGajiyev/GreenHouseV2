"""Five unlike cases, each carried from an hourly load to a 25-year payback.

Every case goes through the **app's own path** -- `app_dispatch.build`,
`year_study.solve_year`, `app_dispatch.account`, and the real period view from
`app_periods` -- and is then checked against the **core** by recomputing the same
quantity a second way. The point is not that the app runs; it is that the numbers
the design receives are the numbers the core produced.

The five are deliberately different in load shape, fleet, price structure, battery
and in what each one proves:

  1  Factory on an expensive grid     3 engines + BESS, flat price, a real year
                                      from 12 typical days. Proves the app path
                                      equals the core path day for day.
  2  Cold store, deep nights          2 engines, a two-zone hourly price. Proves
                                      the replayed price year is the real one and
                                      that the design's energy charge agrees with
                                      the study's own accounting.
  3  Data centre, flat around clock   1 engine, no swing at all. A flat year is
                                      periodic, so one typical day must reproduce
                                      the whole solved year -- an exactness test.
  4  Island, no usable grid           3 engines + BESS, commitment off so the full
                                      8,760 hours can be solved as the truth.
                                      Measures the clustering error directly.
  5  The JSX week, window mode        The old path, untouched, next to the new one:
                                      what annualising one week does to a payback.

Every case ends with the payback, simple and discounted.

    python tools/test_year_cases.py [1|2|3|4|5|all]
"""

from __future__ import annotations

import math
import os
import re
import sys
import time
import traceback
import types

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

import app_dispatch as D
import app_periods as A
import profile_ui as P
import ui_theme as T
import year_study as Y
from reopt_core import model as M

FAIL: list[str] = []
HTML: list[str] = []
YEARS, ESC, DISC = 25, 0.034, 0.0624          # REopt's own fuel escalation and discount


# --------------------------------------------------------------- reporting
def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK' if ok else 'XX'}  {name:<56}{detail}")
    if not ok:
        FAIL.append(name)


def near(name: str, got: float, want: float, rtol: float, detail: str = "") -> None:
    ok = abs(got - want) <= rtol * max(1.0, abs(want))
    check(name, ok, detail or f"{got:,.2f} vs {want:,.2f}  ({100 * (got / want - 1 if want else 0):+.4f}%)")


def head(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def sub(t: str) -> None:
    print(f"\n  {t}\n  {'-' * len(t)}")


# ----------------------------------------------------- headless design layer
class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _stub(period: str = "Day", which: str = "Representative day"):
    """A streamlit double: the design renders into HTML we can inspect."""
    st = types.SimpleNamespace()
    st.html = lambda body, **k: HTML.append(str(body))
    st.markdown = lambda body, **k: HTML.append(str(body))
    st.caption = lambda *a, **k: None
    st.write = lambda *a, **k: None
    st.info = st.warning = st.error = st.success = lambda *a, **k: None
    st.altair_chart = lambda ch, **k: None
    st.columns = lambda spec, **k: [_Ctx() for _ in range(spec if isinstance(spec, int)
                                                         else len(spec))]
    st.expander = lambda *a, **k: _Ctx()
    st.container = lambda *a, **k: _Ctx()
    st.segmented_control = lambda label, options, **k: (period if "Period" in label
                                                        else (which if "Day" in label
                                                              else options[0]))
    st.radio = lambda label, options, **k: options[0]
    st.selectbox = lambda label, options, **k: options[0]
    st.dataframe = lambda *a, **k: None
    st.divider = lambda *a, **k: None
    st.progress = lambda *a, **k: types.SimpleNamespace(progress=lambda *a, **k: None,
                                                        empty=lambda: None)
    return st


def install_stub(**kw) -> None:
    stub = _stub(**kw)
    for mod in (D, A, P, T):
        mod.st = stub


_COLSPAN = re.compile(r'colspan="(\d+)"')


def check_html(where: str) -> int:
    """Every rendered table: a header, rows as wide as it, no NaN reaching a cell."""
    n = 0
    for html in HTML:
        for tbl in re.findall(r"<table.*?</table>", html, re.S):
            n += 1
            heads = re.findall(r"<th[^>]*>(.*?)</th>", tbl, re.S)
            if not heads or any(h.strip() == "" for h in heads):
                FAIL.append(f"{where}: table header {heads}")
                continue
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S):
                cells = re.findall(r"<td([^>]*)>(.*?)</td>", row, re.S)
                if not cells:
                    continue
                width = sum(int(_COLSPAN.search(a).group(1)) if _COLSPAN.search(a) else 1
                            for a, _ in cells)
                if width != len(heads):
                    FAIL.append(f"{where}: row of {width} cells, header of {len(heads)}")
                    break
                for _, v in cells:
                    if v.strip() in ("nan", "None", "NaN", "inf", "-inf", "−inf"):
                        FAIL.append(f"{where}: cell renders as {v.strip()!r}")
                        break
    return n


# ------------------------------------------------------------------ scenario
def units_of(rows: list[tuple]) -> pd.DataFrame:
    """One row per engine: name, kW, energy cost, start cost, min load %, up, down, spill."""
    return pd.DataFrame([
        {D.U_NAME: n, D.U_KW: kw, D.U_COST: c, D.U_START: s, D.U_MIN: lo,
         D.U_UP: up, D.U_DOWN: dn, D.U_SPILL: sp, D.U_MAXST: None}
        for n, kw, c, s, lo, up, dn, sp in rows])


def battery(kw: float, kwh: float, *, wear: float = 0.5, capex: float = 0.0,
            rte: float = 0.88, soc_min: float = 0.3, grid_charge: bool = False) -> dict:
    return dict(kw=kw, kwh=kwh, rte=rte, soc_min=soc_min, soc_init=0.5, cyclic=True,
                wear=wear, grid_charge=grid_charge, capex=capex)


def scen(name: str, *, bat: bool, minload=None, scale: float = 100.0) -> dict:
    return {D.S_NAME: name, D.S_MIN: minload, D.S_BAT: bat, D.S_SCALE: scale,
            D.S_MAXST: None}


def solve_via_app(load, price, units, bat, rows, *, k: int | None,
                  time_limit: int = 300, gap: float = 0.001) -> dict:
    """What render() does when the button is pressed, without the button.

    ``k`` None solves the window as posed; an integer clusters the load into that
    many typical days. Returns the ``out`` dict the results block consumes, so the
    checks below see exactly what the design sees.
    """
    typ = Y.cluster(load, price, k) if k else None
    price_used = ([p for c in typ.day_of for p in typ.price[c]] if typ else list(price))
    runs = []
    for sc in rows:
        inp = D.build(load, price, units, bat, sc)
        if typ is not None:
            inp.tariff.energy_cost_per_kwh = (list(price_used)
                                              + [0.0] * max(0, D.MAX_H - len(price_used)))
        t0 = time.time()
        if typ is not None:
            res = Y.solve_year(lambda dl, dp, _s=sc: D.build(dl, dp, units, bat, _s),
                               load, price, k, typical=typ,
                               time_limit=time_limit, mip_gap=gap)
        else:
            res = M.solve(inp, time_limit=time_limit, mip_gap=gap)
        acc = D.account(res, price_used, units, bat["wear"] if sc.get(D.S_BAT) else 0.0)
        acc["seconds"] = time.time() - t0
        runs.append({"name": sc[D.S_NAME], "res": res, "tariff": inp.tariff, "acc": acc,
                     "battery": bool(inp.storage.enabled),
                     "rule": sc.get(D.S_MIN), "scale": float(sc.get(D.S_SCALE) or 100.0),
                     "hourly": D.hourly(res, price_used, units,
                                        bat["wear"] if inp.storage.enabled else 0.0)})
    return {"runs": runs, "currency": "₸", "wear_h": 15.0,
            "hours": len(runs[0]["res"]["series"]["load_kw"]),
            "price": price_used, "units": units, "bat": bat,
            "typical": (None if typ is None else {"k": typ.k, "weights": list(typ.weights)}),
            "life": {"years": YEARS, "escalation": ESC, "discount": DISC}}


# -------------------------------------------------------------- shared checks
def check_core_agreement(out: dict, load, price, units, bat, rows, k: int) -> None:
    """Re-solve the typical days straight through the core and compare.

    The app path goes through year_study; this goes through reopt_core.model with
    inputs built the same way. If the two disagree, the weighting is wrong.
    """
    typ = Y.cluster(load, price, k)
    for run, sc in zip(out["runs"], rows):
        direct = 0.0
        for c in range(typ.k):
            r = M.solve(D.build(typ.load[c], typ.price[c], units, bat, sc),
                        time_limit=300, mip_gap=0.001)
            direct += typ.weights[c] * r["objective_lifecycle_cost"]
        t = run["res"]["typical"]
        near(f"core, day by day == app, {run['name'][:24]}",
             t["objective_typical_days"], direct, 1e-9)
        # and the app's year is those days plus the starts their joins create
        near(f"year == days + join starts, {run['name'][:24]}",
             run["res"]["objective_lifecycle_cost"],
             direct + t["join_start_cost"], 1e-9)
        print(f"      {run['name'][:34]:<36}{t['starts_inside_days']:>5} starts inside the "
              f"typical days, {t['starts_from_joins']:>4} more from the joins "
              f"({t['join_start_cost']:,.0f} ₸)")


def check_accounting(run: dict, out: dict) -> None:
    """The accountant's total must be the money the solver minimised."""
    near(f"account total == objective, {run['name'][:26]}",
         run["acc"]["total"], run["res"]["objective_lifecycle_cost"], 1e-9)
    # and the count in the cost table must be the count the period view draws
    on = run["res"]["series"].get("fueltech_unit_on") or {}
    if on:
        view = sum(A._starts_in(v) for v in on.values())
        check(f"one start count everywhere, {run['name'][:26]}",
              abs(run["acc"]["starts"] - view) < 0.5,
              f"cost table {run['acc']['starts']:,.0f}, period view {view:,.0f}")


def check_design(out: dict, tag: str) -> None:
    """Render the real period view over the real result and inspect the HTML."""
    run = out["runs"][0]
    for period, which in (("Day", "Representative day"), ("Week", "Peak day")):
        HTML.clear()
        install_stub(period=period, which=which)
        try:
            A.render_periods({"res": run["res"], "tariff": run["tariff"],
                              "currency": out["currency"], "savings": None})
        except Exception as exc:
            FAIL.append(f"{tag} {period}/{which}: {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=3)
            continue
        n = check_html(f"{tag} {period}/{which}")
        check(f"design renders, {period} / {which}", True,
              f"{n} tables, {sum(len(h) for h in HTML):,} bytes")


def show_periods(run: dict, out: dict) -> None:
    """Print the day / week / year block the design shows, from the same function."""
    res = run["res"]
    load = res["series"]["load_kw"]
    rep = A.representative_day(load)
    A._CUR = out["currency"]
    df = A.period_frame(res["series"], run["tariff"], rep, res["sizes"])
    keep = ("Site load (kWh)", "Fuel-fired production (kWh)", "Grid purchase (kWh)",
            "Battery discharged (kWh)", "Peak grid purchase (kW)", "Starts",
            "Energy charge ($)", "Battery full cycles")
    sub(f"the design's own block, representative day #{rep + 1} of {len(load) // 24}")
    cols = [c for c in df.columns if c != "Metric"]
    print(f"      {'Metric':<34}" + "".join(f"{c:>20}" for c in cols))
    for _, r in df.iterrows():
        if r["Metric"] in keep:
            print(f"      {r['Metric']:<34}" + "".join(f"{str(r[c]):>20}" for c in cols))


def show_payback(run: dict, base: dict, out: dict, note: str = "") -> Y.Lifecycle:
    """The end of every case: what the extra CAPEX takes to come back."""
    H = out["hours"]
    year_saving = Y.annualise(base["acc"]["total"] - run["acc"]["total"], H)
    capex = out["bat"]["capex"] if run["battery"] and not base["battery"] else 0.0
    lc = Y.lifecycle(Y.annualise(run["acc"]["total"], H), years=YEARS, escalation=ESC,
                     discount=DISC, annual_saving=year_saving, capex=capex)
    cur = out["currency"]
    sub(f"payback — {run['name']} against {base['name']}{note}")
    print(f"      operating cost per year     {lc.annual_cost:>18,.0f} {cur}")
    print(f"      present value over {lc.years} yr     {lc.present_value:>18,.0f} {cur}"
          f"   (pwf {lc.pwf:.4f} @ {100 * ESC:.1f}% esc / {100 * DISC:.2f}% disc)")
    print(f"      saving per year             {lc.annual_saving:>18,.0f} {cur}")
    print(f"      present value of savings    {lc.saving_present_value:>18,.0f} {cur}")
    print(f"      extra CAPEX                 {lc.capex:>18,.0f} {cur}")
    print(f"      net present value           "
          f"{lc.saving_present_value - lc.capex:>18,.0f} {cur}")
    print(f"      SIMPLE PAYBACK              "
          f"{('%.2f years' % lc.simple_payback_years) if lc.simple_payback_years else 'never':>18}")
    print(f"      DISCOUNTED PAYBACK          "
          f"{('%.2f years' % lc.discounted_payback_years) if lc.discounted_payback_years else 'never':>18}")
    # the lifecycle arithmetic, recomputed the long way
    manual = sum(lc.annual_cost * (1 + ESC) ** y / (1 + DISC) ** y for y in range(1, YEARS + 1))
    near("present value == 25 discounted years, summed by hand",
         lc.present_value, manual, 1e-4)
    return lc


# ==================================================================== case 1
def case1() -> None:
    head("CASE 1 — a factory on an expensive grid: 3 engines + BESS, a real year")
    ex = D._jsx_loads()
    if not ex:
        print("  -- the JSX artifact is missing; skipped")
        return
    year, note = D.build_year(D.YEAR_SHAPES["Continuous, mild seasonal swing"], ex["week"])
    print(f"  load: {note}")
    price = [60.0] * len(year)                       # ₸/kWh, flat, as the JSX study prices it
    units = units_of([("Jenbacher", 1067.0, 22.0, 15_000.0, 50.0, 4, 5, True),
                      ("TEDOM", 1200.0, 22.0, 15_000.0, 50.0, 4, 5, True),
                      ("КГУ-3", 1100.0, 24.0, 15_000.0, 50.0, 4, 5, True)])
    bat = battery(2500.0, 5500.0, wear=0.5, capex=391_000_000.0)
    rows = [scen("B · 90% rule", bat=False, minload=90.0),
            scen("C · 90% + battery", bat=True, minload=90.0)]

    t0 = time.time()
    out = solve_via_app(year, price, units, bat, rows, k=12)
    print(f"\n  12 typical days, 2 scenarios, {time.time() - t0:,.1f} s total "
          f"(weights {out['typical']['weights']} = {sum(out['typical']['weights'])} days)")

    sub("the clustered year against the real one")
    real = sum(year)
    for run in out["runs"]:
        near(f"annual load preserved, {run['name'][:26]}",
             run["res"]["energy"]["annual_load_kwh"], real, 1e-12)
        check_accounting(run, out)
    check_core_agreement(out, year, price, units, bat, rows, 12)

    sub("energy balance of the year, hour by hour")
    for run in out["runs"]:
        s = run["res"]["series"]
        H = len(s["load_kw"])
        worst = max(abs(s["fueltech_kw"][t] + s["grid_kw"][t] + s["battery_discharge_kw"][t]
                        - s["battery_charge_kw"][t] - s["load_kw"][t]
                        - s["export_kw"][t] + s["unserved_kw"][t]) for t in range(H))
        check(f"load balances every hour, {run['name'][:26]}", worst < 1e-6,
              f"worst residual {worst:.2e} kW over {H:,} h")

    check_design(out, "case1")
    show_periods(out["runs"][1], out)
    show_payback(out["runs"][1], out["runs"][0], out)


# ==================================================================== case 2
def case2() -> None:
    head("CASE 2 — a cold store with deep nights and a two-zone price")
    ex = D._jsx_loads()
    if not ex:
        print("  -- the JSX artifact is missing; skipped")
        return
    year, note = D.build_year(D.YEAR_SHAPES["Deep nights and weekends"], ex["week"])
    print(f"  load: {note}")
    # A Czech-style VT/NT tariff: cheap between 22:00 and 06:00, dear by day.
    price = [18.0 if (h % 24) >= 22 or (h % 24) < 6 else 46.0 for h in range(len(year))]
    print(f"  price: two zones, {min(price):.0f} at night and {max(price):.0f} by day, "
          f"mean {sum(price) / len(price):.2f} ₸/kWh")
    units = units_of([("Engine A", 900.0, 21.0, 9_000.0, 40.0, 3, 3, False),
                      ("Engine B", 900.0, 23.0, 9_000.0, 40.0, 3, 3, False)])
    bat = battery(1500.0, 6000.0, wear=0.35, capex=120_000_000.0, grid_charge=True)
    rows = [scen("Engines only", bat=False),
            scen("Engines + battery, grid charging", bat=True)]

    out = solve_via_app(year, price, units, bat, rows, k=8)
    print(f"\n  8 typical days, weights {out['typical']['weights']}")

    sub("the replayed price year is the real price year")
    near("hours of cheap night price preserved",
         sum(1 for p in out["price"] if p < 30.0) / 1.0,
         sum(1 for p in price if p < 30.0) / 1.0, 0.02,
         f"{sum(1 for p in out['price'] if p < 30.0):,} vs "
         f"{sum(1 for p in price if p < 30.0):,} hours")
    near("mean price preserved", sum(out["price"]) / len(out["price"]),
         sum(price) / len(price), 1e-9)

    sub("the design's energy charge is the study's own grid cost")
    for run in out["runs"]:
        check_accounting(run, out)
        s = run["res"]["series"]
        by_hand = sum(out["price"][t] * s["grid_kw"][t] for t in range(len(s["grid_kw"])))
        near(f"grid cost, {run['name'][:26]}", run["acc"]["grid_cost"], by_hand, 1e-9)
        tar = run["tariff"]
        charge = sum(tar.energy_cost_per_kwh[t] * s["grid_kw"][t] for t in range(len(s["grid_kw"])))
        near(f"period view charge, {run['name'][:26]}", charge, by_hand, 1e-9)

    sub("night charging is what the battery is for")
    for run in out["runs"]:
        s = run["res"]["series"]
        night = sum(s["battery_charge_kw"][t] for t in range(len(s["grid_kw"]))
                    if out["price"][t] < 30.0)
        total = sum(s["battery_charge_kw"]) or 1.0
        print(f"      {run['name']:<40}{100 * night / total:>6.1f}% of charging at the night rate")
    r = out["runs"][1]["res"]["series"]
    share = sum(r["battery_charge_kw"][t] for t in range(len(r["grid_kw"]))
                if out["price"][t] < 30.0) / (sum(r["battery_charge_kw"]) or 1.0)
    check("the battery charges mostly at the cheap rate", share > 0.5,
          f"{100 * share:.1f}%")

    check_design(out, "case2")
    show_periods(out["runs"][1], out)
    show_payback(out["runs"][1], out["runs"][0], out)


# ==================================================================== case 3
def case3() -> None:
    head("CASE 3 — a data centre, flat around the clock: one typical day must be exact")
    # No season, no weekend, no daily shape: every day of this year is the same, so
    # the clustered year and the solved year are the same problem. If the weighting
    # is wrong by so much as a rounding error, it shows up here and nowhere else.
    year = [4200.0] * Y.HOURS_PER_YEAR
    # The price is what varies, not the load: a night rate and a day rate, the same
    # every day of the year. The battery then has something to arbitrage, and the
    # year is still exactly periodic, so the exactness test survives.
    price = [0.14 if (h % 24) < 7 else 0.38 for h in range(len(year))]
    print(f"  load: 4,200 kW every hour of the year, {sum(year) / 1e6:,.1f} GWh")
    print(f"  price: $0.14/kWh before 07:00 and $0.38 after, the same every day")
    units = units_of([("Gas engine", 3000.0, 0.09, 4_000.0, 60.0, 8, 8, False)])
    bat = battery(1200.0, 4800.0, wear=0.004, capex=1_600_000.0, grid_charge=True)
    rows = [scen("Engine only", bat=False), scen("Engine + battery", bat=True)]

    t0 = time.time()
    clustered = solve_via_app(year, price, units, bat, rows, k=2)
    t_cluster = time.time() - t0
    t0 = time.time()
    whole = solve_via_app(year, price, units, bat, rows, k=None, time_limit=900, gap=0.0005)
    t_whole = time.time() - t0
    print(f"\n  2 typical days: {t_cluster:,.1f} s     the whole 8,760 hours: {t_whole:,.1f} s"
          f"   ({t_whole / max(t_cluster, 1e-9):,.0f}x)")

    sub("a year of identical days needs one typical day")
    check("the clustering collapsed to a single day",
          clustered["typical"]["k"] == 1 and clustered["typical"]["weights"] == [365],
          f"k={clustered['typical']['k']}, weights {clustered['typical']['weights']}")

    sub("a flat year, both ways")
    for a, b in zip(clustered["runs"], whole["runs"]):
        near(f"same operating cost, {a['name'][:26]}", a["acc"]["total"], b["acc"]["total"], 2e-3)
        near(f"same fuel-fired energy, {a['name'][:26]}", a["acc"]["gen_kwh"], b["acc"]["gen_kwh"], 2e-3)
        print(f"      {a['name']:<30}clustered {a['acc']['total']:>14,.0f}"
              f"   whole year {b['acc']['total']:>14,.0f}"
              f"   status {b['res']['status']}")
    for run in clustered["runs"]:
        check_accounting(run, clustered)

    check_design(clustered, "case3")
    show_periods(clustered["runs"][1], clustered)
    lc_c = show_payback(clustered["runs"][1], clustered["runs"][0], clustered,
                        " (from 2 typical days)")
    lc_w = show_payback(whole["runs"][1], whole["runs"][0], whole,
                        " (from the whole 8,760 hours)")
    if lc_c.simple_payback_years and lc_w.simple_payback_years:
        near("the two paybacks agree", lc_c.simple_payback_years,
             lc_w.simple_payback_years, 0.02)


# ==================================================================== case 4
def case4() -> None:
    head("CASE 4 — an island with no usable grid: the clustering error, measured")
    # Commitment off (no minimum load, no start cost, no minimum up/down), so the
    # whole year is a linear program and can be solved exactly as the truth. This
    # is the only honest way to put a number on what clustering costs.
    ex = D._jsx_loads()
    if not ex:
        print("  -- the JSX artifact is missing; skipped")
        return
    year, note = D.build_year(D.YEAR_SHAPES["Office hours, strong seasonal swing"], ex["week"])
    print(f"  load: {note}")
    price = [500.0] * len(year)               # a grid this dear is effectively no grid
    units = units_of([("DG-1", 2000.0, 34.0, 0.0, 0.0, 1, 1, True),
                      ("DG-2", 2000.0, 36.0, 0.0, 0.0, 1, 1, True),
                      ("DG-3", 2000.0, 41.0, 0.0, 0.0, 1, 1, True)])
    bat = battery(2000.0, 8000.0, wear=0.4, capex=250_000_000.0)
    rows = [scen("Diesel only", bat=False), scen("Diesel + battery", bat=True)]

    # The diesel-only year is an LP that HiGHS cracks in seconds, which makes it
    # the truth the clustering can be measured against. The battery year adds
    # 8,760 coupled state-of-charge equations and a cyclic closing condition and
    # is solved whole below as well, so this case compares both routes on a case
    # where both routes are available -- the only honest way to put a number on
    # what clustering costs.
    #
    # One trap found while building this case, worth leaving written down: asking
    # for a 1e-5 optimality gap on the battery scenario ran for over 13 minutes
    # without returning, because enabling storage creates one binary (the cost
    # constant, model.py:517) and HiGHS then chases a gap the relaxation cannot
    # close. At the app's own default of 0.5 % it solves in 8 seconds.
    sub("the diesel-only year, solved whole, as the truth")
    t0 = time.time()
    truth = solve_via_app(year, price, units, bat, rows[:1], k=None, time_limit=1200)
    t_truth = time.time() - t0
    print(f"      {truth['runs'][0]['acc']['total']:>18,.0f} ₸   "
          f"{truth['runs'][0]['res']['status']}   {t_truth:,.1f} s")

    sub("typical days against it")
    print(f"      {'k':>3}  {'operating cost':>18}  {'error':>9}  {'seconds':>8}  {'speed-up':>9}")
    best = None
    for k in (4, 8, 12, 24):
        t0 = time.time()
        got = solve_via_app(year, price, units, bat, rows[:1], k=k)
        dt = time.time() - t0
        err = 100 * (got["runs"][0]["acc"]["total"] / truth["runs"][0]["acc"]["total"] - 1)
        print(f"      {k:>3}  {got['runs'][0]['acc']['total']:>18,.0f}  {err:>8.3f}%"
              f"  {dt:>8.1f}  {t_truth / max(dt, 1e-9):>8.0f}x")
        if k == 12:
            check("12 typical days within 1% of the solved year", abs(err) < 1.0,
                  f"{err:+.3f}%")
    sub("the battery year, both ways")
    t0 = time.time()
    whole_bat = solve_via_app(year, price, units, bat, rows[1:], k=None, time_limit=600)
    t_whole = time.time() - t0
    best = solve_via_app(year, price, units, bat, rows, k=12)
    for run in best["runs"]:
        check_accounting(run, best)
    err = 100 * (best["runs"][1]["acc"]["total"] / whole_bat["runs"][0]["acc"]["total"] - 1)
    print(f"      whole year {whole_bat['runs'][0]['acc']['total']:>18,.0f} ₸  "
          f"{whole_bat['runs'][0]['res']['status']}  {t_whole:,.1f} s")
    print(f"      12 days    {best['runs'][1]['acc']['total']:>18,.0f} ₸  "
          f"{err:+.3f}%")
    check("12 typical days within 1% of the solved year, with the battery",
          abs(err) < 1.0, f"{err:+.3f}%")

    sub("and the payback the clustered year reports")
    check_design(best, "case4")
    show_periods(best["runs"][1], best)
    show_payback(best["runs"][1], best["runs"][0], best, " (12 typical days)")


# ==================================================================== case 5
def case5() -> None:
    head("CASE 5 — the JSX week in window mode, next to the year it stands for")
    ex = D._jsx_loads()
    if not ex:
        print("  -- the JSX artifact is missing; skipped")
        return
    week = ex["week"]
    price_w = [60.0] * len(week)
    units = units_of([("Jenbacher", 1067.0, 22.0, 15_000.0, 50.0, 4, 5, True),
                      ("TEDOM", 1200.0, 22.0, 15_000.0, 50.0, 4, 5, True)])
    bat = battery(2500.0, 5500.0, wear=0.5, capex=391_000_000.0)
    rows = [scen("B · 90% rule", bat=False, minload=90.0),
            scen("C · 90% + battery", bat=True, minload=90.0)]

    sub("the window path, unchanged")
    win = solve_via_app(week, price_w, units, bat, rows, k=None)
    for run in win["runs"]:
        check_accounting(run, win)
    check(f"horizon is the {len(week)} hours posed", win["hours"] == len(week),
          f"{win['hours']} h")
    check_design(win, "case5-window")
    show_periods(win["runs"][1], win)
    lc_w = show_payback(win["runs"][1], win["runs"][0], win,
                        f" (window × 8,760/{len(week)})")

    sub("the same plant on a real year from typical days")
    year, _ = D.build_year(D.YEAR_SHAPES["Continuous, mild seasonal swing"], week)
    yr = solve_via_app(year, [60.0] * len(year), units, bat, rows, k=12)
    lc_y = show_payback(yr["runs"][1], yr["runs"][0], yr, " (12 typical days)")

    sub("what annualising one week did to the answer")
    for lab, a, b in (("operating cost per year",
                       Y.annualise(win["runs"][1]["acc"]["total"], win["hours"]),
                       Y.annualise(yr["runs"][1]["acc"]["total"], yr["hours"])),
                      ("saving per year", lc_w.annual_saving, lc_y.annual_saving),
                      ("present value of savings", lc_w.saving_present_value,
                       lc_y.saving_present_value)):
        print(f"      {lab:<30}week {a:>18,.0f}   year {b:>18,.0f}"
              f"   {100 * (a / b - 1) if b else 0:+8.2f}%")
    pw = lc_w.simple_payback_years or float("inf")
    py = lc_y.simple_payback_years or float("inf")
    print(f"      {'simple payback':<30}week {pw:>18,.2f}   year {py:>18,.2f}"
          f"   {100 * (pw / py - 1) if py else 0:+8.2f}%")
    check("the week and the year do not give the same payback", abs(pw / py - 1) > 1e-6,
          "as expected: this is why the year mode exists")


CASES = {"1": case1, "2": case2, "3": case3, "4": case4, "5": case5}


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    print(__doc__.strip().splitlines()[0])
    for key, fn in CASES.items():
        if which in ("all", key):
            fn()
    print(f"\n{'=' * 78}")
    print("FAILED: " + "; ".join(FAIL) if FAIL else "every case agreed with the core")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
