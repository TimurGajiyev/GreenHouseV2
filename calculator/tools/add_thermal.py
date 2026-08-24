"""Add the existing-boiler thermal subsystem so CHP scenarios line up with REopt.

Verified against REopt run 7afae73e (Golden CO, Large Office):
  space heating 5,027.88 + domestic hot water 238.57 = 5,266.45 MMBtu fuel
  x 0.80 boiler efficiency                            = 4,213.2 MMBtu thermal
  both match the tool's "Heating System Fuel Used / Thermal Production" exactly.
Lifecycle boiler fuel cost uses existing_boiler_fuel_cost_escalation_rate_fraction
= 0.0348 (financial.jl:7), which reproduces REopt's $454,883.
"""

import io
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def patch(rel, edits):
    p = os.path.join(BASE, rel)
    s = io.open(p, encoding="utf-8").read()
    for old, new, what in edits:
        if old not in s:
            raise SystemExit(f"NOT FOUND in {rel}: {what}")
        s = s.replace(old, new, 1)
        print(f"  ok  {rel}: {what}")
    io.open(p, "w", encoding="utf-8").write(s)


# ---------------------------------------------------------------- data source
patch("reopt_core/data_sources.py", [
    (
        "# ----------------------------------------------------------------- PVWatts",
        '''def heating_load_mmbtu(building_type: str, city: str) -> dict:
    """Annual boiler FUEL in MMBtu, from the tables REopt ships.

    REopt's existing-boiler load is space heating + domestic hot water, taken
    from data/load_profiles/*_annual_mmbtu.json for the CRB city and building.
    """
    out = {}
    for key, fname in (("space_heating", "space_heating_annual_mmbtu.json"),
                       ("domestic_hot_water", "domestic_hot_water_annual_mmbtu.json")):
        path = os.path.join(LOAD_PROFILE_DIR, fname)
        with io.open(path, encoding="utf-8") as fh:
            table = json.load(fh)
        out[key] = float((table.get(city) or {}).get(building_type) or 0.0)
    out["fuel_mmbtu"] = out["space_heating"] + out["domestic_hot_water"]
    return out


# ----------------------------------------------------------------- PVWatts''',
        "heating_load_mmbtu",
    ),
])

