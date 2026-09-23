"""Stress the core — the optimiser on its own, with nothing above it.

Every other suite in this folder builds a scenario through ``app_dispatch`` and
checks that a particular answer came back. This one works the other way round:
it makes up scenarios nobody wrote by hand, and asks whether the answer can
possibly be right. It imports ``reopt_core.model`` and nothing else of ours, so
a failure here is the solver's, not the page's.

Six ways of asking, and they do not overlap:

  A. brute force   tiny instances solved twice — once by the MILP, once by
                   enumerating every on/off pattern there is and costing each
                   one in closed form. Two implementations that share no code
                   have to land on the same number. This is the only check in
                   the project that verifies the optimum rather than a property
                   of it.
  B. invariants    random instances too large to check by eye, read back hour by
                   hour: does the energy balance, does the commitment obey its
                   own minimum times, does the battery obey physics, and does
                   the objective equal the cost of the dispatch it reports?
  C. comparative   a constraint added can never make a plant cheaper; a freedom
     statics       added can never make it dearer. Ten pairs, each one a single
                   field apart.
  D. identities    scaling every price by k scales the bill by k; rotating a
                   cyclic horizon changes nothing; splitting a unit in two
                   changes nothing; the same input twice gives the same number.
  E. degenerate    the inputs nobody means to type: no load, no fleet, one hour,
                   a unit that cannot turn down, a wire of zero, a free grid.
  F. size          the horizons the page warns about, timed.

Usage:

    python tools/stress_core.py                  # everything
    python tools/stress_core.py --only=A,C       # some of it
    python tools/stress_core.py --seed=7         # a different set of instances
    python tools/stress_core.py --cases=20       # more of them
"""

from __future__ import annotations

import argparse
import itertools
import math
import os
import random
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import model as M
from reopt_core.tariff import flat_tariff

FAIL: list[str] = []
SLOW: list[tuple[str, float]] = []


# ----------------------------------------------------------------- reporting
def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'OK' if ok else 'XX'}  {name:<62} {detail}")
    if not ok:
        FAIL.append(name)
    return ok


def close(name: str, got: float, want: float, tol: float = 1e-6, unit: str = "") -> bool:
    """Equal to within a RELATIVE tolerance, which is the only kind that scales.

    The instances here run from a few thousand to a few hundred million, so an
    absolute tolerance is either meaningless at the top or impossible at the
    bottom.
    """
    ok = abs(got - want) <= tol * max(1.0, abs(want))
    return check(name, ok, f"{got:,.4f} vs {want:,.4f}{' ' + unit if unit else ''}")


def at_most(name: str, got: float, cap: float, tol: float = 1e-6, unit: str = "") -> bool:
    ok = got <= cap + tol * max(1.0, abs(cap))
    return check(name, ok, f"{got:,.4f} <= {cap:,.4f}{' ' + unit if unit else ''}")


def at_least(name: str, got: float, floor: float, tol: float = 1e-6, unit: str = "") -> bool:
    ok = got >= floor - tol * max(1.0, abs(floor))
    return check(name, ok, f"{got:,.4f} >= {floor:,.4f}{' ' + unit if unit else ''}")


# ------------------------------------------------------------------- fixtures
def unit(name: str, kw: float, om: float, *, td: float = 0.0, start: float = 0.0,
         up: int = 1, down: int = 1, spill: bool = True,
         max_starts: int | None = None, run_hour: float = 0.0,
         events: int = 0, dur: int = 0, svc: float = 0.0,
         initial_on: bool = False) -> M.FuelTechInputs:
    """One fixed-nameplate machine priced per kWh, with no capital cost at all.

    min_kw == max_kw is what makes this a commitment problem rather than a
    sizing one: the unit is either off or somewhere between its turndown floor
    and its plate, and nothing in between is a decision about how big to build.
    """
    return M.FuelTechInputs(
        enabled=True, kind="CHP", label="CHP", name=name,
        installed_cost_per_kw=0.0, om_cost_per_kw=0.0, om_cost_per_kwh=om,
        fuel_cost_per_mmbtu=0.0, electric_efficiency_full_load=0.35,
        thermal_efficiency_full_load=0.0,
        min_kw=kw, max_kw=kw, min_turn_down_fraction=td,
        start_cost=start, min_up_hours=up, min_down_hours=down,
        can_curtail=spill, max_starts_per_day=max_starts,
        om_cost_per_running_hour=run_hour, initial_on=initial_on,
        maintenance_events=events, maintenance_duration_hours=dur,
        maintenance_cost_per_event=svc,
        macrs_option_years=0, macrs_bonus_fraction=0.0, federal_itc_fraction=0.0)


def battery(kw: float, kwh: float, *, rte: float = 0.88, soc_min: float = 0.2,
            soc_init: float = 0.5, cyclic: bool = True, wear: float = 0.0,
            grid_charge: bool = False) -> M.StorageInputs:
    """A fixed battery. The round trip is split evenly between the two legs."""
    eta = math.sqrt(rte)
    return M.StorageInputs(
        enabled=True, name="Battery",
        installed_cost_per_kw=0.0, installed_cost_per_kwh=0.0,
        installed_cost_constant=0.0, om_cost_fraction_of_installed_cost=0.0,
        min_kw=kw, max_kw=kw, min_kwh=kwh, max_kwh=kwh,
        charge_efficiency=eta, discharge_efficiency=eta, grid_charge_efficiency=eta,
        can_grid_charge=grid_charge, soc_min_fraction=soc_min,
        soc_init_fraction=soc_init, optimize_soc_init_fraction=cyclic,
        discharge_cost_per_kwh=wear,
        macrs_option_years=0, macrs_bonus_fraction=0.0, total_itc_fraction=0.0)


