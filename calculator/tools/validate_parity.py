"""PT2 -- a live head-to-head on a scenario neither calculator had seen.

REopt run c5e511b2-56d6-4673-8a7a-f46338687576, submitted through reopt.nlr.gov
while this test was being written. Golden CO supermarket, 3,000,000 kWh/yr,
PV + Battery, Intermountain REA B-TOU, 20-year analysis, 6 acres.

Every input below is read off that run's own input echo and every reference
number off its own result tables. Nothing here overlaps the earlier test cases:
different building type, load, costs, horizon, discount rate, escalation and
land than TC1/TC2/G1/G2.

A first attempt (PT1, Phoenix) was discarded rather than reported: the web tool
submits the tariff by display name and resolves it server-side, and the record
it resolved implies ~$0.58/kWh -- no URDB rate at that location is above
~$0.13/kWh, so the tariff could not be reproduced on our side. PT2 therefore
keeps the one tariff whose parsing is already proven exact and varies
everything else.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import data_sources as ds
from reopt_core import model as M
from reopt_core.tariff import build_tariff

LAT, LON = 39.74437, -105.15199
URDB = "5b44ffc75457a36716a907eb"       # Intermountain REA, B-TOU
ANNUAL_KWH = 3_000_000.0

# ---- REopt's own numbers: (business as usual, optimized) ----
BAU, OPT = 0, 1
R = {
    "PV Size":                                    (0.0, 25.0,        "kW",  0.20),
    "Battery Power":                              (0.0, 26.0,        "kW",  0.25),
    "Battery Capacity":                           (0.0, 36.0,        "kWh", 0.25),
    "Average Annual PV Energy Production":        (0.0, 36_747.0,    "kWh", 0.20),
    "Utility Energy Cost":                        (190_890.0, 188_571.0, "$", 0.01),
    "Utility Demand Cost":                        (91_771.0, 86_999.0,   "$", 0.02),
    "Utility Fixed Cost":                         (480.0, 480.0,     "$",   0.01),
    "Total Year 1 Utility Cost - Before Tax":     (283_141.0, 276_050.0, "$", 0.01),
    "Total Life Cycle Costs":                     (2_570_463.0, 2_559_868.0, "$", 0.01),
    "Net Present Value":                          (0.0, 10_595.0,    "$",  0.35),
    "Total Upfront Capital Cost Before Incentives": (0.0, 80_081.0,  "$",  0.20),
    "Year 1 O&M Cost, Before Tax":                (0.0, 1_343.0,     "$",  0.20),
}
DISPATCH = {
    "PV Serving Load (kWh)":              (36_304.0,    0.20),
    "PV Charging Battery (kWh)":          (443.0,       1.00),
    "PV Curtailment (kWh)":               (0.0,         0.0),
    "PV Total Electricity Produced (kWh)": (36_747.0,   0.20),
    "Battery Serving Load (kWh)":         (2_766.0,     0.60),
    "Grid Serving Load (kWh)":            (2_960_930.0, 0.01),
    "Grid Charging Battery (kWh)":        (2_624.0,     0.60),
}


def row(name, got, want, unit="", tol=0.02):
    if abs(want) < 1e-9:
        ok, d = abs(got) < 1.0, "—"
    else:
        rel = (got - want) / want
        ok, d = abs(rel) <= tol, f"{rel:+.2%}"
    print(f"  {'OK ' if ok else 'XX '} {name:<44} {got:>14,.0f} {unit:<4} vs "
          f"{want:>14,.0f}  {d}")
    return ok


def main():
    pf, _ = ds.call_pvwatts_api(LAT, LON, tilt=20, azimuth=180, array_type=0,
                                module_type=0, losses=14)
    tar = build_tariff(ds.fetch_urdb_rate(URDB))
    load = ds.build_electric_load("Supermarket", ANNUAL_KWH, LAT, LON)

    inp = M.ScenarioInputs(
        loads_kw=load["loads_kw"], tariff=tar,
        financial=M.FinancialInputs(
            analysis_years=20,
            offtaker_discount_rate_fraction=0.075,
            offtaker_tax_rate_fraction=0.26,
            elec_cost_escalation_rate_fraction=0.022,
            om_cost_escalation_rate_fraction=0.025,
        ),
        pv=M.PVInputs(
            enabled=True, installed_cost_per_kw=1850.0, om_cost_per_kw=20.0,
            min_kw=0.0, max_kw=1500.0, acres_per_kw=0.006,
            macrs_option_years=5, macrs_bonus_fraction=1.0, macrs_itc_reduction=0.5,
            federal_itc_fraction=0.30, production_factor=pf,
        ),
        storage=M.StorageInputs(
            enabled=True, installed_cost_per_kwh=320.0, installed_cost_per_kw=850.0,
            installed_cost_constant=0.0, max_kwh=3000.0,
            om_cost_fraction_of_installed_cost=0.025,
            macrs_option_years=5, macrs_bonus_fraction=1.0, macrs_itc_reduction=0.5,
            total_itc_fraction=0.30, soc_min_fraction=0.2, soc_init_fraction=0.5,
        ),
        fuel_tech=M.FuelTechInputs(enabled=False),
        land_acres=6.0, pv_location="ground",
        compensation_type="no_compensation",
    )

    print(f"load: {load['city']} Supermarket {load['annual_kwh']:,.0f} kWh, "
          f"peak {load['peak_kw']:,.0f} kW")
    print(f"tariff: {tar.fixed_monthly_charge:.2f} $/month fixed, "
          f"{len(tar.tou_demand_rates)} TOU demand periods\n")

    r = M.solve(inp, time_limit=900)
    b = M.business_as_usual(inp)
    sz, u, en, cap, om, bd = (r["sizes"], r["utility"], r["energy"],
                              r["capital"], r["om"], r["breakdown"])
    lcc_bau, lcc_opt = b["lifecycle_cost"], r["objective_lifecycle_cost"]

    res = []
    print("=" * 90)
    print("BUSINESS AS USUAL  (no optimization -- a pure tariff x load check)")
    for k, got in (
        ("Utility Energy Cost", b["year1_energy_cost"]),
        ("Utility Demand Cost", b["year1_tou_demand_cost"] + b["year1_monthly_demand_cost"]),
        ("Utility Fixed Cost", b["year1_fixed_cost"]),
        ("Total Year 1 Utility Cost - Before Tax", b["year1_total"]),
        ("Total Life Cycle Costs", lcc_bau),
    ):
        w, unit, tol = R[k][BAU], R[k][2], R[k][3]
        res.append(row(k, got, w, unit, tol))

    print("\nOPTIMIZED")
    for k, got in (
        ("PV Size", sz["pv_kw"]),
        ("Battery Power", sz["battery_kw"]),
        ("Battery Capacity", sz["battery_kwh"]),
        ("Average Annual PV Energy Production", en["pv_kwh"]),
        ("Utility Energy Cost", u["year1_energy_cost"]),
        ("Utility Demand Cost", u["year1_tou_demand_cost"] + u["year1_monthly_demand_cost"]),
        ("Utility Fixed Cost", u["year1_fixed_cost"]),
        ("Total Year 1 Utility Cost - Before Tax", u["year1_total"]),
        ("Total Upfront Capital Cost Before Incentives", cap["upfront_before_incentives"]),
        ("Year 1 O&M Cost, Before Tax", om["year1_pv"] + om["year1_storage"]),
        ("Total Life Cycle Costs", lcc_opt),
        ("Net Present Value", lcc_bau - lcc_opt),
    ):
        w, unit, tol = R[k][OPT], R[k][2], R[k][3]
        res.append(row(k, got, w, unit, tol))

    print("\nANNUAL ELECTRICITY PRODUCTION BREAKDOWN")
    for k, got in (
        ("PV Serving Load (kWh)", bd["pv_serving_load"]),
        ("PV Charging Battery (kWh)", bd["pv_charging_battery"]),
        ("PV Curtailment (kWh)", bd["pv_curtailed"]),
        ("PV Total Electricity Produced (kWh)", bd["pv_total"]),
        ("Battery Serving Load (kWh)", bd["battery_serving_load"]),
        ("Grid Serving Load (kWh)", bd["grid_serving_load"]),
        ("Grid Charging Battery (kWh)", bd["grid_charging_battery"]),
    ):
        w, tol = DISPATCH[k]
        res.append(row(k, got, w, "kWh", tol))

    print("\n" + "=" * 90)
    print(f"{sum(res)}/{len(res)} rows within tolerance")
    print(f"\nheadline: life cycle cost ${lcc_opt:,.0f} vs REopt ${R['Total Life Cycle Costs'][OPT]:,.0f} "
          f"({lcc_opt / R['Total Life Cycle Costs'][OPT] - 1:+.3%})")


if __name__ == "__main__":
    main()
