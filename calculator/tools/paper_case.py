"""The Sigalo et al. 2023 case, built from the paper's own tables, solved here.

  "Real-Time Economic Dispatch of CHP Systems with Battery Energy Storage for
   Behind-the-Meter Applications", Energies 16(1274), 2023.

Everything below that carries a table number is the paper's. Everything marked
ASSUMPTION is not in the paper and is stated here so it can be argued with.

  equipment   2 x 250 kW_e (Table 2), min stable load 50% (Sections 1, 3),
              fuel cost f(P) = aP^2 + bP + c with Table 3 coefficients,
              heat = 1.332 x P_e (Table 2), BESS 1000 kWh / 250 kW,
              eta_c = eta_d = 0.9, SoC 30-100% (Table 4)
  prices      ToU 0.106 off-peak (00:00-07:30) / 0.140 peak, gas 0.0198 (Table 5)
  heat load   flat 483 kW_th (Figure 7, the "real" trace)
  horizon     48 half-hour steps (Section 5)
  no export   P_grid >= 0 (Eq 13)

ASSUMPTIONS, all forced by gaps in the paper:
  1. The electric load is NOT published (Data Availability: private company).
     Two profiles are run: "figure" -- a reconstruction from Figure 6's visible
     features (near-zero before 02:00, steep morning ramp, ~690 kW peak near
     11:30, a dip near 13:30, 400-650 kW afternoon) -- and "csv", the
     reverse-engineered day in chp_bess_analysis/sigalo_day.csv resampled to
     30 min. Conclusions are reported only where both agree.
  2. The paper has a heat buffer tank but never gives its capacity, and this
     engine has no thermal store. A 90%-efficient gas boiler stands in for it,
     so heat deficits are priced instead of being silently absorbed.
  3. Start-up cost T_SU appears in Eq (19) with no value. Base runs use 0; a
     sensitivity at 100 per start is included.
  4. The day is closed on state of charge (end = start), so one day can be read
     as a repeating day.

HALF-HOUR STEPS ON AN HOURLY ENGINE. reopt_core.model integrates one hour per
step. A half-hour case is exact under: keep every kW rate, halve every per-kWh
price, double the battery's kWh. `python tools/paper_case.py --check-dt` proves
it (the same physical day must cost exactly half when re-declared at dt = 0.5).

    python tools/paper_case.py              the matrix
    python tools/paper_case.py --check-dt   only the scaling proof
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import model as M
from reopt_core.tariff import flat_tariff

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "chp_bess_analysis")

KWH_PER_MMBTU = 293.07107
GAS_PER_KWH = 0.0198
A, B, C = 7.045e-5, 0.0297, 2.0654
UNIT_KW, N_UNITS, MIN_LOAD = 250.0, 2, 0.50
EFF_FULL, EFF_HALF = 0.355, 0.343
TH_FULL, TH_HALF = 0.473, 0.459
Q_HRR = 1.332
BESS_KWH, BESS_KW = 1000.0, 250.0
SOC_MIN, ETA = 0.30, 0.90
TARIFF_OFF, TARIFF_PEAK = 0.106, 0.140
HEAT_FLAT = 483.0
BOILER_EFF = 0.90          # ASSUMPTION 2


# ------------------------------------------------------------------ inputs
def tariff_48() -> list[float]:
    """Table 5: off-peak 00:00-07:30 = steps 1-15, peak thereafter."""
    return [TARIFF_OFF if t < 15 else TARIFF_PEAK for t in range(48)]


def load_figure() -> list[float]:
    """ASSUMPTION 1a -- Figure 6's shape, read off the plotted 'real' trace.

    Anchor points (step, kW) linearly interpolated; the figure is a rendered
    image, so these are eyeball values, not data.
    """
    anchors = [(0, 25), (2, 60), (4, 110), (6, 300), (8, 500), (10, 470),
               (12, 520), (14, 500), (16, 480), (18, 540), (20, 500), (22, 600),
               (24, 690), (26, 420), (27, 260), (29, 520), (31, 560), (33, 400),
               (35, 640), (37, 450), (39, 600), (41, 500), (43, 640), (45, 360),
               (47, 620)]
    out, (px, pv) = [], anchors[0]
    for t in range(48):
        while t > anchors[min(len(anchors) - 1, [i for i, (x, _) in enumerate(anchors)
                                                 if x >= t][0])][0]:
            break
        nxt = next(((x, v) for x, v in anchors if x >= t), anchors[-1])
        prv = [(x, v) for x, v in anchors if x <= t][-1]
        if nxt[0] == prv[0]:
            out.append(float(prv[1]))
        else:
            w = (t - prv[0]) / (nxt[0] - prv[0])
            out.append(float(prv[1] + w * (nxt[1] - prv[1])))
    return out


def load_csv() -> list[float]:
    """ASSUMPTION 1b -- the reverse-engineered day, each hour split in two."""
    path = os.path.join(OUT, "sigalo_day.csv")
    with io.open(path, encoding="utf-8-sig") as fh:
        hourly = [float(r["Electric_Load_kW"]) for r in csv.DictReader(fh)]
    return [v for v in hourly for _ in (0, 1)]


# ------------------------------------------------------------------ pricing
def f_unit(p: float) -> float:
    return A * p * p + B * p + C


def chp_cost_per_hour(p_total: float) -> float:
    """Table 3 curve, cheapest split over 2 convex units."""
    if p_total <= 1e-9:
        return 0.0
    if p_total <= UNIT_KW + 1e-9:
        return f_unit(p_total)
    return 2.0 * f_unit(p_total / 2.0)


# ------------------------------------------------------------------ scenario
def build(load: list[float], *, dt: float = 0.5, chp: bool = True, bess: bool = True,
          eta: float = ETA, start_cost: float = 0.0, max_starts: int | None = None,
          with_heat: bool = True, heat_kw: float = HEAT_FLAT,
          cyclic: bool = True) -> M.ScenarioInputs:
    n = len(load)
    k = dt                                   # every per-kWh price scales by dt
    tar = flat_tariff(0.0)
    price = tariff_48() if n == 48 else [TARIFF_OFF if t < 8 else TARIFF_PEAK for t in range(n)]
    tar.energy_cost_per_kwh = [p * k for p in price] + [0.0] * (8760 - n)
    fleet = [M.FuelTechInputs(
        enabled=chp, kind="CHP", label="CHP", name=f"CHP{i + 1}",
        installed_cost_per_kw=0.0, om_cost_per_kw=0.0, om_cost_per_kwh=0.0,
        fuel_cost_per_mmbtu=GAS_PER_KWH * KWH_PER_MMBTU * k,
        electric_efficiency_full_load=EFF_FULL, electric_efficiency_half_load=EFF_HALF,
        thermal_efficiency_full_load=TH_FULL, thermal_efficiency_half_load=TH_HALF,
        min_kw=UNIT_KW, max_kw=UNIT_KW, min_turn_down_fraction=MIN_LOAD,
        start_cost=start_cost, max_starts_per_day=max_starts, can_curtail=False,
        macrs_option_years=0, macrs_bonus_fraction=0.0, federal_itc_fraction=0.0)
        for i in range(N_UNITS)]
    storage = M.StorageInputs(
        enabled=bess, name="BESS",
        installed_cost_per_kw=0.0, installed_cost_per_kwh=0.0, installed_cost_constant=0.0,
        om_cost_fraction_of_installed_cost=0.0,
        min_kw=BESS_KW if bess else 0.0, max_kw=BESS_KW,
        min_kwh=BESS_KWH / k if bess else 0.0, max_kwh=BESS_KWH / k,   # kWh scales as 1/dt
        charge_efficiency=eta, discharge_efficiency=eta, grid_charge_efficiency=eta,
        can_grid_charge=True, soc_min_fraction=SOC_MIN, soc_init_fraction=SOC_MIN,
        optimize_soc_init_fraction=cyclic,
        macrs_option_years=0, macrs_bonus_fraction=0.0, total_itc_fraction=0.0)
    fin = M.FinancialInputs(
        analysis_years=1, elec_cost_escalation_rate_fraction=0.0,
        om_cost_escalation_rate_fraction=0.0, offtaker_discount_rate_fraction=0.0,
        offtaker_tax_rate_fraction=0.0, fuel_cost_escalation_rate_fraction=0.0)
    kw = dict(loads_kw=list(load), tariff=tar, financial=fin, pv=M.PVInputs(enabled=False),
              storage=storage, fuel_tech=fleet[0], fuel_techs=fleet,
              compensation_type="no_compensation")
    if with_heat:
        kw.update(heating_loads_kw=[heat_kw] * n, boiler_efficiency=BOILER_EFF,
                  existing_boiler_fuel_cost_per_mmbtu=GAS_PER_KWH * KWH_PER_MMBTU * k,
                  boiler_fuel_escalation=0.0)
    return M.ScenarioInputs(**kw)


def report(res: dict, inp: M.ScenarioInputs, *, dt: float, with_heat: bool) -> dict:
    """Re-price the solved schedule with the paper's own quadratic curve."""
    ser = res["series"]
    n = len(ser["load_kw"])
    chp = [sum(v[t] for v in ser["fueltech_unit_kw"].values()) for t in range(n)]
    price = [p / dt for p in inp.tariff.energy_cost_per_kwh[:n]]      # back to true prices
    fuel_paper = sum(chp_cost_per_hour(p) * dt for p in chp)
    grid_cost = sum(price[t] * ser["grid_kw"][t] * dt for t in range(n))
    boiler_kwh = sum(ser["boiler_heat_kw"]) * dt if ser.get("boiler_heat_kw") else 0.0
    boiler_cost = boiler_kwh / BOILER_EFF * GAS_PER_KWH
    units = res["sizes"]["fueltech_units"]
    soc = ser["soc_kwh"]
    out = {
        "status": res["status"], "chp_kwh": sum(chp) * dt,
        "grid_kwh": sum(ser["grid_kw"]) * dt,
        "charge_kwh": sum(ser["battery_charge_kw"]) * dt,
        "discharge_kwh": sum(ser["battery_discharge_kw"]) * dt,
        "starts": sum(u.get("starts") or 0 for u in units),
        "unit_hours": sum(u.get("running_hours") or 0 for u in units) * dt,
        "boiler_kwh_th": boiler_kwh,
        "chp_heat_kwh_th": sum(chp) * dt * Q_HRR,
        "soc_min_pct": 100 * min(soc) * dt / BESS_KWH if soc else 0.0,
        "soc_max_pct": 100 * max(soc) * dt / BESS_KWH if soc else 0.0,
        "fuel_paper": fuel_paper, "grid_cost": grid_cost, "boiler_cost": boiler_cost,
        "total": fuel_paper + grid_cost + boiler_cost,
        "engine_objective": res["objective_lifecycle_cost"],
    }
    # physics the schedule must satisfy
    bad = []
    if min(ser["grid_kw"]) < -1e-6:
        bad.append("grid export")
    if any(0 < p < UNIT_KW * MIN_LOAD - 1e-6 for v in ser["fueltech_unit_kw"].values() for p in v):
        bad.append("engine below 50%")
    if inp.storage.enabled and soc and min(soc) * dt < SOC_MIN * BESS_KWH - 1e-6:
        bad.append("SoC below 30%")
    if with_heat:
        boil = ser.get("boiler_heat_kw") or [0.0] * n
        chph = ser.get("chp_heat_to_load_kw") or [0.0] * n
        worst = max(abs(boil[t] + chph[t] - HEAT_FLAT) for t in range(n))
        if worst > 1e-3:
            bad.append(f"heat balance {worst:.2g}")
    out["violations"] = bad
    return out


