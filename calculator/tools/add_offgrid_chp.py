"""Allow CHP / Prime Generator off-grid, the way REopt.jl (not the web tool) does.

REopt.jl permits CHP off-grid -- scenario.jl:85 lists "CHP" in offgrid_allowed_keys --
but the web tool's `offgrid` config ships no CHP fields at all. Off-grid also forbids
every heating key, so REopt constructs CHP electric-only there (scenario.jl:531).

While wiring this up, two genuine defaults bugs surfaced and are fixed here:

  1. chp.jl:419-421 multiplies installed_cost_per_kw and om_cost_per_kwh by 0.75
     when is_electric_only. Our Prime Generator was using the full CHP cost.
  2. The captured web-tool spec ships CHP with macrs_option_years=5 /
     macrs_bonus_fraction=1, and Prime Generator with 0 / 0. We applied 0/0 to both.

Neither showed up in the G1/G2 validation because CHP sized to 0 kW there, so the
capital-cost slope never entered the objective.
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


# ------------------------------------------------------------------ defaults
patch("reopt_core/defaults.py", [
    (
        "# -------------------------------------------------------------- Site / CRB",
        '''def chp_defaults(is_electric_only: bool = False) -> dict:
    """recip_engine, size class 0 -- REopt/data/chp/chp_defaults.json.

    chp.jl:419-421 scales installed_cost_per_kw and om_cost_per_kwh by 0.75 for an
    electric-only unit (a Prime Generator), and chp.jl:405-411 zeroes its thermal
    efficiency. MACRS comes from the captured web-tool spec: CHP ships 5-year MACRS
    with 100% bonus, Prime Generator ships none.
    """
    factor = 0.75 if is_electric_only else 1.0
    return {
        "installed_cost_per_kw": 4510.0 * factor,
        "om_cost_per_kwh": 0.021 * factor,
        "om_cost_per_kw": 0.0,
        "electric_efficiency_full_load": 0.3555,
        "thermal_efficiency_full_load": 0.0 if is_electric_only else 0.4376,
        "min_turn_down_fraction": 0.25,
        "fuel_cost_per_mmbtu": 8.0,
        "macrs_option_years": 0 if is_electric_only else 5,
        "macrs_bonus_fraction": 0.0 if is_electric_only else 1.0,
        "macrs_itc_reduction": 0.0,
        "federal_itc_fraction": 0.0,
    }


# -------------------------------------------------------------- Site / CRB''',
        "chp_defaults()",
    ),
])

# --------------------------------------------------------------------- model
patch("reopt_core/model.py", [
    (
        """    # ---- existing boiler + CHP thermal credit ----
    # Thermal load the boiler must serve, less whatever CHP recovers.
    thermal_load_mmbtu = ((inp.heating_fuel_mmbtu or 0.0) * inp.boiler_efficiency)""",
        """    # ---- existing boiler + CHP thermal credit ----
    # Off-grid forbids every heating key -- scenario.jl:85's offgrid_allowed_keys has
    # no SpaceHeatingLoad / DomesticHotWaterLoad / ExistingBoiler -- so REopt builds
    # CHP electric-only there (scenario.jl:531). Mirror that: no boiler off-grid.
    _heat_fuel = None if inp.off_grid_flag else inp.heating_fuel_mmbtu
    # Thermal load the boiler must serve, less whatever CHP recovers.
    thermal_load_mmbtu = ((_heat_fuel or 0.0) * inp.boiler_efficiency)""",
        "off-grid forces electric-only",
    ),
    (
        '''        "thermal": {
            "heating_fuel_mmbtu": inp.heating_fuel_mmbtu or 0.0,''',
        '''        "thermal": {
            "heating_fuel_mmbtu": _heat_fuel or 0.0,''',
        "thermal result uses the off-grid-aware value",
    ),
    (
        """    boiler_lcc = 0.0
    if inp.heating_fuel_mmbtu:""",
        """    boiler_lcc = 0.0
    if inp.heating_fuel_mmbtu and not inp.off_grid_flag:""",
        "BAU boiler skipped off-grid",
    ),
    (
        '''        "year1_boiler_fuel_cost": ((inp.heating_fuel_mmbtu or 0.0)
                                   * inp.existing_boiler_fuel_cost_per_mmbtu),''',
        '''        "year1_boiler_fuel_cost": (0.0 if inp.off_grid_flag else
                                   (inp.heating_fuel_mmbtu or 0.0)
                                   * inp.existing_boiler_fuel_cost_per_mmbtu),''',
        "BAU boiler year-1 skipped off-grid",
    ),
])

# ----------------------------------------------------------------------- app
patch("streamlit_app.py", [
    (
        '''if off_grid:
    tech_choices = ["Generator", "PV", "Battery"]
    st.caption(
        "CHP and Prime Generator are not offered off-grid by the web tool "
        "(REopt.jl does allow CHP off-grid — see scenario.jl:85)."
    )
else:
    tech_choices = ["Prime Generator", "CHP", "PV", "Battery"]''',
        '''if off_grid:
    tech_choices = ["Generator", "Prime Generator", "CHP", "PV", "Battery"]
    st.caption(
        "The REopt **web tool** offers only Generator off-grid, but **REopt.jl does "
        "allow CHP**: `off_grid_flag=true` lists \\"CHP\\" in `offgrid_allowed_keys` "
        "(scenario.jl:85). Off-grid forbids every heating key, so REopt builds CHP "
        "electric-only there (scenario.jl:531) — no boiler, no heat-recovery credit. "
        "These two cannot be cross-checked against the web tool, which refuses the "
        "submission."
    )
else:
    tech_choices = ["Prime Generator", "CHP", "PV", "Battery"]''',
        "off-grid tech list",
    ),
    (
        '''# Prime Generator and CHP are mutually exclusive in the web tool (verified).
if "Prime Generator" in techs and "CHP" in techs:
    st.error(
        "Prime Generator and CHP are mutually exclusive — the REopt web tool disables "
        "one when the other is selected. Keeping CHP."
    )
    techs = [t for t in techs if t != "Prime Generator"]''',
        '''# One fuel-fired prime mover at a time. The web tool sets disabled=true on Prime
# Generator when CHP is ticked and vice versa (verified in both orders), and this
# model carries a single fuel_tech slot, so the rule extends to Generator off-grid.
_fuel_picked = [t for t in ("CHP", "Prime Generator", "Generator") if t in techs]
if len(_fuel_picked) > 1:
    st.error(
        "Only one fuel-fired technology at a time — the REopt web tool disables Prime "
        "Generator when CHP is ticked (and vice versa), and this model carries a "
        "single fuel-tech slot. Keeping " + _fuel_picked[0] + "."
    )
    techs = [t for t in techs if t not in _fuel_picked[1:]]''',
        "single fuel tech guard",
    ),
    (
        """heating_fuel_mmbtu = None
