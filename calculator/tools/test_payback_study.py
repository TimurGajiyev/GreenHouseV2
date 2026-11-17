"""The battery payback study (rule-based): the rule, its defaults and formulas, and the page.

    python calculator/tools/test_payback_study.py

  A. the arithmetic is recreate.py's line for line: on synthetic 5-minute steps (the
     run file is git-ignored) payback_rule gives the same engine outputs, charge, import,
     export and yearly figures as docs/zharkent-app/recreate.py -- the rebuild that matched
     the reference run in 100 % of steps -- for every entity and several sizes, and the
     same result row when the battery is priced as the reference prices it;
  B. the defaults are the reference run's, carried in the dispatch study's battery fields,
     except the battery: of the reference's own 24 sizes, the one with the most profit over
     its life, in the band and before wear-out: 5,500 kWh / 1,375 kW, CAPEX 475,200,000 ₸
     at the reference's prices; each
     engine's rating and efficiencies from its datasheet, the derived prices and
     engine-hour rates, the 46 rows of the inputs table, the 14 placeholders;
  C. the result formulas hold on every size of every entity, at the defaults (where they
     are the reference's) and with battery wear, O&M and a replacement; an engine left out
     of the battery's runs exactly as measured, every step balances, and a changed rating
     or efficiency enters the fuel curve, the engine hour and the rule;
  D. the steps are built by the run file's data rules: the study year, gaps bridged only up
     to the limit and never in the never-filled months, load = engines + grid, Жаркент 3
     +1 h;
  E. the page: the switch offers the dispatch study first and this second (the REopt tool
     still hidden); the inputs sit in the dispatch study's panels with its battery fields,
     and a Generators panel has one row per engine;
     nothing runs before Run scenario; no run history, no sidebar, no C-rates, no names of
     people; the cards are the rule's own figures; changed inputs are run on the next press;
  F. with the run file on disk: the reference's published figures to the stated precision
     (skipped without it);
  G. this project's period view on the rule: every hour balances, the hover panel's saving
     is the rule's (recomputed here from the steps, independently), the starts add up, the
     days are whole and dated, and the page draws the Measured chart and the rule's chart
     for every plant;
  H. one engine tied to the battery (the «машина на батарею» of the 17 Nov 2026 meeting):
     off by default, so nothing above moves; every step balances, the other engines run as
     measured, the tied engine starts and stops on the charge, keeps its minimum run and
     never runs under the floor; the battery's own share is told apart from the engine's;
     the page's Battery operation panel, its notes and its warnings;
  I. battery first, a further engine later (Владимир), HOMER's Combined Dispatch, planned
     ahead (MPC: dynamic programming on a forecast, re-planned every hour) and tuning: every
     step balances, the formulas hold, MPC beats the rule on every plant, the triggers and the
     load following do what they say, tuning keeps the best set, and the page runs each.
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

import payback_rule as T     # noqa: E402

STUDY = "Battery payback study (rule-based)"
DISPATCH = "Custom dispatch study (not REopt)"
# words that would name a person, another app or a quantity the page no longer shows
BANNED = ["tailscale", "colleague", "richard", "inputs.py", "c-rate", "krakhmal", "meshki",
          "joined", "default inputs", "run history"]
BANNED_WORDS = re.compile(r"\b(his|him|he)\b", re.I)

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
    """5-minute measured steps with gaps and stretches, the run file's column names."""
    rng = np.random.default_rng(seed)
    n = days * 288
    # within one month, so the month passes the 25 % coverage and enters the year
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


def reference_price(e_kwh: float, p_kw: float) -> float:
    """The reference's battery price: 150 USD per kWh + 120 USD per kW, at 480 ₸/USD."""
    return (e_kwh * 150 + p_kw * 120) * 480


# ------------------------------------------------------------------------------------- A
def a_same_as_recreate() -> None:
    print("\nA. the arithmetic is recreate.py's (which matched the reference run in 100 % of steps)")
    R = _recreate()
    for g, units in R.UNITS.items():
        x = synthetic(g, seed=len(g))
        for e, c in ((3.0, 0.33), (2.0, 0.5), (5.5, 0.25), (0.0, 0.0)):
            ours = T.simulate(x, units, 1000 * e, 1000 * e * c)
            ref = R.simulate(x, units, 1000 * e, 1000 * e * c)
            same = all(np.allclose(ours[k], ref[k]) for k in ("soc", "ch", "dis", "imp", "exp", "oob", "forced"))
            same &= all(np.allclose(ours["out"][u], ref["out"][u]) for u in units)
            check(f"{g} {1000 * e:,.0f} kWh / {1000 * e * c:,.0f} kW: every step the same "
                  "(engines, charge, import, export)", same)
        tb, hb = T.base(x, units), R.base(x, units)
        keys = ["cost_kzt", "fuel_kzt", "om_kzt", "grid_kzt", "run_h", "starts", "imp_kwh", "gen_kwh"]
        check(f"{g}: today's yearly figures the same", all(close(tb[k], hb[k]) for k in keys),
              f"cost {tb.cost_kzt:,.0f} vs {hb.cost_kzt:,.0f}")
        for e, c in ((3.0, 0.33), (1.0, 1.0)):
            ek, pk = 1000 * e, 1000 * e * c
            # the battery's own fields, priced as the reference prices this size
            inp = T.with_inputs(energy_kwh=ek, power_kw=pk, capex_kzt=reference_price(ek, pk))
            s = T.simulate(x, units, ek, pk, inp)
            y = T.evaluate(x, units, ek, pk, s, tb, inp)
            h = R.scenario(x, units, e, c)
            ks = keys + ["capex_kzt", "saving_kzt", "band_kzt", "import_kzt", "cycles", "life_y"]
            ok = all(close(y[k], h[k]) for k in ks)
            ok &= (np.isnan(y.payback_y) and np.isnan(h.payback_y)) or close(y.payback_y, h.payback_y)
            ok &= bool(y.in_band) == bool(h.in_band)
            check(f"{g} {ek:,.0f} kWh / {pk:,.0f} kW: result row the same (price, saving, parts, "
                  "cycles, life, payback)", ok, f"saving {y.saving_kzt:,.0f} vs {h.saving_kzt:,.0f}")


