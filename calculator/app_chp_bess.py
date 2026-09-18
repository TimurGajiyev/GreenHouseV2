"""The REopt web tool's CHP and Battery inputs, field for field.

Source of truth: ``reopt_test_data/chp-bess-panels.json`` -- a live capture of
https://reopt.nlr.gov/tool (grid-tied, CHP + Battery), walked in DOM order once
collapsed and once with "Advanced inputs" open, plus every field that a checkbox
reveals. Labels, order, sections, option lists and placeholders are copied from
it; nothing here is named or grouped by us.

REopt places these inputs across four panels, and so does this module:

  Utilities       Fuel Costs (heating system and CHP fuel type and $/MMBtu,
                  optionally by month) and, under Advanced inputs, the CHP
                  standby charge
  Load Profiles   the typical heating system fuel load
  Financial       the heating-fuel and CHP-fuel escalation rates
  Battery         8 inputs, 19 more under Advanced inputs
  CHP             13 inputs, 31 more under Advanced inputs

Every input starts blank with REopt's default as its placeholder, exactly as the
tool does; a blank field means "use the default". The CHP defaults are not
constants: like the tool, they are derived from the site's heating load (prime
mover, size class, size-cost pairs, efficiencies, minimum size, turndown,
maximum size) by ``reopt_core.chp_defaults``, a verbatim port of chp.jl.
"""

from __future__ import annotations

import csv
import io
import math

import streamlit as st

from reopt_core import chp_defaults as C
from reopt_core import data_sources as ds
from reopt_core import defaults as D
from reopt_core import ui_fields as U

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
FUEL_TYPES = [("natural_gas", "natural gas"), ("diesel", "diesel"), ("propane", "propane"),
              ("biogas", "biogas")]
PRIME_MOVERS = [("recip_engine", "Reciprocating engine"), ("micro_turbine", "Microturbine"),
                ("combustion_turbine", "Combustion turbine"), ("fuel_cell", "Fuel cell")]
MACRS_YEARS = [(0, "No MACRS"), (5, "5 years"), (7, "7 years")]
MACRS_BONUS = [(0.0, "0%"), (0.2, "20%"), (0.4, "40%"), (0.6, "60%"), (0.8, "80%"), (1.0, "100%")]
DISPATCH_STRATEGY = [("cost_optimal", "Cost Optimal (perfect foresight)"),
                     ("backup", "Backup mode"),
                     ("custom_soc", "Custom hourly state of charge")]
CHP_DISPATCH = [("cost_optimal", "Cost optimal"),
                ("follow_electrical_load", "Electrical load-following"),
                ("follow_heating_load", "Heating load-following (beta)")]
PROCESS_TYPES = ["FlatLoad", "FlatLoad_24_5", "FlatLoad_16_7", "FlatLoad_16_5",
                 "FlatLoad_8_7", "FlatLoad_8_5"]
UNLIMITED = 1.0e10


# ------------------------------------------------------------------ inputs
def _num(label: str, key: str, placeholder: str, *, fmt: str | None = None,
         min_value: float | None = 0.0, max_value: float | None = None,
         step: float | None = None, help: str | None = None, disabled: bool = False,
         label_visibility: str = "visible"):
    """A REopt text input: blank shows the default, blank returns None."""
    kw = dict(value=None, placeholder=placeholder, key=key, help=help, disabled=disabled,
              label_visibility=label_visibility)
    if min_value is not None:
        kw["min_value"] = min_value
    if max_value is not None:
        kw["max_value"] = max_value
    if step is not None:
        kw["step"] = step
    if fmt is not None:
        kw["format"] = fmt
    return st.number_input(label, **kw)


def _or(v, default):
    return default if v is None else v


def _pct(v, default_fraction):
    """A percent field: typed as percent, returned as a fraction."""
    return default_fraction if v is None else float(v) / 100.0


def _select(label: str, options: list[tuple], key: str, default, *, disabled: bool = False,
            label_visibility: str = "visible"):
    values = [o[0] for o in options]
    names = dict(options)
    kw = {}
    if st.session_state.get(key) not in values:
        # a value already in session state is the selection; passing an index
        # as well makes Streamlit warn about two sources for one widget
        st.session_state.pop(key, None)
        kw["index"] = values.index(default) if default in values else 0
    return st.selectbox(label, values, key=key, disabled=disabled,
                        format_func=lambda v: names.get(v, v), label_visibility=label_visibility, **kw)


def _reset_button(prefix: str, key: str):
    if st.button("Reset to default values", key=key, icon=":material/refresh:", type="tertiary"):
        for k in [k for k in st.session_state.keys() if str(k).startswith(prefix)]:
            del st.session_state[k]
        st.rerun()


def _read_series(upload, *, n: int = 8760, percent_ok: bool = True) -> list[float] | None:
    """One value per line (or the first column of a CSV), 8,760 of them."""
    if upload is None:
        return None
    text = upload.getvalue().decode("utf-8", errors="replace")
    vals = []
    for row in csv.reader(io.StringIO(text)):
        for cell in row:
            cell = cell.strip()
            if not cell:
                continue
            try:
                vals.append(float(cell))
            except ValueError:
                pass            # a header
            break
    if len(vals) != n:
        st.error(f"Expected {n:,} values, found {len(vals):,}.")
        return None
    if percent_ok and max(vals) > 1.0:
        vals = [v / 100.0 for v in vals]
    return vals


