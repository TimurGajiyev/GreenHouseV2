"""Unit-commitment details beyond REopt, plus a horizon that follows the load.

Added so the CHP + BESS problem in CHP_BESS_model_v2.xlsx can be posed exactly:

  * FuelTechInputs.start_cost          cost per start event (15,000 tenge there)
  * FuelTechInputs.min_up_hours        hours a unit stays on after a start (4)
  * FuelTechInputs.min_down_hours      hours a unit stays off after a stop (5)
  * FuelTechInputs.can_curtail         spill output a turndown floor forces out;
                                       REopt gives every tech dvCurtail (reopt.jl:656)
  * StorageInputs.discharge_cost_per_kwh   cell wear per kWh discharged (0.5 tenge)
  * solve(..., mip_gap=)               relative MIP gap passed to HiGHS
  * horizon = len(loads_kw)            so a 168-hour week can be solved as posed

REopt has no start cost, no min up / min down and no cycling cost. Every field
defaults to "off", and "off" creates no variable and no constraint, so any
scenario that does not set them builds the same LP as before. The horizon is
8,760 whenever the load is 8,760 hours long, which every existing caller passes.

Also fixes a latent crash: the per-unit start count read ftu[g][t - 1], which at
t = 0 is key -1 and raises KeyError whenever a unit is on in the first hour.
"""

import io
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def patch(rel, edits):
    p = os.path.join(BASE, rel)
    s = io.open(p, encoding="utf-8").read()
    for old, new, what in edits:
        n = s.count(old)
        if n != 1:
            raise SystemExit("anchor for {!r} found {} times in {}".format(what, n, rel))
        s = s.replace(old, new, 1)
        print("  ok  {}: {}".format(rel, what))
    io.open(p, "w", encoding="utf-8").write(s)


