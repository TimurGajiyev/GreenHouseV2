"""Compile the dispatch chart for every shape the results block can hand it.

`test_profile_render.py` covers the same ground but has to solve three MILPs
first, so it is minutes per run and no help while the design layer is being
worked on. This one takes a second: it builds the chart directly for the shapes
that change its structure -- day and week, with and without the saving veil, a
fleet ceiling, no units at all, PV, batteries -- and checks the spec that comes
out has the layers the hover depends on.

What it asserts is the contract between `app_periods` and `profile_ui`:

  * the pointer-catching layer is last, carries the whole hour's tooltip, and
    declares the hover parameter
  * the wash is first, so the cursor sits behind the marks
  * the hour's label reaches the panel as the field `title`, which is what
    vega-tooltip promotes to a heading
  * every hour offers the same rows in the same order, because the row colours
    are addressed by position
  * the emitted colour sheet has one rule per row, in that order
"""

from __future__ import annotations

import os
import re
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import profile_ui as P

FAILURES: list[str] = []
CSS: list[str] = []
P.st = types.SimpleNamespace(html=lambda body, **k: CSS.append(str(body)))


def check(cond: bool, where: str, msg: str) -> None:
    if not cond:
        FAILURES.append(f"{where}: {msg}")


def shape(name: str, *, n=24, units=2, pv=False, banks=True, veil=True,
          ceiling=True, week=False):
    hours = list(range(1, n + 1))
    labels = [f"1 January · {h - 1:02d}:00" for h in hours]
    load = [1_400.0 + 40.0 * (h % 13) for h in hours]
    stack = [(f"Engine {j + 1}", P.unit_color(j), [500.0 + 30.0 * j] * n)
             for j in range(units)]
    if pv:
        stack.append(("PV", P.PV_COLOR, [120.0 if 6 < h < 19 else 0.0 for h in hours]))
    stack.append(("Grid", P.GRID_COLOR, [max(0.0, load[i] - 1_200.0) for i in range(n)]))

    ch = [180.0 if h < 8 else 0.0 for h in hours] if banks else [0.0] * n
    dis = [0.0 if h < 8 else 140.0 for h in hours] if banks else [0.0] * n

    detail = []
    for i, h in enumerate(hours):
        d = [("Site load", f"{load[i]:,.0f} kW", P.INK)]
        for j in range(units):
            d.append((f"  Engine {j + 1}", f"{500 + 30 * j:,.0f} kW · 35%",
                      P.unit_color(j)))
        if pv:
            d.append(("PV", "120 kW", P.PV_COLOR))
        if banks:
            d.append(("Battery charge", f"+{ch[i]:,.0f} kW" if ch[i] else "—", P.CHARGE))
            d.append(("Battery discharge", f"−{dis[i]:,.0f} kW" if dis[i] else "—",
                      P.DISCHARGE))
            d.append(("State of charge", "61.0%", P.MUTED))
        d.append(("Grid purchase", "300 kW", P.GRID_COLOR))
        if veil:
            d.append(("Saving, energy", "+1,234 ₸", P.INK))
        detail.append(d)

    CSS.clear()
    chart = P.dispatch_chart(
        hours, labels, stack, load, ch, dis,
        ceiling_kw=(2_267.0 if ceiling else None), week=week, detail=detail,
        veil=([60.0 if i % 3 else -40.0 for i in range(n)] if veil else None))
    spec = chart.to_dict()

    layers = spec["layer"]
    catcher, wash = layers[-1], layers[0]
    check(catcher["mark"]["type"] == "rect" and catcher["mark"]["fillOpacity"] == 0.0,
          name, "the top layer is not the transparent catcher")
    check("tooltip" in catcher["encoding"], name, "the catcher carries no tooltip")
    check(wash["mark"]["type"] == "rect" and "tooltip" not in wash["encoding"],
          name, "the bottom layer is not the cursor wash")

    params = [p["name"] for p in spec.get("params", [])]
    check("ghhover" in params, name, f"hover parameter missing, params={params}")

    tips = catcher["encoding"]["tooltip"]
    check(tips[0].get("title") == "title", name, "the hour label is not the panel heading")
    got = [t.get("title") for t in tips[1:]]
    want = [lab for lab, _, _ in detail[0]]
    check(got == want, name, f"panel rows {got} != {want}")

    # every hour offers the same rows, in the same order
    check(all([lab for lab, _, _ in d] == want for d in detail),
          name, "the row set is not identical across hours")

    # one colour rule per row, in that order
    check(len(CSS) == 1, name, f"expected one colour sheet, got {len(CSS)}")
    rules = re.findall(r"tr:nth-child\((\d+)\) td\.value\{color:(#[0-9A-Fa-f]{6});\}", CSS[0])
    check([int(i) for i, _ in rules] == list(range(1, len(want) + 1)),
          name, "colour rules are not one per row in order")
    check([c for _, c in rules] == [col for _, _, col in detail[0]],
          name, "colour rules do not match the row colours")

    # the axes survived the layering: exactly the reference's pair
    check(catcher["encoding"]["x"]["axis"]["domain"] is True, name, "hours lost their rule")
    check(catcher["encoding"]["y"]["axis"]["domain"] is False, name, "kW grew a rule")
    check(catcher["encoding"]["y"]["axis"]["gridDash"] == [2, 4], name, "grid is not dashed")
    check(spec["height"] == (420 if week else 380), name,
          f"height {spec['height']} is not the reference's")

    print(f"  {'XX' if FAILURES and FAILURES[-1].startswith(name) else 'OK'}  "
          f"{name:<40} {len(layers)} layers, {len(want)} panel rows")


def main() -> None:
    shape("day, 2 engines + battery")
    shape("day, no veil", veil=False)
    shape("day, no ceiling", ceiling=False)
    shape("day, no battery", banks=False)
    shape("day, PV in the stack", pv=True)
    shape("day, one engine", units=1)
    shape("day, grid only", units=0, banks=False, veil=False, ceiling=False)
    shape("week, 168 hours", n=168, week=True)
    shape("week, no battery", n=168, week=True, banks=False)

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print("  - " + f)
        sys.exit(1)
    print("all dispatch-chart checks passed")


if __name__ == "__main__":
    main()