def _heading(text: str, level: int = 4):
    st.markdown(f"{'#' * level} {text}")


# ============================================================== Utilities
def render_fuel_costs() -> dict:
    """Utilities > Fuel Costs, shown when CHP is selected."""
    _heading("Fuel Costs", 5)
    out: dict = {}
    out["boiler_fuel_type"] = _select("Existing heating system fuel type", FUEL_TYPES,
                                      "ub_boiler_fuel_type", "natural_gas")
    monthly_b = st.checkbox("Heating system fuel cost varies by month?", key="ub_monthly_boiler")
    if monthly_b:
        cols = st.columns(6)
        vals = []
        for i, mn in enumerate(MONTHS):
            with cols[i % 6]:
                vals.append(_num(mn, f"ub_boiler_m{i}", "", fmt="%.2f"))
        out["boiler_fuel_monthly"] = vals
        out["boiler_fuel_cost"] = None
    else:
        out["boiler_fuel_cost"] = _num("* Annual existing heating system fuel cost ($/MMBtu)",
                                       "ub_boiler_fuel_cost", "", fmt="%.2f")
        out["boiler_fuel_monthly"] = None
    out["chp_fuel_type"] = _select("CHP fuel type", FUEL_TYPES, "ub_chp_fuel_type", "natural_gas")
    monthly_c = st.checkbox("CHP fuel cost varies by month?", key="ub_monthly_chp")
    if monthly_c:
        cols = st.columns(6)
        vals = []
        for i, mn in enumerate(MONTHS):
            with cols[i % 6]:
                vals.append(_num(mn, f"ub_chp_m{i}", "", fmt="%.2f"))
        out["chp_fuel_monthly"] = vals
        out["chp_fuel_cost"] = None
    else:
        out["chp_fuel_cost"] = _num("* Annual CHP fuel cost ($/MMBtu)", "ub_chp_fuel_cost", "",
                                    fmt="%.2f")
        out["chp_fuel_monthly"] = None
    return out


def fuel_costs_missing(fc: dict) -> list[str]:
    miss = []
    if fc.get("boiler_fuel_monthly") is not None:
        if any(v is None for v in fc["boiler_fuel_monthly"]):
            miss.append("Heating system fuel cost for every month")
    elif fc.get("boiler_fuel_cost") is None:
        miss.append("Annual existing heating system fuel cost ($/MMBtu)")
    if fc.get("chp_fuel_monthly") is not None:
        if any(v is None for v in fc["chp_fuel_monthly"]):
            miss.append("CHP fuel cost for every month")
    elif fc.get("chp_fuel_cost") is None:
        miss.append("Annual CHP fuel cost ($/MMBtu)")
    return miss


def render_standby_charge() -> float:
    """Utilities > Advanced inputs > Electricity Standby Charges."""
    _heading("Electricity Standby Charges", 5)
    return _or(_num("CHP standby charge based on CHP size ($/kW/month)", "ub_standby", "0",
                    fmt="%.2f"), 0.0)


# ========================================================== Load Profiles
def _building_options() -> list[tuple[str, str]]:
    return [o for o in U.options("run_site_attributes_load_profile_attributes_doe_reference_name")
            if o[0]]


def render_heating_load(lat: float, lon: float) -> dict:
    """Load Profiles > * Typical heating system fuel load."""
    _heading("* Typical heating system fuel load", 5)
    split = st.checkbox("Separately input space heating and domestic hot water loads",
                        key="hl_split")
    process = st.checkbox("Add separate higher temperature process heat load", key="hl_process")
    bld = _building_options()
    city, _zone = ds.find_ashrae_zone_city(float(lat), float(lon))
    out = {"split": split, "process": process, "city": city}

    def _one(prefix: str, title: str | None, kind: str | None):
        if title:
            st.markdown(f"**{title}**")
        b = st.selectbox("* Type of building", [v for v, _ in bld], index=None,
                         placeholder="Choose an option", key=f"{prefix}_bldg",
                         format_func=lambda v: dict(bld).get(v, v))
        entry = st.radio("Energy consumption entry", ["Annual", "Monthly"], horizontal=True,
                         key=f"{prefix}_entry", label_visibility="collapsed")
        crb = None
        if b:
            h = ds.heating_load_mmbtu(b, city)
            crb = h[kind] if kind else h["fuel_mmbtu"]
        annual = monthly = None
        if entry == "Annual":
            annual = _num("Annual heating system fuel consumption (MMBtu)", f"{prefix}_annual",
                          f"{crb:.0f}" if crb else "", fmt="%.0f")
        else:
            cols = st.columns(6)
            monthly = []
            for i, mn in enumerate(MONTHS):
                with cols[i % 6]:
                    monthly.append(_num(mn, f"{prefix}_m{i}", "", fmt="%.0f"))
        addr = _num("Addressable load percent (%)", f"{prefix}_addr", "100%", fmt="%.1f",
                    max_value=100.0)
        return {"building": b, "annual": annual, "monthly": monthly,
                "addressable": _pct(addr, 1.0), "crb_mmbtu": crb}

    if split:
        out["space_heating"] = _one("hl_sh", "Space heating", "space_heating")
        out["dhw"] = _one("hl_dhw", "Domestic hot water", "domestic_hot_water")
    else:
        out["total"] = _one("hl_tot", None, None)
    if process:
        st.markdown("**Process heat**")
        pb = st.selectbox("* Type of building", PROCESS_TYPES, index=None,
                          placeholder="Choose an option", key="hl_proc_bldg",
                          format_func=lambda v: dict(U.options(
                              "run_site_attributes_load_profile_attributes_doe_reference_name")
                          ).get(v, v))
        pa = _num("Annual heating system fuel consumption (MMBtu)", "hl_proc_annual", "", fmt="%.0f")
        pp = _num("Addressable load percent (%)", "hl_proc_addr", "100%", fmt="%.1f", max_value=100.0)
        out["process_heat"] = {"building": pb, "annual": pa, "addressable": _pct(pp, 1.0)}

    out["boiler_efficiency"] = _pct(_num("Existing heating system efficiency (% HHV-basis)",
                                         "hl_boiler_eff", "80%", fmt="%.1f", max_value=100.0), 0.8)
    out["max_thermal_factor"] = _or(_num("Max. boiler thermal capacity as factor of peak heating load",
                                         "hl_max_factor", "1.25", fmt="%.2f"), 1.25)
    out["boiler_cost_per_mmbtu_hr"] = _or(_num("Total installed cost for existing boiler ($/MMBtu/hr)",
                                               "hl_boiler_cost_rate", "$0", fmt="%.2f"), 0.0)
    out["boiler_cost_dollars"] = _or(_num("Total installed cost for existing boiler ($)",
                                          "hl_boiler_cost_dollars", "$0", fmt="%.0f"), 0.0)
    return out


