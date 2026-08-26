"""Does fuel_intercept_basis='rated' put the part-load curve the right way round?

REopt applies the fuel intercept to the on/off binary alone
(generator_constraints.jl:11), so it is not scaled by machine size. For a unit
bigger than 1 kW that under-states full-load fuel by exactly the intercept's
share, which makes a WORSE part-load efficiency look CHEAPER. 'rated' scales the
intercept by the unit's nameplate, the way PROJECT_FULL writes it (A = ALPHA*Pn).
"""
from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deviation_analysis import build, unit, TOTAL_GEN_KW
from reopt_core import data_sources as ds
from reopt_core import model as M

pf, _ = ds.call_pvwatts_api(39.74437, -105.15199, tilt=20, azimuth=180,
                            array_type=0, module_type=0, losses=14)
H = TOTAL_GEN_KW
cases = [
    ("D0  linear reference",        [unit(H, name="G1")],            "reopt"),
    ("D3  curve, basis=reopt",      [unit(H, half=0.28, name="G1")], "reopt"),
    ("D3r curve, basis=rated",      [unit(H, half=0.28, name="G1")], "rated"),
]
ref = None
print(f"{'case':<28} {'LCC':>14} {'vs D0':>9} {'fuel gal':>11} {'vs D0':>9} {'s':>7}")
for tag, units, basis in cases:
    t0 = time.time()
    r = M.solve(build(units, pf, basis), time_limit=900)
    el = time.time() - t0
    fuel = sum(u["fuel_units"] for u in r["sizes"]["fueltech_units"])
    lcc = r["objective_lifecycle_cost"]
    if ref is None:
        ref = (lcc, fuel)
        d1 = d2 = "  ref  "
    else:
        d1 = f"{lcc/ref[0]-1:+8.3%}"
        d2 = f"{fuel/ref[1]-1:+8.3%}"
    print(f"{tag:<28} ${lcc:>13,.0f} {d1} {fuel:>11,.0f} {d2} {el:>6.1f}")
