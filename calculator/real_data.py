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

A third source, ALL3, pools all three engines on the hours both plants are
measured: an assumption of one bus that the meters do not show, labelled so.

This module hands the study the measured days of one site, and nothing else:

  * the period is the whole table, every hour the data covers. It is longer
    than a year, so a calendar date can be in it twice (Жаркент 3 has
    September and early October of 2025 and of 2026); the period the plant's
    own meters cover is reported with it;
  * where a logger missed one of engine and grid, build.py / combine.py
    rebuilt it from the same hour's balance (engine = plant - grid, grid =
    plant - engine). That reading is kept, and flagged: column "rebuilt" and
    one "rebuilt <series>" column per series. It is arithmetic on two meters
    of the same hour, not a value from another hour, and dropping it would be
    a bias, not a precaution -- the J320 loggers mostly stop writing the
    engine's output when the engine stops, so the hours without it are the
    outages (REPORT.md Part 18);
  * a day is any 24 consecutive hours measured in full (combine.py's
    *_complete columns), not only midnight to midnight. Each unbroken run of
    complete hours gives as many such days as it holds, starting as near
    midnight as the run allows, so a run that has room for calendar days
    keeps them as calendar days. The optimiser solves a day as a 24-hour
    cycle -- a battery ending where it started, a start priced, minimum up
    and down times -- so a run shorter than 24 hours, and what a longer run
    has over its last whole day, is left out. Nothing is interpolated or
    copied from another hour;
  * the kept days are laid end to end, with their own timestamps. A figure
    "per year" is weighted by calendar month; a month with no kept day is
    not filled, and the year becomes a range (year_study.month_range).

The table is local data and is not in the repository; with it absent,
available() is empty and the study offers no real-data source.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import passports as PP

DATA = Path(__file__).resolve().parent.parent / "real_data" / "zharkent" / "data"
TABLE = DATA / "zharkent_all_hourly.csv"

# Nameplate and electrical efficiency at 100 % / 50 % load, read off the OEM
# documents in docs/equipment (passports.py names each one and its section)
J320 = PP.unit("JMC 320")
QUANTO_1200 = PP.unit("Quanto 1200")

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


# All three engines as one pool. The meters say these are two plants
# (combine.py: Жаркент 3 does not correlate with ЖКПЗ at any shift, and each
# has its own city meter), so a pool assumes a common bus nothing measured. It
# is offered because it was asked for, and its label and source say so. The
# join is tools/battery_real_data.py's "combined" case, hour for hour: the
# CR06 logger keeps UTC+5 while the CC42 logger and the dashboard keep UTC+6,
# so Жаркент 3 moves +1 h; an hour counts only when both plants measured it in
# full; load, purchase and export are each plant's own, added. A purchase is
# never netted against the other plant's export -- the city was paid for it.
ALL3 = "All three · TEDOM + J320 (Жаркент 2) + J320 (Жаркент 3)"
POOL = (ZHKPZ, SITE3)
SHIFT = {SITE3: pd.Timedelta(hours=1)}       # CR06 UTC+5 -> UTC+6, pooled only


def units(site: str) -> list:
    """(name, kW, efficiency at 100 %, at 50 %) for each engine of the site."""
    if site == ALL3:
        return [u for s in POOL for u in SITES[s][4]]
    return SITES[site][4]


def source(site: str) -> str:
    """Where the site's hours come from, in words."""
    if site == ALL3:
        return (" + ".join(SITES[s][5] for s in POOL)
                + "; Жаркент 3 moved +1 h (CR06 keeps UTC+5); the two plants added "
                  "as if on one bus, which their meters do not show")
    return SITES[site][5]


def available() -> list[str]:
    """The plants the table covers, when the table is on disk, then the pool."""
    return list(SITES) + [ALL3] if TABLE.exists() else []


def stamp() -> float:
    """When the table was last written: a cache key, so a rebuilt table is read again."""
    return TABLE.stat().st_mtime if TABLE.exists() else 0.0


def _table() -> pd.DataFrame:
    return pd.read_csv(TABLE, index_col=0, parse_dates=True)


# A reading the logger missed, rebuilt by build.py / combine.py from the
# plant's balance in the same hour: the column, and the column that flags it
FROM_BALANCE = {"j320_2_kw": "j320_2_from_balance", "zhkpz_import_kw": "import_2_from_balance",
                "j320_3_kw": "j320_3_from_balance", "site3_import_kw": "import_3_from_balance"}


