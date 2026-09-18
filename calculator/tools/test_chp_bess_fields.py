"""CHP + Battery against the live REopt web tool: defaults, curve, heat, BAU.

Everything here is checked against numbers the tool itself printed on
2026-09-18 (reopt_test_data/chp-bess-panels.json and REopt run
ee53addc-199c-4176-9dfe-ff3c205e70f9, Golden CO, Hospital, $8/MMBtu):

  1. the CHP defaults the tool derives from the heating load
  2. a scalar cost with no incentives collapses to REopt's one-segment slope
  3. the hourly heating load reproduces the CRB fuel total
  4. the BAU life cycle cost, heating fuel and boiler size REopt reported
  5. every Battery and CHP label in the capture exists in app_chp_bess.py,
     in the same order

    python tools/test_chp_bess_fields.py
"""

from __future__ import annotations

import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import chp_defaults as C
from reopt_core import cost_curve as CC
from reopt_core import data_sources as ds
from reopt_core import model as M
from reopt_core.finance import effective_cost
from reopt_core.tariff import build_tariff

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAPTURE = os.path.join(ROOT, "reopt_test_data", "chp-bess-panels.json")
APP = os.path.join(ROOT, "calculator", "app_chp_bess.py")
LAT, LON = 39.74437, -105.15199
FAIL: list[str] = []


def check(name, got, want, tol=0.0):
    ok = (abs(got - want) <= tol) if isinstance(want, (int, float)) and not isinstance(want, bool) \
        else got == want
    print(f"  {'OK' if ok else 'XX'}  {name:<58} {got!s:>16}  (site {want})")
    if not ok:
        FAIL.append(f"{name}: {got} vs {want}")


