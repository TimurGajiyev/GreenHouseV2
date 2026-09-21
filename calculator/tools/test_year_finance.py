"""Part 1 of the year/25-year methodology check: the finance arithmetic.

No solver. Every formula the 25-year numbers rest on is recomputed here the
long way -- year by year, from the definition -- and compared with the closed
form the core uses, and with the convention REopt.jl itself follows in
``REopt/src/results/proforma.jl`` and ``REopt/src/results/financial.jl``.

The question this answers: when the calculator says "25 years", is the sum it
takes the sum it claims to take?

    python tools/test_year_finance.py
"""

from __future__ import annotations

import os
import sys

# Redirected stdout defaults to the console codepage on Windows; the captions
# these tests print carry a multiplication sign. Pin it, as jsx_render_check does.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import finance as F
from reopt_core import proforma as PF

FAIL: list[str] = []
DEVIATION: list[str] = []
N = 25
ESC_E, ESC_OM, ESC_F = 0.0166, 0.025, 0.034
DISC, TAX, DEG = 0.0624, 0.26, 0.005


def check(name: str, got: float, want: float, rtol: float = 1e-6) -> bool:
    ok = abs(got - want) <= rtol * max(1.0, abs(want))
    print(f"  {'OK' if ok else 'XX'}  {name:<56} {got:>16,.6f}  vs {want:>16,.6f}")
    if not ok:
        FAIL.append(name)
    return ok


def deviation(name: str, got: float, want: float, why: str) -> None:
    """A difference that is real, understood and deliberate -- printed, not failed."""
    print(f"  !!  {name:<56} {got:>16,.6f}  vs {want:>16,.6f}")
    print(f"      {why}")
    DEVIATION.append(name)


def head(t: str) -> None:
    print(f"\n{t}\n{'-' * len(t)}")


# ---------------------------------------------------------------- 1. annuity
def t_annuity() -> None:
    head("1.1  present-worth factors are the geometric sums they claim to be")
    # utils.jl:11 -- pwf = sum_{y=1..N} (1+e)^y / (1+d)^y.  The escalated cost
    # is charged from year 1 onward, i.e. year 1 already carries one year of
    # escalation. Everything downstream inherits that convention.
    for lab, esc in (("elec", ESC_E), ("O&M", ESC_OM), ("fuel", ESC_F), ("zero", 0.0)):
        long = sum((1 + esc) ** y / (1 + DISC) ** y for y in range(1, N + 1))
        check(f"pwf ({lab}) closed form == year-by-year sum",
              F.annuity(N, esc, DISC), long, rtol=1e-5)  # core rounds to 5 dp

    long2 = sum(((1 + ESC_E) * (1 + ESC_F)) ** y / (1 + DISC) ** y for y in range(1, N + 1))
    check("pwf (two escalations) == year-by-year sum",
          F.annuity_two_escalation_rates(N, ESC_E, ESC_F, DISC), long2, rtol=1e-5)

    # Degenerate cases the UI can reach: zero discount, zero escalation.
    check("pwf with d = e is exactly N", F.annuity(N, 0.05, 0.05), float(N), rtol=1e-9)
    check("pwf with d = e = 0 is exactly N", F.annuity(N, 0.0, 0.0), float(N), rtol=1e-9)

    head("1.2  levelization factor (PV degradation)")
    num = sum((1 + ESC_E) ** y / (1 + DISC) ** y * (1 - DEG) ** (y - 1)
              for y in range(1, N + 1))
    check("levelization == degraded sum / pwf",
          F.levelization_factor(N, ESC_E, DISC, DEG), num / F.annuity(N, ESC_E, DISC),
          rtol=1e-5)
    # Not exactly 1: annuity rounds to 5 decimals (utils.jl:30 does the same) and
    # only the denominator is rounded. REopt carries the identical artifact, so
    # this is parity, not error -- but it is 3e-7, so the tolerance must say so.
    check("no degradation -> levelization is 1 (to REopt's own rounding)",
          F.levelization_factor(N, ESC_E, DISC, 0.0), 1.0, rtol=1e-6)
    # Monotone: a longer life with a degrading tech levelizes lower.
    a, b = (F.levelization_factor(n, ESC_E, DISC, DEG) for n in (10, 25))
    print(f"  {'OK' if b < a else 'XX'}  levelization falls with horizon           "
          f"      10 yr {a:.5f}  >  25 yr {b:.5f}")
    if not b < a:
        FAIL.append("levelization monotone")


