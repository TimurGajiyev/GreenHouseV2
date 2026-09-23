"""Night shutdown: States A / B / C for the two-engine plant, and the BESS payback.

**Not REopt.** This belongs to the Custom dispatch study (``app_dispatch.py``),
like everything else that needs per-unit start costs and operating rules. The
engine is ``reopt_core.model`` with the finance switched off, so the objective is
the plain operating cost of the horizon.

The question: at night the factory drops to 1,100 kW, and the two engines held on
their 90% shelf make 2,040 kW between them. Is it cheaper to hold both on and
dump the surplus, to shut one down, or to shut both down and buy from the grid?

    STATE A  both engines stay online at their minimum load (baseload override)
    STATE B  one engine off through the night window, the other carries the load
    STATE C  both engines off, grid and battery carry the night
    FREE     no rule at all -- the MILP commits whatever is cheapest

    python tools/night_states_case.py                     the table, 24-h day
    python tools/night_states_case.py --crossover         sweep for where B beats A
    python tools/night_states_case.py --min-load=50       the 50% rule instead of 90%
    python tools/night_states_case.py --horizon=2500      scale to the payback horizon
    python tools/night_states_case.py --chart=out.png     dispatch of every state

The "cut off" rule does not bite here
-------------------------------------
The rule says: if REopt Core cannot express multi-unit commitment, part-load
curves or per-unit thermal tracking, cut the feature rather than patch the model.
``reopt_core`` already expresses all of the commitment this case needs, as stock
inputs that predate it -- ``FuelTechInputs.start_cost``, ``min_up_hours``,
``min_down_hours``, ``max_starts_per_day``, ``min_turn_down_fraction``,
``can_curtail`` (spill), ``production_factor_series`` (availability), and
``ScenarioInputs.fuel_techs`` for a fleet of distinct machines. Nothing here
adds a constraint, a variable or a term to the model. What is cut is the same
thing ``app_dispatch`` always cuts: part-load *efficiency curves* (each engine
burns a flat 22 ₸ per kWh of rated output) and the heat side (no thermal load,
no thermal tracking). Both are stated, not worked around.

How a state is imposed
----------------------
Without touching the model:

  * **off** in a given hour -- ``production_factor_series[t] = 0``. That is the
    documented availability/maintenance input; it drives ``ftgen[t] <= pf*size``
    to zero, which is what "this engine is not running then" means.
  * **must-run** -- ``min_up_hours = H``. Cyclic commitment closes the horizon,
    so a unit that starts must stay up for the whole of it: the schedule
    collapses to "on throughout" or "off throughout", and at 22 ₸ against a
    60 ₸ grid the optimiser always picks on. The run reports the running hours
    of every unit so that choice is visible rather than assumed.

Starts are counted from the generation series, not from the model's on/off
binary. With availability forced to zero the binary is free to stay latched on
(nothing in the model pays for an idle hour), which would hide exactly the start
this case is about. A start is an hour where a unit generates and did not in the
hour before, wrapped at the horizon seam -- the physical event.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import model as M
from reopt_core.tariff import flat_tariff

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JSX = os.path.join(ROOT, "bess_profile_v2.jsx")

# ---- the plant ------------------------------------------------------------
UNITS = [("Jenbacher", 1067.0), ("TEDOM", 1200.0)]
FUEL_PER_KWH = 22.0        # ₸ per kWh of rated output, spill included
GRID_PER_KWH = 60.0        # ₸ per kWh imported; no demand charge, no export
START_COST = 3_000.0       # ₸ per start event per unit  (was 15,000)
START_WEAR_HOURS = 1.5     # equivalent running hours per start  (was 15)

BESS_KW, BESS_KWH = 2_500.0, 5_500.0
BESS_RTE = 0.88            # round trip; split sqrt each way, as app_dispatch does
BESS_WEAR = 0.50           # ₸ per kWh discharged
BESS_SOC_MIN = 0.30
BESS_CAPEX = 391_000_000.0  # ₸

NIGHT_KW = 1_100.0         # the factory's night level
NIGHT_HOURS = (1, 2, 3, 4, 5, 6)   # 01:00..06:00; the restart lands on 07:00
MIN_LOAD_PCT = 90.0        # the scenario rule; 50 is the other one
HORIZON_HOURS = 2_500      # the payback horizon the task names
HOURS_PER_YEAR = 8_760

STATES = ("A", "B", "C", "FREE")
STATE_TEXT = {
    "A": "both engines online at minimum load (baseload override)",
    "B": "Jenbacher off through the night window, TEDOM carries it",
    "C": "both engines off, grid and battery carry the night",
    "FREE": "no rule -- the MILP commits whatever is cheapest",
}


# ===========================================================================
# 1. the load
# ===========================================================================

def jsx_day() -> list[float]:
    """The factory's own 24-hour day, out of the artifact this study came from."""
    src = io.open(JSX, encoding="utf-8").read()
    m = re.search(r"^const DATA = (.*?);$", src, re.M | re.S)
    if not m:
        raise SystemExit(f"{JSX}: no DATA block")
    d = json.loads(m.group(1))["chp2"]
    return [float(r[0]) for r in d["day"]["A"]["rows"]]


