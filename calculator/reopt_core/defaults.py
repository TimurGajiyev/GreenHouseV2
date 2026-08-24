"""Default values extracted from REopt.jl v0.61.1 struct definitions.

Every value carries a source reference. These are the values the REopt web tool
silently applies when a form field is left blank.
"""

from __future__ import annotations

# ---------------------------------------------------------------- Financial
# REopt/src/core/financial.jl:5-20
FINANCIAL = {
    "om_cost_escalation_rate_fraction": 0.025,
    "elec_cost_escalation_rate_fraction": 0.0166,
    "offtaker_tax_rate_fraction": 0.26,
    "offtaker_discount_rate_fraction": 0.0624,
    "owner_tax_rate_fraction": 0.26,           # = offtaker when not third-party
    "owner_discount_rate_fraction": 0.0624,    # = offtaker when not third-party
    "analysis_years": 25,
    "value_of_lost_load_per_kwh": 1.00,        # financial.jl:17
    "microgrid_upgrade_cost_fraction": 0.0,    # financial.jl:18
    "third_party_ownership": False,
    "offgrid_other_capital_costs": 0.0,
    "offgrid_other_annual_costs": 0.0,
}

# ---------------------------------------------------------------------- PV
# REopt/src/core/pv.jl:5-28
PV = {
    "array_type": 1,               # 0 Ground Fixed, 1 Rooftop Fixed, 2 1-axis, 3 backtrack, 4 2-axis
    "module_type": 0,              # 0 Standard, 1 Premium, 2 Thin film
    "losses": 0.14,
    "gcr": 0.4,
    "inv_eff": 0.96,
    "dc_ac_ratio": 1.2,
    # pv.jl:18 says 18.0, but REopt actually applies the SIZE CLASS value from
    # data/pv/pv_defaults.json. The tool's own Defaults page reports $20/kW-DC
    # for size class 3 (Large Commercial), which is what a commercial run gets.
    "om_cost_per_kw": 20.0,
    "om_cost_per_kw_generic": 18.0,
    "degradation_fraction": 0.005,
    "macrs_option_years": 5,
    "macrs_bonus_fraction": 1.0,
    "macrs_itc_reduction": 0.5,
    "federal_itc_fraction": 0.3,
    "kw_per_square_foot": 0.01,
    "acres_per_kw": 6e-3,
    "min_kw": 0.0,
    "max_kw": 1.0e9,
    "radius": 0,
}

# PV cost curve by size class -- REopt/data/pv/pv_defaults.json
# (roof values; ground-mount applies a mount_premium)
PV_SIZE_CLASSES = [
    {"size_class": 1, "name": "Residential",      "range": (3, 11),            "cost": 2783, "om": 32},
    {"size_class": 2, "name": "Small Commercial", "range": (11, 100),          "cost": 2232, "om": 26},
    {"size_class": 3, "name": "Large Commercial", "range": (100, 2000),        "cost": 1920, "om": 20},
    {"size_class": 4, "name": "Industrial",       "range": (2000, 10000),      "cost": 1661, "om": 20},
    {"size_class": 5, "name": "Utility",          "range": (10000, 100000),    "cost": 1239, "om": 17},
]

# ---------------------------------------------------------- ElectricStorage
# REopt/src/core/energy_storage/electric_storage.jl:225-265
ELECTRIC_STORAGE = {
    "min_kw": 0.0,
    "max_kw": 1.0e4,
    "min_kwh": 0.0,
    "max_kwh": 1.0e6,
    "internal_efficiency_fraction": 0.975,
    "inverter_efficiency_fraction": 0.96,
    "rectifier_efficiency_fraction": 0.96,
    "can_grid_charge": True,
    "installed_cost_per_kw": 968.0,
    "installed_cost_per_kwh": 253.0,
    "installed_cost_constant": 222115.0,   # <-- six figures, invisible in the UI
    "replace_cost_per_kw": 0.0,
    "replace_cost_per_kwh": 0.0,
    "replace_cost_constant": 0.0,
    "inverter_replacement_year": 10,
    "battery_replacement_year": 10,
    "cost_constant_replacement_year": 10,
    "om_cost_fraction_of_installed_cost": 0.025,
    "macrs_option_years": 5,
    "macrs_bonus_fraction": 1.0,
    "macrs_itc_reduction": 0.5,
    "total_itc_fraction": 0.3,
    "total_rebate_per_kw": 0.0,
    "total_rebate_per_kwh": 0.0,
    "soc_min_fraction": 0.2,               # 0.8 when dispatch_strategy == "backup"
    "soc_init_fraction": 0.5,              # 1.0 off-grid
    "min_duration_hours": 0.0,
    "max_duration_hours": 100000.0,
    "dispatch_strategy": "optimized",      # the web UI sends "cost_optimal"; API translates
    "model_degradation": False,
}
# electric_storage.jl:254-255
ELECTRIC_STORAGE["charge_efficiency"] = (
    ELECTRIC_STORAGE["rectifier_efficiency_fraction"]
    * ELECTRIC_STORAGE["internal_efficiency_fraction"] ** 0.5
)
ELECTRIC_STORAGE["discharge_efficiency"] = (
    ELECTRIC_STORAGE["inverter_efficiency_fraction"]
    * ELECTRIC_STORAGE["internal_efficiency_fraction"] ** 0.5
)

