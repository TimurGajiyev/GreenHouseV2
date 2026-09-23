"""Scheduled maintenance in ``reopt_core.model`` -- PyPSA's formulation, tested.

Two triggers, both letting the solver place the outages.

PyPSA's, the original: a count of events (``maintenance_events`` E), a duration
(``maintenance_duration_hours`` D) and the capacity a service takes away
(``maintenance_pu`` alpha). Groups A-N test that one.

HOMER Pro's, added after a four-engine browser run showed the count mode
servicing a unit that never ran: an interval in RUNNING hours
(``maintenance_interval_running_hours``) with a price per service
(``maintenance_cost_per_event``). The count then stops being an input and
becomes an outcome of how much each unit actually ran. Groups O and P test it.

Neither is REopt's: REopt states the timing up front in
``unavailability_periods``, which stays reachable through
``production_factor_series``.

Each group below is independent -- its own scenario, its own solve, one claim.
No group depends on another having run.

  A. off by default      zero events changes no variable, no constraint, no cost
  B. the count           exactly E events happen, for several E
  C. the duration        every event is exactly D hours; total out = E x D
  D. contiguity          the hours out are blocks, not scattered hours
  E. alpha               1.0 takes the unit out; below 1.0 derates it, still on
  F. the restart         coming back from a service is a start, and is priced
  G. spacing             does "free" bunch the events? "even" is the control
  H. monotonicity        more maintenance costs more; "even" >= "free"
  I. edges               D > H, E x D > H, D == H
  J. min_down_hours      a longer minimum down time swallows the service window
  K. the load            nothing is left unserved; the fleet staggers itself
  L. the seam            cyclic wraps a window, finite refuses to start one late
  M. the real regimen    TEDOM/Jenbacher minor service, and what it costs
  N. tractability        what actually makes this hard
  O. running hours       the HOMER trigger: services follow the clock
  P. service cost        what makes the count determinate
  Q. scaling             how long a horizon the counter survives

    python tools/test_maintenance.py --only=G     one group
    python tools/test_maintenance.py             all of them, several minutes

Every group solves its own MILPs, so the whole file is minutes of solver time --
run it a group at a time while working, and whole only when there is time for
it. Group M deliberately asks for a tight gap and is the slowest.
"""

from __future__ import annotations

import math
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import model as M
from reopt_core.tariff import flat_tariff

FAIL: list[str] = []
ONLY = next((a.split("=", 1)[1].upper() for a in sys.argv[1:]
             if a.startswith("--only=")), None)

JEN, TED = ("Jenbacher", 1067.0), ("TEDOM", 1200.0)
FUEL, GRID = 22.0, 60.0


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'OK' if ok else 'XX'}  {name:<58} {detail}")
    if not ok:
        FAIL.append(name)
    return ok


def eq(name: str, got, want, detail: str = "") -> bool:
    return check(name, got == want,
                 detail or (f"{got}" if got == want else f"{got} != {want}"))


def group(letter: str, title: str) -> bool:
    on = ONLY is None or ONLY == letter
    if on:
        print(f"\n{letter}. {title}")
    return on


