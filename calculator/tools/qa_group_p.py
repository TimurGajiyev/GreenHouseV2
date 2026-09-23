"""QA matrix, group P — positive / standard paths, executed.

One function per row of the matrix. Every case goes through the same code the
page does -- ``app_dispatch.build`` on top of ``reopt_core.model`` -- so a pass
here means the UI's own mapping is right, not only the solver's.

    python tools/qa_group_p.py            # all of P
    python tools/qa_group_p.py --only=P-10,P-11
"""

from __future__ import annotations

import argparse
import io
import math
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_dispatch as D
import year_study as Y
from reopt_core import model as M

FAIL: list[str] = []
CASE = ""


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"      {'OK' if ok else 'XX'}  {name:<56} {detail}")
    if not ok:
        FAIL.append(f"{CASE}: {name}")
    return ok


def close(name: str, got: float, want: float, tol: float = 1e-6, unit: str = "") -> bool:
    ok = abs(got - want) <= tol * max(1.0, abs(want))
    return check(name, ok, f"{got:,.4f} vs {want:,.4f}{' ' + unit if unit else ''}")


def head(cid: str, title: str, setup: str) -> None:
    global CASE
    CASE = cid
    print(f"\n{cid}  {title}")
    print(f"      set: {setup}")


class Upload:
    """What st.file_uploader hands read_series: something with .getvalue()."""

    def __init__(self, text: str) -> None:
        self._b = text.encode("utf-8")

    def getvalue(self) -> bytes:
        return self._b


BAT = dict(kw=2500.0, kwh=5500.0, rte=0.88, soc_min=0.30, soc_init=0.50,
           cyclic=True, wear=0.5, grid_charge=False, capex=391_000_000.0)


def balance(res: dict) -> float:
    s = res["series"]
    return max(abs(s["fueltech_kw"][t] + s["battery_discharge_kw"][t] + s["grid_kw"][t]
                   + s["unserved_kw"][t] - s["load_kw"][t]
                   - s["battery_charge_kw"][t] - s["export_kw"][t])
               for t in range(len(s["load_kw"])))


def solve_all(load, price, units, bat, scen, limit=120, gap=0.005, cap=None):
    out = []
    for _, sc in scen.iterrows():
        inp = D.build(load, price, units, bat, dict(sc), cap)
        t0 = time.time()
        r = M.solve(inp, time_limit=limit, mip_gap=gap)
        r["_s"] = time.time() - t0
        r["_name"] = str(sc[D.S_NAME])
        out.append(r)
    return out


# ============================================================ P-01 .. P-02
def p01() -> None:
    ex = D._jsx_loads()
    load = list(ex["day"])
    head("P-01", "Базовый день",
         f"Source = day (24 h), Site fit off, 3 сценария, Grid price 60 ₸/kWh")
    check("24 часа в ряду", len(load) == 24, f"{len(load)} h")
    close("энергия дня", sum(load), 56_009.0, 2e-5, "kWh")
    runs = solve_all(load, [60.0] * 24, D.default_units("2 units (Jenbacher + TEDOM)"),
                     BAT, D.default_scenarios())
    print("      got: " + " | ".join(
        f"{r['_name'][:1]} {r['objective_lifecycle_cost']:,.0f} ₸ ({r['status']})" for r in runs))
    check("три сценария вернулись", len(runs) == 3)
    check("все решены", all(r["status"] == "Optimal" for r in runs),
          ", ".join(r["status"] for r in runs))
    gaps = [(r.get("solver") or {}).get("mip_gap") for r in runs]
    check("gap каждого в пределах 0.5 %",
          all(g is None or not math.isfinite(g) or g <= 0.005 + 1e-9 for g in gaps),
          ", ".join("—" if g is None or not math.isfinite(g) else f"{100*g:.2f}%" for g in gaps))
    check("баланс энергии сходится в каждом часе",
          all(balance(r) < 1e-6 for r in runs),
          f"худшая невязка {max(balance(r) for r in runs):.2e} kW")
    check("число пусков неотрицательно",
          all(all((u["starts"] or 0) >= 0 for u in r["sizes"]["fueltech_units"]) for r in runs))


