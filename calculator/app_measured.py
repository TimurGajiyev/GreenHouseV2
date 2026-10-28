"""The plant's own meters, drawn in the dispatch chart's design.

Shown at the top of "Dispatch by period" when the custom dispatch study runs
on a measured plant, so what the engines and the city actually did sits above
what the optimiser would have had them do. Day, week and month are drawn by
the hour, a year by the day, and every window ends on the date picked.

Every figure is a meter reading (real_data.hours). An hour a meter did not
report is blank -- no bar, a break in the load line, "not measured" in the
hover panel -- and nothing is filled in. In the year view a series is drawn
for a day only when all 24 of its hours were measured, the rule
real_data.year applies to the study's own days.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import profile_ui as P
import real_data as RD

PERIODS = ["Day", "Week", "Month", "Year"]
SCOPE = "ghm_chart"          # the keyed container the hover colours are scoped to
DASH = "—"
NOT = "not measured"


@st.cache_data(show_spinner=False)
def _hours(site: str, stamp: float) -> pd.DataFrame:
    """RD.hours, read again whenever combine.py rewrites the table (``stamp``)."""
    return RD.hours(site)


def window(period: str, end: dt.date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The period ending on ``end``, that day included, as [start, stop)."""
    stop = pd.Timestamp(end) + pd.Timedelta(days=1)
    back = {"Day": pd.DateOffset(days=1), "Week": pd.DateOffset(days=7),
            "Month": pd.DateOffset(months=1), "Year": pd.DateOffset(years=1)}[period]
    return stop - back, stop


def _date(ts, weekday: bool = False) -> str:
    """Portable "22 October 2026" -- ``%-d`` is glibc only."""
    s = f"{ts.day} {ts.strftime('%B')} {ts.year}"
    return f"{ts.strftime('%A')}, {s}" if weekday else s


def frame(hours: pd.DataFrame, units: list[str], start, stop, by_day: bool) -> pd.DataFrame:
    """The window, one row per hour or per day, NaN where nothing was measured.

    The city meter comes split in two: buy is what the plant bought, sell what
    it sent. By day, a column is the day's mean, kept only where all 24 of its
    hours were measured, and ``n_<column>`` says how many were.
    """
    idx = pd.date_range(start, stop, freq="h", inclusive="left")
    w = hours.reindex(idx)
    h = pd.DataFrame({"load": w["load"], "buy": w["buy"], "sell": w["sell"]}, index=idx)
    for u in units:
        h[u] = w[u]
    h["complete"] = w["complete"].eq(True)
    if not by_day:
        return h
    cols = ["load", "buy", "sell", *units]
    g = h[cols].groupby(h.index.floor("D"))
    mean, cnt = g.mean(), g.count()
    d = mean.where(cnt == 24)
    for c in cols:
        d[f"n_{c}"] = cnt[c]
    return d


def _axis(period: str, idx: pd.DatetimeIndex, start, stop) -> tuple[dict, list[float], str]:
    """Tick labels, separators and the axis title for the window."""
    span = f"{_date(start)} – {_date(stop - pd.Timedelta(hours=1))}"
    if period == "Day":
        return {}, [], f"hour of {_date(start, weekday=True)}"
    if period == "Year":
        firsts = [i for i, t in enumerate(idx) if t.day == 1]
        labels = {i + 1: (f"{idx[i]:%b}" + (f" {idx[i].year}" if idx[i].month == 1 or k == 0
                                             else ""))
                  for k, i in enumerate(firsts)}
        return labels, [i + 0.5 for i in firsts if i], f"{span}, by day"
    days = [i for i in range(0, len(idx), 24)]
    every = 1 if period == "Week" else 2
    labels = {i + 1: f"{idx[i].day} {idx[i]:%b}" for k, i in enumerate(days) if k % every == 0}
    # a week is cut into days, a month into weeks
    cuts = [i for i in days if i and (period == "Week" or idx[i].weekday() == 0)]
    return labels, [i + 0.5 for i in cuts], span


