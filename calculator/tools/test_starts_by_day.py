"""The per-unit, per-day starts breakdown in ``app_periods``.

No network, no solver, no browser. The two aggregations are pure functions, and
the render block is exercised by capturing what it hands to ``profile_ui`` --
so the head, the body, the footer and the caption are all checked without a
Streamlit runtime.

What this is guarding: the unit table totals each unit over the whole horizon,
and the summary table splits by day/week/horizon but sums the fleet. The cut
this section adds -- THIS unit on THAT day -- had no test and no reader before,
even though the core has always computed it.

    python tools/test_starts_by_day.py
"""

from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import app_periods as A
import profile_ui as P

FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'OK' if ok else 'XX'}  {name:<58} {detail}")
    if not ok:
        FAIL.append(name)
    return ok


def eq(name: str, got, want) -> bool:
    return check(name, got == want, f"{got!r}" if got == want else f"{got!r} != {want!r}")


# ---------------------------------------------------------------- capture
class Captured:
    """What _starts_section drew, instead of drawing it."""

    def __init__(self) -> None:
        self.tables: list[tuple] = []
        self.charts: list = []
        self.legends: list = []
        self.subs: list[str] = []
        self.captions: list[str] = []


def run_section(res: dict) -> Captured:
    """Call the real render block with profile_ui and streamlit stubbed out."""
    cap = Captured()
    st = A.st
    saved = (P.table, P.legend, P.sub, st.altair_chart, st.caption, P.starts_chart)
    P.table = lambda head, rows, foot=None, **kw: cap.tables.append((head, rows, foot))
    P.legend = lambda items: cap.legends.append(items)
    P.sub = lambda text: cap.subs.append(text)
    st.altair_chart = lambda ch, **kw: cap.charts.append(ch)
    st.caption = lambda text, **kw: cap.captions.append(text)
    try:
        series = res["series"]
        A._starts_section(A._shape(res), series, A._idx(A.horizon(series)), res)
    finally:
        (P.table, P.legend, P.sub, st.altair_chart, st.caption, P.starts_chart) = saved
    return cap


def make_res(per_unit_by_day: list[list[int]] | None, n_days: int,
             names: tuple[str, ...] = ("Jenbacher", "TEDOM"),
             typical: dict | None = None) -> dict:
    """A result shaped like the model's, carrying only what this section reads."""
    H = n_days * 24
    units = []
    for i, nm in enumerate(names):
        by_day = None if per_unit_by_day is None else per_unit_by_day[i]
        units.append({
            "index": i, "name": nm, "kind": "CHP", "size_kw": 1000.0 + i,
            "energy_kwh": 1.0, "capacity_factor": 0.5, "running_hours": 10,
            "fuel_units": 1.0, "fuel_unit_name": "MMBtu", "spill_kwh": 0.0,
            "starts": (None if by_day is None else sum(by_day)),
            "starts_by_day": by_day,
        })
    res = {
        "sizes": {"fueltech_units": units, "storage_units": [], "pv_kw": 0.0},
        "series": {"load_kw": [1.0] * H, "fueltech_unit_kw": {nm: [1.0] * H for nm in names},
                   "unserved_kw": [0.0] * H, "export_kw": [0.0] * H},
    }
    if typical is not None:
        res["typical"] = typical
    return res


# ===========================================================================
print("A. starts_matrix -- the per-unit, per-day counts")
# ===========================================================================
u_tracked = make_res([[1, 0, 2], [0, 1, 0]], 3)["sizes"]["fueltech_units"]
eq("a tracked fleet gives one row per unit",
   A.starts_matrix(u_tracked, 3), [[1, 0, 2], [0, 1, 0]])
u_none = make_res(None, 3)["sizes"]["fueltech_units"]
check("no commitment anywhere -> None, not a grid of zeros",
      A.starts_matrix(u_none, 3) is None)

# a horizon that does not divide into whole days still lines up
eq("a short list is padded to the day count",
   A.starts_matrix(make_res([[1], [2]], 3)["sizes"]["fueltech_units"], 3),
   [[1, 0, 0], [2, 0, 0]])
eq("a long list is trimmed to the day count",
   A.starts_matrix([{"name": "x", "starts_by_day": [1, 1, 1, 1]}], 2), [[1, 1]])
eq("None entries count as zero",
   A.starts_matrix([{"name": "x", "starts_by_day": [1, None, 2]}], 3), [[1, 0, 2]])

# one unit tracked, one not -- the untracked one must not vanish or misalign
mixed = [{"name": "a", "starts_by_day": [1, 2]}, {"name": "b", "starts_by_day": None}]
eq("a unit without commitment becomes a zero row, keeping the row order",
   A.starts_matrix(mixed, 2), [[1, 2], [0, 0]])
print()