patch("reopt_core/model.py", [
    # ---------------------------------------------------------------- inputs
    (
        """    total_itc_fraction: float = 0.3
    # Free-text name, used only for labelling results.
    name: str = \"\"""",
        """    total_itc_fraction: float = 0.3
    # Free-text name, used only for labelling results.
    name: str = \"\"
    # Beyond REopt: wear cost per kWh discharged. 0 adds nothing to the model.
    discharge_cost_per_kwh: float = 0.0""",
        "storage: discharge (cell wear) cost",
    ),
    (
        """    min_turn_down_fraction: float = 0.0""",
        """    min_turn_down_fraction: float = 0.0
    # ---- beyond REopt: unit-commitment details, every one off by default ----
    # Cost per start event. REopt prices no starts. 0 creates no variables.
    start_cost: float = 0.0
    # Hours a unit must stay on after a start / off after a stop. 1 = no rule.
    min_up_hours: int = 1
    min_down_hours: int = 1
    # Let a unit spill output it cannot deliver. It is still paid for (O&M and
    # fuel are charged on rated production) but it does not reach the load.
    # REopt has dvCurtail for every tech (reopt.jl:656); this port had it for PV only.
    can_curtail: bool = False""",
        "fuel tech: start cost, min up/down, curtailment",
    ),

    # --------------------------------------------------------------- horizon
    (
        """def solve(inp: ScenarioInputs, *, time_limit: int = 300, msg: bool = False) -> dict:
    f = inp.financial
    T = list(range(HOURS))""",
        """def solve(inp: ScenarioInputs, *, time_limit: int = 300, msg: bool = False,
          mip_gap: float | None = None) -> dict:
    f = inp.financial
    # The horizon follows the load. Every annual caller passes 8,760 hours, so
    # this is HOURS for them; a 168-hour week can now be solved as posed.
    H = len(inp.loads_kw)
    T = list(range(H))""",
        "solve: horizon from the load, optional MIP gap",
    ),
    (
        """        ft_needs_bin[g] = bool(u.enabled and (ic > 0.0 or u.min_turn_down_fraction > 0.0))""",
        """        ft_needs_bin[g] = bool(u.enabled and (
            ic > 0.0 or u.min_turn_down_fraction > 0.0
            or u.start_cost > 0.0 or u.min_up_hours > 1 or u.min_down_hours > 1))""",
        "binary also needed for starts and min up/down",
    ),

    # ------------------------------------------------------------- variables
    (
        """    ftprod = {t: pulp.lpSum(ftgen[g][t] for g in NG) for t in T}
    ftu = {g: ({t: pulp.LpVariable(f"ftON_{g}_{t}", cat="Binary") for t in T}
               if ft_needs_bin[g] else None) for g in NG}""",
        """    # ftgen is RATED production -- what O&M, fuel and the turndown floor see.
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
                                               or fts[g].min_down_hours > 1))
                   for g in NG}
    ftsu = {g: ({t: pulp.LpVariable(f"ftSU_{g}_{t}", lowBound=0, upBound=1) for t in T}
                if ft_needs_uc[g] else None) for g in NG}
    ftsd = {g: ({t: pulp.LpVariable(f"ftSD_{g}_{t}", lowBound=0, upBound=1) for t in T}
                if ft_needs_uc[g] else None) for g in NG}""",
        "curtailment and start/stop variables",
    ),

    # ------------------------------------------------------------ PV / export
    (
        """    pf = inp.pv.production_factor or [0.0] * HOURS""",
        """    pf = inp.pv.production_factor or [0.0] * H""",
        "PV production factor sized to the horizon",
    ),
    (
        """            export_rate = [inp.wholesale_rate] * HOURS""",
        """            export_rate = [inp.wholesale_rate] * H""",
        "wholesale export rate sized to the horizon",
    ),
    (
        """            export_rate = [0.0] * HOURS""",
        """            export_rate = [0.0] * H""",
        "zero export rate sized to the horizon",
    ),

    # ----------------------------------------------------------- constraints
    (
        """    # Land use -- tech_constraints.jl:26-31""",
        """    # ---- beyond REopt: spill, starts, minimum up and down time ----
    for g in NG:
        if ftcurt[g] is not None:
            for t in T:
                m += ftcurt[g][t] <= ftgen[g][t], f"ft_curt_{g}_{t}"
        if ftsu[g] is None:
            continue
        MU = max(1, int(fts[g].min_up_hours))
        MD = max(1, int(fts[g].min_down_hours))
        for t in T:
            # cyclic, like the state-of-charge balance: the period is closed
            prev = ftu[g][T[-1]] if t == 0 else ftu[g][t - 1]
            m += ftsu[g][t] - ftsd[g][t] == ftu[g][t] - prev, f"ft_switch_{g}_{t}"
            if MU > 1:
                m += (ftu[g][t] >= pulp.lpSum(ftsu[g][(t - k) % H] for k in range(MU))
                      ), f"ft_minup_{g}_{t}"
            if MD > 1:
                m += (1 - ftu[g][t] >= pulp.lpSum(ftsd[g][(t - k) % H] for k in range(MD))
                      ), f"ft_mindown_{g}_{t}"

    # Land use -- tech_constraints.jl:26-31""",
        "curtailment bound, switching logic, min up / min down",
    ),
    (
        """    tar = inp.tariff
    tou_peak, mon_peak = [], []""",
        """    tar = inp.tariff
    # A horizon shorter than a year keeps only the demand-period hours it contains.
    tou_periods = ([[t for t in hrs if t < H] for hrs in tar.tou_demand_periods]
                   if tar is not None else [])
    mon_periods = ([[t for t in hrs if t < H] for hrs in tar.monthly_demand_periods]
                   if tar is not None else [])
    tou_peak, mon_peak = [], []""",
        "demand periods trimmed to the horizon",
    ),
    (
        """        for i, hrs in enumerate(tar.tou_demand_periods):
            for t in hrs:
                m += tou_peak[i] >= grid[t] + gridchg[t], f"toupk_{i}_{t}"
        for mo in range(12):
            for t in tar.monthly_demand_periods[mo]:""",
        """        for i, hrs in enumerate(tou_periods):
            for t in hrs:
                m += tou_peak[i] >= grid[t] + gridchg[t], f"toupk_{i}_{t}"
        for mo in range(12):
            for t in mon_periods[mo]:""",
        "peak tracking over the trimmed periods",
    ),

    # ------------------------------------------------------------- objective
    (
        """    m += (TotalTechCapCosts + TotalStorageCapCosts""",
        """    # Beyond REopt. Built only when some unit carries the cost, so a scenario
    # without them adds a literal 0.0 and the objective is unchanged.
    _start_terms = [fts[g].start_cost * pulp.lpSum(ftsu[g][t] for t in T)
                    for g in NG if ftsu[g] is not None and fts[g].start_cost > 0.0]
    TotalStartCosts = pwf_om * pulp.lpSum(_start_terms) if _start_terms else 0.0
    _cycle_terms = [sts[b].discharge_cost_per_kwh * pulp.lpSum(bdis[b][t] for t in T)
                    for b in NB if sts[b].enabled and sts[b].discharge_cost_per_kwh > 0.0]
    TotalCyclingCosts = pwf_om * pulp.lpSum(_cycle_terms) if _cycle_terms else 0.0

    m += (TotalTechCapCosts + TotalStorageCapCosts""",
        "start and cycling cost expressions",
    ),
    (
        """          + ExistingBoilerFuelCost * (1 - tax_off)), "Costs\"""",
        """          + ExistingBoilerFuelCost * (1 - tax_off)
          + (TotalStartCosts + TotalCyclingCosts) * (1 - tax_own)), "Costs\"""",
        "start and cycling costs in the objective",
    ),
    (
        """    solver = pulp.HiGHS(msg=msg, timeLimit=time_limit)""",
        """    _hopts = dict(msg=msg, timeLimit=time_limit)
    if mip_gap is not None:
        _hopts["gapRel"] = mip_gap
    solver = pulp.HiGHS(**_hopts)""",
        "pass the MIP gap to HiGHS",
    ),

    # --------------------------------------------------------------- results
    (
        """            "capacity_factor": (kwh / (kw * HOURS)) if kw > 1e-9 else 0.0,""",
        """            "capacity_factor": (kwh / (kw * H)) if kw > 1e-9 else 0.0,
            "spill_kwh": (sum(v(ftcurt[g][t]) for t in T) if ftcurt[g] is not None else 0.0),""",
        "capacity factor over the horizon, spill per unit",
    ),
    (
        """                           if v(ftu[g][t]) > 0.5 and v(ftu[g][t - 1]) < 0.5)""",
        """                           if v(ftu[g][t]) > 0.5 and v(ftu[g][(t - 1) % H]) < 0.5)""",
        "start count: fix KeyError at t = 0",
    ),
    (
        """        "fueltech_unit_on": {""",
        """        "fueltech_unit_spill_kw": {
            (fts[g].name or fts[g].label or f"Unit {g + 1}"): [v(ftcurt[g][t]) for t in T]
            for g in NG if fts[g].enabled and ftcurt[g] is not None
        },
        "fueltech_unit_on": {""",
        "per-unit spill series",
    ),
    (
        """            "year1_storage": bat_om_y1,
        },""",
        """            "year1_storage": bat_om_y1,
            "year1_starts": sum(fts[g].start_cost * sum(v(ftsu[g][t]) for t in T)
                                for g in NG if ftsu[g] is not None),
            "year1_storage_cycling": sum(sts[b].discharge_cost_per_kwh
                                         * sum(v(bdis[b][t]) for t in T)
                                         for b in NB if sts[b].enabled),
        },""",
        "start and cycling costs in the O&M results",
    ),
    (
        """        y1_om_total = (out["om"]["year1_pv"] + out["om"]["year1_storage"]
                       + out["om"]["year1_fueltech"])""",
        """        y1_om_total = (out["om"]["year1_pv"] + out["om"]["year1_storage"]
                       + out["om"]["year1_fueltech"] + out["om"]["year1_starts"]
                       + out["om"]["year1_storage_cycling"])""",
        "proforma O&M includes starts and cycling",
    ),
    (
        """                     + sum(r_ * max(loads[h] for h in hrs)
                           for r_, hrs in zip(tar.tou_demand_rates, tar.tou_demand_periods))
                     + sum(tar.monthly_demand_rates[mo] * max(loads[h] for h in tar.monthly_demand_periods[mo])
                           for mo in range(12))""",
        """                     + sum(r_ * max((loads[h] for h in hrs), default=0.0)
                           for r_, hrs in zip(tar.tou_demand_rates, tou_periods))
                     + sum(tar.monthly_demand_rates[mo] * max((loads[h] for h in mon_periods[mo]), default=0.0)
                           for mo in range(12))""",
        "proforma BAU bill over the trimmed periods",
    ),
    (
        """    T = range(HOURS)
    energy = sum(tar.energy_cost_per_kwh[t] * inp.loads_kw[t] for t in T)
    tou = sum(tar.tou_demand_rates[i] * max(inp.loads_kw[t] for t in hrs)
              for i, hrs in enumerate(tar.tou_demand_periods))
    mon = sum(tar.monthly_demand_rates[mo] * max(inp.loads_kw[t] for t in tar.monthly_demand_periods[mo])
              for mo in range(12))""",
        """    H = len(inp.loads_kw)
    T = range(H)
    energy = sum(tar.energy_cost_per_kwh[t] * inp.loads_kw[t] for t in T)
    tou = sum(tar.tou_demand_rates[i] * max((inp.loads_kw[t] for t in hrs if t < H), default=0.0)
              for i, hrs in enumerate(tar.tou_demand_periods))
    mon = sum(tar.monthly_demand_rates[mo]
              * max((inp.loads_kw[t] for t in tar.monthly_demand_periods[mo] if t < H), default=0.0)
              for mo in range(12))""",
        "BAU over the horizon",
    ),
])

print("unit commitment extensions added")
