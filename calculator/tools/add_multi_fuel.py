"""N fuel-fired units, the affine fuel curve and minimum turndown.

All three already exist in REopt and were simply not ported:

  * REopt.jl carries CHP as an ARRAY -- `chps::Array{CHP,1}` (scenario.jl:19),
    built from `chp_array` and auto-named CHP1, CHP2 ... (scenario.jl:490-496).
    The web form exposes exactly one block; the engine never did.
  * The affine fuel curve `fuel = intercept*u + slope*P` is REopt's own
    formulation -- generator_constraints.jl:8-12, with the intercept multiplied
    by `binGenIsOnInTS` so an idle unit burns nothing.
  * `min_turn_down_fraction` is a field on Generator, CHP and Prime Generator in
    all three captured UI configs, enforced at generator_constraints.jl:26-36.

ZERO-DEVIATION GUARANTEE. `electric_efficiency_half_load` defaults to
`electric_efficiency_full_load` in REopt (generator.jl:15,112; chp.jl:280-281;
chp_defaults.json ships no half-load entry). At that default the intercept is
exactly 0.0 and the slope is exactly 1/(eff*HHV) -- verified bit-identical in
Python floats. With intercept 0 and turndown 0 no binary is created at all, and
every expression collapses to the single-unit algebra that was there before.
The validated suites therefore cannot move; that is asserted, not assumed.
"""

import io
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def patch(rel, edits):
    p = os.path.join(BASE, rel)
    s = io.open(p, encoding="utf-8").read()
    for old, new, what in edits:
        if old not in s:
            raise SystemExit("NOT FOUND in {}: {}".format(rel, what))
        s = s.replace(old, new, 1)
        print("  ok  {}: {}".format(rel, what))
    io.open(p, "w", encoding="utf-8").write(s)