def _plant(t: pd.DataFrame, site: str, shift: bool = False) -> pd.DataFrame:
    """One metered plant in the module's own columns, on its own clock or the pool's."""
    plant, grid, engines, complete, plant_units, _ = SITES[site]

    def rebuilt(col: str) -> pd.Series:
        if col not in FROM_BALANCE:
            return pd.Series(False, index=t.index)
        return t[FROM_BALANCE[col]].fillna(False).astype(bool)

    # a plant reading of a few kW below zero is meter noise; demand is not negative
    out = pd.DataFrame({"load": t[plant].clip(lower=0), "grid": t[grid],
                        "buy": t[grid].clip(lower=0), "sell": (-t[grid]).clip(lower=0)},
                       index=t.index)
    for (name, *_), col in zip(plant_units, engines):
        out[name] = t[col]
    out["complete"] = t[complete].astype(bool)
    out["rebuilt grid"] = rebuilt(grid)
    for (name, *_), col in zip(plant_units, engines):
        out[f"rebuilt {name}"] = rebuilt(col)
    out["rebuilt"] = out.filter(like="rebuilt ").any(axis=1)
    if shift and site in SHIFT:
        out.index = out.index + SHIFT[site]
    return out


def _site(site: str) -> pd.DataFrame:
    """Every hour of a site: load, grid (net), buy, sell, one column per engine,
    complete, and the rebuilt flags (any, grid, per engine).

    A NaN is a reading nobody took; sums keep it NaN, so a pooled hour with
    either plant unmeasured is unmeasured.
    """
    t = _table()
    if site != ALL3:
        return _plant(t, site)
    parts = [_plant(t, s, shift=True) for s in POOL]
    idx = parts[0].index.union(parts[1].index)
    a, b = (p.reindex(idx) for p in parts)
    out = pd.DataFrame({c: a[c] + b[c] for c in ("load", "grid", "buy", "sell")}, index=idx)
    pooled = ["load", "grid", "buy", "sell", "complete", "rebuilt grid", "rebuilt"]
    for p in (a, b):
        for name in p.columns.drop(pooled):
            out[name] = p[name].eq(True) if name.startswith("rebuilt ") else p[name]
    out["complete"] = a["complete"].eq(True) & b["complete"].eq(True)
    for c in ("rebuilt grid", "rebuilt"):
        out[c] = a[c].eq(True) | b[c].eq(True)
    return out


def hours(site: str) -> pd.DataFrame:
    """Every hour of the table for one site, exactly as the meters gave it.

    Columns: load (the plant, kW), grid (the city meter, minus = sent to the
    city), buy and sell (what was bought from and sent to the city), one
    column per engine named as in the units list, complete (every one of
    them measured), rebuilt (any of them rebuilt from the hour's balance) and
    "rebuilt grid" / "rebuilt <engine>" (which). An hour a meter did not
    report is NaN in that column and stays NaN: unlike year(), no day is
    dropped and nothing is laid end to end, so the gaps are where they were.
    """
    return _site(site)


def days(complete: pd.Series) -> pd.Series:
    """The hours year() keeps: 24-hour days cut from the runs of complete hours.

    A run of L complete hours holds L // 24 days and L % 24 hours to spare.
    The spare hours go where they put the first day's start nearest midnight,
    so a run with room for calendar days keeps calendar days."""
    ok = complete.eq(True).to_numpy()
    keep = [False] * len(ok)
    i = 0
    while i < len(ok):
        if not ok[i]:
            i += 1
            continue
        j = i
        while j < len(ok) and ok[j]:
            j += 1
        h0 = complete.index[i].hour
        off = min(range((j - i) % 24 + 1),
                  key=lambda o: min((h0 + o) % 24, 24 - (h0 + o) % 24))
        for x in range(i + off, i + off + 24 * ((j - i) // 24)):
            keep[x] = True
        i = j
    return pd.Series(keep, index=complete.index)


def year(site: str) -> dict:
    """The measured days of a site over the whole period, end to end.

    A day is 24 consecutive hours measured in full (``days``). Returns load
    (plant, kW), gpu, grid, buy and sell (kW, as measured), each engine's own
    output (gpu_units, in the order of the units list), the timestamps, the
    days kept and how many of them do not start at midnight (off_midnight),
    the period the meters cover (first and last hour on which all of them
    report) with its length in calendar days, how many calendar dates the
    kept days start on twice, and how many kept hours carry a reading rebuilt
    from the balance (rebuilt_hours; per series in rebuilt).
    """
    t = _site(site)
    names = [u[0] for u in units(site)]
    ok = t["complete"].eq(True)
    k = t[days(ok)]
    span = t.index[ok]
    starts = k.index[::24]
    gpu = sum(k[c] for c in names)
    return {"load": [float(x) for x in k["load"]],
            "gpu": [float(x) for x in gpu], "grid": [float(x) for x in k["grid"]],
            "buy": [float(x) for x in k["buy"]], "sell": [float(x) for x in k["sell"]],
            "gpu_units": [[float(x) for x in k[c]] for c in names],
            "time": list(k.index), "units": units(site), "source": source(site),
            "days": len(starts),
            "off_midnight": int((starts.hour != 0).sum()),
            "period": (span[0], span[-1]),
            "days_period": (span[-1].floor("D") - span[0].floor("D")).days + 1,
            "repeat": int(pd.Series(starts.strftime("%m-%d")).duplicated().sum()),
            "hours": len(k),
            "rebuilt_hours": int(k["rebuilt"].eq(True).sum()),
            "rebuilt": {c: int(k[f"rebuilt {c}"].eq(True).sum()) for c in ("grid", *names)}}
