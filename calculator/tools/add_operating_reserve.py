"""Port REopt's off-grid operating-reserve constraints.

REopt/src/constraints/operating_reserve_constraints.jl, verbatim in structure.
Measured cost of omitting it (OG1 vs REopt run 431b38d4): PV +42.9%, diesel
-26.3%, upfront capital +22.5%. Life cycle cost was almost unaffected (-0.4%),
so the omission distorts the SIZING, not the economics.

Everything here is gated on off_grid_flag, and REopt itself forces every
operating_reserve_required_fraction to 0.0 when on-grid (electric_load.jl:127,
pv.jl:175, wind.jl:172, chp.jl:321). Grid-tied results therefore cannot move.

Defaults, all off-grid only:
  load 0.10  electric_load.jl:20      PV 0.25  pv.jl:46      CHP/Generator 0.0
PV is in BOTH requiring_oper_res and providing_oper_res (techs.jl:368-371):
it needs 25% backup for what it serves, and can offer its unused headroom.
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
    # ---- inputs ----
    (
        "    acres_per_kw: float = 6e-3\n"
        "    production_factor: list[float] = field(default_factory=list)\n"
        "    can_curtail: bool = True",
        "    acres_per_kw: float = 6e-3\n"
        "    production_factor: list[float] = field(default_factory=list)\n"
        "    can_curtail: bool = True\n"
        "    # pv.jl:46 -- off-grid only; REopt zeroes it on-grid (pv.jl:175)\n"
        "    operating_reserve_required_fraction: float = 0.25",
        "PV operating reserve input",
    ),
    (
        "    min_load_met_annual_fraction: float = 0.99999",
        "    min_load_met_annual_fraction: float = 0.99999\n"
        "    # electric_load.jl:20 -- off-grid only; REopt zeroes it on-grid (:127)\n"
        "    operating_reserve_required_fraction: float = 0.1",
        "load operating reserve input",
    ),
    (
        "    only_runs_during_grid_outage: bool = False",
        "    only_runs_during_grid_outage: bool = False\n"
        "    # chp.jl:45 -- 0 means the unit PROVIDES reserve rather than requiring it\n"
        "    operating_reserve_required_fraction: float = 0.0",
        "fuel tech operating reserve input",
    ),

    # ---- constraints ----
    (
        """    if inp.off_grid_flag:
        for t in T:
            m += grid[t] == 0, f"nogrid_{t}"
            m += gridchg[t] == 0, f"nogridchg2_{t}"
        # min_load_met_annual_fraction -- ElectricLoad off-grid input
        m += pulp.lpSum(unserved[t] for t in T) <= (1 - inp.min_load_met_annual_fraction) * sum(loads), "min_load_met\"""",
        """    if inp.off_grid_flag:
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
        f_ft = ft.operating_reserve_required_fraction if ft.enabled else 0.0
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
                if ft.enabled and f_ft == 0.0:
                    m += or_ft[t] <= dvFTsize - ftprod[t], f"or_ft_{t}"
                else:
                    m += or_ft[t] == 0, f"or_ft_{t}"
                # 3. battery: bounded by usable stored energy and by its power rating
                if s.enabled:
                    prev = soc[T[-1]] if t == 0 else soc[t - 1]
                    m += or_bat[t] <= prev - s.soc_min_fraction * dvStorageEnergy \\
                         - dis[t] / s.discharge_efficiency, f"or_bat_e_{t}"
                    m += or_bat[t] <= dvStoragePower - dis[t] / s.discharge_efficiency, f"or_bat_p_{t}"
                else:
                    m += or_bat[t] == 0, f"or_bat_{t}"
                # 6. provided >= required
                m += or_pv[t] + or_ft[t] + or_bat[t] >= required, f"or_bal_{t}\"""",
        "operating reserve constraints",
    ),
])

print("operating reserve added")
