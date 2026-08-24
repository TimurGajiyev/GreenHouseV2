"""Why does the ported model pick less PV than REopt? Marginal-value diagnostic."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import data_sources as ds
from reopt_core.finance import annuity, effective_cost, levelization_factor, MACRS_FIVE_YEAR
from reopt_core.tariff import build_tariff

LAT, LON = 39.74437, -105.15199
YEARS, ESC, DISC, TAX = 25, 0.017, 0.083, 0.26

L = ds.build_electric_load("LargeOffice", 5_000_000, LAT, LON)["loads_kw"]
pf, _ = ds.call_pvwatts_api(LAT, LON, tilt=20, azimuth=180, array_type=0, module_type=0, losses=14)
tar = build_tariff(ds.fetch_urdb_rate("5b44ffc75457a36716a907eb"))

pwf_e = annuity(YEARS, ESC, DISC)
pwf_om = annuity(YEARS, 0.025, DISC)
lvl = levelization_factor(YEARS, ESC, DISC, 0.005)

slope = effective_cost(itc_basis=1600.0, replacement_cost=0.0, replacement_year=YEARS,
                       discount_rate=DISC, tax_rate=TAX, itc=0.3,
                       macrs_schedule=MACRS_FIVE_YEAR, macrs_bonus_fraction=1.0,
                       macrs_itc_reduction=0.5)

annual_kwh_per_kw = sum(pf) * lvl
blended = sum(tar.energy_cost_per_kwh) / 8760
pv_weighted = sum(pf[h] * tar.energy_cost_per_kwh[h] for h in range(8760)) / sum(pf)

print(f"PV annual kWh per kW (levelized): {annual_kwh_per_kw:,.1f}")
print(f"blended energy rate            : ${blended:.4f}/kWh")
print(f"PV-production-weighted rate    : ${pv_weighted:.4f}/kWh")
print(f"PV effective capital           : ${slope:,.2f}/kW  (from $1600)")
print(f"pwf_e={pwf_e}  pwf_om={pwf_om}  levelization={lvl:.4f}")

energy_value = annual_kwh_per_kw * pv_weighted * pwf_e * (1 - TAX)
om_cost = 18.0 * pwf_om * (1 - TAX)
print(f"\nmarginal PV per kW, ENERGY ONLY:")
print(f"   lifecycle energy value  ${energy_value:,.2f}")
print(f"   lifecycle O&M cost      ${om_cost:,.2f}")
print(f"   capital                 ${slope:,.2f}")
print(f"   net                     ${energy_value - om_cost - slope:,.2f} per kW")

# demand: how much peak reduction does PV give per kW installed?
print("\nmonthly peak hours vs PV output at those hours:")
coincident = 0.0
for i, (rate, hrs) in enumerate(zip(tar.tou_demand_rates, tar.tou_demand_periods)):
    peak_h = max(hrs, key=lambda h: L[h])
    coincident += rate * pf[peak_h] * lvl
    if i < 4:
        print(f"   ratchet {i:2d} rate ${rate:.2f}/kW  peak hour {peak_h:5d} "
              f"load {L[peak_h]:7.1f} kW  PV pf {pf[peak_h]:.3f}")
demand_value = coincident * pwf_e * (1 - TAX)
print(f"   naive coincident demand value ${demand_value:,.2f} per kW lifecycle")
print(f"\n   TOTAL naive marginal value ${energy_value + demand_value - om_cost - slope:,.2f} per kW")
