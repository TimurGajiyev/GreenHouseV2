"""N electric storage units.

REopt.jl already indexes storage by name: `StorageTypes.elec::Vector{String}`
(energy_storage/storage.jl:15) and every storage constraint loops
`for b in p.s.storage.types.elec` (storage_constraints.jl, reopt.jl:516). The web
form exposes exactly one battery; the engine never did.

Same technique as the fuel fleet: per-unit variables, then aggregate aliases
carrying the old names, so every downstream expression is untouched and a fleet
of one reproduces the previous algebra term for term.
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
        """    macrs_itc_reduction: float = 0.5
    total_itc_fraction: float = 0.3


@dataclass
class FuelTechInputs:""",
        """    macrs_itc_reduction: float = 0.5
    total_itc_fraction: float = 0.3
    # Free-text name, used only for labelling results.
    name: str = ""


@dataclass
class FuelTechInputs:""",
        "storage: name field",
    ),
    (
        """    fuel_techs: list[FuelTechInputs] | None = None""",
        """    fuel_techs: list[FuelTechInputs] | None = None
    # A bank of distinct batteries. None keeps the single `storage` slot, which
    # is the REopt web-form shape. A list is the REopt.jl shape
    # (StorageTypes.elec is a Vector, storage.jl:15).
    storages: list[StorageInputs] | None = None""",
        "scenario: storages list",
    ),

    # ------------------------------------------------------ capital slopes
    (
        """    s = inp.storage
    npc_kw = npc_kwh = npc_const = 0.0
    if s.enabled:
        sched = macrs_schedule_for(s.macrs_option_years)
        # electric_storage.jl:482-522
        npc_kw = effective_cost(
            itc_basis=s.installed_cost_per_kw,
            replacement_cost=(0.0 if s.inverter_replacement_year >= f.analysis_years else s.replace_cost_per_kw),
            replacement_year=s.inverter_replacement_year,
            discount_rate=f.owner_discount_rate_fraction, tax_rate=tax_own,
            itc=s.total_itc_fraction, macrs_schedule=sched,
            macrs_bonus_fraction=s.macrs_bonus_fraction, macrs_itc_reduction=s.macrs_itc_reduction,
        )
        npc_kwh = effective_cost(
            itc_basis=s.installed_cost_per_kwh,
            replacement_cost=(0.0 if s.battery_replacement_year >= f.analysis_years else s.replace_cost_per_kwh),
            replacement_year=s.battery_replacement_year,
            discount_rate=f.owner_discount_rate_fraction, tax_rate=tax_own,
            itc=s.total_itc_fraction, macrs_schedule=sched,
            macrs_bonus_fraction=s.macrs_bonus_fraction, macrs_itc_reduction=s.macrs_itc_reduction,
        )
        if s.installed_cost_constant:
            npc_const = effective_cost(
                itc_basis=s.installed_cost_constant, replacement_cost=0.0,
                replacement_year=f.analysis_years,
                discount_rate=f.owner_discount_rate_fraction, tax_rate=tax_own,
                itc=s.total_itc_fraction, macrs_schedule=sched,
                macrs_bonus_fraction=s.macrs_bonus_fraction,
                macrs_itc_reduction=s.macrs_itc_reduction,
            )""",
        """    sts = list(inp.storages) if inp.storages else [inp.storage]
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
    npc_kw, npc_kwh, npc_const = b_npc_kw[0], b_npc_kwh[0], b_npc_const[0]""",
        "per-unit storage capital slopes",
    ),

    # ---------------------------------------------------------- variables
    (
        """    dvStoragePower = pulp.LpVariable("dvStoragePower", lowBound=s.min_kw,
                                     upBound=s.max_kw if s.enabled else 0.0)
    dvStorageEnergy = pulp.LpVariable("dvStorageEnergy", lowBound=s.min_kwh,
                                      upBound=s.max_kwh if s.enabled else 0.0)
    # REopt gates the storage cost constant behind a binary so it is only paid
    # when a battery is actually built -- reopt.jl:430, storage_constraints.jl:151
    binStorageConst = pulp.LpVariable("binIncludeStorageCostConstant", cat="Binary")""",
        """    bpow = {b: pulp.LpVariable(f"dvStoragePower_{b}", lowBound=sts[b].min_kw,
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
    binStorageConst = bconst[0]""",
        "per-unit storage size variables",
    ),
    (
        """    chg = {t: pulp.LpVariable(f"chg_{t}", lowBound=0) for t in T}            # into storage (AC)
    gridchg = {t: pulp.LpVariable(f"gridchg_{t}", lowBound=0) for t in T}
    dis = {t: pulp.LpVariable(f"dis_{t}", lowBound=0) for t in T}            # out of storage (AC)
    soc = {t: pulp.LpVariable(f"soc_{t}", lowBound=0) for t in T}""",
        """    bchg = {b: {t: pulp.LpVariable(f"chg_{b}_{t}", lowBound=0) for t in T} for b in NB}
    bgchg = {b: {t: pulp.LpVariable(f"gridchg_{b}_{t}", lowBound=0) for t in T} for b in NB}
    bdis = {b: {t: pulp.LpVariable(f"dis_{b}_{t}", lowBound=0) for t in T} for b in NB}
    bsoc = {b: {t: pulp.LpVariable(f"soc_{b}_{t}", lowBound=0) for t in T} for b in NB}
    chg = {t: pulp.lpSum(bchg[b][t] for b in NB) for t in T}       # into storage (AC)
    gridchg = {t: pulp.lpSum(bgchg[b][t] for b in NB) for t in T}
    dis = {t: pulp.lpSum(bdis[b][t] for b in NB) for t in T}       # out of storage (AC)
    soc = {t: pulp.lpSum(bsoc[b][t] for b in NB) for t in T}""",
        "per-unit storage dispatch variables",
    ),

    # -------------------------------------------------------- constraints
    (
        """    # Storage sizing -- storage_constraints.jl:2-20
    if s.enabled:
        for t in T:
            m += dis[t] <= dvStoragePower, f"dis_pow_{t}"
            m += chg[t] + gridchg[t] <= dvStoragePower, f"chg_pow_{t}"
            m += soc[t] >= s.soc_min_fraction * dvStorageEnergy, f"soc_min_{t}"
            m += soc[t] <= dvStorageEnergy, f"soc_max_{t}"
        if s.min_duration_hours > 0:
            m += dvStorageEnergy >= s.min_duration_hours * dvStoragePower, "dur_min"
        if s.max_duration_hours < 1e5:
            m += dvStorageEnergy <= s.max_duration_hours * dvStoragePower, "dur_max"
        if not s.can_grid_charge:
            for t in T:
                m += gridchg[t] == 0, f"nogridchg_{t}"
        # storage_constraints.jl:151 -- dvStorageEnergy <= max_kwh * bin
        if npc_const:
            m += dvStorageEnergy <= s.max_kwh * binStorageConst, "storage_const_bin"
        # SOC dynamics -- storage_constraints.jl:39-73 (general dispatch)
        for t in T:
            prev = soc[T[-1]] if t == 0 else soc[t - 1]
            m += soc[t] == prev + s.charge_efficiency * chg[t] \\
                 + s.grid_charge_efficiency * gridchg[t] \\
                 - dis[t] / s.discharge_efficiency, f"soc_bal_{t}"
    else:
        for t in T:
            m += chg[t] == 0, f"nochg_{t}"
            m += gridchg[t] == 0, f"nogchg_{t}"
            m += dis[t] == 0, f"nodis_{t}"
            m += soc[t] == 0, f"nosoc_{t}\"""",
        """    # Storage sizing -- storage_constraints.jl:2-20, per unit
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
                m += bsoc[b][t] == prev + st.charge_efficiency * bchg[b][t] \\
                     + st.grid_charge_efficiency * bgchg[b][t] \\
                     - bdis[b][t] / st.discharge_efficiency, f"soc_bal_{b}_{t}"
        else:
            for t in T:
                m += bchg[b][t] == 0, f"nochg_{b}_{t}"
                m += bgchg[b][t] == 0, f"nogchg_{b}_{t}"
                m += bdis[b][t] == 0, f"nodis_{b}_{t}"
                m += bsoc[b][t] == 0, f"nosoc_{b}_{t}\"""",
        "per-unit storage constraints",
    ),

    # --------------------------------------------------- operating reserve
    (
        """                if s.enabled:
                    prev = soc[T[-1]] if t == 0 else soc[t - 1]
                    m += or_bat[t] <= prev - s.soc_min_fraction * dvStorageEnergy \\
                         - dis[t] / s.discharge_efficiency, f"or_bat_e_{t}"
                    m += or_bat[t] <= dvStoragePower - dis[t] / s.discharge_efficiency, f"or_bat_p_{t}"
                else:
                    m += or_bat[t] == 0, f"or_bat_{t}\"""",
        """                if any_storage:
                    m += or_bat[t] <= pulp.lpSum(
                        (bsoc[b][T[-1]] if t == 0 else bsoc[b][t - 1])
                        - sts[b].soc_min_fraction * ben[b]
                        - bdis[b][t] / sts[b].discharge_efficiency
                        for b in NB if sts[b].enabled), f"or_bat_e_{t}"
                    m += or_bat[t] <= pulp.lpSum(
                        bpow[b] - bdis[b][t] / sts[b].discharge_efficiency
                        for b in NB if sts[b].enabled), f"or_bat_p_{t}"
                else:
                    m += or_bat[t] == 0, f"or_bat_{t}\"""",
        "reserve from the whole bank",
    ),

    # ---------------------------------------------------------- objective
    (
        """    TotalStorageCapCosts = (npc_kw * dvStoragePower + npc_kwh * dvStorageEnergy
                            + npc_const * binStorageConst)""",
        """    TotalStorageCapCosts = pulp.lpSum(
        b_npc_kw[b] * bpow[b] + b_npc_kwh[b] * ben[b] + b_npc_const[b] * bconst[b]
        for b in NB)""",
        "storage capital per unit",
    ),
    (
        """    if s.enabled:
        ElectricStorageCapCost = (s.installed_cost_per_kw * dvStoragePower
                                  + s.installed_cost_per_kwh * dvStorageEnergy
                                  + (s.installed_cost_constant * binStorageConst if npc_const else 0.0))
        ElectricStorageOMCost = (pwf_om * s.om_cost_fraction_of_installed_cost
                                 * ElectricStorageCapCost)
    else:
        ElectricStorageCapCost = 0.0
        ElectricStorageOMCost = 0.0""",
        """    if any_storage:
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
        ElectricStorageOMCost = 0.0""",
        "storage O&M per unit",
    ),
])

print("multi-unit storage added")
