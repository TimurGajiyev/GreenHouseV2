"""How the study treats what the meters did not record (REPORT.md Part 18).

    python calculator/tools/test_missing_data.py

  A. nothing invented    every value real_data hands out is the table's own,
                         and the rebuilt flags are combine.py's
  B. rebuilt = balance   a reading the logger missed is the other side of the
                         same hour's balance, engine = plant - grid, nothing else
  C. whole days only     a kept day has 24 complete hours; a day with a hole
                         is left out whole
  D. no selection bias   the kept days run the engines about as often as all
                         the hours do -- dropping the rebuilt hours kept only
                         days the J320 never stopped (100 % / 99.5 % running)
  E. months not filled   a month with no measured hour makes the year a range,
                         between the lowest and the highest measured month

Needs the measured table (real_data/zharkent/data); says so and passes without it.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.WARNING)          # st.cache_data outside Streamlit warns

import pandas as pd

import app_dispatch as D
import real_data as RD
import year_study as Y

FAIL: list[str] = []
ON_KW = 50.0


def check(msg: str, cond: bool, detail: str = "") -> None:
    print(f"  {'OK' if cond else 'XX'}  {msg}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAIL.append(msg)


def head(s: str) -> None:
    print(f"\n{s}")


def a_nothing_invented(t: pd.DataFrame) -> None:
    head("A. nothing invented")
    for site in RD.SITES:
        plant, grid, engines, _, units, _ = RD.SITES[site]
        h = RD.hours(site)
        pairs = [("load", t[plant].clip(lower=0)), ("grid", t[grid])]
        pairs += [(u[0], t[c]) for u, c in zip(units, engines)]
        same = all(h[k].equals(v) for k, v in pairs)
        check(f"{site}: every value is the table's own, NaN where it is NaN", same)
        flags = all(h[f"rebuilt {u[0]}"].equals(
            t[RD.FROM_BALANCE[c]].fillna(False).astype(bool) if c in RD.FROM_BALANCE
            else pd.Series(False, index=t.index)) for u, c in zip(units, engines))
        check(f"{site}: the rebuilt flags are combine.py's", flags)


def b_rebuilt_is_balance(t: pd.DataFrame) -> None:
    head("B. a rebuilt reading is the same hour's balance")
    # the CC42 plant meter reads J320 + import; zhkpz_plant adds the TEDOM to it
    for eng, grid, plant, fe, fg in (
            ("j320_2_kw", "zhkpz_import_kw", t["zhkpz_plant_kw"] - t["tedom_kw"],
             "j320_2_from_balance", "import_2_from_balance"),
            ("j320_3_kw", "site3_import_kw", t["site3_plant_kw"],
             "j320_3_from_balance", "import_3_from_balance")):
        e = t[fe].fillna(False).astype(bool) & plant.notna()
        g = t[fg].fillna(False).astype(bool)
        # the table keeps one decimal, so two readings differ by rounding only
        de = (t.loc[e, eng] - (plant[e] - t.loc[e, grid]).clip(lower=0)).abs().max()
        dg = (t.loc[g, grid] - (plant[g] - t.loc[g, eng])).abs().max()
        check(f"{eng}: rebuilt engine = max(0, plant − grid)", de <= 0.25,
              f"{int(e.sum()):,} h, worst {de:.2f} kW")
        check(f"{grid}: rebuilt grid = plant − engine", dg <= 0.25,
              f"{int(g.sum()):,} h, worst {dg:.2f} kW")


def c_whole_days() -> None:
    head("C. whole days only")
    for site in RD.available():
        h, y = RD.hours(site), RD.year(site)
        kept = pd.DatetimeIndex(y["time"])
        ok = h["complete"].eq(True)
        by = ok.groupby(h.index.floor("D"))
        whole = by.size().eq(24) & by.all()
        check(f"{site}: the kept days are exactly the days with 24 complete hours",
              set(kept.floor("D")) == set(whole.index[whole]), f"{y['days']} days")
        series = [y["load"], y["grid"], y["buy"], y["sell"], *y["gpu_units"]]
        check(f"{site}: no hour of a kept day is blank",
              all(v == v for s in series for v in s) and len(kept) == 24 * y["days"])
        check(f"{site}: the rebuilt hours are counted",
              y["rebuilt_hours"] == int(h.loc[kept, "rebuilt"].eq(True).sum()),
              f"{y['rebuilt_hours']:,} of {y['hours']:,} h")


def d_no_selection_bias() -> None:
    head("D. the kept days are not the days the engines never stopped")
    for site in RD.SITES:
        h, y = RD.hours(site), RD.year(site)
        names = [u[0] for u in RD.units(site)]
        for j, name in enumerate(names):
            if "J320" not in name:
                continue
            every = h[name].dropna()
            kept = pd.Series(y["gpu_units"][j])
            a, k = 100 * (every > ON_KW).mean(), 100 * (kept > ON_KW).mean()
            check(f"{name}: running in {k:.1f} % of kept hours, {a:.1f} % of all hours",
                  abs(k - a) < 6.0, "within 6 points")
            check(f"{name}: the kept days hold engine outages", k < 95.0)


def e_months_not_filled() -> None:
    head("E. a month not measured is a range, never a value")
    t0 = dt.datetime(2026, 1, 1)
    year = [t0 + dt.timedelta(hours=h) for h in range(8760)]
    days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    keep = [x for x in year if x.month not in (2, 12)]
    lo, hi, miss = Y.month_range(keep, [float(x.month) for x in keep])
    have = sum(m * days[m - 1] * 24 for m in range(1, 13) if m not in (2, 12))
    check("February and December are taken at the lowest and the highest measured month",
          miss == [2, 12] and abs(lo - (have + 1 * 59 * 24)) < 1e-6
          and abs(hi - (have + 11 * 59 * 24)) < 1e-6, f"{lo:,.0f} … {hi:,.0f}")
    check("and month_year still gives no single figure for it",
          Y.month_year(keep, [1.0] * len(keep)) == (None, [2, 12]))
    full = Y.month_range(year, [1.0] * 8760)
    check("every month measured: one figure", full == (8760.0, 8760.0, []))
    for site in RD.available():
        y = RD.year(site)
        # one that differs by month, so a month not measured widens the range
        h = [float(t.month) for t in y["time"]]
        lo, hi, miss = Y.month_range(y["time"], h)
        out = {"time": y["time"]}
        page = D._annual(out, len(h), float(len(h)), h)
        check(f"{site}: the page's year is the month range"
              + (f" ({', '.join(D._MONTHS[m - 1] for m in miss)} not measured)" if miss else ""),
              page == (lo, hi) and (lo == hi) == (not miss))


def main() -> int:
    e_months_not_filled()
    if not RD.available():
        print(f"\nno measured table at {RD.TABLE}: the measured checks are skipped")
    else:
        t = RD._table()
        a_nothing_invented(t)
        b_rebuilt_is_balance(t)
        c_whole_days()
        d_no_selection_bias()
    print(f"\n{'FAILED: ' + '; '.join(FAIL) if FAIL else 'all missing-data checks passed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