def scenario(load: list[float], price: list[float], units: list[M.FuelTechInputs],
             *, bat: M.StorageInputs | None = None, cap: float | None = None,
             cyclic: bool = True) -> M.ScenarioInputs:
    """Finance switched off, so the objective IS the operating cost.

    analysis_years = 1 with every rate and tax at zero makes every present-worth
    factor exactly 1, and no technology carries a capital cost, so the number
    the solver minimises is the money the horizon spends and nothing else.
    """
    tar = flat_tariff(0.0)
    tar.energy_cost_per_kwh = list(price) + [0.0] * max(0, 8760 - len(price))
    fin = M.FinancialInputs(
        analysis_years=1, elec_cost_escalation_rate_fraction=0.0,
        om_cost_escalation_rate_fraction=0.0, offtaker_discount_rate_fraction=0.0,
        offtaker_tax_rate_fraction=0.0, fuel_cost_escalation_rate_fraction=0.0)
    return M.ScenarioInputs(
        loads_kw=list(load), tariff=tar, financial=fin, pv=M.PVInputs(enabled=False),
        storage=bat if bat is not None else M.StorageInputs(enabled=False),
        fuel_tech=units[0] if units else M.FuelTechInputs(enabled=False),
        fuel_techs=list(units) if len(units) > 1 else None,
        max_grid_import_kw=cap, cyclic_commitment=cyclic,
        compensation_type="no_compensation")


def run(inp: M.ScenarioInputs, *, gap: float = 0.0, limit: int = 120,
        tag: str = "") -> dict:
    t0 = time.time()
    res = M.solve(inp, time_limit=limit, mip_gap=gap)
    dt = time.time() - t0
    if tag:
        SLOW.append((tag, dt))
    res["_seconds"] = dt
    return res


# -------------------------------------------------- A. the independent optimum
def hour_cost(load_t: float, p: float, ons: list[tuple[float, float, float]],
              cap: float | None, spill: bool) -> float | None:
    """The cheapest way to serve one hour with a KNOWN set of running units.

    With the commitment fixed there is no coupling left between hours, and what
    remains is a one-constraint continuous problem: every running unit sits
    somewhere between its turndown floor and its plate, the wire makes up the
    rest, and the objective is linear in all of it. Cheapest-first is exactly
    optimal for that, so this is not an approximation of the answer — it is the
    answer, arrived at without a solver.

    ``ons`` is (cost per kWh, plate kW, turndown fraction) for each running unit.
    Returns None when the hour cannot be served at all.
    """
    lo = sum(kw * td for _, kw, td in ons)
    hi = sum(kw for _, kw, _ in ons)
    # the wire caps what the utility may deliver, so it puts a FLOOR under the
    # fleet: at least load - cap has to come from the machines
    floor = lo if cap is None else max(lo, load_t - cap)
    if floor > hi + 1e-9:
        return None                       # the wire and the fleet cannot cover it
    if not spill and lo > load_t + 1e-9:
        return None                       # nowhere to put the excess

    rooms = sorted([[c, kw - kw * td] for c, kw, td in ons], key=lambda r: r[0])
    gen = lo
    cost = sum(c * kw * td for c, kw, td in ons)

    need = max(0.0, floor - lo)           # forced by the wire, price no object
    for r in rooms:
        if need <= 1e-12:
            break
        take = min(r[1], need)
        cost += r[0] * take
        gen += take
        r[1] -= take
        need -= take
    if need > 1e-9:
        return None

    want = max(0.0, load_t - gen)         # optional, and only while it undercuts
    for r in rooms:                       # the wire -- the list is sorted, so the
        if want <= 1e-12 or r[0] >= p:    # first unit that does not is the last
            break
        take = min(r[1], want)
        cost += r[0] * take
        gen += take
        r[1] -= take
        want -= take

    if not spill and gen > load_t + 1e-9:
        return None
    delivered = min(gen, load_t) if spill else gen
    return cost + p * (load_t - delivered)


