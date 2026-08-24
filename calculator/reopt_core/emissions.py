"""Grid emissions: Cambium CO2e (climate) + AVERT NOx/SO2/PM2.5 (health).

Mirrors REopt.jl's ElectricUtility emissions inputs:
  * climate  -> Cambium levelized hourly LRMER CO2e, via the same public API
                REopt calls (electric_utility.jl:569-610), lb/MWh -> lb/kWh
  * health   -> AVERT hourly factors shipped in REopt/data/emissions/AVERT_Data,
                declining by ``emissions_factor_*_decrease_fraction`` per year
Costs use the ``annuity`` present-worth factor with each pollutant's own
escalation rate.
"""

from __future__ import annotations

import csv
import io
import json
import os
import urllib.parse
import urllib.request

from .data_sources import REOPT_DIR
from .finance import annuity, annuity_two_escalation_rates

LB_PER_TONNE = 2204.62
AVERT_DIR = os.path.join(REOPT_DIR, "data", "emissions", "AVERT_Data")

# electric_utility.jl:455-471
AVERT_NAME_TO_ABBR = {
    "California": "CA", "Central": "CENT", "Florida": "FL", "Mid-Atlantic": "MIDA",
    "Midwest": "MIDW", "Carolinas": "NCSC", "New England": "NE", "Northwest": "NW",
    "New York": "NY", "Rocky Mountains": "RM", "Southeast": "SE", "Southwest": "SW",
    "Tennessee": "TN", "Texas": "TE", "Alaska": "AKGD",
    "Hawaii (except Oahu)": "HIMS", "Hawaii (Oahu)": "HIOA",
}

# Cost and escalation defaults as the tool's own Defaults page reports them.
EMISSIONS_DEFAULTS = {
    "CO2_cost_per_tonne": 51.0,
    "NOx_grid_cost_per_tonne": 4541.52,
    "SO2_grid_cost_per_tonne": 15887.31,
    "PM25_grid_cost_per_tonne": 103498.17,
    "CO2_cost_escalation_rate_fraction": 0.0422,
    "NOx_cost_escalation_rate_fraction": 0.0316,
    "SO2_cost_escalation_rate_fraction": 0.0436,
    "PM25_cost_escalation_rate_fraction": 0.0417,
    # health factors decline over the analysis period
    "emissions_factor_nox_so2_pm25_decrease_fraction": 0.04590,
    "cambium_scenario": "Mid-case",
    "cambium_location_type": "GEA Regions 2023",
    "cambium_metric_col": "lrmer_co2e",
    "cambium_grid_level": "enduse",
    "cambium_start_year": 2025,
}


def load_avert_profile(pollutant: str, region_name: str) -> list[float]:
    """Hourly lb/kWh for one pollutant and AVERT region (8760 values)."""
    abbr = AVERT_NAME_TO_ABBR.get(region_name)
    if not abbr:
        raise ValueError(f"Unknown AVERT region {region_name!r}")
    path = os.path.join(AVERT_DIR, f"AVERT_2023_{pollutant}_lb_per_kwh.csv")
    with io.open(path, encoding="utf-8-sig") as fh:
        col = [float(r[abbr]) for r in csv.DictReader(fh)]
    while len(col) < 8760:      # the shipped CSVs carry 8759 rows
        col.append(col[-1])
    return col[:8760]


