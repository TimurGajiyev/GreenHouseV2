"""Part 2 of the year/25-year methodology check: what a HORIZON does to the answer.

Two separate questions, because they have two separate answers.

  2  Timebase.  The core sums operating cost over the hours it is given and
     multiplies it by a 25-year present-worth factor. Capital, per-kW O&M and
     the fixed monthly charge are per-YEAR quantities and are NOT scaled by the
     horizon. So a horizon shorter than 8,760 hours puts a year of capital
     against a week of fuel. This part measures that, and shows what it does to
     sizing. (The neighbouring project guards the same trap explicitly:
     D:/Greenhouse/src/optimize.py:235 year_fraction, a copy of Calliope's
     annualisation_weight.)

  3  Annualisation.  The dispatch study solves a window and reports
     "per year = window x 8,760 / H". This part measures the error of that
     estimator against a real solved year -- for every week of the year, every
     month, a tiled week, and 12 weighted representative days (the method
     D:/Greenhouse/src/aggregate.py uses).

    python tools/test_year_horizon.py [2|3|all]
"""

from __future__ import annotations

import os
import statistics
import sys
import time

# Redirected stdout defaults to the console codepage on Windows; the captions
# these tests print carry a multiplication sign. Pin it, as jsx_render_check does.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app_dispatch as D
from reopt_core import model as M
from reopt_core.tariff import flat_tariff

FAIL: list[str] = []
HOURS = 8760


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK' if ok else 'XX'}  {name}{('   ' + detail) if detail else ''}")
    if not ok:
        FAIL.append(name)


def head(t: str) -> None:
    print(f"\n{t}\n{'-' * len(t)}")


# =============================================================== 2. timebase
def grid_only(hours: int) -> M.ScenarioInputs:
    """Nothing but a meter: load, a flat rate and a fixed monthly charge."""
    return M.ScenarioInputs(
        loads_kw=[1000.0] * hours,
        tariff=flat_tariff(0.12, monthly_demand_rate=0.0, fixed_monthly=100.0),
        financial=M.FinancialInputs(),
        pv=M.PVInputs(enabled=False),
        storage=M.StorageInputs(enabled=False),
        fuel_tech=M.FuelTechInputs(enabled=False),
        compensation_type="no_compensation")


def part2_timebase() -> None:
    head("2.1  which objective terms scale with the horizon, and which do not")
    print("      1,000 kW flat load, $0.12/kWh, $100/month fixed charge, no techs.")
    print("      A clean model would give the same lifecycle cost from any window,")
    print("      once the window is scaled up to a year.\n")
    print(f"      {'horizon':>9}  {'lifecycle cost':>16}  {'x 8760/H':>16}  {'vs year':>9}")
    year_lcc = None
    rows = []
    for h in (8760, 4380, 730, 168, 24):
        res = M.solve(grid_only(h), time_limit=120)
        lcc = res["objective_lifecycle_cost"]
        if year_lcc is None:
            year_lcc = lcc
        ann = lcc * HOURS / h
        rows.append((h, lcc, ann))
        print(f"      {h:>9,}  {lcc:>16,.0f}  {ann:>16,.0f}  {100 * (ann / year_lcc - 1):>8.1f}%")

    # The fixed monthly charge is billed 12 times whatever the horizon
    # (model.py: fixed_cost = tar.fixed_monthly_charge * 12), so a 24-hour window
    # annualised carries 365 years of standing charge.
    h24 = next(a for h, _, a in rows if h == 24)
    check("a 24-hour window annualised == the year", abs(h24 / year_lcc - 1) < 0.02,
          f"off by {100 * (h24 / year_lcc - 1):+.1f}%")
    h168 = next(a for h, _, a in rows if h == 168)
    check("a 168-hour window annualised == the year", abs(h168 / year_lcc - 1) < 0.02,
          f"off by {100 * (h168 / year_lcc - 1):+.1f}%")

    head("2.2  the same distortion decides whether anything gets BUILT")
    print("      1,000 kW flat load, grid $0.34/kWh, a sizeable generator at $800/kW")
    print("      burning $0.172/kWh of fuel. Over a year it pays back many times over.\n")
    print(f"      {'horizon':>9}  {'generator kW':>13}  {'verdict'}")
    sized = {}
    for h in (8760, 2190, 730, 168):
        inp = M.ScenarioInputs(
            loads_kw=[1000.0] * h,
            tariff=flat_tariff(0.34),
            financial=M.FinancialInputs(),
            pv=M.PVInputs(enabled=False),
            storage=M.StorageInputs(enabled=False),
            fuel_tech=M.FuelTechInputs(
                enabled=True, kind="Generator", installed_cost_per_kw=800.0,
                om_cost_per_kw=0.0, electric_efficiency_full_load=0.322,
                fuel_cost_per_gallon=2.25, max_kw=2000.0,
                macrs_option_years=0, macrs_bonus_fraction=0.0, federal_itc_fraction=0.0),
            compensation_type="no_compensation")
        kw = M.solve(inp, time_limit=180)["sizes"]["fueltech_kw"]
        sized[h] = kw
        print(f"      {h:>9,}  {kw:>13,.0f}  {'builds' if kw > 1 else 'builds NOTHING'}")

    check("a week sizes the plant the way a year does",
          abs(sized[168] - sized[8760]) <= 0.02 * max(1.0, sized[8760]),
          f"week {sized[168]:,.0f} kW vs year {sized[8760]:,.0f} kW")
    check("a quarter sizes the plant the way a year does",
          abs(sized[2190] - sized[8760]) <= 0.02 * max(1.0, sized[8760]),
          f"quarter {sized[2190]:,.0f} kW vs year {sized[8760]:,.0f} kW")


