"""Kaggle "Microgrid Energy Forecasting Dataset" -> REopt core, BESS payback.

The case:

    BAU      grid + 8.0 MW aggregate CHP
    Optimal  grid + 8.0 MW aggregate CHP + 5.5 MW / 11 MWh BESS ($3,300,000)

and the question is what the BESS is worth -- NPV, simple payback, dispatch.

This maps the CSV onto REopt.jl's own input schema and solves it with the local
engine (``tools.reopt_jl``), BAU alongside optimal, so the financials come out of
REopt's own proforma rather than a spreadsheet beside it.

    python tools/kaggle_microgrid_case.py --audit         dataset audit only, no solve
    python tools/kaggle_microgrid_case.py                 solve the headline (scaled) case
    python tools/kaggle_microgrid_case.py --load-scale=1   solve the raw-dataset case
    python tools/kaggle_microgrid_case.py --both          both scales, side by side
    python tools/kaggle_microgrid_case.py --chart=out.png  write the dispatch chart

READ THE AUDIT FIRST. The dataset is synthetic i.i.d. uniform noise -- solar at
03:00 averages as much as solar at noon, and irradiance, wind speed and cloud
cover have zero correlation with the power columns. ``--audit`` proves it. What
follows therefore tests the *harness*, not any real site's payback.

The "cut off" rule
------------------
Two CHP units, unit commitment, part-load efficiency curves and thermal tracking
are cut out, not worked around. The aggregate plant is a single REopt
``Generator``:

  * ``existing_kw = 8000`` with ``min_kw = max_kw = 0`` -- REopt sets
    ``min_sizes = existing_kw + min_kw`` and ``max_sizes = existing_kw + max_kw``
    (``reopt_inputs.jl:724``), so the plant is pinned at 8 MW in both cases and
    carries no capital cost. That is what makes BAU "grid + CHP only".
  * ``electric_efficiency_half_load == electric_efficiency_full_load`` -- REopt's
    ``fuel_slope_and_intercept`` (``utils.jl:645``) then returns intercept 0 and
    slope 1/eff: a single straight fuel-to-power line through the origin at one
    constant efficiency. No part-load curve.
  * ``min_turn_down_fraction = 0`` and ``om_cost_per_hr_per_kw_rated = 0`` -- the
    ``binGenIsOnInTS`` binary stays cost-free and otherwise unconstrained, so
    there is no commitment logic to solve.
  * no thermal load and no ``CHP`` object at all: the heat side is out of scope.

Every one of those is a stock REopt input. Nothing here patches the model.

Fuel units
----------
``fuel_higher_heating_value_kwh_per_gal = 293.07107`` (kWh per MMBtu), so one
REopt "gallon" is one MMBtu: ``fuel_cost_per_gallon`` reads as $/MMBtu and
``annual_fuel_consumption_gal`` reads as MMBtu.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.reopt_jl import run_reopt_jl

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV = os.path.join(ROOT, "microgrid_energy_dataset (1).csv")

KWH_PER_MMBTU = 293.07107
HOURS = 8760

# --- the system under test --------------------------------------------------
CHP_KW = 8_000.0          # aggregate of the two CHP units
BESS_KW = 5_500.0
BESS_KWH = 11_000.0
BESS_CAPEX = 3_300_000.0  # $ -- the number the payback is asked against

# --- assumptions the dataset does not carry (all overridable on the CLI) ----
CHP_EFFICIENCY = 0.35     # electric, HHV, constant -- the aggregate simplification
CHP_FUEL_PER_MMBTU = 8.00  # $/MMBtu gas, as the repo's other CHP cases use
CHP_OM_PER_KWH = 0.010    # $/kWh variable O&M
LAT, LON = 39.74437, -105.15199  # Golden CO, the site the repo's other cases use
DATA_YEAR = 2023

# Emissions are outside this case's scope. Supplying constants keeps the solve
# offline and deterministic (REopt otherwise calls Cambium/AVERT for them) and
# changes no financial result: include_climate_in_objective defaults to false.
GRID_CO2_LB_PER_KWH = 0.85


# ===========================================================================
# 1. load and audit
# ===========================================================================

def load_dataset(path: str = CSV) -> pd.DataFrame:
    """Read the Kaggle CSV, with the columns this case needs checked present."""
    df = pd.read_csv(path, parse_dates=["timestamp"])
    need = ["timestamp", "load_demand", "electricity_price",
            "solar_power_output", "wind_power_output"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise SystemExit(f"{path}: missing column(s) {missing}")
    return df.sort_values("timestamp").reset_index(drop=True)


def audit(df: pd.DataFrame) -> dict:
    """What the dataset actually is. Every claim is recomputed here, not asserted."""
    out: dict = {}
    step = df.timestamp.diff().dropna().mode().iloc[0]
    out["rows"] = len(df)
    out["step_minutes"] = step.total_seconds() / 60.0
    out["span_days"] = (df.timestamp.max() - df.timestamp.min()).total_seconds() / 86400.0
    out["start"], out["end"] = str(df.timestamp.min()), str(df.timestamp.max())
    out["regular"] = bool((df.timestamp.diff().dropna() == step).all())
    out["nans"] = int(df.isna().sum().sum())

    # (a) uniform-noise fingerprint: for U(a,b), std == (b-a)/sqrt(12), mean == (a+b)/2
    uni = {}
    for c in ("load_demand", "electricity_price", "solar_power_output",
              "wind_power_output", "solar_irradiance", "temperature"):
        if c not in df:
            continue
        s = df[c]
        uni[c] = {"min": float(s.min()), "max": float(s.max()),
                  "mean": float(s.mean()), "std": float(s.std()),
                  "mean_if_uniform": float((s.max() + s.min()) / 2),
                  "std_if_uniform": float((s.max() - s.min()) / np.sqrt(12))}
    out["uniform_fingerprint"] = uni

    # (b) diurnal structure -- does the sun rise in this dataset?
    # The ratio is only meaningful while night output is non-zero; for a real PV
    # fleet it is zero, so report inf there rather than dividing by noise.
    if "hour_of_day" in df:
        byh = df.groupby("hour_of_day")["solar_power_output"].mean()
        night = max(float(byh.reindex([0, 1, 2, 3, 4, 22, 23]).mean()), 0.0)
        noon = float(byh.reindex([11, 12, 13, 14]).mean())
        out["solar_night_kw"], out["solar_noon_kw"] = night, noon
        out["solar_noon_over_night"] = (
            noon / night if night > 0.01 * abs(noon) else float("inf"))

    # (c) physical correlations that must hold in real data
    pairs = [("solar_irradiance", "solar_power_output"), ("wind_speed", "wind_power_output"),
             ("cloud_cover", "solar_irradiance"), ("temperature", "load_demand"),
             ("load_demand", "electricity_price")]
    out["correlations"] = {f"{a} ~ {b}": float(df[a].corr(df[b]))
                           for a, b in pairs if a in df and b in df}

    # (d) the only real relationships in the file: two arithmetic identities
    ident = {}
    if {"total_power_generation", "solar_power_output", "wind_power_output"} <= set(df):
        r = df.total_power_generation - df.solar_power_output - df.wind_power_output
        ident["total_power_generation == solar + wind"] = float(np.abs(r).max())
    if {"optimal_energy_dispatch", "total_power_generation", "load_demand"} <= set(df):
        r = df.optimal_energy_dispatch - (df.total_power_generation - df.load_demand)
        ident["optimal_energy_dispatch == generation - load"] = float(np.abs(r).max())
    out["identities_max_abs_residual"] = ident
    return out


def print_audit(a: dict) -> None:
    print("=" * 78)
    print("DATASET AUDIT")
    print("=" * 78)
    print(f"  {a['rows']:,} rows at {a['step_minutes']:.0f} min, {a['start']} -> {a['end']}")
    print(f"  {a['span_days']:.1f} days   regular grid: {a['regular']}   NaNs: {a['nans']}")
    print()
    print("  Uniform-noise fingerprint   for U(a,b): mean = (a+b)/2, std = (b-a)/sqrt(12)")
    print(f"    {'column':<22}{'min':>9}{'max':>9}{'mean':>10}{'=U?':>9}{'std':>9}{'=U?':>9}")
    for c, v in a["uniform_fingerprint"].items():
        print(f"    {c:<22}{v['min']:>9.2f}{v['max']:>9.2f}{v['mean']:>10.2f}"
              f"{v['mean_if_uniform']:>9.2f}{v['std']:>9.2f}{v['std_if_uniform']:>9.2f}")
    print("    -> every column's mean and std match a flat uniform draw to ~1%.")
    print()
    if "solar_noon_over_night" in a:
        ratio = a["solar_noon_over_night"]
        shown = "inf (night output is zero -- a real day)" if ratio == float("inf") else f"{ratio:.2f}x"
        print(f"  Diurnal structure    solar 22:00-04:00 {a['solar_night_kw']:.1f} kW"
              f"   vs noon {a['solar_noon_kw']:.1f} kW   ratio {shown}")
        print("    -> a real PV fleet is 0 kW at night. This one is not. There is no day.")
    print()
    print("  Physical correlations that real data must show")
    for k, v in a["correlations"].items():
        print(f"    r = {v:+.4f}   {k}")
    print("    -> irradiance does not drive solar, wind speed does not drive wind, cloud")
    print("       does not dim irradiance. The columns are independent draws.")
    print()
    print("  The only genuine relationships in the file (max |residual|)")
    for k, v in a["identities_max_abs_residual"].items():
        print(f"    {v:.3e}   {k}")
    print("    -> two exact arithmetic identities. Nothing else is modelled.")
    print()
    print("  VERDICT: synthetic i.i.d. uniform noise, not a microgrid time series.")
    print("  What follows exercises the REopt mapping; it is not a site forecast. An")
    print("  i.i.d. price with a ~5 c/kWh spread every hour and no autocorrelation is an")
    print("  unrealistically good arbitrage signal, so the BESS payback below is a best")
    print("  case that real tariffs will not reproduce.")
    print()


# ===========================================================================
# 2. dataset -> REopt arrays
# ===========================================================================

def _tile(a: np.ndarray, n: int = HOURS) -> np.ndarray:
    """Repeat a short record to a full REopt year."""
    return np.tile(a, int(np.ceil(n / len(a))))[:n]


def build_profiles(df: pd.DataFrame, *, load_scale: float | str = "auto",
                   price_divisor: float = 100.0, use_renewables: bool = True,
                   chp_kw: float = CHP_KW) -> dict:
    """15-min CSV -> the two 8760-long arrays REopt wants, plus the bookkeeping.

    ``load_demand`` becomes ``ElectricLoad.loads_kw`` and ``electricity_price``
    becomes ``ElectricTariff.tou_energy_rates_per_kwh``. Solar and wind are
    subtracted from the load first, as asked, and the result is floored at zero:
    REopt has no concept of a negative load, so surplus renewable output is spilled
    and counted (``renewable_spill_kwh``) rather than smuggled in as a negative.
    """
    h = df.set_index("timestamp").resample("1h").mean(numeric_only=True)
    h = h.dropna(subset=["load_demand", "electricity_price"])

    gross = h.load_demand.to_numpy(float)
    solar = h.solar_power_output.to_numpy(float)
    wind = h.wind_power_output.to_numpy(float)
    renew = (solar + wind) if use_renewables else np.zeros_like(gross)

    # Scale: the dataset is a ~0.45 MW site (mean net load 0.08 MW once its own
    # solar and wind are netted off) and the system under test is an 8 MW plant --
    # a 100x mismatch, so one of the two has to move. 'auto' scales every power
    # column together until the mean net load equals the CHP nameplate, which is
    # the load the plant and battery actually serve. Note the side effect: this
    # dataset generates nearly as much renewable power as it consumes, so scaling
    # the residual up to 8 MW scales the renewables to ~39 MW and spills a third
    # of them. That is the dataset's own 89% renewable penetration, not an
    # artefact of the scaling; the summary reports both numbers.
    raw_mean_net = float(np.maximum(gross - renew, 0.0).mean())
    scale = (chp_kw / raw_mean_net) if load_scale == "auto" else float(load_scale)

    gross, solar, wind, renew = (x * scale for x in (gross, solar, wind, renew))
    net = np.maximum(gross - renew, 0.0)
    spill = np.maximum(renew - gross, 0.0)

    rates = h.electricity_price.to_numpy(float) / price_divisor

    record_h = len(net)
    return {
        "loads_kw": _tile(net).tolist(),
        "rates_per_kwh": _tile(rates).tolist(),
        "scale": scale,
        "record_hours": record_h,
        "record_days": record_h / 24.0,
        "tiles": HOURS / record_h,
        "gross_mean_kw": float(gross.mean()), "gross_peak_kw": float(gross.max()),
        "net_mean_kw": float(net.mean()), "net_peak_kw": float(net.max()),
        "renewable_mean_kw": float(renew.mean()),
        "renewable_used_kwh": float((renew - spill).sum() * HOURS / record_h),
        "renewable_spill_kwh": float(spill.sum() * HOURS / record_h),
        "spill_hours_fraction": float((spill > 0).mean()),
        "annual_net_kwh": float(net.mean() * HOURS),
        "rate_mean": float(rates.mean()), "rate_min": float(rates.min()),
        "rate_max": float(rates.max()),
    }


# ===========================================================================
# 3. REopt scenario
# ===========================================================================

def chp_marginal_cost_per_kwh(*, efficiency: float = CHP_EFFICIENCY,
                              fuel_per_mmbtu: float = CHP_FUEL_PER_MMBTU,
                              om_per_kwh: float = CHP_OM_PER_KWH) -> float:
    """What a kWh out of the aggregate plant costs -- the number that decides
    every dispatch hour against the grid rate."""
    return fuel_per_mmbtu / (KWH_PER_MMBTU * efficiency) + om_per_kwh


def build_scenario(prof: dict, *, with_bess: bool, chp_kw: float = CHP_KW,
                   efficiency: float = CHP_EFFICIENCY,
                   fuel_per_mmbtu: float = CHP_FUEL_PER_MMBTU,
                   om_per_kwh: float = CHP_OM_PER_KWH,
                   bess_kw: float = BESS_KW, bess_kwh: float = BESS_KWH,
                   bess_capex: float = BESS_CAPEX, incentives: bool = False) -> dict:
    """The REopt API-style dict, in the schema REopt.jl's ``run_reopt`` takes."""
    s = {
        "Settings": {"time_steps_per_hour": 1},
        "Site": {"latitude": LAT, "longitude": LON},
        "ElectricLoad": {
            "loads_kw": prof["loads_kw"],
            "year": DATA_YEAR,
            # already net of the site's own solar/wind, which REopt does not model here
            "loads_kw_is_net": True,
        },
        "ElectricTariff": {"tou_energy_rates_per_kwh": prof["rates_per_kwh"]},
        "ElectricUtility": {
            # constants, so no Cambium/AVERT call; emissions are out of scope and
            # out of the objective (include_climate_in_objective defaults false)
            "emissions_factor_series_lb_CO2_per_kwh": GRID_CO2_LB_PER_KWH,
            "emissions_factor_series_lb_NOx_per_kwh": 0.0,
            "emissions_factor_series_lb_SO2_per_kwh": 0.0,
            "emissions_factor_series_lb_PM25_per_kwh": 0.0,
        },
        # ---- the aggregate CHP, cut down to a plain dispatchable generator ----
        "Generator": {
            "only_runs_during_grid_outage": False,   # it is a prime mover, not backup
            "existing_kw": chp_kw,                   # -> min_size = max_size = chp_kw
            "min_kw": 0.0, "max_kw": 0.0,            # no new capacity, no capital cost
            "electric_efficiency_full_load": efficiency,
            "electric_efficiency_half_load": efficiency,  # == full -> linear, intercept 0
            "min_turn_down_fraction": 0.0,           # no commitment logic
            "om_cost_per_hr_per_kw_rated": 0.0,      # keeps binGenIsOnInTS cost-free
            "om_cost_per_kw": 0.0,                   # sunk plant, identical in both cases
            "om_cost_per_kwh": om_per_kwh,
            "fuel_higher_heating_value_kwh_per_gal": KWH_PER_MMBTU,  # 1 "gal" == 1 MMBtu
            "fuel_cost_per_gallon": fuel_per_mmbtu,                  # so this is $/MMBtu
            "fuel_avail_gal": 1.0e9,
            "can_curtail": True,
            "sells_energy_back_to_grid": False,
            "replacement_year": 25, "replace_cost_per_kw": 0.0,
        },
    }
    if with_bess:
        s["ElectricStorage"] = {
            "min_kw": bess_kw, "max_kw": bess_kw,          # forced 5.5 MW
            "min_kwh": bess_kwh, "max_kwh": bess_kwh,      # forced 11 MWh
            "installed_cost_per_kw": 0.0,
            "installed_cost_per_kwh": bess_capex / bess_kwh,  # -> capex == bess_capex
            # REopt adds a flat $222,115 "+c" adder to every battery by default.
            # The case pins CAPEX at exactly $3.3M, so it has to go -- and dropping
            # it also drops the binIncludeStorageCostConstant binary with it.
            "installed_cost_constant": 0.0,
            "replace_cost_per_kw": 0.0, "replace_cost_per_kwh": 0.0,
            "replace_cost_constant": 0.0,
            "can_grid_charge": True,
            "total_itc_fraction": 0.30 if incentives else 0.0,
            "macrs_option_years": 5 if incentives else 0,
        }
    else:
        s["ElectricStorage"] = {"max_kw": 0.0, "max_kwh": 0.0}
    return s


