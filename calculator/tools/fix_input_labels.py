"""The Inputs table was echoing internal model keys (installed_cost_per_kw,
min_kw, ...). Replace them with the REopt labels, taken from ui_fields.py,
and match REopt's own value formatting and row order.
"""

import io
import os

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "streamlit_app.py")
s = io.open(P, encoding="utf-8").read()

start = s.index('            "inputs_echo": {')
end = s.index("            },\n        }", start) + len("            },\n        }")

NEW = '''            "inputs_echo": _inputs_echo(
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
        }'''
s = s[:start] + NEW + s[end:]

HELPER = '''

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
        utilities["Compensation type"] = k["compensation"]

    load = {
        "Typical electric load profile type": "simulated building",
        "Type of building": k["bldg"] or "—",
        "Annual electric energy consumption (kWh)": f"{k['annual_kwh']:,.0f}",
    }
    financial = {
        "Analysis period (years)": int(k["analysis_years"]),
        "Host discount rate, nominal (%)": f"{k['discount']}%",
        "Electricity cost escalation rate, nominal (%/year)": f"{k['elec_esc']}%",
        "O&M cost escalation rate (%/year)": f"{k['om_esc']}%",
        "Host effective tax rate (%)": f"{k['tax_rate']}%",
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
'''

# put the helper just before the state block (module level, after the widgets)
anchor = "\n# ------------------------------------------------------------------- run\n"
if anchor not in s:
    raise SystemExit("run anchor not found")
s = s.replace(anchor, HELPER + anchor, 1)

io.open(P, "w", encoding="utf-8").write(s)
print("Inputs echo now uses REopt labels")
