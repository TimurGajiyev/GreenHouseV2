"""The app's front door: which study it opens on.

    python calculator/tools/test_app_entry.py

The REopt tool is hidden, not removed (``SHOW_REOPT_TOOL`` in streamlit_app.py).
This runs the app headless twice: as it ships, it must open straight on the
custom dispatch study with no switch above it; with the flag turned on, the
switch must be back with both studies and the REopt tool must still draw its
first step. No API key, nothing online, no solve.
"""
from __future__ import annotations

import logging
import os
import sys
import warnings

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)
HERE = os.path.dirname(os.path.abspath(__file__))
CALC = os.path.dirname(HERE)
APP = os.path.join(CALC, "streamlit_app.py")
sys.path.insert(0, CALC)

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


def main() -> None:
    from streamlit.testing.v1 import AppTest
    os.chdir(os.path.dirname(CALC))

    print("\nas it ships")
    at = AppTest.from_file(APP, default_timeout=120).run()
    check("the app opens", not at.exception, str([e.value for e in at.exception][:1]))
    keys = {w.key for w in at.segmented_control}
    check("no study switch at the top", "study" not in keys, str(sorted(k for k in keys if k)))
    check("it is the custom dispatch study: its Start from switch is there", "gd_values" in keys)
    text = " ".join([*(h.proto.body for h in at.get("html")), *(m.value for m in at.markdown),
                     *(c.value for c in at.caption)])
    check("nothing of the REopt tool is drawn: neither its caption nor its first step",
          "Steps 1–5 of the REopt web tool" not in text and "Use case" not in text
          and len(at.segmented_control) == 1, f"{len(at.segmented_control)} switches")

    print("\nwith SHOW_REOPT_TOOL = True")
    src = open(APP, encoding="utf-8").read()
    flag = "SHOW_REOPT_TOOL = False"
    check("the flag is in the app, set to hide", src.count(flag) == 1)
    at = AppTest.from_string(src.replace(flag, "SHOW_REOPT_TOOL = True"),
                             default_timeout=120).run()
    check("the app opens", not at.exception, str([e.value for e in at.exception][:1]))
    sw = [w for w in at.segmented_control if w.key == "study"]
    check("the switch is back, with both studies, on the REopt tool",
          len(sw) == 1 and list(sw[0].options) == ["REopt tool", "Custom dispatch study (not REopt)"]
          and sw[0].value == "REopt tool", str(sw[0].options if sw else None))
    caps = " ".join(c.value for c in at.caption)
    check("and the REopt tool still draws its first step",
          "Steps 1–5 of the REopt web tool" in caps, caps[:80])
    if sw:
        sw[0].set_value("Custom dispatch study (not REopt)").run()
        check("its second option still opens the dispatch study",
              not at.exception and any(w.key == "gd_values" for w in at.segmented_control))


if __name__ == "__main__":
    main()
    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: " + "; ".join(FAILS))
    sys.exit(1 if FAILS else 0)