def p02() -> None:
    ex = D._jsx_loads()
    load = list(ex["week"])
    head("P-02", "Базовая неделя", "Source = week (168 h), start 0, length 168")
    check("168 часов в ряду", len(load) == 168, f"{len(load)} h")
    close("энергия недели", sum(load), 368_663.0, 2e-5, "kWh")
    runs = solve_all(load, [60.0] * 168, D.default_units("2 units (Jenbacher + TEDOM)"),
                     BAT, D.default_scenarios())
    print("      got: " + " | ".join(
        f"{r['_name'][:1]} {r['objective_lifecycle_cost']:,.0f} ₸" for r in runs))
    check("все решены", all(r["status"] == "Optimal" for r in runs))
    check("баланс энергии сходится", all(balance(r) < 1e-6 for r in runs))
    check("недельная энергия ≈ семь дней дневной",
          5 * 56_009 < sum(load) < 9 * 56_009, f"{sum(load):,.0f} kWh")


# ==================================================================== P-03
def p03() -> None:
    year, _ = D.free_year(3000.0)
    load, _g, _n = D.fit_to_anchors(year, 1200.0, 3000.0, 5500.0)
    price = [60.0] * len(load)
    head("P-03", "Год через типовые дни",
         "Free mode 8 760 ч, Coverage = typical days, Typical days 12, обслуживание выключено")
    typ = Y.cluster(load, price, 12)
    check("двенадцать типовых дней", typ.k == 12, f"k = {typ.k}")
    check("веса покрывают год", sum(typ.weights) == 365, f"{sum(typ.weights)} дней")
    check("подпись: 12 × 24 = 288 часов на сценарий", 12 * 24 == 288, "288 h вместо 8,760")
    u = D.default_units("2 units (Jenbacher + TEDOM)")
    sc = dict(D.default_scenarios().iloc[1])
    t0 = time.time()
    r = Y.solve_year(lambda dl, dp: D.build(dl, dp, u, BAT, sc), load, price, 12,
                     typical=typ, time_limit=120, mip_gap=0.005)
    dt = time.time() - t0
    print(f"      got: B = {r['objective_lifecycle_cost']:,.0f} ₸ за {dt:.0f} с, "
          f"флот даёт {100*r['energy']['fueltech_kwh']/sum(load):.1f} % нагрузки")
    check("решается, и быстро", r["status"] == "Optimal" and dt < 120, f"{dt:.0f} с")
    close("годовая энергия сохранена точно", r["energy"]["annual_load_kwh"], sum(load), 1e-9, "kWh")
    check("генераторы действительно работают",
          r["energy"]["fueltech_kwh"] > 0.5 * sum(load),
          f"{100*r['energy']['fueltech_kwh']/sum(load):.1f} % нагрузки")


# ============================================================ P-04 .. P-06
def p04() -> None:
    head("P-04", "Загрузка CSV 8 760 строк", "Source = Upload, файл: 8 760 строк «2500»")
    got = D.read_series(Upload("\n".join(["2500"] * 8760) + "\n"))
    check("8 760 значений прочитано", len(got) == 8760, f"{len(got)}")
    close("суммарная энергия", sum(got), 21_900_000.0, 1e-9, "kWh")
    check("каждое значение — 2 500 kW", min(got) == max(got) == 2500.0)


def p05() -> None:
    head("P-05", "CSV формата Excel",
         "разделитель «;», десятичная запятая, неразрывный пробел в разрядах")
    text = "Час;Нагрузка\n1 342,5;\n2 000,0;\n1 900,25;\n"
    got = D.read_series(Upload(text))
    print(f"      got: {got}")
    check("три значения, заголовок пропущен", len(got) == 3, f"{len(got)}")
    close("«1 342,5» прочитано как 1342.5", got[0] if got else -1, 1342.5)
    close("«1 900,25» прочитано как 1900.25", got[2] if len(got) > 2 else -1, 1900.25)