def part2c_lifecycle() -> None:
    """The 25-year number, reached twice by different routes, on a full year.

    Route A: the objective the solver minimised -- capital plus each year-one
    operating stream multiplied by its own present-worth factor, after tax.
    Route B: the pro-forma, which builds 25 explicit cash flows and discounts
    them one by one.

    They share inputs but not code. If the design is to show a 25-year figure,
    the two routes must meet.
    """
    head("2.3  the 25-year money, by two independent routes (8,760 h)")
    import math
    from reopt_core.finance import annuity

    # A daily swing, so the battery has something to do and the bill is not flat.
    load = [1000.0 + 600.0 * math.sin(2 * math.pi * (t % 24) / 24.0) for t in range(HOURS)]
    fin = M.FinancialInputs()          # REopt web-tool defaults, 25 years
    inp = M.ScenarioInputs(
        loads_kw=load,
        tariff=flat_tariff(0.14, monthly_demand_rate=12.0, fixed_monthly=250.0),
        financial=fin,
        pv=M.PVInputs(enabled=False),
        storage=M.StorageInputs(enabled=True, min_kw=500.0, max_kw=500.0,
                                min_kwh=2000.0, max_kwh=2000.0),
        fuel_tech=M.FuelTechInputs(enabled=False),
        compensation_type="no_compensation")
    res = M.solve(inp, time_limit=600)
    bau = M.business_as_usual(inp)

    tax = fin.offtaker_tax_rate_fraction
    pwf_e = annuity(fin.analysis_years, fin.elec_cost_escalation_rate_fraction,
                    fin.offtaker_discount_rate_fraction)
    pwf_om = annuity(fin.analysis_years, fin.om_cost_escalation_rate_fraction,
                     fin.owner_discount_rate_fraction)

    lcc = res["objective_lifecycle_cost"]
    rebuilt = (res["capital"]["lifecycle_capex"]
               + pwf_om * res["om"]["year1_storage"] * (1 - fin.owner_tax_rate_fraction)
               + pwf_e * res["utility"]["year1_total"] * (1 - tax))
    print(f"      capital (after ITC and MACRS)   {res['capital']['lifecycle_capex']:>18,.0f}")
    print(f"      year-1 utility bill             {res['utility']['year1_total']:>18,.0f}"
          f"   x pwf_e {pwf_e:.4f} x (1-{tax})")
    print(f"      year-1 storage O&M              {res['om']['year1_storage']:>18,.0f}"
          f"   x pwf_om {pwf_om:.4f}")
    print(f"      rebuilt lifecycle cost          {rebuilt:>18,.0f}")
    print(f"      solver objective                {lcc:>18,.0f}")
    check("the objective is year-one costs x present-worth factors",
          abs(rebuilt - lcc) <= 1e-4 * max(1.0, abs(lcc)),
          f"{100 * (rebuilt / lcc - 1):+.4f}%")

    check("BAU lifecycle == pwf_e x BAU year-1 bill, after tax",
          abs(bau["lifecycle_cost"] - pwf_e * bau["year1_total"] * (1 - tax))
          <= 1e-6 * bau["lifecycle_cost"],
          f"{bau['lifecycle_cost']:,.0f}")

    # REopt defines NPV as lcc_bau - lcc (results/financial.jl). The pro-forma
    # reaches the same number from 25 separate cash flows.
    npv_lcc = bau["lifecycle_cost"] - lcc
    npv_pf = res["proforma"]["npv"]
    print()
    print(f"      NPV as lcc_bau - lcc            {npv_lcc:>18,.0f}")
    print(f"      NPV from the 25 cash flows      {npv_pf:>18,.0f}")
    check("the two NPVs agree to within 1%",
          abs(npv_pf - npv_lcc) <= 0.01 * max(1.0, abs(npv_lcc)),
          f"{100 * (npv_pf / npv_lcc - 1):+.2f}%" if npv_lcc else "")

    cf = res["proforma"]["offtaker_annual_free_cashflows"]
    check("there are exactly analysis_years + 1 cash flows",
          len(cf) == fin.analysis_years + 1, f"{len(cf)} entries")


