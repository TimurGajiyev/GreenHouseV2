"""The engines' own documents, docs/equipment, as the dispatch study reads them.

One entry per machine type, each figure copied from the document named in
``doc`` at the section given in ``where``. Nothing here is derived.

What the units table takes from them: rated kW, electrical efficiency at 100 %
and 50 % load (the two points REopt's straight fuel line runs through,
utils.jl:645), and the 50 % minimum load. The 75 % point is kept to check that
line: it puts the fuel at 75 % load 0.03 % (Quanto 1200), 0.37 % (JMC 320) and
0.85 % (Cento 530) from the passport's own figure (tools/test_passports.py).

What the documents do NOT give, so the table's other columns stay assumptions:

  fuel cost per kWh   the gas tariff. The passports give gas use, not its price
  start cost          a service-contract figure
  min up / down h     a controller setting. The JMC 320 description gives a start
                      to full load in under 300 s, a stop in 280 s and a 30 s
                      restart lockout (sect. 0.20.01): minutes, not hours. The
                      TEDOM sheets give no times at all
  max starts / day    not stated
  service interval    not stated in these documents
  variable O&M        oil use is stated, its price is not
"""
from __future__ import annotations

PASSPORTS: dict[str, dict] = {
    "JMC 320": {
        "machine": "Jenbacher JMC 320 (J 320 GS-D25)",
        "doc": "Техническое описание JMC 320 (Приложение 1), INNIO, 04.09.2023",
        "kw": 1067.0,
        "eff": {100: 40.5, 75: 39.5, 50: 37.4},
        "fuel_kw": {100: 2632.0, 75: 2023.0, 50: 1418.0},
        "min_load": 50.0,
        "start_s": 300, "stop_s": 280, "restart_lock_s": 30,
        "where": {"kw": "разд. 0.01", "eff": "разд. 0.01",
                  "min_load": "разд. 1.11.10 и 2.03.02: «от 100 % до 50 % (Pmin)»",
                  "times": "разд. 0.20.01, тип 3: пуск < 300 с, снятие нагрузки до выбега "
                           "280 с, блокировка перезапуска 30 с"},
    },
    "Quanto 1200": {
        "machine": "TEDOM Quanto 1200 NG",
        "doc": "TS_Quanto_1200_MWM_NG_OM_SE_C_LB_50Hz_S_500_RU_04_2021",
        "kw": 1200.0,
        "eff": {100: 43.6, 75: 42.4, 50: 40.2},
        "fuel_kw": {100: 2750.0, 75: 2123.0, 50: 1492.0},
        "min_load": 50.0,
        "start_s": None, "stop_s": None, "restart_lock_s": None,
        "where": {"kw": "стр. 1", "eff": "стр. 2, «Расширенные технические данные»",
                  "min_load": "стр. 1: «не должна снижаться ниже 50 % номинальной мощности»",
                  "times": "not in the sheet"},
    },
    "Cento 530": {
        "machine": "TEDOM Cento 530 NG SE",
        "doc": "TS_Cento_530_MAN_NG_SE_LB_50Hz_S_EN_12_2019",
        "kw": 528.0,
        "eff": {100: 40.4, 75: 39.7, 50: 37.5},
        "fuel_kw": {100: 1306.0, 75: 997.0, 50: 703.0},
        "min_load": 50.0,
        "start_s": None, "stop_s": None, "restart_lock_s": None,
        "where": {"kw": "p. 1", "eff": "p. 1, Basic Technical Data",
                  "min_load": "p. 1: «must not drop below 50 % of the nominal output»",
                  "times": "not in the sheet"},
    },
}


def unit(key: str) -> tuple[float, float, float]:
    """(rated kW, efficiency at 100 %, at 50 %) -- the shape a units preset takes."""
    p = PASSPORTS[key]
    return p["kw"], p["eff"][100], p["eff"][50]


def source(key: str) -> str:
    """One line naming the document and where its numbers are."""
    p = PASSPORTS[key]
    e = p["eff"]
    return (f"{p['machine']}, {p['doc']}, {p['where']['eff']}: {p['kw']:,.0f} kW, "
            f"КПД эл. {e[100]} / {e[75]} / {e[50]} % при 100 / 75 / 50 %; "
            f"минимум {p['min_load']:.0f} % ({p['where']['min_load']})")
