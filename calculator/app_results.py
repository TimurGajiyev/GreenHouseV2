"""Results page — mirrors the REopt results page section by section.

Sections and row labels follow the real tool: System Performance Year One,
Annual Electricity Production Breakdown, Net Load Duration, Results Comparison
(grid-tied) / Results Summary (off-grid), Inputs, Defaults.
"""

from __future__ import annotations

import calendar

import altair as alt
import pandas as pd
import streamlit as st

import ui_theme as T

HOURS = 8760


def _idx() -> pd.DatetimeIndex:
    return pd.date_range("2017-01-01", periods=HOURS, freq="h")


def _m(x) -> str:
    """Money, with the sign outside the $ as REopt writes it (-$15,263)."""
    if x is None:
        return "N/A"
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def _kw(x) -> str:
    return f"{x:,.0f} kW"


def _kwh(x) -> str:
    return f"{x:,.0f} kWh"


def _tonnes(em, key, digits):
    """Avoided tonnes (BAU minus optimized) for one emissions key."""
    if not em:
        return "N/A"
    v = em["bau"][key] - em["opt"][key]
    return f"{v:,.{digits}f} tonnes"


def _table(rows, cols):
    st.dataframe(pd.DataFrame(rows, columns=cols), hide_index=True, width="stretch")


