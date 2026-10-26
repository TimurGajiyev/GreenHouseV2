"""All three Zharkent engines on one page, measured, and the ЖКПЗ with a battery.

    python real_data/zharkent/combine.py      # first: builds the hourly table
    python real_data/zharkent/charts_all.py
    python real_data/zharkent/charts_all.py units [YYYY-MM-DD]
                                              # only all_3_units_week.png, for
                                              # the week starting that day

Charts (charts/):
  all_1_day.png, all_2_week.png
      measured, both plants: ЖКПЗ (TEDOM + Жаркент 2 + city) and Жаркент 3
  all_3_units_week.png
      measured, the three engines' own output as three lines on one axis,
      drawn the way build.py draws a station's year (GPU*_1_year.png)
  zhkpz_battery_1_day.png, zhkpz_battery_2_week.png
      the ЖКПЗ over the same hours three ways: as measured; scenario A, both
      engines free from 50 % without a battery; scenario B, both engines at
      90 % or more with the battery. A and B are solved by the study's own
      model (calculator/app_dispatch.build -> reopt_core.model.solve), with the
      study page's default inputs, on the measured load of those hours.

The day and the week are the first ones on which all three engines and both
plants are measured in every hour.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "calculator"))
import app_dispatch as D            # noqa: E402
import real_data as RD              # noqa: E402
from reopt_core import model as M   # noqa: E402

C = {"tedom": "#2e6db4", "j2": "#d9822b", "j3": "#8a5a9e", "grid": "#2e8b57",
     "plant": "#1f2933", "bat": "#c0392b", "soc": "#7f8c8d"}
NAME = {"tedom": "Жаркент · TEDOM Quanto 1200", "j2": "Жаркент 2 · J320 (CC42)",
        "j3": "Жаркент 3 · J320 (CR06)", "grid": "Город (минус = отдача)",
        "plant": "Потребление завода"}
# The three engines as lines that cross each other. Their colours were checked
# for that (dataviz validate_palette.js, every pair, on white): worst CVD ΔE 9.8,
# normal vision 22.1. The stacked charts' purple for Жаркент 3 fails it -- ΔE 3.8
# from the TEDOM blue under protanopia -- so Жаркент 3 is aqua here.
LINE = {"tedom": "#2e6db4", "j2": "#d9822b", "j3": "#1baf7a"}
LINE_NAME = {"tedom": "Жаркент · TEDOM Quanto 1200 (ЖКПЗ, дашборд)",
             "j2": "Жаркент 2 · Jenbacher J320 (ЖКПЗ, логгер CC42)",
             "j3": "Жаркент 3 · Jenbacher J320 (свой завод, логгер CR06)"}
RU_DAY = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
GRID_PRICE = 60.0                   # the study page's default, NOT CONFIRMED
BAT = dict(kw=2_500.0, kwh=5_500.0, rte=0.88, soc_min=0.30, soc_init=0.5, cyclic=True,
           wear=0.5, grid_charge=False)


def first_span(t: pd.DataFrame, days: int) -> pd.Timestamp:
    ok = (t.zhkpz_complete & t.site3_complete).groupby(t.index.floor("D")).all()
    run = ok.astype(int).rolling(days).sum()
    return run[run == days].index[0] - pd.Timedelta(days=days - 1)


def axis_time(ax, days):
    if days == 1:
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    else:
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a\n%d.%m"))


def tidy(ax, title):
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
    ax.set_ylabel("Мощность, кВт")
    ax.axhline(0, color="#888", lw=0.8)
    ax.grid(True, color="#e3e3e3", lw=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(loc="upper left", fontsize=8, frameon=False, ncol=3)


def stack(ax, idx, parts, plant):
    """Engines (and battery) stacked; grid on top when bought, below 0 when sent."""
    base = pd.Series(0.0, index=idx)
    for key, s, label in parts:
        ax.fill_between(idx, base, base + s, step="post", color=C[key], alpha=0.75, lw=0,
                        label=label)
        base = base + s
    ax.step(idx, plant, where="post", color=C["plant"], lw=1.8, label=NAME["plant"])


def chart_measured(t, start, days, out):
    w = t[(t.index >= start) & (t.index < start + pd.Timedelta(days=days))]
    fig, axes = plt.subplots(2, 1, figsize=(14 if days > 1 else 11, 9), sharex=True)
    imp = w.zhkpz_import_kw
    stack(axes[0], w.index, [("tedom", w.tedom_kw, NAME["tedom"]), ("j2", w.j320_2_kw, NAME["j2"]),
                             ("grid", imp.clip(lower=0), "Город, покупка")], w.zhkpz_plant_kw)
    axes[0].fill_between(w.index, imp.clip(upper=0), 0, step="post", color=C["grid"], alpha=0.35,
                         lw=0, label="Отдача в город")
    tidy(axes[0], "ЖКПЗ: TEDOM + Jenbacher Жаркент 2 + город")
    imp3 = w.site3_import_kw
    stack(axes[1], w.index, [("j3", w.j320_3_kw, NAME["j3"]),
                             ("grid", imp3.clip(lower=0), "Город, покупка")], w.site3_plant_kw)
    axes[1].fill_between(w.index, imp3.clip(upper=0), 0, step="post", color=C["grid"], alpha=0.35,
                         lw=0, label="Отдача в город")
    tidy(axes[1], "Жаркент 3: Jenbacher J320 + город")
    axis_time(axes[1], days)
    span = (f"{start:%d.%m.%Y}" if days == 1 else
            f"{start:%d.%m} – {start + pd.Timedelta(days=days - 1):%d.%m.%Y}")
    fig.suptitle(f"Все три ГПУ Жаркента, {'сутки' if days == 1 else 'неделя'} {span} · "
                 f"измерено, средняя мощность за час", x=0.01, ha="left", fontsize=13)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def chart_units_week(t, start, out):
    """The three engines' own output over one week, one line each.

    Hourly means as measured, on one axis, as build.py draws a station's year;
    an hour the engine's own value is missing from its logger and was taken
    from the logger's balance (plant - grid) is marked with an x, as build.py
    marks it. Each source keeps its own clock: the dashboard and CC42 read
    UTC+6, CR06 UTC+5.
    """
    end = start + pd.Timedelta(days=7)
    w = t[(t.index >= start) & (t.index < end)]
    fig, ax = plt.subplots(figsize=(16, 6))
    for key, s, filled in (("tedom", w.tedom_kw, None),
                           ("j2", w.j320_2_kw, w.j320_2_from_balance),
                           ("j3", w.j320_3_kw, w.j320_3_from_balance)):
        ax.plot(w.index, s, color=LINE[key], lw=1.8, label=LINE_NAME[key])
        if filled is not None and filled.astype(bool).any():
            ax.plot(w.index, s.where(filled.astype(bool)), color=LINE[key], lw=0,
                    marker="x", ms=5)
    ax.plot([], [], color="#6b6b6b", lw=0, marker="x", ms=5,
            label="часа нет в логе ГПУ, взят из баланса логгера: завод − город")
    # the nameplates the engines run against
    for kw, text in ((1200, "TEDOM Quanto 1200 · 1 200 кВт"),
                     (1067, "Jenbacher J320 · 1 067 кВт")):
        ax.axhline(kw, color="#9a9a9a", lw=0.8, ls=(0, (4, 3)))
        ax.annotate(text, (1.0, kw), xycoords=("axes fraction", "data"), xytext=(-4, 3),
                    textcoords="offset points", ha="right", va="bottom", fontsize=8.5,
                    color="#6b6b6b")
    ax.set_xlim(start, end)
    ax.set_ylim(0, 1400)
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(plt.FuncFormatter(
        lambda x, _: (lambda d: f"{RU_DAY[d.weekday()]}\n{d:%d.%m}")(mdates.num2date(x))))
    ax.set_title("Три ГПУ Жаркента · активная мощность каждой установки\n"
                 f"Неделя {start:%d.%m} – {end - pd.Timedelta(days=1):%d.%m.%Y}"
                 " · средняя мощность за каждый час · часы: дашборд и CC42 UTC+6, CR06 UTC+5",
                 loc="left", fontsize=12, fontweight="bold")
    ax.set_ylabel("Мощность, кВт")
    ax.axhline(0, color="#888", lw=0.8)
    ax.grid(True, color="#e3e3e3", lw=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(loc="upper left", fontsize=9, frameon=False, ncol=2)
    fig.text(0.01, 0.01, "Данные: data/zharkent_all_hourly.xlsx (combine.py) — TEDOM: "
             "дашборд «Жаркент», 5-минутные значения, час = среднее не менее 10 из 12; "
             "J320: логгеры Jenbacher. Ничего не интерполировано.",
             fontsize=8, color="#6b6b6b")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=130)
    plt.close(fig)
    for key, c in (("tedom", "tedom_kw"), ("j2", "j320_2_kw"), ("j3", "j320_3_kw")):
        v = w[c]
        print(f"  {key}: mean {v.mean():,.0f} kW, max {v.max():,.0f}, "
              f"hours below 50 kW {int((v < 50).sum())}")


def solve(load, minload, battery):
    units = D.default_units(D.REAL_PRESET + RD.ZHKPZ)
    sc = D._rule("x", minload=minload, bat=battery)
    price = [GRID_PRICE] * len(load)
    res = M.solve(D.build(load, price, units, BAT, sc), time_limit=300, mip_gap=0.001)
    acc = D.account(res, price, units, BAT["wear"] if battery else 0.0)
    return res, acc, units


def chart_battery(t, start, days, out):
    w = t[(t.index >= start) & (t.index < start + pd.Timedelta(days=days))]
    load = [float(x) for x in w.zhkpz_plant_kw.clip(lower=0)]
    runs = {"A": solve(load, 50.0, False), "B": solve(load, 90.0, True)}
    meas = D.measured_account({"gpu": list(w.tedom_kw + w.j320_2_kw),
                               "grid": list(w.zhkpz_import_kw),
                               "gpu_units": [list(w.tedom_kw), list(w.j320_2_kw)]},
                              [GRID_PRICE] * len(load), runs["A"][2])
    fig, axes = plt.subplots(3, 1, figsize=(14 if days > 1 else 11, 13), sharex=True)
    imp = w.zhkpz_import_kw
    stack(axes[0], w.index, [("tedom", w.tedom_kw, NAME["tedom"]), ("j2", w.j320_2_kw, NAME["j2"]),
                             ("grid", imp.clip(lower=0), "Город, покупка")], w.zhkpz_plant_kw)
    axes[0].fill_between(w.index, imp.clip(upper=0), 0, step="post", color=C["grid"], alpha=0.35,
                         lw=0, label="Отдача в город")
    tidy(axes[0], f"Как работало (логгер + дашборд) · затраты {meas['total'] / 1e6:,.2f} млн ₸, "
                  f"пусков {meas['starts']}")
    titles = {"A": "A · 2 ГПУ от 50 %, без батареи (модель)",
              "B": "B · 2 ГПУ от 90 % + батарея 2 500 кВт / 5 500 кВт·ч (модель)"}
    for ax, key in zip(axes[1:], ("A", "B")):
        res, acc, units = runs[key]
        ser = res["series"]
        names = list(ser["fueltech_unit_kw"])
        spill = ser.get("fueltech_unit_spill_kw") or {}
        net = [pd.Series([g - (spill.get(n) or [0.0] * len(load))[i]
                          for i, g in enumerate(ser["fueltech_unit_kw"][n])], index=w.index)
               for n in names]
        parts = [("tedom", net[0], NAME["tedom"]), ("j2", net[1], NAME["j2"])]
        if key == "B":
            parts.append(("bat", pd.Series(ser["battery_discharge_kw"], index=w.index),
                          "Батарея, разряд"))
        parts.append(("grid", pd.Series(ser["grid_kw"], index=w.index), "Город, покупка"))
        stack(ax, w.index, parts, w.zhkpz_plant_kw)
        if key == "B":
            ch = pd.Series(ser["battery_charge_kw"], index=w.index)
            ax.fill_between(w.index, -ch, 0, step="post", color=C["bat"], alpha=0.35, lw=0,
                            label="Батарея, заряд")
            ax2 = ax.twinx()
            ax2.plot(w.index, ser["soc_kwh"], color=C["soc"], lw=1.2, ls="--",
                     label="Заряд батареи, кВт·ч")
            ax2.set_ylim(0, BAT["kwh"] * 1.05)
            ax2.set_ylabel("Заряд батареи, кВт·ч", color=C["soc"])
            ax2.legend(loc="upper right", fontsize=8, frameon=False)
        tidy(ax, f"{titles[key]} · затраты {acc['total'] / 1e6:,.2f} млн ₸, пусков {acc['starts']}, "
                 f"{res['status']}")
    axis_time(axes[2], days)
    span = (f"{start:%d.%m.%Y}" if days == 1 else
            f"{start:%d.%m} – {start + pd.Timedelta(days=days - 1):%d.%m.%Y}")
    fig.suptitle(f"ЖКПЗ, {'сутки' if days == 1 else 'неделя'} {span}: как работало и что "
                 f"делает батарея · тариф {GRID_PRICE:g} ₸/кВт·ч, ГПУ 22 ₸/кВт·ч при 100 % "
                 f"(не подтверждены)", x=0.01, ha="left", fontsize=12)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)
    a, b = runs["A"][1], runs["B"][1]
    print(f"  {out.name}: measured {meas['total']:,.0f}  A {a['total']:,.0f}  B {b['total']:,.0f}"
          f"  B-A {b['total'] - a['total']:,.0f}  battery out {b['discharge']:,.0f} kWh")


def main():
    t = pd.read_csv(HERE / "data" / "zharkent_all_hourly.csv", index_col=0, parse_dates=True)
    out = HERE / "charts"
    day, week = first_span(t, 1), first_span(t, 7)
    if sys.argv[1:2] == ["units"]:
        start = pd.Timestamp(sys.argv[2]) if len(sys.argv) > 2 else week
        print(f"units, week from {start:%Y-%m-%d}")
        chart_units_week(t, start, out / "all_3_units_week.png")
        return
    print(f"day {day:%Y-%m-%d}, week from {week:%Y-%m-%d}")
    chart_measured(t, day, 1, out / "all_1_day.png")
    chart_measured(t, week, 7, out / "all_2_week.png")
    chart_units_week(t, week, out / "all_3_units_week.png")
    chart_battery(t, day, 1, out / "zhkpz_battery_1_day.png")
    chart_battery(t, week, 7, out / "zhkpz_battery_2_week.png")


if __name__ == "__main__":
    main()
