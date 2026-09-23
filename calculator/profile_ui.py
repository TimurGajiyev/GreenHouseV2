"""The profiling design layer: palette, CSS overrides, tables, dispatch chart.

Everything here is presentation. It reads a solved scenario and draws it; it
never computes an energy or a cost of its own, so the REopt core in
``reopt_core/model.py`` is untouched by anything in this file.

The visual specification is taken verbatim from the reference profiling
artifact (``bess_profile_v2.jsx``) so the two read as one product:

  palette   paper #EEF1F4 · panel #FFFFFF · ink #17242F · muted #5C6B79
            rule #CBD5DC · charge #1F7A8C · discharge #C2571A
            ceiling #8A97A3 · save #3F8F5C · units #46617F #7C6E9B #A8845C
  type      mono for every figure, sans only for headings
  header    mono 10.5px, uppercase, letter-spacing .06em, padding 7px 9px,
            right-aligned except the first column, 1px rule underneath
  body      mono 12px, padding 5px 9px, tabular figures, first column muted
  rows      every second row washed with rgba(23,36,47,0.022)
  total     1px solid ink above, weight 600

Nothing in here is written for a fixed number of generators or batteries: the
column sets, the chart series and the colour assignment are all built by
looping over whatever units the solved result carries.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

# ------------------------------------------------------------------ palette
PAPER = "#EEF1F4"
PANEL = "#FFFFFF"
INK = "#17242F"
MUTED = "#5C6B79"
RULE = "#CBD5DC"
CHARGE = "#1F7A8C"
DISCHARGE = "#C2571A"
CEILING = "#8A97A3"
SAVE = "#3F8F5C"

# The reference ships three unit colours. Past three units the palette repeats,
# so three more harmonised hues are appended before it wraps -- a six-unit
# fleet still gets six distinguishable bars.
GEN = ["#46617F", "#7C6E9B", "#A8845C", "#5F8A7A", "#8C5F6E", "#6E7C93"]
PV_COLOR = "#C08A2E"
GRID_COLOR = "#9BA8B4"

MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS = "Inter, 'Helvetica Neue', Arial, sans-serif"


def unit_color(i: int) -> str:
    return GEN[i % len(GEN)]


# ---------------------------------------------------------------- stylesheet
_CSS = f"""
<style>
/* =============================================================== profiling
   Scoped to .ghp-* so the REopt-orange styling of steps 1-5 is untouched. */

.ghp-panel-head {{
    background: {PANEL};
    border: 1px solid {RULE};
    border-bottom: none;
    padding: 16px 20px 12px;
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 12px;
}}
.ghp-title {{
    font-family: {SANS};
    font-size: 19px;
    font-weight: 650;
    letter-spacing: -0.015em;
    color: {INK};
    margin: 0;
}}
.ghp-sub {{
    font-family: {MONO};
    font-size: 11.5px;
    color: {MUTED};
    letter-spacing: 0.02em;
}}

/* ---- the chart sits between the header and the stat strip; the two
   adjacent-sibling rules close the panel around it. Each block is also
   styled to stand on its own if the sibling match ever fails. ---- */
.stElementContainer:has(.ghp-panel-head) + .stElementContainer,
[data-testid="element-container"]:has(.ghp-panel-head) + [data-testid="element-container"] {{
    background: {PANEL};
    border-left: 1px solid {RULE};
    border-right: 1px solid {RULE};
    padding: 14px 10px 2px 2px;
}}

.ghp-strip {{
    display: flex;
    flex-wrap: wrap;
    background: {PANEL};
    border: 1px solid {RULE};
}}
.ghp-cell {{
    flex: 1 1 130px;
    padding: 12px 16px;
    border-left: 1px solid {RULE};
}}
.ghp-cell:first-child {{ border-left: none; }}
.ghp-cell-k {{
    font-family: {MONO};
    font-size: 10.5px;
    color: {MUTED};
    text-transform: uppercase;
    letter-spacing: 0.07em;
}}
.ghp-cell-v {{
    font-family: {MONO};
    font-size: 15px;
    color: {INK};
    margin-top: 4px;
    font-variant-numeric: tabular-nums;
}}

.ghp-note {{
    background: {PANEL};
    border: 1px solid {RULE};
    border-top: none;
    padding: 10px 16px;
    font-family: {MONO};
    font-size: 11.5px;
    color: {MUTED};
    display: flex;
    flex-wrap: wrap;
    gap: 18px;
}}
.ghp-note b {{ font-weight: 500; }}