# ------------------------------------------------------------------ runs
def check_dt() -> int:
    """The scaling proof.

    ONE physical day, held constant inside each hour, declared two ways: 24
    steps of 1 h, and 48 steps of 30 min under the scaling (prices x dt,
    battery kWh / dt, kW rates untouched). Same day, so the true cost and the
    true energies must come out identical -- that is what makes a half-hour
    case trustworthy on an hourly engine.
    """
    print("dt scaling proof — one physical day, two declarations")
    hourly = load_csv()[::2]                       # 24 hourly points
    half = [v for v in hourly for _ in (0, 1)]     # the same day at 30 min
    ia, ib = build(hourly, dt=1.0), build(half, dt=0.5)
    ra = report(M.solve(ia, time_limit=600, mip_gap=1e-7), ia, dt=1.0, with_heat=True)
    rb = report(M.solve(ib, time_limit=600, mip_gap=1e-7), ib, dt=0.5, with_heat=True)
    tol = 2e-4 * max(1.0, ra["total"])
    rows = [("total cost", ra["total"], rb["total"]),
            ("CHP kWh", ra["chp_kwh"], rb["chp_kwh"]),
            ("grid kWh", ra["grid_kwh"], rb["grid_kwh"]),
            ("discharge kWh", ra["discharge_kwh"], rb["discharge_kwh"]),
            ("boiler kWh_th", ra["boiler_kwh_th"], rb["boiler_kwh_th"])]
    good = True
    print(f"  {'quantity':<16}{'24 x 1 h':>14}{'48 x 30 min':>14}{'diff':>12}")
    for lab, x, y in rows:
        hit = abs(y - x) <= max(tol, 2e-4 * max(1.0, abs(x)))
        good &= hit
        print(f"  {'OK' if hit else 'XX'} {lab:<13}{x:>14,.4f}{y:>14,.4f}{y - x:>+12.2e}")
    print(f"  {'OK' if good else 'XX'}  the half-hour declaration reproduces the hourly day")
    return 0 if good else 1


