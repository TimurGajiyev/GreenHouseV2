"""The year on a measured plant, the way the dispatch study now covers it.

    python calculator/tools/test_year_measured.py

What REPORT.md Part 16's real-data check changed, each held to a second route:

  A. every day on its own   year_study.every_day: no clustering, day c is day c
  B. calendar months        year_study.month_year: a month measured twice counts
                            once, a missing month takes its neighbours' mean
  C. availability           the logger's on/off hours reach the core as each
                            engine's production_factor_series, and an engine the
                            logger shows down produces nothing
  D. the page's own path    build() + solve_year(day_pose=...) reproduces the
                            day-by-day reference run in real_data/zharkent/battery
  E. accounting             the hourly costs a month weighting sums are the
                            costs the totals report, measured and solved alike
  F. resolution             a battery saving inside the solver's gaps is named

Needs the measured table (real_data/zharkent/data); says so and passes without it.
"""
from __future__ import annotations

import csv
import datetime as dt
import logging
import os
import sys
import warnings

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")

import app_dispatch as D        # noqa: E402
import real_data as RD          # noqa: E402
import year_study as Y          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
REF = os.path.join(ROOT, "real_data", "zharkent", "battery", "days_grid60_gas22.csv")
FAIL: list[str] = []
PRICE = 60.0
BAT = dict(kw=2500.0, kwh=5500.0, rte=0.88, soc_min=0.30, soc_init=0.50, cyclic=True,
           wear=0.5, grid_charge=False, capex=391_000_000.0)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK' if ok else 'XX'}  {name}{('   ' + detail) if detail else ''}")
    if not ok:
        FAIL.append(name)


def head(t: str) -> None:
    print(f"\n{t}\n{'-' * len(t)}")


def close(a: float, b: float, rel: float = 1e-9, abs_: float = 1e-6) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def a_every_day() -> None:
    head("A. every day on its own")
    load = [float(h % 24 + 10 * d) for d in range(5) for h in range(24)]
    typ = Y.every_day(load, [PRICE] * len(load))
    check("one typical day per day, each weighted 1", typ.k == 5 and typ.weights == [1] * 5)
    check("day c is day c of the horizon", typ.day_of == list(range(5))
          and all(typ.load[d] == load[24 * d:24 * d + 24] for d in range(5)))
    check("a typical day's members are its own day", Y.members(typ, 3) == [3])
    try:
        Y.every_day(load[:-1], [PRICE] * (len(load) - 1))
        check("a horizon that is not whole days is refused", False)
    except ValueError:
        check("a horizon that is not whole days is refused", True)


def b_months() -> None:
    head("B. calendar months")
    t0 = dt.datetime(2026, 1, 1)
    year = [t0 + dt.timedelta(hours=h) for h in range(8760)]
    v, miss = Y.month_year(year, [1.0] * 8760)
    check("one per hour over a calendar year is 8,760", close(v, 8760.0) and not miss)
    keep = [i for i, t in enumerate(year) if t.month not in (2, 12)]
    v, miss = Y.month_year([year[i] for i in keep], [1.0] * len(keep))
    check("missing February and December are filled from their neighbours",
          close(v, 8760.0) and miss == [2, 12], f"missing {miss}")
    # September measured in two years at two levels counts once, at their mean
    sep25 = [dt.datetime(2025, 9, 1) + dt.timedelta(hours=h) for h in range(720)]
    sep26 = [dt.datetime(2026, 9, 1) + dt.timedelta(hours=h) for h in range(720)]
    rest = [t for t in year if t.month != 9]
    v, _ = Y.month_year(sep25 + sep26 + rest, [1.0] * 720 + [3.0] * 720 + [1.0] * len(rest))
    check("a month measured twice counts once, at its mean", close(v, 8760.0 + 720.0))
    # the hours rule and the per-day rule of battery_real_data agree
    sys.path.insert(0, HERE)
    import battery_real_data as BR
    days = sorted({str(t)[:10] for t in year})
    daily = {d: float(int(d[5:7])) * 24 for d in days if d[5:7] != "05"}
    hourly_t = [t for t in year if str(t)[:10] in daily]
    hourly_v = [daily[str(t)[:10]] / 24 for t in hourly_t]
    check("hours and whole days give the same year",
          close(BR.by_month(daily)[0], Y.month_year(hourly_t, hourly_v)[0]))


def c_availability(site: str) -> dict:
    head(f"C. availability · {site}")
    y = RD.year(site)
    units = D.default_units(D.REAL_PRESET + site)
    meas = {"gpu": y["gpu"], "grid": y["grid"], "gpu_units": y["gpu_units"]}
    av = D.measured_availability(meas, units)
    check("one 0/1 series per engine, as long as the load",
          av is not None and len(av) == len(y["gpu_units"])
          and all(len(a) == len(y["load"]) and set(a) <= {0.0, 1.0} for a in av))
    check("an hour is available exactly when the logger shows the engine above 50 kW",
          all(a[t] == (1.0 if s[t] > D.ON_KW else 0.0)
              for a, s in zip(av, y["gpu_units"]) for t in range(len(a))))
    short = units.iloc[1:] if len(units.index) > 1 else units.assign(**{D.U_KW: 0.0})
    check("a table that no longer matches the engines is not paired",
          D.measured_availability(meas, short) is None)
    sc = D._rule("A", minload=50.0)
    inp = D.build(y["load"][:48], [PRICE] * 48, units, BAT, sc, avail=[a[:48] for a in av])
    fts = list(inp.fuel_techs) if inp.fuel_techs else [inp.fuel_tech]
    check("build() hands each engine its own series",
          all(f.production_factor_series == a[:48] for f, a in zip(fts, av)))
    typ = Y.cluster(y["load"], [PRICE] * len(y["load"]), 6)
    c = 0
    dm = Y.members(typ, c)
    da = D.day_availability(av, typ, c)
    check("a cluster's availability is the mean of its days",
          all(close(da[g][h], sum(av[g][24 * d + h] for d in dm) / len(dm))
              for g in range(len(av)) for h in range(24)))
    return dict(y=y, units=units, meas=meas, av=av)


