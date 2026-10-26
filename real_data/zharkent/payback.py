"""Battery payback on the measured Zharkent year, by hand -- no optimiser.

    python real_data/zharkent/payback.py

The engines run exactly as the logger saw them. A battery is added beside them
with one plain rule, hour by hour:

  charge     from what would otherwise be lost or left idle:
               1. power the site sent to the city (grid < 0), unpaid;
               2. the running engine's unused headroom, rated kW - output,
                  paid at the engine's own cost per kWh;
  discharge  into every hour the site buys from the city, up to that purchase.

Each kWh moved is worth: grid price - (engine cost / round-trip efficiency) - wear
(for exported energy the engine cost is already sunk, so only the wear counts).
Payback = CAPEX / annual saving.
"""
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
YEAR = ("2025-10-01 00:00", "2026-09-30 23:00")

# the study page's defaults -- change here
GRID = 60.0            # ₸/kWh bought from the city
GEN = 22.0             # ₸/kWh from the engine (gas)
UNIT_KW = 1067.0       # Jenbacher J320
RUN_KW = 50.0          # above this the engine counts as running
B_KW, B_KWH = 2500.0, 5500.0
RTE, SOC_MIN = 0.88, 0.30
WEAR = 0.5             # ₸ per kWh discharged
CAPEX = 391_000_000.0  # ₸


def site(files):
    tot = None
    for f, shift in files:
        h = pd.read_csv(HERE / "data" / f"{f}_hourly.csv", index_col=0, parse_dates=True)
        h.index = h.index + pd.Timedelta(hours=shift)
        h = h.reindex(pd.date_range(*YEAR, freq="1h"))[["gpu", "grid"]]
        # headroom only on a running engine; a stopped one is not started
        h["room"] = (UNIT_KW - h.gpu).clip(lower=0).where(h.gpu > RUN_KW, 0.0)
        tot = h if tot is None else tot.add(h, fill_value=0)
    return tot.dropna()


def simulate(h):
    eta = RTE ** 0.5
    lo, soc = SOC_MIN * B_KWH, SOC_MIN * B_KWH
    r = dict(free_in=0.0, gen_in=0.0, out=0.0)
    for grid, room in h[["grid", "room"]].itertuples(index=False):
        room_p = B_KW
        if grid < 0:                                 # 1. export: free energy
            e = min(-grid, room_p, (B_KWH - soc) / eta)
            soc += e * eta; r["free_in"] += e; room_p -= e
        if grid <= 0:                                # 2. engine headroom
            e = min(room, room_p, (B_KWH - soc) / eta)
            soc += e * eta; r["gen_in"] += e
        if grid > 0:                                 # discharge into a purchase
            e = min(grid, B_KW, (soc - lo) * eta)
            soc -= e / eta; r["out"] += e
    return r


def main():
    cases = {"ГПУ-2 · Zharkent (CC42)": [("GPU2_CC42", 0)],
             "ГПУ-3 · Zharkent 2 (CR06)": [("GPU3_CR06", 0)],
             "Обе станции суммарно": [("GPU2_CC42", 0), ("GPU3_CR06", 1)]}
    for name, files in cases.items():
        h = site(files)
        r = simulate(h)
        k = 8760 / len(h)                            # a few hours lack data
        saved_grid = r["out"] * GRID
        gen_cost = r["gen_in"] * GEN
        wear = r["out"] * WEAR
        saving = (saved_grid - gen_cost - wear) * k
        print(f"\n{name}  ({len(h):,} hours with data)")
        print(f"  charged from export        {r['free_in'] * k / 1e3:9,.0f} MWh/yr")
        print(f"  charged from engine room   {r['gen_in'] * k / 1e3:9,.0f} MWh/yr")
        print(f"  discharged into purchases  {r['out'] * k / 1e3:9,.0f} MWh/yr"
              f"  = {r['out'] * k / (B_KWH * (1 - SOC_MIN)):,.0f} full cycles")
        print(f"  grid avoided   {saved_grid * k:15,.0f} ₸")
        print(f"  extra gas      {-gen_cost * k:15,.0f} ₸")
        print(f"  wear           {-wear * k:15,.0f} ₸")
        print(f"  saving / yr    {saving:15,.0f} ₸")
        print(f"  payback        {CAPEX / saving:15,.1f} years" if saving > 0 else "  never")


if __name__ == "__main__":
    main()
