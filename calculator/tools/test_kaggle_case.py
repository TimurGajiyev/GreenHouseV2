"""Checks on the Kaggle -> REopt mapping in ``tools/kaggle_microgrid_case.py``.

No solver. Everything here is about whether the scenario we hand REopt says what
the case description says, and whether the arrays we build out of the CSV are the
arrays we claim to build. The expensive part -- does REopt then solve it -- is the
script's own BAU cross-check.

Four groups:

  A. the "cut off" rule      the aggregate CHP really is one linear, constant-
                             efficiency, no-commitment generator, and REopt's own
                             size arithmetic pins it at 8 MW in both cases
  B. dataset translation     load/price/renewable mapping, tiling, clipping,
                             and that no energy goes missing in the clip
  C. the money               CAPEX lands on 3.3M exactly; payback is
                             CAPEX / (utility + fuel + O&M saving)
  D. the audit               it calls uniform noise noise, and structured data
                             structured

    python tools/test_kaggle_case.py
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import kaggle_microgrid_case as K

FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'OK' if ok else 'XX'}  {name:<58} {detail}")
    if not ok:
        FAIL.append(name)
    return ok


def close(name: str, got: float, want: float, rtol: float = 1e-9) -> bool:
    ok = abs(got - want) <= rtol * max(1.0, abs(want))
    return check(name, ok, f"{got:>18,.6f} vs {want:>18,.6f}")


# ---------------------------------------------------------------------------
# REopt's own fuel-curve formula, transcribed from REopt/src/core/utils.jl:645
# ---------------------------------------------------------------------------

def reopt_fuel_slope_and_intercept(eff_full: float, eff_half: float, hhv: float):
    burn_full = 1.0 / eff_full
    burn_half = 0.5 / eff_half
    slope_kwht_per_kwhe = (burn_full - burn_half) / (1.0 - 0.5)
    intercept_kwht_per_hr = burn_full - slope_kwht_per_kwhe * 1.0
    return slope_kwht_per_kwhe / hhv, intercept_kwht_per_hr / hhv


def small_profile(**kw) -> dict:
    """A tiny deterministic stand-in for the CSV, so the maths is checkable by hand."""
    n = 48
    ts = pd.date_range("2023-01-01", periods=n, freq="1h")
    df = pd.DataFrame({
        "timestamp": ts,
        "load_demand": np.linspace(100.0, 800.0, n),
        "electricity_price": np.linspace(3.0, 12.0, n),
        "solar_power_output": np.full(n, 200.0),
        "wind_power_output": np.full(n, 100.0),
    })
    return K.build_profiles(df, **kw)


# ===========================================================================
print("A. the cut-off rule -- two CHPs collapsed to one standard REopt Generator")
# ===========================================================================
prof = small_profile(load_scale=1.0)
sc = K.build_scenario(prof, with_bess=True)
g = sc["Generator"]

check("no CHP object at all (thermal side cut out)", "CHP" not in sc)
check("no heating loads in the scenario",
      not any(k in sc for k in ("SpaceHeatingLoad", "DomesticHotWaterLoad", "ExistingBoiler")))
check("generator runs outside outages", g["only_runs_during_grid_outage"] is False)
check("half-load efficiency == full-load efficiency",
      g["electric_efficiency_half_load"] == g["electric_efficiency_full_load"],
      f"{g['electric_efficiency_full_load']}")

# the point of that equality: REopt's own formula must return a zero intercept
slope, intercept = reopt_fuel_slope_and_intercept(
    g["electric_efficiency_full_load"], g["electric_efficiency_half_load"],
    g["fuel_higher_heating_value_kwh_per_gal"])
close("REopt fuel curve intercept (no-load fuel burn)", intercept, 0.0, rtol=1e-12)
close("REopt fuel slope == 1/(eff*HHV) MMBtu/kWh", slope,
      1.0 / (K.CHP_EFFICIENCY * K.KWH_PER_MMBTU))

check("no turn-down constraint", g["min_turn_down_fraction"] == 0.0)
check("no hourly-O&M term (keeps binGenIsOnInTS cost-free)",
      g["om_cost_per_hr_per_kw_rated"] == 0.0)

# REopt/src/core/reopt_inputs.jl:724-725 -- min and max both land on 8 MW
min_size = g["existing_kw"] + g["min_kw"]
max_size = g["existing_kw"] + g["max_kw"]
close("REopt min_sizes[Generator] = existing + min_kw", min_size, K.CHP_KW)
close("REopt max_sizes[Generator] = existing + max_kw", max_size, K.CHP_KW)
check("plant is fixed, not sized", min_size == max_size == K.CHP_KW, f"{K.CHP_KW:,.0f} kW")
check("no capital cost for the existing plant",
      g.get("installed_cost_per_kw", 0.0) == 0.0 and g["replace_cost_per_kw"] == 0.0)

# 1 REopt "gallon" == 1 MMBtu
close("fuel HHV set to kWh per MMBtu", g["fuel_higher_heating_value_kwh_per_gal"],
      K.KWH_PER_MMBTU)
close("so fuel_cost_per_gallon reads as $/MMBtu", g["fuel_cost_per_gallon"],
      K.CHP_FUEL_PER_MMBTU)
close("CHP marginal cost $/kWh", K.chp_marginal_cost_per_kwh(),
      K.CHP_FUEL_PER_MMBTU / (K.KWH_PER_MMBTU * K.CHP_EFFICIENCY) + K.CHP_OM_PER_KWH)

# the BAU scenario is the same generator with the battery taken away
sb = K.build_scenario(prof, with_bess=False)
check("BAU generator identical to optimal generator", sb["Generator"] == g)
check("BAU has no storage capacity",
      sb["ElectricStorage"]["max_kw"] == 0.0 and sb["ElectricStorage"]["max_kwh"] == 0.0)
print()

# ===========================================================================
print("B. dataset translation -- CSV columns to REopt arrays")
# ===========================================================================
loads = np.asarray(prof["loads_kw"])
rates = np.asarray(prof["rates_per_kwh"])
check("ElectricLoad.loads_kw has 8760 values", len(loads) == K.HOURS, f"{len(loads)}")
check("tou_energy_rates_per_kwh has 8760 values", len(rates) == K.HOURS, f"{len(rates)}")
check("no negative loads reach REopt", bool((loads >= 0).all()),
      f"min {loads.min():,.3f} kW")
check("load year matches the data", sc["ElectricLoad"]["year"] == K.DATA_YEAR)
check("load is flagged net of on-site generation", sc["ElectricLoad"]["loads_kw_is_net"])
check("price goes in as an energy rate, not a URDB label",
      "tou_energy_rates_per_kwh" in sc["ElectricTariff"] and
      "urdb_label" not in sc["ElectricTariff"])

# cents -> dollars
p_c = small_profile(load_scale=1.0, price_divisor=100.0)
p_d = small_profile(load_scale=1.0, price_divisor=1.0)
close("cents/kWh divided by 100", p_c["rate_mean"] * 100.0, p_d["rate_mean"])
close("rate mean == mean of the price column / 100", p_c["rate_mean"],
      float(np.linspace(3.0, 12.0, 48).mean()) / 100.0, rtol=1e-9)

# net-load subtraction, clipping and the energy it spills
gross = np.linspace(100.0, 800.0, 48)
renew = np.full(48, 300.0)
want_net = np.maximum(gross - renew, 0.0)
close("net load = clip(load - solar - wind, 0), mean", p_c["net_mean_kw"],
      float(want_net.mean()))
close("peak net load", p_c["net_peak_kw"], float(want_net.max()))
spill_h = float(np.maximum(renew - gross, 0.0).sum())
close("spilled renewable energy is counted, not dropped",
      p_c["renewable_spill_kwh"], spill_h * K.HOURS / 48)
close("renewables used + spilled == renewables generated",
      p_c["renewable_used_kwh"] + p_c["renewable_spill_kwh"],
      float(renew.sum()) * K.HOURS / 48)

p_no = small_profile(load_scale=1.0, use_renewables=False)
close("--no-renewables leaves the gross load alone", p_no["net_mean_kw"],
      float(gross.mean()))
close("and spills nothing", p_no["renewable_spill_kwh"], 0.0)

# tiling a short record up to a REopt year
rec = prof["record_hours"]
check("record is tiled, not padded", bool((loads[:rec] == loads[rec:2 * rec]).all()),
      f"{rec} h x {prof['tiles']:.1f}")
close("tile count", prof["tiles"], K.HOURS / rec)
close("annual energy == mean net load x 8760", prof["annual_net_kwh"],
      prof["net_mean_kw"] * K.HOURS)

# scaling
p2 = small_profile(load_scale=2.0)
close("load scale multiplies the net load", p2["net_mean_kw"], 2.0 * p_c["net_mean_kw"])
close("load scale does not touch the price", p2["rate_mean"], p_c["rate_mean"])
p_auto = small_profile(load_scale="auto", chp_kw=K.CHP_KW)
close("'auto' puts the mean net load on the CHP nameplate",
      p_auto["net_mean_kw"], K.CHP_KW, rtol=1e-9)
print()

# ===========================================================================
print("C. the money -- CAPEX, savings, payback")
# ===========================================================================
b = sc["ElectricStorage"]
close("BESS power fixed at 5.5 MW", b["min_kw"], K.BESS_KW)
check("min_kw == max_kw (size is given, not optimised)", b["min_kw"] == b["max_kw"])
close("BESS energy fixed at 11 MWh", b["min_kwh"], K.BESS_KWH)
check("min_kwh == max_kwh", b["min_kwh"] == b["max_kwh"])
close("cost per kWh x 11 MWh == the $3.3M CAPEX",
      b["installed_cost_per_kwh"] * b["max_kwh"], K.BESS_CAPEX)
close("no cost on the power side, so CAPEX is exactly the stated number",
      b["installed_cost_per_kw"] * b["max_kw"], 0.0)
check("no replacement cost inflating the CAPEX",
      b["replace_cost_per_kw"] == 0.0 and b["replace_cost_per_kwh"] == 0.0
      and b["replace_cost_constant"] == 0.0)
# REopt's default installed_cost_constant is 222,115 (electric_storage.jl:181);
# left in, initial_capital_costs comes out at 3,522,115 rather than 3,300,000.
check("REopt's flat $222,115 battery adder is zeroed out",
      b["installed_cost_constant"] == 0.0)
close("total BESS capex REopt will report",
      b["installed_cost_per_kw"] * b["max_kw"]
      + b["installed_cost_per_kwh"] * b["max_kwh"] + b["installed_cost_constant"],
      K.BESS_CAPEX)
check("grid charging allowed (arbitrage needs it)", b["can_grid_charge"] is True)
check("headline run takes no ITC and no MACRS",
      b["total_itc_fraction"] == 0.0 and b["macrs_option_years"] == 0)
bi = K.build_scenario(prof, with_bess=True, incentives=True)["ElectricStorage"]
check("--incentives turns on the 30% ITC and 5-yr MACRS",
      bi["total_itc_fraction"] == 0.30 and bi["macrs_option_years"] == 5)

# the payback definition, on results shaped like REopt's
fake_bau = {"ElectricTariff": {"year_one_bill_before_tax": 5_000_000.0},
            "Generator": {"year_one_fuel_cost_before_tax": 2_000_000.0,
                          "year_one_variable_om_cost_before_tax": 300_000.0,
                          "year_one_fixed_om_cost_before_tax": 0.0},
            "Financial": {}}
fake_opt = {"ElectricTariff": {"year_one_bill_before_tax": 4_400_000.0},
            "Generator": {"year_one_fuel_cost_before_tax": 1_850_000.0,
                          "year_one_variable_om_cost_before_tax": 290_000.0,
                          "year_one_fixed_om_cost_before_tax": 0.0},
            "Financial": {"npv": 1.0, "simple_payback_years": 2.0,
                          "internal_rate_of_return": 0.1}}
s = K.summarize(fake_bau, fake_opt, prof)
close("year-one cost = utility + fuel + CHP O&M", s["bau_opex"]["total"], 7_300_000.0)
close("net saving = utility saving + fuel saving + O&M saving",
      s["savings_year_one"],
      s["savings_utility"] + s["savings_fuel"] + s["savings_chp_om"])
close("net saving", s["savings_year_one"], 760_000.0)
close("simple payback = $3.3M / saving", s["simple_payback_years"],
      K.BESS_CAPEX / 760_000.0)

zero = {k: dict(v) for k, v in fake_opt.items()}
zero["ElectricTariff"] = {"year_one_bill_before_tax": 5_000_000.0}
zero["Generator"] = dict(fake_bau["Generator"])
check("no saving -> payback is infinite, not a divide-by-zero",
      K.summarize(fake_bau, zero, prof)["simple_payback_years"] == float("inf"))

# REopt returns early from its proforma when the system never pays back, leaving
# simple_payback_years at its initialised 0.0 (results/proforma.jl:345). Read
# literally that is "pays back instantly"; it means the opposite.
check("REopt payback of 0.0 is read as 'never', not as zero years",
      K.summarize(fake_bau, {**fake_opt, "Financial": {"npv": -1.0,
                                                       "simple_payback_years": 0.0,
                                                       "internal_rate_of_return": 0.0}},
                  prof)["reopt_never_pays_back"] is True)
check("a real REopt payback is not flagged as 'never'",
      K.summarize(fake_bau, fake_opt, prof)["reopt_never_pays_back"] is False,
      f"{fake_opt['Financial']['simple_payback_years']} yr")
print()

# ===========================================================================
print("D. the audit -- does it tell noise from structure?")
# ===========================================================================
rng = np.random.default_rng(0)
n = 96
ts = pd.date_range("2023-01-01", periods=n, freq="1h")
hour = ts.hour.to_numpy()

noise = pd.DataFrame({
    "timestamp": ts, "hour_of_day": hour,
    "load_demand": rng.uniform(100, 800, n),
    "electricity_price": rng.uniform(3, 12, n),
    "solar_power_output": rng.uniform(0, 500, n),
    "wind_power_output": rng.uniform(0, 300, n),
    "solar_irradiance": rng.uniform(0, 1000, n),
    "wind_speed": rng.uniform(0, 20, n),
    "cloud_cover": rng.uniform(0, 100, n),
    "temperature": rng.uniform(15, 45, n),
})
bell = np.clip(np.sin((hour - 6) / 12 * np.pi), 0, None)
real = noise.copy()
real["solar_irradiance"] = 1000 * bell
real["solar_power_output"] = np.clip(0.5 * real["solar_irradiance"] + rng.normal(0, 5, n), 0, None)

a_noise, a_real = K.audit(noise), K.audit(real)
check("noise: solar at noon ~= solar at night",
      abs(a_noise["solar_noon_over_night"] - 1.0) < 0.5,
      f"{a_noise['solar_noon_over_night']:.2f}x")
check("structured: solar at noon >> solar at night",
      a_real["solar_noon_over_night"] > 5,
      f"{a_real['solar_noon_over_night']:.2f}x"
      + ("  (night output is zero)" if a_real["solar_noon_over_night"] == float("inf") else ""))
r_noise = a_noise["correlations"]["solar_irradiance ~ solar_power_output"]
r_real = a_real["correlations"]["solar_irradiance ~ solar_power_output"]
check("noise: irradiance does not explain solar", abs(r_noise) < 0.3, f"r = {r_noise:+.3f}")
check("structured: irradiance explains solar", r_real > 0.9, f"r = {r_real:+.3f}")

for c, v in a_noise["uniform_fingerprint"].items():
    close(f"noise fingerprint {c}: std vs (b-a)/sqrt(12)", v["std"], v["std_if_uniform"],
          rtol=0.25)

real_csv = K.load_dataset() if os.path.exists(K.CSV) else None
if real_csv is not None:
    a = K.audit(real_csv)
    check("the shipped CSV is regular and complete", a["regular"] and a["nans"] == 0)
    check("the shipped CSV has no diurnal solar cycle",
          abs(a["solar_noon_over_night"] - 1.0) < 0.2,
          f"{a['solar_noon_over_night']:.2f}x")
    for k, v in a["identities_max_abs_residual"].items():
        check(f"identity holds exactly: {k}", v < 1e-6, f"max |resid| {v:.2e}")
print()

# ===========================================================================
print("E. the chart renders")
# ===========================================================================
import tempfile

rng2 = np.random.default_rng(1)
h = K.HOURS
mk = lambda lo, hi: rng2.uniform(lo, hi, h).tolist()
res_opt = {"ElectricUtility": {"electric_to_load_series_kw": mk(0, 6000),
                               "electric_to_storage_series_kw": mk(0, 2000)},
           "Generator": {"electric_to_load_series_kw": mk(0, 8000),
                         "electric_to_storage_series_kw": mk(0, 500)},
           "ElectricStorage": {"storage_to_load_series_kw": mk(0, 5500),
                               "soc_series_fraction": mk(0.2, 1.0)}}
res_bau = {"ElectricUtility": {"electric_to_load_series_kw": mk(0, 6000)},
           "Generator": {"electric_to_load_series_kw": mk(0, 8000)}}
with tempfile.TemporaryDirectory() as td:
    p = K.dispatch_chart(res_opt, res_bau, os.path.join(td, "c.png"), days=7,
                         label="test")
    check("dispatch chart writes a non-trivial PNG", os.path.getsize(p) > 20_000,
          f"{os.path.getsize(p):,} bytes")

d = K.dispatch_series(res_opt)
close("charge series = grid-to-storage + CHP-to-storage",
      float(d["bess_charge"].sum()),
      float(d["grid_to_storage"].sum() + d["chp_to_storage"].sum()))
close("load series = grid + CHP + discharge, all to load",
      float(d["load"].sum()),
      float(d["grid_to_load"].sum() + d["chp_to_load"].sum() + d["bess_discharge"].sum()))
missing = K.dispatch_series({"Generator": {}})
check("a BAU result with no storage keys gives zeros, not a crash",
      float(missing["bess_discharge"].sum()) == 0.0 and len(missing["soc"]) == K.HOURS)
print()

print("=" * 78)
if FAIL:
    print(f"{len(FAIL)} FAILED")
    for f in FAIL:
        print(f"  - {f}")
else:
    print("all checks passed")
print("=" * 78)
raise SystemExit(1 if FAIL else 0)
