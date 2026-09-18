"""CHP + BESS microgrid from CHP_BESS_model_v2.xlsx, posed in this engine.

Every input is read off the workbook's «Допущения» sheet:

  units        Jenbacher 1067 kW, TEDOM 1200 kW, КГУ-3 1100 kW
  min load     90% rule in B and C, 50% technical minimum in A
  min up/down  4 h / 5 h
  CHP cost     22 tenge/kWh, all-in, charged on rated output (spill included)
  start        15,000 tenge per start
  grid         60 tenge/kWh, unlimited, no export, no demand charge
  BESS         5,500 kWh, 2,500 kW inverter, SoC window 30-100%, RTE 0.88
  wear         0.5 tenge per kWh discharged
  CAPEX        391,000,000 tenge

Scenarios, as the workbook defines them, plus one it does not have:

  A  free modulation from 50%, no BESS        their baseline "as is"
  B  90% rule, no BESS
  C  90% rule + BESS
  D  free modulation from 50% + BESS          ours: the battery with no 90% artifact

Their numbers come from a causal rule-based controller. This engine is a MILP
with perfect foresight over the horizon, so for identical constraints each of our
scenario costs is a lower bound on theirs; the difference is what their
controller leaves on the table.

    python tools/chp_bess_suite.py week      exact 168-h week from the workbook
    python tools/chp_bess_suite.py annual    8,760-h year, see make_year()
    python tools/chp_bess_suite.py cliff     the decision-surface cliff at 30,000 tenge
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from reopt_core import model as M
from reopt_core.tariff import flat_tariff

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "chp_bess_analysis")

UNITS = {
    "chp2": [("Jenbacher", 1067.0), ("TEDOM", 1200.0)],
    "chp3": [("Jenbacher", 1067.0), ("TEDOM", 1200.0), ("КГУ-3", 1100.0)],
}
CHP_COST = 22.0
GRID = 60.0
START = 15_000.0
WEAR = 0.5
MIN_UP, MIN_DOWN = 4, 5
BESS_KWH, BESS_KW = 5_500.0, 2_500.0
SOC_MIN = 0.30
RTE = 0.88
ETA = math.sqrt(RTE)
CAPEX = 391_000_000.0

MODES = {
    "A": dict(turndown=0.5, bess=False, name="Свободный 50%"),
    "B": dict(turndown=0.9, bess=False, name="Правило 90%"),
    "C": dict(turndown=0.9, bess=True, name="90% + BESS"),
    "D": dict(turndown=0.5, bess=True, name="Свободный 50% + BESS"),
}


# ------------------------------------------------------------------ scenario
def scenario(load, fleet_key, mode, *, grid=GRID, start=START):
    md = MODES[mode]
    fleet = [M.FuelTechInputs(
        enabled=True, kind="CHP", label="CHP", name=name,
        installed_cost_per_kw=0.0, om_cost_per_kw=0.0, om_cost_per_kwh=CHP_COST,
        fuel_cost_per_mmbtu=0.0, electric_efficiency_full_load=0.35,
        thermal_efficiency_full_load=0.0,
        min_kw=p, max_kw=p, min_turn_down_fraction=md["turndown"],
        start_cost=start, min_up_hours=MIN_UP, min_down_hours=MIN_DOWN,
        can_curtail=True,
        macrs_option_years=0, macrs_bonus_fraction=0.0, federal_itc_fraction=0.0,
    ) for name, p in UNITS[fleet_key]]
    on = md["bess"]
    bat = M.StorageInputs(
        enabled=on, name="BESS",
        installed_cost_per_kw=0.0, installed_cost_per_kwh=0.0, installed_cost_constant=0.0,
        om_cost_fraction_of_installed_cost=0.0,
        min_kw=BESS_KW if on else 0.0, max_kw=BESS_KW,
        min_kwh=BESS_KWH if on else 0.0, max_kwh=BESS_KWH,
        charge_efficiency=ETA, discharge_efficiency=ETA, grid_charge_efficiency=ETA,
        can_grid_charge=False,            # workbook invariant: grid charging 0 hours
        soc_min_fraction=SOC_MIN,
        macrs_option_years=0, macrs_bonus_fraction=0.0, total_itc_fraction=0.0,
        discharge_cost_per_kwh=WEAR,
        # the workbook closes the SoC cycle over its horizon -- REopt's
        # optimize_soc_init_fraction option (electric_storage.jl:209)
        optimize_soc_init_fraction=True,
    )
    fin = M.FinancialInputs(
        analysis_years=1, elec_cost_escalation_rate_fraction=0.0,
        om_cost_escalation_rate_fraction=0.0, offtaker_discount_rate_fraction=0.0,
        offtaker_tax_rate_fraction=0.0, fuel_cost_escalation_rate_fraction=0.0,
    )
    return M.ScenarioInputs(
        loads_kw=list(map(float, load)), tariff=flat_tariff(grid), financial=fin,
        pv=M.PVInputs(enabled=False), storage=bat,
        fuel_tech=fleet[0], fuel_techs=fleet,
        compensation_type="no_compensation",
    )


def account(res, load, *, grid=GRID, start=START):
    """Cost with the workbook's own formula, rebuilt from the solution."""
    ser, sz = res["series"], res["sizes"]
    units = sz["fueltech_units"]
    rated = sum(u["energy_kwh"] for u in units)
    spill = sum(u["spill_kwh"] for u in units)
    g = sum(ser["grid_kw"])
    dis = sum(ser["battery_discharge_kw"])
    ch = sum(ser["battery_charge_kw"])
    starts = sum(u["starts"] or 0 for u in units)
    hours = sum(u["running_hours"] for u in units)
    cost = rated * CHP_COST + g * grid + starts * start + dis * WEAR
    # invariants the workbook checks on every run
    n = len(load)
    bal = max(abs(load[t] + ser["battery_charge_kw"][t]
                  - (ser["fueltech_kw"][t] + ser["battery_discharge_kw"][t] + ser["grid_kw"][t]))
              for t in range(n))
    both = sum(1 for t in range(n)
               if ser["battery_charge_kw"][t] > 1e-3 and ser["battery_discharge_kw"][t] > 1e-3)
    si = res.get("solver") or {}
    return dict(
        cost=cost, objective=res["objective_lifecycle_cost"], status=res["status"],
        model_status=si.get("model_status"), mip_gap=si.get("mip_gap"),
        dual_bound=si.get("mip_dual_bound"),
        chp_kwh=rated, spill_kwh=spill, grid_kwh=g, charge_kwh=ch, discharge_kwh=dis,
        starts=starts, unit_hours=hours, balance_residual_kw=bal, simultaneous_hours=both,
        grid_peak_kw=max(ser["grid_kw"]),
        units=[dict(name=u["name"], kwh=u["energy_kwh"], hours=u["running_hours"],
                    starts=u["starts"], spill=u["spill_kwh"]) for u in units],
    )