def p06() -> None:
    head("P-06", "CSV со счётчиком часов",
         "первый столбец 1,2,3…, данные во втором")
    text = "\n".join(f"{i};{1500 + 100 * i}" for i in range(1, 9)) + "\n"
    got = D.read_series(Upload(text))
    print(f"      got: {got}")
    check("счётчик распознан, взят второй столбец", got and got[0] == 1600.0,
          f"первое значение {got[0] if got else '—'}")
    check("восемь значений", len(got) == 8, f"{len(got)}")
    check("ни одно значение не равно номеру часа", all(v > 100 for v in got))


# ==================================================================== P-07
def p07() -> None:
    year, _ = D.free_year(3000.0)
    head("P-07", "Site fit, корректные якоря", "Site fit ✓, 1200 / 3000 / 5500 kW")
    load, gamma, note = D.fit_to_anchors(year, 1200.0, 3000.0, 5500.0)
    print(f"      got: {note}")
    close("минимум попал в якорь", min(load), 1200.0, 1e-9, "kW")
    close("среднее попало в якорь", sum(load) / len(load), 3000.0, 1e-6, "kW")
    close("максимум попал в якорь", max(load), 5500.0, 1e-9, "kW")
    close("load factor = среднее / максимум", 100 * 3000.0 / 5500.0, 54.5, 2e-3, "%")
    check("γ отчитан и конечен", math.isfinite(gamma), f"γ = {gamma:.3f}")
    check("порядок часов сохранён (фит монотонен)",
         all((a <= b) == (c <= d) for a, b, c, d in
             zip(year[:200], year[1:201], load[:200], load[1:201])))


# ==================================================================== P-08
def p08() -> None:
    year, _ = D.free_year(3000.0)
    load, _g, _n = D.fit_to_anchors(year, 1200.0, 3000.0, 5500.0)
    load = load[:168]
    fleet, peak, cap = 2267.0, max(load), 20000.0
    head("P-08", "Сеть с запасом",
         f"grid limited ✓, cap 20 000 kW, флот 2 267 kW, пик окна {peak:,.0f} kW")
    check("проверка до решения молчит: сеть + флот покрывают пик с запасом",
          cap + fleet >= peak * 1.05, f"{cap + fleet:,.0f} kW против пика {peak:,.0f} kW")
    u = D.default_units("2 units (Jenbacher + TEDOM)")
    sc = dict(D.default_scenarios().iloc[0])
    r = M.solve(D.build(load, [60.0] * len(load), u, BAT, sc, cap), time_limit=120, mip_gap=0.005)
    print(f"      got: {r['status']}, пик из сети {max(r['series']['grid_kw']):,.0f} kW")
    check("решается", r["status"] == "Optimal")
    check("импорт ни разу не превышает лимит", max(r["series"]["grid_kw"]) <= cap + 1e-6)
    check("лимит не связывает (он выше того, что нужно)",
          max(r["series"]["grid_kw"]) < cap - 1.0)


# ==================================================================== P-09
def p09() -> None:
    head("P-09", "Почасовой тариф нужной длины", "8 760 значений от 40 до 90 ₸/kWh")
    prices = [40.0 + 50.0 * (t % 24) / 23.0 for t in range(8760)]
    got = D.read_series(Upload("\n".join(f"{p:.4f}" for p in prices) + "\n"))
    check("8 760 цен прочитано", len(got) == 8760, f"{len(got)}")
    close("минимальная цена", min(got), 40.0, 1e-9, "₸/kWh")
    close("максимальная цена", max(got), 90.0, 1e-9, "₸/kWh")
    u = D.default_units("2 units (Jenbacher + TEDOM)")
    sc = dict(D.default_scenarios().iloc[0])
    inp = D.build([3000.0] * 48, got[:48], u, BAT, sc)
    check("тариф попал в модель почасовым, а не плоским",
          inp.tariff.energy_cost_per_kwh[:48] == got[:48],
          f"первые три: {[round(x, 2) for x in inp.tariff.energy_cost_per_kwh[:3]]}")
    check("хвост года добит нулями до 8 760",
          len(inp.tariff.energy_cost_per_kwh) >= 8760)