def day_profile(night_kw: float = NIGHT_KW,
                night_hours: tuple[int, ...] = NIGHT_HOURS) -> list[float]:
    """The factory day with the night window pinned to the stated level.

    The artifact's own day bottoms out at 1,342 kW at midnight; the case as posed
    puts the night at 1,100 kW, which is what the week's minimum (1,114 kW)
    actually reaches. Only the named hours move -- the rest of the day, including
    the 4,106 kW spike at 17:00, is the measured profile.
    """
    day = jsx_day()
    for t in night_hours:
        day[t % 24] = night_kw
    return day


# ===========================================================================
# 2. a state as model inputs
# ===========================================================================

def build(load: list[float], state: str, *, min_load_pct: float = MIN_LOAD_PCT,
          battery: bool, night_hours: tuple[int, ...] = NIGHT_HOURS,
          start_cost: float = START_COST, fuel_per_kwh: float = FUEL_PER_KWH,
          grid_per_kwh: float = GRID_PER_KWH, min_up: int = 1, min_down: int = 1,
          spill: bool = True) -> M.ScenarioInputs:
    """One state, built only out of stock ``reopt_core`` inputs."""
    H = len(load)
    td = min_load_pct / 100.0
    off = {t % 24 for t in night_hours}

    fleet = []
    for i, (name, kw) in enumerate(UNITS):
        # who is off at night in this state
        forced_off = (state == "C") or (state == "B" and i == 0)
        pf = ([0.0 if (t % 24) in off else 1.0 for t in range(H)]
              if forced_off else None)
        # State A's defining rule: nobody may shut down.
        up = H if state == "A" else max(1, min_up)
        fleet.append(M.FuelTechInputs(
            enabled=True, kind="CHP", label="CHP", name=name,
            installed_cost_per_kw=0.0, om_cost_per_kw=0.0,
            om_cost_per_kwh=fuel_per_kwh,          # the energy cost, on rated output
            fuel_cost_per_mmbtu=0.0, electric_efficiency_full_load=0.35,
            thermal_efficiency_full_load=0.0,      # heat side cut out, as stated
            min_kw=kw, max_kw=kw,                  # fixed nameplate
            min_turn_down_fraction=td,
            start_cost=start_cost,
            min_up_hours=up, min_down_hours=max(1, min_down),
            can_curtail=spill,
            production_factor_series=pf,
            macrs_option_years=0, macrs_bonus_fraction=0.0, federal_itc_fraction=0.0))

    eta = math.sqrt(BESS_RTE)
    storage = M.StorageInputs(
        enabled=battery, name="BESS",
        installed_cost_per_kw=0.0, installed_cost_per_kwh=0.0,
        installed_cost_constant=0.0, om_cost_fraction_of_installed_cost=0.0,
        min_kw=BESS_KW if battery else 0.0, max_kw=BESS_KW,
        min_kwh=BESS_KWH if battery else 0.0, max_kwh=BESS_KWH,
        charge_efficiency=eta, discharge_efficiency=eta, grid_charge_efficiency=eta,
        can_grid_charge=True, soc_min_fraction=BESS_SOC_MIN,
        soc_init_fraction=0.5, optimize_soc_init_fraction=True,   # cyclic SoC
        discharge_cost_per_kwh=BESS_WEAR,
        macrs_option_years=0, macrs_bonus_fraction=0.0, total_itc_fraction=0.0)

    tar = flat_tariff(0.0)
    tar.energy_cost_per_kwh = [grid_per_kwh] * HOURS_PER_YEAR
    fin = M.FinancialInputs(
        analysis_years=1, elec_cost_escalation_rate_fraction=0.0,
        om_cost_escalation_rate_fraction=0.0, offtaker_discount_rate_fraction=0.0,
        offtaker_tax_rate_fraction=0.0, fuel_cost_escalation_rate_fraction=0.0)
    return M.ScenarioInputs(
        loads_kw=list(load), tariff=tar, financial=fin, pv=M.PVInputs(enabled=False),
        storage=storage, fuel_tech=fleet[0], fuel_techs=fleet,
        compensation_type="no_compensation")      # zero export


