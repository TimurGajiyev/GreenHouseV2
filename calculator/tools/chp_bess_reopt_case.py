"""CHP + Battery exactly as the REopt web tool poses it -- our side of the check.

The site: Golden CO (39.74437, -105.15199), grid-tied, cost savings.
Loads:    Hospital, CRB default electric energy; Hospital heating, CRB default
          fuel; existing boiler 80% (hot water).
Fuel:     $8.00/MMBtu for both the boiler and CHP.
Tariff:   the URDB rate the other Golden validators use.
CHP:      every value the tool derives from the heating load -- prime mover,
          size class, size-cost pairs, O&M, efficiencies, minimum non-zero size,
          turndown, maintenance schedule -- via reopt_core.chp_defaults, which
          reproduces the tool's placeholders exactly.
Battery:  the tool's defaults.

    python tools/chp_bess_reopt_case.py            solve and print
    python tools/chp_bess_reopt_case.py --json F   also dump the result summary
    python tools/chp_bess_reopt_case.py --case=2 --jl [--time=3600]
                                                   also solve it with the local REopt.jl
                                                   and print both side by side
"""

from __future__ import annotations

import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import chp_defaults as C
from reopt_core import data_sources as ds
from reopt_core import model as M
from reopt_core.tariff import build_tariff

LAT, LON = 39.74437, -105.15199
URDB = "5b44ffc75457a36716a907eb"
BLDG = "Hospital"


def build(*, annual_kwh: float | None = None, fuel_cost: float = 8.0, chp_fuel_cost: float | None = None,
          battery: dict | None = None) -> tuple[M.ScenarioInputs, dict]:
    city, _ = ds.find_ashrae_zone_city(LAT, LON)
    if annual_kwh is None:
        # CRB default annual kWh for the building (what a blank field sends)
        with io.open(os.path.join(ds.LOAD_PROFILE_DIR, "total_electric_annual_kwh.json"),
                     encoding="utf-8") as fh:
            annual_kwh = float(json.load(fh)[city][BLDG.lower()])  # table keys are lower-case
    elec = ds.build_electric_load(BLDG, annual_kwh, LAT, LON)
    heat = ds.build_heating_load(BLDG, LAT, LON, boiler_efficiency=0.8)
    d = C.get_chp_defaults_prime_mover_size_class(
        avg_boiler_fuel_load_mmbtu_per_hour=heat["avg_fuel_mmbtu_per_hour"],
        boiler_efficiency=0.8)
    di = d["default_inputs"]
    unav = C.generate_year_profile_hourly(2017, di["unavailability_periods"])
    chp = M.FuelTechInputs(
        enabled=True, kind="CHP", label="CHP", name="CHP",
        installed_cost_per_kw=di["installed_cost_per_kw"][0],
        tech_sizes_for_cost_curve=list(di["tech_sizes_for_cost_curve"]),
        installed_cost_curve_per_kw=list(di["installed_cost_per_kw"]),
        om_cost_per_kw=0.0, om_cost_per_kwh=di["om_cost_per_kwh"],
        electric_efficiency_full_load=di["electric_efficiency_full_load"],
        electric_efficiency_half_load=None,
        thermal_efficiency_full_load=di["thermal_efficiency_full_load"],
        thermal_efficiency_half_load=None,
        min_turn_down_fraction=di["min_turn_down_fraction"],
        min_allowable_kw=di["min_allowable_kw"],
        min_kw=0.0, max_kw=d["chp_max_size_kw"],
        fuel_cost_per_mmbtu=(fuel_cost if chp_fuel_cost is None else chp_fuel_cost),
        production_factor_series=[1.0 - x for x in unav],
        macrs_option_years=5, macrs_bonus_fraction=1.0, macrs_itc_reduction=0.5,
        federal_itc_fraction=0.0,
        cooling_thermal_factor=di["cooling_thermal_factor"],
    )
    bat = M.StorageInputs(enabled=True, name="Battery", **(battery or {}))
    fin = M.FinancialInputs(chp_fuel_cost_escalation_rate_fraction=0.0348)
    inp = M.ScenarioInputs(
        loads_kw=elec["loads_kw"], tariff=build_tariff(ds.fetch_urdb_rate(URDB)), financial=fin,
        pv=M.PVInputs(enabled=False), storage=bat, fuel_tech=chp,
        compensation_type="no_compensation",
        heating_loads_kw=heat["loads_kw"],
        existing_boiler_fuel_cost_per_mmbtu=fuel_cost, boiler_efficiency=0.8,
        boiler_fuel_escalation=0.0348,
    )
    meta = {"city": city, "annual_kwh": annual_kwh, "heating_fuel_mmbtu": heat["annual_fuel_mmbtu"],
            "size_class": d["size_class"], "prime_mover": d["prime_mover"],
            "heuristic_kw": d["chp_elec_size_heuristic_kw"], "max_kw": d["chp_max_size_kw"],
            "maintenance_hours": int(sum(unav))}
    return inp, meta


CASES = {
    # REopt ee53addc-199c-4176-9dfe-ff3c205e70f9: nothing built
    "1": dict(),
    # REopt d16fe2f4-4713-46b2-a4cf-828b0bdb3755: cheap CHP gas, cheaper battery
    "2": dict(chp_fuel_cost=3.0, battery=dict(installed_cost_per_kwh=150.0,
                                              installed_cost_per_kw=400.0,
                                              installed_cost_constant=0.0)),
}


