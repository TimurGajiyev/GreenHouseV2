"""CHP defaults chosen from the heating load -- verbatim port of REopt/src/core/chp.jl.

The web tool never shows a fixed CHP price. It sizes a notional CHP from the
site's average boiler fuel load, picks the prime mover and size class from that
size, and only then reads that class's costs, efficiencies, minimum size and
turndown out of ``REopt/data/chp/chp_defaults.json``. For a hospital in Golden
that is a reciprocating engine of size class 2 (170 kW heuristic, 341 kW
maximum), priced by the two-point curve 100 kW -> $3,920/kW and
250 kW -> $3,660/kW -- which is what the tool prints into its placeholders.

Also here: ``generate_year_profile_hourly`` (utils.jl:349), which turns the
prime mover's default maintenance periods into the hourly unavailability that
zeroes CHP output during scheduled downtime.
"""

from __future__ import annotations

import calendar
import datetime as dt
import io
import json
import os

KWH_PER_MMBTU = 293.07107                          # REopt.jl:66
EXISTING_BOILER_EFFICIENCY = 0.8                   # REopt.jl:63
EXISTING_BOILER_EFFICIENCY_DEFAULTS = {"hot_water": EXISTING_BOILER_EFFICIENCY, "steam": 0.75}
CONFLICT_RES_MIN_ALLOWABLE_FRACTION_OF_MAX = 0.25  # chp.jl:4
PRIME_MOVERS = ["recip_engine", "micro_turbine", "combustion_turbine", "fuel_cell"]  # chp.jl:3
AVG_BOILER_FUEL_LOAD_UNDER_RECIP_OVER_CT = {"hot_water": 27.0, "steam": 7.0}      # chp.jl:496

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(_HERE, "..", "..", "REopt", "data", "chp", "chp_defaults.json")
_CACHE: dict | None = None


def _all() -> dict:
    global _CACHE
    if _CACHE is None:
        with io.open(_DATA, encoding="utf-8") as fh:
            _CACHE = json.load(fh)
    return _CACHE


def get_prime_mover_defaults(prime_mover: str, boiler_type: str, size_class: int,
                             is_electric_only: bool) -> dict:
    """chp.jl:403."""
    pmds = _all()[prime_mover]
    out: dict = {}
    for key, val in pmds.items():
        if key in ("thermal_efficiency_full_load", "thermal_efficiency_half_load"):
            out[key] = 0.0 if is_electric_only else val[boiler_type][size_class]
        elif key == "unavailability_periods":
            out[key] = [dict(p) for p in val]
        else:
            out[key] = val[size_class]
        if key in ("installed_cost_per_kw", "om_cost_per_kwh") and is_electric_only:
            out[key] = ([x * 0.75 for x in out[key]] if isinstance(out[key], list)
                        else out[key] * 0.75)
    return out


def get_heuristic_chp_size_kw(avg_boiler_fuel_load_mmbtu_per_hour: float, prime_mover: str,
                              size_class: int, hot_water_or_steam: str, boiler_effic: float,
                              thermal_efficiency: float = float("nan")) -> float:
    """chp.jl:659 (cooling integration omitted: no absorption chiller here)."""
    pmds = _all()[prime_mover]
    therm = (pmds["thermal_efficiency_full_load"][hot_water_or_steam][size_class]
             if thermal_efficiency != thermal_efficiency else thermal_efficiency)
    if therm == 0.0:
        raise ValueError(f"thermal efficiency of {prime_mover} class {size_class} "
                         f"for {hot_water_or_steam} is 0.0; cannot size from heating load")
    elec = pmds["electric_efficiency_full_load"][size_class]
    avg_heating_thermal = avg_boiler_fuel_load_mmbtu_per_hour * boiler_effic
    chp_fuel_rate = avg_heating_thermal / therm
    return chp_fuel_rate * elec * KWH_PER_MMBTU


def get_size_class_from_size(chp_elec_size_heuristic_kw: float, class_bounds: list,
                             n_classes: int) -> int:
    """chp.jl:685. Julia is 1-based; indices are shifted, the arithmetic is not."""
    if chp_elec_size_heuristic_kw < class_bounds[1][1]:
        return 1
    if chp_elec_size_heuristic_kw >= class_bounds[n_classes - 1][0]:
        return n_classes - 1
    for sc in range(3, n_classes):                   # Julia sc in 3:(n_classes-1)
        lo, hi = class_bounds[sc - 1]
        if lo <= chp_elec_size_heuristic_kw < hi:
            return sc - 1
    return 0