# ------------------------------------------------------------------------------------- B
def b_defaults() -> None:
    print("\nB. the defaults are the reference run's, in the dispatch study's battery fields")
    D = T.DEFAULTS
    want = dict(band=0.90, start_wear_h=4.0, service_kzt_kwh=6.0, allow_export=False,
                bridge_h=3.0, gas_kzt_m3=75.0, grid_kzt_kwh=50.0, vat=0.12, gas_kwh_m3=9.44,
                power_kw=1375.0, energy_kwh=5500.0, own_kw=15.0, rte=0.88, soc_lo=0.10,
                wear_kzt_kwh=0.0, soc_start=0.50, om_frac=0.0, replace_year=0,
                cycle_life=6000.0, calendar_life=15.0, soc_hi=0.95, min_run_h=0.5,
                min_off_h=0.25, taper_from=0.85, floor=0.5, below_band_allowed=0.01,
                coverage=0.25, run_kw=50.0)
    bad = [k for k, v in want.items() if getattr(D, k) != v]
    check("every default as the reference run has it", not bad,
          ", ".join(f"{k}={getattr(D, k)}" for k in bad))
    check("CAPEX 475,200,000 ₸ = the reference's price of 5.5 MWh at 0.25 C",
          close(D.capex_kzt, reference_price(5500, 1375)) and D.capex_kzt == 475_200_000.0)
    check("4 h of storage", D.hours == 4.0)
    check("sizes compared 1, 2, 3, 4, 5.5, 7 MWh", D.sizes_mwh == (1.0, 2.0, 3.0, 4.0, 5.5, 7.0))
    check("a size's power keeps the battery's hours; yours keeps its own power",
          T.power_for(5500.0) == 1375.0 and close(T.power_for(2000.0), 500.0))
    check("a size's CAPEX is in proportion to its energy",
          close(T.price(2750.0), D.capex_kzt / 2) and close(T.price(5500.0), D.capex_kzt)
          and all(close(T.price(1000 * e), reference_price(1000 * e, 250 * e)) for e in D.sizes_mwh))
    check("each engine's datasheet: TEDOM 1,200 kW at 40.2 / 42.4 / 43.6 %, each J320 1,066 kW "
          "at 39.6 / 41.9 / 43.2 %; all three work with the battery",
          D.rated("mwm") == 1200.0 and D.rated("zh2") == D.rated("zh3") == 1066.0
          and D.eff("mwm") == T.EFF["mwm"] and D.eff("zh2") == D.eff("zh3") == T.EFF["zh2"]
          and all(D.works(u) for u in T.RATED))
    rows = T.inputs_table(D)
    check("the inputs table has 46 rows", len(rows) == 46, str(len(rows)))
    names = [r["input"] for r in rows]
    check("each input named once", len(set(names)) == len(names))
    ph = sorted(r["input"] for r in rows if r["status"] == "placeholder")
    check("14 placeholders, the same as the header lists", len(ph) == 14
          and sorted(T.PLACEHOLDERS) == ph, f"{ph}")
    text = " ".join(" ".join(r.values()) for r in rows).lower()
    left = [w for w in BANNED if w in text] + BANNED_WORDS.findall(text)
    check("the inputs table names no person or other app, and no C-rate", not left, str(left))
    check("derived: gas 7.094 ₸ per kWh of gas, grid 44.64 ₸/kWh ex VAT",
          close(D.gas_kzt_kwh, 75 / 1.12 / 9.44) and round(D.gas_kzt_kwh * 1000) == 7094
          and round(D.grid_ex_vat, 2) == 44.64)
    check("engine hour TEDOM 7 200, J320 6 396 ₸", D.om_h("mwm") == 7200 and D.om_h("zh2") == 6396)
    check("efficiencies are the reference's (J320 43.2 %, not the passport's 40.5 %)",
          T.EFF["zh2"][1.0] == 0.432 and T.EFF["mwm"][1.0] == 0.436 and T.RATED["zh2"] == 1066)
    check("nothing changed at the defaults", T.changed(D) == [])
    check("a changed grid price is named", T.changed(T.with_inputs(grid_kzt_kwh=60.0)) == ["Grid price incl. VAT"])
    check("a changed battery is named by its fields",
          T.changed(T.with_inputs(energy_kwh=3000.0, om_frac=0.02)) == ["Battery energy", "Battery O&M"])
    check("every changed name is a row of the table",
          set(T.LABELS.values()) <= set(names), str(set(T.LABELS.values()) - set(names)))
    g2 = T.with_inputs(with_battery=("mwm",), gen_kw=(("mwm", 1200.0), ("zh2", 1000.0), ("zh3", 1066.0)))
    ch = T.changed(g2)
    rows2 = {r["input"]: r for r in T.inputs_table(g2)}
    check("a changed rating and the generators with the battery are named, and are rows",
          ch == ["Jenbacher J320 (Жаркент 2): rated output", "Generators with the battery"]
          and all(c in rows2 for c in ch), str(ch))
    check("a typed rating is marked typed, not datasheet",
          rows2["Jenbacher J320 (Жаркент 2): rated output"]["status"] == "typed"
          and rows2["TEDOM Quanto 1200 (Жаркент): rated output"]["status"] == "datasheet")


# ------------------------------------------------------------------------------------- C
def _formulas(r: T.Run, inp: T.Inputs) -> list[str]:
    t, g = r.today, r.group
    bad = []
    for _, y in r.sizes.iterrows():
        e = 1000 * y.e_mwh
        capex = inp.capex_kzt * e / inp.energy_kwh
        net = y.saving_kzt - inp.om_frac * capex
        pay = capex / net if net > 0 else np.nan
        rep = inp.replace_frac * capex if inp.replace_year else 0.0
        if rep and pay == pay and pay > inp.replace_year:
            pay = (capex + rep) / net
        life = min(inp.cycle_life / y.cycles, inp.calendar_life) if y.cycles else inp.calendar_life
        rep_in_life = rep if 0 < inp.replace_year < life else 0.0
        tests = {
            "power": close(1000 * y.p_mw, T.power_for(e, inp)),
            "price": close(y.capex_kzt, capex),
            "cost": close(y.cost_kzt, y.fuel_kzt + y.om_kzt + y.grid_kzt + y.wear_kzt),
            "wear": close(y.wear_kzt, y.throughput_kwh * inp.wear_kzt_kwh),
            "fuel": close(y.fuel_kzt, y.fuel_kwh * inp.gas_kzt_kwh),
            "grid": close(y.grid_kzt, y.imp_kwh * inp.grid_ex_vat),
            "service": close(y.om_kzt, sum((y[f"{u}_run_h"] + inp.start_wear_h * y[f"{u}_starts"])
                                           * inp.om_h(u) for u in T.GROUPS[g]["units"])),
            "saving": close(y.saving_kzt, t.cost_kzt - y.cost_kzt),
            "band": close(y.band_kzt, (t.kzt_per_kwh_gen - y.kzt_per_kwh_gen) * t.gen_kwh),
            "import": close(y.import_kzt, y.saving_kzt - y.band_kzt),
            "₸/kWh": close(y.kzt_per_kwh_gen, (y.fuel_kzt + y.om_kzt) / y.gen_kwh),
            "O&M": close(y.bat_om_kzt, inp.om_frac * capex) and close(y.net_kzt, net),
            "payback": (np.isnan(pay) and np.isnan(y.payback_y)) or close(y.payback_y, pay),
            "cycles": close(y.cycles, y.throughput_kwh / ((inp.soc_hi - inp.soc_lo) * e)),
            "life": close(y.life_y, life),
            "profit": close(y.profit_kzt, net * life - capex - rep_in_life),
            "in band": bool(y.in_band) == bool(
                y.oob_h <= inp.below_band_allowed
                * sum(y[f"{u}_run_h"] for u in T.GROUPS[g]["units"] if inp.works(u))),
            "pays back": bool(y.pays_back) == bool(pay == pay and pay <= life),
        }
        bad += [f"{y.e_mwh:g} MWh {k}" for k, v in tests.items() if not v]
    return bad


