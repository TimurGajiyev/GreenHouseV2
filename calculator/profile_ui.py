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

import json

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
.ghp-pick {{ padding-top: 16px; }}
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
.ghp-sw-save {{ background: {SAVE}; }}
.ghp-sw-ceil {{ background: {CEILING}; }}

/* ---- a quiet caption under a chart: what it is drawn on ---- */
.ghp-cap {{
    font-family: {MONO};
    font-size: 11px;
    color: {MUTED};
    line-height: 1.55;
    padding: 4px 2px 0;
}}
.ghp-cap b {{ font-weight: 500; color: {INK}; }}

/* ---- the pair, face to face: scenario left, against right, the
   difference between them in the middle. Mirrored, so each side reads
   outwards from the verdict. ---- */
.ghp-vs {{
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    background: {PANEL};
    border: 1px solid {RULE};
    margin: 6px 0 14px;
}}
.ghp-vs-side {{
    padding: 16px 20px 15px;
    display: flex;
    flex-direction: column;
    gap: 9px;
    min-width: 0;
}}
.ghp-vs-r {{ align-items: flex-end; text-align: right; }}
.ghp-vs-top {{ display: flex; align-items: center; gap: 12px; }}
.ghp-vs-r .ghp-vs-top {{ flex-direction: row-reverse; }}
.ghp-badge {{
    flex: none;
    width: 34px;
    height: 34px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: {SANS};
    font-size: 16px;
    font-weight: 650;
    color: {PANEL};
}}
.ghp-badge-scenario {{ background: {INK}; }}
.ghp-badge-against {{ background: {CHARGE}; }}
.ghp-vs-role {{
    font-family: {MONO};
    font-size: 10.5px;
    color: {MUTED};
    text-transform: uppercase;
    letter-spacing: 0.07em;
}}
.ghp-vs-name {{
    font-family: {SANS};
    font-size: 15.5px;
    font-weight: 620;
    letter-spacing: -0.01em;
    color: {INK};
    line-height: 1.25;
}}
.ghp-chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.ghp-vs-r .ghp-chips {{ justify-content: flex-end; }}
.ghp-chip {{
    font-family: {MONO};
    font-size: 11px;
    color: {INK};
    border: 1px solid {RULE};
    border-radius: 999px;
    padding: 2px 9px;
    white-space: nowrap;
}}
.ghp-chip-dim {{ color: {MUTED}; }}
.ghp-vs-k {{
    font-family: {MONO};
    font-size: 10.5px;
    color: {MUTED};
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-top: 2px;
}}
.ghp-vs-fig {{
    font-family: {MONO};
    font-size: 19px;
    color: {INK};
    margin-top: -5px;
}}
.ghp-vs-mini {{
    font-family: {MONO};
    font-size: 11.5px;
    color: {MUTED};
    line-height: 1.6;
}}
.ghp-vs-mid {{
    border-left: 1px solid {RULE};
    border-right: 1px solid {RULE};
    background: rgba(23, 36, 47, 0.022);
    padding: 16px 26px;
    min-width: 220px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: 3px;
}}
.ghp-vs-delta {{
    font-family: {SANS};
    font-size: 30px;
    font-weight: 650;
    letter-spacing: -0.02em;
    line-height: 1.1;
}}
.ghp-vs-says {{
    font-family: {SANS};
    font-size: 13px;
    font-weight: 560;
    color: {INK};
    margin-top: 6px;
}}
@media (max-width: 820px) {{
    .ghp-vs {{ grid-template-columns: minmax(0, 1fr); }}
    .ghp-vs-mid {{ border: none; border-top: 1px solid {RULE}; border-bottom: 1px solid {RULE}; }}
    .ghp-vs-r {{ align-items: flex-start; text-align: left; }}
    .ghp-vs-r .ghp-vs-top {{ flex-direction: row; }}
    .ghp-vs-r .ghp-chips {{ justify-content: flex-start; }}
}}

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


def label(text: str) -> None:
    """A small caption beside a switch, in the stat strip's key style; padded
    so it sits level with the switch, which has the scope marker above it."""
    st.html(f'<div class="ghp-cell-k ghp-pick">{text}</div>')


def caption(text: str) -> None:
    """One quiet line under a chart: what it is drawn on."""
    st.html(f'<div class="ghp-cap">{text}</div>')


