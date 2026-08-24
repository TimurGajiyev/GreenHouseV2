"""Generate calculator/reopt_core/ui_fields.py from the live-extracted UI spec.

Never hand-transcribe REopt's field metadata -- generate it, so labels, option
values, option order, defaults and help text are exactly what the tool serves.

Run:  python calculator/tools/gen_ui_fields.py
"""

from __future__ import annotations

import io
import json
import os
import pprint

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = os.path.join(ROOT, "reopt_test_data", "ui-spec.json")
OUT = os.path.join(ROOT, "calculator", "reopt_core", "ui_fields.py")

# Panels the calculator implements (steps 1-5, four technologies).
KEEP_PANELS = {
    "top", "site", "utility", "load_profile", "financial",
    "pv", "battery", "chp", "prime_generator", "generator", "emissions",
}


def main() -> None:
    with io.open(SPEC, encoding="utf-8") as fh:
        spec = json.load(fh)

    merged: dict[str, dict] = {}
    for cfg_name, cfg in spec["configs"].items():
        for f in cfg["fields"]:
            if f["panel"] not in KEEP_PANELS:
                continue
            rec = merged.setdefault(
                f["id"],
                {
                    "id": f["id"],
                    "name": f["name"],
                    "panel": f["panel"],
                    "panel_title": f["panelTitle"],
                    "label": f["label"],
                    "tag": f["tag"],
                    "type": f["type"],
                    "required": f["required"],
                    "default": f["value"],
                    "placeholder": f["placeholder"],
                    "options": [(o["v"], o["t"]) for o in f["options"]] if f["options"] else None,
                    "help": f["help"],
                    "configs": [],
                },
            )
            rec["configs"].append(cfg_name)

    steps = spec["configs"]["chp"]["steps"]
    techs_grid = [(t["id"], t["label"]) for t in spec["configs"]["chp"]["techs"]]
    techs_off = [(t["id"], t["label"]) for t in spec["configs"]["offgrid"]["techs"]]

    body = io.StringIO()
    body.write('"""AUTO-GENERATED from reopt_test_data/ui-spec.json -- do not edit by hand.\n\n')
    body.write("Field metadata scraped live from https://reopt.nlr.gov/tool so that labels,\n")
    body.write("option values/order, defaults and help text match the real tool exactly.\n")
    body.write("Regenerate with: python calculator/tools/gen_ui_fields.py\n\"\"\"\n\n")
    body.write("from __future__ import annotations\n\n")

    pp = pprint.PrettyPrinter(indent=4, width=100, sort_dicts=False)
    body.write("STEPS = " + pp.pformat(steps) + "\n\n")
    body.write("TECHS_GRID_TIED = " + pp.pformat(techs_grid) + "\n\n")
    body.write("TECHS_OFF_GRID = " + pp.pformat(techs_off) + "\n\n")
    body.write("FIELDS = " + pp.pformat(merged) + "\n\n")
    body.write(
        "\n"
        "def field(fid: str) -> dict:\n"
        '    """Return the extracted metadata for one REopt form field id."""\n'
        "    return FIELDS.get(fid, {})\n\n\n"
        "def options(fid: str) -> list[tuple[str, str]]:\n"
        '    """(value, label) pairs in the tool\'s own order, blank entries removed."""\n'
        "    opts = FIELDS.get(fid, {}).get('options') or []\n"
        "    return [(v, t) for v, t in opts if v != '']\n\n\n"
        "def panel_fields(panel: str) -> list[dict]:\n"
        "    return [f for f in FIELDS.values() if f['panel'] == panel]\n"
    )

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as fh:
        fh.write(body.getvalue())

    per_panel: dict[str, int] = {}
    for f in merged.values():
        per_panel[f["panel"]] = per_panel.get(f["panel"], 0) + 1
    print(f"wrote {OUT}")
    print(f"  fields: {len(merged)}")
    print("  per panel: " + json.dumps(per_panel, sort_keys=True))


if __name__ == "__main__":
    main()
