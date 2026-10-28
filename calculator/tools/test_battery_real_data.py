"""Checks on ``tools/battery_real_data.py`` -- the measured-data battery study.

    python calculator/tools/test_battery_real_data.py

Fast (well under a minute): the data assembly, the annualisation, the rule's
arithmetic on a case small enough to work by hand, and the optimiser's
invariants on a few real days. The full study is ``battery_real_data.py all``.
"""
from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import battery_real_data as B   # noqa: E402

FAIL: list[str] = []
P = dict(grid_price=60.0, gas_cost=22.0, start_cost=15_000.0, capex=391_000_000.0,
         bat_om=2.5, replace_year=10, replace_cost=100.0, workers=1)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK' if ok else 'XX'}  {name}{('   ' + detail) if detail else ''}")
    if not ok:
        FAIL.append(name)


def data() -> dict:
    print("\nData assembly")
    out = {}
    for case, n_units in (("zhkpz", 2), ("site3", 1), ("combined", 3)):
        x = B.data_for(case)
        out[case] = x
        n = len(x["load"])
        check(f"{case}: whole days only", n > 0 and n % 24 == 0, f"{n // 24} days")
        check(f"{case}: one series per engine", len(x["gpu_units"]) == n_units)
        check(f"{case}: no negative load", min(x["load"]) >= 0.0)
        check(f"{case}: purchase and export never both in one plant-hour",
              case == "combined" or all(b == 0 or e == 0 for b, e in zip(x["buy"], x["export"])))
    zd = {t[:10] for t in out["zhkpz"]["time"]}
    cd = {t[:10] for t in out["combined"]["time"]}
    check("combined days are days ЖКПЗ is fully measured", cd <= zd, f"{len(cd)} of {len(zd)}")
    return out


def annualisation() -> None:
    print("\nAnnualisation")
    import datetime as dt
    year = [(dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(365)]
    y, miss = B.by_month({d: 1.0 for d in year})
    check("a constant over every day of a year is 365", abs(y - 365.0) < 1e-9 and not miss)
    gaps = {d: 1.0 for d in year if d[5:7] not in ("02", "12")}
    y, miss = B.by_month(gaps)
    check("missing February and December are filled from neighbours", abs(y - 365.0) < 1e-9
          and miss == [2, 12], f"missing {miss}")
    ramp = {d: float(int(d[5:7])) for d in year if d[5:7] != "02"}
    y, _ = B.by_month(ramp)
    want = sum(m * B.DAYS_IN[m] for m in range(1, 13) if m != 2) + 2.0 * B.DAYS_IN[2]
    check("a gap takes the mean of the measured months either side", abs(y - want) < 1e-9)


def rule() -> None:
    print("\nBattery rule, worked by hand")
    units = B.units_for("site3", P)
    x = dict(time=["2026-01-01 00:00", "2026-01-01 01:00"], load=[0.0, 1000.0],
             gpu_units=[[0.0, 0.0]], buy=[0.0, 1000.0], export=[1000.0, 0.0])
    got = B.rule_battery(x, units, P)["2026-01-01"]
    eta = 0.88 ** 0.5
    want = 1000.0 * eta * eta * (60.0 - 0.5)       # free charge in, 88 % back out
    check("an exported MWh comes back as 880 kWh at the grid price less wear",
          abs(got - want) < 1e-6, f"{got:,.2f} vs {want:,.2f}")
    x = dict(time=["2026-01-01 00:00", "2026-01-01 01:00"], load=[500.0, 1000.0],
             gpu_units=[[567.0, 0.0]], buy=[0.0, 1000.0], export=[0.0, 0.0])
    got = B.rule_battery(x, units, P)["2026-01-01"]
    mc = B.marginal_gas_cost(next(u for _, u in units.iterrows()))
    want = 500.0 * eta * eta * (60.0 - 0.5) - 500.0 * mc   # 1,067 kW rated, 567 running
    check("headroom of a running engine is charged at its marginal gas cost",
          abs(got - want) < 1e-6, f"marginal {mc:.2f} ₸/kWh")
    common = dict(time=["2026-01-01 00:00"], load=[0.0], gpu_units=[[0.0], [0.0], [0.0]],
                  buy=[400.0], export=[400.0])
    got = B.rule_battery(common, B.units_for("combined", P), P, common_bus=True)
    check("on a common bus an export that meets a purchase earns the battery nothing",
          abs(got.get("2026-01-01", 0.0)) < 1e-9)


def optimiser(x: dict) -> None:
    print("\nOptimiser on real days")
    for case in B.CASES:
        d0 = x[case]
        for d in range(2):
            sl = slice(24 * d, 24 * d + 24)
            avail = [[1.0 if v > B.ON_KW else 0.0 for v in s[sl]] for s in d0["gpu_units"]]
            day = d0["time"][24 * d][:10]
            r = {(m, k): B.solve_day((case, m, k, day, d0["load"][sl], avail, P))
                 for m in B.MODES for k in ("A", "D")}
            ok = all(v["status"] == "Optimal" for v in r.values())
            check(f"{case} {day}: every solve Optimal", ok)
            tol = lambda a: 1e-3 * abs(a) + 1.0
            for m in B.MODES:
                a, dd = r[(m, "A")]["total"], r[(m, "D")]["total"]
                check(f"{case} {day} {m}: a battery that may idle never costs more",
                      dd <= a + tol(a), f"A {a:,.0f}  D {dd:,.0f}")
            af, am = r[("free", "A")]["total"], r[("measured", "A")]["total"]
            check(f"{case} {day}: measured availability never cheaper than free",
                  am >= af - tol(af), f"free {af:,.0f}  measured {am:,.0f}")


def main() -> int:
    if not B.RD.available():
        print(f"no measured table at {B.RD.TABLE}: nothing to check")
        return 0
    x = data()
    annualisation()
    rule()
    optimiser(x)
    print(f"\n{'FAILED: ' + '; '.join(FAIL) if FAIL else 'all battery-study checks passed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