def matchup_html(left: dict, mid: dict, right: dict) -> str:
    """The pair face to face, as markup (``matchup`` draws it).

    ``left`` and ``right`` are the two sides: ``letter``, ``role`` (scenario
    or against -- the badge takes that role's colour, the same as the charts'),
    ``name``, ``chips`` (list of text, or (text, "dim")), ``key`` and ``fig``
    (the headline figure and its caption) and ``mini`` (one muted line).
    ``mid`` is the difference: ``head``, ``delta`` (text, css class),
    ``under`` and ``says``. Everything is text already formatted."""
    def side(s: dict, cls: str) -> str:
        chips = "".join(
            f'<span class="ghp-chip{" ghp-chip-dim" if isinstance(c, tuple) else ""}">'
            f'{c[0] if isinstance(c, tuple) else c}</span>' for c in s.get("chips", []))
        return (f'<div class="ghp-vs-side {cls}">'
                f'<div class="ghp-vs-top"><span class="ghp-badge ghp-badge-{s["role"]}">'
                f'{s["letter"]}</span><div><div class="ghp-vs-role">{s["role"]}</div>'
                f'<div class="ghp-vs-name">{s["name"]}</div></div></div>'
                f'<div class="ghp-chips">{chips}</div>'
                f'<div class="ghp-vs-k">{s["key"]}</div><div class="ghp-vs-fig">{s["fig"]}</div>'
                f'<div class="ghp-vs-mini">{s.get("mini", "")}</div></div>')
    text, cls = mid["delta"]
    centre = (f'<div class="ghp-vs-mid"><div class="ghp-vs-k">{mid["head"]}</div>'
              f'<div class="ghp-vs-delta {cls}">{text}</div>'
              f'<div class="ghp-vs-mini">{mid["under"]}</div>'
              f'<div class="ghp-vs-says">{mid["says"]}</div></div>')
    return f'<div class="ghp-vs">{side(left, "ghp-vs-l")}{centre}{side(right, "ghp-vs-r")}</div>'


def matchup(left: dict, mid: dict, right: dict) -> None:
    st.html(matchup_html(left, mid, right))


# swatch class per colour, so nothing depends on an inline style surviving
SWATCH = {PV_COLOR: "ghp-sw-pv", GRID_COLOR: "ghp-sw-grid", CHARGE: "ghp-sw-charge",
          DISCHARGE: "ghp-sw-discharge", INK: "ghp-sw-load", SAVE: "ghp-sw-save",
          CEILING: "ghp-sw-ceil"}
SWATCH.update({c: f"ghp-sw-{i}" for i, c in enumerate(GEN)})


def legend(items: list[tuple[str, str]]) -> None:
    chips = "".join(
        f'<span><span class="ghp-swatch {SWATCH.get(c, "ghp-sw-grid")}"></span>{lab}</span>'
        for lab, c in items
    )
    st.html(f'<div class="ghp-legend">{chips}</div>')


def switch(label: str, options: list[str], *, key: str, default: str | None = None,
           fmt=None) -> str:
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
        **({"format_func": fmt} if fmt is not None else {}),
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
def _axis(values=None, title=None, fmt=None, grid=True, domain=True, label_expr=None):
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
    if label_expr is not None:
        kw["labelExpr"] = label_expr
    return alt.Axis(**kw)


def _tooltip_palette(colors: list[str], scope: str | None = None) -> None:
    """Colour the hover panel's figures, one rule per row.

    Vega's tooltip is plain escaped text in an element of its own, so a mark
    cannot colour its own row and no class can be attached to one. What *is*
    fixed is the order: the rows come out in the order of the tooltip channel,
    identically for every hour, so position addresses them. That is why the
    panel carries a dash rather than dropping a row that does not apply -- a
    reflowing table would break both the colours and the reading.

    Every chart on the page shares the one tooltip element, so a second chart
    with other rows would recolour the first. ``scope`` names the keyed
    container (Streamlit's st-key- class) a chart sits in: its rules then hold
    only while the pointer is inside that container, and the extra selectors
    outrank the page's unscoped sheet whatever the order they arrive in.
    """
    pre = f":root:has(.st-key-{scope}:hover) " if scope else ""
    rules = "".join(
        f"{pre}#vg-tooltip-element table tr:nth-child({i}) td.value{{color:{c};}}"
        for i, c in enumerate(colors, start=1))
    st.html(f"<style>{rules}</style>")


