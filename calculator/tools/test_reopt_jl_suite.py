"""REopt.jl's own test suite, run against this calculator.

The web tool can only be checked one submission at a time, and it rate-limits
automated use. REopt.jl ships its own tests instead: scenario files in
REopt/test/scenarios and assertions in REopt/test/runtests.jl, with the
tolerance each assertion allows. This script poses every CHP and Battery test
that stays inside this calculator's technologies (no absorption chiller, no
cooling, no outages) and checks our result with REopt's own expected value and
tolerance.

  heuristic   runtests.jl:217   CHP Sizing Heuristic, cases 1-2
  defaults    runtests.jl:2315  Heating inputs + CHP defaults (size class from load)
  pv_storage  runtests.jl:394   Solar and Storage            LCC to 1e-5
  duration    runtests.jl:4124  Storage Duration
  om_frac     runtests.jl:4523  Battery O&M Cost Fraction
  chp_sizing  runtests.jl:1146  CHP Sizing
  chp_curve   runtests.jl:1172  CHP Cost Curve and Min Allowable Size

    python tools/test_reopt_jl_suite.py            all
    python tools/test_reopt_jl_suite.py pv_storage chp_curve     a subset
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
from reopt_core.finance import npv
from reopt_core.tariff import build_tariff, flat_tariff

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCEN = os.path.join(ROOT, "REopt", "test", "scenarios")
FAIL: list[str] = []
RESULTS: dict = {}


def scenario(name: str) -> dict:
    with io.open(os.path.join(SCEN, name), encoding="utf-8") as fh:
        return json.load(fh)


def approx(name, got, want, *, atol=None, rtol=None):
    tol = atol if atol is not None else abs(want) * rtol
    ok = abs(got - want) <= tol + 1e-12
    tag = f"atol {atol}" if atol is not None else f"rtol {rtol}"
    print(f"  {'OK' if ok else 'XX'}  {name:<56} {got:>16,.4f}   REopt {want:>16,.4f}   ({tag})")
    if not ok:
        FAIL.append(f"{name}: {got} vs {want} ({tag})")
    return ok


# ---------------------------------------------------------------- helpers
def crb_annual_kwh(building: str, city: str) -> float:
    with io.open(os.path.join(ds.LOAD_PROFILE_DIR, "total_electric_annual_kwh.json"), encoding="utf-8") as fh:
        return float(json.load(fh)[city][building.lower()])


def heating_kw(building: str, lat: float, lon: float, *, sh_mmbtu=None, dhw_mmbtu=None,
               sh_monthly=None, dhw_monthly=None, eff=0.8) -> list[float]:
    """SpaceHeatingLoad + DomesticHotWaterLoad, each built on its own (built_in_load)."""
    city, _ = ds.find_ashrae_zone_city(lat, lon)
    months = ds._month_hours_2017()
    total = [0.0] * 8760
    defaults = ds.heating_load_mmbtu(building, city)
    for kind, annual, monthly in (("space_heating", sh_mmbtu, sh_monthly),
                                  ("domestic_hot_water", dhw_mmbtu, dhw_monthly)):
        norm = ds.load_crb_profile(building, city, kind=kind)
        scale, energy = [1.0] * 12, (annual if annual is not None else defaults[kind])
        if monthly:
            energy = 1.0
            for mo, hrs in enumerate(months):
                tot = sum(norm[h] for h in hrs)
                scale[mo] = 0.0 if tot == 0 else monthly[mo] / tot
        for mo, hrs in enumerate(months):
            for h in hrs:
                total[h] += norm[h] * energy * scale[mo] * eff * 293.07107
    return total


def financial(d: dict) -> M.FinancialInputs:
    f = d.get("Financial", {})
    kw = dict(analysis_years=int(f.get("analysis_years", 25)),
              elec_cost_escalation_rate_fraction=f.get("elec_cost_escalation_rate_fraction", 0.0166),
              om_cost_escalation_rate_fraction=f.get("om_cost_escalation_rate_fraction", 0.025),
              offtaker_discount_rate_fraction=f.get("offtaker_discount_rate_fraction", 0.0624),
              offtaker_tax_rate_fraction=f.get("offtaker_tax_rate_fraction", 0.26))
    if "owner_discount_rate_fraction" in f:
        kw["owner_discount_rate_fraction"] = f["owner_discount_rate_fraction"]
    if "owner_tax_rate_fraction" in f:
        kw["owner_tax_rate_fraction"] = f["owner_tax_rate_fraction"]
    if "chp_fuel_cost_escalation_rate_fraction" in f:
        kw["chp_fuel_cost_escalation_rate_fraction"] = f["chp_fuel_cost_escalation_rate_fraction"]
    return M.FinancialInputs(**kw)


def pv_inputs(d: dict, lat: float, lon: float) -> M.PVInputs:
    p = d.get("PV")
    if not p or p.get("max_kw", 1) == 0:
        return M.PVInputs(enabled=False)
    arr = int(p.get("array_type", 1))
    tilt = p.get("tilt", 20 if arr in (0, 1) else 0)
    pf, _ = ds.call_pvwatts_api(lat, lon, tilt=tilt, azimuth=p.get("azimuth", 180 if lat >= 0 else 0),
                                array_type=arr, module_type=int(p.get("module_type", 0)),
                                losses=100 * p.get("losses", 0.14))
    return M.PVInputs(
        enabled=True, production_factor=pf,
        installed_cost_per_kw=p.get("installed_cost_per_kw", 1790.0),
        om_cost_per_kw=p.get("om_cost_per_kw", 18.0),
        min_kw=p.get("min_kw", 0.0), max_kw=p.get("max_kw", 1.0e9),
        degradation_fraction=p.get("degradation_fraction", 0.005),
        macrs_option_years=int(p.get("macrs_option_years", 5)),
        macrs_bonus_fraction=p.get("macrs_bonus_fraction", 0.6),
        macrs_itc_reduction=p.get("macrs_itc_reduction", 0.5),
        federal_itc_fraction=p.get("federal_itc_fraction", 0.3),
        federal_rebate_per_kw=p.get("federal_rebate_per_kw", 0.0),
        operating_reserve_required_fraction=0.0)


def storage_inputs(d: dict) -> M.StorageInputs:
    e = d.get("ElectricStorage")
    if e is None:
        return M.StorageInputs(enabled=False)
    keys = ("installed_cost_per_kw", "installed_cost_per_kwh", "installed_cost_constant",
            "replace_cost_per_kw", "replace_cost_per_kwh", "replace_cost_constant",
            "inverter_replacement_year", "battery_replacement_year", "cost_constant_replacement_year",
            "om_cost_fraction_of_installed_cost", "min_kw", "max_kw", "min_kwh", "max_kwh",
            "soc_min_fraction", "soc_init_fraction", "min_duration_hours", "max_duration_hours",
            "macrs_option_years", "macrs_bonus_fraction", "macrs_itc_reduction",
            "total_itc_fraction", "total_rebate_per_kw", "total_rebate_per_kwh", "can_grid_charge")
    kw = {k: e[k] for k in keys if k in e}
    return M.StorageInputs(enabled=kw.get("max_kw", 1) > 0 and kw.get("max_kwh", 1) > 0, **kw)


# ============================================================ the cases
def case_heuristic():
    print("\nCHP Sizing Heuristic (runtests.jl:217)")
    r = C.get_chp_defaults_prime_mover_size_class(
        hot_water_or_steam="hot_water", prime_mover="recip_engine", size_class=0,
        boiler_efficiency=0.8, avg_electric_load_kw=100.0, max_electric_load_kw=200.0,
        is_electric_only=True)
    approx("case 1 electric only: heuristic kW", r["chp_elec_size_heuristic_kw"], 100.0, atol=1e-3)
    approx("case 1 electric only: max kW", r["chp_max_size_kw"], 200.0, atol=1e-3)
    r = C.get_chp_defaults_prime_mover_size_class(
        hot_water_or_steam="hot_water", avg_boiler_fuel_load_mmbtu_per_hour=100.0 / C.KWH_PER_MMBTU,
        prime_mover="recip_engine", size_class=0, boiler_efficiency=0.8,
        avg_electric_load_kw=10.0, max_electric_load_kw=20.0, is_electric_only=False)
    approx("case 2 heating only: heuristic kW", r["chp_elec_size_heuristic_kw"], 65.0, atol=0.1)
    approx("case 2 heating only: max kW", r["chp_max_size_kw"], 130.0, atol=0.2)


def case_defaults():
    print("\nHeating inputs + CHP defaults (runtests.jl:2315, heating_cooling_load_inputs.json)")
    d = scenario("heating_cooling_load_inputs.json")
    lat, lon = d["Site"]["latitude"], d["Site"]["longitude"]
    sh, dhw = d["SpaceHeatingLoad"]["annual_mmbtu"], d["DomesticHotWaterLoad"]["annual_mmbtu"]
    b = d["SpaceHeatingLoad"]["doe_reference_name"]
    for eff in (0.8, 0.72):
        kw = heating_kw(b, lat, lon, sh_mmbtu=sh, dhw_mmbtu=dhw, eff=eff)
        approx(f"thermal MMBtu at boiler efficiency {eff}", round(sum(kw) / 293.07107), (sh + dhw) * eff, atol=1.0)
    # runtests.jl:2333 sets ExistingBoiler.efficiency = 0.72 before the CHP-default
    # checks and never resets it, so every check below runs at 0.72
    eff = 0.72
    kw = heating_kw(b, lat, lon, sh_mmbtu=sh, dhw_mmbtu=dhw, eff=eff)
    avg = sum(kw) / eff / 293.07107 / 8760
    r = C.get_chp_defaults_prime_mover_size_class(avg_boiler_fuel_load_mmbtu_per_hour=avg,
                                                  prime_mover="recip_engine", boiler_efficiency=eff)
    approx("CHP default min_allowable_kw (size class 2)", r["default_inputs"]["min_allowable_kw"], 50.0, atol=0.01)
    approx("CHP default om_cost_per_kwh", r["default_inputs"]["om_cost_per_kwh"], 0.027, atol=0.0001)
    kw = heating_kw(b, lat, lon, sh_monthly=[1000.0] * 12, dhw_monthly=[1000.0] * 12, eff=eff)
    avg = sum(kw) / eff / 293.07107 / 8760
    r = C.get_chp_defaults_prime_mover_size_class(avg_boiler_fuel_load_mmbtu_per_hour=avg,
                                                  prime_mover="recip_engine", boiler_efficiency=eff)
    approx("monthly 1000 x 12 x 2: min_allowable_kw (class 3)", r["default_inputs"]["min_allowable_kw"], 125.0, atol=0.1)
    approx("monthly 1000 x 12 x 2: om_cost_per_kwh", r["default_inputs"]["om_cost_per_kwh"], 0.023, atol=0.0001)
    r = C.get_chp_defaults_prime_mover_size_class(avg_boiler_fuel_load_mmbtu_per_hour=avg,
                                                  prime_mover="combustion_turbine", size_class=1,
                                                  max_kw=2500.0, boiler_efficiency=eff)
    approx("combustion turbine class 1: min_allowable_kw", r["default_inputs"]["min_allowable_kw"], 2000.0, atol=0.1)
    approx("combustion turbine class 1: om_cost_per_kwh", r["default_inputs"]["om_cost_per_kwh"], 0.015, atol=0.0001)
    approx("heating fuel MMBtu from monthly input", round(sum(kw) / eff / 293.07107), 24000.0, atol=1.0)


def _pv_storage_base(d):
    lat, lon = d["Site"]["latitude"], d["Site"]["longitude"]
    city, _ = ds.find_ashrae_zone_city(lat, lon)
    el = d["ElectricLoad"]
    load = ds.build_electric_load(el["doe_reference_name"], float(el.get("annual_kwh") or crb_annual_kwh(
        el["doe_reference_name"], city)), lat, lon)
    tar = d["ElectricTariff"]
    tariff = (build_tariff(ds.fetch_urdb_rate(tar["urdb_label"])) if "urdb_label" in tar
              else flat_tariff(tar["blended_annual_energy_rate"], tar.get("blended_annual_demand_rate", 0.0)))
    return M.ScenarioInputs(
        loads_kw=load["loads_kw"], tariff=tariff, financial=financial(d),
        pv=pv_inputs(d, lat, lon), storage=storage_inputs(d),
        fuel_tech=M.FuelTechInputs(enabled=False),
        land_acres=d["Site"].get("land_acres"), roof_squarefeet=d["Site"].get("roof_squarefeet"),
        pv_location=(d.get("PV") or {}).get("location", "both"),
        compensation_type="no_compensation"), city


def case_pv_storage():
    print("\nSolar and Storage (runtests.jl:394, pv_storage.json)")
    d = scenario("pv_storage.json")
    inp, city = _pv_storage_base(d)
    t0 = time.time()
    r = M.solve(inp, time_limit=900)
    print(f"  (CRB city {city}, {time.time() - t0:.0f}s, {r['status']})")
    approx("PV size_kw", r["sizes"]["pv_kw"], 216.6667, atol=0.01)
    approx("Financial lcc", r["objective_lifecycle_cost"], 1.2391786e7, rtol=1e-5)
    approx("ElectricStorage size_kw", r["sizes"]["battery_kw"], 49.0, atol=0.1)
    approx("ElectricStorage size_kwh", r["sizes"]["battery_kwh"], 83.3, atol=0.1)
    RESULTS["pv_storage"] = {"pv": r["sizes"]["pv_kw"], "lcc": r["objective_lifecycle_cost"],
                             "kw": r["sizes"]["battery_kw"], "kwh": r["sizes"]["battery_kwh"]}


def case_duration():
    print("\nStorage Duration (runtests.jl:4124)")
    d = scenario("pv_storage.json")
    d["ElectricStorage"]["min_duration_hours"] = 8
    d["ElectricStorage"]["max_duration_hours"] = 8
    inp, _ = _pv_storage_base(d)
    r = M.solve(inp, time_limit=900)
    approx("size_kw x 8 - size_kwh", r["sizes"]["battery_kw"] * 8 - r["sizes"]["battery_kwh"], 0.0, atol=0.1)


def case_om_fraction():
    print("\nBattery O&M Cost Fraction (runtests.jl:4523)")
    d = scenario("battery_om_cost_fraction.json")
    d["PV"]["max_kw"] = 0.0
    d["ElectricStorage"]["min_kw"] = 200.0
    d["ElectricStorage"]["min_kwh"] = 800.0
    inp, _ = _pv_storage_base(d)
    r = M.solve(inp, time_limit=900, mip_gap=0.01)
    cap = r["capital"]["upfront_before_incentives"]
    om = r["om"]["year1_storage"]
    approx("year-one O&M / initial capital cost", om / cap, 0.025, atol=0.0005)


def _chp_sizing_inputs(d, *, chp: dict, pv=None):
    lat, lon = d["Site"]["latitude"], d["Site"]["longitude"]
    city, _ = ds.find_ashrae_zone_city(lat, lon)
    bld = d["ElectricLoad"]["doe_reference_name"]
    load = ds.build_electric_load(bld, crb_annual_kwh(bld, city), lat, lon)
    heat = heating_kw(d["SpaceHeatingLoad"]["doe_reference_name"], lat, lon, eff=0.8)
    avg = sum(heat) / 0.8 / 293.07107 / 8760
    dd = C.get_chp_defaults_prime_mover_size_class(
        avg_boiler_fuel_load_mmbtu_per_hour=avg, prime_mover=chp.get("prime_mover"),
        size_class=chp.get("size_class"), boiler_efficiency=0.8,
        max_kw=chp.get("max_kw", float("nan")))
    di = dd["default_inputs"]
    # chp.jl:200-285: any input the scenario leaves out comes from the class defaults
    cost = chp.get("installed_cost_per_kw", di["installed_cost_per_kw"])
    sizes = chp.get("tech_sizes_for_cost_curve", di["tech_sizes_for_cost_curve"]
                    if "installed_cost_per_kw" not in chp else [])
    pairs = isinstance(cost, list) and len(cost) > 1
    periods = chp.get("unavailability_periods", di["unavailability_periods"])
    unav = C.generate_year_profile_hourly(2017, periods)
    ft = M.FuelTechInputs(
        enabled=True, kind="CHP", label="CHP", name="CHP",
        installed_cost_per_kw=(cost[0] if isinstance(cost, list) else cost),
        tech_sizes_for_cost_curve=(list(sizes) if pairs else []),
        installed_cost_curve_per_kw=(list(cost) if pairs else []),
        om_cost_per_kw=chp.get("om_cost_per_kw", 0.0),
        om_cost_per_kwh=chp.get("om_cost_per_kwh", di["om_cost_per_kwh"]),
        electric_efficiency_full_load=chp.get("electric_efficiency_full_load", di["electric_efficiency_full_load"]),
        electric_efficiency_half_load=chp.get("electric_efficiency_half_load"),
        thermal_efficiency_full_load=chp.get("thermal_efficiency_full_load", di["thermal_efficiency_full_load"]),
        thermal_efficiency_half_load=chp.get("thermal_efficiency_half_load"),
        min_turn_down_fraction=chp.get("min_turn_down_fraction", di["min_turn_down_fraction"]),
        min_allowable_kw=chp.get("min_allowable_kw", di["min_allowable_kw"]),
        min_kw=chp.get("min_kw", 0.0), max_kw=chp.get("max_kw", dd["chp_max_size_kw"]),
        fuel_cost_per_mmbtu=chp["fuel_cost_per_mmbtu"],
        production_factor_series=[1.0 - x for x in unav],
        macrs_option_years=int(chp.get("macrs_option_years", 5)),
        macrs_bonus_fraction=chp.get("macrs_bonus_fraction", 1.0),
        macrs_itc_reduction=chp.get("macrs_itc_reduction", 0.5),
        federal_itc_fraction=chp.get("federal_itc_fraction", 0.0))
    tar = d["ElectricTariff"]
    return M.ScenarioInputs(
        loads_kw=load["loads_kw"],
        tariff=flat_tariff(tar["blended_annual_energy_rate"], tar.get("blended_annual_demand_rate", 0.0)),
        financial=financial(d), pv=(pv or M.PVInputs(enabled=False)),
        storage=M.StorageInputs(enabled=False), fuel_tech=ft,
        compensation_type="no_compensation", pv_location="both",
        heating_loads_kw=heat, boiler_efficiency=0.8,
        existing_boiler_fuel_cost_per_mmbtu=d["ExistingBoiler"]["fuel_cost_per_mmbtu"],
        boiler_fuel_escalation=d["Financial"].get("existing_boiler_fuel_cost_escalation_rate_fraction", 0.0348))


def case_chp_sizing():
    print("\nCHP Sizing (runtests.jl:1146, chp_sizing.json, mip_rel_gap 0.01)")
    d = scenario("chp_sizing.json")
    inp = _chp_sizing_inputs(d, chp=d["CHP"])
    t0 = time.time()
    r = M.solve(inp, time_limit=1800, mip_gap=0.01)
    print(f"  ({time.time() - t0:.0f}s, {r['status']}, gap {(r.get('solver') or {}).get('mip_gap')})")
    approx("CHP size_kw (rounded)", round(r["sizes"]["fueltech_kw"]), 263.0, atol=50.0)
    approx("Financial lcc (rounded)", round(r["objective_lifecycle_cost"]), 1.11e7, rtol=0.05)
    RESULTS["chp_sizing"] = {"chp_kw": r["sizes"]["fueltech_kw"], "lcc": r["objective_lifecycle_cost"]}


def case_chp_curve():
    print("\nCHP Cost Curve and Min Allowable Size (runtests.jl:1172)")
    d = scenario("chp_sizing.json")
    chp = {"prime_mover": "recip_engine", "size_class": 1, "fuel_cost_per_mmbtu": 8.0, "min_kw": 0,
           "min_allowable_kw": 555.5, "max_kw": 555.51,
           "installed_cost_per_kw": [2300.0, 1800.0, 1500.0],
           "tech_sizes_for_cost_curve": [100.0, 300.0, 1140.0],
           "federal_itc_fraction": 0.1, "macrs_option_years": 0, "macrs_bonus_fraction": 0.0,
           "macrs_itc_reduction": 0.0}
    lat, lon = d["Site"]["latitude"], d["Site"]["longitude"]
    pv = pv_inputs({"PV": {"min_kw": 1500, "max_kw": 1500, "installed_cost_per_kw": 1600,
                           "federal_itc_fraction": 0.26, "macrs_option_years": 0,
                           "macrs_bonus_fraction": 0.0, "macrs_itc_reduction": 0.0}}, lat, lon)
    inp = _chp_sizing_inputs(d, chp=chp, pv=pv)
    t0 = time.time()
    r = M.solve(inp, time_limit=1800, mip_gap=0.01)
    print(f"  ({time.time() - t0:.0f}s, {r['status']})")
    x, y = chp["tech_sizes_for_cost_curve"], chp["installed_cost_per_kw"]
    slope = (x[2] * y[2] - x[1] * y[1]) / (x[2] - x[1])
    chp_capex = x[1] * y[1] + (chp["min_allowable_kw"] - x[1]) * slope
    disc = d["Financial"]["offtaker_discount_rate_fraction"]
    chp_life = chp_capex - npv(disc, [0, chp_capex * chp["federal_itc_fraction"]])
    pv_capex = 1500 * 1600
    pv_life = pv_capex - npv(disc, [0, pv_capex * 0.26])
    approx("initial_capital_costs", r["capital"]["upfront_before_incentives"], chp_capex + pv_capex,
           atol=0.0001 * (chp_capex + pv_capex))
    approx("initial_capital_costs_after_incentives", r["capital"]["lifecycle_capex"], chp_life + pv_life,
           atol=0.0001 * (chp_life + pv_life))
    approx("CHP size_kw = min_allowable_kw", r["sizes"]["fueltech_kw"], 555.5, atol=0.1)


def case_chp_payback():
    print("\nCHP Proforma Metrics (runtests.jl:1501, chp_payback.json, mip_rel_gap 0.01)")
    d = scenario("chp_payback.json")
    chp = d["CHP"]
    # FlatLoad scaled to monthly totals: every hour of a month carries total / hours
    months = ds._month_hours_2017()
    load = [0.0] * 8760
    for mo, hrs in enumerate(months):
        for h in hrs:
            load[h] = d["ElectricLoad"]["monthly_totals_kwh"][mo] / len(hrs)
    eff = 0.8                               # ExistingBoiler default, hot_water
    fuel = d["SpaceHeatingLoad"]["annual_mmbtu"] + d["DomesticHotWaterLoad"]["annual_mmbtu"]
    heat = [fuel / 8760 * eff * 293.07107] * 8760
    dd = C.get_chp_defaults_prime_mover_size_class(
        avg_boiler_fuel_load_mmbtu_per_hour=fuel / 8760, prime_mover=chp["prime_mover"],
        size_class=chp["size_class"], boiler_efficiency=eff, max_kw=chp["max_kw"])
    di = dd["default_inputs"]
    unav = C.generate_year_profile_hourly(2017, di["unavailability_periods"])
    ft = M.FuelTechInputs(
        enabled=True, kind="CHP", label="CHP", name="CHP",
        installed_cost_per_kw=chp["installed_cost_per_kw"],
        om_cost_per_kw=0.0, om_cost_per_kwh=chp["om_cost_per_kwh"],
        electric_efficiency_full_load=di["electric_efficiency_full_load"],
        thermal_efficiency_full_load=di["thermal_efficiency_full_load"],
        min_turn_down_fraction=di["min_turn_down_fraction"],
        min_allowable_kw=chp["min_allowable_kw"], min_kw=chp["min_kw"], max_kw=chp["max_kw"],
        fuel_cost_per_mmbtu=chp["fuel_cost_per_mmbtu"],
        production_factor_series=[1.0 - x for x in unav],
        federal_itc_fraction=chp["federal_itc_fraction"],
        macrs_option_years=int(chp["macrs_option_years"]),
        macrs_bonus_fraction=chp["macrs_bonus_fraction"],
        macrs_itc_reduction=chp["macrs_itc_reduction"])
    f = d["Financial"]
    tar = d["ElectricTariff"]
    inp = M.ScenarioInputs(
        loads_kw=load,
        tariff=flat_tariff(tar["blended_annual_energy_rate"], tar["blended_annual_demand_rate"]),
        financial=financial(d), pv=M.PVInputs(enabled=False), storage=M.StorageInputs(enabled=False),
        fuel_tech=ft, compensation_type="no_compensation", pv_location="both",
        heating_loads_kw=heat, boiler_efficiency=eff,
        existing_boiler_fuel_cost_per_mmbtu=d["ExistingBoiler"]["fuel_cost_per_mmbtu"],
        boiler_fuel_escalation=f["existing_boiler_fuel_cost_escalation_rate_fraction"])
    t0 = time.time()
    r = M.solve(inp, time_limit=1800, mip_gap=0.01)
    print(f"  ({time.time() - t0:.0f}s, {r['status']}, CHP {r['sizes']['fueltech_kw']:.1f} kW)")
    pf = r["proforma"]
    print(f"  IRR {pf['internal_rate_of_return']}, NPV {pf['npv']:,.0f}")
    approx("CHP size_kw (fixed)", r["sizes"]["fueltech_kw"], 1104.0, atol=0.01)
    approx("simple_payback_years", pf["simple_payback_years"], 8.31, atol=0.02)
    RESULTS["chp_payback"] = {"payback": pf["simple_payback_years"], "irr": pf["internal_rate_of_return"]}


def case_chp_supp_firing():
    print("\nCHP Supplementary firing and standby, part 1 (runtests.jl:1293)")
    d = scenario("chp_supplementary_firing.json")
    chp, f = d["CHP"], d["Financial"]
    eff = d["ExistingBoiler"]["efficiency"]
    # part 1: firing costs $10,000/kW and is never bought, so a CHP without it is the same model
    tariff = flat_tariff(0.0, 0.0)
    months = ds._month_hours_2017()                       # 2022 has the same month lengths
    tariff.energy_cost_per_kwh = [0.0] * 8760
    for mo, hrs in enumerate(months):
        for h in hrs:
            tariff.energy_cost_per_kwh[h] = d["ElectricTariff"]["monthly_energy_rates"][mo]
    tariff.monthly_demand_rates = list(map(float, d["ElectricTariff"]["monthly_demand_rates"]))
    ft = M.FuelTechInputs(
        enabled=True, kind="CHP", label="CHP", name="CHP",
        installed_cost_per_kw=chp["installed_cost_per_kw"],
        om_cost_per_kw=chp["om_cost_per_kw"], om_cost_per_kwh=chp["om_cost_per_kwh"],
        electric_efficiency_full_load=chp["electric_efficiency_full_load"],
        electric_efficiency_half_load=chp["electric_efficiency_half_load"],
        thermal_efficiency_full_load=chp["thermal_efficiency_full_load"],
        thermal_efficiency_half_load=chp["thermal_efficiency_half_load"],
        min_turn_down_fraction=chp["min_turn_down_fraction"],
        min_allowable_kw=0.0, min_kw=chp["min_kw"], max_kw=chp["max_kw"],
        fuel_cost_per_mmbtu=chp["fuel_cost_per_mmbtu"],
        production_factor_series=[1.0 - x for x in C.generate_year_profile_hourly(
            2022, chp["unavailability_periods"])],
        federal_itc_fraction=0.0, macrs_option_years=0, macrs_bonus_fraction=0.0,
        macrs_itc_reduction=0.0)
    inp = M.ScenarioInputs(
        loads_kw=[800.0] * 8760, tariff=tariff, financial=financial(d),
        pv=M.PVInputs(enabled=False), storage=M.StorageInputs(enabled=False),
        fuel_tech=ft, compensation_type="no_compensation", pv_location="both",
        heating_loads_kw=[12.0 * eff * 293.07107] * 8760, boiler_efficiency=eff,
        existing_boiler_fuel_cost_per_mmbtu=d["ExistingBoiler"]["fuel_cost_per_mmbtu"],
        boiler_fuel_escalation=f["existing_boiler_fuel_cost_escalation_rate_fraction"])
    t0 = time.time()
    r = M.solve(inp, time_limit=1800)
    print(f"  ({time.time() - t0:.0f}s, {r['status']})")
    s = r["series"]
    thermal = (sum(s["chp_heat_to_load_kw"]) + sum(s["chp_heat_waste_kw"])) / 293.07107
    approx("CHP size_kw", r["sizes"]["fueltech_kw"], 800.0, atol=1e-6)
    approx("CHP annual_electric_production_kwh", sum(s["fueltech_kw"]), 800 * 8760, rtol=1e-5)
    approx("CHP annual_thermal_production_mmbtu", thermal,
           800 * (0.4418 / 0.3573) * 8760 / 293.07107, rtol=1e-5)
    approx("year-one demand cost (lifecycle == 0)", r["utility"]["year1_monthly_demand_cost"], 0.0, atol=1e-6)
    approx("total heating thermal load MMBtu", sum(s["heating_load_kw"]) / 293.07107, 12.0 * 8760 * eff, rtol=1e-9)


CASES = {"heuristic": case_heuristic, "defaults": case_defaults, "pv_storage": case_pv_storage,
         "duration": case_duration, "om_frac": case_om_fraction,
         "chp_curve": case_chp_curve, "chp_sizing": case_chp_sizing, "chp_payback": case_chp_payback,
         "chp_supp": case_chp_supp_firing}


def main():
    pick = [a for a in sys.argv[1:] if a in CASES] or list(CASES)
    for k in pick:
        try:
            CASES[k]()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            FAIL.append(f"{k}: {type(exc).__name__}: {exc}")
    print("\n" + "=" * 100)
    if FAIL:
        print(f"{len(FAIL)} FAILURE(S):")
        for f in FAIL:
            print("  -", f)
        sys.exit(1)
    print(f"all {len(pick)} REopt.jl test groups passed")


if __name__ == "__main__":
    main()
