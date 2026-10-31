"""How "A year, and twenty-five of them" carries a window of a measured plant
to a year and to 25 years.

    python calculator/tools/test_year_window.py

A window is the hours the Load panel cuts (start, length) from the measured
days, which real_data.year lays end to end: a day is any 24 measured hours in
a row (real_data.days), so the days of a window need not be consecutive in
time, and some start off midnight.

  A. coverage    typical days with as many clusters as the window has days
                 are every day solved on its own: the two modes are one
                 method at k = n, on a window of calendar days and on one of
                 days that start off midnight
  B. a year      the window's per-year figure, and the battery's saving per
                 year, are the month range of its own hours
  C. 25 years    the lifecycle the comparison shows is the year's saving,
                 escalated and discounted, less the battery's CAPEX, O&M
                 and replacement, at both ends of the range

Printed as NOTE, not failed: what the window does with measured days that are
not consecutive -- "Solve the window as posed" runs straight through the gaps,
a start off a day boundary splices two days into one, and a window inside one
month gives a single per-year figure with eleven months not measured.

Needs the measured table (real_data/zharkent/data); says so and passes without it.
"""
from __future__ import annotations

import logging
import os
import sys
import warnings

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")

import pandas as pd             # noqa: E402

import app_dispatch as D        # noqa: E402
import real_data as RD          # noqa: E402
import year_study as Y          # noqa: E402

FAIL: list[str] = []
PRICE = 60.0
# the page's battery and 25-year defaults
BAT = dict(kw=2500.0, kwh=5500.0, rte=0.88, soc_min=0.30, soc_init=0.50, cyclic=True,
           wear=0.5, grid_charge=False, capex=391_000_000.0,
           om_fraction=0.025, replace_year=10, replace_fraction=1.0)
LIFE = dict(years=25, escalation=0.034, discount=0.0624)
RULES = (("A", D._rule("A", minload=50.0)), ("D", D._rule("D", minload=50.0, bat=True)))
HOUR = pd.Timedelta(hours=1)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK' if ok else 'XX'}  {name}{('   ' + detail) if detail else ''}")
    if not ok:
        FAIL.append(name)


def note(text: str) -> None:
    print(f"  NOTE  {text}")


def head(t: str) -> None:
    print(f"\n{t}\n{'-' * len(t)}")


def close(a: float, b: float, rel: float = 1e-9, abs_: float = 1e-6) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def cut(y: dict, start: int, length: int) -> dict:
    """What the Load panel hands on: the window's hours, timestamps and meters."""
    sl = slice(start, start + length)
    return dict(load=y["load"][sl], time=y["time"][sl], gpu=y["gpu"][sl],
                grid=y["grid"][sl], gpu_units=[g[sl] for g in y["gpu_units"]])


def solve(w: dict, units: pd.DataFrame, typ, name: str, rule: dict) -> dict:
    """One scenario over the window, by the page's own path (render's Solve)."""
    price = [PRICE] * len(w["load"])
    av = D.measured_availability(w, units)
    res = Y.solve_year(None, w["load"], price, typ.k, typical=typ, mip_gap=1e-4,
                       day_pose=lambda c, dl, dp: D.build(
                           dl, dp, units, BAT, rule, avail=D.day_availability(av, typ, c)))
    used = [p for c in typ.day_of for p in typ.price[c]]
    wear = BAT["wear"] if rule[D.S_BAT] else 0.0
    return {"name": name, "battery": bool(rule[D.S_BAT]), "res": res,
            "acc": D.account(res, used, units, wear), "hourly": D.hourly(res, used, units, wear)}


def a_coverage(site: str, y: dict, units: pd.DataFrame, start: int, n: int, what: str) -> dict:
    head(f"A. typical days at k = n are every day · {what}")
    w = cut(y, start, 24 * n)
    t = pd.DatetimeIndex(w["time"])
    print(f"  window: {n} days from {t[0]:%d.%m.%Y %H:%M}, "
          f"{sum(1 for d in range(n) if t[24 * d].hour):d} of them off midnight")
    price = [PRICE] * len(w["load"])
    every, typical = Y.every_day(w["load"], price), Y.cluster(w["load"], price, n)
    check("k = n gives every day its own cluster, weighted 1",
          typical.k == n and sorted(typical.day_of) == list(range(n)) and typical.weights == [1] * n)
    runs = {}
    for name, rule in RULES:
        e = solve(w, units, every, name, rule)
        k = solve(w, units, typical, name, rule)
        check(f"{name}: same total either way", close(e["acc"]["total"], k["acc"]["total"], rel=2e-4),
              f"{e['acc']['total']:,.0f} vs {k['acc']['total']:,.0f}")
        runs[name] = e
    return dict(w=w, runs=runs)


