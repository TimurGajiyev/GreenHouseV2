"""Sana'a factory microgrid — the Sunwoda / Guangzhou Jiancheng proposal, re-costed.

Source: "Sana'a Factory, Yemen — PV-Storage-Diesel-Storage-type DVR Microgrid System
Technical Proposal", May 2026, 29 pp. Every input below is the vendor's own number;
nothing is substituted for a REopt default unless the deck is silent on it.

Site        Bani Mattar District, Sana'a — 15.2811 N, 44.0811 E  (deck p.1)
Load        650-700 kW over 10 working hours, >= 7,000 kWh/day   (deck p.4)
PV          >= 1,500 kWp, fixed tilt ~15 deg, true south          (deck p.7, p.8)
BESS        >= 3,132 kWh, twelve 261 kWh cabinets, 12 x 125 kW PCS (deck p.10)
DG          1,000 kW containerized, prime power                   (deck p.12)
Capex       PV $597,000 / BESS $613,300 / DG $306,500             (deck p.25-27)
Claims      2,737,500 kWh/yr PV, $711,750/yr saved at $0.26/kWh,
            3.3 yr simple payback, 3,000,000 L diesel and 8,000 t CO2 avoided (deck p.27)

Three scenarios, all off-grid, all at the vendor's own prices:
  V  the vendor's design, sizes forced to the deck
  O  the same prices, sizes chosen by the optimizer
  D  diesel only, the counterfactual the vendor's savings claim is measured against
"""

from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import data_sources as ds
from reopt_core import model as M

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "vendor_analysis")

LAT, LON = 15.2811, 44.0811

# ---- the deck's own figures -------------------------------------------------
PV_KWP = 1500.0
BESS_KWH = 3132.0
BESS_KW = 12 * 125.0            # deck p.10: twelve PCS units of >=125 kW
CABINET_HOURS = 261.0 / 125.0   # the cabinet is sold as a fixed 2.088 h block
DG_KW = 1000.0

PV_CAPEX = 597_000.0            # 59.7 x USD 10k
BESS_CAPEX = 613_300.0          # 61.33 x USD 10k
DG_CAPEX = 306_500.0            # 30.65 x USD 10k
DVR_CAPEX = 259_500.0           # 25.95 x USD 10k -- no REopt equivalent
EMS_CAPEX = 150_000.0           # 15.0  x USD 10k
DIST_CAPEX = 175_600.0          # 17.56 x USD 10k
COMMISSIONING = 55_000.0        # 5.5   x USD 10k
TOTAL_EQUIP = 2_161_900.0
TOTAL_PROJECT = 2_361_900.0     # incl. ~10% gross margin

PV_COST_PER_KW = PV_CAPEX / PV_KWP              # 398.00
BESS_COST_PER_KWH = BESS_CAPEX / BESS_KWH       # 195.82
DG_COST_PER_KW = DG_CAPEX / DG_KW               # 306.50

# Deck p.27 states diesel generation costs ~$0.26/kWh. REopt burns fuel by HHV:
#   gal/kWh = 1 / (electric_efficiency * fuel_higher_heating_value_kwh_per_gal)
# so the $/gal implied by the vendor's own $/kWh is derived, not guessed.
DIESEL_PER_KWH = 0.26
GEN_EFF = 0.322                 # generator.jl:112 default, HHV basis
GEN_HHV_KWH_PER_GAL = 40.7      # generator.jl default
GAL_PER_KWH = 1.0 / (GEN_EFF * GEN_HHV_KWH_PER_GAL)
DIESEL_PER_GAL = DIESEL_PER_KWH / GAL_PER_KWH
LITRES_PER_GAL = 3.785411784
KG_CO2_PER_GAL = 10.21          # EPA: 10.21 kg CO2 per US gallon of distillate

ANNUAL_KWH = 7000.0 * 365.0     # deck p.4: ">= 7,000 kWh/day"
ANALYSIS_YEARS = 10             # deck p.27 frames the benefit over 10 years


