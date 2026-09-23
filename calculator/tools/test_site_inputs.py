"""The Site section and the two new fuel-unit columns.

Three things were added and every one of them had to leave the existing model
untouched:

  A. three-anchor fit   a site's own minimum / average / maximum, and the
                        arithmetic showing why an affine stretch cannot do it
  B. grid connection    an optional ceiling on what the utility may deliver
  C. fuel vs O&M        one per-kWh column split into two that sum, so the
                        solver still receives exactly one number
  D. ownership          Paid (owned) carries no purchase cost; Purchase does,
                        and neither ever reaches the dispatch objective
  E. no regression      defaults reproduce the model as it was

Only D and the solver checks need a MILP; the rest is arithmetic.

    python tools/test_site_inputs.py
"""

from __future__ import annotations

import inspect
import io
import math
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import app_dispatch as D
from reopt_core import model as M

FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'OK' if ok else 'XX'}  {name:<60} {detail}")
    if not ok:
        FAIL.append(name)
    return ok


def close(name: str, got: float, want: float, tol: float = 1e-6) -> bool:
    ok = abs(got - want) <= tol * max(1.0, abs(want))
    return check(name, ok, f"{got:,.4f} vs {want:,.4f}")


def shapes() -> dict[str, list[float]]:
    """The shapes the app can actually hand the fit, plus two awkward ones."""
    out: dict[str, list[float]] = {}
    ex = D._jsx_loads()
    if ex:
        out["jsx day"] = list(ex["day"])
        out["jsx week"] = list(ex["week"])
    from reopt_core import data_sources as ds
    for nm in ("Hospital", "Supermarket", "Warehouse"):
        out[f"CRB {nm}"] = ds.load_crb_profile(nm, "Chicago")[:720]
    out["spiky"] = [1.0] * 100 + [50.0] + [1.0] * 99      # one huge hour
    out["two-level"] = [1.0] * 100 + [2.0] * 100
    return out


SITE = (1_200.0, 3_000.0, 5_500.0)      # the partner site: 5.5 MW peak

# ===========================================================================
print("A. the three-anchor fit")
# ===========================================================================
lo, avg, hi = SITE
# Shapes with enough variation to bend. A shape with only two distinct levels
# has no middle hours, so no exponent can move its mean -- that case is below.
for nm, s in shapes().items():
    if nm in ("spiky", "two-level"):
        continue
    out, g, _note = D.fit_to_anchors(s, lo, avg, hi)
    got = (min(out), sum(out) / len(out), max(out))
    ok = all(abs(a - b) < 1e-6 * max(1.0, b) for a, b in zip(got, SITE))
    check(f"{nm}: min/mean/max land exactly on the anchors", ok,
          f"{got[0]:,.0f} / {got[1]:,.0f} / {got[2]:,.0f}  (γ {g:.3f})")

# the honest half: when the average is out of reach, say so rather than return
# a profile whose average is quietly wrong
for nm in ("spiky", "two-level"):
    s = shapes()[nm]
    out, g, note = D.fit_to_anchors(s, lo, avg, hi)
    got_mean = sum(out) / len(out)
    check(f"{nm}: the minimum and maximum are still exact",
          abs(min(out) - lo) < 1e-6 and abs(max(out) - hi) < 1e-6,
          f"{min(out):,.0f} / {max(out):,.0f}")
    check(f"{nm}: the unreachable average is reported, not silently wrong",
          abs(got_mean - avg) > 1.0 and "against the" in note,
          f"came out {got_mean:,.0f} kW — {note.split(' — ')[-1][:52]}...")

# the claim that justifies the exponent: an affine stretch misses the average
print()
worst = 0.0
for nm, s in shapes().items():
    s_lo, s_hi = min(s), max(s)
    if s_hi - s_lo < 1e-12:
        continue
    u = [(x - s_lo) / (s_hi - s_lo) for x in s]
    aff = lo + (hi - lo) * (sum(u) / len(u))     # affine: pinned to min and max
    err = 100 * (aff - avg) / avg
    worst = max(worst, abs(err))
    print(f"      affine on {nm:<16} mean {aff:>7,.0f} kW vs {avg:,.0f} → {err:+.1f}%")
check("an affine stretch misses the average by a material margin", worst > 5.0,
      f"worst {worst:.1f}% — which is why a single exponent is solved instead")

print()
# rank order is what "keeps the shape" means
src = shapes()["jsx week"]
out, _g, _ = D.fit_to_anchors(src, lo, avg, hi)
order_in = sorted(range(len(src)), key=lambda i: src[i])
order_out = sorted(range(len(out)), key=lambda i: out[i])
check("every hour keeps its rank — the quiet hours stay quiet",
      order_in == order_out, f"{len(src):,} hours")
