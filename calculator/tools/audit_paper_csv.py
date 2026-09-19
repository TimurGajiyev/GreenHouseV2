"""Audit a day-long CSV that claims to be digitised from Sigalo et al. 2023.

  "Real-Time Economic Dispatch of CHP Systems with Battery Energy Storage for
   Behind-the-Meter Applications", Energies 16(1274), 2023.

Three questions, kept apart:

  provenance  do the CSV's inputs match the ones the paper publishes (tariff,
              thermal load, time step, SoC window, efficiencies)?
  physics     does the CSV's own schedule obey the equipment limits it claims
              to obey -- balance, no export, engine limits, SoC window, and the
              battery efficiencies of Table 4?
  economics   priced with the paper's own fuel curve, is the CSV's "optimised"
              column actually the cheapest schedule for its own load and
              prices? Re-solved here with this calculator's MILP.

    python tools/audit_paper_csv.py [--csv PATH] [--no-solve]
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import model as M
from reopt_core.tariff import flat_tariff

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV = os.path.join(ROOT, "chp_bess_analysis", "sigalo_day.csv")
OUT = os.path.join(ROOT, "chp_bess_analysis", "sigalo_day_audit.json")

# ---- the paper's own numbers ------------------------------------------------
KWH_PER_MMBTU = 293.07107
GAS_PER_KWH = 0.0198                      # Table 5
A, B, C = 7.045e-5, 0.0297, 2.0654        # Table 3, cost/h with P in kW
UNIT_KW, N_UNITS = 250.0, 2               # Section 2
MIN_LOAD_FRAC = 0.50                      # Sections 1 and 3
Q_HRR = 1.332                             # Table 2: 333/250 = 249.75/187.5 = 166.5/125
EFF_FULL, EFF_HALF = 0.355, 0.343         # Table 2
TH_EFF_FULL = 0.473                       # Table 2
BESS_KWH, BESS_KW = 1000.0, 250.0         # Table 4
SOC_MIN, SOC_MAX = 0.30, 1.00             # Table 4
ETA_C, ETA_D = 0.90, 0.90                 # Table 4
TARIFF_OFF, TARIFF_PEAK = 0.106, 0.140    # Table 5
PAPER_STEPS, PAPER_DT = 48, 0.5           # Section 5
PAPER_HEAT_FLAT = 483.0                   # Figure 7, real heat demand
BOILER_EFF = 0.90                         # NOT in the paper: it has no boiler

NOTES: list[str] = []
FAIL: list[str] = []


def ok(flag: bool, text: str, detail: str = "") -> bool:
    print(f"  {'OK' if flag else 'XX'}  {text:<58}{detail}")
    if not flag:
        FAIL.append(text)
    return flag


def note(text: str) -> None:
    NOTES.append(text)
    print(f"  --  {text}")


def load(path: str) -> list[dict]:
    with io.open(path, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k, v in list(r.items()):
            if k != "Timestamp":
                r[k] = float(v)
    return rows


# ---- the paper's fuel cost, Eq (4) with Table 3 ------------------------------
def f_unit(p: float) -> float:
    """Cost of one engine at output p (currency per hour)."""
    return A * p * p + B * p + C


def chp_cost(p_total: float) -> float:
    """Cheapest way to make p_total on 2 identical convex units, per hour."""
    if p_total <= 1e-9:
        return 0.0
    if p_total <= UNIT_KW + 1e-9:
        return f_unit(p_total)                       # one engine
    return 2.0 * f_unit(p_total / 2.0)               # two, equally loaded


def fuel_kw(p_total: float) -> float:
    """Fuel input, from the same split (Table 2 efficiencies are per unit)."""
    if p_total <= 1e-9:
        return 0.0
    n = 1 if p_total <= UNIT_KW + 1e-9 else 2
    p = p_total / n
    # affine through the 50% and 100% points of Table 2
    slope = (UNIT_KW / EFF_FULL - 0.5 * UNIT_KW / EFF_HALF) / (0.5 * UNIT_KW)
    icept = UNIT_KW / EFF_FULL - slope * UNIT_KW
    return n * (slope * p + icept)


# ============================================================ 1. provenance
def provenance(rows: list[dict]) -> None:
    print("\n1. PROVENANCE — does the CSV carry the paper's inputs?")
    n = len(rows)
    ok(n == PAPER_STEPS, "time resolution: 48 half-hour steps (Section 5)",
       f"CSV has {n} rows of 1 h")
    price = [r["Grid_Price_USD_per_kWh"] for r in rows]
    two_band = set(round(p, 3) for p in price) <= {TARIFF_OFF, TARIFF_PEAK}
    ok(two_band, "tariff: two bands 0.106 / 0.140 (Table 5)",
       f"CSV runs {min(price):.3f}-{max(price):.3f} over {len(set(price))} distinct values")
    heat = [r["Thermal_Load_kW"] for r in rows]
    flat = max(heat) - min(heat) < 60
    ok(flat, "heat load: flat at ~483 kW_th (Figure 7)",
       f"CSV varies {min(heat):.0f}-{max(heat):.0f} kW_th, anti-correlated with the electric load")
    el = [r["Electric_Load_kW"] for r in rows]
    note(f"electric load: CSV {min(el):.0f}-{max(el):.0f} kW vs the paper's figure ~0-690 kW "
         f"(same order, different shape)")
    note("date 2024-10-15: the paper gives no dates; its data 'belongs to a private company'")
    note("currency: CSV says USD, the paper prices in GBP")


# ============================================================ 2. physics
def physics(rows: list[dict]) -> dict:
    print("\n2. PHYSICS — does the CSV's own schedule obey its equipment?")
    n = len(rows)
    dt = 1.0
    bal_opt = max(abs(r["Optimized_CHP_Gen_kW"] + max(r["Battery_Power_kW"], 0.0)
                      + r["Optimized_Grid_Import_kW"] - min(r["Battery_Power_kW"], 0.0) * -1
                      - r["Electric_Load_kW"]) for r in rows)
    ok(bal_opt < 1e-6, "electrical balance holds every hour (Eq 1)", f"worst {bal_opt:.3g} kW")

    # baseline column: generation above load with no battery and no import = export
    exp_base = [r["Baseline_CHP_Gen_kW"] + r["Baseline_Grid_Import_kW"] - r["Electric_Load_kW"]
                for r in rows]
    worst_exp = max(exp_base)
    ok(worst_exp <= 1e-6, "baseline column respects the no-export rule (Eq 13)",
       f"baseline over-generates up to {worst_exp:.0f} kW in {sum(1 for e in exp_base if e > 1e-6)} hours")

    chp = [r["Optimized_CHP_Gen_kW"] for r in rows]
    ok(max(chp) <= N_UNITS * UNIT_KW + 1e-6, "CHP within 2 x 250 kW", f"max {max(chp):.0f} kW")
    lo = [p for p in chp if 0 < p < UNIT_KW * MIN_LOAD_FRAC - 1e-6]
    ok(not lo, "CHP never runs below the 50% minimum stable load", f"{len(lo)} hours below 125 kW")

    bp = [r["Battery_Power_kW"] for r in rows]
    ok(max(abs(x) for x in bp) <= BESS_KW + 1e-6, "battery within +/-250 kW",
       f"max {max(abs(x) for x in bp):.0f} kW")

    soc = [r["Battery_SOC_kWh"] for r in rows]
    # implied efficiency: the CSV's own SoC trace against its own power
    eff_c, eff_d = [], []
    for i in range(1, n):
        d = soc[i] - soc[i - 1]
        p = bp[i]
        if p < -1e-6 and d > 0:
            eff_c.append(d / (-p * dt))
        elif p > 1e-6 and d < 0:
            eff_d.append((-d) / (p * dt))
    ok(abs(sum(eff_c) / max(1, len(eff_c)) - ETA_C) < 0.02,
       "charge efficiency 90% (Table 4)",
       f"CSV implies {100 * sum(eff_c) / max(1, len(eff_c)):.0f}%")
    ok(abs(sum(eff_d) / max(1, len(eff_d)) - ETA_D) < 0.02,
       "discharge efficiency 90% (Table 4)",
       f"CSV implies {100 * sum(eff_d) / max(1, len(eff_d)):.0f}%")

    floor, ceil = SOC_MIN * BESS_KWH, SOC_MAX * BESS_KWH
    below = [s for s in soc if s < floor - 1e-6]
    ok(not below, f"SoC inside the 30-100% window ({floor:.0f}-{ceil:.0f} kWh)",
       f"{len(below)} of {n} hours below the floor, lowest {min(soc):.0f} kWh = {100 * min(soc) / BESS_KWH:.0f}%")
    # charitable reading: the column may be usable energy above the 30% floor
    usable = ceil - floor
    if not below or True:
        fits = min(soc) >= -1e-6 and max(soc) <= usable + 1e-6
        note(f"read as energy ABOVE the 30% floor the column {'fits' if fits else 'still does not fit'} "
             f"the 0-{usable:.0f} kWh usable band ({min(soc):.0f}-{max(soc):.0f} kWh) — "
             f"that reading rescues the SoC window but not the efficiencies")

    # re-run the CSV's own battery commands at the paper's efficiencies
    start = soc[0] - (-bp[0]) * dt if bp[0] < 0 else soc[0] + bp[0] * dt
    e, trace = start, []
    for p in bp:
        e += (-p * dt * ETA_C) if p < 0 else (-p * dt / ETA_D)
        trace.append(e)
    note(f"with Table 4 efficiencies the same commands end the day at {trace[-1]:.0f} kWh "
         f"instead of {soc[-1]:.0f} kWh (lossless), and run from {min(trace):.0f} kWh")

    heat_chp = [Q_HRR * p for p in chp]
    deficit = [max(0.0, r["Thermal_Load_kW"] - h) for r, h in zip(rows, heat_chp)]
    surplus = [max(0.0, h - r["Thermal_Load_kW"]) for r, h in zip(rows, heat_chp)]
    ok(max(deficit) < 1e-6, "CHP heat covers the heat load every hour (Eq 2, no boiler)",
       f"short by up to {max(deficit):.0f} kW_th, {sum(deficit):.0f} kWh_th over {sum(1 for d in deficit if d > 1e-6)} hours")
    # the tank can cover a deficit if it was charged first: track its net balance
    run, traj = 0.0, []
    for h, r in zip(heat_chp, rows):
        run += h - r["Thermal_Load_kW"]
        traj.append(run)
    need0 = max(0.0, -min(traj))
    note(f"tank: to cover those hours the buffer must start the day holding {need0:,.0f} kWh_th and "
         f"hold at least {max(traj) - min(traj):,.0f} kWh_th — the paper states no tank capacity, so "
         f"this is neither confirmed nor refuted")
    note(f"heat surplus to the tank {sum(surplus):,.0f} kWh_th — the paper's tank has no stated "
         f"capacity, so nothing bounds it")
    return {"deficit_kwh_th": sum(deficit), "surplus_kwh_th": sum(surplus),
            "soc_paper_eff_min": min(trace), "soc_paper_eff_end": trace[-1]}


# ============================================================ 3. economics
def price_schedule(rows: list[dict], chp_key: str, grid_key: str, heat_deficit: bool) -> dict:
    """Price any schedule with the paper's own fuel curve."""
    fuel = sum(chp_cost(r[chp_key]) for r in rows)                     # 1 h steps
    grid = sum(r[grid_key] * r["Grid_Price_USD_per_kWh"] for r in rows)
    boiler = 0.0
    if heat_deficit:
        boiler = sum(max(0.0, r["Thermal_Load_kW"] - Q_HRR * r[chp_key]) / BOILER_EFF * GAS_PER_KWH
                     for r in rows)
    return {"chp_fuel": fuel, "grid": grid, "boiler": boiler, "total": fuel + grid + boiler}