def scenario(profile: str, *, pv=(0.0, 0.0), bat_kwh=(0.0, 0.0), bat_kw=(0.0, 0.0),
             gen=(0.0, 0.0), pf=None):
    """Build one off-grid Yemen scenario. Tuples are (min, max)."""
    load = ds.build_electric_load(profile, ANNUAL_KWH, LAT, LON)
    return load, M.ScenarioInputs(
        loads_kw=load["loads_kw"],
        tariff=None,
        off_grid_flag=True,
        # No US tax code in Yemen: no ITC, no MACRS, no tax shield anywhere.
        financial=M.FinancialInputs(
            analysis_years=ANALYSIS_YEARS,
            offtaker_discount_rate_fraction=0.083,
            offtaker_tax_rate_fraction=0.0,
            owner_tax_rate_fraction=0.0,
            fuel_cost_escalation_rate_fraction=0.034,
        ),
        pv=M.PVInputs(
            enabled=pv[1] > 0, installed_cost_per_kw=PV_COST_PER_KW,
            min_kw=pv[0], max_kw=pv[1], om_cost_per_kw=20.0,
            macrs_option_years=0, macrs_bonus_fraction=0.0,
            macrs_itc_reduction=0.0, federal_itc_fraction=0.0,
            production_factor=pf,
        ),
        storage=M.StorageInputs(
            enabled=bat_kwh[1] > 0,
            # The vendor sells an indivisible 125 kW / 261 kWh cabinet, so the PCS
            # is inside the per-kWh price and the duration is fixed at 2.088 h.
            # Without the duration lock the optimizer buys unpriced power.
            installed_cost_per_kwh=BESS_COST_PER_KWH,
            installed_cost_per_kw=0.0,
            installed_cost_constant=0.0,
            min_duration_hours=CABINET_HOURS, max_duration_hours=CABINET_HOURS,
            min_kwh=bat_kwh[0], max_kwh=bat_kwh[1],
            min_kw=bat_kw[0], max_kw=bat_kw[1],
            can_grid_charge=False,
            macrs_option_years=0, macrs_bonus_fraction=0.0,
            macrs_itc_reduction=0.0, total_itc_fraction=0.0,
        ),
        fuel_tech=M.FuelTechInputs(
            enabled=gen[1] > 0, kind="Generator", label="Diesel Generator",
            installed_cost_per_kw=DG_COST_PER_KW,
            om_cost_per_kw=10.0,                # generator.jl:107, off-grid
            om_cost_per_kwh=0.0,
            electric_efficiency_full_load=GEN_EFF,
            fuel_higher_heating_value_kwh_per_gal=GEN_HHV_KWH_PER_GAL,
            fuel_cost_per_gallon=DIESEL_PER_GAL,
            min_kw=gen[0], max_kw=gen[1],
            macrs_option_years=0, macrs_bonus_fraction=0.0, federal_itc_fraction=0.0,
            replacement_year=10, replace_cost_per_kw=DG_COST_PER_KW,
        ),
        min_load_met_annual_fraction=0.99999,
    )


def run(name, desc, **kw):
    load, inp = scenario(**kw)
    r = M.solve(inp, time_limit=900)
    sz, en = r["sizes"], r["energy"]
    gal = en["fueltech_kwh"] * GAL_PER_KWH
    out = {
        "name": name, "desc": desc,
        "pv_kw": sz["pv_kw"], "battery_kw": sz["battery_kw"],
        "battery_kwh": sz["battery_kwh"], "gen_kw": sz["fueltech_kw"],
        "lcc": r["objective_lifecycle_cost"],
        "peak_kw": load["peak_kw"], "annual_kwh": load["annual_kwh"],
        "pv_kwh": en["pv_kwh"], "pv_curtailed_kwh": en["pv_curtailed_kwh"],
        "diesel_kwh": en["fueltech_kwh"],
        "diesel_gal": gal, "diesel_litres": gal * LITRES_PER_GAL,
        "co2_tonnes": gal * KG_CO2_PER_GAL / 1000.0,
        "upfront": r["capital"]["upfront_before_incentives"],
        "breakdown": r["breakdown"],
    }
    print(f"\n--- {name}: {desc}")
    print(f"    PV {out['pv_kw']:>8,.0f} kW   Battery {out['battery_kw']:>7,.0f} kW / "
          f"{out['battery_kwh']:>8,.0f} kWh   DG {out['gen_kw']:>7,.0f} kW")
    print(f"    upfront ${out['upfront']:>13,.0f}    "
          f"{ANALYSIS_YEARS}-yr life cycle cost ${out['lcc']:>14,.0f}")
    print(f"    PV generated {out['pv_kwh']:>11,.0f} kWh   curtailed "
          f"{out['pv_curtailed_kwh']:>11,.0f} kWh "
          f"({(out['pv_curtailed_kwh'] / out['pv_kwh'] * 100) if out['pv_kwh'] else 0:.1f}%)")
    print(f"    diesel {out['diesel_kwh']:>13,.0f} kWh  = {out['diesel_litres']:>11,.0f} L"
          f"   CO2 {out['co2_tonnes']:>9,.0f} t/yr")
    return out, r


