"""Every unbroken stretch as one window -- REopt's way -- checked from outside.

    python calculator/tools/test_stretch_cover.py

REopt solves a year as one window (``time_steps = 1:length(loads_kw)``,
reopt_inputs.jl:175). A measured plant's horizon is not one run: ЖКПЗ's days lie
in unbroken stretches between gaps in the data. The page now solves each stretch
as one window and lays them end to end (``year_study.stretches``, ``by_stretch``);
it is exact but slow (hours with a battery), so the page shows every day on
its own instead, and keeps this way, with the others, behind ``SHOW_ALL_COVERS``.

  A. the stretches: cut exactly where the logger's clock jumps (recounted here
     from the timestamps), whole days, tiling the horizon in order; one stretch
     when there are no timestamps;
  B. the solve, both value sets, on measured days that hold one-day and
     multi-day stretches: each piece is the window the core solves on its own
     (recomputed with a direct solve), a one-day piece is that day of
     every-day-on-its-own, the starts charged at the joins are the ones a
     cyclic recount finds, the accounts add up to the objective; a load with no
     gap is exactly the one window REopt would solve;
  C. the page, both value sets: every day on its own the one way shown, said in
     the panel and the results; the flag brings the others back, and the stretch
     way picked there solves by stretches;
  D. the core is the core of a03fbd3, byte for byte.

Needs the measured table (real_data) and HiGHS; no API key, nothing online.
"""
from __future__ import annotations

import datetime as dt
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

import pandas as pd             # noqa: E402

import app_dispatch as D        # noqa: E402
import real_data as RD          # noqa: E402
import year_study as Y          # noqa: E402
from reopt_core import model as M   # noqa: E402

FAILS: list[str] = []
PRESET = next(p for p in D.unit_presets() if RD.ZHKPZ in p)
GAP, LIMIT = 0.0001, 300


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


def close(a: float, b: float, rel: float = 1e-9, absol: float = 1e-3) -> bool:
    return abs(a - b) <= max(absol, rel * max(abs(a), abs(b)))


