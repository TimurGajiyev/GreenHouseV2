"""The units table: "Spread services" hidden and always on; "Variable O&M"
hidden; each unit's cost of running said under the table.

    python calculator/tools/test_units_table.py

The column is hidden, not removed (``SPREAD_ALWAYS_ON`` in app_dispatch.py):

  A. the model always gets evenly spread services, whatever a row holds --
     on, off, or nothing at all (a row added on the page);
  B. the page, both value sets: the column is hidden in the units table, every
     other column still shows, and every row still carries the column, on;
  C. what "even" does, solved: four services on a 96-hour horizon land one in
     each quarter, where "free" may put them anywhere.

"Variable O&M" is hidden too, not removed (``SHOW_VARIABLE_OM``), and the
table says each unit's cost of running, everything in:

  D. Variable O&M: hidden on both value sets, kept in every row (0), still
     read into the model, and shown again by its flag;
  E. the cost under the table, recomputed here from the row itself -- the gas
     price is the full-load cost times the full-load efficiency, the gas line
     runs through the 100 % and 50 % points -- for both value sets, with and
     without efficiencies, services and hourly O&M, and as the page says it.

No API key, nothing online.
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

import app_dispatch as D        # noqa: E402
from reopt_core import model as M   # noqa: E402

FAILS: list[str] = []
BAT = dict(kw=2500.0, kwh=5500.0, rte=0.88, soc_min=0.30, soc_init=0.50,
           cyclic=True, wear=0.5, grid_charge=False, capex=391_000_000.0)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


def a_model() -> None:
    print("\nA. the model always gets evenly spread services")
    check("the switch is set to always on", D.SPREAD_ALWAYS_ON is True)
    load = [1500.0] * 96
    sc = dict(D.default_scenarios().iloc[0])
    for held in (True, False, None, float("nan")):
        u = D.default_units("2 units (Jenbacher + TEDOM)")
        u[D.U_MSPACE] = u[D.U_MSPACE].astype(object)
        u.loc[:, D.U_MSPACE] = held
        u.loc[:, D.U_MEV] = 2
        inp = D.build(load, [60.0] * len(load), u, BAT, sc)
        got = [f.maintenance_spacing for f in inp.fuel_techs if f.enabled]
        check(f"a row holding {held!r} is spread evenly", got and all(g == "even" for g in got),
              str(got))


def b_page() -> None:
    print("\nB. the page, both value sets")
    from streamlit.testing.v1 import AppTest

    def _page():
        import app_dispatch
        app_dispatch.render()
    os.chdir(os.path.dirname(os.path.dirname(HERE)))
    at = AppTest.from_function(_page, default_timeout=120).run()
    check("the page opens", not at.exception, str([e.value for e in at.exception][:1]))
    for values in (D.VALUES_OURS, D.VALUES_ZH):
        at.segmented_control(key="gd_values").set_value(values).run()
        ed = [d for d in at.get("dataframe") if d.proto.id.endswith("-gd_units")]
        check(f"{values}: the units table is there", len(ed) == 1)
        if not ed:
            continue
        cols = json.loads(ed[0].proto.columns)
        check(f"{values}: Spread services is hidden",
              cols.get(D.U_MSPACE, {}).get("hidden") is True, str(cols.get(D.U_MSPACE)))
        # the service columns left on show are the two of test_service_columns.py
        shown = [c for c in (D.U_KW, D.U_MIN, D.U_UP, D.U_DOWN, D.U_MINT, D.U_MCOST)
                 if not cols.get(c, {}).get("hidden")]
        check(f"{values}: the columns around it still show",
              len(shown) == 6, str(shown))
        df = at.session_state["gd_units_df"]
        check(f"{values}: every row still carries the column, on",
              D.U_MSPACE in df.columns and bool(df[D.U_MSPACE].all()), str(list(df[D.U_MSPACE])))


def c_solved() -> None:
    # Spacing belongs to the core's scheduled maintenance, which the page poses
    # only with SERVICE_IN_CORE (services are otherwise priced per running hour,
    # test_service_columns.py); it is switched on here to show what it does.
    print("\nC. what it does, solved (the core's scheduled maintenance, SERVICE_IN_CORE)")
    D.SERVICE_IN_CORE = True
    try:
        _c_solved()
    finally:
        D.SERVICE_IN_CORE = False


def _c_solved() -> None:
    load = [1500.0] * 96
    sc = dict(D.default_scenarios().iloc[0])
    u = D.default_units("2 units (Jenbacher + TEDOM)")
    u.loc[:, D.U_MEV] = 4
    u.loc[:, D.U_MDUR] = 4
    inp = D.build(load, [60.0] * len(load), u, BAT, sc)
    res = M.solve(inp, time_limit=120, mip_gap=0.001)
    check("it solves", res.get("solved", True) and res["objective_lifecycle_cost"] is not None,
          str(res.get("status")))
    # the model's own service-start indicators: a run of service hours can join
    # the next one, or wrap past the last hour (the horizon is cyclic), so the
    # starts are read off the model rather than off the hours a unit was down
    units = [u for u in res["sizes"]["fueltech_units"] if u.get("maintenance_starts") is not None]
    ok = bool(units)
    for u in units:
        quarter = [t // 24 for t in u["maintenance_starts"]]
        ok &= sorted(quarter) == [0, 1, 2, 3]
        print(f"      {u['name']}: services begin at hours {u['maintenance_starts']} "
              f"-> quarters {quarter}")
    check("each unit's four services fall one in each quarter of the horizon", ok)


def _close(a: float, b: float, rel: float = 1e-9) -> bool:
    return abs(a - b) <= max(1e-9, rel * max(abs(a), abs(b)))


def expected(u) -> dict:
    """A unit's cost of running, from its row alone, not through the page."""
    kw = float(u[D.U_KW])
    om = float(u.get(D.U_OM) or 0.0)
    hourly = float(u.get(D.U_OMH) or 0.0)
    n, c = float(u.get(D.U_MINT) or 0.0), float(u.get(D.U_MCOST) or 0.0)
    hourly += c / n if n > 0 and c > 0 else 0.0
    try:
        e100, e50 = float(u[D.U_EFF100]) / 100.0, float(u[D.U_EFF50]) / 100.0
        curve = e100 > 0 and e50 > 0
    except (TypeError, ValueError):
        curve = False
    if curve:
        gas = float(u[D.U_COST]) * e100                    # ₸ per kWh of gas
        f_full, f_half = kw / e100, 0.5 * kw / e50         # kWh of gas an hour
        slope = (f_full - f_half) / (0.5 * kw)
        idle = f_full - slope * kw
        per_kwh, per_hour = gas * slope + om, gas * idle + hourly
    else:
        per_kwh, per_hour = float(u[D.U_COST]) + om, hourly
    return {"full": per_kwh + per_hour / kw, "half": per_kwh + per_hour / (0.5 * kw),
            "per_kwh": per_kwh, "per_hour": per_hour}