def render(site: str) -> None:
    hours = _hours(site, RD.stamp())
    units = [u[0] for u in RD.units(site)]
    rated = [u[1] for u in RD.units(site)]
    # opens on the last day every meter measured in full, all 24 hours of it
    ok = hours["complete"]
    by = ok.groupby(hours.index.floor("D"))
    whole = (by.size() == 24) & by.all()
    full_days = whole.index[whole.values]
    if len(full_days) == 0:
        return

    c1, c2 = st.columns([1, 1], vertical_alignment="bottom")
    with c1:
        period = P.switch("Measured period", PERIODS, key="ghm_period", default="Week")
    with c2:
        end = st.date_input(
            "Measured, ending on", value=full_days[-1].date(),
            min_value=hours.index[0].date(), max_value=hours.index[-1].date(),
            format="DD.MM.YYYY", key=f"ghm_end_{RD.available().index(site)}")

    by_day = period == "Year"
    start, stop = window(period, end)
    f = frame(hours, units, start, stop, by_day)
    hourly = frame(hours, units, start, stop, False) if by_day else f
    n = len(f)

    def col(c: str) -> list[float | None]:
        return [None if pd.isna(v) else float(v) for v in f[c]]

    def got(c: str) -> list[int | None]:
        return [int(v) for v in f[f"n_{c}"]] if by_day else [None] * n

    load, buy, sell = col("load"), col("buy"), col("sell")
    per_unit = [col(u) for u in units]

    # ---- the hover panel: one fixed set of rows, as the chart requires ----
    def kw(v: float | None, measured: int | None) -> str:
        if v is None:
            return NOT if measured is None else f"{NOT} · {measured} of 24 h"
        if abs(v) <= 0.5:
            return DASH
        return (f"{v:,.0f} kW avg · {v * 24 / 1000:,.1f} MWh" if by_day
                else f"{v:,.0f} kW")

    n_load, n_buy, n_sell = got("load"), got("buy"), got("sell")
    n_unit = [got(u) for u in units]
    detail = []
    for i in range(n):
        vals = [s[i] for s in per_unit]
        d = [("Site load", kw(load[i], n_load[i]), P.INK),
             ("Engines output",
              kw(sum(vals), None) if all(v is not None for v in vals) else NOT, P.MUTED)]
        for j, u in enumerate(units):
            v = vals[j]
            text = kw(v, n_unit[j][i])
            # of its nameplate, not of the load: a plant that sends power to
            # the city runs its engines above its own load
            if v is not None and abs(v) > 0.5:
                text += f" · {100.0 * v / rated[j]:.0f}% of rated"
            d.append((f"  {u}", text, P.unit_color(j)))
        d.append(("Grid purchase", kw(buy[i], n_buy[i]), P.GRID_COLOR))
        d.append(("Sent to the city", kw(sell[i], n_sell[i]), P.MUTED))
        detail.append(d)

    labels = ([_date(t, weekday=True) for t in f.index] if by_day
              else [f"{_date(t)} · {t.hour:02d}:00" for t in f.index])
    stack = [(u, P.unit_color(j), per_unit[j]) for j, u in enumerate(units)]
    stack.append(("Grid", P.GRID_COLOR, buy))
    xlabels, seps, xtitle = _axis(period, f.index, start, stop)

    strap = " + ".join(f"{u} {k:,.0f}" for u, k in zip(units, rated))
    strap += (f" = {sum(rated):,.0f} kW" if len(units) > 1 else " kW") + f" · {RD.source(site)}"
    P.panel_head("Measured", strap)
    chart = P.dispatch_chart(
        list(range(1, n + 1)), labels, stack, load, [0.0] * n, [0.0] * n,
        ceiling_kw=sum(rated), week=period != "Day", detail=detail,
        xlabels=xlabels or None, xtitle=xtitle, seps=seps, tip_scope=SCOPE)
    with st.container(key=SCOPE):
        st.altair_chart(chart, width="stretch")

    # ---- the strip: each figure over the hours its own meter reported ----
    # Not over the hours every meter reported: a pool needs all of a plant's
    # meters and the other plant's too, and over a month with one of them
    # dark that is no hour at all -- a strip of zeros under a chart full of
    # readings. Each sum below skips only its own blanks, and the note says
    # how many hours each one covers.
    n = len(hourly)
    big = n > 168

    def energy(x: float) -> str:
        return f"{x / 1000:,.1f} MWh" if big else f"{x:,.0f} kWh"

    eng = hourly[units]
    eng_h = eng.notna().sum()
    city = hourly["buy"].notna()
    # the share needs the load and the purchase in the same hour
    both = hourly["load"].notna() & city
    load_e, buy_e = hourly.loc[both, "load"].sum(), hourly.loc[both, "buy"].sum()
    P.stat_strip([
        ("Every meter reported", f"{int(hourly['complete'].sum()):,}/{n:,} h"),
        ("Engines", energy(eng.sum().sum()) if eng_h.any() else DASH),
        ("Grid purchase", energy(hourly["buy"].sum()) if city.any() else DASH),
        ("Sent to the city", energy(hourly["sell"].sum()) if city.any() else DASH),
        ("Peak grid purchase", f"{hourly['buy'].max():,.0f} kW" if city.any() else DASH),
        ("Engine share of load",
         f"{100.0 * (load_e - buy_e) / load_e:,.1f}%" if load_e > 0 else DASH),
    ], highlight={"Grid purchase"})
    P.note([b for b in (
        "meter readings only: hourly means of measured samples; a blank is an hour a "
        "meter did not report, and nothing is filled in",
        "a series is drawn for a day only when all 24 of its hours were measured"
        if by_day else "",
        "each figure sums the hours its own meter reported, of " + f"{n:,}: "
        + ", ".join(f"{u} <b>{int(eng_h[u]):,}</b>" for u in units)
        + f", city meter{'s' if site == RD.ALL3 else ''} <b>{int(city.sum()):,}</b>"
        + (" (an hour needs both plants')" if site == RD.ALL3 else ""),
        f"engine share of load = load less purchase, over load, in the "
        f"<b>{int(both.sum()):,}</b> h the plant load was measured",
    ) if b])
