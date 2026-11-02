"""Independent checks of the "Compare two scenarios" pictures.

    python calculator/tools/test_compare_viz.py

Every figure the four charts and the matchup draw is recomputed here from the
solver's own output -- its objective, its hourly series, the inputs on the
page -- or from first principles (the discounted cash flows of a battery),
never through the page's helpers that built the chart, and compared with the
numbers the chart actually carries. The charts are read back from the page the
way Streamlit ships them to the browser: the Vega-Lite spec and its Arrow
datasets, found by the keyed container each chart sits in.

  A. the chart functions on made-up numbers: the bridge closes, the cash curve
     starts at the price and ends at the net present value, the ladder is
     sorted, the energy bars add up, every label inside a fill is legible.
  B. the page, both value sets (our study, the Tailscale app), every ordered
     pair of scenarios: no error, and every plotted number equal to the one
     recomputed here.
  C. the swap and a pair with no battery between them.

Needs the measured table (real_data) and HiGHS; no API key, nothing online.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import warnings

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pandas as pd            # noqa: E402
import pyarrow as pa           # noqa: E402

import app_dispatch as D       # noqa: E402
import profile_ui as P         # noqa: E402
import real_data as RD         # noqa: E402

FAILS: list[str] = []
N_OK = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global N_OK
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if ok:
        N_OK += 1
    else:
        FAILS.append(name)


def head(t: str) -> None:
    print(f"\n{t}")


def close(a: float, b: float, rel: float = 1e-9, absol: float = 1e-6) -> bool:
    return abs(a - b) <= max(absol, rel * max(abs(a), abs(b)))


# ------------------------------------------------------------ chart reading
def _layers(spec: dict) -> list[dict]:
    out = []
    for layer in spec.get("layer", [spec]):
        out += _layers(layer) if "layer" in layer else [layer]
    return out


def frames_of_chart(chart) -> list[tuple[str, pd.DataFrame]]:
    """(mark type, data) per layer of an Altair chart object."""
    d = chart.to_dict()
    sets = d.get("datasets", {})
    out = []
    for layer in _layers(d):
        name = (layer.get("data") or d.get("data") or {}).get("name")
        mark = layer["mark"]["type"] if isinstance(layer["mark"], dict) else layer["mark"]
        out.append((mark, pd.DataFrame(sets.get(name, []))))
    return out


def frames_on_page(at, key: str) -> list[tuple[str, pd.DataFrame]]:
    """(mark type, data) per layer of the chart in the keyed container ``key``,
    read from what Streamlit sends: the spec and its Arrow datasets."""
    def find(node):
        for ch in getattr(node, "children", {}).values():
            pid = getattr(getattr(ch, "proto", None), "id", "") or ""
            if isinstance(pid, str) and pid.endswith("-" + key):
                return ch
            got = find(ch)
            if got is not None:
                return got
        return None
    block = find(at._tree)
    if block is None:
        return []
    charts = [c for c in block.children.values() if getattr(c, "type", "") == "vega_lite_chart"]
    if not charts:
        return []
    p = charts[0].proto
    spec = json.loads(p.spec)
    sets = {s.name: pa.ipc.open_stream(s.data.data).read_all().to_pandas() for s in p.datasets}
    out = []
    for layer in _layers(spec):
        name = (layer.get("data") or spec.get("data") or {}).get("name")
        mark = layer["mark"]["type"] if isinstance(layer["mark"], dict) else layer["mark"]
        out.append((mark, sets.get(name, pd.DataFrame())))
    return out


def layer(frames, mark: str, nth: int = 0) -> pd.DataFrame:
    got = [f for m, f in frames if m == mark]
    return got[nth] if len(got) > nth else pd.DataFrame()


# --------------------------------------------- first principles: the money
def cash_curve(saving: float, *, capex: float, years: int, esc: float, disc: float,
               om_fraction: float, replace_year: int, replace_fraction: float) -> list[float]:
    """Cumulative discounted cash of a battery bought for ``capex``: year 0 the
    price paid, each year after its saving less its O&M -- both escalated from
    year one, REopt's convention -- less the replacement in its year."""
    om = om_fraction * capex
    rep = replace_fraction * capex if 0 < replace_year < years else 0.0
    cum, run = [-capex], -capex
    for y in range(1, years + 1):
        flow = (saving - om) * (1 + esc) ** y - (rep if y == replace_year else 0.0)
        run += flow / (1 + disc) ** y
        cum.append(run)
    return cum