def avg_fuel_from_inputs(hl: dict | None, lat: float, lon: float) -> float | None:
    """Average boiler FUEL load (MMBtu/h) -- what chp.jl sizes the CHP from.

    Pure arithmetic on the entered (or CRB default) annual fuel, so the CHP
    placeholders update without rebuilding the 8,760-hour profile on every rerun.
    """
    if not hl:
        return None

    def part(p_):
        if not p_ or not p_.get("building"):
            return None
        if p_.get("monthly") and all(v is not None for v in p_["monthly"]):
            return sum(p_["monthly"]) * p_["addressable"]
        if p_.get("annual") is not None:
            return p_["annual"] * p_["addressable"]
        return p_.get("crb_mmbtu") or 0.0

    parts = [hl.get("space_heating"), hl.get("dhw")] if hl.get("split") else [hl.get("total")]
    vals = [part(p_) for p_ in parts]
    if any(v is None for v in vals):
        return None
    total = sum(vals)
    ph = hl.get("process_heat") if hl.get("process") else None
    if ph and ph.get("building"):
        total += (ph["annual"] if ph["annual"] is not None else 10000.0) * ph["addressable"]
    return total / 8760.0


def heating_load_missing(hl: dict) -> list[str]:
    miss = []
    parts = [hl.get("space_heating"), hl.get("dhw")] if hl.get("split") else [hl.get("total")]
    for p_ in parts:
        if p_ is not None and not p_.get("building"):
            miss.append("Type of building (heating load)")
            break
    if hl.get("process") and not (hl.get("process_heat") or {}).get("building"):
        miss.append("Type of building (process heat)")
    return miss


def build_heating_profile(hl: dict, lat: float, lon: float) -> dict:
    """Hourly heating THERMAL load for the model, from the Load Profiles inputs."""
    eff = hl["boiler_efficiency"]
    total = [0.0] * 8760
    fuel = 0.0
    unaddr = 0.0

    def _add(res):
        nonlocal fuel, unaddr
        for t in range(8760):
            total[t] += res["loads_kw"][t]
        fuel += res["annual_fuel_mmbtu"]
        unaddr += res["unaddressable_fuel_mmbtu"]

    if hl["split"]:
        for part, kind in ((hl["space_heating"], "space_heating"), (hl["dhw"], "domestic_hot_water")):
            _add(_single_kind(part, kind, lat, lon, eff))
    else:
        p_ = hl["total"]
        _add(ds.build_heating_load(p_["building"], lat, lon, annual_mmbtu=p_["annual"],
                                   monthly_mmbtu=(p_["monthly"] if p_["monthly"] and all(
                                       v is not None for v in p_["monthly"]) else None),
                                   addressable_load_fraction=p_["addressable"],
                                   boiler_efficiency=eff))
    if hl["process"] and hl.get("process_heat", {}).get("building"):
        ph = hl["process_heat"]
        # process heat CRB defaults are the flat industrial loads (heating_cooling_loads.jl:208)
        norm = ds.custom_normalized_flatload(ph["building"])
        default = 10000.0          # heating_cooling_loads.jl:212, FlatLoad process heat
        mmbtu = (ph["annual"] if ph["annual"] is not None else default) * ph["addressable"]
        kw = [v * mmbtu * eff * 293.07107 for v in norm]
        _add({"loads_kw": kw, "annual_fuel_mmbtu": sum(kw) / (eff * 293.07107),
              "unaddressable_fuel_mmbtu": (ph["annual"] or default) * (1 - ph["addressable"])})
    return {"loads_kw": total, "annual_fuel_mmbtu": fuel, "unaddressable_fuel_mmbtu": unaddr,
            "avg_fuel_mmbtu_per_hour": fuel / 8760.0, "peak_kw": max(total) if total else 0.0,
            "boiler_efficiency": eff}