def c_formulas() -> None:
    print("\nC. the result formulas, on every size of every entity (this project's hourly steps)")
    D = T.DEFAULTS
    extra = T.with_inputs(wear_kzt_kwh=2.0, om_frac=0.02, replace_year=6, replace_frac=0.6,
                          energy_kwh=2500.0, power_kw=1000.0, capex_kzt=250e6)
    for g in T.GROUPS:
        r = T.run_group(g)
        bad = _formulas(r, D)
        check(f"{g}: all hold on all {len(r.sizes)} sizes at the defaults", not bad, ", ".join(bad[:5]))
        # at the defaults they are the reference's: payback = price ÷ saving,
        # profit = saving × life – price
        ref = all(((y.saving_kzt <= 0 and np.isnan(y.payback_y))
                   or close(y.payback_y, y.capex_kzt / y.saving_kzt))
                  and close(y.profit_kzt, y.saving_kzt * y.life_y - y.capex_kzt)
                  for _, y in r.sizes.iterrows())
        check(f"{g}: at the defaults payback = price ÷ saving and profit = saving × life – price", ref)
        b = r.best
        ok = r.sizes[r.sizes.in_band & r.sizes.pays_back]
        check(f"{g}: the third card is the shortest payback in the band and before wear-out",
              (b is None and ok.empty) or (b is not None and close(b.payback_y, ok.payback_y.min())))
        check(f"{g}: your battery is the 5,500 kWh / 1,375 kW", r.yours.e_mwh == 5.5 and r.yours.p_mw == 1.375)
        r2 = T.run_group(g, extra)
        bad = _formulas(r2, extra)
        check(f"{g}: all hold with battery wear, O&M and a replacement", not bad, ", ".join(bad[:5]))
        check(f"{g}: your 2,500 kWh / 1,000 kW is run though it is not a size compared",
              r2.yours.e_mwh == 2.5 and r2.yours.p_mw == 1.0 and 2.5 not in list(r2.sizes.e_mwh))
        y1 = r2.yours
        check(f"{g}: battery wear and O&M only lower the saving",
              y1.wear_kzt > 0 and y1.bat_om_kzt > 0 and y1.net_kzt < y1.saving_kzt)
    print("   the default battery: the most profit over life of the reference's own sizes")
    for g in ("K", "KM"):
        x = T.hourly_steps(g)
        units = T.GROUPS[g]["units"]
        mine = T.run_group(g, x=x).yours
        beaten = []
        for e in (1.0, 2.0, 3.0, 4.0, 5.5, 7.0):
            for c in (0.25, 0.33, 0.5, 1.0):
                ek, pk = 1000 * e, 1000 * e * c
                if (ek, pk) == (D.energy_kwh, D.power_kw):
                    continue
                inp = T.with_inputs(energy_kwh=ek, power_kw=pk, capex_kzt=reference_price(ek, pk))
                y = T.evaluate(x, units, ek, pk, T.simulate(x, units, ek, pk, inp),
                               T.base(x, units, inp), inp)
                if y.in_band and y.pays_back and y.profit_kzt > mine.profit_kzt:
                    beaten.append(f"{e:g} MWh × {c:g} C {y.profit_kzt / 1e6:,.1f} M")
        check(f"{g}: none of the reference's 24 sizes at its prices earns more over its life "
              f"than the default ({mine.profit_kzt / 1e6:,.1f} M ₸), in the band and before "
              "wear-out", not beaten and bool(mine.in_band and mine.pays_back), "; ".join(beaten[:3]))
    print("   generators: one or more with the battery, the others as measured")
    for keep in (("mwm",), ("zh2",), ("mwm", "zh2"), ()):
        inp = T.with_inputs(with_battery=keep)
        for g in T.GROUPS:
            units = T.GROUPS[g]["units"]
            r = T.run_group(g, inp)
            x, s, y, t = r.x, r.sim, r.yours, r.today
            fixed = [u for u in units if u not in keep]
            same = all(np.array_equal(s["out"][u], x[f"{u}_measured"].fillna(0).values) for u in fixed)
            same &= all(close(y[f"{u}_{k}"], t[f"{u}_{k}"]) for u in fixed
                        for k in ("fuel", "run_h", "starts", "kwh"))
            bal = np.abs(sum(s["out"][u] for u in units) + s["imp"] + s["dis"]
                         - s["need"] - s["ch"] - s["exp"]).max()
            rule_h = sum(y[f"{u}_run_h"] for u in units if u in keep)
            bad = _formulas(r, inp)
            check(f"{'+'.join(keep) or 'none'} on {g}: the others run as measured (output, fuel, "
                  "hours, starts), every step balances, the formulas hold, the band counts the "
                  "rule's hours", same and bal < 1e-6 and not bad and close(y.rule_run_h, rule_h)
                  and bool(y.in_band) == bool(y.oob_h <= 0.01 * rule_h),
                  f"bal {bal:.1e}; {', '.join(bad[:3])}")
    x = T.hourly_steps("K")
    hi = T.with_inputs(gen_eff=(("mwm", (0.45, 0.47, 0.48)), ("zh2", (0.396, 0.419, 0.432)),
                                ("zh3", (0.396, 0.419, 0.432))),
                       gen_kw=(("mwm", 1000.0), ("zh2", 1066.0), ("zh3", 1066.0)))
    p = np.array([0.0, 30.0, 300.0, 500.0, 750.0, 1000.0])
    f = T.fuel_kw("mwm", p, 50.0, hi)
    pts = np.array([500 / 0.45, 750 / 0.47, 1000 / 0.48])
    check("a typed rating and efficiencies give the fuel curve through rated × load ÷ efficiency",
          f[0] == 0 and f[1] == 0 and np.allclose(f[3:], pts) and f[2] > 0)
    check("and the engine hour: service rate × the typed rating", hi.om_h("mwm") == 6000.0)
    r0, r1 = T.run_group("K", x=x), T.run_group("K", hi, x=x)
    check("and they move today's fuel and the rule's",
          r1.today.mwm_fuel < r0.today.mwm_fuel and not np.array_equal(r1.sim["out"]["mwm"], r0.sim["out"]["mwm"])
          and r1.sim["out"]["mwm"].max() <= 1000.0 + 1e-9)