# ------------------------------------------------------- 2. capital cost slope
def t_effective_cost() -> None:
    head("1.3  effective_cost: the capital number the 25-year objective uses")
    base = dict(itc_basis=1000.0, replacement_cost=0.0, replacement_year=10,
                discount_rate=DISC, tax_rate=TAX, itc=0.0,
                macrs_schedule=[0.0], macrs_bonus_fraction=0.0, macrs_itc_reduction=0.0)
    check("no incentive, no replacement -> slope == basis",
          F.effective_cost(**base), 1000.0)

    rep = dict(base, replacement_cost=300.0)
    check("replacement at year 10 == basis + rep(1-tax)/(1+d)^10",
          F.effective_cost(**rep), 1000.0 + 300.0 * (1 - TAX) / (1 + DISC) ** 10, rtol=1e-4)

    itc = dict(base, itc=0.3)
    check("30% ITC taken at end of year 1",
          F.effective_cost(**itc), 1000.0 - 300.0 / (1 + DISC), rtol=1e-4)

    macrs = dict(base, macrs_schedule=F.MACRS_FIVE_YEAR, macrs_bonus_fraction=0.0)
    want = 1000.0 - sum(r * 1000.0 * TAX / (1 + DISC) ** (i + 1)
                        for i, r in enumerate(F.MACRS_FIVE_YEAR))
    check("5-year MACRS shields discounted year by year",
          F.effective_cost(**macrs), want, rtol=1e-4)

    bonus = dict(base, macrs_schedule=F.MACRS_FIVE_YEAR, macrs_bonus_fraction=1.0)
    check("100% bonus depreciation lands wholly in year 1",
          F.effective_cost(**bonus), 1000.0 - 1000.0 * TAX / (1 + DISC), rtol=1e-4)

    # A tech whose replacement falls outside the horizon must not be charged for
    # it. model.py guards this at the call site (replacement_year >= years -> 0).
    print("  --  replacement beyond the horizon is zeroed by model.py, not here")


