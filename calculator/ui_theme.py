"""Visual pieces that config.toml cannot express, matched to reopt.nlr.gov.

Colours here were sampled from the live tool (see .streamlit/config.toml header).
Everything that CAN be themed natively lives in config.toml; this module only
adds the two things Streamlit has no native equivalent for:

  * the orange section header bar that REopt puts above each Step-5 panel
  * the results cards (white stat cards + the dark life-cycle-savings card)
"""

from __future__ import annotations

import streamlit as st

ORANGE = "#E07700"
BLUE = "#0079C2"
PANEL = "#FDF4ED"
INK = "#333333"
DARK_CARD = "#3B3B3B"

_CSS = f"""
<style>
/* ---- Step headings: REopt uses light-weight orange ---- */
.reopt-step {{
    color: {ORANGE};
    font-size: 30px;
    font-weight: 300;
    margin: 1.4rem 0 0.4rem 0;
}}

/* ---- Orange section header bar above each panel ---- */
.reopt-panel-head {{
    background: {ORANGE};
    color: #FFFFFF;
    font-size: 16px;
    font-weight: 500;
    padding: 9px 14px;
    border-radius: 4px 4px 0 0;
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 14px;
}}
.reopt-panel-head .req {{
    font-size: 12px;
    font-weight: 400;
    opacity: 0.9;
}}

/* the expander that follows a header bar sits flush under it */
.reopt-panel-head + div [data-testid="stExpander"] details {{
    border-top-left-radius: 0;
    border-top-right-radius: 0;
    border-top: none;
    background: {PANEL};
}}

/* ---- Results stat cards ---- */
.reopt-card {{
    background: {PANEL};
    border: 1px solid #EFE2D6;
    border-radius: 6px;
    padding: 20px 22px;
    height: 100%;
}}
.reopt-card-title {{
    font-size: 19px;
    font-weight: 400;
    color: {INK};
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
}}
.reopt-card-title .ico {{ color: {ORANGE}; font-size: 26px; }}
.reopt-figs {{ display: flex; gap: 46px; margin: 10px 0 12px 0; }}
.reopt-fig-num {{ font-size: 34px; font-weight: 300; color: {INK}; line-height: 1.1; }}
.reopt-fig-lab {{ font-size: 15px; color: #5A5A5A; }}
.reopt-card-note {{ font-size: 13px; color: #5A5A5A; line-height: 1.45; }}

/* ---- Dark life cycle savings card ---- */
.reopt-savings {{
    background: {DARK_CARD};
    color: #FFFFFF;
    border-radius: 6px;
    padding: 20px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 28px;
    margin-top: 14px;
}}
.reopt-savings-left {{ max-width: 70%; }}
.reopt-savings-title {{
    font-size: 21px;
    font-weight: 400;
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 6px;
}}
.reopt-savings-note {{ font-size: 13px; opacity: 0.85; line-height: 1.45; }}
.reopt-savings-value {{ font-size: 40px; font-weight: 300; white-space: nowrap; }}


/* ---- misc ---- */
.reopt-hint {{ font-size: 12px; color: #767676; }}
</style>
"""



