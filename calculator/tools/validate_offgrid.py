"""OG1 -- validate the off-grid path against a real REopt web-tool run.

REopt run 431b38d4-8d87-448c-a483-a4c6f9826116, off-grid, Golden CO,
FlatLoad_8_7 @ 2,555,000 kWh, 10-year analysis. Every input below is read off
that run's own "Inputs" echo, so nothing is assumed.

Two of REopt's off-grid behaviours are deliberately isolated:

  A. The web tool pins the generator to 200% of peak load (its "Peak Load
     Multiplier"), giving 1,750 kW rather than letting the optimizer choose.
     That is a tool-side convention -- no such rule exists in REopt.jl -- so
     OG1a pins it the same way and OG1b lets our optimizer size it.
  B. REopt applies operating reserve off-grid (10% of load, 25% of PV). We do
     not model it. The PV gap between OG1a and REopt is that omission's price.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import data_sources as ds
from reopt_core import model as M

LAT, LON = 39.74437, -105.15199
ANNUAL_KWH = 2_555_000.0
GAL_PER_KWH = 1.0 / (0.322 * 40.7)

# ---- what REopt reported for this run ----
REOPT = {
    "PV Size (kW)": 767.0,
    "Battery Capacity (kWh)": 0.0,
    "Generator Size (kW)": 1750.0,
    "PV Total Electricity Produced (kWh)": 1_143_326.0,
    "PV Curtailment (kWh)": 175_423.0,
    "Generator Total Electricity Produced (kWh)": 1_587_071.0,
    "Annual Diesel Fuel Use (gal)": 121_101.0,
    "Total Upfront Capital Cost Before Incentives ($)": 3_234_152.0,
    "Year 1 O&M Cost ($)": 32_846.0,
    "Total Life Cycle Costs ($)": 4_224_458.0,
}


def build(gen_min, gen_max, pf):
    load = ds.build_electric_load("FlatLoad_8_7", ANNUAL_KWH, LAT, LON)
    return load, M.ScenarioInputs(
        loads_kw=load["loads_kw"], tariff=None, off_grid_flag=True,
        financial=M.FinancialInputs(
            analysis_years=10,
            offtaker_discount_rate_fraction=0.0624,
            offtaker_tax_rate_fraction=0.26,
            om_cost_escalation_rate_fraction=0.025,
            fuel_cost_escalation_rate_fraction=0.0197,
        ),
        pv=M.PVInputs(
            enabled=True, installed_cost_per_kw=2208.0, om_cost_per_kw=20.0,
            macrs_option_years=5, macrs_bonus_fraction=1.0, macrs_itc_reduction=0.5,
            federal_itc_fraction=0.30, acres_per_kw=0.006, production_factor=pf,
        ),
        storage=M.StorageInputs(
            enabled=True, installed_cost_per_kwh=253.0, installed_cost_per_kw=968.0,
            installed_cost_constant=222_115.0, om_cost_fraction_of_installed_cost=0.025,
            macrs_option_years=5, macrs_bonus_fraction=1.0, macrs_itc_reduction=0.5,
            total_itc_fraction=0.30, soc_min_fraction=0.2, soc_init_fraction=1.0,
            can_grid_charge=False,
        ),
        fuel_tech=M.FuelTechInputs(
            enabled=True, kind="Generator", label="Generator",
            installed_cost_per_kw=880.0, fuel_cost_per_gallon=2.25,
            om_cost_per_kw=10.0, om_cost_per_kwh=0.0,
            electric_efficiency_full_load=0.322,
            fuel_higher_heating_value_kwh_per_gal=40.7,
            min_kw=gen_min, max_kw=gen_max,
            replacement_year=10, replace_cost_per_kw=880.0,
            macrs_option_years=0, macrs_bonus_fraction=0.0, federal_itc_fraction=0.0,
        ),
        land_acres=50.0, pv_location="ground",
        min_load_met_annual_fraction=0.999,
    )


def row(name, got, want, unit="", tol=0.03):
    if want in (None, 0.0):
        ok = abs(got) < 1.0 if want == 0.0 else None
        d = "—"
    else:
        rel = (got - want) / want
        ok, d = abs(rel) <= tol, f"{rel:+.2%}"
    tag = "-- " if ok is None else ("OK " if ok else "XX ")
    print(f"   {tag} {name:<46} {got:>13,.0f} {unit:<4} vs {want:>13,.0f}  {d}")
    return ok


def main():
    pf, _ = ds.call_pvwatts_api(LAT, LON, tilt=20, azimuth=180, array_type=0,
                                module_type=0, losses=14)
    load, _ = build(0, 0, pf)
    print(f"peak load {load['peak_kw']:,.0f} kW  ->  REopt pins the generator at "
          f"200% = {2 * load['peak_kw']:,.0f} kW\n")

    print("=" * 84)
    print("OG1a  generator pinned to 1,750 kW, as the web tool submitted it")
    _, inp = build(1750.0, 1750.0, pf)
    r = M.solve(inp, time_limit=900)
    sz, en, cap, om = r["sizes"], r["energy"], r["capital"], r["om"]
    res = [
        row("PV Size", sz["pv_kw"], REOPT["PV Size (kW)"], "kW"),
        row("Battery Capacity", sz["battery_kwh"], REOPT["Battery Capacity (kWh)"], "kWh"),
        row("Generator Size", sz["fueltech_kw"], REOPT["Generator Size (kW)"], "kW"),
        row("PV Total Electricity Produced", en["pv_kwh"],
            REOPT["PV Total Electricity Produced (kWh)"], "kWh"),
        row("PV Curtailment", en["pv_curtailed_kwh"],
            REOPT["PV Curtailment (kWh)"], "kWh", 0.10),
        row("Generator Total Electricity Produced", en["fueltech_kwh"],
            REOPT["Generator Total Electricity Produced (kWh)"], "kWh"),
        row("Annual Diesel Fuel Use", en["fueltech_kwh"] * GAL_PER_KWH,
            REOPT["Annual Diesel Fuel Use (gal)"], "gal"),
        row("Total Upfront Capital Cost Before Incentives",
            cap["upfront_before_incentives"],
            REOPT["Total Upfront Capital Cost Before Incentives ($)"], "$"),
        row("Year 1 O&M Cost", om["year1_pv"] + om["year1_fueltech"] + om["year1_storage"],
            REOPT["Year 1 O&M Cost ($)"], "$"),
        row("Total Life Cycle Costs", r["objective_lifecycle_cost"],
            REOPT["Total Life Cycle Costs ($)"], "$"),
    ]
    good = [x for x in res if x is not None]
    print(f"   -> {sum(good)}/{len(good)} within tolerance")
    orr = r.get("operating_reserve", {})
    print(f"   operating reserve required {orr.get('required_kwh', 0):>12,.0f} kWh "
          f"vs REopt 497,473")
    print(f"   operating reserve provided {orr.get('provided_kwh', 0):>12,.0f} kWh "
          f"vs REopt 763,620")

    print("=" * 84)
    print("OG1c  PV pinned to REopt's 767 kW -- is the cost surface simply flat?")
    _, inp3 = build(1750.0, 1750.0, pf)
    inp3.pv.min_kw = 767.0
    inp3.pv.max_kw = 767.0
    r3 = M.solve(inp3, time_limit=900)
    d = r3["objective_lifecycle_cost"] - r["objective_lifecycle_cost"]
    print(f"   PV   767 kW  ->  life cycle cost ${r3['objective_lifecycle_cost']:,.0f}")
    print(f"   PV {r['sizes']['pv_kw']:,.0f} kW  ->  life cycle cost "
          f"${r['objective_lifecycle_cost']:,.0f}")
    print(f"   difference ${d:,.0f} "
          f"({d / r['objective_lifecycle_cost']:+.2%} of life cycle cost)")
    print(f"   REopt reported ${REOPT['Total Life Cycle Costs ($)']:,.0f} at PV 767 kW; "
          f"ours at the same size differs by "
          f"{r3['objective_lifecycle_cost'] / REOPT['Total Life Cycle Costs ($)'] - 1:+.2%}")
    print("   The web tool ran HiGHS at a 5% optimality tolerance, so two points this "
          "close in cost are indistinguishable to it.")

    print("=" * 84)
    print("OG1b  same scenario, our optimizer free to size the generator")
    _, inp2 = build(0.0, 5000.0, pf)
    r2 = M.solve(inp2, time_limit=900)
    s2, e2 = r2["sizes"], r2["energy"]
    print(f"   PV {s2['pv_kw']:,.0f} kW   Battery {s2['battery_kwh']:,.0f} kWh   "
          f"Generator {s2['fueltech_kw']:,.0f} kW")
    print(f"   life cycle cost ${r2['objective_lifecycle_cost']:,.0f}  "
          f"vs ${r['objective_lifecycle_cost']:,.0f} pinned  "
          f"(${r['objective_lifecycle_cost'] - r2['objective_lifecycle_cost']:,.0f} lower)")
    print(f"   diesel {e2['fueltech_kwh'] * GAL_PER_KWH:,.0f} gal/yr")


if __name__ == "__main__":
    main()
