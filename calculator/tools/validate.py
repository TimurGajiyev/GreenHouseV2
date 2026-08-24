"""Validate the ported model against the real REopt web-tool runs.

Reference run (captured 2026-08-23, job 8176a8da-26e9-436e-b17d-52ce1fe4ce42):
  site 1617 Cole Blvd Golden CO, Large Office 5,000,000 kWh, 5 acres
  PV $1600/kW max 2000 kW, Battery $300/kWh $800/kW constant $0
  tariff Intermountain REA Commercial Demand Metered TOU (B-TOU)
  -> REopt returned PV 498 kW, Battery 199 kW / 470 kWh, savings $107,910
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import data_sources as ds
from reopt_core import model as M
from reopt_core.tariff import build_tariff

LAT, LON = 39.74437, -105.15199
URDB = "5b44ffc75457a36716a907eb"


def main() -> None:
    t0 = time.time()
    print("loading load profile ...")
    L = ds.build_electric_load("LargeOffice", 5_000_000, LAT, LON)
    print(f"  city={L['city']}  annual={L['annual_kwh']:,.0f} kWh  peak={L['peak_kw']:,.1f} kW")

    print("calling PVWatts ...")
    pf, _ = ds.call_pvwatts_api(LAT, LON, tilt=20, azimuth=180, array_type=0,
                                module_type=0, losses=14)
    print(f"  annual kWh/kW = {sum(pf):,.1f}")

    print("fetching URDB rate ...")
    tar = build_tariff(ds.fetch_urdb_rate(URDB))
    print(f"  {tar.utility} | {tar.name}")
    print(f"  blended energy ${tar.blended_energy_rate:.4f}/kWh  "
          f"TOU demand periods={len(tar.tou_demand_rates)} rates={tar.tou_demand_rates}  "
          f"monthly demand={set(round(r,2) for r in tar.monthly_demand_rates)}  "
          f"fixed=${tar.fixed_monthly_charge}/mo")

    inp = M.ScenarioInputs(
        loads_kw=L["loads_kw"],
        tariff=tar,
        financial=M.FinancialInputs(
            analysis_years=25,
            elec_cost_escalation_rate_fraction=0.017,
            offtaker_discount_rate_fraction=0.083,
        ),
        pv=M.PVInputs(enabled=True, installed_cost_per_kw=1600.0, max_kw=2000.0,
                      production_factor=pf),
        storage=M.StorageInputs(enabled=True, installed_cost_per_kwh=300.0,
                                installed_cost_per_kw=800.0, installed_cost_constant=0.0,
                                max_kwh=4000.0),
        fuel_tech=M.FuelTechInputs(enabled=False),
        land_acres=5.0,
    )

    bau = M.business_as_usual(inp)
    print(f"\nBAU year-1 utility cost: ${bau['year1_total']:,.0f} "
          f"(energy ${bau['year1_energy_cost']:,.0f} + "
          f"TOU demand ${bau['year1_tou_demand_cost']:,.0f} + "
          f"monthly demand ${bau['year1_monthly_demand_cost']:,.0f} + "
          f"fixed ${bau['year1_fixed_cost']:,.0f})")

    print("\nsolving ...")
    r = M.solve(inp, msg=False, time_limit=600)
    print(f"  status: {r['status']}   ({time.time()-t0:.0f}s total)")
    sz = r["sizes"]
    print(f"\n  PV        {sz['pv_kw']:>10,.1f} kW      (REopt: 498 kW)")
    print(f"  Battery   {sz['battery_kw']:>10,.1f} kW      (REopt: 199 kW)")
    print(f"  Battery   {sz['battery_kwh']:>10,.1f} kWh     (REopt: 470 kWh)")
    e = r["energy"]
    print(f"\n  PV energy      {e['pv_kwh']:>12,.0f} kWh   (REopt: 721,620)")
    print(f"  PV curtailed   {e['pv_curtailed_kwh']:>12,.0f} kWh   (REopt: 4,986)")
    print(f"  grid           {e['grid_kwh']:>12,.0f} kWh")
    u = r["utility"]
    print(f"\n  optimised year-1 utility ${u['year1_total']:,.0f}")
    print(f"  BAU  lifecycle  ${bau['lifecycle_cost']:,.0f}")
    print(f"  opt  objective  ${r['objective_lifecycle_cost']:,.0f}")
    print(f"  implied savings ${bau['lifecycle_cost'] - r['objective_lifecycle_cost']:,.0f}"
          f"   (REopt: $107,910)")
    print(f"\n  cap cost slopes: PV ${r['capital']['pv_cap_cost_slope_per_kw']:.2f}/kW  "
          f"batt ${r['capital']['storage_npc_per_kw']:.2f}/kW "
          f"${r['capital']['storage_npc_per_kwh']:.2f}/kWh")
    print(f"  factors: {r['factors']}")


if __name__ == "__main__":
    main()
