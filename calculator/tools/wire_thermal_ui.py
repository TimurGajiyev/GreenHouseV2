"""Wire the thermal subsystem into the Streamlit app and separate the two
fuel-fired technologies REopt distinguishes:

  Prime Generator  gas recip engine, no heat recovery   ($/MMBtu)
  Generator        diesel, off-grid only                ($/gallon)
  CHP              gas recip engine WITH heat recovery  ($/MMBtu) + existing boiler
"""

import io
import os

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "streamlit_app.py")
s = io.open(P, encoding="utf-8").read()


def sub(old, new, what):
    global s
    if old not in s:
        raise SystemExit(f"NOT FOUND: {what}")
    s = s.replace(old, new, 1)
    print(f"  ok  {what}")


# 1. distinguish Prime Generator (gas) from off-grid Generator (diesel)
sub(
    'gen_kind = "CHP" if use_chp else "Generator"',
    'use_prime = "Prime Generator" in techs\n'
    '# REopt\'s Prime Generator is a gas recip engine (no heat recovery); the\n'
    '# off-grid Generator is diesel. CHP is the gas engine WITH heat recovery.\n'
    'gen_kind = "CHP" if (use_chp or use_prime) else "Generator"',
    "gen_kind for prime generator",
)

# 2. Prime Generator panel uses the gas engine inputs, not diesel
sub(
    '''    title = "Combined Heat & Power" if use_chp else (
        "Prime Generator" if "Prime Generator" in techs else "Generator")''',
    '''    title = ("Combined Heat & Power" if use_chp
             else "Prime Generator" if use_prime else "Generator")''',
    "panel title",
)
sub(
    "        if use_chp:\n"
    '            chp0 = {"installed_cost_per_kw": 4510.0, "om_cost_per_kwh": 0.021,\n'
    '                    "electric_efficiency_full_load": 0.3555, "thermal_efficiency_full_load": 0.4376}',
    "        if use_chp or use_prime:\n"
    "            # data/chp/chp_defaults.json -- recip_engine, size class 0.\n"
    "            # A prime generator is the same engine with no heat recovery.\n"
    '            chp0 = {"installed_cost_per_kw": 4510.0, "om_cost_per_kwh": 0.021,\n'
    '                    "electric_efficiency_full_load": 0.3555,\n'
    '                    "thermal_efficiency_full_load": 0.4376 if use_chp else 0.0}',
    "gas engine defaults",
)
sub(
    '''            with c3:
                gen_cfg["thermal_efficiency_full_load"] = st.number_input(
                    "Thermal efficiency at 100% load (HHV)", min_value=0.0, max_value=1.0,
                    value=chp0["thermal_efficiency_full_load"], step=0.005, key="chp_theff")
                gen_cfg["max_kw"] = st.number_input("Maximum electric capacity (kW)",
                                                    min_value=0.0, value=2000.0, step=50.0,
                                                    key="chp_max")
            gen_cfg["om_cost_per_kw"] = 0.0''',
    '''            with c3:
                if use_chp:
                    gen_cfg["thermal_efficiency_full_load"] = st.number_input(
                        "Thermal efficiency at 100% load (HHV)", min_value=0.0, max_value=1.0,
                        value=chp0["thermal_efficiency_full_load"], step=0.005, key="chp_theff")
                else:
                    gen_cfg["thermal_efficiency_full_load"] = 0.0
                    st.caption("A prime generator recovers no heat, so it has no "
                               "thermal efficiency and no boiler credit.")
                gen_cfg["max_kw"] = st.number_input("Maximum electric capacity (kW)",
                                                    min_value=0.0, value=2000.0, step=50.0,
                                                    key="chp_max")
            gen_cfg["om_cost_per_kw"] = 0.0''',
    "thermal efficiency only for CHP",
)

# 3. existing boiler inputs, shown when CHP is selected (REopt requires them)
sub(
    "# ---------------------------------------------------------------- Financial",
    '''# --------------------------------------------- Existing heating system (CHP)
heating_fuel_mmbtu = None
boiler_fuel_cost = 8.0
if use_chp:
    T.panel_head("Existing Heating System", icon="local_fire_department", required=True)
    with st.expander("Heating system inputs", expanded=False):
        st.caption(
            "Selecting CHP makes REopt model the existing boiler too: its fuel cost "
            "enters both the business-as-usual and optimized life cycle cost, and CHP "
            "heat recovery displaces boiler fuel."
        )
        c1, c2 = st.columns(2)
        with c1:
            boiler_fuel_cost = st.number_input(
                "Annual existing heating system fuel cost ($/MMBtu) *",
                min_value=0.0, value=8.0, step=0.5, key="boiler_fuel",
            )
        with c2:
            boiler_eff = st.number_input(
                "Existing heating system efficiency (% HHV-basis)",
                min_value=1.0, max_value=100.0, value=80.0, step=1.0, key="boiler_eff",
            ) / 100.0
        try:
            from reopt_core import data_sources as _ds
            _city, _ = _ds.find_ashrae_zone_city(float(lat), float(lon))
            _h = _ds.heating_load_mmbtu(bldg, _city) if bldg else None
            if _h and _h["fuel_mmbtu"] > 0:
                heating_fuel_mmbtu = _h["fuel_mmbtu"]
                st.caption(
                    f"Heating load for {bldg} in {_city}: "
                    f"space heating {_h['space_heating']:,.0f} + domestic hot water "
                    f"{_h['domestic_hot_water']:,.0f} = **{_h['fuel_mmbtu']:,.0f} MMBtu** of "
                    f"boiler fuel per year, from the tables REopt ships."
                )
            elif bldg:
                st.warning(f"No bundled heating load for {bldg} in {_city}.")
        except Exception as _exc:
            st.warning(f"Heating load lookup failed: {_exc}")
else:
    boiler_eff = 0.8

# ---------------------------------------------------------------- Financial''',
    "existing heating system panel",
)

# 4. pass the thermal inputs to the model
sub(
    "            min_load_met_annual_fraction=float(min_load_met) / 100,",
    "            min_load_met_annual_fraction=float(min_load_met) / 100,\n"
    "            heating_fuel_mmbtu=heating_fuel_mmbtu,\n"
    "            existing_boiler_fuel_cost_per_mmbtu=float(boiler_fuel_cost),\n"
    "            boiler_efficiency=float(boiler_eff),",
    "thermal inputs into the scenario",
)

io.open(P, "w", encoding="utf-8").write(s)
print("thermal UI wired")