def dispatch_chart(hours: list[int], labels: list[str], stack: list[tuple[str, str, list[float]]],
                   load: list[float], charge: list[float], discharge: list[float],
                   *, ceiling_kw: float | None = None, week: bool = False,
                   height: int | None = None,
                   detail: list[list[tuple[str, str, str]]] | None = None,
                   veil: list[float] | None = None,
                   xlabels: dict[int, str] | None = None, xtitle: str | None = None,
                   seps: list[float] | None = None, tip_scope: str | None = None):
    """Stacked supply, signed battery bar, load line -- the reference chart.

    ``stack`` is a list of ``(name, colour, series)`` built by the caller from
    however many units the result carries, so this function never names a unit.
    A value of None is a reading nobody took: no bar, and the load line breaks
    there rather than running straight across the hole.

    ``xlabels`` (position -> text) replaces the hour numbers with the caller's
    own ticks, ``xtitle`` the axis title and ``seps`` the day separators;
    ``tip_scope`` scopes the hover colours to a keyed container (see
    ``_tooltip_palette``) for a page that draws a second chart.

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
    # a month of hours or a year of days is more columns than a week's bar fits
    long = n > 168
    if long:
        bar = 1 if n > 400 else 2
    if height is None:
        height = 420 if week else 380

    def _ok(v) -> bool:
        return v is not None and v == v

    rows = []
    for name, color, vals in stack:
        for i in range(n):
            if _ok(vals[i]) and abs(vals[i]) > 1e-9:
                rows.append({"h": hours[i], "src": name, "kw": vals[i], "t": labels[i]})
    stack_df = pd.DataFrame(rows or [{"h": hours[0], "src": "", "kw": 0.0, "t": labels[0]}])
    order = {name: i for i, (name, _, _) in enumerate(stack)}
    stack_df["o"] = stack_df["src"].map(order).fillna(0)

    bess = [charge[i] - discharge[i] for i in range(n)]
    bess_df = pd.DataFrame({"h": hours, "kw": bess, "t": labels,
                            "sgn": ["charge" if v >= 0 else "discharge" for v in bess]})
    bess_df = bess_df[bess_df["kw"].abs() > 1e-9]
    load_df = pd.DataFrame({"h": hours, "kw": [v if _ok(v) else None for v in load],
                            "t": labels})
    # each unbroken run of readings is a line of its own
    gap = load_df["kw"].isna()
    load_df["seg"] = gap.cumsum()
    load_df = load_df[~gap]

    top = max([sum(v[i] for _, _, v in stack if _ok(v[i])) for i in range(n)]
              + [v for v in load if _ok(v)] + [1.0]
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
    label_expr = None
    if xlabels:
        xticks = sorted(xlabels)
        names_at = [""] * (max(hours) + 1)
        for h, text in xlabels.items():
            names_at[h] = text
        label_expr = f"{json.dumps(names_at, ensure_ascii=False)}[datum.value] || ''"
    else:
        xticks = ([1] + list(range(24, n + 1, 24)) if week
                  else [h for h in hours if h % 2 == 1])
    if xtitle is None:
        xtitle = "hour of week" if week else "hour of day"
    # horizontal rules only, as in the reference grid
    xscale = alt.Scale(domain=[hours[0] - 0.5, hours[-1] + 0.5], nice=False)
    yscale = alt.Scale(domain=[bot, top], nice=False)
    xaxis = _axis(values=xticks, title=xtitle, grid=False, label_expr=label_expr)
    xenc = alt.X("h:Q", axis=xaxis, scale=xscale)
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
        tip_df["f0"] = [f"{v:,.0f} kW" if _ok(v) else "—" for v in load]
        tips.append(alt.Tooltip("f0:N", title="site load"))
        palette.append(INK)
    # the same axis definitions as every other layer, so Vega-Lite merges them
    # into the one pair of axes; an `axis=None` on either drops both
    _band = alt.Chart(tip_df).mark_rect().encode(
        x=alt.X("x0:Q", scale=xscale, axis=xaxis), x2="x1:Q",
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
    # and anything longer none at all: hundreds of dots are only a thicker line
    point = (False if long
             else alt.OverlayMarkDef(color=INK, size=6, filled=True) if week
             else alt.OverlayMarkDef(color=PANEL, stroke=INK, strokeWidth=1.6,
                                     size=26, filled=False))
    line = alt.Chart(load_df).mark_line(
        color=INK, strokeWidth=1.1 if week else 1.6, point=point,
    ).encode(x=xenc, y=yenc, detail="seg:N")
    # the reference's activeDot: the hovered hour's marker fills in and swells
    active = alt.Chart(load_df).mark_point(
        size=80, filled=True, fill=INK, stroke=PANEL, strokeWidth=2,
    ).encode(x=xenc, y=yenc,
             opacity=alt.when(hover).then(alt.value(1.0)).otherwise(alt.value(0.0)))

    layers = [wash]
    if seps is None and week:
        seps = list(range(24, n, 24))
    if seps:
        layers.append(alt.Chart(pd.DataFrame({"x": seps}))
                      .mark_rule(color=RULE, strokeWidth=1).encode(x="x:Q"))
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

    _tooltip_palette(palette, tip_scope)
    return (alt.layer(*layers)
            .properties(height=height, background=PANEL, padding={"left": 4, "right": 8,
                                                                  "top": 6, "bottom": 2})
            # without this the unit colours and the battery charge/discharge
            # colours are merged into one scale and the battery bar takes a
            # generator's colour
            .resolve_scale(color="independent")
            .configure_view(stroke=None)
            .configure_axis(labelFont=MONO, titleFont=MONO))


def _m_label(v: float, cur: str, signed: bool = False) -> str:
    """Money in millions to one decimal, for a label at a bar's tip."""
    sign = ("+" if v > 0.05e6 else "−" if v < -0.05e6 else "") if signed else (
        "−" if v < -0.05e6 else "")
    body = f"{abs(v) / 1e6:,.1f}"
    return f"{sign}${body}M" if cur == "$" else f"{sign}{body} M {cur}"


