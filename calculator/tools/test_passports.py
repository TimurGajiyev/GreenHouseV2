"""The units presets against the engines' own documents (passports.py).

Checks that what the dispatch study offers as a measured plant's engines is
what docs/equipment says, figure for figure, and that the straight fuel line
the model draws through the 100 % and 50 % points (REopt's
fuel_slope_and_intercept, utils.jl:645) lands on each passport's 75 % point.
No solver, no data table needed for the first half; the presets are checked
for whichever plants are on disk.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

logging.disable(logging.WARNING)          # st.cache_data outside Streamlit warns

import app_dispatch as D
import passports as PP
import real_data as RD

FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  {'OK' if cond else 'XX'}  {msg}")
    if not cond:
        FAILURES.append(msg)


def main() -> None:
    print("passports, each against itself")
    for k, p in PP.PASSPORTS.items():
        kw, e, f = p["kw"], p["eff"], p["fuel_kw"]
        # the stated efficiency is the stated output over the stated fuel, to rounding
        check(abs(100 * kw / f[100] - e[100]) < 0.05,
              f"{k}: {kw:,.0f} kW / {f[100]:,.0f} kW fuel = {100 * kw / f[100]:.2f} %, "
              f"stated {e[100]} %")
        f100, f50 = kw / (e[100] / 100), 0.5 * kw / (e[50] / 100)
        f75 = f50 + (f100 - f50) / (0.5 * kw) * 0.25 * kw
        dev = 100 * (f75 / f[75] - 1)
        check(abs(dev) < 1.0, f"{k}: the 100–50 % fuel line at 75 % load, {f75:,.1f} kW, "
                              f"is {dev:+.2f} % from the passport's {f[75]:,.0f} kW")
        check(p["min_load"] == 50.0, f"{k}: minimum load {p['min_load']:.0f} %")

    print("\nOEM lookup on the study page")
    for k in PP.PASSPORTS:
        check(D.OEM.get(PP.unit(k), "").startswith(PP.PASSPORTS[k]["machine"]),
              f"{k}: {PP.unit(k)} names its document")

    print("\nmeasured plants' presets")
    if not RD.available():
        print("  --  the measured table is not on disk; presets skipped")
    for site in RD.available():
        u = D.default_units(D.REAL_PRESET + site)
        for _, row in u.iterrows():
            key = (float(row[D.U_KW]), float(row[D.U_EFF100]), float(row[D.U_EFF50]))
            check(key in D.OEM and float(row[D.U_MIN]) == 50.0,
                  f"{row[D.U_NAME]}: {key[0]:,.0f} kW, {key[1]} / {key[2]} %, "
                  f"min {row[D.U_MIN]:.0f} % = passport")
        cols = list(u.columns)
        check(cols[:5] == [D.U_NAME, D.U_KW, D.U_EFF100, D.U_EFF50, D.U_MIN],
              f"{site}: the passport columns come first")

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print("  - " + f)
        sys.exit(1)
    print("all passport checks passed")


if __name__ == "__main__":
    main()
