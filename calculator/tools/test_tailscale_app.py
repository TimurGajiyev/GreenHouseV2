"""The Tailscale app rebuilt on the page: his rule, his defaults, his formulas, his data rules.

    python calculator/tools/test_tailscale_app.py

  A. the arithmetic is recreate.py's line for line: on synthetic 5-minute steps (his own
     steps are git-ignored) tailscale_method gives the same engine outputs, charge, import,
     export and yearly figures as docs/zharkent-app/recreate.py -- the rebuild that matched
     his published run in 100 % of steps -- for every entity and several sizes;
  B. every default is his: the 41 rows of his "Inputs of this run", the derived prices and
     engine-hour rates of his "Derived:" line, the 24 sizes, the 15 placeholders;
  C. his 15 result formulas (README 3.5) hold on every size of every entity;
  D. the steps are built by his data rules: the study year, gaps bridged only up to the
     limit and never in his never-filled months, load = engines + grid, Meshki +1 h;
  E. the page: the switch offers the dispatch study first and this second (the REopt tool
     still hidden), the dispatch study is untouched, the three views open, the cards are
     the engine's own figures, Run scenario adds a run;
  F. with his run file on disk: his published figures to the stated precision (skipped
     without it);
  G. this project's period view on his rule: every hour balances, the hover panel's saving
     is his (recomputed here from the steps, independently), the starts are his, the days
     are whole and dated, and the page draws the Measured chart and the rule's chart for
     every entity.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import re
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)
HERE = os.path.dirname(os.path.abspath(__file__))
CALC = os.path.dirname(HERE)
ROOT = os.path.dirname(CALC)
sys.path.insert(0, CALC)

import tailscale_method as T     # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


def close(a, b, rel=1e-9, ab=1e-6) -> bool:
    return abs(a - b) <= max(ab, rel * max(abs(a), abs(b)))


def _recreate():
    spec = importlib.util.spec_from_file_location(
        "recreate", os.path.join(ROOT, "docs", "zharkent-app", "recreate.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def synthetic(group: str, days: int = 12, seed: int = 0) -> pd.DataFrame:
    """5-minute measured steps with gaps, stretches and three months, his column names."""
    rng = np.random.default_rng(seed)
    n = days * 288
    # within one month, so the month passes his 25 % coverage and enters the year
    t = pd.date_range("2026-04-03", periods=n, freq="5min")
    keep = np.ones(n, bool)
    keep[400:460] = False          # a gap: two stretches
    keep[1500:1503] = False
    hour = (t.hour + t.minute / 60).values
    load = 1300 + 600 * np.sin(hour / 24 * 2 * np.pi) + rng.normal(0, 120, n)
    if group == "M":
        load = 0.4 * load
    x = pd.DataFrame({"time": t, "load": np.maximum(load, 150)})
    units = T.GROUPS[group]["units"]
    left = x["load"].values.copy()
    for u in units:
        on = rng.random(n) > 0.3
        p = np.where(on, np.minimum(T.RATED[u] * rng.uniform(0.4, 1.0, n), left + 200), 0.0)
        x[f"{u}_measured"] = np.maximum(p, 0)
        left = left - x[f"{u}_measured"].values
    x["grid_measured"] = left
    x = x[keep].reset_index(drop=True)
    x["new"] = x["time"].diff() != pd.Timedelta(minutes=5)
    x.attrs["dt"] = 5 / 60
    return x


# ------------------------------------------------------------------------------------- A
def a_same_as_recreate() -> None:
    print("\nA. the arithmetic is recreate.py's (which matched his run in 100 % of steps)")
    R = _recreate()
    for g, units in R.UNITS.items():
        x = synthetic(g, seed=len(g))
        for e, c in ((3.0, 0.33), (2.0, 0.5), (5.5, 0.25), (0.0, 0.0)):
            ours = T.simulate(x, units, 1000 * e, 1000 * e * c)
            his = R.simulate(x, units, 1000 * e, 1000 * e * c)
            same = all(np.allclose(ours[k], his[k]) for k in ("soc", "ch", "dis", "imp", "exp", "oob", "forced"))
            same &= all(np.allclose(ours["out"][u], his["out"][u]) for u in units)
            check(f"{g} {e:g} MWh × {c:g} C: every step the same (engines, charge, import, export)",
                  same)
        tb, hb = T.base(x, units), R.base(x, units)
        keys = ["cost_kzt", "fuel_kzt", "om_kzt", "grid_kzt", "run_h", "starts", "imp_kwh", "gen_kwh"]
        check(f"{g}: today's yearly figures the same", all(close(tb[k], hb[k]) for k in keys),
              f"cost {tb.cost_kzt:,.0f} vs {hb.cost_kzt:,.0f}")
        for e, c in ((3.0, 0.33), (1.0, 1.0)):
            s = T.simulate(x, units, 1000 * e, 1000 * e * c)
            y = T.evaluate(x, units, e, c, s, tb)
            h = R.scenario(x, units, e, c)
            ks = keys + ["capex_kzt", "saving_kzt", "band_kzt", "import_kzt", "cycles", "life_y"]
            ok = all(close(y[k], h[k]) for k in ks)
            ok &= (np.isnan(y.payback_y) and np.isnan(h.payback_y)) or close(y.payback_y, h.payback_y)
            ok &= bool(y.in_band) == bool(h.in_band)
            check(f"{g} {e:g} MWh × {c:g} C: result row the same (saving, parts, cycles, life, payback)",
                  ok, f"saving {y.saving_kzt:,.0f} vs {h.saving_kzt:,.0f}")


# ------------------------------------------------------------------------------------- B
def b_defaults() -> None:
    print("\nB. every default is his")
    D = T.DEFAULTS
    rows = {r["input"]: r for r in T.inputs_table(D)}
    check("his inputs table has 41 rows", len(rows) == 41, str(len(rows)))
    want = {"MWM rated output": "1200 kW", "Jenbacher rated output": "1066 kW",
            "Service cost basis": "6.0 KZT/kWh at rated output",
            "Start wear": "4.0 equivalent engine hours per start", "KZT per EUR": "520 KZT/EUR",
            "Start wear values compared": "[0, 1, 2, 4, 8] equivalent engine hours per start",
            "Battery price": "150 USD per kWh of battery", "Inverter price": "120 USD per kW of inverter",
            "Other battery costs": "0 USD", "Capacities compared": "[1, 2, 3, 4, 5.5, 7] MWh",
            "C-rates compared": "[0.25, 0.33, 0.5, 1.0] C (power = capacity × C)",
            "KZT per USD": "480 KZT/USD", "Battery cycle life": "6000 full cycles",
            "Battery calendar life": "15 years", "Round-trip efficiency": "0.88 frac, AC to AC",
            "Usable charge window": "(0.1, 0.95) frac of nominal energy",
            "Battery's own consumption": "15 kW", "Efficient band: engines run at least at": "0.9 frac of rated",
            "Export allowed": "False", "All engines may stop": "True", "Minimum run time": "0.5 h",
            "Minimum off time": "0.25 h", "Charge taper": "(0.85, 1.0) frac",
            "Datasheet minimum load": "0.5 frac of rated",
            "Allowed time below the band": "0.01 frac of engine hours", "VAT": "0.12 frac",
            "Gas price incl. VAT": "75 KZT/m³ incl. VAT", "Grid price incl. VAT": "50 KZT/kWh incl. VAT",
            "Gas heating value": "9.44 kWh/m³", "Export price": "0.0 KZT/kWh",
            "Study year from": "2025-10-01", "Study year to": "2026-10-01",
            "Bridge data gaps up to": "3 h", "Month coverage needed": "0.25 frac of hours",
            "Engine counts as running above": "50 kW"}
    bad = [k for k, v in want.items() if rows.get(k, {}).get("value") != v]
    check("each value as his table prints it", not bad,
          "; ".join(f"{k}: {rows.get(k, {}).get('value')!r}" for k in bad))
    status = {r["input"]: r["status"] for r in rows.values()}
    ph = sorted(k for k, v in status.items() if v == "placeholder")
    check("15 placeholders, as his header lists them", len(ph) == 15 and len(T.PLACEHOLDERS) == 15,
          f"{len(ph)} in the table")
    check("derived: gas 7.094 KZT per kWh of gas, grid 44.64 KZT/kWh ex VAT",
          close(D.gas_kzt_kwh, 75 / 1.12 / 9.44) and round(D.gas_kzt_kwh * 1000) == 7094
          and round(D.grid_ex_vat, 2) == 44.64)
    check("engine hour MWM 7 200, Jenbacher 6 396 KZT", D.om_h("mwm") == 7200 and D.om_h("zh2") == 6396)
    check("battery price 3 MWh × 0.33 C = 273.0 M KZT (his default)",
          close(T.price(3.0, 0.33), 273_024_000.0), f"{T.price(3.0, 0.33):,.0f}")
    check("24 sizes compared plus yours", len(D.capacities) * len(D.c_rates) == 24)
    check("efficiencies are his (J320 43.2 %, not the passport's 40.5 %)",
          T.EFF["zh2"][1.0] == 0.432 and T.EFF["mwm"][1.0] == 0.436 and T.RATED["zh2"] == 1066)
    check("nothing changed from inputs.py at the defaults", T.changed(D) == [])
    check("a changed grid price is named", T.changed(T.with_inputs(grid_kzt_kwh=60.0)) == ["Grid price incl. VAT"])


# ------------------------------------------------------------------------------------- C
def c_formulas() -> None:
    print("\nC. his 15 result formulas, on every size of every entity (this project's hourly steps)")
    D = T.DEFAULTS
    for g in T.GROUPS:
        r = T.run_group(g)
        t = r.today
        bad = []
        for _, y in r.sizes.iterrows():
            e, p = 1000 * y.e_mwh, 1000 * y.e_mwh * y.c_rate
            tests = {
                "price": close(y.capex_kzt, (e * 150 + p * 120) * 480),
                "cost": close(y.cost_kzt, y.fuel_kzt + y.om_kzt + y.grid_kzt),
                "fuel": close(y.fuel_kzt, y.fuel_kwh * D.gas_kzt_kwh),
                "grid": close(y.grid_kzt, y.imp_kwh * D.grid_ex_vat),
                "service": close(y.om_kzt, sum((y[f"{u}_run_h"] + 4.0 * y[f"{u}_starts"]) * D.om_h(u)
                                               for u in T.GROUPS[g]["units"])),
                "saving": close(y.saving_kzt, t.cost_kzt - y.cost_kzt),
                "band": close(y.band_kzt, (t.kzt_per_kwh_gen - y.kzt_per_kwh_gen) * t.gen_kwh),
                "import": close(y.import_kzt, y.saving_kzt - y.band_kzt),
                "kzt/kwh": close(y.kzt_per_kwh_gen, (y.fuel_kzt + y.om_kzt) / y.gen_kwh),
                "payback": (y.saving_kzt <= 0 and np.isnan(y.payback_y))
                           or close(y.payback_y, y.capex_kzt / y.saving_kzt),
                "cycles": close(y.cycles, y.throughput_kwh / (0.85 * e)),
                "life": close(y.life_y, min(6000 / y.cycles, 15) if y.cycles else 15),
                "profit": close(y.profit_kzt, y.saving_kzt * y.life_y - y.capex_kzt),
                "in band": bool(y.in_band) == bool(y.oob_h <= 0.01 * y.run_h),
                "pays back": bool(y.pays_back) == bool(y.payback_y == y.payback_y and y.payback_y <= y.life_y),
            }
            bad += [f"{y.e_mwh:g}×{y.c_rate:g} {k}" for k, v in tests.items() if not v]
        check(f"{g}: all 15 hold on all {len(r.sizes)} sizes", not bad, ", ".join(bad[:5]))
        b = r.best
        ok = r.sizes[r.sizes.in_band & r.sizes.pays_back]
        check(f"{g}: the third card is the shortest payback in the band and before wear-out",
              (b is None and ok.empty) or (b is not None and close(b.payback_y, ok.payback_y.min())))


# ------------------------------------------------------------------------------------- D
def d_steps() -> None:
    print("\nD. the steps follow his data rules")
    s = pd.Series([1.0, np.nan, np.nan, 4.0, np.nan, np.nan, np.nan, np.nan, 9.0, np.nan])
    b = T._bridge(s, 3)
    check("a gap of 2 is bridged by a straight line", list(b[:4]) == [1.0, 2.0, 3.0, 4.0])
    check("a gap of 4 (over the limit) and a gap at the end stay empty",
          b[4:8].isna().all() and np.isnan(b.iloc[9]))
    check("0 = no filling", T._bridge(s, 0).isna().sum() == s.isna().sum())
    for g in T.GROUPS:
        x = T.hourly_steps(g)
        units = T.GROUPS[g]["units"]
        check(f"{g}: only the study year Oct 2025 – Sep 2026",
              x.time.min() >= pd.Timestamp("2025-10-01") and x.time.max() < pd.Timestamp("2026-10-01"))
        check(f"{g}: every step complete, load = engines + grid",
              not x[[f"{u}_measured" for u in units] + ["grid_measured"]].isna().any().any()
              and np.allclose(x.load, x[[f"{u}_measured" for u in units]].sum(axis=1) + x.grid_measured))
        check(f"{g}: a stretch starts after every jump in the clock",
              (x["new"] == (x.time.diff() != pd.Timedelta(hours=1))).all())
    k = T.hourly_steps("K")
    dec_feb = k[k.time.dt.to_period("M").astype(str).isin(["2025-12", "2026-02"])]
    raw = pd.read_csv(T.HOURLY, parse_dates=["time"])
    raw_df = raw[raw.time.dt.to_period("M").astype(str).isin(["2025-12", "2026-02"])]
    complete = (raw_df.tedom_kw.notna() & raw_df.j320_2_kw.notna() & raw_df.zhkpz_import_kw.notna()
                & ~raw_df.j320_2_from_balance.fillna(False).astype(bool)
                & ~raw_df.import_2_from_balance.fillna(False).astype(bool)).sum()
    check("Krakhmal: nothing filled in December 2025 and February 2026 (his never-filled)",
          len(dec_feb) == complete, f"{len(dec_feb)} steps vs {complete} measured")
    t = T.base(k, ["mwm", "zh2"])
    check("Krakhmal: the year from the months over 25 % coverage only",
          "2025-12" not in t.attrs["months"] and "2026-02" not in t.attrs["months"],
          f"left out {t.attrs['left_out']}")
    m = T.hourly_steps("M")
    raw_m = raw.set_index("time")["j320_3_kw"].dropna()
    first_raw = raw_m.index[raw_m.index >= pd.Timestamp("2025-10-01") - pd.Timedelta(hours=1)][0]
    check("Meshki: the CR06 clock moved +1 h", m.time.iloc[0] >= first_raw + pd.Timedelta(hours=1))


# ------------------------------------------------------------------------------------- E
def e_page() -> None:
    print("\nE. the page")
    from streamlit.testing.v1 import AppTest
    os.chdir(ROOT)
    at = AppTest.from_file(os.path.join(CALC, "streamlit_app.py"), default_timeout=600).run()
    sw = [w for w in at.segmented_control if w.key == "study"]
    check("the switch: dispatch study first, this second, the REopt tool still hidden",
          len(sw) == 1 and list(sw[0].options) == ["Custom dispatch study (not REopt)",
                                                   "Tailscale app (colleague's method)"]
          and sw[0].value == "Custom dispatch study (not REopt)",
          str(sw[0].options if sw else None))
    check("the dispatch study opens as before", not at.exception
          and any(w.key == "gd_values" for w in at.segmented_control))
    sw[0].set_value("Tailscale app (colleague's method)").run(timeout=600)
    check("this page opens on his default run", not at.exception and not at.error,
          str([e.value[:120] for e in at.exception][:1]))
    runs = at.session_state["ts_runs"]
    check("one run, 'Default inputs', at his defaults", len(runs) == 1
          and runs[0]["name"] == "Default inputs" and runs[0]["inp"] == T.DEFAULTS)
    html = " ".join(h.proto.body for h in at.get("html"))
    cards = re.findall(r'ts-card-v">([^<]+)', html)
    r = runs[0]["results"]["K"]
    want = [f"{r.today.cost_kzt / 1e6:,.1f} M KZT/yr", f"{r.yours.payback_y:.1f} y payback",
            f"{r.best.payback_y:.1f} y" if r.best is not None else "none"]
    check("Krakhmal's three cards are the engine's figures", cards == want, f"{cards} vs {want}")
    check("the report says which steps it ran on", "Measured steps:" in html)
    check("the inputs table, 41 rows", html.count('class="ts-badge"') == 41)
    for g in ("M", "KM"):
        at.segmented_control(key="ts_entity").set_value(g).run(timeout=600)
        check(f"{g} tab opens", not at.exception)
    for v in ("Today", "Data"):
        at.radio(key="ts_view").set_value(v).run(timeout=600)
        check(f"the {v} view opens", not at.exception, str([e.value[:120] for e in at.exception][:1]))
    html = " ".join(h.proto.body for h in at.get("html"))
    check("the Data view carries the data check against his Data page",
          any("Data check" in (x.label or "") for x in at.expander))
    at.radio(key="ts_view").set_value("Battery scenarios").run(timeout=600)
    at.number_input(key="ts_cap").set_value(2.0).run()
    at.button(key="ts_run").click().run(timeout=600)
    runs = at.session_state["ts_runs"]
    check("Run scenario adds a run with the inputs typed", len(runs) == 2
          and runs[-1]["inp"].capacity_mwh == 2.0 and not at.exception)


# ------------------------------------------------------------------------------------- F
def f_his() -> None:
    print("\nF. his published run, on his own steps")
    if not T.his_steps_available():
        print("  skipped: his run file is not on this machine (.playwright/output/zharkent/)")
        return
    for g in T.GROUPS:
        r = T.run_group(g, x=T.his_steps(g))
        h, hr = T.HIS_TODAY[g], T.HIS_RESULT[g]
        check(f"{g}: today {r.today.cost_kzt / 1e6:.1f} M = his {h['cost'] / 1e6:.1f}",
              round(r.today.cost_kzt / 1e5) == round(h["cost"] / 1e5))
        check(f"{g}: saving {r.yours.saving_kzt / 1e6:.1f} M = his {hr['saving'] / 1e6:.1f}, payback "
              f"{r.yours.payback_y:.2f} = his {hr['payback']}",
              round(r.yours.saving_kzt / 1e5) == round(hr["saving"] / 1e5)
              and round(r.yours.payback_y, 2) == hr["payback"])


# ------------------------------------------------------------------------------------- G
def g_periods() -> None:
    print("\nG. this project's period view, fed by his rule")
    D = T.DEFAULTS
    for g in T.GROUPS:
        r = T.run_group(g)
        st_ = T.period_state(r)
        s, sav = st_["res"]["series"], st_["savings"]
        H = len(s["load_kw"])
        names = list(s["fueltech_unit_kw"])
        bal = max(abs(sum(s["fueltech_unit_kw"][n][i] for n in names) + s["grid_kw"][i]
                      + s["battery_discharge_kw"][i] - s["load_kw"][i] - s["battery_charge_kw"][i]
                      - s["export_kw"][i]) for i in range(H))
        check(f"{g}: every hour balances (engines + grid + discharge = load + charge + export)",
              bal < 1e-6, f"{bal:.2e}")
        t = pd.DatetimeIndex(st_["time"])
        whole = all((t[d * 24 + 23] - t[d * 24]) == pd.Timedelta(hours=23) for d in range(H // 24))
        check(f"{g}: {H // 24} whole days of 24 consecutive hours, dated", H % 24 == 0 and whole
              and t.is_monotonic_increasing)
        # independently: each kept hour's cost from his steps, today and with the rule
        x, sim, units = r.x, r.sim, T.GROUPS[g]["units"]
        hour = x["time"].dt.floor("h")
        kept = set(t)
        e0 = e1 = o0 = o1 = 0.0
        new = x["new"].values
        for u in units:
            pm = x[f"{u}_measured"].fillna(0).values
            pr = sim["out"][u]
            for p, sign in ((pm, 0), (pr, 1)):
                run = p > D.run_kw
                meas = pm > D.run_kw
                start = (run & ~np.r_[False, run[:-1]] & ~new) | (new & run & ~meas)
                e = T.fuel_kw(u, p) * D.gas_kzt_kwh + run * D.om_h(u)
                o = start * D.start_wear_h * D.om_h(u)
                m = hour.isin(kept).values
                if sign == 0:
                    e0 += e[m].sum(); o0 += o[m].sum()
                else:
                    e1 += e[m].sum(); o1 += o[m].sum()
        m = hour.isin(kept).values
        e0 += (np.maximum(x["grid_measured"].values, 0) * D.grid_ex_vat)[m].sum()
        e1 += (sim["imp"] * D.grid_ex_vat)[m].sum()
        check(f"{g}: the hover panel's saving is his, hour by hour (energy and starts)",
              close(sum(sav["save_e"]), e0 - e1, 1e-9, 1.0) and close(sum(sav["save_s"]), o0 - o1, 1e-9, 1.0),
              f"{sum(sav['save_e']) + sum(sav['save_s']):,.0f} vs {e0 - e1 + o0 - o1:,.0f} ₸")
        rows = st_["res"]["sizes"]["fueltech_units"]
        check(f"{g}: each unit's starts by day add up to its starts",
              all(sum(u["starts_by_day"]) == u["starts"] for u in rows))
        b = st_["res"]["sizes"]["storage_units"]
        check(f"{g}: the battery is yours, his cycles", len(b) == 1 and b[0]["energy_kwh"] == 3000
              and close(b[0]["full_cycles"], sum(s["battery_discharge_kw"]) / (3000 * 0.85)))
    from streamlit.testing.v1 import AppTest
    os.chdir(ROOT)
    at = AppTest.from_file(os.path.join(CALC, "streamlit_app.py"), default_timeout=600).run()
    [w for w in at.segmented_control if w.key == "study"][0].set_value(
        "Tailscale app (colleague's method)").run(timeout=600)
    for g in T.GROUPS:
        at.segmented_control(key="ts_entity").set_value(g).run(timeout=600)
        html = " ".join(h.proto.body for h in at.get("html"))
        titles = re.findall(r'ghp-title">([^<]+)', html)
        check(f"{g}: the page draws the Measured chart and the rule's chart",
              not at.exception and "Measured" in titles and any("his rule" in x for x in titles),
              str(titles[:3]))


if __name__ == "__main__":
    a_same_as_recreate()
    b_defaults()
    c_formulas()
    d_steps()
    e_page()
    f_his()
    g_periods()
    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: " + "; ".join(FAILS))
    sys.exit(1 if FAILS else 0)
