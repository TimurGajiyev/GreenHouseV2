"""Battery payback on the measured Zharkent data -- REPORT.md Part 18.

Every hour comes from the meters (real_data/zharkent/data/zharkent_all_hourly.csv,
built by real_data/zharkent/build.py and combine.py). Only fully measured days are
used and nothing inside a day is interpolated: no synthetic load anywhere.

    python calculator/tools/battery_real_data.py solve    # every measured day, ~10 min on 4 cores
    python calculator/tools/battery_real_data.py report   # tables from the saved results
    python calculator/tools/battery_real_data.py all      # both

Options -- the defaults are the dispatch study page's own:
    --grid-price 60   --gas-cost 22   --start-cost 15000   --capex 391000000
    --replace-year 15 --workers 4

Cases
  zhkpz     ЖКПЗ: TEDOM Quanto 1200 (Жаркент) + Jenbacher J320 (Жаркент 2) + city
  site3     Жаркент 3: Jenbacher J320 (CR06) + city
  combined  all three engines as one pool, on the days both plants are fully
            measured. The meters say these are two plants (combine.py), so this
            assumes a common bus. The CR06 logger runs on UTC+5, the CC42 logger
            and the dashboard on UTC+6, so CR06 is shifted by +1 h.

Three views of the same days
  free      optimiser, each day solved alone (24 h, cyclic); the engines may run
            in any hour -- what the study page assumes
  measured  optimiser; an engine may run only in the hours it actually ran
            (> 50 kW in the logger), the availability the site really had
  rule      no optimiser: the engines run exactly as logged and a battery is
            added by a plain rule (charge from export and from running-engine
            headroom at the marginal gas cost, discharge into purchases)

Scenarios: A = engines from 50 %, no battery; D = from 50 % + battery (the
battery alone, D - A); B = from 90 % + battery (the page's default, B - A).
Engines carry their OEM part-load curves (real_data.py), so a kWh at part load
costs more, as the data sheets say.

Results go to real_data/zharkent/battery/: days_<tag>.csv (one row per case,
mode, scenario and day), meta_<tag>.json (inputs, SHA-256 of the data table,
git commit) and summary_<tag>.md. <tag> names the prices, so a run at another
price does not overwrite the reference run.
"""
from __future__ import annotations

import argparse
import calendar
import collections
import csv
import hashlib
import json
import logging
import os
import subprocess
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
logging.disable(logging.WARNING)          # st.cache_data outside Streamlit warns
warnings.filterwarnings("ignore")

import pandas as pd                  # noqa: E402

import app_dispatch as D             # noqa: E402
import real_data as RD               # noqa: E402
import year_study as Y               # noqa: E402
from reopt_core import model as M    # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
OUT_DIR = os.path.join(ROOT, "real_data", "zharkent", "battery")

# The dispatch study page's battery panel defaults (app_dispatch.render).
BATTERY = dict(kw=2500.0, kwh=5500.0, rte=0.88, soc_min=0.30, soc_init=0.50, cyclic=True,
               wear=0.5, grid_charge=False)
YEARS, ESCALATION, DISCOUNT = 25, 0.034, 0.0624
KZT_PER_USD = 460.0              # «CAPEX 391 000 000 ₸ — 850 000 USD по курсу 460»
ON_KW = 50.0                     # above this a logged engine counts as running
TIME_LIMIT, MIP_GAP = 120, 1e-4  # per day; the page's 0.5 % would drown the battery
CASES = ("zhkpz", "site3", "combined")
MODES = ("free", "measured")
SCENARIOS = {"A": dict(minload=50.0), "D": dict(minload=50.0, bat=True),
             "B": dict(minload=90.0, bat=True)}
LABEL = {"zhkpz": "ЖКПЗ (TEDOM Quanto 1200 + J320 Жаркент 2)",
         "site3": "Жаркент 3 (J320)",
         "combined": "Three engines as one pool (ЖКПЗ + Жаркент 3)"}
