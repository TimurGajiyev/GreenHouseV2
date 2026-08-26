"""Exercise every app_periods function against a real solved scenario.

Written after a `%-d` strftime format reached the results page unnoticed: the
form was checked end to end but the results page never was, so a crash there
survived. These are pure-function checks -- no browser, no Streamlit runtime --
so they can run in the ordinary validator sweep.

Two shapes are covered because they take different code paths:
  single  one fuel unit, one battery   -- the REopt web-form shape
  fleet   three fuel units, two batteries
"""

from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from reopt_core import data_sources as ds
from reopt_core import model as M
from reopt_core.tariff import build_tariff

import app_periods as P

LAT, LON = 39.74437, -105.15199
URDB = "5b44ffc75457a36716a907eb"

FAILURES: list[str] = []


def check(name, fn):
    try:
        out = fn()
    except Exception as exc:
        FAILURES.append(f"{name}: {type(exc).__name__}: {exc}")
        print(f"  XX  {name}")
        traceback.print_exc(limit=3)
        return None
    print(f"  OK  {name}")
    return out


def frame_ok(df, name, min_rows=1):
    if df is None:
        FAILURES.append(f"{name}: returned None")
        return
    if not isinstance(df, pd.DataFrame):
        FAILURES.append(f"{name}: not a DataFrame")
        return
    if len(df) < min_rows:
        FAILURES.append(f"{name}: {len(df)} rows, expected >= {min_rows}")
        return
    # every cell must render -- a NaN or a raw Timestamp is a display bug
    for col in df.columns:
        if df[col].isna().any():
            FAILURES.append(f"{name}: NaN in column {col!r}")


def scenario(n_gen: int, n_bat: int, pf, tar):
    load = ds.build_electric_load("Supermarket", 3_000_000.0, LAT, LON)
    gens = [M.FuelTechInputs(
        enabled=True, kind="Generator", name=f"Gen {i + 1}",
        installed_cost_per_kw=800.0, om_cost_per_kw=10.0,
        fuel_cost_per_gallon=2.25, min_kw=0.0, max_kw=400.0)
        for i in range(n_gen)]
    bats = [M.StorageInputs(
        enabled=True, name=f"Battery {i + 1}",
        installed_cost_per_kwh=320.0, installed_cost_per_kw=850.0,
        installed_cost_constant=0.0, max_kwh=1500.0)
        for i in range(n_bat)]
    return load, M.ScenarioInputs(
        loads_kw=load["loads_kw"], tariff=tar,
        financial=M.FinancialInputs(analysis_years=20,
                                    offtaker_discount_rate_fraction=0.075),
        pv=M.PVInputs(enabled=True, installed_cost_per_kw=1850.0,
                      max_kw=1000.0, acres_per_kw=0.006, production_factor=pf),
        storage=bats[0], storages=(bats if n_bat > 1 else None),
        fuel_tech=gens[0], fuel_techs=(gens if n_gen > 1 else None),
        land_acres=6.0, pv_location="ground", compensation_type="no_compensation",
    )


def exercise(tag, res, tar):
    print(f"\n--- {tag} ---")
    series = res["series"]
    load = series["load_kw"]

    rep = check("representative_day", lambda: P.representative_day(load))
    pk = check("peak_day", lambda: P.peak_day(load))
    if rep is None or pk is None:
        return
    if not (0 <= rep < 365 and 0 <= pk < 365):
        FAILURES.append(f"{tag}: day index out of range rep={rep} peak={pk}")

    idx = P._idx()
    # the label that crashed on Windows
    lab = check("_daylabel", lambda: P._daylabel(idx[rep * 24]))
    lab2 = check("_daylabel weekday", lambda: P._daylabel(idx[pk * 24], weekday=True))
    print(f"      representative day = {lab};  peak day = {lab2}")

    hf = check("hourly_frame (rep)", lambda: P.hourly_frame(series, rep))
    frame_ok(hf, f"{tag} hourly_frame", min_rows=25)
    if hf is not None:
        if list(hf["Hour"])[:3] != [1, 2, 3] or list(hf["Hour"])[-1] != "Total":
            FAILURES.append(f"{tag}: hourly_frame must run 1..24 then Total")
        # the hourly load column must add up to the daily total
        day_load = sum(load[rep * 24:(rep + 1) * 24])
        got = float(hf["Load (kW)"].iloc[-1])
        if abs(got - day_load) > 1.0:
            FAILURES.append(f"{tag}: hourly total {got:,.0f} != daily load {day_load:,.0f}")

    check("hourly_frame (peak)", lambda: P.hourly_frame(series, pk))

    pfm = check("period_frame", lambda: P.period_frame(series, tar, rep))
    frame_ok(pfm, f"{tag} period_frame", min_rows=6)
    if pfm is not None:
        cols = list(pfm.columns)
        if cols != ["Metric", "Representative day", "Week", "Year"]:
            FAILURES.append(f"{tag}: period_frame columns {cols}")
        # the Year column must equal the annual totals from the model
        row = pfm[pfm["Metric"] == "Site load (kWh)"]
        if len(row):
            got = float(str(row["Year"].iloc[0]).replace(",", ""))
            if abs(got - sum(load)) > 2.0:
                FAILURES.append(f"{tag}: period_frame year load {got:,.0f} != {sum(load):,.0f}")

    mp = check("monthly_peak_frame", lambda: P.monthly_peak_frame(series))
    frame_ok(mp, f"{tag} monthly_peak_frame", min_rows=13)

    uf = check("unit_frame", lambda: P.unit_frame(res["sizes"]))
    frame_ok(uf, f"{tag} unit_frame")
    sf = check("storage_frame", lambda: P.storage_frame(res["sizes"]))
    frame_ok(sf, f"{tag} storage_frame")

    n_units = len(res["sizes"].get("fueltech_units") or [])
    n_bats = len(res["sizes"].get("storage_units") or [])
    print(f"      {n_units} fuel unit rows, {n_bats} battery rows")
    if uf is not None and len(uf) != n_units:
        FAILURES.append(f"{tag}: unit_frame rows {len(uf)} != {n_units}")
    if sf is not None and len(sf) != n_bats:
        FAILURES.append(f"{tag}: storage_frame rows {len(sf)} != {n_bats}")

    # per-unit series must line up with the aggregate, hour by hour
    per = series.get("fueltech_unit_kw") or {}
    if per:
        agg = series["fueltech_kw"]
        worst = max(abs(sum(v[t] for v in per.values()) - agg[t]) for t in range(8760))
        print(f"      per-unit series vs aggregate: worst hour {worst:.6f} kW")
        if worst > 1e-6:
            FAILURES.append(f"{tag}: per-unit fuel series do not sum to the aggregate")


def main():
    pf, _ = ds.call_pvwatts_api(LAT, LON, tilt=20, azimuth=180, array_type=0,
                                module_type=0, losses=14)
    tar = build_tariff(ds.fetch_urdb_rate(URDB))

    for tag, ng, nb in (("single  1 gen / 1 battery", 1, 1),
                        ("fleet   3 gen / 2 batteries", 3, 2)):
        _, inp = scenario(ng, nb, pf, tar)
        res = M.solve(inp, time_limit=900)
        exercise(tag, res, tar)

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print("  - " + f)
        sys.exit(1)
    print("all period-view checks passed")


if __name__ == "__main__":
    main()