def solve(load, fleet_key, mode, *, grid=GRID, start=START, gap=None, limit=1800):
    t0 = time.time()
    res = M.solve(scenario(load, fleet_key, mode, grid=grid, start=start),
                  time_limit=limit, mip_gap=gap)
    acc = account(res, load, grid=grid, start=start)
    acc["seconds"] = time.time() - t0
    return acc, res


# ---------------------------------------------------------- workbook inputs
def jsx_data():
    src = io.open(os.path.join(ROOT, "bess_profile_v2.jsx"), encoding="utf-8").read()
    def grab(name):
        return json.loads(re.search(r"const " + name + r" = (\{.*?\});\n", src, flags=re.S).group(1))
    return grab("DATA"), grab("SUMMARY")


def their_week_cost(rows, soc0):
    raw = sum(r[1] * CHP_COST + r[5] * GRID + r[6] * START + r[3] * WEAR for r in rows)
    # The week is a slice of their year, not a closed period. Price the SoC drift
    # the way the artifact does (bess_profile_v2.jsx: dSoc * eta * grid tariff).
    d_kwh = (rows[-1][4] - soc0) / 100.0 * BESS_KWH
    return raw - d_kwh * ETA * GRID, raw, d_kwh


# ------------------------------------------------------------ annual profile
def make_year(seed=20260824):
    """PROJECT_FULL.md A.7 make_year(), archetype 1 "Две смены", re-targeted to the
    v2 envelope (mean 2,300 kW, peak 5,500 kW). Yields exactly 20,148 MWh, the
    workbook's annual load. The v2 generator itself (energo_handover) is not in the
    workspace, so the noise draw differs from theirs: same envelope, not the same year.
    """
    a = dict(base=2.30, day_amp=1.30, night=0.62, weekend=0.90, season=0.10,
             noise=0.06, spike_p=0.010, spike=2.10, shifts=2,
             target_mean=2.3, target_peak=5.5)
    rng = np.random.default_rng(seed)
    hours = np.arange(8760); hod = hours % 24; dow = (hours // 24 + 3) % 7; doy = hours // 24
    shape = np.where((hod >= 6) & (hod < 22), 1.0, 0.0)
    shape = np.where((hod >= 13) & (hod < 15), 0.45, shape)
    smooth = np.convolve(np.r_[shape[-3:], shape, shape[:3]], np.ones(5) / 5, mode="same")[3:-3]
    x = a["base"] * (a["night"] + (a["day_amp"] - a["night"]) * smooth)
    x = x * np.where(dow >= 5, a["weekend"], 1.0)
    x = x * (1.0 + a["season"] * np.cos(2 * np.pi * doy / 365.0))
    x = x * (1.0 + rng.normal(0, a["noise"], 8760))
    hit = rng.random(8760) < a["spike_p"]
    x = np.where(hit, x * rng.uniform(1.0, a["spike"] / a["day_amp"] + 0.6, 8760), x)
    x = np.clip(x, 0.25, None) * 1000.0
    for _ in range(2):
        x = x * (a["target_mean"] * 1000.0 / x.mean())
        x = np.minimum(x, a["target_peak"] * 1000.0)
    return np.round(x, 1)


def month_slices():
    days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    out, h = [], 0
    for d in days:
        out.append((h, h + d * 24))
        h += d * 24
    return out


def solve_year(load, fleet_key, mode, *, grid=GRID, start=START, gap=0.005, limit=300,
               verbose=True):
    """Twelve closed monthly MILPs. The battery cycles within a day, so closing SoC
    at month end costs nothing material; a unit state at a month boundary can add or
    save at most one start per unit per month.

    Costs are incumbents, so each is an UPPER bound on the true optimum; the summed
    dual bound is the matching lower bound. Savings computed from incumbents are
    therefore conservative for the battery."""
    tot = None
    for i, (a, b) in enumerate(month_slices()):
        acc, _ = solve(load[a:b], fleet_key, mode, grid=grid, start=start, gap=gap, limit=limit)
        acc["dual_bound"] = acc["dual_bound"] if acc["dual_bound"] is not None else acc["cost"]
        if verbose:
            print(f"      m{i+1:>2} {acc['cost']:>12,.0f} ₸  gap {acc['mip_gap']:>6.3%}  "
                  f"{acc['seconds']:>5.0f}s  {acc['model_status']}", flush=True)
        if tot is None:
            tot = {k: v for k, v in acc.items() if k != "units"}
            tot["status"] = [acc["status"]]
            tot["month_gaps"] = [acc["mip_gap"]]
        else:
            for k in ("cost", "objective", "chp_kwh", "spill_kwh", "grid_kwh", "charge_kwh",
                      "discharge_kwh", "starts", "unit_hours", "simultaneous_hours", "seconds",
                      "dual_bound"):
                tot[k] += acc[k]
            tot["balance_residual_kw"] = max(tot["balance_residual_kw"], acc["balance_residual_kw"])
            tot["grid_peak_kw"] = max(tot["grid_peak_kw"], acc["grid_peak_kw"])
            tot["status"].append(acc["status"])
            tot["month_gaps"].append(acc["mip_gap"])
    tot["mip_gap"] = (tot["cost"] - tot["dual_bound"]) / tot["cost"]
    return tot


def payback(save):
    return CAPEX / save if save > 0 else None


def fmt_pb(x):
    return "не окупается" if x is None else f"{x:.1f} лет"


# -------------------------------------------------------------------- tracks
def track_week():
    DATA, _ = jsx_data()
    out = {}
    print("Track 1 -- the exact 168-hour week (01.06.2026) from the workbook\n")
    for fk in ("chp2", "chp3"):
        wk = DATA[fk]["week"]
        load = [r[0] for r in wk["A"]["rows"]]
        print(f"=== {fk}: {' + '.join(f'{n} {int(p)}' for n, p in UNITS[fk])} kW ===")
        print(f"{'':3}{'их контроллер, ₸':>18} {'наш MILP, ₸':>14} {'разница':>9}"
              f"  {'пуски их/наш':>13} {'сеть МВт·ч их/наш':>18} {'сброс их/наш':>13}  {'s':>5}")
        out[fk] = {}
        for mode in "ABCD":
            acc, _ = solve(load, fk, mode, limit=600)
            row = dict(ours=acc)
            if mode in wk:
                rows = wk[mode]["rows"]
                theirs, raw, dsoc = their_week_cost(rows, wk[mode]["soc0"])
                t_starts = sum(r[6] for r in rows)
                t_grid = sum(r[5] for r in rows) / 1000
                t_spill = sum(r[8] for r in rows)
                row.update(theirs=theirs, theirs_raw=raw, theirs_dsoc_kwh=dsoc,
                           theirs_starts=t_starts, theirs_grid_mwh=t_grid, theirs_spill=t_spill)
                gap = (acc["cost"] - theirs) / theirs
                print(f"{mode:<3}{theirs:>18,.0f} {acc['cost']:>14,.0f} {gap:>+9.2%}"
                      f"  {t_starts:>6.0f}/{acc['starts']:<6} {t_grid:>8.1f}/{acc['grid_kwh']/1000:<9.1f}"
                      f" {t_spill:>6.0f}/{acc['spill_kwh']:<6.0f} {acc['seconds']:>5.1f}")
            else:
                print(f"{mode:<3}{'—':>18} {acc['cost']:>14,.0f} {'':>9}"
                      f"  {'—':>6}/{acc['starts']:<6} {'—':>8}/{acc['grid_kwh']/1000:<9.1f}"
                      f" {'—':>6}/{acc['spill_kwh']:<6.0f} {acc['seconds']:>5.1f}")
            if abs(acc["cost"] - acc["objective"]) > 1.0:
                print(f"   !! objective {acc['objective']:,.0f} != rebuilt cost {acc['cost']:,.0f}")
            if acc["balance_residual_kw"] > 1e-3 or acc["simultaneous_hours"]:
                print(f"   !! balance {acc['balance_residual_kw']:.4f} kW, "
                      f"simultaneous charge+discharge {acc['simultaneous_hours']} h")
            out[fk][mode] = row
        ours = {m: out[fk][m]["ours"]["cost"] for m in "ABCD"}
        th = {m: out[fk][m]["theirs"] for m in "ABC"}
        print(f"   экономия недели   B-C: их {th['B']-th['C']:>11,.0f}   наш {ours['B']-ours['C']:>11,.0f}"
              f"   |  A-C: их {th['A']-th['C']:>11,.0f}   наш {ours['A']-ours['C']:>11,.0f}"
              f"   |  A-D (наш): {ours['A']-ours['D']:>11,.0f}\n")
    os.makedirs(OUT, exist_ok=True)
    io.open(os.path.join(OUT, "week_results.json"), "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, indent=1, default=float))


def track_annual(fleets=("chp2", "chp3"), modes="ABCD", grid=GRID, start=START, tag="base"):
    _, SUMMARY = jsx_data()
    load = make_year()
    print(f"Track 2 -- 8,760 h year, {load.sum()/1000:,.0f} MWh, mean {load.mean():,.0f} kW, "
          f"peak {load.max():,.0f} kW  |  grid {grid} ₸/kWh, start {start:,.0f} ₸\n")
    out = {}
    for fk in fleets:
        out[fk] = {}
        print(f"=== {fk} ===")
        for mode in modes:
            print(f"  -- {mode} {MODES[mode]['name']}", flush=True)
            r = solve_year(load, fk, mode, grid=grid, start=start)
            out[fk][mode] = r
            print(f"  {mode} {MODES[mode]['name']:<22} {r['cost']:>14,.0f} ₸  "
                  f"(нижняя граница {r['dual_bound']:>14,.0f}, зазор {r['mip_gap']:.3%})   "
                  f"КГУ {r['chp_kwh']/1000:>7,.0f} МВт·ч  сеть {r['grid_kwh']/1000:>6,.0f}  "
                  f"сброс {r['spill_kwh']/1000:>4,.0f}  пусков {r['starts']:>4}  "
                  f"моточасы {r['unit_hours']:>6,}  {r['seconds']:>6.0f} s", flush=True)
        c = {m: out[fk][m]["cost"] for m in modes}
        if set("ABC") <= set(modes):
            s = SUMMARY[fk] if tag == "base" else None
            print(f"  --- окупаемость BESS, CAPEX {CAPEX/1e6:,.0f} млн ₸")
            db = {m: out[fk][m]["dual_bound"] for m in modes}
            for lbl, base, alt, key in (("к B (эффект батареи при правиле 90%)", "B", "C", "payB"),
                                        ("к A (что получит завод, их постановка)", "A", "C", "payA"),
                                        ("A -> D (чистая батарея, без правила 90%)", "A", "D", None)):
                if alt not in modes or base not in modes:
                    continue
                sv = c[base] - c[alt]           # both incumbents: conservative
                sv_hi = c[base] - db[alt]       # alt at its lower bound: optimistic
                theirs = "   | у них нет" if key is None else (
                    "" if s is None else f"   | у них {fmt_pb(s[key])}")
                print(f"      {lbl:<44} экономия {sv:>13,.0f} ₸/год -> {fmt_pb(payback(sv))}"
                      f"  (граница {fmt_pb(payback(sv_hi))}){theirs}")
            print(f"      артефакт правила 90% (B - A): {c['B']-c['A']:,.0f} ₸/год"
                  + ("" if s is None else f"   | у них {s['artifact']:,}"))
        print()
    os.makedirs(OUT, exist_ok=True)
    io.open(os.path.join(OUT, f"annual_{tag}_{'_'.join(fleets)}.json"), "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, indent=1, default=float))
    return out


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "week"
    if what == "week":
        track_week()
    elif what == "annual":
        fl = tuple(sys.argv[2:]) or ("chp2", "chp3")
        track_annual(fleets=fl)
    elif what == "cliff":
        # workbook «Поверхность решения»: min_load 0.9, start 30,000, tariff 46.25 -> "не окупается"
        track_annual(fleets=("chp2",), modes="ABC", grid=46.25, start=30_000.0, tag="cliff")
    elif what == "month":
        load = make_year()
        a, b = month_slices()[5]
        for fk in ("chp2", "chp3"):
            for mode in "ABCD":
                acc, _ = solve(load[a:b], fk, mode, gap=0.001, limit=900)
                print(f"{fk} {mode}: {acc['cost']:,.0f} ₸  {acc['seconds']:.1f} s  {acc['status']}  "
                      f"starts {acc['starts']}  balance {acc['balance_residual_kw']:.4f}")