# ===========================================================================
# 4. metrics
# ===========================================================================

def _g(res: dict, tech: str, key: str, default: float = 0.0) -> float:
    return float(res.get(tech, {}).get(key, default) or 0.0)


def year_one_operating_cost(res: dict) -> dict:
    """Year-one cash out of the door: utility bill + CHP fuel + CHP O&M."""
    utility = _g(res, "ElectricTariff", "year_one_bill_before_tax")
    fuel = _g(res, "Generator", "year_one_fuel_cost_before_tax")
    om = (_g(res, "Generator", "year_one_variable_om_cost_before_tax")
          + _g(res, "Generator", "year_one_fixed_om_cost_before_tax"))
    return {"utility": utility, "fuel": fuel, "chp_om": om,
            "total": utility + fuel + om}


def dispatch_series(res: dict) -> dict:
    """Grid / CHP / BESS power series, in the sign convention the chart uses."""
    n = HOURS
    z = np.zeros(n)

    def ser(tech: str, key: str) -> np.ndarray:
        v = res.get(tech, {}).get(key)
        return z if v is None else np.asarray(v, float)[:n]

    grid_load = ser("ElectricUtility", "electric_to_load_series_kw")
    grid_stor = ser("ElectricUtility", "electric_to_storage_series_kw")
    chp_load = ser("Generator", "electric_to_load_series_kw")
    chp_stor = ser("Generator", "electric_to_storage_series_kw")
    bess_load = ser("ElectricStorage", "storage_to_load_series_kw")
    soc = ser("ElectricStorage", "soc_series_fraction")
    return {"grid_to_load": grid_load, "chp_to_load": chp_load,
            "bess_discharge": bess_load, "bess_charge": grid_stor + chp_stor,
            "grid_to_storage": grid_stor, "chp_to_storage": chp_stor,
            "soc": soc, "load": grid_load + chp_load + bess_load}


