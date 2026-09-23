"""Checks on the night-shutdown states in ``tools/night_states_case.py``.

Five groups, in the order the doubts arise:

  A. the cut-off rule      every input the case needs is already a stock
                           ``reopt_core`` field, so nothing had to be patched
  B. how a state is built  A is must-run, B drops one engine at night, C drops
                           both, FREE is unconstrained -- and only through
                           ``production_factor_series`` and ``min_up_hours``
  C. the arithmetic        the minimum-load shelves, the night surplus, and what
                           the battery can physically absorb of it
  D. the counters          starts off the generation series; the cost rebuilt
                           line by line adds up to the reported total
  E. one real solve        the states dispatch as described and the energy
                           balance closes hour by hour

    python tools/test_night_states.py
"""

from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import fields

from reopt_core import model as M
from tools import night_states_case as K

FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'OK' if ok else 'XX'}  {name:<60} {detail}")
    if not ok:
        FAIL.append(name)
    return ok


def close(name: str, got: float, want: float, rtol: float = 1e-9) -> bool:
    ok = abs(got - want) <= rtol * max(1.0, abs(want))
    return check(name, ok, f"{got:>16,.4f} vs {want:>16,.4f}")


DAY = K.day_profile()
H = len(DAY)
NIGHT = set(K.NIGHT_HOURS)

# ===========================================================================
print("A. the cut-off rule -- is anything actually missing from reopt_core?")
# ===========================================================================
ft = {f.name for f in fields(M.FuelTechInputs)}
sc = {f.name for f in fields(M.ScenarioInputs)}
st = {f.name for f in fields(M.StorageInputs)}
need_ft = ["start_cost", "min_up_hours", "min_down_hours", "max_starts_per_day",
           "min_turn_down_fraction", "can_curtail", "production_factor_series",
           "om_cost_per_running_hour", "min_kw", "max_kw", "om_cost_per_kwh"]
for n in need_ft:
    check(f"FuelTechInputs.{n} exists", n in ft)
check("ScenarioInputs.fuel_techs -- a fleet of distinct units", "fuel_techs" in sc)
check("ScenarioInputs.cyclic_commitment", "cyclic_commitment" in sc)
check("StorageInputs.discharge_cost_per_kwh -- the BESS wear cost",
      "discharge_cost_per_kwh" in st)
check("StorageInputs.soc_min_fraction", "soc_min_fraction" in st)
print("    -> multi-unit commitment for 2 distinct CHP units is already in the core,")
print("       so the cut-off rule's condition is not met and nothing is patched.")

src = open(K.__file__, encoding="utf-8").read()
for bad in ("pulp.", "LpVariable", "lpSum", "+= ", "M.solve(inp, time_limit"):
    pass
check("the case never imports pulp", "import pulp" not in src)
check("the case never touches reopt_core internals",
      "_model" not in src and "model._" not in src)
print()

# ===========================================================================
print("B. how each state is built")
# ===========================================================================
built = {s: K.build(DAY, s, battery=True) for s in K.STATES}

for s in K.STATES:
    fleet = built[s].fuel_techs
    check(f"State {s}: both engines present, fixed nameplate",
          len(fleet) == 2 and all(u.min_kw == u.max_kw for u in fleet),
          ", ".join(f"{u.name} {u.min_kw:,.0f} kW" for u in fleet))

# A: must-run, nobody may shut down
check("A: min_up_hours spans the horizon for both engines",
      all(u.min_up_hours == H for u in built["A"].fuel_techs), f"{H} h")
check("A: no availability window -- both engines available every hour",
      all(u.production_factor_series is None for u in built["A"].fuel_techs))

# B: Jenbacher off at night, TEDOM untouched
pf_b = built["B"].fuel_techs[0].production_factor_series
check("B: Jenbacher unavailable exactly in the night window",
      pf_b is not None and {t for t in range(H) if pf_b[t] == 0.0} == NIGHT,
      f"hours {sorted(NIGHT)}")
check("B: TEDOM stays available all day",
      built["B"].fuel_techs[1].production_factor_series is None)
check("B: neither engine is forced must-run",
      all(u.min_up_hours == 1 for u in built["B"].fuel_techs))

# C: both off at night
check("C: both engines unavailable in the night window",
      all(u.production_factor_series is not None
          and {t for t in range(H) if u.production_factor_series[t] == 0.0} == NIGHT
          for u in built["C"].fuel_techs))