# ------------------------------------------------------------------------------------- D
def d_steps() -> None:
    print("\nD. the steps follow the run file's data rules")
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
    check("ЖКПЗ: nothing filled in December 2025 and February 2026 (never filled)",
          len(dec_feb) == complete, f"{len(dec_feb)} steps vs {complete} measured")
    t = T.base(k, ["mwm", "zh2"])
    check("ЖКПЗ: the year from the months over 25 % coverage only",
          "2025-12" not in t.attrs["months"] and "2026-02" not in t.attrs["months"],
          f"left out {t.attrs['left_out']}")
    m = T.hourly_steps("M")
    raw_m = raw.set_index("time")["j320_3_kw"].dropna()
    first_raw = raw_m.index[raw_m.index >= pd.Timestamp("2025-10-01") - pd.Timedelta(hours=1)][0]
    check("Жаркент 3: the CR06 clock moved +1 h", m.time.iloc[0] >= first_raw + pd.Timedelta(hours=1))


# ------------------------------------------------------------------------------------- E
def _page():
    from streamlit.testing.v1 import AppTest
    os.chdir(ROOT)
    at = AppTest.from_file(os.path.join(CALC, "streamlit_app.py"), default_timeout=900).run()
    return at


def _texts(at) -> str:
    """Everything the page shows in words: html, markdown, captions, alerts, widget labels,
    help texts and options."""
    out = [h.proto.body for h in at.get("html")]
    for kind in ("markdown", "caption", "info", "warning", "error", "success"):
        out += [str(e.value) for e in getattr(at, kind)]
    for kind in ("number_input", "checkbox", "radio", "multiselect", "selectbox",
                 "segmented_control", "button", "date_input", "expander"):
        for w in getattr(at, kind):
            out.append(str(getattr(w, "label", "") or ""))
            out.append(str(getattr(w, "help", "") or ""))
            out += [str(o) for o in (getattr(w, "options", None) or [])]
    return " ".join(out)