# ===========================================================================
print("B. starts_by_weekday -- the fold used beyond a month")
# ===========================================================================
idx = A._idx(14 * 24)
eq("the shared index starts on a Sunday (2017-01-01)", idx[0].weekday(), 6)
# day 0 Sun, 1 Mon, 2 Tue ... put one start on each of the first 7 days
wk = A.starts_by_weekday([[1, 1, 1, 1, 1, 1, 1] + [0] * 7], idx)
eq("seven consecutive days land one start on each weekday", wk[0], [1] * 7)
# two Tuesdays: day 2 and day 9
wk2 = A.starts_by_weekday([[0, 0, 3, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0]], idx)
eq("both Tuesdays fold onto Tuesday", wk2[0][1], 7)
check("and nothing leaks onto the other weekdays",
      sum(wk2[0]) == 7 and wk2[0][1] == 7, f"{wk2[0]}")
eq("the fold preserves the fleet total",
   sum(sum(r) for r in A.starts_by_weekday([[1, 2, 3], [4, 5, 6]], idx)), 21)
eq("one row per unit", len(A.starts_by_weekday([[1], [2], [3]], idx)), 3)
# days beyond the index are dropped rather than crashing
# a 3-day index covers Sun, Mon, Tue (2017-01-01 is a Sunday); days 3..19 have
# no hour in the index and are dropped rather than raising
eq("a day past the end of the index is ignored, not an IndexError",
   A.starts_by_weekday([[1] * 20], A._idx(3 * 24))[0], [1, 1, 0, 0, 0, 0, 1])
print()

# ===========================================================================
print("C. the day table -- a horizon of a month or less")
# ===========================================================================
week = make_res([[1, 0, 0, 2, 0, 1, 0], [0, 1, 1, 0, 0, 0, 3]], 7)
cap = run_section(week)
eq("the section is titled", cap.subs, ["Starts by unit and day"])
eq("one chart is drawn", len(cap.charts), 1)
eq("the legend names both units", [lab for lab, _ in cap.legends[0]],
   ["Jenbacher", "TEDOM"])
check("the legend colours are the shared unit palette",
      [c for _, c in cap.legends[0]] == [P.unit_color(0), P.unit_color(1)])
eq("one table is drawn", len(cap.tables), 1)

head, body, foot = cap.tables[0]
eq("head is UNIT + one column per day + TOTAL", len(head), 1 + 7 + 1)
eq("first and last column labels", (head[0], head[-1]), ("UNIT", "TOTAL"))
eq("day columns carry the weekday, starting Sunday", head[1:4], ["SUN 1", "MON 2", "TUE 3"])
eq("one body row per unit", len(body), 2)
eq("the row is named for its unit", [r[0] for r in body], ["Jenbacher", "TEDOM"])


def cell(c):
    return c[0] if isinstance(c, tuple) else c


eq("a day with no start reads as a dash, not 0",
   [cell(c) for c in body[0][1:8]], ["1", "—", "—", "2", "—", "1", "—"])
eq("each unit's TOTAL is its own row sum", [cell(r[-1]) for r in body], ["4", "5"])
eq("the Fleet footer sums each day column",
   [cell(c) for c in foot[1:8]], ["1", "1", "1", "2", "0", "1", "3"])
eq("the Fleet total is the fleet's starts", cell(foot[-1]), "9")
eq("the footer is labelled", foot[0], "Fleet")
check("the section total matches the unit table's own per-unit totals",
      sum(u["starts"] for u in week["sizes"]["fueltech_units"]) == 9)
check("the caption states the horizon and the cyclic rule",
      "7 days" in cap.captions[0] and "cyclic" in cap.captions[0],
      cap.captions[0][:60] + "...")
check("a month still uses day columns", len(run_section(
    make_res([[1] * 31, [0] * 31], 31)).tables[0][0]) == 1 + 31 + 1)
print()