def reopt_scenario(*, fuel_cost: float = 8.0, chp_fuel_cost: float | None = None,
                   battery: dict | None = None, annual_kwh: float | None = None) -> dict:
    """The same case as REopt.jl input: only what the site's form sends, the rest
    left to REopt.jl's defaults (which the web tool shares -- CHP ITC 0%, MACRS 5 yr
    100% bonus, escalations 1.66% / 3.48%, discount 6.24%, tax 26%)."""
    d = {
        "Site": {"latitude": LAT, "longitude": LON},
        "ElectricLoad": {"doe_reference_name": BLDG},
        "ElectricTariff": {"urdb_label": URDB},
        "SpaceHeatingLoad": {"doe_reference_name": BLDG},
        "DomesticHotWaterLoad": {"doe_reference_name": BLDG},
        "ExistingBoiler": {"fuel_cost_per_mmbtu": fuel_cost, "efficiency": 0.8},
        "CHP": {"fuel_cost_per_mmbtu": fuel_cost if chp_fuel_cost is None else chp_fuel_cost},
        "ElectricStorage": dict(battery or {}),
    }
    if annual_kwh is not None:
        d["ElectricLoad"]["annual_kwh"] = annual_kwh
    return d


def compare_jl(res: dict, bau: dict, jl: dict) -> None:
    chp, st, fin = jl.get("CHP", {}), jl.get("ElectricStorage", {}), jl["Financial"]
    boiler = jl.get("ExistingBoiler", {})
    pf = res.get("proforma") or {}
    u = res["sizes"]["fueltech_units"][0]
    rows = [
        ("CHP size kW", chp.get("size_kw", 0.0), res["sizes"]["fueltech_kw"]),
        ("CHP electric kWh", chp.get("annual_electric_production_kwh", 0.0), u["energy_kwh"]),
        ("CHP fuel MMBtu", chp.get("annual_fuel_consumption_mmbtu", 0.0), u["fuel_units"]),
        ("CHP heat to load MMBtu", chp.get("thermal_to_load_series_mmbtu_per_hour") and
         sum(chp["thermal_to_load_series_mmbtu_per_hour"]) or 0.0, res["thermal"]["chp_thermal_mmbtu"]),
        ("boiler fuel MMBtu", boiler.get("annual_fuel_consumption_mmbtu", 0.0), res["thermal"]["boiler_fuel_mmbtu"]),
        ("battery kW", st.get("size_kw", 0.0), res["sizes"]["battery_kw"]),
        ("battery kWh", st.get("size_kwh", 0.0), res["sizes"]["battery_kwh"]),
        ("initial capital $", fin.get("initial_capital_costs", 0.0), res["capital"]["upfront_before_incentives"]),
        ("LCC optimal $", fin["lcc"], res["objective_lifecycle_cost"]),
        ("LCC BAU $", fin.get("lcc_bau", float("nan")), bau.get("lifecycle_cost", float("nan"))),
        ("NPV $", fin.get("npv", float("nan")), bau.get("lifecycle_cost", 0) - res["objective_lifecycle_cost"]),
        ("simple payback yrs", fin.get("simple_payback_years", float("nan")), pf.get("simple_payback_years", float("nan"))),
        ("IRR", fin.get("internal_rate_of_return", float("nan")), pf.get("internal_rate_of_return", float("nan"))),
    ]
    r = jl.get("_runner", {})
    print(f"\nREopt.jl {r.get('reopt_version')} (local, HiGHS gap {r.get('mip_rel_gap')}, "
          f"{r.get('seconds')} s, status {jl.get('status')})")
    print(f"  {'':<26}{'REopt.jl':>18}{'this calculator':>18}{'diff':>14}")
    for lab, a, b in rows:
        rel = f"{(b - a) / a:+.2%}" if a else ""
        print(f"  {lab:<26}{a:>18,.2f}{b:>18,.2f}{rel:>14}")


def main():
    case = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--case=")), "1")
    inp, meta = build(**CASES[case])
    meta["case"] = case
    print("inputs:", json.dumps(meta, default=float))
    t0 = time.time()
    res = M.solve(inp, time_limit=900)
    bau = M.business_as_usual(inp)
    u = res["sizes"]["fueltech_units"][0]
    th = res["thermal"]
    print(f"status {res['status']}  {time.time() - t0:.0f}s  gap {(res.get('solver') or {}).get('mip_gap')}")
    print(f"CHP {u['size_kw']:,.1f} kW (segment {u['segment']}), {u['energy_kwh']:,.0f} kWh, "
          f"{u['running_hours']} h, unavailable {u['unavailable_hours']} h, fuel {u['fuel_units']:,.0f} MMBtu")
    print(f"battery {res['sizes']['battery_kw']:,.1f} kW / {res['sizes']['battery_kwh']:,.1f} kWh")
    print(f"heat: load {th['thermal_load_mmbtu']:,.0f} MMBtu, CHP to load {th['chp_thermal_mmbtu']:,.0f}, "
          f"boiler {th['boiler_thermal_mmbtu']:,.0f} (boiler fuel {th['boiler_fuel_mmbtu']:,.0f})")
    print(f"LCC optimal ${res['objective_lifecycle_cost']:,.0f}   BAU ${bau.get('lifecycle_cost', 0):,.0f}")
    if "--jl" in sys.argv:
        from tools.reopt_jl import run_reopt_jl
        tl = float(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--time=")), 3600))
        jl = run_reopt_jl(reopt_scenario(**CASES[case]), bau=True, gap=0.01, time_limit=tl)
        compare_jl(res, bau, jl)
    if len(sys.argv) > 2 and sys.argv[1] == "--json":
        io.open(sys.argv[2], "w", encoding="utf-8").write(json.dumps({
            "meta": meta, "sizes": res["sizes"], "thermal": th, "capital": res["capital"],
            "lcc": res["objective_lifecycle_cost"], "bau_lcc": bau.get("lifecycle_cost")},
            default=float, indent=1))


if __name__ == "__main__":
    main()
