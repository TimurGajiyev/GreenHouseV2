"""Measured hourly load from the Zharkent engine loggers, as a study input.

real_data/zharkent/build.py turns the Jenbacher logger exports into one hourly
CSV per station (plant, gpu, grid in kW: the mean of the logger's own samples
in each clock hour). This module reads those CSVs and hands the dispatch study
the measured days, and nothing else:

  * the period is 1 Oct 2025 00:00 - 30 Sep 2026 23:00. It is the one stretch
    both loggers cover end to end, and it leaves out September 2025 --
    commissioning on CR06, a run of impossible plant readings on CC42;
  * a day is kept only if every one of its 24 hours has a plant reading and
    an engine or grid reading. Nothing is interpolated or copied from another
    day: a day with a hole in it is left out whole;
  * where one of engine and grid is missing in a kept hour it is the other
    side of the meter balance, plant = gpu + grid (true within 20 kW on
    87-94 % of the hours where all three were logged);
  * the kept days are laid end to end. The study annualises by hours, so a
    figure "per year" is the kept days scaled to 8,760 h.

The two stations are separate meters logged in different time zones. "Both
units together" moves CR06 (UTC+5) onto CC42's clock (UTC+6) and keeps only
the days both loggers recorded in full.

The CSVs are local data and are not in the repository; with them absent,
available() is empty and the study offers no real-data source.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "real_data" / "zharkent" / "data"
YEAR = ("2025-10-01 00:00", "2026-09-30 23:00")
# Jenbacher JMC 320 (J 320 GS-D25) nameplate, INNIO technical description of
# 04.09.2023, section 0.01: «Электрическая выходная мощность 1067 кВт эл.»
# (docs/equipment). The loggers name the engine type J320 on both stations.
J320_KW = 1067.0

# label shown on the page: (station files, hours to shift onto UTC+6, units)
BOTH = "ГПУ-2 + ГПУ-3 together (CC42 + CR06)"
SITES: dict[str, tuple[tuple[str, ...], tuple[int, ...], list[tuple[str, float]]]] = {
    BOTH: (("GPU2_CC42", "GPU3_CR06"), (0, 1),
           [("Jenbacher J320 (ГПУ-2)", J320_KW), ("Jenbacher J320 (ГПУ-3)", J320_KW)]),
    "ГПУ-2 · Zharkent (CC42)": (("GPU2_CC42",), (0,), [("Jenbacher J320 (ГПУ-2)", J320_KW)]),
    "ГПУ-3 · Zharkent 2 (CR06)": (("GPU3_CR06",), (0,), [("Jenbacher J320 (ГПУ-3)", J320_KW)]),
}


def available() -> list[str]:
    """The sites whose CSVs are on disk."""
    return [k for k, (files, _, _) in SITES.items()
            if all((DATA / f"{f}_hourly.csv").exists() for f in files)]


def _station(name: str, shift_h: int) -> pd.DataFrame:
    h = pd.read_csv(DATA / f"{name}_hourly.csv", index_col=0, parse_dates=True)
    h.index = h.index + pd.Timedelta(hours=shift_h)
    h = h.reindex(pd.date_range(*YEAR, freq="1h"))[["plant", "gpu", "grid"]]
    # the other side of the balance, where only one of the two was logged
    h["grid"] = h.grid.fillna(h.plant - h.gpu)
    h["gpu"] = h.gpu.fillna((h.plant - h.grid).clip(lower=0))
    return h


def year(site: str) -> dict:
    """The fully measured days of a site, end to end.

    Returns load (plant, kW), gpu and grid (kW, as logged), the timestamps,
    the days kept and the days in the period.
    """
    files, shifts, units = SITES[site]
    frames = [_station(f, sh) for f, sh in zip(files, shifts)]
    ok = pd.Series(True, index=frames[0].index)
    for h in frames:
        ok &= h.notna().all(axis=1)
    day = ok.index.floor("D")
    full = ok.groupby(day).transform("all")
    tot = frames[0][full]
    for h in frames[1:]:
        tot = tot + h[full]
    # a plant reading of a few kW below zero is meter noise; demand is not negative
    return {"load": [float(x) for x in tot.plant.clip(lower=0)], "gpu": [float(x) for x in tot.gpu],
            "grid": [float(x) for x in tot.grid], "time": list(tot.index),
            "units": units, "days": int(full.sum() // 24),
            "days_period": int(day.nunique()), "hours": len(tot)}