# the role a bar plays in the scenario chart, and its colour: the picked
# scenario in ink, what it is set against in the charge teal, the rest as context
ROLE_COLORS = {"scenario": INK, "against": CHARGE, "other": CEILING, "measured": GRID_COLOR}


def _ink_on(fill: str) -> str:
    """White or the ink for a label set inside a fill: whichever contrasts more."""
    def lum(hex_color: str) -> float:
        h = hex_color.lstrip("#")
        ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    f = lum(fill)
    return PANEL if 1.05 / (f + 0.05) >= (f + 0.05) / (lum(INK) + 0.05) else INK


def _two_lines(text: str) -> str:
    """An axis label broken once, at its first space, for the axis's labelExpr."""
    return text.replace(" ", "|", 1)


def _full(v: float, cur: str, signed: bool = False) -> str:
    """Money in full for a hover panel, with a true minus: −13,023,379 ₸."""
    return (f"{v:+,.0f}" if signed else f"{v:,.0f}").replace("-", "\u2212") + f" {cur}"


def _quiet(*layers):
    """The layers, with the hover panel off on every one that names no tooltip.

    Streamlit's chart theme turns tooltips on for every mark, so a layer drawn
    only to decorate -- a link, a label, a wash, a stalk -- would answer the
    pointer with its raw fields ("ref 200290708.508 · short Measured"). Only a
    layer that says what to show is left to show it."""
    for lc in layers:
        if lc.encoding.tooltip is not alt.Undefined:
            continue
        m = lc.mark
        lc.mark = alt.MarkDef(type=m, tooltip=False) if isinstance(m, str) else m.copy()
        if not isinstance(m, str):
            lc.mark.tooltip = False
    return list(layers)


def cost_bridge_chart(start: dict, steps: list[dict], end: dict, cur: str, *,
                      scope: str | None = None, height: int = 300):
    """From one scenario's operating cost to another's, part by part.

    A bridge: the first column is ``start`` -- the scenario set against, its
    cost the zero line -- each next one a part of the cost moving the level up
    (it costs more there) or down (it costs less), the last ``end``, the picked
    scenario, as one bar from that zero line to where the parts leave it. So
    the reader sees not only which is cheaper but which parts make it so, and
    that they add up: the end bar is the parts' sum, drawn.

    ``start`` and ``end`` are dicts with ``letter`` and ``total``; ``steps``
    with ``label``, ``a`` (the start's figure on that part) and ``b`` (the
    end's). The axis is money against the start, so no bar is cut off at the
    baseline: each one's length is the difference it stands for."""
    s_col = f"{start['letter']}|{_m_label(start['total'], cur)}"
    e_col = f"{end['letter']}|{_m_label(end['total'], cur)}"
    cols = [s_col] + [_two_lines(st_["label"]) for st_ in steps] + [e_col]
    full = lambda v: _full(v, cur)
    bars, conn, lvl = [], [], 0.0
    prev = s_col
    for st_ in steps:
        d = st_["b"] - st_["a"]
        col = _two_lines(st_["label"])
        conn.append({"col": prev, "col2": col, "y": lvl})
        bars.append({"col": col, "y0": lvl, "y1": lvl + d,
                     "kind": "up" if d > 0 else "down", "txt": _m_label(d, cur, signed=True),
                     "part": st_["label"], "a": full(st_["a"]), "b": full(st_["b"]),
                     "chg": _full(d, cur, signed=True)})
        lvl += d
        prev = col
    total = end["total"] - start["total"]
    conn.append({"col": prev, "col2": e_col, "y": lvl})
    bars.append({"col": e_col, "y0": 0.0, "y1": total, "kind": "end",
                 "txt": _m_label(total, cur, signed=True), "part": "operating cost",
                 "a": full(start["total"]), "b": full(end["total"]),
                 "chg": _full(total, cur, signed=True)})
    df = pd.DataFrame(bars)
    df["top"] = df[["y0", "y1"]].max(axis=1)
    df["bot"] = df[["y0", "y1"]].min(axis=1)
    df["upward"] = df["y1"] >= df["y0"]
    levels = [0.0] + [b["y1"] for b in bars]
    lo, hi = min(levels), max(levels)
    pad = max(hi - lo, abs(start["total"]) * 0.01, 1.0) * 0.24
    x = alt.X("col:N", sort=cols, title=None,
              axis=alt.Axis(labelFont=MONO, labelFontSize=11, labelColor=INK, labelAngle=0,
                            labelExpr="split(datum.label, '|')", labelPadding=8,
                            ticks=False, domain=False, labelLimit=140))
    y = alt.Y("y0:Q", title=f"cost against {start['letter']}, {cur}",
              scale=alt.Scale(domain=[lo - pad, hi + pad], nice=False),
              axis=_axis(fmt="~s", domain=False))
    tip = [alt.Tooltip("part:N", title="part"),
           alt.Tooltip("a:N", title=start["letter"]), alt.Tooltip("b:N", title=end["letter"]),
           alt.Tooltip("chg:N", title=f"{end['letter']} − {start['letter']}")]
    color = alt.Color("kind:N", legend=None,
                      scale=alt.Scale(domain=["up", "down", "end"], range=[DISCHARGE, SAVE, INK]))
    links = alt.Chart(pd.DataFrame(conn)).mark_rule(
        color=MUTED, strokeDash=[3, 3], strokeWidth=1).encode(
        x=alt.X("col:N", sort=cols), x2="col2:N", y="y:Q")
    zero = alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(
        color=CHARGE, strokeDash=[5, 3], strokeWidth=1.25).encode(y="y:Q")
    mark = alt.Chart(pd.DataFrame({"col": [s_col], "y": [0.0]})).mark_circle(
        color=CHARGE, size=150, opacity=1, stroke=PANEL, strokeWidth=2).encode(
        x=alt.X("col:N", sort=cols), y="y:Q")
    body = alt.Chart(df).mark_bar(size=24, cornerRadius=3).encode(
        x=x, y=y, y2="y1:Q", color=color, tooltip=tip)
    above = alt.Chart(df).transform_filter("datum.upward").mark_text(
        baseline="bottom", dy=-6, font=MONO, fontSize=11, color=INK).encode(
        x=alt.X("col:N", sort=cols), y="top:Q", text="txt:N")
    below = alt.Chart(df).transform_filter("!datum.upward").mark_text(
        baseline="top", dy=6, font=MONO, fontSize=11, color=INK).encode(
        x=alt.X("col:N", sort=cols), y="bot:Q", text="txt:N")
    _tooltip_palette([INK] * 4, scope)
    return (alt.layer(*_quiet(zero, links, body, mark, above, below))
            .properties(height=height, background=PANEL,
                        padding={"left": 4, "right": 12, "top": 10, "bottom": 2})
            .configure_view(stroke=None)
            .configure_axis(labelFont=MONO, titleFont=MONO))


