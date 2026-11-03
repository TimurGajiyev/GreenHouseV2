"""Service in the units table: two columns, priced per running hour.

    python calculator/tools/test_service_columns.py

The units table keeps two service columns, as a service plan is written: one
service every N running hours, at C each. Every running hour carries C / N on
top of the O&M per running hour (``app_dispatch.run_rate``); the core is not
changed. The four other columns (count, duration, capacity lost, spread) are
hidden, not removed, and ``SERVICE_IN_CORE = True`` poses them as before.

  A. why: the old six columns, posed exactly as the page posed them, on ЖКПЗ's
     measured days -- services multiplied by the days of a day-by-day solve,
     an interval that cannot be posed there at all, a service that costs
     nothing in hours the logger already shows the engine down, a service
     price the accounts never saw;
  B. the two columns, both value sets, every way of solving: nothing changes
     at zero, the hidden columns change nothing, an OEM interval poses
     everywhere, the accounts add up to the objective, and the service part
     is the hours on times C / N, recomputed from the solver's own series;
  C. the page, both value sets: two service columns shown, four hidden, the
     rate said under the table and in the inputs, a solve with services on;
  D. the core is the core of a03fbd3, byte for byte.

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

import app_dispatch as D        # noqa: E402
import real_data as RD          # noqa: E402
import year_study as Y          # noqa: E402
from reopt_core import model as M   # noqa: E402

FAILS: list[str] = []
PRESET = next(p for p in D.unit_presets() if RD.ZHKPZ in p)
N_OEM, C_OEM = 2_000.0, 1_500_000.0          # a minor service: every 2,000 run h


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


def close(a: float, b: float, rel: float = 1e-9, absol: float = 1e-3) -> bool:
    return abs(a - b) <= max(absol, rel * max(abs(a), abs(b)))


# --------------------------------------------------------------------- setup
_YEAR = None


def case(values: str, hours: int = 24 * 7, start: int = 0) -> dict:
    """ЖКПЗ's measured days, posed with a value set's own inputs."""
    global _YEAR
    _YEAR = _YEAR or RD.year(RD.ZHKPZ)
    y = _YEAR
    V = D.VALUES[values]
    if values == D.VALUES_ZH:
        start += D.zh_window(list(y["time"]))[0]
    load = y["load"][start:start + hours]
    meas = {"gpu_units": [g[start:start + hours] for g in y["gpu_units"]]}
    units = D.default_units(PRESET, values)
    bat = dict(kw=V["b_kw"], kwh=V["b_kwh"], rte=0.88, soc_min=V["soc_min"] / 100.0,
               soc_init=0.5, cyclic=True, wear=V["wear"], grid_charge=False, capex=V["capex"],
               om_fraction=0.0, replace_year=0, replace_fraction=0.0, own_kw=V["own_kw"])
    return dict(values=values, load=load, price=[V["grid"]] * len(load), units=units,
                bat=bat, meas=meas, measured=V["avail"] == 0)


def solve(c: dict, units, mode: str = "window", scen: str = "A · ГПУ от 50%, без батареи"):
    sc = dict(D.SCENARIO_LIBRARY[scen])
    avail = D.measured_availability(c["meas"], units) if c["measured"] else None
    if mode == "window":
        return M.solve(D.build(c["load"], c["price"], units, c["bat"], sc, avail=avail),
                       time_limit=120, mip_gap=0.0001)
    typ = (Y.every_day(c["load"], c["price"]) if mode == "every"
           else Y.cluster(c["load"], c["price"], 3))
    return Y.solve_year(None, c["load"], c["price"], typ.k, typical=typ,
                        day_pose=lambda k, dl, dp: D.build(
                            dl, dp, units, c["bat"], sc, avail=D.day_availability(avail, typ, k)),
                        time_limit=120, mip_gap=0.0001)


def with_(units, **cols):
    u = units.copy()
    for k, v in cols.items():
        u[k] = u[k].astype(object) if not isinstance(v, (int, float)) else u[k]
        u.loc[:, k] = v
    return u


def hours_on(res: dict) -> dict[str, int]:
    """Hours each unit is on, from the solver's own on/off series."""
    on = res["series"].get("fueltech_unit_on") or {}
    return {n: sum(1 for x in s if x > 0.5) for n, s in on.items()}


