"""Render the artifact's case through our profiling view and compare cell by cell.

Two questions, kept apart:

  structure   does our table carry the same columns, in the same order, with the
              same number of rows and the same total row?
  values      where the two dispatches agree, do the cells agree?

They are separate because our dispatch is not theirs — this engine is cheaper on
five of the six cases — so a value difference is expected wherever the solutions
differ. The one case where both sides land on the same schedule (two engines,
free modulation, no battery) is the one where every shared cell must match.

    python tools/jsx_render_check.py          compare, print the report
    python tools/jsx_render_check.py page     also write the HTML for capture
"""

from __future__ import annotations

import io
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# This report prints the artifact's own headers and totals, which carry the
# minus sign U+2212, the middle dot and the tenge. Redirected to a file on a
# Russian Windows, stdout defaults to cp1251 and the first of those raises,
# so the run fails on a print rather than on anything it checked.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                   # pragma: no cover
    pass

import jsx_case as J
import profile_ui as P
import app_periods as A
import chp_bess_suite as S
from reopt_core import model as M

OUT = os.path.join(J.ROOT, "chp_bess_analysis")
SHOTS = os.path.join(J.ROOT, "screenshots")
DN = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
FAIL: list[str] = []


def nf(v) -> str:
    return f"{round(v):,}".replace(",", " ")


# --------------------------------------------------------- the artifact's tables
def their_day_table(cfg, md) -> dict:
    """`dayTable` from bess_profile_v2.jsx, transcribed."""
    d = cfg["day"][md]
    head = ["Час", "Нагрузка", *cfg["names"], "Заряд +", "Разряд −", "Сеть", "SoC %"]
    rows = [[str(i + 1), nf(r[0]), *[nf(g) for g in d["gen"][i]], nf(r[2]),
             ("−" + nf(r[3])) if r[3] else "0", nf(r[5]), f"{r[4]:.1f}"]
            for i, r in enumerate(d["rows"])]
    t = J.their_totals(d["rows"])
    gs = [sum(g[j] for g in d["gen"]) for j in range(len(cfg["names"]))]
    foot = ["Итого", nf(t["load"]), *[nf(x) for x in gs], nf(t["ch"]),
            "−" + nf(t["dis"]), nf(t["grid"]), ""]
    return {"head": head, "rows": rows, "foot": foot}


def their_week_table(cfg, md) -> dict:
    d = cfg["week"][md]
    head = ["День", "Нагрузка", *cfg["names"], "Заряд +", "Разряд −", "Сеть",
            "Пик", "Пусков"]
    rows = []
    for k, dn in enumerate(DN):
        seg, gseg = d["rows"][k * 24:k * 24 + 24], d["gen"][k * 24:k * 24 + 24]
        t = J.their_totals(seg)
        rows.append([dn, nf(t["load"]),
                     *[nf(sum(g[j] for g in gseg)) for j in range(len(cfg["names"]))],
                     nf(t["ch"]), "−" + nf(t["dis"]), nf(t["grid"]),
                     nf(t["peak"]), str(int(t["starts"]))])
    return {"head": head, "rows": rows}


