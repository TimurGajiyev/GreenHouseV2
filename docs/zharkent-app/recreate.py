"""Rebuild the Zharkent app's battery method from its published numbers.

    python docs/zharkent-app/recreate.py            the default run, checked step by step
    python docs/zharkent-app/recreate.py sizes      every size of the default run
    python docs/zharkent-app/recreate.py split      what the saving is made of
    python docs/zharkent-app/recreate.py alone      the battery's own saving, every size

Input: the app's own files for the run "Default inputs" (16 Oct 2026 13:51), fetched from
https://zharkent.tail042aa5.ts.net/app/static/runs/c1621a84d5f54a63/ into
.playwright/output/zharkent/ (git-ignored: the colleague's data, not ours):

    runs_c1621a84d5f54a63_decisions.csv.gz   every 5-minute step he simulated
    runs_c1621a84d5f54a63_results.csv        his yearly figures for every size

The decisions file carries the measured load and engines of every step (the input) and
his rule's engines, battery and import (the output). The rule below was read off his
decision texts ("hold", "START", "STOP", "no unit free to start", "engines below the
band") and his inputs table; every constant is his, nothing is ours.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, ".playwright", "output", "zharkent")
RUN = "c1621a84d5f54a63"

# ---- his inputs (Inputs of this run; derived line) ---------------------------------
DT = 5 / 60                                     # h per step
RATED = {"mwm": 1200.0, "zh2": 1066.0, "zh3": 1066.0}
# fuel line: kW of gas through rated x load / efficiency at 50, 75 and 100 % (his
# "straight lines through 600 kW -> 1 493 kW ..."), the 50-75 % slope below 50 %
EFF = {"mwm": {0.5: 0.402, 0.75: 0.424, 1.0: 0.436}, "zh2": {0.5: 0.396, 0.75: 0.419, 1.0: 0.432}}
EFF["zh3"] = EFF["zh2"]
FUEL_PTS = {u: ([RATED[u] * f for f in e], [RATED[u] * f / v for f, v in e.items()])
            for u, e in EFF.items()}
RUN_KW = 50.0                                   # "engine counts as running above"
GAS = 75.0 / 1.12 / 9.44                        # KZT per kWh of gas = 7.094
GRID = 50.0 / 1.12                              # KZT per kWh imported = 44.64
OM_H = {u: 6.0 * kw for u, kw in RATED.items()} # KZT per engine hour = 6 KZT/kWh x rated
START_H = 4.0                                   # engine hours per start (default)
BAND, FLOOR = 0.90, 0.50                        # band; datasheet minimum
EXPORT = False                                  # "Allow export (not compensated)"
RTE, LO, HI, TAPER = 0.88, 0.10, 0.95, 0.85     # battery
AUX = 15.0                                      # battery's own use, kW
MIN_ON, MIN_OFF = 6, 3                          # 0.5 h and 0.25 h in steps
BAT_USD_KWH, INV_USD_KW, KZT_USD = 150.0, 120.0, 480.0
CYCLE_LIFE, CAL_LIFE = 6000.0, 15.0
COVERAGE = 0.25                                 # month kept if this share of hours closes
UNITS = {"K": ["mwm", "zh2"], "M": ["zh3"], "KM": ["mwm", "zh2", "zh3"]}


def fuel_kw(u: str, p: np.ndarray) -> np.ndarray:
    xs, ys = FUEL_PTS[u]
    slope = (ys[1] - ys[0]) / (xs[1] - xs[0])
    f = np.where(p < xs[0], ys[0] + slope * (p - xs[0]), np.interp(p, xs, ys))
    return np.where(p > RUN_KW, f, 0.0)


def steps(group: str) -> pd.DataFrame:
    d = pd.read_csv(os.path.join(DATA, f"runs_{RUN}_decisions.csv.gz"), parse_dates=["time"],
                    low_memory=False)
    x = d[d.group == group].sort_values("time").reset_index(drop=True)
    x["new"] = x["time"].diff() != pd.Timedelta(minutes=5)
    return x


# ---- a year from the steps: his month scaling ----------------------------------------
def year(x: pd.DataFrame, per_step: pd.DataFrame) -> pd.Series:
    """Each month x (hours in month / complete hours); months under 25 % dropped;
    the year = the mean of the months kept x 12."""
    m = x["time"].dt.to_period("M")
    hours = m.map(lambda p: p.days_in_month * 24)
    have = per_step.groupby(m).sum()
    complete = x.groupby(m).size() * DT
    in_month = hours.groupby(m).first()
    keep = complete / in_month >= COVERAGE
    scaled = have[keep].mul(in_month[keep] / complete[keep], axis=0)
    return scaled.sum() * 12 / int(keep.sum())


def cost(x: pd.DataFrame, out: dict[str, np.ndarray], imp: np.ndarray, exp: np.ndarray,
         start_h: float = START_H, extra: dict | None = None) -> pd.Series:
    """Fuel + service (engine hours + starts x start wear) + grid, per year."""
    cols = {}
    new = x["new"].values
    for u, p in out.items():
        run = p > RUN_KW
        # a start inside a stretch, or the rule switching on at a stretch's first step an
        # engine the meters show off there (how his starts add up, to the start)
        meas = x[f"{u}_measured"].fillna(0).values > RUN_KW
        start = (run & ~np.r_[False, run[:-1]] & ~new) | (new & run & ~meas)
        cols[f"{u}_fuel"] = fuel_kw(u, p) * DT
        cols[f"{u}_run_h"] = run * DT
        cols[f"{u}_starts"] = start.astype(float)
        cols[f"{u}_kwh"] = p * DT
    cols["imp_kwh"], cols["exp_kwh"] = imp * DT, exp * DT
    for k, v in (extra or {}).items():
        cols[k] = v
    y = year(x, pd.DataFrame(cols))
    us = list(out)
    y["fuel_kwh"] = sum(y[f"{u}_fuel"] for u in us)
    y["fuel_kzt"] = y["fuel_kwh"] * GAS
    y["run_h"] = sum(y[f"{u}_run_h"] for u in us)
    y["starts"] = sum(y[f"{u}_starts"] for u in us)
    y["om_kzt"] = sum((y[f"{u}_run_h"] + start_h * y[f"{u}_starts"]) * OM_H[u] for u in us)
    y["grid_kzt"] = y["imp_kwh"] * GRID
    y["gen_kwh"] = sum(y[f"{u}_kwh"] for u in us)
    y["cost_kzt"] = y["fuel_kzt"] + y["om_kzt"] + y["grid_kzt"]
    y["kzt_per_kwh_gen"] = (y["fuel_kzt"] + y["om_kzt"]) / y["gen_kwh"]
    return y


def base(x: pd.DataFrame, units: list[str], start_h: float = START_H) -> pd.Series:
    """Today, from the meters: each engine as measured, the grid as measured."""
    g = x["grid_measured"].values
    return cost(x, {u: x[f"{u}_measured"].fillna(0).values for u in units},
                np.maximum(g, 0), np.maximum(-g, 0), start_h)


# ---- the rule --------------------------------------------------------------------------
def simulate(x: pd.DataFrame, units: list[str], e_kwh: float, p_kw: float,
             avail: dict[str, np.ndarray] | None = None) -> dict:
    """His rule, step by step. ``avail`` (ours, not his) limits each engine to the steps
    the meters show it running; None = always available, as he has it."""
    n, eta = len(x), RTE ** 0.5
    load = x["load"].values
    new = x["new"].values
    meas_on = {u: (x[f"{u}_measured"].fillna(0).values > RUN_KW) for u in units}
    out = {u: np.zeros(n) for u in units}
    soc_s, ch_s, dis_s, imp_s, exp_s, oob, forced = (np.zeros(n) for _ in range(7))
    on = {u: False for u in units}
    age = {u: 0 for u in units}
    soc = 0.5
    for i in range(n):
        if new[i]:                               # a new stretch: 50 % charge, engines as measured
            soc = 0.5
            for u in units:
                on[u], age[u] = bool(meas_on[u][i]), 10 ** 6
        free = {u: avail is None or bool(avail[u][i]) for u in units}
        for u in units:                          # an engine the meters show down is stopped
            if on[u] and not free[u]:
                on[u], age[u] = False, 0
        need = load[i] + AUX if e_kwh > 0 else load[i]
        give = min(p_kw, max(0.0, (soc - LO) * e_kwh * eta / DT)) if e_kwh > 0 else 0.0
        taper = min(1.0, (1.0 - soc) / (1.0 - TAPER))
        take = min(p_kw * taper, max(0.0, (HI - soc) * e_kwh / eta / DT)) if e_kwh > 0 else 0.0
        r_on = sum(RATED[u] for u in units if on[u])
        if r_on + give < need:                   # short: start the engine off the longest,
            while r_on + give < need:            # and the next one if that is not enough
                cand = [u for u in units if not on[u] and age[u] >= MIN_OFF and free[u]]
                if not cand:
                    break
                u = max(cand, key=lambda k: age[k])
                on[u], age[u] = True, 0
                r_on += RATED[u]
        elif BAND * r_on > need + take:          # surplus even at the band: stop the longest-running
            cand = [u for u in units if on[u] and age[u] >= MIN_ON]
            for u in sorted(cand, key=lambda k: -age[k]):
                if r_on - RATED[u] + give >= need:
                    on[u], age[u] = False, 0
                    break
        r_on = sum(RATED[u] for u in units if on[u])
        # even the datasheet floor makes more than the load and the battery can absorb,
        # and export is forbidden: an engine is stopped whatever the cover ("forced");
        # with export allowed the engines stay at the floor and the surplus is exported
        while not EXPORT and r_on and FLOOR * r_on > need + take:
            u = max((k for k in units if on[k]), key=lambda k: age[k])
            on[u], age[u] = False, 0
            forced[i] = 1.0
            r_on = sum(RATED[k] for k in units if on[k])
        gen = min(r_on, need + take)             # engines full, the battery takes the surplus
        gen = max(gen, FLOOR * r_on)             # never under the datasheet floor
        if r_on and gen < BAND * r_on - 1e-6:
            oob[i] = 1.0
        for u in units:
            out[u][i] = gen * RATED[u] / r_on if on[u] else 0.0
        if gen >= need:
            ch = min(gen - need, take); dis = 0.0
            exp_s[i] = gen - need - ch
        else:
            ch = 0.0; dis = min(need - gen, give)
            imp_s[i] = need - gen - dis
        soc += (ch * eta - dis / eta) * DT / e_kwh if e_kwh > 0 else 0.0
        soc_s[i], ch_s[i], dis_s[i] = soc, ch, dis
        for u in units:
            age[u] += 1
    return dict(out=out, soc=soc_s, ch=ch_s, dis=dis_s, imp=imp_s, exp=exp_s, oob=oob,
                forced=forced)


def scenario(x: pd.DataFrame, units: list[str], e_mwh: float, c_rate: float,
             start_h: float = START_H, avail=None) -> pd.Series:
    e, p = 1000.0 * e_mwh, 1000.0 * e_mwh * c_rate
    s = simulate(x, units, e, p, avail)
    y = cost(x, s["out"], s["imp"], s["exp"], start_h,
             extra={"throughput_kwh": s["dis"] * DT, "oob_h": s["oob"] * DT})
    b = base(x, units, start_h)
    y["capex_kzt"] = (e * BAT_USD_KWH + p * INV_USD_KW) * KZT_USD
    y["saving_kzt"] = b["cost_kzt"] - y["cost_kzt"]
    y["band_kzt"] = (b["kzt_per_kwh_gen"] - y["kzt_per_kwh_gen"]) * b["gen_kwh"]
    y["import_kzt"] = y["saving_kzt"] - y["band_kzt"]
    y["cycles"] = y["throughput_kwh"] / (e * (HI - LO)) if e else 0.0
    y["life_y"] = min(CYCLE_LIFE / y["cycles"], CAL_LIFE) if y["cycles"] else CAL_LIFE
    y["payback_y"] = y["capex_kzt"] / y["saving_kzt"] if y["saving_kzt"] > 0 else np.nan
    y["in_band"] = y["oob_h"] <= 0.01 * y["run_h"]
    return y


def his(group: str, e: float | None, c: float | None, seq: int = 4) -> pd.Series:
    r = pd.read_csv(os.path.join(DATA, f"runs_{RUN}_results.csv"))
    r = r[(r.group == group) & (r.seq == seq)]
    if e is None:
        return r[r.case == "BASE"].iloc[0]
    return r[(r.case == "RULES") & (r.e_mwh == e) & (abs(r.c_rate - c) < 1e-9)].iloc[0]


def pct(a, b):
    return f"{100 * (a - b) / b:+.2f} %" if b else "—"


def check_default() -> None:
    """Today and the default battery (3 MWh x 0.33 C), against his numbers and steps."""
    keys = ["cost_kzt", "fuel_kzt", "om_kzt", "grid_kzt", "run_h", "starts", "imp_kwh", "gen_kwh"]
    for g, units in UNITS.items():
        x = steps(g)
        print(f"\n== {g}: {len(x):,} steps, {int(x['new'].sum())} stretches")
        b, hb = base(x, units), his(g, None, None)
        print("  today       " + "  ".join(f"{k} {b[k]:,.0f} ({pct(b[k], hb[k])})" for k in keys))
        e, c = 3.0, 0.33
        s = simulate(x, units, 1000 * e, 1000 * e * c)
        # step by step against his decisions
        same = {u: np.mean(np.abs(s["out"][u] - x[u].values) < 1.0) for u in units}
        on_same = {u: np.mean((s["out"][u] > RUN_KW) == (x[u].values > RUN_KW)) for u in units}
        soc_err = np.abs(s["soc"] - x["soc"].values)
        print("  steps       output within 1 kW: " + ", ".join(f"{u} {v:.1%}" for u, v in same.items())
              + " · on/off same: " + ", ".join(f"{u} {v:.1%}" for u, v in on_same.items())
              + f" · charge within 1 %-point: {np.mean(soc_err < 0.01):.1%}"
              + f" · import within 1 kW: {np.mean(np.abs(s['imp'] - x['imp'].values) < 1):.1%}")
        y, hy = scenario(x, units, e, c), his(g, e, c)
        print("  3 MWh×0.33  " + "  ".join(f"{k} {y[k]:,.0f} ({pct(y[k], hy[k])})" for k in keys + ["saving_kzt"])
              + f"  cycles {y['cycles']:.0f} ({pct(y['cycles'], hy['cycles'])})"
              + f"  payback {y['payback_y']:.2f} y (his {hy['payback_y']:.2f})")


def check_sizes() -> None:
    """Every size of the default run: his payback and saving against the rebuilt ones."""
    rows = []
    for g, units in UNITS.items():
        x = steps(g)
        for e in (1.0, 2.0, 3.0, 4.0, 5.5, 7.0):
            for c in (0.25, 0.33, 0.5, 1.0):
                y, h = scenario(x, units, e, c), his(g, e, c)
                rows.append(dict(group=g, size=f"{e:g}x{c:g}", saving=y["saving_kzt"] / 1e6,
                                 his_saving=h["saving_kzt"] / 1e6, payback=y["payback_y"],
                                 his_payback=h["payback_y"], starts=y["starts"], his_starts=h["starts"]))
    t = pd.DataFrame(rows)
    t["d_saving_%"] = 100 * (t.saving - t.his_saving) / t.his_saving.abs()
    pd.set_option("display.width", 200)
    print(t.round(2).to_string(index=False))
    print(f"\nsaving within 2 % of his: {np.mean(t['d_saving_%'].abs() < 2):.0%} of {len(t)} sizes; "
          f"median |difference| {t['d_saving_%'].abs().median():.2f} %")


def split() -> None:
    """What his saving is made of, with his own machinery: the rule without a battery,
    and every case again with the engines only in the hours the meters show them running."""
    for g, units in UNITS.items():
        x = steps(g)
        b = base(x, units)
        avail = {u: x[f"{u}_measured"].fillna(0).values > RUN_KW for u in units}
        rule0 = scenario(x, units, 0.0, 0.0)
        rule0_av = scenario(x, units, 0.0, 0.0, avail=avail)
        bat = scenario(x, units, 3.0, 0.33)
        bat_av = scenario(x, units, 3.0, 0.33, avail=avail)
        m = lambda v: f"{v / 1e6:,.1f}"
        print(f"\n== {g}: today {m(b['cost_kzt'])} M KZT/yr, import {b['imp_kwh'] / 1e3:,.0f} MWh")
        print(f"  engines always available (his):  rule, no battery {m(rule0['cost_kzt'])} "
              f"(saves {m(b['cost_kzt'] - rule0['cost_kzt'])}) · rule + 3 MWh×0.33 {m(bat['cost_kzt'])} "
              f"(saves {m(bat['saving_kzt'])}; the battery's own share {m(rule0['cost_kzt'] - bat['cost_kzt'])})")
        print(f"  engines as the meters show them: rule, no battery {m(rule0_av['cost_kzt'])} "
              f"(saves {m(b['cost_kzt'] - rule0_av['cost_kzt'])}) · rule + 3 MWh×0.33 {m(bat_av['cost_kzt'])} "
              f"(saves {m(b['cost_kzt'] - bat_av['cost_kzt'])}; the battery's own share {m(rule0_av['cost_kzt'] - bat_av['cost_kzt'])})"
              f" · import with battery {bat_av['imp_kwh'] / 1e3:,.0f} MWh")
        cap = bat["capex_kzt"]
        for name, s in (("his framing", bat["saving_kzt"]),
                        ("battery alone, availability as logged", rule0_av["cost_kzt"] - bat_av["cost_kzt"])):
            print(f"  payback, {name}: {cap / s:.1f} y" if s > 0 else f"  payback, {name}: never")


def battery_alone() -> None:
    """Every size, the battery's own saving (rule + battery against the rule alone), its
    payback and life, with the engines as he has them and as the meters show them."""
    rows = []
    for g, units in UNITS.items():
        x = steps(g)
        avail = {u: x[f"{u}_measured"].fillna(0).values > RUN_KW for u in units}
        for mode, av in (("always", None), ("as logged", avail)):
            r0 = scenario(x, units, 0.0, 0.0, avail=av)
            for e in (1.0, 2.0, 3.0, 4.0, 5.5, 7.0):
                for c in (0.25, 0.33, 0.5, 1.0):
                    y = scenario(x, units, e, c, avail=av)
                    own = r0["cost_kzt"] - y["cost_kzt"]
                    pb = y["capex_kzt"] / own if own > 0 else np.inf
                    rows.append(dict(group=g, engines=mode, size=f"{e:g}x{c:g}", own_M=own / 1e6,
                                     payback_y=pb, life_y=y["life_y"], in_band=bool(y["in_band"]),
                                     pays_before_wearout=bool(pb <= y["life_y"] and y["in_band"])))
    t = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    for (g, mode), s in t.groupby(["group", "engines"], sort=False):
        ok = s[s.pays_before_wearout]
        best = s[s.in_band].sort_values("payback_y").head(3)
        print(f"{g:>2} · engines {mode:9}: battery's own saving {s.own_M.min():6.1f} … {s.own_M.max():6.1f} M/yr · "
              f"in-band sizes paying back before wear-out: {len(ok)} of {int(s.in_band.sum())} · shortest: "
              + "; ".join(f"{r.size} {r.payback_y:.1f} y (life {r.life_y:.1f})" for r in best.itertuples()))


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "default"
    {"default": check_default, "sizes": check_sizes, "split": split,
     "alone": battery_alone}[what]()