boiler_fuel_cost = 8.0
if use_chp:""",
        """heating_fuel_mmbtu = None
boiler_fuel_cost = 8.0
# Off-grid has no boiler: scenario.jl:85 rejects the heating keys outright.
if use_chp and not off_grid:""",
        "heating panel is grid-tied only",
    ),
    (
        '''        if use_chp or use_prime:
            # data/chp/chp_defaults.json -- recip_engine, size class 0.
            # A prime generator is the same engine with no heat recovery.
            chp0 = {"installed_cost_per_kw": 4510.0, "om_cost_per_kwh": 0.021,
                    "electric_efficiency_full_load": 0.3555,
                    "thermal_efficiency_full_load": 0.4376 if use_chp else 0.0}''',
        '''        if use_chp or use_prime:
            # data/chp/chp_defaults.json -- recip_engine, size class 0. A prime
            # generator is the same engine electric-only, which chp.jl:419-421
            # prices at 0.75x. Off-grid CHP is electric-only too (scenario.jl:531).
            chp0 = D.chp_defaults(is_electric_only=(use_prime or off_grid))
            for _k in ("macrs_option_years", "macrs_bonus_fraction",
                       "macrs_itc_reduction", "federal_itc_fraction"):
                gen_cfg[_k] = chp0[_k]
            if use_chp and off_grid:
                st.caption(
                    "Off-grid CHP is modelled electric-only — REopt forbids heating "
                    "loads off-grid (scenario.jl:85), so there is no heat to recover."
                )''',
        "chp defaults from defaults.py",
    ),
    (
        '''            with c3:
                if use_chp:
                    gen_cfg["thermal_efficiency_full_load"] = st.number_input(''',
        '''            with c3:
                if use_chp and not off_grid:
                    gen_cfg["thermal_efficiency_full_load"] = st.number_input(''',
        "thermal efficiency hidden off-grid",
    ),
    (
        '''                else:
                    gen_cfg["thermal_efficiency_full_load"] = 0.0
                    st.caption("A prime generator recovers no heat, so it has no "
                               "thermal efficiency and no boiler credit.")''',
        '''                else:
                    gen_cfg["thermal_efficiency_full_load"] = 0.0
                    st.caption("Electric-only: no heat recovery, so no thermal "
                               "efficiency and no boiler credit.")''',
        "electric-only caption",
    ),
])

print("off-grid CHP enabled")
