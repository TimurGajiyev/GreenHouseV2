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
from reopt_core import model as M
from reopt_core.tariff import flat_tariff

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSX = os.path.join(ROOT, "bess_profile_v2.jsx")
MAX_H = 8760

# column names of the two editable tables
U_NAME, U_KW, U_COST, U_START = "Unit", "Rated kW", "Energy cost per kWh", "Start cost"
U_MIN, U_UP, U_DOWN, U_SPILL = "Min load %", "Min up h", "Min down h", "Spill allowed"
S_NAME, S_MIN, S_BAT, S_SCALE = "Scenario", "Min load % (blank = per unit)", "Battery", "Load scale %"

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
                          U_UP: 4, U_DOWN: 5, U_SPILL: True} for n, kw in JSX_UNITS[preset]])


def default_scenarios() -> pd.DataFrame:
    """The artifact's three rules, A / B / C."""
    return pd.DataFrame([
        {S_NAME: "A · free from 50%", S_MIN: 50.0, S_BAT: False, S_SCALE: 100.0},
        {S_NAME: "B · 90% rule", S_MIN: 90.0, S_BAT: False, S_SCALE: 100.0},
        {S_NAME: "C · 90% + battery", S_MIN: 90.0, S_BAT: True, S_SCALE: 100.0},
    ])