def cash_curve_chart(years: list[int], lo: list[float], hi: list[float], cur: str, *,
                     payback: tuple[float, float | None] | None = None, replace_year: int = 0,
                     horizon: int | None = None, scope: str | None = None,
                     height: int = 300, title: str = "cumulative cash, discounted"):
    """Money over the years: where it stands at each year's end, as one line.

    For a battery, year 0 is its price, below the zero line, and every year
    after adds that year's saving net of its O&M (less the replacement, in its
    year), discounted: the line crosses zero where the battery has paid for
    itself, and it ends on the net present value. The ground between the line
    and zero is washed orange below and green above -- the side of the line
    says the same, so the sign never rests on colour.

    ``lo`` and ``hi`` are the curve at the low and at the high end of the
    yearly saving (one curve when every month was measured): the low end is
    the solid line, the high end dashed, the range between them shaded.
    ``payback`` is (year, year), or (year, None) when only the high end pays
    back. Hovering a year shows where both ends stand and what that year added."""
    n = horizon or (years[-1] if years else 0)
    ranged = any(abs(a - b) > 0.5 for a, b in zip(lo, hi))
    rows = []
    for i, (yr, a, b) in enumerate(zip(years, lo, hi)):
        pa, pb = (lo[i - 1], hi[i - 1]) if i else (0.0, 0.0)
        rows.append({"year": yr, "lo": a, "hi": b,
                     "at": (_full(a, cur) if abs(b - a) < 0.5 else
                            f"{_full(min(a, b), cur)[:-len(cur) - 1]} … {_full(max(a, b), cur)}"),
                     "flow": (_full(a - pa, cur, signed=True) if abs((b - pb) - (a - pa)) < 0.5 else
                              f"{_full(min(a - pa, b - pb), cur, signed=True)[:-len(cur) - 1]} … "
                              f"{_full(max(a - pa, b - pb), cur, signed=True)}"),
                     "yl": f"year {yr}" + (" · the price" if yr == 0 else
                                           " · replacement" if yr == replace_year else "")})
    df = pd.DataFrame(rows)
    # the wash follows the low line exactly: its zero crossings are added as
    # points, so neither colour spills over the line where it crosses
    pts = []
    for i, (yr, v) in enumerate(zip(years, lo)):
        if i:
            py, pv = years[i - 1], lo[i - 1]
            if (pv < 0 < v) or (pv > 0 > v):
                pts.append((py + (0 - pv) / (v - pv) * (yr - py), 0.0))
        pts.append((yr, v))
    wash = pd.DataFrame([{"year": x, "neg": min(v, 0.0), "pos": max(v, 0.0), "zero": 0.0}
                         for x, v in pts])
    vals = [*lo, *hi, 0.0]
    vmin, vmax = min(vals), max(vals)
    pad = max(vmax - vmin, 1.0) * 0.16
    x = alt.X("year:Q", title="year",
              scale=alt.Scale(domain=[min(years) - 0.5, n + 0.5], nice=False),
              axis=_axis(values=list(range(0, n + 1, 5 if n > 12 else 1)), fmt="d",
                         grid=False, domain=False))
    y = alt.Y("lo:Q", title=f"{title}, {cur}",
              scale=alt.Scale(domain=[vmin - pad, vmax + pad], nice=False),
              axis=_axis(fmt="~s", domain=False))
    tip = [alt.Tooltip("yl:N", title="end of"), alt.Tooltip("at:N", title="cumulative"),
           alt.Tooltip("flow:N", title="that year")]
    layers = []
    if payback is not None:
        # (year, year) or (year, None): the high end pays back, the low never does
        p0, p1 = payback
        if p1 is None:
            b, lab = n + 0.5, f"pays back · year {p0:,.1f} … never"
        else:
            p0, p1 = sorted((p0, p1))
            b = max(p1, p0 + 0.04)
            lab = (f"pays back · year {p0:,.1f}" if p1 - p0 < 0.05 else
                   f"pays back · year {p0:,.1f} … {p1:,.1f}")
        # the words beside the band, or inside its left edge when it reaches the right
        inside = b > n * 0.6
        band = pd.DataFrame({"a": [p0], "b": [b], "lab": [lab], "at": [p0 if inside else b]})
        layers += [
            alt.Chart(band).mark_rect(color=SAVE, opacity=0.10).encode(x="a:Q", x2="b:Q"),
            alt.Chart(band).mark_rule(color=SAVE, strokeWidth=1.5, strokeDash=[4, 3]).encode(
                x="a:Q"),
            alt.Chart(band).mark_text(align="right" if inside else "left", baseline="top",
                                      dx=-6 if inside else 6, dy=4, font=MONO,
                                      fontSize=11, color=INK).encode(
                x="at:Q", y=alt.value(0), text="lab:N")]
    layers += [
        alt.Chart(wash).mark_area(color=DISCHARGE, opacity=0.13).encode(
            x="year:Q", y="neg:Q", y2="zero:Q"),
        alt.Chart(wash).mark_area(color=SAVE, opacity=0.15).encode(
            x="year:Q", y="pos:Q", y2="zero:Q"),
        alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(color=INK, strokeWidth=1).encode(
            y="y:Q")]
    if ranged:
        layers += [
            alt.Chart(df).mark_area(color=CEILING, opacity=0.22).encode(x=x, y=y, y2="hi:Q"),
            alt.Chart(df).mark_line(color=INK, strokeWidth=1.5, strokeDash=[5, 3]).encode(
                x="year:Q", y="hi:Q")]
    layers.append(alt.Chart(df).mark_line(color=INK, strokeWidth=2, strokeJoin="round",
                                          strokeCap="round").encode(x=x, y=y))
    ends = df.iloc[[0, -1]]
    layers.append(alt.Chart(ends).mark_circle(size=64, color=INK, opacity=1, stroke=PANEL,
                                              strokeWidth=2).encode(x="year:Q", y="lo:Q"))
    if lo[0] < 0 and years[0] == 0:
        start = pd.DataFrame({"x": [0], "y": [lo[0]], "lab": [f"{_m_label(lo[0], cur)} · the price"]})
        layers.append(alt.Chart(start).mark_text(
            align="left", baseline="top", dx=2, dy=9, font=MONO, fontSize=11,
            color=INK).encode(x="x:Q", y="y:Q", text="lab:N"))
    if replace_year and replace_year in years:
        i = years.index(replace_year)
        rep = pd.DataFrame({"x": [replace_year], "y": [min(lo[i], hi[i])],
                            "lab": ["replacement"]})
        layers.append(alt.Chart(rep).mark_text(baseline="top", dy=8, font=MONO, fontSize=10.5,
                                               color=MUTED).encode(x="x:Q", y="y:Q", text="lab:N"))
    last_lo, last_hi = lo[-1], hi[-1]
    end_txt = (_m_label(last_lo, cur, signed=True) if abs(last_hi - last_lo) < 0.5e5 else
               f"{_m_label(min(last_lo, last_hi), cur, signed=True)} … "
               f"{_m_label(max(last_lo, last_hi), cur, signed=True)}")
    up = last_lo >= 0
    end = pd.DataFrame({"x": [years[-1]], "y": [max(last_lo, last_hi) if up
                                                 else min(last_lo, last_hi)],
                        "lab": [end_txt]})
    layers.append(alt.Chart(end).mark_text(
        align="right", baseline="bottom" if up else "top", dy=-9 if up else 9,
        font=MONO, fontSize=11, fontWeight=600, color=INK).encode(
        x="x:Q", y="y:Q", text="lab:N"))
    if payback is None and lo[0] < 0:
        never = pd.DataFrame({"lab": [f"does not pay back in {n} years"]})
        layers.append(alt.Chart(never).mark_text(
            align="right", baseline="top", dx=-4, dy=4, font=MONO, fontSize=11,
            color=INK).encode(x=alt.value("width"), y=alt.value(0), text="lab:N"))
    # hover: a year at a time, the whole column of the plot as the target
    hover = alt.selection_point(fields=["year"], nearest=True, on="pointerover",
                                clear="pointerout", empty=False)
    layers += [
        alt.Chart(df).mark_rule(color=MUTED, strokeWidth=1).encode(x="year:Q").transform_filter(
            hover),
        alt.Chart(df).mark_circle(size=70, color=INK, opacity=1, stroke=PANEL,
                                  strokeWidth=2).encode(x="year:Q", y="lo:Q").transform_filter(
            hover),
        alt.Chart(df).mark_rule(strokeWidth=16, opacity=0).encode(
            x="year:Q", tooltip=tip).add_params(hover)]
    _tooltip_palette([INK] * 3, scope)
    return (alt.layer(*_quiet(*layers))
            .properties(height=height, background=PANEL,
                        padding={"left": 4, "right": 12, "top": 10, "bottom": 2})
            .configure_view(stroke=None)
            .configure_axis(labelFont=MONO, titleFont=MONO))