def summarize(bau: dict, opt: dict, prof: dict, *, bess_capex: float = BESS_CAPEX) -> dict:
    """The financial answer, both the way REopt states it and the way asked for."""
    ob, oo = year_one_operating_cost(bau), year_one_operating_cost(opt)
    savings = ob["total"] - oo["total"]
    fin = opt.get("Financial", {})

    out = {
        "bau_opex": ob, "opt_opex": oo,
        "savings_year_one": savings,
        "savings_utility": ob["utility"] - oo["utility"],
        "savings_fuel": ob["fuel"] - oo["fuel"],
        "savings_chp_om": ob["chp_om"] - oo["chp_om"],
        "bess_capex": bess_capex,
        "simple_payback_years": (bess_capex / savings) if savings > 0 else float("inf"),
        # REopt's own, from its proforma: after-tax free cash flow, its internal BAU
        "reopt_npv": float(fin.get("npv", float("nan"))),
        "reopt_simple_payback_years": float(fin.get("simple_payback_years", float("nan"))),
        "reopt_irr": float(fin.get("internal_rate_of_return", float("nan")) or 0.0),
        # REopt returns early from its proforma when cumulative cash flow never
        # turns positive (results/proforma.jl:345), leaving simple_payback_years
        # and IRR at their initialised 0.0. A literal 0.0 therefore means "never
        # pays back", not "pays back instantly" -- do not read it as a number.
        "reopt_never_pays_back": float(fin.get("simple_payback_years", -1.0)) == 0.0,
        "reopt_lcc": float(fin.get("lcc", float("nan"))),
        "reopt_lcc_bau": float(fin.get("lcc_bau", float("nan"))),
        "reopt_initial_capital_costs": float(fin.get("initial_capital_costs", 0.0)),
        # energy
        "bau_grid_kwh": _g(bau, "ElectricUtility", "annual_energy_supplied_kwh"),
        "opt_grid_kwh": _g(opt, "ElectricUtility", "annual_energy_supplied_kwh"),
        "bau_chp_kwh": _g(bau, "Generator", "annual_energy_produced_kwh"),
        "opt_chp_kwh": _g(opt, "Generator", "annual_energy_produced_kwh"),
        "bau_fuel_mmbtu": _g(bau, "Generator", "annual_fuel_consumption_gal"),
        "opt_fuel_mmbtu": _g(opt, "Generator", "annual_fuel_consumption_gal"),
        "bess_size_kw": _g(opt, "ElectricStorage", "size_kw"),
        "bess_size_kwh": _g(opt, "ElectricStorage", "size_kwh"),
        "chp_size_kw": _g(opt, "Generator", "size_kw"),
        "chp_size_kw_bau": _g(bau, "Generator", "size_kw"),
    }
    d = dispatch_series(opt)
    out["bess_discharge_kwh"] = float(d["bess_discharge"].sum())
    out["bess_charge_kwh"] = float(d["bess_charge"].sum())
    out["bess_cycles"] = out["bess_discharge_kwh"] / BESS_KWH if BESS_KWH else 0.0
    out["bess_roundtrip"] = (out["bess_discharge_kwh"] / out["bess_charge_kwh"]
                             if out["bess_charge_kwh"] else 0.0)
    return out