# FREE: nothing imposed
check("FREE: no availability window and no must-run",
      all(u.production_factor_series is None and u.min_up_hours == 1
          for u in built["FREE"].fuel_techs))

# the shared settings
f0 = built["A"].fuel_techs[0]
close("energy cost is 22 per kWh of rated output", f0.om_cost_per_kwh, K.FUEL_PER_KWH)
close("start cost is the revised 3,000", f0.start_cost, 3_000.0)
check("spill is allowed (surplus can be dumped)", f0.can_curtail is True)
check("no thermal side -- the heat is cut out, as stated",
      f0.thermal_efficiency_full_load == 0.0
      and built["A"].heating_loads_kw is None)
check("zero export", built["A"].compensation_type == "no_compensation")
bat = built["A"].storage
close("BESS power", bat.max_kw, 2_500.0)
close("BESS energy", bat.max_kwh, 5_500.0)
close("BESS round trip is 88%", bat.charge_efficiency * bat.discharge_efficiency, 0.88)
close("BESS wear", bat.discharge_cost_per_kwh, 0.50)
close("BESS minimum state of charge", bat.soc_min_fraction, 0.30)
check("BESS state of charge closes over the day", bat.optimize_soc_init_fraction is True)
check("no BESS in the no-battery build",
      K.build(DAY, "A", battery=False).storage.enabled is False)
grid = built["A"].tariff.energy_cost_per_kwh
check("grid price is flat at 60", min(grid) == max(grid) == K.GRID_PER_KWH)
fin = built["A"].financial
check("finance is off -- the objective is plain operating cost",
      fin.analysis_years == 1 and fin.offtaker_discount_rate_fraction == 0.0
      and fin.offtaker_tax_rate_fraction == 0.0
      and fin.elec_cost_escalation_rate_fraction == 0.0)
print()

# ===========================================================================
print("C. the arithmetic of the minimum-load rule")
# ===========================================================================
j_kw, t_kw = K.UNITS[0][1], K.UNITS[1][1]
close("Jenbacher at 90%", 0.90 * j_kw, 960.3)
close("TEDOM at 90%", 0.90 * t_kw, 1_080.0)
close("both at 90% -- the task's 2,040 kW shelf", 0.90 * (j_kw + t_kw), 2_040.3)
close("night surplus at 90%", 0.90 * (j_kw + t_kw) - K.NIGHT_KW, 940.3)
close("both at 50%", 0.50 * (j_kw + t_kw), 1_133.5)
close("night surplus at 50%", 0.50 * (j_kw + t_kw) - K.NIGHT_KW, 33.5)
check("at 50% the shelf nearly fits the night load -- no deadlock to break",
      0.50 * (j_kw + t_kw) - K.NIGHT_KW < 50.0, "33.5 kW over")

n_hours = len(K.NIGHT_HOURS)
surplus = (0.90 * (j_kw + t_kw) - K.NIGHT_KW) * n_hours
close("surplus over the whole night window at 90% (kWh)", surplus, 940.3 * 6)
usable = K.BESS_KWH * (1.0 - K.BESS_SOC_MIN)
close("BESS usable energy above its 30% floor", usable, 3_850.0)
check("the battery cannot absorb the whole 90% surplus", usable < surplus,
      f"{usable:,.0f} < {surplus:,.0f} kWh")
close("TEDOM alone covers the night at 90% (1,080 <= 1,100 <= 1,200)",
      1.0 if 0.9 * t_kw <= K.NIGHT_KW <= t_kw else 0.0, 1.0)

close("value of one night hour of surplus at 90%", 940.3 * K.FUEL_PER_KWH, 20_686.6)
check("one start is far cheaper than one hour of dumped surplus",
      K.START_COST < 940.3 * K.FUEL_PER_KWH,
      f"3,000 vs {940.3 * K.FUEL_PER_KWH:,.0f}")
print()

# ===========================================================================
print("D. the counters")
# ===========================================================================
close("a unit that never runs has no starts",
      K.starts_from_generation([0.0] * 24), 0)
close("a unit on all day, wrapped, has no starts",
      K.starts_from_generation([500.0] * 24), 0)
off_night = [0.0 if t in NIGHT else 500.0 for t in range(24)]
close("off through the night window is exactly one start",
      K.starts_from_generation(off_night), 1)