def fetch_cambium_profile(latitude: float, longitude: float, *,
                          scenario: str = "Mid-case",
                          location_type: str = "GEA Regions 2023",
                          start_year: int = 2025,
                          lifetime: int = 25,
                          metric_col: str = "lrmer_co2e",
                          grid_level: str = "enduse",
                          timeout: int = 90) -> dict:
    """electric_utility.jl:569 -- same endpoint, project uuid and parameters."""
    payload = {
        "project_uuid": "0f92fe57-3365-428a-8fe8-0afc326b3b43",   # Cambium 2023
        "scenario": scenario,
        "location_type": location_type,
        "latitude": str(round(latitude, 3)),
        "longitude": str(round(longitude, 3)),
        "start_year": str(start_year),
        "lifetime": str(lifetime),
        "discount_rate": "0.0",
        "time_type": "hourly",
        "metric_col": metric_col,
        "smoothing_method": "rolling",
        "gwp": "100yrAR6",
        "grid_level": grid_level,
        "ems_mass_units": "lb",
    }
    url = "https://scenarioviewer.nlr.gov/api/get-levelized/?" + urllib.parse.urlencode(payload)
    req = urllib.request.Request(url, headers={"User-Agent": "REopt.jl"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    msg = resp.get("message") or {}
    vals = msg.get("values") or []
    if len(vals) != 8760:
        raise RuntimeError(f"Cambium returned {len(vals)} values, expected 8760")
    # lb/MWh -> lb/kWh for CO2 metrics
    series = [v / 1000.0 for v in vals] if "co2" in metric_col else list(vals)
    return {"location": msg.get("location", ""), "metric_col": msg.get("metric_col", metric_col),
            "series": series}


def fetch_avert_profile(latitude: float, longitude: float, year: int = 2017,
                        timeout: int = 90) -> dict:
    """AVERT region + hourly grid emissions factors, day-of-week aligned.

    Same endpoint the web tool uses. Preferred over reading the shipped CSVs
    directly because it also resolves the AVERT region from lat/lon (REopt does
    that with a shapefile lookup) and aligns the profile to the load year.
    """
    url = ("https://reopt.nlr.gov/tool/emissions-profile?"
           + urllib.parse.urlencode({"latitude": latitude, "longitude": longitude,
                                     "year": year}))
    req = urllib.request.Request(url, headers={"User-Agent": "REopt-calculator"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    series = {}
    for pol in ("NOx", "SO2", "PM25", "CO2"):
        key = f"emissions_factor_series_lb_{pol}_per_kwh"
        if key in d and len(d[key]) == 8760:
            series[pol] = [float(v) for v in d[key]]
    return {
        "avert_region": d.get("avert_region", ""),
        "avert_region_abbr": d.get("avert_region_abbr", ""),
        "series": series,
    }


def fetch_health_cost_defaults(latitude: float, longitude: float,
                               inflation: float = 0.025, timeout: int = 60) -> dict:
    """Location-specific EASIUR health costs and escalation rates.

    REopt derives these from the EASIUR dataset via a CAMx grid lookup
    (financial.jl:220-300). Rather than port the HDF5 + Lambert projection we
    call the same endpoint the web tool uses to populate its own defaults --
    values match the tool's Defaults page exactly for every location tested.
    """
    url = ("https://reopt.nlr.gov/tool/emissions-health-defaults?"
           + urllib.parse.urlencode({"latitude": latitude, "longitude": longitude,
                                     "inflation": inflation}))
    req = urllib.request.Request(url, headers={"User-Agent": "REopt-calculator"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    if "error" in d:
        raise RuntimeError(f"emissions-health-defaults: {d['error']}")
    out = {}
    for pol in ("NOx", "SO2", "PM25"):
        for suffix in ("grid_cost_per_tonne", "onsite_fuelburn_cost_per_tonne",
                       "cost_escalation_rate_fraction"):
            key = f"{pol}_{suffix}"
            if key in d:
                out[key] = float(d[key])
    return out


def _health_mean_factor(decrease: float, years: int) -> float:
    """Mean of (1 - d)^y over y = 1..N -- REopt reports the period average."""
    return sum((1 - decrease) ** y for y in range(1, years + 1)) / years


def compute(*, grid_kwh_hourly: list[float], cambium_series: list[float],
            avert: dict[str, list[float]], years: int,
            discount_rate: float, opts: dict | None = None) -> dict:
    """Annual and lifetime emissions plus their monetised cost.

    ``grid_kwh_hourly`` is grid electricity consumed in each hour (kWh);
    onsite fuel burn is not modelled here (no generator fuel emissions yet).
    """
    o = dict(EMISSIONS_DEFAULTS)
    o.update(opts or {})

    co2_t = sum(cambium_series[h] * grid_kwh_hourly[h] for h in range(8760)) / LB_PER_TONNE

    decrease = o["emissions_factor_nox_so2_pm25_decrease_fraction"]
    hf = _health_mean_factor(decrease, years)
    health_yr1, health_t = {}, {}
    for pol in ("NOx", "SO2", "PM25"):
        prof = avert.get(pol)
        yr1 = sum(prof[h] * grid_kwh_hourly[h] for h in range(8760)) / LB_PER_TONNE if prof else 0.0
        health_yr1[pol] = yr1
        # REopt reports the AVERAGE annual emissions over the analysis period
        health_t[pol] = yr1 * hf

    cost_climate = (co2_t * o["CO2_cost_per_tonne"]
                    * annuity(years, o["CO2_cost_escalation_rate_fraction"], discount_rate))

    # Health factors fall while their $/tonne rises, so the two rates must be
    # combined in one annuity (utils.jl:21 annuity_two_escalation_rates) rather
    # than averaged separately -- doing it separately understates cost by ~9%.
    cost_health = sum(
        health_yr1[pol] * o[f"{pol}_grid_cost_per_tonne"]
        * annuity_two_escalation_rates(
            years, o[f"{pol}_cost_escalation_rate_fraction"], -decrease, discount_rate)
        for pol in ("NOx", "SO2", "PM25")
    )

    return {
        "annual_co2e_tonnes": co2_t,
        "total_co2e_tonnes": co2_t * years,
        "annual_nox_tonnes": health_t["NOx"],
        "annual_so2_tonnes": health_t["SO2"],
        "annual_pm25_tonnes": health_t["PM25"],
        "total_nox_tonnes": health_t["NOx"] * years,
        "total_so2_tonnes": health_t["SO2"] * years,
        "total_pm25_tonnes": health_t["PM25"] * years,
        "cost_climate": cost_climate,
        "cost_health": cost_health,
    }