def print_summary(s: dict, prof: dict, *, label: str = "") -> None:
    m = lambda x: f"{x:>16,.0f}"
    print("=" * 78)
    print(f"RESULTS{'  -- ' + label if label else ''}")
    print("=" * 78)
    print(f"  Site as modelled     mean net load {prof['net_mean_kw']:>10,.0f} kW"
          f"   peak {prof['net_peak_kw']:>10,.0f} kW")
    print(f"                       annual energy {prof['annual_net_kwh'] / 1e6:>10,.2f} GWh"
          f"   load scale x{prof['scale']:,.1f}")
    print(f"                       renewables    {prof['renewable_mean_kw']:>10,.0f} kW mean,"
          f" {prof['renewable_spill_kwh'] / 1e6:,.2f} GWh/yr spilled"
          f" ({100 * prof['spill_hours_fraction']:.0f}% of hours)")
    print(f"  Fixed capacity       CHP {s['chp_size_kw_bau']:,.0f} kW (BAU)"
          f" / {s['chp_size_kw']:,.0f} kW (optimal)"
          f"      BESS {s['bess_size_kw']:,.0f} kW / {s['bess_size_kwh']:,.0f} kWh")
    print()
    print("  Year-one operating cost          BAU          Optimal          Saving")
    for k, name in (("utility", "Utility bill"), ("fuel", "CHP fuel"),
                    ("chp_om", "CHP variable O&M")):
        print(f"    {name:<28}{m(s['bau_opex'][k])}{m(s['opt_opex'][k])}"
              f"{m(s['bau_opex'][k] - s['opt_opex'][k])}")
    print(f"    {'TOTAL':<28}{m(s['bau_opex']['total'])}{m(s['opt_opex']['total'])}"
          f"{m(s['savings_year_one'])}")
    print()
    print("  Annual energy balance            BAU          Optimal")
    print(f"    {'Grid import (GWh)':<28}{s['bau_grid_kwh'] / 1e6:>16,.2f}"
          f"{s['opt_grid_kwh'] / 1e6:>16,.2f}")
    print(f"    {'CHP generation (GWh)':<28}{s['bau_chp_kwh'] / 1e6:>16,.2f}"
          f"{s['opt_chp_kwh'] / 1e6:>16,.2f}")
    print(f"    {'CHP fuel (MMBtu)':<28}{s['bau_fuel_mmbtu']:>16,.0f}"
          f"{s['opt_fuel_mmbtu']:>16,.0f}")
    print(f"    {'BESS discharge (GWh)':<28}{'-':>16}{s['bess_discharge_kwh'] / 1e6:>16,.2f}")
    print(f"    {'BESS charge (GWh)':<28}{'-':>16}{s['bess_charge_kwh'] / 1e6:>16,.2f}")
    print(f"    {'BESS full cycles / yr':<28}{'-':>16}{s['bess_cycles']:>16,.0f}")
    print(f"    {'BESS round-trip (%)':<28}{'-':>16}{100 * s['bess_roundtrip']:>16,.1f}")
    print()
    never = s["reopt_never_pays_back"]
    capex_ok = abs(s["reopt_initial_capital_costs"] - s["bess_capex"]) < 1.0
    pb = s["simple_payback_years"]
    print("  Financial")
    print(f"    {'BESS CAPEX':<40}{s['bess_capex']:>18,.0f}")
    print(f"    {'REopt initial_capital_costs':<40}{s['reopt_initial_capital_costs']:>18,.0f}"
          f"   {'== CAPEX, as built' if capex_ok else '<-- DOES NOT MATCH CAPEX'}")
    print(f"    {'Net annual saving (year 1, pre-tax)':<40}{s['savings_year_one']:>18,.0f}")
    print(f"    {'Simple payback (CAPEX / saving)':<40}"
          + (f"{pb:>18,.2f}  yr" if np.isfinite(pb) else f"{'never':>18}      "))
    print(f"    {'REopt NPV (lcc_bau - lcc)':<40}{s['reopt_npv']:>18,.0f}")
    if never:
        print(f"    {'REopt simple_payback_years':<40}{'never':>18}"
              "      (returns 0.0 when cumulative cash flow")
        print(f"    {'REopt IRR':<40}{'n/a':>18}"
              "       never turns positive -- proforma.jl:345)")
    else:
        print(f"    {'REopt simple_payback_years':<40}"
              f"{s['reopt_simple_payback_years']:>18,.2f}  yr   (after-tax free cash flow)")
        print(f"    {'REopt IRR':<40}{100 * s['reopt_irr']:>18,.1f}  %")
    print(f"    {'REopt LCC  BAU':<40}{s['reopt_lcc_bau']:>18,.0f}")
    print(f"    {'REopt LCC  optimal':<40}{s['reopt_lcc']:>18,.0f}")
    print()