.ghp-h3 {{
    margin: 26px 0 10px;
    font-family: {SANS};
    font-size: 14.5px;
    font-weight: 620;
    letter-spacing: -0.01em;
    color: {INK};
}}

/* ---------------------------------------------------------------- tables */
.ghp-wrap {{
    background: {PANEL};
    border: 1px solid {RULE};
    overflow-x: auto;
}}
.ghp-wrap.ghp-tall {{ max-height: 560px; overflow-y: auto; }}

.ghp-table {{
    border-collapse: collapse;
    width: 100%;
    min-width: 560px;
}}
.ghp-table th {{
    font-family: {MONO};
    font-size: 10.5px;
    color: {MUTED};
    font-weight: 400;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 7px 9px;
    text-align: right;
    white-space: nowrap;
    border-bottom: 1px solid {RULE};
    background: {PANEL};
    position: sticky;
    top: 0;
    z-index: 2;
}}
.ghp-table td {{
    font-family: {MONO};
    font-size: 12px;
    color: {INK};
    padding: 5px 9px;
    text-align: right;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}}
.ghp-table th:first-child,
.ghp-table td:first-child {{ text-align: left; }}
/* the label column absorbs the slack so the figures stay packed to the
   right, the way they read when the table is full of unit columns */
.ghp-table th:first-child {{ width: 100%; }}
.ghp-table td:first-child {{ color: {MUTED}; }}

.ghp-table tbody tr:nth-child(even) {{ background: rgba(23, 36, 47, 0.022); }}

.ghp-table tr.ghp-foot td {{
    border-top: 1px solid {INK};
    font-weight: 600;
    color: {INK};
}}
.ghp-table tr.ghp-sect td {{
    background: transparent;
    color: {INK};
    font-weight: 600;
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 15px 9px 5px;
    border-bottom: 1px solid {RULE};
}}
.ghp-table tr.ghp-sect td:first-child {{ color: {INK}; }}

.ghp-pos {{ color: {SAVE}; }}
.ghp-neg {{ color: {DISCHARGE}; }}
.ghp-dim {{ color: {MUTED}; }}
.ghp-key {{ color: {INK}; font-weight: 600; }}

/* ---- legend chips under the chart ---- */
.ghp-legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    padding: 2px 2px 0;
    font-family: {MONO};
    font-size: 11px;
    color: {MUTED};
}}
.ghp-swatch {{
    display: inline-block;
    width: 9px;
    height: 9px;
    margin-right: 6px;
    vertical-align: baseline;
}}
.ghp-sw-0 {{ background: {GEN[0]}; }}
.ghp-sw-1 {{ background: {GEN[1]}; }}
.ghp-sw-2 {{ background: {GEN[2]}; }}
.ghp-sw-3 {{ background: {GEN[3]}; }}
.ghp-sw-4 {{ background: {GEN[4]}; }}
.ghp-sw-5 {{ background: {GEN[5]}; }}
.ghp-sw-pv {{ background: {PV_COLOR}; }}
.ghp-sw-grid {{ background: {GRID_COLOR}; }}
.ghp-sw-charge {{ background: {CHARGE}; }}
.ghp-sw-discharge {{ background: {DISCHARGE}; }}
.ghp-sw-load {{ background: {INK}; }}

/* ---- Vega's tooltip is built outside the chart, in one element hung off
   the page body, so CSS is the only thing that can reach it. Streamlit ships
   vega-tooltip's own stylesheet, and its own theme on top of that, from the
   document head; both address the cells as `#id table tr td.value`, so this
   sheet has to say exactly that too and win on document order. Anything
   shorter loses -- their rule sets the value cell to display block, aligned
   left and clamped to five lines, which is why the figures used to sit under
   their labels instead of forming a column.

   Layout follows the reference's Tip component: white panel, 1px rule, mono
   12px, muted label on the left, figure right-aligned on tabular numerals,
   line-height 1.7, 230px floor, and the hour as a heading with a rule under
   it -- vega-tooltip promotes the field named `title` to a heading.

   Never write an HTML tag in here, not even inside a comment: st.html
   sanitises the string it is given and one stray tag costs the whole sheet. */