DAYS_IN = {m: calendar.monthrange(2026, m)[1] for m in range(1, 13)}
FIELDS = ("case", "mode", "scen", "day", "status", "gap", "total", "gen_kwh", "gen_cost",
          "grid_kwh", "grid_cost", "starts", "start_cost", "discharge", "wear_cost", "spill")


# ------------------------------------------------------------------ inputs
def tag(p: dict) -> str:
    return f"grid{p['grid_price']:g}_gas{p['gas_cost']:g}"


def units_for(case: str, p: dict) -> pd.DataFrame:
    """The engines each plant runs, with their OEM curves, at the run's prices."""
    if case == "zhkpz":
        u = D.default_units(D.REAL_PRESET + RD.ZHKPZ)
    elif case == "site3":
        u = D.default_units(D.REAL_PRESET + RD.SITE3)
    else:
        u = pd.concat([D.default_units(D.REAL_PRESET + RD.ZHKPZ),
                       D.default_units(D.REAL_PRESET + RD.SITE3)], ignore_index=True)
    u[D.U_COST] = p["gas_cost"]
    u[D.U_START] = p["start_cost"]
    return u


def data_for(case: str) -> dict:
    """time, load, per-engine output, purchase and export on fully measured days."""
    if case in ("zhkpz", "site3"):
        y = RD.year(RD.ZHKPZ if case == "zhkpz" else RD.SITE3)
        return dict(time=[str(t) for t in y["time"]], load=y["load"], gpu_units=y["gpu_units"],
                    buy=[max(0.0, g) for g in y["grid"]], export=[max(0.0, -g) for g in y["grid"]])
    t = pd.read_csv(RD.TABLE, index_col=0, parse_dates=True)
    s3 = t[["j320_3_kw", "site3_import_kw", "site3_plant_kw", "site3_complete"]].copy()
    s3.index = s3.index + pd.Timedelta(hours=1)          # CR06 UTC+5 -> UTC+6
    c = t[["tedom_kw", "j320_2_kw", "zhkpz_import_kw", "zhkpz_plant_kw", "zhkpz_complete"]].join(s3)
    ok = c["zhkpz_complete"].astype(bool) & c["site3_complete"].fillna(False).astype(bool)
    day = c.index.floor("D")
    full = (ok.groupby(day).transform("size") == 24) & ok.groupby(day).transform("all")
    k = c[full]
    return dict(
        time=[str(x) for x in k.index],
        load=list((k.zhkpz_plant_kw.clip(lower=0) + k.site3_plant_kw.clip(lower=0)).astype(float)),
        gpu_units=[list(k.tedom_kw.astype(float)), list(k.j320_2_kw.astype(float)),
                   list(k.j320_3_kw.astype(float))],
        buy=list((k.zhkpz_import_kw.clip(lower=0) + k.site3_import_kw.clip(lower=0)).astype(float)),
        export=list((-k.zhkpz_import_kw.clip(upper=0) - k.site3_import_kw.clip(upper=0)).astype(float)))


def battery(p: dict) -> dict:
    return dict(BATTERY, capex=p["capex"])


# ------------------------------------------------------------------ solve
def solve_day(job: tuple) -> dict:
    case, mode, key, day, load24, avail, p = job
    units = units_for(case, p)
    sc = D._rule(key, **SCENARIOS[key])
    bat = battery(p)
    inp = D.build(load24, [p["grid_price"]] * 24, units, bat, sc)
    if mode == "measured":
        for g, u in enumerate(list(inp.fuel_techs) if inp.fuel_techs else [inp.fuel_tech]):
            u.production_factor_series = avail[g]
    res = M.solve(inp, time_limit=TIME_LIMIT, mip_gap=MIP_GAP)
    acc = D.account(res, [p["grid_price"]] * 24, units, bat["wear"] if sc[D.S_BAT] else 0.0)
    return dict(case=case, mode=mode, scen=key, day=day,
                **{k: acc[k] for k in FIELDS if k not in ("case", "mode", "scen", "day")})