def their_hour_week_table(cfg, md) -> dict:
    d = cfg["week"][md]
    head = ["День", "Час", "Нагрузка", *cfg["names"], "Заряд +", "Разряд −",
            "Сеть", "SoC %"]
    rows = [[DN[i // 24], str(i % 24 + 1), nf(r[0]), *[nf(g) for g in d["gen"][i]],
             nf(r[2]), ("−" + nf(r[3])) if r[3] else "0", nf(r[5]), f"{r[4]:.1f}"]
            for i, r in enumerate(d["rows"])]
    return {"head": head, "rows": rows}


# ------------------------------------------------------------------- our tables
def our_tables(res, per: str) -> dict:
    """Exactly what render_periods puts on the page, without a Streamlit runtime."""
    series = res["series"]
    sh = A._shape(res)
    H = A.horizon(series)
    n_h = min(24, H) if per == "day" else min(168, H)
    rows = A._window_rows(series, sh, 0, n_h)
    if per == "day":
        return {"head": A._hour_head(sh, "HOUR"),
                "rows": [A._hour_row(r, sh, str(i + 1)) for i, r in enumerate(rows)],
                "foot": A._hour_foot(rows, sh), "shape": sh}
    return {"head": A._hour_head(sh, "DAY", "HOUR"),
            "rows": [A._hour_row(r, sh, DN[i // 24], str(i % 24 + 1))
                     for i, r in enumerate(rows)],
            "foot": A._hour_foot(rows, sh, pad=1), "shape": sh}


# ------------------------------------------------------------------- comparison
EXPECT = {                      # their column -> ours, by meaning
    "Час": "HOUR", "День": "DAY", "Нагрузка": "LOAD", "Заряд +": "CHARGE +",
    "Разряд −": "DISCHARGE −", "Сеть": "GRID", "SoC %": "SOC %",
    "Пик": "PEAK GRID", "Пусков": "STARTS",
}


def _cell(c) -> str:
    return c[0] if isinstance(c, tuple) else str(c)


def compare_structure(tag: str, theirs: dict, ours: dict, has_bess: bool) -> None:
    th, oh = theirs["head"], ours["head"]
    # unit names are rendered uppercase on our side; compare them case-blind
    want = [EXPECT.get(c, c.upper()) for c in th]
    oh_cmp = [c.upper() for c in oh]
    if not has_bess:
        # no battery in this scenario, so the three battery columns are not drawn
        want = [c for c in want if c not in ("CHARGE +", "DISCHARGE −", "SOC %")]
    missing = [c for c in want if c not in oh_cmp]
    extra = [c for c in oh if c.upper() not in want]
    order_ok = [c for c in oh_cmp if c in want] == want
    print(f"    их колонки : {' | '.join(th)}")
    print(f"    наши       : {' | '.join(oh)}")
    if missing:
        FAIL.append(f"{tag}: нет колонок {missing}")
        print(f"    XX  отсутствуют: {missing}")
    if not order_ok:
        FAIL.append(f"{tag}: порядок колонок отличается")
        print("    XX  порядок общих колонок отличается")
    if not missing and order_ok:
        print(f"    OK  все {len(want)} колонок эталона на месте и в том же порядке"
              + (f"; сверх них наши {extra}" if extra else ""))
    if len(theirs["rows"]) != len(ours["rows"]):
        FAIL.append(f"{tag}: {len(ours['rows'])} строк против {len(theirs['rows'])}")
        print(f"    XX  строк {len(ours['rows'])} против {len(theirs['rows'])}")
    else:
        print(f"    OK  {len(ours['rows'])} строк, как в эталоне")
    tf, of = theirs.get("foot"), ours.get("foot")
    if tf and of:
        n_extra = len(of) - len([c for c in want if c in oh_cmp])
        print(f"    строка итогов: их {' | '.join(str(x) for x in tf)}")
        print(f"                   наша {' | '.join(_cell(x) for x in of)}")


def compare_values(tag: str, cfg, md, res, per: str) -> None:
    """Per-hour agreement, column by column, on the quantities both sides carry."""
    d = cfg[per][md]
    ser = res["series"]
    sh = A._shape(res)
    n = len(d["rows"])
    names = sh["names"]
    per_unit = ser.get("fueltech_unit_kw") or {}
    cols = {
        "нагрузка": ([r[0] for r in d["rows"]], ser["load_kw"]),
        "выработка парка": ([r[1] for r in d["rows"]],
                            [sum(per_unit.get(nm, [0.0] * n)[t] for nm in names)
                             + (ser.get("fueltech_unit_spill_kw") and 0 or 0)
                             for t in range(n)]),
        "закуп из сети": ([r[5] for r in d["rows"]], ser["grid_kw"]),
        "заряд": ([r[2] for r in d["rows"]], ser["battery_charge_kw"]),
        "разряд": ([r[3] for r in d["rows"]], ser["battery_discharge_kw"]),
    }
    print(f"    {'величина':<18}{'макс. расхождение':>20}{'часов различаются':>20}")
    for lab, (a, b) in cols.items():
        diffs = [abs(a[t] - b[t]) for t in range(n)]
        bad = sum(1 for x in diffs if x > 1.0)
        print(f"    {lab:<18}{max(diffs):>17,.1f} кВт{bad:>17} / {n}")
    # per-unit split: identical prices make it degenerate, only the sum is pinned
    if len(names) > 1:
        worst = max(abs(d["gen"][t][j] - per_unit.get(names[j], [0.0] * n)[t])
                    for t in range(n) for j in range(len(names)))
        print(f"    {'разбивка по агрегатам':<18}{worst:>13,.1f} кВт   "
              f"(цены агрегатов равны -> расщепление вырождено)")


def main():
    data, _, _ = J.load_jsx()
    want_page = len(sys.argv) > 1 and sys.argv[1] == "page"
    pages = {}

    for fk in ("chp2", "chp3"):
        cfg = data[fk]
        for md in ("A", "C"):
            tag = f"{cfg['label']} / {J.MODE_NAME[md]}"
            load = [r[0] for r in cfg["day"][md]["rows"]]
            res = M.solve(S.scenario(load, fk, md), time_limit=300)
            ours = our_tables(res, "day")
            theirs = their_day_table(cfg, md)
            print(f"\n{'=' * 92}\n  СУТКИ · {tag}\n{'=' * 92}")
            compare_structure(tag + " / сутки", theirs, ours,
                              has_bess=bool(S.MODES[md]["bess"]))
            compare_values(tag + " / сутки", cfg, md, res, "day")
            if want_page and fk == "chp2" and md == "C":
                pages["day"] = (res, cfg, md)

    if want_page:
        render_page(*pages["day"])

    print("\n" + "=" * 92)
    if FAIL:
        print(f"{len(FAIL)} РАСХОЖДЕНИЙ:")
        for f in FAIL:
            print("  -", f)
        sys.exit(1)
    print("структура таблиц совпадает с эталоном во всех проверенных случаях")


def render_page(res, cfg, md) -> None:
    """Draw the block into a standalone page so it can be captured."""
    html: list[str] = []
    stub = types.SimpleNamespace(
        html=lambda b, **k: html.append(str(b)), markdown=lambda b, **k: html.append(str(b)),
        caption=lambda *a, **k: None, write=lambda *a, **k: None,
        altair_chart=lambda *a, **k: None,
        columns=lambda spec, **k: [_C() for _ in range(spec if isinstance(spec, int) else len(spec))],
        expander=lambda *a, **k: _C(), container=lambda *a, **k: _C(),
        segmented_control=lambda l, o, **k: o[0], radio=lambda l, o, **k: o[0],
        dataframe=lambda *a, **k: None, divider=lambda *a, **k: None)
    import ui_theme
    for mod in (A, P, ui_theme):
        mod.st = stub
    A.render_periods({"res": res, "tariff": None})
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, "jsx_case_block.html")
    io.open(path, "w", encoding="utf-8").write(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='margin:0;padding:24px;background:#EEF1F4'>"
        + P._CSS + "".join(html) + "</body>")
    print(f"\nстраница для снимка -> screenshots/jsx_case_block.html")


class _C:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


if __name__ == "__main__":
    main()