patch("reopt_core/model.py", [
    (
        "from .finance import annuity, effective_cost, levelization_factor, macrs_schedule_for",
        "from .finance import (annuity, effective_cost, fuel_slope_and_intercept,\n"
        "                      levelization_factor, macrs_schedule_for)",
        "import the fuel curve",
    ),

    # ---------------------------------------------------------------- inputs
    (
        """    only_runs_during_grid_outage: bool = False
    # chp.jl:45 -- 0 means the unit PROVIDES reserve rather than requiring it
    operating_reserve_required_fraction: float = 0.0""",
        """    only_runs_during_grid_outage: bool = False
    # chp.jl:45 -- 0 means the unit PROVIDES reserve rather than requiring it
    operating_reserve_required_fraction: float = 0.0
    # Free-text name; REopt auto-names an array of CHP units CHP1, CHP2 ...
    # (scenario.jl:496). Only used for labelling results.
    name: str = ""
    # generator.jl:15 / chp.jl:280 -- None means "same as full load", which is
    # REopt's own default and makes the fuel curve exactly linear (intercept 0).
    electric_efficiency_half_load: float | None = None
    # generator_constraints.jl:26-36. 0 means no turndown floor and no binary.
    min_turn_down_fraction: float = 0.0""",
        "fuel tech: name, half-load efficiency, turndown",
    ),
    (
        """    pv: PVInputs
    storage: StorageInputs
    fuel_tech: FuelTechInputs
    off_grid_flag: bool = False""",
        """    pv: PVInputs
    storage: StorageInputs
    fuel_tech: FuelTechInputs
    # A fleet of distinct units. None keeps the single `fuel_tech` slot, which
    # is the REopt web-form shape. A list is the REopt.jl shape (scenario.jl:19).
    fuel_techs: list[FuelTechInputs] | None = None
    # How the fuel-curve intercept scales. "reopt" multiplies it by the on/off
    # binary alone, exactly as generator_constraints.jl:11 does. "rated" also
    # multiplies by the unit's rated kW, which is the physically consistent form
    # for a fleet of fixed-size machines but is NOT what REopt computes.
    # Irrelevant at REopt defaults, where the intercept is 0 either way.
    fuel_intercept_basis: str = "reopt"
    off_grid_flag: bool = False""",
        "scenario: fuel_techs list and intercept basis",
    ),

    # ------------------------------------------------------- capital slopes
    (
        """    ft = inp.fuel_tech
    ft_slope = 0.0
    if ft.enabled:
        ft_slope = effective_cost(
            itc_basis=ft.installed_cost_per_kw,
            replacement_cost=(0.0 if ft.replacement_year >= f.analysis_years else ft.replace_cost_per_kw),
            replacement_year=ft.replacement_year,
            discount_rate=f.owner_discount_rate_fraction, tax_rate=tax_own,
            itc=ft.federal_itc_fraction,
            macrs_schedule=macrs_schedule_for(ft.macrs_option_years),
            macrs_bonus_fraction=ft.macrs_bonus_fraction if ft.macrs_option_years else 0.0,
            macrs_itc_reduction=ft.macrs_itc_reduction if ft.macrs_option_years else 0.0,
        )""",
        """    # A fleet of one is the single-slot case, so both shapes run one code path.
    fts = list(inp.fuel_techs) if inp.fuel_techs else [inp.fuel_tech]
    NG = range(len(fts))
    ft = fts[0]                     # kept for the single-unit expressions below

    ft_slopes = {}
    for g in NG:
        u = fts[g]
        ft_slopes[g] = effective_cost(
            itc_basis=u.installed_cost_per_kw,
            replacement_cost=(0.0 if u.replacement_year >= f.analysis_years else u.replace_cost_per_kw),
            replacement_year=u.replacement_year,
            discount_rate=f.owner_discount_rate_fraction, tax_rate=tax_own,
            itc=u.federal_itc_fraction,
            macrs_schedule=macrs_schedule_for(u.macrs_option_years),
            macrs_bonus_fraction=u.macrs_bonus_fraction if u.macrs_option_years else 0.0,
            macrs_itc_reduction=u.macrs_itc_reduction if u.macrs_option_years else 0.0,
        ) if u.enabled else 0.0

    # ---- affine fuel curve per unit, utils.jl:645 + generator_constraints.jl:8 ----
    # CHP is priced per MMBtu, so its heating value is kWh per MMBtu.
    ft_slope_fuel, ft_icept, ft_needs_bin = {}, {}, {}
    for g in NG:
        u = fts[g]
        hhv = (293.07107 if u.kind == "CHP" else u.fuel_higher_heating_value_kwh_per_gal)
        half = (u.electric_efficiency_half_load
                if u.electric_efficiency_half_load is not None
                else u.electric_efficiency_full_load)
        sl, ic = fuel_slope_and_intercept(
            electric_efficiency_full_load=u.electric_efficiency_full_load,
            electric_efficiency_half_load=half,
            fuel_higher_heating_value_kwh_per_unit=hhv,
        )
        ft_slope_fuel[g], ft_icept[g] = sl, ic
        # A binary is only needed when something actually references on/off.
        # At REopt defaults ic == 0.0 and turndown == 0, so none is created and
        # the model stays a pure LP -- identical to the pre-curve formulation.
        ft_needs_bin[g] = bool(u.enabled and (ic > 0.0 or u.min_turn_down_fraction > 0.0))""",
        "per-unit capital slopes and fuel curves",
    ),

    # ---------------------------------------------------------- variables
    (
        """    dvFTsize = pulp.LpVariable("dvSize_FT", lowBound=ft.min_kw,
                               upBound=ft.max_kw if ft.enabled else 0.0)""",
        """    ftsize = {g: pulp.LpVariable(f"dvSize_FT_{g}", lowBound=fts[g].min_kw,
                                 upBound=fts[g].max_kw if fts[g].enabled else 0.0)
              for g in NG}
    # Aggregate alias: every expression downstream is written against the fleet
    # total, so the single-unit algebra is untouched when the fleet has one unit.
    dvFTsize = pulp.lpSum(ftsize[g] for g in NG)""",
        "per-unit size variables",
    ),
    (
        """    ftprod = {t: pulp.LpVariable(f"ftprod_{t}", lowBound=0) for t in T}""",
        """    ftgen = {g: {t: pulp.LpVariable(f"ftprod_{g}_{t}", lowBound=0) for t in T}
             for g in NG}
    ftprod = {t: pulp.lpSum(ftgen[g][t] for g in NG) for t in T}
    ftu = {g: ({t: pulp.LpVariable(f"ftON_{g}_{t}", cat="Binary") for t in T}
               if ft_needs_bin[g] else None) for g in NG}""",
        "per-unit production and on/off binaries",
    ),

    # -------------------------------------------------------- constraints
    (
        """        m += ftprod[t] <= dvFTsize, f"ft_cap_{t}\"""",
        """        for g in NG:
            # Rated production never exceeds installed size (tech_constraints.jl)
            m += ftgen[g][t] <= ftsize[g], f"ft_cap_{g}_{t}"
            if ft_needs_bin[g]:
                # generator_constraints.jl:22-24 -- off means exactly zero.
                # The big-M is the unit's own upper bound, as REopt uses max_sizes.
                m += ftgen[g][t] <= fts[g].max_kw * ftu[g][t], f"ft_on_{g}_{t}"
                if fts[g].min_turn_down_fraction > 0:
                    # generator_constraints.jl:32-35
                    m += (fts[g].min_turn_down_fraction * ftsize[g] - ftgen[g][t]
                          <= fts[g].max_kw * (1 - ftu[g][t])), f"ft_turndown_{g}_{t}\"""",
        "per-unit capacity, on/off and turndown",
    ),

    # ------------------------------------------------------------ thermal
    (
        """        if ft.enabled and ft.kind == "CHP" and ft.thermal_efficiency_full_load > 0:
            # recovered heat scales with electric output by the efficiency ratio
            ratio = ft.thermal_efficiency_full_load / ft.electric_efficiency_full_load
            m += chp_thermal <= (pulp.lpSum(ftprod[t] for t in T) * ratio / 293.07107), "chp_heat\"""",
        """        _heat_units = [g for g in NG if fts[g].enabled and fts[g].kind == "CHP"
                       and fts[g].thermal_efficiency_full_load > 0]
        if _heat_units:
            # recovered heat scales with electric output by the efficiency ratio
            m += chp_thermal <= pulp.lpSum(
                pulp.lpSum(ftgen[g][t] for t in T)
                * (fts[g].thermal_efficiency_full_load / fts[g].electric_efficiency_full_load)
                / 293.07107 for g in _heat_units), "chp_heat\"""",
        "thermal credit summed over CHP units",
    ),

    # --------------------------------------------------- operating reserve
    (
        """                if ft.enabled and f_ft == 0.0:
                    m += or_ft[t] <= dvFTsize - ftprod[t], f"or_ft_{t}"
                else:
                    m += or_ft[t] == 0, f"or_ft_{t}\"""",
        """                _prov = [g for g in NG if fts[g].enabled
                         and fts[g].operating_reserve_required_fraction == 0.0]
                if _prov:
                    m += or_ft[t] <= pulp.lpSum(ftsize[g] - ftgen[g][t] for g in _prov), f"or_ft_{t}"
                else:
                    m += or_ft[t] == 0, f"or_ft_{t}\"""",
        "reserve headroom summed over providing units",
    ),

    # ---------------------------------------------------------- objective
    (
        """    TotalTechCapCosts = pv_slope * dvPVsize + ft_slope * dvFTsize""",
        """    TotalTechCapCosts = pv_slope * dvPVsize + pulp.lpSum(
        ft_slopes[g] * ftsize[g] for g in NG)""",
        "capital cost per unit",
    ),
    (
        """    TotalPerUnitSizeOMCosts = pwf_om * (inp.pv.om_cost_per_kw * dvPVsize + ft.om_cost_per_kw * dvFTsize)""",
        """    TotalPerUnitSizeOMCosts = pwf_om * (
        inp.pv.om_cost_per_kw * dvPVsize
        + pulp.lpSum(fts[g].om_cost_per_kw * ftsize[g] for g in NG))""",
        "fixed O&M per unit",
    ),
    (
        """    TotalPerUnitProdOMCosts = pwf_om * ft.om_cost_per_kwh * pulp.lpSum(ftprod[t] for t in T)""",
        """    TotalPerUnitProdOMCosts = pwf_om * pulp.lpSum(
        fts[g].om_cost_per_kwh * pulp.lpSum(ftgen[g][t] for t in T) for g in NG)""",
        "variable O&M per unit",
    ),
    (
        """    # Fuel: kWh_elec / efficiency -> fuel kWh -> gallons or MMBtu
    if ft.enabled and ft.kind == "Generator":
        gal = pulp.lpSum(ftprod[t] for t in T) / (
            ft.electric_efficiency_full_load * ft.fuel_higher_heating_value_kwh_per_gal)
        TotalFuelCosts = pwf_fuel * ft.fuel_cost_per_gallon * gal
    elif ft.enabled and ft.kind == "CHP":
        mmbtu = pulp.lpSum(ftprod[t] for t in T) / ft.electric_efficiency_full_load / 293.07107
        TotalFuelCosts = pwf_fuel * ft.fuel_cost_per_mmbtu * mmbtu
    else:
        TotalFuelCosts = 0.0""",
        """    # Fuel, per unit: generator_constraints.jl:8-12
    #     usage = slope * production + intercept * on
    # At REopt's default (half == full load) intercept is 0 and slope is exactly
    # 1/(eff*HHV), so this reduces to the previous linear term term-for-term.
    ft_fuel_units = {}
    TotalFuelCosts = 0.0
    for g in NG:
        u = fts[g]
        if not u.enabled:
            ft_fuel_units[g] = 0.0
            continue
        usage = ft_slope_fuel[g] * pulp.lpSum(ftgen[g][t] for t in T)
        if ft_needs_bin[g] and ft_icept[g] > 0.0:
            coef = ft_icept[g]
            if inp.fuel_intercept_basis == "rated":
                if u.min_kw != u.max_kw:
                    raise ValueError(
                        "fuel_intercept_basis='rated' needs a fixed-size unit "
                        "(min_kw == max_kw); unit %d is sized by the optimizer." % g)
                coef *= u.max_kw
            usage = usage + coef * pulp.lpSum(ftu[g][t] for t in T)
        ft_fuel_units[g] = usage
        price = (u.fuel_cost_per_gallon if u.kind == "Generator" else u.fuel_cost_per_mmbtu)
        TotalFuelCosts = TotalFuelCosts + pwf_fuel * price * usage""",
        "fuel cost per unit via the affine curve",
    ),

    # ------------------------------------------------------------ results
    (
        """    v = lambda x: float(pulp.value(x) or 0.0)
    pv_kw, ft_kw = v(dvPVsize), v(dvFTsize)""",
        """    v = lambda x: float(pulp.value(x) or 0.0)
    pv_kw, ft_kw = v(dvPVsize), v(dvFTsize)
    ft_unit_rows = []
    for g in NG:
        if not fts[g].enabled:
            continue
        kw = v(ftsize[g])
        kwh = sum(v(ftgen[g][t]) for t in T)
        hrs = sum(1 for t in T if v(ftgen[g][t]) > 1e-6)
        ft_unit_rows.append({
            "index": g,
            "name": fts[g].name or fts[g].label or fts[g].kind,
            "kind": fts[g].kind,
            "size_kw": kw,
            "energy_kwh": kwh,
            "running_hours": hrs,
            "capacity_factor": (kwh / (kw * HOURS)) if kw > 1e-9 else 0.0,
            "fuel_units": float(pulp.value(ft_fuel_units[g]) or 0.0),
            "fuel_unit_name": ("gallons" if fts[g].kind == "Generator" else "MMBtu"),
            "starts": (sum(1 for t in T
                           if v(ftu[g][t]) > 0.5 and v(ftu[g][t - 1]) < 0.5)
                       if ft_needs_bin[g] else None),
        })""",
        "per-unit result rows",
    ),
])

print("multi-unit fuel techs added")