def e_page() -> None:
    print("\nE. the page")
    at = _page()
    sw = [w for w in at.segmented_control if w.key == "study"]
    check("the switch: dispatch study first, this second, the REopt tool still hidden",
          len(sw) == 1 and list(sw[0].options) == [DISPATCH, STUDY] and sw[0].value == DISPATCH,
          str(sw[0].options if sw else None))
    vals = [w for w in at.segmented_control if w.key == "gd_values"]
    check("the dispatch study opens as before, its second value set renamed",
          not at.exception and len(vals) == 1
          and list(vals[0].options) == ["Our study", "Payback study values"],
          str(vals[0].options if vals else None))
    sw[0].set_value(STUDY).run(timeout=900)
    check("this page opens", not at.exception and not at.error,
          str([e.value[:160] for e in at.exception][:1]))
    check("nothing runs before Run scenario", "bp_result" not in at.session_state
          and any("Run scenario" in i.value for i in at.info))
    run = [b for b in at.button if b.key == "bp_run"]
    check("a Run scenario button, primary like Solve scenarios",
          len(run) == 1 and run[0].label == "Run scenario" and run[0].proto.type == "primary")
    check("no sidebar", len(at.sidebar.number_input) + len(at.sidebar.selectbox)
          + len(at.sidebar.radio) + len(at.sidebar.button) == 0)
    html = " ".join(h.proto.body for h in at.get("html"))
    check("the inputs sit in the dispatch study's panels",
          all(f'reopt-panel-head"><span>{p}</span>' in html
              for p in ("Engines and the rule", "Prices", "Battery", "Measured steps")))
    labels = {w.key: w.label for w in at.number_input}
    battery = {"bp_kw": "Power (kW)", "bp_kwh": "Energy (kWh)", "bp_own": "Own use (kW)",
               "bp_rte": "Round-trip efficiency (%)", "bp_socmin": "Minimum SoC (%)",
               "bp_bwear": "Wear cost (₸ per kWh discharged)", "bp_capex": "Battery CAPEX (₸)",
               "bp_soc0": "Start SoC (%)", "bp_om": "Battery O&M (% of CAPEX per year)",
               "bp_rep_year": "Replacement in year (0 = none)",
               "bp_rep_cost": "Replacement cost (% of CAPEX)"}
    bad = {k: labels.get(k) for k, v in battery.items() if labels.get(k) != v}
    check("the battery's fields are the dispatch study's", not bad, str(bad))
    gens = all(at.checkbox(key=f"bp_on_{u}").value is True
               and at.number_input(key=f"bp_kw_{u}").value == T.DEFAULTS.rated(u)
               and [at.number_input(key=f"bp_e{f}_{u}").value for f in (50, 75, 100)]
               == [round(100 * v, 1) for v in T.DEFAULTS.eff(u).values()]
               for u in T.RATED)
    check("a Generators panel: one row per engine, ticked, with its datasheet rating and "
          "efficiencies", gens and 'reopt-panel-head"><span>Generators</span>' in html)
    check("their values are the defaults", at.number_input(key="bp_kw").value == 1375.0
          and at.number_input(key="bp_kwh").value == 5500.0
          and at.number_input(key="bp_capex").value == 475_200_000.0)
    words = _texts(at).lower()
    left = [w for w in BANNED if w in words] + BANNED_WORDS.findall(words)
    check("before a run: no names of people or other apps, no C-rates", not left, str(left))

    at.button(key="bp_run").click().run(timeout=900)
    res = at.session_state["bp_result"]
    check("Run scenario runs all three plants at the inputs shown",
          not at.exception and res["inp"] == T.DEFAULTS and set(res["results"]) == set(T.GROUPS),
          str([e.value[:160] for e in at.exception][:1]))
    html = " ".join(h.proto.body for h in at.get("html"))
    cards = re.findall(r'bp-card-v">([^<]+)', html)
    r = res["results"]["K"]
    want = [f"{r.today.cost_kzt / 1e6:,.1f} M ₸/yr", f"{r.yours.payback_y:.1f} y payback",
            f"{r.best.payback_y:.1f} y" if r.best is not None else "none"]
    check("ЖКПЗ's three cards are the rule's figures", cards == want, f"{cards} vs {want}")
    check("the report says which steps it ran on", "Measured steps:" in html)
    check("the inputs table, 46 rows", html.count('class="bp-badge"') == 46)
    check("no history table and no Show picker", "Run history" not in html
          and not any(w.key in ("ts_show", "bp_show") for w in at.selectbox))
    for name in ("Жаркент 3", "Both plants, one battery", "ЖКПЗ"):
        at.segmented_control(key="bp_entity").set_value(name).run(timeout=900)
        check(f"{name} opens", not at.exception, str([e.value[:160] for e in at.exception][:1]))
    words = _texts(at).lower()
    left = [w for w in BANNED if w in words] + BANNED_WORDS.findall(words)
    check("after a run: no names of people or other apps, no C-rates", not left, str(left))
    for v in ("Today, measured", "Measured data", "Battery payback"):
        at.segmented_control(key="bp_view").set_value(v).run(timeout=900)
        check(f"the {v} view opens", not at.exception, str([e.value[:160] for e in at.exception][:1]))
        words = _texts(at).lower()
        left = [w for w in BANNED if w in words] + BANNED_WORDS.findall(words)
        check(f"the {v} view names no person or other app", not left, str(left))

    at.number_input(key="bp_grid").set_value(60.0).run(timeout=900)
    check("a changed input shows the results are stale until the next run",
          any("other inputs" in w.value for w in at.warning)
          and at.session_state["bp_result"]["inp"] == T.DEFAULTS)
    at.number_input(key="bp_kwh").set_value(3000.0).run(timeout=900)
    at.number_input(key="bp_capex").set_value(180_000_000.0).run(timeout=900)
    at.button(key="bp_run").click().run(timeout=900)
    res = at.session_state["bp_result"]
    y = res["results"]["K"].yours
    check("the next press runs the inputs typed: 3,000 kWh / 1,375 kW at 180 M ₸, grid 60",
          not at.exception and res["inp"].energy_kwh == 3000.0 and res["inp"].grid_kzt_kwh == 60.0
          and y.e_mwh == 3.0 and y.p_mw == 1.375 and close(y.capex_kzt, 180e6)
          and not any("other inputs" in w.value for w in at.warning))
    check("and names what was changed", any("Battery energy" in c.value and "Battery CAPEX" in c.value
                                            and "Grid price incl. VAT" in c.value for c in at.caption))

    for u in ("zh2", "zh3"):
        at.checkbox(key=f"bp_on_{u}").uncheck().run(timeout=900)
    at.button(key="bp_run").click().run(timeout=900)
    res = at.session_state["bp_result"]
    html = " ".join(h.proto.body for h in at.get("html"))
    check("one generator with the battery: the run takes it, and the page says the others run "
          "as measured", not at.exception and res["inp"].with_battery == ("mwm",)
          and "Generators with the battery: TEDOM Quanto 1200 (Жаркент)" in html
          and "runs as measured" in html)
    at.segmented_control(key="bp_entity").set_value("Жаркент 3").run(timeout=900)
    html = " ".join(h.proto.body for h in at.get("html"))
    check("a plant with none of its generators ticked says so and still draws",
          not at.exception and "No generator of this plant works with the battery" in html)
    at.checkbox(key="bp_on_mwm").uncheck().run(timeout=900)
    run = at.button(key="bp_run")
    check("with no generator ticked, Run scenario is off and the page says why",
          run.disabled and any("at least one generator" in w.value for w in at.warning))


# ------------------------------------------------------------------------------------- F
def f_reference() -> None:
    print("\nF. the reference's published run, on its own steps")
    if not T.his_steps_available():
        print("  skipped: the run file is not on this machine (.playwright/output/zharkent/)")
        return
    # the reference's own battery: 3,000 kWh / 990 kW at its price
    ref = T.with_inputs(energy_kwh=3000.0, power_kw=990.0, capex_kzt=reference_price(3000, 990))
    for g in T.GROUPS:
        r = T.run_group(g, ref, x=T.his_steps(g))
        h, hr = T.HIS_TODAY[g], T.HIS_RESULT[g]
        check(f"{g}: today {r.today.cost_kzt / 1e6:.1f} M = published {h['cost'] / 1e6:.1f}",
              round(r.today.cost_kzt / 1e5) == round(h["cost"] / 1e5))
        check(f"{g}: saving {r.yours.saving_kzt / 1e6:.1f} M = published {hr['saving'] / 1e6:.1f}, "
              f"payback {r.yours.payback_y:.2f} = published {hr['payback']}",
              round(r.yours.saving_kzt / 1e5) == round(hr["saving"] / 1e5)
              and round(r.yours.payback_y, 2) == hr["payback"])