#vg-tooltip-element {{
    background: {PANEL};
    border: 1px solid {RULE};
    border-radius: 0;
    box-shadow: 0 2px 10px rgba(23, 36, 47, 0.10);
    padding: 10px 12px;
    font-family: {MONO};
    font-size: 12px;
    color: {INK};
    max-width: none;
}}
#vg-tooltip-element h2 {{
    font-family: {MONO};
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    color: {INK};
    margin: 0 0 7px;
    padding-bottom: 6px;
    border-bottom: 1px solid {RULE};
}}
#vg-tooltip-element table {{
    border-spacing: 0;
    min-width: 230px;
    width: 100%;
}}
#vg-tooltip-element table tr td {{
    padding: 0;
    line-height: 1.7;
    overflow: visible;
    text-overflow: clip;
}}
#vg-tooltip-element table tr td.key {{
    color: {MUTED};
    font-weight: 400;
    text-align: left;
    max-width: none;
    padding-right: 18px;
    /* the reference indents its per-unit lines with two spaces */
    white-space: pre;
}}
#vg-tooltip-element table tr td.value {{
    display: table-cell;
    color: {INK};
    text-align: right;
    max-width: none;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}}

/* ---- segmented switches in the profiling block only ----
   The marker span is emitted immediately before the widget, so the widget is
   its next element sibling. Steps 1-5 keep Streamlit's own styling. */
