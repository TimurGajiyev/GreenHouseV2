"""Run the profiling artifact's own example through this engine and compare.

`bess_profile_v2.jsx` ships its results inline: a 24-hour day and a 168-hour
week for two fleets (2 and 3 engines) under three operating rules, plus the
annual summary. Those rows come from a causal rule-based controller.

This script takes the artifact's own load profile and its own prices, poses the
identical problem to this MILP, and puts the two answers side by side. Because
the constraints are the same and this solver has perfect foresight over the
horizon, each of our costs is a lower bound on theirs: the difference is what
their controller leaves on the table, not a disagreement about physics.

    python tools/jsx_case.py day      24-hour case, both fleets, modes A/B/C
    python tools/jsx_case.py week     168-hour case (slower, binaries)
    python tools/jsx_case.py check    only verify the artifact's own arithmetic
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import model as M

import chp_bess_suite as S

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JSX = os.path.join(ROOT, "bess_profile_v2.jsx")
OUT = os.path.join(ROOT, "chp_bess_analysis")

# the artifact's own constants, read off the top of the file
KZT_CHP, KZT_GRID, KZT_START, KZT_CYCLE = 22.0, 60.0, 15_000.0, 0.5
MODE_NAME = {"A": "Свободный 50%", "B": "Правило 90%", "C": "90% + BESS"}


def load_jsx() -> tuple[dict, dict, dict]:
    src = io.open(JSX, encoding="utf-8").read()
    out = []
    for name in ("DATA", "SUMMARY", "PROFILES"):
        m = re.search(rf"^const {name} = (.*?);$", src, re.M | re.S)
        out.append(json.loads(m.group(1)))
    return tuple(out)


# --------------------------------------------------------------- their side
def their_totals(rows: list[list[float]]) -> dict:
    """`totals()` and `money()` from the artifact, transcribed."""
    col = lambda k: sum(r[k] for r in rows)
    return dict(
        load=col(0), chp=col(1), ch=col(2), dis=col(3), grid=col(5),
        starts=col(6), spill=col(8), peak=max(r[5] for r in rows),
        cost=sum(r[1] * KZT_CHP + r[5] * KZT_GRID + r[6] * KZT_START
                 + r[3] * KZT_CYCLE for r in rows),
    )


def check_theirs(data: dict) -> list[str]:
    """Does the artifact reconcile with itself?"""
    bad = []
    for fk, cfg in data.items():
        for per in ("day", "week"):
            for md, d in cfg[per].items():
                rows, gen = d["rows"], d["gen"]
                for i, (r, g) in enumerate(zip(rows, gen)):
                    load, chp, ch, dis, soc, grid, st, uon, spill = r
                    # the per-unit columns must add up to the fleet column
                    if abs(sum(g) - chp) > 1.0:
                        bad.append(f"{fk}/{per}/{md} h{i}: units {sum(g):,.0f} != chp {chp:,.0f}")
                        break
                    # supply must meet demand: net generation + discharge + grid
                    net = chp - spill
                    if abs((net + dis + grid) - (load + ch)) > 1.0:
                        bad.append(f"{fk}/{per}/{md} h{i}: balance off by "
                                   f"{(net + dis + grid) - (load + ch):,.1f} kW")
                        break
                    if ch > 1e-6 and dis > 1e-6:
                        bad.append(f"{fk}/{per}/{md} h{i}: charging and discharging together")
                        break
    return bad


# ----------------------------------------------------------------- our side
def ours(load: list[float], fleet_key: str, mode: str, *, time_limit: int,
         mip_gap: float | None) -> dict:
    t0 = time.time()
    res = M.solve(S.scenario(load, fleet_key, mode), time_limit=time_limit,
                  mip_gap=mip_gap)
    acc = S.account(res, load)
    acc["seconds"] = time.time() - t0
    acc["peak"] = acc.pop("grid_peak_kw")
    return acc


# ------------------------------------------------------------------- report
def compare(per: str, data: dict, *, time_limit: int, mip_gap: float | None) -> list[dict]:
    rows_out = []
    for fk in ("chp2", "chp3"):
        cfg = data[fk]
        names = " + ".join(cfg["names"])
        print(f"\n{'=' * 96}")
        print(f"{cfg['label']}  ({names})   потолок {cfg['pchp']:,} кВт   "
              f"BESS {cfg['cap']:,.0f} кВт·ч")
        print("=" * 96)
        base = cfg[per]["B"]
        for md in ("A", "B", "C"):
            d = cfg[per][md]
            load = [r[0] for r in d["rows"]]
            t = their_totals(d["rows"])
            o = ours(load, fk, md, time_limit=time_limit, mip_gap=mip_gap)
            gap = (o["cost"] - t["cost"]) / t["cost"]
            print(f"\n  {md}. {MODE_NAME[md]}   нагрузка {t['load']:,.0f} кВт·ч")
            print(f"     {'':<22}{'артефакт':>16}{'наш MILP':>16}{'разница':>14}")
            for lab, key, fmt in (
                ("стоимость, ₸", "cost", ",.0f"),
                ("выработка КГУ, кВт·ч", "chp", ",.0f"),
                ("закуп из сети, кВт·ч", "grid", ",.0f"),
                ("пик закупа, кВт", "peak", ",.0f"),
                ("пусков", "starts", ",.0f"),
                ("сброс, кВт·ч", "spill", ",.0f"),
                ("заряд, кВт·ч", "ch", ",.0f"),
                ("разряд, кВт·ч", "dis", ",.0f"),
            ):
                ours_key = {"chp": "chp_kwh", "grid": "grid_kwh", "spill": "spill_kwh",
                            "ch": "charge_kwh", "dis": "discharge_kwh"}.get(key, key)
                a, b = t[key], o[ours_key]
                print(f"     {lab:<22}{a:>16{fmt}}{b:>16{fmt}}{b - a:>+14{fmt}}")
            note = ""
            if o.get("mip_gap") is not None and o["mip_gap"] > 5e-4:
                note = f"   [зазор MIP {o['mip_gap']:.2%}, наша цифра — верхняя граница]"
            print(f"     {'итог':<22}{'':>16}{'':>16}{gap:>+13.2%}{note}")
            rows_out.append(dict(fleet=fk, period=per, mode=md, theirs=t, ours=o, delta=gap))

        # what the battery is worth, on each side, against the 90% rule
        tb, tc = their_totals(cfg[per]["B"]["rows"]), their_totals(cfg[per]["C"]["rows"])
        ob = next(r for r in rows_out if r["fleet"] == fk and r["mode"] == "B")["ours"]
        oc = next(r for r in rows_out if r["fleet"] == fk and r["mode"] == "C")["ours"]
        print(f"\n  ценность BESS против правила 90% (B -> C), за {per}:")
        print(f"     артефакт {tb['cost'] - tc['cost']:>+14,.0f} ₸      "
              f"наш MILP {ob['cost'] - oc['cost']:>+14,.0f} ₸")
        ta = their_totals(cfg[per]["A"]["rows"])
        oa = next(r for r in rows_out if r["fleet"] == fk and r["mode"] == "A")["ours"]
        print(f"  цена правила 90% (A -> B), за {per}:")
        print(f"     артефакт {tb['cost'] - ta['cost']:>+14,.0f} ₸      "
              f"наш MILP {ob['cost'] - oa['cost']:>+14,.0f} ₸")
    return rows_out


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "day"
    data, summary, profiles = load_jsx()

    print("Проверка арифметики самого артефакта")
    bad = check_theirs(data)
    if bad:
        print(f"  {len(bad)} расхождений:")
        for b in bad[:10]:
            print("   -", b)
    else:
        n = sum(len(cfg[p][m]["rows"]) for cfg in data.values()
                for p in ("day", "week") for m in ("A", "B", "C"))
        print(f"  OK  {n:,} часов: столбцы агрегатов сходятся с колонкой КГУ, "
              f"баланс мощности сходится, одновременного заряда и разряда нет")
    if what == "check":
        return

    per = "week" if what == "week" else "day"
    tl = 600 if per == "week" else 120
    gap = 0.0005 if per == "week" else None
    rows = compare(per, data, time_limit=tl, mip_gap=gap)

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"jsx_case_{per}.json")
    io.open(path, "w", encoding="utf-8").write(
        json.dumps(rows, ensure_ascii=False, indent=1, default=float))
    print(f"\nсохранено -> chp_bess_analysis/jsx_case_{per}.json")


if __name__ == "__main__":
    main()