# ===========================================================================
# 3. accounting -- rebuilt from the solution, not read off the objective
# ===========================================================================

def starts_from_generation(series: list[float], *, cyclic: bool = True) -> int:
    """A start is an hour the unit generates when the hour before it did not.

    Counted off the generation series rather than the model's on/off binary:
    when availability is forced to zero the binary may stay latched on at no
    cost, which would hide the very start this case prices.
    """
    n = len(series)
    on = [x > 1e-6 for x in series]
    prev = (lambda t: on[(t - 1) % n]) if cyclic else (lambda t: on[t - 1] if t else False)
    return sum(1 for t in range(n) if on[t] and not prev(t))


def account(res: dict, load: list[float], *, fuel_per_kwh: float = FUEL_PER_KWH,
            grid_per_kwh: float = GRID_PER_KWH, start_cost: float = START_COST,
            wear_hours: float = START_WEAR_HOURS) -> dict:
    """Every line of the operating cost, rebuilt from the dispatch."""
    ser, sz = res["series"], res["sizes"]
    rows = sz.get("fueltech_units") or []
    H = len(load)

    per_unit = []
    for r in rows:
        name = r["name"]
        gen = ser["fueltech_unit_kw"].get(name, [0.0] * H)
        st = starts_from_generation(gen)
        per_unit.append({
            "name": name,
            "energy_kwh": r["energy_kwh"],
            "spill_kwh": r.get("spill_kwh") or 0.0,
            "running_hours": r.get("running_hours") or 0,
            "starts": st,
            "effective_hours": (r.get("running_hours") or 0) + st * wear_hours,
        })

    gen_kwh = sum(u["energy_kwh"] for u in per_unit)
    spill = sum(u["spill_kwh"] for u in per_unit)
    starts = sum(u["starts"] for u in per_unit)
    grid_kwh = sum(ser["grid_kw"])
    dis = sum(ser["battery_discharge_kw"])
    chg = sum(ser["battery_charge_kw"])

    fuel_cost = gen_kwh * fuel_per_kwh
    grid_cost = grid_kwh * grid_per_kwh
    st_cost = starts * start_cost
    wear_cost = dis * BESS_WEAR
    return {
        "hours": H,
        "load_kwh": sum(load),
        "gen_kwh": gen_kwh, "spill_kwh": spill, "grid_kwh": grid_kwh,
        "served_kwh": gen_kwh - spill,
        "charge_kwh": chg, "discharge_kwh": dis,
        "starts": starts,
        "running_hours": sum(u["running_hours"] for u in per_unit),
        "effective_hours": sum(u["effective_hours"] for u in per_unit),
        "fuel_cost": fuel_cost, "grid_cost": grid_cost,
        "start_cost": st_cost, "wear_cost": wear_cost,
        "total": fuel_cost + grid_cost + st_cost + wear_cost,
        "per_unit": per_unit,
        "unserved_kwh": sum(ser["unserved_kw"]),
        "export_kwh": sum(ser["export_kw"]),
        "status": res["status"],
        "objective": res.get("objective_lifecycle_cost"),
    }


