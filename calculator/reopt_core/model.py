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

from .finance import (annuity, effective_cost, fuel_slope_and_intercept,
                      levelization_factor, macrs_schedule_for)
from .proforma import build as proforma_build, depreciation_tax_shields, pv_lcoe
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
    fuel_intercept_basis: str = "reopt"
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


# --------------------------------------------------------------- the model
def solve(inp: ScenarioInputs, *, time_limit: int = 300, msg: bool = False) -> dict:
    f = inp.financial
    T = list(range(HOURS))
    loads = inp.loads_kw

    # ---- present-worth factors: REopt/src/core/reopt_inputs.jl:1128-1138 ----
    pwf_e = annuity(f.analysis_years, f.elec_cost_escalation_rate_fraction,
                    f.offtaker_discount_rate_fraction)
    pwf_om = annuity(f.analysis_years, f.om_cost_escalation_rate_fraction,
                     f.owner_discount_rate_fraction)
    pwf_fuel = annuity(f.analysis_years, f.fuel_cost_escalation_rate_fraction,
                       f.offtaker_discount_rate_fraction)
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
        itc = inp.pv.federal_itc_fraction
        pv_slope = effective_cost(
            itc_basis=inp.pv.installed_cost_per_kw,
            replacement_cost=0.0, replacement_year=f.analysis_years,
            discount_rate=f.owner_discount_rate_fraction, tax_rate=tax_own, itc=itc,
            macrs_schedule=macrs_schedule_for(inp.pv.macrs_option_years),
            macrs_bonus_fraction=inp.pv.macrs_bonus_fraction if inp.pv.macrs_option_years else 0.0,
            macrs_itc_reduction=inp.pv.macrs_itc_reduction if inp.pv.macrs_option_years else 0.0,
        )

    # A fleet of one is the single-slot case, so both shapes run one code path.
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
        ft_needs_bin[g] = bool(u.enabled and (ic > 0.0 or u.min_turn_down_fraction > 0.0))

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
        )
        b_npc_kwh[b] = effective_cost(
            itc_basis=st.installed_cost_per_kwh,
            replacement_cost=(0.0 if st.battery_replacement_year >= f.analysis_years else st.replace_cost_per_kwh),
            replacement_year=st.battery_replacement_year,
            discount_rate=f.owner_discount_rate_fraction, tax_rate=tax_own,
            itc=st.total_itc_fraction, macrs_schedule=sched,
            macrs_bonus_fraction=st.macrs_bonus_fraction, macrs_itc_reduction=st.macrs_itc_reduction,
        )
        b_npc_const[b] = effective_cost(
            itc_basis=st.installed_cost_constant, replacement_cost=0.0,
            replacement_year=f.analysis_years,
            discount_rate=f.owner_discount_rate_fraction, tax_rate=tax_own,
            itc=st.total_itc_fraction, macrs_schedule=sched,
            macrs_bonus_fraction=st.macrs_bonus_fraction,
            macrs_itc_reduction=st.macrs_itc_reduction,
        ) if st.installed_cost_constant else 0.0
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

    dvPVsize = pulp.LpVariable("dvSize_PV", lowBound=inp.pv.min_kw,
                               upBound=pv_space_max if inp.pv.enabled else 0.0)
    ftsize = {g: pulp.LpVariable(f"dvSize_FT_{g}", lowBound=fts[g].min_kw,
                                 upBound=fts[g].max_kw if fts[g].enabled else 0.0)
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
    ftprod = {t: pulp.lpSum(ftgen[g][t] for g in NG) for t in T}
    ftu = {g: ({t: pulp.LpVariable(f"ftON_{g}_{t}", cat="Binary") for t in T}
               if ft_needs_bin[g] else None) for g in NG}
    bchg = {b: {t: pulp.LpVariable(f"chg_{b}_{t}", lowBound=0) for t in T} for b in NB}
    bgchg = {b: {t: pulp.LpVariable(f"gridchg_{b}_{t}", lowBound=0) for t in T} for b in NB}
    bdis = {b: {t: pulp.LpVariable(f"dis_{b}_{t}", lowBound=0) for t in T} for b in NB}
    bsoc = {b: {t: pulp.LpVariable(f"soc_{b}_{t}", lowBound=0) for t in T} for b in NB}
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
    chp_thermal = pulp.LpVariable("chp_thermal_mmbtu", lowBound=0)
    boiler_thermal = pulp.LpVariable("boiler_thermal_mmbtu", lowBound=0)

    tar = inp.tariff
    tou_peak, mon_peak = [], []
    if tar is not None:
        tou_peak = [pulp.LpVariable(f"tou_{i}", lowBound=0) for i in range(len(tar.tou_demand_rates))]
        mon_peak = [pulp.LpVariable(f"mon_{i}", lowBound=0) for i in range(12)]

    # ----------------------------------------------------------- constraints
    # PV production ties to size (tech_constraints.jl: dvRatedProduction == prodfactor * dvSize)
    pf = inp.pv.production_factor or [0.0] * HOURS
    for t in T:
        m += pvprod[t] + pvcurt[t] == pf[t] * dvPVsize * lvl_pv, f"pv_prod_{t}"
        if not inp.pv.can_curtail:
            m += pvcurt[t] == 0, f"pv_nocurt_{t}"
        for g in NG:
            # Rated production never exceeds installed size (tech_constraints.jl)
            m += ftgen[g][t] <= ftsize[g], f"ft_cap_{g}_{t}"
            if ft_needs_bin[g]:
                # generator_constraints.jl:22-24 -- off means exactly zero.
                # The big-M is the unit's own upper bound, as REopt uses max_sizes.
                m += ftgen[g][t] <= fts[g].max_kw * ftu[g][t], f"ft_on_{g}_{t}"
                if fts[g].min_turn_down_fraction > 0:
                    # generator_constraints.jl:32-35
                    m += (fts[g].min_turn_down_fraction * ftsize[g] - ftgen[g][t]
                          <= fts[g].max_kw * (1 - ftu[g][t])), f"ft_turndown_{g}_{t}"

    # Land use -- tech_constraints.jl:26-31
    if inp.land_acres is not None and inp.pv.enabled:
        m += inp.pv.acres_per_kw * dvPVsize <= inp.land_acres, "land"

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
            # SOC dynamics -- storage_constraints.jl:39-73 (general dispatch)
            for t in T:
                prev = bsoc[b][T[-1]] if t == 0 else bsoc[b][t - 1]
                m += bsoc[b][t] == prev + st.charge_efficiency * bchg[b][t] \
                     + st.grid_charge_efficiency * bgchg[b][t] \
                     - bdis[b][t] / st.discharge_efficiency, f"soc_bal_{b}_{t}"
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
                        (bsoc[b][T[-1]] if t == 0 else bsoc[b][t - 1])
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
        for i, hrs in enumerate(tar.tou_demand_periods):
            for t in hrs:
                m += tou_peak[i] >= grid[t] + gridchg[t], f"toupk_{i}_{t}"
        for mo in range(12):
            for t in tar.monthly_demand_periods[mo]:
                m += mon_peak[mo] >= grid[t] + gridchg[t], f"monpk_{mo}_{t}"

    # Thermal balance: boiler covers whatever CHP does not.
    if thermal_load_mmbtu > 0:
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
    TotalTechCapCosts = pv_slope * dvPVsize + pulp.lpSum(
        ft_slopes[g] * ftsize[g] for g in NG)
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
    TotalPerUnitProdOMCosts = pwf_om * pulp.lpSum(
        fts[g].om_cost_per_kwh * pulp.lpSum(ftgen[g][t] for t in T) for g in NG)

    # Fuel, per unit: generator_constraints.jl:8-12
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
        TotalFuelCosts = TotalFuelCosts + pwf_fuel * price * usage

    if tar is not None:
        # Export credit: net metering pays the retail energy rate, net billing the
        # wholesale rate. REopt models these as the NEM / WHL export bins.
        if inp.compensation_type == "net_metering":
            export_rate = list(tar.energy_cost_per_kwh)
        elif inp.compensation_type in ("net_billing", "net_meter_net_bill"):
            export_rate = [inp.wholesale_rate] * HOURS
        else:
            export_rate = [0.0] * HOURS
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

    m += (TotalTechCapCosts + TotalStorageCapCosts
          + (TotalPerUnitSizeOMCosts + ElectricStorageOMCost) * (1 - tax_own)
          + TotalPerUnitProdOMCosts * (1 - tax_own)
          + TotalFuelCosts * (1 - tax_off)
          + TotalElecBill * (1 - tax_off)
          + ExistingBoilerFuelCost * (1 - tax_off)), "Costs"

    # ---------------------------------------------------------------- solve
    solver = pulp.HiGHS(msg=msg, timeLimit=time_limit)
    status = m.solve(solver)

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
    bat_om_y1 = sum(
        sts[b].om_cost_fraction_of_installed_cost
        * (sts[b].installed_cost_per_kw * v(bpow[b])
           + sts[b].installed_cost_per_kwh * v(ben[b])
           + (sts[b].installed_cost_constant if v(ben[b]) > 1e-6 else 0.0))
        for b in NB if sts[b].enabled)
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
        "fueltech_unit_on": {
            (fts[g].name or fts[g].label or f"Unit {g + 1}"): [v(ftu[g][t]) for t in T]
            for g in NG if fts[g].enabled and ft_needs_bin[g]
        },
    }

    pv_energy = sum(series["pv_to_load_kw"]) + sum(series["pv_curtailed_kw"])
    ft_energy = sum(series["fueltech_kw"])
    grid_energy = sum(series["grid_kw"]) + sum(
        max(0.0, series["battery_charge_kw"][t] - series["pv_to_load_kw"][t]) for t in T
    ) * 0.0  # grid charging already inside grid_kw accounting below

    out = {
        "status": pulp.LpStatus[status],
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
            "upfront_before_incentives": (
                inp.pv.installed_cost_per_kw * pv_kw
                + sum(fts[g].installed_cost_per_kw * v(ftsize[g]) for g in NG)
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
                     + sum(r_ * max(loads[h] for h in hrs)
                           for r_, hrs in zip(tar.tou_demand_rates, tar.tou_demand_periods))
                     + sum(tar.monthly_demand_rates[mo] * max(loads[h] for h in tar.monthly_demand_periods[mo])
                           for mo in range(12))
                     + tar.fixed_monthly_charge * 12)
        pv_capex = inp.pv.installed_cost_per_kw * pv_kw
        bat_capex = bat_basis
        ft_capex = sum(fts[g].installed_cost_per_kw * v(ftsize[g]) for g in NG)
        initial_capital = pv_capex + bat_capex + ft_capex
        y1_om_total = (out["om"]["year1_pv"] + out["om"]["year1_storage"]
                       + out["om"]["year1_fueltech"])
        sh_pv = depreciation_tax_shields(pv_capex, inp.pv.federal_itc_fraction,
                                         inp.pv.macrs_option_years, inp.pv.macrs_bonus_fraction,
                                         inp.pv.macrs_itc_reduction, tax_own, f.analysis_years)
        sh_bat = depreciation_tax_shields(bat_capex, s.total_itc_fraction, s.macrs_option_years,
                                          s.macrs_bonus_fraction, s.macrs_itc_reduction,
                                          tax_own, f.analysis_years) if any_storage else [0.0] * (f.analysis_years + 1)
        shields = [a + b for a, b in zip(sh_pv, sh_bat)]
        itc_amt = pv_capex * inp.pv.federal_itc_fraction + sum(
            (sts[b].installed_cost_per_kw * v(bpow[b])
             + sts[b].installed_cost_per_kwh * v(ben[b])
             + (sts[b].installed_cost_constant if v(ben[b]) > 1e-6 else 0.0))
            * sts[b].total_itc_fraction for b in NB if sts[b].enabled)
        pf = proforma_build(
            years=f.analysis_years, initial_capital=initial_capital,
            bau_year1_bill=bau_year1,
            opt_year1_bill=(out["utility"]["year1_energy_cost"]
                            + out["utility"]["year1_tou_demand_cost"]
                            + out["utility"]["year1_monthly_demand_cost"]
                            + out["utility"]["year1_fixed_cost"]),
            year1_om=y1_om_total, elec_escalation=f.elec_cost_escalation_rate_fraction,
            om_escalation=f.om_cost_escalation_rate_fraction, tax_rate=tax_off,
            discount_rate=f.offtaker_discount_rate_fraction,
            itc_amount=itc_amt, depr_shields=shields)
        out["proforma"] = {
            "simple_payback_years": pf["simple_payback_years"],
            "internal_rate_of_return": pf["internal_rate_of_return"],
            "cumulative_cashflow": pf["cumulative_cashflow"],
            "net_free_cashflow": pf["net_free_cashflow"],
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
    T = range(HOURS)
    energy = sum(tar.energy_cost_per_kwh[t] * inp.loads_kw[t] for t in T)
    tou = sum(tar.tou_demand_rates[i] * max(inp.loads_kw[t] for t in hrs)
              for i, hrs in enumerate(tar.tou_demand_periods))
    mon = sum(tar.monthly_demand_rates[mo] * max(inp.loads_kw[t] for t in tar.monthly_demand_periods[mo])
              for mo in range(12))
    fixed = tar.fixed_monthly_charge * 12
    year1 = energy + tou + mon + fixed
    pwf_e = annuity(f.analysis_years, f.elec_cost_escalation_rate_fraction,
                    f.offtaker_discount_rate_fraction)
    # BAU carries the full boiler fuel bill: no CHP means no heat recovery
    boiler_lcc = 0.0
    if inp.heating_fuel_mmbtu and not inp.off_grid_flag:
        boiler_lcc = (annuity(f.analysis_years, inp.boiler_fuel_escalation,
                              f.offtaker_discount_rate_fraction)
                      * inp.heating_fuel_mmbtu * inp.existing_boiler_fuel_cost_per_mmbtu
                      * (1 - f.offtaker_tax_rate_fraction))
    return {
        "year1_energy_cost": energy, "year1_tou_demand_cost": tou,
        "year1_monthly_demand_cost": mon, "year1_fixed_cost": fixed,
        "year1_total": year1,
        "year1_boiler_fuel_cost": (0.0 if inp.off_grid_flag else
                                   (inp.heating_fuel_mmbtu or 0.0)
                                   * inp.existing_boiler_fuel_cost_per_mmbtu),
        "boiler_lifecycle_cost": boiler_lcc,
        "lifecycle_cost": pwf_e * year1 * (1 - f.offtaker_tax_rate_fraction) + boiler_lcc,
    }
