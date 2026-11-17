"""Battery payback study (rule-based): the page.

The inputs sit in the dispatch study's own panels and fields -- Engines and the rule,
Prices, Battery, Measured steps -- and nothing runs until Run scenario is pressed. The
results are the rule-based study's (payback_rule.py): three cards per plant with their
arithmetic, payback and profit by battery size, where the saving comes from, engine
starts, a day step by step, start wear and wear, then this project's own period view
(the meters as they ran, the battery under the rule hour by hour) and the inputs table.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, replace

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import payback_rule as T
import profile_ui as P
import ui_theme as UT

ss = st.session_state

# ---- palette (the dispatch study's ink, the chart series' own colours) ------------------
ACCENT, RED, INK, MUTED = "#0b6aa2", "#c0392b", "#1b1f24", "#5f6b7a"
SERIES = {"TEDOM": "#b5762a", "J320 Жаркент 2": "#0a75ad", "J320 Жаркент 3": "#2e8b47",
          "Grid import": "#c94040", "Export": "#c2457a", "Battery discharging": "#6f42c1",
          "Battery charging": "#b19cd9", "Load": INK, "Load + battery's own use": INK,
          "Running in the band": "#0a75ad", "Replacing import": "#d2691e",
          "Fuel": "#b5762a", "Service": "#1f86c1",
          "Engine start wear, with the battery": "#b5762a", "Battery wear": "#6f42c1",
          "Engine start wear, today": INK}
STATUS = {"datasheet": ("#0b6aa2", "#e8f2fa"), "placeholder": ("#c0392b", "#fdecea"),
          "confirmed": ("#2e7d32", "#eaf5ea"), "typed": ("#5f6b7a", "#f1f3f5")}
MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
CUR = "₸"

CSS = """
<style>
.bp-label{font-family:%(mono)s;font-size:.78rem;letter-spacing:.18em;color:%(acc)s;font-weight:600;margin:.2rem 0 .3rem}
.bp-title{font-family:%(mono)s;font-size:1.45rem;font-weight:700;color:%(ink)s;margin:.1rem 0 .2rem}
.bp-run{color:%(muted)s;font-size:.95rem;margin-bottom:.6rem}
.bp-ph{border-left:3px solid %(red)s;padding:.35rem .8rem;color:%(red)s;font-size:.86rem;margin:.4rem 0 .8rem;line-height:1.45}
.bp-note{border-left:3px solid %(acc)s;padding:.35rem .8rem;color:%(ink)s;font-size:.86rem;margin:.4rem 0 .8rem;background:#f3f8fc}
.bp-about{color:%(muted)s;font-size:.95rem;margin:.2rem 0 .6rem}
.bp-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:.3rem 0 .6rem}
@media (max-width:820px){.bp-cards{grid-template-columns:1fr}}
.bp-card{border:1px solid #d5dbe1;border-radius:2px;padding:12px 14px;background:#fff}
.bp-card-k{font-size:.8rem;color:%(muted)s;margin-bottom:.35rem}
.bp-card-v{font-family:%(mono)s;font-size:1.45rem;font-weight:700;color:%(ink)s;margin-bottom:.25rem}
.bp-card-s{font-size:.8rem;color:%(muted)s;line-height:1.35}
.bp-h{font-family:%(mono)s;font-size:1.02rem;font-weight:700;color:%(ink)s;margin:.9rem 0 .1rem}
.bp-sub{font-size:.85rem;color:%(muted)s;margin:0 0 .3rem}
.bp-badge{display:inline-block;font-size:.72rem;padding:0 .4rem;border:1px solid;border-radius:2px}
.bp-tbl{width:100%%;border-collapse:collapse;font-size:.82rem}
.bp-tbl th{text-align:left;color:%(ink)s;font-weight:600;border-bottom:1px solid #d5dbe1;padding:6px 6px}
.bp-tbl td{border-bottom:1px solid #eef1f4;padding:6px 6px;vertical-align:top;color:%(ink)s}
.bp-tbl tr.bp-chg td{background:#fff7e0}
.bp-stats{display:grid;grid-template-columns:repeat(var(--n,4),minmax(0,1fr));gap:14px;margin:.4rem 0 .8rem}
@media (max-width:820px){.bp-stats{grid-template-columns:1fr 1fr}}
.bp-stat{border-left:2px solid %(ink)s;padding:2px 10px}
.bp-stat-v{font-family:%(mono)s;font-size:1.15rem;font-weight:700;color:%(ink)s}
.bp-stat-k{font-size:.85rem;color:%(ink)s}
.bp-stat-s{font-size:.78rem;color:%(muted)s}
.bp-foot{font-size:.8rem;color:%(muted)s;line-height:1.45;margin-top:.8rem}
</style>
""" % dict(mono=MONO, acc=ACCENT, ink=INK, muted=MUTED, red=RED)

SRC_FILE, SRC_HOURLY = "5-minute run file", "Hourly measurements"
SIZE_OPTS = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 5.5, 6.0, 7.0, 8.0, 10.0]
VIEWS = ["Battery payback", "Today, measured", "Measured data"]
HOURS_AXIS = alt.Axis(values=list(range(0, 9)), format="d")
MODES = ["By the rule: every ticked engine", "One engine tied to the battery",
         "Battery first, a further engine later", "Charge at low load, follow at high load",
         "Planned ahead (MPC)"]
MODE_KEYS = ["rule", "tied", "delayed", "combined", "mpc"]
FORECASTS = {"previous": "From the 7 days before", "perfect": "The load itself (the ceiling)"}
TIED_ENGINES = ["zh2", "zh3"]


def _tied_on() -> bool:
    """Whether one engine is tied to the battery, as the switch below the Battery panel was
    last set (the Generators panel is drawn before it)."""
    return ss.get("bp_mode") == MODES[1]


def _g(x: float) -> str:
    return f"{x:g}"


def _m(v: float, d: int = 1) -> str:
    return f"{v / 1e6:,.{d}f} M"


def _n(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")


def _size(e_mwh: float, p_mw: float) -> str:
    return f"{1000 * e_mwh:,.0f} kWh / {1000 * p_mw:,.0f} kW"


def _short(e_mwh: float) -> str:
    return f"{_g(e_mwh)} MWh"


# ---- the inputs, in the dispatch study's panels -----------------------------------------
PLANT = {u: T.GROUPS[g]["name"] for g in ("K", "M") for u in T.GROUPS[g]["units"]}
GEN_COLS = [2.4, 1.5, 1.2, 1.0, 1.0, 1.0]
GEN_HEAD = [
    ("Generator", None),
    ("Works with the battery",
     "Ticked: the engine follows the rule together with the battery. Unticked: it runs as "
     "the meters show, its output is taken off the load, and the battery works with the "
     "other engines (and may take what this one exports)."),
    ("Rated output (kW)",
     "The engine's output whenever it runs under the rule, the top of its fuel curve, and "
     "the cost of its engine hour (service rate × rated kW)."),
    ("Efficiency at 50 %",
     "Electrical efficiency (LHV), in %, at 50, 75 and 100 % load. Fuel follows straight "
     "lines through the three points; below 50 % the 50–75 % slope is extended."),
    ("at 75 %", None),
    ("at 100 %", None),
]


def generators() -> tuple[tuple, tuple, tuple]:
    """One row per engine: works with the battery, rated output, efficiency at 50 / 75 /
    100 % load. The defaults are the datasheets'."""
    D = T.DEFAULTS
    UT.panel_head("Generators")
    with st.expander("Generators", expanded=True):
        for c, (title, help_) in zip(st.columns(GEN_COLS, vertical_alignment="bottom"), GEN_HEAD):
            with c:
                st.markdown(f"**{title}**", help=help_)
        gen_kw, gen_eff, works = [], [], []
        for u in T.RATED:
            row = st.columns(GEN_COLS, vertical_alignment="center")
            with row[0]:
                st.markdown(f"{T.LONG[u]}  \n:gray[{PLANT[u]}]")
            with row[1]:
                if st.checkbox(f"{T.LONG[u]} works with the battery", value=D.works(u),
                               key=f"bp_on_{u}", label_visibility="collapsed",
                               disabled=_tied_on(),
                               help="One engine is tied to the battery: it is chosen in "
                                    "Battery operation." if _tied_on() else None):
                    works.append(u)
            with row[2]:
                kw = st.number_input(f"{T.LONG[u]} rated output (kW)", 1.0, 10_000.0,
                                     D.rated(u), step=1.0, format="%.0f", key=f"bp_kw_{u}",
                                     label_visibility="collapsed")
            effs = []
            for c, (f, v) in zip(row[3:], D.eff(u).items()):
                with c:
                    effs.append(st.number_input(
                        f"{T.LONG[u]} efficiency at {100 * f:g} % (%)", 1.0, 100.0,
                        round(100 * v, 1), step=0.1, format="%.1f",
                        key=f"bp_e{100 * f:g}_{u}", label_visibility="collapsed"))
            gen_kw.append((u, float(kw)))
            gen_eff.append((u, tuple(round(float(e) / 100.0, 6) for e in effs)))
    return tuple(gen_kw), tuple(gen_eff), tuple(works)


def inputs() -> tuple[T.Inputs, str]:
    D = T.DEFAULTS
    gen_kw, gen_eff, works = generators()
    UT.panel_head("Engines and the rule")
    with st.expander("Engines and the rule", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            band = st.number_input(
                "Engines run at least at (% of rated)", 50.0, 100.0, 100 * D.band, step=5.0,
                key="bp_band",
                help="The efficient band. An engine runs at this share of its rating or above, "
                     "or stops; below it only when the battery is full and export is "
                     "forbidden, down to the datasheet minimum of 50 %.")
        with c2:
            wear = st.number_input(
                "Start wear (engine hours per start)", 0.0, 20.0, D.start_wear_h, step=0.5,
                key="bp_wear",
                help="A start costs as much service as this many hours of running. To be "
                     "set by the service company (warm vs cold start).")
        with c3:
            service = st.number_input(
                f"Service ({CUR} per kWh of rating)", 0.0, 30.0, D.service_kzt_kwh, step=0.5,
                key="bp_service",
                help="The service company's rate. An engine hour costs this × the engine's "
                     "rated kW: 7 200 ₸ for the TEDOM, 6 396 ₸ for a J320 at 6 ₸.")
        with c4:
            export = st.checkbox("Allow export (not compensated)", D.allow_export, key="bp_export",
                                 help="Off: when even the engines' minimum makes more than the "
                                      "load and the battery can take, an engine stops. On: it "
                                      "runs at its minimum and the surplus goes to the city "
                                      "for nothing.")
    UT.panel_head("Prices")
    with st.expander("Prices", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            gas = st.number_input(f"Gas ({CUR}/m³ incl. VAT)", 1.0, 500.0, D.gas_kzt_m3,
                                  step=1.0, key="bp_gas")
        with c2:
            grid = st.number_input(f"Grid ({CUR}/kWh incl. VAT)", 1.0, 200.0, D.grid_kzt_kwh,
                                   step=0.5, key="bp_grid", help="Flat; no capacity charge.")
        with c3:
            vat = st.number_input("VAT (%)", 0.0, 30.0, 100 * D.vat, step=1.0, key="bp_vat",
                                  help="Prices are taken ex VAT: the plant recovers input VAT.")
        with c4:
            heat = st.number_input("Gas heating value (kWh/m³)", 8.0, 11.0, D.gas_kwh_m3,
                                   step=0.01, key="bp_heat",
                                   help="Tedom technical sheet basis 34 MJ/m³; confirm from "
                                        "the supply contract.")
    UT.panel_head("Battery")
    with st.expander("Battery", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            b_kw = st.number_input("Power (kW)", 1.0, value=D.power_kw, step=100.0, key="bp_kw")
            b_kwh = st.number_input("Energy (kWh)", 1.0, value=D.energy_kwh, step=100.0,
                                    key="bp_kwh")
            own = st.number_input("Own use (kW)", 0.0, value=D.own_kw, step=5.0, key="bp_own",
                                  help="Cooling and controls, drawn every step while there is "
                                       "a battery.")
        with c2:
            rte = st.number_input("Round-trip efficiency (%)", 1.0, 100.0, 100 * D.rte,
                                  step=1.0, key="bp_rte", help="Applied as √RTE each way.")
            soc_min = st.number_input("Minimum SoC (%)", 0.0, 90.0, 100 * D.soc_lo, step=5.0,
                                      key="bp_socmin",
                                      help=f"The charge window runs from here to "
                                           f"{100 * D.soc_hi:g} %.")
        with c3:
            b_wear = st.number_input(f"Wear cost ({CUR} per kWh discharged)", 0.0,
                                     value=D.wear_kzt_kwh, step=0.1, key="bp_bwear")
            capex = st.number_input(f"Battery CAPEX ({CUR})", 0.0, value=D.capex_kzt,
                                    step=1_000_000.0, format="%.0f", key="bp_capex",
                                    help="The battery's price. The other sizes compared are "
                                         "priced in proportion to their energy.")
        with c4:
            soc0 = st.number_input("Start SoC (%)", 0.0, 100.0, 100 * D.soc_start, step=5.0,
                                   key="bp_soc0",
                                   help="Every unbroken run of measured data starts at this "
                                        "charge.")
        c5, c6, c7 = st.columns(3)
        with c5:
            om = st.number_input("Battery O&M (% of CAPEX per year)", 0.0, 20.0,
                                 100 * D.om_frac, step=0.1, key="bp_om",
                                 help="Fixed upkeep of the battery, taken off its saving every "
                                      "year.")
        with c6:
            rep_year = int(st.number_input("Replacement in year (0 = none)", 0, 40,
                                           D.replace_year, step=1, key="bp_rep_year",
                                           help="Paid in this year if the battery has not "
                                                "paid back by then, and in the profit over "
                                                "its life if it falls inside that life."))
        with c7:
            rep_pct = st.number_input("Replacement cost (% of CAPEX)", 0.0, 200.0,
                                      100 * D.replace_frac, step=5.0, key="bp_rep_cost")
        c8, c9, c10 = st.columns(3)
        with c8:
            cycles = st.number_input("Cycle life (full cycles)", 500, 30000, int(D.cycle_life),
                                     step=500, key="bp_cycles",
                                     help="Life in years = this ÷ the cycles a year, never "
                                          "beyond the calendar life. A size counts only if it "
                                          "pays back before it wears out.")
        with c9:
            cal = st.number_input("Calendar life (years)", 1, 40, int(D.calendar_life),
                                  key="bp_cal",
                                  help="A battery ages even when it cycles little.")
        with c10:
            sizes = st.multiselect(
                "Other sizes compared (MWh)", SIZE_OPTS, list(D.sizes_mwh), format_func=_g,
                key="bp_sizes",
                help="Energies for the payback, profit, saving and starts charts, each with "
                     "this battery's own hours of storage and priced in proportion to its "
                     "CAPEX.")
    tied = battery_operation()
    UT.panel_head("Measured steps")
    with st.expander("Measured steps", expanded=True):
        c1, c2 = st.columns(2)
        have = T.his_steps_available()
        with c1:
            if have:
                source = st.radio("Steps", [SRC_FILE, SRC_HOURLY], horizontal=True,
                                  key="bp_source",
                                  help="The 5-minute run file, or this project's hourly table "
                                       "built by the same data rules. The arithmetic is the "
                                       "same either way.")
            else:
                source = SRC_HOURLY
                st.markdown("**Steps:** hourly measurements",
                            help="The 5-minute run file is not on this machine, so the rule "
                                 "runs on this project's hourly table.")
        with c2:
            bridge = st.number_input("Bridge data gaps up to (hours)", 0.0, 24.0, D.bridge_h,
                                     step=0.5, key="bp_bridge",
                                     help="Gaps in one signal up to this long are bridged by a "
                                          "straight line; longer gaps stay empty. ЖКПЗ's "
                                          "December 2025 and February 2026 are never filled.")
    inp = replace(D, gen_kw=gen_kw, gen_eff=gen_eff, with_battery=works, band=band / 100.0, start_wear_h=float(wear), service_kzt_kwh=float(service),
                  allow_export=bool(export), gas_kzt_m3=float(gas), grid_kzt_kwh=float(grid),
                  vat=float(vat) / 100.0, gas_kwh_m3=float(heat), power_kw=float(b_kw),
                  energy_kwh=float(b_kwh), own_kw=float(own), rte=float(rte) / 100.0,
                  soc_lo=float(soc_min) / 100.0, wear_kzt_kwh=float(b_wear),
                  capex_kzt=float(capex), soc_start=float(soc0) / 100.0,
                  om_frac=float(om) / 100.0, replace_year=rep_year,
                  replace_frac=float(rep_pct) / 100.0, cycle_life=float(cycles),
                  calendar_life=float(cal),
                  sizes_mwh=tuple(sorted(float(x) for x in sizes)) or D.sizes_mwh,
                  bridge_h=float(bridge), **tied)
    return inp, source


def battery_operation() -> dict:
    """How the battery works with the engines. By the rule (the default) nothing about the
    rule changes; each other way shows only its own fields."""
    D = T.DEFAULTS
    UT.panel_head("Battery operation")
    with st.expander("Battery operation", expanded=True):
        mode = st.radio(
            "How the battery works with the engines", MODES, horizontal=True, key="bp_mode",
            help="By the rule: every engine ticked in Generators follows the rule with the "
                 "battery. One engine tied to the battery: that engine charges it, the battery "
                 "gives in its place (the 17 Nov meeting). Battery first, a further engine "
                 "later: the battery covers the gap first; another engine starts only once the "
                 "gap has lasted longer than set, or the charge is down to the level set "
                 "(Владимир). Charge at low load, follow at high load: HOMER's Combined "
                 "Dispatch. Planned ahead (MPC): the engines and the battery are planned every "
                 "hour a day ahead on a load forecast, the least-cost plan by dynamic "
                 "programming.")
        key = MODE_KEYS[MODES.index(mode)]
        out: dict = {} if key == "rule" else {"mode": key}
        if key == "tied":
            c1, c2, c3, c4, c5 = st.columns([1.4, 1, 1, 1, 1.3])
            with c1:
                eng = st.selectbox("Engine tied to the battery", TIED_ENGINES,
                                   index=TIED_ENGINES.index(D.tied_engine),
                                   format_func=lambda u: T.LONG[u], key="bp_tied_engine",
                                   help="Жаркент 3 has the most spare output while Универсал "
                                        "draws little; Жаркент 2 can cover anything at ЖКПЗ.")
            with c2:
                on = st.number_input("Engine starts at charge (%)", 10.0, 90.0, 100 * D.tied_on,
                                     step=5.0, key="bp_tied_on",
                                     help="It also starts whenever the battery cannot cover "
                                          "the gap.")
            with c3:
                off = st.number_input("Engine stops at charge (%)", 20.0, 100 * D.soc_hi,
                                      100 * D.tied_off, step=5.0, key="bp_tied_off",
                                      help="It also stops, once its minimum run is over, when "
                                           "it could only run below the band and the battery "
                                           "covers the gap.")
            with c4:
                run_h = st.number_input("Minimum run (hours)", 0.0, 12.0, D.tied_min_run_h,
                                        step=0.5, key="bp_tied_run")
            with c5:
                give = st.number_input("Battery gives only above load (kW, 0 = always)", 0.0,
                                       20_000.0, D.give_from_kw, step=100.0, key="bp_give_from",
                                       help="Below this load of the plant the battery holds its "
                                            "charge for the bigger loads, and the engines and "
                                            "the grid serve the load.")
            out.update(tied_engine=eng, tied_on=round(float(on) / 100.0, 6),
                       tied_off=round(float(off) / 100.0, 6), tied_min_run_h=float(run_h),
                       give_from_kw=float(give))
        elif key == "delayed":
            c1, c2, c3 = st.columns(3)
            with c1:
                dh = st.number_input("Further engine starts after the gap lasts (hours)", 0.5,
                                     24.0, D.delay_h, step=0.5, key="bp_delay_h",
                                     help="Until then the battery covers the gap, and the grid "
                                          "what the battery cannot.")
            with c2:
                ds = st.number_input("... or once the charge is down to (%)", 10.0, 95.0,
                                     100 * D.delay_soc, step=5.0, key="bp_delay_soc")
            with c3:
                dr = st.number_input("Minimum run of an engine so started (hours)", 0.5, 12.0,
                                     D.delay_min_run_h, step=0.5, key="bp_delay_run")
            out.update(delay_h=float(dh), delay_soc=round(float(ds) / 100.0, 6),
                       delay_min_run_h=float(dr))
        elif key == "combined":
            c1, c2 = st.columns(2)
            with c1:
                cl = st.number_input("Engines charge the battery below load (kW, 0 = the largest "
                                     "engine's rating)", 0.0, 20_000.0, D.cd_load_kw,
                                     step=100.0, key="bp_cd_load",
                                     help="Below it, cycle charging: engines at full output "
                                          "charge the battery up to the level on the right; above "
                                          "it, load following: engines make what the load needs.")
            with c2:
                cs = st.number_input("Charge to (%)", 20.0, 100 * D.soc_hi, 100 * D.cd_setpoint,
                                     step=5.0, key="bp_cd_set")
            out.update(cd_load_kw=float(cl), cd_setpoint=round(float(cs) / 100.0, 6))
        elif key == "mpc":
            c1, c2, c3 = st.columns([1.6, 1, 1])
            with c1:
                fc = st.radio("Load forecast", list(FORECASTS), horizontal=True, key="bp_mpc_fc",
                              format_func=lambda k: FORECASTS[k],
                              help="From the 7 days before: each clock hour's mean over the "
                                   "week before, the hour itself as measured -- what a "
                                   "controller would know. The load itself: as if the load "
                                   "were known in advance -- the ceiling no way of running "
                                   "can beat.")
            with c2:
                hz = st.number_input("Plan horizon (hours)", 6.0, 72.0, D.mpc_horizon_h,
                                     step=6.0, key="bp_mpc_h")
            with c3:
                rp = st.number_input("Re-plan every (hours)", 1.0, 24.0, D.mpc_replan_h,
                                     step=1.0, key="bp_mpc_rp",
                                     help="Every hour is what makes it work: re-planned less "
                                          "often it follows a stale forecast.")
            out.update(mpc_forecast=fc, mpc_horizon_h=float(hz), mpc_replan_h=float(rp))
            st.caption("Planning every hour takes about 10 s per battery size and plant, so a "
                       "run takes a few minutes.")
        if key in ("tied", "delayed", "combined"):
            if st.checkbox("Tune these thresholds on the data, per plant", value=False,
                           key="bp_tune",
                           help="Tries a grid of values for your battery on each plant's year "
                                "and keeps the set that saves the most with the engines in the "
                                "band. Tuned on the year it is judged on: it shows what the "
                                "thresholds can do here, not what they would do next year."):
                out["tune"] = True
    return out


# ---- the arithmetic, cached --------------------------------------------------------------
@st.cache_resource(max_entries=8, show_spinner=False)
def _steps(group: str, source: str, items: tuple, study_only: bool = True):
    inp = T.Inputs(**dict(items))
    if source == SRC_FILE and T.his_steps_available():
        return T.his_steps(group)
    return T.hourly_steps(group, inp, study_only=study_only)


def _items(inp: T.Inputs) -> tuple:
    return tuple(sorted(asdict(inp).items()))


def _run(inp: T.Inputs, source: str) -> dict:
    bar = st.progress(0.0, text="Running the rule")
    out = {}
    groups = list(T.GROUPS)
    for gi, g in enumerate(groups):
        name = T.GROUPS[g]["name"]

        def tick(i, n, _gi=gi, _name=name):
            bar.progress((_gi + i / n) / len(groups),
                         text=f"Running the rule: {_name}, size {i + 1} of {n}")
        out[g] = T.run_group(g, inp, x=_steps(g, source, _items(inp)), on_size=tick)
    bar.empty()
    return out


# ---- charts --------------------------------------------------------------------------------
def _legend_sel():
    return alt.selection_point(fields=["series"], bind="legend")


def _scale(names):
    return alt.Scale(domain=list(names), range=[SERIES.get(n, "#888") for n in names])


def _by_size(df: pd.DataFrame, y: str, ytitle: str, sizes, today: float | None = None,
             fmt: str = ",.1f"):
    lo, hi = (min(sizes), max(sizes)) if sizes else (1.0, 7.0)
    ticks = list(range(int(np.floor(lo)), int(np.ceil(hi)) + 1))
    base = alt.Chart(df).encode(
        x=alt.X("e_mwh:Q", title="battery energy, MWh",
                scale=alt.Scale(domain=[lo, hi], nice=False),
                axis=alt.Axis(values=ticks, format="d")),
        y=alt.Y(f"{y}:Q", title=ytitle),
        tooltip=[alt.Tooltip("label:N", title="battery"), alt.Tooltip(f"{y}:Q", format=fmt)])
    ch = base.mark_line(strokeWidth=2, color=ACCENT) + base.mark_point(filled=True, size=60,
                                                                        color=ACCENT)
    if today is not None:
        ch = ch + alt.Chart(pd.DataFrame({"y": [today]})).mark_rule(
            strokeDash=[5, 4], color=INK).encode(y="y:Q")
    return ch.properties(height=280)


def _sizes_frame(sizes: pd.DataFrame) -> pd.DataFrame:
    d = sizes.copy()
    d["label"] = [_size(e, p) for e, p in zip(d.e_mwh, d.p_mw)]
    d["profit_M"] = d["profit_kzt"] / 1e6
    return d


def _h(title: str, sub: str | None = None, help: str | None = None):
    st.markdown(f'<div class="bp-h">{title}</div>', unsafe_allow_html=True, help=help)
    if sub:
        st.markdown(f'<div class="bp-sub">{sub}</div>', unsafe_allow_html=True)


# ---- the report ----------------------------------------------------------------------------
def _cards(r: T.Run) -> None:
    t, y, b = r.today, r.yours, r.best
    pay = "never" if y.payback_y != y.payback_y else f"{y.payback_y:.1f} y payback"
    cards = [
        ("Today, measured", f"{_m(t.cost_kzt)} {CUR}/yr",
         f"{_n(t.run_h)} engine h · {_n(t.starts)} starts · import {_n(t.imp_kwh / 1e3)} MWh"),
        (f"Your battery: {_size(y.e_mwh, y.p_mw)}", pay,
         f"saving {_m(y.net_kzt)} · life {y.life_y:.1f} y · profit over life "
         f"{_m(y.profit_kzt)} · {_n(y.starts)} starts"),
    ]
    if b is not None:
        cards.append((f"Shortest payback, in the band and before wear-out: "
                      f"{_size(b.e_mwh, b.p_mw)}", f"{b.payback_y:.1f} y",
                      f"saving {_m(b.net_kzt)} · life {b.life_y:.1f} y · profit over life "
                      f"{_m(b.profit_kzt)} · {_n(b.starts)} starts"))
    else:
        cards.append(("Shortest payback, in the band and before wear-out", "none",
                      "no size compared pays back before it wears out"))
    st.html('<div class="bp-cards">' + "".join(
        f'<div class="bp-card"><div class="bp-card-k">{k}</div><div class="bp-card-v">{v}</div>'
        f'<div class="bp-card-s">{s}</div></div>' for k, v, s in cards) + "</div>")
    own = T.battery_own(r, y)
    if own is not None:
        eng = T.LONG[r.inp.tied_engine]
        pay_own = ("never pays back" if own["payback"] != own["payback"] else
                   f"pays back in {own['payback']:.1f} y against a life of {y.life_y:.1f} y")
        who = (f"{eng} switched on by the rule would save {_m(own['engine'])} {CUR} a year by "
               "itself" if r.inp.tied else "the same engines switched on by the rule would save "
               f"{_m(own['engine'])} {CUR} a year by themselves")
        st.html('<div class="bp-note">'
                + (f'Without the battery, {who}. ' if not r.inp.tied or r.inp.tied_engine in
                   T.GROUPS[r.group]["units"] else "")
                + f'The battery adds {_m(own["gross"])} {CUR} a year on top'
                + (f', {_m(own["net"])} after its O&M' if y.bat_om_kzt else "")
                + f': on that share alone it {pay_own}.</div>')
    with st.expander("How each value was built", expanded=False):
        cols = st.columns(3)
        with cols[0]:
            st.markdown("**Today, measured**")
            st.markdown("\n".join("- " + s for s in _today_lines(r)))
        with cols[1]:
            st.markdown(f"**Your battery: {_size(y.e_mwh, y.p_mw)}**")
            st.markdown("\n".join("- " + s for s in _size_lines(r, y)))
        with cols[2]:
            if b is not None:
                st.markdown(f"**Shortest payback: {_size(b.e_mwh, b.p_mw)}**")
                st.markdown("\n".join("- " + s for s in _size_lines(r, b)))


def _today_lines(r: T.Run) -> list[str]:
    t, inp = r.today, r.inp
    units = T.GROUPS[r.group]["units"]
    hours = " + ".join(f"{_n(t[f'{u}_run_h'])} h × {_n(inp.om_h(u))}" for u in units)
    return [f"Today {_m(t.cost_kzt)} {CUR}/yr = fuel {_m(t.fuel_kzt)} + service {_m(t.om_kzt)} "
            f"+ grid {_m(t.grid_kzt)}",
            f"Fuel = {_n(t.fuel_kwh / 1e3)} MWh of gas × {inp.gas_kzt_kwh:.3f} {CUR}",
            f"Service = engine hours ({hours}) + start wear {inp.start_wear_h:g} h × "
            f"{_n(t.starts)} starts × the hourly rate",
            f"Grid = import {_n(t.imp_kwh / 1e3)} MWh × {inp.grid_ex_vat:.2f} {CUR}",
            f"From {_n(t.attrs.get('complete_h', 0))} complete hours, "
            f"{len(t.attrs.get('months', []))} months used, scaled to a year"]


def _size_lines(r: T.Run, y: pd.Series) -> list[str]:
    t, inp = r.today, r.inp
    pay = ("never" if y.payback_y != y.payback_y else
           f"{y.payback_y:.1f} years = {_m(y.capex_kzt)} "
           + (f"+ replacement {_m(inp.replace_frac * y.capex_kzt)} " if inp.replace_year
              and y.payback_y > inp.replace_year else "")
           + f"÷ {_m(y.net_kzt)} a year")
    below = 100 * y.oob_h / y.rule_run_h if y.rule_run_h else 0.0
    lines = [f"Battery {_size(y.e_mwh, y.p_mw)} ({1000 * y.e_mwh / max(1e-9, 1000 * y.p_mw):.2f} h "
             "of storage)",
             f"Saving {_m(y.saving_kzt)} {CUR}/yr = today {_m(t.cost_kzt)} – with battery "
             f"{_m(y.cost_kzt)}",
             f"fuel {_m(t.fuel_kzt)} → {_m(y.fuel_kzt)}, service {_m(t.om_kzt)} → "
             f"{_m(y.om_kzt)}, grid {_m(t.grid_kzt)} → {_m(y.grid_kzt)}"
             + (f", battery wear {_m(y.wear_kzt)}" if y.wear_kzt else "")]
    if y.bat_om_kzt:
        lines.append(f"Battery O&M {_m(y.bat_om_kzt)} a year: net saving {_m(y.net_kzt)}")
    own = T.battery_own(r, y)
    if own is not None:
        lines.append(f"The same engines without the battery {_m(r.alone.cost_kzt)} {CUR}/yr: "
                     f"they save {_m(own['engine'])} by themselves, the battery adds "
                     f"{_m(own['gross'])}"
                     + (f" ({_m(own['net'])} after its O&M)" if y.bat_om_kzt else "")
                     + (f", payback on that share {own['payback']:.1f} years"
                        if own["payback"] == own["payback"] else ", which never pays it back"))
    lines += [
        f"Running in the band {_m(y.band_kzt)} = (today {t.kzt_per_kwh_gen:.2f} – "
        f"{y.kzt_per_kwh_gen:.2f} {CUR} per kWh the engines make) × today's "
        f"{t.gen_kwh / 1e6:.2f} GWh",
        f"Replacing import {_m(y.import_kzt)} = saving – running in the band (import "
        f"{_n(t.imp_kwh / 1e3)} → {_n(y.imp_kwh / 1e3)} MWh)",
        f"Battery CAPEX {_m(y.capex_kzt)} {CUR}",
        f"Payback {pay}",
        f"Engine starts {_n(y.starts)} a year (today {_n(t.starts)}); engine hours "
        f"{_n(y.run_h)} (today {_n(t.run_h)})",
        f"Below the {inp.band * 100:g} % band {_n(y.oob_h)} h a year ({below:.1f} % of the "
        "rule's engine hours)",
        f"Battery life {y.life_y:.1f} years = {inp.cycle_life:g} cycles ÷ {y.cycles:.0f} a year"
        + (f", capped at {inp.calendar_life:g}" if y.life_y >= inp.calendar_life else ""),
        f"Pays back before it wears out: {'yes' if y.pays_back else 'no'}"
        + ("" if y.payback_y != y.payback_y else
           f" (payback {y.payback_y:.1f} y vs life {y.life_y:.1f} y)"),
        f"Profit over the battery's life {_m(y.profit_kzt)} {CUR} = {_m(y.net_kzt)} × "
        f"{y.life_y:.1f} years – {_m(y.capex_kzt)}"
        + (f" – replacement {_m(y.replace_kzt)}" if y.replace_kzt else ""),
        f"From {_n(t.attrs.get('complete_h', 0))} complete hours, "
        f"{len(t.attrs.get('months', []))} months used, scaled to a year"]
    return lines


def _shift_day(key: str, days: list, step: int) -> None:
    """◀ ▶: the previous or next day that has data (days without data are skipped)."""
    i = days.index(ss[key]) if ss.get(key) in days else 0
    ss[key] = days[max(0, min(len(days) - 1, i + step))]


def _day_chart(r: T.Run) -> None:
    x, s = r.x, r.sim
    units = T.GROUPS[r.group]["units"]
    days = sorted(pd.Series(x["time"].dt.date).unique())
    if not days:
        return
    key = f"bp_day_{r.group}"
    default = dt.date(2026, 4, 21) if dt.date(2026, 4, 21) in days else days[len(days) // 2]
    ss.setdefault(key, default)
    if ss[key] not in days:
        ss[key] = min(days, key=lambda d: abs((d - ss[key]).days))
    i = days.index(ss[key])
    y = r.yours
    step_min = round(x.attrs.get("dt", 1.0) * 60)
    _h(f"{ss[key]:%Y-%m-%d}, every {step_min} minutes, {_size(y.e_mwh, y.p_mw)}",
       "Columns: who covered the load in each step, measured above, with the battery below, "
       "on the same scale.")
    c1, c2, c3, c4 = st.columns([0.6, 2.2, 0.6, 6])
    with c1:
        st.button("◀", key=f"{key}_prev", disabled=i == 0, on_click=_shift_day,
                  args=(key, days, -1))
    with c2:
        st.date_input("Day", key=key, min_value=days[0], max_value=days[-1],
                      label_visibility="collapsed")
    with c3:
        st.button("▶", key=f"{key}_next", disabled=i == len(days) - 1, on_click=_shift_day,
                  args=(key, days, +1))
    mask = (x["time"].dt.date == ss[key]).values
    per_day = int(round(24 / x.attrs.get("dt", 1.0)))
    with c4:
        st.caption(f"{int(mask.sum())} of {per_day} steps have data this day · {len(days)} days "
                   "with data")
    tt = x["time"].values[mask]
    g = x["grid_measured"].values[mask]
    rows = []
    for u in units:
        rows += [dict(time=a, series=T.NAME[u], kw=b) for a, b in zip(tt, x[f"{u}_measured"].values[mask])]
    rows += [dict(time=a, series="Grid import", kw=max(b, 0)) for a, b in zip(tt, g)]
    rows += [dict(time=a, series="Export", kw=-max(-b, 0)) for a, b in zip(tt, g)]
    m_df = pd.DataFrame(rows)
    load = pd.DataFrame(dict(time=tt, kw=x["load"].values[mask]))
    rows = []
    for u in units:
        rows += [dict(time=a, series=T.NAME[u], kw=b) for a, b in zip(tt, s["out"][u][mask])]
    rows += [dict(time=a, series="Battery discharging", kw=b) for a, b in zip(tt, s["dis"][mask])]
    rows += [dict(time=a, series="Grid import", kw=b) for a, b in zip(tt, s["imp"][mask])]
    rows += [dict(time=a, series="Battery charging", kw=-b) for a, b in zip(tt, s["ch"][mask])]
    rows += [dict(time=a, series="Export", kw=-b) for a, b in zip(tt, s["exp"][mask])]
    r_df = pd.DataFrame(rows)
    need = pd.DataFrame(dict(time=tt, kw=s["need"][mask]))
    lo = min(-1000.0, float(min(m_df.kw.min(), r_df.kw.min())) * 1.1)
    hi = max(3500.0, float(max(load.kw.max(), need.kw.max(),
                               r_df[r_df.kw > 0].groupby("time").kw.sum().max())) * 1.1)
    order_m = [T.NAME[u] for u in units] + ["Grid import", "Export"]
    order_r = [T.NAME[u] for u in units] + ["Battery discharging", "Grid import",
                                            "Battery charging", "Export"]
    step = pd.Timedelta(hours=x.attrs.get("dt", 1.0))

    def bars(df, order, line):
        sel = _legend_sel()
        b = alt.Chart(df.assign(end=df["time"] + step)).mark_bar().encode(
            x=alt.X("time:T", title=None, axis=alt.Axis(format="%H:%M")), x2="end:T",
            y=alt.Y("sum(kw):Q", title="kW", scale=alt.Scale(domain=[lo, hi])),
            color=alt.Color("series:N", scale=_scale(order), sort=order, title=None,
                            legend=alt.Legend(orient="top", labelLimit=0)),
            order=alt.Order("rank:Q"),
            opacity=alt.condition(sel, alt.value(1), alt.value(0.15)),
            tooltip=["series:N", alt.Tooltip("time:T", format="%H:%M"),
                     alt.Tooltip("kw:Q", format=",.0f")],
        ).transform_calculate(rank=f"indexof({order!r}, datum.series)").add_params(sel)
        ln = alt.Chart(line).mark_line(color=INK, strokeWidth=1.6,
                                       interpolate="step-after").encode(x="time:T", y="kw:Q")
        return (b + ln).properties(height=300)

    st.markdown('<div class="bp-h">Today, measured</div>', unsafe_allow_html=True)
    st.altair_chart(bars(m_df, order_m, load), width="stretch")
    st.caption("Black line: the load.")
    st.markdown('<div class="bp-h">With the battery, '
                + (f'{T.LONG[r.inp.tied_engine]} tied to it' if r.inp.tied
                   else T.mode_label(r.inp))
                + '</div>', unsafe_allow_html=True)
    st.altair_chart(bars(r_df, order_r, need), width="stretch")
    st.caption("Black line: the load and the battery's own use.")
    soc = pd.DataFrame(dict(time=tt, soc=100 * s["soc"][mask]))
    st.altair_chart(alt.Chart(soc).mark_line(color=SERIES["Battery discharging"]).encode(
        x=alt.X("time:T", title=None, axis=alt.Axis(format="%H:%M")),
        y=alt.Y("soc:Q", title="% charge", scale=alt.Scale(domain=[0, 100]))).properties(
        height=130), width="stretch")


def _wear_charts(r: T.Run) -> None:
    y, b = r.yours, r.best
    sizes_ = [(y.e_mwh, y.p_mw)] + ([(b.e_mwh, b.p_mw)] if b is not None else [])
    rows = []
    for e, p in dict.fromkeys(sizes_):
        for w, pb in T.start_wear_curve(r, 1000 * e):
            rows.append(dict(h=w, payback=pb, series=_size(e, p)))
    _h("Start wear", "Payback as the engine hours charged per start change: no published "
       "figure exists for gas engines, so it is shown across the range.",
       help="Your battery, and the size with the shortest payback.")
    if rows:
        df = pd.DataFrame(rows)
        ch = alt.Chart(df).encode(
            x=alt.X("h:Q", title="engine hours charged per start", axis=HOURS_AXIS),
            y=alt.Y("payback:Q", title="payback, years"),
            color=alt.Color("series:N", title=None, legend=alt.Legend(orient="top", labelLimit=0),
                            scale=alt.Scale(range=[ACCENT, "#c27c2c"])),
            tooltip=["series:N", "h:Q", alt.Tooltip("payback:Q", format=".2f")])
        st.altair_chart((ch.mark_line() + ch.mark_point(filled=True)).properties(height=260),
                        width="stretch")

    _h("Wear per year: engine starts vs battery cycles",
       "Where a dashed line crosses the flat one, engine starts cost as much as the battery's "
       "cycling.",
       help="Engine start wear = starts × engine hours per start × the hourly service rate. "
            "Battery wear = its CAPEX ÷ its life.")
    w = pd.DataFrame(T.wear_vs_start(r, y))
    names = ["Engine start wear, with the battery", "Engine start wear, today", "Battery wear"]
    long = pd.concat([w.assign(series=names[0], v=w.with_battery / 1e6),
                      w.assign(series=names[1], v=w.today / 1e6),
                      w.assign(series=names[2], v=w.battery / 1e6)])
    st.altair_chart(alt.Chart(long).mark_line(point=True).encode(
        x=alt.X("h:Q", title="engine hours charged per start", axis=HOURS_AXIS),
        y=alt.Y("v:Q", title=f"M {CUR} per year"),
        color=alt.Color("series:N", scale=_scale(names), title=None,
                        legend=alt.Legend(orient="top", labelLimit=0)),
        strokeDash=alt.StrokeDash("series:N", legend=None,
                                  scale=alt.Scale(domain=names, range=[[5, 4], [5, 4], [1, 0]])),
        tooltip=["series:N", "h:Q", alt.Tooltip("v:Q", format=",.1f")]).properties(height=260),
        width="stretch")

    _h("Wear per year by battery size")
    d = r.sizes.sort_values("e_mwh")
    rows = []
    for _, s in d.iterrows():
        lab = _short(s.e_mwh)
        rows.append(dict(size=lab, series="Engine start wear, with the battery",
                         v=s.start_wear_kzt / 1e6, k=0))
        rows.append(dict(size=lab, series="Battery wear", v=s.battery_wear_kzt / 1e6, k=1))
    if rows:
        names = ["Engine start wear, with the battery", "Battery wear"]
        order = [_short(e) for e in d.e_mwh]
        bars = alt.Chart(pd.DataFrame(rows)).mark_bar().encode(
            x=alt.X("size:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("sum(v):Q", title=f"M {CUR} per year"),
            color=alt.Color("series:N", scale=_scale(names), title=None,
                            legend=alt.Legend(orient="top", labelLimit=0)),
            order=alt.Order("k:Q"),
            tooltip=["size:N", "series:N", alt.Tooltip("v:Q", format=",.1f")])
        today = r.today.start_wear_kzt / 1e6
        rule = alt.Chart(pd.DataFrame({"y": [today]})).mark_rule(strokeDash=[5, 4],
                                                                  color=INK).encode(y="y:Q")
        st.altair_chart((bars + rule).properties(height=280), width="stretch")
        st.caption(f"Dashed: engine start wear today, {today:,.1f} M {CUR} per year.")


def _periods(r: T.Run) -> None:
    """The dispatch study's own period view: the meters as they ran, then the battery under
    the rule hour by hour, with the hover panel, the tables and the starts."""
    import app_periods as A
    state = T.period_state(r)
    st.html('<div class="bp-note">' + "The meters as they ran, then your battery under the "
            f"rule, hour by hour on {state['days']} whole days of the "
            f"{r.x.attrs.get('source', 'steps')}"
            + (f"; {state['hours_dropped']:,} h in days the data does not complete are not drawn"
               if state["hours_dropped"] > 0 else "")
            + ". The saving in the hover panel is today's cost of the hour less the rule's, in "
              "fuel, engine hours, grid and start wear.</div>")
    A.render_periods(state)


def _mode_text(inp: T.Inputs) -> str:
    """The run's battery operation, in a sentence for the report's header."""
    gens = (f'Generators with the battery: {", ".join(T.LONG[u] for u in inp.with_battery)}; '
            'the others run as measured. ' if len(inp.with_battery) < len(T.RATED) else "")
    tuned = "Thresholds tuned on the data, per plant. " if inp.tune and inp.mode in T.TUNE_GRID else ""
    if inp.mode == "tied":
        return (f'{T.LONG[inp.tied_engine]} is tied to the battery: it starts at '
                f'{100 * inp.tied_on:g} % charge, runs at full output and stops at '
                f'{100 * inp.tied_off:g} %; the other engines run as measured. ' + tuned)
    if inp.mode == "delayed":
        return (gens + f'Battery first: a further engine starts only once the gap has lasted '
                f'longer than {inp.delay_h:g} h, or the charge is down to {100 * inp.delay_soc:g} %. '
                + tuned)
    if inp.mode == "combined":
        lim = f"{inp.cd_load_kw:,.0f} kW" if inp.cd_load_kw > 0 else "the largest engine's rating"
        return (gens + f'Combined Dispatch: below {lim} the engines charge the battery to '
                f'{100 * inp.cd_setpoint:g} %; above it they follow the load. ' + tuned)
    if inp.mode == "mpc":
        return (gens + f'Planned ahead (MPC): every {inp.mpc_replan_h:g} h the engines and the '
                f'battery are planned {inp.mpc_horizon_h:g} h ahead on '
                + ("the forecast from the 7 days before. " if inp.mpc_forecast == "previous"
                   else "the load itself -- the ceiling, as if the load were known. "))
    return gens


def _tuned_text(inp: T.Inputs) -> str:
    """The tuned thresholds in words."""
    if inp.mode == "tied":
        return (f"starts at {100 * inp.tied_on:g} %, stops at {100 * inp.tied_off:g} %, "
                f"runs at least {inp.tied_min_run_h:g} h")
    if inp.mode == "delayed":
        return f"after {inp.delay_h:g} h of gap, or at {100 * inp.delay_soc:g} % charge"
    return (f"cycle charging below {inp.cd_load_kw:,.0f} kW, to {100 * inp.cd_setpoint:g} %")


def _report(res: dict) -> None:
    inp = res["inp"]
    st.html(
        '<div class="bp-label">ZHARKENT · BATTERY PAYBACK</div>'
        '<div class="bp-title">Battery payback, rule-based</div>'
        f'<div class="bp-run">Run {res["time"]:%d %b %Y, %H:%M}. Battery '
        f'{inp.energy_kwh:,.0f} kWh / {inp.power_kw:,.0f} kW ({inp.hours:.2f} h of storage), '
        f'CAPEX {inp.capex_kzt:,.0f} {CUR}. Engines run at least at {inp.band * 100:g} % of '
        f'rated; a start wears them as {inp.start_wear_h:g} hours of running. '
        + _mode_text(inp)
        + f'Measured steps: {res["source"].lower()}.</div>'
        f'<div class="bp-ph">Inputs still waiting for a contract or a supplier\'s figure: '
        f'{", ".join(T.PLACEHOLDERS)}.</div>')
    names = {T.GROUPS[g]["name"]: g for g in T.GROUPS}
    pick = P.switch("Plant", list(names), key="bp_entity")
    g = names[pick]
    r = res["results"][g]
    st.html(f'<div class="bp-about">{T.GROUPS[g]["about"]}</div>')
    units = T.GROUPS[g]["units"]
    off = [T.LONG[u] for u in units if not inp.works(u)]
    if inp.tied and inp.tied_engine not in units:
        st.html(f'<div class="bp-note">The engine tied to the battery, '
                f'{T.LONG[inp.tied_engine]}, is at the other plant: here the engines run as '
                'measured, and the battery charges only from what they export.</div>')
    elif inp.tied:
        st.html(f'<div class="bp-note">{T.LONG[inp.tied_engine]} is tied to the battery'
                + (f'; {", ".join(off)} {"run" if len(off) > 1 else "runs"} as measured'
                   if off else "") + '.</div>')
    elif off and len(off) == len(units):
        st.html('<div class="bp-note">No generator of this plant works with the battery: '
                'its engines run as measured, and the battery charges only from what they '
                'export.</div>')
    elif off:
        st.html(f'<div class="bp-note">{", ".join(off)} {"run" if len(off) > 1 else "runs"} '
                'as measured; the battery works with the other engines.</div>')
    if r.tuned is not None:
        st.html(f'<div class="bp-note">Thresholds tuned on this plant\'s year '
                f'({len(r.tuned)} sets tried): {_tuned_text(r.inp)}. Tuned on the year they are '
                'judged on, they show what the thresholds can do here, not a forecast.</div>')
    _cards(r)
    d = _sizes_frame(r.sizes)
    sizes = list(inp.sizes_mwh)

    _h("Payback by battery size", "Years for the saving to repay the battery. Lower is "
       f"better. Every size has {inp.hours:.2f} h of storage.",
       help="Simple payback = CAPEX ÷ the saving a year (less the battery's O&M). Sizes that "
            "keep the engines below the band more than 1 % of their running hours are left out.")
    st.altair_chart(_by_size(d[d.in_band & d.payback_y.notna()], "payback_y", "years", sizes,
                             fmt=".2f"), width="stretch")
    out_band = d[~d.in_band].e_mwh.tolist()
    never = d[d.in_band & d.payback_y.isna()].e_mwh.tolist()
    if out_band or never:
        st.caption("Not drawn: "
                   + "; ".join(p for p in (
                       (", ".join(_short(e) for e in out_band) + " (the engines run below "
                        f"the band more than {100 * inp.below_band_allowed:g} % of their "
                        "hours)") if out_band else "",
                       (", ".join(_short(e) for e in never) + " (never pays back)")
                       if never else "") if p) + ".")

    _h("Profit over the battery's life",
       "What each size earns over its life, after paying for itself. Higher is better.",
       help="Profit over life = saving × life – CAPEX (– a replacement inside the life).")
    st.altair_chart(_by_size(d[d.in_band], "profit_M", f"M {CUR} over the battery's life",
                             sizes), width="stretch")

    _h("Where the saving comes from",
       help="Running in the band = (today's – the rule's cost per kWh the engines make) × "
            "today's generation. Replacing import = saving – running in the band.")
    s_ = d.sort_values("e_mwh")
    rows = []
    for _, z in s_.iterrows():
        lab = _short(z.e_mwh)
        rows.append(dict(size=lab, series="Running in the band", v=z.band_kzt / 1e6, k=0))
        rows.append(dict(size=lab, series="Replacing import", v=z.import_kzt / 1e6, k=1))
    if rows:
        names2 = ["Running in the band", "Replacing import"]
        sel = _legend_sel()
        st.altair_chart(alt.Chart(pd.DataFrame(rows)).mark_bar().encode(
            x=alt.X("size:N", sort=[_short(e) for e in s_.e_mwh], title=None,
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y("sum(v):Q", title=f"M {CUR} per year"),
            color=alt.Color("series:N", scale=_scale(names2), title=None,
                            legend=alt.Legend(orient="top", labelLimit=0)),
            order=alt.Order("k:Q"),
            opacity=alt.condition(sel, alt.value(1), alt.value(0.15)),
            tooltip=["size:N", "series:N", alt.Tooltip("v:Q", format=",.1f")]).add_params(sel)
            .properties(height=280), width="stretch")

    _h("Engine starts per year", "With each size; dashed: today.")
    st.altair_chart(_by_size(d, "starts", "starts per year", sizes, today=r.today.starts,
                             fmt=",.0f"), width="stretch")

    _day_chart(r)
    _wear_charts(r)
    _periods(r)

    _h("Inputs of this run",
       f"Derived: gas {inp.gas_kzt_kwh:.3f} {CUR} per kWh of gas · grid {inp.grid_ex_vat:.2f} "
       f"{CUR}/kWh · engine hour TEDOM {inp.om_h('mwm'):,.0f}, J320 {inp.om_h('zh2'):,.0f} "
       f"{CUR}. Highlighted rows were changed from the defaults.")
    chg = set(T.changed(inp))
    rows = []
    for row in T.inputs_table(inp):
        fg, bg = STATUS[row["status"]]
        rows.append(f'<tr class="{"bp-chg" if row["input"] in chg else ""}"><td>{row["input"]}</td>'
                    f'<td>{row["value"]}</td><td>{row["source"]}</td>'
                    f'<td><span class="bp-badge" style="color:{fg};border-color:{fg};'
                    f'background:{bg}">{row["status"]}</span></td></tr>')
    st.html('<table class="bp-tbl"><thead><tr><th>Input</th><th>Value</th><th>Source</th>'
            '<th>Status</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>"
            '<div class="bp-foot">The rule: an engine runs only if it can work at or above the '
            'band, or if the other engines plus the battery cannot cover the load. Engines are '
            'taken as always available. Every step of measured data where the power balance '
            'closes is simulated (gaps up to the fill limit bridged); unbroken runs of data '
            'start at the start SoC with the engines as measured. Today\'s operation is costed '
            'on the same steps, so the comparison is like for like. Battery life = cycle life ÷ '
            'cycles a year, capped at the calendar life; a size counts only if it pays back '
            'before it wears out.</div>')


# ---- Today and the measured data -------------------------------------------------------------
def _stats(items) -> None:
    st.html(f'<div class="bp-stats" style="--n:{len(items)}">' + "".join(
        f'<div class="bp-stat" style="border-color:{c}"><div class="bp-stat-v">{v}</div>'
        f'<div class="bp-stat-k">{k}</div><div class="bp-stat-s">{s}</div></div>'
        for v, k, s, c in items) + "</div>")


def view_today(inp: T.Inputs, source: str) -> None:
    st.html('<div class="bp-label">ZHARKENT · TODAY, MEASURED</div>'
            '<div class="bp-title">What the plant costs today</div>'
            '<div class="bp-run">The measured baseline of each plant, before any battery: fuel, '
            'service and grid import, worked out from the meters for October 2025 – September '
            '2026. Nothing here is simulated.</div>')
    for g in ("K", "M"):
        x = _steps(g, source, _items(inp))
        units = T.GROUPS[g]["units"]
        r = T.Run(group=g, x=x, today=T.base(x, units, inp), yours=pd.Series(dtype=float),
                  sizes=pd.DataFrame(), inp=inp)
        b = T.today_breakdown(r)
        with st.container(border=True):
            c1, c2 = st.columns([1, 2])
            c1.markdown(f'<div class="bp-title" style="font-size:1.15rem">{T.GROUPS[g]["name"]}'
                        '</div>', unsafe_allow_html=True)
            c2.markdown('<div class="bp-sub" style="text-align:right">annual figure from '
                        f'{len(b["months"])} months · left out (too few complete hours): '
                        + (", ".join(pd.Period(m).strftime("%b %Y") for m in b["left_out"])
                           or "none") + "</div>", unsafe_allow_html=True)
            _h("Operating cost per year", help="Fuel + service + grid import, each month scaled "
               "to its full length, the months kept averaged and × 12.")
            _stats([(f"{_m(b['total'])} {CUR}", "Total", f"≈ {b['total'] / inp.kzt_eur / 1e3:,.0f} k EUR", INK),
                    (f"{_m(b['fuel'])} {CUR}", "Fuel", f"{_n(b['fuel_kwh'] / 1e3)} MWh gas", SERIES["Fuel"]),
                    (f"{_m(b['service'])} {CUR}", "Service (engine hours + starts)",
                     f"≈ {b['service'] / inp.kzt_eur / 1e3:,.0f} k EUR", SERIES["Service"]),
                    (f"{_m(b['grid'])} {CUR}", "Grid import", f"{_n(b['imp'] / 1e3)} MWh", SERIES["Grid import"]),
                    (f"{_n(b['load'] / 1e3)} MWh", "Load served",
                     f"generation {_n(b['gen'] / 1e3)} + import {_n(b['imp'] / 1e3)} – export "
                     f"{_n(b['exp'] / 1e3)}", INK)])
            _h("Engines per year")
            _stats([(f"{_n(e['kwh'] / 1e3)} MWh", T.LONG[u],
                     f"{_n(e['run_h'])} h · {_n(e['starts'])} starts · loading {e['loading']:.0%}",
                     SERIES[T.NAME[u]]) for u, e in b["engines"].items()])
            _h("What full-output running could save at most",
               help="Excess engine hours = hours run – energy ÷ rating, at the service rate; "
                    "part-load fuel penalty = gas burnt – gas at full-load efficiency; fuel "
                    "burned for export = export × fuel cost per kWh made.")
            _stats([(f"{_m(b['excess_kzt'])} {CUR}", "Excess engine hours",
                     f"{_n(b['excess_h'])} h at the service rate", SERIES["TEDOM"]),
                    (f"{_m(b['penalty_kzt'])} {CUR}", "Part-load fuel penalty",
                     f"{_n(b['penalty_kwh'] / 1e3)} MWh gas", SERIES["TEDOM"]),
                    (f"{_m(b['export_kzt'])} {CUR}", "Fuel burned for export",
                     f"{_n(b['exp'] / 1e3)} MWh exported, not compensated",
                     SERIES["Battery discharging"])])
            mt = T.months_table(x, units, inp)
            _h("Cost by month", help="Each month's fuel, service and grid, scaled to the whole "
               "month; the share above each bar is its complete hours. A month under the "
               "coverage is left out of the year.")
            rows = []
            for _, m in mt.iterrows():
                for k, lab in (("fuel_kzt", "Fuel"), ("service_kzt", "Service"),
                               ("grid_kzt", "Grid import")):
                    rows.append(dict(month=str(m.month), series=lab, v=m[k] / 1e6, kept=m.kept,
                                     share=f"{m.share:.0%}" if m.kept else "left out"))
            if rows:
                df = pd.DataFrame(rows)
                names = ["Fuel", "Service", "Grid import"]
                bars = alt.Chart(df).mark_bar().encode(
                    x=alt.X("month:N", title=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("sum(v):Q", title=f"M {CUR}"),
                    color=alt.Color("series:N", scale=_scale(names), title=None,
                                    legend=alt.Legend(orient="top", labelLimit=0)),
                    opacity=alt.condition("datum.kept", alt.value(1), alt.value(0.3)),
                    tooltip=["month:N", "series:N", alt.Tooltip("v:Q", format=",.1f"), "share:N"])
                lab = alt.Chart(df.drop_duplicates("month")).mark_text(dy=-6, fontSize=10).encode(
                    x="month:N", y=alt.value(8), text="share:N",
                    color=alt.condition("datum.kept", alt.value(MUTED), alt.value(RED)))
                st.altair_chart((bars + lab).properties(height=280), width="stretch")


def view_data(inp: T.Inputs, source: str) -> None:
    st.html('<div class="bp-label">ZHARKENT · MEASURED DATA</div>'
            '<div class="bp-title">How the plants run today</div>'
            '<div class="bp-run">Measured power of each engine and the grid exchange of each '
            'plant, step by step, before any battery. The bars show the whole period by month; '
            'pick a month for its steps.</div>')
    xs = {g: _steps(g, source, _items(inp), study_only=False) for g in ("K", "M")}
    months = sorted({str(p) for x in xs.values() for p in x["time"].dt.to_period("M").unique()})
    if not months:
        return
    cov = {}
    for g, x in xs.items():
        mt = T.months_table(x, T.GROUPS[g]["units"], inp)
        cov[g] = mt.set_index(mt["month"].astype(str))
    pick = st.selectbox("Month", months, index=max(0, len(months) - 2),
                        format_func=lambda m: pd.Period(m).strftime("%B %Y"), key="bp_data_month")
    for g in ("K", "M"):
        x, units = xs[g], T.GROUPS[g]["units"]
        mt = cov[g]
        with st.container(border=True):
            st.markdown(f'<div class="bp-title" style="font-size:1.15rem">{T.GROUPS[g]["name"]}</div>'
                        f'<div class="bp-sub">{T.GROUPS[g]["about"]}</div>', unsafe_allow_html=True)
            _h("Energy by month", "% above each bar = hours complete")
            rows = []
            for m, row in mt.iterrows():
                for u in units:
                    rows.append(dict(month=m, series=T.NAME[u], v=row[f"{u}_mwh"]))
                rows.append(dict(month=m, series="Grid import", v=row.imp_mwh))
                rows.append(dict(month=m, series="Export", v=-row.exp_mwh))
            df = pd.DataFrame(rows)
            names = [T.NAME[u] for u in units] + ["Grid import", "Export"]
            bars = alt.Chart(df).mark_bar().encode(
                x=alt.X("month:N", title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("sum(v):Q", title="MWh"),
                color=alt.Color("series:N", scale=_scale(names), title=None,
                                legend=alt.Legend(orient="top", labelLimit=0)),
                tooltip=["month:N", "series:N", alt.Tooltip("v:Q", format=",.0f")])
            pct = pd.DataFrame([dict(month=m, s=f"{row.share:.0%}") for m, row in mt.iterrows()])
            lab = alt.Chart(pct).mark_text(dy=-4, fontSize=10, color=MUTED).encode(
                x="month:N", y=alt.value(8), text="s:N")
            st.altair_chart((bars + lab).properties(height=260), width="stretch")
            sel = x[x["time"].dt.to_period("M").astype(str) == pick]
            _h(f"{pd.Period(pick).strftime('%B %Y')}, step by step")
            if not sel.empty:
                long = []
                for u in units:
                    long += [dict(time=a, series=T.NAME[u], kw=b) for a, b in zip(sel.time, sel[f"{u}_measured"])]
                long += [dict(time=a, series="Grid import", kw=b) for a, b in zip(sel.time, sel.grid_measured)]
                long += [dict(time=a, series="Load", kw=b) for a, b in zip(sel.time, sel.load)]
                n2 = [T.NAME[u] for u in units] + ["Grid import", "Load"]
                st.altair_chart(alt.Chart(pd.DataFrame(long)).mark_line(strokeWidth=1.2).encode(
                    x=alt.X("time:T", title=None), y=alt.Y("kw:Q", title="kW"),
                    color=alt.Color("series:N", scale=_scale(n2), title=None,
                                    legend=alt.Legend(orient="top", labelLimit=0)),
                    tooltip=["series:N", "time:T", alt.Tooltip("kw:Q", format=",.0f")])
                    .properties(height=260), width="stretch")
            else:
                st.caption("No complete steps this month.")
            with st.expander("Monthly table"):
                show = mt[[f"{u}_mwh" for u in units] + ["imp_mwh", "exp_mwh", "complete_h", "hours"]].copy()
                show.columns = [f"{T.LONG[u]} MWh" for u in units] + ["Import MWh", "Export MWh",
                                                                      "Hours complete", "Hours in month"]
                st.dataframe(show.round(0), width="stretch")


# ---- the page ------------------------------------------------------------------------------
def render() -> None:
    st.html(CSS)
    UT.step("Battery payback study")
    inp, source = inputs()
    ch = T.changed(inp)
    blocked = None
    if inp.tied and inp.tied_on >= inp.tied_off:
        blocked = "The tied engine must start at a lower charge than the one it stops at."
    elif not inp.tied and not inp.with_battery:
        blocked = "Tick at least one generator to work with the battery."
    if blocked:
        st.warning(blocked, icon=":material/warning:")
    if st.button("Run scenario", type="primary", key="bp_run", disabled=bool(blocked)):
        ss["bp_result"] = dict(inp=inp, source=source, time=dt.datetime.now(),
                               results=_run(inp, source))
    st.caption("Changed from the defaults: " + (", ".join(ch) if ch else "nothing"))
    view = P.switch("View", VIEWS, key="bp_view")
    if view == VIEWS[0]:
        res = ss.get("bp_result")
        if not res:
            st.info("Press **Run scenario** to run the rule for your battery and every size "
                    "compared, on all three plants.")
            return
        if res["inp"] != inp or res["source"] != source:
            st.warning("These results were run with other inputs. Press **Run scenario** to "
                       "run the ones above.", icon=":material/history:")
        with st.container(border=True):
            _report(res)
    elif view == VIEWS[1]:
        view_today(inp, source)
    else:
        view_data(inp, source)
