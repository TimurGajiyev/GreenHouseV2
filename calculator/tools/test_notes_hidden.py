"""The explanatory notes under the inputs are hidden, not removed -- checked from outside.

    python calculator/tools/test_notes_hidden.py

The dispatch page used to carry a paragraph under almost every input: what the
Tailscale app's values are, what the load and units sections mean, where the
passport values come from, each unit's cost of running, the battery and rules
lines, how the year is solved. They are hidden behind ``SHOW_NOTES``:

  A. both value sets, before and after a solve: none of those notes is drawn,
     and the page raises nothing;
  B. what stays: the one-line readouts of numbers (the load's hours and kWh, the
     hours each engine was down), a warning that a service row is half filled
     in, and the way the year is solved, named in four words, with what it does
     and gets wrong as the label's help;
  C. that help is the corrected note: each day picks its battery charge afresh at
     midnight and the battery's saving reads 3-7 % high on our values -- not the
     "within about 1 %" it used to say; engine availability is said to be measured
     only where it is;
  D. SHOW_NOTES = True draws every note again, the corrected one included;
  E. the core is the core of a03fbd3, byte for byte.

Needs the measured table (real_data) and HiGHS; no API key, nothing online.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)
HERE = os.path.dirname(os.path.abspath(__file__))
CALC = os.path.dirname(HERE)
ROOT = os.path.dirname(CALC)
sys.path.insert(0, CALC)

from streamlit.testing.v1 import AppTest   # noqa: E402

import app_dispatch as D        # noqa: E402

FAILS: list[str] = []

# the opening words of every note the inventory found on the page (both value sets)
NOTES = {
    "the Tailscale app's values": "Every input below is the Tailscale app's",
    "the measured load's level": "A measured plant is its own demand",
    "no export": "No export and no demand charge",
    "what a unit row is": "Each unit runs at a fixed nameplate",
    "the passport values": "From the passports",
    "each unit's cost of running": "Cost of running, everything in",
    "the battery's size": "Size is fixed; each scenario below",
    "the rules picked": "picked. Fine-tune them below",
    "how the year is solved": "solved as a 24-hour cycle",
    "every day one by one": "solved one by one",
}
ZH_ONLY = {"the Tailscale app's values"}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


def _page():
    import app_dispatch
    app_dispatch.render()


def drawn(at) -> str:
    """Every caption and markdown body the page drew (not the help behind an icon)."""
    return " ".join([c.value for c in at.caption] + [str(m.value) for m in at.markdown])


def label(at):
    lab = [m for m in at.markdown if m.value == f"**{D.COVER_EVERY}**"]
    return lab[0] if len(lab) == 1 else None


def main() -> None:
    os.chdir(ROOT)
    check("the notes are hidden by default", D.SHOW_NOTES is False)
    at = AppTest.from_function(_page, default_timeout=900).run()
    check("the page opens", not at.exception, str([e.value for e in at.exception][:1]))

    print("\nA-C. notes hidden, readouts kept, the way named with its corrected note")
    for values in (D.VALUES_OURS, D.VALUES_ZH):
        tag = values[:4]
        at.segmented_control(key="gd_values").set_value(values).run()
        text = drawn(at)
        left = [k for k, v in NOTES.items() if v in text]
        check(f"{tag}: none of the {len(NOTES)} notes is drawn", not left, ", ".join(left))
        check(f"{tag}: the load's readout stays",
              " hours · " in text and " kWh · peak " in text)
        if values == D.VALUES_OURS:
            check(f"{tag}: the hours each engine was down stay", "Down in the logger" in text)
        lab = label(at)
        hlp = lab.proto.help if lab else ""
        check(f"{tag}: the way is named in four words, its note behind the label's help",
              lab is not None and len(hlp) > 200, hlp[:60])
        check(f"{tag}: the note says each day picks its battery charge afresh at midnight",
              "picks its battery charge afresh at midnight" in hlp)
        check(f"{tag}: and that the battery's saving reads 3-7 % high on our values, "
              "not within about 1 %",
              "3–7 % high" in hlp and "7.30–7.59" in hlp and "within about 1 %" not in hlp)
        measured = values == D.VALUES_OURS
        check(f"{tag}: engine availability is called measured only where it is",
              ("measured engine availability" in hlp) == measured)

        # a service row half filled in still gets its warning
        u = at.session_state["gd_units_df"].copy()
        u.loc[u.index[0], D.U_MINT] = 1500
        u.loc[u.index[0], D.U_MCOST] = 0
        at.session_state["gd_units_df"] = u
        if "gd_units" in at.session_state:
            del at.session_state["gd_units"]
        at.run()
        check(f"{tag}: a half-filled service row still gets its warning",
              "set both the interval and the cost" in drawn(at))
        u.loc[u.index[0], D.U_MINT] = 0
        at.session_state["gd_units_df"] = u
        if "gd_units" in at.session_state:
            del at.session_state["gd_units"]
        at.run()

        # after a solve too: the inputs keep their notes hidden, nothing raises
        ln = next(w for w in at.number_input if (w.key or "").startswith("gd_len_"))
        ln.set_value(24 * 4).run()
        at.button(key="gd_run").click().run(timeout=900)
        check(f"{tag}: a solve raises nothing", not at.exception and not at.error,
              str([e.value for e in [*at.exception, *at.error]][:1]))
        check(f"{tag}: and draws results", bool(at.session_state["gd_results"]))
        left = [k for k, v in NOTES.items() if v in drawn(at)]
        check(f"{tag}: after the solve the input notes are still hidden", not left, ", ".join(left))

    print("\nD. SHOW_NOTES = True draws them all again")
    D.SHOW_NOTES = True
    try:
        for values in (D.VALUES_OURS, D.VALUES_ZH):
            tag = values[:4]
            at2 = AppTest.from_function(_page, default_timeout=900).run()
            at2.segmented_control(key="gd_values").set_value(values).run()
            text = drawn(at2)
            want = {k: v for k, v in NOTES.items()
                    if k != "every day one by one" and (values == D.VALUES_ZH or k not in ZH_ONLY)}
            back = [k for k, v in want.items() if v in text]
            check(f"{tag}: every note is drawn again ({len(back)} of {len(want)})",
                  len(back) == len(want), ", ".join(sorted(set(want) - set(back))))
            check(f"{tag}: the way's note is the corrected one, drawn in full, no label",
                  "3–7 % high" in text and "within about 1 %" not in text
                  and label(at2) is None)
            check(f"{tag}: no exception with the notes on", not at2.exception)
    finally:
        D.SHOW_NOTES = False

    print("\nE. the core")
    same = subprocess.run(["git", "diff", "--quiet", "a03fbd3", "--", "calculator/reopt_core"],
                          cwd=ROOT).returncode == 0
    check("reopt_core is a03fbd3's, byte for byte", same)

    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: " + "; ".join(FAILS))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