def d_variable_om() -> None:
    print("\nD. Variable O&M: hidden, kept, still read")
    check("its flag is set to hide", D.SHOW_VARIABLE_OM is False)
    load = [1500.0] * 24
    sc = dict(D.default_scenarios().iloc[0])
    # with efficiencies the gas goes on its curve and O&M per kWh beside it;
    # without, one price a kWh carries both (fuel cost + O&M)
    for preset, want in ((next(p for p in D.unit_presets() if "ЖКПЗ" in p), lambda r: 1.5),
                         ("2 units (Jenbacher + TEDOM)", lambda r: float(r[D.U_COST]) + 1.5)):
        u = D.default_units(preset)
        u.loc[:, D.U_OM] = 1.5
        inp = D.build(load, [60.0] * len(load), u, BAT, sc)
        got = [f.om_cost_per_kwh for f in inp.fuel_techs if f.enabled]
        exp = [want(r) for _, r in u.iterrows() if float(r[D.U_KW]) > 0]
        check(f"a value in it still reaches the model's om_cost_per_kwh ({preset[:24]})",
              got == exp, f"{got} vs {exp}")
    from streamlit.testing.v1 import AppTest

    def _page():
        import app_dispatch
        app_dispatch.render()
    os.chdir(os.path.dirname(os.path.dirname(HERE)))
    at = AppTest.from_function(_page, default_timeout=120).run()
    for values in (D.VALUES_OURS, D.VALUES_ZH):
        at.segmented_control(key="gd_values").set_value(values).run()
        ed = [d for d in at.get("dataframe") if d.proto.id.endswith("-gd_units")]
        cols = json.loads(ed[0].proto.columns) if ed else {}
        df = at.session_state["gd_units_df"]
        check(f"{values}: Variable O&M is hidden, every row keeps it at 0",
              cols.get(D.U_OM, {}).get("hidden") is True
              and D.U_OM in df.columns and (df[D.U_OM] == 0).all(), str(cols.get(D.U_OM)))
        check(f"{values}: the cost-of-running note is hidden with the other notes",
              "Cost of running" not in " ".join(x.value for x in at.caption))
        D.SHOW_NOTES = True
        try:
            at.run()
            caps = " ".join(x.value for x in at.caption)
        finally:
            D.SHOW_NOTES = False
        want = [expected(r) for _, r in df.iterrows() if float(r[D.U_KW]) > 0]
        said = all(f"**{w['full']:,.1f}**" in caps and f"**{w['half']:,.1f}**" in caps
                   and f"{w['per_hour']:,.0f}" in caps for w in want)
        check(f"{values}: SHOW_NOTES = True says the cost of running under the table, "
              "as recomputed here",
              "Cost of running, everything in" in caps and said,
              "; ".join(f"{w['full']:.1f} / {w['half']:.1f}" for w in want))
    D.SHOW_VARIABLE_OM = True
    try:
        at.run()
        ed = [d for d in at.get("dataframe") if d.proto.id.endswith("-gd_units")]
        cols = json.loads(ed[0].proto.columns) if ed else {}
        check("SHOW_VARIABLE_OM = True shows it again",
              not at.exception and not cols.get(D.U_OM, {}).get("hidden"))
    finally:
        D.SHOW_VARIABLE_OM = False


