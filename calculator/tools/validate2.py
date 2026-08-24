"""Validate against the FULL REopt results page for the A/B scenario.

Reference: REopt run "AB TEST PV+Battery" (Golden CO, Large Office 5,000,000 kWh,
Intermountain REA B-TOU, PV $1600/kW max 2000, Battery $300/kWh $800/kW const $0
max 4000 kWh, 25 yr, 8.3% discount, 1.7% escalation).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import data_sources as ds
from reopt_core import model as M
from reopt_core.tariff import build_tariff

LAT, LON = 39.74437, -105.15199

TARGET = {
    "pv_kw": 165, "bat_kw": 78, "bat_kwh": 171,
    "pv_total_kwh": 240_791, "pv_to_load": 239_468, "pv_to_batt": 1_324,
    "pv_export": 0, "pv_curtail": 0,
    "grid_to_load": 4_751_911, "grid_to_batt": 8_217, "grid_total": 4_760_128,
    "batt_to_load": 8_622,
    "y1_energy_bau": 318_150, "y1_energy_opt": 302_887,
    "y1_demand_bau": 193_252, "y1_demand_opt": 177_523,
    "y1_fixed": 480,
    "y1_total_bau": 511_882, "y1_total_opt": 480_890,
    "cap_after_incentives": 196_571,
    "om_lifecycle": 60_234, "y1_om": 6_162,
    "utility_lifecycle_bau": 4_624_884, "utility_lifecycle_opt": 4_344_872,
    "lcc_bau": 4_624_883, "lcc_opt": 4_601_676,
    "npv": 23_207, "upfront": 378_800,
}


def row(name, got, want, unit="", tol=0.01):
    if want in (0, None):
        ok = abs(got) < 1.0
        d = "—"
    else:
        d = (got - want) / want
        ok = abs(d) <= tol
        d = f"{d:+.2%}"
    flag = "OK " if ok else "XX "
    print(f"  {flag} {name:<44} {got:>14,.0f} {unit:<5} vs {want:>14,.0f}  {d}")
    return ok


def main() -> None:
    L = ds.build_electric_load("LargeOffice", 5_000_000, LAT, LON)
    pf, _ = ds.call_pvwatts_api(LAT, LON, tilt=20, azimuth=180, array_type=0,
                                module_type=0, losses=14)
    tar = build_tariff(ds.fetch_urdb_rate("5b44ffc75457a36716a907eb"))

    inp = M.ScenarioInputs(
        loads_kw=L["loads_kw"], tariff=tar,
        financial=M.FinancialInputs(analysis_years=25,
                                    elec_cost_escalation_rate_fraction=0.017,
                                    offtaker_discount_rate_fraction=0.083),
        pv=M.PVInputs(enabled=True, installed_cost_per_kw=1600.0, max_kw=2000.0,
                      om_cost_per_kw=20.0, production_factor=pf),
        storage=M.StorageInputs(enabled=True, installed_cost_per_kwh=300.0,
                                installed_cost_per_kw=800.0,
                                installed_cost_constant=0.0, max_kwh=4000.0),
        fuel_tech=M.FuelTechInputs(enabled=False),
        land_acres=5.0, pv_location="ground",
    )
    r = M.solve(inp, time_limit=900)
    b = M.business_as_usual(inp)
    sz, en, u, cap, om, f = (r["sizes"], r["energy"], r["utility"],
                             r["capital"], r["om"], r["factors"])
    s = r["series"]
    pv_to_batt = sum(min(s["pv_to_load_kw"][t], s["battery_charge_kw"][t]) for t in range(8760))

    print(f"status: {r['status']}\n")
    print("SYSTEM SIZE")
    ok = []
    ok.append(row("PV", sz["pv_kw"], TARGET["pv_kw"], "kW", 0.05))
    ok.append(row("Battery power", sz["battery_kw"], TARGET["bat_kw"], "kW", 0.05))
    ok.append(row("Battery capacity", sz["battery_kwh"], TARGET["bat_kwh"], "kWh", 0.05))

    print("\nENERGY")
    ok.append(row("PV total produced", en["pv_kwh"], TARGET["pv_total_kwh"], "kWh", 0.02))
    ok.append(row("PV curtailed", en["pv_curtailed_kwh"], TARGET["pv_curtail"], "kWh"))
    ok.append(row("Grid total consumed", en["grid_kwh"], TARGET["grid_total"], "kWh", 0.02))
    ok.append(row("Battery serving load", en["battery_discharge_kwh"], TARGET["batt_to_load"], "kWh", 0.15))

    print("\nYEAR 1 UTILITY")
    ok.append(row("energy  BAU", b["year1_energy_cost"], TARGET["y1_energy_bau"], "$", 0.001))
    ok.append(row("energy  optimized", u["year1_energy_cost"], TARGET["y1_energy_opt"], "$", 0.01))
    ok.append(row("demand  BAU", b["year1_tou_demand_cost"] + b["year1_monthly_demand_cost"],
                  TARGET["y1_demand_bau"], "$", 0.001))
    ok.append(row("demand  optimized", u["year1_tou_demand_cost"] + u["year1_monthly_demand_cost"],
                  TARGET["y1_demand_opt"], "$", 0.01))
    ok.append(row("total   BAU", b["year1_total"], TARGET["y1_total_bau"], "$", 0.001))
    ok.append(row("total   optimized", u["year1_total"], TARGET["y1_total_opt"], "$", 0.01))

    print("\nCOSTS")
    tech_cap = (cap["pv_cap_cost_slope_per_kw"] * sz["pv_kw"]
                + cap["storage_npc_per_kw"] * sz["battery_kw"]
                + cap["storage_npc_per_kwh"] * sz["battery_kwh"])
    y1om = om["year1_pv"] + om["year1_storage"] + om["year1_fueltech"]
    ok.append(row("Tech capital after incentives", tech_cap, TARGET["cap_after_incentives"], "$", 0.02))
    ok.append(row("Year 1 O&M before tax", y1om, TARGET["y1_om"], "$", 0.02))
    ok.append(row("O&M lifecycle after tax", y1om * f["pwf_om"] * 0.74,
                  TARGET["om_lifecycle"], "$", 0.02))
    ok.append(row("Upfront before incentives", cap["upfront_before_incentives"],
                  TARGET["upfront"], "$", 0.02))
    ok.append(row("Utility lifecycle BAU", b["lifecycle_cost"],
                  TARGET["utility_lifecycle_bau"], "$", 0.001))
    ok.append(row("LCC BAU", b["lifecycle_cost"], TARGET["lcc_bau"], "$", 0.001))
    ok.append(row("LCC optimized", r["objective_lifecycle_cost"], TARGET["lcc_opt"], "$", 0.02))
    ok.append(row("NPV (savings)", b["lifecycle_cost"] - r["objective_lifecycle_cost"],
                  TARGET["npv"], "$", 0.05))

    print(f"\n{sum(ok)}/{len(ok)} checks within tolerance")


if __name__ == "__main__":
    main()