# ------------------------------------------------------------------------------------- G
def g_periods() -> None:
    print("\nG. this project's period view, fed by the rule")
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
        # independently: each kept hour's cost from the steps, today and with the rule
        x, sim, units = r.x, r.sim, T.GROUPS[g]["units"]
        hour = x["time"].dt.floor("h")
        kept = set(t)
        e0 = e1 = o0 = o1 = 0.0
        new = x["new"].values
        m = hour.isin(kept).values
        for u in units:
            pm = x[f"{u}_measured"].fillna(0).values
            meas = pm > D.run_kw
            for p, which in ((pm, 0), (sim["out"][u], 1)):
                run = p > D.run_kw
                start = (run & ~np.r_[False, run[:-1]] & ~new) | (new & run & ~meas)
                e = T.fuel_kw(u, p) * D.gas_kzt_kwh + run * D.om_h(u)
                o = start * D.start_wear_h * D.om_h(u)
                if which == 0:
                    e0 += e[m].sum(); o0 += o[m].sum()
                else:
                    e1 += e[m].sum(); o1 += o[m].sum()
        e0 += (np.maximum(x["grid_measured"].values, 0) * D.grid_ex_vat)[m].sum()
        e1 += (sim["imp"] * D.grid_ex_vat)[m].sum()
        check(f"{g}: the hover panel's saving is the rule's, hour by hour (energy and starts)",
              close(sum(sav["save_e"]), e0 - e1, 1e-9, 1.0) and close(sum(sav["save_s"]), o0 - o1, 1e-9, 1.0),
              f"{sum(sav['save_e']) + sum(sav['save_s']):,.0f} vs {e0 - e1 + o0 - o1:,.0f} ₸")
        rows = st_["res"]["sizes"]["fueltech_units"]
        check(f"{g}: each unit's starts by day add up to its starts",
              all(sum(u["starts_by_day"]) == u["starts"] for u in rows))
        b = st_["res"]["sizes"]["storage_units"]
        check(f"{g}: the battery is yours, 5,500 kWh / 1,375 kW, cycles over the 85 % window",
              len(b) == 1 and b[0]["energy_kwh"] == 5500 and b[0]["power_kw"] == 1375
              and close(b[0]["full_cycles"], sum(s["battery_discharge_kw"]) / (5500 * 0.85)))
        check(f"{g}: the chart is labelled by the battery, not by a person",
              st_["label"] == "Battery 5,500 kWh / 1,375 kW · by the rule", st_["label"])
    at = _page()
    [w for w in at.segmented_control if w.key == "study"][0].set_value(STUDY).run(timeout=900)
    at.button(key="bp_run").click().run(timeout=900)
    for name in ("ЖКПЗ", "Жаркент 3", "Both plants, one battery"):
        at.segmented_control(key="bp_entity").set_value(name).run(timeout=900)
        html = " ".join(h.proto.body for h in at.get("html"))
        titles = re.findall(r'ghp-title">([^<]+)', html)
        check(f"{name}: the page draws the Measured chart and the rule's chart",
              not at.exception and "Measured" in titles and any("by the rule" in x for x in titles),
              str(titles[:3]))


# ------------------------------------------------------------------------------------- H
MODES = ["By the rule: every ticked engine", "One engine tied to the battery",
         "Battery first, a further engine later", "Charge at low load, follow at high load",
         "Planned ahead (MPC)"]


def _runs(on: np.ndarray, new: np.ndarray) -> list[tuple[int, int]]:
    """Each run of the engine within a stretch, as (first step, length)."""
    out, start = [], None
    for i, v in enumerate(on):
        if start is not None and (not v or new[i]):
            out.append((start, i - start))
            start = None
        if v and start is None:
            start = i
    if start is not None:
        out.append((start, len(on) - start))
    return out