# ===========================================================================
print("D. the weekday table -- a horizon longer than a month")
# ===========================================================================
# one start every Tuesday of a 364-day horizon, none for TEDOM but day 5
year_j = [1 if A._idx(364 * 24)[d * 24].weekday() == 1 else 0 for d in range(364)]
year_t = [0] * 364
year_t[5] = 2
yr = make_res([year_j, year_t], 364)
cap = run_section(yr)
eq("still one chart and one table", (len(cap.charts), len(cap.tables)), (1, 1))
head, body, foot = cap.tables[0]
eq("head is UNIT + 7 weekdays + TOTAL, PER DAY, BUSIEST DAY", len(head), 1 + 7 + 3)
eq("the weekday labels", head[1:8], ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"])
eq("every Jenbacher start is a Tuesday", [cell(c) for c in body[0][1:8]],
   ["—", "52", "—", "—", "—", "—", "—"])
eq("Jenbacher's total", cell(body[0][-3]), "52")
eq("starts per day is the total over the day count", cell(body[0][-2]),
   f"{52 / 364:,.2f}")
check("the busiest day names a date", "January" in cell(body[0][-1]),
      cell(body[0][-1]))
eq("TEDOM's two starts fall on one day", cell(body[1][-3]), "2")
eq("and its busiest day carries both", cell(body[1][-1]).split(" · ")[0], "2")
eq("a unit with no starts at all shows a dash for the busiest day",
   cell(run_section(make_res([[0] * 364, [0] * 364], 364)).tables[0][1][0][-1]), "—")
eq("the fleet footer totals", cell(foot[-3]), "54")
check("the caption says it folded onto weekdays",
      "weekday" in cap.captions[0], cap.captions[0][:70] + "...")
print()

# ===========================================================================
print("E. when the section stays silent")
# ===========================================================================
eq("a single-day run draws nothing -- the unit total already IS the day",
   len(run_section(make_res([[3], [1]], 1)).tables), 0)
check("and no chart either", len(run_section(make_res([[3], [1]], 1)).charts) == 0)
eq("a run with no commitment draws nothing", len(run_section(make_res(None, 7)).tables), 0)
check("no section heading is emitted when there is nothing to show",
      run_section(make_res(None, 7)).subs == [])
print()

# ===========================================================================
print("F. the chart itself")
# ===========================================================================
mat = [[1, 0, 2, 0, 0, 1, 0], [0, 1, 0, 0, 0, 0, 3]]
ch = P.starts_chart(list(range(1, 8)),
                    [f"day {d}" for d in range(1, 8)],
                    [("Jenbacher", P.unit_color(0), mat[0]),
                     ("TEDOM", P.unit_color(1), mat[1])])
df = ch.layer[0].data
check("the chart is built without a Streamlit runtime", ch is not None)
# mat has 5 non-zero cells summing to 8 -- a zero day draws no bar at all
eq("only non-zero cells become bars", len(df), 5)
eq("the bars carry the fleet's starts", int(df["n"].sum()), 8)
eq("both units appear", sorted(df["src"].unique().tolist()), ["Jenbacher", "TEDOM"])
check("the stacking order follows the unit order",
      df[df["src"] == "Jenbacher"]["o"].max() < df[df["src"] == "TEDOM"]["o"].min())
check("a day label rides along for the tooltip", "day 1" in df["t"].tolist())
zero = P.starts_chart([1, 2], ["a", "b"], [("x", P.unit_color(0), [0, 0])])
check("an all-zero fleet still yields a drawable chart", zero is not None,
      f"{len(zero.layer[0].data)} row placeholder")
wide = P.starts_chart(list(range(1, 366)), [f"d{d}" for d in range(365)],
                      [("x", P.unit_color(0), [1] * 365)])
check("365 days build too, with thinned ticks", wide is not None)

# Two Vega traps this chart hit, both invisible in the spec and only findable by
# rendering it and reading the SVG back. Guarded here because the symptom is a
# silently wrong axis, not an error: the count axis came out labelled 0 and 2
# with no line at 1, which is where most of the bars end.
import json

spec = json.loads(ch.to_json())
yaxes = [l["encoding"]["y"].get("axis") for l in spec["layer"]]
check("every layer carries the same y axis, so the shared axis cannot be dropped",
      len(yaxes) > 1 and all(a == yaxes[0] for a in yaxes))
check("no layer sets axis=None, which would remove the axis from the chart",
      all(a is not None for a in yaxes))
eq('the count axis format is ",d" and never a bare "d" (a bare "d" makes Vega '
   "drop ticks out of an explicit values list)", yaxes[0]["format"], ",d")
vals = yaxes[0]["values"]
eq("the tick values are every whole number up to the tallest bar",
   vals, list(range(0, max(vals) + 1)))
eq("and the scale is pinned to them, so no tick falls outside the domain",
   spec["layer"][0]["encoding"]["y"]["scale"]["domain"], [0, max(vals)])
print()

# ===========================================================================
print("G. the clustered-year caveat")
# ===========================================================================
cap = run_section(make_res([[1] * 364, [0] * 364], 364,
                           typical={"k": 12, "starts_from_joins": 7}))
check("a typical-day year says so, with the join count",
      "typical days" in cap.captions[0] and "lower bound" in cap.captions[0]
      and "7 of 364" in cap.captions[0], cap.captions[0][-120:])
cap2 = run_section(make_res([[1] * 364, [0] * 364], 364))
check("a directly-solved year carries no such note",
      "typical days" not in cap2.captions[0])
print()

print("=" * 80)
if FAIL:
    print(f"{len(FAIL)} FAILED")
    for f in FAIL:
        print(f"  - {f}")
else:
    print("all checks passed")
print("=" * 80)
raise SystemExit(1 if FAIL else 0)