close("two separate stops is two starts",
      K.starts_from_generation([0, 0, 5, 5, 0, 0, 5, 5] + [5] * 16), 2)
close("a mid-day dip that does not wrap is one start",
      K.starts_from_generation([5, 5, 0, 0, 5, 5, 5, 5]), 1)
check("the seam is wrapped, not a free start",
      K.starts_from_generation([0.0, 5, 5, 5]) == 1
      and K.starts_from_generation([5, 5, 5, 0.0]) == 1)

# accounting adds up, on a synthetic result shaped like the model's
fake = {
    "status": "Optimal",
    "objective_lifecycle_cost": 0.0,
    "sizes": {"fueltech_units": [
        {"name": "Jenbacher", "energy_kwh": 1_000.0, "spill_kwh": 100.0,
         "running_hours": 18},
        {"name": "TEDOM", "energy_kwh": 2_000.0, "spill_kwh": 0.0,
         "running_hours": 24}]},
    "series": {
        "fueltech_unit_kw": {"Jenbacher": off_night, "TEDOM": [500.0] * 24},
        "grid_kw": [10.0] * 24, "battery_discharge_kw": [20.0] * 24,
        "battery_charge_kw": [5.0] * 24, "unserved_kw": [0.0] * 24,
        "export_kw": [0.0] * 24, "soc_kwh": [1.0] * 24,
        "load_kw": [1.0] * 24, "fueltech_unit_spill_kw": {}},
}
acc = K.account(fake, [1.0] * 24)
close("fuel cost = generation x 22", acc["fuel_cost"], 3_000.0 * 22.0)
close("grid cost = import x 60", acc["grid_cost"], 240.0 * 60.0)
close("starts counted per unit off the generation series", acc["starts"], 1)
close("start cost = starts x 3,000", acc["start_cost"], 3_000.0)
close("BESS wear = discharge x 0.50", acc["wear_cost"], 480.0 * 0.50)
close("total is the sum of its four lines", acc["total"],
      acc["fuel_cost"] + acc["grid_cost"] + acc["start_cost"] + acc["wear_cost"])
close("effective hours = running + starts x 1.5", acc["effective_hours"],
      18 + 24 + 1 * 1.5)
close("served energy is generation less spill", acc["served_kwh"], 3_000.0 - 100.0)

sc2 = K.scale_to(acc, 2_500)
close("scaling to the horizon is linear in the cost", sc2["total"],
      acc["total"] * 2_500 / 24)
close("and in the energy", sc2["gen_kwh"], acc["gen_kwh"] * 2_500 / 24)
close("payback = capex / annual saving", K.payback_years(391_000_000.0, 39_100_000.0),
      10.0)
check("no saving is never, not a divide-by-zero",
      K.payback_years(391_000_000.0, 0.0) == float("inf"))
print()

# ===========================================================================
print("E. the load profile")
# ===========================================================================
raw = K.jsx_day()
check("the factory day is 24 hourly values", len(raw) == 24, f"{len(raw)}")
close("its peak is the 17:00 spike", max(raw), 4_106.0)
check("only the night hours move", all(DAY[t] == raw[t] for t in range(24)
                                      if t not in NIGHT))
check("and they move to the stated night level",
      all(DAY[t] == K.NIGHT_KW for t in NIGHT), f"{K.NIGHT_KW:,.0f} kW")
check("the restart lands on 07:00", max(NIGHT) + 1 == 7)
print()

# ===========================================================================
print("F. one real solve -- do the states dispatch as described?")
# ===========================================================================
runs = {s: K.run_state(DAY, s, battery=False, min_load_pct=90.0, time_limit=120)
        for s in K.STATES}
for s, acc in runs.items():
    check(f"State {s} solves to proven optimality", acc["status"] == "Optimal",
          f"{acc['status']}, gap "
          + ("exact" if not acc.get("mip_gap") else f"{100 * acc['mip_gap']:.4f}%"))

jen, ted = K.UNITS[0][0], K.UNITS[1][0]
gA = runs["A"]["res"]["series"]["fueltech_unit_kw"]
check("A: both engines run all 24 hours", all(
    all(v > 1e-6 for v in gA[n]) for n in (jen, ted)),
    f"{sum(1 for v in gA[jen] if v > 1e-6)} / {sum(1 for v in gA[ted] if v > 1e-6)} h")