def scale_to(acc: dict, hours: int) -> dict:
    """The same accounting stretched to a longer horizon of identical days."""
    k = hours / acc["hours"]
    out = {kk: (vv * k if isinstance(vv, (int, float)) and kk not in ("hours",) else vv)
           for kk, vv in acc.items() if kk not in ("per_unit", "status", "objective")}
    out["hours"] = hours
    out["scale"] = k
    return out


# ===========================================================================
# 4. run
# ===========================================================================

def run_state(load: list[float], state: str, *, battery: bool, time_limit: int = 300,
              wear_hours: float = START_WEAR_HOURS, mip_gap: float | None = 1e-6,
              **kw) -> dict:
    inp = build(load, state, battery=battery, **kw)
    res = M.solve(inp, time_limit=time_limit, mip_gap=mip_gap)
    acc = account(res, load,
                  fuel_per_kwh=kw.get("fuel_per_kwh", FUEL_PER_KWH),
                  grid_per_kwh=kw.get("grid_per_kwh", GRID_PER_KWH),
                  start_cost=kw.get("start_cost", START_COST),
                  wear_hours=wear_hours)
    acc["state"], acc["battery"] = state, battery
    acc["mip_gap"] = (res.get("solver") or {}).get("mip_gap")
    acc["res"] = res
    return acc


def payback_years(capex: float, annual_saving: float) -> float:
    return capex / annual_saving if annual_saving > 1e-9 else float("inf")


def annualise(acc: dict) -> float:
    return acc["total"] * HOURS_PER_YEAR / acc["hours"]


# ===========================================================================
# 5. output
# ===========================================================================

def _f(x: float, w: int = 14, d: int = 0) -> str:
    return f"{x:>{w},.{d}f}"


def print_table(runs: dict[tuple[str, bool], dict], *, horizon: int,
                min_load_pct: float, night_kw: float, night_hours: tuple[int, ...],
                start_cost: float, wear_hours: float) -> None:
    """The comparison matrix the task asks for, plus what it takes to read it."""
    order = [s for s in STATES if (s, True) in runs or (s, False) in runs]
    H24 = next(iter(runs.values()))["hours"]
    k = horizon / H24

    print("=" * 96)
    print(f"STATE COMPARISON   {min_load_pct:.0f}% minimum-load rule"
          f"   night {night_kw:,.0f} kW in hours "
          f"{night_hours[0]:02d}:00-{night_hours[-1]:02d}:00"
          f"   start {start_cost:,.0f} ₸ / {wear_hours:g} h")
    print(f"  one {H24}-hour day, scaled x{k:,.2f} to the {horizon:,}-hour horizon")
    print("=" * 96)

    for bat in (False, True):
        present = [s for s in order if (s, bat) in runs]
        if not present:
            continue
        print(f"\n  {'WITH the 2,500 kW / 5,500 kWh BESS' if bat else 'WITHOUT the BESS'}")
        print(f"    {'':<26}" + "".join(f"{s:>16}" for s in present))
        rows = [
            ("Spill (kWh)", "spill_kwh", 0),
            ("Starts", "starts", 0),
            ("Effective hours", "effective_hours", 1),
            ("Own generation (kWh)", "gen_kwh", 0),
            ("Grid purchase (kWh)", "grid_kwh", 0),
            ("BESS discharged (kWh)", "discharge_kwh", 0),
            ("Fuel cost (₸)", "fuel_cost", 0),
            ("Grid cost (₸)", "grid_cost", 0),
            ("Start cost (₸)", "start_cost", 0),
            ("BESS wear (₸)", "wear_cost", 0),
            ("OPERATING COST (₸)", "total", 0),
        ]
        for lab, key, dec in rows:
            vals = "".join(_f(runs[(s, bat)][key] * (k if key != "starts" else k), 16, dec)
                           if key != "starts" else _f(runs[(s, bat)][key] * k, 16, 0)
                           for s in present)
            print(f"    {lab:<26}" + vals)
        base = runs[(present[0], bat)]["total"] * k
        print(f"    {'vs State ' + present[0] + ' (₸)':<26}"
              + "".join(_f(runs[(s, bat)]["total"] * k - base, 16, 0) for s in present))

        def _g(s: str) -> str:
            g = runs[(s, bat)].get("mip_gap")
            return "exact" if g is None or g != g or abs(g) < 1e-9 else f"{100 * g:.4f}%"
        print(f"    {'MIP gap':<26}" + "".join(f"{_g(s):>16}" for s in present))
        print(f"    {'status':<26}"
              + "".join(f"{runs[(s, bat)]['status'][:16]:>16}" for s in present))