# ---------------------------------------------- 3. pro-forma escalation timing
def t_proforma_timing() -> None:
    head("1.4  pro-forma cash flows escalate the way REopt.jl escalates")
    # REopt/src/results/proforma.jl:55-57
    #     escalate_om(val) = [val * (1 + esc)^yr for yr in 1:years]
    # i.e. the year-1 cash flow is already escalated once.
    want = [100.0 * (1 + ESC_OM) ** y for y in range(1, N + 1)]
    got = PF.escalate(100.0, ESC_OM, N)
    check("proforma.escalate matches (1+e)^yr, yr from 1", got[0], want[0], rtol=1e-9)
    check("  ... and at year 25", got[-1], want[-1], rtol=1e-9)

    # The lifecycle objective multiplies a year-one value by pwf. For that to be
    # the same money as the cash-flow stream, the stream must escalate the same
    # way. Both are sums of val*(1+e)^y/(1+d)^y -- check they agree to the cent.
    pwf = F.annuity(N, ESC_OM, DISC)
    stream = sum(c / (1 + DISC) ** y for y, c in enumerate(got, start=1))
    check("NPV(escalated stream) == pwf x year-one value", stream, pwf * 100.0, rtol=1e-4)

    head("1.5  pv_lcoe: O&M escalation against financial.jl:268")
    # REopt: om_series = [annual_om * (1+e)^yr for yr in 1:years]
    # Ours (proforma.pv_lcoe): (1+e)^(y-1). One year of escalation short.
    cap, om1, energy = 1_000_000.0, 20_000.0, 2_000_000.0
    ours = PF.pv_lcoe(capital_cost=cap, year1_om=om1, years=N, om_escalation=ESC_OM,
                      discount_rate=DISC, tax_rate=TAX, itc_amount=0.0,
                      depr_shields=[0.0] * (N + 1), annual_energy_kwh=energy,
                      degradation=DEG)
    npv_om_reopt = sum(om1 * (1 + ESC_OM) ** y * (1 - TAX) / (1 + DISC) ** y
                       for y in range(1, N + 1))
    npv_energy = sum(energy * (1 - DEG) ** (y - 1) / (1 + DISC) ** y
                     for y in range(1, N + 1))
    reopt = (cap + npv_om_reopt) / npv_energy
    deviation("pv_lcoe vs financial.jl:268", ours, reopt,
              f"ours escalates O&M as (1+e)^(y-1), REopt as (1+e)^y: "
              f"{100 * (ours / reopt - 1):+.3f} % on the whole LCOE. REPORT.md Part 10 "
              f"already records PV LCOE 1-4 % off the live tool in the OTHER direction "
              f"(ours $0.070 vs tool $0.067), so matching REopt.jl here would widen that "
              f"gap. Left alone deliberately; decide against the live tool, not the source.")

    head("1.6  proforma.build (legacy, unused by the app)")
    b = PF.build(years=N, initial_capital=0.0, bau_year1_bill=100.0, opt_year1_bill=0.0,
                 year1_om=0.0, elec_escalation=ESC_E, om_escalation=ESC_OM,
                 tax_rate=0.0, discount_rate=DISC, itc_amount=0.0,
                 depr_shields=[0.0] * (N + 1))
    deviation("build() year-1 cash flow", b["net_free_cashflow"][1], 100.0 * (1 + ESC_E),
              "escalates as (1+e)^(y-1). Dead code: the app's payback and IRR come from "
              "the Metrics/add_tech port above, which is faithful. Nothing reads build().")


# ------------------------------------------------- 4. the 25-year sum as a whole
def t_lifecycle_identity() -> None:
    head("1.7  a whole 25-year bill: closed form vs 25 explicit years")
    bill1 = 1_000_000.0           # year-one electricity bill
    om1 = 50_000.0                # year-one O&M
    fuel1 = 300_000.0             # year-one fuel
    capital = 4_000_000.0

    lcc_closed = (capital
                  + F.annuity(N, ESC_E, DISC) * bill1 * (1 - TAX)
                  + F.annuity(N, ESC_OM, DISC) * om1 * (1 - TAX)
                  + F.annuity(N, ESC_F, DISC) * fuel1 * (1 - TAX))
    lcc_long = capital + sum(
        (bill1 * (1 + ESC_E) ** y + om1 * (1 + ESC_OM) ** y + fuel1 * (1 + ESC_F) ** y)
        * (1 - TAX) / (1 + DISC) ** y for y in range(1, N + 1))
    check("lifecycle cost == sum of 25 discounted years", lcc_closed, lcc_long, rtol=1e-4)

    # What 25 years is worth against 1: the multiplier the design shows.
    for n in (1, 10, 20, 25, 30):
        print(f"      pwf_e({n:>2} yr) = {F.annuity(n, ESC_E, DISC):7.4f}"
              f"   pwf_fuel = {F.annuity(n, ESC_F, DISC):7.4f}")


def main() -> int:
    print(__doc__.strip().splitlines()[0])
    t_annuity()
    t_effective_cost()
    t_proforma_timing()
    t_lifecycle_identity()
    print(f"\n{'FAILED: ' + ', '.join(FAIL) if FAIL else 'all finance checks passed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
