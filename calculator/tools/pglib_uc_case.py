"""Cross-validate this calculator's commitment maths against IEEE PES pglib-uc.

  Power Grid Lib -- Unit Commitment, curated by the IEEE PES Task Force on
  Benchmarks for Validation of Emerging Power System Algorithms.
  https://github.com/power-grid-lib/pglib-uc   (CC-BY)

The benchmark ships real instances (CAISO, FERC, RTS-GMLC) AND the task force's
own reference model, uc_model.jl. That model is the ground truth here: the same
derived instance is solved by it (JuMP + HiGHS) and by reopt_core.model, and the
two objectives must agree.

pglib-uc models more than this calculator does, so the instance is *derived*,
and every change is listed here rather than hidden:

  reserves        -> 0            we have no reserve product
  ramp limits     -> P_max        non-binding; we have no ramp constraints
  startup lags    -> the hot one  we carry a single start cost
  piecewise cost  -> its two end points (affine), which both models then price
                     identically: ours through an efficiency pair chosen to
                     reproduce cost(P) = beta*u + alpha*P exactly
  renewables      -> removed      keeps the balance thermal-only
  initial state   -> all units off, which this engine is told directly
                     (cyclic_commitment=False, initial_on=False). A tail of
                     zero-demand periods is still appended so the two models
                     also agree about the end of the horizon
  demand          -> scaled to the chosen generator subset, and never below the
                     smallest unit's minimum output (both models balance with
                     equality, so an unservable sliver is infeasible for both)

What is left is exactly the arithmetic this calculator claims: commitment with
minimum up and down times, start costs, minimum stable load, an affine cost
curve and an equality demand balance.

    python tools/pglib_uc_case.py [--case=rts_gmlc/2020-01-27.json]
                                  [--gens=12] [--periods=24] [--tail=4] [--all]
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import model as M
from reopt_core.tariff import flat_tariff

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(ROOT, "benchmarks")
PGLIB = os.path.join(BENCH, "pglib-uc")
REF_JL = os.path.join(BENCH, "uc_reference_highs.jl")
JL_ENV = os.path.join(ROOT, "reopt_jl")
DEPOT = r"D:\JuliaDepot"
KWH_PER_MMBTU = 293.07107
GRID_PRICE = 1.0e6          # the benchmark has no grid: price imports out of the optimum


# ------------------------------------------------------------------ derive
def derive(data: dict, *, n_gens: int | None, periods: int, tail: int,
           headroom: float = 0.85) -> dict:
    gens = sorted(data["thermal_generators"])
    if n_gens:
        gens = gens[:n_gens]
    out_gens = {}
    for g in gens:
        s = dict(data["thermal_generators"][g])
        pmax, pmin = s["power_output_maximum"], s["power_output_minimum"]
        pw = s["piecewise_production"]
        s["piecewise_production"] = [dict(pw[0]), dict(pw[-1])]      # affine
        s["startup"] = [dict(s["startup"][0])]                        # one category
        s["ramp_up_limit"] = s["ramp_down_limit"] = pmax
        s["ramp_startup_limit"] = s["ramp_shutdown_limit"] = pmax
        s["unit_on_t0"], s["power_output_t0"] = 0, 0.0
        s["time_down_t0"], s["time_up_t0"] = 168, 0
        s["must_run"] = 0
        out_gens[g] = s
    cap = sum(s["power_output_maximum"] for s in out_gens.values())
    pmin_small = min(s["power_output_minimum"] for s in out_gens.values())
    dem = list(data["demand"])[:periods]
    k = headroom * cap / max(dem)
    dem = [max(pmin_small, round(d * k, 6)) for d in dem] + [0.0] * tail
    return {"time_periods": len(dem), "demand": dem, "reserves": [0.0] * len(dem),
            "thermal_generators": out_gens, "renewable_generators": {}}


# ------------------------------------------------------------------ ours
def to_inputs(case: dict) -> M.ScenarioInputs:
    """Same instance as reopt_core inputs.

    cost(P) = beta*u + alpha*P is carried through the efficiency pair REopt's
    fuel curve is built from (utils.jl:645). That intercept is per kW of rated
    capacity and CHP scales it by the unit size (chp_constraints.jl:34), so the
    pair is fitted against beta / P_max; with the fuel priced at one unit per
    kWh of fuel the curve then lands exactly on alpha and beta. beta may be
    negative -- several benchmark units have a cost curve whose first point sits
    below the linear extension -- which the engine now carries.
    """
    fleet = []
    for name, s in sorted(case["thermal_generators"].items()):
        pmax, pmin = s["power_output_maximum"], s["power_output_minimum"]
        (x1, c1), (x2, c2) = ((p["mw"], p["cost"]) for p in s["piecewise_production"])
        alpha = (c2 - c1) / (x2 - x1)
        beta = c1 - alpha * x1
        full = alpha + beta / pmax                  # fuel per kWh at full load
        half = 0.5 * alpha + beta / pmax            # ... at half load
        if abs(full) < 1e-12 or abs(half) < 1e-12:  # a zero-cost unit
            full = half = 1e-12
        fleet.append(M.FuelTechInputs(
            enabled=True, kind="CHP", label="UC", name=name,
            installed_cost_per_kw=0.0, om_cost_per_kw=0.0, om_cost_per_kwh=0.0,
            fuel_cost_per_mmbtu=KWH_PER_MMBTU,            # so cost == fuel in kWh terms
            electric_efficiency_full_load=1.0 / full,
            electric_efficiency_half_load=0.5 / half,
            thermal_efficiency_full_load=0.0,
            min_kw=pmax, max_kw=pmax, min_turn_down_fraction=pmin / pmax,
            start_cost=s["startup"][0]["cost"],
            min_up_hours=int(s["time_up_minimum"]), min_down_hours=int(s["time_down_minimum"]),
            initial_on=False, can_curtail=False,
            macrs_option_years=0, macrs_bonus_fraction=0.0, federal_itc_fraction=0.0))
    n = case["time_periods"]
    tar = flat_tariff(0.0)
    tar.energy_cost_per_kwh = [GRID_PRICE] * 8760
    fin = M.FinancialInputs(
        analysis_years=1, elec_cost_escalation_rate_fraction=0.0,
        om_cost_escalation_rate_fraction=0.0, offtaker_discount_rate_fraction=0.0,
        offtaker_tax_rate_fraction=0.0, fuel_cost_escalation_rate_fraction=0.0)
    return M.ScenarioInputs(
        loads_kw=[float(d) for d in case["demand"]], tariff=tar, financial=fin,
        pv=M.PVInputs(enabled=False), storage=M.StorageInputs(enabled=False),
        fuel_tech=fleet[0], fuel_techs=fleet, compensation_type="no_compensation",
        cyclic_commitment=False)


def ours_cost(res: dict, case: dict) -> dict:
    """Price our schedule with the benchmark's own cost definition."""
    ser = res["series"]
    n = case["time_periods"]
    total, started, gen_kwh = 0.0, 0, 0.0
    on_series = ser.get("fueltech_unit_on") or {}
    for name, s in case["thermal_generators"].items():
        (x1, c1), (x2, c2) = ((p["mw"], p["cost"]) for p in s["piecewise_production"])
        alpha = (c2 - c1) / (x2 - x1)
        beta = c1 - alpha * x1
        p = ser["fueltech_unit_kw"][name]
        on = on_series.get(name) or [1.0 if p[t] > 1e-6 else 0.0 for t in range(n)]
        for t in range(n):
            if on[t] > 0.5:
                total += beta + alpha * p[t]
            prev = on[t - 1] if t else 0.0          # the horizon starts with every unit off
            if on[t] > 0.5 and prev < 0.5:
                total += s["startup"][0]["cost"]
                started += 1
        gen_kwh += sum(p)
    return {"benchmark_cost": total, "starts": started, "generation": gen_kwh,
            "grid": sum(ser["grid_kw"]), "engine_objective": res["objective_lifecycle_cost"],
            "status": res["status"]}