# ------------------------------------------------------------- A. the old way
def a_old() -> None:
    print("\nA. the six columns as they were (SERVICE_IN_CORE = True), ЖКПЗ")
    D.SERVICE_IN_CORE = True
    try:
        for values in (D.VALUES_OURS, D.VALUES_ZH):
            c = case(values)
            U, tag = c["units"], values[:4]
            base = solve(c, U, "every")
            one = solve(c, with_(U, **{D.U_MEV: 1, D.U_MDUR: 8}), "every")
            down = {n: sum(1 for x in s if x > 0.5)
                    for n, s in (one["series"].get("fueltech_unit_maintenance") or {}).items()}
            on_base, on_one = sum(hours_on(base).values()), sum(hours_on(one).values())
            check(f"{tag}: day by day, '1 service' became one EVERY day: the engines ran "
                  f"{on_one} h instead of {on_base}, and the cost rose",
                  on_one < 0.85 * on_base
                  and one["objective_lifecycle_cost"] > base["objective_lifecycle_cost"] * 1.05,
                  f"{base['objective_lifecycle_cost']:,.0f} -> {one['objective_lifecycle_cost']:,.0f}"
                  + (f"; service hours {down}" if down else ""))
            for label, cols in (("4 services of 8 h", {D.U_MEV: 4, D.U_MDUR: 8}),
                                (f"an OEM interval of {N_OEM:,.0f} run h",
                                 {D.U_MINT: N_OEM, D.U_MDUR: 8, D.U_MCOST: C_OEM})):
                try:
                    solve(c, with_(U, **cols), "every")
                    check(f"{tag}: day by day, {label} could not be posed", False, "it solved")
                except ValueError as e:
                    check(f"{tag}: day by day, {label} could not be posed", True, str(e)[:70])
            w1 = solve(c, with_(U, **{D.U_MEV: 2, D.U_MDUR: 8, D.U_MCOST: 500_000.0}), "window")
            acc = D.account(w1, c["price"], with_(U, **{D.U_MEV: 2, D.U_MDUR: 8,
                                                         D.U_MCOST: 500_000.0}), c["bat"]["wear"])
            check(f"{tag}: one window, the service price reached the objective but not the "
                  "accounts", close(w1["objective_lifecycle_cost"] - acc["total"],
                                    2 * 2 * 500_000.0, 1e-6, 1.0),
                  f"objective − accounts {w1['objective_lifecycle_cost'] - acc['total']:,.0f}")
            if c["measured"]:
                # on these 14 days each engine stands 8 h in a row somewhere in the
                # logger's own record, and the solver puts the service there
                c14 = case(values, hours=24 * 14)
                U14 = c14["units"]
                s0 = solve(c14, U14, "window")
                s1 = solve(c14, with_(U14, **{D.U_MEV: 1, D.U_MDUR: 8}), "window")
                avail = D.measured_availability(c14["meas"], U14)
                names = [str(n) for n in U14[D.U_NAME]]
                inside = all(avail[i][t] == 0.0
                             for i, n in enumerate(names)
                             for t, x in enumerate((s1["series"].get("fueltech_unit_maintenance")
                                                    or {}).get(n, [])) if x > 0.5)
                check(f"{tag}: availability as measured, the service goes into hours the logger "
                      "already shows the engine down, and costs nothing",
                      inside and close(s1["objective_lifecycle_cost"],
                                       s0["objective_lifecycle_cost"], 1e-6),
                      f"{s0['objective_lifecycle_cost']:,.0f} vs {s1['objective_lifecycle_cost']:,.0f}"
                      f"; all service hours in logged downtime: {inside}")
    finally:
        D.SERVICE_IN_CORE = False