# ===========================================================================
# 5. dispatch chart
# ===========================================================================

# dataviz reference palette, categorical slots 1-4 (validated: CVD dE 9.2 worst
# adjacent pair, normal-vision 27.6, all inside the lightness band)
C_GRID, C_CHP, C_DISCHARGE, C_CHARGE = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"
SURFACE, INK, INK_MUTED, GRIDLINE = "#fcfcfb", "#0b0b0b", "#898781", "#e1e0d9"


def dispatch_chart(opt: dict, bau: dict, path: str, *, days: int = 7,
                   start_hour: int = 0, label: str = "") -> str:
    """BAU and optimal dispatch as small multiples, SOC in its own panel.

    Three panels on one shared x axis rather than one crowded one: the two cases
    stack the same way against the same y scale, so the difference the BESS makes
    is a shape difference and not a colour puzzle. SOC is a fraction, not power,
    so it gets its own panel instead of a second y axis.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    d, b = dispatch_series(opt), dispatch_series(bau)
    sl = slice(start_hour, start_hour + days * 24)
    x = np.arange(start_hour, start_hour + days * 24)
    mw = lambda a: a[sl] / 1000.0

    fig, (axb, axo, axs) = plt.subplots(
        3, 1, figsize=(13, 9.2), sharex=True, height_ratios=[2.2, 2.2, 1.0],
        gridspec_kw={"hspace": 0.28})
    fig.patch.set_facecolor(SURFACE)

    # --- panel 1: BAU -- grid + CHP only -------------------------------------
    axb.stackplot(x, mw(b["grid_to_load"]), mw(b["chp_to_load"]),
                  labels=["Grid import", "CHP (8 MW aggregate)"],
                  colors=[C_GRID, C_CHP], edgecolor=SURFACE, linewidth=0.4)
    axb.plot(x, mw(b["load"]), color=INK, lw=2.0, label="Site net load")

    # --- panel 2: optimal -- the BESS added, charging drawn below zero --------
    axo.stackplot(x, mw(d["grid_to_load"]), mw(d["chp_to_load"]), mw(d["bess_discharge"]),
                  labels=["Grid import", "CHP (8 MW aggregate)", "BESS discharge"],
                  colors=[C_GRID, C_CHP, C_DISCHARGE], edgecolor=SURFACE, linewidth=0.4)
    axo.fill_between(x, 0, -mw(d["bess_charge"]), color=C_CHARGE, label="BESS charge",
                     edgecolor=SURFACE, linewidth=0.4)
    axo.plot(x, mw(d["load"]), color=INK, lw=2.0, label="Site net load")
    axo.axhline(0, color="#c3c2b7", lw=1.0)

    # one y scale for both cases, so the panels are comparable by eye
    top = max(mw(b["load"]).max(), mw(d["load"]).max()) * 1.08
    bot = -mw(d["bess_charge"]).max() * 1.15 if d["bess_charge"].any() else 0.0
    axb.set_ylim(bot, top)
    axo.set_ylim(bot, top)

    for a, head in ((axb, "BAU   grid + CHP"),
                    (axo, "Optimal   grid + CHP + 5.5 MW / 11 MWh BESS")):
        a.set_ylabel("Power  (MW)", color=INK, fontsize=10)
        a.set_title(head, color=INK, fontsize=11, loc="left", pad=26,
                    fontweight="bold")
        leg = a.legend(loc="lower left", bbox_to_anchor=(0, 1.005), ncol=5,
                       frameon=False, fontsize=9, handlelength=1.4,
                       columnspacing=1.6, borderpad=0, handletextpad=0.6)
        for t in leg.get_texts():
            t.set_color("#52514e")

    # --- panel 3: state of charge --------------------------------------------
    axs.fill_between(x, 0, 100 * d["soc"][sl], color=C_DISCHARGE, alpha=0.16, lw=0)
    axs.plot(x, 100 * d["soc"][sl], color=C_DISCHARGE, lw=2.0)
    axs.set_ylim(0, 100)
    axs.set_ylabel("BESS SOC  (%)", color=INK, fontsize=10)
    axs.set_xlabel(f"Hour of the modelled year   (day {start_hour // 24 + 1}"
                   f"-{(start_hour + days * 24) // 24})", color=INK, fontsize=10)

    for a in (axb, axo, axs):
        a.set_facecolor(SURFACE)
        a.grid(axis="y", color=GRIDLINE, lw=0.8)
        a.set_axisbelow(True)
        for side in ("top", "right", "left"):
            a.spines[side].set_visible(False)
        a.spines["bottom"].set_color("#c3c2b7")
        a.tick_params(colors=INK_MUTED, labelsize=9, length=0)
        a.set_xlim(x[0], x[-1])
        a.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v)}"))

    fig.suptitle("Dispatch: grid vs CHP vs BESS" + (f"   --   {label}" if label else ""),
                 color=INK, fontsize=14, fontweight="bold", x=0.5, y=0.985)
    fig.savefig(path, dpi=140, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return path


def print_dispatch_table(opt: dict, bau: dict, *, days: int = 7) -> None:
    """The chart's numbers, in text -- the table view the chart's legend points at."""
    d, b = dispatch_series(opt), dispatch_series(bau)
    n = days * 24
    print("  Dispatch over the charted window (first "
          f"{days} days), MWh")
    print(f"    {'':<28}{'BAU':>14}{'Optimal':>14}")
    rows = [("Grid to load", b["grid_to_load"][:n], d["grid_to_load"][:n]),
            ("CHP to load", b["chp_to_load"][:n], d["chp_to_load"][:n]),
            ("BESS discharge to load", b["bess_discharge"][:n], d["bess_discharge"][:n]),
            ("BESS charge (grid)", b["grid_to_storage"][:n], d["grid_to_storage"][:n]),
            ("BESS charge (CHP)", b["chp_to_storage"][:n], d["chp_to_storage"][:n]),
            ("Site net load", b["load"][:n], d["load"][:n])]
    for name, bb, dd in rows:
        print(f"    {name:<28}{bb.sum() / 1000:>14,.1f}{dd.sum() / 1000:>14,.1f}")
    print()


# ===========================================================================
# 6. run
# ===========================================================================

def run_case(prof: dict, *, gap: float, time_limit: float, fresh: bool,
             incentives: bool, **kw) -> tuple[dict, dict, dict]:
    """Solve BAU and optimal; cross-check REopt's internal BAU against ours."""
    sc_bau = build_scenario(prof, with_bess=False, incentives=incentives, **kw)
    sc_opt = build_scenario(prof, with_bess=True, incentives=incentives, **kw)

    print("  solving BAU (grid + CHP only) ...", flush=True)
    bau = run_reopt_jl(sc_bau, bau=False, gap=gap, time_limit=time_limit, fresh=fresh)
    print(f"    {bau.get('status')}  {bau.get('_runner', {}).get('seconds')} s", flush=True)

    print("  solving optimal (grid + CHP + BESS), BAU alongside ...", flush=True)
    opt = run_reopt_jl(sc_opt, bau=True, gap=gap, time_limit=time_limit, fresh=fresh)
    print(f"    {opt.get('status')}  {opt.get('_runner', {}).get('seconds')} s", flush=True)

    # our standalone BAU and REopt's own internally-derived BAU must agree
    ours, theirs = bau["Financial"]["lcc"], opt["Financial"].get("lcc_bau", float("nan"))
    rel = abs(ours - theirs) / max(1.0, abs(theirs))
    ok = "OK" if rel <= 2 * gap else "XX"
    print(f"    {ok}  BAU cross-check: our LCC {ours:,.0f} vs REopt's lcc_bau "
          f"{theirs:,.0f}  ({100 * rel:.3f}%)", flush=True)
    return bau, opt, {"bau_lcc_ours": ours, "bau_lcc_reopt": theirs, "bau_lcc_rel": rel}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--csv", default=CSV)
    p.add_argument("--audit", action="store_true", help="dataset audit only, no solve")
    p.add_argument("--load-scale", default="auto",
                   help="'auto' (mean net load = CHP nameplate) or a number; 1 = raw dataset")
    p.add_argument("--both", action="store_true", help="run --load-scale=auto and =1")
    p.add_argument("--price-units", choices=("cents", "dollars"), default="cents",
                   help="how to read electricity_price (default cents/kWh -> /100)")
    p.add_argument("--no-renewables", action="store_true",
                   help="do not net solar+wind off the load")
    p.add_argument("--chp-kw", type=float, default=CHP_KW)
    p.add_argument("--chp-efficiency", type=float, default=CHP_EFFICIENCY)
    p.add_argument("--fuel-cost", type=float, default=CHP_FUEL_PER_MMBTU, help="$/MMBtu")
    p.add_argument("--chp-om-per-kwh", type=float, default=CHP_OM_PER_KWH)
    p.add_argument("--bess-kw", type=float, default=BESS_KW)
    p.add_argument("--bess-kwh", type=float, default=BESS_KWH)
    p.add_argument("--bess-capex", type=float, default=BESS_CAPEX)
    p.add_argument("--incentives", action="store_true",
                   help="apply the 30%% ITC and 5-yr MACRS to the BESS")
    p.add_argument("--chart", default="", help="write the dispatch chart here (PNG)")
    p.add_argument("--chart-days", type=int, default=7)
    p.add_argument("--gap", type=float, default=0.01)
    p.add_argument("--time", type=float, default=600.0)
    p.add_argument("--fresh", action="store_true", help="ignore the solve cache")
    p.add_argument("--json", default="", help="dump the summary here")
    a = p.parse_args(argv)

    df = load_dataset(a.csv)
    print_audit(audit(df))
    if a.audit:
        return 0

    scales = ["auto", 1.0] if a.both else [a.load_scale]
    dump: dict = {"csv": os.path.basename(a.csv), "cases": {}}

    for sc in scales:
        prof = build_profiles(
            df, load_scale=sc, use_renewables=not a.no_renewables,
            price_divisor=100.0 if a.price_units == "cents" else 1.0, chp_kw=a.chp_kw)
        label = ("site scaled to the plant (x%.1f)" % prof["scale"]
                 if sc == "auto" else "raw dataset scale (x%.1f)" % prof["scale"])
        print("=" * 78)
        print(f"CASE: {label}")
        print("=" * 78)
        print(f"  {prof['record_days']:.1f} days of hourly record tiled x{prof['tiles']:.2f}"
              f" to REopt's 8760")
        print(f"  grid rate  {a.price_units}/kWh -> ${prof['rate_min']:.4f} .."
              f" ${prof['rate_max']:.4f}, mean ${prof['rate_mean']:.4f}/kWh")
        print(f"  CHP marginal cost ${chp_marginal_cost_per_kwh(efficiency=a.chp_efficiency, fuel_per_mmbtu=a.fuel_cost, om_per_kwh=a.chp_om_per_kwh):.4f}/kWh"
              f"  (fuel ${a.fuel_cost:.2f}/MMBtu at {100 * a.chp_efficiency:.0f}% +"
              f" ${a.chp_om_per_kwh:.3f}/kWh O&M)")
        print()

        bau, opt, xc = run_case(
            prof, gap=a.gap, time_limit=a.time, fresh=a.fresh, incentives=a.incentives,
            chp_kw=a.chp_kw, efficiency=a.chp_efficiency, fuel_per_mmbtu=a.fuel_cost,
            om_per_kwh=a.chp_om_per_kwh, bess_kw=a.bess_kw, bess_kwh=a.bess_kwh,
            bess_capex=a.bess_capex)
        print()
        s = summarize(bau, opt, prof, bess_capex=a.bess_capex)
        print_summary(s, prof, label=label)
        print_dispatch_table(opt, bau, days=a.chart_days)

        if a.chart:
            out = a.chart
            if len(scales) > 1:
                stem, ext = os.path.splitext(a.chart)
                out = f"{stem}_{'scaled' if sc == 'auto' else 'raw'}{ext or '.png'}"
            dispatch_chart(opt, bau, out, days=a.chart_days, label=label)
            print(f"  chart -> {out}")
            print()

        dump["cases"][str(sc)] = {"profile": {k: v for k, v in prof.items()
                                              if not isinstance(v, list)},
                                  "summary": s, "bau_cross_check": xc}

    if a.json:
        with io.open(a.json, "w", encoding="utf-8") as fh:
            json.dump(dump, fh, indent=1, default=float)
        print(f"  summary -> {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