# The web UI's dispatch_strategy values -> REopt.jl enum.
# "cost_optimal" and "daily_foresight_optimized" do not exist in REopt.jl;
# the API layer translates them. electric_storage.jl:261
DISPATCH_STRATEGY_UI_TO_JL = {
    "cost_optimal": "optimized",
    "peak_shaving_look_ahead": "peak_shaving_look_ahead",
    "peak_shaving_look_behind": "peak_shaving_look_behind",
    "self_consumption": "self_consumption",
    "backup": "backup",
    "daily_foresight_optimized": "optimized",  # API-only in REopt.jl
    "custom_soc": "custom_soc",
}

# --------------------------------------------------------------- Generator
# REopt/src/core/generator.jl:9-47
def generator_defaults(off_grid_flag: bool = False, only_runs_during_grid_outage: bool = True,
                       analysis_years: int = 25) -> dict:
    installed = 880.0 if off_grid_flag else (650.0 if only_runs_during_grid_outage else 800.0)
    return {
        "installed_cost_per_kw": installed,
        "om_cost_per_kw": 10.0 if off_grid_flag else 20.0,
        "om_cost_per_kwh": 0.0,
        "fuel_cost_per_gallon": 2.25,
        "electric_efficiency_full_load": 0.322,
        "electric_efficiency_half_load": 0.322,
        "fuel_higher_heating_value_kwh_per_gal": 40.7,
        "min_turn_down_fraction": 0.15 if off_grid_flag else 0.0,
        "macrs_option_years": 0,
        "macrs_bonus_fraction": 0.0,
        "macrs_itc_reduction": 0.0,
        "federal_itc_fraction": 0.0,
        "replacement_year": 10 if off_grid_flag else analysis_years,
        "replace_cost_per_kw": installed if off_grid_flag else 0.0,
        "only_runs_during_grid_outage": only_runs_during_grid_outage,
        "min_kw": 0.0,
        "max_kw": 1.0e9,
    }

def chp_defaults(is_electric_only: bool = False) -> dict:
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


# -------------------------------------------------------------- Site / CRB
# REopt/src/core/doe_commercial_reference_building_loads.jl:61-78
CRB_CITIES = [
    ("Miami", 25.761680, -80.191790, "1A"),
    ("Houston", 29.760427, -95.369803, "2A"),
    ("Phoenix", 33.448377, -112.074037, "2B"),
    ("Atlanta", 33.748995, -84.387982, "3A"),
    ("LasVegas", 36.1699, -115.1398, "3B"),
    ("LosAngeles", 34.052234, -118.243685, "3B"),
    ("SanFrancisco", 37.3382, -121.8863, "3C"),
    ("Baltimore", 39.290385, -76.612189, "4A"),
    ("Albuquerque", 35.085334, -106.605553, "4B"),
    ("Seattle", 47.606209, -122.332071, "4C"),
    ("Chicago", 41.878114, -87.629798, "5A"),
    ("Boulder", 40.014986, -105.270546, "5B"),
    ("Minneapolis", 44.977753, -93.265011, "6A"),
    ("Helena", 46.588371, -112.024505, "6B"),
    ("Duluth", 46.786672, -92.100485, "7"),
    ("Fairbanks", 59.0397, -158.4575, "8"),
]

# DOE building types are NOT duplicated here on purpose: the authoritative
# list (22 options, exact labels and order) is generated from the live tool
# into reopt_core/ui_fields.py. Use:
#     ui_fields.options("run_site_attributes_load_profile_attributes_doe_reference_name")
