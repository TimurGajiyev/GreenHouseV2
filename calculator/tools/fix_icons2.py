"""st.html sanitises <svg> out of the markup, so render icons as CSS
background-images (data URIs) instead. CSS survives sanitisation.
"""

import io
import os
import re
import urllib.parse

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui_theme.py")
s = io.open(P, encoding="utf-8").read()

PATHS = {
    "location_on": "M480-480q33 0 56.5-23.5T560-560q0-33-23.5-56.5T480-640q-33 0-56.5 23.5T400-560q0 33 23.5 56.5T480-480Zm0 400Q319-217 239.5-334.5T160-552q0-150 96.5-239T480-880q127 0 223.5 89T800-552q0 100-79.5 217.5T480-80Z",
    "bolt": "M400-80v-320H280l160-480h240L520-400h160L400-80Z",
    "bar_chart": "M160-160v-400h160v400H160Zm240 0v-640h160v640H400Zm240 0v-280h160v280H640Z",
    "attach_money": "M441-120v-86q-53-12-91.5-46T293-348l74-30q15 48 44.5 73t77.5 25q41 0 69.5-18.5T587-356q0-35-22-55.5T463-458q-86-27-118-64.5T313-614q0-65 42-101t106-42v-83h80v83q50 8 82 36.5t45 66.5l-74 32q-12-32-34-48t-58-16q-44 0-67 19.5T412-614q0 33 30 52t104 40q79 22 112.5 63T692-352q0 71-42 108t-109 46v78h-100Z",
    "eco": "M180-475q0-151 106-258t257-107h277v130q0 151-106 257T457-347h-97v187h-180v-315Z",
    "solar_power": "M120-120v-80h140l-60-160h-80v-80h720v80h-80l-60 160h140v80H120Zm160-240h400l-30-80H310l30 80ZM160-520v-80h80v80h-80Zm280-320v-80h80v80h-80ZM720-520v-80h80v80h-80ZM243-687l-57-57 57-57 56 57-56 57Zm474 0-57-57 57-57 57 57-57 57ZM480-400q-66 0-113-47t-47-113q0-66 47-113t113-47q66 0 113 47t47 113q0 66-47 113t-113 47Z",
    "battery_charging_full": "M280-80q-17 0-28.5-11.5T240-120v-640q0-17 11.5-28.5T280-800h80v-80h240v80h80q17 0 28.5 11.5T720-760v640q0 17-11.5 28.5T680-80H280Zm160-160 160-240h-90v-160L360-400h80v160Z",
    "savings": "M520-600q17 0 28.5-11.5T560-640q0-17-11.5-28.5T520-680q-17 0-28.5 11.5T480-640q0 17 11.5 28.5T520-600ZM320-640h160v-80H320v80Zm-140 520q-42-139-81-278.5T60-680q0-92 64-156t156-64q45 0 85.5 17t71.5 49l64 64h139v270l-92 31-56 187 68 72v210H600v-80H440v80H180Z",
}


def data_uri(path: str, color: str) -> str:
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 -960 960 960' "
           f"fill='{color}'><path d='{path}'/></svg>")
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="")


css_rules = ["\n/* ---- icons as CSS background images (st.html strips <svg>) ---- */",
             ".reopt-ico {{ display:inline-block; background-repeat:no-repeat; "
             "background-position:center; background-size:contain; flex:none; }}"]
for name, p in PATHS.items():
    css_rules.append(f".ico-{name.replace('_', '-')}-o {{ background-image:url(\"{data_uri(p, '#E07700')}\"); }}")
    css_rules.append(f".ico-{name.replace('_', '-')}-w {{ background-image:url(\"{data_uri(p, '#FFFFFF')}\"); }}")
css_block = "\n".join(css_rules) + "\n"

# insert before the closing </style>
s = s.replace("/* ---- misc ---- */", css_block + "\n/* ---- misc ---- */", 1)

# helper that emits a span with the right icon class
helper = '''

def _ico(name: str, size: int = 26, white: bool = False) -> str:
    """Icon as a CSS-backed span (st.html removes inline <svg>)."""
    if name not in _ICONS:
        return ""
    cls = "ico-" + name.replace("_", "-") + ("-w" if white else "-o")
    return (f'<span class="reopt-ico {cls}" '
            f'style="width:{size}px;height:{size}px"></span>')
'''
s = s.replace("\ndef inject() -> None:", helper + "\n\ndef inject() -> None:", 1)

# swap the call sites
s = s.replace('    ico = _svg(icon, size=20, color="#FFFFFF") if icon else ""',
              '    ico = _ico(icon, size=20, white=True) if icon else ""')
s = s.replace("f'<div class=\"reopt-card-title\">{_svg(icon, size=28)}<span>{title}</span></div>'",
              "f'<div class=\"reopt-card-title\">{_ico(icon, size=28)}<span>{title}</span></div>'")
s = s.replace('f\'<div class="reopt-savings-title">{_svg("savings", size=26, color="#FFFFFF")}\'',
              'f\'<div class="reopt-savings-title">{_ico("savings", size=26, white=True)}\'')

io.open(P, "w", encoding="utf-8").write(s)
print("icons switched to CSS background data-URIs")