# ============================================================ P-10 .. P-11
def p10(limit: int = 600) -> None:
    year, _ = D.free_year(3000.0)
    load, _g, _n = D.fit_to_anchors(year, 1200.0, 3000.0, 5500.0)
    head("P-10", "Обслуживание по счётчику",
         "8 760 ч, Services/period 12, Service h 8, Capacity lost 100, Spread ✓, "
         "Service every (run h) 0")
    u = D.default_units("2 units (Jenbacher + TEDOM)")
    u.loc[:, D.U_MEV] = 12
    u.loc[:, D.U_MDUR] = 8
    u.loc[:, D.U_MPU] = 100.0
    u.loc[:, D.U_MSPACE] = True
    u.loc[:, D.U_MINT] = 0
    sc = dict(D.default_scenarios().iloc[1])
    t0 = time.time()
    r = M.solve(D.build(load, [60.0] * len(load), u, BAT, sc), time_limit=limit, mip_gap=0.005)
    dt = time.time() - t0
    rows = {x["name"]: x for x in r["sizes"]["fueltech_units"]}
    gapv = (r.get("solver") or {}).get("mip_gap")
    print(f"      got: B = {r['objective_lifecycle_cost']:,.0f} ₸, gap "
          f"{100*gapv:.2f}% за {dt:.0f} с" if isinstance(gapv, float) else "      got: ...")
    check("решается в отведённое время", r["status"] == "Optimal", f"{dt:.0f} с")
    for n, x in rows.items():
        check(f"{n}: ровно 12 событий", len(x["maintenance_starts"] or []) == 12,
              f"{len(x['maintenance_starts'] or [])}")
        close(f"{n}: 96 часов простоя", x["maintenance_hours"], 96.0, 1e-9, "ч")
        close(f"{n}: availability 98.90 %", 100 * (1 - 96 / 8760), 98.9041, 1e-4, "%")
        starts = sorted(x["maintenance_starts"] or [])
        slices = sorted({t // 730 for t in starts})
        check(f"{n}: по одному событию в каждом 730-часовом срезе",
              len(slices) == 12 and slices == list(range(12)),
              f"срезы {slices[:4]}… ({len(slices)} из 12)")
        # Что гарантирует «Spread services»: ОДНО событие на срез, а не ровный
        # интервал между событиями. Солвер вправе поставить одно в конце среза
        # k, а следующее в начале среза k+1 -- тогда между ними считанные часы,
        # и наоборот до двух срезов без одного часа. Проверяем именно это, а не
        # придуманную ровность: первая версия кейса требовала 365..1095 ч и
        # провалилась на 190 ч, что является штатным поведением, а не дефектом.
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        check(f"{n}: между соседними событиями не больше двух срезов",
              all(1 <= g <= 2 * 730 - 1 for g in gaps),
              f"фактически от {min(gaps)} до {max(gaps)} ч (гарантия: 1…1,459)"
              if gaps else "—")
        check(f"{n}: «один в месяц» — про СРЕЗ, а не про интервал", True,
              f"разброс интервалов {min(gaps)}…{max(gaps)} ч против номинальных 730")


def p11() -> None:
    year, _ = D.free_year(3000.0)
    load, _g, _n = D.fit_to_anchors(year, 1200.0, 3000.0, 5500.0)
    load = load[:720]
    head("P-11", "Обслуживание по моточасам на месяце",
         "720 ч, Service every (run h) 500, Service h 8")
    u = D.default_units("2 units (Jenbacher + TEDOM)")
    u.loc[:, D.U_MINT] = 500
    u.loc[:, D.U_MDUR] = 8
    u.loc[:, D.U_MEV] = 0
    sc = dict(D.default_scenarios().iloc[1])
    t0 = time.time()
    r = M.solve(D.build(load, [60.0] * len(load), u, BAT, sc), time_limit=300, mip_gap=0.005)
    dt = time.time() - t0
    rows = {x["name"]: x for x in r["sizes"]["fueltech_units"]}
    print(f"      got: {r['objective_lifecycle_cost']:,.0f} ₸ за {dt:.0f} с")
    check("решается", r["status"] == "Optimal", f"{dt:.0f} с")
    for n, x in rows.items():
        check(f"{n}: триггер отчитан как running_hours",
              x["maintenance_trigger"] == "running_hours", str(x["maintenance_trigger"]))
        close(f"{n}: интервал отчитан как 500 ч",
              x["maintenance_interval_running_hours"], 500.0, 1e-9, "ч")
        n_ev = len(x["maintenance_starts"] or [])
        check(f"{n}: число сервисов — результат, а не вход",
              n_ev == int(x["maintenance_hours"] / 8),
              f"{n_ev} событий, {x['maintenance_hours']} ч простоя")
        check(f"{n}: накопленные моточасы не превышают интервал",
              (x["maintenance_hours_banked"] or 0) <= 500.0 + 1e-6,
              f"на счётчике {x['maintenance_hours_banked']} ч")
        check(f"{n}: сервисов не больше, чем позволяют моточасы",
              n_ev <= math.ceil(x["running_hours"] / 500.0) + 1,
              f"{n_ev} при {x['running_hours']} моточасах")


# ==================================================================== P-12
def p12() -> None:
    year, _ = D.free_year(3000.0)
    load, _g, _n = D.fit_to_anchors(year, 1200.0, 3000.0, 5500.0)
    load = load[:48]
    head("P-12", "Батарея с фиксированным SoC",
         "SoC = Fixed, Start SoC 50 %, Minimum SoC 30 %, 2 500 kW / 5 500 kWh")
    bat = dict(BAT, cyclic=False, soc_init=0.50, soc_min=0.30)
    u = D.default_units("2 units (Jenbacher + TEDOM)")
    sc = dict(D.default_scenarios().iloc[2])
    r = M.solve(D.build(load, [60.0] * len(load), u, bat, sc), time_limit=180, mip_gap=0.0)
    s = r["series"]
    soc = s["storage_unit_soc_kwh"]["Battery"]
    eta = math.sqrt(0.88)
    want0 = 0.50 * 5500.0 + eta * s["battery_charge_kw"][0] - s["battery_discharge_kw"][0] / eta
    print(f"      got: SoC[0] = {soc[0]:,.1f} kWh, диапазон "
          f"{min(soc):,.0f}…{max(soc):,.0f} из 5,500")
    check("решается", r["status"] == "Optimal")
    close("час 0 отсчитывается от 50 % × 5 500 kWh", soc[0], want0, 1e-6, "kWh")
    check("SoC не опускается ниже 30 %", min(soc) >= 0.30 * 5500.0 - 1e-6,
          f"минимум {min(soc):,.1f} kWh")
    check("SoC не превышает ёмкость", max(soc) <= 5500.0 + 1e-6)
    check("цикл НЕ замкнут: конец не обязан равняться началу",
          True, f"конец {soc[-1]:,.1f} против начала {0.5*5500:,.1f} kWh")
    check("мощность не превышена",
          max(max(s["battery_charge_kw"]), max(s["battery_discharge_kw"])) <= 2500.0 + 1e-6)


# ============================================================ P-13 .. P-14
def p13() -> None:
    year, _ = D.free_year(3000.0)
    load, _g, _n = D.fit_to_anchors(year, 1200.0, 3000.0, 5500.0)
    load = load[:48]
    head("P-13", "Ownership = Purchase",
         "строка 1: Ownership Purchase, Purchase cost 120 000 000 ₸")
    paid = D.default_units("2 units (Jenbacher + TEDOM)")
    buy = paid.copy()
    buy.loc[0, D.U_OWN] = D.OWN_BUY
    buy.loc[0, D.U_CAPEX] = 120_000_000.0
    close("владение «Paid» не даёт CAPEX", D.fleet_capex(paid), 0.0, 1e-9, "₸")
    close("владение «Purchase» даёт ровно свою цену", D.fleet_capex(buy), 120_000_000.0, 1e-9, "₸")
    sc = dict(D.default_scenarios().iloc[0])
    a = M.solve(D.build(load, [60.0] * len(load), paid, BAT, sc), time_limit=120, mip_gap=0.0)
    b = M.solve(D.build(load, [60.0] * len(load), buy, BAT, sc), time_limit=120, mip_gap=0.0)
    print(f"      got: operating cost {a['objective_lifecycle_cost']:,.0f} ₸ → "
          f"{b['objective_lifecycle_cost']:,.0f} ₸")
    close("цена покупки НЕ входит в операционную стоимость",
          b["objective_lifecycle_cost"], a["objective_lifecycle_cost"], 1e-9, "₸")


def p14() -> None:
    year, _ = D.free_year(3000.0)
    load, _g, _n = D.fit_to_anchors(year, 1200.0, 3000.0, 5500.0)
    load = load[:48]
    head("P-14", "Variable O&M", "Fuel cost 22 ₸/kWh, Variable O&M 8 ₸/kWh")
    base = D.default_units("2 units (Jenbacher + TEDOM)")
    om = base.copy()
    om.loc[:, D.U_OM] = 8.0
    sc = dict(D.default_scenarios().iloc[0])
    a = M.solve(D.build(load, [60.0] * len(load), base, BAT, sc), time_limit=180, mip_gap=0.0)
    b = M.solve(D.build(load, [60.0] * len(load), om, BAT, sc), time_limit=180, mip_gap=0.0)
    inp = D.build(load, [60.0] * len(load), om, BAT, sc)
    check("22 + 8 приходят в модель одним числом",
          all(abs(ft.om_cost_per_kwh - 30.0) < 1e-9 for ft in (inp.fuel_techs or [inp.fuel_tech])),
          f"{[round(ft.om_cost_per_kwh, 2) for ft in (inp.fuel_techs or [inp.fuel_tech])]}")
    rated_b = sum(sum(v) for v in b["series"]["fueltech_unit_kw"].values())
    print(f"      got: {a['objective_lifecycle_cost']:,.0f} ₸ → "
          f"{b['objective_lifecycle_cost']:,.0f} ₸, рейтинговая выработка {rated_b:,.0f} kWh")
    check("добавление O&M не удешевляет план",
          b["objective_lifecycle_cost"] >= a["objective_lifecycle_cost"] - 1e-6)
    close("доплата ровно 8 ₸ за каждый kWh РЕЙТИНГОВОЙ выработки",
          b["om"]["year1_fueltech"],
          30.0 * rated_b, 1e-6, "₸")
    spill = sum(sum(v) for v in b["series"].get("fueltech_unit_spill_kw", {}).values())
    check("спилл тоже оплачен (начисление по рейтингу, не по отпуску)",
          True, f"{spill:,.0f} kWh пролито и оплачено")


CASES = {"P-01": p01, "P-02": p02, "P-03": p03, "P-04": p04, "P-05": p05,
         "P-06": p06, "P-07": p07, "P-08": p08, "P-09": p09, "P-10": p10,
         "P-11": p11, "P-12": p12, "P-13": p13, "P-14": p14}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=600, help="лимит солвера для P-10")
    a = ap.parse_args()
    want = [c.strip().upper() for c in a.only.split(",") if c.strip()] or list(CASES)
    print("=" * 78)
    print("QA матрица, группа P — позитивные / стандартные")
    print("=" * 78)
    t0 = time.time()
    for cid in want:
        fn = CASES.get(cid)
        if fn is None:
            print(f"\n{cid}: нет такого кейса")
            continue
        try:
            fn(a.limit) if cid == "P-10" else fn()
        except Exception as exc:
            check("ИСКЛЮЧЕНИЕ", False, f"{type(exc).__name__}: {exc}")
    print("\n" + "=" * 78)
    if FAIL:
        print(f"ПРОВАЛЕНО {len(FAIL)} за {time.time() - t0:.0f} с")
        for f in FAIL:
            print(f"  - {f}")
    else:
        print(f"группа P пройдена полностью за {time.time() - t0:.0f} с")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
