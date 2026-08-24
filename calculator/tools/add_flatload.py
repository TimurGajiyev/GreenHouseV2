"""Port REopt's procedural FlatLoad profiles.

Only plain "FlatLoad" ships as a .dat file; the five shift variants are generated
in code by custom_normalized_flatload (doe_commercial_reference_building_loads.jl:278).
They are city-independent, which is what makes a non-US site expressible at all.
"""

import io
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def patch(rel, edits):
    p = os.path.join(BASE, rel)
    s = io.open(p, encoding="utf-8").read()
    for old, new, what in edits:
        if old not in s:
            raise SystemExit("NOT FOUND in {}: {}".format(rel, what))
        s = s.replace(old, new, 1)
        print("  ok  {}: {}".format(rel, what))
    io.open(p, "w", encoding="utf-8").write(s)


patch("reopt_core/data_sources.py", [
    (
        "def build_electric_load(",
        '''FLAT_LOAD_TYPES = ("FlatLoad", "FlatLoad_24_5", "FlatLoad_16_7",
                   "FlatLoad_16_5", "FlatLoad_8_7", "FlatLoad_8_5")


def custom_normalized_flatload(doe_reference_name: str, year: int = 2017) -> list[float]:
    """REopt/src/core/doe_commercial_reference_building_loads.jl:278

    Verbatim port. Julia's dayofweek is Mon=1..Sun=7 and weekends = [6,7];
    Python's weekday() is Mon=0..Sun=6, so weekends are (5, 6).
    hour_range_16 = 6:21 (6am through the end of the 21st hour, i.e. 10pm)
    hour_range_8  = 9:16 (9am through the end of the 16th hour, i.e. 5pm)
    """
    periods = 8760
    start = datetime.datetime(year, 1, 1, 0, 0)
    dt_hourly = [start + datetime.timedelta(hours=i) for i in range(periods)]

    weekday_mask = [1] * periods
    hour_mask = [1] * periods
    weekends = (5, 6)
    hour_range_16 = range(6, 22)
    hour_range_8 = range(9, 17)
    if doe_reference_name != "FlatLoad":
        for i, dt in enumerate(dt_hourly):
            if doe_reference_name in ("FlatLoad_24_5", "FlatLoad_16_5", "FlatLoad_8_5"):
                if dt.weekday() in weekends:
                    weekday_mask[i] = 0
            if doe_reference_name in ("FlatLoad_16_5", "FlatLoad_16_7"):
                if dt.hour not in hour_range_16:
                    hour_mask[i] = 0
            elif doe_reference_name in ("FlatLoad_8_5", "FlatLoad_8_7"):
                if dt.hour not in hour_range_8:
                    hour_mask[i] = 0

    binary = [w * h for w, h in zip(weekday_mask, hour_mask)]
    total = sum(binary)
    return [i / total for i in binary]


def build_electric_load(''',
        "custom_normalized_flatload",
    ),
    (
        '''    city, zone = find_ashrae_zone_city(lat, lon)
    norm = load_crb_profile(building_type, city)''',
        '''    city, zone = find_ashrae_zone_city(lat, lon)
    if building_type in FLAT_LOAD_TYPES and building_type != "FlatLoad":
        # Shift-based flat loads are procedural and city-independent, so they carry
        # no ASHRAE-zone assumption -- the only load shapes valid outside the US.
        norm = custom_normalized_flatload(building_type)
        city, zone = building_type, "n/a"
    else:
        norm = load_crb_profile(building_type, city)''',
        "flat loads bypass the city lookup",
    ),
    (
        "import io\nimport json",
        "import datetime\nimport io\nimport json",
        "datetime import",
    ),
])

print("FlatLoad ported")