# Inline SVG icons (Material Symbols paths) so nothing depends on a web font.
_ICONS = {
    "location_on": "M480-480q33 0 56.5-23.5T560-560q0-33-23.5-56.5T480-640q-33 0-56.5 23.5T400-560q0 33 23.5 56.5T480-480Zm0 400Q319-217 239.5-334.5T160-552q0-150 96.5-239T480-880q127 0 223.5 89T800-552q0 100-79.5 217.5T480-80Z",
    "bolt": "M400-80v-320H280l160-480h240L520-400h160L400-80Z",
    "bar_chart": "M160-160v-400h160v400H160Zm240 0v-640h160v640H400Zm240 0v-280h160v280H640Z",
    "attach_money": "M441-120v-86q-53-12-91.5-46T293-348l74-30q15 48 44.5 73t77.5 25q41 0 69.5-18.5T587-356q0-35-22-55.5T463-458q-86-27-118-64.5T313-614q0-65 42-101t106-42v-83h80v83q50 8 82 36.5t45 66.5l-74 32q-12-32-34-48t-58-16q-44 0-67 19.5T412-614q0 33 30 52t104 40q79 22 112.5 63T692-352q0 71-42 108t-109 46v78h-100Z",
    "eco": "M180-475q0-151 106-258t257-107h277v130q0 151-106 257T457-347h-97v187h-180v-315Z",
    "solar_power": "M120-120v-80h140l-60-160h-80v-80h720v80h-80l-60 160h140v80H120Zm160-240h400l-30-80H310l30 80ZM160-520v-80h80v80h-80Zm280-320v-80h80v80h-80ZM720-520v-80h80v80h-80ZM243-687l-57-57 57-57 56 57-56 57Zm474 0-57-57 57-57 57 57-57 57ZM480-400q-66 0-113-47t-47-113q0-66 47-113t113-47q66 0 113 47t47 113q0 66-47 113t-113 47Z",
    "battery_charging_full": "M280-80q-17 0-28.5-11.5T240-120v-640q0-17 11.5-28.5T280-800h80v-80h240v80h80q17 0 28.5 11.5T720-760v640q0 17-11.5 28.5T680-80H280Zm160-160 160-240h-90v-160L360-400h80v160Z",
    "savings": "M520-600q17 0 28.5-11.5T560-640q0-17-11.5-28.5T520-680q-17 0-28.5 11.5T480-640q0 17 11.5 28.5T520-600ZM320-640h160v-80H320v80ZM180-120q-42-139-81-278.5T60-680q0-92 64-156t156-64q45 0 85.5 17t71.5 49l64 64h139q29-54 82.5-87T840-890v270l-92 31-56 187 68 72v210H600v-80H440v80H180Z",
}


def _svg(name: str, size: int = 26, color: str = ORANGE) -> str:
    path = _ICONS.get(name)
    if not path:
        return ""
    return (f'<svg viewBox="0 -960 960 960" width="{size}" height="{size}" '
            f'fill="{color}" style="vertical-align:middle;flex:none">'
            f'<path d="{path}"/></svg>')



def _ico(name: str, size: int = 26, white: bool = False) -> str:
    """Icon as a CSS-backed span (st.html removes inline <svg>)."""
    if name not in _ICONS:
        return ""
    cls = "ico-" + name.replace("_", "-") + ("-w" if white else "-o")
    return (f'<span class="reopt-ico {cls}" '
            f'style="width:{size}px;height:{size}px"></span>')


def inject() -> None:
    """Add the stylesheet once per run."""
    st.html(_CSS)


def step(title: str) -> None:
    """A REopt-style step heading (orange, light weight)."""
    st.html(f'<div class="reopt-step">{title}</div>')


def panel_head(title: str, icon: str = "", required: bool = False) -> None:
    """The orange bar REopt shows above each Step-5 section."""
    ico = ""  # Streamlit sanitises <svg> and data: URIs out of st.html
    req = '<span class="req">(required)</span>' if required else ""
    st.html(f'<div class="reopt-panel-head">{ico}<span>{title}</span>{req}</div>')


def stat_card(title: str, icon: str, figures: list[tuple[str, str]], note: str = "") -> None:
    """White stat card: title + one or two big figures + a note."""
    figs = "".join(
        f'<div><div class="reopt-fig-num">{v}</div>'
        f'<div class="reopt-fig-lab">{lab}</div></div>'
        for v, lab in figures
    )
    st.html(
        f'<div class="reopt-card">'
        f'<div class="reopt-card-title"><span>{title}</span></div>'
        f'<div class="reopt-figs">{figs}</div>'
        f'<div class="reopt-card-note">{note}</div>'
        f"</div>"
    )


def savings_card(title: str, note: str, value: str) -> None:
    """Dark card for life cycle savings, as on the REopt results page."""
    st.html(
        f'<div class="reopt-savings">'
        f'<div class="reopt-savings-left">'
        f'<div class="reopt-savings-title">'
        f"<span>{title}</span></div>"
        f'<div class="reopt-savings-note">{note}</div>'
        f"</div>"
        f'<div class="reopt-savings-value">{value}</div>'
        f"</div>"
    )