def solve_day(rows: list[dict], *, with_heat: bool, time_limit: int = 600) -> dict:
    """The same day posed to this calculator's MILP."""
    load = [r["Electric_Load_kW"] for r in rows]
    price = [r["Grid_Price_USD_per_kWh"] for r in rows]
    tar = flat_tariff(0.0)
    tar.energy_cost_per_kwh = list(price) + [0.0] * (8760 - len(price))
    fleet = [M.FuelTechInputs(
        enabled=True, kind="CHP", label="CHP", name=f"CHP{i + 1}",
        installed_cost_per_kw=0.0, om_cost_per_kw=0.0, om_cost_per_kwh=0.0,
        fuel_cost_per_mmbtu=GAS_PER_KWH * KWH_PER_MMBTU,
        electric_efficiency_full_load=EFF_FULL, electric_efficiency_half_load=EFF_HALF,
        thermal_efficiency_full_load=TH_EFF_FULL,
        min_kw=UNIT_KW, max_kw=UNIT_KW, min_turn_down_fraction=MIN_LOAD_FRAC,
        can_curtail=False, macrs_option_years=0, macrs_bonus_fraction=0.0,
        federal_itc_fraction=0.0) for i in range(N_UNITS)]
    storage = M.StorageInputs(
        enabled=True, name="BESS",
        installed_cost_per_kw=0.0, installed_cost_per_kwh=0.0, installed_cost_constant=0.0,
        om_cost_fraction_of_installed_cost=0.0,
        min_kw=BESS_KW, max_kw=BESS_KW, min_kwh=BESS_KWH, max_kwh=BESS_KWH,
        charge_efficiency=ETA_C, discharge_efficiency=ETA_D, grid_charge_efficiency=ETA_C,
        can_grid_charge=True, soc_min_fraction=SOC_MIN, soc_init_fraction=SOC_MIN,
        macrs_option_years=0, macrs_bonus_fraction=0.0, total_itc_fraction=0.0)
    fin = M.FinancialInputs(
        analysis_years=1, elec_cost_escalation_rate_fraction=0.0,
        om_cost_escalation_rate_fraction=0.0, offtaker_discount_rate_fraction=0.0,
        offtaker_tax_rate_fraction=0.0, fuel_cost_escalation_rate_fraction=0.0)
    kw = dict(loads_kw=load, tariff=tar, financial=fin, pv=M.PVInputs(enabled=False),
              storage=storage, fuel_tech=fleet[0], fuel_techs=fleet,
              compensation_type="no_compensation")
    if with_heat:
        kw.update(heating_loads_kw=[r["Thermal_Load_kW"] for r in rows],
                  boiler_efficiency=BOILER_EFF,
                  existing_boiler_fuel_cost_per_mmbtu=GAS_PER_KWH * KWH_PER_MMBTU,
                  boiler_fuel_escalation=0.0)
    res = M.solve(M.ScenarioInputs(**kw), time_limit=time_limit, mip_gap=1e-4)
    ser = res["series"]
    chp = [sum(v[t] for v in ser["fueltech_unit_kw"].values()) for t in range(len(load))]
    out = {"status": res["status"], "objective": res["objective_lifecycle_cost"],
           "chp_kw": chp, "grid_kw": list(ser["grid_kw"]),
           "charge_kw": list(ser["battery_charge_kw"]),
           "discharge_kw": list(ser["battery_discharge_kw"]),
           "soc_kwh": list(ser["soc_kwh"]),
           "chp_kwh": sum(chp), "grid_kwh": sum(ser["grid_kw"]),
           "starts": sum(u.get("starts") or 0 for u in res["sizes"]["fueltech_units"])}
    # price it with the paper's curve, exactly as the CSV schedule was priced
    rows_o = [{"Optimized_CHP_Gen_kW": chp[t], "Optimized_Grid_Import_kW": ser["grid_kw"][t],
               "Grid_Price_USD_per_kWh": price[t], "Thermal_Load_kW": rows[t]["Thermal_Load_kW"]}
              for t in range(len(load))]
    out["priced"] = price_schedule(rows_o, "Optimized_CHP_Gen_kW", "Optimized_Grid_Import_kW",
                                   heat_deficit=with_heat)
    return out