def pattern_cost(load: list[float], price: list[float], units: list[M.FuelTechInputs],
                 pat: list[tuple[int, ...]], cap: float | None,
                 cyclic: bool) -> float | None:
    """What one complete on/off pattern costs, or None if it is not allowed."""
    H, G = len(load), len(units)
    total = 0.0
    for g, u in enumerate(units):
        on = pat[g]
        su, sd = [0] * H, [0] * H
        for t in range(H):
            if t == 0:
                prev = on[H - 1] if cyclic else (1 if u.initial_on else 0)
            else:
                prev = on[t - 1]
            su[t] = 1 if (on[t] and not prev) else 0
            sd[t] = 1 if (prev and not on[t]) else 0
        mu, md = max(1, int(u.min_up_hours)), max(1, int(u.min_down_hours))
        for t in range(H):
            if mu > 1:
                s = sum(su[(t - k) % H] for k in range(mu) if cyclic or t - k >= 0)
                if s > on[t]:
                    return None
            if md > 1:
                s = sum(sd[(t - k) % H] for k in range(md) if cyclic or t - k >= 0)
                if s > 1 - on[t]:
                    return None
        if u.max_starts_per_day is not None:
            for d in range((H + 23) // 24):
                if sum(su[d * 24:(d + 1) * 24]) > u.max_starts_per_day:
                    return None
        total += u.start_cost * sum(su)
        total += u.om_cost_per_running_hour * sum(on)

    for t in range(H):
        ons = [(units[g].om_cost_per_kwh, units[g].max_kw,
                units[g].min_turn_down_fraction)
               for g in range(G) if pat[g][t]]
        c = hour_cost(load[t], price[t], ons, cap, units[0].can_curtail if units else True)
        if c is None:
            return None
        total += c
    return total


def brute_force(load, price, units, cap=None, cyclic=True) -> float | None:
    """Every pattern there is. 2^(H x G) of them, so keep the instance small."""
    H, G = len(load), len(units)
    best = None
    for combo in itertools.product((0, 1), repeat=H * G):
        pat = [combo[g * H:(g + 1) * H] for g in range(G)]
        c = pattern_cost(load, price, units, pat, cap, cyclic)
        if c is not None and (best is None or c < best - 1e-12):
            best = c
    return best


def group_a(rng: random.Random, cases: int) -> None:
    print("\nA. the optimum, found twice and independently")
    print("   the MILP against an exhaustive search over every on/off pattern")
    print("-" * 78)
    n_ok = 0
    for i in range(cases):
        H = rng.choice([5, 6, 7])
        G = rng.choice([1, 1, 2])
        spill = rng.random() < 0.7
        cyclic = rng.random() < 0.7
        base = rng.uniform(400, 2500)
        load = [round(base * rng.uniform(0.35, 1.25), 3) for _ in range(H)]
        price = [round(rng.uniform(5, 90), 3) for _ in range(H)]
        units = []
        for g in range(G):
            units.append(unit(
                f"U{g + 1}", round(rng.uniform(300, 1400), 1), round(rng.uniform(8, 70), 3),
                td=rng.choice([0.0, 0.3, 0.5, 0.8]),
                start=rng.choice([0.0, 0.0, 5_000.0, 40_000.0]),
                up=rng.choice([1, 1, 2, 3]), down=rng.choice([1, 1, 2]),
                spill=spill, initial_on=rng.random() < 0.5))
        cap = rng.choice([None, None, round(base * rng.uniform(0.2, 1.4), 1)])

        want = brute_force(load, price, units, cap, cyclic)
        res = run(scenario(load, price, units, cap=cap, cyclic=cyclic), gap=0.0, limit=60)
        got = res["objective_lifecycle_cost"]
        shape = (f"H={H} G={G} {'cyc' if cyclic else 'fin'} "
                 f"{'spill' if spill else 'no spill'} cap={cap if cap else '-'}")
        if want is None:
            ok = res["status"] == "Infeasible"
            check(f"{i + 1:2d}. no pattern serves it, and the solver agrees", ok,
                  f"{shape} -> {res['status']}")
        else:
            ok = (res["status"] == "Optimal"
                  and abs(got - want) <= 1e-6 * max(1.0, abs(want)))
            check(f"{i + 1:2d}. the MILP found the enumerated optimum", ok,
                  f"{shape}  {got:,.2f} vs {want:,.2f}")
        n_ok += bool(ok)
    check("every tiny instance agreed with brute force", n_ok == cases,
          f"{n_ok} of {cases}")


# ------------------------------------------------------- B. invariants, random
def invariants(tag: str, inp: M.ScenarioInputs, res: dict,
               units: list[M.FuelTechInputs], bat: M.StorageInputs | None) -> None:
    """Everything that has to hold whatever the instance was."""
    s = res["series"]
    H = len(s["load_kw"])
    load = s["load_kw"]

    worst = max(abs(s["fueltech_kw"][t] + s["battery_discharge_kw"][t] + s["grid_kw"][t]
                    + s["unserved_kw"][t]
                    - load[t] - s["battery_charge_kw"][t] - s["export_kw"][t])
                for t in range(H))
    check(f"{tag}: supply equals demand in every hour", worst < 1e-6,
          f"worst residual {worst:.3e} kW")
    check(f"{tag}: a grid-tied run leaves nothing unserved and exports nothing",
          sum(s["unserved_kw"]) < 1e-6 and sum(s["export_kw"]) < 1e-6,
          f"{sum(s['unserved_kw']):.3e} / {sum(s['export_kw']):.3e} kWh")
    check(f"{tag}: the grid is never asked to take power back",
          min(s["grid_kw"]) > -1e-9, f"min {min(s['grid_kw']):.3e} kW")

    rows = {r["name"]: r for r in res["sizes"]["fueltech_units"]}
    for u in units:
        gen = s["fueltech_unit_kw"].get(u.name)
        if gen is None:
            continue
        hi = max(gen)
        check(f"{tag}: {u.name} never exceeds its plate", hi <= u.max_kw + 1e-6,
              f"{hi:,.1f} <= {u.max_kw:,.0f} kW")
        on = s["fueltech_unit_on"].get(u.name)
        if on is None:
            continue
        bad_floor = [t for t in range(H)
                     if on[t] > 0.5 and gen[t] < u.min_turn_down_fraction * u.max_kw - 1e-6]
        bad_off = [t for t in range(H) if on[t] < 0.5 and gen[t] > 1e-6]
        maint = s.get("fueltech_unit_maintenance", {}).get(u.name)
        if maint:                         # a unit in a full outage is off and idle
            bad_floor = [t for t in bad_floor if maint[t] < 0.5]
        check(f"{tag}: {u.name} runs at or above its turndown floor whenever it runs",
              not bad_floor, f"{len(bad_floor)} hour(s) below the floor")
        check(f"{tag}: {u.name} produces nothing while it is off", not bad_off,
              f"{len(bad_off)} hour(s) on while off")

        cyc = inp.cyclic_commitment
        starts = [t for t in range(H)
                  if on[t] > 0.5 and (on[t - 1] < 0.5 if (t or cyc)
                                      else not u.initial_on)]
        stops = [t for t in range(H)
                 if on[t] < 0.5 and (on[t - 1] > 0.5 if (t or cyc) else u.initial_on)]
        reported = rows[u.name]["starts"]
        if reported is not None:
            check(f"{tag}: {u.name}'s reported starts are its off-to-on transitions",
                  reported == len(starts), f"{reported} vs {len(starts)}")
        mu, md = max(1, u.min_up_hours), max(1, u.min_down_hours)
        if mu > 1:
            bad = [t for t in starts
                   for k in range(mu)
                   if (cyc or t + k < H) and on[(t + k) % H] < 0.5]
            check(f"{tag}: {u.name} stays up its minimum {mu} h after a start",
                  not bad, f"{len(bad)} violation(s)")
        if md > 1:
            bad = [t for t in stops
                   for k in range(md)
                   if (cyc or t + k < H) and on[(t + k) % H] > 0.5]
            check(f"{tag}: {u.name} stays down its minimum {md} h after a stop",
                  not bad, f"{len(bad)} violation(s)")
        if u.max_starts_per_day is not None:
            per_day = rows[u.name]["starts_by_day"] or []
            check(f"{tag}: {u.name} keeps inside {u.max_starts_per_day} start(s) a day",
                  all(d <= u.max_starts_per_day for d in per_day),
                  f"busiest day {max(per_day or [0])}")

    if bat is not None and bat.enabled:
        soc = s["storage_unit_soc_kwh"].get(bat.name, s["soc_kwh"])
        kwh = bat.max_kwh
        check(f"{tag}: the battery stays inside its own floor and ceiling",
              min(soc) >= bat.soc_min_fraction * kwh - 1e-6 and max(soc) <= kwh + 1e-6,
              f"{min(soc):,.1f}..{max(soc):,.1f} of {kwh:,.0f} kWh")
        at_most(f"{tag}: the battery never exceeds its rated power",
                max(max(s['battery_charge_kw']), max(s['battery_discharge_kw'])),
                bat.max_kw, 1e-6, "kW")
        worst_soc = 0.0
        for t in range(H):
            prev = soc[t - 1] if t else (soc[H - 1] if bat.optimize_soc_init_fraction
                                         else bat.soc_init_fraction * kwh)
            want = (prev + bat.charge_efficiency * s["battery_charge_kw"][t]
                    - s["battery_discharge_kw"][t] / bat.discharge_efficiency)
            worst_soc = max(worst_soc, abs(soc[t] - want))
        check(f"{tag}: the state of charge follows its own physics",
              worst_soc < 1e-5, f"worst residual {worst_soc:.3e} kWh")
        if bat.optimize_soc_init_fraction:
            dis, chg = sum(s["battery_discharge_kw"]), sum(s["battery_charge_kw"])
            if chg > 1e-6:
                close(f"{tag}: a closed cycle gives back exactly the round trip",
                      dis / chg, bat.charge_efficiency * bat.discharge_efficiency, 1e-4)

    if inp.max_grid_import_kw is not None and not (bat and bat.can_grid_charge):
        at_most(f"{tag}: the wire carries no more than it is rated for",
                max(s["grid_kw"]), inp.max_grid_import_kw, 1e-6, "kW")

    # the solver's own account of how solved it is. A dual bound above the
    # objective would mean the reported answer is below what the relaxation
    # says is possible, which cannot happen and would make every gap a fiction.
    si = res.get("solver") or {}
    if isinstance(si.get("mip_dual_bound"), float) and math.isfinite(si["mip_dual_bound"]):
        at_most(f"{tag}: the dual bound sits under the answer it bounds",
                si["mip_dual_bound"], res["objective_lifecycle_cost"], 1e-6)

    # the objective against the cost of the dispatch it reports
    om, ut = res["om"], res.get("utility", {})
    parts = (om["year1_fueltech"] + om["year1_starts"] + om["year1_running_hours"]
             + om["year1_storage_cycling"] + om["year1_services"] + om["year1_storage"]
             + om["year1_pv"] + ut.get("year1_energy_cost", 0.0)
             + ut.get("year1_tou_demand_cost", 0.0)
             + ut.get("year1_monthly_demand_cost", 0.0) + ut.get("year1_fixed_cost", 0.0)
             + res["capital"]["lifecycle_capex"])
    close(f"{tag}: the objective is the sum of the costs it reports",
          res["objective_lifecycle_cost"], parts, 1e-6)


def group_b(rng: random.Random, cases: int) -> None:
    print("\nB. invariants on instances nobody designed")
    print("   random fleets, loads, prices, wires and batteries, read back hour by hour")
    print("-" * 78)
    ran = committed = 0
    for i in range(cases):
        H = rng.choice([24, 36, 48, 72])
        G = rng.choice([1, 2, 2, 3])
        base = rng.uniform(800, 4000)
        load = [round(base * (0.55 + 0.45 * math.sin(2 * math.pi * t / 24)
                              + rng.uniform(-0.08, 0.08)), 3) for t in range(H)]
        load = [max(1.0, x) for x in load]
        spiky = rng.random() < 0.4
        # The tariff has to sit near the fleet's own cost or the sweep is
        # vacuous: a grid at 10-40 against machines at 10-55 leaves every unit
        # off in every hour, and an instance where nothing commits proves
        # nothing about commitment. These bands overlap, and the guard at the
        # end of the group checks that most instances really did run something.
        cheap_grid = rng.random() < 0.25
        lo, hi = (12, 30) if cheap_grid else (28, 95)
        price = [round(rng.uniform(lo, hi) * (3.0 if (spiky and t % 24 in (18, 19)) else 1.0), 3)
                 for t in range(H)]
        units = [unit(f"U{g + 1}", round(rng.uniform(400, 1600), 1),
                      round(rng.uniform(10, 45), 3),
                      td=rng.choice([0.0, 0.4, 0.5, 0.9]),
                      start=rng.choice([0.0, 3_000.0, 15_000.0]),
                      up=rng.choice([1, 2, 4]), down=rng.choice([1, 2, 5]),
                      spill=rng.random() < 0.8,
                      max_starts=rng.choice([None, None, 1, 2]),
                      run_hour=rng.choice([0.0, 0.0, 500.0]))
                 for g in range(G)]
        bat = None
        if rng.random() < 0.6:
            bat = battery(round(rng.uniform(500, 2500), 1), round(rng.uniform(1000, 6000), 1),
                          rte=rng.choice([0.85, 0.88, 0.95]),
                          soc_min=rng.choice([0.0, 0.2, 0.3]),
                          cyclic=rng.random() < 0.7,
                          wear=rng.choice([0.0, 0.5, 3.0]),
                          grid_charge=rng.random() < 0.3)
        cap = rng.choice([None, None, None, round(base * 1.2, 1)])
        inp = scenario(load, price, units, bat=bat, cap=cap,
                       cyclic=rng.random() < 0.75)
        res = run(inp, gap=0.002, limit=120, tag=f"B{i + 1}")
        tag = f"B{i + 1} (H={H}, {G}u{', bat' if bat else ''}{', cap' if cap else ''})"
        if res["status"] != "Optimal":
            check(f"{tag}: solved", False, res["status"])
            continue
        invariants(tag, inp, res, units, bat)
        if sum(res["series"]["fueltech_kw"]) > 1e-6:
            ran += 1
        if any(r["starts"] for r in res["sizes"]["fueltech_units"]):
            committed += 1
    check("most of the sweep actually committed a machine", ran >= 0.6 * cases,
          f"{ran} of {cases} ran a unit, {committed} of {cases} started one")


# ----------------------------------------------------- C. comparative statics
def group_c() -> None:
    print("\nC. comparative statics — a constraint costs, a freedom pays")
    print("   each pair differs in exactly one field")
    print("-" * 78)
    H = 48
    load = [1800 + 900 * math.sin(2 * math.pi * t / 24) + 200 * (t % 7) for t in range(H)]
    price = [28.0 + (40.0 if t % 24 in (18, 19, 20) else 0.0) for t in range(H)]

    def cost(units, **kw) -> float:
        r = run(scenario(load, price, units, **kw), gap=0.0, limit=180)
        if r["status"] != "Optimal":
            return float("inf")
        return r["objective_lifecycle_cost"]

    base = [unit("A", 1200, 22.0, td=0.5, start=8000, up=2, down=2),
            unit("B", 900, 30.0, td=0.4, start=5000, up=2, down=2)]
    c0 = cost(base)
    print(f"      the plant to be poked at: {c0:,.0f}")

    dearer = [unit("A", 1200, 22.0, td=0.5, start=8000, up=2, down=2),
              unit("B", 900, 30.0, td=0.4, start=5000, up=2, down=2)]
    r = run(scenario(load, [p * 1.5 for p in price], dearer), gap=0.0, limit=180)
    at_least("a grid that charges half as much again cannot cost less",
             r["objective_lifecycle_cost"], c0)

    at_least("a unit whose O&M rises cannot make the plant cheaper",
             cost([unit("A", 1200, 27.0, td=0.5, start=8000, up=2, down=2), base[1]]), c0)
    at_least("a start that costs more cannot make the plant cheaper",
             cost([unit("A", 1200, 22.0, td=0.5, start=60000, up=2, down=2), base[1]]), c0)
    at_least("a longer minimum up time cannot make the plant cheaper",
             cost([unit("A", 1200, 22.0, td=0.5, start=8000, up=8, down=2), base[1]]), c0)
    at_least("a longer minimum down time cannot make the plant cheaper",
             cost([unit("A", 1200, 22.0, td=0.5, start=8000, up=2, down=8), base[1]]), c0)
    at_least("a cap on starts per day cannot make the plant cheaper",
             cost([unit("A", 1200, 22.0, td=0.5, start=8000, up=2, down=2, max_starts=1),
                   base[1]]), c0)
    at_least("a higher turndown floor cannot make the plant cheaper",
             cost([unit("A", 1200, 22.0, td=0.9, start=8000, up=2, down=2), base[1]]), c0)
    at_least("forbidding spill cannot make the plant cheaper",
             cost([unit("A", 1200, 22.0, td=0.5, start=8000, up=2, down=2, spill=False),
                   unit("B", 900, 30.0, td=0.4, start=5000, up=2, down=2, spill=False)]), c0)
    at_least("a service the plant has to fit in cannot make it cheaper",
             cost([unit("A", 1200, 22.0, td=0.5, start=8000, up=2, down=2,
                        events=2, dur=4, svc=100000.0), base[1]]), c0)
    at_least("a wire with a ceiling cannot beat one without",
             cost(base, cap=2200.0), c0)
    at_most("a battery the plant may ignore cannot make it dearer",
            cost(base, bat=battery(1500, 4000, wear=0.0)), c0)
    at_most("a third machine cannot make the plant dearer",
            cost(base + [unit("C", 700, 26.0, td=0.4, start=4000, up=2, down=2)]), c0)
    at_most("a wider wire cannot cost more than a narrower one",
            cost(base, cap=4000.0), cost(base, cap=2200.0))
    # The two seam conventions are NOT ordered in general, and it is worth being
    # precise about why. A finite horizon whose units all begin ON is a genuine
    # relaxation of the cyclic one: the cyclic optimum's own schedule is legal
    # there, the look-back windows stop at hour 0 instead of wrapping, and a
    # unit already running at hour 0 is not charged for starting. A finite
    # horizon whose units begin OFF is not a relaxation at all -- it forces a
    # start on anything running at hour 0, and the run below pays exactly one of
    # unit A's starts for it. Asserting the wrong direction here is what caught
    # the distinction.
    warm = [unit("A", 1200, 22.0, td=0.5, start=8000, up=2, down=2, initial_on=True),
            unit("B", 900, 30.0, td=0.4, start=5000, up=2, down=2, initial_on=True)]
    at_most("a finite horizon that starts warm cannot cost more than the cyclic one",
            cost(warm, cyclic=False), c0)
    cold = cost(base, cyclic=False)
    check("and one that starts cold pays for the first start, to the penny",
          abs((cold - c0) - 8000.0) < 1e-6, f"{cold - c0:+,.0f} = A's start cost")


# --------------------------------------------------------------- D. identities
def group_d() -> None:
    print("\nD. identities the answer has to satisfy exactly")
    print("-" * 78)
    H = 48
    load = [2000 + 800 * math.sin(2 * math.pi * t / 24) + 150 * math.cos(t) for t in range(H)]
    price = [25.0 + 15.0 * (t % 24 > 16) for t in range(H)]
    fleet = lambda k=1.0: [                                     # noqa: E731
        unit("A", 1100, 20.0 * k, td=0.5, start=9000 * k, up=2, down=2),
        unit("B", 800, 31.0 * k, td=0.4, start=6000 * k, up=2, down=2)]

    r0 = run(scenario(load, price, fleet()), gap=0.0, limit=180)
    c0 = r0["objective_lifecycle_cost"]

    # 1. every price scaled by k scales the bill by k and leaves the plan alone
    k = 3.0
    rk = run(scenario(load, [p * k for p in price], fleet(k)), gap=0.0, limit=180)
    close("scaling every price by 3 scales the bill by 3", rk["objective_lifecycle_cost"],
          k * c0, 1e-6)
    close("and the plant runs exactly the same hours",
          sum(rk["series"]["fueltech_kw"]), sum(r0["series"]["fueltech_kw"]), 1e-5)

    # 2. a cyclic horizon is a circle, so where it is cut cannot matter
    for shift in (7, 13):
        rot = load[shift:] + load[:shift]
        rp = price[shift:] + price[:shift]
        rr = run(scenario(rot, rp, fleet()), gap=0.0, limit=180)
        close(f"rotating the cyclic horizon by {shift} h changes nothing",
              rr["objective_lifecycle_cost"], c0, 1e-6)

    # 3. the same question twice
    r2 = run(scenario(load, price, fleet()), gap=0.0, limit=180)
    close("the same input gives the same number twice",
          r2["objective_lifecycle_cost"], c0, 1e-9)

    # 4. a cyclic schedule repeated is feasible for the doubled horizon, so two
    #    of them can never cost more than twice one -- and here they cost exactly
    #    twice, because the repeat is optimal
    rd = run(scenario(load + load, price + price, fleet()), gap=0.0, limit=300)
    at_most("two copies of a cyclic horizon cost no more than twice one",
            rd["objective_lifecycle_cost"], 2 * c0, 1e-6)

    # 5. a machine with no commitment of its own is just capacity: splitting it
    #    in two halves must change nothing
    one = [unit("One", 1200, 24.0)]
    two = [unit("H1", 600, 24.0), unit("H2", 600, 24.0)]
    close("a unit with no turndown and no start cost splits in two for free",
          run(scenario(load, price, two), gap=0.0, limit=120)["objective_lifecycle_cost"],
          run(scenario(load, price, one), gap=0.0, limit=120)["objective_lifecycle_cost"],
          1e-6)

    # 6. two identical machines are interchangeable, so naming them the other way
    #    round cannot move the number
    swap = [unit("B", 800, 31.0, td=0.4, start=6000, up=2, down=2),
            unit("A", 1100, 20.0, td=0.5, start=9000, up=2, down=2)]
    close("the order the fleet is listed in does not matter",
          run(scenario(load, price, swap), gap=0.0, limit=180)["objective_lifecycle_cost"],
          c0, 1e-6)


# -------------------------------------------------------------- E. degenerate
def group_e() -> None:
    print("\nE. the inputs nobody means to type")
    print("-" * 78)
    H = 24
    load = [1500.0] * H
    price = [30.0] * H

    r = run(scenario([0.0] * H, price, [unit("A", 1000, 20.0, td=0.5, start=5000)]),
            gap=0.0, limit=60)
    check("no load: the answer is zero and nothing runs",
          r["status"] == "Optimal" and abs(r["objective_lifecycle_cost"]) < 1e-6
          and sum(r["series"]["fueltech_kw"]) < 1e-6,
          f"{r['objective_lifecycle_cost']:,.4f}")

    # A site with nothing on it is the one case the core answers twice: the MILP
    # solves it, and business_as_usual works it out in closed form. They have to
    # agree, and both have to equal the arithmetic anyone would do by hand.
    inp = scenario(load, price, [])
    r = run(inp, gap=0.0, limit=60)
    close("no fleet: the bill is the load at the tariff, to the penny",
          r["objective_lifecycle_cost"], sum(load) * 30.0, 1e-9)
    bau = M.business_as_usual(inp)
    close("and the closed-form BAU agrees with the solver to the penny",
          bau["year1_total"], r["objective_lifecycle_cost"], 1e-9)
    close("and its lifecycle cost is that year once, with finance switched off",
          bau["lifecycle_cost"], bau["year1_total"], 1e-9)

    r = run(scenario([2400.0], [45.0], [unit("A", 1000, 20.0, td=0.5)]), gap=0.0, limit=60)
    check("a horizon of one hour is still a horizon", r["status"] == "Optimal",
          f"{r['objective_lifecycle_cost']:,.2f}")

    r = run(scenario(load, [0.0] * H, [unit("A", 1000, 20.0, td=0.5, start=5000)]),
            gap=0.0, limit=60)
    check("a free grid: nothing is worth burning gas for",
          abs(r["objective_lifecycle_cost"]) < 1e-6
          and sum(r["series"]["fueltech_kw"]) < 1e-6,
          f"{r['objective_lifecycle_cost']:,.4f}")

    r = run(scenario(load, [400.0] * H, [unit("A", 1000, 20.0)]), gap=0.0, limit=60)
    close("a dear grid: the machine runs flat out and the wire covers the rest",
          sum(r["series"]["fueltech_kw"]), 1000.0 * H, 1e-6)

    # a unit that cannot turn down at all: on means exactly its plate
    r = run(scenario(load, price, [unit("A", 1000, 20.0, td=1.0)]), gap=0.0, limit=60)
    gen = r["series"]["fueltech_unit_kw"]["A"]
    check("a unit with no turndown is at its plate or at zero",
          all(abs(g) < 1e-6 or abs(g - 1000.0) < 1e-6 for g in gen),
          f"{len(set(round(g, 3) for g in gen))} distinct output(s)")

    # a minimum up time longer than the horizon, on a closed loop: the unit can
    # never start, so it is on for all of it or none of it
    r = run(scenario(load, price, [unit("A", 1000, 20.0, td=0.5, up=H + 5)]),
            gap=0.0, limit=60)
    on = r["series"]["fueltech_unit_on"]["A"]
    check("a minimum up time longer than a closed horizon is all or nothing",
          len(set(round(x) for x in on)) == 1, f"on in {sorted(set(round(x) for x in on))}")

    # the wire does all of it, or none of it
    r = run(scenario(load, price, [unit("A", 2000, 20.0, td=0.2)], cap=0.0),
            gap=0.0, limit=60)
    check("a wire of zero forces the fleet to carry the whole load",
          r["status"] == "Optimal" and max(r["series"]["grid_kw"]) < 1e-6
          and abs(sum(r["series"]["fueltech_kw"]) - sum(load)) < 1e-4,
          f"grid {max(r['series']['grid_kw']):.3e} kW")

    r = run(scenario(load, price, [unit("A", 500, 20.0)], cap=0.0), gap=0.0, limit=60)
    check("a wire of zero with too little plate is infeasible, not fudged",
          r["status"] == "Infeasible", r["status"])

    # a battery that costs more to cycle than the spread can ever pay
    r = run(scenario(load, price, [], bat=battery(1000, 4000, wear=500.0)),
            gap=0.0, limit=60)
    check("a battery dearer than the spread is left alone",
          sum(r["series"]["battery_discharge_kw"]) < 1e-6,
          f"{sum(r['series']['battery_discharge_kw']):.3e} kWh")

    # A battery told it may not charge from the grid must not charge from the
    # grid. With no PV and no engine on site there is nowhere else for the
    # energy to come from, so the only right answer is that it never cycles and
    # the site pays what a site with no battery pays. This is the check that
    # caught it: the flag zeroed the grid-charge variable and nothing else, and
    # the battery went on arbitraging through the on-site charge variable.
    swing = [10.0] * 12 + [200.0] * 12
    flat = sum(load[t] * swing[t] for t in range(H))
    r = run(scenario(load, swing, [], bat=battery(1000, 4000, wear=0.0, soc_min=0.0,
                                                  grid_charge=False)), gap=0.0, limit=60)
    check("a battery forbidden the grid does not charge from it",
          sum(r["series"]["battery_charge_kw"]) < 1e-6,
          f"{sum(r['series']['battery_charge_kw']):,.1f} kWh in")
    close("and the site pays exactly what it would with no battery at all",
          r["objective_lifecycle_cost"], flat, 1e-9)

    # Forbidden the grid but given an engine with headroom, it charges from the
    # engine: the constraint is about the SOURCE, not about the battery.
    #
    # The instance has to be built with care or it proves nothing. An engine
    # large enough to cover the dear hours on its own makes the marginal source
    # in those hours the engine itself, and no battery can arbitrage 8 against
    # 8. What is needed is headroom when power is cheap and a shortfall when it
    # is dear: 2,000 kW of plate against 1,200 kW of load in the first half and
    # 2,600 kW in the second, so the last 600 kW of the peak comes from the
    # wire at 200 and is worth displacing.
    shaped = [1200.0] * 12 + [2600.0] * 12
    r = run(scenario(shaped, swing, [unit("A", 2000, 8.0)],
                     bat=battery(1000, 4000, wear=0.0, soc_min=0.0, grid_charge=False)),
            gap=0.0, limit=60)
    check("forbidden the grid, it still charges from an engine on site",
          sum(r["series"]["battery_charge_kw"]) > 1.0,
          f"{sum(r['series']['battery_charge_kw']):,.0f} kWh in")
    check("and it does so only while the engine has headroom",
          sum(r["series"]["battery_charge_kw"][12:]) < 1e-6,
          f"{sum(r['series']['battery_charge_kw'][:12]):,.0f} kWh in the quiet half, "
          f"{sum(r['series']['battery_charge_kw'][12:]):,.0f} in the busy one")

    # ... and allowed the grid, it does what a battery is for
    r = run(scenario(load, swing, [], bat=battery(1000, 4000, wear=0.0, soc_min=0.0,
                                                  grid_charge=True)),
            gap=0.0, limit=60)
    at_most("a battery on a swinging price earns its keep",
            r["objective_lifecycle_cost"], flat - 1.0)
    check("and it charges when power is cheap, not when it is dear",
          sum(r["series"]["battery_charge_kw"][:12]) > sum(r["series"]["battery_charge_kw"][12:]),
          f"{sum(r['series']['battery_charge_kw'][:12]):,.0f} vs "
          f"{sum(r['series']['battery_charge_kw'][12:]):,.0f} kWh")


# -------------------------------------------------------------------- F. size
def group_f() -> None:
    print("\nF. the sizes the page warns about")
    print("-" * 78)
    def year(seed: int) -> tuple[list[float], list[float]]:
        rng = random.Random(seed)
        load, price = [], []
        for t in range(8760):
            day = math.sin(2 * math.pi * (t % 24) / 24)
            season = math.sin(2 * math.pi * t / 8760)
            load.append(2600 + 900 * day + 500 * season + rng.uniform(-80, 80))
            price.append(26 + 12 * day + rng.uniform(-3, 3))
        return load, price

    load, price = year(11)

    # a pure LP: no turndown, no start cost, so the core makes no binaries at all
    inp = scenario(load, price, [unit("A", 2000, 21.0)])
    r = run(inp, gap=0.0, limit=600, tag="F: 8,760 h, LP")
    check(f"8,760 hours as a pure LP solve in {r['_seconds']:.1f} s",
          r["status"] == "Optimal", f"{r['objective_lifecycle_cost']:,.0f}")
    invariants("F-LP", inp, r, [inp.fuel_tech], None)

    # two weeks of real commitment, three machines and a battery
    H = 336
    inp = scenario(load[:H], price[:H],
                   [unit("A", 1200, 20.0, td=0.5, start=9000, up=3, down=3),
                    unit("B", 900, 27.0, td=0.4, start=6000, up=2, down=2),
                    unit("C", 700, 33.0, td=0.4, start=4000, up=2, down=2)],
                   bat=battery(1500, 4000, wear=0.5))
    r = run(inp, gap=0.005, limit=600, tag="F: 336 h, 3 units + battery")
    gapv = (r.get("solver") or {}).get("mip_gap")
    check(f"336 hours of commitment in {r['_seconds']:.1f} s",
          r["status"] == "Optimal",
          f"{r['objective_lifecycle_cost']:,.0f}"
          + (f", gap {100 * gapv:.2f}%" if isinstance(gapv, float) else ""))
    invariants("F-336", inp, r, list(inp.fuel_techs or []),
               inp.storage)

    # a month with a service to place and a wire to respect
    H = 720
    inp = scenario(load[:H], price[:H],
                   [unit("A", 1400, 19.0, td=0.5, start=9000, up=4, down=4,
                         events=1, dur=8, svc=250000.0),
                    unit("B", 1100, 26.0, td=0.5, start=7000, up=4, down=4)],
                   cap=2600.0)
    r = run(inp, gap=0.01, limit=600, tag="F: 720 h, service + wire")
    gapv = (r.get("solver") or {}).get("mip_gap")
    check(f"720 hours with a service to place in {r['_seconds']:.1f} s",
          r["status"] == "Optimal",
          f"{r['objective_lifecycle_cost']:,.0f}"
          + (f", gap {100 * gapv:.2f}%" if isinstance(gapv, float) else ""))
    invariants("F-720", inp, r, list(inp.fuel_techs or []), None)
    rows = {x["name"]: x for x in r["sizes"]["fueltech_units"]}
    check("the service the unit was given was actually taken",
          rows["A"]["maintenance_hours"] is not None
          and abs(rows["A"]["maintenance_hours"] - 8) < 1e-6,
          f"{rows['A']['maintenance_hours']} h out")


# -------------------------------------------------------------------- driver
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", default="ABCDEF", help="letters of the groups to run")
    ap.add_argument("--seed", type=int, default=20260923)
    ap.add_argument("--cases", type=int, default=0,
                    help="instances per randomised group (default: 14 for A, 10 for B)")
    a = ap.parse_args()
    want = {c.upper() for c in a.only if c.isalpha()}
    rng = random.Random(a.seed)

    print("=" * 78)
    print(f"stressing reopt_core.model — seed {a.seed}, groups {''.join(sorted(want))}")
    print("=" * 78)
    t0 = time.time()
    if "A" in want:
        group_a(rng, a.cases or 14)
    if "B" in want:
        group_b(rng, a.cases or 10)
    if "C" in want:
        group_c()
    if "D" in want:
        group_d()
    if "E" in want:
        group_e()
    if "F" in want:
        group_f()

    print()
    if SLOW:
        worst = sorted(SLOW, key=lambda x: -x[1])[:5]
        print("slowest solves: " + ", ".join(f"{n} {s:.1f} s" for n, s in worst))
    print("=" * 78)
    if FAIL:
        print(f"{len(FAIL)} FAILED in {time.time() - t0:.0f} s")
        for f in FAIL:
            print(f"  - {f}")
    else:
        print(f"every stress check passed in {time.time() - t0:.0f} s")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