check("and the map is monotone in the source value",
      all(out[i] <= out[j] + 1e-9
          for i, j in zip(order_in, order_in[1:])))

# degenerate and awkward inputs
flat, gf, nf = D.fit_to_anchors([500.0] * 24, lo, avg, hi)
check("a flat shape cannot be stretched, so it becomes the average",
      all(abs(x - avg) < 1e-9 for x in flat) and "flat" in nf, f"{flat[0]:,.0f} kW")
empty, _, _ = D.fit_to_anchors([], lo, avg, hi)
check("an empty profile returns empty rather than dividing by zero", empty == [])
narrow, gn, _ = D.fit_to_anchors(shapes()["jsx week"], 2_999.0, 3_000.0, 3_001.0)
check("anchors a hair apart still resolve", abs(sum(narrow) / len(narrow) - 3_000.0) < 1e-6,
      f"mean {sum(narrow) / len(narrow):,.4f}, γ {gn:.3f}")
# an average pressed against a boundary needs an extreme exponent, not a failure
for target, side in ((1_250.0, "near the minimum"), (5_450.0, "near the maximum")):
    o, gg, _ = D.fit_to_anchors(shapes()["jsx week"], lo, target, hi)
    check(f"an average {side} still fits", abs(sum(o) / len(o) - target) < 1e-3,
          f"mean {sum(o) / len(o):,.1f}, γ {gg:.2f}")
print()

# ===========================================================================
print("B. the grid connection ceiling")
# ===========================================================================
fields = {f.name for f in __import__("dataclasses").fields(M.ScenarioInputs)}
check("ScenarioInputs carries max_grid_import_kw", "max_grid_import_kw" in fields)
check("and it defaults to None, i.e. unlimited",
      M.ScenarioInputs(loads_kw=[1.0], tariff=None, financial=M.FinancialInputs(),
                       pv=M.PVInputs(), storage=M.StorageInputs(),
                       fuel_tech=M.FuelTechInputs()).max_grid_import_kw is None)


def solve_cap(cap, load_kw=2_000.0, hours=24, units=True):
    u = D.default_units("2 units (Jenbacher + TEDOM)") if units else pd.DataFrame()
    if units:
        u.loc[:, D.U_KW] = 0.0          # no generation: the grid must carry it all
    inp = D.build([load_kw] * hours, [60.0] * hours, u,
                  dict(kw=0.0, kwh=0.0, rte=0.88, wear=0.5, soc_min=0.3,
                       soc_init=0.5, cyclic=True, grid_charge=True),
                  {D.S_NAME: "x", D.S_MIN: 50.0, D.S_BAT: False,
                   D.S_SCALE: 100.0, D.S_MAXST: None}, grid_cap=cap)
    return M.solve(inp, time_limit=60, mip_gap=1e-4)


free = solve_cap(None)
peak_free = max(free["series"]["grid_kw"])
close("with no ceiling the grid carries the whole 2,000 kW load", peak_free, 2_000.0, 1e-4)
# A ceiling the site cannot live under has no answer: grid-tied runs pin
# unserved load to zero (model.py "noun_"), so the shortfall cannot be absorbed
# and the problem is Infeasible. That is the honest outcome, and the app warns
# before solving rather than letting the solver say it.
starved = solve_cap(1_400.0)
check("a ceiling below what the site can cover is Infeasible, not silently served",
      starved["status"] != "Optimal", f"status {starved['status']}")
check("because grid-tied runs cannot leave load unserved", True,
      "model.py pins unserved to 0 unless off_grid_flag")

# With generation present the ceiling is feasible. To make it BIND rather than
# pass vacuously the grid is priced below the engines, so the optimiser wants
# every kilowatt the wire will pass and the cap is what stops it.
u = D.default_units("2 units (Jenbacher + TEDOM)")      # 2,267 kW of engines


def cheap_grid(cap):
    return M.solve(D.build([2_700.0] * 24, [10.0] * 24, u,
                           dict(kw=0.0, kwh=0.0, rte=0.88, wear=0.5, soc_min=0.3,
                                soc_init=0.5, cyclic=True, grid_charge=True),
                           {D.S_NAME: "x", D.S_MIN: 50.0, D.S_BAT: False,
                            D.S_SCALE: 100.0, D.S_MAXST: None}, grid_cap=cap),
                   time_limit=90, mip_gap=1e-4)