def render_results(state: dict) -> None:
    res, bau = state["res"], (state["bau"] or {})
    load, off_grid, years = state["load"], state["off_grid"], state["inp_years"]
    inputs_echo = state.get("inputs_echo", {})

    sz = {k: (0.0 if isinstance(v, float) and abs(v) < 1e-9 else v)
          for k, v in res["sizes"].items()}
    en, cap, om = res["energy"], res["capital"], res.get("om", {})
    bd = res.get("breakdown", {})
    pf = res.get("proforma", {})
    u = res.get("utility", {})

    st.divider()
    st.header("Results for your site")
    st.caption(
        "These results summarize the economic viability of PV, battery storage, "
        "CHP and generator at your site. Edit your inputs to see how changes affect them."
    )
    if res["status"] != "Optimal":
        st.warning(f"Solver status: {res['status']}")

    # ------------------------------------------------------ headline cards
    cards = []
    if sz["pv_kw"] > 0 or not sz["fueltech_kind"]:
        cards.append(("Your optimized solar installation size", "solar_power",
                      [(_kw(sz["pv_kw"]), "PV size")],
                      "Measured in kilowatts (kW) of direct current (DC), this optimized "
                      "size minimizes the life cycle cost of energy at your site."))
    if sz["battery_kwh"] > 0 or sz["battery_kw"] > 0 or not sz["fueltech_kind"]:
        cards.append(("Your optimized battery power and capacity", "battery_charging_full",
                      [(_kw(sz["battery_kw"]), "battery power"),
                       (_kwh(sz["battery_kwh"]), "battery capacity")],
                      "The battery power (kW-AC) and energy capacity (kWh) are optimized "
                      "independently for economic performance."))
    if sz["fueltech_kind"]:
        cards.append((f"Your optimized {sz['fueltech_kind']} size", "bolt",
                      [(_kw(sz["fueltech_kw"]), f"{sz['fueltech_kind']} size")],
                      "Fuel-fired capacity sized against its fuel and capital cost."))

    for i in range(0, len(cards), 2):
        cols = st.columns(min(2, len(cards) - i))
        for j, col in enumerate(cols):
            title, icon, figs, note = cards[i + j]
            with col:
                T.stat_card(title, icon, figs, note)

    st.caption(
        "The optimized size may not be commercially available. The user is responsible "
        "for finding a commercial product that is closest in size to the optimized size."
    )

    if not off_grid and bau:
        savings = bau["lifecycle_cost"] - res["objective_lifecycle_cost"]
        T.savings_card(
            f"Your potential life cycle savings ({years} years)",
            "This is the net present value of the savings (or costs if negative) realized "
            "by the project based on the difference between the total life cycle costs of "
            "doing business as usual compared to the optimal case.",
            _m(savings),
        )
        c = st.columns(4)
        c[0].metric("Payback period",
                    f"{pf['simple_payback_years']:.2f} yrs"
                    if pf.get("simple_payback_years") is not None else "N/A")
        c[1].metric("Internal rate of return",
                    f"{100 * pf['internal_rate_of_return']:.1f} %" if pf else "N/A")
        c[2].metric("PV levelized cost of energy",
                    f"${pf.get('pv_lcoe', 0.0):.3f}/kWh" if pf else "N/A")
        c[3].metric("Load met",
                    f"{100 * (1 - en['unserved_kwh'] / en['annual_load_kwh']):.2f} %")
    else:
        lcoe = res["objective_lifecycle_cost"] / max(1.0, en["annual_load_kwh"] * years)
        T.savings_card(
            f"Your total life cycle cost ({years} years)",
            "Off-grid systems have no business-as-usual case to compare against, so REopt "
            "reports the total life cycle cost rather than savings (reopt.jl:117).",
            _m(res["objective_lifecycle_cost"]),
        )
        c = st.columns(3)
        c[0].metric("Levelized cost of energy", f"${lcoe:.3f}/kWh")
        c[1].metric("Unserved load", _kwh(en["unserved_kwh"]))
        c[2].metric("Annual load met",
                    f"{100 * (1 - en['unserved_kwh'] / en['annual_load_kwh']):.2f} %")

    # ---------------------------------------------- System Performance Year One
    with st.expander("System Performance Year One", expanded=True):
        st.caption(
            "Dispatch strategy optimized by REopt for typical operation of the "
            "optimized system, for every hour of the year."
        )
        s = res["series"]
        df = pd.DataFrame(
            {"Total Electric Load": s["load_kw"],
             "PV Serving Load": s["pv_to_load_kw"],
             "Battery Serving Load": s["battery_discharge_kw"],
             "Grid Serving Load": s["grid_kw"]},
            index=_idx(),
        )
        if sz["fueltech_kind"] and sz["fueltech_kw"] > 0:
            df[f"{sz['fueltech_kind']} Serving Load"] = s["fueltech_kw"]

        wk = st.slider("Week of the year", 1, 52, 26, key="week")
        lo, hi = (wk - 1) * 168, min(HOURS, (wk - 1) * 168 + 168)
        wdf = df.iloc[lo:hi].reset_index(names="time").melt("time", var_name="series",
                                                            value_name="kW")
        st.altair_chart(
            alt.Chart(wdf).mark_line(interpolate="step-after").encode(
                x=alt.X("time:T", title=None),
                y=alt.Y("kW:Q", title="Power (kW)", stack=None),
                color=alt.Color("series:N", title=None),
                tooltip=["time:T", "series:N", alt.Tooltip("kW:Q", format=",.1f")],
            ).properties(height=320),
            width="stretch",
        )
        if sz["battery_kwh"] > 0:
            soc = pd.DataFrame(
                {"State of Charge": [100 * v / sz["battery_kwh"] for v in s["soc_kwh"][lo:hi]]},
                index=_idx()[lo:hi]).reset_index(names="time")
            st.altair_chart(
                alt.Chart(soc).mark_area(opacity=0.45).encode(
                    x=alt.X("time:T", title=None),
                    y=alt.Y("State of Charge:Q", title="State of charge (%)",
                            scale=alt.Scale(domain=[0, 100])),
                ).properties(height=150),
                width="stretch",
            )

    # ------------------------------- Annual Electricity Production Breakdown
    with st.expander("Annual Electricity Production Breakdown", expanded=False):
        st.caption(
            "Annual production of electricity for each technology and where it goes. "
            "For PV this is the average annual production, including year-over-year "
            "degradation."
        )
        st.markdown("**Grid** — average annual dispatch results")
        _table([("Grid Serving Load (kWh)", f"{bd.get('grid_serving_load', 0):,.0f}"),
                ("Grid Charging Battery (kWh)", f"{bd.get('grid_charging_battery', 0):,.0f}"),
                ("Grid Total Electricity Consumed (kWh)", f"{bd.get('grid_total', 0):,.0f}")],
               ["", "kWh"])
        if sz["pv_kw"] > 0:
            st.markdown("**PV** — average annual dispatch results")
            _table([("PV Serving Load (kWh)", f"{bd.get('pv_serving_load', 0):,.0f}"),
                    ("PV Charging Battery (kWh)", f"{bd.get('pv_charging_battery', 0):,.0f}"),
                    ("PV Exported to Grid (kWh)", f"{bd.get('pv_exported', 0):,.0f}"),
                    ("PV Curtailment (kWh)", f"{bd.get('pv_curtailed', 0):,.0f}"),
                    ("PV Total Electricity Produced (kWh)", f"{bd.get('pv_total', 0):,.0f}")],
                   ["", "kWh"])
        if sz["battery_kwh"] > 0:
            st.markdown("**Battery** — average annual dispatch results")
            _table([("Battery Serving Load (kWh)", f"{bd.get('battery_serving_load', 0):,.0f}"),
                    ("Battery Exported to Grid (kWh)", f"{bd.get('battery_exported', 0):,.0f}")],
                   ["", "kWh"])
        if sz["fueltech_kind"] and sz["fueltech_kw"] > 0:
            st.markdown(f"**{sz['fueltech_kind']}** — average annual dispatch results")
            _table([(f"{sz['fueltech_kind']} Serving Load (kWh)",
                     f"{bd.get('fueltech_serving_load', 0):,.0f}")], ["", "kWh"])

    # ----------------------------------------------------- Net Load Duration
    with st.expander("Net Load Duration", expanded=False):
        st.caption(
            "Reduction in peak load when the optimized technologies are implemented."
        )
        s = res["series"]
        bau_sorted = sorted(load["loads_kw"], reverse=True)
        opt_net = [s["grid_kw"][t] + (s["battery_charge_kw"][t] if not off_grid else 0.0)
                   for t in range(HOURS)]
        opt_sorted = sorted(opt_net, reverse=True)
        step = 12  # thin for rendering
        ld = pd.DataFrame({
            "Hours (cumulative)": list(range(0, HOURS, step)) * 2,
            "kW": bau_sorted[::step] + opt_sorted[::step],
            "case": ["Business as usual"] * len(bau_sorted[::step])
                    + ["Optimized case"] * len(opt_sorted[::step]),
        })
        st.altair_chart(
            alt.Chart(ld).mark_line().encode(
                x=alt.X("Hours (cumulative):Q"),
                y=alt.Y("kW:Q", title="Net Site Load (kW)"),
                color=alt.Color("case:N", title=None),
            ).properties(height=300),
            width="stretch",
        )

    # ------------------------------------- Results Comparison / Results Summary
    if off_grid or not bau:
        with st.expander("Results Summary", expanded=True):
            rows = [("PV Size", _kw(sz["pv_kw"])),
                    ("Battery Power", _kw(sz["battery_kw"])),
                    ("Battery Capacity", _kwh(sz["battery_kwh"]))]
            if sz["fueltech_kind"]:
                rows.append((f"{sz['fueltech_kind']} Size", _kw(sz["fueltech_kw"])))
            rows += [
                ("Annual Site Load", _kwh(en["annual_load_kwh"])),
                ("Annual Load Met",
                 f"{100 * (1 - en['unserved_kwh'] / en['annual_load_kwh']):.2f} %"),
                ("Average Annual PV Energy Production", _kwh(en["pv_kwh"])),
                ("Total Upfront Capital Cost Before Incentives",
                 _m(cap["upfront_before_incentives"])),
                ("Year 1 O&M Cost, Before Tax",
                 _m(sum(om.values()) if om else 0)),
                ("Total Life Cycle Costs", _m(res["objective_lifecycle_cost"])),
            ]
            _table(rows, ["", "Optimized"])
            st.caption("Off-grid has no business-as-usual case — REopt.jl skips it "
                       "(reopt.jl:117).")
    else:
        with st.expander("Results Comparison", expanded=True):
            st.caption("These results show how doing business as usual compares to "
                       "the optimal case.")
            y1om = sum(om.values()) if om else 0.0
            f = res["factors"]
            tech_cap_after = (cap["pv_cap_cost_slope_per_kw"] * sz["pv_kw"]
                              + cap["storage_npc_per_kw"] * sz["battery_kw"]
                              + cap["storage_npc_per_kwh"] * sz["battery_kwh"]
                              + cap["fueltech_cap_cost_slope_per_kw"] * sz["fueltech_kw"])
            om_lcc = y1om * f["pwf_om"] * (1 - state["tax_rate"])
            savings = bau["lifecycle_cost"] - res["objective_lifecycle_cost"]

            def d(a, b, fmt):
                return fmt(b - a)

            rows = [
                ("— System Size —", "", "", ""),
                ("PV Size", _kw(0), _kw(sz["pv_kw"]), _kw(sz["pv_kw"])),
                ("Battery Power", _kw(0), _kw(sz["battery_kw"]), _kw(sz["battery_kw"])),
                ("Battery Capacity", _kwh(0), _kwh(sz["battery_kwh"]), _kwh(sz["battery_kwh"])),
            ]
            if sz["fueltech_kind"]:
                rows.append((f"{sz['fueltech_kind']} Size", _kw(0), _kw(sz["fueltech_kw"]),
                             _kw(sz["fueltech_kw"])))
            em = state.get("emissions")
            ren_opt = (en["pv_kwh"] / en["annual_load_kwh"] * 100) if en["annual_load_kwh"] else 0.0
            rows += [
                ("— Energy Production and Fuel Use —", "", "", ""),
                ("Average Annual PV Energy Production", _kwh(0), _kwh(en["pv_kwh"]),
                 _kwh(en["pv_kwh"])),
                ("Average Annual Energy Supplied from Grid", _kwh(en["annual_load_kwh"]),
                 _kwh(bd.get("grid_total", 0)),
                 _kwh(bd.get("grid_total", 0) - en["annual_load_kwh"])),
                ("— Renewable Energy Metrics —", "", "", ""),
                ("Annual Renewable Electricity (% of electricity consumption)",
                 "0%", f"{ren_opt:.0f}%", f"{ren_opt:.0f}%"),
                ("— Climate Emissions —", "", "", ""),
                ("Avoided CO2e Emissions throughout Analysis Period", "N/A",
                 _tonnes(em, "total_co2e_tonnes", 0), _tonnes(em, "total_co2e_tonnes", 0)),
                ("— Health Emissions —", "", "", ""),
                ("Avoided NOx Emissions throughout Analysis Period", "N/A",
                 _tonnes(em, "total_nox_tonnes", 2), _tonnes(em, "total_nox_tonnes", 2)),
                ("Avoided SO2 Emissions throughout Analysis Period", "N/A",
                 _tonnes(em, "total_so2_tonnes", 2), _tonnes(em, "total_so2_tonnes", 2)),
                ("Avoided PM2.5 Emissions throughout Analysis Period", "N/A",
                 _tonnes(em, "total_pm25_tonnes", 2), _tonnes(em, "total_pm25_tonnes", 2)),
                ("— Year 1 Utility Electricity Cost — Before Tax —", "", "", ""),
                ("Utility Export Benefit", _m(0), _m(0), _m(0)),
                ("Utility Energy Cost", _m(bau["year1_energy_cost"]),
                 _m(u.get("year1_energy_cost", 0)),
                 _m(u.get("year1_energy_cost", 0) - bau["year1_energy_cost"])),
                ("Utility Demand Cost",
                 _m(bau["year1_tou_demand_cost"] + bau["year1_monthly_demand_cost"]),
                 _m(u.get("year1_tou_demand_cost", 0) + u.get("year1_monthly_demand_cost", 0)),
                 _m(u.get("year1_tou_demand_cost", 0) + u.get("year1_monthly_demand_cost", 0)
                    - bau["year1_tou_demand_cost"] - bau["year1_monthly_demand_cost"])),
                ("Utility Fixed Cost", _m(bau["year1_fixed_cost"]),
                 _m(u.get("year1_fixed_cost", 0)), _m(0)),
                ("Utility Minimum Cost Adder", _m(0), _m(0), _m(0)),
                ("Total Year 1 Utility Cost - Before Tax", _m(bau["year1_total"]),
                 _m(u.get("year1_total", 0)), _m(u.get("year1_total", 0) - bau["year1_total"])),
                ("— Life Cycle Cost Breakdown —", "", "", ""),
                ("Technology Capital Costs + Replacements, After Incentives", _m(0),
                 _m(tech_cap_after), _m(tech_cap_after)),
                ("O&M Costs", _m(0), _m(om_lcc), _m(om_lcc)),
                ("Total Utility Electricity Cost", _m(bau["lifecycle_cost"]),
                 _m(res["objective_lifecycle_cost"] - tech_cap_after - om_lcc),
                 _m(res["objective_lifecycle_cost"] - tech_cap_after - om_lcc
                    - bau["lifecycle_cost"])),
                ("Total Production-Based Incentive", _m(0), _m(0), _m(0)),
                ("Cost of Climate Emissions throughout Analysis Period (If Included in Objective)",
                 _m(0), _m(0), _m(0)),
                ("Cost of Health Emissions throughout Analysis Period (If Included in Objective)",
                 _m(0), _m(0), _m(0)),
                ("— Summary Financial Metrics —", "", "", ""),
                ("Total Upfront Capital Cost Before Incentives", _m(0),
                 _m(cap["upfront_before_incentives"]), _m(cap["upfront_before_incentives"])),
                ("Year 1 O&M Cost, Before Tax", _m(0), _m(y1om), _m(y1om)),
                ("Total Life Cycle Costs", _m(bau["lifecycle_cost"]),
                 _m(res["objective_lifecycle_cost"]), _m(-savings)),
                ("Net Present Value", _m(0), _m(savings), _m(savings)),
                ("Payback Period", "N/A",
                 f"{pf['simple_payback_years']:.2f} yrs"
                 if pf.get("simple_payback_years") is not None else "N/A",
                 f"{pf['simple_payback_years']:.2f} yrs"
                 if pf.get("simple_payback_years") is not None else "N/A"),
                ("Internal Rate of Return", "N/A",
                 f"{100 * pf['internal_rate_of_return']:.1f}%" if pf else "N/A",
                 f"{100 * pf['internal_rate_of_return']:.1f}%" if pf else "N/A"),
                ("PV Levelized Cost of Energy", "N/A",
                 f"${pf.get('pv_lcoe', 0.0):.3f}/kWh" if pf else "N/A",
                 f"${pf.get('pv_lcoe', 0.0):.3f}/kWh" if pf else "N/A"),
            ]
            _table(rows, ["", "Business As Usual", "Financial", "Difference"])

    # ------------------------------ Renewable Energy & Emissions Metrics
    em = state.get("emissions")
    if em:
        with st.expander("Renewable Energy & Emissions Metrics", expanded=False):
            st.caption(
                "These results show emissions outcomes for the business as usual and "
                "optimized cases. If marginal grid emissions rates are utilized (the "
                "default inputs), users should focus on avoided emissions, rather than "
                "emissions totals. For all emissions outputs, t represents metric tons "
                "(tonnes)."
            )
            b, o = em["bau"], em["opt"]
            ren = (en["pv_kwh"] / en["annual_load_kwh"] * 100) if en["annual_load_kwh"] else 0.0
            t2 = lambda v: f"{v:,.2f}"
            t0 = lambda v: f"{v:,.0f}"

            def trio(label, bv, ov, fmt):
                return (label, fmt(bv), fmt(ov), fmt(ov - bv))

            pct = ("N/A" if not b["total_co2e_tonnes"] else
                   f"{100 * (b['total_co2e_tonnes'] - o['total_co2e_tonnes']) / b['total_co2e_tonnes']:.2f}%")
            rows = [
                ("\u2014 Renewable Energy \u2014", "", "", ""),
                ("Annual Renewable Electricity (% of electricity consumption)",
                 "0%", f"{ren:.0f}%", f"{ren:.0f}%"),
                ("\u2014 Climate & Health Emissions Costs \u2014", "", "", ""),
                trio("Cost of Climate Emissions throughout Analysis Period",
                     b["cost_climate"], o["cost_climate"], _m),
                trio("Cost of Health Emissions throughout Analysis Period",
                     b["cost_health"], o["cost_health"], _m),
                ("\u2014 Climate Emissions, CO2e \u2014", "", "", ""),
                trio("Average Annual Emissions (t CO2e)",
                     b["annual_co2e_tonnes"], o["annual_co2e_tonnes"], t0),
                trio("Average Annual Emissions from Grid Purchases (t CO2e)",
                     b["annual_co2e_tonnes"], o["annual_co2e_tonnes"], t0),
                ("Average Annual Emissions from Onsite Fuel Burn (t CO2e)", "0", "0", "0"),
                trio("Total Emissions throughout Analysis Period (t CO2e)",
                     b["total_co2e_tonnes"], o["total_co2e_tonnes"], t0),
                trio("Emissions from Grid Purchases throughout Analysis Period (t CO2e)",
                     b["total_co2e_tonnes"], o["total_co2e_tonnes"], t0),
                ("Emissions from Onsite Fuel Burn throughout Analysis Period (t CO2e)",
                 "0", "0", "0"),
                ("Percent Reduction in CO2 Emissions from BAU (%)", "N/A", pct, pct),
            ]
            for pol, key in (("NOx", "nox"), ("SO2", "so2"), ("PM2.5", "pm25")):
                rows += [
                    (f"\u2014 Health Emissions, {pol} \u2014", "", "", ""),
                    trio(f"Average Annual Emissions (t {pol})",
                         b[f"annual_{key}_tonnes"], o[f"annual_{key}_tonnes"], t2),
                    trio(f"Average Annual Emissions from Grid Purchases (t {pol})",
                         b[f"annual_{key}_tonnes"], o[f"annual_{key}_tonnes"], t2),
                    (f"Average Annual Emissions from Onsite Fuel Burn (t {pol})",
                     "0.00", "0.00", "0.00"),
                    trio(f"Total Emissions throughout Analysis Period (t {pol})",
                         b[f"total_{key}_tonnes"], o[f"total_{key}_tonnes"], t2),
                    trio(f"Emissions from Grid Purchases throughout Analysis Period (t {pol})",
                         b[f"total_{key}_tonnes"], o[f"total_{key}_tonnes"], t2),
                    (f"Emissions from Onsite Fuel Burn throughout Analysis Period (t {pol})",
                     "0.00", "0.00", "0.00"),
                ]
            _table(rows, ["", "Business As Usual", "Financial", "Difference"])
            st.caption(
                f"Cambium location: {em['cambium_location']} \u00b7 "
                f"EPA AVERT region: {em['avert_region']}"
            )

    # ---------------------------------------------------------------- Inputs
    with st.expander("Inputs", expanded=False):
        st.caption("The results are based on the following user supplied inputs.")
        for group, rows in inputs_echo.items():
            if not rows:
                continue
            st.markdown(f"**{group}**")
            _table(list(rows.items()), ["", "Value"])

    # -------------------------------------------------------------- Defaults
    with st.expander("Defaults", expanded=False):
        st.caption("The results are based on the following default inputs.")
        f, em = res["factors"], state.get("emissions")
        hc = (em or {}).get("health_costs", {})

        def grp(name, rows):
            st.markdown(f"**{name}**")
            _table(rows, ["", "Value"])

        grp("Site", [
            ("Sector", "Commercial/Industrial"),
            ("Solver name", "HiGHS"),
            ("Optimization timeout (seconds)", "600"),
        ])
        if not off_grid:
            grp("Utilities", [("Compensation type", state.get("compensation", "no_compensation"))])
        grp("Load Profile", [("Load adjustment (%)", "100%")])
        grp("Financial", [
            ("Host effective tax rate (%)", f"{state['tax_rate'] * 100:g}%"),
            ("O&M cost escalation rate (%/year)", f"{float(state.get('om_esc', 2.5)):g}%"),
            ("Minimum capital cost, before incentives ($)", "None"),
            ("Maximum capital cost, before incentives ($)", "None"),
            ("Third Party Ownership", "No"),
        ])
        if em:
            grp("Renewable Energy & Emissions Accounting", [
                ("EPA's AVERT Region", em["avert_region"]),
                ("Geographic resolution", "GEA Regions 2023"),
                ("Metric", "LRMER CO2e Combined"),
                ("Grid scenario", "Mid-case"),
                ("Use emissions averaged over the analysis period?", "Yes"),
                ("Cambium start year", "2025"),
                ("Include distribution losses?", "Enduse"),
                ("Projected annual percent decrease in grid health emissions factors (%/year)",
                 "4.590%"),
                ("CO2 cost ($/t CO2)", "51.0"),
                ("Grid emissions NOx cost ($/t NOx)",
                 f"{hc.get('NOx_grid_cost_per_tonne', 0):,.2f}"),
                ("Grid emissions SO2 cost ($/t SO2)",
                 f"{hc.get('SO2_grid_cost_per_tonne', 0):,.2f}"),
                ("Grid emissions PM2.5 cost ($/t PM2.5)",
                 f"{hc.get('PM25_grid_cost_per_tonne', 0):,.2f}"),
                ("CO2 cost escalation rate, nominal (%)", "4.22%"),
                ("NOx cost escalation rate, nominal (%)",
                 f"{hc.get('NOx_cost_escalation_rate_fraction', 0) * 100:.2f}%"),
                ("SO2 cost escalation rate, nominal (%)",
                 f"{hc.get('SO2_cost_escalation_rate_fraction', 0) * 100:.2f}%"),
                ("PM2.5 cost escalation rate, nominal (%)",
                 f"{hc.get('PM25_cost_escalation_rate_fraction', 0) * 100:.2f}%"),
            ])
        if sz["pv_kw"] > 0 or state.get("used_pv"):
            grp("PV", [
                ("O&M cost ($/kW-DC per year)", "$20"),
                ("Module type", "Standard"),
                ("Array type", "Ground Mount, Fixed"),
                ("Array azimuth (deg)", "180"),
                ("Array tilt (deg)", "20"),
                ("DC to AC size ratio", "1.2"),
                ("System losses (%)", "14%"),
                ("Ground-mount power density (acres per kW-DC)", "0.006"),
                ("Federal percentage-based incentive (%)", "30%"),
                ("MACRS bonus depreciation", "100%"),
                ("MACRS schedule", "5 years"),
            ])
        if state.get("used_battery"):
            grp("Battery", [
                ("Annual O&M cost as a percent of upfront cost (%)", "2.5%"),
                ("Allow grid to charge battery", "Yes"),
                ("Battery dispatch strategy", "Cost Optimal (perfect foresight)"),
                ("Energy capacity replacement cost ($/kWh)", "$0"),
                ("Energy capacity replacement year", "10"),
                ("Power capacity replacement cost ($/kW)", "$0"),
                ("Power capacity replacement year", "10"),
                ("Minimum energy capacity (kWh)", "0"),
                ("Minimum power capacity (kW)", "0"),
                ("Rectifier efficiency (%)", "96%"),
                ("Round trip efficiency (%)", "97.5%"),
                ("Inverter efficiency (%)", "96%"),
                ("Minimum state of charge (%)", "20%"),
                ("Initial state of charge (%)", "50%"),
                ("Total percentage-based incentive (%)", "30%"),
                ("MACRS bonus depreciation", "100%"),
                ("MACRS schedule", "5 years"),
            ])

        st.markdown("**Derived factors** — computed by this calculator, not REopt rows")
        _table([
            ("pwf_e (electricity present-worth factor)", f"{f['pwf_e']:.5f}"),
            ("pwf_om (O&M present-worth factor)", f"{f['pwf_om']:.5f}"),
            ("PV levelization factor", f"{f['levelization_factor_pv']:.5f}"),
            ("PV effective capital after ITC + MACRS ($/kW)",
             f"{cap['pv_cap_cost_slope_per_kw']:,.2f}"),
            ("Battery effective capital ($/kW)", f"{cap['storage_npc_per_kw']:,.2f}"),
            ("Battery effective capital ($/kWh)", f"{cap['storage_npc_per_kwh']:,.2f}"),
            ("Battery effective constant ($)", f"{cap['storage_npc_constant']:,.2f}"),
        ], ["", "Value"])
        st.caption(
            "annuity() / levelization_factor() — utils.jl:11,54 · "
            "effective_cost() — utils.jl:83 · battery O&M basis — reopt.jl:422-433"
        )

    with st.expander("Load profile source", expanded=False):
        st.write(
            f"DOE commercial reference building **{load['city']}** "
            f"(ASHRAE zone {load['ashrae_zone']}), scaled to "
            f"{load['annual_kwh']:,.0f} kWh. Peak {load['peak_kw']:,.1f} kW."
        )
        st.caption("crb8760_norm_<City>_<Type>.dat shipped with REopt.jl; nearest-city "
                   "selection per doe_commercial_reference_building_loads.jl:79-93.")