def scenario_ladder_chart(rows: list[dict], cur: str, *, ref: dict,
                          scope: str | None = None):
    """Every scenario's operating cost, cheapest on top, set against one of them.

    A dot a scenario on one money axis, and a stalk from the scenario set
    against (``ref``: ``letter`` and ``total``; its cost the dashed teal line)
    to each dot, so the distance a stalk runs is what that scenario costs more
    or less than it. Dots carry no length, so the axis need not start at zero
    and the differences -- a few per cent of the total -- are not flattened
    against it, as they were when every scenario was a bar from zero. The
    figures stand in a column at the right, clear of the dots.

    ``rows``: ``label`` (the full name, for the hover panel), ``short`` (the
    axis text), ``role`` (a ROLE_COLORS key), ``total``, and ``tip`` (the
    per-year figure for the hover panel)."""
    rows = sorted(rows, key=lambda r: r["total"])
    ref_v = ref["total"]
    df = pd.DataFrame([{"label": r["label"], "short": r.get("short", r["label"]),
                        "role": r["role"], "v": r["total"], "ref": ref_v,
                        "txt": _m_label(r["total"], cur),
                        "dtxt": ("—" if r["role"] == "against" else
                                 _m_label(r["total"] - ref_v, cur, signed=True)),
                        "full": _full(r["total"], cur),
                        "d": ("—" if r["role"] == "against" else
                              _full(r["total"] - ref_v, cur, signed=True)),
                        "tip": r.get("tip", "")} for r in rows])
    vals = [r["total"] for r in rows] + [ref_v]
    lo, hi = min(vals), max(vals)
    pad = max(hi - lo, abs(ref_v) * 0.02, 1.0) * 0.12
    order = [r.get("short", r["label"]) for r in rows]
    roles = list(ROLE_COLORS)
    y = alt.Y("short:N", sort=order, title=None,
              axis=alt.Axis(labelFont=MONO, labelFontSize=11, labelColor=INK, labelLimit=180,
                            ticks=False, domain=False, labelPadding=10))
    x = alt.X("v:Q", title=f"operating cost, {cur} — not from zero",
              scale=alt.Scale(domain=[lo - pad, hi + pad], nice=False, zero=False),
              axis=_axis(fmt="~s", domain=False))
    tip = [alt.Tooltip("label:N", title="scenario"), alt.Tooltip("full:N", title="cost"),
           alt.Tooltip("d:N", title=f"against {ref['letter']}"),
           alt.Tooltip("tip:N", title="per year")]
    refl = alt.Chart(pd.DataFrame({"v": [ref_v]})).mark_rule(
        color=CHARGE, strokeDash=[5, 3], strokeWidth=1.25).encode(x="v:Q")
    stalk = alt.Chart(df).mark_rule(color=RULE, strokeWidth=2.5).encode(
        y=y, x="ref:Q", x2="v:Q")
    dots = alt.Chart(df).mark_circle(size=170, opacity=1, stroke=PANEL, strokeWidth=2).encode(
        y=y, x=x, tooltip=tip,
        color=alt.Color("role:N", legend=None,
                        scale=alt.Scale(domain=roles, range=[ROLE_COLORS[k] for k in roles])))
    cost = alt.Chart(df).mark_text(align="right", dx=96, font=MONO, fontSize=11,
                                   color=INK).encode(y=y, x=alt.value("width"), text="txt:N")
    diff = alt.Chart(df).mark_text(align="right", dx=180, font=MONO, fontSize=11,
                                   color=MUTED).encode(y=y, x=alt.value("width"), text="dtxt:N")
    heads = pd.DataFrame({"t": ["cost", f"vs {ref['letter']}"], "dx": [96, 180]})
    head_cost = alt.Chart(heads.iloc[[0]]).mark_text(
        align="right", baseline="bottom", dx=96, dy=-4, font=MONO, fontSize=10, color=MUTED).encode(
        x=alt.value("width"), y=alt.value(0), text="t:N")
    head_diff = alt.Chart(heads.iloc[[1]]).mark_text(
        align="right", baseline="bottom", dx=180, dy=-4, font=MONO, fontSize=10, color=MUTED).encode(
        x=alt.value("width"), y=alt.value(0), text="t:N")
    _tooltip_palette([INK] * 4, scope)
    return (alt.layer(*_quiet(refl, stalk, dots, cost, diff, head_cost, head_diff))
            # the figures' column sits past the plot's right edge; Vega's fit
            # already makes room for it, so no padding is added for it here
            .properties(height=44 * len(rows) + 50, background=PANEL,
                        padding={"left": 4, "right": 12, "top": 20, "bottom": 2})
            .configure_view(stroke=None)
            .configure_axis(labelFont=MONO, titleFont=MONO))