# ------------------------------------------------------------------ theirs
def reference(case: dict, tag: str, *, timeout: float = 2400) -> dict:
    src = os.path.join(BENCH, f"{tag}.case.json")
    dst = os.path.join(BENCH, f"{tag}.out.json")
    with io.open(src, "w", encoding="utf-8") as fh:
        json.dump(case, fh)
    julia = shutil.which("julia") or os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "julia.exe")
    cmd = [julia, f"--project={JL_ENV}", REF_JL, src, dst]
    p = subprocess.run(cmd, env=dict(os.environ, JULIA_DEPOT_PATH=DEPOT),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    if p.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError(f"reference model failed:\n{p.stdout[-2500:]}\n{p.stderr[-2500:]}")
    with io.open(dst, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------ main
def main() -> None:
    arg = lambda k, d: next((a.split("=", 1)[1] for a in sys.argv if a.startswith(f"--{k}=")), d)
    rel = arg("case", os.path.join("rts_gmlc", "2020-01-27.json"))
    n_gens = None if "--all" in sys.argv else int(arg("gens", "12"))
    periods, tail = int(arg("periods", "24")), int(arg("tail", "4"))
    with io.open(os.path.join(PGLIB, rel), encoding="utf-8") as fh:
        data = json.load(fh)
    case = derive(data, n_gens=n_gens, periods=periods, tail=tail)
    tag = rel.replace("/", "_").replace("\\", "_").replace(".json", "")
    cap = sum(s["power_output_maximum"] for s in case["thermal_generators"].values())
    print(f"pglib-uc {rel}: {len(case['thermal_generators'])} units, "
          f"{case['time_periods']} periods ({periods} + {tail} idle), "
          f"capacity {cap:,.0f}, peak demand {max(case['demand']):,.0f}")

    t0 = time.time()
    ref = reference(case, tag)
    t_ref = time.time() - t0
    print(f"  reference (pglib-uc uc_model.jl, HiGHS) : {ref['objective']:>16,.2f}   "
          f"{ref['status']}  {t_ref:,.0f}s")

    t0 = time.time()
    res = M.solve(to_inputs(case), time_limit=2400, mip_gap=0.0)
    t_ours = time.time() - t0
    o = ours_cost(res, case)
    print(f"  this calculator                         : {o['benchmark_cost']:>16,.2f}   "
          f"{o['status']}  {t_ours:,.0f}s")
    d = o["benchmark_cost"] - ref["objective"]
    print(f"  difference                              : {d:>16,.2f}   "
          f"({d / ref['objective']:+.4%})")
    print(f"  grid import (must be 0): {o['grid']:.6g}   starts: ours {o['starts']}, "
          f"reference {sum(sum(1 for t, v in enumerate(c) if v > 0.5 and (c[t - 1] if t else 0) < 0.5) for c in ref['commitment'].values())}")
    ok = abs(d) <= 1e-4 * max(1.0, abs(ref["objective"]))
    print(f"\n  {'OK' if ok else 'XX'}  objectives agree to 0.01%")
    with io.open(os.path.join(BENCH, f"{tag}.compare.json"), "w", encoding="utf-8") as fh:
        json.dump({"instance": rel, "reference": {k: v for k, v in ref.items()
                                                  if k not in ("commitment", "output")},
                   "ours": o, "difference": d,
                   "seconds": {"reference": t_ref, "ours": t_ours}}, fh, indent=1, default=float)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
