"""Variability harness: run the same scenarios through OUR engine and compare
against the numbers harvested from the live REopt tool.

Runs the exact model the Streamlit UI calls (reopt_core.model), so this measures
the calculator, not the widgets. The UI is verified separately.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import data_sources as ds
from reopt_core import emissions as EM
from reopt_core import model as M
from reopt_core.tariff import build_tariff

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REOPT_RESULTS = os.path.join(ROOT, "reopt_test_data", "variability-reopt.json")

# The tool picks whatever rate the dropdown lands on, so mirror the rate it
# actually used, resolved back to its URDB label.
CASES = {
    "V1": dict(lat=41.8781, lon=-87.6298, urdb="687f45e19a6047fc7105198c",
               building="Hospital", annual_kwh=8_000_000, years=30, discount=0.06,
               esc=0.025, land_acres=None, roof_sqft=120_000.0, pv_location="roof",
               compensation="net_metering", nem_limit=1000.0,
               pv=dict(installed_cost_per_kw=1750.0, max_kw=1500.0, om_cost_per_kw=20.0),
               battery=None),
    "V2": dict(lat=47.6062, lon=-122.3321, urdb="5633a2585457a30652bc06b2",
               building="Warehouse", annual_kwh=1_500_000, years=15, discount=0.09,
               esc=0.012, land_acres=3.0, pv=None,
               battery=dict(installed_cost_per_kwh=280.0, installed_cost_per_kw=750.0,
                            installed_cost_constant=0.0, max_kwh=3000.0)),
    "V3": dict(lat=25.7617, lon=-80.1918, urdb="6877df0bffcc8e1d050fa08f",
               building="FullServiceRest", annual_kwh=800_000, years=20, discount=0.08,
               esc=0.03, land_acres=1.0,
               pv=dict(installed_cost_per_kw=2100.0, max_kw=400.0, om_cost_per_kw=20.0),
               battery=dict(installed_cost_per_kwh=400.0, installed_cost_per_kw=1000.0,
                            installed_cost_constant=0.0, max_kwh=1000.0)),
    "V4": dict(lat=35.0844, lon=-106.6504, urdb="539f74b1ec4f024411ed0aef",
               building="MidriseApartment", annual_kwh=2_500_000, years=25, discount=0.07,
               esc=0.02, land_acres=4.0,
               pv=dict(installed_cost_per_kw=1920.0, max_kw=2000.0, om_cost_per_kw=20.0),
               battery=dict(installed_cost_per_kwh=253.0, installed_cost_per_kw=968.0,
                            installed_cost_constant=0.0, max_kwh=5000.0)),
}


def money(s):
    if s is None:
        return None
    m = re.search(r"-?\$?-?([\d,]+(?:\.\d+)?)", str(s))
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return -v if "-" in str(s).split(".")[0][:2] or str(s).strip().startswith("-") else v


def num(s):
    if s is None:
        return None
    m = re.search(r"-?([\d,]+(?:\.\d+)?)", str(s))
    return float(m.group(1).replace(",", "")) if m else None


def cmp_row(name, got, want, unit="", tol=0.02):
    if want is None:
        print(f"   --  {name:<38} {got:>14,.0f} {unit:<5}  (REopt row absent)")
        return None
    if abs(want) < 1e-9:
        ok = abs(got) < 1.0
        d = "—"
    else:
        rel = (got - want) / want
        ok = abs(rel) <= tol
        d = f"{rel:+.2%}"
    print(f"   {'OK ' if ok else 'XX '} {name:<38} {got:>14,.0f} {unit:<5} vs {want:>14,.0f}  {d}")
    return ok


def main() -> None:
    reopt = json.load(io.open(REOPT_RESULTS, encoding="utf-8"))
    v1p = os.path.join(ROOT, "reopt_test_data", "variability-v1.json")
    if os.path.exists(v1p):
        reopt["V1"] = json.load(io.open(v1p, encoding="utf-8"))
    grand = []
    for cid, c in CASES.items():
        rec = reopt.get(cid) or {}
        rows = rec.get("rows")
        print(f"\n{'=' * 74}\n{cid}  {rec.get('url', '').split('/')[-1]}")
        if not rows:
            print("   REopt run failed/absent — skipping comparison")
            continue

        L = ds.build_electric_load(c["building"], c["annual_kwh"], c["lat"], c["lon"])
        tar = build_tariff(ds.fetch_urdb_rate(c["urdb"]))
        pf = [0.0] * 8760
        if c["pv"]:
            pf, _ = ds.call_pvwatts_api(c["lat"], c["lon"], tilt=20, azimuth=180,
                                        array_type=0, module_type=0, losses=14)
        print(f"   city={L['city']}  rate={tar.utility} | {tar.name[:44]}")

        inp = M.ScenarioInputs(
            loads_kw=L["loads_kw"], tariff=tar,
            financial=M.FinancialInputs(analysis_years=c["years"],
                                        elec_cost_escalation_rate_fraction=c["esc"],
                                        offtaker_discount_rate_fraction=c["discount"]),
            pv=M.PVInputs(enabled=bool(c["pv"]), production_factor=pf, **(c["pv"] or {})),
            storage=M.StorageInputs(enabled=bool(c["battery"]), **(c["battery"] or {})),
            fuel_tech=M.FuelTechInputs(enabled=False),
            land_acres=c["land_acres"],
            roof_squarefeet=c.get("roof_sqft"),
            pv_location=c.get("pv_location", "ground"),
            compensation_type=c.get("compensation", "no_compensation"),
            net_metering_limit_kw=c.get("nem_limit"),
        )
        r = M.solve(inp, time_limit=900)
        b = M.business_as_usual(inp)
        sz, u = r["sizes"], r["utility"]

        res = []
        res.append(cmp_row("PV size", sz["pv_kw"], num((rows.get("PV Size") or [None, None])[1]), "kW", 0.06))
        res.append(cmp_row("Battery power", sz["battery_kw"],
                           num((rows.get("Battery Power") or [None, None])[1]), "kW", 0.10))
        res.append(cmp_row("Battery capacity", sz["battery_kwh"],
                           num((rows.get("Battery Capacity") or [None, None])[1]), "kWh", 0.10))
        res.append(cmp_row("Year 1 utility, BAU", b["year1_total"],
                           money((rows.get("Total Year 1 Utility Cost - Before Tax") or [None])[0]),
                           "$", 0.01))
        res.append(cmp_row("Year 1 utility, optimized", u["year1_total"],
                           money((rows.get("Total Year 1 Utility Cost - Before Tax") or [None, None])[1]),
                           "$", 0.02))
        res.append(cmp_row("Life cycle cost, BAU", b["lifecycle_cost"],
                           money((rows.get("Total Life Cycle Costs") or [None])[0]), "$", 0.01))
        res.append(cmp_row("Life cycle cost, optimized", r["objective_lifecycle_cost"],
                           money((rows.get("Total Life Cycle Costs") or [None, None])[1]), "$", 0.02))

        # emissions context: AVERT region + Cambium location must match
        try:
            prof = EM.fetch_avert_profile(c["lat"], c["lon"])
            want_reg = (rows.get("EPA's AVERT Region") or [""])[0]
            ok = prof["avert_region"] == want_reg
            print(f"   {'OK ' if ok else 'XX '} {'AVERT region':<38} {prof['avert_region']:>14} "
                  f"    vs {want_reg:>14}")
            res.append(ok)
        except Exception as exc:
            print(f"   --  AVERT lookup failed: {exc}")

        good = [x for x in res if x is not None]
        print(f"   -> {sum(good)}/{len(good)} match")
        grand.append((cid, sum(good), len(good)))

    print(f"\n{'=' * 74}\nSUMMARY")
    for cid, ok, tot in grand:
        print(f"   {cid}  {ok}/{tot}")
    print(f"   TOTAL {sum(o for _, o, _ in grand)}/{sum(t for _, _, t in grand)}")


if __name__ == "__main__":
    main()