# ------------------------------------------------------------- B. the new way
def b_new() -> None:
    print("\nB. the two columns, both value sets, every way of solving")
    check("the core's scheduled maintenance is off", D.SERVICE_IN_CORE is False)
    for values in (D.VALUES_OURS, D.VALUES_ZH):
        c = case(values)
        U, tag = c["units"], values[:4]
        rate = C_OEM / N_OEM
        oem = with_(U, **{D.U_MINT: N_OEM, D.U_MCOST: C_OEM})
        check(f"{tag}: the rate is cost ÷ interval, {rate:,.0f} per running hour",
              all(close(D.service_rate(u), rate) for _, u in oem.iterrows()))
        check(f"{tag}: one of the two alone prices nothing",
              all(D.service_rate(u) == 0 for _, u in with_(U, **{D.U_MINT: N_OEM}).iterrows())
              and all(D.service_rate(u) == 0 for _, u in with_(U, **{D.U_MCOST: C_OEM}).iterrows()))
        for mode, word in (("window", "one window"), ("every", "day by day"),
                           ("typical", "typical days")):
            base = solve(c, U, mode)
            hidden = solve(c, with_(U, **{D.U_MEV: 4, D.U_MDUR: 8, D.U_MPU: 50.0,
                                          D.U_MSPACE: False}), mode)
            check(f"{tag} {word}: the hidden columns change nothing",
                  close(hidden["objective_lifecycle_cost"], base["objective_lifecycle_cost"]))
            try:
                res = solve(c, oem, mode)
            except Exception as e:      # noqa: BLE001 -- a failure to pose is the finding
                check(f"{tag} {word}: an OEM interval poses", False, f"{type(e).__name__}: {e}")
                continue
            acc = D.account(res, c["price"], oem, c["bat"]["wear"])
            check(f"{tag} {word}: an OEM interval poses, and the accounts add up to the "
                  "objective", close(acc["total"], res["objective_lifecycle_cost"], 1e-6, 1.0),
                  f"{acc['total']:,.0f} vs {res['objective_lifecycle_cost']:,.0f}")
            plain = D.account(res, c["price"], U, c["bat"]["wear"])
            want = sum(hours_on(res).values()) * rate
            check(f"{tag} {word}: the services are the hours on × {rate:,.0f}, recomputed "
                  "from the solver's series", close(acc["total"] - plain["total"], want, 1e-9, 1.0),
                  f"{acc['total'] - plain['total']:,.0f} vs {want:,.0f}")
            check(f"{tag} {word}: and the dearer hour never makes the engines run more",
                  sum(hours_on(res).values()) <= sum(hours_on(base).values()),
                  f"{sum(hours_on(base).values())} h -> {sum(hours_on(res).values())} h")
        # the measured plant's engines pay for services on the hours they run,
        # wherever the logger shows them down
        if c["measured"]:
            b0, b1 = solve(c, U), solve(c, oem)
            check(f"{tag}: availability as measured, the services are not free",
                  b1["objective_lifecycle_cost"] > b0["objective_lifecycle_cost"])
        # a dearer service, or a shorter interval, never makes the engines run more
        h = [sum(hours_on(solve(c, with_(U, **{D.U_MINT: N_OEM, D.U_MCOST: cc}))).values())
             for cc in (0.0, 1e6, 1e7, 1e8)]
        check(f"{tag}: running hours fall as the service gets dearer", h == sorted(h, reverse=True),
              str(h))