def first_above(cum: list[float]) -> float | None:
    """The year from which ``cum`` stays at or above zero, interpolated."""
    if cum[-1] < 0:
        return None
    y = len(cum) - 1
    while y > 0 and cum[y - 1] >= 0:
        y -= 1
    if y == 0:
        return 0.0
    a, b = cum[y - 1], cum[y]
    return (y - 1) + (-a / (b - a) if b != a else 0.0)


# ---------------------------------------------------------------- A. units
def a_units() -> None:
    head("A. the chart functions on made-up numbers")
    steps = [{"label": "Generation", "a": 100.0e6, "b": 103.0e6},
             {"label": "Grid purchase", "a": 80.0e6, "b": 67.0e6},
             {"label": "Starts", "a": 10.0e6, "b": 11.9e6},
             {"label": "Battery wear", "a": 0.0, "b": 0.3e6}]
    a_tot = sum(s["a"] for s in steps)
    b_tot = sum(s["b"] for s in steps)
    fr = frames_of_chart(P.cost_bridge_chart({"letter": "A", "total": a_tot}, steps,
                                             {"letter": "B", "total": b_tot}, "₸"))
    bars = layer(fr, "bar")
    chain = all(close(bars.y0.iloc[i + 1], bars.y1.iloc[i]) for i in range(len(steps) - 1))
    check("bridge: each part starts where the last one ended", chain)
    check("bridge: the last part lands where the end bar ends",
          close(bars.y1.iloc[len(steps) - 1], bars.y1.iloc[-1]))
    check("bridge: the end bar runs from the zero line to B − A",
          close(bars.y0.iloc[-1], 0.0) and close(bars.y1.iloc[-1], b_tot - a_tot))
    check("bridge: a part B pays more on goes up, one it pays less on goes down",
          list(bars.kind) == ["up", "down", "up", "up", "end"], str(list(bars.kind)))
    check("bridge: the signed labels", list(bars.txt) ==
          ["+3.0 M ₸", "−13.0 M ₸", "+1.9 M ₸", "+0.3 M ₸", "−7.8 M ₸"], str(list(bars.txt)))
    links = layer(fr, "rule", 1)
    check("bridge: one dashed link between each two columns", len(links) == len(steps) + 1)

    cap, yrs = 391e6, 25
    lo = cash_curve(20e6, capex=cap, years=yrs, esc=0.034, disc=0.0624, om_fraction=0.025,
                    replace_year=10, replace_fraction=1.0)
    hi = cash_curve(60e6, capex=cap, years=yrs, esc=0.034, disc=0.0624, om_fraction=0.025,
                    replace_year=10, replace_fraction=1.0)
    p_hi, p_lo = first_above(hi), first_above(lo)
    fr = frames_of_chart(P.cash_curve_chart(list(range(yrs + 1)), lo, hi, "₸",
                                            payback=(p_hi, p_lo) if p_hi else None,
                                            replace_year=10, horizon=yrs))
    cols = layer(fr, "line")
    check("cash: one point a year, year 0 to 25", list(cols.year) == list(range(yrs + 1)))
    check("cash: the solid line is the low end, the dashed one the high end",
          all(close(a, b) for a, b in zip(cols.lo, lo)) and all(close(a, b) for a, b in zip(cols.hi, hi)))
    washes = [f for m, f in fr if m == "area"]
    neg, pos = washes[0], washes[1]
    check("cash: orange wash only below zero, green only above, meeting the line exactly",
          (neg.neg <= 0).all() and (pos.pos >= 0).all()
          and all(close(a + b, lo[int(x)]) for x, a, b in zip(neg.year, neg.neg, pos.pos)
                  if x == int(x)))
    xs = list(neg.year)
    crossings = [x for x in xs if x != int(x)]
    check("cash: the line's zero crossings are points of the wash, so no colour spills",
          all(any(abs(c - x) < 1e-9 for x in xs) for c in crossings) and len(xs) >= len(lo))
    texts = [f for m, f in fr if m == "text"]
    labs = " ".join(" ".join(map(str, t.get("lab", []))) for t in texts)
    check("cash: the replacement year is named", "replacement" in labs)
    check("cash: the payback is marked where the high end crosses zero",
          p_hi is not None and f"year {p_hi:,.1f}" in labs, labs[:120])
    check("cash: and the low end, which never crosses, is said to be never",
          p_lo is None and f"year {p_hi:,.1f} … never" in labs, labs[:120])

    rows = [{"label": "A", "role": "against", "total": 200e6, "tip": "x"},
            {"label": "B", "role": "scenario", "total": 192e6, "tip": "y"},
            {"label": "C", "role": "other", "total": 210e6, "tip": "z"},
            {"label": "Measured", "role": "measured", "total": 236e6, "tip": "w"}]
    fr = frames_of_chart(P.scenario_ladder_chart(rows, "₸", ref={"letter": "A", "total": 200e6}))
    dots = layer(fr, "circle")
    check("ladder: cheapest on top", list(dots.label) == ["B", "A", "C", "Measured"])
    check("ladder: each row's cost and its difference from A, in the column at the right",
          list(dots.txt) == ["192.0 M ₸", "200.0 M ₸", "210.0 M ₸", "236.0 M ₸"]
          and list(dots.dtxt) == ["−8.0 M ₸", "—", "+10.0 M ₸", "+36.0 M ₸"],
          f"{list(dots.txt)} {list(dots.dtxt)}")

    src = [("U1", P.unit_color(0)), ("U2", P.unit_color(1)), ("Grid", P.GRID_COLOR)]
    mix = [{"label": "B", "parts": {"U1": 4e6, "U2": 1e6, "Grid": 5e6}},
           {"label": "A", "parts": {"U1": 3e6, "U2": 0.0, "Grid": 7e6}}]
    fr = frames_of_chart(P.energy_mix_chart(mix, src))
    seg = layer(fr, "bar")
    by = seg.groupby("label").apply(lambda g: (g.x1 - g.x0).sum(), include_groups=False)
    check("energy: each bar is the sum of its sources, in MWh",
          close(by["B"], 10e3) and close(by["A"], 10e3), str(dict(by)))
    check("energy: a source at zero draws nothing", not ((seg.label == "A") & (seg.src == "U2")).any())
    check("energy: blocks laid end to end, no overlap", all(
        close(g.x0.iloc[i + 1], g.x1.iloc[i]) for _, g in seg.groupby("label")
        for i in range(len(g) - 1)))

    def contrast(a: str, b: str) -> float:
        def lum(h):
            c = [int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
            return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        la, lb = sorted((lum(a), lum(b)), reverse=True)
        return (la + 0.05) / (lb + 0.05)
    worst = min(contrast(P._ink_on(c), c) for c in [*P.GEN, P.GRID_COLOR, P.CEILING])
    check("energy: a share printed inside a block is legible on every source colour",
          worst >= 3.0, f"worst contrast {worst:.2f}:1")

    loud = []
    for name, ch in [("bridge", P.cost_bridge_chart({"letter": "A", "total": a_tot}, steps,
                                                    {"letter": "B", "total": b_tot}, "₸")),
                     ("cash", P.cash_curve_chart(list(range(yrs + 1)), lo, hi, "₸",
                                                 payback=(p_hi, p_lo), replace_year=10,
                                                 horizon=yrs)),
                     ("ladder", P.scenario_ladder_chart(rows, "₸",
                                                        ref={"letter": "A", "total": 200e6})),
                     ("energy", P.energy_mix_chart(mix, src))]:
        for lyr in _layers(ch.to_dict()):
            m = lyr["mark"] if isinstance(lyr["mark"], dict) else {"type": lyr["mark"]}
            if "tooltip" not in lyr.get("encoding", {}) and m.get("tooltip") is not False:
                loud.append(f"{name}:{m['type']}")
    check("hover: only the layers that say what to show answer the pointer "
          "(Streamlit turns tooltips on for every mark)", not loud, ", ".join(loud))

    html = P.matchup_html(
        {"letter": "B", "role": "scenario", "name": "x", "chips": ["battery", ("no", "dim")],
         "key": "k", "fig": "1", "mini": "m"},
        {"head": "B against A", "delta": ("−7.8 M ₸", "ghp-pos"), "under": "u", "says": "s"},
        {"letter": "A", "role": "against", "name": "y", "chips": [], "key": "k", "fig": "2"})
    check("matchup: both badges in their role's colour and the difference between them",
          'ghp-badge-scenario">B<' in html and 'ghp-badge-against">A<' in html
          and 'ghp-vs-delta ghp-pos">−7.8 M ₸<' in html)
    check("matchup: no stray tag in the stylesheet (st.html drops it all)",
          "<" not in P._CSS.split("<style>", 1)[1].rsplit("</style>", 1)[0])


# ----------------------------------------------------------------- B. page
def _page() -> None:
    import app_dispatch
    app_dispatch.render()


def _independent(out: dict, r: dict) -> dict:
    """A run's figures from the solver's output and the page's inputs only."""
    res, units = r["res"], out["units"]
    ser = res["series"]
    price = out["price"]
    start_of = {str(u[D.U_NAME]): float(u[D.U_START] or 0.0) for _, u in units.iterrows()}
    rows = res["sizes"].get("fueltech_units") or []
    return {
        "total": res["objective_lifecycle_cost"],
        "grid_cost": sum(p * g for p, g in zip(price, ser["grid_kw"])),
        "start_cost": sum((u.get("starts") or 0) * start_of.get(u["name"], 0.0) for u in rows),
        "grid_kwh": sum(ser["grid_kw"]),
        "unit_kwh": {u["name"]: float(u["energy_kwh"]) for u in rows},
    }


def _pair_checks(at, out: dict, run: dict, base: dict, tag: str) -> None:
    hours = out["hours"]
    ir, ib = _independent(out, run), _independent(out, base)
    rs, bs = D._short(run["name"]), D._short(base["name"])
    html = " ".join(h.proto.body for h in at.get("html"))
    check(f"{tag}: the matchup names the pair, each in its role",
          f'ghp-badge-scenario">{rs}<' in html and f'ghp-badge-against">{bs}<' in html)

    fr = frames_on_page(at, "gd_bridge_chart")
    bars = layer(fr, "bar")
    check(f"{tag}: the bridge is on the page", len(bars) >= 2)
    if len(bars) >= 2:
        endb = bars.iloc[-1]
        check(f"{tag}: the bridge ends at the solver's own difference of the two objectives",
              close(endb.y1, ir["total"] - ib["total"], 1e-6, 1.0),
              f"{endb.y1:,.0f} against {ir['total'] - ib['total']:,.0f}")
        steps = bars.iloc[:-1]
        check(f"{tag}: and its parts add up to it",
              close(steps.y1.iloc[-1], endb.y1, 1e-9, 1e-3))
        grid = steps[steps.part == "Grid purchase"]
        if len(grid):
            got = float(grid.y1.iloc[0] - grid.y0.iloc[0])
            check(f"{tag}: the grid part is Σ price × grid hour by hour, both sides",
                  close(got, ir["grid_cost"] - ib["grid_cost"], 1e-9, 1e-3),
                  f"{got:,.0f} against {ir['grid_cost'] - ib['grid_cost']:,.0f}")
        sts = steps[steps.part == "Starts"]
        if len(sts):
            got = float(sts.y1.iloc[0] - sts.y0.iloc[0])
            check(f"{tag}: the starts part is each unit's starts × its start cost",
                  close(got, ir["start_cost"] - ib["start_cost"], 1e-9, 1e-3),
                  f"{got:,.0f} against {ir['start_cost'] - ib['start_cost']:,.0f}")

    dots = layer(frames_on_page(at, "gd_ladder_chart"), "circle")
    check(f"{tag}: the ladder has every scenario, and the logger's operation where measured",
          len(dots) == len(out["runs"]) + (1 if out.get("measured") else 0), str(len(dots)))
    if len(dots):
        check(f"{tag}: cheapest on top", list(dots.v) == sorted(dots.v))
        want = {rr["name"]: rr["res"]["objective_lifecycle_cost"] for rr in out["runs"]}
        got = {lab.split("  · ")[0]: v for lab, v in zip(dots.label, dots.v)}
        check(f"{tag}: each dot is that scenario's objective",
              all(close(got[nm], v, 1e-6, 1.0) for nm, v in want.items()))
        check(f"{tag}: the pair is marked: the scenario and what it is set against",
              set(dots[dots.role == "scenario"].label) == {run["name"] + "  · scenario"}
              and set(dots[dots.role == "against"].label) == {base["name"] + "  · against"})

    seg = layer(frames_on_page(at, "gd_mix_chart"), "bar")
    if len(seg):
        ok = True
        for rr in out["runs"]:
            ind = _independent(out, rr)
            mine = seg[seg.label.str.split("  · ").str[0] == rr["name"]]
            for nm, kwh in ind["unit_kwh"].items():
                got = ((mine.src == nm) * (mine.x1 - mine.x0)).sum() * 1e3
                ok &= close(got, kwh, 1e-9, 1e-3) if kwh > 0 else not (mine.src == nm).any()
            g = ((mine.src == "Grid") * (mine.x1 - mine.x0)).sum() * 1e3
            ok &= close(g, ind["grid_kwh"], 1e-9, 1e-3)
        check(f"{tag}: every energy block is the solver's own kWh, engine by engine and grid", ok)
        meas = out.get("measured")
        if meas and len(meas.get("gpu") or []) == hours:
            mine = seg[seg.label == "Measured (logger)"]
            buy = meas.get("buy") or [max(0.0, g) for g in meas["grid"]]
            tot = (mine.x1 - mine.x0).sum() * 1e3
            check(f"{tag}: the logger's bar is its engines plus what it bought",
                  close(tot, sum(meas["gpu"]) + sum(buy), 1e-9, 1e-3),
                  f"{tot:,.0f} against {sum(meas['gpu']) + sum(buy):,.0f}")
    else:
        check(f"{tag}: the energy chart is on the page", False)

    cols = layer(frames_on_page(at, "gd_cash_chart"), "line")
    if not len(cols):
        check(f"{tag}: the cash chart is on the page", False)
        return
    life = out.get("life") or {}
    years = int(life.get("years", 25))
    esc, disc = float(life.get("escalation", 0.0)), float(life.get("discount", 0.0))
    bat = out["bat"]
    between = run["battery"] != base["battery"]
    if between:
        buyer, other = (run, base) if run["battery"] else (base, run)
        s_lo, s_hi = D._gain_year(buyer, other, out, hours)      # the buyer's saving a year
        check(f"{tag}: the yearly saving the line is built on is not zero",
              abs(s_lo) + abs(s_hi) > 1.0, f"{s_lo:,.0f} … {s_hi:,.0f}")
        terms = dict(capex=float(bat.get("capex", 0.0)), years=years, esc=esc, disc=disc,
                     om_fraction=float(bat.get("om_fraction", 0.0)),
                     replace_year=int(bat.get("replace_year", 0) or 0),
                     replace_fraction=float(bat.get("replace_fraction", 0.0)))
        lo, hi = cash_curve(s_lo, **terms), cash_curve(s_hi, **terms)
        check(f"{tag}: year 0 is minus the battery's price",
              close(cols.lo.iloc[0], -terms["capex"], 1e-12, 1.0), f"{cols.lo.iloc[0]:,.0f}")
        check(f"{tag}: every year's point is the discounted cash recomputed here",
              len(cols) == years + 1 and all(close(a, b, 1e-9, 1.0) for a, b in zip(cols.lo, lo))
              and all(close(a, b, 1e-9, 1.0) for a, b in zip(cols.hi, hi)),
              f"last {cols.lo.iloc[-1]:,.0f} against {lo[-1]:,.0f}")
        n = D._pair_numbers(buyer, other, out, hours)
        # the verdict's NPV uses REopt's present-worth factor, which REopt rounds
        # to five decimals (utils.jl:11); the line is the exact year-by-year sum.
        # They part by at most half a unit of that fifth decimal of the net flow.
        slack = 0.5e-5 * (max(abs(s_lo), abs(s_hi)) + terms["om_fraction"] * terms["capex"]) + 1.0
        ends = (min(cols.lo.iloc[-1], cols.hi.iloc[-1]), max(cols.lo.iloc[-1], cols.hi.iloc[-1]))
        check(f"{tag}: and the line ends on the net present value the verdict states",
              abs(ends[0] - n["net"][0]) <= slack and abs(ends[1] - n["net"][1]) <= slack,
              f"apart by {max(abs(ends[0] - n['net'][0]), abs(ends[1] - n['net'][1])):,.0f} "
              f"{out['currency']}, REopt's rounding allows {slack:,.0f}")
        texts = " ".join(" ".join(map(str, f.get("lab", []))) for m, f in
                         frames_on_page(at, "gd_cash_chart") if m == "text")
        p = first_above(hi)
        if p is None:
            check(f"{tag}: never paying back is said on the chart",
                  f"does not pay back in {years} years" in texts, texts[:100])
        else:
            check(f"{tag}: the payback marked is the year the cash stays above zero",
                  f"year {p:,.1f}" in texts, f"{p:.2f} · {texts[:100]}")
    else:
        s_lo, s_hi = D._gain_year(run, base, out, hours)
        check(f"{tag}: the yearly saving the line is built on is not zero",
              abs(s_lo) + abs(s_hi) > 1.0, f"{s_lo:,.0f} … {s_hi:,.0f}")
        f = [((1 + esc) / (1 + disc)) ** y for y in range(1, years + 1)]
        want = [sum(f[:y]) * s_lo for y in range(1, years + 1)]
        check(f"{tag}: no battery between them -- the saving added up from year 1, nothing to repay",
              list(cols.year) == list(range(1, years + 1))
              and all(close(a, b, 1e-9, 1.0) for a, b in zip(cols.lo, want)),
              f"last {cols.lo.iloc[-1]:,.0f} against {want[-1]:,.0f}")


def b_page() -> None:
    head("B. the page, both value sets, every ordered pair")
    if not RD.available():
        print("  --  the measured table is not here")
        return
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_function(_page, default_timeout=120).run()
    check("the page opens", not at.exception, str([e.value for e in at.exception][:1]))
    for values in (D.VALUES_OURS, D.VALUES_ZH):
        print(f"\n  -- {values}")
        at.segmented_control(key="gd_values").set_value(values).run()
        ln = next(w for w in at.number_input if (w.key or "").startswith("gd_len_"))
        # his per-year figure (month_mean) drops a month with under a quarter of its
        # hours measured, so four days give him a year of zero: a month, then
        ln.set_value(96 if values == D.VALUES_OURS else 744).run()
        # every unbroken stretch is one window now, and a long one with a battery
        # may take the page's whole 600 s; these checks read the numbers back from
        # the solve, whatever its gap, so a minute per window serves them
        at.number_input(key="gd_tlim").set_value(60).run()
        at.button(key="gd_run").click().run(timeout=1800)
        check(f"{values}: a solve raises no error", not at.exception and not at.error,
              str([e.value for e in [*at.exception, *at.error]][:1]))
        out = at.session_state["gd_results"]
        runs = out["runs"]
        check(f"{values}: the accounts the charts use add up to the objectives",
              all(close(r["acc"]["total"], r["res"]["objective_lifecycle_cost"], 1e-6, 1.0)
                  for r in runs))
        by = {r["name"]: r for r in runs}
        for a in by:
            at.segmented_control(key="gd_pick").set_value(a).run()
            for b in by:
                if b == a:
                    continue
                at.segmented_control(key=f"gd_vs_{a}").set_value(b).run()
                tag = f"{values[:4]} {D._short(a)} vs {D._short(b)}"
                check(f"{tag}: no error", not at.exception,
                      str([e.value for e in at.exception][:1]))
                if not at.exception:
                    _pair_checks(at, out, by[a], by[b], tag)

        # C. the swap: the other side becomes the scenario and every picture follows
        a = at.session_state["gd_pick"]
        b = at.session_state[f"gd_vs_{a}"]
        at.button(key="gd_swap").click().run()
        check(f"{values}: the swap", at.session_state["gd_pick"] == b
              and at.session_state[f"gd_vs_{b}"] == a and not at.exception)
        html = " ".join(h.proto.body for h in at.get("html"))
        check(f"{values}: after it the bridge starts from the old scenario",
              f"From {D._short(a)}&#x27;s cost to {D._short(b)}&#x27;s" in html
              or f"From {D._short(a)}'s cost to {D._short(b)}'s" in html)


if __name__ == "__main__":
    a_units()
    b_page()
    print(f"\n{N_OK} passed, {len(FAILS)} failed")
    for f in FAILS:
        print("  FAIL", f)
    sys.exit(1 if FAILS else 0)