def main():
    global DIESEL_PER_GAL
    print(f"Sana'a factory, off-grid, {ANALYSIS_YEARS}-yr horizon")
    print(f"  load  {ANNUAL_KWH:,.0f} kWh/yr")
    print(f"  diesel implied by the deck's $0.26/kWh: ${DIESEL_PER_GAL:.2f}/gal "
          f"(${DIESEL_PER_GAL / LITRES_PER_GAL:.2f}/L)")
    pf, _ = ds.call_pvwatts_api(LAT, LON, tilt=15, azimuth=180,
                                array_type=0, module_type=0, losses=14)
    print(f"  PVWatts at this site: {sum(pf):,.0f} kWh/kWp/yr "
          f"(deck claims 1,825 -> {1825 / sum(pf) - 1:+.1%})")

    results = {}
    for prof in ("FlatLoad_8_7", "FlatLoad_16_7"):
        print(f"\n{'=' * 78}\nLOAD SHAPE {prof}")
        big = 1e6
        V, rV = run("V", f"vendor design as specified [{prof}]", profile=prof, pf=pf,
                    pv=(PV_KWP, PV_KWP), bat_kwh=(BESS_KWH, BESS_KWH),
                    bat_kw=(BESS_KW, BESS_KW), gen=(DG_KW, DG_KW))
        O, rO = run("O", f"same prices, optimizer sizes [{prof}]", profile=prof, pf=pf,
                    pv=(0.0, 5000.0), bat_kwh=(0.0, 20000.0), bat_kw=(0.0, 10000.0),
                    gen=(0.0, 2000.0))
        D, rD = run("D", f"diesel only (the counterfactual) [{prof}]", profile=prof, pf=pf,
                    pv=(0.0, 0.0), bat_kwh=(0.0, 0.0), bat_kw=(0.0, 0.0),
                    gen=(0.0, 2000.0))
        results[prof] = {"V": V, "O": O, "D": D,
                         "raw": {"V": rV["sizes"], "O": rO["sizes"], "D": rD["sizes"]}}
        print(f"\n    vendor design vs diesel-only: "
              f"${D['lcc'] - V['lcc']:,.0f} saved over {ANALYSIS_YEARS} yr")
        print(f"    optimizer  vs vendor design:  "
              f"${V['lcc'] - O['lcc']:,.0f} better")

    # ---- the deck's whole case rests on diesel at $0.26/kWh; test that ----
    print(f"\n{'=' * 78}\nDIESEL PRICE SENSITIVITY (FlatLoad_8_7, optimizer sizing)")
    print(f"{'$/L':>7} {'$/kWh':>7} {'PV kW':>8} {'Batt kWh':>10} {'DG kW':>8} "
          f"{'LCC opt':>13} {'LCC diesel':>13} {'saving':>13}")
    base = DIESEL_PER_GAL
    sens = []
    for per_l in (0.45, 0.70, 0.90, 1.20, 1.60):
        DIESEL_PER_GAL = per_l * LITRES_PER_GAL
        _, io_ = scenario("FlatLoad_8_7", pv=(0.0, 5000.0), bat_kwh=(0.0, 20000.0),
                          bat_kw=(0.0, 10000.0), gen=(0.0, 2000.0), pf=pf)
        ro = M.solve(io_, time_limit=900)
        _, id_ = scenario("FlatLoad_8_7", pv=(0.0, 0.0), bat_kwh=(0.0, 0.0),
                          bat_kw=(0.0, 0.0), gen=(0.0, 2000.0), pf=pf)
        rd = M.solve(id_, time_limit=900)
        s = rd["objective_lifecycle_cost"] - ro["objective_lifecycle_cost"]
        row = {"usd_per_litre": per_l,
               "usd_per_kwh": DIESEL_PER_GAL * GAL_PER_KWH,
               "pv_kw": ro["sizes"]["pv_kw"], "battery_kwh": ro["sizes"]["battery_kwh"],
               "gen_kw": ro["sizes"]["fueltech_kw"],
               "lcc_optimized": ro["objective_lifecycle_cost"],
               "lcc_diesel_only": rd["objective_lifecycle_cost"], "saving": s}
        sens.append(row)
        print(f"{per_l:>7.2f} {row['usd_per_kwh']:>7.3f} {row['pv_kw']:>8,.0f} "
              f"{row['battery_kwh']:>10,.0f} {row['gen_kw']:>8,.0f} "
              f"${row['lcc_optimized']:>12,.0f} ${row['lcc_diesel_only']:>12,.0f} "
              f"${s:>12,.0f}")
    DIESEL_PER_GAL = base
    results["diesel_sensitivity"] = sens

    io.open(os.path.join(OUT, "yemen_runs.json"), "w", encoding="utf-8").write(
        json.dumps(results, indent=2, default=float))
    print(f"\nwrote {os.path.join(OUT, 'yemen_runs.json')}")


if __name__ == "__main__":
    main()