def jobs(p: dict):
    for case in CASES:
        x = data_for(case)
        for d in range(len(x["load"]) // 24):
            sl = slice(24 * d, 24 * d + 24)
            avail = [[1.0 if v > ON_KW else 0.0 for v in s[sl]] for s in x["gpu_units"]]
            for mode in MODES:
                for key in SCENARIOS:
                    yield (case, mode, key, x["time"][24 * d][:10], x["load"][sl], avail, p)


def table_sha() -> str:
    h = hashlib.sha256()
    with open(RD.TABLE, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def solve(p: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"days_{tag(p)}.csv")
    n = 0
    with open(path, "w", encoding="utf-8", newline="") as fh, \
            ProcessPoolExecutor(max_workers=p["workers"]) as ex:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in ex.map(solve_day, jobs(p), chunksize=4):
            w.writerow(r)
            n += 1
            if n % 250 == 0:
                print(f"  {n} days solved", flush=True)
    meta = dict(params=p, battery=BATTERY, years=YEARS, escalation=ESCALATION, discount=DISCOUNT,
                time_limit=TIME_LIMIT, mip_gap=MIP_GAP, on_kw=ON_KW, solves=n,
                data_table=os.path.relpath(RD.TABLE, ROOT).replace(os.sep, "/"),
                data_sha256=table_sha(), git_commit=git_commit())
    with open(os.path.join(OUT_DIR, f"meta_{tag(p)}.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    print(f"{n} solves -> {os.path.relpath(path, ROOT)}")


# ------------------------------------------------------------------ report
def by_month(daily: dict) -> tuple[float, list[int]]:
    """{'YYYY-MM-DD': value} -> a year weighted by calendar month.

    Each month is its measured days' mean times its length; a month with no
    measured day takes the mean of the nearest measured months either side.
    A date measured in two years counts in its month once per year, i.e. the
    month's mean uses both."""
    acc = collections.defaultdict(list)
    for d, v in daily.items():
        acc[int(d[5:7])].append(v)
    mean = {m: sum(v) / len(v) for m, v in acc.items()}
    year = 0.0
    for m in range(1, 13):
        if m in mean:
            year += mean[m] * DAYS_IN[m]
            continue
        # neighbours are measured months only, never a month filled here
        prev = next(mean[(m - k - 2) % 12 + 1] for k in range(12) if (m - k - 2) % 12 + 1 in mean)
        nxt = next(mean[(m + k) % 12 + 1] for k in range(12) if (m + k) % 12 + 1 in mean)
        year += (prev + nxt) / 2 * DAYS_IN[m]
    return year, sorted(set(range(1, 13)) - set(mean))


def by_hours(daily: dict) -> float:
    """The study page's own annualisation: the kept days scaled to 365."""
    return sum(daily.values()) * 365.0 / len(daily) if daily else 0.0


def economics(save: float, p: dict) -> dict:
    lc = Y.lifecycle(0.0, years=YEARS, escalation=ESCALATION, discount=DISCOUNT,
                     annual_saving=save, capex=p["capex"])
    return dict(npv=lc.saving_present_value - p["capex"], simple=lc.simple_payback_years,
                discounted=lc.discounted_payback_years, pwf=lc.pwf)


def break_even(p: dict) -> tuple[float, float]:
    pwf = Y.lifecycle(0.0, years=YEARS, escalation=ESCALATION, discount=DISCOUNT).pwf
    replace = p["capex"] / (1 + DISCOUNT) ** p["replace_year"]
    return p["capex"] / pwf, (p["capex"] + replace) / pwf


def marginal_gas_cost(u) -> float:
    """Gas cost of one more kWh from a running engine, on its OEM affine curve."""
    price, slope, _ = D.fuel_curve(u)
    return price * slope


def rule_battery(x: dict, units: pd.DataFrame, p: dict, common_bus: bool = False) -> dict:
    """Engines exactly as logged, a battery added by rule; {date: saving}.

    Charge in hours without a purchase: first from what the site sent to the city
    (free), then from running engines' headroom at their marginal gas cost.
    Discharge into every purchase. With ``common_bus`` one plant's export first
    offsets the other's purchase in the same hour -- what a wire alone would do,
    so the battery is not credited with it."""
    eta = BATTERY["rte"] ** 0.5
    lo = BATTERY["soc_min"] * BATTERY["kwh"]
    soc = lo
    rows = [u for _, u in units.iterrows()]
    mc = [marginal_gas_cost(u) for u in rows]
    rated = [float(u[D.U_KW]) for u in rows]
    out = collections.defaultdict(float)
    for h in range(len(x["load"])):
        day = x["time"][h][:10]
        buy, exp = x["buy"][h], x["export"][h]
        if common_bus:
            net = buy - exp
            buy, exp = max(0.0, net), max(0.0, -net)
        room = BATTERY["kw"]
        if exp > 0:
            e = min(exp, room, (BATTERY["kwh"] - soc) / eta)
            soc += e * eta
            room -= e
        if buy <= 0:
            for g, s in enumerate(x["gpu_units"]):
                if s[h] <= ON_KW or room <= 0:
                    continue
                e = min(max(0.0, rated[g] - s[h]), room, (BATTERY["kwh"] - soc) / eta)
                soc += e * eta
                room -= e
                out[day] -= e * mc[g]
        else:
            e = min(buy, BATTERY["kw"], (soc - lo) * eta)
            soc -= e / eta
            out[day] += e * (p["grid_price"] - BATTERY["wear"])
    return out


def measured_daily(x: dict, units: pd.DataFrame, p: dict) -> dict:
    """The logger's own operation, priced exactly as a scenario is."""
    out = {}
    for d in range(len(x["load"]) // 24):
        sl = slice(24 * d, 24 * d + 24)
        meas = {"gpu": [sum(v) for v in zip(*[s[sl] for s in x["gpu_units"]])],
                "grid": x["buy"][sl], "gpu_units": [s[sl] for s in x["gpu_units"]]}
        out[x["time"][24 * d][:10]] = D.measured_account(meas, [p["grid_price"]] * 24, units)["total"]
    return out


def _yrs(v: float | None) -> str:
    return f"{v:.1f}" if v else "never"


def _m(v: float) -> str:
    return f"{v / 1e6:,.1f}"


def _npv(v: float) -> str:
    return f"{v / 1e6:,.0f} (${v / KZT_PER_USD / 1e3:,.0f}k)"


def report(p: dict) -> str:
    path = os.path.join(OUT_DIR, f"days_{tag(p)}.csv")
    with open(os.path.join(OUT_DIR, f"meta_{tag(p)}.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    res = collections.defaultdict(dict)
    for r in rows:
        res[(r["case"], r["mode"], r["scen"])][r["day"]] = float(r["total"])
    bad = sum(1 for r in rows if r["status"] != "Optimal")
    worst = max(float(r["gap"] or 0.0) for r in rows)
    be, be_rep = break_even(p)
    L = [f"# Battery payback on the measured Zharkent data — {tag(p)}", "",
         f"Grid {p['grid_price']:g} ₸/kWh · gas {p['gas_cost']:g} ₸/kWh at full load (OEM part-load "
         f"curves) · start {p['start_cost']:,.0f} ₸ · battery {BATTERY['kw']:,.0f} kW / "
         f"{BATTERY['kwh']:,.0f} kWh, RTE {BATTERY['rte']:.0%}, SoC ≥ {BATTERY['soc_min']:.0%}, "
         f"wear {BATTERY['wear']} ₸/kWh · CAPEX {p['capex']:,.0f} ₸ · {YEARS} yr, escalation "
         f"{ESCALATION:.1%}, discount {DISCOUNT:.2%}.", "",
         f"Solves {len(rows):,}, not Optimal {bad}, worst gap {worst:.1e}. Data table SHA-256 "
         f"`{meta['data_sha256'][:16]}…`, commit `{(meta.get('git_commit') or '?')[:7]}`.", "",
         f"Break-even saving: **{_m(be)} M ₸/yr** without a battery replacement, "
         f"**{_m(be_rep)} M ₸/yr** with one replacement at the same price in year "
         f"{p['replace_year']}.", ""]
    if meta["data_sha256"] != table_sha():
        L += ["> **The data table has changed since this run was solved.** Run `solve` again.", ""]
    for case in CASES:
        x = data_for(case)
        units = units_for(case, p)
        days = sorted({t[:10] for t in x["time"]})
        meas = measured_daily(x, units, p)
        m_year, missing = by_month(meas)
        L += [f"## {LABEL[case]}", "",
              f"{len(days)} fully measured days, {days[0]} – {days[-1]}"
              + (f"; months with no measured day, filled from their neighbours: {missing}" if missing else "")
              + f". Over those days: load {sum(x['load']) / 1e3:,.0f} MWh, bought "
              f"{sum(x['buy']) / 1e3:,.0f} MWh, sent to the city {sum(x['export']) / 1e3:,.0f} MWh.", "",
              f"Measured operation, priced as a scenario: **{_m(m_year)} M ₸/yr** "
              f"({_m(by_hours(meas))} scaled by hours).", "",
              "| View | A, M ₸/yr | A − measured | Battery D−A, M ₸/yr | by hours | NPV, M ₸ | Payback simple / disc., yr | Page default B−A, M ₸/yr |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for mode in MODES:
            a = res[(case, mode, "A")]
            if len(a) != len(days):
                L.append(f"| {mode} | incomplete: {len(a)} of {len(days)} days | | | | | | |")
                continue
            a_y, _ = by_month(a)
            dsave = {d: a[d] - res[(case, mode, "D")][d] for d in a}
            bsave = {d: a[d] - res[(case, mode, "B")][d] for d in a}
            dm, _ = by_month(dsave)
            bm, _ = by_month(bsave)
            e = economics(dm, p)
            name = "optimiser, engines free" if mode == "free" else "optimiser, availability as measured"
            L.append(f"| {name} | {_m(a_y)} | {_m(a_y - m_year)} | **{_m(dm)}** | {_m(by_hours(dsave))} | "
                     f"{_npv(e['npv'])} | {_yrs(e['simple'])} / {_yrs(e['discounted'])} | {_m(bm)} |")
        for bus in ((False, True) if case == "combined" else (False,)):
            rb = rule_battery(x, units, p, common_bus=bus)
            rd = {d: rb.get(d, 0.0) for d in days}
            ry, _ = by_month(rd)
            e = economics(ry, p)
            name = ("engines as logged + battery by rule"
                    + (", common bus (export offsets the other plant first)" if bus else
                       (", no bus netting (credits the battery with a wire's work)" if case == "combined" else "")))
            L.append(f"| {name} | — | — | **{_m(ry)}** | {_m(by_hours(rd))} | {_npv(e['npv'])} | "
                     f"{_yrs(e['simple'])} / {_yrs(e['discounted'])} | — |")
        L.append("")
    L += [f"US$ at {KZT_PER_USD:,.0f} ₸/$. Annual figures are weighted by calendar month; "
          "'by hours' is the study page's own scaling of the kept days to a year.", ""]
    text = "\n".join(L)
    with open(os.path.join(OUT_DIR, f"summary_{tag(p)}.md"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("solve", "report", "all"))
    ap.add_argument("--grid-price", type=float, default=60.0)
    ap.add_argument("--gas-cost", type=float, default=22.0)
    ap.add_argument("--start-cost", type=float, default=15_000.0)
    ap.add_argument("--capex", type=float, default=391_000_000.0)
    ap.add_argument("--replace-year", type=int, default=15)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if not RD.available():
        sys.exit(f"No measured table at {RD.TABLE}; run real_data/zharkent/build.py and combine.py.")
    p = dict(grid_price=a.grid_price, gas_cost=a.gas_cost, start_cost=a.start_cost,
             capex=a.capex, replace_year=a.replace_year, workers=a.workers)
    if a.action in ("solve", "all"):
        solve(p)
    if a.action in ("report", "all"):
        print(report(p))


if __name__ == "__main__":
    main()
