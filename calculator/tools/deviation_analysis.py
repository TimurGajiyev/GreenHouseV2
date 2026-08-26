"""How far does the multi-unit machinery move our numbers, and when?

The question this answers is not "does it work" but "what does it cost us in
fidelity to REopt". It runs a controlled ladder on one scenario where the fuel
tech actually produces energy -- off-grid Golden CO, the OG1 setup -- because a
scenario with the generator sized to 0 kW cannot show any deviation at all.

  D0  one unit, REopt defaults                       reference
  D1  the same capacity split into 2 identical units  must be identical
  D2  the same capacity split into 3 identical units  must be identical
  D3  one unit, part-load curve switched on           deviation measured
  D4  one unit, minimum turndown switched on          deviation measured
  D5  three units, curve and turndown on              deviation measured
  D6  three DIFFERENT units, curve and turndown on    the real fleet case

D1 and D2 are the correctness test of the refactor: splitting one unit into N
identical ones changes nothing physical, so any difference is a modelling bug,
not a modelling choice.
"""

from __future__ import annotations

import copy
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import data_sources as ds
from reopt_core import model as M

LAT, LON = 39.74437, -105.15199
ANNUAL_KWH = 2_555_000.0
TOTAL_GEN_KW = 1750.0


def unit(size, *, half=None, turndown=0.0, name=""):
    return M.FuelTechInputs(
        enabled=True, kind="Generator", label="Generator", name=name,
        installed_cost_per_kw=880.0, fuel_cost_per_gallon=2.25,
        om_cost_per_kw=10.0, om_cost_per_kwh=0.0,
        electric_efficiency_full_load=0.322,
        electric_efficiency_half_load=half,
        min_turn_down_fraction=turndown,
        fuel_higher_heating_value_kwh_per_gal=40.7,
        min_kw=size, max_kw=size,
        replacement_year=10, replace_cost_per_kw=880.0,
        macrs_option_years=0, macrs_bonus_fraction=0.0, federal_itc_fraction=0.0,
    )


def build(units, pf, basis="reopt"):
    load = ds.build_electric_load("FlatLoad_8_7", ANNUAL_KWH, LAT, LON)
    return M.ScenarioInputs(
        loads_kw=load["loads_kw"], tariff=None, off_grid_flag=True,
        financial=M.FinancialInputs(
            analysis_years=10, offtaker_discount_rate_fraction=0.0624,
            offtaker_tax_rate_fraction=0.26, om_cost_escalation_rate_fraction=0.025,
            fuel_cost_escalation_rate_fraction=0.0197),
        pv=M.PVInputs(enabled=True, installed_cost_per_kw=2208.0, om_cost_per_kw=20.0,
                      macrs_option_years=5, macrs_bonus_fraction=1.0,
                      macrs_itc_reduction=0.5, federal_itc_fraction=0.30,
                      acres_per_kw=0.006, production_factor=pf),
        storage=M.StorageInputs(
            enabled=True, installed_cost_per_kwh=253.0, installed_cost_per_kw=968.0,
            installed_cost_constant=222_115.0, om_cost_fraction_of_installed_cost=0.025,
            macrs_option_years=5, macrs_bonus_fraction=1.0, macrs_itc_reduction=0.5,
            total_itc_fraction=0.30, soc_min_fraction=0.2, soc_init_fraction=1.0,
            can_grid_charge=False),
        fuel_tech=units[0], fuel_techs=units, fuel_intercept_basis=basis,
        land_acres=50.0, pv_location="ground",
        min_load_met_annual_fraction=0.999,
    )


GAL_PER_KWH = 1.0 / (0.322 * 40.7)


