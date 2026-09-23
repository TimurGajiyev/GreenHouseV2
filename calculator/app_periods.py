"""Day / week / year views, and the hour-by-hour tables, in the profiling design.

The framing follows the summary tables in PROJECT_FULL §9.2 and §10.3 -- a
representative day, a week and the full year in one grid, so a reader can see
the same quantities at three time scales without switching pages. Row labels
stay in the REopt vocabulary used everywhere else on the results page.

The representative day is chosen the way PROJECT_FULL picks it: the day whose
total energy is closest to the median across the year, so it is typical rather
than extreme. The peak day is offered alongside because that is the one that
sets the demand charge.

Presentation comes from ``profile_ui`` (palette, table hierarchy, chart). This
module only aggregates an already-solved result: it reads ``res["series"]`` and
``res["sizes"]`` and sums them. No cost or energy is recomputed here, so the
REopt core is untouched.

Every table and every chart series is built by looping over the units the
result carries -- ``sizes["fueltech_units"]`` and ``sizes["storage_units"]`` --
so one generator, three generators or six all render without a code change.
"""

from __future__ import annotations

import calendar

import pandas as pd
import streamlit as st

import profile_ui as P
import ui_theme as T

HOURS = 8760            # a full REopt year; any horizon is accepted
DAYS = 365
MINUS = "−"        # true minus, as the reference uses for discharge


def horizon(series: dict) -> int:
    """Hours in this result. A REopt run is 8,760; a posed case can be shorter."""
    return len(series["load_kw"])


def _idx(n: int = HOURS) -> pd.DatetimeIndex:
    return pd.date_range("2017-01-01", periods=n, freq="h")


_CUR = "$"          # set per render; a custom study may price in any currency


def _m(x) -> str:
    if x is None:
        return "N/A"
    if _CUR == "$":
        return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"
    return f"{'-' if x < 0 else ''}{abs(x):,.0f} {_CUR}"


def _signed(x) -> str:
    """+1,234 / −1,234 in the current currency, as the reference writes savings."""
    body = _m(abs(x))
    return ("+" if x > 0.5 else ("−" if x < -0.5 else "")) + body


def _n(x) -> str:
    return f"{x:,.0f}"


def _daylabel(ts, weekday: bool = False) -> str:
    """Portable "3 May" / "Wednesday, 3 May".

    ``%-d`` is a glibc extension that Windows strftime rejects with
    "Invalid format string", so the day number is formatted separately.
    """
    day = f"{ts.day} {ts.strftime('%B')}"
    return f"{ts.strftime('%A')}, {day}" if weekday else day


def _daily_totals(series: list[float]) -> list[float]:
    n = len(series) // 24
    return [sum(series[d * 24:(d + 1) * 24]) for d in range(n)]


