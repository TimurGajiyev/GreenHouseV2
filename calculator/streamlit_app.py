"""REopt-style calculator — steps 1-5, four technologies.

Field labels, option values/order, defaults and help text are generated from a
live extraction of https://reopt.nlr.gov/tool (see reopt_core/ui_fields.py).
Formulas and defaults come from the REopt.jl v0.61.1 source in ../REopt.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

import ui_theme as T
from reopt_core import defaults as D
from reopt_core import ui_fields as U

st.set_page_config(page_title="REopt calculator", page_icon=":material/bolt:", layout="wide")

F = U.FIELDS


# --------------------------------------------------------------- helpers
def meta(fid: str) -> dict:
    return F.get(fid, {})


def label_of(fid: str, fallback: str = "") -> str:
    return (meta(fid).get("label") or fallback).replace(" *", "").strip() or fallback


def help_of(fid: str) -> str | None:
    return meta(fid).get("help") or None


def opts(fid: str) -> list[tuple[str, str]]:
    return U.options(fid)


def default_num(fid: str, fallback: float) -> float:
    raw = (meta(fid).get("default") or "").strip()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def num_input(fid: str, fallback: float, *, key: str, fmt: str = "%.4f",
              min_value: float = 0.0, step: float | None = None, label: str | None = None):
    return st.number_input(
        label or label_of(fid, key),
        min_value=min_value,
        value=float(st.session_state.get(key, default_num(fid, fallback))),
        step=step if step is not None else max(0.01, abs(fallback) / 100 or 0.01),
        format=fmt,
        help=help_of(fid),
        key=key,
    )


def select(fid: str, *, key: str, label: str | None = None, index: int = 0):
    """Mirror a REopt <select>.

    When the real tool ships a blank default (a required field the user must
    choose), keep it blank here too instead of silently selecting the first
    option -- otherwise e.g. "Type of building" would quietly become Hospital.
    """
    o = opts(fid)
    if not o:
        return None
    values = [v for v, _ in o]
    labels = {v: t for v, t in o}
    raw_default = (meta(fid).get("default") or "").strip()
    placeholder = raw_default == "" and (meta(fid).get("options") or [["", ""]])[0][0] == ""

    if placeholder:
        return st.selectbox(
            label or label_of(fid, key),
            values,
            index=None,
            placeholder="Choose an option",
            format_func=lambda v: labels.get(v, v),
            help=help_of(fid),
            key=key,
        )
    if raw_default in values:
        index = values.index(raw_default)
    return st.selectbox(
        label or label_of(fid, key),
        values,
        index=index,
        format_func=lambda v: labels.get(v, v),
        help=help_of(fid),
        key=key,
    )


# ------------------------------------------------------------------ state
ss = st.session_state
ss.setdefault("results", None)

T.inject()
st.title(":material/bolt: REopt calculator")
st.caption(
    "Steps 1–5 of the REopt web tool, limited to Prime Generator / Generator, CHP, PV "
    "and Battery. Inputs mirror reopt.nlr.gov; formulas come from REopt.jl v0.61.1."
)

# ============================================================== Step 1
T.step(U.STEPS[1])
use_case = st.segmented_control(
    "Use case", ["Single site", "Portfolio/sensitivity analysis"],
    default="Single site", key="use_case", label_visibility="collapsed",
)
if use_case != "Single site":
    st.info("Portfolio/sensitivity analysis is disabled in the real tool too. Using single site.")
    use_case = "Single site"

# ============================================================== Step 2
T.step(U.STEPS[2])
grid_mode = st.segmented_control(
    "Grid mode", ["Grid-tied", "Off-grid"], default="Grid-tied",
    key="grid_mode", label_visibility="collapsed",
)
off_grid = grid_mode == "Off-grid"
if off_grid:
    st.caption(
        "Off-grid is modelled as a year-long outage: no electricity tariff is collected, "
        "and there is no business-as-usual case (REopt.jl reopt.jl:117)."
    )

# ============================================================== Step 3
T.step(U.STEPS[3])
goals = st.pills(
    "Energy goals", ["Cost savings", "Resilience"],
    default=["Cost savings"], selection_mode="multi",
    key="goals", label_visibility="collapsed",
)
resilience = "Resilience" in (goals or [])

# ============================================================== Step 4
T.step(U.STEPS[4].replace(" *", ""))
st.caption("This calculator implements four of REopt's technologies.")

if off_grid:
    tech_choices = ["Generator", "Prime Generator", "CHP", "PV", "Battery"]
    st.caption(
        "The REopt **web tool** offers only Generator off-grid, but **REopt.jl does "
        "allow CHP**: `off_grid_flag=true` lists \"CHP\" in `offgrid_allowed_keys` "
        "(scenario.jl:85). Off-grid forbids every heating key, so REopt builds CHP "
        "electric-only there (scenario.jl:531) — no boiler, no heat-recovery credit. "
        "These two cannot be cross-checked against the web tool, which refuses the "
        "submission."
    )
else:
    tech_choices = ["Prime Generator", "CHP", "PV", "Battery"]

techs = st.pills(
    "Technologies", tech_choices, default=["PV", "Battery"], selection_mode="multi",
    key="techs", label_visibility="collapsed",
)
techs = techs or []

# One fuel-fired prime mover at a time. The web tool sets disabled=true on Prime
# Generator when CHP is ticked and vice versa (verified in both orders), and this
# model carries a single fuel_tech slot, so the rule extends to Generator off-grid.
_fuel_picked = [t for t in ("CHP", "Prime Generator", "Generator") if t in techs]
if len(_fuel_picked) > 1:
    st.error(
        "Only one fuel-fired technology at a time — the REopt web tool disables Prime "
        "Generator when CHP is ticked (and vice versa), and this model carries a "
        "single fuel-tech slot. Keeping " + _fuel_picked[0] + "."
    )
    techs = [t for t in techs if t not in _fuel_picked[1:]]

use_pv = "PV" in techs
use_bat = "Battery" in techs
use_chp = "CHP" in techs
use_gen = ("Generator" in techs) or ("Prime Generator" in techs)
use_prime = "Prime Generator" in techs
# REopt's Prime Generator is a gas recip engine (no heat recovery); the
# off-grid Generator is diesel. CHP is the gas engine WITH heat recovery.
gen_kind = "CHP" if (use_chp or use_prime) else "Generator"
gen_label = "CHP" if use_chp else ("Prime Generator" if use_prime else "Generator")

if not techs:
    st.warning("Select at least one technology to continue.")

# ============================================================== Step 5
T.step(U.STEPS[5])

# ---- Step 5 panels, in the REopt order:
# Site -> Utilities -> Load Profiles -> Financial -> Emissions -> PV -> Battery

T.panel_head("Site", icon="location_on", required=True)
with st.expander("Site inputs", expanded=True):
    st.text_input(label_of("run_site_attributes_description", "Evaluation name"),
                  key="description", placeholder="My evaluation")

    use_latlon = st.checkbox(
        label_of("site_use_latitude_longitude", "Use latitude & longitude"),
        key="use_latlon",
        help=help_of("site_use_latitude_longitude"),
    )
    c1, c2 = st.columns(2)
    if use_latlon:
        with c1:
            lat = st.number_input("Latitude", value=39.74437, format="%.5f", key="lat")
        with c2:
            lon = st.number_input("Longitude", value=-105.15199, format="%.5f", key="lon")
    else:
        with c1:
            st.text_input("Site location", value="1617 Cole Blvd, Golden, CO 80401",
                          key="address",
                          help="Coordinates drive the CRB load-profile city and the PVWatts call.")
        with c2:
            st.caption("Geocoding is not wired up; enter coordinates below or tick "
                       "**Use latitude & longitude**.")
        cc1, cc2 = st.columns(2)
        with cc1:
            lat = st.number_input("Latitude", value=39.74437, format="%.5f", key="lat")
        with cc2:
            lon = st.number_input("Longitude", value=-105.15199, format="%.5f", key="lon")

    # PV & Wind space available -- reopt_inputs.jl:620-645 picks the max PV size from this
    space = st.radio(
        "PV & Wind space available",
        ["Land only", "Roofspace only", "Land & roofspace"],
        horizontal=True, key="space",
    )
    pv_location = {"Land only": "ground", "Roofspace only": "roof",
                   "Land & roofspace": "both"}[space]

    c3, c4 = st.columns(2)
    land_acres = None
    roof_sqft = None
    with c3:
        if pv_location in ("ground", "both"):
            land_acres = st.number_input(
                label_of("run_site_attributes_land_acres",
                         "Land available for PV & Wind (acres)"),
                min_value=0.0, value=5.0, step=0.5, key="land_acres",
                help=help_of("run_site_attributes_land_acres"),
            )
    with c4:
        if pv_location in ("roof", "both"):
            roof_sqft = st.number_input(
                "Roofspace available for PV (ft²)", min_value=0.0,
                value=50_000.0, step=1000.0, format="%.0f", key="roof_sqft",
                help="Converted at PV.kw_per_square_foot = 0.01 kW/ft² (pv.jl:23).",
            )
    sector = select("run_site_attributes_attributes_sector", key="sector", label="Sector")

# ---------------------------------------------------------------- Utilities
tariff_mode = "URDB rate"
urdb_label = ""
compensation = "no_compensation"
wholesale_rate = 0.0
nem_limit = None
if not off_grid:
    T.panel_head("Utilities", icon="bolt", required=True)
    with st.expander("Utility inputs", expanded=True):
        custom_rate = st.checkbox(
            label_of("run_site_attributes_electric_tariff_attributes_custom_electricity_rate",
                     "Use custom electricity rate"),
            key="custom_rate",
        )
        tariff_mode = "Custom flat rate" if custom_rate else "URDB rate"

        if not custom_rate:
            if st.button("Search rates for this location", key="find_rates"):
                try:
                    from reopt_core import data_sources as _ds
                    ss["rate_list"] = _ds.urdb_rates_by_location(float(lat), float(lon))
                except Exception as exc:
                    st.error(f"URDB lookup failed: {exc}")
                    ss["rate_list"] = []
            rl = ss.get("rate_list") or []
            if rl:
                labels = {r.get("label", ""): f"{r.get('utility','?')}: {r.get('name','?')}"
                          for r in rl if r.get("label")}
                urdb_label = st.selectbox(
                    "Electricity rate *", list(labels), key="urdb_pick",
                    format_func=lambda v: labels.get(v, v),
                    help="Submitted as `urdb_label`, exactly as the REopt form does.",
                )
            else:
                urdb_label = st.text_input(
                    "Electricity rate * (URDB label)",
                    value="5b44ffc75457a36716a907eb", key="urdb_label",
                    help="Press **Search rates for this location** for a picker, "
                         "or paste a URDB label directly.",
                )
        else:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.number_input("Energy rate ($/kWh)", min_value=0.0, value=0.10,
                                step=0.01, format="%.4f", key="flat_e")
            with c2:
                st.number_input("Monthly demand rate ($/kW)", min_value=0.0, value=0.0,
                                step=1.0, key="flat_d")
            with c3:
                st.number_input("Fixed charge ($/month)", min_value=0.0, value=0.0,
                                step=5.0, key="flat_fixed")

        compensation = select(
            "run_site_attributes_electric_tariff_attributes_compensation_type",
            key="compensation", label="Compensation type",
        ) or "no_compensation"
        if compensation in ("net_metering", "net_meter_net_bill"):
            nem_limit = st.number_input(
                label_of("run_site_attributes_electric_tariff_attributes_net_metering_limit_kw",
                         "Net metering system size limit (kW)") + " *",
                min_value=0.0, value=1000.0, step=50.0, key="nem_limit",
                help="REopt requires this whenever net metering is selected: the upper "
                     "limit on capacity that may participate in the net metering "
                     "agreement (electric_utility.jl:5).",
            )
        if compensation in ("net_billing", "net_meter_net_bill"):
            wholesale_rate = st.number_input(
                "Wholesale export rate ($/kWh)", min_value=0.0, value=0.03,
                step=0.005, format="%.4f", key="wholesale",
            )

# ------------------------------------------------------------ Load profiles
T.panel_head("Load Profiles", icon="bar_chart", required=True)
with st.expander("Load profile inputs", expanded=True):
    c1, c2 = st.columns(2)
    with c1:
        bldg = select("run_site_attributes_load_profile_attributes_doe_reference_name",
                      key="bldg", label="Type of building *")
    with c2:
        load_entry = st.radio("Energy consumption entry", ["Annual", "Monthly"],
                              horizontal=True, key="load_entry")
    if load_entry == "Annual":
        annual_kwh = st.number_input(
            label_of("run_site_attributes_load_profile_attributes_annual_kwh",
                     "Annual energy consumption (kWh)"),
            min_value=0.0, value=5_000_000.0, step=100_000.0, format="%.0f",
            key="annual_kwh",
            help=help_of("run_site_attributes_load_profile_attributes_annual_kwh"),
        )
    else:
        st.caption("Monthly totals (kWh) — the annual sum scales the CRB profile.")
        mcols = st.columns(6)
        monthly = []
        for i, mn in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]):
            with mcols[i % 6]:
                monthly.append(st.number_input(mn, min_value=0.0, value=416_667.0,
                                               step=1000.0, format="%.0f", key=f"m_{i}"))
        annual_kwh = sum(monthly)
        st.caption(f"Annual total: {annual_kwh:,.0f} kWh")

    if off_grid:
        c3, c4 = st.columns(2)
        with c3:
            min_load_met = st.number_input("Minimum load met (%)", min_value=0.0,
                                           max_value=100.0, value=99.9, step=0.1,
                                           key="min_load_met")
        with c4:
            # electric_load.jl:20 -- off-grid default 10%, forced to 0 on-grid
            load_opres = st.number_input(
                "Load operating reserve requirement (%)", min_value=0.0, max_value=100.0,
                value=10.0, step=1.0, key="load_opres",
                help="Share of served load that must be backed by spare capacity at "
                     "every hour. REopt applies this off-grid only (electric_load.jl:20).",
            )
        st.caption("Off-grid runs must serve at least this share of annual load, and "
                   "must hold operating reserve every hour.")
    else:
        min_load_met = 100.0
        load_opres = 0.0

# --------------------------------------------- Existing heating system (CHP)
heating_fuel_mmbtu = None
boiler_fuel_cost = 8.0
# Off-grid has no boiler: scenario.jl:85 rejects the heating keys outright.
if use_chp and not off_grid:
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

# ---------------------------------------------------------------- Financial
T.panel_head("Financial", icon="attach_money")
with st.expander("Financial inputs", expanded=False):
    c1, c2, c3 = st.columns(3)
    with c1:
        analysis_years = st.number_input(
            label_of("run_site_attributes_financial_attributes_analysis_years",
                     "Analysis period (years)"),
            min_value=1, max_value=75, value=int(D.FINANCIAL["analysis_years"]),
            step=1, key="years",
            help=help_of("run_site_attributes_financial_attributes_analysis_years"),
        )
        tax_rate = st.number_input("Host effective tax rate (%)", min_value=0.0,
                                   max_value=100.0,
                                   value=D.FINANCIAL["offtaker_tax_rate_fraction"] * 100,
                                   step=0.1, key="tax")
    with c2:
        discount = st.number_input(
            label_of("run_site_attributes_financial_attributes_offtaker_discount_rate_fraction",
                     "Host discount rate, nominal (%)"),
            min_value=0.0, max_value=100.0,
            value=D.FINANCIAL["offtaker_discount_rate_fraction"] * 100, step=0.01,
            key="disc",
        )
        om_esc = st.number_input("O&M cost escalation rate (%/year)", min_value=-10.0,
                                 max_value=50.0,
                                 value=D.FINANCIAL["om_cost_escalation_rate_fraction"] * 100,
                                 step=0.1, key="om_esc")
    with c3:
        elec_esc = st.number_input(
            label_of("run_site_attributes_financial_attributes_elec_cost_escalation_rate_fraction",
                     "Electricity cost escalation rate, nominal (%/year)"),
            min_value=-10.0, max_value=50.0,
            value=D.FINANCIAL["elec_cost_escalation_rate_fraction"] * 100, step=0.01,
            key="elec_esc",
        )

# ---------------------------------------------------------------- Emissions
T.panel_head("Emissions", icon="eco")
with st.expander("Emissions inputs", expanded=False):
    clean_target = select("run_clean_energy_target", key="clean_target",
                          label="Renewable Energy & Emissions target")
    if clean_target and clean_target != "none":
        st.info(
            "Renewable-energy and emissions targets add constraints in "
            "`renewable_energy_constraints.jl` / `emissions_constraints.jl`. "
            "Those are not ported yet, so this selection is recorded but not enforced."
        )
    cambium_scenario = select(
        "run_site_attributes_electric_tariff_attributes_cambium_scenario",
        key="cambium_scenario", label="Grid scenario") or "Mid-case"
    st.caption(
        "Climate CO2e comes from NLR's Cambium levelized LRMER. Health emissions "
        "(NOx, SO2, PM2.5) use the EPA AVERT hourly factors, and their $/tonne and "
        "escalation rates come from EASIUR. The AVERT region, Cambium location and "
        "EASIUR costs are all resolved from the site coordinates, exactly as the tool "
        "does, and are reported in the results rather than chosen here. "
        "`include_climate_in_objective` / `include_health_in_objective` stay false, "
        "which is the tool's default, so emissions are reported but not optimised against."
    )
pv_cfg: dict = {}
if use_pv:
    T.panel_head("PV", icon="solar_power")
    with st.expander("PV inputs", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            pv_cfg["installed_cost_per_kw"] = st.number_input(
                label_of("run_site_attributes_pv_attributes_installed_cost_per_kw",
                         "System capital cost ($/kW-DC)"),
                min_value=0.0, value=1920.0, step=10.0, key="pv_cost",
                help=help_of("run_site_attributes_pv_attributes_installed_cost_per_kw"),
            )
            pv_cfg["min_kw"] = st.number_input("Minimum new PV size (kW-DC)", min_value=0.0,
                                               value=0.0, step=10.0, key="pv_min")
        with c2:
            pv_cfg["om_cost_per_kw"] = st.number_input(
                "O&M cost ($/kW-DC per year)", min_value=0.0,
                value=float(D.PV["om_cost_per_kw"]), step=1.0, key="pv_om",
            )
            pv_cfg["max_kw"] = st.number_input("Maximum new PV size (kW-DC)", min_value=0.0,
                                               value=2000.0, step=10.0, key="pv_max")
        with c3:
            arr = select("run_site_attributes_pv_attributes_array_type", key="pv_array",
                         label="Array type")
            pv_cfg["array_type_label"] = arr
            pv_cfg["federal_itc_fraction"] = st.number_input(
                "Federal ITC (%)", min_value=0.0, max_value=100.0,
                value=D.PV["federal_itc_fraction"] * 100, step=1.0, key="pv_itc",
            ) / 100.0
            if off_grid:
                # pv.jl:46 -- off-grid default 25%, forced to 0 on-grid (pv.jl:175)
                pv_cfg["operating_reserve_required_fraction"] = st.number_input(
                    "PV operating reserve requirement (%)", min_value=0.0, max_value=100.0,
                    value=25.0, step=1.0, key="pv_opres",
                    help="Share of PV output serving load that must be backed by spare "
                         "capacity elsewhere. Off-grid only (pv.jl:46).",
                ) / 100.0

bat_cfg: dict = {}
if use_bat:
    T.panel_head("Battery", icon="battery_charging_full")
    with st.expander("Battery inputs", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            bat_cfg["installed_cost_per_kwh"] = st.number_input(
                label_of("run_site_attributes_storage_attributes_installed_cost_per_kwh",
                         "Energy capacity cost ($/kWh)"),
                min_value=0.0, value=float(D.ELECTRIC_STORAGE["installed_cost_per_kwh"]),
                step=5.0, key="bat_kwh_cost",
            )
            bat_cfg["min_kwh"] = st.number_input("Minimum energy capacity (kWh)", min_value=0.0,
                                                 value=0.0, step=10.0, key="bat_min_kwh")
        with c2:
            bat_cfg["installed_cost_per_kw"] = st.number_input(
                label_of("run_site_attributes_storage_attributes_installed_cost_per_kw",
                         "Power capacity cost ($/kW)"),
                min_value=0.0, value=float(D.ELECTRIC_STORAGE["installed_cost_per_kw"]),
                step=5.0, key="bat_kw_cost",
            )
            bat_cfg["max_kwh"] = st.number_input("Maximum energy capacity (kWh)", min_value=0.0,
                                                 value=1_000_000.0, step=100.0, key="bat_max_kwh")
        with c3:
            bat_cfg["installed_cost_constant"] = st.number_input(
                label_of("run_site_attributes_storage_attributes_installed_cost_constant",
                         "Constant cost ($)"),
                min_value=0.0, value=float(D.ELECTRIC_STORAGE["installed_cost_constant"]),
                step=1000.0, key="bat_const",
                help="REopt.jl default is $222,115 — a fixed cost added whenever a battery "
                     "is included. It is blank in the real tool's form.",
            )
            bat_cfg["can_grid_charge"] = st.selectbox(
                "Allow grid to charge battery", [True, False],
                format_func=lambda b: "Yes" if b else "No", key="bat_gridchg",
            ) is True

gen_cfg: dict = {}
if use_gen or use_chp:
    title = ("Combined Heat & Power" if use_chp
             else "Prime Generator" if use_prime else "Generator")
    with st.expander(title, expanded=False):
        gd = D.generator_defaults(off_grid_flag=off_grid, only_runs_during_grid_outage=False,
                                  analysis_years=int(analysis_years))
        c1, c2, c3 = st.columns(3)
        if use_chp or use_prime:
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
                )
            with c1:
                gen_cfg["installed_cost_per_kw"] = st.number_input(
                    "Installed cost ($/kW)", min_value=0.0,
                    value=chp0["installed_cost_per_kw"], step=50.0, key="chp_cost",
                    help="REopt/data/chp/chp_defaults.json — recip_engine, size class 0.")
                gen_cfg["fuel_cost_per_mmbtu"] = st.number_input(
                    "Annual CHP fuel cost ($/MMBtu)", min_value=0.0, value=8.0, step=0.5,
                    key="chp_fuel")
            with c2:
                gen_cfg["electric_efficiency_full_load"] = st.number_input(
                    "Electric efficiency at 100% load (HHV)", min_value=0.01, max_value=1.0,
                    value=chp0["electric_efficiency_full_load"], step=0.005, key="chp_eff")
                gen_cfg["om_cost_per_kwh"] = st.number_input(
                    "Variable O&M ($/kWh)", min_value=0.0, value=chp0["om_cost_per_kwh"],
                    step=0.001, format="%.3f", key="chp_omkwh")
            with c3:
                if use_chp and not off_grid:
                    gen_cfg["thermal_efficiency_full_load"] = st.number_input(
                        "Thermal efficiency at 100% load (HHV)", min_value=0.0, max_value=1.0,
                        value=chp0["thermal_efficiency_full_load"], step=0.005, key="chp_theff")
                else:
                    gen_cfg["thermal_efficiency_full_load"] = 0.0
                    st.caption("Electric-only: no heat recovery, so no thermal "
                               "efficiency and no boiler credit.")
                gen_cfg["max_kw"] = st.number_input("Maximum electric capacity (kW)",
                                                    min_value=0.0, value=2000.0, step=50.0,
                                                    key="chp_max")
            gen_cfg["om_cost_per_kw"] = 0.0
        else:
            with c1:
                gen_cfg["installed_cost_per_kw"] = st.number_input(
                    "Installed cost ($/kW)", min_value=0.0,
                    value=float(gd["installed_cost_per_kw"]), step=10.0, key="gen_cost")
                gen_cfg["fuel_cost_per_gallon"] = st.number_input(
                    "Fuel cost ($/gallon)", min_value=0.0,
                    value=float(gd["fuel_cost_per_gallon"]), step=0.05, key="gen_fuel")
            with c2:
                gen_cfg["electric_efficiency_full_load"] = st.number_input(
                    "Electric efficiency at 100% load", min_value=0.01, max_value=1.0,
                    value=float(gd["electric_efficiency_full_load"]), step=0.005, key="gen_eff")
                gen_cfg["om_cost_per_kw"] = st.number_input(
                    "Fixed O&M ($/kW/yr)", min_value=0.0, value=float(gd["om_cost_per_kw"]),
                    step=1.0, key="gen_om")
            with c3:
                gen_cfg["max_kw"] = st.number_input("Maximum capacity (kW)", min_value=0.0,
                                                    value=5000.0, step=50.0, key="gen_max")
                gen_cfg["om_cost_per_kwh"] = st.number_input(
                    "Variable O&M ($/kWh)", min_value=0.0, value=float(gd["om_cost_per_kwh"]),
                    step=0.001, format="%.3f", key="gen_omkwh")
            gen_cfg["replacement_year"] = int(gd["replacement_year"])
            gen_cfg["replace_cost_per_kw"] = float(gd["replace_cost_per_kw"])

st.divider()
_missing = []
if not bldg:
    _missing.append("Type of building")
if _missing:
    st.warning("Required, not yet chosen: " + ", ".join(_missing))
run = st.button("Get results", type="primary", width="stretch",
                disabled=(not techs) or bool(_missing))



def _opt_label(fid: str, value):
    """REopt shows the option label, not its value (no_compensation ->
    'No compensation for exports')."""
    for v, t in U.options(fid):
        if v == value:
            return t
    return value

# --- REopt "Your Inputs" echo -------------------------------------------------
# Row labels come from ui_fields.py (scraped from the live tool) so the Inputs
# table reads exactly like REopt's, not like our internal variable names.
_PV_ROWS = [
    ("installed_cost_per_kw", "run_site_attributes_pv_attributes_installed_cost_per_kw", "num"),
    ("min_kw", "run_site_attributes_pv_attributes_min_kw", "num"),
    ("max_kw", "run_site_attributes_pv_attributes_max_kw", "num"),
    ("om_cost_per_kw", "run_site_attributes_pv_attributes_om_cost_per_kw", "money2"),
    ("federal_itc_fraction", None, "pct"),
]
_BAT_ROWS = [
    ("installed_cost_per_kwh", "run_site_attributes_storage_attributes_installed_cost_per_kwh", "money2"),
    ("installed_cost_per_kw", "run_site_attributes_storage_attributes_installed_cost_per_kw", "money2"),
    ("installed_cost_constant", "run_site_attributes_storage_attributes_installed_cost_constant", "money2"),
    ("om_cost_fraction_of_installed_cost",
     "run_site_attributes_storage_attributes_om_cost_fraction_of_installed_cost", "raw"),
    ("min_kwh", "run_site_attributes_storage_attributes_min_kwh", "num"),
    ("max_kwh", "run_site_attributes_storage_attributes_max_kwh", "num"),
    ("can_grid_charge", "run_site_attributes_storage_attributes_can_grid_charge", "yesno"),
]
_GEN_LABELS = {
    "installed_cost_per_kw": "Installed cost ($/kW)",
    "fuel_cost_per_gallon": "Fuel cost ($/gallon)",
    "fuel_cost_per_mmbtu": "Annual CHP fuel cost ($/MMBtu)",
    "electric_efficiency_full_load": "Electric efficiency at 100% load",
    "thermal_efficiency_full_load": "Thermal efficiency at 100% load (HHV)",
    "om_cost_per_kw": "Fixed O&M ($/kW/yr)",
    "om_cost_per_kwh": "Variable O&M ($/kWh)",
    "max_kw": "Maximum capacity (kW)",
    "replacement_year": "Replacement year",
    "replace_cost_per_kw": "Replacement cost ($/kW)",
}
_SPACE_LABEL = {"Land only": "Land", "Roofspace only": "Roofspace",
                "Land & roofspace": "Land & roofspace"}


def _fmt(kind, v):
    if v is None or v == "":
        return "—"
    if kind == "num":
        return f"{float(v):,.1f}"
    if kind == "money2":
        return f"${float(v):,.2f}"
    if kind == "pct":
        return f"{float(v) * 100:.0f}%"
    if kind == "yesno":
        return "Yes" if v in (True, "true", "Yes") else "No"
    return str(v)


def _rows(cfg, spec):
    out = {}
    for key, fid, kind in spec:
        if key not in cfg:
            continue
        if fid:
            lab = (U.field(fid).get("label") or key).replace(" *", "").strip()
            # REopt renders this one oddly (its label captured as "30%")
            if key == "federal_itc_fraction" or lab.endswith("%") and lab[0].isdigit():
                lab = "Federal percentage-based incentive (%)"
        else:
            lab = "Federal percentage-based incentive (%)"
        out[lab] = _fmt(kind, cfg[key])
    return out


def _inputs_echo(**k):
    site = {
        "Evaluation name": k["description"] or "—",
        "Site Location": f"{k['address']} ({k['lat']}, {k['lon']})",
        "PV & wind space available": _SPACE_LABEL.get(k["space"], k["space"]),
    }
    if k["land_acres"]:
        site["Land available (acres)"] = f"{k['land_acres']:g}"
    if k["roof_sqft"]:
        site["Roofspace available (ft2)"] = f"{k['roof_sqft']:,.0f}"
    if k["sector"]:
        site["Sector"] = k["sector"]

    utilities = {}
    if not k["off_grid"]:
        tar = k["tariff"]
        utilities["Electricity rate source"] = (
            "URDB rate" if k["tariff_mode"] == "URDB rate" else "Custom flat rate")
        if tar is not None:
            utilities["URDB rate"] = f"{tar.utility} - {tar.name}"
        utilities["Compensation type"] = _opt_label(
            "run_site_attributes_electric_tariff_attributes_compensation_type",
            k["compensation"])

    load = {
        "Typical electric load profile type": "simulated building",
        # REopt shows the building LABEL ("Office - Large"), not the value
        "Type of building": _opt_label(
            "run_site_attributes_load_profile_attributes_doe_reference_name",
            k["bldg"]) if k["bldg"] else "—",
        "Annual electric energy consumption (kWh)": f"{k['annual_kwh']:,.0f}",
    }
    # %g drops float noise: 6.239999999999999 -> 6.24, 26.0 -> 26
    financial = {
        "Analysis period (years)": int(k["analysis_years"]),
        "Host discount rate, nominal (%)": f"{float(k['discount']):g}%",
        "Electricity cost escalation rate, nominal (%/year)": f"{float(k['elec_esc']):g}%",
        "O&M cost escalation rate (%/year)": f"{float(k['om_esc']):g}%",
        "Host effective tax rate (%)": f"{float(k['tax_rate']):g}%",
    }
    emissions = {}
    em = k.get("emissions")
    if em:
        emissions = {
            "Cambium location": em["cambium_location"],
            "Cambium Levelization Years": int(k["analysis_years"]),
            "EPA's AVERT Region": em["avert_region"],
        }

    echo = {
        "Energy Goals": {"Goals": ", ".join(k["goals"] or ["Cost savings"])},
        "Technologies Selected": {"Technologies": ", ".join(k["techs"])},
        "Site": site,
        "Utilities": utilities,
        "Load Profile": load,
        "Financial": financial,
        "Renewable Energy & Emissions Accounting": emissions,
    }
    if k["use_pv"]:
        echo["PV"] = _rows(k["pv_cfg"], _PV_ROWS)
    if k["use_bat"]:
        echo["Battery"] = _rows(k["bat_cfg"], _BAT_ROWS)
    if k["use_gen"] and k["gen_cfg"]:
        echo[k["gen_kind"]] = {
            _GEN_LABELS.get(key, key): (f"{v:,.4g}" if isinstance(v, (int, float)) else str(v))
            for key, v in k["gen_cfg"].items()
        }
    return {g: rows for g, rows in echo.items() if rows}

# ------------------------------------------------------------------- run
if run:
    from reopt_core import data_sources as ds
    from reopt_core import model as M
    from reopt_core.tariff import build_tariff, flat_tariff

    prog = st.progress(0.0, text="Building load profile…")
    try:
        load = ds.build_electric_load(bldg, float(annual_kwh), float(lat), float(lon))
        prog.progress(0.25, text=f"Load profile from {load['city']} — calling PVWatts…")

        pf = [0.0] * 8760
        if use_pv:
            array_map = {"Ground Mount, Fixed": 0, "Rooftop, Fixed": 1,
                         "Ground Mount, 1-Axis Tracking": 2, "1-Axis Backtracking": 3,
                         "Ground Mount, 2-Axis Tracking": 4}
            at = array_map.get(pv_cfg.get("array_type_label") or "", 1)
            pf, _ = ds.call_pvwatts_api(float(lat), float(lon),
                                        tilt=20 if at in (0, 1) else 0,
                                        azimuth=180, array_type=at, module_type=0, losses=14)
        prog.progress(0.5, text="Fetching tariff…")

        tar = None
        if not off_grid:
            if tariff_mode == "URDB rate" and urdb_label.strip():
                tar = build_tariff(ds.fetch_urdb_rate(urdb_label.strip()))
            else:
                tar = flat_tariff(float(ss.get("flat_e", 0.10)),
                                  float(ss.get("flat_d", 0.0)),
                                  float(ss.get("flat_fixed", 0.0)))
        prog.progress(0.65, text="Solving (HiGHS)…")

        fin = M.FinancialInputs(
            analysis_years=int(analysis_years),
            elec_cost_escalation_rate_fraction=float(elec_esc) / 100,
            om_cost_escalation_rate_fraction=float(om_esc) / 100,
            offtaker_discount_rate_fraction=float(discount) / 100,
            offtaker_tax_rate_fraction=float(tax_rate) / 100,
        )
        # Streamlit reloads this script but keeps imported modules cached, so an
        # old reopt_core.model can linger after an edit. Filter to the fields the
        # loaded dataclass actually has and say so, instead of a bare TypeError.
        import dataclasses as _dc
        _known = {f.name for f in _dc.fields(M.ScenarioInputs)}

        def _scenario(**kw):
            unknown = sorted(set(kw) - _known)
            if unknown:
                st.warning(
                    "Ignoring " + ", ".join(unknown) + " — the loaded reopt_core.model "
                    "is older than this page. Restart Streamlit to pick up the change."
                )
            return M.ScenarioInputs(**{k: v for k, v in kw.items() if k in _known})

        inp = _scenario(
            loads_kw=load["loads_kw"],
            tariff=tar,
            financial=fin,
            pv=M.PVInputs(enabled=use_pv, production_factor=pf,
                          **{k: v for k, v in pv_cfg.items() if k != "array_type_label"}),
            storage=M.StorageInputs(enabled=use_bat, **bat_cfg),
            fuel_tech=M.FuelTechInputs(enabled=(use_gen or use_chp), kind=gen_kind,
                                       label=gen_label, **gen_cfg),
            off_grid_flag=off_grid,
            land_acres=(float(land_acres) if land_acres else None),
            roof_squarefeet=(float(roof_sqft) if roof_sqft else None),
            pv_location=pv_location,
            compensation_type=compensation,
            wholesale_rate=float(wholesale_rate),
            net_metering_limit_kw=(float(nem_limit) if nem_limit else None),
            min_load_met_annual_fraction=float(min_load_met) / 100,
            operating_reserve_required_fraction=float(load_opres) / 100,
            heating_fuel_mmbtu=heating_fuel_mmbtu,
            existing_boiler_fuel_cost_per_mmbtu=float(boiler_fuel_cost),
            boiler_efficiency=float(boiler_eff),
        )
        res = M.solve(inp, time_limit=600)
        bau = M.business_as_usual(inp)

        emis = None
        if not off_grid:
            prog.progress(0.9, text="Fetching grid emissions factors…")
            try:
                from reopt_core import emissions as EM
                cam = EM.fetch_cambium_profile(
                    float(lat), float(lon), scenario=cambium_scenario,
                    start_year=EM.EMISSIONS_DEFAULTS["cambium_start_year"],
                    lifetime=int(analysis_years))
                prof = EM.fetch_avert_profile(float(lat), float(lon))
                avert_region = prof["avert_region"] or "Rocky Mountains"
                av = prof["series"] or {
                    p: EM.load_avert_profile(p, avert_region) for p in ("NOx", "SO2", "PM25")}
                health = EM.fetch_health_cost_defaults(
                    float(lat), float(lon), inflation=float(om_esc) / 100)
                grid_opt = res["series"]["grid_kw"]
                grid_bau = load["loads_kw"]
                common = dict(cambium_series=cam["series"], avert=av,
                              years=int(analysis_years),
                              discount_rate=float(discount) / 100, opts=health)
                emis = {
                    "bau": EM.compute(grid_kwh_hourly=grid_bau, **common),
                    "opt": EM.compute(grid_kwh_hourly=grid_opt, **common),
                    "cambium_location": cam["location"],
                    "avert_region": avert_region,
                    "health_costs": health,
                }
            except Exception as exc:
                st.warning(f"Emissions factors unavailable: {exc}")
        prog.progress(1.0, text="Done")
        ss["results"] = {
            "res": res, "bau": bau, "load": load, "tariff": tar, "emissions": emis,
            "off_grid": off_grid, "inp_years": int(analysis_years),
            "tax_rate": float(tax_rate) / 100,
            "om_esc": float(om_esc),
            "compensation": _opt_label(
                "run_site_attributes_electric_tariff_attributes_compensation_type",
                compensation),
            "used_pv": use_pv,
            "used_battery": use_bat,
            "inputs_echo": _inputs_echo(
                goals=goals, techs=techs, off_grid=off_grid,
                description=ss.get("description", ""),
                address=ss.get("address", ""), lat=lat, lon=lon,
                space=space, land_acres=land_acres, roof_sqft=roof_sqft,
                sector=sector, tariff=tar, tariff_mode=tariff_mode,
                compensation=compensation, bldg=bldg, annual_kwh=annual_kwh,
                analysis_years=analysis_years, discount=discount,
                elec_esc=elec_esc, om_esc=om_esc, tax_rate=tax_rate,
                use_pv=use_pv, pv_cfg=pv_cfg, use_bat=use_bat, bat_cfg=bat_cfg,
                use_gen=(use_gen or use_chp), gen_cfg=gen_cfg, gen_kind=gen_kind,
                emissions=emis,
            ),
        }
    except Exception as exc:  # surface the real reason, do not swallow it
        prog.empty()
        st.error(f"Run failed: {exc}")
        ss["results"] = None

# --------------------------------------------------------------- results
if ss.get("results"):
    from app_results import render_results
    render_results(ss["results"])
