"""The Tailscale app, the colleague's Zharkent battery calculator, rebuilt on this page.

Its layout, its sidebar and defaults, its rule and its result formulas are his
(docs/zharkent-app/README.md, WALKTHROUGH.md and screens/): the sidebar with its five
groups, three views (Battery scenarios · Data · Today), a report per run with three
entity tabs, three cards whose arithmetic opens below them, eight charts and the inputs
table. The arithmetic is tailscale_method.py, which reproduces his published run step
for step on his own 5-minute steps.

Two things are not his and are said where they show: which measured steps the rule runs
on (his 5-minute steps when his run file is on disk, else this project's hourly table
built by his data rules), and a data check on the Data view that sets this project's
months beside his Data page. His RU translation, run history on a server and dark
theme are not copied: the page is in English, as his opens, and keeps runs for the
session.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, replace

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import tailscale_method as T

ss = st.session_state

# ---- his palette ----------------------------------------------------------------------
ACCENT, RED, INK, MUTED = "#0b6aa2", "#c0392b", "#1b1f24", "#5f6b7a"
C_RATE = {0.2: "#7f7f7f", 0.25: "#0072b2", 0.33: "#c27c2c", 0.5: "#2e8b57", 0.75: "#17becf",
          1.0: "#c2185b", 1.5: "#6a3d9a", 2.0: "#8c564b"}
SERIES = {"MWM": "#b5762a", "Zharkent 2": "#0a75ad", "Zharkent 3": "#2e8b47",
          "Grid import": "#c94040", "Export": "#c2457a", "Battery discharging": "#6f42c1",
          "Battery charging": "#b19cd9", "Load": INK, "Load + battery's own use": INK,
          "Running in the band": "#0a75ad", "Replacing import": "#d2691e",
          "Fuel": "#b5762a", "Service": "#1f86c1", "Engine start wear, with the battery": "#b5762a",
          "Battery wear": "#6f42c1", "Engine start wear, today": INK}
STATUS = {"datasheet": ("#0b6aa2", "#e8f2fa"), "placeholder": ("#c0392b", "#fdecea"),
          "confirmed": ("#2e7d32", "#eaf5ea")}
MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

CSS = """
<style>
.ts-label{font-family:%(mono)s;font-size:.78rem;letter-spacing:.18em;color:%(acc)s;font-weight:600;margin:.2rem 0 .3rem}
.ts-title{font-family:%(mono)s;font-size:1.55rem;font-weight:700;color:%(ink)s;margin:.1rem 0 .2rem}
.ts-run{color:%(muted)s;font-size:.95rem;margin-bottom:.6rem}
.ts-ph{border-left:3px solid %(red)s;padding:.35rem .8rem;color:%(red)s;font-size:.86rem;margin:.4rem 0 .8rem;line-height:1.45}
.ts-about{color:%(muted)s;font-size:.95rem;margin:.2rem 0 .6rem}
.ts-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:.3rem 0 .6rem}
@media (max-width:820px){.ts-cards{grid-template-columns:1fr}}
.ts-card{border:1px solid #d5dbe1;border-radius:2px;padding:12px 14px;background:#fff}
.ts-card-k{font-size:.8rem;color:%(muted)s;margin-bottom:.35rem}
.ts-card-v{font-family:%(mono)s;font-size:1.45rem;font-weight:700;color:%(ink)s;margin-bottom:.25rem}
.ts-card-s{font-size:.8rem;color:%(muted)s;line-height:1.35}
.ts-h{font-family:%(mono)s;font-size:1.02rem;font-weight:700;color:%(ink)s;margin:.9rem 0 .1rem}
.ts-sub{font-size:.85rem;color:%(muted)s;margin:0 0 .3rem}
.ts-badge{display:inline-block;font-size:.72rem;padding:0 .4rem;border:1px solid;border-radius:2px}
.ts-tbl{width:100%%;border-collapse:collapse;font-size:.82rem}
.ts-tbl th{text-align:left;color:%(ink)s;font-weight:600;border-bottom:1px solid #d5dbe1;padding:6px 6px}
.ts-tbl td{border-bottom:1px solid #eef1f4;padding:6px 6px;vertical-align:top;color:%(ink)s}
.ts-tbl tr.ts-chg td{background:#fff7e0}
.ts-tbl td.ts-n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.ts-stats{display:grid;grid-template-columns:repeat(var(--n,4),minmax(0,1fr));gap:14px;margin:.4rem 0 .8rem}
@media (max-width:820px){.ts-stats{grid-template-columns:1fr 1fr}}
.ts-stat{border-left:2px solid %(ink)s;padding:2px 10px}
.ts-stat-v{font-family:%(mono)s;font-size:1.15rem;font-weight:700;color:%(ink)s}
.ts-stat-k{font-size:.85rem;color:%(ink)s}
.ts-stat-s{font-size:.78rem;color:%(muted)s}
.ts-foot{font-size:.8rem;color:%(muted)s;line-height:1.45;margin-top:.8rem}
.ts-ours{border-left:3px solid %(acc)s;padding:.35rem .8rem;color:%(ink)s;font-size:.86rem;margin:.4rem 0 .8rem;background:#f3f8fc}
</style>
""" % dict(mono=MONO, acc=ACCENT, ink=INK, muted=MUTED, red=RED)

# ---- his "?" notes (README appendix B) --------------------------------------------------
HELP = {
    "view": "Battery scenarios: run the rule with any inputs. Data: the measured data hour by "
            "hour. Today: what the plant costs now, from the meters.",
    "name": "Your label for this run; it shows in the run history.",
    "capacity": "This battery gets the cards, the 5-minute decisions and the day charts.",
    "c_rate": "Power = capacity × C-rate. 0.5 C: a full battery empties in 2 hours at full "
              "power; 1 C: in 1 hour.",
    "band": "Richard, 14 Oct 2026: the optimiser runs engines only in the efficient band "
            "(datasheet floor is 50 %).",
    "start_wear": "Handover placeholder. To be set by the service company (warm vs cold).",
    "service": "Service company's presented figure; used only to set the cost per engine hour. "
               "Cost per engine hour = this × rated kW.",
    "export": "Richard, 14 Oct 2026: export forbidden by default; also run with it allowed.",
    "bridge": "Gaps in one signal up to this long are bridged by a straight line between the "
              "readings either side (tagged 'filled'); longer gaps stay empty. Krakhmal's "
              "December 2025 and February 2026 are never filled. 0 = no filling.",
    "gas": "Richard, 14 Oct 2026.",
    "grid": "Richard, 14 Oct 2026; flat, no capacity charge assumed.",
    "vat": "Kazakhstan VAT 12 %; prices below are taken EX VAT (client recovers input VAT).",
    "heat": "Tedom technical sheet basis 34 MJ/m³ (Jenbacher uses 9.5); confirm from supply "
            "contract.",
    "caps": "Battery capacities compared in every run (each with every C-rate below).",
    "crates": "C-rates compared in every run; 0.33 C on 3 MWh = 1 MW.",
    "usd_kwh": "Richard, 14 Oct 2026.",
    "usd_kw": "Richard, 14 Oct 2026.",
    "kzt_usd": "Placeholder exchange rate.",
    "cycle": "Battery life in cycles; life in years = this ÷ cycles a year (capped at the "
             "calendar life). Typical LFP warranty figure; replace with the supplier's.",
    "calendar": "A battery ages even when it cycles little; its life never exceeds this.",
    "rte": "Handover placeholder; applied as √RTE each way.",
    "window": "Handover placeholder.",
    "own": "Handover placeholder: cooling and controls.",
    "source": "Not in his app. His rule runs on his own 5-minute steps; this page runs it on "
              "his steps when his run file is on disk, else on this project's hourly table, "
              "built by his data rules. The arithmetic is the same either way; the steps are "
              "not, and the Data view says how they differ.",
}
CAPS_OPTS = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 5.5, 6.0, 7.0, 8.0, 10.0]
CRATE_OPTS = [0.2, 0.25, 0.33, 0.5, 0.75, 1.0, 1.5, 2.0]
SRC_HIS, SRC_OURS = "His 5-minute steps", "This project's hourly table"


def _g(x: float) -> str:
    return f"{x:g}"


def _m(v: float, d: int = 1) -> str:
    return f"{v / 1e6:,.{d}f} M"


def _n(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")


def _size(e: float, c: float) -> str:
    p = e * c
    return f"{_g(e)} MWh × {_g(c)} C = {p:.3g} MW"


# ---- the sidebar ---------------------------------------------------------------------------
def sidebar() -> tuple[str, str, T.Inputs, str, bool]:
    D = T.DEFAULTS
    with st.sidebar:
        st.radio("Language / Язык", ["EN"], horizontal=True, key="ts_lang",
                 help="His app also has RU; this page carries EN, as his opens.")
        view = st.radio("View", ["Battery scenarios", "Data", "Today"], horizontal=True,
                        key="ts_view", help=HELP["view"])
        st.header("Zharkent")
        name = st.text_input("Scenario name", "Scenario", key="ts_name", help=HELP["name"])
        st.markdown("**Your battery**")
        st.caption("The cards, the day charts and the decisions follow this battery. It is "
                   "always calculated, whatever the comparison lists below.")
        c1, c2 = st.columns(2)
        with c1:
            cap = st.number_input("Capacity, MWh", 0.5, 30.0, D.capacity_mwh, step=0.5,
                                  key="ts_cap", help=HELP["capacity"])
        with c2:
            crate = st.selectbox("C-rate", CRATE_OPTS, index=CRATE_OPTS.index(D.c_rate),
                                 format_func=lambda v: f"{_g(v)} C", key="ts_crate",
                                 help=HELP["c_rate"])
        st.caption(f"Power = {_g(cap)} MWh × {_g(crate)} C = {cap * crate:.3g} MW")
        with st.expander("Engines and the rule", expanded=True):
            band = st.slider("Band: engines run at least at, % of rated", 50, 100,
                             int(round(D.band * 100)), key="ts_band", help=HELP["band"])
            wear = st.number_input("Start wear, engine hours per start", 0.0, 20.0,
                                   D.start_wear_h, step=0.5, key="ts_wear",
                                   help=HELP["start_wear"])
            service = st.number_input("Service, KZT per kWh at rated output", 0.0, 30.0,
                                      D.service_kzt_kwh, step=0.5, key="ts_service",
                                      help=HELP["service"])
            export = st.checkbox("Allow export (not compensated)", D.allow_export,
                                 key="ts_export", help=HELP["export"])
        with st.expander("Data"):
            bridge = st.number_input("Bridge data gaps up to, hours", 0.0, 24.0, D.bridge_h,
                                     step=0.5, key="ts_bridge", help=HELP["bridge"])
            have_his = T.his_steps_available()
            source = st.radio("Measured steps (not in his app)", [SRC_HIS, SRC_OURS],
                              index=0 if have_his else 1, key="ts_source",
                              help=HELP["source"], disabled=not have_his)
            if not have_his:
                st.caption("His run file is not on this machine "
                           "(`.playwright/output/zharkent/`), so the rule runs on this "
                           "project's hourly table.")
                source = SRC_OURS
        with st.expander("Prices"):
            gas = st.number_input("Gas, KZT/m³ incl. VAT", 1.0, 500.0, D.gas_kzt_m3,
                                  key="ts_gas", help=HELP["gas"])
            grid = st.number_input("Grid, KZT/kWh incl. VAT", 1.0, 200.0, D.grid_kzt_kwh,
                                   step=0.5, key="ts_grid", help=HELP["grid"])
            vat = st.number_input("VAT, %", 0.0, 30.0, D.vat * 100, key="ts_vat",
                                  help=HELP["vat"])
            heat = st.number_input("Gas heating value, kWh/m³", 8.0, 11.0, D.gas_kwh_m3,
                                   step=0.01, key="ts_heat", help=HELP["heat"])
        with st.expander("Other sizes for the payback charts"):
            caps = st.multiselect("Capacities, MWh", CAPS_OPTS, list(D.capacities),
                                  format_func=_g, key="ts_caps", help=HELP["caps"])
            crates = st.multiselect("C-rates", CRATE_OPTS, list(D.c_rates),
                                    format_func=lambda v: f"{_g(v)} C", key="ts_crates",
                                    help=HELP["crates"])
            st.caption(f"{len(caps) * len(crates)} combinations, plus your battery. They only "
                       "feed the payback, saving and starts charts. More sizes take longer: "
                       "about a second each on the server.")
        with st.expander("Battery"):
            usd_kwh = st.number_input("Battery, USD per kWh", 0.0, 1000.0, D.bat_usd_kwh,
                                      step=5.0, key="ts_usdkwh", help=HELP["usd_kwh"])
            usd_kw = st.number_input("Inverter, USD per kW", 0.0, 1000.0, D.inv_usd_kw,
                                     step=5.0, key="ts_usdkw", help=HELP["usd_kw"])
            kzt_usd = st.number_input("KZT per USD", 100.0, 1000.0, D.kzt_usd,
                                      key="ts_kztusd", help=HELP["kzt_usd"])
            cycles = st.number_input("Cycle life, full cycles", 1000, 20000, int(D.cycle_life),
                                     step=500, key="ts_cycles", help=HELP["cycle"])
            cal = st.number_input("Calendar life, years", 5, 30, int(D.calendar_life),
                                  key="ts_cal", help=HELP["calendar"])
            st.caption("Battery life = cycle life ÷ cycles a year, never beyond the calendar "
                       "life. Payback must come before it.")
            rte = st.slider("Round-trip efficiency, %", 70, 98, int(round(D.rte * 100)),
                            key="ts_rte", help=HELP["rte"])
            lo, hi = st.slider("Usable charge window, %", 0, 100,
                               (int(D.soc_lo * 100), int(D.soc_hi * 100)), key="ts_window",
                               help=HELP["window"])
            own = st.number_input("Battery's own consumption, kW", 0.0, 200.0, D.own_kw,
                                  key="ts_own", help=HELP["own"])
        inp = replace(D, capacity_mwh=float(cap), c_rate=float(crate), band=band / 100.0,
                      start_wear_h=float(wear), service_kzt_kwh=float(service),
                      allow_export=bool(export), bridge_h=float(bridge), gas_kzt_m3=float(gas),
                      grid_kzt_kwh=float(grid), vat=float(vat) / 100.0, gas_kwh_m3=float(heat),
                      capacities=tuple(sorted(float(c) for c in caps)) or D.capacities,
                      c_rates=tuple(sorted(float(c) for c in crates)) or D.c_rates,
                      bat_usd_kwh=float(usd_kwh), inv_usd_kw=float(usd_kw),
                      kzt_usd=float(kzt_usd), cycle_life=float(cycles),
                      calendar_life=float(cal), rte=rte / 100.0, soc_lo=lo / 100.0,
                      soc_hi=hi / 100.0, own_kw=float(own))
        ch = T.changed(inp)
        st.caption("Changed from inputs.py: " + (", ".join(ch) if ch else "nothing"))
        go = st.button("Run scenario", type="primary", key="ts_run", width="stretch")
    return view, name, inp, source, go


# ---- the arithmetic, cached ------------------------------------------------------------------
@st.cache_resource(max_entries=8, show_spinner=False)
def _steps(group: str, source: str, items: tuple, study_only: bool = True):
    inp = T.Inputs(**dict(items))
    if source == SRC_HIS and T.his_steps_available():
        return T.his_steps(group)
    return T.hourly_steps(group, inp, study_only=study_only)


@st.cache_resource(max_entries=4, show_spinner=False)
def _compute(items: tuple, source: str) -> dict:
    inp = T.Inputs(**dict(items))
    return {g: T.run_group(g, inp, x=_steps(g, source, items)) for g in T.GROUPS}


def _items(inp: T.Inputs) -> tuple:
    return tuple(sorted(asdict(inp).items()))


# ---- charts --------------------------------------------------------------------------------
def _legend_sel():
    return alt.selection_point(fields=["series"], bind="legend")


def _scale(names):
    return alt.Scale(domain=list(names), range=[SERIES.get(n, C_RATE.get(n, "#888")) for n in names])


def _crate_scale(crates):
    labels = [f"{_g(c)} C" for c in crates]
    return alt.Scale(domain=labels, range=[C_RATE.get(c, "#888") for c in crates])


def _line_by_size(df: pd.DataFrame, y: str, ytitle: str, crates, today: float | None = None,
                  fmt: str = ",.1f", caps=None):
    sel = _legend_sel()
    lo_, hi_ = (min(caps), max(caps)) if caps else (1.0, 7.0)
    ticks = list(range(int(np.floor(lo_)), int(np.ceil(hi_)) + 1))
    base = alt.Chart(df).encode(
        x=alt.X("e_mwh:Q", title="battery capacity, MWh",
                scale=alt.Scale(domain=[lo_, hi_], nice=False),
                axis=alt.Axis(values=ticks, format="d")),
        y=alt.Y(f"{y}:Q", title=ytitle),
        color=alt.Color("series:N", scale=_crate_scale(crates), title=None,
                        legend=alt.Legend(orient="top", labelLimit=0)),
        opacity=alt.condition(sel, alt.value(1), alt.value(0.12)),
        tooltip=[alt.Tooltip("label:N", title="size"), alt.Tooltip(f"{y}:Q", format=fmt)])
    ch = base.mark_line(strokeWidth=2) + base.mark_point(filled=True, size=55)
    ch = ch.add_params(sel)
    if today is not None:
        ch = ch + alt.Chart(pd.DataFrame({"y": [today], "series": ["Today"]})).mark_rule(
            strokeDash=[5, 4], color=INK).encode(y="y:Q")
    return ch.properties(height=300)


def _sizes_frame(sizes: pd.DataFrame) -> pd.DataFrame:
    d = sizes.copy()
    d["series"] = d["c_rate"].map(lambda c: f"{_g(c)} C")
    d["label"] = [_size(e, c) for e, c in zip(d.e_mwh, d.c_rate)]
    d["payback"] = d["payback_y"]
    d["profit_M"] = d["profit_kzt"] / 1e6
    return d


def _h(title: str, sub: str | None = None, help: str | None = None):
    st.markdown(f'<div class="ts-h">{title}</div>', unsafe_allow_html=True, help=help)
    if sub:
        st.markdown(f'<div class="ts-sub">{sub}</div>', unsafe_allow_html=True)


# ---- the report ----------------------------------------------------------------------------
def _cards(r: T.Run) -> None:
    t, y, b = r.today, r.yours, r.best
    pay = "never" if y.payback_y != y.payback_y else f"{y.payback_y:.1f} y payback"
    cards = [
        ("Today, measured", f"{_m(t.cost_kzt)} KZT/yr",
         f"{_n(t.run_h)} engine h · {_n(t.starts)} starts · import {_n(t.imp_kwh / 1e3)} MWh"),
        (f"Your battery: {_size(y.e_mwh, y.c_rate)}", pay,
         f"saving {_m(y.saving_kzt)} · life {y.life_y:.1f} y · profit over life "
         f"{_m(y.profit_kzt)} · {_n(y.starts)} starts"),
    ]
    if b is not None:
        cards.append((f"Shortest payback, in the band and before wear-out: "
                      f"{_size(b.e_mwh, b.c_rate)}", f"{b.payback_y:.1f} y",
                      f"saving {_m(b.saving_kzt)} · life {b.life_y:.1f} y · profit over life "
                      f"{_m(b.profit_kzt)} · {_n(b.starts)} starts"))
    else:
        cards.append(("Shortest payback, in the band and before wear-out", "none",
                      "no size compared pays back before it wears out"))
    st.html('<div class="ts-cards">' + "".join(
        f'<div class="ts-card"><div class="ts-card-k">{k}</div><div class="ts-card-v">{v}</div>'
        f'<div class="ts-card-s">{s}</div></div>' for k, v, s in cards) + "</div>")
    with st.expander("How each value was built", expanded=False):
        cols = st.columns(3)
        with cols[0]:
            st.markdown("**Today, measured**")
            st.markdown("\n".join("- " + s for s in _today_lines(r)))
        with cols[1]:
            st.markdown(f"**Your battery: {_size(y.e_mwh, y.c_rate)}**")
            st.markdown("\n".join("- " + s for s in _size_lines(r, y)))
        with cols[2]:
            if b is not None:
                st.markdown(f"**Shortest payback: {_size(b.e_mwh, b.c_rate)}**")
                st.markdown("\n".join("- " + s for s in _size_lines(r, b)))


def _today_lines(r: T.Run) -> list[str]:
    t, inp = r.today, r.inp
    units = T.GROUPS[r.group]["units"]
    hours = " + ".join(f"{_n(t[f'{u}_run_h'])} h × {_n(inp.om_h(u))}" for u in units)
    return [f"Today {_m(t.cost_kzt)} KZT/yr = fuel {_m(t.fuel_kzt)} + service {_m(t.om_kzt)} "
            f"+ grid {_m(t.grid_kzt)}",
            f"Fuel = {_n(t.fuel_kwh / 1e3)} MWh of gas × {inp.gas_kzt_kwh:.3f} KZT",
            f"Service = engine hours ({hours}) + start wear {inp.start_wear_h:g} h × "
            f"{_n(t.starts)} starts × the hourly rate",
            f"Grid = import {_n(t.imp_kwh / 1e3)} MWh × {inp.grid_ex_vat:.2f} KZT",
            f"From {_n(t.attrs.get('complete_h', 0))} complete hours, "
            f"{len(t.attrs.get('months', []))} months used, scaled to a year"]


def _size_lines(r: T.Run, y: pd.Series) -> list[str]:
    t, inp = r.today, r.inp
    e, p = 1000 * y.e_mwh, 1000 * y.e_mwh * y.c_rate
    pay = ("never" if y.payback_y != y.payback_y else
           f"{y.payback_y:.1f} years = {_m(y.capex_kzt)} ÷ {_m(y.saving_kzt)}")
    below = 100 * y.oob_h / y.run_h if y.run_h else 0.0
    return [f"Battery {_size(y.e_mwh, y.c_rate)}",
            f"Saving {_m(y.saving_kzt)} KZT/yr = today {_m(t.cost_kzt)} – with battery "
            f"{_m(y.cost_kzt)}",
            f"fuel {_m(t.fuel_kzt)} → {_m(y.fuel_kzt)}, service {_m(t.om_kzt)} → "
            f"{_m(y.om_kzt)}, grid {_m(t.grid_kzt)} → {_m(y.grid_kzt)}",
            f"Running in the band {_m(y.band_kzt)} = (today {t.kzt_per_kwh_gen:.2f} – "
            f"{y.kzt_per_kwh_gen:.2f} KZT per kWh the engines make) × today's "
            f"{t.gen_kwh / 1e6:.2f} GWh",
            f"Replacing import {_m(y.import_kzt)} = saving – running in the band (import "
            f"{_n(t.imp_kwh / 1e3)} → {_n(y.imp_kwh / 1e3)} MWh)",
            f"Battery cost {_m(y.capex_kzt)} KZT = ({_n(e)} kWh × {inp.bat_usd_kwh:g} + "
            f"{_n(p)} kW × {inp.inv_usd_kw:g}) = {_n(y.capex_kzt / inp.kzt_usd)} USD × "
            f"{inp.kzt_usd:g} KZT/USD",
            f"Payback {pay}",
            f"Engine starts {_n(y.starts)} a year (today {_n(t.starts)}); engine hours "
            f"{_n(y.run_h)} (today {_n(t.run_h)})",
            f"Below the {inp.band * 100:g} % band {_n(y.oob_h)} h a year ({below:.1f} % of "
            "engine hours)",
            f"Battery life {y.life_y:.1f} years = {inp.cycle_life:g} cycles ÷ {y.cycles:.0f} a "
            "year" + (f", capped at {inp.calendar_life:g}" if y.life_y >= inp.calendar_life else ""),
            f"Pays back before it wears out: {'yes' if y.pays_back else 'no'}"
            + ("" if y.payback_y != y.payback_y else
               f" (payback {y.payback_y:.1f} y vs life {y.life_y:.1f} y)"),
            f"Profit over the battery's life {_m(y.profit_kzt)} KZT = {_m(y.saving_kzt)} × "
            f"{y.life_y:.1f} years – {_m(y.capex_kzt)}",
            f"From {_n(t.attrs.get('complete_h', 0))} complete hours, "
            f"{len(t.attrs.get('months', []))} months used, scaled to a year"]


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
    key = f"ts_day_{r.group}"
    default = dt.date(2026, 4, 21) if dt.date(2026, 4, 21) in days else days[len(days) // 2]
    ss.setdefault(key, default)
    if ss[key] not in days:
        ss[key] = min(days, key=lambda d: abs((d - ss[key]).days))
    i = days.index(ss[key])
    y = r.yours
    step_min = round(x.attrs.get("dt", 1.0) * 60)
    _h(f"{ss[key]:%Y-%m-%d}, every {step_min} minutes, {_size(y.e_mwh, y.c_rate)}",
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
    meas = {T.NAME[u]: x[f"{u}_measured"].values[mask] for u in units}
    g = x["grid_measured"].values[mask]
    rows = []
    for n, v in meas.items():
        rows += [dict(time=a, series=n, kw=b) for a, b in zip(tt, v)]
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
    hi = max(3500.0, float(max(load.kw.max(), need.kw.max(), r_df.groupby("time").kw.sum().max())) * 1.1)
    order_m = [T.NAME[u] for u in units] + ["Grid import", "Export"]
    order_r = [T.NAME[u] for u in units] + ["Battery discharging", "Grid import",
                                            "Battery charging", "Export"]

    step = pd.Timedelta(hours=x.attrs.get("dt", 1.0))

    def bars(df, order, line, line_name):
        sel = _legend_sel()
        # each step drawn across its own interval, so the columns touch as his do
        b = alt.Chart(df.assign(end=df["time"] + step)).mark_bar().encode(
            x=alt.X("time:T", title=None, axis=alt.Axis(format="%H:%M")),
            x2="end:T",
            y=alt.Y("sum(kw):Q", title="kW", scale=alt.Scale(domain=[lo, hi])),
            color=alt.Color("series:N", scale=_scale(order + [line_name]), sort=order, title=None,
                            legend=alt.Legend(orient="top", labelLimit=0)),
            order=alt.Order("rank:Q"),
            opacity=alt.condition(sel, alt.value(1), alt.value(0.15)),
            tooltip=["series:N", alt.Tooltip("time:T", format="%H:%M"),
                     alt.Tooltip("kw:Q", format=",.0f")],
        ).transform_calculate(rank=f"indexof({order!r}, datum.series)").add_params(sel)
        ln = alt.Chart(line.assign(series=line_name)).mark_line(
            color=INK, strokeWidth=1.6, interpolate="step-after").encode(
            x="time:T", y="kw:Q")
        return (b + ln).properties(height=300)

    st.markdown('<div class="ts-h">Today, measured</div>', unsafe_allow_html=True)
    st.altair_chart(bars(m_df, order_m, load, "Load"), width="stretch")
    st.markdown('<div class="ts-h">With the battery, by the rule</div>', unsafe_allow_html=True)
    st.altair_chart(bars(r_df, order_r, need, "Load + battery's own use"),
                    width="stretch")
    soc = pd.DataFrame(dict(time=tt, soc=100 * s["soc"][mask]))
    st.altair_chart(alt.Chart(soc).mark_line(color=SERIES["Battery discharging"]).encode(
        x=alt.X("time:T", title=None, axis=alt.Axis(format="%H:%M")),
        y=alt.Y("soc:Q", title="% charge", scale=alt.Scale(domain=[0, 100]))).properties(
        height=130), width="stretch")


def _wear_charts(r: T.Run, crate_key: str) -> None:
    y, b = r.yours, r.best
    sizes_ = [(y.e_mwh, y.c_rate)] + ([(b.e_mwh, b.c_rate)] if b is not None else [])
    rows = []
    for e, c in dict.fromkeys(sizes_):
        for w, pb in T.start_wear_curve(r, e, c):
            rows.append(dict(h=w, payback=pb, series=_size(e, c)))
    _h("Start wear", "Payback as the engine hours charged per start change: no published "
       "figure exists for gas engines, so it is shown across the range.",
       help="Payback of your battery and of the shortest-payback size at each start wear.")
    if rows:
        df = pd.DataFrame(rows)
        sel = _legend_sel()
        ch = alt.Chart(df).encode(
            x=alt.X("h:Q", title="engine hours charged per start"),
            y=alt.Y("payback:Q", title="payback, years"),
            color=alt.Color("series:N", title=None, legend=alt.Legend(orient="top"),
                            scale=alt.Scale(range=["#0072b2", "#c27c2c"])),
            opacity=alt.condition(sel, alt.value(1), alt.value(0.12)),
            tooltip=["series:N", "h:Q", alt.Tooltip("payback:Q", format=".2f")])
        st.altair_chart((ch.mark_line() + ch.mark_point(filled=True)).add_params(sel)
                        .properties(height=260), width="stretch")

    _h("Wear per year: engine starts vs battery cycles",
       "Where the solid line crosses the flat one, engine starts cost as much as the "
       "battery's cycling.",
       help="Engine start wear = starts × engine hours per start × the hourly service rate. "
            "Battery wear = its price ÷ its life.")
    w = pd.DataFrame(T.wear_vs_start(r, y))
    long = pd.concat([
        w.assign(series="Engine start wear, with the battery", v=w.with_battery / 1e6),
        w.assign(series="Engine start wear, today", v=w.today / 1e6),
        w.assign(series="Battery wear", v=w.battery / 1e6)])
    sel = _legend_sel()
    names = ["Engine start wear, with the battery", "Engine start wear, today", "Battery wear"]
    st.altair_chart(alt.Chart(long).mark_line(point=True).encode(
        x=alt.X("h:Q", title="engine hours charged per start"),
        y=alt.Y("v:Q", title="M KZT per year"),
        color=alt.Color("series:N", scale=_scale(names), title=None, legend=alt.Legend(orient="top", labelLimit=0)),
        strokeDash=alt.StrokeDash("series:N", legend=None,
                                  scale=alt.Scale(domain=names, range=[[5, 4], [5, 4], [1, 0]])),
        opacity=alt.condition(sel, alt.value(1), alt.value(0.12)),
        tooltip=["series:N", "h:Q", alt.Tooltip("v:Q", format=",.1f")]).add_params(sel)
        .properties(height=260), width="stretch")

    _h("Wear per year by battery size")
    crates = list(r.inp.c_rates)
    c = st.segmented_control("C-rate", crates, default=0.33 if 0.33 in crates else crates[0],
                             format_func=lambda v: f"{_g(v)} C", key=crate_key)
    c = c if c is not None else crates[0]
    d = r.sizes[r.sizes.c_rate == c].sort_values("e_mwh")
    rows = []
    for _, s in d.iterrows():
        lab = f"{_g(s.e_mwh)} MWh ({s.e_mwh * s.c_rate:.3g} MW)"
        rows.append(dict(size=lab, series="Engine start wear, with the battery",
                         v=s.start_wear_kzt / 1e6, k=s.e_mwh))
        rows.append(dict(size=lab, series="Battery wear", v=s.battery_wear_kzt / 1e6, k=s.e_mwh))
    if rows:
        df = pd.DataFrame(rows)
        order = [f"{_g(e)} MWh ({e * c:.3g} MW)" for e in d.e_mwh]
        names = ["Engine start wear, with the battery", "Battery wear"]
        bars = alt.Chart(df).mark_bar().encode(
            x=alt.X("size:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("sum(v):Q", title="M KZT per year"),
            color=alt.Color("series:N", scale=_scale(names), title=None, legend=alt.Legend(orient="top", labelLimit=0)),
            tooltip=["size:N", "series:N", alt.Tooltip("v:Q", format=",.1f")])
        today = r.today.start_wear_kzt / 1e6
        rule = alt.Chart(pd.DataFrame({"y": [today]})).mark_rule(strokeDash=[5, 4], color=INK).encode(y="y:Q")
        st.altair_chart((bars + rule).properties(height=280), width="stretch")
        st.caption(f"Dashed: engine start wear today, {today:,.1f} M KZT per year.")


def _report(run: dict) -> None:
    inp, res = run["inp"], run["results"]
    ph = ", ".join(T.PLACEHOLDERS)
    st.html(
        '<div class="ts-label">ZHARKENT · BATTERY SCENARIO</div>'
        f'<div class="ts-title">{run["name"]}</div>'
        f'<div class="ts-run">Run {run["time"]:%d %b %Y, %H:%M}. Your battery: '
        f'{_size(inp.capacity_mwh, inp.c_rate)}. Start wear {inp.start_wear_h:g} engine hours per '
        f'start. Band {inp.band * 100:g} %.</div>'
        f'<div class="ts-ph">Placeholder inputs in use: {ph}.</div>'
        f'<div class="ts-ours">Measured steps: <b>{run["source"]}</b>'
        + ("" if run["source"] == SRC_HIS else
           " — his rule and formulas, on this project's hourly table built by his data "
           "rules; his own figures come from his 5-minute steps, so they differ (Data view: "
           "the data check)") + ".</div>")
    labels = {g: v["name"] for g, v in T.GROUPS.items()}
    g = st.segmented_control("Entity", list(T.GROUPS), default="K", format_func=labels.get,
                             key="ts_entity", label_visibility="collapsed") or "K"
    r = res[g]
    st.html(f'<div class="ts-about">{T.GROUPS[g]["about"]}</div>')
    _cards(r)
    d = _sizes_frame(r.sizes)
    crates = list(inp.c_rates)

    _h("Payback by battery size", "Years for the saving to repay the battery. Lower is better.",
       help="Simple payback = battery price ÷ saving a year. Sizes that keep the engines below "
            "the band more than 1 % of their running hours are left out.")
    ok = d[d.in_band & d.payback.notna()]
    st.altair_chart(_line_by_size(ok, "payback", "years", crates, fmt=".2f", caps=inp.capacities),
                    width="stretch")

    _h("Profit over the battery's life",
       "What each size earns over its life, after paying for itself. Higher is better.",
       help="Profit over life = saving × life – price.")
    st.altair_chart(_line_by_size(d[d.in_band], "profit_M", "M KZT over the battery's life",
                                  crates, caps=inp.capacities), width="stretch")

    _h("Where the saving comes from",
       help="Running in the band = (today's – the rule's KZT per kWh the engines make) × "
            "today's generation. Replacing import = saving – running in the band.")
    c = st.segmented_control("C-rate", crates, default=0.33 if 0.33 in crates else crates[0],
                             format_func=lambda v: f"{_g(v)} C", key=f"ts_split_c_{g}")
    c = c if c is not None else crates[0]
    s = d[d.c_rate == c].sort_values("e_mwh")
    rows = []
    for _, z in s.iterrows():
        lab = f"{_g(z.e_mwh)} MWh ({z.e_mwh * z.c_rate:.3g} MW)"
        rows.append(dict(size=lab, series="Running in the band", v=z.band_kzt / 1e6, k=0))
        rows.append(dict(size=lab, series="Replacing import", v=z.import_kzt / 1e6, k=1))
    if rows:
        names = ["Running in the band", "Replacing import"]
        order = [f"{_g(e)} MWh ({e * c:.3g} MW)" for e in s.e_mwh]
        sel = _legend_sel()
        st.altair_chart(alt.Chart(pd.DataFrame(rows)).mark_bar().encode(
            x=alt.X("size:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("sum(v):Q", title="M KZT per year"),
            color=alt.Color("series:N", scale=_scale(names), title=None, legend=alt.Legend(orient="top", labelLimit=0)),
            order=alt.Order("k:Q", sort="ascending"),
            opacity=alt.condition(sel, alt.value(1), alt.value(0.15)),
            tooltip=["size:N", "series:N", alt.Tooltip("v:Q", format=",.1f")]).add_params(sel)
            .properties(height=300), width="stretch")

    _h("Engine starts per year", help="Starts a year with each size; today dashed.")
    st.altair_chart(_line_by_size(d, "starts", "starts per year", crates, today=r.today.starts,
                                  fmt=",.0f", caps=inp.capacities), width="stretch")

    _day_chart(r)
    _wear_charts(r, f"ts_wear_c_{g}")
    _periods(r)

    _h("Inputs of this run",
       f"Derived: gas {inp.gas_kzt_kwh * 1000:,.0f} KZT per MWh of gas · grid "
       f"{inp.grid_ex_vat:.2f} KZT/kWh · engine hour MWM {inp.om_h('mwm'):,.0f}, Jenbacher "
       f"{inp.om_h('zh2'):,.0f} KZT. Highlighted rows were changed for this run.")
    chg = set(T.changed(inp))
    rows = []
    for row in T.inputs_table(inp):
        fg, bg = STATUS[row["status"]]
        hit = any(c.split(" ")[0].lower() in row["input"].lower() for c in chg)
        rows.append(f'<tr class="{"ts-chg" if hit else ""}"><td>{row["input"]}</td>'
                    f'<td>{row["value"]}</td><td>{row["source"]}</td>'
                    f'<td><span class="ts-badge" style="color:{fg};border-color:{fg};'
                    f'background:{bg}">{row["status"]}</span></td></tr>')
    st.html('<table class="ts-tbl"><thead><tr><th>Input</th><th>Value</th><th>Source</th>'
            '<th>Status</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>"
            '<div class="ts-foot">The rule: an engine runs only if it can work at or above the '
            'band, or if the other engines plus the battery cannot cover the load. Engines are '
            'taken as always available. Every step of measured data where the power balance '
            'closes is simulated (gaps up to the fill limit bridged); stretches of data start at '
            '50 % charge with the engines as measured. Today\'s operation is costed on the same '
            'steps, so the comparison is like for like. Battery life = cycle life ÷ cycles a '
            'year, capped at the calendar life; a size counts only if it pays back before it '
            'wears out.</div>')


def _periods(r: T.Run) -> None:
    """This project's "Dispatch by period" on his rule: the plant's own meters (the
    Measured chart) above, your battery under his rule below, hour by hour with the
    hover panel, the tables and the starts -- the same view as the dispatch study's."""
    import app_periods as A
    state = T.period_state(r)
    st.html('<div class="ts-ours">' + "This project's period view (not in his app): the meters "
            "as they ran, then your battery under his rule, hour by hour on "
            f"{state['days']} whole days of the {r.x.attrs.get('source', 'steps')}"
            + (f"; {state['hours_dropped']:,} h in days the data does not complete are not drawn"
               if state["hours_dropped"] > 0 else "")
            + ". The saving in the hover panel is his: today's cost of the hour less the "
              "rule's, in fuel, engine hours, grid and start wear.</div>")
    A.render_periods(state)


# ---- the views -------------------------------------------------------------------------------
def _history() -> dict | None:
    runs = ss.get("ts_runs", [])
    if not runs:
        return None
    st.markdown("## Run history")
    rows = []
    for i, r in enumerate(runs):
        best = {}
        for g, v in r["results"].items():
            b = v.best
            best[f"{T.GROUPS[g]['name'].split(' ')[0]} best"] = (
                f"{_g(b.e_mwh)} MWh × {_g(b.c_rate)} C: {b.payback_y:.1f} y" if b is not None else "—")
        rows.append({"name": r["name"], "run": f"{r['time']:%d.%m.%Y %H:%M}",
                     "your battery": _size(r["inp"].capacity_mwh, r["inp"].c_rate), **best,
                     "changed": ", ".join(T.changed(r["inp"])) or "—"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    # the run to show lives in session state only (a new run sets it), so the widget is
    # never handed a default as well
    if ss.get("ts_show") not in range(len(runs)):
        ss["ts_show"] = len(runs) - 1
    pick = st.selectbox("Show", list(range(len(runs))),
                        format_func=lambda i: f"{runs[i]['name']} · {runs[i]['time']:%d.%m %H:%M}",
                        key="ts_show")
    return runs[pick]


def _ensure_default(source: str) -> None:
    if ss.get("ts_runs"):
        return
    with st.spinner("Running the default inputs (24 sizes on each entity)…"):
        res = _compute(_items(T.DEFAULTS), source)
    ss["ts_runs"] = [dict(name="Default inputs", time=dt.datetime.now(), inp=T.DEFAULTS,
                          source=source, results=res)]


def view_scenarios(name: str, inp: T.Inputs, source: str, go: bool) -> None:
    _ensure_default(source)
    if go:
        with st.spinner("Running the rule for your battery and every size…"):
            res = _compute(_items(inp), source)
        ss["ts_runs"].append(dict(name=name or "Scenario", time=dt.datetime.now(), inp=inp,
                                  source=source, results=res))
        ss["ts_show"] = len(ss["ts_runs"]) - 1
    run = _history()
    if run is not None:
        with st.container(border=True):
            _report(run)


def view_today(inp: T.Inputs, source: str) -> None:
    st.html('<div class="ts-label">ZHARKENT · TODAY, MEASURED</div>'
            '<div class="ts-title">What the plant costs today</div>'
            '<div class="ts-run">The measured baseline for each entity, before any battery: '
            'fuel, service and grid import, worked out from the meter data for October 2025 – '
            'September 2026. Nothing here is simulated.</div>'
            f'<div class="ts-ph">Placeholder inputs in use ({len(T.PLACEHOLDERS)}): '
            f'{", ".join(T.PLACEHOLDERS)}. Every money figure depends on them; do not quote any '
            'to the client until they are replaced.</div>')
    for g in ("K", "M"):
        x = _steps(g, source, _items(inp))
        units = T.GROUPS[g]["units"]
        r = T.Run(group=g, x=x, today=T.base(x, units, inp), yours=pd.Series(dtype=float),
                  sizes=pd.DataFrame(), inp=inp)
        b = T.today_breakdown(r)
        with st.container(border=True):
            c1, c2 = st.columns([1, 2])
            c1.markdown(f'<div class="ts-title" style="font-size:1.15rem">{T.GROUPS[g]["name"]}'
                        '</div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="ts-sub" style="text-align:right">annual figure from '
                        f'{len(b["months"])} months · left out (too few complete hours): '
                        f'{", ".join(pd.Period(m).strftime("%b %Y") for m in b["left_out"]) or "none"}</div>', unsafe_allow_html=True)
            _h("Operating cost per year", help="Fuel + service + grid import, each month scaled "
               "to its full length, the months kept averaged and × 12.")
            _stats([(f"{_m(b['total'])} KZT", "Total", f"≈ {b['total'] / inp.kzt_eur / 1e3:,.0f} k EUR", INK),
                    (f"{_m(b['fuel'])} KZT", "Fuel", f"{_n(b['fuel_kwh'] / 1e3)} MWh gas", SERIES["Fuel"]),
                    (f"{_m(b['service'])} KZT", "Service (engine hours + starts)",
                     f"≈ {b['service'] / inp.kzt_eur / 1e3:,.0f} k EUR", SERIES["Service"]),
                    (f"{_m(b['grid'])} KZT", "Grid import", f"{_n(b['imp'] / 1e3)} MWh", SERIES["Grid import"]),
                    (f"{_n(b['load'] / 1e3)} MWh", "Load served",
                     f"generation {_n(b['gen'] / 1e3)} + import {_n(b['imp'] / 1e3)} – export "
                     f"{_n(b['exp'] / 1e3)}", INK)])
            _h("Engines per year")
            _stats([(f"{_n(e['kwh'] / 1e3)} MWh", T.LONG[u],
                     f"{_n(e['run_h'])} h · {_n(e['starts'])} starts · loading {e['loading']:.0%}",
                     SERIES[T.NAME[u]]) for u, e in b["engines"].items()])
            _h("What full-output running could save at most",
               help="Excess engine hours = hours run – energy ÷ rated, at the service rate; "
                    "part-load fuel penalty = gas burnt – gas at full-load efficiency; fuel "
                    "burned for export = export × fuel cost per kWh made.")
            _stats([(f"{_m(b['excess_kzt'])} KZT", "Excess engine hours",
                     f"{_n(b['excess_h'])} h at the service rate", SERIES["MWM"]),
                    (f"{_m(b['penalty_kzt'])} KZT", "Part-load fuel penalty",
                     f"{_n(b['penalty_kwh'] / 1e3)} MWh gas", SERIES["MWM"]),
                    (f"{_m(b['export_kzt'])} KZT", "Fuel burned for export",
                     f"{_n(b['exp'] / 1e3)} MWh exported, not compensated", SERIES["Battery discharging"])])
            mt = T.months_table(x, units, inp)
            _h("Cost by month", help="Each month's fuel, service and grid, scaled to the whole "
               "month; the share above each bar is its complete hours. A month under the "
               "coverage is left out of the year.")
            rows = []
            for _, m in mt.iterrows():
                for k, lab in (("fuel_kzt", "Fuel"), ("service_kzt", "Service"), ("grid_kzt", "Grid import")):
                    rows.append(dict(month=str(m.month), series=lab, v=m[k] / 1e6, kept=m.kept,
                                     share=f"{m.share:.0%}" if m.kept else "left out"))
            if rows:
                df = pd.DataFrame(rows)
                names = ["Fuel", "Service", "Grid import"]
                bars = alt.Chart(df).mark_bar().encode(
                    x=alt.X("month:N", title=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("sum(v):Q", title="M KZT"),
                    color=alt.Color("series:N", scale=_scale(names), title=None, legend=alt.Legend(orient="top", labelLimit=0)),
                    opacity=alt.condition("datum.kept", alt.value(1), alt.value(0.3)),
                    tooltip=["month:N", "series:N", alt.Tooltip("v:Q", format=",.1f"), "share:N"])
                lab = alt.Chart(df.drop_duplicates("month")).mark_text(dy=-6, fontSize=10).encode(
                    x="month:N", y=alt.value(8), text="share:N",
                    color=alt.condition("datum.kept", alt.value(MUTED), alt.value(RED)))
                st.altair_chart((bars + lab).properties(height=280), width="stretch")


def _stats(items) -> None:
    st.html(f'<div class="ts-stats" style="--n:{len(items)}">' + "".join(
        f'<div class="ts-stat" style="border-color:{c}"><div class="ts-stat-v">{v}</div>'
        f'<div class="ts-stat-k">{k}</div><div class="ts-stat-s">{s}</div></div>'
        for v, k, s, c in items) + "</div>")


def view_data(inp: T.Inputs, source: str) -> None:
    st.html('<div class="ts-label">ZHARKENT · MEASURED DATA</div>'
            '<div class="ts-title">How the Zharkent plant runs today</div>'
            '<div class="ts-run">Measured power of each engine and the grid exchange of each '
            'entity, hour by hour, before any battery. Pick a month below. The bars show the '
            'whole year by month.</div>')
    xs = {g: _steps(g, source, _items(inp), study_only=False) for g in ("K", "M")}
    months = sorted({str(p) for x in xs.values() for p in x["time"].dt.to_period("M").unique()})
    if not months:
        return
    cov = {}
    for g, x in xs.items():
        mt = T.months_table(x, T.GROUPS[g]["units"], inp)
        cov[g] = mt.set_index(mt["month"].astype(str))
    pick = st.segmented_control(
        "Month", months, default=months[-2] if len(months) > 1 else months[0],
        format_func=lambda m: f"{pd.Period(m).strftime('%b %y')} · K {cov['K'].loc[m].share:.0%}"
        if m in cov["K"].index else f"{pd.Period(m).strftime('%b %y')}", key="ts_data_month",
        label_visibility="collapsed") or months[-1]
    for g in ("K", "M"):
        x, units = xs[g], T.GROUPS[g]["units"]
        mt = cov[g]
        with st.container(border=True):
            st.markdown(f'<div class="ts-title" style="font-size:1.15rem">{T.GROUPS[g]["name"]}</div>'
                        f'<div class="ts-sub">{T.GROUPS[g]["about"]}</div>', unsafe_allow_html=True)
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
                color=alt.Color("series:N", scale=_scale(names), title=None, legend=alt.Legend(orient="top", labelLimit=0)),
                tooltip=["month:N", "series:N", alt.Tooltip("v:Q", format=",.0f")])
            pct = pd.DataFrame([dict(month=m, s=f"{row.share:.0%}") for m, row in mt.iterrows()])
            lab = alt.Chart(pct).mark_text(dy=-4, fontSize=10, color=MUTED).encode(
                x="month:N", y=alt.value(8), text="s:N")
            st.altair_chart((bars + lab).properties(height=260), width="stretch")
            sel = x[x["time"].dt.to_period("M").astype(str) == pick]
            _h(f"{pd.Period(pick).strftime('%b %Y')}, hour by hour" if source == SRC_OURS else
               f"{pd.Period(pick).strftime('%b %Y')}, step by step")
            if not sel.empty:
                long = []
                for u in units:
                    long += [dict(time=a, series=T.NAME[u], kw=b) for a, b in zip(sel.time, sel[f"{u}_measured"])]
                long += [dict(time=a, series="Grid import", kw=b) for a, b in zip(sel.time, sel.grid_measured)]
                long += [dict(time=a, series="Load", kw=b) for a, b in zip(sel.time, sel.load)]
                d2 = pd.DataFrame(long)
                n2 = [T.NAME[u] for u in units] + ["Grid import", "Load"]
                st.altair_chart(alt.Chart(d2).mark_line(strokeWidth=1.2).encode(
                    x=alt.X("time:T", title=None), y=alt.Y("kw:Q", title="kW"),
                    color=alt.Color("series:N", scale=_scale(n2), title=None, legend=alt.Legend(orient="top", labelLimit=0)),
                    tooltip=["series:N", "time:T", alt.Tooltip("kw:Q", format=",.0f")]).properties(height=260),
                    width="stretch")
            else:
                st.caption("No complete hours this month.")
            with st.expander("Monthly table"):
                show = mt[[f"{u}_mwh" for u in units] + ["imp_mwh", "exp_mwh", "complete_h", "hours"]].copy()
                show.columns = [f"{T.LONG[u]} MWh" for u in units] + ["Import MWh", "Export MWh",
                                                                      "Hours complete", "Hours in month"]
                st.dataframe(show.round(0), width="stretch")
            with st.expander("Data check: this project's hourly table against his Data page "
                             "(not in his app)", expanded=(g == "K")):
                chk = T.data_check(g)
                if not chk.empty:
                    st.dataframe(chk, hide_index=True, width="stretch")
                    st.caption(
                        "His figures are read off his Data page (screens/data). Ours are this "
                        "project's hourly table before any of his step rules: every reading, "
                        "including the ones rebuilt from the hour's balance. The grid agrees; "
                        "the engines differ where the two sources hold different hours "
                        "(Krakhmal's MWM before November 2025 is not in this table) and where "
                        "this project rebuilt a missing Jenbacher reading from the balance.")
    st.html('<div class="ts-foot"><b>Sources.</b> ' + (
        "His 5-minute steps, as his run file publishes them." if source == SRC_HIS else
        "This project's hourly table (real_data/zharkent/data/zharkent_all_hourly.csv): the "
        "Tedom dashboard's 5-minute readings averaged to the hour, the Jenbacher loggers CC42 and "
        "CR06, about one averaged sample per hour. Readings this project rebuilt from the hour's "
        "balance are left out here, as his are left empty. Meshki's CR06 clock is shifted +1 h. "
        "Load = engines + grid, only for hours where every piece is known.") + "</div>")


def render() -> None:
    st.html(CSS)
    view, name, inp, source, go = sidebar()
    if view == "Battery scenarios":
        view_scenarios(name, inp, source, go)
    elif view == "Today":
        view_today(inp, source)
    else:
        view_data(inp, source)
