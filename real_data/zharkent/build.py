"""Build one clean time series per station from the Jenbacher logger exports,
then draw the year, the first day and the first week.

    python real_data/zharkent/build.py

Input:  raw/GPU2_CC42/*.xlsx, raw/GPU3_CR06/*.xlsx (one workbook per month,
        exported from the engine's own logger, sheet "Значения - M01").
Output: data/<station>_hourly.csv, data/<station>_samples.csv, charts/*.png

Each workbook carries three data points, each with its OWN timestamps
(roughly one averaged sample per 55 min; the short October-2026 files are
finer, about 7 min) and an average / MIN / MAX per sample:

    HalIO_.MM2VIS.rP_ActUnfilt[1]  -> gpu    active power of the engine, kW
    Customized_.MM2VIS.rPcsm_act   -> plant  plant consumption, kW
    Customized_.MM2VIS.rPmns_act   -> grid   power at the grid meter, kW
                                             (+ bought from the city,
                                              - sent to the city)

They close a balance: plant = gpu + grid (within 20 kW on 87-94 % of hours).

Cleaning:
  * "***" (no data), -999999 (invalid) and the +/-5000 clamp are dropped;
  * plant below -50 kW and grid below -1,200 kW are glitches and dropped;
  * timestamps repeated across files are kept once (the CC42 March workbook
    exists three times, one copy reaching back to 15 Jan);
  * engine samples are missing for ~30 % of hours, mostly while it stands
    still (there plant = grid), but on CC42 also while it runs. A missing gpu
    hour is rebuilt from the balance, gpu = plant - grid,
    clipped at zero. Column gpu_filled says which hours were rebuilt.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import openpyxl
import pandas as pd

HERE = Path(__file__).resolve().parent

STATIONS = {
    # folder: (label, station name in the workbook, logger time zone)
    "GPU2_CC42": ("ГПУ-2 · Zharkent (CC42)", "Zharkent", "UTC+6"),
    "GPU3_CR06": ("ГПУ-3 · Zharkent 2 (CR06)", "Zharkent 2", "UTC+5"),
}
SIGNALS = {0: "gpu", 4: "plant", 8: "grid"}     # first column of each block
NAMES = {"gpu": "Активная мощность ГПУ", "plant": "Активная мощность завода",
         "grid": "Потребление с города (минус = отдаём городу)"}
GPU_MAX_KW = 1200          # J320 nameplate ~1.06 MW; highest logged 1,130 kW
COLORS = {"gpu": "#d9822b", "plant": "#1f3b57", "grid": "#2e8b57"}


def read_station(folder):
    """All samples of one station: one row per (signal, timestamp)."""
    rows = []
    for f in sorted((HERE / "raw" / folder).glob("*.xlsx")):
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        ws = next(w for w in wb.worksheets if w.title.startswith("Знач"))
        for r in list(ws.iter_rows(values_only=True))[2:]:
            for k, sig in SIGNALS.items():
                if r[k] is not None:
                    rows.append((sig, r[k], r[k + 1], r[k + 2], r[k + 3]))
        wb.close()
    df = pd.DataFrame(rows, columns=["signal", "ts", "avg", "min", "max"])
    for c in ("avg", "min", "max"):
        v = pd.to_numeric(df[c], errors="coerce")
        df[c] = v.where((v > -5000) & (v < 5000))
    # A plant cannot draw negative power, and one engine of ~1.1 MW cannot send
    # more than that to the city: such samples are logger glitches.
    glitch = (((df.signal == "plant") & (df.avg < -50))
              | ((df.signal == "grid") & (df.avg < -GPU_MAX_KW)))
    print(f"  {folder}: dropped {int(glitch.sum())} glitch samples")
    df = df[~glitch]
    df = df.dropna(subset=["avg"]).drop_duplicates(["signal", "ts"])
    return df.sort_values("ts").reset_index(drop=True)


def hourly(samples):
    """Hourly mean per signal, gpu rebuilt from the balance where it is missing."""
    wide = {}
    for sig, g in samples.groupby("signal"):
        wide[sig] = g.set_index("ts")["avg"].resample("1h").mean()
    h = pd.DataFrame(wide)[["gpu", "plant", "grid"]]
    rebuilt = h.gpu.isna() & h.plant.notna() & h.grid.notna()
    h.loc[rebuilt, "gpu"] = (h.plant - h.grid)[rebuilt].clip(lower=0)
    h["gpu_filled"] = rebuilt
    h.index.name = "time"
    return h


def style(ax, title):
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold")
    ax.set_ylabel("Мощность, кВт")
    ax.axhline(0, color="#888", lw=0.8)
    ax.grid(True, color="#e3e3e3", lw=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(loc="upper left", fontsize=9, frameon=False, ncol=2)


def chart_year(h, label, out):
    fig, ax = plt.subplots(figsize=(16, 6))
    d = h[["gpu", "plant", "grid"]].resample("1D").mean()
    for sig in ("plant", "gpu", "grid"):
        ax.plot(h.index, h[sig], color=COLORS[sig], lw=0.4, alpha=0.25)
        ax.plot(d.index, d[sig], color=COLORS[sig], lw=1.8, label=NAMES[sig])
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    style(ax, f"{label}\nВесь период {h.index[0]:%d.%m.%Y} – {h.index[-1]:%d.%m.%Y}"
              " · тонкая линия: каждый час, толстая: среднее за сутки")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def chart_span(h, start, days, label, out):
    """Hourly values over a short span; rebuilt gpu hours marked with x."""
    end = start + pd.Timedelta(days=days)
    w = h[(h.index >= start) & (h.index < end)]
    fig, ax = plt.subplots(figsize=(14 if days > 1 else 11, 5.5))
    for sig in ("plant", "gpu", "grid"):
        ax.plot(w.index, w[sig], color=COLORS[sig], lw=1.8, marker="o",
                ms=2.5 if days > 1 else 4, label=NAMES[sig])
    if w.gpu_filled.any():
        ax.plot(w.index, w.gpu.where(w.gpu_filled), color=COLORS["gpu"], lw=0,
                marker="x", ms=5, label="ГПУ нет в логе, взята из баланса: завод − город")
    ax.fill_between(w.index, w.grid, 0, where=w.grid < 0, color=COLORS["grid"],
                    alpha=0.18, lw=0)
    ax.set_xlim(start, end)
    if days == 1:
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        span = f"{start:%d.%m.%Y}"
    else:
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a\n%d.%m"))
        span = f"{start:%d.%m} – {end - pd.Timedelta(days=1):%d.%m.%Y}"
    style(ax, f"{label}\n{'Первый день' if days == 1 else 'Первая неделя'}, {span}"
              " · средняя мощность за каждый час")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def first_full_day(h):
    """First calendar day on which all three signals cover at least 20 hours."""
    ok = h[["gpu", "plant", "grid"]].notna().all(axis=1)
    per_day = ok.groupby(h.index.floor("D")).sum()
    return per_day[per_day >= 20].index[0]


def main():
    for folder, (label, _, tz) in STATIONS.items():
        s = read_station(folder)
        h = hourly(s)
        s.to_csv(HERE / "data" / f"{folder}_samples.csv", index=False)
        h.to_csv(HERE / "data" / f"{folder}_hourly.csv", float_format="%.1f")
        lab = f"{label}, время логгера {tz}"
        day = first_full_day(h)
        chart_year(h, lab, HERE / "charts" / f"{folder}_1_year.png")
        chart_span(h, day, 1, lab, HERE / "charts" / f"{folder}_2_first_day.png")
        chart_span(h, day, 7, lab, HERE / "charts" / f"{folder}_3_first_week.png")

        e = h[["gpu", "plant", "grid"]]
        print(f"{folder}: {h.index[0]} .. {h.index[-1]}, first full day {day:%Y-%m-%d}")
        print(f"  hours with plant data {h.plant.notna().sum()}, gpu rebuilt {h.gpu_filled.sum()}")
        print(f"  energy MWh  plant {e.plant.sum()/1e3:,.0f}  gpu {e.gpu.sum()/1e3:,.0f}"
              f"  grid in {e.grid.clip(lower=0).sum()/1e3:,.0f}"
              f"  grid out {-e.grid.clip(upper=0).sum()/1e3:,.0f}")
        print(f"  peak kW  plant {e.plant.max():,.0f}  gpu {e.gpu.max():,.0f}"
              f"  grid {e.grid.max():,.0f} / {e.grid.min():,.0f}")


if __name__ == "__main__":
    main()