def b_year(ctx: dict) -> None:
    head("B. the window's year is its month range")
    w, runs = ctx["w"], ctx["runs"]
    out, H = {"time": w["time"]}, len(w["load"])
    for name, r in runs.items():
        cost = D._run_hourly_cost(r)
        lo, hi, gap = Y.month_range(w["time"], cost)
        check(f"{name}: per year = month range of its hours", D._run_year(r, out, H) == (lo, hi),
              f"{lo / 1e6:,.1f} … {hi / 1e6:,.1f} M ₸/yr, {len(gap)} months not measured")
    a, d = runs["A"], runs["D"]
    diff = [x - z for x, z in zip(D._run_hourly_cost(a), D._run_hourly_cost(d))]
    check("the battery's saving per year is ranged on the hour-by-hour difference",
          D._gain_year(d, a, out, H) == Y.month_range(w["time"], diff)[:2])


def c_lifetime(ctx: dict) -> None:
    head("C. 25 years of the window's year")
    w, runs = ctx["w"], ctx["runs"]
    out = {"time": w["time"], "bat": BAT, "life": LIFE}
    year, extra, lcs, reverse = D._pair_life(runs["D"], runs["A"], out, len(w["load"]))
    check("D buys the battery: its CAPEX, its side, both ends of the range",
          extra == BAT["capex"] and not reverse and lcs is not None and len(lcs) == 2)
    growth = (1 + LIFE["escalation"]) / (1 + LIFE["discount"])
    pwf = sum(growth ** t for t in range(1, LIFE["years"] + 1))
    # REopt's annuity rounds the factor to 5 decimals (finance.annuity)
    check("the present-worth factor is the year-by-year sum, as REopt rounds it",
          close(lcs[0].pwf, pwf, rel=1e-6), f"{lcs[0].pwf} vs {pwf:.9f}")
    for end, s, lc in zip(("low", "high"), year, lcs):
        check(f"{end}: the saving is the year's, escalated and discounted year by year",
              close(lc.annual_saving, s) and close(lc.saving_present_value, s * lc.pwf),
              f"{s / 1e6:,.1f} M ₸/yr × {lc.pwf}")
        check(f"{end}: NPV = saving − CAPEX − O&M − replacement, all present value",
              close(lc.net_present_value, lc.saving_present_value - BAT["capex"]
                    - lc.om_present_value - lc.replace_present_value, rel=1e-9),
              f"NPV {lc.net_present_value / 1e6:,.0f} M ₸, payback "
              f"{lc.simple_payback_years or 'never'}")


def notes(site: str, y: dict) -> None:
    head(f"NOTES · {site}")
    t = pd.DatetimeIndex(y["time"])
    seams = [i for i in range(1, len(t)) if t[i] - t[i - 1] != HOUR]
    weeks = range(0, len(t) - 168 + 1, 24)
    crossing = sum(1 for s in weeks if any(s < i < s + 168 for i in seams))
    note(f"the measured days have {len(seams)} gaps between them; {crossing} of {len(weeks)} "
         f"week-long windows cross one. 'Every day solved on its own' is unaffected, but "
         f"'Solve the window as posed' runs straight through a gap: the battery's charge and "
         f"the minimum up/down times carry over hours that are days or weeks apart")
    spliced = sum(1 for d in range(6) if t[12 + 24 * d + 23] - t[12 + 24 * d] != 23 * HOUR)
    note(f"a window starting at hour 12 instead of 0: {spliced} of its first 6 'days' join "
         f"two measured days that are not consecutive in time. The start hour is free on the "
         f"page; only a multiple of 24 keeps the measured days whole")
    may = [i for i, x in enumerate(t) if x.month == t[0].month and x.year == t[0].year]
    if len(may) >= 48:
        lo, hi, gap = Y.month_range([t[i] for i in may], [float(i % 24) for i in may])
        note(f"a window inside one month ({t[0]:%B %Y}): per year {lo:,.0f} … {hi:,.0f}, one "
             f"figure, though {len(gap)} months are not measured -- with one month measured "
             f"its lowest and highest are the same month")


def main() -> int:
    if not RD.available():
        print(f"no measured table at {RD.TABLE}: nothing to check")
        return 0
    site = RD.ZHKPZ
    y = RD.year(site)
    units = D.default_units(D.REAL_PRESET + site)
    t = pd.DatetimeIndex(y["time"])
    # six calendar days in a row, and the first six days, most of them off midnight
    cal = next(d for d in range(y["days"] - 5)
               if all(t[24 * (d + i)].hour == 0 for i in range(6)))
    first = a_coverage(site, y, units, 24 * cal, 6, "six calendar days")
    a_coverage(site, y, units, 0, 6, "days off midnight")
    b_year(first)
    c_lifetime(first)
    notes(site, y)
    print(f"\n{'FAILED: ' + '; '.join(FAIL) if FAIL else 'all window checks passed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
