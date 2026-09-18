"""Their dispatch_sim day, posed to our optimiser instead of to a rule set.

Same fleet, same fuel curves, same gas price, same grid tariff, same per-running-
hour O&M, same start wear, same battery. The difference is the decision rule:
they apply fixed SOC/margin thresholds without foresight, we solve the hour-ahead
commitment to least cost over the whole day.

One honest limitation up front: this engine is hourly and their sheet is
1-minute. Averaging their day to hours removes 27% of the peak and all the
minute-scale excursions that motivate the battery in the first place, so the
grid import and the start count here are not theirs and cannot be. What this run
does settle is whether their *economic frame* can pay for a battery at all when
the dispatch is chosen optimally rather than by thresholds.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import openpyxl

from reopt_core import model as M
from reopt_core.tariff import flat_tariff

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "chp_bess_analysis")
XL = os.path.join(ROOT, "CHP_BESS_dispatch_sim.xlsx")

# --- straight off the Inputs and FuelCurves sheets -------------------------
FLEET = [("Unit 1 MWM", 1200.0, 0.428, 0.365),      # kW, eff at 100%, eff at 50%
         ("Unit 2 Jenbacher", 1100.0, 0.422, 0.360),
         ("Unit 3 Jenbacher", 1100.0, 0.415, 0.354)]
GAS_PER_KWH = 45_000.0 / (9.5 * 1000.0)   # 45,000 ₸ per 1000 m3, LHV 9.5 kWh/m3
GRID = 50.0                                # ₸/kWh
OM_HOUR = 9_000.0                          # ₸ per engine running hour
WEAR_HOURS = 15.0                          # equivalent run hours per start
BESS_KWH_NOM, BESS_KW = 5_500.0, 2_500.0
SOC_LO, SOC_HI = 0.10, 0.95
RTE = 0.88
AUX_KW = 15.0
CAPEX = 450_000_000.0
DAYS = 330.0
MIN_STABLE = 0.5


def hourly_process_load():
    wb = openpyxl.load_workbook(XL, data_only=True)
    sim = wb["Sim"]
    hdr = [c.value for c in sim[1]]
    ci = hdr.index("Process load (MW)")
    vals = [r[ci] for r in sim.iter_rows(min_row=2, values_only=True) if r[ci] is not None]
    a = np.array(vals[:1440], dtype=float).reshape(24, 60).mean(axis=1)
    return a * 1000.0        # MW -> kW


def scenario(load_kw, *, bess, always_full, start_wear_hours=WEAR_HOURS, om_hour=OM_HOUR):
    turndown = 1.0 if always_full else MIN_STABLE
    fleet = []
    for name, p, eff_full, eff_half in FLEET:
        fleet.append(M.FuelTechInputs(
            enabled=True, kind="Generator", label="CHP", name=name,
            installed_cost_per_kw=0.0, om_cost_per_kw=0.0, om_cost_per_kwh=0.0,
            om_cost_per_running_hour=om_hour,
            # fuel accounted in kWh of gas: one "gallon" = 1 kWh(gas)
            fuel_higher_heating_value_kwh_per_gal=1.0,
            fuel_cost_per_gallon=GAS_PER_KWH,
            electric_efficiency_full_load=eff_full,
            electric_efficiency_half_load=(None if always_full else eff_half),
            min_kw=p, max_kw=p, min_turn_down_fraction=turndown,
            start_cost=start_wear_hours * om_hour,
            min_up_hours=1, min_down_hours=1, can_curtail=True,
            macrs_option_years=0, macrs_bonus_fraction=0.0, federal_itc_fraction=0.0,
        ))
    usable_top = BESS_KWH_NOM * SOC_HI
    bat = M.StorageInputs(
        enabled=bess, name="BESS",
        installed_cost_per_kw=0.0, installed_cost_per_kwh=0.0, installed_cost_constant=0.0,
        om_cost_fraction_of_installed_cost=0.0,
        min_kw=BESS_KW if bess else 0.0, max_kw=BESS_KW,
        min_kwh=usable_top if bess else 0.0, max_kwh=usable_top,
        charge_efficiency=RTE ** 0.5, discharge_efficiency=RTE ** 0.5,
        grid_charge_efficiency=RTE ** 0.5, can_grid_charge=False,
        soc_min_fraction=(BESS_KWH_NOM * SOC_LO) / usable_top,
        macrs_option_years=0, macrs_bonus_fraction=0.0, total_itc_fraction=0.0,
        discharge_cost_per_kwh=0.0,
        # the workbook closes the SoC cycle over its horizon -- REopt's
        # optimize_soc_init_fraction option (electric_storage.jl:209)
        optimize_soc_init_fraction=True,
    )
    fin = M.FinancialInputs(
        analysis_years=1, elec_cost_escalation_rate_fraction=0.0,
        om_cost_escalation_rate_fraction=0.0, offtaker_discount_rate_fraction=0.0,
        offtaker_tax_rate_fraction=0.0, fuel_cost_escalation_rate_fraction=0.0)
    load = [l + (AUX_KW if bess else 0.0) for l in load_kw]
    return M.ScenarioInputs(
        loads_kw=load, tariff=flat_tariff(GRID), financial=fin,
        pv=M.PVInputs(enabled=False), storage=bat,
        fuel_tech=fleet[0], fuel_techs=fleet,
        fuel_intercept_basis="rated",     # scale the curve intercept by nameplate
        compensation_type="no_compensation")


def run(tag, load, **kw):
    t0 = time.time()
    r = M.solve(scenario(load, **kw), time_limit=600, mip_gap=0.0005)
    ser, sz = r["series"], r["sizes"]
    units = sz["fueltech_units"]
    gen = sum(u["energy_kwh"] for u in units)
    spill = sum(u["spill_kwh"] for u in units)
    grid = sum(ser["grid_kw"])
    starts = sum(u["starts"] or 0 for u in units)
    hours = sum(u["running_hours"] for u in units)
    gas = sum(u["fuel_units"] for u in units)          # kWh of gas
    om = r["om"]
    cost = (gas * GAS_PER_KWH + grid * GRID
            + hours * kw.get("om_hour", OM_HOUR)
            + starts * kw.get("start_wear_hours", WEAR_HOURS) * kw.get("om_hour", OM_HOUR))
    out = dict(tag=tag, cost=cost, objective=r["objective_lifecycle_cost"],
               gen_mwh=gen / 1000, gas_mwh=gas / 1000, grid_mwh=grid / 1000,
               spill_mwh=spill / 1000, starts=starts, hours=hours,
               eff_hours=hours + starts * kw.get("start_wear_hours", WEAR_HOURS),
               charge_mwh=sum(ser["battery_charge_kw"]) / 1000,
               discharge_mwh=sum(ser["battery_discharge_kw"]) / 1000,
               seconds=time.time() - t0, status=r["status"],
               gap=(r.get("solver") or {}).get("mip_gap"))
    assert abs(cost - out["objective"]) < 5.0, (cost, out["objective"])
    return out


def main():
    load = hourly_process_load()
    print(f"Их сутки, усреднённые до часов: {load.sum()/1000:.2f} МВт·ч, "
          f"средняя {load.mean()/1000:.3f} МВт, пик {load.max()/1000:.3f} МВт\n")

    rows = []
    for tag, kw in (
        ("без BESS, агрегаты только 100% (их базовая логика)", dict(bess=False, always_full=True)),
        ("без BESS, оптимизатор модулирует 50-100%",           dict(bess=False, always_full=False)),
        ("с BESS, агрегаты только 100% (их правила)",          dict(bess=True,  always_full=True)),
        ("с BESS, оптимизатор модулирует 50-100%",             dict(bess=True,  always_full=False)),
    ):
        r = run(tag, load, **kw)
        rows.append(r)
        print(f"  {tag:<52} {r['cost']:>11,.0f} ₸/сут  газ {r['gas_mwh']:>6.1f}  "
              f"сеть {r['grid_mwh']:>5.2f}  моточасы {r['hours']:>4}  пусков {r['starts']:>2}  "
              f"эфф.часы {r['eff_hours']:>5.1f}  {r['seconds']:>5.1f}s")

    print()
    print("Окупаемость батареи в ИХ экономической рамке, CAPEX 450 млн ₸, 330 дней:")
    for base, alt, lbl in ((0, 2, "их логика: 100%-агрегаты, без -> с BESS"),
                           (1, 3, "оптимизатор: модуляция 50-100%, без -> с BESS"),
                           (1, 2, "честная база (оптимизатор без BESS) -> их правила с BESS")):
        sv = (rows[base]["cost"] - rows[alt]["cost"]) * DAYS
        print(f"   {lbl:<52} {sv:>+14,.0f} ₸/год  ->  "
              f"{'нет окупаемости' if sv <= 0 else f'{CAPEX/sv:.1f} лет'}")
    their_base, their_bess = 1_456_456.378, 1_752_384.552
    print(f"\n   их собственный результат               "
          f"{(their_base-their_bess)*DAYS:>+14,.0f} ₸/год  ->  нет окупаемости")
    print(f"   их базовые сутки {their_base:,.0f} ₸ против нашей лучшей базы "
          f"{min(r['cost'] for r in rows[:2]):,.0f} ₸ "
          f"({(min(r['cost'] for r in rows[:2])-their_base)/their_base:+.1%})")

    os.makedirs(OUT, exist_ok=True)
    io.open(os.path.join(OUT, "dispatch_sim_ours.json"), "w", encoding="utf-8").write(
        json.dumps(rows, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
