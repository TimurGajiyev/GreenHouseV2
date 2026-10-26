"""One hourly table for all three Zharkent engines, the table the study runs on.

    python real_data/zharkent/build.py      # logger exports -> data/*_hourly.csv
    python real_data/zharkent/combine.py    # + dashboard export -> the table below

Inputs
  data/GPU2_CC42_hourly.csv   Jenbacher logger, Жаркент 2 (J320), from build.py
  data/GPU3_CR06_hourly.csv   Jenbacher logger, Жаркент 3 (J320), from build.py
  raw/dashboard/zharkent_generator_info_5min.csv
                              monitoring dashboard, station «Жаркент» (TEDOM
                              Quanto 1200), 5-minute values:
                                Мощность установки               -> TEDOM output
                                Импорт электроэнергии (ввод ЖКПЗ) -> city import
                                Потребляемая мощность предприятием (ввод ЖКПЗ)
                                Реактивная мощность

What the meters say, checked on the 438 hours where both sources overlap
(14.09-05.10.2026), on the same clock (no shift fits better):
  * the dashboard's ЖКПЗ import IS the CC42 logger's grid meter (median
    difference 6.5 kW);
  * ЖКПЗ consumption = TEDOM + the CC42 logger's plant meter (median
    difference 6.4 kW). The CC42 "plant" meter therefore reads the plant
    LESS the TEDOM, and the plant ЖКПЗ is fed by two engines and the city:
        zhkpz_plant = tedom + j320_2 + zhkpz_import
  * Жаркент 3 (CR06) does not correlate with ЖКПЗ at any shift: another plant.

Hourly values are means of measured samples only. A TEDOM hour needs at least
10 of its 12 five-minute samples; fewer and it is left empty. Nothing is
interpolated. The logger side is build.py's hourly table; where the logger
missed one of engine and grid, that one is the other side of its balance,
plant = engine + grid (columns *_from_balance say which hours).
"""
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DASH = HERE / "raw" / "dashboard" / "zharkent_generator_info_5min.csv"
MIN_SAMPLES = 10            # of 12 five-minute values in an hour

RU = {
    "tedom_kw": "Жаркент · TEDOM Quanto 1200, мощность, кВт",
    "j320_2_kw": "Жаркент 2 · Jenbacher J320 (CC42), мощность, кВт",
    "zhkpz_import_kw": "ЖКПЗ · импорт из города (минус = отдача), кВт",
    "zhkpz_plant_kw": "ЖКПЗ · потребление завода = TEDOM + J320 + импорт, кВт",
    "j320_3_kw": "Жаркент 3 · Jenbacher J320 (CR06), мощность, кВт",
    "site3_import_kw": "Жаркент 3 · импорт из города (минус = отдача), кВт",
    "site3_plant_kw": "Жаркент 3 · потребление завода, кВт",
    "zhkpz_complete": "ЖКПЗ · час измерен полностью",
    "site3_complete": "Жаркент 3 · час измерен полностью",
    "tedom_samples": "TEDOM · 5-минутных значений в часе",
    "j320_2_from_balance": "Жаркент 2 · мощность взята из баланса логгера",
    "j320_3_from_balance": "Жаркент 3 · мощность взята из баланса логгера",
    "import_2_from_balance": "ЖКПЗ · импорт взят из баланса логгера",
    "import_3_from_balance": "Жаркент 3 · импорт взят из баланса логгера",
    "reactive_kvar": "Жаркент · реактивная мощность, квар",
}


def dashboard() -> pd.DataFrame:
    d = pd.read_csv(DASH, encoding="utf-8-sig")
    d.columns = ["time", "tedom", "imp", "plant", "q"]
    d["time"] = pd.to_datetime(d["time"])
    d = d.set_index("time")
    n = d["tedom"].resample("1h").count()
    h = d.resample("1h").mean()
    h.loc[n < MIN_SAMPLES, "tedom"] = float("nan")
    h["samples"] = n
    return h


def table() -> pd.DataFrame:
    dash = dashboard()
    c2 = pd.read_csv(HERE / "data" / "GPU2_CC42_hourly.csv", index_col=0, parse_dates=True)
    c3 = pd.read_csv(HERE / "data" / "GPU3_CR06_hourly.csv", index_col=0, parse_dates=True)
    idx = pd.date_range(min(c2.index.min(), dash.index.min()),
                        max(c2.index.max(), dash.index.max()), freq="1h")
    dash, c2, c3 = dash.reindex(idx), c2.reindex(idx), c3.reindex(idx)
    # a grid hour the logger missed is the other side of its own balance,
    # grid = plant - engine, as build.py already does for the engine
    for c in (c2, c3):
        c["grid_from_balance"] = c["grid"].isna() & c["plant"].notna() & c["gpu"].notna()
        c["grid"] = c["grid"].fillna(c["plant"] - c["gpu"])
        c["gpu_filled"] = c["gpu_filled"].astype("boolean").fillna(False).astype(bool)
    t = pd.DataFrame(index=idx)
    t.index.name = "time"
    t["tedom_kw"] = dash["tedom"]
    t["j320_2_kw"] = c2["gpu"]
    t["zhkpz_import_kw"] = c2["grid"]
    # the CC42 plant meter is J320 + import; add the TEDOM for the plant itself
    t["zhkpz_plant_kw"] = dash["tedom"] + c2["plant"]
    t["j320_3_kw"] = c3["gpu"]
    t["site3_import_kw"] = c3["grid"]
    t["site3_plant_kw"] = c3["plant"]
    t["zhkpz_complete"] = t[["tedom_kw", "j320_2_kw", "zhkpz_import_kw", "zhkpz_plant_kw"]].notna().all(axis=1)
    t["site3_complete"] = t[["j320_3_kw", "site3_import_kw", "site3_plant_kw"]].notna().all(axis=1)
    t["tedom_samples"] = dash["samples"].fillna(0).astype(int)
    t["j320_2_from_balance"] = c2["gpu_filled"]
    t["j320_3_from_balance"] = c3["gpu_filled"]
    t["import_2_from_balance"] = c2["grid_from_balance"]
    t["import_3_from_balance"] = c3["grid_from_balance"]
    t["reactive_kvar"] = dash["q"]
    return t


def main():
    t = table()
    t.to_csv(HERE / "data" / "zharkent_all_hourly.csv", float_format="%.1f")
    x = t.copy()
    x.index = x.index.strftime("%Y-%m-%d %H:%M")
    x.index.name = "Время"
    x.rename(columns=RU).to_excel(HERE / "data" / "zharkent_all_hourly.xlsx", float_format="%.1f")
    days = lambda c: int(t[c].groupby(t.index.floor("D")).all().sum())
    print(f"{t.index[0]} .. {t.index[-1]}, {len(t):,} hours")
    print(f"ЖКПЗ complete hours {int(t.zhkpz_complete.sum()):,}, complete days {days('zhkpz_complete')}")
    print(f"Жаркент 3 complete hours {int(t.site3_complete.sum()):,}, complete days {days('site3_complete')}")


if __name__ == "__main__":
    main()