# ========================================================== 3. annualisation
def lp_units():
    """The study's own fleet with the commitment rules switched off.

    Minimum load, start cost and minimum up/down times are what make the model
    an integer program. Without them it is a pure LP, so a full solved year is
    a matter of seconds and can serve as the truth this part measures against.
    """
    u = D.default_units("2 units (Jenbacher + TEDOM)").copy()
    u[D.U_MIN] = 0.0
    u[D.U_START] = 0.0
    u[D.U_UP] = 1
    u[D.U_DOWN] = 1
    return u


def window_cost(load: list[float], units, bat: dict, sc: dict) -> float:
    """Operating cost of exactly these hours. Finance is off in D.build, so the
    objective IS the window's operating cost -- no present-worth factor in it."""
    return window_run(load, units, bat, sc)[0]


def window_run(load: list[float], units, bat: dict, sc: dict,
               time_limit: int = 600, gap: float = 1e-4) -> tuple[float, int, str]:
    """Cost, starts and status for exactly these hours."""
    price = [S_GRID] * len(load)
    res = M.solve(D.build(load, price, units, bat, sc), time_limit=time_limit, mip_gap=gap)
    if res["status"] not in ("Optimal", "Not Solved"):
        raise RuntimeError(f"{len(load)} h window: {res['status']}")
    starts = sum(int(r.get("starts") or 0) for r in (res["sizes"].get("fueltech_units") or []))
    return res["objective_lifecycle_cost"], starts, res["status"]


S_GRID = 60.0


