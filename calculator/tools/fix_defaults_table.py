"""Rewrite the Defaults drawer to REopt's grouping and exact row labels.

Previously it mixed our internal names (pwf_e, "PV effective capital ...").
Those still matter, so they move to a clearly separate "Derived factors" block
below the REopt-shaped defaults rather than being mislabelled as REopt rows.
"""

import io
import os

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app_results.py")
s = io.open(P, encoding="utf-8").read()

start = s.index('    # -------------------------------------------------------------- Defaults')
end = s.index('    with st.expander("Load profile source", expanded=False):')

NEW = '''    # -------------------------------------------------------------- Defaults
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
            ("O&M cost escalation rate (%/year)", f"{state.get('om_esc', 2.5)}%"),
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

'''
s = s[:start] + NEW + s[end:]
io.open(P, "w", encoding="utf-8").write(s)
print("Defaults table rewritten with REopt labels")
