"""The units table: "Spread services" hidden, and always on.

    python calculator/tools/test_units_table.py

The column is hidden, not removed (``SPREAD_ALWAYS_ON`` in app_dispatch.py):

  A. the model always gets evenly spread services, whatever a row holds --
     on, off, or nothing at all (a row added on the page);
  B. the page, both value sets: the column is hidden in the units table, every
     other column still shows, and every row still carries the column, on;
  C. what "even" does, solved: four services on a 96-hour horizon land one in
     each quarter, where "free" may put them anywhere.

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


if __name__ == "__main__":
    a_model()
    b_page()
    c_solved()
    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: " + "; ".join(FAILS))
    sys.exit(1 if FAILS else 0)
