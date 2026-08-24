"""Financial primitives ported verbatim from REopt.jl v0.61.1.

Every function here is a direct translation of Julia source in
``REopt/src/core/utils.jl``. Line references are to that file. Nothing in this
module is invented -- if a formula is not in REopt.jl it does not belong here.
"""

from __future__ import annotations

from typing import Sequence

# IRS Pub. 946 depreciation schedules.
# REopt/src/core/financial.jl:19-20
MACRS_FIVE_YEAR = [0.2, 0.32, 0.192, 0.1152, 0.1152, 0.0576]
MACRS_SEVEN_YEAR = [0.1429, 0.2449, 0.1749, 0.1249, 0.0893, 0.0892, 0.0893, 0.0446]


def annuity_two_escalation_rates(
    years: int, rate_escalation1: float, rate_escalation2: float, rate_discount: float
) -> float:
    """REopt/src/core/utils.jl:21

    Geometric sum of (1+e1)^n * (1+e2)^n / (1+d)^n for n = 1..years, refactored
    as ((1 + e1 + e2 + e1*e2) / (1 + d))^n. Assumes cost growth in first period.
    """
    x = (1 + rate_escalation1 + rate_escalation2 + rate_escalation1 * rate_escalation2) / (
        1 + rate_discount
    )
    if x != 1:
        pwf = round(x * (1 - x**years) / (1 - x), 5)
    else:
        pwf = float(years)
    return pwf


def annuity(years: int, rate_escalation: float, rate_discount: float) -> float:
    """REopt/src/core/utils.jl:11"""
    return annuity_two_escalation_rates(years, rate_escalation, 0.0, rate_discount)


def levelization_factor(
    years: int, rate_escalation: float, rate_discount: float, rate_degradation: float
) -> float:
    """REopt/src/core/utils.jl:54

    Ratio of (an annuity escalating at the electricity cost escalation rate with
    a negative escalation equal to the tech degradation rate starting year 2) to
    pwf_e. Only PV carries a degradation rate in REopt.
    """
    num = 0.0
    for yr in range(1, years + 1):
        num += (1 + rate_escalation) ** yr / (1 + rate_discount) ** yr * (
            1 - rate_degradation
        ) ** (yr - 1)
    den = annuity(years, rate_escalation, rate_discount)
    return num / den if den != 0 else 1.0


def npv(rate: float, cash_flows: Sequence[float]) -> float:
    """REopt/src/core/utils.jl:295 -- cash_flows[0] is undiscounted (t=0)."""
    total = cash_flows[0]
    for y, c in enumerate(cash_flows[1:], start=1):
        total += c / (1 + rate) ** y
    return total


def effective_cost(
    *,
    itc_basis: float,
    replacement_cost: float,
    replacement_year: int,
    discount_rate: float,
    tax_rate: float,
    itc: float,
    macrs_schedule: Sequence[float],
    macrs_bonus_fraction: float,
    macrs_itc_reduction: float,
    rebate_per_kw: float = 0.0,
) -> float:
    """REopt/src/core/utils.jl:83

    Effective (net present) capital cost per unit after ITC and depreciation.
    This is the ``cap_cost_slope`` the MILP multiplies by system size.

    From the Julia docstring:
      (i)   depreciation tax shields are nominal -- no inflation adjustment
      (ii)  ITC and bonus depreciation are taken at end of year 1
      (iii) replacement cost is a one-time capex discounted back at r_owner
      (iv)  cash incentives reduce the ITC basis
      (v)   cash incentives are not taxable
      (vi)  cash incentives must already be folded into ``itc_basis``
    """
    # itc reduces depreciable_basis
    depr_basis = itc_basis * (1 - macrs_itc_reduction * itc)

    # Bonus depreciation taken from tech cost after itc reduction ($/kW)
    bonus_depreciation = depr_basis * macrs_bonus_fraction

    # ITC and bonus depreciation reduce the depreciable basis
    depr_basis -= bonus_depreciation

    # Replacement cost discounted to replacement year, net of tax deduction
    replacement = replacement_cost * (1 - tax_rate) / ((1 + discount_rate) ** replacement_year)

    tax_savings_array = [0.0]
    for idx, macrs_rate in enumerate(macrs_schedule):
        depreciation_amount = macrs_rate * depr_basis
        if idx == 0:  # Julia is 1-indexed; idx==1 there
            depreciation_amount += bonus_depreciation
        tax_savings_array.append(depreciation_amount * tax_rate)

    # Add the ITC to the tax savings (end of year 1)
    tax_savings_array[1] += itc_basis * itc

    tax_savings = npv(discount_rate, tax_savings_array)

    cap_cost_slope = itc_basis - tax_savings + replacement - rebate_per_kw

    if cap_cost_slope < 0:  # sanity check, as in Julia
        cap_cost_slope = 0.0

    return round(cap_cost_slope, 4)


def macrs_schedule_for(option_years: int) -> list[float]:
    """REopt/src/core/cost_curve.jl:319-332 and electric_storage.jl:477"""
    if option_years == 5:
        return list(MACRS_FIVE_YEAR)
    if option_years == 7:
        return list(MACRS_SEVEN_YEAR)
    if option_years == 0:
        return [0.0]
    raise ValueError("macrs_option_years must be 0, 5, or 7.")