def get_chp_defaults_prime_mover_size_class(*, hot_water_or_steam: str | None = None,
                                            avg_boiler_fuel_load_mmbtu_per_hour: float | None = None,
                                            prime_mover: str | None = None,
                                            size_class: int | None = None,
                                            max_kw: float = float("nan"),
                                            boiler_efficiency: float | None = None,
                                            avg_electric_load_kw: float | None = None,
                                            max_electric_load_kw: float | None = None,
                                            is_electric_only: bool = False,
                                            thermal_efficiency: float = float("nan")) -> dict:
    """chp.jl:479 -- prime mover, size class and every class default, from the load."""
    if prime_mover is not None and prime_mover not in PRIME_MOVERS:
        raise ValueError(f"prime_mover must be one of {PRIME_MOVERS}")
    if hot_water_or_steam is None:
        hot_water_or_steam = "hot_water"
    if hot_water_or_steam not in ("hot_water", "steam"):
        raise ValueError("hot_water_or_steam must be hot_water or steam")
    if avg_boiler_fuel_load_mmbtu_per_hour is not None and avg_boiler_fuel_load_mmbtu_per_hour < 0:
        raise ValueError("avg_boiler_fuel_load_mmbtu_per_hour must be >= 0.0")

    pm_all = _all()
    recalc = False
    boiler_effic = float("nan")
    chp_elec_size_heuristic_kw = None
    chp_max_size_kw = None
    if avg_boiler_fuel_load_mmbtu_per_hour is not None and not is_electric_only:
        if prime_mover is None:
            prime_mover = ("recip_engine" if avg_boiler_fuel_load_mmbtu_per_hour
                           <= AVG_BOILER_FUEL_LOAD_UNDER_RECIP_OVER_CT[hot_water_or_steam]
                           else "combustion_turbine")
        if size_class is None:
            size_class_calc, recalc = 0, True
        else:
            size_class_calc = size_class
        boiler_effic = (EXISTING_BOILER_EFFICIENCY_DEFAULTS[hot_water_or_steam]
                        if boiler_efficiency is None else boiler_efficiency)
        chp_elec_size_heuristic_kw = get_heuristic_chp_size_kw(
            avg_boiler_fuel_load_mmbtu_per_hour, prime_mover, size_class_calc,
            hot_water_or_steam, boiler_effic, thermal_efficiency)
        chp_max_size_kw = 2 * chp_elec_size_heuristic_kw
    elif avg_electric_load_kw is not None and max_electric_load_kw is not None:
        chp_elec_size_heuristic_kw = avg_electric_load_kw
        chp_max_size_kw = max_electric_load_kw

    if prime_mover is None:
        prime_mover = "recip_engine"
    if max_kw == max_kw:                              # not NaN
        chp_max_size_kw = max_kw

    n_classes = len(pm_all[prime_mover]["installed_cost_per_kw"])
    class_bounds = pm_all[prime_mover]["tech_sizes_for_cost_curve"]

    if size_class is not None:
        if size_class < 0 or size_class > n_classes - 1:
            raise ValueError(f"size class {size_class} outside 0..{n_classes - 1} for {prime_mover}")
        if chp_max_size_kw is None:
            chp_max_size_kw = class_bounds[size_class][1]
    elif chp_elec_size_heuristic_kw is not None:
        size_class = get_size_class_from_size(chp_elec_size_heuristic_kw, class_bounds, n_classes)
    else:
        size_class = 0

    if recalc:
        size_class_last = [0]
        while size_class not in size_class_last:
            size_class_last.append(size_class)
            chp_elec_size_heuristic_kw = get_heuristic_chp_size_kw(
                avg_boiler_fuel_load_mmbtu_per_hour, prime_mover, size_class,
                hot_water_or_steam, boiler_effic, thermal_efficiency)
            chp_max_size_kw = 2 * chp_elec_size_heuristic_kw
            size_class = get_size_class_from_size(chp_elec_size_heuristic_kw, class_bounds, n_classes)

    defaults = get_prime_mover_defaults(prime_mover, hot_water_or_steam, size_class, is_electric_only)
    if chp_max_size_kw is not None and defaults["min_allowable_kw"] > chp_max_size_kw:
        defaults["min_allowable_kw"] = chp_max_size_kw * CONFLICT_RES_MIN_ALLOWABLE_FRACTION_OF_MAX

    return {
        "prime_mover": prime_mover,
        "size_class": size_class,
        "hot_water_or_steam": hot_water_or_steam,
        "default_inputs": defaults,
        "chp_elec_size_heuristic_kw": chp_elec_size_heuristic_kw,
        "size_class_bounds": class_bounds,
        "chp_max_size_kw": chp_max_size_kw,
    }


def _first_day_of_week(d: dt.date) -> dt.date:
    """Julia Dates.firstdayofweek -- the Monday on or before ``d``."""
    return d - dt.timedelta(days=d.weekday())


def generate_year_profile_hourly(year: int, consecutive_periods: list[dict]) -> list[float]:
    """utils.jl:349 -- 1.0 in every hour of every period, else 0.0 (8,760 values).

    Periods that fall outside their month or run past the year end are skipped,
    as the Julia version skips them (it prints and carries on).
    """
    start = dt.datetime(year, 1, 1)
    last = dt.datetime(year, 12, 30, 23) if calendar.isleap(year) else dt.datetime(year, 12, 31, 23)
    n = int((last - start).total_seconds() // 3600) + 1
    prof = [0.0] * n
    for p in consecutive_periods:
        month = int(p["month"])
        wom = int(p["start_week_of_month"])
        dow = int(p["start_day_of_week"])            # Monday..Sunday = 1..7
        hour = int(p["start_hour"])                   # 1..24
        dur = int(p["duration_hours"])
        try:
            first = dt.date(year, month, 1)
            start_date = _first_day_of_week(first) + dt.timedelta(weeks=wom - 1, days=dow - 1)
            if start_date.month != month:
                continue
            s_dt = dt.datetime(start_date.year, start_date.month, start_date.day) + dt.timedelta(hours=hour - 1)
            if (s_dt + dt.timedelta(hours=dur)).year > year:
                continue
            e_dt = s_dt + dt.timedelta(hours=dur - 1)
            i0 = int((s_dt - start).total_seconds() // 3600)
            i1 = int((e_dt - start).total_seconds() // 3600)
            for i in range(max(0, i0), min(n - 1, i1) + 1):
                prof[i] = 1.0
        except ValueError:
            continue
    return prof[:8760] + [0.0] * max(0, 8760 - len(prof))