def _single_kind(p_: dict, kind: str, lat: float, lon: float, eff: float) -> dict:
    """One of space heating / hot water, entered on its own."""
    city, _ = ds.find_ashrae_zone_city(lat, lon)
    norm = ds.load_crb_profile(p_["building"], city, kind=kind)
    default = ds.heating_load_mmbtu(p_["building"], city)[kind]
    months = ds._month_hours_2017()
    scale = [1.0] * 12
    if p_["monthly"] and all(v is not None for v in p_["monthly"]):
        energy = 1.0
        for mo, hrs in enumerate(months):
            tot = sum(norm[h] for h in hrs)
            scale[mo] = 0.0 if tot == 0 else p_["monthly"][mo] * p_["addressable"] / tot
        unaddr = sum(p_["monthly"]) * (1 - p_["addressable"])
    elif p_["annual"] is not None:
        energy = p_["annual"] * p_["addressable"]
        unaddr = p_["annual"] * (1 - p_["addressable"])
    else:
        energy, unaddr = default, 0.0
    kw = []
    for mo, hrs in enumerate(months):
        for h in hrs:
            kw.append(norm[h] * energy * scale[mo] * eff * 293.07107)
    return {"loads_kw": kw, "annual_fuel_mmbtu": sum(kw) / (eff * 293.07107),
            "unaddressable_fuel_mmbtu": unaddr}


# ============================================================== Financial
def render_financial_fuel() -> dict:
    """Financial: the two fuel escalation rates REopt shows when CHP is selected."""
    return {
        "boiler_escalation": _pct(_num(
            "Existing heating system fuel cost escalation rate, nominal (%/year)",
            "fin_boiler_esc", "3.48%", fmt="%.2f", min_value=-10.0), 0.0348),
        "chp_escalation": _pct(_num(
            "CHP fuel cost escalation rate, nominal (%/year)",
            "fin_chp_esc", "3.48%", fmt="%.2f", min_value=-10.0), 0.0348),
    }


