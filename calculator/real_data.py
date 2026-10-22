"""Measured hourly load of the Zharkent plants, as a study input.

real_data/zharkent/combine.py builds one hourly table for the three engines,
data/zharkent_all_hourly.csv, from the Jenbacher logger exports (build.py) and
the monitoring dashboard's 5-minute export for station «Жаркент». The meters
say there are two plants:

  ЖКПЗ        fed by TEDOM Quanto 1200 («Жаркент»), Jenbacher J320 («Жаркент 2»,
              logger CC42) and the city:
                  zhkpz_plant = tedom + j320_2 + zhkpz_import
              (the dashboard's ЖКПЗ import is the CC42 logger's grid meter, and
              ЖКПЗ consumption is the TEDOM plus the CC42 plant meter, both
              within ~6 kW on the hours they overlap);
  Жаркент 3   its own plant, fed by Jenbacher J320 (logger CR06) and the city.

This module hands the study the measured days of one plant, and nothing else:

  * the period is 1 Oct 2025 00:00 - 30 Sep 2026 23:00: at most one of each
    calendar day, and September 2025 (commissioning on CR06, impossible plant
    readings on CC42) left out;
  * a day is kept only if every one of its 24 hours is measured in full
    (combine.py's *_complete columns). Nothing is interpolated or copied
    from another day: a day with a hole in it is left out whole;
  * the kept days are laid end to end. The study annualises by hours, so a
    figure "per year" is the kept days scaled to 8,760 h.

The table is local data and is not in the repository; with it absent,
available() is empty and the study offers no real-data source.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "real_data" / "zharkent" / "data"
TABLE = DATA / "zharkent_all_hourly.csv"
YEAR = ("2025-10-01 00:00", "2026-09-30 23:00")

# Nameplate and electrical efficiency at 100 % / 50 % load, from the OEM
# documents in docs/equipment:
#   Jenbacher JMC 320 (J 320 GS-D25), INNIO technical description 04.09.2023,
#     section 0.01: 1 067 kW el., 40,5 % / 39,5 % / 37,4 % at 100 / 75 / 50 %;
#   TEDOM Quanto 1200 NG, TS_Quanto_1200_MWM_NG_OM_SE_C_LB_50Hz_S_500_RU_04_2021:
#     1 200 kW, 43,6 % / 42,4 % / 40,2 % at 100 / 75 / 50 %.
J320 = (1067.0, 40.5, 37.4)
QUANTO_1200 = (1200.0, 43.6, 40.2)

ZHKPZ = "ЖКПЗ · Жаркент (TEDOM) + Жаркент 2 (J320)"
SITE3 = "Жаркент 3 · J320 (CR06)"

# label: (plant column, grid column, engine columns, complete column, units, source)
SITES: dict[str, tuple] = {
    ZHKPZ: ("zhkpz_plant_kw", "zhkpz_import_kw", ("tedom_kw", "j320_2_kw"), "zhkpz_complete",
            [("TEDOM Quanto 1200 (Жаркент)", *QUANTO_1200),
             ("Jenbacher J320 (Жаркент 2)", *J320)],
            "dashboard «Жаркент» (TEDOM, ЖКПЗ import) + Jenbacher logger CC42"),
    SITE3: ("site3_plant_kw", "site3_import_kw", ("j320_3_kw",), "site3_complete",
            [("Jenbacher J320 (Жаркент 3)", *J320)],
            "Jenbacher logger CR06, plant meter"),
}


def _units(site: str) -> list:
    return SITES[site][4]


def available() -> list[str]:
    """The plants the table covers, when the table is on disk."""
    return list(SITES) if TABLE.exists() else []


def _table() -> pd.DataFrame:
    t = pd.read_csv(TABLE, index_col=0, parse_dates=True)
    return t.loc[YEAR[0]:YEAR[1]]


def year(site: str) -> dict:
    """The fully measured days of a plant, end to end.

    Returns load (plant, kW), gpu and grid (kW, as measured), each engine's own
    output (gpu_units, in the order of the units list), the timestamps, the
    days kept and the days in the period.
    """
    plant, grid, engines, complete, units, source = SITES[site]
    t = _table()
    day = t.index.floor("D")
    full = t[complete].astype(bool).groupby(day).transform("all")
    k = t[full]
    gpu = sum(k[c] for c in engines)
    # a plant reading of a few kW below zero is meter noise; demand is not negative
    return {"load": [float(x) for x in k[plant].clip(lower=0)],
            "gpu": [float(x) for x in gpu], "grid": [float(x) for x in k[grid]],
            "gpu_units": [[float(x) for x in k[c]] for c in engines],
            "time": list(k.index), "units": units, "source": source,
            "days": int(full.sum() // 24), "days_period": int(day.nunique()),
            "hours": len(k)}