def main():
    print("1. CHP defaults derived from the heating load (Hospital, Golden)")
    heat = ds.build_heating_load("Hospital", LAT, LON)
    d = C.get_chp_defaults_prime_mover_size_class(
        avg_boiler_fuel_load_mmbtu_per_hour=heat["avg_fuel_mmbtu_per_hour"], boiler_efficiency=0.8)
    di = d["default_inputs"]
    check("heuristic size, as printed (truncated) kW", int(d["chp_elec_size_heuristic_kw"]), 170)
    check("size class", d["size_class"], 2)
    check("prime mover", d["prime_mover"], "recip_engine")
    check("maximum new electric power capacity kW", round(d["chp_max_size_kw"]), 341)
    check("minimum new non-zero power capacity kW", di["min_allowable_kw"], 50.0)
    check("size-cost pair sizes", list(di["tech_sizes_for_cost_curve"]), [100, 250])
    check("size-cost pair costs", list(di["installed_cost_per_kw"]), [3920.0, 3660.0])
    check("variable O&M $/kWh", di["om_cost_per_kwh"], 0.027)
    check("electric efficiency 100%", di["electric_efficiency_full_load"], 0.312)
    check("thermal efficiency 100%", di["thermal_efficiency_full_load"], 0.485)
    check("min electric loading", di["min_turn_down_fraction"], 0.25)
    check("absorption chiller knockdown", di["cooling_thermal_factor"], 0.825)
    unav = C.generate_year_profile_hourly(2017, di["unavailability_periods"])
    check("default maintenance hours in 2017", int(sum(unav)), 432)

    print("\n2. Cost curve: a scalar with no incentives is one segment of effective_cost(round(c))")
    for c in (1920.0, 3382.5, 4510.0, 2764.49):
        sl, _, yi, n = CC.cost_curve(CC.CostCurveTech(installed_cost_per_kw=c, tech_sizes_for_cost_curve=[]),
                                     analysis_years=25, owner_discount_rate=0.0624, owner_tax_rate=0.26)
        ref = effective_cost(itc_basis=round(c), replacement_cost=0.0, replacement_year=25,
                             discount_rate=0.0624, tax_rate=0.26, itc=0.0, macrs_schedule=[0.0],
                             macrs_bonus_fraction=0.0, macrs_itc_reduction=0.0)
        check(f"  ${c:,.2f}/kW -> segments", n, 1)
        check(f"  ${c:,.2f}/kW -> slope", sl[0], ref, 1e-9)
    sl, bx, yi, n = CC.cost_curve(CC.CostCurveTech(installed_cost_per_kw=[3920.0, 3660.0],
                                                   tech_sizes_for_cost_curve=[100, 250]),
                                  analysis_years=25, owner_discount_rate=0.0624, owner_tax_rate=0.26)
    check("class 2 pairs -> segments", n, 3)
    check("class 2 pairs -> breakpoints", [round(x) for x in bx[:3]], [0, 100, 250])
    # the curve must pass through the priced points: 100 kW x $3,920 and 250 kW x $3,660
    at = lambda kw, s: sl[s] * kw + yi[s]
    check("curve at 100 kW (segment 1) $", round(at(100, 0)), 392000)
    # REopt rounds each segment slope to whole dollars (cost_curve.jl:272), so its
    # own curve reaches 250 kW at 392,000 + round(523,000 / 150) x 150 = 915,050
    check("curve at 250 kW (segment 2), REopt's rounded slope $", round(at(250, 1)),
          392000 + round((915000 - 392000) / 150) * 150)

    print("\n3. Hourly heating load vs the CRB table")
    tbl = ds.heating_load_mmbtu("Hospital", heat["city"])
    check("annual heating fuel MMBtu", round(heat["annual_fuel_mmbtu"], 1), round(tbl["fuel_mmbtu"], 1))
    check("thermal MMBtu (site: 7,925)", round(sum(heat["loads_kw"]) / 293.07107), 7925)
    check("boiler size MMBtu/h (1.25 x peak, site 4.7)", round(1.25 * heat["peak_kw"] / 293.07107, 1), 4.7)

    print("\n4. BAU against REopt run ee53addc (nothing built)")
    with io.open(os.path.join(ds.LOAD_PROFILE_DIR, "total_electric_annual_kwh.json"), encoding="utf-8") as fh:
        annual_kwh = float(json.load(fh)[heat["city"]]["hospital"])
    elec = ds.build_electric_load("Hospital", annual_kwh, LAT, LON)
    inp = M.ScenarioInputs(
        loads_kw=elec["loads_kw"], tariff=build_tariff(ds.fetch_urdb_rate("5b44ffc75457a36716a907eb")),
        financial=M.FinancialInputs(), pv=M.PVInputs(enabled=False),
        storage=M.StorageInputs(enabled=False), fuel_tech=M.FuelTechInputs(enabled=False),
        heating_loads_kw=heat["loads_kw"], existing_boiler_fuel_cost_per_mmbtu=8.0,
        boiler_efficiency=0.8, boiler_fuel_escalation=0.0348)
    bau = M.business_as_usual(inp)
    check("annual electric kWh", round(annual_kwh), 8281865)
    check("BAU total life cycle cost $", round(bau["lifecycle_cost"]), 9525566)
    check("BAU non-outage fuel cost (lifecycle) $", round(bau["boiler_lifecycle_cost"]), 1060174)
    check("BAU heating system fuel cost, year 1 $", round(bau["year1_boiler_fuel_cost"]), 79254)
    check("BAU total utility electricity cost $", round(bau["lifecycle_cost"] - bau["boiler_lifecycle_cost"]),
          8465392)

    print("\n5. Every captured Battery and CHP label is in the panel code, in order")
    cap = json.load(io.open(CAPTURE, encoding="utf-8"))["panels"]
    full = io.open(APP, encoding="utf-8").read()
    bounds = {"battery": (full.index("def render_battery"), full.index("def _size_class_options")),
              "chp": (full.index("def render_chp"), len(full))}
    for panel in ("battery", "chp"):
        src = full[bounds[panel][0]:bounds[panel][1]]
        labels = [f["label"] for part in ("basic", "advanced") for f in cap[panel][part]
                  if "label" in f and "id" in f]
        pos, missing, order_ok = -1, [], True
        for lab in labels:
            i = src.find(lab.replace("* ", "")) if src.find(lab) < 0 else src.find(lab)
            if i < 0:
                missing.append(lab)
                continue
            if i < pos:
                order_ok = False
            pos = max(pos, i)
        check(f"{panel}: captured labels present", len(labels) - len(missing), len(labels))
        check(f"{panel}: in the site's order", order_ok, True)
        for m in missing:
            FAIL.append(f"{panel}: label not found -- {m}")

    print("\n" + "=" * 78)
    if FAIL:
        print(f"{len(FAIL)} FAILURE(S):")
        for f in FAIL:
            print("  -", f)
        sys.exit(1)
    print("all CHP + Battery field checks passed")


if __name__ == "__main__":
    main()