# ---------------------------------------------------------------- A. stretches
def a_stretches() -> None:
    print("\nA. the stretches")
    y = RD.year(RD.ZHKPZ)
    t = [pd.Timestamp(x).to_pydatetime() for x in y["time"]]
    b = Y.stretches(y["time"], len(t))
    # recounted here: a cut wherever the next hour is not one hour on
    cuts = [i for i in range(1, len(t)) if t[i] - t[i - 1] != dt.timedelta(hours=1)]
    check("a stretch ends exactly where the logger's clock jumps",
          [a for a, _ in b[1:]] == cuts, f"{len(cuts)} jumps, {len(b)} stretches")
    check("the stretches tile the horizon, in order",
          b[0][0] == 0 and b[-1][1] == len(t) and all(b[i][1] == b[i + 1][0] for i in range(len(b) - 1)))
    check("every stretch is whole days (the data keeps whole days only)",
          all((e - s) % 24 == 0 for s, e in b), str(sorted({(e - s) // 24 for s, e in b})[:8]))
    inside = all(t[i] - t[i - 1] == dt.timedelta(hours=1) for s, e in b for i in range(s + 1, e))
    check("inside a stretch every hour follows the last", inside)
    check("no timestamps: the whole horizon is one stretch, as REopt's window",
          Y.stretches(None, 240) == [(0, 240)] and Y.stretches([], 240) == [(0, 240)])
    # the caveat that a scaled window carries reaches the stretch way's results too
    st_ = {"stretch": True, "bounds": [(0, 240)]}
    check("a horizon with no clock, shorter than a year, keeps its scaling caveat, "
          "however it was solved",
          D.annualised_window({"time": None, "typical": st_}, 240)
          and D.annualised_window({"time": None, "typical": None}, 240)
          and not D.annualised_window({"time": ["t"] * 240, "typical": st_}, 240)
          and D.annualised_window({"time": None, "typical": {"every": True}}, 240)
          and not D.annualised_window({"time": None, "typical": st_}, D.MAX_H))
    try:
        Y.by_stretch([1.0] * 48, [1.0] * 48, [(0, 24), (30, 48)])
        check("stretches that do not tile the horizon are refused", False)
    except ValueError:
        check("stretches that do not tile the horizon are refused", True)


# ---------------------------------------------------------------- B. the solve
def _setup(values: str, hours: int):
    y = RD.year(RD.ZHKPZ)
    V = D.VALUES[values]
    start = D.zh_window(list(y["time"]))[0] if values == D.VALUES_ZH else 0
    load = y["load"][start:start + hours]
    times = list(y["time"])[start:start + hours]
    units = D.default_units(PRESET, values)
    meas = {"gpu_units": [g[start:start + hours] for g in y["gpu_units"]]}
    avail = D.measured_availability(meas, units) if V["avail"] == 0 else None
    bat = dict(kw=V["b_kw"], kwh=V["b_kwh"], rte=0.88, soc_min=V["soc_min"] / 100.0,
               soc_init=0.5, cyclic=True, wear=V["wear"], grid_charge=False, capex=V["capex"],
               om_fraction=0.0, replace_year=0, replace_fraction=0.0, own_kw=V["own_kw"])
    return V, load, [V["grid"]] * len(load), times, units, avail, bat


def _solve_stretches(load, price, times, units, avail, bat, sc):
    bounds = Y.stretches(times, len(load))
    typ = Y.by_stretch(load, price, bounds)
    res = Y.solve_year(None, load, price, typ.k, typical=typ,
                       day_pose=lambda c, dl, dp: D.build(
                           dl, dp, units, bat, sc,
                           avail=None if avail is None else
                           [a[bounds[c][0]:bounds[c][1]] for a in avail]),
                       time_limit=LIMIT, mip_gap=GAP)
    return res, bounds


def b_solve() -> None:
    print("\nB. the solve, both value sets")
    for values in (D.VALUES_OURS, D.VALUES_ZH):
        V, load, price, times, units, avail, bat = _setup(values, 24 * 10)
        tag = values[:4]
        for name in V["rules"][:2]:
            sc = dict(V["library"][name])
            res, bounds = _solve_stretches(load, price, times, units, avail, bat, sc)
            short = name.split(" · ")[0]
            check(f"{tag} {short}: {len(bounds)} stretches in 10 measured days, one and more days long",
                  len(bounds) >= 2 and any(b - a == 24 for a, b in bounds)
                  and any(b - a > 24 for a, b in bounds), str([(b - a) // 24 for a, b in bounds]))
            # each piece is the window the core solves on its own
            pieces, own_starts = [], 0
            for a, b in bounds:
                r = M.solve(D.build(load[a:b], price[a:b], units, bat, sc,
                                    avail=None if avail is None else [x[a:b] for x in avail]),
                            time_limit=LIMIT, mip_gap=GAP)
                pieces.append(r)
                own_starts += sum(int(u.get("starts") or 0) for u in r["sizes"]["fueltech_units"])
            gaps = [(r.get("solver") or {}).get("mip_gap") or 0.0 for r in pieces]
            # the joins: a cyclic recount over the laid-out horizon, charged at each
            # unit's start cost, is what the whole adds to the pieces
            on = res["series"].get("fueltech_unit_on") or {}
            cost_of = {str(u[D.U_NAME]): float(u[D.U_START] or 0.0) for _, u in units.iterrows()}
            whole_starts, join_cost = 0, 0.0
            for unit, ser in on.items():
                n = sum(1 for i in range(len(ser)) if ser[i] > 0.5 and ser[i - 1] <= 0.5)
                mine = sum(int(u.get("starts") or 0) for r in pieces
                           for u in r["sizes"]["fueltech_units"] if u["name"] == unit)
                whole_starts += n
                join_cost += (n - mine) * cost_of.get(unit, 0.0)
            want = sum(r["objective_lifecycle_cost"] for r in pieces) + join_cost
            check(f"{tag} {short}: the whole is its pieces solved as single windows, plus the "
                  "starts the joins add", close(res["objective_lifecycle_cost"], want,
                                                max(gaps + [1e-9]) + 1e-9, 1.0),
                  f"{res['objective_lifecycle_cost']:,.0f} vs {want:,.0f}; joins add "
                  f"{whole_starts - own_starts} starts")
            check(f"{tag} {short}: the series cover the horizon hour for hour",
                  len(res["series"]["load_kw"]) == len(load)
                  and all(close(x, y) for x, y in zip(res["series"]["load_kw"],
                                                      [v + (V["own_kw"] if sc.get(D.S_BAT) else 0.0)
                                                       for v in load])))
            acc = D.account(res, price, units, bat["wear"] if sc.get(D.S_BAT) else 0.0)
            check(f"{tag} {short}: the accounts add up to the objective",
                  close(acc["total"], res["objective_lifecycle_cost"], 1e-6, 1.0),
                  f"{acc['total']:,.0f} vs {res['objective_lifecycle_cost']:,.0f}")
            # a one-day stretch is exactly that day of every-day-on-its-own
            one = [i for i, (a, b) in enumerate(bounds) if b - a == 24]
            ev = Y.solve_year(None, load, price, len(load) // 24,
                              typical=Y.every_day(load, price),
                              day_pose=lambda c, dl, dp: D.build(
                                  dl, dp, units, bat, sc,
                                  avail=None if avail is None else
                                  [x[24 * c:24 * c + 24] for x in avail]),
                              time_limit=LIMIT, mip_gap=GAP)
            same = all(close(sum(pieces[i]["series"]["grid_kw"]),
                             sum(ev["series"]["grid_kw"][bounds[i][0]:bounds[i][1]]), 1e-6, 1e-3)
                       for i in one)
            check(f"{tag} {short}: a one-day stretch is that day of every-day-on-its-own",
                  bool(one) and same, f"{len(one)} one-day stretches")
        # no timestamps: one stretch, exactly the one window REopt would solve
        sc = dict(V["library"][V["rules"][0]])
        res, bounds = _solve_stretches(load[:72], price[:72], None, units,
                                       None if avail is None else [a[:72] for a in avail], bat, sc)
        w = M.solve(D.build(load[:72], price[:72], units, bat, sc,
                            avail=None if avail is None else [a[:72] for a in avail]),
                    time_limit=LIMIT, mip_gap=GAP)
        check(f"{tag}: a load with no gap is one stretch, the window REopt solves",
              bounds == [(0, 72)] and close(res["objective_lifecycle_cost"],
                                            w["objective_lifecycle_cost"], 1e-9, 1.0),
              f"{res['objective_lifecycle_cost']:,.0f} vs {w['objective_lifecycle_cost']:,.0f}")


# ------------------------------------------------------------------- C. page
def c_page() -> None:
    print("\nC. the page, both value sets")
    from streamlit.testing.v1 import AppTest

    def _page():
        import app_dispatch
        app_dispatch.render()
    os.chdir(ROOT)
    at = AppTest.from_function(_page, default_timeout=120).run()
    check("the page opens", not at.exception, str([e.value for e in at.exception][:1]))
    # a solver setting, not a value set's: it opens at 600 and then keeps what is typed
    check("the time limit per window opens at REopt's own 600 s",
          at.number_input(key="gd_tlim").value == 600)
    for values in (D.VALUES_OURS, D.VALUES_ZH):
        at.segmented_control(key="gd_values").set_value(values).run()
        caps = " ".join(c.value for c in at.caption)
        # the stretch way is exact but slow (hours with a battery); every day on
        # its own is the one way shown, a few minutes for a measured year
        check(f"{values}: one way only, every day on its own, said in the panel",
              not any((r.key or "") == "gd_cover" for r in at.radio)
              and D.COVER_SHOWN == D.COVER_EVERY and D.COVER_EVERY in caps
              and "within about 1 % of solving each unbroken stretch whole" in caps)
        ln = next(w for w in at.number_input if (w.key or "").startswith("gd_len_"))
        ln.set_value(24 * 10).run()
        at.button(key="gd_run").click().run(timeout=900)
        check(f"{values}: a solve raises no error", not at.exception and not at.error,
              str([e.value for e in [*at.exception, *at.error]][:1]))
        out = at.session_state["gd_results"]
        t = (out or {}).get("typical") or {}
        check(f"{values}: the results were solved day by day, and say so",
              t.get("every") is True and not t.get("stretch") and t.get("k") == 10
              and all(r["res"]["typical"].get("every") for r in out["runs"]))
        check(f"{values}: every scenario's accounts add up to its objective",
              all(close(r["acc"]["total"], r["res"]["objective_lifecycle_cost"], 1e-6, 1.0)
                  for r in out["runs"]))
        html = " ".join(h.proto.body for h in at.get("html"))
        caps = " ".join(c.value for c in at.caption)
        check(f"{values}: the results say how the horizon was solved",
              "every day solved on its own" in html and "every day is solved on its own" in caps)
    # the stretch way, still there behind the flag, still solves on the page
    D.SHOW_ALL_COVERS = True
    try:
        at.run()
        r = [w for w in at.radio if (w.key or "") == "gd_cover"]
        check("SHOW_ALL_COVERS = True offers the four ways again, every day first",
              not at.exception and len(r) == 1 and list(r[0].options)[0] == D.COVER_EVERY
              and D.COVER_STRETCH in r[0].options and len(r[0].options) == 4,
              str(r[0].options if r else None))
        if r:
            r[0].set_value(D.COVER_STRETCH).run()
            at.number_input(key="gd_tlim").set_value(120).run()
            at.button(key="gd_run").click().run(timeout=900)
            out = at.session_state["gd_results"]
            t = (out or {}).get("typical") or {}
            check("and the stretch way, picked there, solves by stretches",
                  not at.exception and t.get("stretch") is True
                  and t.get("bounds") == Y.stretches(out.get("time"), out["hours"]))
    finally:
        D.SHOW_ALL_COVERS = False


# ------------------------------------------------------------------- D. core
def d_core() -> None:
    print("\nD. the core")
    r = subprocess.run(["git", "diff", "--quiet", "a03fbd3", "--", "calculator/reopt_core"], cwd=ROOT)
    check("reopt_core is a03fbd3's, byte for byte", r.returncode == 0)


if __name__ == "__main__":
    if not RD.available():
        print("the measured table is not here")
        sys.exit(0)
    a_stretches()
    b_solve()
    c_page()
    d_core()
    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: " + "; ".join(FAILS))
    sys.exit(1 if FAILS else 0)