# ------------------------------------------------------------------ scenario
def build(load: list[float], price: list[float], units: pd.DataFrame, bat: dict,
          sc: dict) -> M.ScenarioInputs:
    """One scenario as model inputs. Finance off: the objective is operating cost."""
    scale = float(sc.get(S_SCALE) or 100.0) / 100.0
    loads = [x * scale for x in load]
    override = sc.get(S_MIN)
    override = None if override is None or (isinstance(override, float) and math.isnan(override)) \
        else float(override)
    fleet = []
    for _, u in units.iterrows():
        kw = float(u[U_KW] or 0.0)
        if kw <= 0:
            continue
        td = (override if override is not None else float(u[U_MIN] or 0.0)) / 100.0
        fleet.append(M.FuelTechInputs(
            enabled=True, kind="CHP", label="CHP", name=str(u[U_NAME] or f"Unit {len(fleet) + 1}"),
            installed_cost_per_kw=0.0, om_cost_per_kw=0.0, om_cost_per_kwh=float(u[U_COST] or 0.0),
            fuel_cost_per_mmbtu=0.0, electric_efficiency_full_load=0.35,
            thermal_efficiency_full_load=0.0,
            min_kw=kw, max_kw=kw, min_turn_down_fraction=td,
            start_cost=float(u[U_START] or 0.0),
            min_up_hours=max(1, int(u[U_UP] or 1)), min_down_hours=max(1, int(u[U_DOWN] or 1)),
            can_curtail=bool(u[U_SPILL]),
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
        compensation_type="no_compensation")


def account(res: dict, price: list[float], units: pd.DataFrame, wear: float) -> dict:
    """The operating cost, rebuilt line by line from the solution."""
    ser, sz = res["series"], res["sizes"]
    rows = sz.get("fueltech_units") or []
    cost_of = {str(u[U_NAME]): (float(u[U_COST] or 0.0), float(u[U_START] or 0.0))
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
    return dict(
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


def _compare(runs: list[dict], cur: str) -> None:
    head = ["Metric"] + [r["name"] for r in runs]
    acc = [r["acc"] for r in runs]
    base = acc[0]["total"]

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
        line("Unit-hours", "unit_hours", lambda v: f"{v:,.0f}"),
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
    rows.append(["Solver"] + [
        f"{a['status']}" + (f", gap {100 * a['gap']:.2f}%" if a.get("gap") is not None else "")
        for a in acc])
    P.table(head, rows, ["Operating cost"] + [money(a["total"]) for a in acc],
            sections={0: "Energy", 9: "Cost", 13: "Comparison"})


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
        sources = ["Upload hourly CSV"] + (["Example: bess_profile_v2.jsx day (24 h)",
                                            "Example: bess_profile_v2.jsx week (168 h)"] if ex else [])
        src = st.radio("Source", sources, index=1 if ex else 0, key="gd_src", horizontal=True)
        load: list[float] = []
        if src.startswith("Upload"):
            up = st.file_uploader("Hourly load, kW — one value per line or the first column of "
                                  "a CSV; any length from 24 to 8,760 hours",
                                  type=["csv", "txt"], key="gd_load_up")
            if up is not None:
                load = read_series(up)
        else:
            load = list(ex["day" if "day" in src else "week"])
        if load:
            n = len(load)
            c1, c2 = st.columns(2)
            with c1:
                start = int(st.number_input("Window start hour (0 = first)", 0, max(0, n - 1), 0,
                                            key="gd_start"))
            with c2:
                length = int(st.number_input("Window length (hours)", 1, min(MAX_H, n - start),
                                             min(MAX_H, n - start), key="gd_len"))
            load = load[start:start + length]
            st.caption(f"{len(load):,} hours · {sum(load):,.0f} kWh · peak {max(load):,.0f} kW "
                       f"· minimum {min(load):,.0f} kW")

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
                U_COST: st.column_config.NumberColumn(f"Energy cost ({cur}/kWh)", min_value=0.0,
                                                      help="Charged on rated output, spill included."),
                U_START: st.column_config.NumberColumn(f"Start cost ({cur})", min_value=0.0),
                U_MIN: st.column_config.NumberColumn(min_value=0.0, max_value=100.0,
                                                     help="Minimum load while running, % of rated."),
                U_UP: st.column_config.NumberColumn(min_value=1, step=1),
                U_DOWN: st.column_config.NumberColumn(min_value=1, step=1),
                U_SPILL: st.column_config.CheckboxColumn(
                    help="Output above the load may be spilled (paid for, not used)."),
            })
        st.caption("Each unit runs at a fixed nameplate: on/off, a minimum load while on, a "
                   "start cost, and minimum up and down times. Leave a row's rating at 0 to "
                   "drop it; an empty table means grid (and battery) only.")

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
            grid_charge = st.checkbox("Allow grid charging", value=False, key="gd_gridchg")
        with c4:
            soc_mode = st.radio("State of charge at the start",
                                ["Cyclic (end = start)", "Fixed"], key="gd_socmode")
            soc_init = st.number_input("Start SoC (%)", 0.0, 100.0, 50.0, step=5.0,
                                       key="gd_socinit", disabled=soc_mode != "Fixed")
        st.caption("Size is fixed; each scenario below switches the battery on or off.")
    bat = dict(kw=b_kw, kwh=b_kwh, rte=rte / 100.0, soc_min=soc_min / 100.0,
               soc_init=soc_init / 100.0, cyclic=soc_mode.startswith("Cyclic"),
               wear=wear, grid_charge=grid_charge)

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
                    min_value=1.0, step=5.0, help="Scales the whole load — for variability."),
            })
        st.caption("Each row is solved separately and compared side by side. The JSX's own "
                   "three rules are filled in; add rows to vary the load level, the minimum-load "
                   "rule or the battery.")
        c1, c2 = st.columns(2)
        with c1:
            tlim = st.number_input("Time limit per scenario (s)", 10, 3600, 120, step=10,
                                   key="gd_tlim")
        with c2:
            gap = st.number_input("Optimality gap (%)", 0.0, 10.0, 0.5, step=0.1, key="gd_gap")
        if len(load) > 168 and len(units.index):
            st.info(f"{len(load):,} hours with on/off units means "
                    f"{len(load) * len(units.index):,} commitment binaries per scenario; "
                    "expect the time limit to be reached and a small remaining gap.")

    # ---- run --------------------------------------------------------------------
    missing = []
    if not load:
        missing.append("hourly load")
    if scen is None or not len(scen.index):
        missing.append("at least one scenario")
    if missing:
        st.warning("Required: " + ", ".join(missing))
    if st.button("Solve scenarios", type="primary", disabled=bool(missing), key="gd_run"):
        runs = []
        prog = st.progress(0.0, text="Solving")
        rows = [r for r in scen.to_dict("records") if str(r.get(S_NAME) or "").strip()]
        try:
            for i, sc in enumerate(rows):
                prog.progress(i / len(rows), text=f"Solving {sc[S_NAME]} ({i + 1} of {len(rows)})")
                inp = build(load, price, units, bat, sc)
                t0 = time.time()
                res = M.solve(inp, time_limit=int(tlim), mip_gap=float(gap) / 100.0)
                acc = account(res, price, units, bat["wear"] if sc.get(S_BAT) else 0.0)
                acc["seconds"] = time.time() - t0
                runs.append({"name": str(sc[S_NAME]), "res": res, "tariff": inp.tariff, "acc": acc})
            prog.progress(1.0, text="Done")
            ss["gd_results"] = {"runs": runs, "currency": cur}
        except Exception as exc:  # show the real reason
            prog.empty()
            st.error(f"Run failed: {exc}")
            ss["gd_results"] = None

    # ---- results ----------------------------------------------------------------
    out = ss.get("gd_results")
    if not out:
        return
    runs, cur = out["runs"], out["currency"]
    T.panel_head("Scenario comparison")
    _compare(runs, cur)
    pick = P.switch("Scenario", [r["name"] for r in runs], key="gd_pick")
    run = next((r for r in runs if r["name"] == pick), runs[0])
    A.render_periods({"res": run["res"], "tariff": run["tariff"], "currency": cur})