def e_cost_line() -> None:
    print("\nE. the cost of running, recomputed from the row")
    preset = next(p for p in D.unit_presets() if "ЖКПЗ" in p)
    for values in (D.VALUES_OURS, D.VALUES_ZH):
        base = D.default_units(preset, values)
        variants = {"as set": base}
        v = base.copy(); v.loc[:, D.U_MINT] = 2000.0; v.loc[:, D.U_MCOST] = 1_500_000.0
        variants["with a service plan"] = v
        v = base.copy(); v.loc[:, D.U_OMH] = 5000.0; v.loc[:, D.U_OM] = 1.0
        variants["with hourly and per-kWh O&M"] = v
        v = base.copy(); v[D.U_EFF100] = None; v[D.U_EFF50] = None
        variants["without efficiencies (one price a kWh)"] = v
        for name, units in variants.items():
            ok, got = True, []
            for _, r in units.iterrows():
                c, w = D.unit_cost_line(r), expected(r)
                ok &= all(_close(c[k], w[k], 1e-9) for k in w)
                got.append(f"{c['full']:.2f}/{c['half']:.2f}")
            check(f"{values[:4]} {name}: full, half, per kWh and per hour as recomputed", ok,
                  " ".join(got))
    # the hand figures quoted to the reader
    zh = D.default_units(preset, D.VALUES_ZH).iloc[0]
    ours = D.default_units(preset, D.VALUES_OURS).iloc[0]
    c1, c2 = D.unit_cost_line(ours), D.unit_cost_line(zh)
    check("TEDOM, our study: 22.0 ₸/kWh at full load, 23.9 at half, 20.14 + 2,233 an hour",
          round(c1["full"], 1) == 22.0 and round(c1["half"], 1) == 23.9
          and round(c1["per_kwh"], 2) == 20.14 and round(c1["per_hour"]) == 2233,
          str({k: round(x, 2) for k, x in c1.items()}))
    check("TEDOM, his values: 22.3 at full load, 29.6 at half, 14.89 + 8,851 an hour",
          round(c2["full"], 1) == 22.3 and round(c2["half"], 1) == 29.6
          and round(c2["per_kwh"], 2) == 14.89 and round(c2["per_hour"]) == 8851,
          str({k: round(x, 2) for k, x in c2.items()}))


if __name__ == "__main__":
    a_model()
    b_page()
    c_solved()
    d_variable_om()
    e_cost_line()
    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: " + "; ".join(FAILS))
    sys.exit(1 if FAILS else 0)
