"""Compare CHP (G1) and Prime Generator (G2) against the live REopt runs.

G1 REopt 7afae73e-2c85-40d3-aa77-2036a4cbaa78
G2 REopt 8100e6cc-52ff-4e74-829a-b9b70c36de82
Both: Golden CO, Large Office 5,000,000 kWh, 5 acres, Intermountain REA B-TOU,
PV $1600/kW max 2000, Battery $300/kWh $800/kW const $0 max 4000, 25 yr,
8.3% discount, 1.7% escalation, fuel $8.00/MMBtu.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import data_sources as ds
from reopt_core import defaults as D
from reopt_core import model as M
from reopt_core.tariff import build_tariff

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAT, LON = 39.74437, -105.15199
URDB = "5b44ffc75457a36716a907eb"


def money(s):
    if s is None:
        return None
    neg = str(s).strip().startswith("-")
    m = re.search(r"([\d,]+(?:\.\d+)?)", str(s))
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return -v if neg else v


def num(s):
    if s is None:
        return None
    m = re.search(r"([\d,]+(?:\.\d+)?)", str(s))
    return float(m.group(1).replace(",", "")) if m else None


def row(name, got, want, unit="", tol=0.02):
    if want is None:
        print(f"   --  {name:<44} {got:>14,.0f} {unit}   (row absent)")
        return None
    if abs(want) < 1e-9:
        ok, d = abs(got) < 1.0, "—"
    else:
        rel = (got - want) / want
        ok, d = abs(rel) <= tol, f"{rel:+.2%}"
    print(f"   {'OK ' if ok else 'XX '} {name:<44} {got:>14,.0f} {unit:<5} vs {want:>14,.0f}  {d}")
    return ok


def main() -> None:
    reopt = json.load(io.open(os.path.join(ROOT, "reopt_test_data", "gen-reopt.json"),
                              encoding="utf-8"))
    L = ds.build_electric_load("LargeOffice", 5_000_000, LAT, LON)
    heat = ds.heating_load_mmbtu("LargeOffice", L["city"])
    pf, _ = ds.call_pvwatts_api(LAT, LON, tilt=20, azimuth=180, array_type=0,
                                module_type=0, losses=14)
    tar = build_tariff(ds.fetch_urdb_rate(URDB))
    print(f"heating fuel {heat['fuel_mmbtu']:,.2f} MMBtu "
          f"(space {heat['space_heating']:,.1f} + DHW {heat['domestic_hot_water']:,.1f})\n")

    # Exactly what the UI now sends: defaults.chp_defaults() applies the 0.75x
    # electric-only scaling (chp.jl:419) and the MACRS split from the web-tool spec.
    def cfg(electric_only):
        d = dict(D.chp_defaults(is_electric_only=electric_only))
        d.pop("min_turn_down_fraction", None)
        d.update(kind="CHP", max_kw=2000.0)
        return d

    CHP = cfg(False)
    PG = cfg(True)
    print(f"CHP  cost ${CHP['installed_cost_per_kw']:,.0f}/kW  om ${CHP['om_cost_per_kwh']}/kWh  "
          f"macrs {CHP['macrs_option_years']}yr bonus {CHP['macrs_bonus_fraction']}")
    print(f"PG   cost ${PG['installed_cost_per_kw']:,.0f}/kW  om ${PG['om_cost_per_kwh']}/kWh  "
          f"macrs {PG['macrs_option_years']}yr bonus {PG['macrs_bonus_fraction']}\n")

    grand = []
    for cid, ft_cfg, with_heat in (("G1", CHP, True), ("G2", PG, False)):
        rows = (reopt.get(cid) or {}).get("rows") or {}
        print(f"{'=' * 78}\n{cid}  {'CHP' if cid == 'G1' else 'Prime Generator'} + PV + Battery")
        if not rows:
            print("   REopt run missing"); continue

        inp = M.ScenarioInputs(
            loads_kw=L["loads_kw"], tariff=tar,
            financial=M.FinancialInputs(analysis_years=25,
                                        elec_cost_escalation_rate_fraction=0.017,
                                        offtaker_discount_rate_fraction=0.083),
            pv=M.PVInputs(enabled=True, installed_cost_per_kw=1600.0, max_kw=2000.0,
                          om_cost_per_kw=20.0, production_factor=pf),
            storage=M.StorageInputs(enabled=True, installed_cost_per_kwh=300.0,
                                    installed_cost_per_kw=800.0,
                                    installed_cost_constant=0.0, max_kwh=4000.0),
            fuel_tech=M.FuelTechInputs(enabled=True, **ft_cfg),
            land_acres=5.0, pv_location="ground",
            heating_fuel_mmbtu=(heat["fuel_mmbtu"] if with_heat else None),
            existing_boiler_fuel_cost_per_mmbtu=8.0,
        )
        r = M.solve(inp, time_limit=900)
        b = M.business_as_usual(inp)
        sz, u, th = r["sizes"], r["utility"], r.get("thermal", {})

        res = []
        res.append(row("PV size", sz["pv_kw"], num((rows.get("PV Size") or [None, None])[1]), "kW", 0.03))
        res.append(row("Battery power", sz["battery_kw"],
                       num((rows.get("Battery Power") or [None, None])[1]), "kW", 0.05))
        res.append(row("Battery capacity", sz["battery_kwh"],
                       num((rows.get("Battery Capacity") or [None, None])[1]), "kWh", 0.05))
        fuel_key = "CHP Size" if cid == "G1" else "Prime Generator Size"
        res.append(row(f"{fuel_key}", sz["fueltech_kw"],
                       num((rows.get(fuel_key) or [None, None])[1]), "kW"))
        if with_heat:
            res.append(row("Heating System Fuel Used", th.get("boiler_fuel_mmbtu", 0),
                           num((rows.get("Heating System Fuel Used") or [None])[0]), "MMBtu", 0.01))
            res.append(row("Heating System Fuel Cost (lifecycle)",
                           th.get("boiler_fuel_cost_lifecycle", 0),
                           money((rows.get("Heating System Fuel Cost") or [None])[0]), "$", 0.01))
        res.append(row("Year 1 utility, BAU", b["year1_total"],
                       money((rows.get("Total Year 1 Utility Cost - Before Tax") or [None])[0]), "$", 0.01))
        res.append(row("Year 1 utility, optimized", u["year1_total"],
                       money((rows.get("Total Year 1 Utility Cost - Before Tax") or [None, None])[1]), "$", 0.01))
        res.append(row("Life cycle cost, BAU", b["lifecycle_cost"],
                       money((rows.get("Total Life Cycle Costs") or [None])[0]), "$", 0.01))
        res.append(row("Life cycle cost, optimized", r["objective_lifecycle_cost"],
                       money((rows.get("Total Life Cycle Costs") or [None, None])[1]), "$", 0.01))
        res.append(row("Net present value", b["lifecycle_cost"] - r["objective_lifecycle_cost"],
                       money((rows.get("Net Present Value") or [None, None])[1]), "$", 0.05))

        good = [x for x in res if x is not None]
        print(f"   -> {sum(good)}/{len(good)} match\n")
        grand.append((cid, sum(good), len(good)))

    print("SUMMARY")
    for cid, ok, tot in grand:
        print(f"   {cid}  {ok}/{tot}")
    print(f"   TOTAL {sum(o for _, o, _ in grand)}/{sum(t for _, _, t in grand)}")


if __name__ == "__main__":
    main()