MATRIX = [
    ("grid only", dict(chp=False, bess=False)),
    ("CHP only, no battery", dict(bess=False)),
    ("CHP + battery (paper's ideal)", dict()),
    ("CHP + battery, lossless (the CSV's assumption)", dict(eta=1.0)),
    ("CHP + battery, start cost 100", dict(start_cost=100.0)),
    ("CHP + battery, max 1 start/day/unit", dict(max_starts=1)),
    ("CHP + battery, heat ignored", dict(with_heat=False)),
    ("CHP + battery, SoC fixed at 30% start", dict(cyclic=False)),
]


def main() -> None:
    if "--check-dt" in sys.argv:
        sys.exit(check_dt())
    results = {}
    for tag, loader in (("figure", load_figure), ("csv", load_csv)):
        load = loader()
        print(f"\n{'=' * 104}\nLOAD '{tag}': 48 x 30 min, {sum(load) * 0.5:,.0f} kWh/day, "
              f"peak {max(load):,.0f} kW, min {min(load):,.0f} kW, mean {sum(load) / len(load):,.0f} kW")
        print(f"  {'scenario':<46}{'total':>10}{'fuel':>10}{'grid':>9}{'boiler':>9}"
              f"{'CHP kWh':>10}{'grid kWh':>10}{'st':>4}{'SoC%':>11}")
        base = None
        for name, kwargs in MATRIX:
            inp = build(load, **kwargs)
            t0 = time.time()
            res = M.solve(inp, time_limit=900, mip_gap=1e-5)
            r = report(res, inp, dt=0.5, with_heat=kwargs.get("with_heat", True))
            r["seconds"] = time.time() - t0
            results[f"{tag}/{name}"] = r
            base = base if base is not None else r["total"]
            soc = f"{r['soc_min_pct']:.0f}-{r['soc_max_pct']:.0f}"
            flag = "" if not r["violations"] else "  !! " + ", ".join(r["violations"])
            print(f"  {name:<46}{r['total']:>10,.2f}{r['fuel_paper']:>10,.2f}"
                  f"{r['grid_cost']:>9,.2f}{r['boiler_cost']:>9,.2f}"
                  f"{r['chp_kwh']:>10,.0f}{r['grid_kwh']:>10,.0f}{r['starts']:>4}"
                  f"{soc:>11}{flag}")
        base = results[f"{tag}/CHP + battery (paper's ideal)"]
        b, g = base["total"], results[f"{tag}/grid only"]["total"]
        nb = results[f"{tag}/CHP only, no battery"]["total"]
        print(f"  savings vs grid only {100 * (g - b) / g:.1f}%   "
              f"battery worth {nb - b:,.2f}/day over CHP alone")
        # the engine optimises an affine fuel curve and is then re-priced on the
        # paper's quadratic: that gap bounds how much of any small difference
        # between scenarios is approximation rather than dispatch
        gap = base["total"] - base["engine_objective"]
        print(f"  affine fuel curve vs Table 3 quadratic: {gap:+,.2f} "
              f"({gap / base['total']:+.2%}) — differences smaller than this are noise")
        caps = results[f"{tag}/CHP + battery, max 1 start/day/unit"]["engine_objective"]
        print(f"  constraint monotonicity (engine objective): base {base['engine_objective']:,.2f} "
              f"<= capped {caps:,.2f}  {'OK' if caps >= base['engine_objective'] - 1e-6 else 'XX'}")
    with io.open(os.path.join(OUT, "paper_case.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1, default=float)
    print(f"\nsaved -> chp_bess_analysis/paper_case.json")


if __name__ == "__main__":
    main()