# ================================================================ Battery
def render_battery(off_grid: bool = False) -> dict:
    """Battery panel: 8 inputs, then 19 under Advanced inputs."""
    SD = D.ELECTRIC_STORAGE
    r: dict = {}
    r["installed_cost_per_kwh"] = _or(_num("Energy capacity cost ($/kWh)", "bt_kwh_cost",
                                           f"${SD['installed_cost_per_kwh']:,.0f}", fmt="%.2f"),
                                      float(SD["installed_cost_per_kwh"]))
    r["installed_cost_per_kw"] = _or(_num("Power capacity cost ($/kW)", "bt_kw_cost",
                                          f"${SD['installed_cost_per_kw']:,.0f}", fmt="%.2f"),
                                     float(SD["installed_cost_per_kw"]))
    r["installed_cost_constant"] = _or(_num("Constant cost ($)", "bt_const",
                                            f"${SD['installed_cost_constant']:,.0f}", fmt="%.0f"),
                                       float(SD["installed_cost_constant"]))
    r["om_cost_fraction_of_installed_cost"] = _pct(_num(
        "Annual O&M cost as a percent of upfront cost (%)", "bt_om", "2.5%", fmt="%.2f",
        max_value=100.0), 0.025)
    if not off_grid:
        r["can_grid_charge"] = _select("Allow grid to charge battery", [(True, "Yes"), (False, "No")],
                                       "bt_gridchg", True)
    strategy = _select("Battery dispatch strategy", DISPATCH_STRATEGY, "bt_strategy", "cost_optimal")
    fixed_soc = None
    if strategy == "custom_soc":
        up = st.file_uploader("Upload hourly state of charge (8,760 values, % or fraction)",
                              type=["csv", "txt"], key="bt_soc_upload")
        fixed_soc = _read_series(up)
        if fixed_soc is None:
            st.caption("REopt requires the hourly state-of-charge profile for this strategy.")
    r["min_kwh"] = _or(_num("Minimum energy capacity (kWh)", "bt_min_kwh", "0", fmt="%.0f"), 0.0)
    r["max_kwh"] = _or(_num("Maximum energy capacity (kWh)", "bt_max_kwh", "Unlimited", fmt="%.0f"),
                       1.0e6)

    adv = st.toggle("Advanced inputs", key="bt_adv")
    rect, internal, inv = 0.96, 0.975, 0.96
    # electric_storage.jl:205 -- backup mode changes the default minimum SOC to 80%
    soc_min_default = 0.8 if strategy == "backup" else 0.2
    r["soc_min_fraction"] = soc_min_default
    r["soc_init_fraction"] = 0.5
    r.update(replace_cost_per_kwh=0.0, battery_replacement_year=10, replace_cost_per_kw=0.0,
             inverter_replacement_year=10, replace_cost_constant=0.0,
             cost_constant_replacement_year=10, min_kw=0.0, max_kw=1.0e4,
             min_duration_hours=0.0, max_duration_hours=100000.0, total_itc_fraction=0.3,
             total_rebate_per_kw=0.0, macrs_option_years=5, macrs_bonus_fraction=1.0)
    if adv:
        _heading("Battery Replacement Costs")
        r["replace_cost_per_kwh"] = _or(_num("Energy capacity replacement cost ($/kWh)",
                                             "bt_rep_kwh", "$0", fmt="%.2f"), 0.0)
        r["battery_replacement_year"] = int(_or(_num("Energy capacity replacement year",
                                                     "bt_rep_kwh_yr", "10", fmt="%.0f"), 10))
        r["replace_cost_per_kw"] = _or(_num("Power capacity replacement cost ($/kW)",
                                            "bt_rep_kw", "$0", fmt="%.2f"), 0.0)
        r["inverter_replacement_year"] = int(_or(_num("Power capacity replacement year",
                                                      "bt_rep_kw_yr", "10", fmt="%.0f"), 10))
        r["replace_cost_constant"] = _or(_num("Constant replacement cost ($)", "bt_rep_const",
                                              "$0", fmt="%.0f"), 0.0)
        r["cost_constant_replacement_year"] = int(_or(_num("Constant replacement year",
                                                           "bt_rep_const_yr", "10", fmt="%.0f"), 10))
        _heading("Battery Characteristics")
        r["min_kw"] = _or(_num("Minimum power capacity (kW)", "bt_min_kw", "0", fmt="%.0f"), 0.0)
        r["max_kw"] = _or(_num("Maximum power capacity (kW)", "bt_max_kw", "Unlimited", fmt="%.0f"),
                          1.0e4)
        r["min_duration_hours"] = _or(_num("Minimum battery duration (hours)", "bt_min_dur", "0",
                                           fmt="%.2f"), 0.0)
        r["max_duration_hours"] = _or(_num("Maximum battery duration (hours)", "bt_max_dur",
                                           "Unlimited", fmt="%.2f"), 100000.0)
        rect = _pct(_num("Rectifier efficiency (%)", "bt_rect", "96%", fmt="%.1f", max_value=100.0), 0.96)
        internal = _pct(_num("Round trip efficiency (%)", "bt_internal", "97.5%", fmt="%.1f",
                             max_value=100.0), 0.975)
        inv = _pct(_num("Inverter efficiency (%)", "bt_inv", "96%", fmt="%.1f", max_value=100.0), 0.96)
        r["soc_min_fraction"] = _pct(_num("Minimum state of charge (%)", "bt_soc_min",
                                          f"{soc_min_default * 100:.0f}%", fmt="%.1f",
                                          max_value=100.0), soc_min_default)
        r["soc_init_fraction"] = _pct(_num("Initial state of charge (%)", "bt_soc_init", "50%",
                                           fmt="%.1f", max_value=100.0), 0.5)
        _heading("Battery Incentives and Tax Treatment")
        _heading("Capital Cost Based Incentives", 5)
        r["total_itc_fraction"] = _pct(_num("Total percentage-based incentive (%)", "bt_itc", "30%",
                                            fmt="%.1f", max_value=100.0), 0.3)
        r["total_rebate_per_kw"] = _or(_num("Total power capacity rebate ($/kW)", "bt_rebate",
                                            "$0", fmt="%.2f"), 0.0)
        _heading("Tax Treatment", 5)
        r["macrs_option_years"] = _select("MACRS schedule", MACRS_YEARS, "bt_macrs", 5)
        r["macrs_bonus_fraction"] = _select("MACRS bonus depreciation", MACRS_BONUS, "bt_bonus", 1.0)
    _reset_button("bt_", "bt_reset")

    # electric_storage.jl: efficiencies are built from the three the form asks for
    r["charge_efficiency"] = rect * internal ** 0.5
    r["discharge_efficiency"] = inv * internal ** 0.5
    r["grid_charge_efficiency"] = r["charge_efficiency"] if r.get("can_grid_charge", False) else 0.0
    if off_grid:
        r["can_grid_charge"] = False
    r["macrs_itc_reduction"] = 0.5
    r["fixed_soc_series_fraction"] = fixed_soc
    return {"inputs": r, "dispatch_strategy": strategy,
            "efficiencies": {"rectifier": rect, "internal": internal, "inverter": inv}}


# ==================================================================== CHP
def _size_class_options(prime_mover: str) -> list[tuple[int, str]]:
    bounds = C._all()[prime_mover]["tech_sizes_for_cost_curve"]
    return [(k, f"Size Class {k} ({lo:,.0f} - {hi:,.0f} kW)") for k, (lo, hi) in enumerate(bounds)]


def chp_site_defaults(avg_fuel_mmbtu_per_hour: float | None, boiler_efficiency: float, *,
                      prime_mover: str | None = None, size_class: int | None = None,
                      max_kw: float = float("nan")) -> dict:
    """chp.jl:479 on the site's heating load -- what the tool prints as placeholders."""
    return C.get_chp_defaults_prime_mover_size_class(
        avg_boiler_fuel_load_mmbtu_per_hour=avg_fuel_mmbtu_per_hour,
        boiler_efficiency=boiler_efficiency, prime_mover=prime_mover, size_class=size_class,
        max_kw=max_kw)


