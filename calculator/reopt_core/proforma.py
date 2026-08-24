"""Pro-forma cash flow: simple payback, IRR and PV LCOE.

Ported from ``REopt/src/results/proforma.jl`` (cash-flow assembly and the
payback loop at lines 344-361) and ``REopt/src/results/financial.jl:320``
for the levelized cost of energy.
"""

from __future__ import annotations

from typing import Sequence

from .finance import macrs_schedule_for


def irr(cash_flows: Sequence[float], lo: float = -0.99, hi: float = 10.0,
        tol: float = 1e-7, iters: int = 200) -> float:
    """Internal rate of return by bisection on NPV(rate) = 0."""
    def npv_at(rate: float) -> float:
        return sum(c / (1 + rate) ** i for i, c in enumerate(cash_flows))

    f_lo, f_hi = npv_at(lo), npv_at(hi)
    if f_lo * f_hi > 0:
        return 0.0
    for _ in range(iters):
        mid = (lo + hi) / 2
        f_mid = npv_at(mid)
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def depreciation_tax_shields(itc_basis: float, itc: float, macrs_option_years: int,
                             macrs_bonus_fraction: float, macrs_itc_reduction: float,
                             tax_rate: float, years: int) -> list[float]:
    """Annual depreciation tax shield, same basis logic as utils.jl:83."""
    out = [0.0] * (years + 1)
    if macrs_option_years == 0 or itc_basis <= 0:
        return out
    depr_basis = itc_basis * (1 - macrs_itc_reduction * itc)
    bonus = depr_basis * macrs_bonus_fraction
    depr_basis -= bonus
    for idx, rate in enumerate(macrs_schedule_for(macrs_option_years)):
        yr = idx + 1
        if yr > years:
            break
        amount = rate * depr_basis + (bonus if idx == 0 else 0.0)
        out[yr] += amount * tax_rate
    return out


def build(*, years: int, initial_capital: float,
          bau_year1_bill: float, opt_year1_bill: float,
          year1_om: float, elec_escalation: float, om_escalation: float,
          tax_rate: float, discount_rate: float,
          itc_amount: float, depr_shields: Sequence[float]) -> dict:
    """Assemble the offtaker net free cash flow and derive payback + IRR.

    proforma.jl:265-274 -- free_cashflow[0] = -capital (+ ibi/cbi);
    later years carry depreciation shields, incentives and after-tax opex;
    the ITC lands in year 1.
    """
    net = [-initial_capital]
    for y in range(1, years + 1):
        bill_saving = (bau_year1_bill - opt_year1_bill) * (1 + elec_escalation) ** (y - 1)
        om = year1_om * (1 + om_escalation) ** (y - 1)
        after_tax = (bill_saving - om) * (1 - tax_rate)
        cf = after_tax + (depr_shields[y] if y < len(depr_shields) else 0.0)
        if y == 1:
            cf += itc_amount
        net.append(cf)

    cumulative = []
    run = 0.0
    for c in net:
        run += c
        cumulative.append(run)

    payback = None
    if cumulative[-1] >= 0:
        payback = 0.0
        for i in range(1, years + 1):
            if cumulative[i] < 0:
                payback += 1
            elif cumulative[i - 1] < 0 < cumulative[i]:
                payback += -(cumulative[i - 1] / net[i])
        payback = round(payback, 2)

    # Degenerate case: nothing was built, so there is no investment to return.
    # REopt reports 0 for both payback and IRR here rather than a meaningless
    # rate from an all-zero cash flow.
    invested = initial_capital > 1e-6
    return {
        "net_free_cashflow": net,
        "cumulative_cashflow": cumulative,
        "simple_payback_years": (payback if invested else 0.0),
        "internal_rate_of_return": (irr(net) if invested else 0.0),
        "npv": sum(c / (1 + discount_rate) ** i for i, c in enumerate(net)),
    }


def pv_lcoe(*, capital_cost: float, year1_om: float, years: int,
            om_escalation: float, discount_rate: float, tax_rate: float,
            itc_amount: float, depr_shields: Sequence[float],
            annual_energy_kwh: float, degradation: float) -> float:
    """financial.jl:320

    lcoe = (capital + npv(O&M) - npv(incentives) - itc - npv(tax deductions))
           / npv(annual energy)
    """
    if annual_energy_kwh <= 0:
        return 0.0
    npv_om = sum(year1_om * (1 + om_escalation) ** (y - 1) * (1 - tax_rate)
                 / (1 + discount_rate) ** y for y in range(1, years + 1))
    npv_shields = sum((depr_shields[y] if y < len(depr_shields) else 0.0)
                      / (1 + discount_rate) ** y for y in range(1, years + 1))
    npv_itc = itc_amount / (1 + discount_rate)
    npv_energy = sum(annual_energy_kwh * (1 - degradation) ** (y - 1)
                     / (1 + discount_rate) ** y for y in range(1, years + 1))
    return (capital_cost + npv_om - npv_itc - npv_shields) / npv_energy