def d_page_path(site: str, ctx: dict, case: str, n_days: int = 6) -> None:
    head(f"D/E. the page's day-by-day path · {site}")
    y, units, av = ctx["y"], ctx["units"], ctx["av"]
    H = 24 * n_days
    load, price = y["load"][:H], [PRICE] * H
    ref = {}
    if os.path.exists(REF):
        with open(REF, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["case"] == case:
                    ref[(r["mode"], r["scen"], r["day"])] = float(r["total"])
    days = [str(t)[:10] for t in y["time"][:H:24]]
    typ = Y.every_day(load, price)
    for mode in ("free", "measured"):
        a = av if mode == "measured" else None
        for key, rule in (("A", D._rule("A", minload=50.0)),
                          ("D", D._rule("D", minload=50.0, bat=True))):
            wear = BAT["wear"] if rule[D.S_BAT] else 0.0
            res = Y.solve_year(None, load, price, typ.k, typical=typ, mip_gap=1e-4,
                               day_pose=lambda c, dl, dp, _r=rule, _a=a: D.build(
                                   dl, dp, units, BAT, _r, avail=D.day_availability(_a, typ, c)))
            acc = D.account(res, price, units, wear)
            hourly = D.hourly(res, price, units, wear)
            hsum = sum(e + o for e, o in zip(hourly["energy"], hourly["ops"]))
            check(f"{mode} {key}: hourly costs add up to the total",
                  close(hsum, acc["total"], rel=1e-6), f"{hsum:,.0f} vs {acc['total']:,.0f}")
            if ref:
                # the reference solved each day alone with no join charge; the
                # page's replay adds the starts two unlike days create
                want = sum(ref[(mode, key, d)] for d in days)
                got = acc["total"] - res["typical"]["join_start_cost"]
                check(f"{mode} {key}: the page path reproduces the reference run",
                      close(got, want, rel=2e-4), f"{got:,.0f} vs {want:,.0f}")
            if mode == "measured":
                down = [(g, t) for g, s in enumerate(a) for t in range(H) if s[t] < 0.5]
                gen = res["series"]["fueltech_unit_kw"]
                names = list(gen)
                check(f"{mode} {key}: an engine the logger shows down produces nothing",
                      all(gen[names[g]][t] <= 1e-6 for g, t in down), f"{len(down)} down hours")


def e_measured_costs(site: str, ctx: dict) -> None:
    head(f"E. measured operation, hour by hour · {site}")
    m = D.measured_account(ctx["meas"], [PRICE] * len(ctx["y"]["load"]), ctx["units"])
    h = D.measured_hourly(ctx["meas"], [PRICE] * len(ctx["y"]["load"]), ctx["units"])
    check("the logged hours add up to measured_account's total",
          close(sum(h), m["total"], rel=1e-9), f"{sum(h):,.0f} vs {m['total']:,.0f}")
    out = {"time": ctx["y"]["time"]}
    yr = D._annual(out, len(h), m["total"], h)
    by_m, _ = Y.month_year(ctx["y"]["time"], h)
    check("a measured horizon is carried to a year by calendar month", close(yr, by_m))
    check("a horizon without dates is scaled by hours",
          close(D._annual({}, len(h), m["total"], h), m["total"] * 8760 / len(h)))


def f_resolution() -> None:
    head("F. a battery saving the gaps cannot resolve is named")
    def run(name, total, gap, battery, rule=50.0):
        return {"name": name, "battery": battery, "rule": rule, "scale": 100.0,
                "starts": None, "acc": {"total": total, "gap": gap}}
    a = run("A", 1_000_000.0, 0.005, False)
    d = run("D", 996_000.0, 0.005, True)
    check("a 0.4 % saving inside two 0.5 % gaps is unresolved",
          [(x[0], x[1]) for x in D._unresolved([a, d])] == [("D", "A")])
    a2, d2 = run("A", 1_000_000.0, 1e-4, False), run("D", 996_000.0, 1e-4, True)
    check("the same saving at 0.01 % gaps is resolved", D._unresolved([a2, d2]) == [])
    lp_a, lp_d = run("A", 1_000.0, None, False), run("D", 1_000.0, None, True)
    check("a pair of LPs with no gap at all is never flagged", D._unresolved([lp_a, lp_d]) == [])


def main() -> int:
    a_every_day()
    b_months()
    f_resolution()
    if not RD.available():
        print(f"\nno measured table at {RD.TABLE}: the measured checks are skipped")
    else:
        for site, case in ((RD.ZHKPZ, "zhkpz"), (RD.SITE3, "site3")):
            ctx = c_availability(site)
            e_measured_costs(site, ctx)
            d_page_path(site, ctx, case)
    print(f"\n{'FAILED: ' + '; '.join(FAIL) if FAIL else 'all measured-year checks passed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