def h_tied() -> None:
    print("\nH. one engine tied to the battery")
    D = T.DEFAULTS
    check("off by default: the rule as before, nothing extra in the table",
          D.mode == "rule" and not D.tied and T.run_group("K").alone is None
          and len(T.inputs_table(D)) == 46 and T.changed(D) == [])
    for eng in ("zh2", "zh3"):
        inp = T.with_inputs(mode="tied", tied_engine=eng, tied_on=0.45, tied_off=0.90,
                            tied_min_run_h=2.0)
        for g in T.GROUPS:
            units = T.GROUPS[g]["units"]
            r = T.run_group(g, inp)
            x, s, y = r.x, r.sim, r.yours
            dt = x.attrs.get("dt", 1.0)
            bal = np.abs(sum(s["out"][u] for u in units) + s["imp"] + s["dis"] - s["need"]
                         - s["ch"] - s["exp"]).max()
            others = all(np.array_equal(s["out"][u], x[f"{u}_measured"].fillna(0).values)
                         for u in units if u != eng)
            both = int(((s["ch"] > 1e-9) & (s["dis"] > 1e-9)).sum())
            soc_ok = s["soc"].min() >= inp.soc_lo - 1e-9 and s["soc"].max() <= inp.soc_hi + 1e-9
            check(f"{eng} tied, {g}: every step balances, the other engines as measured, never "
                  "charging and discharging at once, the charge inside its window",
                  bal < 1e-6 and others and both == 0 and soc_ok,
                  f"bal {bal:.1e}, both {both}, soc {s['soc'].min():.3f}..{s['soc'].max():.3f}")
            if eng in units:
                R, new = inp.rated(eng), x["new"].values
                p_out = s["out"][eng]
                on = p_out > 0
                floor_ok = bool((p_out[on] >= inp.floor * R - 1e-6).all() and (p_out <= R + 1e-6).all())
                eta = inp.rte ** 0.5
                E, P = 1000 * y.e_mwh, 1000 * y.p_mw
                gap = x["load"].values + inp.own_kw - sum(
                    (x[f"{u}_measured"].fillna(0).values for u in units if u != eng), np.zeros(len(x)))
                bad_start = bad_stop = short = 0
                for i in range(1, len(x)):
                    if new[i]:
                        continue
                    soc0 = s["soc"][i - 1]
                    give = min(P, max(0.0, (soc0 - inp.soc_lo) * E * eta / dt))
                    take = min(P * min(1.0, (1 - soc0) / (1 - inp.taper_from)),
                               max(0.0, (inp.soc_hi - soc0) * E / eta / dt))
                    if on[i] and not on[i - 1] and not (soc0 <= inp.tied_on + 1e-9 or gap[i] > give):
                        bad_start += 1
                    if (on[i - 1] and not on[i] and not s["forced"][i]
                            and not (soc0 >= inp.tied_off - 1e-9 or inp.band * R > gap[i] + take)):
                        bad_stop += 1
                runs = _runs(on, new)
                min_run = int(round(inp.tied_min_run_h / dt))
                for a, n in runs:
                    end = a + n
                    ends_early = end < len(x) and not new[end] and not s["forced"][end]
                    if n < min_run and ends_early:
                        short += 1
                check(f"{eng} tied, {g}: it starts only at the lower charge or when the battery "
                      "cannot cover the gap, stops only at the upper charge or when it could not "
                      "run in the band, keeps its minimum run, never under the floor",
                      not bad_start and not bad_stop and not short and floor_ok,
                      f"starts {bad_start}, stops {bad_stop}, short runs {short}, floor {floor_ok}")
            else:
                check(f"{eng} tied, {g}: a plant without the tied engine keeps its engines as "
                      "measured", all(np.array_equal(s["out"][u], x[f"{u}_measured"].fillna(0).values)
                                      for u in units))
            bad = _formulas(r, inp)
            o = T.battery_own(r, y)
            check(f"{eng} tied, {g}: the formulas hold, and the engine's part plus the battery's "
                  "make the saving", not bad and o is not None
                  and close(o["engine"] + o["gross"], y.saving_kzt, 1e-9, 1.0)
                  and close(o["net"], o["gross"] - y.bat_om_kzt, 1e-9, 1.0),
                  ", ".join(bad[:3]))
    inp = T.with_inputs(mode="tied", give_from_kw=1e6)
    r = T.run_group("KM", inp)
    check("with the battery giving only above a load never reached, it never gives",
          float(r.sim["dis"].max()) == 0.0)
    inp = T.with_inputs(mode="tied", tied_engine="zh2", tied_on=0.4, give_from_kw=1500.0)
    rows = {row["input"]: row for row in T.inputs_table(inp)}
    ch = T.changed(inp)
    check("the table names the tied engine and its settings (52 rows), the changes list them",
          len(rows) == 52 and rows["Engine tied to the battery"]["value"] == T.LONG["zh2"]
          and rows["Tied engine starts at charge"]["value"] == "40 %"
          and rows["Battery gives from load"]["value"] == "1,500 kW and above"
          and rows["Generators with the battery"]["value"] == T.LONG["zh2"]
          and {"Battery operation", "Engine tied to the battery", "Tied engine starts at charge",
               "Battery gives from load", "Generators with the battery"} <= set(ch)
          and set(ch) <= set(rows), str(ch))

    at = _page()
    [w for w in at.segmented_control if w.key == "study"][0].set_value(STUDY).run(timeout=900)
    html = " ".join(h.proto.body for h in at.get("html"))
    keys = ("bp_tied_engine", "bp_tied_on", "bp_tied_off", "bp_tied_run", "bp_give_from")
    fields = {w.key: w for w in [*at.number_input, *at.selectbox] if w.key in keys}
    check("a Battery operation panel in the same design, by the rule by default, no fields of "
          "the other ways shown",
          'reopt-panel-head"><span>Battery operation</span>' in html
          and at.radio(key="bp_mode").value == MODES[0] and list(at.radio(key="bp_mode").options) == MODES
          and len(fields) == 0
          and not any(at.checkbox(key=f"bp_on_{u}").disabled for u in T.RATED))
    at.radio(key="bp_mode").set_value(MODES[1]).run(timeout=900)
    fields = {w.key: w for w in [*at.number_input, *at.selectbox] if w.key in keys}
    check("tied: its fields on, the Generators ticks off, J320 Жаркент 3 by default",
          len(fields) == 5 and all(not w.disabled for w in fields.values())
          and all(at.checkbox(key=f"bp_on_{u}").disabled for u in T.RATED)
          and at.selectbox(key="bp_tied_engine").value == "zh3")
    at.button(key="bp_run").click().run(timeout=900)
    res = at.session_state["bp_result"]
    html = " ".join(h.proto.body for h in at.get("html"))
    check("the run is tied: the header says which engine and its charge levels",
          not at.exception and res["inp"].tied and res["inp"].tied_engine == "zh3"
          and "Jenbacher J320 (Жаркент 3) is tied to the battery: it starts at 50 % charge" in html,
          str([e.value[:160] for e in at.exception][:1]))
    check("ЖКПЗ says the tied engine is at the other plant",
          "is at the other plant" in html)
    at.segmented_control(key="bp_entity").set_value("Both plants, one battery").run(timeout=900)
    html = " ".join(h.proto.body for h in at.get("html"))
    r = res["results"]["KM"]
    o = T.battery_own(r, r.yours)
    check("both plants: the engine's own saving and the battery's share are on the page",
          not at.exception and f"would save {o['engine'] / 1e6:,.1f} M" in html
          and f"The battery adds {o['gross'] / 1e6:,.1f} M" in html
          and "Jenbacher J320 (Жаркент 3) tied to it" in " ".join(m.value for m in at.markdown))
    words = _texts(at).lower()
    left = [w for w in BANNED if w in words] + BANNED_WORDS.findall(words)
    check("tied mode names no person or other app", not left, str(left))
    at.number_input(key="bp_tied_on").set_value(90.0).run(timeout=900)
    at.number_input(key="bp_tied_off").set_value(60.0).run(timeout=900)
    check("starting at a higher charge than it stops: Run scenario off, the page says why",
          at.button(key="bp_run").disabled
          and any("lower charge than the one it stops at" in w.value for w in at.warning))
    at.radio(key="bp_mode").set_value(MODES[0]).run(timeout=900)
    at.button(key="bp_run").click().run(timeout=900)
    check("back to the rule: the tied fields are ignored and the run is the defaults' again",
          not at.exception and at.session_state["bp_result"]["inp"] == T.DEFAULTS
          and not at.button(key="bp_run").disabled)


