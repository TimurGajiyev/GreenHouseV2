"""Custom dispatch study -- GreenHouse's own section, deliberately NOT REopt.

The REopt panels copy reopt.nlr.gov field for field and nothing else. Studies
like bess_profile_v2.jsx need inputs REopt does not have: an arbitrary hourly
load, per-unit start cost and minimum run times, a battery wear cost, a short
horizon, and several operating rules compared side by side. They live here, in
a section marked as not REopt, and feed the same "Dispatch by period" view.

The engine is the same MILP (reopt_core.model) with the finance switched off:
one period, no discounting, no tax, no capital cost, so the objective is the
plain operating cost of the horizon -- the quantity the JSX reports. It has
perfect foresight over the horizon, so on identical constraints its cost is a
lower bound on a rule-based controller's.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import time

import pandas as pd
import streamlit as st

import app_periods as A
import profile_ui as P
import ui_theme as T
import year_study as Y
from reopt_core import data_sources as ds
from reopt_core import model as M
from reopt_core.tariff import flat_tariff

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSX = os.path.join(ROOT, "bess_profile_v2.jsx")
MAX_H = 8760
# HiGHS takes a number, not a flag: a limit no run will ever reach is "none".
NO_LIMIT = 10 ** 9

# column names of the two editable tables
U_NAME, U_KW, U_COST, U_START = "Unit", "Rated kW", "Energy cost per kWh", "Start cost"
U_MIN, U_UP, U_DOWN, U_SPILL = "Min load %", "Min up h", "Min down h", "Spill allowed"
U_MAXST = "Max starts/day"
U_MEV, U_MDUR, U_MPU = "Services/period", "Service h", "Capacity lost %"
U_MSPACE = "Spread services"
U_MINT, U_MCOST = "Service every (run h)", "Service cost"
U_OWN, U_CAPEX, U_OM = "Ownership", "Purchase cost", "Variable O&M per kWh"
OWN_PAID, OWN_BUY = "Paid (owned)", "Purchase"
# The per-kWh cost was one column doing two jobs. An OEM quotes them apart --
# gas against стоимость моточаса -- and they move for different reasons, so the
# UI splits them. The MODEL still takes one number: om_cost_per_kwh is their
# sum, so nothing in the solver changed and a row left at O&M 0 prices exactly
# as it did before the column existed.
# PyPSA calls the third one maintenance_pu; here it reads as the capacity the
# service takes away, so 100% is the unit fully out -- which is what a gas
# engine service is: it cools down, is worked on, and is started again.
MSPACE_EVEN, MSPACE_FREE = "Evenly", "Anywhere"
S_NAME, S_MIN, S_BAT, S_SCALE = "Scenario", "Min load % (blank = per unit)", "Battery", "Load scale %"
S_MAXST = "Max starts/day (blank = per unit)"

# the two ways a horizon can be covered
COVER_WINDOW = "Solve the window as posed"
COVER_DAYS = "A year from typical days (weighted)"

# bess_profile_v2.jsx / CHP_BESS_model_v2.xlsx, «Допущения»
JSX_UNITS = {
    "2 units (Jenbacher + TEDOM)": [("Jenbacher", 1067.0), ("TEDOM", 1200.0)],
    "3 units (+ КГУ-3)": [("Jenbacher", 1067.0), ("TEDOM", 1200.0), ("КГУ-3", 1100.0)],
}


# ------------------------------------------------------------------ inputs
@st.cache_data(show_spinner=False)
def _jsx_loads() -> dict[str, list[float]]:
    """The artifact's own load profiles: one 24-h day and one 168-h week."""
    if not os.path.exists(JSX):
        return {}
    src = io.open(JSX, encoding="utf-8").read()
    m = re.search(r"^const DATA = (.*?);$", src, re.M | re.S)
    if not m:
        return {}
    d = json.loads(m.group(1))["chp2"]
    return {"day": [float(r[0]) for r in d["day"]["A"]["rows"]],
            "week": [float(r[0]) for r in d["week"]["A"]["rows"]]}


# A year's worth of hours that is not simply one week said 52 times.
#
# The artifact carries a day and a week. Neither holds a season, so a year made
# by repeating them has none either -- and an optimiser handed the same week 52
# times re-derives the same answer 52 times. Measured on this app: a 30-day
# window annualised came within 0.5 % of "solving" the tiled year, for 15 s of
# work against 225 s. The extra 8,040 hours bought nothing.
#
# So the shape comes from a real hourly year -- the DOE commercial reference
# buildings REopt itself ships, which carry a genuine season and a genuine
# weekday/weekend -- and only the LEVEL comes from the example week. The pairing
# below is by shape, not by the name of the building: the artifact's factory
# runs round the clock at a peak of 1.9 times its mean and never drops below
# half of it, and the DOE hospital is the reference building that behaves like
# that. The name is stated anyway, because a reader is entitled to know what the
# numbers are really made of.
#
# The choice between them is no longer offered on the page. YEAR_SHAPES and
# build_year are kept, and the year-profile tests still exercise them, but the
# free mode now draws one fixed shape (FREE_SHAPE below) and takes its LEVEL
# from the Site panel instead of from the example week. See render() for why.
YEAR_CITY = "Chicago"
YEAR_SHAPES: dict[str, tuple[str, str]] = {
    "Continuous, mild seasonal swing": ("Hospital", "crb"),
    "Continuous with a daily peak": ("Supermarket", "crb"),
    "Office hours, strong seasonal swing": ("LargeOffice", "crb"),
    "Deep nights and weekends": ("Warehouse", "crb"),
    "Two shifts, five days — no climate assumed": ("FlatLoad_16_5", "flat"),
    "Round the clock, five days — no climate assumed": ("FlatLoad_24_5", "flat"),
}


def build_year(spec: tuple[str, str], week: list[float]) -> tuple[list[float], str]:
    """A full hourly year in the example week's units, and a line saying what it is.

    The level is matched on the MEAN, not the peak: the operating cost this
    study reports is driven by energy, so the year is made to carry the same
    average kilowatt as the week the plant was drawn around. Its peak then comes
    from the real shape and is reported, because it may well differ.
    """
    name, kind = spec
    norm = (ds.custom_normalized_flatload(name) if kind == "flat"
            else ds.load_crb_profile(name, YEAR_CITY))
    mean_week = sum(week) / len(week)
    mean_norm = sum(norm) / len(norm)
    year = [v * mean_week / mean_norm for v in norm]
    peak, low = max(year), min(year)
    months = [sum(year[i * 730:(i + 1) * 730]) / 730 for i in range(12)]
    swing = max(months) / max(1e-9, min(months))
    where = ("procedural, no climate in it" if kind == "flat"
             else f"DOE reference building in {YEAR_CITY}, a US climate")
    return year, (
        f"{len(year):,} real hours — {name} ({where}) — scaled so the year averages "
        f"{mean_week:,.0f} kW, the example week's own average. Peak {peak:,.0f} kW, "
        f"quietest hour {low:,.0f} kW, busiest month {swing:.2f}\u00d7 the quietest. "
        f"Cut the window you want below."
    )


# The one shape the free mode draws. It was the first entry of YEAR_SHAPES and
# the dropdown's default, so nothing about the generated year changes by fixing
# it: round the clock, peak about 1.9 times the mean, never below half of it,
# which is what the artifact's factory does.
FREE_SHAPE: tuple[str, str] = ("Hospital", "crb")

# The Site panel's three anchors. They live here because the free year is built
# before that panel renders and has to read the average out of session state --
# on the very first pass there is nothing there yet and the default is the only
# honest answer. The widgets below use the same names, so the two cannot drift.
SITE_MIN_DEFAULT, SITE_AVG_DEFAULT, SITE_MAX_DEFAULT = 1_200.0, 3_000.0, 5_500.0


def free_year(avg_kw: float) -> tuple[list[float], str]:
    """A full hourly year at the site's own average kilowatt, and a line saying what it is.

    The same hours as build_year and the same mean-matching arithmetic; what
    differs is where the mean comes from. build_year took it from the example
    week -- a level nobody chose, carried over from a file that happens to ship
    with the app. This takes it from the Site panel, which is a number the user
    typed. The peak and the quietest hour still fall where the shape puts them
    and are reported as such: until the Site panel is asked to fit, they are
    whatever the reference year says, not the site's own.
    """
    name, kind = FREE_SHAPE
    norm = (ds.custom_normalized_flatload(name) if kind == "flat"
            else ds.load_crb_profile(name, YEAR_CITY))
    mean_norm = sum(norm) / len(norm)
    year = [v * avg_kw / mean_norm for v in norm]
    peak, low = max(year), min(year)
    months = [sum(year[i * 730:(i + 1) * 730]) / 730 for i in range(12)]
    swing = max(months) / max(1e-9, min(months))
    where = ("procedural, no climate in it" if kind == "flat"
             else f"DOE reference building in {YEAR_CITY}, a US climate")
    return year, (
        f"{len(year):,} real hours \u2014 {name} ({where}) \u2014 scaled so the year averages "
        f"{avg_kw:,.0f} kW, the Site panel's own average below. Peak {peak:,.0f} kW, "
        f"quietest hour {low:,.0f} kW, busiest month {swing:.2f}\u00d7 the quietest. "
        f"Cut the window you want below."
    )