.ghp-switch-scope {{ display: none; }}
.stElementContainer:has(.ghp-switch-scope) + .stElementContainer [data-testid="stButtonGroup"] {{
    gap: 0;
    border: 1px solid {RULE};
    width: fit-content;
    border-radius: 0;
    background: {PANEL};
}}
.stElementContainer:has(.ghp-switch-scope) + .stElementContainer [data-testid="stButtonGroup"] button {{
    font-family: {MONO};
    font-size: 12px;
    letter-spacing: 0.04em;
    padding: 9px 18px;
    border: none;
    border-left: 1px solid {RULE};
    border-radius: 0;
    background: {PANEL};
    color: {MUTED};
}}
.stElementContainer:has(.ghp-switch-scope) + .stElementContainer [data-testid="stButtonGroup"] button:first-child {{
    border-left: none;
}}
.stElementContainer:has(.ghp-switch-scope) + .stElementContainer [data-testid="stButtonGroup"] button[aria-checked="true"],
.stElementContainer:has(.ghp-switch-scope) + .stElementContainer [data-testid="stButtonGroup"] button[aria-pressed="true"] {{
    background: {INK};
    color: {PAPER};
}}
</style>
"""


def inject() -> None:
    """Add the profiling stylesheet once per run."""
    st.html(_CSS)


# ------------------------------------------------------------------ pieces
def panel_head(title: str, subtitle: str = "") -> None:
    sub = f'<span class="ghp-sub">{subtitle}</span>' if subtitle else ""
    st.html(f'<div class="ghp-panel-head"><h2 class="ghp-title">{title}</h2>{sub}</div>')


def stat_strip(cells: list[tuple[str, str]], highlight: set[str] | None = None) -> None:
    """The six-figure strip under the chart. ``highlight`` emphasises a value."""
    hl = highlight or set()
    out = []
    for k, v in cells:
        cls = "ghp-cell-v ghp-key" if k in hl else "ghp-cell-v"
        out.append(f'<div class="ghp-cell"><div class="ghp-cell-k">{k}</div>'
                   f'<div class="{cls}">{v}</div></div>')
    st.html('<div class="ghp-strip">' + "".join(out) + "</div>")


def note(parts: list[str]) -> None:
    st.html('<div class="ghp-note">' + "".join(f"<span>{p}</span>" for p in parts) + "</div>")


def sub(text: str) -> None:
    st.html(f'<div class="ghp-h3">{text}</div>')


# swatch class per colour, so nothing depends on an inline style surviving
SWATCH = {PV_COLOR: "ghp-sw-pv", GRID_COLOR: "ghp-sw-grid", CHARGE: "ghp-sw-charge",
          DISCHARGE: "ghp-sw-discharge", INK: "ghp-sw-load"}
SWATCH.update({c: f"ghp-sw-{i}" for i, c in enumerate(GEN)})


def legend(items: list[tuple[str, str]]) -> None:
    chips = "".join(
        f'<span><span class="ghp-swatch {SWATCH.get(c, "ghp-sw-grid")}"></span>{lab}</span>'
        for lab, c in items
    )
    st.html(f'<div class="ghp-legend">{chips}</div>')


def switch(label: str, options: list[str], *, key: str, default: str | None = None) -> str:
    """A segmented control wearing the reference's switch styling.

    `required=True` matters: without it a segmented control lets the reader
    click the option that is already chosen and turn it OFF. The call then
    returns None, this function quietly falls back to the default, and the
    buttons are left showing nothing selected while the page is drawn for
    something -- a switch that lies about its own position.
    """
    st.html('<span class="ghp-switch-scope"></span>')
    picked = st.segmented_control(
        label, options, default=default or options[0], key=key,
        required=True, label_visibility="collapsed",
    )
    return picked or (default or options[0])


# ------------------------------------------------------------------- table
Cell = str | tuple[str, str]        # plain text, or (text, css class)


def _td(c: Cell) -> str:
    if isinstance(c, tuple):
        return f'<td class="{c[1]}">{c[0]}</td>'
    return f"<td>{c}</td>"


def table(head: list[str], rows: list[list[Cell]], foot: list[Cell] | None = None,
          *, tall: bool = False, sections: dict[int, str] | None = None) -> None:
    """Render one table in the reference's exact visual hierarchy.

    ``sections`` maps a row index to a section caption inserted above it, which
    is how the summary table groups metrics without leaving the single grid.
    """
    sec = sections or {}
    ncol = len(head)
    body = []
    for i, r in enumerate(rows):
        if i in sec:
            body.append(f'<tr class="ghp-sect"><td colspan="{ncol}">{sec[i]}</td></tr>')
        body.append("<tr>" + "".join(_td(c) for c in r) + "</tr>")
    if foot:
        body.append('<tr class="ghp-foot">' + "".join(_td(c) for c in foot) + "</tr>")
    st.html(
        f'<div class="ghp-wrap{" ghp-tall" if tall else ""}">'
        f'<table class="ghp-table"><thead><tr>'
        + "".join(f"<th>{h}</th>" for h in head)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


# ------------------------------------------------------------------- chart
def _axis(values=None, title=None, fmt=None, grid=True, domain=True):
    # The reference's axes: no tick marks on either, a rule under the hours and
    # none beside the kW, and a grid of horizontal dashes 2 on 4 off.
    # Altair rejects an explicit None for these, so only pass what is set
    kw = dict(labelFont=MONO, labelFontSize=11, labelColor=MUTED,
              titleFont=MONO, titleFontSize=11.5, titleColor=MUTED,
              titleFontWeight=400, domain=domain, domainColor=RULE,
              ticks=False, gridColor=RULE, gridDash=[2, 4], grid=grid)
    if values is not None:
        kw["values"] = values
    if title is not None:
        kw["title"] = title
    if fmt is not None:
        kw["format"] = fmt
    return alt.Axis(**kw)


def _tooltip_palette(colors: list[str]) -> None:
    """Colour the hover panel's figures, one rule per row.

    Vega's tooltip is plain escaped text in an element of its own, so a mark
    cannot colour its own row and no class can be attached to one. What *is*
    fixed is the order: the rows come out in the order of the tooltip channel,
    identically for every hour, so position addresses them. That is why the
    panel carries a dash rather than dropping a row that does not apply -- a
    reflowing table would break both the colours and the reading.

    One dispatch chart is drawn per page, so this global sheet is unambiguous.
    """
    rules = "".join(
        f"#vg-tooltip-element table tr:nth-child({i}) td.value{{color:{c};}}"
        for i, c in enumerate(colors, start=1))
    st.html(f"<style>{rules}</style>")


def dispatch_chart(hours: list[int], labels: list[str], stack: list[tuple[str, str, list[float]]],
                   load: list[float], charge: list[float], discharge: list[float],
                   *, ceiling_kw: float | None = None, week: bool = False,
                   height: int | None = None,
                   detail: list[list[tuple[str, str, str]]] | None = None,
                   veil: list[float] | None = None):
    """Stacked supply, signed battery bar, load line -- the reference chart.

    ``stack`` is a list of ``(name, colour, series)`` built by the caller from
    however many units the result carries, so this function never names a unit.

    ``detail`` is the reference's hover panel: for each hour, the rows of its
    Tip component as ``(label, text, colour)``, already formatted. Every hour
    must give the same labels in the same order.

    ``veil`` is the reference's money band, one height per hour in kW: the
    hour's saving divided by the price spread, hung from the load line. Its
    area times the spread is the saving -- green where the hour saves, peach
    where it costs more.
    """
    n = len(hours)
    bar = 3 if week else 13
    if height is None:
        height = 420 if week else 380

    rows = []
    for name, color, vals in stack:
        for i in range(n):
            if abs(vals[i]) > 1e-9:
                rows.append({"h": hours[i], "src": name, "kw": vals[i], "t": labels[i]})
    stack_df = pd.DataFrame(rows or [{"h": hours[0], "src": "", "kw": 0.0, "t": labels[0]}])
    order = {name: i for i, (name, _, _) in enumerate(stack)}
    stack_df["o"] = stack_df["src"].map(order).fillna(0)

    bess = [charge[i] - discharge[i] for i in range(n)]
    bess_df = pd.DataFrame({"h": hours, "kw": bess, "t": labels,
                            "sgn": ["charge" if v >= 0 else "discharge" for v in bess]})
    bess_df = bess_df[bess_df["kw"].abs() > 1e-9]
    load_df = pd.DataFrame({"h": hours, "kw": load, "t": labels})

    top = max([sum(v[i] for _, _, v in stack) for i in range(n)] + list(load) + [1.0]
              + ([load[i] - veil[i] for i in range(n)] if veil else []))
    if ceiling_kw:
        top = max(top, ceiling_kw)
    top = -(-top * 1.06 // 500) * 500
    bot = max(discharge) if discharge else 0.0
    bot = -max(500.0, -(-bot * 1.25 // 500) * 500) if bot > 0 else 0.0
    if veil:
        low = min(load[i] - veil[i] for i in range(n))
        if low < bot:
            bot = (low // 500) * 500
    ticks = [v for v in range(int(bot), int(top) + 1, 500)]
    if len(ticks) > 16:
        step = 500 * (len(ticks) // 14 + 1)
        ticks = [v for v in range(int(bot), int(top) + 1, step)]

    # the reference labels every second hour counting from the first
    xticks = ([1] + list(range(24, n + 1, 24)) if week
              else [h for h in hours if h % 2 == 1])
    xtitle = "hour of week" if week else "hour of day"
    # horizontal rules only, as in the reference grid
    xscale = alt.Scale(domain=[hours[0] - 0.5, hours[-1] + 0.5], nice=False)
    yscale = alt.Scale(domain=[bot, top], nice=False)
    xenc = alt.X("h:Q", axis=_axis(values=xticks, title=xtitle, grid=False), scale=xscale)
    yenc = alt.Y("kw:Q", axis=_axis(values=ticks, title="kW", fmt=",.0f", domain=False), scale=yscale)

    names = [nm for nm, _, _ in stack]
    colors = [c for _, c, _ in stack]

    # ---- the hover panel -------------------------------------------------
    # Recharts gives a whole category one tooltip and lays a translucent cursor
    # over the hovered column. The same thing in Vega-Lite is a transparent
    # rect per hour, on top of every other layer so it takes the pointer
    # wherever in the column it is -- over a bar, over the line, or over empty
    # space -- carrying that hour's panel as one tooltip object.
    hover = alt.selection_point(name="ghhover", on="pointerover", clear="pointerout",
                                fields=["h"], empty=False)
    tip_df = pd.DataFrame({"h": hours, "title": labels,
                           "x0": [h - 0.5 for h in hours],
                           "x1": [h + 0.5 for h in hours],
                           "y0": bot, "y1": top})
    # vega-tooltip renders the field called `title` as the panel's heading
    tips = [alt.Tooltip("title:N", title="title")]
    palette: list[str] = []
    if detail:
        used: set[str] = set()
        for k, (lab, _, col) in enumerate(detail[0]):
            key = lab
            while key in used:          # the labels become object keys
                key += "\u2009"
            used.add(key)
            tip_df[f"f{k}"] = [d[k][1] for d in detail]
            tips.append(alt.Tooltip(f"f{k}:N", title=key))
            palette.append(col)
    else:
        tip_df["f0"] = [f"{v:,.0f} kW" for v in load]
        tips.append(alt.Tooltip("f0:N", title="site load"))
        palette.append(INK)
    # the same axis definitions as every other layer, so Vega-Lite merges them
    # into the one pair of axes; an `axis=None` on either drops both
    _band = alt.Chart(tip_df).mark_rect().encode(
        x=alt.X("x0:Q", scale=xscale,
                axis=_axis(values=xticks, title=xtitle, grid=False)), x2="x1:Q",
        y=alt.Y("y0:Q", scale=yscale,
                axis=_axis(values=ticks, title="kW", fmt=",.0f", domain=False)), y2="y1:Q")
    # Recharts paints its cursor behind the marks, so the wash and the surface
    # that catches the pointer are two layers: the wash at the very bottom, the
    # catcher on top of everything, transparent but still hit-tested.
    wash = _band.mark_rect(fill=INK).encode(
        fillOpacity=alt.when(hover).then(alt.value(0.05)).otherwise(alt.value(0.0)))
    cursor = _band.mark_rect(fill=INK, fillOpacity=0.0).encode(
        tooltip=tips).add_params(hover)

    # Recharts draws the BESS bar beside the stack, not on top of it; in
    # Vega-Lite that is a pixel offset on each mark
    off = bar / 2.0 + 0.5
    supply = alt.Chart(stack_df).mark_bar(size=bar, fillOpacity=0.85,
                                          xOffset=-off).encode(
        x=xenc, y=alt.Y("kw:Q", stack="zero",
                        axis=_axis(values=ticks, title="kW", fmt=",.0f", domain=False), scale=yscale),
        color=alt.Color("src:N", scale=alt.Scale(domain=names, range=colors),
                        legend=None),
        order=alt.Order("o:Q", sort="ascending"),
    )
    battery = alt.Chart(bess_df).mark_bar(size=bar, xOffset=off).encode(
        x=xenc, y=yenc,
        color=alt.Color("sgn:N", scale=alt.Scale(domain=["charge", "discharge"],
                                                 range=[CHARGE, DISCHARGE]), legend=None),
    )
    # a day gets the reference's hollow markers, a week a fine ink dot
    point = (alt.OverlayMarkDef(color=INK, size=6, filled=True) if week
             else alt.OverlayMarkDef(color=PANEL, stroke=INK, strokeWidth=1.6,
                                     size=26, filled=False))
    line = alt.Chart(load_df).mark_line(
        color=INK, strokeWidth=1.1 if week else 1.6, point=point,
    ).encode(x=xenc, y=yenc)
    # the reference's activeDot: the hovered hour's marker fills in and swells
    active = alt.Chart(load_df).mark_point(
        size=80, filled=True, fill=INK, stroke=PANEL, strokeWidth=2,
    ).encode(x=xenc, y=yenc,
             opacity=alt.when(hover).then(alt.value(1.0)).otherwise(alt.value(0.0)))

    layers = [wash]
    if week:
        seps = pd.DataFrame({"x": list(range(24, n, 24))})
        layers.append(alt.Chart(seps).mark_rule(color=RULE, strokeWidth=1).encode(x="x:Q"))
    if veil:
        # beneath the bars, as in the reference, and straight-edged: the band's
        # area is the money, so a smoothing curve would misstate it
        vdf = pd.DataFrame({
            "h": hours, "load": load,
            "pos_lo": [load[i] - max(veil[i], 0.0) for i in range(n)],
            "neg_hi": [load[i] - min(veil[i], 0.0) for i in range(n)],
        })
        # two bands so each keeps one colour; an hour of the other sign
        # collapses onto the load line
        for lo, hi, col in (("pos_lo", "load", SAVE), ("load", "neg_hi", DISCHARGE)):
            layers.append(alt.Chart(vdf).mark_area(
                color=col, opacity=0.2, interpolate="linear").encode(
                x=xenc, y=alt.Y(f"{lo}:Q", scale=yscale,
                                axis=_axis(values=ticks, title="kW", fmt=",.0f", domain=False)),
                y2=f"{hi}:Q"))
    layers += [supply, battery,
               alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(color=INK, strokeWidth=1)
               .encode(y="y:Q")]
    if ceiling_kw:
        cap = pd.DataFrame({"y": [float(ceiling_kw)],
                            "lab": [f"fleet nameplate {ceiling_kw:,.0f} kW"],
                            "x": [float(hours[-1])]})
        layers.append(alt.Chart(cap).mark_rule(
            color=CEILING, strokeDash=[6, 4], strokeWidth=1.25).encode(y="y:Q"))
        # alt.value() on x would be a pixel offset; anchor the caption to the
        # last hour instead so it sits at the right edge of the plotting area
        layers.append(alt.Chart(cap).mark_text(
            align="right", baseline="bottom", dy=-4, color=CEILING,
            font=MONO, fontSize=11).encode(y="y:Q", x="x:Q", text="lab:N"))
    layers += [line, active, cursor]

    _tooltip_palette(palette)
    return (alt.layer(*layers)
            .properties(height=height, background=PANEL, padding={"left": 4, "right": 8,
                                                                  "top": 6, "bottom": 2})
            # without this the unit colours and the battery charge/discharge
            # colours are merged into one scale and the battery bar takes a
            # generator's colour
            .resolve_scale(color="independent")
            .configure_view(stroke=None)
            .configure_axis(labelFont=MONO, titleFont=MONO))


def starts_chart(days: list[int], labels: list[str],
                 stack: list[tuple[str, str, list[float]]], *,
                 height: int = 200, tick_every: int | None = None):
    """Starts per calendar day, stacked by unit -- one bar per day of the horizon.

    ``stack`` is a list of ``(name, colour, per-day counts)`` built by the
    caller from however many units the result carries, so this function never
    names a unit. Counts are whole numbers, so the y axis is stepped in
    integers rather than the kW scale the dispatch chart uses.

    A start is an off-to-on transition, and the core counts it cyclically, so a
    unit already running at hour 0 is not charged a start on day 0.
    """
    n = len(days)
    rows = []
    for name, color, vals in stack:
        for i in range(n):
            if vals[i]:
                rows.append({"d": days[i], "src": name, "n": vals[i], "t": labels[i]})
    names = [s[0] for s in stack]
    colors = [s[1] for s in stack]
    df = pd.DataFrame(rows or [{"d": days[0], "src": names[0], "n": 0, "t": labels[0]}])
    order = {name: i for i, name in enumerate(names)}
    df["o"] = df["src"].map(order).fillna(0)

    top = max([sum(v[i] for _, _, v in stack) for i in range(n)] + [1])
    step = 1 if top <= 6 else (2 if top <= 12 else max(1, round(top / 6)))
    ticks = list(range(0, int(top) + step, step))
    if tick_every is None:
        tick_every = 1 if n <= 14 else (7 if n <= 70 else 30)
    xvals = [days[i] for i in range(0, n, tick_every)]
    # a day's bar keeps a visible body up to a month, then thins to a density plot
    bar = 15 if n <= 14 else (9 if n <= 40 else (3 if n <= 130 else 1.4))

    # Two Vega traps, both found by rendering this and reading the SVG back.
    #
    # The format is ",d" and not "d". A bare "d" makes Vega drop ticks out of an
    # explicit ``values`` list: on domain [0, 2] with values [0, 1, 2] it draws
    # 0 and 2 and no line at 1 -- the value most of these bars sit on. ",d",
    # ".0f" and ",.0f" all keep the three; only "d" loses one. (The hour axis
    # gets away with "d" because its domain is wider.)
    #
    # And one y encoding is reused by every layer, as the dispatch chart does: a
    # layered chart resolves ONE shared y axis, so a bare ``y="n:Q"`` on the
    # zero rule would contribute Vega's default ticks, and ``axis=None`` there
    # removes the axis from the whole chart.
    yenc = alt.Y("n:Q", title="Starts", stack=True,
                 scale=alt.Scale(domain=[0, ticks[-1]], nice=False),
                 axis=_axis(values=ticks, fmt=",d", domain=False))
    bars = alt.Chart(df).mark_bar(size=bar).encode(
        x=alt.X("d:Q", title="Day of the horizon", scale=alt.Scale(
            domain=[days[0] - 0.6, days[-1] + 0.6], nice=False),
            axis=_axis(values=xvals, fmt=",d", grid=False)),
        y=yenc,
        color=alt.Color("src:N", scale=alt.Scale(domain=names, range=colors),
                        legend=None),
        order=alt.Order("o:Q", sort="ascending"),
        tooltip=[alt.Tooltip("t:N", title="Day"), alt.Tooltip("src:N", title="Unit"),
                 alt.Tooltip("n:Q", title="Starts", format="d")],
    )
    base = alt.Chart(pd.DataFrame({"n": [0.0]})).mark_rule(
        color=INK, strokeWidth=1).encode(y=yenc)
    return (alt.layer(bars, base)
            .properties(height=height, background=PANEL,
                        padding={"left": 4, "right": 8, "top": 6, "bottom": 2})
            .configure_view(stroke=None)
            .configure_axis(labelFont=MONO, titleFont=MONO))
