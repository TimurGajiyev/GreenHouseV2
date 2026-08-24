"""URDB tariff -> hourly energy prices, TOU demand periods, monthly demand periods.

Mirrors what REopt.jl's ElectricTariff builds from a ``urdb_label``
(REopt/src/core/electric_tariff.jl and urdb.jl): per-time-step energy cost,
time-of-use demand rate lookups, monthly (flat) demand rates and a fixed charge.

Only the first tier of each rate period is used, which is what REopt does when
``ElectricTariff`` is built without tiered-consumption inputs.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field

HOURS_PER_YEAR = 8760


def _month_of_hour(year: int = 2017) -> list[int]:
    """0-based month index for each of the 8760 hours (non-leap year)."""
    out: list[int] = []
    for m in range(1, 13):
        days = calendar.monthrange(year, m)[1]
        out.extend([m - 1] * days * 24)
    return out[:HOURS_PER_YEAR]


def _is_weekend(year: int = 2017) -> list[bool]:
    out: list[bool] = []
    for m in range(1, 13):
        days = calendar.monthrange(year, m)[1]
        for d in range(1, days + 1):
            wd = calendar.weekday(year, m, d)  # Mon=0 .. Sun=6
            out.extend([wd >= 5] * 24)
    return out[:HOURS_PER_YEAR]


def _tier_rate(structure, period: int) -> float:
    """First-tier $/unit for a rate period, rate + adj as URDB defines them."""
    try:
        tier = structure[period][0]
    except (IndexError, TypeError):
        return 0.0
    return float(tier.get("rate", 0.0) or 0.0) + float(tier.get("adj", 0.0) or 0.0)


@dataclass
class Tariff:
    name: str
    utility: str
    energy_cost_per_kwh: list[float]          # 8760
    tou_demand_periods: list[list[int]]       # per TOU period -> hour indices
    tou_demand_rates: list[float]             # $/kW per TOU period
    monthly_demand_periods: list[list[int]]   # 12 -> hour indices
    monthly_demand_rates: list[float]         # $/kW per month
    fixed_monthly_charge: float = 0.0
    raw: dict = field(default_factory=dict)

    @property
    def blended_energy_rate(self) -> float:
        return sum(self.energy_cost_per_kwh) / len(self.energy_cost_per_kwh)


def build_tariff(rate: dict, year: int = 2017) -> Tariff:
    """Translate a URDB rate document into per-hour prices and demand periods."""
    months = _month_of_hour(year)
    weekend = _is_weekend(year)

    # ---- energy ----
    e_struct = rate.get("energyratestructure") or []
    e_wd = rate.get("energyweekdayschedule") or []
    e_we = rate.get("energyweekendschedule") or []
    energy = [0.0] * HOURS_PER_YEAR
    for h in range(HOURS_PER_YEAR):
        m, hr = months[h], h % 24
        sched = e_we if (weekend[h] and e_we) else e_wd
        period = 0
        if sched and m < len(sched) and hr < len(sched[m]):
            period = int(sched[m][hr])
        energy[h] = _tier_rate(e_struct, period) if e_struct else 0.0

    # ---- time-of-use demand ----
    # URDB TOU demand charges are billed EVERY MONTH against that month's peak
    # within the period, not once per year. REopt models this as one ratchet per
    # (month, period) -- ElectricTariff.tou_demand_ratchet_time_steps.
    d_struct = rate.get("demandratestructure") or []
    d_wd = rate.get("demandweekdayschedule") or []
    d_we = rate.get("demandweekendschedule") or []
    n_periods = len(d_struct)
    ratchets: dict[tuple[int, int], list[int]] = {}
    if n_periods and d_wd:
        for h in range(HOURS_PER_YEAR):
            m, hr = months[h], h % 24
            sched = d_we if (weekend[h] and d_we) else d_wd
            if sched and m < len(sched) and hr < len(sched[m]):
                p = int(sched[m][hr])
                if 0 <= p < n_periods:
                    ratchets.setdefault((m, p), []).append(h)
    keys = sorted(ratchets)
    tou_periods = [ratchets[k] for k in keys]
    tou_rates = [_tier_rate(d_struct, k[1]) for k in keys]

    # ---- monthly (flat) demand ----
    f_struct = rate.get("flatdemandstructure") or []
    f_months = rate.get("flatdemandmonths") or []
    monthly_periods: list[list[int]] = [[] for _ in range(12)]
    for h in range(HOURS_PER_YEAR):
        monthly_periods[months[h]].append(h)
    monthly_rates = [0.0] * 12
    if f_struct and f_months:
        for m in range(12):
            p = int(f_months[m]) if m < len(f_months) else 0
            monthly_rates[m] = _tier_rate(f_struct, p)

    # ---- fixed charge ----
    fixed = float(rate.get("fixedchargefirstmeter") or 0.0)
    units = (rate.get("fixedchargeunits") or "").strip()
    if units and "day" in units.lower():
        fixed *= 30.0  # normalise $/day to $/month

    return Tariff(
        name=rate.get("name", ""),
        utility=rate.get("utility", ""),
        energy_cost_per_kwh=energy,
        tou_demand_periods=[p for p in tou_periods if p],
        tou_demand_rates=[r for p, r in zip(tou_periods, tou_rates) if p],
        monthly_demand_periods=monthly_periods,
        monthly_demand_rates=monthly_rates,
        fixed_monthly_charge=fixed,
        raw=rate,
    )


def flat_tariff(energy_rate: float, monthly_demand_rate: float = 0.0,
                fixed_monthly: float = 0.0) -> Tariff:
    """A blended flat rate, matching the tool's 'Use custom electricity rate' path."""
    months = _month_of_hour()
    monthly_periods: list[list[int]] = [[] for _ in range(12)]
    for h in range(HOURS_PER_YEAR):
        monthly_periods[months[h]].append(h)
    return Tariff(
        name="Custom flat rate",
        utility="(user supplied)",
        energy_cost_per_kwh=[float(energy_rate)] * HOURS_PER_YEAR,
        tou_demand_periods=[],
        tou_demand_rates=[],
        monthly_demand_periods=monthly_periods,
        monthly_demand_rates=[float(monthly_demand_rate)] * 12,
        fixed_monthly_charge=float(fixed_monthly),
    )