def print_payback(runs: dict[tuple[str, bool], dict], *, horizon: int) -> None:
    """Two payback framings, because conflating them is the known trap."""
    order = [s for s in STATES if (s, True) in runs and (s, False) in runs]
    a_no = annualise(runs[("A", False)]) if ("A", False) in runs else None

    print("\n" + "=" * 96)
    print(f"PAYBACK OF THE BESS   capex {BESS_CAPEX:,.0f} ₸")
    print("=" * 96)
    print(f"    {'':<26}{'annual, no BESS':>20}{'annual, with BESS':>20}"
          f"{'BESS saving/yr':>18}{'payback (yr)':>14}")
    for s in order:
        no, yes = annualise(runs[(s, False)]), annualise(runs[(s, True)])
        sav = no - yes
        pb = payback_years(BESS_CAPEX, sav)
        print(f"    {'State ' + s:<26}{no:>20,.0f}{yes:>20,.0f}{sav:>18,.0f}"
              + (f"{pb:>14,.1f}" if math.isfinite(pb) else f"{'never':>14}"))

    if a_no is not None:
        print(f"\n    As the task defines it -- savings measured against the baseload rule")
        print(f"    (State A without a BESS, {a_no:,.0f} ₸/yr). This bundles the rule")
        print(f"    change with the battery, so it is not the battery's own payback:")
        print(f"    {'':<26}{'annual, with BESS':>20}{'saving vs A':>18}{'payback (yr)':>14}")
        for s in order:
            yes = annualise(runs[(s, True)])
            sav = a_no - yes
            pb = payback_years(BESS_CAPEX, sav)
            print(f"    {'State ' + s:<26}{yes:>20,.0f}{sav:>18,.0f}"
                  + (f"{pb:>14,.1f}" if math.isfinite(pb) else f"{'never':>14}"))


def print_dispatch(runs: dict[tuple[str, bool], dict], state: str, bat: bool) -> None:
    """Hour by hour, so the state is visible rather than asserted."""
    acc = runs.get((state, bat))
    if acc is None:
        return
    ser = acc["res"]["series"]
    names = [n for n, _ in UNITS]
    print(f"\n  Hourly dispatch -- State {state}"
          f"{' with BESS' if bat else ''}   ({STATE_TEXT[state]})")
    print(f"    {'h':>3}{'load':>9}" + "".join(f"{n[:9]:>10}" for n in names)
          + f"{'spill':>9}{'grid':>9}{'chg':>8}{'dis':>8}{'SoC%':>7}")
    soc = ser["soc_kwh"]
    for t in range(acc["hours"]):
        gen = [ser["fueltech_unit_kw"].get(n, [0.0] * acc["hours"])[t] for n in names]
        sp = sum(ser.get("fueltech_unit_spill_kw", {}).get(n, [0.0] * acc["hours"])[t]
                 for n in names)
        pct = 100 * soc[t] / BESS_KWH if bat and BESS_KWH else 0.0
        print(f"    {t:>3}{ser['load_kw'][t]:>9,.0f}"
              + "".join(f"{g:>10,.0f}" for g in gen)
              + f"{sp:>9,.0f}{ser['grid_kw'][t]:>9,.0f}"
              + f"{ser['battery_charge_kw'][t]:>8,.0f}"
              + f"{ser['battery_discharge_kw'][t]:>8,.0f}{pct:>7,.0f}")


# ===========================================================================
# 6. crossover
# ===========================================================================