def render_chp(avg_fuel_mmbtu_per_hour: float | None, boiler_efficiency: float) -> dict:
    """CHP panel: 13 inputs, then 31 under Advanced inputs."""
    custom = bool(st.session_state.get("cp_custom", False))
    pm_sel = st.session_state.get("cp_pm") if custom else None
    sc_sel = st.session_state.get("cp_sc") if custom else None
    d = chp_site_defaults(avg_fuel_mmbtu_per_hour, boiler_efficiency,
                          prime_mover=pm_sel, size_class=sc_sel)
    di = d["default_inputs"]
    pm, sc = d["prime_mover"], d["size_class"]
    if not custom:
        # the disabled boxes follow the heating load, as on the site; a keyed widget
        # would otherwise keep whatever it showed on its first render
        st.session_state["cp_pm"], st.session_state["cp_sc"] = pm, sc

    _select("Prime mover type", PRIME_MOVERS, "cp_pm", pm, disabled=not custom)
    sc_opts = _size_class_options(pm)
    if st.session_state.get("cp_sc") not in [o[0] for o in sc_opts]:
        st.session_state.pop("cp_sc", None)
    _select("Size class", sc_opts, "cp_sc", sc, disabled=not custom)
    if d["chp_elec_size_heuristic_kw"] is not None:
        # the tool truncates (170.57 kW prints as 170)
        st.caption(f"Electric capacity sized based on the average load for all 8,760 hours of the "
                   f"year = {int(d['chp_elec_size_heuristic_kw']):,} kW (Size Class {sc})")
    st.checkbox("Change default prime mover & size class?", key="cp_custom")
    if d["chp_elec_size_heuristic_kw"] is not None and st.button(
            "Apply CHP size to the max size considered", key="cp_apply", type="tertiary"):
        st.session_state["cp_max"] = float(round(d["chp_elec_size_heuristic_kw"]))
        st.rerun()

    r: dict = {}
    r["min_kw"] = _or(_num("Minimum new electric power capacity (kW)", "cp_min", "0", fmt="%.0f"), 0.0)
    r["min_allowable_kw"] = _or(_num("Minimum new non-zero power capacity (kW)", "cp_min_nz",
                                     f"{di['min_allowable_kw']:,.0f}", fmt="%.0f"),
                                di["min_allowable_kw"])
    r["max_kw"] = _or(_num("Maximum new electric power capacity (kW)", "cp_max",
                           f"{d['chp_max_size_kw']:,.0f}" if d["chp_max_size_kw"] else "",
                           fmt="%.0f"), d["chp_max_size_kw"] or 0.0)
    existing = st.checkbox("Existing CHP system?", key="cp_existing")
    r["existing_kw"] = 0.0
    loads_is_net = True
    if existing:
        r["existing_kw"] = _or(_num("Existing CHP size (kW)", "cp_existing_kw", "0", fmt="%.0f"), 0.0)
        loads_is_net = st.radio(
            "Existing CHP load basis",
            ["Net (gross load minus existing CHP generation)", "Gross load (also known as native load)"],
            key="cp_net", label_visibility="collapsed").startswith("Net")

    single = st.checkbox("Use single cost ($/kW) for all CHP sizes?", key="cp_single")
    single_cost = None
    pair_sizes, pair_costs = list(di["tech_sizes_for_cost_curve"]), list(di["installed_cost_per_kw"])
    if single:
        single_cost = _num("* Total installed cost ($/kW)", "cp_single_cost", "", fmt="%.2f")
    else:
        h0, h1, h2 = st.columns([2, 1, 1])
        with h1:
            st.markdown("**Size-Cost Pair 1**")
        with h2:
            st.markdown("**Size-Cost Pair 2**")
        r0, a0, b0 = st.columns([2, 1, 1])
        with r0:
            st.markdown("Electric power capacity (kW)")
        with a0:
            s1 = _num("Size 1", "cp_pair_s1", f"{pair_sizes[0]:,.0f}", fmt="%.0f",
                      label_visibility="collapsed")
        with b0:
            s2 = _num("Size 2", "cp_pair_s2", f"{pair_sizes[1]:,.0f}", fmt="%.0f",
                      label_visibility="collapsed")
        r1, a1, b1 = st.columns([2, 1, 1])
        with r1:
            st.markdown("Total installed cost ($/kW)")
        with a1:
            c1 = _num("Cost 1", "cp_pair_c1", f"${pair_costs[0]:.0f}", fmt="%.2f",
                      label_visibility="collapsed")
        with b1:
            c2 = _num("Cost 2", "cp_pair_c2", f"${pair_costs[1]:.0f}", fmt="%.2f",
                      label_visibility="collapsed")
        pair_sizes = [_or(s1, pair_sizes[0]), _or(s2, pair_sizes[1])]
        pair_costs = [_or(c1, pair_costs[0]), _or(c2, pair_costs[1])]
    dispatch = _select("Dispatch options", CHP_DISPATCH, "cp_dispatch", "cost_optimal")

    # ---------------------------------------------------- Advanced inputs
    adv = st.toggle("Advanced inputs", key="cp_adv")
    periods = di["unavailability_periods"]
    schedule = C.generate_year_profile_hourly(2017, periods)
    custom_profile = None
    r.update(om_cost_per_kw=0.0, om_cost_per_kwh=di["om_cost_per_kwh"],
             electric_efficiency_full_load=di["electric_efficiency_full_load"],
             electric_efficiency_half_load=None,
             thermal_efficiency_full_load=di["thermal_efficiency_full_load"],
             thermal_efficiency_half_load=None,
             min_turn_down_fraction=di["min_turn_down_fraction"],
             cooling_thermal_factor=di["cooling_thermal_factor"],
             federal_itc_fraction=0.0, federal_rebate_per_kw=0.0,
             state_ibi_fraction=0.0, state_ibi_max=UNLIMITED,
             state_rebate_per_kw=0.0, state_rebate_max=UNLIMITED,
             utility_ibi_fraction=0.0, utility_ibi_max=UNLIMITED,
             utility_rebate_per_kw=0.0, utility_rebate_max=UNLIMITED,
             production_incentive_per_kwh=0.0, production_incentive_years=1,
             production_incentive_max_benefit=1.0e9, production_incentive_max_kw=1.0e9,
             macrs_option_years=5, macrs_bonus_fraction=1.0)
    if adv:
        _heading("CHP Maintenance Schedule")
        how = st.segmented_control("Maintenance schedule", ["Default", "Upload"], default="Default",
                                   key="cp_maint", label_visibility="collapsed")
        if how == "Upload":
            up = st.file_uploader("* Custom downtime schedule (8,760 values, 1 = unavailable)",
                                  type=["csv", "txt"], key="cp_maint_upload")
            got = _read_series(up, percent_ok=False)
            if got is not None:
                schedule = got
        else:
            st.caption("A default maintenance schedule has been selected based on your prime mover "
                       "type and the year of your electric load profile.")
            st.caption("Use the **summary table** and **detailed table** links below to view the "
                       "details of the default schedule.")
        buf = io.StringIO()
        buf.write("hour,unavailable\n")
        for i, v in enumerate(schedule):
            buf.write(f"{i + 1},{int(v)}\n")
        c_dl, c_sum, c_det = st.columns(3)
        with c_dl:
            st.download_button("Download schedule", buf.getvalue(), file_name="chp_maintenance_schedule.csv",
                               mime="text/csv", key="cp_maint_dl", type="tertiary",
                               icon=":material/download:")
        with c_sum:
            with st.popover("View summary table"):
                st.dataframe([{"Month": MONTHS[p_["month"] - 1],
                               "Start week of month": p_["start_week_of_month"],
                               "Start day of week": p_["start_day_of_week"],
                               "Start hour": p_["start_hour"],
                               "Duration (hours)": p_["duration_hours"]} for p_ in periods],
                             hide_index=True)
        with c_det:
            with st.popover("View detailed table"):
                rows, run_start = [], None
                for i, v in enumerate(schedule + [0.0]):
                    if v >= 0.5 and run_start is None:
                        run_start = i
                    elif v < 0.5 and run_start is not None:
                        rows.append({"First unavailable hour": run_start + 1,
                                     "Last unavailable hour": i, "Hours": i - run_start})
                        run_start = None
                st.dataframe(rows, hide_index=True)

        _heading("CHP Costs")
        r["om_cost_per_kw"] = _or(_num("Fixed O&M Cost ($/kW/yr)", "cp_om_kw", "$0", fmt="%.2f"), 0.0)
        r["om_cost_per_kwh"] = _or(_num("Variable O&M Cost ($/kWh)", "cp_om_kwh",
                                        f"${di['om_cost_per_kwh']:.3f}", fmt="%.4f"),
                                   di["om_cost_per_kwh"])

        _heading("CHP System Characteristics")
        r["electric_efficiency_full_load"] = _pct(_num(
            "Electric efficiency at 100% load (% HHV-basis)", "cp_ee100",
            f"{di['electric_efficiency_full_load'] * 100:.2f}%", fmt="%.2f", max_value=100.0),
            di["electric_efficiency_full_load"])
        _ee50 = _num("Electric efficiency at 50% load (% HHV-basis)", "cp_ee50",
                     f"{di['electric_efficiency_full_load'] * 100:.2f}%", fmt="%.2f", max_value=100.0)
        r["electric_efficiency_half_load"] = None if _ee50 is None else _ee50 / 100.0
        r["thermal_efficiency_full_load"] = _pct(_num(
            "Thermal efficiency at 100% load (% HHV-basis)", "cp_te100",
            f"{di['thermal_efficiency_full_load'] * 100:.2f}%", fmt="%.2f", max_value=100.0),
            di["thermal_efficiency_full_load"])
        _te50 = _num("Thermal efficiency at 50% load (% HHV-basis)", "cp_te50",
                     f"{di['thermal_efficiency_full_load'] * 100:.2f}%", fmt="%.2f", max_value=100.0)
        r["thermal_efficiency_half_load"] = None if _te50 is None else _te50 / 100.0
        r["min_turn_down_fraction"] = _pct(_num(
            "Min. electric loading of prime mover (% of rated electric capacity)", "cp_turndown",
            f"{di['min_turn_down_fraction'] * 100:.2f}%", fmt="%.2f", max_value=100.0),
            di["min_turn_down_fraction"])
        r["cooling_thermal_factor"] = _pct(_num(
            "Knockdown factor for CHP-supplied thermal to Absorption Chiller (%)", "cp_knock",
            f"{di['cooling_thermal_factor'] * 100:.2f}%", fmt="%.2f", max_value=100.0),
            di["cooling_thermal_factor"])
        gen = st.radio("CHP maximum generation",
                       ["Always allow CHP to operate at maximum capacity",
                        "Provide custom maximum generation profile"], key="cp_maxgen")
        if gen.startswith("Provide"):
            up = st.file_uploader("Custom maximum generation profile (8,760 values, % or fraction)",
                                  type=["csv", "txt"], key="cp_maxgen_upload")
            custom_profile = _read_series(up)

        _heading("CHP Incentives and Tax Treatment")
        _heading("Capital Cost or System Size Based Incentives", 5)
        st.markdown("[Database of state incentives for renewables](https://www.dsireusa.org/)")
        heads = ["", "Incentive based on percentage of cost (%)",
                 "Maximum dollar amount for incentive based on percentage of cost ($)",
                 "Rebate based on system size ($/kW)",
                 "Maximum dollar amount for rebate based on system size ($)"]
        cols = st.columns([1, 2, 2, 2, 2])
        for c_, h in zip(cols, heads):
            with c_:
                st.markdown(f"**{h}**" if h else "")
        for region in ("Federal", "State", "Utility"):
            key = region.lower()
            cols = st.columns([1, 2, 2, 2, 2])
            with cols[0]:
                st.markdown(f"**{region}**")
            with cols[1]:
                pct = _num(f"{region} %", f"cp_{key}_pct", "0%", fmt="%.2f", max_value=100.0,
                           label_visibility="collapsed")
            with cols[2]:
                if region == "Federal":
                    st.markdown("Unlimited")
                    pmax = None
                else:
                    pmax = _num(f"{region} % max", f"cp_{key}_pmax", "Unlimited", fmt="%.0f",
                                label_visibility="collapsed")
            with cols[3]:
                reb = _num(f"{region} rebate", f"cp_{key}_reb", "$0", fmt="%.2f",
                           label_visibility="collapsed")
            with cols[4]:
                if region == "Federal":
                    st.markdown("Unlimited")
                    rmax = None
                else:
                    rmax = _num(f"{region} rebate max", f"cp_{key}_rmax", "Unlimited", fmt="%.0f",
                                label_visibility="collapsed")
            if region == "Federal":
                r["federal_itc_fraction"] = _pct(pct, 0.0)
                r["federal_rebate_per_kw"] = _or(reb, 0.0)
            else:
                r[f"{key}_ibi_fraction"] = _pct(pct, 0.0)
                r[f"{key}_ibi_max"] = _or(pmax, UNLIMITED)
                r[f"{key}_rebate_per_kw"] = _or(reb, 0.0)
                r[f"{key}_rebate_max"] = _or(rmax, UNLIMITED)

        _heading("Production Based Incentives", 5)
        heads = ["", "Production incentive ($/kWh)", "Incentive duration (yrs)",
                 "Maximum incentive ($)", "System size limit (kW)"]
        cols = st.columns([1, 2, 2, 2, 2])
        for c_, h in zip(cols, heads):
            with c_:
                st.markdown(f"**{h}**" if h else "")
        cols = st.columns([1, 2, 2, 2, 2])
        with cols[0]:
            st.markdown("**Total**")
        with cols[1]:
            r["production_incentive_per_kwh"] = _or(_num("PBI $/kWh", "cp_pbi", "$0.000", fmt="%.3f",
                                                         label_visibility="collapsed"), 0.0)
        with cols[2]:
            r["production_incentive_years"] = int(_or(_num("PBI years", "cp_pbi_yrs", "1", fmt="%.0f",
                                                           label_visibility="collapsed"), 1))
        with cols[3]:
            r["production_incentive_max_benefit"] = _or(_num("PBI max", "cp_pbi_max", "Unlimited",
                                                             fmt="%.0f", label_visibility="collapsed"),
                                                        1.0e9)
        with cols[4]:
            r["production_incentive_max_kw"] = _or(_num("PBI size", "cp_pbi_kw", "Unlimited",
                                                        fmt="%.0f", label_visibility="collapsed"),
                                                   1.0e9)
        _heading("Tax Treatment", 5)
        r["macrs_option_years"] = _select("MACRS schedule", MACRS_YEARS, "cp_macrs", 5)
        r["macrs_bonus_fraction"] = _select("MACRS bonus depreciation", MACRS_BONUS, "cp_bonus", 1.0)
    _reset_button("cp_", "cp_reset")

    # ---- assemble exactly what REopt's CHP struct would carry
    avail = [1.0 - x for x in schedule]
    if custom_profile is not None:
        avail = [a * b for a, b in zip(custom_profile, avail)]
    if single:
        r["installed_cost_per_kw"] = _or(single_cost, 0.0)
        r["tech_sizes_for_cost_curve"], r["installed_cost_curve_per_kw"] = [], []
    else:
        r["installed_cost_per_kw"] = float(pair_costs[0])
        r["tech_sizes_for_cost_curve"] = [float(x) for x in pair_sizes]
        r["installed_cost_curve_per_kw"] = [float(x) for x in pair_costs]
    r["production_factor_series"] = avail
    r["follow_electrical_load"] = dispatch == "follow_electrical_load"
    r["follow_heating_load"] = dispatch == "follow_heating_load"
    r["macrs_itc_reduction"] = 0.5
    return {"inputs": r, "defaults": d, "single_cost_missing": single and single_cost is None,
            "loads_kw_is_net": loads_is_net, "maintenance_hours": int(sum(schedule)),
            "dispatch": dispatch}