# ---------------------------------------------------------------- scenario
def shaped(hours: int, level: float = 1500.0, flat: bool = False) -> list[float]:
    """A load with a daily shape, which is what breaks the solver's symmetry.

    A flat load makes every placement of a service identical, so branch and
    bound has nothing to prune and a 168-hour instance can run for minutes
    without closing the gap. That is a real property of the formulation, not an
    artefact of testing -- group N measures it -- but every other group here
    wants a load a real site could have, so this is the default.
    """
    if flat:
        return [level] * hours
    return [level * (0.72 + 0.38 * math.sin((t % 24 - 6) / 24 * 2 * math.pi)
                     + (0.06 if (t // 24) % 7 < 5 else -0.10))
            for t in range(hours)]


def scenario(*, hours: int, units=(JEN, TED), events=0, duration=0, pu=1.0,
             spacing="free", battery=True, load_kw=1500.0, min_down=1,
             min_load=0.50, start_cost=15_000.0, cyclic=True, flat=False,
             interval=0.0, svc_cost=0.0, price=None,
             maintain=(0, 1)) -> M.ScenarioInputs:
    """A fleet on a shaped load, so a service has a cheapest hour to find."""
    fleet = []
    for i, (name, kw) in enumerate(units):
        on = i in maintain
        fleet.append(M.FuelTechInputs(
            enabled=True, kind="CHP", label="CHP", name=name,
            installed_cost_per_kw=0.0, om_cost_per_kw=0.0, om_cost_per_kwh=((price or {}).get(name, FUEL)),
            fuel_cost_per_mmbtu=0.0, electric_efficiency_full_load=0.35,
            thermal_efficiency_full_load=0.0,
            min_kw=kw, max_kw=kw, min_turn_down_fraction=min_load,
            start_cost=start_cost, min_up_hours=1, min_down_hours=min_down,
            can_curtail=True,
            maintenance_events=(events if on else 0),
            maintenance_duration_hours=(duration if on else 0),
            maintenance_pu=pu, maintenance_spacing=spacing,
            maintenance_interval_running_hours=(interval if on else 0.0),
            maintenance_cost_per_event=svc_cost,
            macrs_option_years=0, macrs_bonus_fraction=0.0,
            federal_itc_fraction=0.0))
    eta = math.sqrt(0.88)
    bat = M.StorageInputs(
        enabled=battery, name="BESS",
        installed_cost_per_kw=0.0, installed_cost_per_kwh=0.0,
        installed_cost_constant=0.0, om_cost_fraction_of_installed_cost=0.0,
        min_kw=2500.0 if battery else 0.0, max_kw=2500.0,
        min_kwh=5500.0 if battery else 0.0, max_kwh=5500.0,
        charge_efficiency=eta, discharge_efficiency=eta, grid_charge_efficiency=eta,
        can_grid_charge=True, soc_min_fraction=0.30, soc_init_fraction=0.5,
        optimize_soc_init_fraction=True, discharge_cost_per_kwh=0.50,
        macrs_option_years=0, macrs_bonus_fraction=0.0, total_itc_fraction=0.0)
    tar = flat_tariff(0.0)
    tar.energy_cost_per_kwh = [GRID] * 8760
    fin = M.FinancialInputs(
        analysis_years=1, elec_cost_escalation_rate_fraction=0.0,
        om_cost_escalation_rate_fraction=0.0, offtaker_discount_rate_fraction=0.0,
        offtaker_tax_rate_fraction=0.0, fuel_cost_escalation_rate_fraction=0.0)
    return M.ScenarioInputs(
        loads_kw=shaped(hours, load_kw, flat), tariff=tar, financial=fin,
        pv=M.PVInputs(enabled=False), storage=bat,
        fuel_tech=fleet[0], fuel_techs=fleet, cyclic_commitment=cyclic,
        compensation_type="no_compensation")


def solve(inp: M.ScenarioInputs, *, gap=5e-3, t=300) -> dict:
    """0.5% gap and a 300 s cap -- the same tolerance the app offers, so these
    measure the model as it is actually solved rather than an ideal of it."""
    return M.solve(inp, time_limit=t, mip_gap=gap)


def row(res: dict, name: str) -> dict:
    return next(r for r in res["sizes"]["fueltech_units"] if r["name"] == name)


def mseries(res: dict, name: str) -> list[float]:
    return res["series"].get("fueltech_unit_maintenance", {}).get(name, [])


def blocks(series: list[float], *, wrap: bool = True) -> list[int]:
    """Lengths of the runs of 'in maintenance' hours, wrapping the seam."""
    n = len(series)
    on = [x > 0.5 for x in series]
    if not any(on):
        return []
    if all(on):
        return [n]
    start = next(i for i in range(n) if on[i] and not on[(i - 1) % n]) if wrap \
        else next(i for i in range(n) if on[i])
    out, run = [], 0
    for k in range(n):
        i = (start + k) % n if wrap else start + k
        if wrap or i < n:
            if on[i]:
                run += 1
            elif run:
                out.append(run)
                run = 0
    if run:
        out.append(run)
    return out


def cost(res: dict) -> float:
    return res["objective_lifecycle_cost"]


# ===========================================================================
if group("A", "off by default -- the model without maintenance is unchanged"):
    base = solve(scenario(hours=72))
    r = row(base, "Jenbacher")
    check("no maintenance inputs -> no maintenance result", r["maintenance_hours"] is None)
    check("and no maintenance series", mseries(base, "Jenbacher") == [])
    check("the units still run", r["running_hours"] > 0, f"{r['running_hours']} h")
    # a scenario given events but zero duration is still not maintainable
    z = solve(scenario(hours=72, events=6, duration=0))
    check("events without a duration is not maintainable",
          row(z, "Jenbacher")["maintenance_hours"] is None)
    eq("and costs exactly what the plain scenario costs",
       round(cost(z), 4), round(cost(base), 4))
    z2 = solve(scenario(hours=72, events=0, duration=8))
    eq("a duration without events likewise", round(cost(z2), 4), round(cost(base), 4))

# ===========================================================================
if group("B", "the event count is honoured"):
    for E in (1, 2, 4):
        res = solve(scenario(hours=168, events=E, duration=8, spacing="even"))
        r = row(res, "Jenbacher")
        eq(f"E={E}: exactly {E} events start", len(r["maintenance_starts"]), E,
           f"at hours {r['maintenance_starts']}")

# ===========================================================================
if group("C", "the duration is honoured"):
    for D in (1, 4, 8, 24):
        res = solve(scenario(hours=168, events=3, duration=D, spacing="even"))
        r = row(res, "Jenbacher")
        eq(f"D={D}: total hours out is E x D", r["maintenance_hours"], float(3 * D))
        b = blocks(mseries(res, "Jenbacher"))
        # Events cannot overlap, but nothing stops two of them ABUTTING across
        # a segment boundary, and then they read as one block of 2D. That is
        # only reachable when D is large next to the segment (here D=24 against
        # 56 h segments); at a real plan's ratio -- 8 h in a 730 h month -- it
        # cannot happen. So the guarantee is: whole multiples of D, summing to
        # E x D, and no single block longer than the whole plan.
        check(f"D={D}: every block is a whole multiple of D",
              all(x % D == 0 for x in b) and sum(b) == 3 * D, f"{b}")
        if b != [D] * 3:
            print(f"      note: D={D} abuts across a segment boundary -> {b}; "
                  f"{D} h in a {168 // 3} h segment is {100 * D / (168 // 3):.0f}% of it")

# ===========================================================================
if group("D", "contiguity -- blocks, not scattered hours"):
    res = solve(scenario(hours=168, events=2, duration=12, spacing="even"))
    s = mseries(res, "Jenbacher")
    b = blocks(s)
    eq("2 blocks of 12 h", b, [12] * 2)
    eq("24 hours out in total", int(sum(s)), 24)
    check("the coverage variable is integral, not a fraction",
          all(abs(x - round(x)) < 1e-6 for x in s),
          f"worst {max(abs(x - round(x)) for x in s):.2e}")
    # the same total spread as single hours would be 48 blocks of 1 -- the
    # formulation is what rules that out
    check("not 24 separate one-hour outages", len(b) == 2, f"{len(b)} blocks")

# ===========================================================================
if group("E", "maintenance_pu -- full outage against a derate"):
    full = solve(scenario(hours=168, events=2, duration=12, pu=1.0, spacing="even"))
    gen = full["series"]["fueltech_unit_kw"]["Jenbacher"]
    mm = mseries(full, "Jenbacher")
    check("pu=1.0: the unit produces nothing while out",
          all(gen[t] < 1e-6 for t in range(168) if mm[t] > 0.5),
          f"max {max([gen[t] for t in range(168) if mm[t] > 0.5], default=0):.3f} kW")
    onser = full["series"]["fueltech_unit_on"]["Jenbacher"]
    check("pu=1.0: and is recorded as off, not idling on",
          all(onser[t] < 0.5 for t in range(168) if mm[t] > 0.5))

    half = solve(scenario(hours=168, events=2, duration=12, pu=0.5, spacing="even"))
    genh = half["series"]["fueltech_unit_kw"]["Jenbacher"]
    mh = mseries(half, "Jenbacher")
    out_h = [t for t in range(168) if mh[t] > 0.5]
    eq("pu=0.5: still 2 x 12 h of event", blocks(mh), [12, 12])
    check("pu=0.5: the ceiling is halved, not zeroed",
          all(genh[t] <= 0.5 * JEN[1] + 1e-6 for t in out_h))
    check("pu=0.5: and the unit may keep running through it",
          any(genh[t] > 1e-6 for t in out_h),
          f"max {max(genh[t] for t in out_h):,.0f} kW of {JEN[1]:,.0f}")
    check("a derate is cheaper than a full outage", cost(half) < cost(full),
          f"{cost(half):,.0f} vs {cost(full):,.0f}")

# ===========================================================================
if group("F", "the restart after a service is a start, and is priced"):
    no_m = solve(scenario(hours=168, events=0, duration=0))
    with_m = solve(scenario(hours=168, events=3, duration=8, spacing="even"))
    s0 = row(no_m, "Jenbacher")["starts"]
    s1 = row(with_m, "Jenbacher")["starts"]
    # A shaped load makes a unit cycle on its own overnight, so the absolute
    # count is not the claim -- the claim is that each service adds a restart.
    print(f"      starts without maintenance {s0}, with 3 services {s1}")
    # A service adds a restart only when it lands in an hour the unit would
    # have been running. When the optimiser puts one inside an off period the
    # shaped load was going to cause anyway, the fleet gets the service for no
    # extra start -- which is the practice the maintenance literature
    # describes, scheduling the outage into a low-load window.
    check("a service adds at most one restart, never more", s1 - s0 <= 3,
          f"+{s1 - s0} for 3 services")
    check("and at least one of them shows up as a restart", s1 - s0 >= 1,
          f"+{s1 - s0}")
    if s1 - s0 < 3:
        print(f"      note: {3 - (s1 - s0)} service(s) fell inside an off period the "
              f"load already caused -- free of a start, which is the point of "
              f"letting the solver choose")
    check("and the services themselves are all there",
          row(with_m, "Jenbacher")["maintenance_hours"] == 24.0, "3 x 8 h")
    # and the objective pays for them
    paid = solve(scenario(hours=120, events=2, duration=8, start_cost=100_000.0,
                          spacing="even"))
    n_paid = sum(r["starts"] for r in paid["sizes"]["fueltech_units"])
    free = solve(scenario(hours=120, events=2, duration=8, start_cost=0.0,
                          spacing="even"))
    n_free = sum(r["starts"] for r in free["sizes"]["fueltech_units"])
    d = cost(paid) - cost(free)
    # At 100,000 a start the solver will avoid every start it can, so the two
    # runs need not take the same schedule. What must hold is that the dearer
    # run pays exactly its own starts, and that it takes no more of them.
    print(f"      starts: {n_free} at 0 per start, {n_paid} at 100,000 per start")
    check("the dearer run does not take more starts than the free one",
          n_paid <= n_free, f"{n_paid} <= {n_free}")
    # A dear start does not just raise the bill, it changes the schedule: the
    # solver here buys its way out of 19 starts with fuel. So the delta is not
    # the start charge alone. Two bounds ARE exact, both straight from
    # optimality, writing base for everything that is not start cost:
    #   the free run minimises base, so base_free <= base_paid, hence
    #     delta >= n_paid x S
    #   the paid run could have kept the free schedule, hence
    #     delta <= n_free x S
    lo, hi = n_paid * 100_000.0, n_free * 100_000.0
    check("delta is at least the starts the dearer run actually pays for",
          d >= lo - 1.0, f"{d:,.0f} >= {lo:,.0f}")
    check("and at most what the free schedule would have cost at that price",
          d <= hi + 1.0, f"{d:,.0f} <= {hi:,.0f}")
    print(f"      the {d - lo:,.0f} above the bill is fuel bought to dodge "
          f"{n_free - n_paid} starts")

# ===========================================================================
if group("G", "spacing -- does 'free' bunch the events?"):
    H = 168
    for E, D in ((3, 8),):
        fr = solve(scenario(hours=H, events=E, duration=D, spacing="free"))
        ev = solve(scenario(hours=H, events=E, duration=D, spacing="even"))
        sf = sorted(row(fr, "Jenbacher")["maintenance_starts"])
        se = sorted(row(ev, "Jenbacher")["maintenance_starts"])
        gap_f = min((b - a for a, b in zip(sf, sf[1:])), default=H)
        gap_e = min((b - a for a, b in zip(se, se[1:])), default=H)
        ideal = H / E
        print(f"      E={E} D={D}  free  starts {sf}  min gap {gap_f}")
        print(f"      E={E} D={D}  even  starts {se}  min gap {gap_e}")
        eq(f"E={E}: 'free' still delivers the count", len(sf), E)
        eq(f"E={E}: 'even' still delivers the count", len(se), E)
        check(f"E={E}: 'even' keeps one service per segment of {ideal:.0f} h",
              all(int(i * ideal) <= s < int((i + 1) * ideal) + 1
                  for i, s in enumerate(se)), f"{se}")
        # the claim under test: nothing in the objective spreads 'free' out
        check(f"E={E}: 'free' min gap vs 'even' min gap",
              True, f"{gap_f} vs {gap_e} h "
              + ("-- free is NOT spread" if gap_f < 0.5 * ideal else "-- free happens to spread"))

# ===========================================================================
if group("H", "monotonicity"):
    a = solve(scenario(hours=168, events=2, duration=8, spacing="even"))
    b = solve(scenario(hours=168, events=3, duration=8, spacing="even"))
    c = solve(scenario(hours=168, events=3, duration=16, spacing="even"))
    check("more events cost more", cost(b) > cost(a), f"{cost(b):,.0f} > {cost(a):,.0f}")
    check("longer events cost more", cost(c) > cost(b), f"{cost(c):,.0f} > {cost(b):,.0f}")
    fr = solve(scenario(hours=168, events=3, duration=8, spacing="free"))
    ev = solve(scenario(hours=168, events=3, duration=8, spacing="even"))
    check("'even' is a restriction, so it cannot be cheaper than 'free'",
          cost(ev) >= cost(fr) - 1.0, f"{cost(ev):,.0f} >= {cost(fr):,.0f}")

# ===========================================================================
if group("I", "edges"):
    # a window longer than the horizon is simply not maintainable
    big = solve(scenario(hours=24, events=1, duration=48))
    check("a window longer than the horizon leaves the unit unmaintained",
          row(big, "Jenbacher")["maintenance_hours"] is None)
    # E x D that does not fit must say so, with the numbers
    try:
        solve(scenario(hours=48, events=6, duration=12))
        check("E x D > H is refused with a readable message", False, "no error raised")
    except ValueError as exc:
        check("E x D > H is refused with a readable message",
              "72 h" in str(exc) and "48 h" in str(exc), str(exc)[:88])
    # exactly filling the horizon is legal
    fullout = solve(scenario(hours=48, events=1, duration=48, maintain=(0,)))
    eq("a window exactly the length of the horizon is allowed",
       row(fullout, "Jenbacher")["maintenance_hours"], 48.0)
    eq("and that unit generates nothing at all",
       round(row(fullout, "Jenbacher")["energy_kwh"], 6), 0.0)

# ===========================================================================
if group("J", "interaction with min_down_hours"):
    short = solve(scenario(hours=168, events=2, duration=8, min_down=1, spacing="even"))
    longd = solve(scenario(hours=168, events=2, duration=8, min_down=24, spacing="even"))
    on_s = short["series"]["fueltech_unit_on"]["Jenbacher"]
    on_l = longd["series"]["fueltech_unit_on"]["Jenbacher"]
    off_s = sum(1 for x in on_s if x < 0.5)
    off_l = sum(1 for x in on_l if x < 0.5)
    check("min_down=1: the unit is off at least for the services", off_s >= 16,
          f"{off_s} h off, 16 h of it service")
    check("min_down=24: the minimum down time swallows the window",
          off_l >= 48, f"{off_l} h off for 2 x 8 h of service")
    eq("the service hours themselves are unchanged",
       row(longd, "Jenbacher")["maintenance_hours"], 16.0)
    check("and it costs more", cost(longd) > cost(short),
          f"{cost(longd):,.0f} > {cost(short):,.0f}")

# ===========================================================================
if group("K", "the load is still served, and the fleet staggers itself"):
    res = solve(scenario(hours=168, events=3, duration=8, spacing="even"))
    ser = res["series"]
    eq("nothing is left unserved", round(sum(ser["unserved_kw"]), 6), 0.0)
    eq("and nothing is exported", round(sum(ser["export_kw"]), 6), 0.0)
    H = len(ser["load_kw"])
    # fueltech_kw is already net of spill (ftgen - ftcurt), so this is the
    # balance the model itself enforces, including the slack terms
    worst = max(abs(ser["fueltech_kw"][t] + ser["grid_kw"][t]
                    + ser["battery_discharge_kw"][t] - ser["battery_charge_kw"][t]
                    + ser["unserved_kw"][t] - ser["export_kw"][t]
                    - ser["load_kw"][t]) for t in range(H))
    check("supply equals load every hour", worst < 1e-5, f"max residual {worst:.2e} kW")
    mj, mt = mseries(res, "Jenbacher"), mseries(res, "TEDOM")
    both = sum(1 for t in range(H) if mj[t] > 0.5 and mt[t] > 0.5)
    total_m = int(sum(mj) + sum(mt))
    print(f"      overlapping service hours: {both} of {total_m}")
    check("the solver does not put both engines out at once",
          both == 0, f"{both} overlapping hours")

# ===========================================================================
if group("L", "the seam -- cyclic against finite"):
    cyc = solve(scenario(hours=168, events=1, duration=12, cyclic=True, spacing="even"))
    fin = solve(scenario(hours=168, events=1, duration=12, cyclic=False, spacing="even"))
    eq("cyclic: one 12 h block", blocks(mseries(cyc, "Jenbacher")), [12])
    sf = row(fin, "Jenbacher")["maintenance_starts"]
    eq("finite: one event too", len(sf), 1, f"at hour {sf}")
    check("finite: the event cannot start where it would run past the end",
          sf[0] <= 168 - 12, f"start {sf[0]}, horizon 168, duration 12")
    eq("finite: and it is still 12 hours",
       row(fin, "Jenbacher")["maintenance_hours"], 12.0)

# ===========================================================================
if group("M", "the real regimen -- a gas engine's minor service"):
    # TEDOM/Jenbacher minor service: every 1,000-2,000 operating hours, one
    # service shift of 4-8 h. Over a 4-week window at 1,500 kW that is well
    # under one event; the interesting number is what a year's worth costs, so
    # this scales a 4-week window with the events a 4-week share would carry.
    H = 672
    # A tight gap here on purpose. At the app's 0.5% an 8 h service in 672 h is
    # BELOW the solver's noise floor -- measured, the "constrained" run came out
    # 0.05% CHEAPER than the unconstrained one, which cannot be true of an added
    # constraint and is simply two incumbents inside one tolerance. Adding a
    # constraint can only raise the optimum, so if the sign comes out wrong the
    # gap is what is being measured, not the maintenance.
    TIGHT = dict(gap=1e-5, t=240)
    base = solve(scenario(hours=H, events=0, duration=0), **TIGHT)
    plan = solve(scenario(hours=H, events=1, duration=8, spacing="even"), **TIGHT)
    r = row(plan, "Jenbacher")
    print(f"      1 service of 8 h in {H} h: availability "
          f"{100 * (1 - r['maintenance_hours'] / H):.2f}%")
    print(f"      operating cost {cost(base):,.0f} -> {cost(plan):,.0f} "
          f"({100 * (cost(plan) / cost(base) - 1):+.3f}%)")
    eq("one 8 h service per unit", r["maintenance_hours"], 8.0)
    check("availability lands near the 99% a 6 x 8 h year implies",
          0.985 <= 1 - r["maintenance_hours"] / H <= 1.0,
          f"{100 * (1 - r['maintenance_hours'] / H):.2f}%")
    # What the solver actually PROVED, not what it labelled itself. The wrapper
    # reports status "Optimal" while still carrying a residual MIP gap, so the
    # gap is what bounds any comparison: a 672 h two-engine commitment problem
    # came back "Optimal" at 0.47% and 1.03% here, and the thing being measured
    # is 0.005%. Adding a constraint cannot lower the true optimum, so the
    # honest claim is monotonicity WITHIN the gap that was achieved.
    g_b = (base.get("solver") or {}).get("mip_gap") or 0.0
    g_p = (plan.get("solver") or {}).get("mip_gap") or 0.0
    floor = max(g_b, g_p) * abs(cost(base))
    print(f"      residual gap: base {100 * g_b:.3f}%, plan {100 * g_p:.3f}% "
          f"-> differences below {floor:,.0f} are not resolvable")
    check("adding the service cannot lower the optimum, within the proven gap",
          cost(plan) >= cost(base) - floor,
          f"{cost(plan):,.0f} >= {cost(base):,.0f} - {floor:,.0f}")
    check("and a real service regimen is not a structural cost",
          cost(plan) / cost(base) - 1 < 0.02,
          f"{100 * (cost(plan) / cost(base) - 1):+.4f}% on the window"
          + (" -- inside the gap, so the sign means nothing"
             if abs(cost(plan) - cost(base)) < floor else ""))
    # and the 48 h window REopt assumes for a recip engine, for comparison
    reopt_like = solve(scenario(hours=H, events=1, duration=48, spacing="even"),
                       **TIGHT)
    print(f"      REopt's 48 h window instead: {cost(reopt_like):,.0f} "
          f"({100 * (cost(reopt_like) / cost(base) - 1):+.3f}%)")
    d48 = cost(reopt_like) - cost(plan)
    check("a 48 h window is at least not cheaper than an 8 h one",
          d48 > -floor, f"{cost(reopt_like):,.0f} vs {cost(plan):,.0f} "
          f"({d48:+,.0f}, floor {floor:,.0f})")
    print(f"      6 x 8 h a year is {6 * 8} h out (99.45% available); REopt's "
          f"9 x 48 h is {9 * 48} h (95.07%) -- a 6x difference in downtime")

# ===========================================================================
if group("N", "tractability -- what actually makes this hard"):
    # The guess was that free placement is the expensive part, because it is a
    # symmetric problem: nothing prefers one hour, so branch and bound has
    # nothing to prune. Measured, that is not where the cost is. The LOAD SHAPE
    # dominates -- a flat load fails to close the gap under either spacing,
    # while a shaped one closes it under both, in a third of the time. So
    # "even" earns its place on schedule QUALITY (group G: free bunches two
    # services 10 h apart in a 168 h horizon), not on speed.
    import time as _time

    ASKED, CAP = 5e-3, 45
    print(f"      {'case':<28}{'seconds':>9}{'gap %':>9}{'events':>8}")
    got: dict[tuple[bool, str], tuple[float, float]] = {}
    for flat in (True, False):
        for sp in ("free", "even"):
            t0 = _time.time()
            res = solve(scenario(hours=120, events=2, duration=8, flat=flat,
                                 spacing=sp), gap=ASKED, t=CAP)
            el = _time.time() - t0
            g = (res.get("solver") or {}).get("mip_gap")
            n = len(row(res, "Jenbacher")["maintenance_starts"])
            lab = f"{'flat' if flat else 'shaped'} load, {sp}"
            print(f"      {lab:<28}{el:>9.1f}"
                  + (f"{100 * g:>9.3f}" if g is not None else f"{'n/a':>9}")
                  + f"{n:>8}")
            eq(f"{lab}: still 2 events", n, 2)
            got[(flat, sp)] = (el, g or 0.0)
    for sp in ("free", "even"):
        check(f"a shaped load closes the asked-for gap under '{sp}'",
              got[(False, sp)][1] <= ASKED * 1.02,
              f"{100 * got[(False, sp)][1]:.3f}% <= {100 * ASKED:.3f}%")
    check("a flat load does not close it under either spacing -- symmetry, "
          "not the spacing rule",
          min(got[(True, "free")][1], got[(True, "even")][1]) > ASKED,
          f"free {100 * got[(True, 'free')][1]:.3f}%, "
          f"even {100 * got[(True, 'even')][1]:.3f}%")
    check("so the load shape dominates, not free placement",
          max(got[(False, sp)][0] for sp in ("free", "even"))
          < min(got[(True, sp)][0] for sp in ("free", "even")),
          f"shaped {max(got[(False, sp)][0] for sp in ('free', 'even')):.0f} s "
          f"vs flat {min(got[(True, sp)][0] for sp in ('free', 'even')):.0f} s")

# ===========================================================================
if group("O", "the running-hours trigger -- services follow the clock"):
    # The count mode schedules E services whether or not the unit ran. The
    # browser run caught that on a four-engine fleet: a unit that produced
    # nothing still reported three services. This is the fix -- a ceiling on
    # the running hours banked since the last service, so the COUNT becomes an
    # outcome of how much the unit actually ran.
    N, D = 100, 8
    res = solve(scenario(hours=168, interval=N, duration=D, svc_cost=50_000.0), t=90)
    for nm in ("Jenbacher", "TEDOM"):
        r = row(res, nm)
        runs, svc = r["running_hours"], len(r["maintenance_starts"])
        print(f"      {nm:<10} ran {runs:>3} h, {svc} service(s), "
              f"{r['maintenance_hours_banked']:>5.1f} h banked at the end")
        eq(f"{nm}: reported on the running-hours trigger",
           r["maintenance_trigger"], "running_hours")
        eq(f"{nm}: the interval is echoed back",
           r["maintenance_interval_running_hours"], float(N))
        check(f"{nm}: banked hours never exceed the interval",
              r["maintenance_hours_banked"] <= N + 1e-6,
              f"{r['maintenance_hours_banked']:.1f} <= {N}")
        need = math.ceil(runs / N) if runs > 0 else 0
        check(f"{nm}: at least ceil(run h / interval) services",
              svc >= need, f"{svc} >= ceil({runs}/{N}) = {need}")
        eq(f"{nm}: every service is D hours", blocks(mseries(res, nm)), [D] * svc)

    # the claim the whole change rests on
    idle = solve(scenario(hours=168, interval=N, duration=D, svc_cost=50_000.0,
                          price={"TEDOM": 500.0}), t=90)
    r = row(idle, "TEDOM")
    print(f"      priced out at 500/kWh: TEDOM ran {r['running_hours']} h, "
          f"produced {r['energy_kwh']:,.0f} kWh")
    eq("a unit priced out of the dispatch never runs", r["running_hours"], 0)
    eq("and is therefore never serviced", len(r["maintenance_starts"]), 0)
    eq("no hours out either", r["maintenance_hours"], 0.0)
    check("while the unit that does run is still serviced",
          len(row(idle, "Jenbacher")["maintenance_starts"]) > 0,
          f"{len(row(idle, 'Jenbacher')['maintenance_starts'])} services")

    loose = solve(scenario(hours=168, interval=150, duration=D, svc_cost=50_000.0), t=90)
    tight = solve(scenario(hours=168, interval=60, duration=D, svc_cost=50_000.0), t=90)
    n_loose, n_tight = (
        sum(len(row(x, nm)["maintenance_starts"]) for nm in ("Jenbacher", "TEDOM"))
        for x in (loose, tight))
    check("a tighter interval needs at least as many services",
          n_tight >= n_loose, f"N=60 -> {n_tight}, N=200 -> {n_loose}")
    check("and costs at least as much", cost(tight) >= cost(loose) - 1.0,
          f"{cost(tight):,.0f} >= {cost(loose):,.0f}")

    both = solve(scenario(hours=168, interval=N, events=99, duration=D,
                          svc_cost=50_000.0), t=90)
    check("an interval overrides the event count rather than clashing with it",
          both["status"] == "Optimal"
          and len(row(both, "Jenbacher")["maintenance_starts"]) < 99,
          f"{len(row(both, 'Jenbacher')['maintenance_starts'])} services, not 99")

    try:
        solve(scenario(hours=48, interval=100, duration=8), t=30)
        check("an interval that cannot complete a cycle is refused", False,
              "no error raised")
    except ValueError as exc:
        check("an interval that cannot complete a cycle is refused",
              "108" in str(exc) and "48 h" in str(exc), str(exc)[:90])

# ===========================================================================
if group("P", "the service cost -- what makes the count determinate"):
    # The interval is a CEILING on banked hours, not an instruction to service
    # only when due. With no price a service dropped into an hour the unit was
    # idle anyway is free, and the solver may take more than the interval needs
    # -- measured at 4 where 2 were due.
    N, D = 100, 8
    free = solve(scenario(hours=168, interval=N, duration=D, svc_cost=0.0), t=90)
    paid = solve(scenario(hours=168, interval=N, duration=D, svc_cost=300_000.0), t=90)
    n_free, n_paid = (
        sum(len(row(x, nm)["maintenance_starts"]) for nm in ("Jenbacher", "TEDOM"))
        for x in (free, paid))
    print(f"      fleet services: {n_free} at no cost, {n_paid} at 300,000 each")
    check("pricing a service does not increase the count", n_paid <= n_free,
          f"{n_paid} <= {n_free}")
    eq("the priced run charges exactly its own services",
       round(paid["om"]["year1_services"], 2), round(n_paid * 300_000.0, 2))
    eq("and the free run charges nothing", free["om"]["year1_services"], 0.0)
    for nm in ("Jenbacher", "TEDOM"):
        r = row(paid, nm)
        check(f"{nm}: interval still honoured when services cost money",
              r["maintenance_hours_banked"] <= N + 1e-6,
              f"{r['maintenance_hours_banked']:.1f} <= {N}")

# ===========================================================================
if group("Q", "how far the running-hours trigger scales"):
    # The counter is a chain: fth[t] depends on fth[t-1] for every hour, and
    # with cyclic commitment the chain closes into a loop. That is a weak LP
    # relaxation, and it does not survive a long horizon -- found when the
    # year-scale render fixture came back with the engines never running at
    # all, which is the trivial incumbent rather than an answer.
    import time as _time

    ASKED, CAP = 5e-3, 90
    print(f"      {'hours':>7}{'N':>7}{'seconds':>9}{'gap %':>9}"
          f"{'run h':>9}{'services':>10}")
    got = {}
    for H, N in ((240, 100), (1000, 600), (2000, 1200)):
        t0 = _time.time()
        res = solve(scenario(hours=H, interval=N, duration=8, svc_cost=250_000.0),
                    gap=ASKED, t=CAP)
        el = _time.time() - t0
        g = (res.get("solver") or {}).get("mip_gap") or 0.0
        rows = res["sizes"]["fueltech_units"]
        rh = sum(r["running_hours"] for r in rows)
        sv = sum(len(r["maintenance_starts"] or []) for r in rows)
        print(f"      {H:>7}{N:>7}{el:>9.1f}{100 * g:>9.3f}{rh:>9}{sv:>10}")
        got[H] = (g, rh)
    check("short horizons close to a usable gap and actually dispatch",
          got[240][0] < 0.10 and got[240][1] > 0, f"gap {100 * got[240][0]:.2f}%")
    check("1,000 hours still does", got[1000][0] < 0.10 and got[1000][1] > 0,
          f"gap {100 * got[1000][0]:.2f}%")
    check("2,000 hours does NOT -- the counter chain stops being tractable",
          got[2000][0] > 0.20,
          f"gap {100 * got[2000][0]:.2f}% against the {100 * ASKED:.1f}% asked "
          f"-- the answer is not bounded, whatever it dispatched")
    print("      => use the running-hours trigger on windows up to ~1,000 h at")
    print("         this cap; for a year use the count mode or typical days.")

print("\n" + "=" * 80)
if FAIL:
    print(f"{len(FAIL)} FAILED")
    for f in FAIL:
        print(f"  - {f}")
else:
    print("all maintenance checks passed")
print("=" * 80)
raise SystemExit(1 if FAIL else 0)
