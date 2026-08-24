"""TEST CASE 2 — validate the ported model against a second live REopt run.

REopt run 18d2e5c0-536f-4a07-8d8b-d2a24673b830 "TC2 Phoenix Supermarket":
  3401 N Central Ave, Phoenix AZ · Supermarket · 3,000,000 kWh · 2 acres
  rate USBIA-San Carlos Project: Commercial Pumps (539fc194ec4f024c27d8a859)
  PV $2000/kW max 1000 kW · Battery $350/kWh $900/kW const $0 max 2000 kWh
  20 years · discount 7.5% · elec escalation 2.2%
REopt built nothing (all rates too cheap), so BAU == optimized.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import data_sources as ds
from reopt_core import emissions as EM
from reopt_core import model as M
from reopt_core.tariff import build_tariff

LAT, LON = 33.4869, -112.0738
URDB = "539fc194ec4f024c27d8a859"
YEARS, DISC, ESC = 20, 0.075, 0.022

TARGET = {
    "pv_kw": 0, "bat_kw": 0, "bat_kwh": 0,
    "y1_energy": 117_000, "y1_demand": 16_526, "y1_fixed": 300, "y1_total": 133_826,
    "lcc": 1_214_920,
    "co2e_annual": 423, "cost_climate": 316_776, "cost_health": 270_141,
    "nox_annual": 0.46, "so2_annual": 0.21, "pm25_annual": 0.07,
    "cambium_location": "West Connect South", "avert_region": "Southwest",
}


def row(name, got, want, unit="", tol=0.02):
    if want in (0, None):
        ok, d = abs(got) < 1.0, "—"
    else:
        d = (got - want) / want
        ok, d = abs(d) <= tol, f"{d:+.2%}"
    print(f"  {'OK ' if ok else 'XX '} {name:<40} {got:>13,.2f} {unit:<6} vs {want:>13,.2f}  {d}")
    return ok


def main() -> None:
    L = ds.build_electric_load("Supermarket", 3_000_000, LAT, LON)
    print(f"CRB city: {L['city']} (zone {L['ashrae_zone']})  peak {L['peak_kw']:,.0f} kW\n")
    pf, _ = ds.call_pvwatts_api(LAT, LON, tilt=20, azimuth=180, array_type=0,
                                module_type=0, losses=14)
    tar = build_tariff(ds.fetch_urdb_rate(URDB))
    print(f"rate: {tar.utility} | {tar.name}")
    print(f"  blended energy ${tar.blended_energy_rate:.4f}/kWh  "
          f"TOU ratchets={len(tar.tou_demand_rates)}  fixed=${tar.fixed_monthly_charge}/mo\n")

    inp = M.ScenarioInputs(
        loads_kw=L["loads_kw"], tariff=tar,
        financial=M.FinancialInputs(analysis_years=YEARS,
                                    elec_cost_escalation_rate_fraction=ESC,
                                    offtaker_discount_rate_fraction=DISC),
        pv=M.PVInputs(enabled=True, installed_cost_per_kw=2000.0, max_kw=1000.0,
                      om_cost_per_kw=20.0, production_factor=pf),
        storage=M.StorageInputs(enabled=True, installed_cost_per_kwh=350.0,
                                installed_cost_per_kw=900.0,
                                installed_cost_constant=0.0, max_kwh=2000.0),
        fuel_tech=M.FuelTechInputs(enabled=False),
        land_acres=2.0, pv_location="ground",
    )
    r = M.solve(inp, time_limit=900)
    b = M.business_as_usual(inp)
    sz = r["sizes"]

    ok = []
    print("SYSTEM SIZE (REopt built nothing)")
    ok.append(row("PV", sz["pv_kw"], TARGET["pv_kw"], "kW"))
    ok.append(row("Battery power", sz["battery_kw"], TARGET["bat_kw"], "kW"))
    ok.append(row("Battery capacity", sz["battery_kwh"], TARGET["bat_kwh"], "kWh"))

    print("\nYEAR 1 UTILITY (BAU)")
    ok.append(row("energy", b["year1_energy_cost"], TARGET["y1_energy"], "$", 0.01))
    ok.append(row("demand", b["year1_tou_demand_cost"] + b["year1_monthly_demand_cost"],
                  TARGET["y1_demand"], "$", 0.01))
    ok.append(row("fixed", b["year1_fixed_cost"], TARGET["y1_fixed"], "$", 0.01))
    ok.append(row("total", b["year1_total"], TARGET["y1_total"], "$", 0.01))
    print("\nLIFE CYCLE")
    ok.append(row("Total life cycle cost", b["lifecycle_cost"], TARGET["lcc"], "$", 0.01))

    print("\nEMISSIONS")
    cam = EM.fetch_cambium_profile(LAT, LON, lifetime=YEARS)
    av = {p: EM.load_avert_profile(p, TARGET["avert_region"]) for p in ("NOx", "SO2", "PM25")}
    health = EM.fetch_health_cost_defaults(LAT, LON)
    print("  EASIUR (location-specific): NOx ${NOx_grid_cost_per_tonne:,.2f}  "
          "SO2 ${SO2_grid_cost_per_tonne:,.2f}  PM2.5 ${PM25_grid_cost_per_tonne:,.2f}".format(**health))
    em = EM.compute(grid_kwh_hourly=L["loads_kw"], cambium_series=cam["series"],
                    avert=av, years=YEARS, discount_rate=DISC, opts=health)
    print(f"  Cambium location: {cam['location']!r} vs REopt {TARGET['cambium_location']!r}"
          f"  {'OK' if cam['location'] == TARGET['cambium_location'] else 'XX'}")
    ok.append(cam["location"] == TARGET["cambium_location"])
    ok.append(row("Average annual CO2e (t)", em["annual_co2e_tonnes"], TARGET["co2e_annual"], "t", 0.02))
    ok.append(row("Average annual NOx (t)", em["annual_nox_tonnes"], TARGET["nox_annual"], "t", 0.05))
    ok.append(row("Average annual SO2 (t)", em["annual_so2_tonnes"], TARGET["so2_annual"], "t", 0.05))
    ok.append(row("Average annual PM2.5 (t)", em["annual_pm25_tonnes"], TARGET["pm25_annual"], "t", 0.08))
    ok.append(row("Cost of climate emissions", em["cost_climate"], TARGET["cost_climate"], "$", 0.02))
    ok.append(row("Cost of health emissions", em["cost_health"], TARGET["cost_health"], "$", 0.02))

    print(f"\n{sum(ok)}/{len(ok)} checks within tolerance")


if __name__ == "__main__":
    main()