def _num(cell: str, decimal_comma: bool) -> float | None:
    cell = cell.strip().replace(" ", "").replace(" ", "").replace(" ", "")
    if decimal_comma:
        cell = cell.replace(",", ".")
    try:
        return float(cell)
    except ValueError:
        return None


def read_series(upload) -> list[float]:
    """An hourly series from a text or CSV file.

    One value per line, or a table. Excel exports with ';' separators and decimal
    commas ("1 342,5") are read. Header rows and blank lines are skipped. When the
    first column just counts the hours (1, 2, 3 ... or 0, 1, 2 ...), the values
    are taken from the next column.
    """
    text = upload.getvalue().decode("utf-8-sig", errors="replace")
    semi = ";" in text
    delim = ";" if semi else ("\t" if "\t" in text else ",")
    rows = []
    for row in csv.reader(io.StringIO(text), delimiter=delim):
        vals = [_num(c, semi) for c in row]
        if any(v is not None for v in vals):
            rows.append(vals)
    if not rows:
        return []
    width = max(len(r) for r in rows)
    cols = [[r[j] if j < len(r) else None for r in rows] for j in range(width)]
    numeric = [c for c in cols if sum(v is not None for v in c) >= max(1, len(rows) // 2)]
    if not numeric:
        return []
    pick = numeric[0]
    first = [v for v in pick if v is not None]
    if len(numeric) > 1 and len(first) > 1 and all(
            abs((b - a) - 1.0) < 1e-9 for a, b in zip(first, first[1:])):
        pick = numeric[1]                       # an hour counter, not the data
    return [v for v in pick if v is not None]


def default_units(preset: str) -> pd.DataFrame:
    return pd.DataFrame([{U_NAME: n, U_KW: kw, U_COST: 22.0, U_START: 15_000.0, U_MIN: 50.0,
                          U_UP: 4, U_DOWN: 5, U_SPILL: True, U_MAXST: None,
                          U_MEV: 0, U_MDUR: 8, U_MPU: 100.0, U_MSPACE: True,
                          U_MINT: 0, U_MCOST: 0.0,
                          # O&M at 0 and the machines already bought: the fleet
                          # prices exactly as it did before these columns
                          U_OM: 0.0, U_OWN: OWN_PAID, U_CAPEX: 0.0}
                         for n, kw in JSX_UNITS[preset]])


def fit_to_anchors(shape: list[float], lo: float, avg: float,
                   hi: float) -> tuple[list[float], float, str]:
    """Refit a load shape onto a site's own minimum, average and maximum.

    Why this is not the straight line the brief asks for
    ----------------------------------------------------
    An affine map ``L = a*s + b`` has two free numbers, so it can satisfy two
    of the three anchors. Pin it to the minimum and the maximum and the mean
    falls where the shape puts it, which on the profiles this app ships is
    wrong by a lot: for a 1,200 / 3,000 / 5,500 kW site the JSX week comes out
    at 2,753 kW and the Chicago supermarket at 3,408 kW -- ‑8 % and +14 % on the
    one number that sets the fuel bill. Three anchors need a third degree of
    freedom.

    So the shape is normalised to u in [0, 1] and mapped through

        L[t] = lo + (hi - lo) * u[t] ** gamma

    with a single gamma solved so the mean lands exactly on ``avg``. The map is
    monotone, so every hour keeps its rank: the quiet hours stay the quiet
    hours and the peak hour stays the peak. It is exact on all three anchors.

    gamma is returned because it is the honest diagnostic. 1.0 means the shape
    already had the right fullness and was only stretched; far from 1.0 means
    the site's average sits well away from where this shape puts it and the
    curve had to be bent to agree. Measured on the shipped shapes against a
    1,200 / 3,000 / 5,500 site: JSX day 0.81, JSX week 0.83, Chicago hospital
    1.23, supermarket 1.54, warehouse 1.06.
    """
    n = len(shape)
    if n == 0:
        return [], 1.0, "no profile to scale"
    s_lo, s_hi = min(shape), max(shape)
    if s_hi - s_lo < 1e-12:
        # a flat shape carries no information to stretch; the average is all
        # three anchors at once, and saying so beats dividing by zero
        return [avg] * n, 1.0, ("the shape is flat, so it cannot be fitted to a "
                                "minimum and a maximum — every hour is the average")
    u = [(x - s_lo) / (s_hi - s_lo) for x in shape]
    want = (avg - lo) / (hi - lo)          # where the mean must sit in [0, 1]

    def mean_pow(g: float) -> float:
        return sum(x ** g for x in u) / n

    # How far the exponent can actually move the mean. As gamma falls to 0 every
    # hour above the minimum rises to the maximum, so the mean tends to the
    # FRACTION of hours above the minimum; as gamma grows every hour below the
    # maximum falls to the minimum, so it tends to the fraction of hours AT the
    # maximum. Outside that band no exponent exists, and a shape with only two
    # distinct levels has no band at all -- there are no middle hours to bend.
    p_above = sum(1 for x in u if x > 1e-12) / n
    p_at_max = sum(1 for x in u if x > 1 - 1e-12) / n
    if not (p_at_max < want < p_above):
        aff = [lo + (hi - lo) * x for x in u]
        got_aff = sum(aff) / n
        levels = len({round(x, 9) for x in u})
        why = ("the shape has only "
               f"{levels} distinct level{'s' if levels != 1 else ''}, so there are no "
               "middle hours to bend" if levels <= 2 else
               f"this shape can only average between "
               f"{lo + (hi - lo) * p_at_max:,.0f} and {lo + (hi - lo) * p_above:,.0f} kW "
               f"once its minimum and maximum are pinned")
        return aff, 1.0, (
            f"minimum and maximum hit exactly, but the average came out "
            f"{got_aff:,.0f} kW against the {avg:,.0f} asked — {why}. "
            f"Stretched straight instead; change the average, or use a profile with "
            f"more variation in it.")

    # mean_pow is continuous and strictly decreasing in gamma, from 1 as
    # gamma -> 0 to 0 as gamma -> inf, so a bisection on log gamma always lands
    a, b = 1e-6, 1e6
    for _ in range(200):
        mid = math.sqrt(a * b)
        if mean_pow(mid) > want:
            a = mid
        else:
            b = mid
    gamma = math.sqrt(a * b)
    out = [lo + (hi - lo) * (x ** gamma) for x in u]
    got = sum(out) / n
    note = (f"fitted on {n:,} hours: min {min(out):,.0f} · mean {got:,.0f} · "
            f"max {max(out):,.0f} kW  (γ {gamma:.3f}"
            + (", the shape barely bent" if 0.9 <= gamma <= 1.1 else
               ", the shape was bent to reach the average") + ")")
    return out, gamma, note


def fleet_capex(units: pd.DataFrame) -> float:
    """What the fleet costs to acquire: the rows marked Purchase, and only those.

    A row marked Paid (owned) contributes nothing -- the machine is already
    bought, so there is no acquisition to recover. This never reaches the MILP:
    the dispatch objective in this study is operating cost with the finance
    switched off, and the battery CAPEX does not enter it either. It is an
    investment figure, reported beside the battery's.
    """
    total = 0.0
    for _, u in units.iterrows():
        if float(u.get(U_KW) or 0.0) <= 0:
            continue
        if str(u.get(U_OWN) or OWN_PAID) == OWN_BUY:
            total += float(u.get(U_CAPEX) or 0.0)
    return total


def _maint_note(units: pd.DataFrame, hours: int) -> None:
    """What the service settings mean in the units the OEM writes the plan in.

    A gas engine's interval is in OPERATING hours: TEDOM and Jenbacher minor
    service is every 1,000-2,000 running hours, one shift (4-8 h) out. Running
    flat out a unit clocks ~730 h a month, so that falls every 1.5-2.5 months
    rather than monthly. Two ways to say it here, and the line differs:

      running-hour interval  the honest one. The count of services is an
                             OUTCOME of how much the unit runs, so it cannot be
                             stated up front -- only the ceiling can.
      a count per horizon    a proxy. It is stated up front, so the division is
                             done here, and a unit that never runs still gets
                             serviced, which is wrong but cheap.
    """
    rows, any_interval = [], False
    for _, u in units.iterrows():
        kw = float(u.get(U_KW) or 0.0)
        D = _opt_int(u.get(U_MDUR)) or 0
        N = float(u.get(U_MINT) or 0.0)
        E = _opt_int(u.get(U_MEV)) or 0
        cost = float(u.get(U_MCOST) or 0.0)
        if kw <= 0 or D <= 0 or (N <= 0 and E <= 0):
            continue
        name = u.get(U_NAME)
        if N > 0:
            any_interval = True
            most = int(hours // (N + D)) + 1
            rows.append(
                f"**{name}**: a {D} h service every **{N:,.0f} running hours** — "
                f"at most {most} of them in {hours:,} h if it runs throughout, "
                f"fewer if it does not, none if it never starts"
                + (f"; {cost:,.0f} each" if cost > 0 else
                   " — **no service cost set**, so an extra service in an idle "
                   "hour is free and the count may exceed what the interval needs"))
        else:
            out = E * D
            interval = (hours - out) / E
            flag = ("" if 1_000 <= interval <= 2_000 else
                    " — tighter than the 1,000–2,000 h minor-service interval"
                    if interval < 1_000 else
                    " — looser than the 1,000–2,000 h minor-service interval")
            rows.append(
                f"**{name}**: {E} × {D} h = {out} h out of {hours:,} h — "
                f"availability {100 * (1 - out / hours):.2f} %, one service every "
                f"~{interval:,.0f} running hours{flag}")
    if not rows:
        return
    st.caption("Service plan — " + "  \n".join(rows))
    st.caption(
        "The interval is in **running** hours, which is how INNIO Jenbacher and "
        "TEDOM write it; at continuous duty a unit clocks about 730 h a month, so "
        "a 1,000–2,000 h interval falls every 1.5–2.5 months, not monthly. "
        + ("Setting a running-hour interval overrides the count: the number of "
           "services becomes an outcome, and a unit that never runs is never "
           "serviced." if any_interval else
           "A count is a proxy for that interval — it is fixed up front, so a "
           "unit that never runs still gets serviced. Set 'Service every (run h)' "
           "instead to trigger on actual running hours."))


def default_scenarios() -> pd.DataFrame:
    """The artifact's three rules, A / B / C."""
    return pd.DataFrame([
        {S_NAME: "A · free from 50%", S_MIN: 50.0, S_BAT: False, S_SCALE: 100.0, S_MAXST: None},
        {S_NAME: "B · 90% rule", S_MIN: 90.0, S_BAT: False, S_SCALE: 100.0, S_MAXST: None},
        {S_NAME: "C · 90% + battery", S_MIN: 90.0, S_BAT: True, S_SCALE: 100.0, S_MAXST: None},
    ])


def _opt_int(v) -> int | None:
    """A blank / NaN cell is "no limit"; anything else is a whole number >= 0."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else max(0, int(round(f)))


# ------------------------------------------------------------------ scenario
def build(load: list[float], price: list[float], units: pd.DataFrame, bat: dict,
          sc: dict, grid_cap: float | None = None) -> M.ScenarioInputs:
    """One scenario as model inputs. Finance off: the objective is operating cost."""
    scale = float(sc.get(S_SCALE) or 100.0) / 100.0
    loads = [x * scale for x in load]
    override = sc.get(S_MIN)
    override = None if override is None or (isinstance(override, float) and math.isnan(override)) \
        else float(override)
    st_over = _opt_int(sc.get(S_MAXST))
    fleet = []
    for _, u in units.iterrows():
        kw = float(u[U_KW] or 0.0)
        if kw <= 0:
            continue
        td = (override if override is not None else float(u[U_MIN] or 0.0)) / 100.0
        fleet.append(M.FuelTechInputs(
            enabled=True, kind="CHP", label="CHP", name=str(u[U_NAME] or f"Unit {len(fleet) + 1}"),
            installed_cost_per_kw=0.0, om_cost_per_kw=0.0, om_cost_per_kwh=(float(u[U_COST] or 0.0) + float(u.get(U_OM) or 0.0)),
            fuel_cost_per_mmbtu=0.0, electric_efficiency_full_load=0.35,
            thermal_efficiency_full_load=0.0,
            min_kw=kw, max_kw=kw, min_turn_down_fraction=td,
            start_cost=float(u[U_START] or 0.0),
            min_up_hours=max(1, int(u[U_UP] or 1)), min_down_hours=max(1, int(u[U_DOWN] or 1)),
            can_curtail=bool(u[U_SPILL]),
            max_starts_per_day=(st_over if st_over is not None else _opt_int(u.get(U_MAXST))),
            maintenance_events=max(0, _opt_int(u.get(U_MEV)) or 0),
            maintenance_duration_hours=max(0, _opt_int(u.get(U_MDUR)) or 0),
            maintenance_pu=min(1.0, max(0.0, float(u.get(U_MPU) or 100.0) / 100.0)),
            maintenance_spacing=("even" if bool(u.get(U_MSPACE, True)) else "free"),
            maintenance_interval_running_hours=max(0.0, float(u.get(U_MINT) or 0.0)),
            maintenance_cost_per_event=max(0.0, float(u.get(U_MCOST) or 0.0)),
            macrs_option_years=0, macrs_bonus_fraction=0.0, federal_itc_fraction=0.0))
    on = bool(sc.get(S_BAT)) and bat["kw"] > 0 and bat["kwh"] > 0
    eta = math.sqrt(bat["rte"])
    storage = M.StorageInputs(
        enabled=on, name="Battery",
        installed_cost_per_kw=0.0, installed_cost_per_kwh=0.0, installed_cost_constant=0.0,
        om_cost_fraction_of_installed_cost=0.0,
        min_kw=bat["kw"] if on else 0.0, max_kw=bat["kw"],
        min_kwh=bat["kwh"] if on else 0.0, max_kwh=bat["kwh"],
        charge_efficiency=eta, discharge_efficiency=eta, grid_charge_efficiency=eta,
        can_grid_charge=bat["grid_charge"], soc_min_fraction=bat["soc_min"],
        soc_init_fraction=bat["soc_init"], optimize_soc_init_fraction=bat["cyclic"],
        discharge_cost_per_kwh=bat["wear"],
        macrs_option_years=0, macrs_bonus_fraction=0.0, total_itc_fraction=0.0)
    tar = flat_tariff(0.0)
    tar.energy_cost_per_kwh = list(price) + [0.0] * max(0, MAX_H - len(price))
    fin = M.FinancialInputs(
        analysis_years=1, elec_cost_escalation_rate_fraction=0.0,
        om_cost_escalation_rate_fraction=0.0, offtaker_discount_rate_fraction=0.0,
        offtaker_tax_rate_fraction=0.0, fuel_cost_escalation_rate_fraction=0.0)
    return M.ScenarioInputs(
        loads_kw=loads, tariff=tar, financial=fin, pv=M.PVInputs(enabled=False),
        storage=storage,
        fuel_tech=fleet[0] if fleet else M.FuelTechInputs(enabled=False),
        fuel_techs=fleet if len(fleet) > 1 else None,
        max_grid_import_kw=grid_cap,
        compensation_type="no_compensation")


def account(res: dict, price: list[float], units: pd.DataFrame, wear: float) -> dict:
    """The operating cost, rebuilt line by line from the solution."""
    ser, sz = res["series"], res["sizes"]
    rows = sz.get("fueltech_units") or []
    cost_of = {str(u[U_NAME]): (float(u[U_COST] or 0.0) + float(u.get(U_OM) or 0.0),
                               float(u[U_START] or 0.0))
               for _, u in units.iterrows()}
    gen_kwh = sum(r["energy_kwh"] for r in rows)
    gen_cost = sum(r["energy_kwh"] * cost_of.get(r["name"], (0.0, 0.0))[0] for r in rows)
    starts = sum(r.get("starts") or 0 for r in rows)
    start_cost = sum((r.get("starts") or 0) * cost_of.get(r["name"], (0.0, 0.0))[1] for r in rows)
    grid = ser["grid_kw"]
    grid_kwh = sum(grid)
    grid_cost = sum(price[t] * grid[t] for t in range(len(grid)))
    dis = sum(ser["battery_discharge_kw"])
    ch = sum(ser["battery_charge_kw"])
    H = len(grid)
    days = max(1, (H + 23) // 24)
    by_day = [0] * days
    for r in rows:
        for d, n in enumerate(r.get("starts_by_day") or []):
            by_day[d] += n
    return dict(
        starts_day_avg=starts / (H / 24.0), starts_day_max=max(by_day),
        starts_year=starts * MAX_H / H,
        load=sum(ser["load_kw"]), gen_kwh=gen_kwh, gen_cost=gen_cost, grid_kwh=grid_kwh,
        grid_cost=grid_cost, peak=max(grid, default=0.0), starts=starts, start_cost=start_cost,
        charge=ch, discharge=dis, wear_cost=dis * wear,
        spill=sum(r.get("spill_kwh") or 0.0 for r in rows),
        unit_hours=sum(r.get("running_hours") or 0 for r in rows),
        total=gen_cost + grid_cost + start_cost + dis * wear,
        objective=res["objective_lifecycle_cost"],
        gap=(res.get("solver") or {}).get("mip_gap"), status=res["status"])


# ------------------------------------------------------------------ view
def _money(x: float, cur: str) -> str:
    s = f"{abs(x):,.0f}"
    return (f"-{cur}{s}" if x < 0 else f"{cur}{s}") if cur == "$" else \
        (f"{'−' if x < 0 else ''}{s} {cur}")


def _compare(runs: list[dict], cur: str, hours: int, wear_h: float = 15.0) -> None:
    head = ["Metric"] + [r["name"] for r in runs]
    acc = [r["acc"] for r in runs]
    base = acc[0]["total"]
    k = MAX_H / hours

    def line(lab, key, fmt):
        return [lab] + [fmt(a[key]) for a in acc]

    kwh = lambda v: f"{v:,.0f}"
    money = lambda v: _money(v, cur)
    rows = [
        line("Load (kWh)", "load", kwh),
        line("Fuel-fired generation (kWh)", "gen_kwh", kwh),
        line("Grid purchase (kWh)", "grid_kwh", kwh),
        line("Peak grid purchase (kW)", "peak", kwh),
        line("Battery charged (kWh)", "charge", kwh),
        line("Battery discharged (kWh)", "discharge", kwh),
        line("Spill (kWh)", "spill", kwh),
        line("Starts", "starts", lambda v: f"{v:,.0f}"),
        line("Starts per day, average (fleet)", "starts_day_avg", lambda v: f"{v:,.2f}"),
        line("Starts on the busiest day (fleet)", "starts_day_max", lambda v: f"{v:,.0f}"),
        line("Starts per year" + ("" if hours == MAX_H else " (annualised)"), "starts_year",
             lambda v: f"{v:,.0f}"),
        line("Unit-hours", "unit_hours", lambda v: f"{v:,.0f}"),
        ["Effective hours (running + starts × " + f"{wear_h:g} h)"]
        + [f"{a['unit_hours'] + a['starts'] * wear_h:,.0f}" for a in acc],
        line("Generation cost", "gen_cost", money),
        line("Grid cost", "grid_cost", money),
        line("Start cost", "start_cost", money),
        line("Battery wear", "wear_cost", money),
    ]
    delta = ["vs first scenario"] + [
        ("—" if i == 0 else (_money(a["total"] - base, cur),
                             "ghp-neg" if a["total"] > base + 0.5 else "ghp-pos"))
        for i, a in enumerate(acc)]
    rows.append(delta)
    rows.append([f"Operating cost per year{'' if hours == MAX_H else f' (× {k:,.2f})'}"]
                + [money(a["total"] * k) for a in acc])
    rows.append(["vs first scenario, per year"] + [
        ("—" if i == 0 else (_money((a["total"] - base) * k, cur),
                             "ghp-neg" if a["total"] > base + 0.5 else "ghp-pos"))
        for i, a in enumerate(acc)])
    # HiGHS reports an infinite MIP gap for a model with no integers in it at
    # all -- a scenario with no fuel-fired units is a plain LP -- and "gap inf%"
    # is not a thing to show anybody. There is no gap to report, so report none.
    def _gap(a: dict) -> str:
        g = a.get("gap")
        return "" if g is None or g != g or g in (float("inf"), float("-inf"))             else f", gap {100 * g:.2f}%"

    rows.append(["Solver"] + [f"{a['status']}{_gap(a)}" for a in acc])
    P.table(head, rows, ["Operating cost"] + [money(a["total"]) for a in acc],
            sections={0: "Energy", 7: "Starts and running", 13: "Cost", 17: "Comparison"})


def hourly(res: dict, price: list[float], units: pd.DataFrame, wear: float) -> dict:
    """Each hour's cost, split the way the reference splits a saving:
    energy (generation at unit cost plus grid purchase) and operations
    (start costs and battery wear)."""
    ser = res["series"]
    H = len(ser["load_kw"])
    cost_of = {str(u[U_NAME]): (float(u[U_COST] or 0.0) + float(u.get(U_OM) or 0.0),
                               float(u[U_START] or 0.0))
               for _, u in units.iterrows()}
    energy = [price[t] * ser["grid_kw"][t] for t in range(H)]
    for name, kw in (ser.get("fueltech_unit_kw") or {}).items():
        c = cost_of.get(name, (0.0, 0.0))[0]
        for t in range(H):
            energy[t] += c * kw[t]
    starts = [0] * H
    ops = [wear * ser["battery_discharge_kw"][t] for t in range(H)]
    for name, on in (ser.get("fueltech_unit_on") or {}).items():
        sc = cost_of.get(name, (0.0, 0.0))[1]
        for t in range(H):
            if on[t] > 0.5 and on[t - 1] < 0.5:            # cyclic, as the model counts
                starts[t] += 1
                ops[t] += sc
    return {"energy": energy, "ops": ops, "starts": starts,
            "soc": list(ser.get("soc_kwh") or [])}


def _soc0(run: dict, bat: dict) -> float:
    """SoC before the first hour: the closing SoC when cyclic, else the fixed start."""
    soc = run["hourly"]["soc"]
    if not run["battery"] or not soc:
        return 0.0
    return soc[-1] if bat["cyclic"] else bat["soc_init"] * bat["kwh"]


def savings(run: dict, base: dict, out: dict) -> dict:
    """Per-hour saving of ``run`` against ``base`` for the chart's veil and strip."""
    price, units, bat = out["price"], out["units"], out["bat"]
    costs = [float(u[U_COST] or 0.0) for _, u in units.iterrows() if float(u[U_KW] or 0.0) > 0]
    p_mean = sum(price) / max(1, len(price))
    spread = p_mean - (sum(costs) / len(costs) if costs else 0.0)
    if spread <= 0:
        spread = p_mean or 1.0
    a, b = run["hourly"], base["hourly"]
    H = len(a["energy"])
    return {
        "base": base["name"],
        "save_e": [b["energy"][t] - a["energy"][t] for t in range(H)],
        "save_s": [b["ops"][t] - a["ops"][t] for t in range(H)],
        "starts_cur": a["starts"], "starts_base": b["starts"],
        "soc_cur": a["soc"] if run["battery"] else [],
        "soc_base": b["soc"] if base["battery"] else [],
        "soc0_cur": _soc0(run, bat), "soc0_base": _soc0(base, bat),
        "eta": math.sqrt(bat["rte"]), "price_mean": p_mean, "spread": spread,
    }


def _default_base(run: dict, others: list[dict]) -> dict:
    """As the reference: a battery scenario is measured against the scenario with
    the same rule and no battery; otherwise against the first other scenario."""
    if run["battery"]:
        same = [r for r in others if not r["battery"]
                and r.get("rule") == run.get("rule") and r.get("scale") == run.get("scale")]
        if same:
            return same[0]
        plain = [r for r in others if not r["battery"]]
        if plain:
            return plain[-1]
    return others[0]


def _economics(run: dict, others: list[dict], out: dict, hours: int) -> None:
    """The reference's savings and payback strip, as one table: this scenario
    against every other, per window and per year, with the battery CAPEX it
    adds and the years that CAPEX takes to pay back."""
    cur, capex = out["currency"], out["bat"].get("capex", 0.0)
    A._CUR = cur
    k = MAX_H / hours
    rows = []
    for o in others:
        save = o["acc"]["total"] - run["acc"]["total"]
        year = save * k
        extra = (capex if run["battery"] and not o["battery"] else
                 -capex if o["battery"] and not run["battery"] else 0.0)
        if extra > 0:
            pay = (f"{extra / year:,.1f} years", "ghp-pos") if year > 0 else ("never", "ghp-neg")
        elif extra < 0:
            pay = ("saves the CAPEX" if year >= 0 else f"{-extra / -year:,.1f} years (the other way)",
                   "ghp-pos" if year >= 0 else "ghp-neg")
        else:
            pay = ("—", "")
        cls = "ghp-pos" if save >= 0 else "ghp-neg"
        rows.append([o["name"], (A._signed(save), cls), (A._signed(year), cls),
                     _money(extra, cur) if extra else "—", pay])
    P.table(["Compared with", "Saving over the window", "Saving per year",
             "Extra battery CAPEX", "Payback"], rows)
    note = [f"<b>{run['name']}</b> against each other scenario; positive = cheaper to run",
            f"battery CAPEX <b>{_money(capex, cur)}</b>"]
    if hours != MAX_H:
        # How good that scaling is, measured rather than assumed: tools/
        # test_year_horizon.py cut a solved year 52 ways and annualised each week.
        note.append(f"per year = window × 8,760 / {hours:,} h — an annualisation of this "
                    f"window, not a full-year run. Measured against a solved year "
                    f"(REPORT.md Part 16): a single week lands between −15% and +23% of "
                    f"it, a single month up to +18%. The payback below carries that error")
    P.note(note)


def _pay(simple: float | None, disc: float | None, tail: str = "") -> tuple[str, str]:
    """Simple and discounted payback in one cell, or the honest word for neither.

    One cell rather than two columns: the table already carries five, and a
    seventh would fall off the right edge of the panel at the design's width.
    """
    if simple is None:
        return ("never", "ghp-neg")
    d = f"{disc:,.1f}" if disc is not None else "never"
    return (f"{simple:,.1f} / {d} yr{tail}", "ghp-pos")


def _lifecycle(run: dict, others: list[dict], out: dict, hours: int) -> None:
    """The same comparison carried out to the end of the analysis period.

    Nothing here re-solves anything: it takes the annual operating cost each
    scenario already reported and applies REopt's own present-worth factor, the
    one ``reopt_core.finance.annuity`` builds. See ``year_study.lifecycle``.
    """
    cur, capex = out["currency"], out["bat"].get("capex", 0.0)
    A._CUR = cur                 # _signed() formats in it; do not inherit it by luck
    life = out.get("life") or {}
    years = int(life.get("years", 25))
    esc, disc = float(life.get("escalation", 0.0)), float(life.get("discount", 0.0))
    own = Y.lifecycle(Y.annualise(run["acc"]["total"], hours),
                      years=years, escalation=esc, discount=disc)

    rows = []
    for o in others:
        year = Y.annualise(o["acc"]["total"] - run["acc"]["total"], hours)
        extra = (capex if run["battery"] and not o["battery"] else
                 -capex if o["battery"] and not run["battery"] else 0.0)
        lc = Y.lifecycle(Y.annualise(run["acc"]["total"], hours), years=years,
                         escalation=esc, discount=disc, annual_saving=year,
                         capex=max(0.0, extra))
        cls = "ghp-pos" if year >= 0 else "ghp-neg"
        # Net present value of choosing this scenario over that one: the present
        # value of what it saves, less the capital it has to spend to save it. A
        # negative ``extra`` means the OTHER scenario is the one spending, so not
        # spending it counts in this scenario's favour -- hence minus extra, not
        # minus max(0, extra).
        net = lc.saving_present_value - extra
        if extra > 0:
            pay = _pay(lc.simple_payback_years, lc.discounted_payback_years)
        elif extra < 0:
            # The comparison read from the other side, the way the savings strip
            # above words it: it is that scenario's CAPEX being repaid, or not.
            back = Y.lifecycle(0.0, years=years, escalation=esc, discount=disc,
                               annual_saving=-year, capex=-extra)
            pay = _pay(back.simple_payback_years, back.discounted_payback_years,
                       " reversed")
        else:
            pay = ("—", "")
        rows.append([
            o["name"],
            (A._signed(year), cls),
            (A._signed(lc.saving_present_value), cls),
            _money(extra, cur) if extra else "—",
            (A._signed(net), "ghp-pos" if net >= 0 else "ghp-neg"),
            pay,
        ])
    P.table(["Compared with", "Saving per year", f"Present value, {years} yr",
             "Extra CAPEX", "Net present value", "Payback"], rows,
            [f"{run['name']} — operating cost", _money(own.annual_cost, cur) + " / yr",
             _money(own.present_value, cur), "", "", ""])
    P.note([
        f"present worth factor <b>{own.pwf:.4f}</b> over <b>{years}</b> years "
        f"at {100 * esc:.2f}% escalation and {100 * disc:.2f}% discount",
        "the factor is REopt's own <b>annuity</b> (utils.jl:11), which charges year 1 "
        "already escalated once",
        "payback reads <b>simple / discounted</b>: undiscounted CAPEX ÷ year-one saving, "
        "then the year in which the discounted savings have repaid it",
        "<b>reversed</b> marks a row where it is the other scenario's CAPEX being repaid",
        "one year repeated with escalation — REopt's own lifetime convention",
    ])


# ------------------------------------------------------------------ page
def render() -> None:
    ss = st.session_state
    T.step("Custom dispatch study")
    st.warning(
        "**Not REopt.** This section is GreenHouse's own. It takes inputs the REopt web "
        "tool does not have — an hourly load of any length, start cost and minimum run "
        "times per unit, a battery wear cost and several operating rules side by side — "
        "and solves them with the same optimisation engine, finance switched off: the "
        "result is the plain operating cost of the horizon. Nothing here can be checked "
        "against reopt.nlr.gov.", icon=":material/science:")

    # ---- 1. load ------------------------------------------------------------
    T.panel_head("Load", required=True)
    with st.expander("Hourly load", expanded=True):
        ex = _jsx_loads()
        FREE = "Free mode: a real year, no file needed"
        # Free mode used to need the example week for its level, so it was
        # offered only when that file was present. It takes the level from the
        # Site panel now and needs nothing, so it always stands. The order is
        # unchanged where the file does exist.
        sources = (["Upload hourly CSV"]
                   + (["Example: bess_profile_v2.jsx day (24 h)",
                       "Example: bess_profile_v2.jsx week (168 h)"] if ex else [])
                   + [FREE])
        src = st.radio("Source", sources, index=1 if ex else 0, key="gd_src", horizontal=True)
        # The Site panel below can refit the level, which makes every level this
        # panel quotes provisional. It renders after this one, so its checkbox is
        # read from session state -- present from the previous rerun, absent on
        # the very first pass, which is the right default either way.
        _refit = bool(ss.get("gd_site_on"))
        _prov = (" — provisional: the Site panel below refits this level onto the "
                 "site's own minimum, average and maximum." if _refit else "")
        load: list[float] = []
        if src.startswith("Upload"):
            up = st.file_uploader("Hourly load, kW — one value per line or the first column of "
                                  "a CSV; any length from 24 to 8,760 hours",
                                  type=["csv", "txt"], key="gd_load_up")
            if up is not None:
                load = read_series(up)
        elif src == FREE:
            # ---- Annual shape: retired from the page, kept in the code -------
            # A dropdown stood here offering the six YEAR_SHAPES, and it settled
            # two questions at once: which reference year supplied the hours,
            # and -- through build_year, which matched the example week's mean --
            # what level those hours carried. The level is the Site panel's job
            # now. The site states its own minimum, average and maximum, so a
            # reference building's kilowatt has no standing here, and choosing
            # between six of them only produced the mismatch the Site panel
            # exists to remove. The shape is fixed at FREE_SHAPE; the level is
            # read from the Site panel's average below, on every pass, fit or no
            # fit. YEAR_SHAPES and build_year stay exported for the year-profile
            # tests -- nothing on this page calls them any more.
            #
            #   shape = st.selectbox("Annual shape", list(YEAR_SHAPES), key="gd_shape",
            #                        help="What the year's hour-to-hour and season-to-"
            #                             "season SHAPE is taken from.")
            #   load, note = build_year(YEAR_SHAPES[shape], ex["week"])
            _avg = float(ss.get("gd_site_avg") or 0.0) or SITE_AVG_DEFAULT
            load, note = free_year(_avg)
            st.caption(note + _prov)
        else:
            load = list(ex["day" if "day" in src else "week"])
        if load:
            n = len(load)
            c1, c2 = st.columns(2)
            # keyed by source and length, so switching the source (a day, a week, a
            # new upload) starts from its whole series, not the previous window
            wk = f"{src}_{n}"
            with c1:
                start = int(st.number_input("Window start hour (0 = first)", 0, max(0, n - 1), 0,
                                            key=f"gd_start_{wk}"))
            with c2:
                length = int(st.number_input("Window length (hours)", 1, min(MAX_H, n - start),
                                             min(MAX_H, n - start), key=f"gd_len_{wk}_{start}"))
            load = load[start:start + length]
            st.caption(f"{len(load):,} hours · {sum(load):,.0f} kWh · peak {max(load):,.0f} kW "
                       f"· minimum {min(load):,.0f} kW" + _prov)

    # ---- 1b. site -------------------------------------------------------------
    # The shape above says WHEN the site draws power; this says HOW MUCH. They
    # are separate questions and the app used to answer only the first, which is
    # why every figure so far has rested on a reference building's level rather
    # than the plant's own.
    T.panel_head("Site")
    grid_cap = None
    with st.expander("Site demand", expanded=True):
        fit_on = st.checkbox(
            "Scale the profile to this site's own demand", value=False, key="gd_site_on",
            help="Off: the profile is used at the level it arrives with. On: its shape "
                 "is kept and refitted onto the three numbers below.")
        c1, c2, c3 = st.columns(3)
        with c1:
            s_min = st.number_input(f"Minimum load (kW)", 0.0, value=SITE_MIN_DEFAULT, step=50.0,
                                    key="gd_site_min",
                                    help="The floor the site never goes below — its "
                                         "baseload, not the lowest hour of a quiet day.")
        with c2:
            s_avg = st.number_input(f"Average load (kW)", 0.0, value=SITE_AVG_DEFAULT, step=50.0,
                                    key="gd_site_avg",
                                    help="Mean demand. This is what sets total energy "
                                         "over the horizon, so it drives the fuel bill. "
                                         "In Free mode it also sets the level of the "
                                         "generated year, whether or not the box above "
                                         "is ticked.")
        with c3:
            s_max = st.number_input(f"Maximum load (kW)", 0.0, value=SITE_MAX_DEFAULT, step=50.0,
                                    key="gd_site_max",
                                    help="Peak demand — 5,500 kW for the partner site.")
        cap_on = st.checkbox(
            "The grid connection is limited", value=False, key="gd_cap_on",
            help="A transformer or supply contract ceiling on what may be drawn from "
                 "the utility, counting battery charging. Off = unlimited, which is "
                 "what REopt itself assumes.")
        if cap_on:
            grid_cap = st.number_input(f"Maximum grid import (kW)", 0.0, value=2_000.0,
                                       step=100.0, key="gd_cap_kw")
        # The fit comes BEFORE the connection check on purpose: the check has to
        # read the peak the solver will actually see. Reading it first reported
        # the profile's own 4,106 kW and called a 5,500 kW site merely "tight".
        if fit_on and load:
            if not (s_min < s_avg < s_max):
                st.error(
                    f"The three anchors have to increase: minimum {s_min:,.0f} < average "
                    f"{s_avg:,.0f} < maximum {s_max:,.0f} kW. No curve passes through "
                    f"them otherwise, so the profile is left at its own level.")
            else:
                load, _g, _note = fit_to_anchors(load, s_min, s_avg, s_max)
                st.caption(_note)
                st.caption(
                    f"{len(load):,} hours · {sum(load):,.0f} kWh · "
                    f"load factor {100 * s_avg / s_max:.1f} %. The shape is kept and every "
                    f"hour keeps its rank; only the level is the site's. An affine stretch "
                    f"would hit the minimum and the maximum and miss the average by up to "
                    f"14 % on these shapes, which is why a single exponent is solved instead.")
        elif fit_on:
            st.caption("Load a profile above and its shape will be refitted onto these three.")
        else:
            st.caption(
                "Not scaling. The profile keeps the level it arrived with — in Free "
                "mode that is the average above, already applied; for an upload or an "
                "example week it is the file's own. Tick the box to pin the minimum "
                "and the maximum as well.")

        # Now that `load` is the series the solver will receive, the connection
        # can be checked against it. A grid-tied run may not leave load unserved
        # -- reopt_core pins it to zero unless off_grid_flag -- so a ceiling the
        # plant cannot make up does not brown the site out, it returns
        # "Infeasible" with no explanation. Said here instead, with the numbers.
        if cap_on and load:
            # The units table renders below this panel, so on the first pass the
            # fleet is unknown. Claiming infeasibility then would be a guess.
            #
            # It is read from gd_fleet_kw, which the units panel writes at the
            # END of its own render, and NOT from gd_units_df: that frame is the
            # preset as it shipped and never carries an edit, so a rating typed
            # into the table was ignored here -- lower a unit to 1,500 kW and
            # this check went on counting the preset's 2,267 kW. One rerun
            # behind is the same bargain the fit checkbox above makes, and it is
            # the honest one: a data editor's edits are only known after it has
            # rendered.
            _fleet_kw = ss.get("gd_fleet_kw")
            if _fleet_kw is None:
                _fleet_df = ss.get("gd_units_df")
                _fleet_kw = (float(pd.to_numeric(_fleet_df[U_KW], errors="coerce")
                                   .fillna(0.0).clip(lower=0).sum())
                             if _fleet_df is not None and U_KW in _fleet_df else None)
            _peak = max(load)
            if _fleet_kw is not None and _peak > 0:
                _have = grid_cap + _fleet_kw
                if _have < _peak - 1e-6:
                    st.error(
                        f"No answer exists: the peak is {_peak:,.0f} kW but the wire "
                        f"passes {grid_cap:,.0f} kW and the fleet is rated "
                        f"{_fleet_kw:,.0f} kW — {_have:,.0f} kW between them. The solver "
                        f"reports Infeasible rather than shedding load, because a "
                        f"grid-tied run cannot leave demand unmet. Raise the import "
                        f"limit, add capacity, or lower the site's maximum.")
                elif _have < _peak * 1.05:
                    st.warning(
                        f"Tight: peak {_peak:,.0f} kW against {_have:,.0f} kW of wire "
                        f"plus fleet. Take one unit out for a service and the hour "
                        f"cannot be served.")

    # ---- 2. prices ------------------------------------------------------------
    T.panel_head("Grid price", required=True)
    with st.expander("Grid price", expanded=True):
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            cur = st.text_input("Currency", value="₸", key="gd_cur").strip() or "$"
        with c2:
            flat = st.number_input(f"Grid price ({cur}/kWh)", 0.0, value=60.0, step=1.0,
                                   key="gd_grid")
        with c3:
            pup = st.file_uploader("Or hourly prices (same length as the load)",
                                   type=["csv", "txt"], key="gd_price_up")
        price = [flat] * len(load)
        if pup is not None and load:
            hp = read_series(pup)
            if len(hp) >= len(load):
                price = hp[:len(load)]
                st.caption(f"hourly prices {min(price):,.2f}–{max(price):,.2f} {cur}/kWh")
            else:
                st.error(f"{len(hp)} prices for {len(load)} hours — using the flat price.")
        st.caption("No export and no demand charge in this study.")

    # ---- 3. units -------------------------------------------------------------
    T.panel_head("Fuel-fired units")
    with st.expander("Units", expanded=True):
        preset = st.selectbox("Start from", list(JSX_UNITS), key="gd_preset")
        if ss.get("gd_units_preset") != preset:
            ss["gd_units_df"] = default_units(preset)
            ss["gd_units_preset"] = preset
            ss.pop("gd_units", None)
        units = st.data_editor(
            ss["gd_units_df"], num_rows="dynamic", use_container_width=True, key="gd_units",
            column_config={
                U_KW: st.column_config.NumberColumn(min_value=0.0, step=10.0, format="%.0f"),
                U_COST: st.column_config.NumberColumn(
                    f"Fuel cost ({cur}/kWh)", min_value=0.0,
                    help="Gas only. Charged on rated output, spill included."),
                U_OM: st.column_config.NumberColumn(
                    f"Variable O&M ({cur}/kWh)", min_value=0.0,
                    help="Стоимость моточаса per kWh generated — oil, filters, plugs, "
                         "overhaul reserve. Added to the fuel cost above and charged the "
                         "same way, on rated output. Leave at 0 and pricing is exactly "
                         "what it was before this column existed."),
                U_OWN: st.column_config.SelectboxColumn(
                    options=[OWN_PAID, OWN_BUY], required=True,
                    help="Paid (owned): the machine is already bought, so it carries no "
                         "purchase cost. Purchase: its cost below joins the investment "
                         "the study pays back."),
                U_CAPEX: st.column_config.NumberColumn(
                    f"Purchase cost ({cur})", min_value=0.0, format="%.0f",
                    help="Only read when Ownership is Purchase. It is an investment "
                         "figure, not an operating one: it never enters the dispatch "
                         "objective, exactly as the battery CAPEX does not."),
                U_START: st.column_config.NumberColumn(f"Start cost ({cur})", min_value=0.0),
                U_MIN: st.column_config.NumberColumn(min_value=0.0, max_value=100.0,
                                                     help="Minimum load while running, % of rated."),
                U_UP: st.column_config.NumberColumn(min_value=1, step=1),
                U_DOWN: st.column_config.NumberColumn(min_value=1, step=1),
                U_SPILL: st.column_config.CheckboxColumn(
                    help="Output above the load may be spilled (paid for, not used)."),
                U_MAXST: st.column_config.NumberColumn(
                    min_value=0, step=1, format="%d",
                    help="At most this many starts in any calendar day. Blank = no limit."),
                U_MEV: st.column_config.NumberColumn(
                    min_value=0, step=1, format="%d",
                    help="Scheduled services in the horizon. The optimiser picks the "
                         "hours; 0 = no maintenance modelled."),
                U_MDUR: st.column_config.NumberColumn(
                    min_value=0, step=1, format="%d",
                    help="Hours the unit is out per service. A gas engine's minor "
                         "service is one shift: TEDOM and Jenbacher practice is 4-8 h."),
                U_MPU: st.column_config.NumberColumn(
                    min_value=0.0, max_value=100.0, step=5.0, format="%.0f",
                    help="Capacity the service takes away. 100% = fully out, which is "
                         "what a service visit is; below that is a derate."),
                U_MSPACE: st.column_config.CheckboxColumn(
                    help="On: one service per equal slice of the horizon, as a service "
                         "plan reads. Off: the optimiser may put them anywhere, and "
                         "nothing in the cost stops it bunching them. Unused when a "
                         "running-hour interval is set."),
                U_MINT: st.column_config.NumberColumn(
                    min_value=0, step=100, format="%d",
                    help="Service every this many RUNNING hours — how INNIO Jenbacher "
                         "and TEDOM write the interval (minor service 1,000–2,000 h). "
                         "Set it and the count above is ignored: the number of "
                         "services becomes an outcome of how much the unit runs, and a "
                         "unit that never runs is never serviced. 0 = use the count."),
                U_MCOST: st.column_config.NumberColumn(
                    min_value=0.0, format="%.0f",
                    help="Parts and labour for one service. The interval is a ceiling "
                         "on banked hours, so with no price an extra service in an "
                         "idle hour is free and the solver may take it. Any positive "
                         "figure makes the count the minimum the interval requires."),
            })
        wear_h = st.number_input(
            "Start wear, equivalent running hours per start (report only)", 0.0, 100.0, 15.0,
            step=1.0, key="gd_wear_h",
            help="CHP_BESS_dispatch_sim.xlsx: OEM maintenance plans count a start as 10–20 "
                 "running hours. Used for the 'effective hours' row; it does not change "
                 "the dispatch — the start cost does.")
        st.caption("Each unit runs at a fixed nameplate: on/off, a minimum load while on, a "
                   "start cost, and minimum up and down times. Leave a row's rating at 0 to "
                   "drop it; an empty table means grid (and battery) only.")
        _maint_note(units, len(load))
        # What the Site panel above will count as the fleet on the next rerun.
        # The edited frame itself is deliberately NOT written back to
        # gd_units_df: st.data_editor holds its edits as a delta against the
        # frame it was handed, and with num_rows="dynamic" a frame written back
        # with its added rows in it would take them again. A single number
        # carries no such risk.
        ss["gd_fleet_kw"] = float(pd.to_numeric(units[U_KW], errors="coerce")
                                  .fillna(0.0).clip(lower=0).sum()) if len(units.index) else 0.0

    # ---- 4. battery -----------------------------------------------------------
    T.panel_head("Battery")
    with st.expander("Battery", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            b_kw = st.number_input("Power (kW)", 0.0, value=2_500.0, step=100.0, key="gd_bkw")
            b_kwh = st.number_input("Energy (kWh)", 0.0, value=5_500.0, step=100.0, key="gd_bkwh")
        with c2:
            rte = st.number_input("Round-trip efficiency (%)", 1.0, 100.0, 88.0, step=1.0,
                                  key="gd_rte")
            soc_min = st.number_input("Minimum SoC (%)", 0.0, 100.0, 30.0, step=5.0, key="gd_socmin")
        with c3:
            wear = st.number_input(f"Wear cost ({cur} per kWh discharged)", 0.0, value=0.5,
                                   step=0.1, key="gd_wear")
            capex = st.number_input(f"Battery CAPEX ({cur})", 0.0, value=391_000_000.0,
                                    step=1_000_000.0, format="%.0f", key="gd_capex",
                                    help="Only for payback: CAPEX divided by the annual saving "
                                         "against a scenario without the battery.")
            grid_charge = st.checkbox("Allow grid charging", value=False, key="gd_gridchg")
        with c4:
            soc_mode = st.radio("State of charge at the start",
                                ["Cyclic (end = start)", "Fixed"], key="gd_socmode")
            soc_init = st.number_input("Start SoC (%)", 0.0, 100.0, 50.0, step=5.0,
                                       key="gd_socinit", disabled=soc_mode != "Fixed")
        st.caption("Size is fixed; each scenario below switches the battery on or off.")
    bat = dict(kw=b_kw, kwh=b_kwh, rte=rte / 100.0, soc_min=soc_min / 100.0,
               soc_init=soc_init / 100.0, cyclic=soc_mode.startswith("Cyclic"),
               wear=wear, grid_charge=grid_charge, capex=capex)

    # ---- 5. scenarios ---------------------------------------------------------
    T.panel_head("Scenarios", required=True)
    with st.expander("Operating rules to compare", expanded=True):
        if "gd_scen_df" not in ss:
            ss["gd_scen_df"] = default_scenarios()
        scen = st.data_editor(
            ss["gd_scen_df"], num_rows="dynamic", use_container_width=True, key="gd_scen",
            column_config={
                S_MIN: st.column_config.NumberColumn(min_value=0.0, max_value=100.0,
                                                     help="Overrides every unit's minimum load."),
                S_BAT: st.column_config.CheckboxColumn(),
                S_SCALE: st.column_config.NumberColumn(
                    min_value=1.0, step=5.0,
                    help="Scales the whole load — for variability. It is applied AFTER "
                         "the Site panel's fit, so anything but 100 moves the site's "
                         "minimum, average and maximum by the same factor."),
                S_MAXST: st.column_config.NumberColumn(
                    min_value=0, step=1, format="%d",
                    help="Overrides every unit's max starts per day for this scenario."),
            })
        st.caption("Each row is solved separately and compared side by side. The JSX's own "
                   "three rules are filled in; add rows to vary the load level, the minimum-load "
                   "rule or the battery.")
        # Two levers scale the same series and the scenario one runs last, so a
        # row at anything but 100 % silently moves the anchors the Site panel was
        # just told to hold. Measured: a 120 % row turns a 5,500 kW maximum into
        # 6,600 kW. Worth saying out loud rather than leaving in the arithmetic.
        if bool(ss.get("gd_site_on")):
            _scales = pd.to_numeric(scen[S_SCALE], errors="coerce").fillna(100.0)
            _off = sorted({float(x) for x in _scales if abs(float(x) - 100.0) > 1e-9})
            if _off:
                _lo, _hi = min(_off), max(_off)
                st.warning(
                    f"The Site panel is fitting the profile to a fixed minimum, average "
                    f"and maximum, but "
                    f"{'a row scales' if len(_off) == 1 else 'rows scale'} the load to "
                    + ", ".join(f"{x:,.0f} %" for x in _off) +
                    f". The scale is applied after the fit, so those rows do not run at "
                    f"the site's numbers — a {_hi:,.0f} % row takes the maximum to "
                    f"{_hi / 100 * float(ss.get('gd_site_max', 0.0)):,.0f} kW. Leave the "
                    f"scale at 100 % to compare rules at the site's own demand, or accept "
                    f"that these rows describe a different site.")
        c1, c2 = st.columns(2)
        with c1:
            tlim = st.number_input("Time limit per scenario (s) — 0 for none", 0, 86_400, 120,
                                   step=10, key="gd_tlim",
                                   help="0 lets the solver run until it proves the optimum. "
                                        "A year of commitment can take a long time; the page "
                                        "waits for it.")
        with c2:
            gap = st.number_input("Optimality gap (%)", 0.0, 10.0, 0.5, step=0.1, key="gd_gap")

    # ---- 6. how a year is covered, and what 25 of them are worth ----------------
    T.panel_head("A year, and twenty-five of them")
    with st.expander("Coverage and lifetime", expanded=True):
        whole = len(load) % 24 == 0 and len(load) // 24 >= 4
        cover = st.radio(
            "How to cover the horizon",
            [COVER_WINDOW, COVER_DAYS], key="gd_cover", horizontal=True,
            help="A full year of on/off units is 8,760 hours of binaries and does not "
                 "solve. Clustering the days into a few typical ones and weighting them "
                 "by how many real days each stands for is the standard answer "
                 "(Kotzur et al., Applied Energy 213 (2018) 123-135). Measured on this "
                 "calculator: 12 typical days reproduced a solved year to 0.01 %.")
        year_mode = cover == COVER_DAYS and whole
        if cover == COVER_DAYS and not whole:
            st.warning(f"Typical days need at least four whole days of load; this horizon "
                       f"is {len(load):,} hours. Solving the window as posed instead.",
                       icon=":material/warning:")
        c1, c2, c3 = st.columns(3)
        with c1:
            # A fixed default, not one derived from the load: a widget whose
            # default moves with the page keeps whatever number the first render
            # happened to produce, and the first render carries the 24-hour day.
            kdays = st.number_input("Typical days", 2, 60, Y.suggest_k(365),
                                    step=1, key="gd_kdays", disabled=not year_mode,
                                    help="Each one is solved once, then laid down on every "
                                         "real day of its cluster. 4 already lands within "
                                         "0.5 %, 8 within 0.02 %, 12 within 0.01 %.")
        with c2:
            yrs = st.number_input("Analysis period (years)", 1, 40, 25, step=1, key="gd_years",
                                  help="REopt's own default is 25 years.")
        with c3:
            esc = st.number_input("Operating cost escalation (%/yr)", 0.0, 20.0, 3.4, step=0.1,
                                  key="gd_esc",
                                  help="REopt's default fuel escalation is 3.4 %/yr and its "
                                       "electricity escalation 1.66 %/yr. One rate is used "
                                       "here because the study prices one operating cost.")
        disc = st.number_input("Discount rate (%/yr)", 0.0, 30.0, 6.24, step=0.01,
                               key="gd_disc",
                               help="REopt's own offtaker default is 6.24 %/yr, nominal.")
        if year_mode:
            _kk = max(1, min(int(kdays), len(load) // 24))
            st.caption(f"{_kk} typical days × 24 h = {_kk * 24:,} hours to solve per scenario "
                       f"instead of {len(load):,}. Annual energy is preserved exactly; the "
                       f"year's peak is smoothed by the clustering; the starts created where "
                       f"two unlike days meet are counted and charged, but a minimum up or "
                       f"down time spanning that join is not enforced.")
        elif len(load) > 168 and len(units.index):
            st.info(f"{len(load):,} hours with on/off units means "
                    f"{len(load) * len(units.index):,} commitment binaries per scenario; "
                    "expect the time limit to be reached and a small remaining gap. "
                    f"'{COVER_DAYS}' above solves the same year in a fraction of the time.")

    # ---- run --------------------------------------------------------------------
    missing = []
    if not load:
        missing.append("hourly load")
    if scen is None or not len(scen.index):
        missing.append("at least one scenario")
    if missing:
        st.warning("Required: " + ", ".join(missing))
    if st.button("Solve scenarios", type="primary", disabled=bool(missing), key="gd_run"):
        runs, unsolved = [], []
        prog = st.progress(0.0, text="Solving")
        rows = [r for r in scen.to_dict("records") if str(r.get(S_NAME) or "").strip()]
        try:
            # One clustering for the whole study: the typical days come from the
            # load, not from the operating rule, so every scenario is compared on
            # the same calendar. The load scale of a scenario is applied inside
            # build(), after the day has been chosen.
            # Never ask for more typical days than the load has days to give.
            kk = max(1, min(int(kdays), len(load) // 24))
            typ = Y.cluster(load, price, kk) if year_mode else None
            price_used = list(price)
            if typ is not None:
                price_used = [p for c in typ.day_of for p in typ.price[c]]
            for i, sc in enumerate(rows):
                prog.progress(i / len(rows), text=f"Solving {sc[S_NAME]} ({i + 1} of {len(rows)})")
                inp = build(load, price, units, bat, sc, grid_cap)
                if typ is not None:
                    # The year the design will show is the typical days replayed,
                    # so the tariff it prices hours with has to be the replayed
                    # price too -- otherwise the energy charge in the period view
                    # would be computed on hours that were never solved. Identical
                    # to the original series whenever the price is flat.
                    inp.tariff.energy_cost_per_kwh = (
                        list(price_used) + [0.0] * max(0, MAX_H - len(price_used)))
                t0 = time.time()
                # 0 means "no limit": HiGHS wants a number, not a flag, so it
                # is handed one no run will ever reach.
                lim = NO_LIMIT if int(tlim) == 0 else int(tlim)
                if typ is not None:
                    res = Y.solve_year(
                        lambda dl, dp, _sc=sc: build(dl, dp, units, bat, _sc),
                        load, price, kk, typical=typ,
                        time_limit=lim, mip_gap=float(gap) / 100.0,
                        on_day=lambda c, k, _n=sc[S_NAME], _i=i: prog.progress(
                            (i + c / k) / len(rows),
                            text=f"Solving {_n}: typical day {c + 1} of {k}"))
                else:
                    res = M.solve(inp, time_limit=lim, mip_gap=float(gap) / 100.0)
                # A rule the solver could not answer is not a cheap rule. Its
                # series are all zero and its objective is None, so tabulating
                # it would put an unbeatable 0 in the comparison and make every
                # saving, payback and NPV measured against it nonsense. It is
                # named below the table instead.
                if not res.get("solved", True):
                    unsolved.append((str(sc[S_NAME]), res["status"]))
                    continue
                acc = account(res, price_used, units, bat["wear"] if sc.get(S_BAT) else 0.0)
                acc["seconds"] = time.time() - t0
                runs.append({"name": str(sc[S_NAME]), "res": res, "tariff": inp.tariff,
                             "acc": acc, "battery": bool(inp.storage.enabled),
                             "rule": (None if sc.get(S_MIN) is None or (isinstance(sc.get(S_MIN), float)
                                                                        and math.isnan(sc[S_MIN]))
                                      else float(sc[S_MIN])),
                             "scale": float(sc.get(S_SCALE) or 100.0),
                             "hourly": hourly(res, price_used, units,
                                              bat["wear"] if inp.storage.enabled else 0.0)})
            prog.progress(1.0, text="Done")
            if not runs:
                raise RuntimeError(
                    "not one rule was solved — "
                    + "; ".join(f"{n}: {s}" for n, s in unsolved)
                    + ". Raise the time limit, widen the optimality gap, or "
                      "shorten the horizon.")
            ss["gd_results"] = {"runs": runs, "unsolved": unsolved,
                                # what was asked of the solver, so the results
                                # can say whether it delivered it
                                "gap_target": float(gap) / 100.0,
                                "currency": cur, "wear_h": wear_h,
                                "hours": len(runs[0]["res"]["series"]["load_kw"]),
                                "price": price_used, "units": units, "bat": bat,
                                "fleet_capex": fleet_capex(units),
                                "grid_cap": grid_cap,
                                "typical": (None if typ is None else
                                            {"k": typ.k, "weights": list(typ.weights)}),
                                "life": {"years": int(yrs), "escalation": float(esc) / 100.0,
                                         "discount": float(disc) / 100.0}}
        except Exception as exc:  # show the real reason
            prog.empty()
            st.error(f"Run failed: {exc}")
            ss["gd_results"] = None

    # ---- results ----------------------------------------------------------------
    out = ss.get("gd_results")
    if not out:
        return
    runs, cur = out["runs"], out["currency"]
    H = out.get("hours") or len(runs[0]["res"]["series"]["load_kw"])
    T.panel_head("Scenario comparison")
    # Named, not tabulated: a rule with no solution has no cost to compare.
    if out.get("unsolved"):
        st.warning(
            "Left out of the comparison because the solver returned no answer for "
            + ", ".join(f"**{n}** ({s})" for n, s in out["unsolved"])
            + ". A rule that did not solve is not a cheap rule — it has no cost at "
              "all, and putting a zero in the table would make every saving and "
              "payback beside it meaningless. Raise the time limit, widen the "
              "optimality gap, or shorten the horizon and solve again.",
            icon=":material/timer_off:")

    # A column the solver did not finish is an UPPER BOUND, not a cost, and it
    # must not sit silently beside columns that were proved.
    #
    # The gap was already in the Solver row at the foot of the table, which is
    # the last place a reader looks and the easiest to read as a footnote.
    # Measured on a year with a 120 s limit: A closed to 0.03 %, B stopped at
    # 20.49 % and C at 46.61 %, and the economics below went on to report that A
    # saves 240,656,433 kA/yr against B and 703,760,266 kA against C -- of which
    # up to 228,196,344 kA is not a saving at all, only the distance B still had
    # to travel. Savings, NPV and payback are differences, so an unconverged
    # column poisons every figure it touches.
    #
    # The test is the reader's own: the optimality gap they asked for. A run
    # that came back above it did not deliver what was requested, and that is
    # exactly the run worth naming. No invented threshold is needed.
    _target = float(out.get("gap_target") or 0.0)
    _wide = [(r["name"], g) for r in runs
             for g in [(r["acc"] or {}).get("gap")]
             if isinstance(g, float) and g == g and abs(g) != float("inf")
             and g > _target + 1e-9]
    if _wide:
        st.warning(
            "Not proved, and so not comparable: "
            + ", ".join(f"**{n}** stopped at a gap of {100 * g:.2f} %" for n, g in _wide)
            + f" against the {100 * _target:.2f} % that was asked for. Those columns "
              "are upper bounds — the true cost is somewhere below them — so the "
              "savings, net present values and paybacks computed against them are "
              "worth at most as much as the gap. Raise the time limit or shorten "
              "the horizon before reading anything into a difference.",
            icon=":material/rule:")

    if out.get("typical"):
        t = out["typical"]
        P.note([f"a year from <b>{t['k']}</b> typical days, weighted "
                f"{' + '.join(str(w) for w in t['weights'])} = <b>{sum(t['weights'])}</b> days",
                "every figure below is the weighted year, so nothing needs annualising",
                "annual energy is exact; the peak is smoothed by the clustering; the starts "
                "the joins between unlike days create are counted and charged, a minimum up "
                "or down time spanning a join is not (method: Kotzur et al. 2018)"])
    _compare(runs, cur, H, out.get("wear_h", 15.0))

    T.panel_head("Economics of one scenario against the others")
    names = [r["name"] for r in runs]
    pick = P.switch("Scenario", names, key="gd_pick")
    run = next((r for r in runs if r["name"] == pick), runs[0])
    others = [r for r in runs if r is not run]
    if others:
        _economics(run, others, out, H)
        T.panel_head(f"Over {int((out.get('life') or {}).get('years', 25))} years")
        _lifecycle(run, others, out, H)
        base_name = st.selectbox(
            "Veil and savings in the chart below are measured against", [r["name"] for r in others],
            index=[r["name"] for r in others].index(_default_base(run, others)["name"]),
            key=f"gd_base_{pick}")
        base = next(r for r in others if r["name"] == base_name)
        sav = savings(run, base, out)
    else:
        sav = None
    A.render_periods({"res": run["res"], "tariff": run["tariff"], "currency": cur,
                      "savings": sav})