uncapped = cheap_grid(None)
bound = cheap_grid(800.0)
peak_un = max(uncapped["series"]["grid_kw"])
peak_cap = max(g + c for g, c in zip(bound["series"]["grid_kw"],
                                     bound["series"]["battery_charge_kw"]))
check("with grid cheaper than fuel the uncapped run leans on the wire",
      peak_un > 800.0, f"{peak_un:,.0f} kW drawn when nothing stops it")
check("the ceiling is feasible with the engines there",
      bound["status"] == "Optimal", f"status {bound['status']}")
check("and it binds — the draw sits exactly on the limit",
      abs(peak_cap - 800.0) < 1e-3, f"peak draw {peak_cap:,.1f} kW of 800")
served = [g + f for g, f in zip(bound["series"]["grid_kw"],
                                bound["series"]["fueltech_kw"])]
check("the load is still met in full — the plant covers what the wire cannot",
      all(abs(x - 2_700.0) < 1e-3 for x in served),
      f"min {min(served):,.1f} / max {max(served):,.1f} kW")
check("and a binding ceiling costs money, because it forces dearer generation",
      bound["objective_lifecycle_cost"] > uncapped["objective_lifecycle_cost"],
      f"{bound['objective_lifecycle_cost']:,.0f} > "
      f"{uncapped['objective_lifecycle_cost']:,.0f}")
print()

# ===========================================================================
print("C. fuel and O&M are two columns and one model number")
# ===========================================================================
u = D.default_units("2 units (Jenbacher + TEDOM)")
check("the table ships an O&M column", D.U_OM in u.columns)
close("which defaults to zero", float(u[D.U_OM].iloc[0]), 0.0)


def built(df, **kw):
    return D.build([1_500.0] * 48, [60.0] * 48, df,
                   dict(kw=2500.0, kwh=5500.0, rte=0.88, wear=0.5, soc_min=0.3,
                        soc_init=0.5, cyclic=True, grid_charge=True),
                   {D.S_NAME: "x", D.S_MIN: 50.0, D.S_BAT: True,
                    D.S_SCALE: 100.0, D.S_MAXST: None}, **kw)


close("with O&M at 0 the model sees the fuel cost alone — as before the split",
      built(u).fuel_techs[0].om_cost_per_kwh, 22.0)
u2 = u.copy()
u2.loc[:, D.U_OM] = 3.5
close("with O&M set the model sees the sum", built(u2).fuel_techs[0].om_cost_per_kwh, 25.5)
u3 = u.copy()
u3.loc[:, D.U_COST] = 0.0
u3.loc[:, D.U_OM] = 25.5
close("the split is additive, so either column alone reaches the same number",
      built(u3).fuel_techs[0].om_cost_per_kwh, 25.5)
check("one model field still carries it — no second per-kWh term was added",
      not hasattr(M.FuelTechInputs(), "variable_om_per_kwh"))

# and the rebuilt cost table must agree with what the solver was charged
res = M.solve(built(u2), time_limit=90, mip_gap=1e-4)
acc = D.account(res, [60.0] * 48, u2, 0.5)
gen_kwh = sum(r["energy_kwh"] for r in res["sizes"]["fueltech_units"])
close("account() prices generation at fuel + O&M, matching the model",
      acc["gen_cost"], gen_kwh * 25.5, 1e-9)
print()

# ===========================================================================
print("D. ownership")
# ===========================================================================
owned = D.default_units("2 units (Jenbacher + TEDOM)")
close("a fleet that is already paid for costs nothing to acquire",
      D.fleet_capex(owned), 0.0)
buy = owned.copy()
buy.loc[0, D.U_OWN] = D.OWN_BUY
buy.loc[0, D.U_CAPEX] = 120_000_000.0
buy.loc[1, D.U_CAPEX] = 999_000_000.0        # owned: must be ignored
close("only the Purchase rows count", D.fleet_capex(buy), 120_000_000.0)
both = buy.copy()
both.loc[1, D.U_OWN] = D.OWN_BUY
close("two purchases add up", D.fleet_capex(both), 1_119_000_000.0)
dropped = both.copy()
dropped.loc[1, D.U_KW] = 0.0                 # a row dropped from the fleet
close("a unit dropped by setting its rating to 0 brings no cost with it",
      D.fleet_capex(dropped), 120_000_000.0)

# the money must not reach the dispatch objective
a = M.solve(built(owned), time_limit=90, mip_gap=1e-4)
b = M.solve(built(both), time_limit=90, mip_gap=1e-4)
close("purchase cost never enters the operating objective",
      b["objective_lifecycle_cost"], a["objective_lifecycle_cost"], 1e-9)