def kmeans_days(days, k: int, seed: int = 0):
    """k-means++ on whole days, centroids as representatives, weights = members.

    Ported from D:/Greenhouse/src/aggregate.py:_kmeans so the comparison below is
    against that project's actual method and not a rough imitation of it.
    """
    import numpy as np
    x = np.asarray(days, dtype=float)
    x = x / max(x.max(), 1e-9)
    rng = np.random.default_rng(seed)
    n = len(x)
    centers = np.empty((k, x.shape[1]))
    centers[0] = x[rng.integers(n)]
    d2 = ((x - centers[0]) ** 2).sum(axis=1)
    for j in range(1, k):
        probs = d2 / d2.sum() if d2.sum() > 0 else np.full(n, 1 / n)
        centers[j] = x[rng.choice(n, p=probs)]
        d2 = np.minimum(d2, ((x - centers[j]) ** 2).sum(axis=1))
    labels = np.zeros(n, dtype=int)
    for it in range(100):
        dist = ((x[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        new = dist.argmin(axis=1)
        if it and (new == labels).all():
            break
        labels = new
        for c in range(k):
            mask = labels == c
            if mask.any():
                centers[c] = x[mask].mean(axis=0)
            else:
                far = dist.min(axis=1).argmax()
                centers[c] = x[far]
                labels[far] = c
    raw = np.asarray(days, dtype=float)
    reps, weights = [], []
    for c in range(k):
        mask = labels == c
        if not mask.any():
            continue
        reps.append(raw[mask].mean(axis=0).tolist())
        weights.append(int(mask.sum()))
    return reps, weights


def part3_annualisation() -> None:
    head("3.1  a real solved year, and every shortcut that claims to stand in for it")
    ex = D._jsx_loads()
    if not ex:
        print("  -- the JSX artifact is not present; skipping")
        return
    week = ex["week"]
    year, note = D.build_year(D.YEAR_SHAPES["Continuous, mild seasonal swing"], week)
    print(f"      load: {note}\n")

    units = lp_units()
    bat = dict(kw=2500.0, kwh=5500.0, rte=0.88, soc_min=0.30, soc_init=0.5,
               cyclic=True, wear=0.5, grid_charge=False, capex=0.0)
    sc = {D.S_NAME: "A", D.S_MIN: None, D.S_BAT: True, D.S_SCALE: 100.0, D.S_MAXST: None}

    t0 = time.time()
    truth = window_cost(year, units, bat, sc)
    print(f"      solved year (8,760 h, LP): {truth:>18,.0f}   [{time.time() - t0:,.1f} s]\n")

    # --- every calendar week of that year, annualised the way the app does
    errs = []
    for w in range(52):
        cut = year[w * 168:(w + 1) * 168]
        est = window_cost(cut, units, bat, sc) * HOURS / 168
        errs.append(100 * (est / truth - 1))
    lo, hi = min(errs), max(errs)
    print(f"      52 single weeks x 8,760/168:")
    print(f"        best  {min(errs, key=abs):+7.2f}%   worst {max(errs, key=abs):+7.2f}%"
          f"   median {statistics.median(errs):+7.2f}%   spread {hi - lo:6.2f} pp")
    check("any single week annualises the year to within 2%", max(abs(e) for e in errs) < 2.0,
          f"worst {max(errs, key=abs):+.2f}%")

    # --- the week the app actually defaults to, tiled 52.14 times (old free mode)
    tiled = (week * 53)[:HOURS]
    est_tiled = window_cost(tiled, units, bat, sc)
    print(f"\n      the example week tiled into a year: {est_tiled:>14,.0f}"
          f"   {100 * (est_tiled / truth - 1):+7.2f}%")
    check("tiling one week reproduces the year", abs(est_tiled / truth - 1) < 0.02,
          f"off by {100 * (est_tiled / truth - 1):+.2f}%")

    # --- calendar months
    merr = []
    start = 0
    for m, dim in enumerate([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]):
        h = dim * 24
        est = window_cost(year[start:start + h], units, bat, sc) * HOURS / h
        merr.append(100 * (est / truth - 1))
        start += h
    print(f"\n      12 calendar months x 8,760/H:")
    print(f"        best  {min(merr, key=abs):+7.2f}%   worst {max(merr, key=abs):+7.2f}%"
          f"   median {statistics.median(merr):+7.2f}%")
    check("any single month annualises the year to within 2%",
          max(abs(e) for e in merr) < 2.0, f"worst {max(merr, key=abs):+.2f}%")

    # --- representative days with weights (D:/Greenhouse/src/aggregate.py)
    days = [year[d * 24:(d + 1) * 24] for d in range(365)]
    print(f"\n      k representative days, each solved once and weighted:")
    for k in (4, 8, 12, 24):
        t0 = time.time()
        reps, weights = kmeans_days(days, k)
        est = sum(w * window_cost(r, units, bat, sc) for r, w in zip(reps, weights))
        err = 100 * (est / truth - 1)
        print(f"        k={k:>3}  {est:>16,.0f}   {err:+7.2f}%   "
              f"[{time.time() - t0:,.1f} s, {sum(weights)} days covered]")
        if k == 12:
            check("12 weighted representative days land within 2% of the year",
                  abs(err) < 2.0, f"off by {err:+.2f}%")


def part3b_commitment() -> None:
    """The same question with the integer rules ON, on a window still solvable whole.

    Part 3 ran a pure LP, because only an LP lets a whole year be solved as the
    truth to measure against. But the study's real scenarios carry minimum load,
    start costs and minimum up/down times -- and those are exactly what a day
    boundary cuts through. So the clustering is checked again here on ONE MONTH,
    where the full commitment problem can still be solved honestly, against
    representative days drawn from that month.
    """
    head("3.2  representative days under the real commitment rules (one month)")
    ex = D._jsx_loads()
    if not ex:
        print("  -- the JSX artifact is not present; skipping")
        return
    # The shape matters here. A continuous load runs the fleet flat out and never
    # starts anything -- the commitment rules are then inert and the test proves
    # nothing (measured: 0 starts, every method within 0.00%). "Deep nights and
    # weekends" (DOE warehouse) falls to 0.15x its mean at night, below the
    # minimum load of a single engine, so units must stop and restart. That is
    # what a day boundary can get wrong.
    year, _ = D.build_year(D.YEAR_SHAPES["Deep nights and weekends"], ex["week"])
    jan = year[:31 * 24]

    units = D.default_units(list(D.JSX_UNITS)[1])   # 3 units, 50% floor, 15k starts, 4/5 h
    bat = dict(kw=2500.0, kwh=5500.0, rte=0.88, soc_min=0.30, soc_init=0.5,
               cyclic=True, wear=0.5, grid_charge=False, capex=0.0)
    sc = {D.S_NAME: "A", D.S_MIN: None, D.S_BAT: True, D.S_SCALE: 100.0, D.S_MAXST: None}

    t0 = time.time()
    truth, truth_starts, status = window_run(jan, units, bat, sc, time_limit=1800, gap=1e-3)
    print(f"      January solved whole (744 h, MILP, {status}): {truth:>16,.0f}"
          f"   {truth_starts} starts   [{time.time() - t0:,.1f} s]\n")

    days = [jan[d * 24:(d + 1) * 24] for d in range(31)]
    for k in (4, 8, 31):
        t0 = time.time()
        reps, weights = kmeans_days(days, k)
        est, st = 0.0, 0.0
        for r, w in zip(reps, weights):
            c, s_, _ = window_run(r, units, bat, sc, time_limit=120, gap=1e-3)
            est += w * c
            st += w * s_
        err = 100 * (est / truth - 1)
        print(f"        k={k:>3}  {est:>16,.0f}   {err:+7.2f}%   "
              f"{st:>5,.0f} starts vs {truth_starts}   [{time.time() - t0:,.1f} s]")
        if k == 8:
            check("8 weighted representative days match the month, rules on",
                  abs(err) < 3.0, f"off by {err:+.2f}%")
    print("      k=31 is every day solved separately: it isolates the cost of the")
    print("      DAY BOUNDARY alone, with no clustering error left in it.")

    est_w, st_w, _ = window_run(jan[:168], units, bat, sc, time_limit=300, gap=1e-3)
    est_w *= 744 / 168
    print(f"\n      control -- the first week of January x 744/168: {est_w:>14,.0f}"
          f"   {100 * (est_w / truth - 1):+7.2f}%")


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    print(__doc__.strip().splitlines()[0])
    if which in ("2", "all"):
        part2_timebase()
    if which in ("2c", "25", "all"):
        part2c_lifecycle()
    if which in ("3", "all"):
        part3_annualisation()
    if which in ("3b", "all"):
        part3b_commitment()
    print(f"\n{'FAILED: ' + '; '.join(FAIL) if FAIL else 'all horizon checks passed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