# ------------------------------------------------------------------------------------- I
def i_more_ways() -> None:
    print("\nI. battery first (Владимир), Combined Dispatch, planned ahead (MPC), tuning")
    rule = {g: T.run_group(g).yours for g in T.GROUPS}
    ways = [("delayed", {}), ("combined", {}), ("mpc", {"mpc_forecast": "previous"}),
            ("mpc", {"mpc_forecast": "perfect"})]
    for mode, kw in ways:
        inp = T.with_inputs(mode=mode, **kw)
        tag = mode + (f" ({kw['mpc_forecast']})" if kw else "")
        for g in T.GROUPS:
            units = T.GROUPS[g]["units"]
            r = T.run_group(g, inp)
            s, y = r.sim, r.yours
            bal = np.abs(sum(s["out"][u] for u in units) + s["imp"] + s["dis"] - s["need"]
                         - s["ch"] - s["exp"]).max()
            both = int(((s["ch"] > 1e-9) & (s["dis"] > 1e-9)).sum())
            soc_ok = s["soc"].min() >= inp.soc_lo - 1e-9 and s["soc"].max() <= inp.soc_hi + 1e-9
            cap_ok = all(((s["out"][u] <= inp.rated(u) + 1e-6)
                          & ((s["out"][u] == 0) | (s["out"][u] >= inp.floor * inp.rated(u) - 1e-6))).all()
                         for u in units)
            bad = _formulas(r, inp)
            o = T.battery_own(r, y)
            check(f"{tag}, {g}: every step balances, never charging and discharging at once, the "
                  "charge in its window, engines between the floor and their rating, the formulas "
                  "hold, the engines' part plus the battery's make the saving",
                  bal < 1e-6 and both == 0 and soc_ok and cap_ok and not bad and o is not None
                  and close(o["engine"] + o["gross"], y.saving_kzt, 1e-9, 1.0),
                  f"bal {bal:.1e}, both {both}, {', '.join(bad[:2])}")
            if mode == "mpc":
                check(f"{tag}, {g}: in the band, and saves more than the rule "
                      f"({y.saving_kzt / 1e6:,.1f} against {rule[g].saving_kzt / 1e6:,.1f} M)",
                      bool(y.in_band) and y.saving_kzt > rule[g].saving_kzt)
    # battery first: never a further engine while the triggers cannot fire
    for g in ("K", "KM"):
        units = T.GROUPS[g]["units"]
        r = T.run_group(g, T.with_inputs(mode="delayed", delay_h=10_000.0, delay_soc=0.0))
        new = r.x["new"].values
        starts = sum(int(((r.sim["out"][u][1:] > 0) & (r.sim["out"][u][:-1] == 0) & ~new[1:]).sum())
                     for u in units)
        check(f"battery first, {g}: with triggers that never fire, no engine is ever started "
              "within a stretch", starts == 0, f"{starts} starts")
    # Combined Dispatch above every load: load following, the battery charged only by the band
    for g in ("K", "KM"):
        units = T.GROUPS[g]["units"]
        inp = T.with_inputs(mode="combined", cd_load_kw=1.0)
        r = T.run_group(g, inp)
        s = r.sim
        gen = sum(s["out"][u] for u in units)
        r_on = sum(np.where(s["out"][u] > 0, inp.rated(u), 0.0) for u in units)
        over = (s["ch"] > 1e-6) & (gen > np.maximum(s["need"], inp.band * r_on) + 1e-6)
        check(f"Combined Dispatch, {g}: following the load, the engines charge the battery only "
              "with what the band forces", int(over.sum()) == 0, f"{int(over.sum())} steps")
    # tuning: the run takes the best set tried, which is at least as good as the defaults
    for mode in ("tied", "delayed", "combined"):
        r0 = T.run_group("KM", T.with_inputs(mode=mode))
        r1 = T.run_group("KM", T.with_inputs(mode=mode, tune=True))
        t = r1.tuned
        ok_rows = t[t["in_band"]] if t["in_band"].any() else t
        best = ok_rows.sort_values("net_kzt", ascending=False).iloc[0]
        same = all(close(getattr(r1.inp, k), float(best[k])) for k in T.TUNE_GRID[mode])
        check(f"tuning {mode}, both plants: {len(t)} sets tried, the run uses the best "
              f"({r1.yours.net_kzt / 1e6:,.1f} against {r0.yours.net_kzt / 1e6:,.1f} M untuned)",
              same and close(r1.yours.net_kzt, float(best["net_kzt"]), 1e-9, 1.0)
              and (r1.yours.net_kzt >= r0.yours.net_kzt - 1.0 or not r0.yours.in_band))
    rows = {m: len(T.inputs_table(T.with_inputs(mode=m))) for m in ("delayed", "combined", "mpc")}
    check("the table names each way and its settings (49 rows), and tuning (50)",
          rows == {"delayed": 49, "combined": 49, "mpc": 49}
          and len(T.inputs_table(T.with_inputs(mode="delayed", tune=True))) == 50, str(rows))
    check("the changes name the way and what was moved",
          T.changed(T.with_inputs(mode="mpc", mpc_forecast="perfect"))
          == ["Battery operation", "Load forecast"]
          and T.changed(T.with_inputs(mode="delayed", delay_h=2.0, tune=True))
          == ["Battery operation", "Further engine starts after the gap lasts", "Thresholds"])

    at = _page()
    [w for w in at.segmented_control if w.key == "study"][0].set_value(STUDY).run(timeout=900)
    for mode, keys in ((MODES[2], ("bp_delay_h", "bp_delay_soc", "bp_delay_run")),
                       (MODES[3], ("bp_cd_load", "bp_cd_set")),
                       (MODES[4], ("bp_mpc_h", "bp_mpc_rp"))):
        at.radio(key="bp_mode").set_value(mode).run(timeout=900)
        shown = {w.key for w in at.number_input}
        check(f"{mode}: its own fields, and only those of the other ways it shares",
              set(keys) <= shown and not ({"bp_tied_on", "bp_tied_off"} & shown)
              and (mode == MODES[4]) == ("bp_mpc_fc" in {w.key for w in at.radio}))
    at.radio(key="bp_mode").set_value(MODES[2]).run(timeout=900)
    at.button(key="bp_run").click().run(timeout=900)
    res = at.session_state["bp_result"]
    html = " ".join(h.proto.body for h in at.get("html"))
    check("battery first runs from the page and says so",
          not at.exception and res["inp"].mode == "delayed"
          and "Battery first: a further engine starts only once the gap has lasted longer than 1 h" in html,
          str([e.value[:160] for e in at.exception][:1]))
    at.checkbox(key="bp_tune").check().run(timeout=900)
    at.button(key="bp_run").click().run(timeout=900)
    html = " ".join(h.proto.body for h in at.get("html"))
    check("tuned from the page: the plant's tuned thresholds are named",
          not at.exception and "Thresholds tuned on this plant's year" in html)
    at.radio(key="bp_mode").set_value(MODES[4]).run(timeout=900)
    at.button(key="bp_run").click().run(timeout=1800)
    res = at.session_state["bp_result"]
    html = " ".join(h.proto.body for h in at.get("html"))
    words = _texts(at).lower()
    left = [w for w in BANNED if w in words] + BANNED_WORDS.findall(words)
    check("planned ahead runs from the page, names its forecast, no person or other app named",
          not at.exception and res["inp"].mode == "mpc"
          and "Planned ahead (MPC): every 1 h the engines and the battery are planned 24 h ahead" in html
          and not left, str(left))


if __name__ == "__main__":
    a_same_as_recreate()
    b_defaults()
    c_formulas()
    d_steps()
    e_page()
    f_reference()
    g_periods()
    h_tied()
    i_more_ways()
    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: " + "; ".join(FAILS))
    sys.exit(1 if FAILS else 0)