def representative_day(load: list[float]) -> int:
    """Day index whose energy is closest to the median day -- PROJECT_FULL's rule."""
    daily = _daily_totals(load)
    if not daily:
        return 0
    ordered = sorted(daily)
    med = ordered[len(ordered) // 2]
    return min(range(len(daily)), key=lambda d: abs(daily[d] - med))


def peak_day(load: list[float]) -> int:
    n = len(load) // 24
    if n == 0:
        return 0
    return max(range(n), key=lambda d: max(load[d * 24:(d + 1) * 24]))


def _slice(series: dict, start_h: int, n_h: int) -> dict:
    """Window of every hourly series, whatever the horizon."""
    H = horizon(series)
    out = {}
    for k, v in series.items():
        if isinstance(v, dict):
            out[k] = {name: s[start_h:start_h + n_h] for name, s in v.items()}
        elif isinstance(v, list) and len(v) == H:
            out[k] = v[start_h:start_h + n_h]
    return out


def _starts_in(on: list[float]) -> int:
    """Off->on transitions, counted cyclically like the unit-commitment block."""
    if not on:
        return 0
    n = len(on)
    return sum(1 for t in range(n) if on[t] > 0.5 and on[(t - 1) % n] <= 0.5)


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


def _period_block(series: dict, tariff, start_h: int, n_h: int, label: str,
                  sizes: dict | None = None) -> dict:
    """The metric set the reference summary carries, at one time scale.

    Mirrors `summaryTable` in bess_profile_v2.jsx: load, generation, charge,
    discharge, grid, peak, starts, spill, fleet running hours, grid share and
    battery cycles. The reference's cost rows are its own tenge tariff model;
    the cost row here is the one this calculator actually computes, the tariff
    energy charge.
    """
    s = _slice(series, start_h, n_h)
    grid = s["grid_kw"]
    gen = s["fueltech_kw"]
    load = s["load_kw"]
    dis = s["battery_discharge_kw"]
    out = {
        "Site load (kWh)": sum(load),
        "PV production (kWh)": sum(s["pv_to_load_kw"]) + sum(s.get("pv_curtailed_kw", [0])),
        "Fuel-fired production (kWh)": sum(gen),
        "Battery charged (kWh)": sum(s["battery_charge_kw"]),
        "Battery discharged (kWh)": sum(dis),
        "Grid purchase (kWh)": sum(grid),
    }
    spill = sum(sum(v) for v in (s.get("fueltech_unit_spill_kw") or {}).values())
    if spill > 1e-6:
        out["Spill (kWh)"] = spill
    if sum(s.get("unserved_kw", [0])) > 1e-6:
        out["Unserved load (kWh)"] = sum(s["unserved_kw"])

    out["Peak grid purchase (kW)"] = max(grid) if grid else 0.0
    out["Grid share of load (%)"] = (100.0 * sum(grid) / sum(load)) if sum(load) > 0 else 0.0

    units = s.get("fueltech_unit_kw") or {}
    if units:
        out["Fleet running hours"] = float(sum(
            1 for v in units.values() for x in v if x > 1e-6))
    on = s.get("fueltech_unit_on") or {}
    if on:
        out["Starts"] = float(sum(_starts_in(v) for v in on.values()))
    # a full cycle is one pass through the installed energy capacity
    cap = sum(b["energy_kwh"] for b in ((sizes or {}).get("storage_units") or []))
    if cap > 1e-6:
        out["Battery full cycles"] = sum(dis) / cap
        # The reference carries a SoC correction because a window that ends
        # fuller than it started has been subsidised by stored energy. The SOC
        # balance here wraps cyclically (model.py:472), so over the full year
        # this is exactly zero; inside a day or a week it is not, and the row
        # says by how much the window is flattered or penalised.
        soc = series["soc_kwh"]
        H = len(soc)
        out["Battery SOC carried (kWh)"] = soc[(start_h + n_h - 1) % H] - soc[(start_h - 1) % H]

    if tariff is not None:
        e = sum(tariff.energy_cost_per_kwh[start_h + h] * grid[h] for h in range(n_h))
        out["Energy charge ($)"] = e
    return out


def period_frame(series: dict, tariff, rep_day: int, sizes: dict | None = None) -> pd.DataFrame:
    """Representative day / week containing it / whole horizon, side by side."""
    H = horizon(series)
    week_start = (rep_day // 7) * 7 * 24
    blocks = [
        ("Representative day", _period_block(series, tariff, rep_day * 24,
                                             min(24, H), "day", sizes)),
        ("Week", _period_block(series, tariff, week_start,
                               min(168, H - week_start), "week", sizes)),
        (("Year" if H == HOURS else "Horizon"),
         _period_block(series, tariff, 0, H, "horizon", sizes)),
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
            elif k.endswith("(%)") or k == "Battery full cycles":
                row[name] = f"{val:,.1f}"
            else:
                row[name] = f"{val:,.0f}"
        rows.append(row)
    return pd.DataFrame(rows)


def monthly_peak_frame(series: dict) -> pd.DataFrame | None:
    """Peak grid purchase per month -- the quantity a demand charge bills on.

    Only a full calendar year has twelve months to bill, so a shorter horizon
    returns None and the section is skipped.
    """
    if horizon(series) != HOURS:
        return None
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


def starts_matrix(units: list[dict], n_days: int) -> list[list[int]] | None:
    """Per unit, starts in each calendar day of the horizon.

    The core already counts this (``starts_by_day`` per unit, one entry per
    calendar day of whatever horizon was solved) and the year path recounts it
    over the replayed year; nothing is recomputed here. ``None`` when no unit
    tracks starts at all -- a run with no commitment has none to show.

    A unit's list is padded or trimmed to ``n_days`` so a horizon that does not
    divide into whole days still lines up with the day columns.
    """
    if not any(u.get("starts_by_day") for u in units):
        return None
    out = []
    for u in units:
        by_day = list(u.get("starts_by_day") or [])
        by_day = (by_day + [0] * n_days)[:n_days]
        out.append([int(v or 0) for v in by_day])
    return out


def starts_by_weekday(mat: list[list[int]], idx: pd.DatetimeIndex) -> list[list[int]]:
    """The same counts folded onto Monday..Sunday.

    For a horizon of many days the per-day table stops fitting, and the useful
    question becomes how often a given unit starts on a given weekday. The
    weekday comes from the same index every other view here uses.
    """
    out = [[0] * 7 for _ in mat]
    for i, row in enumerate(mat):
        for d, n in enumerate(row):
            if d * 24 < len(idx):
                out[i][idx[d * 24].weekday()] += n
    return out


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


# --------------------------------------------------- the profiling layout
def _shape(res: dict) -> dict:
    """What this result actually contains -- drives every column set below."""
    sizes, series = res["sizes"], res["series"]
    units = [u for u in (sizes.get("fueltech_units") or []) if u["size_kw"] > 1e-6]
    banks = [b for b in (sizes.get("storage_units") or []) if b["energy_kwh"] > 1e-6]
    per_unit = series.get("fueltech_unit_kw") or {}
    return {
        "units": units,
        "names": [u["name"] for u in units],
        "series": [per_unit.get(u["name"], [0.0] * horizon(series)) for u in units],
        "on": [(series.get("fueltech_unit_on") or {}).get(u["name"]) for u in units],
        "spill": [(series.get("fueltech_unit_spill_kw") or {}).get(u["name"]) for u in units],
        "banks": banks,
        "cap_kwh": sum(b["energy_kwh"] for b in banks),
        "nameplate_kw": sum(u["size_kw"] for u in units),
        "pv": sizes.get("pv_kw", 0.0) > 1e-6,
        "any_spill": any(u.get("spill_kwh", 0.0) > 1e-6 for u in units),
        "any_maint": any(u.get("maintenance_hours") is not None for u in units),
        "any_maint_interval": any(u.get("maintenance_trigger") == "running_hours"
                                  for u in units),
        "any_on": bool(series.get("fueltech_unit_on")),
        "any_unserved": sum(series.get("unserved_kw") or [0.0]) > 1e-6,
        "any_export": sum(series.get("export_kw") or [0.0]) > 1e-6,
    }


def _headline(sh: dict, res: dict) -> tuple[str, str]:
    """Panel title and the mono strapline, both built from the fleet itself."""
    units, banks = sh["units"], sh["banks"]
    if units:
        kinds = {u["kind"] for u in units}
        kind = kinds.pop() if len(kinds) == 1 else "unit"
        title = f"{len(units)} × {kind}" if len(units) > 1 else kind
        parts = [f"{u['name']} {u['size_kw']:,.0f}" for u in units]
        strap = " + ".join(parts)
        if len(units) > 1:
            strap += f" = {sh['nameplate_kw']:,.0f} kW"
        else:
            strap += " kW"
    else:
        title = "Dispatch"
        strap = ""
    extra = []
    if sh["pv"]:
        extra.append(f"PV {res['sizes']['pv_kw']:,.0f} kW")
    for b in banks:
        extra.append(f"{b['name']} {b['power_kw']:,.0f} kW / {b['energy_kwh']:,.0f} kWh")
    if extra:
        strap = (strap + " · " if strap else "") + " · ".join(extra)
    return title, strap


def _window_rows(series: dict, sh: dict, start_h: int, n_h: int) -> list[dict]:
    """One dict per hour of the window, with a column per unit."""
    s = _slice(series, start_h, n_h)
    out = []
    for h in range(n_h):
        r = {
            "load": s["load_kw"][h],
            "pv": s["pv_to_load_kw"][h],
            "grid": s["grid_kw"][h],
            "ch": s["battery_charge_kw"][h],
            "dis": s["battery_discharge_kw"][h],
            "soc": s["soc_kwh"][h],
            "units": [(s.get("fueltech_unit_kw") or {}).get(nm, [0.0] * n_h)[h]
                      for nm in sh["names"]],
            "spill": [(s.get("fueltech_unit_spill_kw") or {}).get(nm, [0.0] * n_h)[h]
                      for nm in sh["names"]],
            "on": [(s.get("fueltech_unit_on") or {}).get(nm, [0.0] * n_h)[h]
                   for nm in sh["names"]],
            "unserved": (s.get("unserved_kw") or [0.0] * n_h)[h],
            "export": (s.get("export_kw") or [0.0] * n_h)[h],
        }
        out.append(r)
    return out


def _hour_head(sh: dict, *lead: str) -> list[str]:
    head = [*lead, "LOAD"]
    head += [nm.upper() for nm in sh["names"]]
    if sh["pv"]:
        head.append("PV")
    if sh["banks"]:
        head += ["CHARGE +", "DISCHARGE " + MINUS]
    head.append("GRID")
    if sh["banks"]:
        head.append("SOC %" if sh["cap_kwh"] > 0 else "SOC kWh")
    if sh["any_on"]:
        head.append("ON")          # units running -- the reference's `uon`
    if sh["any_spill"]:
        head.append("SPILL")
    if sh["any_export"]:
        head.append("EXPORT")
    if sh["any_unserved"]:
        head.append("UNSERVED")
    return head


def _hour_row(r: dict, sh: dict, *lead: str) -> list:
    row = [*lead, _n(r["load"])]
    row += [_n(v) for v in r["units"]]
    if sh["pv"]:
        row.append(_n(r["pv"]))
    if sh["banks"]:
        row.append(_n(r["ch"]))
        row.append((MINUS + _n(r["dis"]), "ghp-neg") if r["dis"] > 0.5 else "0")
    row.append(_n(r["grid"]))
    if sh["banks"]:
        row.append(f"{r['soc'] / sh['cap_kwh'] * 100:,.1f}" if sh["cap_kwh"] > 0
                   else _n(r["soc"]))
    if sh["any_on"]:
        row.append(str(int(sum(1 for v in r["on"] if v > 0.5))))
    if sh["any_spill"]:
        row.append(_n(sum(r["spill"])) if sum(r["spill"]) > 0.5 else "—")
    if sh["any_export"]:
        row.append(_n(r["export"]) if r["export"] > 0.5 else "—")
    if sh["any_unserved"]:
        row.append((_n(r["unserved"]), "ghp-neg") if r["unserved"] > 0.5 else "—")
    return row


def _hour_foot(rows: list[dict], sh: dict, label: str = "Total",
               pad: int = 0) -> list:
    tot = lambda k: sum(r[k] for r in rows)
    foot = [label, *([""] * pad), _n(tot("load"))]
    foot += [_n(sum(r["units"][j] for r in rows)) for j in range(len(sh["names"]))]
    if sh["pv"]:
        foot.append(_n(tot("pv")))
    if sh["banks"]:
        foot.append(_n(tot("ch")))
        foot.append(MINUS + _n(tot("dis")))
    foot.append(_n(tot("grid")))
    if sh["banks"]:
        foot.append(f"{rows[-1]['soc'] / sh['cap_kwh'] * 100:,.1f}" if sh["cap_kwh"] > 0
                    else _n(rows[-1]["soc"]))
    if sh["any_on"]:
        # unit-hours over the window, the total the "ON" column sums to
        foot.append(str(int(sum(1 for r in rows for v in r["on"] if v > 0.5))))
    if sh["any_spill"]:
        foot.append(_n(sum(sum(r["spill"]) for r in rows)))
    if sh["any_export"]:
        foot.append(_n(tot("export")))
    if sh["any_unserved"]:
        foot.append(_n(tot("unserved")))
    return foot


def _summary_table(series: dict, tariff, rep_day: int, sh: dict,
                   res_sizes: dict | None = None) -> None:
    """Metric × day / week / horizon, grouped into sections like the reference."""
    H = horizon(series)
    df = period_frame(series, tariff, rep_day, res_sizes)
    cols = [c for c in df.columns if c != "Metric"]
    # the reference's summary order: load, generation, charge, discharge, grid,
    # then peak and the operating counters, then cost
    groups = {
        "Energy": ["Site load (kWh)", "PV production (kWh)", "Fuel-fired production (kWh)",
                   "Battery charged (kWh)", "Battery discharged (kWh)",
                   "Grid purchase (kWh)", "Spill (kWh)", "Unserved load (kWh)"],
        "Power and operation": ["Peak grid purchase (kW)", "Grid share of load (%)",
                                "Fleet running hours", "Starts", "Battery full cycles",
                                "Battery SOC carried (kWh)"],
        "Cost": ["Energy charge ($)"],
    }
    rows, sections, seen = [], {}, set()
    for sec, keys in groups.items():
        first = True
        for k in keys:
            hit = df[df["Metric"] == k]
            if hit.empty:
                continue
            if first:
                sections[len(rows)] = sec
                first = False
            v = hit.iloc[0]
            seen.add(k)
            cells = [v["Metric"]]
            for c in cols:
                cells.append((v[c], "ghp-key") if k == "Site load (kWh)" else v[c])
            rows.append(cells)
    for _, v in df.iterrows():          # anything a future field adds
        if v["Metric"] not in seen:
            rows.append([v["Metric"]] + [v[c] for c in cols])
    last = f"YEAR, 8,760 H" if H == HOURS else f"HORIZON, {H:,} H"
    head = ["METRIC", "REPRESENTATIVE DAY", "WEEK", last]
    if H <= 168:                       # a week or less: the middle column repeats the whole
        head, rows = ([head[0], head[1], last],
                      [[r[0], r[1], r[3]] for r in rows])
    P.table(head, rows, sections=sections)


_WD = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _starts_section(sh: dict, series: dict, idx: pd.DatetimeIndex, res: dict) -> None:
    """Starts per unit AND per day -- the one cut the other tables do not make.

    The unit table above totals each unit's starts over the whole horizon; the
    summary table splits starts by day, week and horizon but sums the fleet.
    Neither answers "how many times did this particular engine start on this
    particular day", which is the number an OEM maintenance plan is written
    against. The core already carries it per unit (``starts_by_day``); this only
    lays it out.

    A day column up to a month, a weekday fold beyond that -- 365 columns is
    not a table anyone reads, and by then the useful question is which weekday
    a unit keeps cycling on.
    """
    H = horizon(series)
    ndays = max(1, -(-H // 24))
    mat = starts_matrix(sh["units"], ndays)
    if mat is None or ndays < 2:
        return                      # a single-day run: the unit total IS the day
    names, n_units = sh["names"], len(sh["units"])
    colors = [P.unit_color(i) for i in range(n_units)]
    totals = [sum(r) for r in mat]

    P.sub("Starts by unit and day")

    st.altair_chart(
        P.starts_chart(list(range(1, ndays + 1)),
                       [_daylabel(idx[d * 24], weekday=True) for d in range(ndays)],
                       list(zip(names, colors, mat))),
        use_container_width=True)
    P.legend(list(zip(names, colors)))

    if ndays <= 31:
        head = ["UNIT"] + [f"{_WD[idx[d * 24].weekday()]} {idx[d * 24].day}"
                           for d in range(ndays)] + ["TOTAL"]
        body = [[names[i]] + [(f"{v:,}", "ghp-neg") if v else "—" for v in mat[i]]
                + [(f"{totals[i]:,}", "ghp-key")] for i in range(n_units)]
        foot = ["Fleet"] + [f"{sum(mat[i][d] for i in range(n_units)):,}"
                            for d in range(ndays)] + [f"{sum(totals):,}"]
        P.table(head, body, foot)
    else:
        wk = starts_by_weekday(mat, idx)
        head = ["UNIT"] + _WD + ["TOTAL", "PER DAY", "BUSIEST DAY"]
        body = []
        for i in range(n_units):
            worst = max(mat[i]) if mat[i] else 0
            when = (_daylabel(idx[mat[i].index(worst) * 24]) if worst else "—")
            body.append([names[i]] + [f"{v:,}" if v else "—" for v in wk[i]]
                        + [(f"{totals[i]:,}", "ghp-key"),
                           f"{totals[i] / ndays:,.2f}",
                           f"{worst:,} · {when}" if worst else "—"])
        foot = (["Fleet"]
                + [f"{sum(wk[i][d] for i in range(n_units)):,}" for d in range(7)]
                + [f"{sum(totals):,}", f"{sum(totals) / ndays:,.2f}",
                   f"{max((max(mat[i]) for i in range(n_units)), default=0):,}"])
        P.table(head, body, foot)

    bits = [f"{ndays:,} days", "off-to-on transitions, counted cyclically so a unit "
            "already running at hour 0 is not charged a start on day 0"]
    if ndays > 31:
        bits.insert(1, "folded onto weekdays because the horizon is longer than a month")
    if res.get("typical"):
        t = res["typical"]
        bits.append(f"the year is replayed from {t['k']} typical days, so the per-day "
                    f"pattern repeats them and the count is a lower bound "
                    f"({t.get('starts_from_joins', 0):,} of {sum(totals):,} come from "
                    f"the joins between unlike days)")
    st.caption("Starts per unit per day — " + "; ".join(bits) + ".")


# ----------------------------------------------------------------- render
def render_periods(state: dict) -> None:
    global _CUR
    _CUR = state.get("currency") or "$"
    res = state["res"]
    series = res.get("series") or {}
    if not series:
        return
    tariff = state.get("tariff")
    load = series["load_kw"]
    sh = _shape(res)
    idx = _idx(horizon(series))
    rep, pk = representative_day(load), peak_day(load)

    T.panel_head("Dispatch by period", icon="calendar_month")

    # ---- switches -------------------------------------------------------
    # Each switch is drawn only where it has something to switch between. They
    # used to be drawn always and then overruled a line later, so on a
    # single-day run -- which is what the dispatch study loads by default --
    # both took the click, showed themselves pressed, and changed nothing.
    #
    #   period   needs more than a day, or "Week" shows the same hours again
    #   day      needs two whole days, or both positions land on day 0
    H = horizon(series)
    period, day = "Day", 0
    show_period, show_day = H > 24, H // 24 >= 2
    if show_period or show_day:
        c1, c2 = st.columns([1, 1])
        with c1:
            if show_period:
                period = P.switch("Period", ["Day", "Week"], key="ghp_period")
        with c2:
            if show_day:
                which = P.switch("Day", ["Representative day", "Peak day"], key="ghp_day")
                day = rep if which == "Representative day" else pk
    else:
        P.note([f"A horizon of <b>{H}</b> hours is a single day: no other day to "
                f"choose, and no week to widen to."])

    if period == "Day":
        start, n_h = day * 24, min(24, H)
        hours = list(range(1, n_h + 1))
        labels = [f"{_daylabel(idx[start])} · {h:02d}:00" for h in range(n_h)]
        when = _daylabel(idx[start], weekday=True)
    else:
        start = (day // 7) * 7 * 24
        n_h = min(168, H - start)
        hours = list(range(1, n_h + 1))
        labels = [f"{_daylabel(idx[start + h])} · {idx[start + h].hour:02d}:00"
                  for h in range(n_h)]
        when = (f"{_daylabel(idx[start])} to {_daylabel(idx[start + n_h - 1])}")

    rows = _window_rows(series, sh, start, n_h)

    # ---- savings against a base scenario (custom dispatch study) --------
    # state["savings"]: per-hour money of the base minus this run, split as
    # the reference splits it -- energy (smooth, drawn as the veil) and
    # starts plus wear (lumpy, tooltip and totals only) -- plus the SoC each
    # run leaves in the battery, valued at the grid price it will displace.
    sav = state.get("savings")
    veil = save_e = save_s = None
    if sav:
        save_e = sav["save_e"][start:start + n_h]
        save_s = sav["save_s"][start:start + n_h]
        veil = [x / sav["spread"] for x in save_e]

        def _dsoc(soc: list[float], soc0: float) -> float:
            if not soc:
                return 0.0
            before = soc[start - 1] if start > 0 else soc0
            return soc[start + n_h - 1] - before

        d_soc = _dsoc(sav["soc_cur"], sav["soc0_cur"]) - _dsoc(sav["soc_base"], sav["soc0_base"])
        soc_corr = d_soc * sav["eta"] * sav["price_mean"]
        st_cur = sum(sav["starts_cur"][start:start + n_h])
        st_base = sum(sav["starts_base"][start:start + n_h])
        e_tot, s_tot = sum(save_e), sum(save_s)
        sav_total = e_tot + s_tot + soc_corr

    # ---- panel: header, chart, stat strip ------------------------------
    title, strap = _headline(sh, res)
    P.panel_head(title, strap)

    stack = [(nm, P.unit_color(j), [r["units"][j] for r in rows])
             for j, nm in enumerate(sh["names"])]
    if sh["pv"]:
        stack.append(("PV", P.PV_COLOR, [r["pv"] for r in rows]))
    stack.append(("Grid", P.GRID_COLOR, [r["grid"] for r in rows]))

    # The reference's Tip component, hour by hour: one panel naming every
    # series, each figure in its series' colour. The row set is identical for
    # every hour -- a row that does not apply carries an em dash instead of
    # disappearing -- so the panel does not reflow under the pointer and
    # profile_ui can colour the figures by position, which is the only handle
    # CSS has on Vega's tooltip. The saving rows keep the reference's green
    # and carry their own sign; the veil under the load line is what shows an
    # hour that costs more.
    dash = "\u2014"

    def _tip_kw(v: float) -> str:
        return f"{v:,.0f} kW" if abs(v) > 0.5 else dash

    detail = []
    for i, r in enumerate(rows):
        d: list[tuple[str, str, str]] = [("Site load", f"{r['load']:,.0f} kW", P.INK)]
        if sh["units"]:
            d.append(("Fleet output", _tip_kw(sum(r["units"])), P.MUTED))
            for j, nm in enumerate(sh["names"]):
                share = 100.0 * r["units"][j] / r["load"] if r["load"] > 1e-9 else 0.0
                d.append((f"  {nm}",
                          (f"{r['units'][j]:,.0f} kW \u00b7 {share:.0f}%"
                           if r["units"][j] > 0.5 else dash),
                          P.unit_color(j)))
        if sh["pv"]:
            d.append(("PV", _tip_kw(r["pv"]), P.PV_COLOR))
        if sh["banks"]:
            d.append(("Battery charge",
                      f"+{r['ch']:,.0f} kW" if r["ch"] > 0.5 else dash, P.CHARGE))
            d.append(("Battery discharge",
                      f"\u2212{r['dis']:,.0f} kW" if r["dis"] > 0.5 else dash, P.DISCHARGE))
        d.append(("Grid purchase", _tip_kw(r["grid"]), P.GRID_COLOR))
        if sh["any_spill"]:
            d.append(("Spill", _tip_kw(sum(r["spill"])), P.DISCHARGE))
        if sh["any_unserved"]:
            d.append(("Unserved", _tip_kw(r["unserved"]), P.DISCHARGE))
        if sh["any_on"]:
            prev = rows[i - 1]["on"] if i else rows[-1]["on"]
            started = sum(1 for j, v in enumerate(r["on"]) if v > 0.5 and prev[j] <= 0.5)
            d.append(("Units running",
                      f"{sum(1 for v in r['on'] if v > 0.5)} of {len(sh['names'])}", P.MUTED))
            d.append(("Starts this hour", str(started) if started else dash, P.DISCHARGE))
        if sh["banks"]:
            soc = (r["soc"] / sh["cap_kwh"] * 100.0) if sh["cap_kwh"] > 0 else r["soc"]
            d.append(("State of charge", f"{soc:,.1f}%", P.MUTED))
        if sav:
            # The reference greens these two. It can afford to: it colours each
            # figure as it writes it, so a negative hour comes out peach. Here
            # the colour is set in CSS by row position and cannot change with
            # the sign, and a loss printed in green would be a lie, so the
            # figures stay in ink. The sign is on the number, and the veil
            # under the load line is green or peach for that same hour.
            d.append(("Saving, energy", _signed(save_e[i]), P.INK))
            d.append(("Saving, starts and wear",
                      _signed(save_s[i]) if abs(save_s[i]) > 0.5 else dash, P.INK))
        detail.append(d)

    st.altair_chart(
        P.dispatch_chart(
            hours, labels, stack,
            [r["load"] for r in rows], [r["ch"] for r in rows], [r["dis"] for r in rows],
            ceiling_kw=(sh["nameplate_kw"] if sh["units"] else None),
            week=(period == "Week"), detail=detail, veil=veil,
        ),
        use_container_width=True,
    )

    charged = sum(r["ch"] for r in rows)
    discharged = sum(r["dis"] for r in rows)
    grid_kwh = sum(r["grid"] for r in rows)
    peak_grid = max((r["grid"] for r in rows), default=0.0)
    idle = sum(1 for r in rows if r["ch"] <= 0.5 and r["dis"] <= 0.5)
    e_charge = None
    if tariff is not None:
        e_charge = sum(tariff.energy_cost_per_kwh[start + h] * rows[h]["grid"]
                       for h in range(n_h))

    # the reference's six: charge, discharge, grid, peak, idle, money.
    # With no battery those three cells have nothing to say, so the fuel-fired
    # figures take their place rather than leaving the strip half empty.
    cells = []
    if sh["banks"]:
        cells += [("Battery charged", f"{charged:,.0f} kWh"),
                  ("Battery discharged", f"{discharged:,.0f} kWh")]
    elif sh["units"]:
        fuel = sum(sum(r["units"]) for r in rows)
        run = sum(1 for r in rows for v in r["units"] if v > 0.5)
        cells += [("Fuel-fired", f"{fuel:,.0f} kWh"),
                  ("Unit-hours", f"{run:,} of {n_h * len(sh['names']):,}")]
    cells += [("Grid purchase", f"{grid_kwh:,.0f} kWh"),
              ("Peak grid purchase", f"{peak_grid:,.0f} kW")]
    if sh["banks"]:
        cells.append(("Battery idle", f"{idle} of {n_h} h"))
    elif sh["units"]:
        cells.append(("Fuel share of load",
                      f"{100.0 * sum(sum(r['units']) for r in rows) / max(1e-9, sum(r['load'] for r in rows)):,.1f}%"))
    if sav:
        # the reference's last cell: the whole saving of the window
        key = f"Saving vs {sav['base']}"
        cells.append((key, (f'<span class="{"ghp-pos" if sav_total >= 0 else "ghp-neg"}">'
                            f'{_signed(sav_total)}</span>')))
        P.stat_strip(cells, highlight={key})
    else:
        cells.append(("Energy charge", _m(e_charge) if e_charge is not None else "—"))
        P.stat_strip(cells, highlight={"Energy charge"})

    bits = [f"{when}"]
    if sh["units"]:
        run = sum(1 for r in rows for v in r["units"] if v > 0.5)
        starts = sum(_starts_in([r["on"][j] for r in rows])
                     for j in range(len(sh["names"])))
        bits.append(f"unit-hours <b>{run:,}</b> of {n_h * len(sh['names']):,}")
        if any(o is not None for o in sh["on"]):
            bits.append(f"starts in window <b>{starts}</b>")
    # only report these when the shown window actually has them; the column
    # stays because the run as a whole does
    sp = sum(sum(r["spill"]) for r in rows)
    if sp > 0.5:
        bits.append(f'spill <b class="ghp-neg">{sp:,.0f} kWh</b>')
    un = sum(r["unserved"] for r in rows)
    if un > 0.5:
        bits.append(f'unserved <b class="ghp-neg">{un:,.0f} kWh</b>')
    P.note(bits)
    if sav:
        cls = lambda v: "ghp-pos" if v >= 0 else "ghp-neg"
        P.note([
            f'vs <b>{sav["base"]}</b>',
            f'energy <b class="{cls(e_tot)}">{_signed(e_tot)}</b>',
            f'starts {st_cur} vs {st_base} and wear <b class="{cls(s_tot)}">{_signed(s_tot)}</b>',
            f'SoC correction {d_soc:+,.0f} kWh <b class="{cls(soc_corr)}">{_signed(soc_corr)}</b>',
            f'veil height = saving / {sav["spread"]:,.0f} {_CUR}/kWh spread',
        ])

    leg = [(nm, P.unit_color(j)) for j, nm in enumerate(sh["names"])]
    if sh["pv"]:
        leg.append(("PV", P.PV_COLOR))
    leg.append(("Grid", P.GRID_COLOR))
    if sh["banks"]:
        leg += [("Battery charge", P.CHARGE), ("Battery discharge", P.DISCHARGE)]
    leg.append(("Site load", P.INK))
    P.legend(leg)

    # ---- hour by hour ---------------------------------------------------
    if period == "Day":
        P.sub(f"Hour by hour · {when}")
        P.table(_hour_head(sh, "HOUR"),
                [_hour_row(r, sh, f"{h}") for h, r in zip(hours, rows)],
                _hour_foot(rows, sh))
    else:
        P.sub(f"Day by day · {when}")
        drows, dfoot = [], []
        for d in range(n_h // 24):
            blk = rows[d * 24:(d + 1) * 24]
            ts = idx[start + d * 24]
            agg = {
                "load": sum(r["load"] for r in blk),
                "pv": sum(r["pv"] for r in blk),
                "grid": sum(r["grid"] for r in blk),
                "ch": sum(r["ch"] for r in blk),
                "dis": sum(r["dis"] for r in blk),
                "soc": blk[-1]["soc"],
                "units": [sum(r["units"][j] for r in blk) for j in range(len(sh["names"]))],
                "spill": [sum(r["spill"][j] for r in blk) for j in range(len(sh["names"]))],
                "on": blk[-1]["on"],
                "unserved": sum(r["unserved"] for r in blk),
                "export": sum(r["export"] for r in blk),
            }
            row = _hour_row(agg, sh, ts.strftime("%a %d %b"))
            row.append(_n(max(r["grid"] for r in blk)))
            if any(o is not None for o in sh["on"]):
                row.append(str(sum(_starts_in([r["on"][j] for r in blk])
                                   for j in range(len(sh["names"])))))
            drows.append(row)
        head = _hour_head(sh, "DAY") + ["PEAK GRID"]
        foot = _hour_foot(rows, sh) + [_n(max(r["grid"] for r in rows))]
        if any(o is not None for o in sh["on"]):
            head.append("STARTS")
            foot.append(str(sum(_starts_in([r["on"][j] for r in rows])
                                for j in range(len(sh["names"])))))
        P.table(head, drows, foot)

        with st.expander(f"All {n_h} hours", expanded=False):
            P.table(_hour_head(sh, "DAY", "HOUR"),
                    [_hour_row(r, sh, idx[start + h].strftime("%a"), str(h % 24 + 1))
                     for h, r in enumerate(rows)],
                    _hour_foot(rows, sh, pad=1), tall=True)

    # ---- summary across the three time scales ---------------------------
    P.sub("Summary")
    _summary_table(series, tariff, rep, sh, res["sizes"])
    st.caption(
        f"The representative day is the one whose energy is closest to the median "
        f"across the year — {_daylabel(idx[rep * 24])}. The week is the calendar "
        f"week containing it."
    )

    # ---- per-unit tables, one row per unit however many there are -------
    if sh["units"]:
        P.sub("Fuel-fired units")
        u0 = sh["units"][0]
        head = ["UNIT", "TYPE", "SIZE kW", "PRODUCTION kWh", "CAPACITY FACTOR",
                "RUNNING HOURS", f"FUEL {u0['fuel_unit_name'].upper()}"]
        show_starts = any(u.get("starts") is not None for u in sh["units"])
        show_spill = sh["any_spill"]
        show_maint = sh["any_maint"]
        if show_spill:
            head.append("SPILL kWh")
        if show_starts:
            head.append("STARTS")
        if show_maint:
            # The complaint this answers: a RUNNING HOURS of 8,760 is only
            # believable next to the services that made room for it.
            head += ["SERVICES", "SERVICE H", "AVAILABILITY"]
            if sh["any_maint_interval"]:
                # on the running-hours trigger the count is an OUTCOME, so the
                # interval it came from and the hours still banked are the two
                # numbers that explain it
                head += ["EVERY RUN H", "BANKED H"]
        body = []
        for u in sh["units"]:
            r = [u["name"], u["kind"], _n(u["size_kw"]), _n(u["energy_kwh"]),
                 f"{u['capacity_factor']:.1%}", f"{u['running_hours']:,}",
                 _n(u["fuel_units"])]
            if show_spill:
                r.append((_n(u.get("spill_kwh", 0.0)), "ghp-neg")
                         if u.get("spill_kwh", 0.0) > 0.5 else "—")
            if show_starts:
                r.append(f"{u['starts']:,}" if u.get("starts") is not None else "—")
            if show_maint:
                mh = u.get("maintenance_hours")
                ev = u.get("maintenance_starts")
                if mh is None:
                    r += ["—", "—", "—"]
                else:
                    r += [f"{len(ev or []):,}", (f"{mh:,.0f}", "ghp-neg"),
                          f"{100 * (1 - mh / horizon(series)):.2f}%"]
                if sh["any_maint_interval"]:
                    iv, bk = u.get("maintenance_interval_running_hours"),                         u.get("maintenance_hours_banked")
                    r += [f"{iv:,.0f}" if iv else "—",
                          f"{bk:,.0f}" if bk is not None else "—"]
            body.append(r)
        foot = ["Fleet", "", _n(sh["nameplate_kw"]),
                _n(sum(u["energy_kwh"] for u in sh["units"])), "",
                f"{sum(u['running_hours'] for u in sh['units']):,}",
                _n(sum(u["fuel_units"] for u in sh["units"]))]
        if show_spill:
            foot.append(_n(sum(u.get("spill_kwh", 0.0) for u in sh["units"])))
        if show_starts:
            foot.append(f"{sum(u['starts'] or 0 for u in sh['units']):,}")
        if show_maint:
            _mh = sum(u.get("maintenance_hours") or 0.0 for u in sh["units"])
            _ev = sum(len(u.get("maintenance_starts") or []) for u in sh["units"])
            _cap = horizon(series) * len(sh["units"])
            foot += [f"{_ev:,}", f"{_mh:,.0f}",
                     f"{100 * (1 - _mh / _cap):.2f}%" if _cap else "—"]
            if sh["any_maint_interval"]:
                foot += ["", ""]
        P.table(head, body, foot)
        if show_maint:
            st.caption(
                ("Services are triggered by RUNNING hours, the way a gas engine's "
                 "plan is actually written: the count is an outcome of how much each "
                 "unit ran, EVERY RUN H is the interval and BANKED H is what stood on "
                 "the clock at the end of the horizon. A unit that never runs is never "
                 "serviced."
                 if sh["any_maint_interval"] else
                 "Services are scheduled by the optimiser as a fixed count per horizon "
                 "(PyPSA's formulation: a count, a duration, and the capacity the "
                 "service takes away) — a proxy for an interval that is really written "
                 "in RUNNING hours, so a unit that never runs still gets serviced. "
                 "Set a running-hour interval per unit to trigger on actual hours.")
                + " A full outage is recorded as off, so the restart after it counts as "
                  "a start — which is what it is."
            )

        _starts_section(sh, series, idx, res)

    if sh["banks"]:
        P.sub("Battery units")
        # the model sums throughput over the whole horizon, so the label has to
        # say which horizon that is -- "/yr" is only true for a full year
        _sfx = "/YR" if horizon(series) == HOURS else f"/{horizon(series):,}H"
        P.table(["UNIT", "POWER kW", "ENERGY kWh", "DURATION H",
                 f"DISCHARGED kWh{_sfx}", f"FULL CYCLES{_sfx}"],
                [[b["name"], _n(b["power_kw"]), _n(b["energy_kwh"]),
                  f"{b['duration_hours']:,.2f}", _n(b["throughput_kwh"]),
                  _n(b["full_cycles"])] for b in sh["banks"]],
                ["Bank", _n(sum(b["power_kw"] for b in sh["banks"])),
                 _n(sh["cap_kwh"]), "",
                 _n(sum(b["throughput_kwh"] for b in sh["banks"])), ""])

    # ---- monthly peaks --------------------------------------------------
    mf = monthly_peak_frame(series)
    if mf is None:
        return
    P.sub("Monthly peak grid purchase")
    P.table(["MONTH", "PEAK GRID PURCHASE kW", "GRID ENERGY kWh"],
            [[r["Month"], r["Peak grid purchase (kW)"], r["Grid energy (kWh)"]]
             for _, r in mf.iloc[:-1].iterrows()],
            [mf.iloc[-1]["Month"], mf.iloc[-1]["Peak grid purchase (kW)"],
             mf.iloc[-1]["Grid energy (kWh)"]])
    st.caption(
        "A time-of-use demand charge bills the peak in each period of **each month**, "
        "so the sum of the twelve monthly peaks — not the single annual peak — is what "
        "the demand part of the bill tracks."
    )