def crossover(load: list[float], *, min_load_pct: float, battery: bool,
              horizon: int, night_kw: float, night_hours: tuple[int, ...],
              start_cost: float, time_limit: int = 300) -> None:
    """Where does shutting an engine down start to pay?

    Two sweeps, each holding everything else still: the length of the night
    window, and the price of a start. Both are solved, not extrapolated.
    """
    print("\n" + "=" * 96)
    print(f"CROSS-OVER   State B against State A"
          f"   ({'with' if battery else 'without'} the BESS,"
          f" {min_load_pct:.0f}% rule)")
    print("=" * 96)

    base = jsx_day()
    print("\n  1. Night-window length N -- both states re-solved on the same day,")
    print(f"     with hours 01:00..N pinned to {night_kw:,.0f} kW. N=0 is the untouched")
    print(f"     profile: no window to shut down in, so B is A by definition.")
    print(f"    {'N (h)':>7}{'window':>14}{'A (₸/day)':>16}{'B (₸/day)':>16}"
          f"{'B - A':>14}{'A spill':>12}{'B spill':>11}{'B starts':>10}")
    prev_sign = None
    for n in range(0, 13):
        hrs = tuple(range(1, 1 + n))
        ld = day_profile(night_kw, hrs) if n else list(base)
        aa = run_state(ld, "A", battery=battery, min_load_pct=min_load_pct,
                       night_hours=hrs or (1,), start_cost=start_cost,
                       time_limit=time_limit)
        bb = (run_state(ld, "B", battery=battery, min_load_pct=min_load_pct,
                        night_hours=hrs or (1,), start_cost=start_cost,
                        time_limit=time_limit) if n else aa)
        d = bb["total"] - aa["total"]
        win = f"{hrs[0]:02d}:00-{hrs[-1]:02d}:00" if n else "none"
        print(f"    {n:>7}{win:>14}{aa['total']:>16,.0f}{bb['total']:>16,.0f}"
              f"{d:>14,.0f}{aa['spill_kwh']:>12,.0f}{bb['spill_kwh']:>11,.0f}"
              f"{bb['starts']:>10,.0f}")
        sign = d < -0.5
        if prev_sign is not None and sign and not prev_sign:
            print(f"    {'':>7}  ^^^ CROSS-OVER: B overtakes A between "
                  f"N={n - 1} and N={n} hours")
        prev_sign = sign

    print(f"\n  2. Start price -- night window {night_hours[0]:02d}:00-"
          f"{night_hours[-1]:02d}:00, everything else held still")
    print(f"    {'₸/start':>10}{'A (₸/day)':>16}{'B (₸/day)':>16}{'B - A':>16}")
    ld = list(load)
    pts: list[tuple[float, float, float]] = []
    for sc in (0.0, 3_000.0, 15_000.0, 50_000.0, 100_000.0, 150_000.0, 200_000.0):
        aa = run_state(ld, "A", battery=battery, min_load_pct=min_load_pct,
                       night_hours=night_hours, start_cost=sc, time_limit=time_limit)
        bb = run_state(ld, "B", battery=battery, min_load_pct=min_load_pct,
                       night_hours=night_hours, start_cost=sc, time_limit=time_limit)
        print(f"    {sc:>10,.0f}{aa['total']:>16,.0f}{bb['total']:>16,.0f}"
              f"{bb['total'] - aa['total']:>16,.0f}")
        pts.append((sc, aa["total"], bb["total"]))

    # The exact break-even. Once the start price is high enough that neither
    # state moves its commitment any further, B is affine in it: B(s) = c + n*s,
    # with n the starts B carries that A does not. Fit that on the top two
    # points -- both solved, not extrapolated -- and solve B(s) = A. If n does
    # not come out whole, or A moved between them, the dispatch is still
    # shifting and no break-even is claimed.
    (s1, a1, b1), (s2, a2, b2) = pts[-2], pts[-1]
    n = (b2 - b1) / (s2 - s1)
    c = b1 - n * s1
    print()
    if abs(n - round(n)) > 1e-6 or abs(a2 - a1) > 0.5 or round(n) <= 0:
        print(f"    No clean break-even over this range: fitted starts {n:.3f}, "
              f"A moved {a2 - a1:,.0f}.")
        return
    star = (a2 - c) / n
    print(f"    B carries {round(n)} start(s) that A does not, so over the settled")
    print(f"    range B(s) = {c:,.0f} + {round(n)}s against A = {a2:,.0f}.")
    if star < 0:
        print("    => A is cheaper even at a ZERO start price. The start penalty is")
        print("       not what decides this comparison; the surplus is.")
    else:
        print(f"    => BREAK-EVEN START PRICE = {star:,.0f} per start.")
        print(f"       Below it B wins, above it A wins. The case sets "
              f"{start_cost:,.0f}, which is {star / start_cost:,.1f}x lower, so B")
        print(f"       wins by a wide margin and the start penalty is not binding.")


