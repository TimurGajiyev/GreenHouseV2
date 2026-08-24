"""One-off: extend app_results.py with the remaining REopt result rows/sections."""

import io
import os

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app_results.py")
s = io.open(P, encoding="utf-8").read()


def sub(old, new, what):
    global s
    if old not in s:
        raise SystemExit(f"NOT FOUND: {what}")
    s = s.replace(old, new, 1)
    print(f"  ok  {what}")


# --- renewable % + emissions helper available in Results Comparison ---
sub(
    '            rows += [\n                ("— Energy Production and Fuel Use —", "", "", ""),',
    '            em = state.get("emissions")\n'
    '            ren_opt = (en["pv_kwh"] / en["annual_load_kwh"] * 100) if en["annual_load_kwh"] else 0.0\n'
    '            rows += [\n                ("— Energy Production and Fuel Use —", "", "", ""),',
    "renewable/emissions vars",
)

# --- insert renewable, climate and health rows before the utility cost block ---
old_util = ('                ("— Year 1 Utility Electricity Cost — Before Tax —", "", "", ""),\n'
            '                ("Utility Energy Cost",')
new_util = (
    '                ("— Renewable Energy Metrics —", "", "", ""),\n'
    '                ("Annual Renewable Electricity (% of electricity consumption)",\n'
    '                 "0%", f"{ren_opt:.0f}%", f"{ren_opt:.0f}%"),\n'
    '                ("— Climate Emissions —", "", "", ""),\n'
    '                ("Avoided CO2e Emissions throughout Analysis Period", "N/A",\n'
    '                 _tonnes(em, "total_co2e_tonnes", 0), _tonnes(em, "total_co2e_tonnes", 0)),\n'
    '                ("— Health Emissions —", "", "", ""),\n'
    '                ("Avoided NOx Emissions throughout Analysis Period", "N/A",\n'
    '                 _tonnes(em, "total_nox_tonnes", 2), _tonnes(em, "total_nox_tonnes", 2)),\n'
    '                ("Avoided SO2 Emissions throughout Analysis Period", "N/A",\n'
    '                 _tonnes(em, "total_so2_tonnes", 2), _tonnes(em, "total_so2_tonnes", 2)),\n'
    '                ("Avoided PM2.5 Emissions throughout Analysis Period", "N/A",\n'
    '                 _tonnes(em, "total_pm25_tonnes", 2), _tonnes(em, "total_pm25_tonnes", 2)),\n'
    '                ("— Year 1 Utility Electricity Cost — Before Tax —", "", "", ""),\n'
    '                ("Utility Export Benefit", _m(0), _m(0), _m(0)),\n'
    '                ("Utility Energy Cost",')
sub(old_util, new_util, "renewable + emissions rows")

# --- Utility Minimum Cost Adder ---
sub(
    '                ("Total Year 1 Utility Cost - Before Tax", _m(bau["year1_total"]),',
    '                ("Utility Minimum Cost Adder", _m(0), _m(0), _m(0)),\n'
    '                ("Total Year 1 Utility Cost - Before Tax", _m(bau["year1_total"]),',
    "Utility Minimum Cost Adder",
)

# --- life cycle rows REopt shows that we lacked ---
sub(
    '                ("— Summary Financial Metrics —", "", "", ""),',
    '                ("Total Production-Based Incentive", _m(0), _m(0), _m(0)),\n'
    '                ("Cost of Climate Emissions throughout Analysis Period '
    '(If Included in Objective)",\n                 _m(0), _m(0), _m(0)),\n'
    '                ("Cost of Health Emissions throughout Analysis Period '
    '(If Included in Objective)",\n                 _m(0), _m(0), _m(0)),\n'
    '                ("— Summary Financial Metrics —", "", "", ""),',
    "PBI + emissions-cost rows",
)

# --- helper for avoided-tonnes formatting ---
sub(
    'def _table(rows, cols):',
    'def _tonnes(em, key, digits):\n'
    '    """Avoided tonnes (BAU minus optimized) for one emissions key."""\n'
    '    if not em:\n'
    '        return "N/A"\n'
    '    v = em["bau"][key] - em["opt"][key]\n'
    '    return f"{v:,.{digits}f} tonnes"\n\n\n'
    'def _table(rows, cols):',
    "_tonnes helper",
)

# --- new section: Renewable Energy & Emissions Metrics ---
EM_SECTION = '''    # ------------------------------ Renewable Energy & Emissions Metrics
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
                ("\\u2014 Renewable Energy \\u2014", "", "", ""),
                ("Annual Renewable Electricity (% of electricity consumption)",
                 "0%", f"{ren:.0f}%", f"{ren:.0f}%"),
                ("\\u2014 Climate & Health Emissions Costs \\u2014", "", "", ""),
                trio("Cost of Climate Emissions throughout Analysis Period",
                     b["cost_climate"], o["cost_climate"], _m),
                trio("Cost of Health Emissions throughout Analysis Period",
                     b["cost_health"], o["cost_health"], _m),
                ("\\u2014 Climate Emissions, CO2e \\u2014", "", "", ""),
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
                    (f"\\u2014 Health Emissions, {pol} \\u2014", "", "", ""),
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
                f"Cambium location: {em['cambium_location']} \\u00b7 "
                f"EPA AVERT region: {em['avert_region']}"
            )

    # ---------------------------------------------------------------- Inputs'''
sub("    # ---------------------------------------------------------------- Inputs",
    EM_SECTION, "Renewable Energy & Emissions Metrics section")

io.open(P, "w", encoding="utf-8").write(s)
print("app_results.py patched")