def run(tag, desc, units, pf, basis="reopt"):
    inp = build(units, pf, basis)
    t0 = time.time()
    r = M.solve(inp, time_limit=600)
    el = time.time() - t0
    sz, en = r["sizes"], r["energy"]
    nbin = sum(1 for u in units if u.enabled and
               (u.electric_efficiency_half_load not in (None, u.electric_efficiency_full_load)
                or u.min_turn_down_fraction > 0)) * 8760
    fuel = sum(u["fuel_units"] for u in sz["fueltech_units"])
    return {
        "tag": tag, "desc": desc, "units": len(units),
        "lcc": r["objective_lifecycle_cost"],
        "pv_kw": sz["pv_kw"], "bat_kwh": sz["battery_kwh"], "gen_kw": sz["fueltech_kw"],
        "gen_kwh": en["fueltech_kwh"], "fuel_gal": fuel,
        "seconds": el, "binaries": nbin, "rows": sz["fueltech_units"],
        "status": r["status"],
    }


def line(res, ref=None):
    d = lambda a, b: "  ref " if ref is None else (
        "  0.00%" if abs(b) < 1e-9 and abs(a) < 1e-9 else
        ("   n/a" if abs(b) < 1e-9 else f"{(a - b) / b:+7.3%}"))
    print(f"  {res['tag']:<4} {res['desc']:<38} "
          f"LCC ${res['lcc']:>12,.0f} {d(res['lcc'], ref['lcc'] if ref else 0)}   "
          f"fuel {res['fuel_gal']:>9,.0f} gal {d(res['fuel_gal'], ref['fuel_gal'] if ref else 0)}   "
          f"{res['binaries']:>6,} bin  {res['seconds']:>6.1f} s  {res['status']}")


def main():
    pf, _ = ds.call_pvwatts_api(LAT, LON, tilt=20, azimuth=180, array_type=0,
                                module_type=0, losses=14)
    print("Off-grid Golden CO, FlatLoad_8_7 @ 2,555,000 kWh, 10 yr, generator "
          f"fleet fixed at {TOTAL_GEN_KW:,.0f} kW total\n")

    H = TOTAL_GEN_KW
    cases = [
        ("D0", "1 unit, REopt defaults", [unit(H, name="G1")]),
        ("D1", "2 identical units, defaults",
         [unit(H / 2, name="G1"), unit(H / 2, name="G2")]),
        ("D2", "3 identical units, defaults",
         [unit(H / 3, name=f"G{i+1}") for i in range(3)]),
        ("D3", "1 unit, part-load curve (half 28%)", [unit(H, half=0.28, name="G1")]),
        ("D4", "1 unit, turndown 30%", [unit(H, turndown=0.30, name="G1")]),
        ("D5", "3 units, curve + turndown",
         [unit(H / 3, half=0.28, turndown=0.30, name=f"G{i+1}") for i in range(3)]),
        ("D6", "3 different units, curve + turndown",
         [unit(800.0, half=0.29, turndown=0.30, name="Jenbacher"),
          unit(600.0, half=0.28, turndown=0.30, name="TEDOM"),
          unit(350.0, half=0.26, turndown=0.30, name="Backup")]),
    ]

    print("=" * 128)
    ref = None
    out = []
    for tag, desc, units in cases:
        res = run(tag, desc, units, pf)
        if ref is None:
            ref = res
        line(res, None if res is ref else ref)
        out.append(res)

    print("=" * 128)
    print("\nCorrectness gate -- splitting one unit into N identical units must change nothing:")
    for r in out[1:3]:
        dl = abs(r["lcc"] - ref["lcc"])
        df = abs(r["fuel_gal"] - ref["fuel_gal"])
        ok = dl < 1.0 and df < 1.0
        print(f"  {r['tag']}  |dLCC| = ${dl:.6f}   |dfuel| = {df:.6f} gal   "
              f"-> {'IDENTICAL' if ok else 'DIFFERS -- investigate'}")

    print("\nPer-unit dispatch, D6 (the real fleet case):")
    for u in out[-1]["rows"]:
        st = "" if u["starts"] is None else f"  starts {u['starts']:>4}"
        print(f"  {u['name']:<12} {u['size_kw']:>7,.0f} kW  "
              f"{u['energy_kwh']:>11,.0f} kWh  CF {u['capacity_factor']:>6.1%}  "
              f"run {u['running_hours']:>5} h  fuel {u['fuel_units']:>9,.0f} gal{st}")


if __name__ == "__main__":
    main()