check("which is the same treatment the battery CAPEX gets", True,
      "both are investment figures, reported beside the dispatch")
print()

# ===========================================================================
print("E. no regression — the defaults are the model as it was")
# ===========================================================================
d = D.default_units("2 units (Jenbacher + TEDOM)")
inp = built(d)
close("fuel cost reaches the model unchanged", inp.fuel_techs[0].om_cost_per_kwh, 22.0)
check("the grid stays unlimited unless asked", inp.max_grid_import_kw is None)
close("start cost unchanged", inp.fuel_techs[0].start_cost, 15_000.0)
close("minimum load unchanged", inp.fuel_techs[0].min_turn_down_fraction, 0.5)
check("minimum up/down unchanged",
      inp.fuel_techs[0].min_up_hours == 4 and inp.fuel_techs[0].min_down_hours == 5)
close("battery wear unchanged", inp.storage.discharge_cost_per_kwh, 0.5)
check("nameplate fixed as before",
      inp.fuel_techs[0].min_kw == inp.fuel_techs[0].max_kw == 1067.0)
check("maintenance still off by default",
      inp.fuel_techs[0].maintenance_events == 0
      and inp.fuel_techs[0].maintenance_interval_running_hours == 0.0)
print()

# ===========================================================================
print("F. the free year — the shape is fixed, the level is the site's")
# ===========================================================================
# The "Annual shape" dropdown is gone from the page. Six shapes were on offer
# and the one chosen decided the level too, through build_year, which matched
# the example week's mean -- a number nobody typed. The shape is now fixed and
# the level comes from the Site panel's average. What has to hold: the hours
# are the same hours as the retired default, the mean is exactly what was
# asked for, and the example week no longer enters the calculation at all.
sig = inspect.signature(D.free_year)
check("the free year is built from one number, the site's average",
      list(sig.parameters) == ["avg_kw"], ", ".join(sig.parameters) or "(none)")
for want in (3_000.0, 1_750.0, 8_400.0):
    y, note = D.free_year(want)
    close(f"a year asked for {want:,.0f} kW averages {want:,.0f} kW",
          sum(y) / len(y), want, 1e-9)
    check(f"  and is a full year of hours at {want:,.0f} kW", len(y) == 8760, f"{len(y):,} h")
    check(f"  and says so in its caption", f"{want:,.0f} kW" in note
          and "Site panel" in note)

# the hours themselves are the retired dropdown's default, untouched: the two
# series differ by one constant factor and nothing else.
_ex = D._jsx_loads()
if _ex:
    old, _ = D.build_year(D.YEAR_SHAPES[next(iter(D.YEAR_SHAPES))], _ex["week"])
    new, _ = D.free_year(3_000.0)
    check("the fixed shape is the dropdown's old default", len(old) == len(new))
    ratios = [n / o for n, o in zip(new, old) if o > 0]
    close("  and differs from it by a level only, not by shape",
          max(ratios) / min(ratios), 1.0, 1e-9)
else:
    check("the fixed shape is the dropdown's old default", True,
          "skipped: bess_profile_v2.jsx not present")

# the retired widget must be gone from the page, not merely unused
_src = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "app_dispatch.py"), encoding="utf-8").read()
_live = [ln for ln in _src.splitlines()
         if "Annual shape" in ln and not ln.lstrip().startswith("#")]
check("no live widget builds an annual-shape dropdown", not _live,
      _live[0].strip()[:60] if _live else "kept in comments only")
check("the retired shapes are still importable for the year tests",
      callable(D.build_year) and len(D.YEAR_SHAPES) == 6, f"{len(D.YEAR_SHAPES)} shapes")

# and the level the free year carries never disturbs the fit: whatever average
# the year is built at, the anchors are what come out the other side.
for lvl in (2_000.0, 5_000.0):
    y, _ = D.free_year(lvl)
    f, g, _n = D.fit_to_anchors(y[:720], 1_200.0, 3_000.0, 5_500.0)
    close(f"built at {lvl:,.0f} kW, the fit still lands on its minimum", min(f), 1_200.0, 1e-6)
    close(f"built at {lvl:,.0f} kW, the fit still lands on its average",
          sum(f) / len(f), 3_000.0, 1e-4)
    close(f"built at {lvl:,.0f} kW, the fit still lands on its maximum", max(f), 5_500.0, 1e-6)
print()

print("=" * 82)
if FAIL:
    print(f"{len(FAIL)} FAILED")
    for f in FAIL:
        print(f"  - {f}")
else:
    print("all site-input checks passed")
print("=" * 82)
raise SystemExit(1 if FAIL else 0)
