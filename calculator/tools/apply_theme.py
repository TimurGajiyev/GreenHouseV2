"""Apply the REopt visual style to streamlit_app.py and app_results.py."""

import io
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def patch(path, edits):
    p = os.path.join(BASE, path)
    s = io.open(p, encoding="utf-8").read()
    for old, new, what in edits:
        if old not in s:
            raise SystemExit(f"NOT FOUND in {path}: {what}")
        s = s.replace(old, new, 1)
        print(f"  ok  {path}: {what}")
    io.open(p, "w", encoding="utf-8").write(s)


# ------------------------------------------------------------------ app
patch("streamlit_app.py", [
    (
        "from reopt_core import defaults as D\nfrom reopt_core import ui_fields as U",
        "import ui_theme as T\nfrom reopt_core import defaults as D\nfrom reopt_core import ui_fields as U",
        "import ui_theme",
    ),
    (
        'st.title(":material/bolt: REopt calculator")',
        'T.inject()\nst.title(":material/bolt: REopt calculator")',
        "inject stylesheet",
    ),
    # step headings -> REopt orange
    ('st.header(U.STEPS[1])  # "Step 1: Select Use Case"',
     'T.step(U.STEPS[1])', "step 1 heading"),
    ('st.header(U.STEPS[2])  # "Step 2: Select Grid-Tied or Off-Grid"',
     'T.step(U.STEPS[2])', "step 2 heading"),
    ('st.header(U.STEPS[3])  # "Step 3: Select Your Energy Goals"',
     'T.step(U.STEPS[3])', "step 3 heading"),
    ('st.header(U.STEPS[4].replace(" *", ""))  # "Step 4: Select Technologies to Evaluate"',
     'T.step(U.STEPS[4].replace(" *", ""))', "step 4 heading"),
    ('st.header(U.STEPS[5])  # "Step 5: Enter Your Site Data"',
     'T.step(U.STEPS[5])', "step 5 heading"),
    # orange bars above each Step-5 panel
    ('with st.expander("Site (required)", expanded=True):',
     'T.panel_head("Site", icon="location_on", required=True)\n'
     'with st.expander("Site inputs", expanded=True):',
     "Site panel head"),
    ('    with st.expander("Utilities (required)", expanded=True):',
     '    T.panel_head("Utilities", icon="bolt", required=True)\n'
     '    with st.expander("Utility inputs", expanded=True):',
     "Utilities panel head"),
    ('with st.expander("Load Profiles (required)", expanded=True):',
     'T.panel_head("Load Profiles", icon="bar_chart", required=True)\n'
     'with st.expander("Load profile inputs", expanded=True):',
     "Load Profiles panel head"),
    ('with st.expander("Financial", expanded=False):',
     'T.panel_head("Financial", icon="attach_money")\n'
     'with st.expander("Financial inputs", expanded=False):',
     "Financial panel head"),
    ('with st.expander("Emissions", expanded=False):',
     'T.panel_head("Emissions", icon="eco")\n'
     'with st.expander("Emissions inputs", expanded=False):',
     "Emissions panel head"),
    ('    with st.expander("PV", expanded=False):',
     '    T.panel_head("PV", icon="solar_power")\n'
     '    with st.expander("PV inputs", expanded=False):',
     "PV panel head"),
    ('    with st.expander("Battery", expanded=False):',
     '    T.panel_head("Battery", icon="battery_charging_full")\n'
     '    with st.expander("Battery inputs", expanded=False):',
     "Battery panel head"),
])

# -------------------------------------------------------------- results
patch("app_results.py", [
    (
        "import altair as alt\nimport pandas as pd\nimport streamlit as st",
        "import altair as alt\nimport pandas as pd\nimport streamlit as st\n\nimport ui_theme as T",
        "import ui_theme",
    ),
    (
        '''    # ------------------------------------------------------ headline metrics
    c = st.columns(4)
    c[0].metric("PV size", _kw(sz["pv_kw"]))
    c[1].metric("Battery power", _kw(sz["battery_kw"]))
    c[2].metric("Battery capacity", _kwh(sz["battery_kwh"]))
    if sz["fueltech_kind"]:
        c[3].metric(f"{sz['fueltech_kind']} size", _kw(sz["fueltech_kw"]))
    else:
        c[3].metric("Load met",
                    f"{100 * (1 - en['unserved_kwh'] / en['annual_load_kwh']):.2f} %")

    if not off_grid and bau:
        savings = bau["lifecycle_cost"] - res["objective_lifecycle_cost"]
        c = st.columns(4)
        c[0].metric(f"Life cycle savings ({years} yr)", _m(savings))
        c[1].metric("Payback period",
                    f"{pf['simple_payback_years']:.2f} yrs"
                    if pf.get("simple_payback_years") is not None else "N/A")
        c[2].metric("Internal rate of return",
                    f"{100 * pf['internal_rate_of_return']:.1f} %" if pf else "N/A")
        c[3].metric("PV levelized cost of energy",
                    f"${pf.get('pv_lcoe', 0.0):.3f}/kWh" if pf else "N/A")
    else:
        lcoe = res["objective_lifecycle_cost"] / max(1.0, en["annual_load_kwh"] * years)
        c = st.columns(3)
        c[0].metric("Total life cycle cost", _m(res["objective_lifecycle_cost"]))
        c[1].metric("Levelized cost of energy", f"${lcoe:.3f}/kWh")
        c[2].metric("Unserved load", _kwh(en["unserved_kwh"]))''',
        '''    # ------------------------------------------------------ headline cards
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
                    f"{100 * (1 - en['unserved_kwh'] / en['annual_load_kwh']):.2f} %")''',
        "headline cards",
    ),
])

print("theme applied")
