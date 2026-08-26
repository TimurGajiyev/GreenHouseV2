"""Day / week / year views, and the hour-by-hour table for one day.

The framing follows the summary tables in PROJECT_FULL §9.2 and §10.3 -- a
representative day, a week and the full year in one grid, so a reader can see
the same quantities at three time scales without switching pages. Row labels
stay in the REopt vocabulary used everywhere else on the results page.

The representative day is chosen the way PROJECT_FULL picks it: the day whose
total energy is closest to the median across the year, so it is typical rather
than extreme. The peak day is offered alongside because that is the one that
sets the demand charge.
"""

from __future__ import annotations

import calendar

import altair as alt
import pandas as pd
import streamlit as st

import ui_theme as T

HOURS = 8760
DAYS = 365


def _idx() -> pd.DatetimeIndex:
    return pd.date_range("2017-01-01", periods=HOURS, freq="h")


def _m(x) -> str:
    if x is None:
        return "N/A"
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def _daily_totals(series: list[float]) -> list[float]:
    return [sum(series[d * 24:(d + 1) * 24]) for d in range(DAYS)]


def representative_day(load: list[float]) -> int:
    """Day index whose energy is closest to the median day -- PROJECT_FULL's rule."""
    daily = _daily_totals(load)
    ordered = sorted(daily)
    med = ordered[len(ordered) // 2]
    return min(range(DAYS), key=lambda d: abs(daily[d] - med))


def peak_day(load: list[float]) -> int:
    return max(range(DAYS), key=lambda d: max(load[d * 24:(d + 1) * 24]))


def _slice(series: dict, start_h: int, n_h: int) -> dict:
    out = {}
    for k, v in series.items():
        if isinstance(v, dict):
            out[k] = {name: s[start_h:start_h + n_h] for name, s in v.items()}
        elif isinstance(v, list) and len(v) == HOURS:
            out[k] = v[start_h:start_h + n_h]
    return out


# ------------------------------------------------------------------ tables
def hourly_frame(series: dict, day: int) -> pd.DataFrame:
    """The 1..24 table for one day."""
    s = _slice(series, day * 24, 24)
    units = s.get("fueltech_unit_kw") or {}
    rows = []
    for h in range(24):
        row = {
            "Hour": h + 1,
            "Load (kW)": s["load_kw"][h],
            "PV (kW)": s["pv_to_load_kw"][h],
        }
        for name, vals in units.items():
            row[f"{name} (kW)"] = vals[h]
        if len(units) > 1:
            row["Fuel total (kW)"] = s["fueltech_kw"][h]
        row.update({
            "Battery charge (kW)": s["battery_charge_kw"][h],
            "Battery discharge (kW)": s["battery_discharge_kw"][h],
            "State of charge (kWh)": s["soc_kwh"][h],
            "Grid (kW)": s["grid_kw"][h],
        })
        if sum(s.get("export_kw", [0])) > 1e-6:
            row["Export (kW)"] = s["export_kw"][h]
        if sum(s.get("unserved_kw", [0])) > 1e-6:
            row["Unserved (kW)"] = s["unserved_kw"][h]
        if sum(s.get("pv_curtailed_kw", [0])) > 1e-6:
            row["PV curtailed (kW)"] = s["pv_curtailed_kw"][h]
        rows.append(row)

    df = pd.DataFrame(rows)
    total = {c: (df[c].sum() if c != "Hour" else "Total") for c in df.columns}
    # a running SOC does not sum; show where it ended
    if "State of charge (kWh)" in total:
        total["State of charge (kWh)"] = df["State of charge (kWh)"].iloc[-1]
    return pd.concat([df, pd.DataFrame([total])], ignore_index=True)


def _period_block(series: dict, tariff, start_h: int, n_h: int, label: str) -> dict:
    s = _slice(series, start_h, n_h)
    grid = s["grid_kw"]
    gen = s["fueltech_kw"]
    out = {
        "Site load (kWh)": sum(s["load_kw"]),
        "PV production (kWh)": sum(s["pv_to_load_kw"]) + sum(s.get("pv_curtailed_kw", [0])),
        "Fuel-fired production (kWh)": sum(gen),
        "Battery charged (kWh)": sum(s["battery_charge_kw"]),
        "Battery discharged (kWh)": sum(s["battery_discharge_kw"]),
        "Grid purchase (kWh)": sum(grid),
        "Peak grid purchase (kW)": max(grid) if grid else 0.0,
    }
    if sum(s.get("unserved_kw", [0])) > 1e-6:
        out["Unserved load (kWh)"] = sum(s["unserved_kw"])
    if tariff is not None:
        e = sum(tariff.energy_cost_per_kwh[start_h + h] * grid[h] for h in range(n_h))
        out["Energy charge ($)"] = e
    return out


def period_frame(series: dict, tariff, rep_day: int) -> pd.DataFrame:
    """Representative day / week containing it / full year, side by side."""
    week_start = (rep_day // 7) * 7 * 24
    blocks = [
        ("Representative day", _period_block(series, tariff, rep_day * 24, 24, "day")),
        ("Week", _period_block(series, tariff, week_start, min(168, HOURS - week_start), "week")),
        ("Year", _period_block(series, tariff, 0, HOURS, "year")),
    ]
    keys = []
    for _, b in blocks:
        for k in b:
            if k not in keys:
                keys.append(k)
    rows = []
    for k in keys:
        row = {"Metric": k}
        for name, b in blocks:
            val = b.get(k)
            if val is None:
                row[name] = "—"
            elif k.endswith("($)"):
                row[name] = _m(val)
            else:
                row[name] = f"{val:,.0f}"
        rows.append(row)
    return pd.DataFrame(rows)


def monthly_peak_frame(series: dict) -> pd.DataFrame:
    """Peak grid purchase per month -- the quantity a demand charge bills on."""
    idx = _idx()
    df = pd.DataFrame({"grid": series["grid_kw"], "month": idx.month})
    g = df.groupby("month")["grid"]
    rows = [{"Month": calendar.month_abbr[mo],
             "Peak grid purchase (kW)": f"{g.max().get(mo, 0.0):,.0f}",
             "Grid energy (kWh)": f"{g.sum().get(mo, 0.0):,.0f}"}
            for mo in range(1, 13)]
    rows.append({"Month": "Sum of 12 monthly peaks",
                 "Peak grid purchase (kW)": f"{g.max().sum():,.0f}",
                 "Grid energy (kWh)": f"{g.sum().sum():,.0f}"})
    return pd.DataFrame(rows)


def unit_frame(sizes: dict) -> pd.DataFrame | None:
    rows = sizes.get("fueltech_units") or []
    if not rows:
        return None
    out = []
    for u in rows:
        r = {
            "Unit": u["name"],
            "Type": u["kind"],
            "Size (kW)": f"{u['size_kw']:,.0f}",
            "Production (kWh)": f"{u['energy_kwh']:,.0f}",
            "Capacity factor": f"{u['capacity_factor']:.1%}",
            "Running hours": f"{u['running_hours']:,}",
            f"Fuel ({u['fuel_unit_name']})": f"{u['fuel_units']:,.0f}",
        }
        if u.get("starts") is not None:
            r["Starts"] = f"{u['starts']:,}"
        out.append(r)
    return pd.DataFrame(out)


def storage_frame(sizes: dict) -> pd.DataFrame | None:
    rows = sizes.get("storage_units") or []
    if not rows:
        return None
    return pd.DataFrame([{
        "Unit": u["name"],
        "Power (kW)": f"{u['power_kw']:,.0f}",
        "Energy (kWh)": f"{u['energy_kwh']:,.0f}",
        "Duration (h)": f"{u['duration_hours']:,.2f}",
        "Discharged (kWh/yr)": f"{u['throughput_kwh']:,.0f}",
        "Full cycles/yr": f"{u['full_cycles']:,.0f}",
    } for u in rows])


# ----------------------------------------------------------------- render
def render_periods(state: dict) -> None:
    res = state["res"]
    series = res.get("series") or {}
    if not series:
        return
    tariff = state.get("tariff")
    load = series["load_kw"]

    T.panel_head("Dispatch by period", icon="calendar_month")

    units = unit_frame(res["sizes"])
    if units is not None and len(units) > 1:
        st.caption("Each fuel-fired unit is sized and dispatched separately.")
        st.dataframe(units, hide_index=True, width="stretch")
    elif units is not None:
        st.dataframe(units, hide_index=True, width="stretch")

    banks = storage_frame(res["sizes"])
    if banks is not None and len(banks) > 1:
        st.caption("Each battery is sized and dispatched separately.")
        st.dataframe(banks, hide_index=True, width="stretch")

    rep, pk = representative_day(load), peak_day(load)
    idx = _idx()
    st.dataframe(period_frame(series, tariff, rep), hide_index=True, width="stretch")
    st.caption(
        f"The representative day is the one whose energy is closest to the median "
        f"across the year — {idx[rep * 24]:%-d %B}. The week is the calendar week "
        f"containing it."
    )

    st.markdown("**Hour by hour**")
    choice = st.radio(
        "Day to show", ["Representative day", "Peak day"],
        horizontal=True, key="period_day_choice", label_visibility="collapsed",
    )
    day = rep if choice == "Representative day" else pk
    st.caption(f"{idx[day * 24]:%A, %-d %B} — hours 1 to 24.")

    hf = hourly_frame(series, day)
    st.dataframe(hf, hide_index=True, width="stretch")

    # stacked supply against the load line
    s = _slice(series, day * 24, 24)
    parts = {"PV": s["pv_to_load_kw"], "Battery": s["battery_discharge_kw"],
             "Grid": s["grid_kw"]}
    for name, vals in (s.get("fueltech_unit_kw") or {}).items():
        parts[name] = vals
    long = pd.DataFrame([
        {"Hour": h + 1, "Source": k, "kW": vals[h]}
        for k, vals in parts.items() for h in range(24) if abs(vals[h]) > 1e-9
    ])
    if not long.empty:
        base = alt.Chart(long).mark_bar().encode(
            x=alt.X("Hour:O", title="Hour of day"),
            y=alt.Y("kW:Q", title="kW", stack="zero"),
            color=alt.Color("Source:N", legend=alt.Legend(orient="bottom")),
            tooltip=["Hour", "Source", alt.Tooltip("kW:Q", format=",.0f")],
        )
        line = alt.Chart(pd.DataFrame(
            {"Hour": list(range(1, 25)), "kW": s["load_kw"]}
        )).mark_line(color="#3B3B3B", strokeWidth=2, point=True).encode(
            x="Hour:O", y="kW:Q", tooltip=[alt.Tooltip("kW:Q", format=",.0f")])
        st.altair_chart(base + line, use_container_width=True)
        st.caption("Bars are supply by source; the dark line is site load.")

    st.markdown("**Monthly peak grid purchase**")
    st.dataframe(monthly_peak_frame(series), hide_index=True, width="stretch")
    st.caption(
        "A time-of-use demand charge bills the peak in each period of **each month**, "
        "so the sum of the twelve monthly peaks — not the single annual peak — is what "
        "the demand part of the bill tracks."
    )