def main() -> None:
    path = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--csv=")), CSV)
    rows = load(path)
    print(f"Audit of {os.path.relpath(path, ROOT)} against Sigalo et al. 2023")
    provenance(rows)
    phys = physics(rows)

    print("\n3. ECONOMICS — priced with the paper's own fuel curve (Table 3)")
    csv_opt = price_schedule(rows, "Optimized_CHP_Gen_kW", "Optimized_Grid_Import_kW", True)
    csv_base = price_schedule(rows, "Baseline_CHP_Gen_kW", "Baseline_Grid_Import_kW", True)
    print(f"  CSV 'optimised' : CHP fuel {csv_opt['chp_fuel']:>9,.2f}  grid {csv_opt['grid']:>8,.2f}"
          f"  boiler {csv_opt['boiler']:>8,.2f}  total {csv_opt['total']:>9,.2f}")
    print(f"  CSV  baseline   : CHP fuel {csv_base['chp_fuel']:>9,.2f}  grid {csv_base['grid']:>8,.2f}"
          f"  boiler {csv_base['boiler']:>8,.2f}  total {csv_base['total']:>9,.2f}")

    out = {"provenance_notes": NOTES, "failures": FAIL, "physics": phys,
           "csv_optimized": csv_opt, "csv_baseline": csv_base}
    if "--no-solve" not in sys.argv:
        for tag, heat in (("electric only", False), ("with heat + 90% boiler", True)):
            print(f"\n  re-solved by this calculator ({tag}) ...")
            r = solve_day(rows, with_heat=heat)
            p = r["priced"]
            print(f"  {r['status']}: CHP {r['chp_kwh']:,.0f} kWh, grid {r['grid_kwh']:,.0f} kWh, "
                  f"starts {r['starts']}")
            print(f"  ours            : CHP fuel {p['chp_fuel']:>9,.2f}  grid {p['grid']:>8,.2f}"
                  f"  boiler {p['boiler']:>8,.2f}  total {p['total']:>9,.2f}")
            ref = csv_opt["total"] if heat else csv_opt["chp_fuel"] + csv_opt["grid"]
            print(f"  vs the CSV's 'optimised' schedule: {p['total'] - ref:+,.2f} "
                  f"({(p['total'] - ref) / ref:+.2%})")
            out[f"ours_{'heat' if heat else 'elec'}"] = r

    with io.open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, default=float)
    print(f"\nsaved -> {os.path.relpath(OUT, ROOT)}")
    print(f"\n{len(FAIL)} of the CSV's own claims fail" if FAIL else "\nall claims hold")


if __name__ == "__main__":
    main()