# ------------------------------------------------------------------ C. page
def c_page() -> None:
    print("\nC. the page, both value sets")
    if not RD.available():
        print("  --  the measured table is not here")
        return
    import json
    from streamlit.testing.v1 import AppTest

    def _page():
        import app_dispatch
        app_dispatch.render()
    os.chdir(ROOT)
    at = AppTest.from_function(_page, default_timeout=120).run()
    check("the page opens", not at.exception, str([e.value for e in at.exception][:1]))
    for values in (D.VALUES_OURS, D.VALUES_ZH):
        at.segmented_control(key="gd_values").set_value(values).run()
        ed = [d for d in at.get("dataframe") if d.proto.id.endswith("-gd_units")]
        cols = json.loads(ed[0].proto.columns) if ed else {}
        hidden = [c for c in (D.U_MEV, D.U_MDUR, D.U_MPU, D.U_MSPACE)
                  if cols.get(c, {}).get("hidden")]
        shown = [c for c in (D.U_MINT, D.U_MCOST) if not cols.get(c, {}).get("hidden")]
        check(f"{values}: two service columns shown, four hidden",
              len(hidden) == 4 and len(shown) == 2, f"shown {shown}, hidden {hidden}")
        u = at.session_state["gd_units_df"].copy()
        u.loc[:, D.U_MINT] = N_OEM
        u.loc[:, D.U_MCOST] = C_OEM
        at.session_state["gd_units_df"] = u
        if "gd_units" in at.session_state:      # edits made on the old table
            del at.session_state["gd_units"]
        at.run()
        check(f"{values}: the rate note is hidden with the other notes",
              "per running hour" not in " ".join(x.value for x in at.caption))
        D.SHOW_NOTES = True
        try:
            at.run()
            caps = " ".join(x.value for x in at.caption)
        finally:
            D.SHOW_NOTES = False
        at.run()
        check(f"{values}: SHOW_NOTES = True says the rate under the table",
              f"{C_OEM / N_OEM:,.0f} per running hour" in caps, caps[caps.find("Services"):][:90])
        ln = next(w for w in at.number_input if (w.key or "").startswith("gd_len_"))
        ln.set_value(96 if values == D.VALUES_OURS else 744).run()
        # every unbroken stretch is one window now, and a long one with a battery
        # may take the page's whole 600 s; these checks read the numbers back from
        # the solve, whatever its gap, so a minute per window serves them
        at.number_input(key="gd_tlim").set_value(60).run()
        at.button(key="gd_run").click().run(timeout=1800)
        check(f"{values}: a solve with services on raises no error",
              not at.exception and not at.error,
              str([e.value for e in [*at.exception, *at.error]][:1]))
        out = at.session_state["gd_results"]
        ok = all(close(r["acc"]["total"], r["res"]["objective_lifecycle_cost"], 1e-6, 1.0)
                 for r in out["runs"])
        check(f"{values}: every scenario's accounts add up to its objective", ok)
        html = " ".join(h.proto.body for h in at.get("html"))
        check(f"{values}: the inputs table lists the services per running hour",
              "Services, per running hour" in html and f"{C_OEM / N_OEM:,.0f}" in html)
    # the way back: SERVICE_IN_CORE shows the core's columns again (spread stays
    # hidden and always on, as test_units_table.py has it)
    D.SERVICE_IN_CORE = True
    try:
        at.run()
        ed = [d for d in at.get("dataframe") if d.proto.id.endswith("-gd_units")]
        cols = json.loads(ed[0].proto.columns) if ed else {}
        back = [c for c in (D.U_MEV, D.U_MDUR, D.U_MPU) if not cols.get(c, {}).get("hidden")]
        check("SERVICE_IN_CORE = True brings the core's three columns back, spread still hidden",
              not at.exception and len(back) == 3 and cols.get(D.U_MSPACE, {}).get("hidden") is True,
              str(back))
    finally:
        D.SERVICE_IN_CORE = False


# ------------------------------------------------------------------ D. core
def d_core() -> None:
    print("\nD. the core")
    r = subprocess.run(["git", "diff", "--quiet", "a03fbd3", "--", "calculator/reopt_core"],
                       cwd=ROOT)
    check("reopt_core is a03fbd3's, byte for byte", r.returncode == 0)


if __name__ == "__main__":
    if not RD.available():
        print("the measured table is not here")
        sys.exit(0)
    a_old()
    b_new()
    c_page()
    d_core()
    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: " + "; ".join(FAILS))
    sys.exit(1 if FAILS else 0)
