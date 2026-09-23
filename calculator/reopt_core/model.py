"""The optimisation model, ported from REopt.jl v0.61.1.

Structure follows ``REopt/src/core/reopt.jl`` (objective) and
``REopt/src/constraints/*.jl`` (constraints). Solved with HiGHS via PuLP --
HiGHS is the same solver the REopt web tool submits (`solver_name: "HiGHS"`
in the captured /tool/results payload).

Scope: PV, ElectricStorage, Generator, CHP. Single node, 1-hour time steps,
grid-tied or off-grid.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pulp

from .cost_curve import CostCurveTech, cost_curve, needs_segments, segments
from .finance import (annuity, effective_cost, fuel_slope_and_intercept,
                      levelization_factor, macrs_schedule_for)
from .proforma import depreciation_tax_shields, pv_lcoe
from . import proforma as PF
from .tariff import Tariff

HOURS = 8760
D_KW_PER_SQFT = 0.01   # PV.kw_per_square_foot -- pv.jl:23


# --------------------------------------------------------------- input types
@dataclass
class FinancialInputs:
    analysis_years: int = 25
    elec_cost_escalation_rate_fraction: float = 0.0166
    om_cost_escalation_rate_fraction: float = 0.025
    offtaker_discount_rate_fraction: float = 0.0624
    offtaker_tax_rate_fraction: float = 0.26
    owner_discount_rate_fraction: float | None = None   # defaults to offtaker
    owner_tax_rate_fraction: float | None = None
    fuel_cost_escalation_rate_fraction: float = 0.034
    # financial.jl:9 -- CHP fuel has its own escalation (web form: 3.48%).
    # None keeps the generic rate above, which is how every run before this
    # field existed was priced.
    chp_fuel_cost_escalation_rate_fraction: float | None = None

    def __post_init__(self) -> None:
        if self.owner_discount_rate_fraction is None:
            self.owner_discount_rate_fraction = self.offtaker_discount_rate_fraction
        if self.owner_tax_rate_fraction is None:
            self.owner_tax_rate_fraction = self.offtaker_tax_rate_fraction


@dataclass
class PVInputs:
    enabled: bool = False
    installed_cost_per_kw: float = 1920.0
    om_cost_per_kw: float = 20.0
    min_kw: float = 0.0
    max_kw: float = 1.0e9
    degradation_fraction: float = 0.005
    macrs_option_years: int = 5
    macrs_bonus_fraction: float = 1.0
    macrs_itc_reduction: float = 0.5
    federal_itc_fraction: float = 0.3
    acres_per_kw: float = 6e-3
    production_factor: list[float] = field(default_factory=list)
    can_curtail: bool = True
    # pv.jl:46 -- off-grid only; REopt zeroes it on-grid (pv.jl:175)
    operating_reserve_required_fraction: float = 0.25
    # pv.jl -- REopt prices PV through cost_curve.jl too; a $/kW federal rebate
    # is the one incentive beyond the ITC that its test scenarios use.
    federal_rebate_per_kw: float = 0.0


@dataclass
class StorageInputs:
    enabled: bool = False
    installed_cost_per_kw: float = 968.0
    installed_cost_per_kwh: float = 253.0
    installed_cost_constant: float = 222115.0
    replace_cost_per_kw: float = 0.0
    replace_cost_per_kwh: float = 0.0
    inverter_replacement_year: int = 10
    battery_replacement_year: int = 10
    om_cost_fraction_of_installed_cost: float = 0.025
    min_kw: float = 0.0
    max_kw: float = 1.0e4
    min_kwh: float = 0.0
    max_kwh: float = 1.0e6
    charge_efficiency: float = 0.96 * 0.975 ** 0.5
    discharge_efficiency: float = 0.96 * 0.975 ** 0.5
    grid_charge_efficiency: float = 0.96 * 0.975 ** 0.5
    can_grid_charge: bool = True
    soc_min_fraction: float = 0.2
    soc_init_fraction: float = 0.5
    min_duration_hours: float = 0.0
    max_duration_hours: float = 100000.0
    macrs_option_years: int = 5
    macrs_bonus_fraction: float = 1.0
    macrs_itc_reduction: float = 0.5
    total_itc_fraction: float = 0.3
    # Free-text name, used only for labelling results.
    name: str = ""
    # Beyond REopt: wear cost per kWh discharged. 0 adds nothing to the model.
    discharge_cost_per_kwh: float = 0.0
    # ---- electric_storage.jl fields the web form exposes (Advanced inputs) ----
    replace_cost_constant: float = 0.0
    cost_constant_replacement_year: int = 10
    total_rebate_per_kw: float = 0.0
    total_rebate_per_kwh: float = 0.0
    # electric_storage.jl:209 + storage_constraints.jl:39-53. False (REopt's
    # default): SOC before hour 1 is soc_init_fraction x energy and the final
    # SOC is free. True: initial SOC is optimised and equals the final SOC.
    optimize_soc_init_fraction: bool = False
    # 'Custom hourly state of charge' -- storage_constraints.jl:139-148
    fixed_soc_series_fraction: list[float] | None = None
    fixed_soc_series_fraction_tolerance: float = 0.02


@dataclass
class FuelTechInputs:
    """Generator (diesel) or CHP (natural gas) -- both are fuel-burning techs."""
    enabled: bool = False
    kind: str = "Generator"                    # "Generator" | "CHP" (fuel maths)
    label: str = ""                            # what to call it in the UI
    installed_cost_per_kw: float = 800.0
    om_cost_per_kw: float = 20.0
    om_cost_per_kwh: float = 0.0
    electric_efficiency_full_load: float = 0.322
    fuel_higher_heating_value_kwh_per_gal: float = 40.7
    fuel_cost_per_gallon: float = 2.25         # Generator: $/gal
    fuel_cost_per_mmbtu: float = 8.0           # CHP: $/MMBtu
    thermal_efficiency_full_load: float = 0.0  # CHP only
    min_kw: float = 0.0
    max_kw: float = 1.0e9
    macrs_option_years: int = 0
    macrs_bonus_fraction: float = 0.0
    macrs_itc_reduction: float = 0.0
    federal_itc_fraction: float = 0.0
    replacement_year: int = 25
    replace_cost_per_kw: float = 0.0
    only_runs_during_grid_outage: bool = False
    # chp.jl:45 -- 0 means the unit PROVIDES reserve rather than requiring it
    operating_reserve_required_fraction: float = 0.0
    # Free-text name; REopt auto-names an array of CHP units CHP1, CHP2 ...
    # (scenario.jl:496). Only used for labelling results.
    name: str = ""
    # generator.jl:15 / chp.jl:280 -- None means "same as full load", which is
    # REopt's own default and makes the fuel curve exactly linear (intercept 0).
    electric_efficiency_half_load: float | None = None
    # generator_constraints.jl:26-36. 0 means no turndown floor and no binary.
    min_turn_down_fraction: float = 0.0
    # ---- beyond REopt: unit-commitment details, every one off by default ----
    # Cost per start event. REopt prices no starts. 0 creates no variables.
    start_cost: float = 0.0
    # O&M billed per hour the unit runs, not per kWh. REopt has only per-kW-year
    # and per-kWh terms; a per-running-hour service contract is a third structure
    # and it does not scale with output. 0 creates no variables.
    om_cost_per_running_hour: float = 0.0
    # Hours a unit must stay on after a start / off after a stop. 1 = no rule.
    min_up_hours: int = 1
    min_down_hours: int = 1
    # Only read when ScenarioInputs.cyclic_commitment is False: the unit's state
    # in the hour before the horizon starts.
    initial_on: bool = False
    # At most this many starts in any calendar day of the horizon (hours
    # 0-23, 24-47, ...). OEM maintenance plans cap starts per day; the rule
    # simulations this project compared (1-minute workbook vs hourly JSX)
    # disagreed mostly on how often engines start. None = no limit and no
    # new variables or constraints.
    max_starts_per_day: int | None = None
    # ---- scheduled maintenance, PyPSA's formulation ------------------------
    # PyPSA (docs.pypsa.org, "Maintenance scheduling") gives a maintainable
    # component three inputs and lets the SOLVER place the outages: a number of
    # events, a duration each, and how much capacity is lost while one is on.
    # REopt has nothing of the sort -- its CHP carries fixed
    # ``unavailability_periods`` whose timing the user states (utils.jl:349,
    # reproduced in ``chp_defaults.generate_year_profile_hourly``). Both are
    # useful and they answer different questions, so this is the optimised one
    # and ``production_factor_series`` stays the stated-timing one.
    #
    # 0 events creates no variables and no constraints, so a scenario without
    # maintenance is the same model it was before this field existed.
    maintenance_events: int = 0
    # Hours per event. A gas engine's minor service is one service shift --
    # TEDOM and Jenbacher practice is 4-8 h, the unit cooling down, being
    # worked on and restarted -- so this is hours, not days.
    maintenance_duration_hours: int = 0
    # Fraction of capacity lost during an event. PyPSA's ``maintenance_pu``,
    # default 1.0 = the unit is fully out. Below 1.0 it keeps running derated,
    # which is a partial outage rather than a service visit.
    maintenance_pu: float = 1.0
    # "free"  -- PyPSA's own rule: exactly ``maintenance_events`` starts
    #            anywhere in the horizon. Nothing stops the solver bunching
    #            them, because nothing in the objective prefers them spread.
    # "even"  -- one event per equal segment of the horizon, the solver
    #            choosing the hour inside its segment. This is what a service
    #            plan actually looks like; it is a restriction, so it can only
    #            cost the same or more than "free".
    # Ignored in the running-hours mode below, where the count is an outcome.
    maintenance_spacing: str = "free"
    # ---- the running-hours trigger (HOMER Pro's) ---------------------------
    # A gas engine's service interval is written in OPERATING hours, not
    # calendar ones: INNIO Jenbacher and TEDOM publish minor service every
    # 1,000-2,000 running hours. A fixed count of events is a proxy for that and
    # a poor one -- it schedules a service on a unit that never ran, which the
    # four-engine browser run showed happening. HOMER Pro triggers on an
    # interval in operating hours instead, and so does this when it is set.
    #
    # > 0 switches the trigger: the model carries a "running hours since the
    # last service" counter per unit and never lets it exceed this, so the
    # NUMBER of services becomes an outcome of how much the unit actually runs.
    # A unit that never starts accumulates nothing and is never serviced.
    # ``maintenance_events`` and ``maintenance_spacing`` are then unused.
    # 0 (the default) keeps the count mode above, unchanged.
    maintenance_interval_running_hours: float = 0.0
    # Running hours already on the clock when the horizon opens. Only read in
    # the running-hours mode with ``cyclic_commitment`` off, where the horizon
    # has a real beginning; the cyclic case wraps the counter instead.
    maintenance_hours_at_start: float = 0.0
    # What one service costs -- parts and labour, HOMER Pro's third maintenance
    # input beside the interval and the downtime. It is what makes the number of
    # services determinate: the running-hours rule is a CEILING on banked hours,
    # so without a price an extra service placed in an hour the unit was idle
    # anyway is free and the solver may take it. Measured: at 0 a unit needing
    # two services took four. Any positive figure removes the indifference.
    maintenance_cost_per_event: float = 0.0
    # Let a unit spill output it cannot deliver. It is still paid for (O&M and
    # fuel are charged on rated production) but it does not reach the load.
    # REopt has dvCurtail for every tech (reopt.jl:656); this port had it for PV only.
    can_curtail: bool = False
    # ---- chp.jl fields the web form exposes; every default is REopt's "off" ----
    # Size-cost pairs. When both lists are given the capital cost is REopt's
    # piecewise curve (cost_curve.jl) instead of installed_cost_per_kw.
    tech_sizes_for_cost_curve: list[float] = field(default_factory=list)
    installed_cost_curve_per_kw: list[float] = field(default_factory=list)
    min_allowable_kw: float = 0.0          # 0 or at least this much (chp.jl:21)
    existing_kw: float = 0.0               # already installed, no capital cost
    federal_rebate_per_kw: float = 0.0
    state_ibi_fraction: float = 0.0
    state_ibi_max: float = 1.0e10
    state_rebate_per_kw: float = 0.0
    state_rebate_max: float = 1.0e10
    utility_ibi_fraction: float = 0.0
    utility_ibi_max: float = 1.0e10
    utility_rebate_per_kw: float = 0.0
    utility_rebate_max: float = 1.0e10
    production_incentive_per_kwh: float = 0.0
    production_incentive_max_benefit: float = 1.0e9
    production_incentive_years: int = 1
    production_incentive_max_kw: float = 1.0e9
    # chp.jl:280 -- None means same as full load (thermal curve intercept 0)
    thermal_efficiency_half_load: float | None = None
    # production_factor.jl:285 -- (custom maximum profile) x (1 - maintenance).
    # None = available at full capacity every hour.
    production_factor_series: list[float] | None = None
    follow_electrical_load: bool = False   # chp_constraints.jl add_chp_electrical_load_following
    follow_heating_load: bool = False      # chp_constraints.jl add_chp_heating_load_following
    cooling_thermal_factor: float = 0.0    # only acts with an absorption chiller (none here)
    fuel_type: str = "natural_gas"
    # CHP fuel by month (12 values, $/MMBtu). None = fuel_cost_per_mmbtu all year.
    fuel_cost_per_mmbtu_monthly: list[float] | None = None
    # ElectricTariff "CHP standby charge based on CHP size ($/kW/month)" --
    # reopt.jl:295 charges pwf_e x 12 x rate x size, after tax.
    standby_rate_per_kw_per_month: float = 0.0


@dataclass
class ScenarioInputs:
    loads_kw: list[float]
    tariff: Tariff | None
    financial: FinancialInputs
    pv: PVInputs
    storage: StorageInputs
    fuel_tech: FuelTechInputs
    # A fleet of distinct units. None keeps the single `fuel_tech` slot, which
    # is the REopt web-form shape. A list is the REopt.jl shape (scenario.jl:19).
    fuel_techs: list[FuelTechInputs] | None = None
    # A bank of distinct batteries. None keeps the single `storage` slot, which
    # is the REopt web-form shape. A list is the REopt.jl shape
    # (StorageTypes.elec is a Vector, storage.jl:15).
    storages: list[StorageInputs] | None = None
    # How the fuel-curve intercept scales. "reopt" multiplies it by the on/off
    # binary alone, exactly as generator_constraints.jl:11 does. "rated" also
    # multiplies by the unit's rated kW, which is the physically consistent form
    # for a fleet of fixed-size machines but is NOT what REopt computes.
    # Irrelevant at REopt defaults, where the intercept is 0 either way.
    # "reopt" follows REopt per technology: the CHP fuel y-intercept scales with
    # the unit's size (chp_constraints.jl:34), the generator's does not
    # (generator_constraints.jl:11). "rated" is the older fixed-size shortcut,
    # kept so earlier scenarios reproduce; it needs min_kw == max_kw.
    fuel_intercept_basis: str = "reopt"
    # Commitment across the seam of the horizon. True (the default) wraps it:
    # hour 0 follows hour H-1, so a run of 8,760 hours reads as a repeating year
    # and a short window as a repeating window -- no free start at hour 0, no
    # forgotten shutdown at the end. False states a finite horizon instead: each
    # unit begins in FuelTechInputs.initial_on and the minimum up/down windows
    # only look back inside the horizon, which is the unit-commitment
    # convention. The wrap costs nothing when the minimum times are short next
    # to the horizon; when they are comparable to it, it is a real restriction
    # (a unit stopped near the end cannot run near the start).
    cyclic_commitment: bool = True
    off_grid_flag: bool = False
    land_acres: float | None = None
    roof_squarefeet: float | None = None
    pv_location: str = "ground"            # "ground" | "roof" | "both"
    compensation_type: str = "no_compensation"
    wholesale_rate: float = 0.0
    # ElectricUtility.net_metering_limit_kw -- "Upper limit on the total capacity
    # of technologies that can participate in net metering" (electric_utility.jl:5)
    net_metering_limit_kw: float | None = None
    min_load_met_annual_fraction: float = 0.99999
    # electric_load.jl:20 -- off-grid only; REopt zeroes it on-grid (:127)
    operating_reserve_required_fraction: float = 0.1
    existing_boiler_fuel_cost_per_mmbtu: float = 8.0
    boiler_efficiency: float = 0.8
    # Annual boiler FUEL (MMBtu) from the CRB tables; None = no heating load
    heating_fuel_mmbtu: float | None = None
    # financial.jl:7 existing_boiler_fuel_cost_escalation_rate_fraction
    boiler_fuel_escalation: float = 0.0348
    # Hourly heating THERMAL load (kW), space heating + hot water, as REopt
    # builds it (heating_cooling_loads.jl). When given, heat is balanced hour by
    # hour -- CHP heat can only displace boiler fuel in the hour it is made.
    heating_loads_kw: list[float] | None = None
    boiler_max_thermal_factor_on_peak_load: float = 1.25
    boiler_installed_cost_per_mmbtu_per_hour: float = 0.0
    boiler_installed_cost_dollars: float = 0.0
    boiler_fuel_cost_per_mmbtu_monthly: list[float] | None = None
    boiler_fuel_type: str = "natural_gas"
    heating_unaddressable_fuel_mmbtu: float = 0.0   # reported, as REopt does
    # "Net (gross load minus existing CHP generation)" -- reopt_inputs.jl:1258.
    # When True and a unit has existing_kw, that unit's available output is added
    # back onto the load, because the metered load was already net of it.
    loads_kw_is_net: bool = True


def _month_of_hour_2017() -> list[int]:
    import datetime as _dt
    out, d = [], _dt.datetime(2017, 1, 1)
    for _ in range(8760):
        out.append(d.month - 1)
        d += _dt.timedelta(hours=1)
    return out


_MONTH_OF_HOUR = _month_of_hour_2017()


# --------------------------------------------------------------- the model
def solve(inp: ScenarioInputs, *, time_limit: int = 300, msg: bool = False,
          mip_gap: float | None = None) -> dict:
    f = inp.financial
    # The horizon follows the load. Every annual caller passes 8,760 hours, so
    # this is HOURS for them; a 168-hour week can now be solved as posed.
    H = len(inp.loads_kw)
    T = list(range(H))
    loads = list(inp.loads_kw)
    if inp.loads_kw_is_net:
        for _u in (list(inp.fuel_techs) if inp.fuel_techs else [inp.fuel_tech]):
            if _u.enabled and _u.kind == "CHP" and _u.existing_kw > 0:
                _pfx = (list(_u.production_factor_series)[:H]
                        if _u.production_factor_series is not None else [1.0] * H)
                loads = [loads[t] + _u.existing_kw * _pfx[t] for t in range(H)]

    # ---- present-worth factors: REopt/src/core/reopt_inputs.jl:1128-1138 ----
    pwf_e = annuity(f.analysis_years, f.elec_cost_escalation_rate_fraction,
                    f.offtaker_discount_rate_fraction)
    pwf_om = annuity(f.analysis_years, f.om_cost_escalation_rate_fraction,
                     f.owner_discount_rate_fraction)
    pwf_fuel = annuity(f.analysis_years, f.fuel_cost_escalation_rate_fraction,
                       f.offtaker_discount_rate_fraction)
    # reopt_inputs.jl pwf_fuel["CHP"] uses chp_fuel_cost_escalation_rate_fraction
    pwf_fuel_chp = (pwf_fuel if f.chp_fuel_cost_escalation_rate_fraction is None
                    else annuity(f.analysis_years, f.chp_fuel_cost_escalation_rate_fraction,
                                 f.offtaker_discount_rate_fraction))
    pwf_boiler = annuity(f.analysis_years, inp.boiler_fuel_escalation,
                         f.offtaker_discount_rate_fraction)
    # PV is the only tech with degradation -> levelization_factor (reopt_inputs.jl:1119)
    lvl_pv = levelization_factor(f.analysis_years, f.elec_cost_escalation_rate_fraction,
                                 f.offtaker_discount_rate_fraction, inp.pv.degradation_fraction)

    tax_own = f.owner_tax_rate_fraction
    tax_off = f.offtaker_tax_rate_fraction

    # ---- capital cost slopes: utils.jl:83 effective_cost ----
    pv_slope = 0.0
    if inp.pv.enabled:
        # reopt_inputs.jl setup_pv_inputs -> update_cost_curve! -> cost_curve.jl.
        # For a whole-dollar cost and no rebate this is the same number the
        # direct effective_cost call gave; with a rebate it is REopt's number.
        _psl, _, _, _pn = cost_curve(
            CostCurveTech(installed_cost_per_kw=inp.pv.installed_cost_per_kw,
                          tech_sizes_for_cost_curve=[],
                          federal_itc_fraction=inp.pv.federal_itc_fraction,
                          federal_rebate_per_kw=inp.pv.federal_rebate_per_kw,
                          macrs_option_years=inp.pv.macrs_option_years,
                          macrs_bonus_fraction=inp.pv.macrs_bonus_fraction,
                          macrs_itc_reduction=inp.pv.macrs_itc_reduction),
            analysis_years=f.analysis_years, owner_discount_rate=f.owner_discount_rate_fraction,
            owner_tax_rate=tax_own)
        pv_slope = _psl[0]

    # A fleet of one is the single-slot case, so both shapes run one code path.
    fts = list(inp.fuel_techs) if inp.fuel_techs else [inp.fuel_tech]
    NG = range(len(fts))
    ft = fts[0]                     # kept for the single-unit expressions below

    ft_slopes = {}
    # CHP (and Prime Generator, which REopt builds as a CHP) is priced through
    # cost_curve.jl: size-cost pairs and the full incentive table become a
    # piecewise curve. With a scalar cost and no incentives that curve is one
    # segment whose slope is effective_cost(round(cost)) -- REopt's own number.
    ft_curve = {}
    for g in NG:
        u = fts[g]
        ft_curve[g] = None
        if u.enabled and u.kind == "CHP":
            _pairs = bool(u.tech_sizes_for_cost_curve and u.installed_cost_curve_per_kw)
            _sl, _bx, _yi, _n = cost_curve(
                CostCurveTech(
                    installed_cost_per_kw=(list(u.installed_cost_curve_per_kw) if _pairs
                                           else u.installed_cost_per_kw),
                    tech_sizes_for_cost_curve=(list(u.tech_sizes_for_cost_curve) if _pairs else []),
                    federal_itc_fraction=u.federal_itc_fraction,
                    federal_rebate_per_kw=u.federal_rebate_per_kw,
                    state_ibi_fraction=u.state_ibi_fraction, state_ibi_max=u.state_ibi_max,
                    state_rebate_per_kw=u.state_rebate_per_kw, state_rebate_max=u.state_rebate_max,
                    utility_ibi_fraction=u.utility_ibi_fraction, utility_ibi_max=u.utility_ibi_max,
                    utility_rebate_per_kw=u.utility_rebate_per_kw,
                    utility_rebate_max=u.utility_rebate_max,
                    macrs_option_years=u.macrs_option_years,
                    macrs_bonus_fraction=u.macrs_bonus_fraction,
                    macrs_itc_reduction=u.macrs_itc_reduction),
                analysis_years=f.analysis_years,
                owner_discount_rate=f.owner_discount_rate_fraction,
                owner_tax_rate=tax_own)
            ft_slopes[g] = _sl[0]
            if needs_segments(_n, is_chp=True, min_allowable_kw=u.min_allowable_kw):
                ft_curve[g] = segments(_sl, _bx, _yi, _n, min_allowable_kw=u.min_allowable_kw)
            continue
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
    ft_th_slope, ft_th_icept = {}, {}
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
        # chp_constraints.jl:47-51 -- thermal output per kWe, affine like fuel.
        # Half == full (REopt's default) gives slope th/el and intercept 0.
        if u.kind == "CHP" and u.thermal_efficiency_full_load > 0:
            _th_half_eff = (u.thermal_efficiency_half_load
                            if u.thermal_efficiency_half_load is not None
                            else u.thermal_efficiency_full_load)
            _full = 1.0 / u.electric_efficiency_full_load * u.thermal_efficiency_full_load
            _half = 0.5 / half * _th_half_eff
            ft_th_slope[g] = (_full - _half) / (1.0 - 0.5)
            ft_th_icept[g] = _full - ft_th_slope[g] * 1.0
        else:
            ft_th_slope[g], ft_th_icept[g] = 0.0, 0.0
        # A binary is only needed when something actually references on/off.
        # At REopt defaults ic == 0.0 and turndown == 0, so none is created and
        # the model stays a pure LP -- identical to the pre-curve formulation.
        ft_needs_bin[g] = bool(u.enabled and (
            abs(ic) > 1.0e-7 or u.min_turn_down_fraction > 0.0
            or abs(ft_th_icept[g]) > 1.0e-7
            or u.start_cost > 0.0 or u.min_up_hours > 1 or u.min_down_hours > 1
            or u.om_cost_per_running_hour > 0.0 or u.max_starts_per_day is not None
            # a full outage has to show up as off, so the restart after it is
            # counted and priced like any other start -- which is what it is:
            # the unit cools, is worked on, and is started again
            or ((u.maintenance_events > 0
                 or u.maintenance_interval_running_hours > 0)
                and u.maintenance_duration_hours > 0
                and u.maintenance_pu >= 1.0)
            # the running-hours counter is driven by the on/off binary, so it
            # needs one whatever the outage does to capacity
            or (u.maintenance_interval_running_hours > 0
                and u.maintenance_duration_hours > 0)))

    sts = list(inp.storages) if inp.storages else [inp.storage]
    NB = range(len(sts))
    s = sts[0]                      # kept for the single-unit expressions below
    any_storage = any(b.enabled for b in sts)

    b_npc_kw, b_npc_kwh, b_npc_const = {}, {}, {}
    for b in NB:
        st = sts[b]
        if not st.enabled:
            b_npc_kw[b] = b_npc_kwh[b] = b_npc_const[b] = 0.0
            continue
        sched = macrs_schedule_for(st.macrs_option_years)
        # electric_storage.jl:482-522
        b_npc_kw[b] = effective_cost(
            itc_basis=st.installed_cost_per_kw,
            replacement_cost=(0.0 if st.inverter_replacement_year >= f.analysis_years else st.replace_cost_per_kw),
            replacement_year=st.inverter_replacement_year,
            discount_rate=f.owner_discount_rate_fraction, tax_rate=tax_own,
            itc=st.total_itc_fraction, macrs_schedule=sched,
            macrs_bonus_fraction=st.macrs_bonus_fraction, macrs_itc_reduction=st.macrs_itc_reduction,
            rebate_per_kw=st.total_rebate_per_kw,
        )
        b_npc_kwh[b] = effective_cost(
            itc_basis=st.installed_cost_per_kwh,
            replacement_cost=(0.0 if st.battery_replacement_year >= f.analysis_years else st.replace_cost_per_kwh),
            replacement_year=st.battery_replacement_year,
            discount_rate=f.owner_discount_rate_fraction, tax_rate=tax_own,
            itc=st.total_itc_fraction, macrs_schedule=sched,
            macrs_bonus_fraction=st.macrs_bonus_fraction, macrs_itc_reduction=st.macrs_itc_reduction,
        ) - st.total_rebate_per_kwh                    # electric_storage.jl:506
        b_npc_const[b] = effective_cost(
            itc_basis=st.installed_cost_constant,
            replacement_cost=(0.0 if st.cost_constant_replacement_year >= f.analysis_years
                              else st.replace_cost_constant),
            replacement_year=st.cost_constant_replacement_year,
            discount_rate=f.owner_discount_rate_fraction, tax_rate=tax_own,
            itc=st.total_itc_fraction, macrs_schedule=sched,
            macrs_bonus_fraction=st.macrs_bonus_fraction,
            macrs_itc_reduction=st.macrs_itc_reduction,
        ) if (st.installed_cost_constant or st.replace_cost_constant) else 0.0
    npc_kw, npc_kwh, npc_const = b_npc_kw[0], b_npc_kwh[0], b_npc_const[0]

    # ------------------------------------------------------------- variables
    m = pulp.LpProblem("REopt", pulp.LpMinimize)

    # PV upper bound from available space -- reopt_inputs.jl:620-645
    pv_space_max = inp.pv.max_kw
    if inp.pv.enabled:
        roof_max = (inp.roof_squarefeet * D_KW_PER_SQFT) if inp.roof_squarefeet else None
        land_max = (inp.land_acres / inp.pv.acres_per_kw) if inp.land_acres else None
        if inp.pv_location == "roof" and roof_max is not None:
            pv_space_max = min(pv_space_max, roof_max)
        elif inp.pv_location == "ground" and land_max is not None:
            pv_space_max = min(pv_space_max, land_max)
        elif inp.pv_location == "both" and roof_max is not None and land_max is not None:
            # REopt only restricts "both" when BOTH areas are given
            pv_space_max = min(pv_space_max, roof_max + land_max)

    # a technology that is switched off carries no size floor: its minimum is a
    # sizing bound on a tech being considered, not a commitment to build it
    dvPVsize = pulp.LpVariable("dvSize_PV", lowBound=inp.pv.min_kw if inp.pv.enabled else 0.0,
                               upBound=pv_space_max if inp.pv.enabled else 0.0)
    ftsize = {g: pulp.LpVariable(f"dvSize_FT_{g}",
                                 lowBound=(fts[g].existing_kw + fts[g].min_kw)
                                 if fts[g].enabled else 0.0,
                                 upBound=(fts[g].existing_kw + fts[g].max_kw)
                                 if fts[g].enabled else 0.0)
              for g in NG}
    # max_sizes = existing_kw + max_kw -- the big-M REopt uses for every CHP constraint
    ft_M = {g: fts[g].existing_kw + fts[g].max_kw for g in NG}
    # hourly availability: (custom maximum profile) x (1 - maintenance); None = 1
    ft_pf = {g: (list(fts[g].production_factor_series)[:H]
                 if (fts[g].enabled and fts[g].production_factor_series is not None) else None)
             for g in NG}
    # Aggregate alias: every expression downstream is written against the fleet
    # total, so the single-unit algebra is untouched when the fleet has one unit.
    dvFTsize = pulp.lpSum(ftsize[g] for g in NG)
    bpow = {b: pulp.LpVariable(f"dvStoragePower_{b}", lowBound=sts[b].min_kw,
                               upBound=sts[b].max_kw if sts[b].enabled else 0.0)
            for b in NB}
    ben = {b: pulp.LpVariable(f"dvStorageEnergy_{b}", lowBound=sts[b].min_kwh,
                              upBound=sts[b].max_kwh if sts[b].enabled else 0.0)
           for b in NB}
    # REopt gates the storage cost constant behind a binary so it is only paid
    # when a battery is actually built -- reopt.jl:430, storage_constraints.jl:151
    bconst = {b: pulp.LpVariable(f"binIncludeStorageCostConstant_{b}", cat="Binary")
              for b in NB}
    # Aggregate aliases so the rest of the model is unchanged for a bank of one.
    dvStoragePower = pulp.lpSum(bpow[b] for b in NB)
    dvStorageEnergy = pulp.lpSum(ben[b] for b in NB)
    binStorageConst = bconst[0]

    pvprod = {t: pulp.LpVariable(f"pvprod_{t}", lowBound=0) for t in T}      # PV -> load/storage
    pvcurt = {t: pulp.LpVariable(f"pvcurt_{t}", lowBound=0) for t in T}
    ftgen = {g: {t: pulp.LpVariable(f"ftprod_{g}_{t}", lowBound=0) for t in T}
             for g in NG}
    # ftgen is RATED production -- what O&M, fuel and the turndown floor see.
    # A unit allowed to curtail delivers ftgen - ftcurt to the load balance.
    ftcurt = {g: ({t: pulp.LpVariable(f"ftcurt_{g}_{t}", lowBound=0) for t in T}
                  if (fts[g].enabled and fts[g].can_curtail) else None) for g in NG}
    ftprod = {t: pulp.lpSum((ftgen[g][t] - ftcurt[g][t]) if ftcurt[g] is not None
                            else ftgen[g][t] for g in NG) for t in T}
    ftu = {g: ({t: pulp.LpVariable(f"ftON_{g}_{t}", cat="Binary") for t in T}
               if ft_needs_bin[g] else None) for g in NG}
    # Start / stop indicators. Continuous in [0, 1]: with u binary and
    # su - sd = u[t] - u[t-1] they take integral values at any optimum.
    ft_needs_uc = {g: bool(fts[g].enabled and (fts[g].start_cost > 0.0
                                               or fts[g].min_up_hours > 1
                                               or fts[g].min_down_hours > 1
                                               or fts[g].max_starts_per_day is not None))
                   for g in NG}
    ftsu = {g: ({t: pulp.LpVariable(f"ftSU_{g}_{t}", lowBound=0, upBound=1) for t in T}
                if ft_needs_uc[g] else None) for g in NG}
    ftsd = {g: ({t: pulp.LpVariable(f"ftSD_{g}_{t}", lowBound=0, upBound=1) for t in T}
                if ft_needs_uc[g] else None) for g in NG}
    # ---- scheduled maintenance (PyPSA's two variables) --------------------
    # A unit is maintainable when it has been given both a number of events and
    # a duration, and the horizon is long enough to hold one. Everything below
    # is skipped otherwise, so no variable and no constraint is created.
    ft_maint = {g: bool(fts[g].enabled
                        and (fts[g].maintenance_events > 0
                             or fts[g].maintenance_interval_running_hours > 0)
                        and fts[g].maintenance_duration_hours > 0
                        and fts[g].maintenance_duration_hours <= H)
                for g in NG}
    # which trigger each maintainable unit is on: running hours, or a count
    ft_mint = {g: bool(ft_maint[g]
                       and fts[g].maintenance_interval_running_hours > 0)
               for g in NG}
    # binary: an event STARTS in this hour
    ftms = {g: ({t: pulp.LpVariable(f"ftMS_{g}_{t}", cat="Binary") for t in T}
                if ft_maint[g] else None) for g in NG}
    # continuous in [0, 1]: the unit is IN an event this hour. It is pinned to
    # the starts by the coverage equality below, so it takes integral values.
    ftm = {g: ({t: pulp.LpVariable(f"ftM_{g}_{t}", lowBound=0, upBound=1) for t in T}
               if ft_maint[g] else None) for g in NG}
    # running hours banked since the last service, capped at the interval. Only
    # the running-hours trigger builds these; the count mode adds no variable.
    fth = {g: ({t: pulp.LpVariable(
        f"ftH_{g}_{t}", lowBound=0,
        upBound=float(fts[g].maintenance_interval_running_hours)) for t in T}
        if ft_mint[g] else None) for g in NG}
    bchg = {b: {t: pulp.LpVariable(f"chg_{b}_{t}", lowBound=0) for t in T} for b in NB}
    bgchg = {b: {t: pulp.LpVariable(f"gridchg_{b}_{t}", lowBound=0) for t in T} for b in NB}
    bdis = {b: {t: pulp.LpVariable(f"dis_{b}_{t}", lowBound=0) for t in T} for b in NB}
    bsoc = {b: {t: pulp.LpVariable(f"soc_{b}_{t}", lowBound=0) for t in T} for b in NB}
    def _soc_prev(b, t):
        if t > 0:
            return bsoc[b][t - 1]
        if sts[b].optimize_soc_init_fraction:
            return bsoc[b][T[-1]]
        return sts[b].soc_init_fraction * ben[b]

    chg = {t: pulp.lpSum(bchg[b][t] for b in NB) for t in T}       # into storage (AC)
    gridchg = {t: pulp.lpSum(bgchg[b][t] for b in NB) for t in T}
    dis = {t: pulp.lpSum(bdis[b][t] for b in NB) for t in T}       # out of storage (AC)
    soc = {t: pulp.lpSum(bsoc[b][t] for b in NB) for t in T}
    grid = {t: pulp.LpVariable(f"grid_{t}", lowBound=0) for t in T}
    unserved = {t: pulp.LpVariable(f"uns_{t}", lowBound=0) for t in T}
    export = {t: pulp.LpVariable(f"exp_{t}", lowBound=0) for t in T}

    # ---- existing boiler + CHP thermal credit ----
    # Off-grid forbids every heating key -- scenario.jl:85's offgrid_allowed_keys has
    # no SpaceHeatingLoad / DomesticHotWaterLoad / ExistingBoiler -- so REopt builds
    # CHP electric-only there (scenario.jl:531). Mirror that: no boiler off-grid.
    _heat_fuel = None if inp.off_grid_flag else inp.heating_fuel_mmbtu
    # Thermal load the boiler must serve, less whatever CHP recovers.
    thermal_load_mmbtu = ((_heat_fuel or 0.0) * inp.boiler_efficiency)
    if inp.heating_loads_kw is not None and not inp.off_grid_flag:
        thermal_load_mmbtu = sum(list(inp.heating_loads_kw)[:H]) / 293.07107
    chp_thermal = pulp.LpVariable("chp_thermal_mmbtu", lowBound=0)
    boiler_thermal = pulp.LpVariable("boiler_thermal_mmbtu", lowBound=0)

    tar = inp.tariff
    # A horizon shorter than a year keeps only the demand-period hours it contains.
    tou_periods = ([[t for t in hrs if t < H] for hrs in tar.tou_demand_periods]
                   if tar is not None else [])
    mon_periods = ([[t for t in hrs if t < H] for hrs in tar.monthly_demand_periods]
                   if tar is not None else [])
    tou_peak, mon_peak = [], []
    if tar is not None:
        tou_peak = [pulp.LpVariable(f"tou_{i}", lowBound=0) for i in range(len(tar.tou_demand_rates))]
        mon_peak = [pulp.LpVariable(f"mon_{i}", lowBound=0) for i in range(12)]

    # ----------------------------------------------------------- constraints
    # PV production ties to size (tech_constraints.jl: dvRatedProduction == prodfactor * dvSize)
    pf = inp.pv.production_factor or [0.0] * H
    for t in T:
        m += pvprod[t] + pvcurt[t] == pf[t] * dvPVsize * lvl_pv, f"pv_prod_{t}"
        if not inp.pv.can_curtail:
            m += pvcurt[t] == 0, f"pv_nocurt_{t}"
        for g in NG:
            _pf = ft_pf[g][t] if ft_pf[g] is not None else None
            _M = ft_M[g]
            # Rated production never exceeds installed size (tech_constraints.jl).
            # ftgen is what the unit delivers, pf x rated in REopt's terms, so an
            # availability below 1 scales the ceiling and the turndown floor alike.
            # Maintenance takes maintenance_pu of the ceiling away while an
            # event is on: at the default 1.0 the unit can produce nothing.
            # Written against the big-M rather than dvSize so the product stays
            # linear -- with min_kw == max_kw (a fixed nameplate, which is every
            # commitment scenario here) the two are the same number.
            _mnt = (fts[g].maintenance_pu * _M * ftm[g][t]) if ft_maint[g] else 0.0
            if _pf is None:
                m += ftgen[g][t] <= ftsize[g] - _mnt, f"ft_cap_{g}_{t}"
            else:
                m += ftgen[g][t] <= _pf * ftsize[g] - _pf * _mnt, f"ft_cap_{g}_{t}"
            if ft_needs_bin[g]:
                # generator_constraints.jl:22-24 -- off means exactly zero.
                # The big-M is the unit's own upper bound, as REopt uses max_sizes.
                m += ftgen[g][t] <= _M * ftu[g][t], f"ft_on_{g}_{t}"
                if fts[g].min_turn_down_fraction > 0:
                    # generator_constraints.jl:32-35 / chp_constraints.jl:198-201
                    if _pf is None:
                        m += (fts[g].min_turn_down_fraction * ftsize[g] - ftgen[g][t]
                              <= _M * (1 - ftu[g][t])), f"ft_turndown_{g}_{t}"
                    else:
                        m += (_pf * fts[g].min_turn_down_fraction * ftsize[g] - ftgen[g][t]
                              <= _pf * _M * (1 - ftu[g][t])), f"ft_turndown_{g}_{t}"
                    if fts[g].min_kw == fts[g].max_kw:
                        # Fixed nameplate: the same floor written without a big-M.
                        # A valid inequality -- the integer solutions are identical,
                        # the LP relaxation is tighter, branch and bound is shorter.
                        m += (ftgen[g][t] >= (1.0 if _pf is None else _pf)
                              * fts[g].min_turn_down_fraction * _M
                              * ftu[g][t]), f"ft_turndown_tight_{g}_{t}"

    # ---- scheduled maintenance: PyPSA's event count and coverage ----------
    for g in NG:
        if not ft_maint[g]:
            continue
        u = fts[g]
        E, D = int(u.maintenance_events), int(u.maintenance_duration_hours)
        who = u.name or u.label or f"unit {g}"
        if not ft_mint[g] and E * D > H:
            # Events cannot overlap: ftm is capped at 1, so two starts inside D
            # hours of each other would make the coverage equality
            # unsatisfiable. E events of D hours therefore need E*D hours of
            # horizon. Said here, with the numbers, rather than surfacing as a
            # bare "Infeasible".
            raise ValueError(
                f"{who}: {E} maintenance events of {D} h need {E * D} h but the "
                f"horizon is {H} h. Reduce the count or the duration, or solve "
                f"a longer horizon.")
        if ft_mint[g]:
            N = float(u.maintenance_interval_running_hours)
            # Worst case the unit runs every hour it is not in service, so the
            # horizon holds at most H/(N+D) whole cycles. Each costs D hours
            # out. If a cycle cannot fit at all the plan is unsatisfiable, and
            # saying so with the numbers beats a bare "Infeasible".
            if N + D > H and D > 0:
                raise ValueError(
                    f"{who}: a {N:g} running-hour service interval with a {D} h "
                    f"service needs {N + D:g} h to complete one cycle, but the "
                    f"horizon is {H} h. Lengthen the horizon, or raise the "
                    f"interval, or shorten the service.")
        # An event started at s occupies s .. s+D-1. The horizon is a closed
        # period everywhere else in this model (the state of charge wraps, so
        # does commitment when cyclic_commitment is on), so a window wraps too
        # rather than being forbidden near the end -- otherwise the last D-1
        # hours of the year could never hold a service and the count would be
        # unsatisfiable on a horizon that is an exact multiple of the spacing.
        wrap = inp.cyclic_commitment
        for t in T:
            cover = [ftms[g][(t - k) % H] for k in range(D)
                     if wrap or t - k >= 0]
            m += ftm[g][t] == pulp.lpSum(cover), f"ft_mcover_{g}_{t}"
        if not wrap:
            # a finite horizon cannot start an event it has no room to finish
            for t in T[max(0, H - D + 1):]:
                m += ftms[g][t] == 0, f"ft_mfit_{g}_{t}"
        if ft_mint[g]:
            # ---- the running-hours trigger -------------------------------
            # fth[t] is the running hours banked since the last service, read
            # at the end of hour t. Its upper bound is the interval itself, so
            # the cap IS the rule: the unit cannot bank more than N running
            # hours without a reset, and only a service resets it.
            #
            #   fth[t] <= fth[t-1] + u[t]              grows only by running
            #   fth[t] >= fth[t-1] + u[t] - M*ms[t]    and by exactly that,
            #                                          unless a service starts
            #   fth[t] <= M*(1 - ms[t])                a service zeroes it
            #
            # Together: ms[t]=0 pins fth[t] = fth[t-1] + u[t]; ms[t]=1 forces
            # fth[t] = 0. The count of services is whatever that forces -- an
            # outcome, not an input, which is the whole point. A unit that
            # never runs banks nothing and is never due.
            N = float(u.maintenance_interval_running_hours)
            BM = N + 1.0
            for t in T:
                if t > 0:
                    prev = fth[g][t - 1]
                elif inp.cyclic_commitment:
                    prev = fth[g][T[-1]]      # the clock wraps, like the SoC
                else:
                    prev = float(u.maintenance_hours_at_start)
                run = ftu[g][t] if ftu[g] is not None else 1.0
                m += fth[g][t] <= prev + run, f"ft_hgrow_{g}_{t}"
                m += (fth[g][t] >= prev + run - BM * ftms[g][t],
                      f"ft_hkeep_{g}_{t}")
                m += fth[g][t] <= BM * (1 - ftms[g][t]), f"ft_hreset_{g}_{t}"
        elif u.maintenance_spacing == "even" and E > 0:
            # one event per equal segment: a service plan, not a free choice of
            # E hours. The solver still picks the hour inside each segment.
            edges = [round(i * H / E) for i in range(E + 1)]
            for i in range(E):
                lo, hi = edges[i], edges[i + 1]
                m += (pulp.lpSum(ftms[g][t] for t in T[lo:hi]) == 1,
                      f"ft_mseg_{g}_{i}")
        else:
            m += pulp.lpSum(ftms[g][t] for t in T) == E, f"ft_mcount_{g}"
        if u.maintenance_pu >= 1.0 and ft_needs_bin[g]:
            # fully out means off, so the restart is a start like any other
            for t in T:
                m += ftu[g][t] <= 1 - ftm[g][t], f"ft_moff_{g}_{t}"

    # ---- beyond REopt: spill, starts, minimum up and down time ----
    for g in NG:
        if ftcurt[g] is not None:
            for t in T:
                m += ftcurt[g][t] <= ftgen[g][t], f"ft_curt_{g}_{t}"
        if ftsu[g] is None:
            continue
        MU = max(1, int(fts[g].min_up_hours))
        MD = max(1, int(fts[g].min_down_hours))
        cyc = inp.cyclic_commitment
        for t in T:
            # cyclic: the period is closed, like the state-of-charge balance.
            # finite: the unit enters the horizon in its stated initial state and
            # the look-back windows stop at hour 0 (uc convention).
            if t == 0:
                prev = ftu[g][T[-1]] if cyc else (1.0 if fts[g].initial_on else 0.0)
            else:
                prev = ftu[g][t - 1]
            m += ftsu[g][t] - ftsd[g][t] == ftu[g][t] - prev, f"ft_switch_{g}_{t}"
            back = (lambda k: (t - k) % H) if cyc else (lambda k: t - k)
            if MU > 1:
                m += (ftu[g][t] >= pulp.lpSum(ftsu[g][back(k)] for k in range(MU)
                                              if cyc or t - k >= 0)), f"ft_minup_{g}_{t}"
            if MD > 1:
                m += (1 - ftu[g][t] >= pulp.lpSum(ftsd[g][back(k)] for k in range(MD)
                                                  if cyc or t - k >= 0)), f"ft_mindown_{g}_{t}"
        # starts per calendar day. su >= u[t] - u[t-1] >= 0 at every real start,
        # so capping the sum of su caps the real starts; su stays continuous.
        if fts[g].max_starts_per_day is not None:
            cap = max(0, int(fts[g].max_starts_per_day))
            for d in range((H + 23) // 24):
                m += (pulp.lpSum(ftsu[g][t] for t in T[d * 24:(d + 1) * 24]) <= cap
                      ), f"ft_maxstarts_{g}_{d}"

    # Land use: REopt adds LandConstraint only alongside CST (tech_constraints.jl:23);
    # for PV alone the space limit is the max size set above (reopt_inputs.jl:620-645),
    # which for "both" is roof + land -- a separate land cap would cut that to land only.

    # Storage sizing -- storage_constraints.jl:2-20, per unit
    for b in NB:
        st = sts[b]
        if st.enabled:
            for t in T:
                m += bdis[b][t] <= bpow[b], f"dis_pow_{b}_{t}"
                m += bchg[b][t] + bgchg[b][t] <= bpow[b], f"chg_pow_{b}_{t}"
                m += bsoc[b][t] >= st.soc_min_fraction * ben[b], f"soc_min_{b}_{t}"
                m += bsoc[b][t] <= ben[b], f"soc_max_{b}_{t}"
            if st.min_duration_hours > 0:
                m += ben[b] >= st.min_duration_hours * bpow[b], f"dur_min_{b}"
            if st.max_duration_hours < 1e5:
                m += ben[b] <= st.max_duration_hours * bpow[b], f"dur_max_{b}"
            if not st.can_grid_charge:
                for t in T:
                    m += bgchg[b][t] == 0, f"nogridchg_{b}_{t}"
            # storage_constraints.jl:151 -- dvStorageEnergy <= max_kwh * bin
            if b_npc_const[b]:
                m += ben[b] <= st.max_kwh * bconst[b], f"storage_const_bin_{b}"
            # SOC dynamics -- storage_constraints.jl:39-73 (general dispatch).
            # (4a): the state before hour 1 is soc_init_fraction x energy and the
            # last state is free -- REopt's default. With optimize_soc_init_fraction
            # the first state is instead tied to the last one (a closed cycle).
            for t in T:
                prev = _soc_prev(b, t)
                m += bsoc[b][t] == prev + st.charge_efficiency * bchg[b][t] \
                     + st.grid_charge_efficiency * bgchg[b][t] \
                     - bdis[b][t] / st.discharge_efficiency, f"soc_bal_{b}_{t}"
            # (4l): "Custom hourly state of charge" -- fixed series +- tolerance
            if st.fixed_soc_series_fraction is not None:
                _fx = list(st.fixed_soc_series_fraction)[:H]
                _tol = st.fixed_soc_series_fraction_tolerance
                for t in T:
                    m += bsoc[b][t] <= (_tol + _fx[t]) * ben[b], f"soc_fix_hi_{b}_{t}"
                    m += bsoc[b][t] >= (-_tol + _fx[t]) * ben[b], f"soc_fix_lo_{b}_{t}"
        else:
            for t in T:
                m += bchg[b][t] == 0, f"nochg_{b}_{t}"
                m += bgchg[b][t] == 0, f"nogchg_{b}_{t}"
                m += bdis[b][t] == 0, f"nodis_{b}_{t}"
                m += bsoc[b][t] == 0, f"nosoc_{b}_{t}"

    # Electric load balance -- load_balance.jl:3
    can_export = (not inp.off_grid_flag) and inp.compensation_type != "no_compensation"
    # NOTE: net_metering_limit_kw caps the capacity that may PARTICIPATE in the
    # net metering agreement -- it does NOT cap system size. Verified against
    # REopt run 53747394 (limit 1,000 kW, PV sized to the 1,200 kW roof limit).
    # REopt puts export above the limit in a separate EXC bin at a lower rate;
    # that bin is not modelled here, so all export is credited at the NEM rate.
    for t in T:
        m += (pvprod[t] + ftprod[t] + dis[t] + grid[t] + unserved[t]
              == loads[t] + chg[t] + gridchg[t] + export[t]), f"load_bal_{t}"
        if not can_export:
            m += export[t] == 0, f"noexport_{t}"

    _or_req, _or_vars = [], None
    if inp.off_grid_flag:
        for t in T:
            m += grid[t] == 0, f"nogrid_{t}"
            m += gridchg[t] == 0, f"nogridchg2_{t}"
        # min_load_met_annual_fraction -- ElectricLoad off-grid input
        m += pulp.lpSum(unserved[t] for t in T) <= (1 - inp.min_load_met_annual_fraction) * sum(loads), "min_load_met"

        # ---- operating reserve, operating_reserve_constraints.jl ----
        # Off-grid only. PV both requires reserve on what it serves and can
        # provide reserve from its headroom (techs.jl:368-371); the fuel tech
        # and the battery provide it.
        f_load = inp.operating_reserve_required_fraction
        f_pv = inp.pv.operating_reserve_required_fraction if inp.pv.enabled else 0.0
        f_ft = ft.operating_reserve_required_fraction if ft.enabled else 0.0  # noqa: F841
        if f_load > 0 or f_pv > 0:
            or_pv = {t: pulp.LpVariable(f"or_pv_{t}", lowBound=0) for t in T}
            or_ft = {t: pulp.LpVariable(f"or_ft_{t}", lowBound=0) for t in T}
            or_bat = {t: pulp.LpVariable(f"or_bat_{t}", lowBound=0) for t in T}
            for t in T:
                # 1. production going to load, per tech (storage and curtailment removed)
                pv_to_load = pvprod[t] - chg[t] - export[t]
                # 2. reserve required by the requiring techs and by served load
                required = f_pv * pv_to_load + f_load * (loads[t] - unserved[t])

                # 4. reserve a providing tech can offer out of its own headroom
                if inp.pv.enabled and f_pv < 1.0:
                    m += or_pv[t] <= (pf[t] * dvPVsize * lvl_pv - pv_to_load) * (1 - f_pv), f"or_pv_{t}"
                else:
                    m += or_pv[t] == 0, f"or_pv_{t}"
                _prov = [g for g in NG if fts[g].enabled
                         and fts[g].operating_reserve_required_fraction == 0.0]
                if _prov:
                    m += or_ft[t] <= pulp.lpSum(ftsize[g] - ftgen[g][t] for g in _prov), f"or_ft_{t}"
                else:
                    m += or_ft[t] == 0, f"or_ft_{t}"
                # 3. battery: bounded by usable stored energy and by its power rating
                if any_storage:
                    m += or_bat[t] <= pulp.lpSum(
                        _soc_prev(b, t)
                        - sts[b].soc_min_fraction * ben[b]
                        - bdis[b][t] / sts[b].discharge_efficiency
                        for b in NB if sts[b].enabled), f"or_bat_e_{t}"
                    m += or_bat[t] <= pulp.lpSum(
                        bpow[b] - bdis[b][t] / sts[b].discharge_efficiency
                        for b in NB if sts[b].enabled), f"or_bat_p_{t}"
                else:
                    m += or_bat[t] == 0, f"or_bat_{t}"
                # 6. provided >= required
                m += or_pv[t] + or_ft[t] + or_bat[t] >= required, f"or_bal_{t}"
                _or_req.append(required)
            _or_vars = (or_pv, or_ft, or_bat)
    else:
        for t in T:
            m += unserved[t] == 0, f"noun_{t}"

    # Peak demand tracking for demand charges -- electric_tariff / ElectricUtility
    if tar is not None:
        for i, hrs in enumerate(tou_periods):
            for t in hrs:
                m += tou_peak[i] >= grid[t] + gridchg[t], f"toupk_{i}_{t}"
        for mo in range(12):
            for t in mon_periods[mo]:
                m += mon_peak[mo] >= grid[t] + gridchg[t], f"monpk_{mo}_{t}"

    # ---- segmented CHP cost curve -- cost_curve_constraints.jl (7f)-(7h) ----
    # A unit on a cost curve (or with a minimum non-zero size) buys its new
    # capacity on exactly one segment. REopt's last breakpoint is a 1e10
    # sentinel; it is clamped to the unit's max_kw here, which leaves the
    # feasible set unchanged (purchase <= max_kw anyway) and keeps the big-M sane.
    ft_seg, ft_purch = {}, {}
    for g in NG:
        u = fts[g]
        if not u.enabled:
            continue
        if ft_curve[g] is not None:
            _z = [pulp.LpVariable(f"dvSegmentSystemSize_{g}_{k}", lowBound=0)
                  for k in range(len(ft_curve[g]))]
            _y = [pulp.LpVariable(f"binSegment_{g}_{k}", cat="Binary")
                  for k in range(len(ft_curve[g]))]
            for k, sg in enumerate(ft_curve[g]):
                m += _z[k] >= sg["min"] * _y[k], f"seg_min_{g}_{k}"
                m += _z[k] <= min(sg["max"], u.max_kw) * _y[k], f"seg_max_{g}_{k}"
            m += pulp.lpSum(_z) == ftsize[g] - u.existing_kw, f"seg_sum_{g}"
            m += pulp.lpSum(_y) <= 1, f"seg_one_{g}"
            ft_seg[g] = (_z, _y)
        elif u.existing_kw > 0:
            # tech_constraints.jl: dvPurchaseSize >= dvSize - existing_kw
            ft_purch[g] = pulp.LpVariable(f"dvPurchaseSize_FT_{g}", lowBound=0)
            m += ft_purch[g] >= ftsize[g] - u.existing_kw, f"purchase_{g}"

    # ---- production based incentive -- production_incentive_constraints.jl ----
    _pbi = []
    for g in NG:
        u = fts[g]
        if not (u.enabled and u.production_incentive_per_kwh > 0):
            continue
        _pwf_pbi = annuity(int(u.production_incentive_years), 0.0, f.owner_discount_rate_fraction)
        _dv = pulp.LpVariable(f"dvProdIncent_{g}", lowBound=0)
        _bb = pulp.LpVariable(f"binProdIncent_{g}", cat="Binary")
        m += _dv <= _bb * u.production_incentive_max_benefit * _pwf_pbi, f"pbi_ub_{g}"
        m += (_dv <= u.production_incentive_per_kwh * _pwf_pbi
              * pulp.lpSum(ftgen[g][t] for t in T)), f"pbi_prod_{g}"
        m += ftsize[g] <= u.production_incentive_max_kw + ft_M[g] * (1 - _bb), f"pbi_size_{g}"
        _pbi.append(_dv)
    TotalProductionIncentive = pulp.lpSum(_pbi) if _pbi else 0.0

    # ---- electrical load following -- chp_constraints.jl add_chp_electrical_... ----
    for g in NG:
        u = fts[g]
        if not (u.enabled and u.follow_electrical_load):
            continue
        _Me = 2 * max(ft_M[g], max(loads) if loads else 0.0)
        _be = {t: pulp.LpVariable(f"binCHPSizeExceedsElectricLoad_{g}_{t}", cat="Binary") for t in T}
        for t in T:
            _p = ft_pf[g][t] if ft_pf[g] is not None else 1.0
            m += _Me * _be[t] >= _p * ftsize[g] - loads[t], f"fel_a_{g}_{t}"
            m += _Me * _be[t] <= _Me - (loads[t] - _p * ftsize[g]), f"fel_b_{g}_{t}"
            if _p > 0:
                # rated >= size - M b, delivered = pf x rated
                m += ftgen[g][t] >= _p * ftsize[g] - _p * _Me * _be[t], f"fel_c_{g}_{t}"
            m += grid[t] + gridchg[t] <= _Me * (1 - _be[t]), f"fel_d_{g}_{t}"

    # ---- hourly heat balance -- thermal_tech_constraints.jl / chp_constraints.jl ----
    # REopt balances heat in every hour: CHP heat serves that hour's load or is
    # wasted; the existing boiler makes up the rest. The annual aggregate this
    # replaces let July CHP heat pay down January boiler fuel.
    _hl = None if inp.off_grid_flag else (list(inp.heating_loads_kw)[:H]
                                          if inp.heating_loads_kw is not None else None)
    _heat_units = [g for g in NG if fts[g].enabled and fts[g].kind == "CHP"
                   and fts[g].thermal_efficiency_full_load > 0]
    boil_h, chpheat_h, thI = {}, {}, {}
    boiler_max_kw = 0.0
    _bsize = None
    ExistingBoilerCapex = 0.0
    if _hl is not None:
        boiler_max_kw = inp.boiler_max_thermal_factor_on_peak_load * (max(_hl) if _hl else 0.0)
        boil_h = {t: pulp.LpVariable(f"boilerHeat_{t}", lowBound=0, upBound=boiler_max_kw) for t in T}
        if _heat_units:
            chpheat_h = {t: pulp.LpVariable(f"chpHeatToLoad_{t}", lowBound=0) for t in T}
            for g in _heat_units:
                if abs(ft_th_icept[g]) > 1.0e-7:
                    _ic = ft_th_icept[g]
                    thI[g] = {t: pulp.LpVariable(f"dvHeatingProductionYIntercept_{g}_{t}") for t in T}
                    for t in T:
                        m += thI[g][t] <= _ic * ftsize[g], f"thI_a1_{g}_{t}"
                        m += thI[g][t] <= _ic * ft_M[g] * ftu[g][t], f"thI_a2_{g}_{t}"
                        m += (thI[g][t] >= _ic * ftsize[g]
                              - _ic * ft_M[g] * (1 - ftu[g][t])), f"thI_b_{g}_{t}"
        for t in T:
            m += (boil_h[t] + (chpheat_h[t] if chpheat_h else 0.0) == _hl[t]), f"heat_bal_{t}"
            if chpheat_h:
                # heat to load <= heat produced; the difference is dvProductionToWaste
                m += chpheat_h[t] <= pulp.lpSum(
                    ft_th_slope[g] * ftgen[g][t] + (thI[g][t] if g in thI else 0.0)
                    for g in _heat_units), f"chp_heat_{t}"
        # heating load following (beta in the web tool)
        for g in _heat_units:
            u = fts[g]
            if not u.follow_heating_load:
                continue
            _sl, _ic = ft_th_slope[g], ft_th_icept[g]
            _Mh = 2 * max(ft_M[g] * (abs(_sl) + abs(_ic)), max(_hl) if _hl else 0.0, 1.0)
            _bh = {t: pulp.LpVariable(f"binCHPSizeExceedsHeatingLoad_{g}_{t}", cat="Binary") for t in T}
            for t in T:
                _p = ft_pf[g][t] if ft_pf[g] is not None else 1.0
                _cap = (_p * _sl + (_ic if _p > 0.0 else 0.0)) * ftsize[g]
                m += _Mh * _bh[t] >= _cap - _hl[t], f"fhl_a_{g}_{t}"
                m += _Mh * _bh[t] <= _Mh - (_hl[t] - _cap), f"fhl_b_{g}_{t}"
                if _p > 0:
                    m += ftgen[g][t] >= _p * ftsize[g] - _p * ft_M[g] * _bh[t], f"fhl_c_{g}_{t}"
                m += boil_h[t] <= _Mh * (1 - _bh[t]), f"fhl_d_{g}_{t}"
        # existing boiler capital cost -- existing_boiler.jl:109-114, thermal_tech_constraints.jl:313
        _b_per_kw = 0.0
        if inp.boiler_installed_cost_per_mmbtu_per_hour and not inp.boiler_installed_cost_dollars:
            _b_per_kw = (inp.boiler_installed_cost_per_mmbtu_per_hour / 293.07107
                         * inp.boiler_max_thermal_factor_on_peak_load)
        if _b_per_kw or inp.boiler_installed_cost_dollars:
            _bsize = pulp.LpVariable("dvSize_ExistingBoiler", lowBound=0, upBound=boiler_max_kw)
            for t in T:
                m += boil_h[t] <= _bsize, f"boiler_size_{t}"
            ExistingBoilerCapex = _b_per_kw * _bsize
            if inp.boiler_installed_cost_dollars:
                _bin_b = pulp.LpVariable("binExistingBoiler", cat="Binary")
                m += _bsize <= _bin_b * max(boiler_max_kw, 1.0), "boiler_bin"
                ExistingBoilerCapex = ExistingBoilerCapex + inp.boiler_installed_cost_dollars * _bin_b
        # the annual reporting variables become sums of the hourly ones
        m += chp_thermal == (pulp.lpSum(chpheat_h[t] for t in T) / 293.07107
                             if chpheat_h else 0.0), "chp_thermal_sum"
        m += boiler_thermal == pulp.lpSum(boil_h[t] for t in T) / 293.07107, "boiler_thermal_sum"

    # Thermal balance: boiler covers whatever CHP does not.
    elif thermal_load_mmbtu > 0:
        m += boiler_thermal + chp_thermal == thermal_load_mmbtu, "thermal_balance"
        _heat_units = [g for g in NG if fts[g].enabled and fts[g].kind == "CHP"
                       and fts[g].thermal_efficiency_full_load > 0]
        if _heat_units:
            # recovered heat scales with electric output by the efficiency ratio
            m += chp_thermal <= pulp.lpSum(
                pulp.lpSum(ftgen[g][t] for t in T)
                * (fts[g].thermal_efficiency_full_load / fts[g].electric_efficiency_full_load)
                / 293.07107 for g in _heat_units), "chp_heat"
        else:
            m += chp_thermal == 0, "no_chp_heat"
    else:
        m += chp_thermal == 0, "no_thermal_load"
        m += boiler_thermal == 0, "no_boiler"

    # ------------------------------------------------------------- objective
    # reopt.jl:511 -- Costs
    def _ft_capex(g):
        if g in ft_seg:
            _z, _y = ft_seg[g]
            return pulp.lpSum(sg["slope"] * _z[k] + sg["yint"] * _y[k]
                              for k, sg in enumerate(ft_curve[g]))
        if g in ft_purch:
            return ft_slopes[g] * ft_purch[g]
        return ft_slopes[g] * ftsize[g]
    TotalTechCapCosts = pv_slope * dvPVsize + pulp.lpSum(_ft_capex(g) for g in NG)
    TotalStorageCapCosts = pulp.lpSum(
        b_npc_kw[b] * bpow[b] + b_npc_kwh[b] * ben[b] + b_npc_const[b] * bconst[b]
        for b in NB)

    TotalPerUnitSizeOMCosts = pwf_om * (
        inp.pv.om_cost_per_kw * dvPVsize
        + pulp.lpSum(fts[g].om_cost_per_kw * ftsize[g] for g in NG))
    # reopt.jl:422-433 -- ElectricStorageCapCost is the FULL initial cost basis
    # (per-kW + per-kWh + the cost constant), and O&M is a fraction of that.
    if any_storage:
        ElectricStorageCapCost = pulp.lpSum(
            sts[b].installed_cost_per_kw * bpow[b]
            + sts[b].installed_cost_per_kwh * ben[b]
            + (sts[b].installed_cost_constant * bconst[b] if b_npc_const[b] else 0.0)
            for b in NB if sts[b].enabled)
        # O&M is a per-unit fraction of that unit's own basis
        ElectricStorageOMCost = pwf_om * pulp.lpSum(
            sts[b].om_cost_fraction_of_installed_cost
            * (sts[b].installed_cost_per_kw * bpow[b]
               + sts[b].installed_cost_per_kwh * ben[b]
               + (sts[b].installed_cost_constant * bconst[b] if b_npc_const[b] else 0.0))
            for b in NB if sts[b].enabled)
    else:
        ElectricStorageCapCost = 0.0
        ElectricStorageOMCost = 0.0
    def _rated_sum(g):
        # delivered = pf x rated, so rated = delivered / pf wherever pf > 0
        if ft_pf[g] is None:
            return pulp.lpSum(ftgen[g][t] for t in T)
        return pulp.lpSum(ftgen[g][t] * (1.0 / ft_pf[g][t]) for t in T if ft_pf[g][t] > 0)
    TotalPerUnitProdOMCosts = pwf_om * pulp.lpSum(
        fts[g].om_cost_per_kwh * _rated_sum(g) for g in NG)

    # Fuel, per unit. REopt writes the y-intercept of the fuel curve two ways,
    # and the difference is a whole factor of the unit's size:
    #
    #   Generator  generator_constraints.jl:8-12
    #              usage = slope * production + intercept * binGenIsOnInTS
    #   CHP        chp_constraints.jl:18-34
    #              usage = slope * production + dvFuelBurnYIntercept, with
    #              dvFuelBurnYIntercept >= intercept * dvSize - max_size * (1 - bin)
    #
    # fuel_slope_and_intercept (utils.jl:645) returns that intercept per kW of
    # RATED capacity, which is why CHP scales it by dvSize and the generator
    # does not. Here the product size x on is linearised exactly (dvOnCapacity),
    # so the term is right whether the unit is fixed or being sized, and for a
    # negative intercept too -- REopt's own condition is abs(intercept) > 1e-7
    # (chp_constraints.jl:18), not intercept > 0. At REopt's default (half ==
    # full load) the intercept is 0 and both forms collapse to the linear term.
    ft_on_kw = {}
    for g in NG:
        u = fts[g]
        if (u.enabled and u.kind == "CHP" and ft_needs_bin[g]
                and abs(ft_icept[g]) > 1.0e-7 and inp.fuel_intercept_basis != "rated"):
            _M = ft_M[g]
            ft_on_kw[g] = {t: pulp.LpVariable(f"dvOnCapacity_{g}_{t}", lowBound=0,
                                              upBound=_M) for t in T}
            for t in T:
                z, on = ft_on_kw[g][t], ftu[g][t]
                m += z <= ftsize[g], f"onkw_a_{g}_{t}"
                m += z <= _M * on, f"onkw_b_{g}_{t}"
                m += z >= ftsize[g] - _M * (1 - on), f"onkw_c_{g}_{t}"
    ft_fuel_units = {}
    TotalFuelCosts = 0.0
    for g in NG:
        u = fts[g]
        if not u.enabled:
            ft_fuel_units[g] = 0.0
            continue
        usage = ft_slope_fuel[g] * pulp.lpSum(ftgen[g][t] for t in T)
        if g in ft_on_kw:
            usage = usage + ft_icept[g] * pulp.lpSum(ft_on_kw[g][t] for t in T)
        elif ft_needs_bin[g] and abs(ft_icept[g]) > 1.0e-7:
            coef = ft_icept[g]
            if inp.fuel_intercept_basis == "rated":
                if u.min_kw != u.max_kw:
                    raise ValueError(
                        "fuel_intercept_basis='rated' needs a fixed-size unit "
                        "(min_kw == max_kw); unit %d is sized by the optimizer." % g)
                coef *= u.max_kw
            usage = usage + coef * pulp.lpSum(ftu[g][t] for t in T)
        ft_fuel_units[g] = usage
        _pwf = pwf_fuel_chp if u.kind == "CHP" else pwf_fuel
        if u.kind == "CHP" and u.fuel_cost_per_mmbtu_monthly:
            # "CHP fuel cost varies by month?" -- each hour priced at its month
            _mp = [u.fuel_cost_per_mmbtu_monthly[_MONTH_OF_HOUR[t]] for t in T]
            _hourly = (pulp.lpSum(_mp[t] * ft_slope_fuel[g] * ftgen[g][t] for t in T))
            if g in ft_on_kw:
                _hourly = _hourly + pulp.lpSum(_mp[t] * ft_icept[g] * ft_on_kw[g][t] for t in T)
            elif ft_needs_bin[g] and abs(ft_icept[g]) > 1.0e-7:
                _c = ft_icept[g] * (u.max_kw if inp.fuel_intercept_basis == "rated" else 1.0)
                _hourly = _hourly + pulp.lpSum(_mp[t] * _c * ftu[g][t] for t in T)
            TotalFuelCosts = TotalFuelCosts + _pwf * _hourly
        else:
            price = (u.fuel_cost_per_gallon if u.kind == "Generator" else u.fuel_cost_per_mmbtu)
            TotalFuelCosts = TotalFuelCosts + _pwf * price * usage

    if tar is not None:
        # Export credit: net metering pays the retail energy rate, net billing the
        # wholesale rate. REopt models these as the NEM / WHL export bins.
        if inp.compensation_type == "net_metering":
            export_rate = list(tar.energy_cost_per_kwh)
        elif inp.compensation_type in ("net_billing", "net_meter_net_bill"):
            export_rate = [inp.wholesale_rate] * H
        else:
            export_rate = [0.0] * H
        energy_cost = (pulp.lpSum(tar.energy_cost_per_kwh[t] * (grid[t] + gridchg[t]) for t in T)
                       - pulp.lpSum(export_rate[t] * export[t] for t in T))
        demand_cost = pulp.lpSum(tar.tou_demand_rates[i] * tou_peak[i] for i in range(len(tou_peak))) \
                    + pulp.lpSum(tar.monthly_demand_rates[mo] * mon_peak[mo] for mo in range(12))
        fixed_cost = tar.fixed_monthly_charge * 12
        TotalElecBill = pwf_e * (energy_cost + demand_cost + fixed_cost)
    else:
        TotalElecBill = 0.0

    # Existing boiler fuel, tax deductible for the offtaker like other fuel
    ExistingBoilerFuelCost = (
        pwf_boiler * inp.existing_boiler_fuel_cost_per_mmbtu
        * (boiler_thermal / inp.boiler_efficiency)) if thermal_load_mmbtu > 0 else 0.0
    if boil_h and inp.boiler_fuel_cost_per_mmbtu_monthly:
        ExistingBoilerFuelCost = pwf_boiler * pulp.lpSum(
            inp.boiler_fuel_cost_per_mmbtu_monthly[_MONTH_OF_HOUR[t]]
            * boil_h[t] / (inp.boiler_efficiency * 293.07107) for t in T)

    # Beyond REopt. Built only when some unit carries the cost, so a scenario
    # without them adds a literal 0.0 and the objective is unchanged.
    _start_terms = [fts[g].start_cost * pulp.lpSum(ftsu[g][t] for t in T)
                    for g in NG if ftsu[g] is not None and fts[g].start_cost > 0.0]
    TotalStartCosts = pwf_om * pulp.lpSum(_start_terms) if _start_terms else 0.0
    _hour_terms = [fts[g].om_cost_per_running_hour * pulp.lpSum(ftu[g][t] for t in T)
                   for g in NG if ftu[g] is not None and fts[g].om_cost_per_running_hour > 0.0]
    TotalRunHourCosts = pwf_om * pulp.lpSum(_hour_terms) if _hour_terms else 0.0
    _svc_terms = [fts[g].maintenance_cost_per_event
                  * pulp.lpSum(ftms[g][t] for t in T)
                  for g in NG if ftms[g] is not None
                  and fts[g].maintenance_cost_per_event > 0.0]
    TotalServiceCosts = pwf_om * pulp.lpSum(_svc_terms) if _svc_terms else 0.0
    _cycle_terms = [sts[b].discharge_cost_per_kwh * pulp.lpSum(bdis[b][t] for t in T)
                    for b in NB if sts[b].enabled and sts[b].discharge_cost_per_kwh > 0.0]
    TotalCyclingCosts = pwf_om * pulp.lpSum(_cycle_terms) if _cycle_terms else 0.0
    _standby = [fts[g].standby_rate_per_kw_per_month * ftsize[g]
                for g in NG if fts[g].enabled and fts[g].standby_rate_per_kw_per_month > 0]
    TotalCHPStandbyCharges = pwf_e * 12 * pulp.lpSum(_standby) if _standby else 0.0

    m += (TotalTechCapCosts + TotalStorageCapCosts
          + (TotalPerUnitSizeOMCosts + ElectricStorageOMCost) * (1 - tax_own)
          + TotalPerUnitProdOMCosts * (1 - tax_own)
          + TotalFuelCosts * (1 - tax_off)
          + TotalElecBill * (1 - tax_off)
          + ExistingBoilerFuelCost * (1 - tax_off)
          + (TotalStartCosts + TotalCyclingCosts + TotalRunHourCosts
             + TotalServiceCosts) * (1 - tax_own)
          # reopt.jl:525 -- CHP standby charge, deductible for the offtaker
          + TotalCHPStandbyCharges * (1 - tax_off)
          # reopt.jl:531 -- production incentive, taxable to the owner
          - TotalProductionIncentive * (1 - tax_own)
          # reopt.jl:582 -- existing boiler capital cost, never incentivised
          + ExistingBoilerCapex), "Costs"

    # ---------------------------------------------------------------- solve
    _hopts = dict(msg=msg, timeLimit=time_limit)
    if mip_gap is not None:
        _hopts["gapRel"] = mip_gap
    solver = pulp.HiGHS(**_hopts)
    status = m.solve(solver)
    # Reporting only: how solved is "solved". pulp keeps the HiGHS instance on the
    # problem; the MIP gap and dual bound turn a time-limited run into a range.
    solver_info = {}
    _hs = getattr(m, "solverModel", None)
    if _hs is not None:
        try:
            _hi = _hs.getInfo()
            solver_info = {
                "model_status": _hs.modelStatusToString(_hs.getModelStatus()),
                "mip_gap": float(_hi.mip_gap),
                "mip_dual_bound": float(_hi.mip_dual_bound),
            }
        except Exception:  # an LP, or an older highspy
            solver_info = {}

    v = lambda x: float(pulp.value(x) or 0.0)
    pv_kw, ft_kw = v(dvPVsize), v(dvFTsize)
    # per-unit storage basis, so a bank of several batteries is costed
    # against each unit's own prices rather than the first unit's
    def _bat_basis():
        tot = 0.0
        for b in NB:
            if not sts[b].enabled:
                continue
            e = v(ben[b])
            tot += (sts[b].installed_cost_per_kw * v(bpow[b])
                    + sts[b].installed_cost_per_kwh * e
                    + (sts[b].installed_cost_constant if e > 1e-6 else 0.0))
        return tot
    bat_basis = _bat_basis()

    def _ft_upfront(g):
        """CHPCapexNoIncentives: the size-cost curve without incentives."""
        u = fts[g]
        if not u.enabled:
            return 0.0
        purchase = max(0.0, v(ftsize[g]) - u.existing_kw)
        if g in ft_seg and u.tech_sizes_for_cost_curve and u.installed_cost_curve_per_kw:
            c, sz = list(u.installed_cost_curve_per_kw), list(u.tech_sizes_for_cost_curve)
            sl, yi = [c[0]], [0.0]
            for k in range(1, len(sz)):
                ts = float(round((c[k] * sz[k] - c[k - 1] * sz[k - 1]) / (sz[k] - sz[k - 1])))
                yi.append(float(round(c[k - 1] * sz[k - 1] - ts * sz[k - 1])))
                sl.append(ts)
            sl.append(c[-1])
            yi.append(0.0)
            _z, _y = ft_seg[g]
            return sum(sl[k] * v(_z[k]) + yi[k] * v(_y[k]) for k in range(min(len(sl), len(_z))))
        return u.installed_cost_per_kw * purchase
    bat_om_y1 = sum(
        sts[b].om_cost_fraction_of_installed_cost
        * (sts[b].installed_cost_per_kw * v(bpow[b])
           + sts[b].installed_cost_per_kwh * v(ben[b])
           + (sts[b].installed_cost_constant if v(ben[b]) > 1e-6 else 0.0))
        for b in NB if sts[b].enabled)
    def _was_off(g, t):
        """State in the hour before t, on the same seam rule the model used."""
        if t == 0 and not inp.cyclic_commitment:
            return not fts[g].initial_on
        return v(ftu[g][(t - 1) % H]) < 0.5

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
            "capacity_factor": (kwh / (kw * H)) if kw > 1e-9 else 0.0,
            "spill_kwh": (sum(v(ftcurt[g][t]) for t in T) if ftcurt[g] is not None else 0.0),
            "fuel_units": float(pulp.value(ft_fuel_units[g]) or 0.0),
            "fuel_unit_name": ("gallons" if fts[g].kind == "Generator" else "MMBtu"),
            "existing_kw": fts[g].existing_kw,
            "purchase_kw": max(0.0, kw - fts[g].existing_kw),
            "segment": (next((k + 1 for k, _y in enumerate(ft_seg[g][1]) if v(_y) > 0.5), None)
                        if g in ft_seg else None),
            "unavailable_hours": (sum(1 for t in T if ft_pf[g][t] <= 0.0)
                                  if ft_pf[g] is not None else 0),
            "production_incentive": 0.0,
            "starts": (sum(1 for t in T if v(ftu[g][t]) > 0.5 and _was_off(g, t))
                       if ft_needs_bin[g] else None),
            # the schedule the solver chose: hours out, and the hour each event
            # began. None when the unit is not maintainable.
            "maintenance_hours": (round(sum(v(ftm[g][t]) for t in T), 3)
                                  if ft_maint[g] else None),
            "maintenance_starts": ([t for t in T if v(ftms[g][t]) > 0.5]
                                   if ft_maint[g] else None),
            # what triggered them, and -- in the running-hours mode, where the
            # count is an outcome -- how full the clock was left at the end
            "maintenance_trigger": (("running_hours" if ft_mint[g] else "count")
                                    if ft_maint[g] else None),
            "maintenance_interval_running_hours": (
                float(fts[g].maintenance_interval_running_hours)
                if ft_mint[g] else None),
            "maintenance_hours_banked": (round(v(fth[g][T[-1]]), 3)
                                         if ft_mint[g] else None),
            # the same count, per calendar day of the horizon
            "starts_by_day": ([sum(1 for t in T[d * 24:(d + 1) * 24]
                                   if v(ftu[g][t]) > 0.5 and _was_off(g, t))
                               for d in range((H + 23) // 24)]
                              if ft_needs_bin[g] else None),
        })
    bat_kw, bat_kwh = v(dvStoragePower), v(dvStorageEnergy)

    series = {
        "load_kw": loads,
        "pv_to_load_kw": [v(pvprod[t]) for t in T],
        "pv_curtailed_kw": [v(pvcurt[t]) for t in T],
        "fueltech_kw": [v(ftprod[t]) for t in T],
        "battery_discharge_kw": [v(dis[t]) for t in T],
        "battery_charge_kw": [v(chg[t]) + v(gridchg[t]) for t in T],
        "grid_kw": [v(grid[t]) for t in T],
        "soc_kwh": [v(soc[t]) for t in T],
        "unserved_kw": [v(unserved[t]) for t in T],
        "export_kw": [v(export[t]) for t in T],
        # one series per fuel-fired unit, so the hourly table can break the
        # fleet out; empty when no unit is enabled
        "fueltech_unit_kw": {
            (fts[g].name or fts[g].label or f"Unit {g + 1}"): [v(ftgen[g][t]) for t in T]
            for g in NG if fts[g].enabled
        },
        "storage_unit_soc_kwh": {
            (sts[b].name or f"Battery {b + 1}"): [v(bsoc[b][t]) for t in T]
            for b in NB if sts[b].enabled
        },
        "fueltech_unit_spill_kw": {
            (fts[g].name or fts[g].label or f"Unit {g + 1}"): [v(ftcurt[g][t]) for t in T]
            for g in NG if fts[g].enabled and ftcurt[g] is not None
        },
        "heating_load_kw": (list(_hl) if _hl is not None else []),
        "chp_heat_to_load_kw": [v(chpheat_h[t]) for t in T] if chpheat_h else [],
        "boiler_heat_kw": [v(boil_h[t]) for t in T] if boil_h else [],
        "chp_heat_waste_kw": ([max(0.0, sum(ft_th_slope[g] * v(ftgen[g][t])
                                           + (v(thI[g][t]) if g in thI else 0.0)
                                           for g in _heat_units) - v(chpheat_h[t])) for t in T]
                              if chpheat_h else []),
        "fueltech_unit_on": {
            (fts[g].name or fts[g].label or f"Unit {g + 1}"): [v(ftu[g][t]) for t in T]
            for g in NG if fts[g].enabled and ft_needs_bin[g]
        },
        # 1 in every hour the unit is in a maintenance event, so the chosen
        # schedule can be drawn beside the dispatch
        "fueltech_unit_maintenance": {
            (fts[g].name or fts[g].label or f"Unit {g + 1}"): [v(ftm[g][t]) for t in T]
            for g in NG if ft_maint[g]
        },
    }

    pv_energy = sum(series["pv_to_load_kw"]) + sum(series["pv_curtailed_kw"])
    ft_energy = sum(series["fueltech_kw"])
    grid_energy = sum(series["grid_kw"]) + sum(
        max(0.0, series["battery_charge_kw"][t] - series["pv_to_load_kw"][t]) for t in T
    ) * 0.0  # grid charging already inside grid_kw accounting below

    out = {
        "status": pulp.LpStatus[status],
        "solver": solver_info,
        "objective_lifecycle_cost": float(pulp.value(m.objective) or 0.0),
        "sizes": {
            "pv_kw": pv_kw, "battery_kw": bat_kw, "battery_kwh": bat_kwh,
            "fueltech_kw": ft_kw,
            "fueltech_kind": (ft.label or ft.kind) if ft.enabled else None,
            "fueltech_units": ft_unit_rows,
            "storage_units": [
                {"index": b,
                 "name": sts[b].name or f"Battery {b + 1}",
                 "power_kw": v(bpow[b]),
                 "energy_kwh": v(ben[b]),
                 "duration_hours": (v(ben[b]) / v(bpow[b])) if v(bpow[b]) > 1e-9 else 0.0,
                 "throughput_kwh": sum(v(bdis[b][t]) for t in T),
                 "full_cycles": (sum(v(bdis[b][t]) for t in T) / v(ben[b]))
                                if v(ben[b]) > 1e-9 else 0.0}
                for b in NB if sts[b].enabled
            ],
        },
        "energy": {
            "annual_load_kwh": sum(loads),
            "pv_kwh": pv_energy,
            "pv_curtailed_kwh": sum(series["pv_curtailed_kw"]),
            "fueltech_kwh": ft_energy,
            "grid_kwh": sum(series["grid_kw"]),
            "battery_discharge_kwh": sum(series["battery_discharge_kw"]),
            "unserved_kwh": sum(series["unserved_kw"]),
            "exported_kwh": sum(series["export_kw"]),
        },
        "capital": {
            "pv_cap_cost_slope_per_kw": pv_slope,
            "fueltech_cap_cost_slope_per_kw": (
                sum(ft_slopes[g] * v(ftsize[g]) for g in NG) / ft_kw
                if ft_kw > 1e-9 else 0.0),
            "storage_npc_per_kw": npc_kw,
            "storage_npc_per_kwh": npc_kwh,
            "storage_npc_constant": npc_const,
            # REopt results Financial.initial_capital_costs_after_incentives:
            # the capital terms of the objective, net of ITC, MACRS and rebates
            "lifecycle_capex": v(TotalTechCapCosts + TotalStorageCapCosts),
            "upfront_before_incentives": (
                inp.pv.installed_cost_per_kw * pv_kw
                + sum(_ft_upfront(g) for g in NG)
                + bat_basis
            ),
        },
        "om": {
            "year1_pv": inp.pv.om_cost_per_kw * pv_kw,
            "year1_fueltech": sum(
                fts[g].om_cost_per_kw * v(ftsize[g])
                + fts[g].om_cost_per_kwh * sum(v(ftgen[g][t]) for t in T)
                for g in NG),
            "year1_storage": bat_om_y1,
            "year1_starts": sum(fts[g].start_cost * sum(v(ftsu[g][t]) for t in T)
                                for g in NG if ftsu[g] is not None),
            "year1_running_hours": sum(fts[g].om_cost_per_running_hour * sum(v(ftu[g][t]) for t in T)
                                       for g in NG if ftu[g] is not None),
            "year1_storage_cycling": sum(sts[b].discharge_cost_per_kwh
                                         * sum(v(bdis[b][t]) for t in T)
                                         for b in NB if sts[b].enabled),
            "year1_services": sum(fts[g].maintenance_cost_per_event
                                  * sum(v(ftms[g][t]) for t in T)
                                  for g in NG if ftms[g] is not None),
        },
        "thermal": {
            "heating_fuel_mmbtu": _heat_fuel or 0.0,
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
        "operating_reserve": {
            "required_kwh": (sum(pulp.value(x) or 0.0 for x in _or_req)
                             if inp.off_grid_flag and _or_req else 0.0),
            "provided_kwh": (sum(v(_or_vars[0][t]) + v(_or_vars[1][t]) + v(_or_vars[2][t])
                                 for t in T) if inp.off_grid_flag and _or_vars else 0.0),
        },
        "factors": {"pwf_e": pwf_e, "pwf_om": pwf_om, "pwf_fuel": pwf_fuel,
                    "pwf_boiler": pwf_boiler,
                    "levelization_factor_pv": lvl_pv},
        "series": series,
    }

    # --- dispatch split, matching REopt's Annual Electricity Production Breakdown ---
    pv_to_batt, grid_to_batt = 0.0, 0.0
    for t in T:
        charged = v(chg[t])
        pv_to_batt += charged
        grid_to_batt += v(gridchg[t])
    out["breakdown"] = {
        "grid_serving_load": sum(series["grid_kw"]),
        "grid_charging_battery": grid_to_batt,
        "grid_total": sum(series["grid_kw"]) + grid_to_batt,
        "pv_serving_load": sum(series["pv_to_load_kw"]) - pv_to_batt,
        "pv_charging_battery": pv_to_batt,
        "pv_exported": sum(series["export_kw"]),
        "pv_curtailed": sum(series["pv_curtailed_kw"]),
        "pv_total": pv_energy,
        "battery_serving_load": sum(series["battery_discharge_kw"]),
        "battery_exported": 0.0,
        "fueltech_serving_load": ft_energy,
    }

    if tar is not None:
        out["utility"] = {
            "year1_energy_cost": sum(
                tar.energy_cost_per_kwh[t] * series["grid_kw"][t] for t in T),
            "year1_tou_demand_cost": sum(
                tar.tou_demand_rates[i] * v(tou_peak[i]) for i in range(len(tou_peak))),
            "year1_monthly_demand_cost": sum(
                tar.monthly_demand_rates[mo] * v(mon_peak[mo]) for mo in range(12)),
            "year1_fixed_cost": tar.fixed_monthly_charge * 12,
        }
        # ---- pro-forma: payback, IRR, PV LCOE (results/proforma.jl, financial.jl:320) ----
        bau_year1 = (sum(tar.energy_cost_per_kwh[t] * loads[t] for t in T)
                     + sum(r_ * max((loads[h] for h in hrs), default=0.0)
                           for r_, hrs in zip(tar.tou_demand_rates, tou_periods))
                     + sum(tar.monthly_demand_rates[mo] * max((loads[h] for h in mon_periods[mo]), default=0.0)
                           for mo in range(12))
                     + tar.fixed_monthly_charge * 12)
        pv_capex = inp.pv.installed_cost_per_kw * pv_kw
        bat_capex = bat_basis
        ft_capex = sum(_ft_upfront(g) for g in NG)
        initial_capital = pv_capex + bat_capex + ft_capex
        y1_om_total = (out["om"]["year1_pv"] + out["om"]["year1_storage"]
                       + out["om"]["year1_fueltech"] + out["om"]["year1_starts"]
                       + out["om"]["year1_storage_cycling"] + out["om"]["year1_running_hours"]
                       + out["om"]["year1_services"])
        sh_pv = depreciation_tax_shields(pv_capex, inp.pv.federal_itc_fraction,
                                         inp.pv.macrs_option_years, inp.pv.macrs_bonus_fraction,
                                         inp.pv.macrs_itc_reduction, tax_own, f.analysis_years)
        sh_bat = depreciation_tax_shields(bat_capex, s.total_itc_fraction, s.macrs_option_years,
                                          s.macrs_bonus_fraction, s.macrs_itc_reduction,
                                          tax_own, f.analysis_years) if any_storage else [0.0] * (f.analysis_years + 1)
        shields = [a + b for a, b in zip(sh_pv, sh_bat)]
        for g in NG:
            if fts[g].enabled and fts[g].kind == "CHP" and _ft_upfront(g) > 0:
                _sh = depreciation_tax_shields(
                    _ft_upfront(g), fts[g].federal_itc_fraction, fts[g].macrs_option_years,
                    fts[g].macrs_bonus_fraction, fts[g].macrs_itc_reduction,
                    tax_own, f.analysis_years)
                shields = [a + b for a, b in zip(shields, _sh)]
        itc_amt = pv_capex * inp.pv.federal_itc_fraction + sum(
            (sts[b].installed_cost_per_kw * v(bpow[b])
             + sts[b].installed_cost_per_kwh * v(ben[b])
             + (sts[b].installed_cost_constant if v(ben[b]) > 1e-6 else 0.0))
            * sts[b].total_itc_fraction for b in NB if sts[b].enabled)
        # ---- REopt's pro-forma, proforma.jl host-owned branch ----------------
        _n = f.analysis_years
        _m = PF.Metrics(_n)
        _om_esc = f.om_cost_escalation_rate_fraction
        if inp.pv.enabled and pv_kw > 1e-9:
            PF.add_tech(_m, om_escalation=_om_esc, capital_cost=pv_capex, new_kw=pv_kw,
                        annual_om=pv_kw * inp.pv.om_cost_per_kw,
                        federal_itc_fraction=inp.pv.federal_itc_fraction,
                        federal_rebate_per_kw=inp.pv.federal_rebate_per_kw,
                        degradation_fraction=inp.pv.degradation_fraction,
                        macrs_option_years=inp.pv.macrs_option_years,
                        macrs_bonus_fraction=inp.pv.macrs_bonus_fraction,
                        macrs_itc_reduction=inp.pv.macrs_itc_reduction)
        _rep_cost = 0.0
        for b in NB:
            st_ = sts[b]
            if st_.enabled and v(bpow[b]) > 1e-9:
                _rep_cost += PF.add_storage(
                    _m, om_escalation=_om_esc, size_kw=v(bpow[b]), size_kwh=v(ben[b]),
                    cost_per_kw=st_.installed_cost_per_kw, cost_per_kwh=st_.installed_cost_per_kwh,
                    cost_constant=st_.installed_cost_constant,
                    replace_per_kw=st_.replace_cost_per_kw, replace_per_kwh=st_.replace_cost_per_kwh,
                    replace_constant=st_.replace_cost_constant,
                    battery_replacement_year=st_.battery_replacement_year,
                    om_fraction=st_.om_cost_fraction_of_installed_cost,
                    rebate_per_kw=st_.total_rebate_per_kw, rebate_per_kwh=st_.total_rebate_per_kwh,
                    itc_fraction=st_.total_itc_fraction, macrs_option_years=st_.macrs_option_years,
                    macrs_bonus_fraction=st_.macrs_bonus_fraction,
                    macrs_itc_reduction=st_.macrs_itc_reduction)
        _standby_y1 = 0.0
        _chp_fuel_y1 = _chp_fuel_mmbtu = _chp_heat_prod = 0.0
        for g in NG:
            u = fts[g]
            if not u.enabled or v(ftsize[g]) <= 1e-9:
                continue
            _kw = v(ftsize[g])
            _kwh = sum(v(ftgen[g][t]) for t in T)
            # hourly fuel, then priced hour by hour (monthly prices when given)
            _fuel_h = [ft_slope_fuel[g] * v(ftgen[g][t])
                       + ((ft_icept[g] * (u.max_kw if inp.fuel_intercept_basis == "rated" else 1.0)
                           * v(ftu[g][t])) if (ft_needs_bin[g] and ft_icept[g] > 0.0) else 0.0)
                       for t in T]
            if u.kind == "CHP" and u.fuel_cost_per_mmbtu_monthly:
                _fuel_y1 = sum(u.fuel_cost_per_mmbtu_monthly[_MONTH_OF_HOUR[t]] * _fuel_h[t] for t in T)
            else:
                _fuel_y1 = sum(_fuel_h) * (u.fuel_cost_per_gallon if u.kind == "Generator"
                                           else u.fuel_cost_per_mmbtu)
            # results/chp.jl:165 digits=3, results/generator.jl:35 digits=2
            _fuel_y1 = round(_fuel_y1, 2 if u.kind == "Generator" else 3)
            _new_kw = max(0.0, _kw - u.existing_kw)
            _extra = (u.start_cost * sum(v(ftsu[g][t]) for t in T) if ftsu[g] is not None else 0.0) \
                + (u.om_cost_per_running_hour * sum(v(ftu[g][t]) for t in T) if ftu[g] is not None else 0.0)
            if u.kind == "CHP":
                _standby_y1 += 12 * u.standby_rate_per_kw_per_month * _kw
                _chp_fuel_y1 += _fuel_y1
                _chp_fuel_mmbtu += sum(_fuel_h)
                # heat produced, used or wasted (REopt annual_thermal_production_mmbtu)
                _chp_heat_prod += sum(ft_th_slope[g] * v(ftgen[g][t])
                                      + (v(thI[g][t]) if g in thI else 0.0) for t in T) / 293.07107
                PF.add_tech(
                    _m, om_escalation=_om_esc, capital_cost=_ft_upfront(g), new_kw=_new_kw,
                    annual_om=_kwh * u.om_cost_per_kwh + _new_kw * u.om_cost_per_kw + _extra,
                    annual_om_bau=u.existing_kw * u.om_cost_per_kw,
                    fuel_year1=_fuel_y1,
                    fuel_escalation=(f.chp_fuel_cost_escalation_rate_fraction
                                     if f.chp_fuel_cost_escalation_rate_fraction is not None
                                     else f.fuel_cost_escalation_rate_fraction),
                    federal_itc_fraction=u.federal_itc_fraction,
                    federal_rebate_per_kw=u.federal_rebate_per_kw,
                    state_ibi_fraction=u.state_ibi_fraction, state_ibi_max=u.state_ibi_max,
                    state_rebate_per_kw=u.state_rebate_per_kw, state_rebate_max=u.state_rebate_max,
                    utility_ibi_fraction=u.utility_ibi_fraction, utility_ibi_max=u.utility_ibi_max,
                    utility_rebate_per_kw=u.utility_rebate_per_kw,
                    utility_rebate_max=u.utility_rebate_max,
                    production_incentive_per_kwh=u.production_incentive_per_kwh,
                    production_incentive_max_benefit=u.production_incentive_max_benefit,
                    production_incentive_years=int(u.production_incentive_years),
                    year_one_energy_kwh=_kwh,
                    macrs_option_years=u.macrs_option_years,
                    macrs_bonus_fraction=u.macrs_bonus_fraction,
                    macrs_itc_reduction=u.macrs_itc_reduction)
            else:
                # proforma.jl:108-133 -- generator: O&M and fuel only
                PF.add_tech(_m, om_escalation=_om_esc, capital_cost=0.0, new_kw=0.0,
                            annual_om=_kw * u.om_cost_per_kw + _kwh * u.om_cost_per_kwh + _extra)
                PF.add_fuel(_m, year1=_fuel_y1, year1_bau=0.0,
                            escalation=f.fuel_cost_escalation_rate_fraction)
        # existing boiler fuel, optimal and BAU (proforma.jl:146-160)
        _boiler_y1 = _boiler_y1_bau = 0.0
        if boil_h:
            _bp = (lambda t: inp.boiler_fuel_cost_per_mmbtu_monthly[_MONTH_OF_HOUR[t]]) \
                if inp.boiler_fuel_cost_per_mmbtu_monthly else (lambda t: inp.existing_boiler_fuel_cost_per_mmbtu)
            _den = inp.boiler_efficiency * 293.07107
            _boiler_y1 = sum(_bp(t) * v(boil_h[t]) / _den for t in T)
            _boiler_y1_bau = sum(_bp(t) * _hl[t] / _den for t in T)
        elif thermal_load_mmbtu > 0:
            _boiler_y1 = v(boiler_thermal) / inp.boiler_efficiency * inp.existing_boiler_fuel_cost_per_mmbtu
            _boiler_y1_bau = (_heat_fuel or 0.0) * inp.existing_boiler_fuel_cost_per_mmbtu
        # results/existing_boiler.jl:109 rounds year-one fuel cost to digits=3
        _boiler_y1, _boiler_y1_bau = round(_boiler_y1, 3), round(_boiler_y1_bau, 3)
        # the web tool's fuel rows: year one, and lifecycle after tax (results/chp.jl,
        # existing_boiler.jl, financial.jl standby); hour-by-hour prices included
        out["thermal"].update({
            "boiler_fuel_cost_year1": _boiler_y1,
            "boiler_fuel_cost_lifecycle": _boiler_y1 * pwf_boiler * (1 - tax_off),
            # existing_boiler.jl: max size = factor x peak heating load
            "boiler_capacity_mmbtu_per_hour": boiler_max_kw / 293.07107,
            "chp_fuel_mmbtu": _chp_fuel_mmbtu,
            "chp_thermal_production_mmbtu": _chp_heat_prod,
            "chp_fuel_cost_year1": _chp_fuel_y1,
            "chp_fuel_cost_lifecycle": _chp_fuel_y1 * pwf_fuel_chp * (1 - tax_off),
            "standby_year1": _standby_y1,
            "standby_lifecycle": _standby_y1 * pwf_e * (1 - tax_off),
        })
        if _boiler_y1 or _boiler_y1_bau:
            PF.add_fuel(_m, year1=_boiler_y1, year1_bau=_boiler_y1_bau, escalation=inp.boiler_fuel_escalation)
        _export_y1 = round(sum(export_rate[t] * series["export_kw"][t] for t in T)
                           if inp.compensation_type != "no_compensation" else 0.0)   # digits=0
        # results/electric_tariff.jl:61-79: energy and demand to cents, fixed to dollars;
        # the BAU bill is the same function on the BAU run
        _u = out["utility"]
        _bill = (round(_u["year1_energy_cost"], 2)
                 + round(_u["year1_tou_demand_cost"] + _u["year1_monthly_demand_cost"], 2)
                 + round(_u["year1_fixed_cost"]))
        _bill_bau = (round(sum(tar.energy_cost_per_kwh[t] * loads[t] for t in T), 2)
                     + round(bau_year1 - sum(tar.energy_cost_per_kwh[t] * loads[t] for t in T)
                             - tar.fixed_monthly_charge * 12, 2)
                     + round(tar.fixed_monthly_charge * 12))
        _boiler_capex_bau = 0.0
        # BAU year 0 is -lifecycle_capital_costs_bau, i.e. the BAU ExistingBoilerCost
        if boil_h and max(_hl) > 0 and (inp.boiler_installed_cost_per_mmbtu_per_hour or inp.boiler_installed_cost_dollars):
            if inp.boiler_installed_cost_per_mmbtu_per_hour and not inp.boiler_installed_cost_dollars:
                _boiler_capex_bau = (inp.boiler_installed_cost_per_mmbtu_per_hour / 293.07107
                                     * inp.boiler_max_thermal_factor_on_peak_load) * max(_hl)
            else:
                _boiler_capex_bau = inp.boiler_installed_cost_dollars
        pf = PF.finish(
            _m, elec_escalation=f.elec_cost_escalation_rate_fraction, tax_rate=tax_off,
            discount_rate=f.offtaker_discount_rate_fraction,
            initial_capital=initial_capital,   # InitialCapexNoIncentives: no ExistingBoiler
            lifecycle_capital_bau=_boiler_capex_bau,
            year1_bill=_bill, year1_bill_bau=_bill_bau, year1_export=_export_y1, year1_export_bau=0.0,
            year1_standby=_standby_y1)
        out["proforma"] = {
            "simple_payback_years": pf["simple_payback_years"],
            "internal_rate_of_return": pf["internal_rate_of_return"],
            "cumulative_cashflow": pf["cumulative_cashflow"],
            "net_free_cashflow": pf["net_free_cashflow"],
            "npv": pf["npv"],
            "offtaker_annual_free_cashflows": pf["offtaker_annual_free_cashflows"],
            "offtaker_annual_free_cashflows_bau": pf["offtaker_annual_free_cashflows_bau"],
            "battery_replacement_cost": _rep_cost,
            "pv_lcoe": (pv_lcoe(capital_cost=pv_capex, year1_om=out["om"]["year1_pv"],
                                years=f.analysis_years,
                                om_escalation=f.om_cost_escalation_rate_fraction,
                                discount_rate=f.offtaker_discount_rate_fraction,
                                tax_rate=tax_own,
                                itc_amount=pv_capex * inp.pv.federal_itc_fraction,
                                depr_shields=sh_pv, annual_energy_kwh=pv_energy,
                                degradation=inp.pv.degradation_fraction)
                        if pv_energy > 0 else 0.0),
        }
        out["utility"]["year1_total"] = (
            out["utility"]["year1_energy_cost"]
            + out["utility"]["year1_tou_demand_cost"]
            + out["utility"]["year1_monthly_demand_cost"]
            + out["utility"]["year1_fixed_cost"]
        )
    return out


def business_as_usual(inp: ScenarioInputs) -> dict:
    """BAU: grid serves the whole load, no DER.

    REopt runs a separate BAU scenario for grid-tied cases; off-grid has none
    (reopt.jl:117 -- 'The BAU scenario is not applicable for off-grid microgrids').
    """
    if inp.off_grid_flag or inp.tariff is None:
        return {}
    tar, f = inp.tariff, inp.financial
    H = len(inp.loads_kw)
    T = range(H)
    energy = sum(tar.energy_cost_per_kwh[t] * inp.loads_kw[t] for t in T)
    tou = sum(tar.tou_demand_rates[i] * max((inp.loads_kw[t] for t in hrs if t < H), default=0.0)
              for i, hrs in enumerate(tar.tou_demand_periods))
    mon = sum(tar.monthly_demand_rates[mo]
              * max((inp.loads_kw[t] for t in tar.monthly_demand_periods[mo] if t < H), default=0.0)
              for mo in range(12))
    fixed = tar.fixed_monthly_charge * 12
    year1 = energy + tou + mon + fixed
    pwf_e = annuity(f.analysis_years, f.elec_cost_escalation_rate_fraction,
                    f.offtaker_discount_rate_fraction)
    # BAU carries the full boiler fuel bill: no CHP means no heat recovery
    boiler_lcc = 0.0
    _pwf_b = annuity(f.analysis_years, inp.boiler_fuel_escalation, f.offtaker_discount_rate_fraction)
    boiler_fuel_mmbtu = 0.0
    boiler_year1 = 0.0
    boiler_capex = 0.0
    if inp.heating_loads_kw is not None and not inp.off_grid_flag:
        # the same hourly load the optimal case balances, all of it on the boiler
        _hl = list(inp.heating_loads_kw)[:H]
        _fuel_h = [x / (inp.boiler_efficiency * 293.07107) for x in _hl]
        boiler_fuel_mmbtu = sum(_fuel_h)
        if inp.boiler_fuel_cost_per_mmbtu_monthly:
            boiler_year1 = sum(inp.boiler_fuel_cost_per_mmbtu_monthly[_MONTH_OF_HOUR[t]] * _fuel_h[t]
                               for t in T)
        else:
            boiler_year1 = boiler_fuel_mmbtu * inp.existing_boiler_fuel_cost_per_mmbtu
        boiler_lcc = _pwf_b * boiler_year1 * (1 - f.offtaker_tax_rate_fraction)
        # existing boiler capital cost, sized to the peak it must serve in BAU
        _peak = max(_hl) if _hl else 0.0
        if inp.boiler_installed_cost_per_mmbtu_per_hour and not inp.boiler_installed_cost_dollars:
            boiler_capex = (inp.boiler_installed_cost_per_mmbtu_per_hour / 293.07107
                            * inp.boiler_max_thermal_factor_on_peak_load) * _peak
        elif inp.boiler_installed_cost_dollars and _peak > 0:
            boiler_capex = inp.boiler_installed_cost_dollars
        boiler_lcc += boiler_capex
    elif inp.heating_fuel_mmbtu and not inp.off_grid_flag:
        boiler_fuel_mmbtu = inp.heating_fuel_mmbtu
        boiler_year1 = inp.heating_fuel_mmbtu * inp.existing_boiler_fuel_cost_per_mmbtu
        boiler_lcc = _pwf_b * boiler_year1 * (1 - f.offtaker_tax_rate_fraction)
    return {
        "year1_energy_cost": energy, "year1_tou_demand_cost": tou,
        "year1_monthly_demand_cost": mon, "year1_fixed_cost": fixed,
        "year1_total": year1,
        "year1_boiler_fuel_cost": 0.0 if inp.off_grid_flag else boiler_year1,
        "boiler_fuel_mmbtu": 0.0 if inp.off_grid_flag else boiler_fuel_mmbtu,
        "boiler_lifecycle_cost": boiler_lcc,
        "lifecycle_cost": pwf_e * year1 * (1 - f.offtaker_tax_rate_fraction) + boiler_lcc,
    }