# ===========================================================================
# 7. chart
# ===========================================================================

C_J, C_T, C_DIS, C_CHG = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"
C_GRID_ = "#eda100"
SURFACE, INK, INK_MUTED, GRIDLINE = "#fcfcfb", "#0b0b0b", "#898781", "#e1e0d9"


def chart(runs: dict[tuple[str, bool], dict], path: str, *, battery: bool,
          min_load_pct: float) -> str:
    """One panel per state, same y scale, so the rules are compared by shape."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    present = [s for s in STATES if (s, battery) in runs]
    n = len(present)
    fig, axes = plt.subplots(n, 1, figsize=(12, 2.7 * n + 1.2), sharex=True,
                             gridspec_kw={"hspace": 0.42})
    axes = [axes] if n == 1 else list(axes)
    fig.patch.set_facecolor(SURFACE)
    names = [nm for nm, _ in UNITS]

    top = max(max(runs[(s, battery)]["res"]["series"]["load_kw"]) for s in present) * 1.15
    bot = -BESS_KW * 1.15 if battery else 0.0

    for ax, s in zip(axes, present):
        acc = runs[(s, battery)]
        ser, H = acc["res"]["series"], acc["hours"]
        x = list(range(H))
        g = [ser["fueltech_unit_kw"].get(nm, [0.0] * H) for nm in names]
        stack = [g[0], g[1], ser["battery_discharge_kw"], ser["grid_kw"]]
        labs = [names[0], names[1], "BESS discharge", "Grid import"]
        ax.stackplot(x, *stack, labels=labs, colors=[C_J, C_T, C_DIS, C_GRID_],
                     edgecolor=SURFACE, linewidth=0.5)
        if battery:
            ax.fill_between(x, 0, [-v for v in ser["battery_charge_kw"]], color=C_CHG,
                            label="BESS charge", edgecolor=SURFACE, linewidth=0.5)
        sp = [sum(ser.get("fueltech_unit_spill_kw", {}).get(nm, [0.0] * H)[t]
                  for nm in names) for t in x]
        if any(v > 1e-6 for v in sp):
            ax.plot(x, sp, color="#d03b3b", lw=2.0, ls=(0, (3, 2)), label="Spill")
        ax.plot(x, ser["load_kw"], color=INK, lw=2.0, label="Factory load")
        ax.axhline(0, color="#c3c2b7", lw=1.0)
        ax.set_ylim(bot, top)
        ax.set_ylabel("kW", color=INK, fontsize=10)
        ax.set_title(f"State {s}   {STATE_TEXT[s]}   —   "
                     f"{acc['total']:,.0f} ₸/day, {acc['starts']:.0f} starts, "
                     f"{acc['spill_kwh']:,.0f} kWh spilled",
                     color=INK, fontsize=10.5, loc="left", pad=24, fontweight="bold")
        leg = ax.legend(loc="lower left", bbox_to_anchor=(0, 1.005), ncol=7,
                        frameon=False, fontsize=8.5, handlelength=1.3,
                        columnspacing=1.2, borderpad=0, handletextpad=0.5)
        for tx in leg.get_texts():
            tx.set_color("#52514e")
        ax.grid(axis="y", color=GRIDLINE, lw=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color("#c3c2b7")
        ax.tick_params(colors=INK_MUTED, labelsize=9, length=0)
        ax.set_xlim(0, H - 1)
    axes[-1].set_xlabel("Hour of the day", color=INK, fontsize=10)
    fig.suptitle(f"Night shutdown states   —   {min_load_pct:.0f}% minimum-load rule, "
                 f"{'with' if battery else 'without'} the BESS",
                 color=INK, fontsize=13, fontweight="bold", y=0.997)
    fig.savefig(path, dpi=140, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return path


# ===========================================================================
# 8. CLI
# ===========================================================================

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--min-load", type=float, default=MIN_LOAD_PCT,
                   help="minimum-load rule, %% of nameplate (90 or 50)")
    p.add_argument("--both-rules", action="store_true", help="run 90%% and 50%%")
    p.add_argument("--night-kw", type=float, default=NIGHT_KW)
    p.add_argument("--night-hours", default="1-6", help="e.g. 1-6")
    p.add_argument("--start-cost", type=float, default=START_COST)
    p.add_argument("--wear-hours", type=float, default=START_WEAR_HOURS)
    p.add_argument("--grid", type=float, default=GRID_PER_KWH)
    p.add_argument("--fuel", type=float, default=FUEL_PER_KWH)
    p.add_argument("--horizon", type=int, default=HORIZON_HOURS)
    p.add_argument("--no-spill", action="store_true", help="forbid dumping surplus")
    p.add_argument("--crossover", action="store_true")
    p.add_argument("--dispatch", action="store_true", help="print hour-by-hour tables")
    p.add_argument("--chart", default="")
    p.add_argument("--time-limit", type=int, default=300)
    p.add_argument("--json", default="")
    a = p.parse_args(argv)

    lo, _, hi = a.night_hours.partition("-")
    hrs = tuple(range(int(lo), int(hi or lo) + 1))
    load = day_profile(a.night_kw, hrs)
    print(f"Factory day: {sum(load):,.0f} kWh, peak {max(load):,.0f} kW, "
          f"night {a.night_kw:,.0f} kW in hours {hrs[0]:02d}:00-{hrs[-1]:02d}:00")
    print(f"Fleet: " + ", ".join(f"{n} {kw:,.0f} kW" for n, kw in UNITS)
          + f" at {a.fuel:,.0f} ₸/kWh; grid {a.grid:,.0f} ₸/kWh, zero export")
    dump: dict = {"cases": {}}

    for rule in ([90.0, 50.0] if a.both_rules else [a.min_load]):
        mins = [kw * rule / 100.0 for _, kw in UNITS]
        print(f"\nMinimum-load rule {rule:.0f}%: "
              + " + ".join(f"{m:,.1f}" for m in mins)
              + f" = {sum(mins):,.1f} kW against a {a.night_kw:,.0f} kW night "
              + f"({sum(mins) - a.night_kw:+,.1f} kW)")
        runs: dict[tuple[str, bool], dict] = {}
        for state in STATES:
            for bat in (False, True):
                runs[(state, bat)] = run_state(
                    load, state, battery=bat, min_load_pct=rule,
                    night_hours=hrs, start_cost=a.start_cost, fuel_per_kwh=a.fuel,
                    grid_per_kwh=a.grid, spill=not a.no_spill,
                    time_limit=a.time_limit)
        print_table(runs, horizon=a.horizon, min_load_pct=rule, night_kw=a.night_kw,
                    night_hours=hrs, start_cost=a.start_cost, wear_hours=a.wear_hours)
        print_payback(runs, horizon=a.horizon)
        if a.dispatch:
            for state in STATES:
                print_dispatch(runs, state, True)
        if a.chart:
            stem, ext = os.path.splitext(a.chart)
            for bat in (False, True):
                out = f"{stem}_{int(rule)}_{'bess' if bat else 'nobess'}{ext or '.png'}"
                chart(runs, out, battery=bat, min_load_pct=rule)
                print(f"  chart -> {out}")
        if a.crossover:
            for bat in (False, True):
                crossover(load, min_load_pct=rule, battery=bat, horizon=a.horizon,
                          night_kw=a.night_kw, night_hours=hrs,
                          start_cost=a.start_cost, time_limit=a.time_limit)
        dump["cases"][f"{rule:.0f}"] = {
            f"{s}_{'bess' if b else 'nobess'}":
                {k: v for k, v in acc.items() if k not in ("res",)}
            for (s, b), acc in runs.items()}

    if a.json:
        with io.open(a.json, "w", encoding="utf-8") as fh:
            json.dump(dump, fh, indent=1, default=float)
        print(f"\n  summary -> {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