def energy_mix_chart(rows: list[dict], sources: list[tuple[str, str]], *,
                     scope: str | None = None, min_share: float = 0.07,
                     unit: str = "MWh"):
    """Where each scenario's energy came from: one tall segmented bar a row.

    ``sources`` is ``(name, colour)`` in stack order -- each engine in the
    dispatch chart's own colour, then the grid -- so a source wears the same
    colour here as in every other chart on the page. ``rows``: ``label``,
    ``parts`` (source -> kWh) and ``tips`` (source -> one line for the hover
    panel). Each block prints its share where the share fits inside it; the
    legend names the blocks, the hover panel carries the rest."""
    df_rows = []
    for r in rows:
        tot = sum(max(0.0, r["parts"].get(nm, 0.0)) for nm, _ in sources) or 1.0
        x0 = 0.0
        for nm, col in sources:
            v = max(0.0, r["parts"].get(nm, 0.0))
            if v <= 0:
                continue
            sh = v / tot
            df_rows.append({"label": r["label"], "src": nm, "x0": x0 / 1e3, "x1": (x0 + v) / 1e3,
                            "mid": (x0 + v / 2) / 1e3, "mwh": f"{v / 1e3:,.0f} {unit}",
                            "share": f"{sh * 100:,.1f} %",
                            "lab": f"{sh * 100:,.0f}%" if sh >= min_share else "",
                            "tc": _ink_on(col), "more": (r.get("tips") or {}).get(nm, "—")})
            x0 += v
    df = pd.DataFrame(df_rows)
    order = [r["label"] for r in rows]
    names = [nm for nm, _ in sources]
    y = alt.Y("label:N", sort=order, title=None,
              axis=alt.Axis(labelFont=MONO, labelFontSize=11, labelColor=INK, labelLimit=330,
                            ticks=False, domain=False, labelPadding=10))
    x = alt.X("x0:Q", title=f"energy, {unit}", axis=_axis(fmt=",.0f", domain=False),
              scale=alt.Scale(domain=[0, max(df["x1"].max() if len(df) else 1.0, 1.0) * 1.02],
                              nice=False))
    tip = [alt.Tooltip("label:N", title="scenario"), alt.Tooltip("src:N", title="source"),
           alt.Tooltip("mwh:N", title="energy"), alt.Tooltip("share:N", title="share"),
           alt.Tooltip("more:N", title="ran")]
    bars = alt.Chart(df).mark_bar(size=26, cornerRadius=4, stroke=PANEL, strokeWidth=2).encode(
        y=y, x=x, x2="x1:Q", tooltip=tip,
        color=alt.Color("src:N", legend=None,
                        scale=alt.Scale(domain=names, range=[c for _, c in sources])))
    text = alt.Chart(df).transform_filter("datum.lab != ''").mark_text(
        font=MONO, fontSize=11, fontWeight=600).encode(
        y=y, x="mid:Q", text="lab:N", color=alt.Color("tc:N", scale=None, legend=None))
    _tooltip_palette([INK] * 5, scope)
    return (alt.layer(*_quiet(bars, text))
            .properties(height=46 * len(rows) + 50, background=PANEL,
                        padding={"left": 4, "right": 12, "top": 8, "bottom": 2})
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