# --------------------------------------------------------------------- model
patch("reopt_core/model.py", [
    (
        """    existing_boiler_fuel_cost_per_mmbtu: float = 8.0
    boiler_efficiency: float = 0.8
    heating_load_mmbtu_per_hour: list[float] | None = None""",
        """    existing_boiler_fuel_cost_per_mmbtu: float = 8.0
    boiler_efficiency: float = 0.8
    # Annual boiler FUEL (MMBtu) from the CRB tables; None = no heating load
    heating_fuel_mmbtu: float | None = None
    # financial.jl:7 existing_boiler_fuel_cost_escalation_rate_fraction
    boiler_fuel_escalation: float = 0.0348""",
        "thermal inputs",
    ),
    (
        """    pwf_fuel = annuity(f.analysis_years, f.fuel_cost_escalation_rate_fraction,
                       f.offtaker_discount_rate_fraction)""",
        """    pwf_fuel = annuity(f.analysis_years, f.fuel_cost_escalation_rate_fraction,
                       f.offtaker_discount_rate_fraction)
    pwf_boiler = annuity(f.analysis_years, inp.boiler_fuel_escalation,
                         f.offtaker_discount_rate_fraction)""",
        "boiler present-worth factor",
    ),
    (
        """    tar = inp.tariff
    tou_peak, mon_peak = [], []""",
        """    # ---- existing boiler + CHP thermal credit ----
    # Thermal load the boiler must serve, less whatever CHP recovers.
    thermal_load_mmbtu = ((inp.heating_fuel_mmbtu or 0.0) * inp.boiler_efficiency)
    chp_thermal = pulp.LpVariable("chp_thermal_mmbtu", lowBound=0)
    boiler_thermal = pulp.LpVariable("boiler_thermal_mmbtu", lowBound=0)

    tar = inp.tariff
    tou_peak, mon_peak = [], []""",
        "thermal variables",
    ),
    (
        """    # ------------------------------------------------------------- objective""",
        """    # Thermal balance: boiler covers whatever CHP does not.
    if thermal_load_mmbtu > 0:
        m += boiler_thermal + chp_thermal == thermal_load_mmbtu, "thermal_balance"
        if ft.enabled and ft.kind == "CHP" and ft.thermal_efficiency_full_load > 0:
            # recovered heat scales with electric output by the efficiency ratio
            ratio = ft.thermal_efficiency_full_load / ft.electric_efficiency_full_load
            m += chp_thermal <= (pulp.lpSum(ftprod[t] for t in T) * ratio / 293.07107), "chp_heat"
        else:
            m += chp_thermal == 0, "no_chp_heat"
    else:
        m += chp_thermal == 0, "no_thermal_load"
        m += boiler_thermal == 0, "no_boiler"

    # ------------------------------------------------------------- objective""",
        "thermal balance",
    ),
    (
        """    m += (TotalTechCapCosts + TotalStorageCapCosts""",
        """    # Existing boiler fuel, tax deductible for the offtaker like other fuel
    ExistingBoilerFuelCost = (
        pwf_boiler * inp.existing_boiler_fuel_cost_per_mmbtu
        * (boiler_thermal / inp.boiler_efficiency)) if thermal_load_mmbtu > 0 else 0.0

    m += (TotalTechCapCosts + TotalStorageCapCosts""",
        "boiler fuel cost expression",
    ),
    (
        """          + TotalElecBill * (1 - tax_off)), "Costs\"""",
        """          + TotalElecBill * (1 - tax_off)
          + ExistingBoilerFuelCost * (1 - tax_off)), "Costs\"""",
        "boiler cost into objective",
    ),
    (
        """        "factors": {"pwf_e": pwf_e, "pwf_om": pwf_om, "pwf_fuel": pwf_fuel,""",
        """        "thermal": {
            "heating_fuel_mmbtu": inp.heating_fuel_mmbtu or 0.0,
            "thermal_load_mmbtu": thermal_load_mmbtu,
            "chp_thermal_mmbtu": v(chp_thermal),
            "boiler_thermal_mmbtu": v(boiler_thermal),
            "boiler_fuel_mmbtu": (v(boiler_thermal) / inp.boiler_efficiency
                                  if thermal_load_mmbtu > 0 else 0.0),
            "boiler_fuel_cost_year1": (v(boiler_thermal) / inp.boiler_efficiency
                                       * inp.existing_boiler_fuel_cost_per_mmbtu
                                       if thermal_load_mmbtu > 0 else 0.0),
            "boiler_fuel_cost_lifecycle": (v(boiler_thermal) / inp.boiler_efficiency
                                           * inp.existing_boiler_fuel_cost_per_mmbtu
                                           * pwf_boiler * (1 - tax_off)
                                           if thermal_load_mmbtu > 0 else 0.0),
        },
        "factors": {"pwf_e": pwf_e, "pwf_om": pwf_om, "pwf_fuel": pwf_fuel,
                    "pwf_boiler": pwf_boiler,""",
        "thermal results",
    ),
    (
        """    fixed = tar.fixed_monthly_charge * 12
    year1 = energy + tou + mon + fixed
    pwf_e = annuity(f.analysis_years, f.elec_cost_escalation_rate_fraction,
                    f.offtaker_discount_rate_fraction)""",
        """    fixed = tar.fixed_monthly_charge * 12
    year1 = energy + tou + mon + fixed
    pwf_e = annuity(f.analysis_years, f.elec_cost_escalation_rate_fraction,
                    f.offtaker_discount_rate_fraction)
    # BAU carries the full boiler fuel bill: no CHP means no heat recovery
    boiler_lcc = 0.0
    if inp.heating_fuel_mmbtu:
        boiler_lcc = (annuity(f.analysis_years, inp.boiler_fuel_escalation,
                              f.offtaker_discount_rate_fraction)
                      * inp.heating_fuel_mmbtu * inp.existing_boiler_fuel_cost_per_mmbtu
                      * (1 - f.offtaker_tax_rate_fraction))""",
        "BAU boiler factor",
    ),
    (
        """        "lifecycle_cost": pwf_e * year1 * (1 - f.offtaker_tax_rate_fraction),
    }""",
        """        "year1_boiler_fuel_cost": ((inp.heating_fuel_mmbtu or 0.0)
                                   * inp.existing_boiler_fuel_cost_per_mmbtu),
        "boiler_lifecycle_cost": boiler_lcc,
        "lifecycle_cost": pwf_e * year1 * (1 - f.offtaker_tax_rate_fraction) + boiler_lcc,
    }""",
        "BAU boiler in lifecycle",
    ),
])

print("thermal subsystem added")