check("A: no starts", runs["A"]["starts"] == 0)
check("A: both sit at or above the 90% shelf all night",
      all(gA[jen][t] >= 0.9 * j_kw - 1e-6 and gA[ted][t] >= 0.9 * t_kw - 1e-6
          for t in NIGHT))
check("A: the surplus is dumped", runs["A"]["spill_kwh"] > 1_000.0,
      f"{runs['A']['spill_kwh']:,.0f} kWh/day")

gB = runs["B"]["res"]["series"]["fueltech_unit_kw"]
check("B: Jenbacher is off through the night window",
      all(gB[jen][t] < 1e-6 for t in NIGHT))
check("B: TEDOM carries the night on its own",
      all(gB[ted][t] > 1e-6 for t in NIGHT),
      f"{min(gB[ted][t] for t in NIGHT):,.0f}-{max(gB[ted][t] for t in NIGHT):,.0f} kW")
check("B: exactly one start", runs["B"]["starts"] == 1, f"{runs['B']['starts']}")
# The case as posed says B drops spill to zero. It drops the NIGHT-WINDOW spill
# to zero; the 90% shelf still overhangs at 23:00, where the load is 1,765 kW
# against a 2,040.3 kW floor. That residual is the shelf, not the night rule.
spill_b = runs["B"]["res"]["series"].get("fueltech_unit_spill_kw", {})
night_spill = sum(spill_b.get(n, [0.0] * 24)[t] for n in (jen, ted) for t in NIGHT)
check("B: no spill inside the night window", night_spill < 1e-6,
      f"{night_spill:,.1f} kWh")
close("B: the spill that is left is the 23:00 shelf overhang",
      runs["B"]["spill_kwh"], 0.90 * (j_kw + t_kw) - raw[23], rtol=1e-6)
check("B: so 'spill drops to 0' holds for the night, not the whole day",
      runs["B"]["spill_kwh"] > 1e-6 and runs["B"]["spill_kwh"] < 0.1 * runs["A"]["spill_kwh"],
      f"{runs['B']['spill_kwh']:,.1f} vs A's {runs['A']['spill_kwh']:,.0f} kWh/day")

gC = runs["C"]["res"]["series"]["fueltech_unit_kw"]
check("C: both engines are off through the night window",
      all(gC[n][t] < 1e-6 for n in (jen, ted) for t in NIGHT))
check("C: two starts", runs["C"]["starts"] == 2, f"{runs['C']['starts']}")
check("C: the grid carries the night",
      all(runs["C"]["res"]["series"]["grid_kw"][t] > 1e-6 for t in NIGHT))

# energy balance, hour by hour, in every state
for s, acc in runs.items():
    ser = acc["res"]["series"]
    worst = 0.0
    for t in range(24):
        gen = sum(ser["fueltech_unit_kw"][n][t] for n in (jen, ted))
        spill = sum(ser.get("fueltech_unit_spill_kw", {}).get(n, [0.0] * 24)[t]
                    for n in (jen, ted))
        served = (gen - spill + ser["grid_kw"][t] + ser["battery_discharge_kw"][t]
                  - ser["battery_charge_kw"][t] + ser["unserved_kw"][t]
                  - ser["export_kw"][t])
        worst = max(worst, abs(served - ser["load_kw"][t]))
    check(f"{s}: supply equals load every hour", worst < 1e-5,
          f"max residual {worst:.2e} kW")
    check(f"{s}: nothing unserved and nothing exported",
          acc["unserved_kwh"] < 1e-6 and acc["export_kwh"] < 1e-6)

# the ordering the case turns on, without a battery
check("without the BESS, B is cheaper than A",
      runs["B"]["total"] < runs["A"]["total"],
      f"{runs['B']['total']:,.0f} vs {runs['A']['total']:,.0f} per day")
check("without the BESS, C is the worst of the three",
      runs["C"]["total"] > max(runs["A"]["total"], runs["B"]["total"]),
      f"{runs['C']['total']:,.0f} per day")
check("FREE is no worse than any imposed rule",
      runs["FREE"]["total"] <= min(runs[s]["total"] for s in ("A", "B", "C")) + 1e-6,
      f"{runs['FREE']['total']:,.0f} per day")
print()

print("=" * 82)
if FAIL:
    print(f"{len(FAIL)} FAILED")
    for f in FAIL:
        print(f"  - {f}")
else:
    print("all checks passed")
print("=" * 82)
raise SystemExit(1 if FAIL else 0)
