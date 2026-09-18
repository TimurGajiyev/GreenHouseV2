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


# =====================================================================
# REopt/src/results/proforma.jl, host-owned branch -- verbatim port.
#
# The simpler ``build`` above predates this and priced only the electricity
# bill and O&M. REopt's pro-forma also carries every fuel stream (CHP fuel,
# the existing boiler in both cases, each with its own escalation), the CHP
# standby charge, cash incentives, production incentives and battery
# replacement, and it escalates year-one values from year 1 onward:
# val * (1 + esc) ** yr for yr in 1..N.
# =====================================================================
class Metrics:
    """proforma.jl:3 struct Metrics."""

    def __init__(self, years: int):
        self.years = years
        self.federal_itc = 0.0
        self.om_series = [0.0] * years
        self.om_series_bau = [0.0] * years
        self.fuel_cost_series = [0.0] * years
        self.fuel_cost_series_bau = [0.0] * years
        self.total_pbi = [0.0] * years
        self.total_pbi_bau = [0.0] * years
        self.total_depreciation = [0.0] * years
        self.total_ibi_and_cbi = 0.0


def escalate(val: float, rate: float, years: int) -> list[float]:
    """proforma.jl escalate_om / escalate_fuel: val * (1 + rate)^yr, yr = 1..years."""
    return [val * (1 + rate) ** yr for yr in range(1, years + 1)]


def _add(a: list[float], b: list[float]) -> list[float]:
    return [x + y for x, y in zip(a, b)]


def depreciation_schedule(*, basis: float, itc_fraction: float, macrs_option_years: int,
                          macrs_bonus_fraction: float, macrs_itc_reduction: float,
                          years: int) -> list[float]:
    """results/financial.jl:331 get_depreciation_schedule."""
    out = [0.0] * years
    if macrs_option_years not in (5, 7):
        return out
    sched = macrs_schedule_for(macrs_option_years)
    red = 0.0 if itc_fraction == 0.0 else macrs_itc_reduction
    bonus_basis = basis - basis * itc_fraction * red
    macrs_basis = bonus_basis * (1 - macrs_bonus_fraction)
    for i, r in enumerate(sched, start=1):
        if i < years:                                   # Julia: if i < length(schedule)
            out[i - 1] = macrs_basis * r
    out[0] += macrs_bonus_fraction * bonus_basis
    return out


def add_tech(m: Metrics, *, om_escalation: float, capital_cost: float, new_kw: float,
             annual_om: float, annual_om_bau: float = 0.0,
             fuel_year1: float = 0.0, fuel_escalation: float = 0.0,
             federal_itc_fraction: float = 0.0, federal_rebate_per_kw: float = 0.0,
             state_ibi_fraction: float = 0.0, state_ibi_max: float = 1e10,
             state_rebate_per_kw: float = 0.0, state_rebate_max: float = 1e10,
             utility_ibi_fraction: float = 0.0, utility_ibi_max: float = 1e10,
             utility_rebate_per_kw: float = 0.0, utility_rebate_max: float = 1e10,
             production_incentive_per_kwh: float = 0.0, production_incentive_max_benefit: float = 1e9,
             production_incentive_years: int = 0, year_one_energy_kwh: float = 0.0,
             degradation_fraction: float = 0.0,
             macrs_option_years: int = 0, macrs_bonus_fraction: float = 0.0,
             macrs_itc_reduction: float = 0.0) -> None:
    """proforma.jl update_metrics, host-owned. ``annual_om`` is a positive cost."""
    n = m.years
    m.om_series = _add(m.om_series, escalate(-annual_om, om_escalation, n))
    m.om_series_bau = _add(m.om_series_bau, escalate(-annual_om_bau, om_escalation, n))
    if fuel_year1:
        m.fuel_cost_series = _add(m.fuel_cost_series, escalate(-fuel_year1, fuel_escalation, n))
    # "in the spreadsheet utility incentives are applied first"
    utility_ibi = min(capital_cost * utility_ibi_fraction, utility_ibi_max)
    utility_cbi = min(new_kw * utility_rebate_per_kw, utility_rebate_max)
    state_ibi = min((capital_cost - utility_ibi - utility_cbi) * state_ibi_fraction, state_ibi_max)
    state_cbi = min(new_kw * state_rebate_per_kw, state_rebate_max)
    federal_cbi = new_kw * federal_rebate_per_kw
    m.total_ibi_and_cbi += (utility_ibi + state_ibi) + (utility_cbi + federal_cbi + state_cbi)
    pbi = []
    for yr in range(n):
        if yr < production_incentive_years:
            deg = (1 - degradation_fraction) ** yr
            pbi.append(min(production_incentive_per_kwh * year_one_energy_kwh * deg,
                           production_incentive_max_benefit * deg))
        else:
            pbi.append(0.0)
    m.total_pbi = _add(m.total_pbi, pbi)
    basis = capital_cost - state_ibi - utility_ibi - state_cbi - utility_cbi
    m.federal_itc += federal_itc_fraction * basis
    m.total_depreciation = _add(m.total_depreciation, depreciation_schedule(
        basis=basis, itc_fraction=federal_itc_fraction, macrs_option_years=macrs_option_years,
        macrs_bonus_fraction=macrs_bonus_fraction, macrs_itc_reduction=macrs_itc_reduction, years=n))


def add_storage(m: Metrics, *, om_escalation: float, size_kw: float, size_kwh: float,
                cost_per_kw: float, cost_per_kwh: float, cost_constant: float,
                replace_per_kw: float, replace_per_kwh: float, replace_constant: float,
                battery_replacement_year: int, om_fraction: float,
                rebate_per_kw: float, rebate_per_kwh: float, itc_fraction: float,
                macrs_option_years: int, macrs_bonus_fraction: float, macrs_itc_reduction: float) -> float:
    """proforma.jl:78-106. Returns the (negative) replacement cost for the capital summary."""
    n = m.years
    capital = size_kw * cost_per_kw + size_kwh * cost_per_kwh + cost_constant
    replacement = -1 * (size_kw * replace_per_kw + size_kwh * replace_per_kwh + replace_constant)
    m.om_series = _add(m.om_series, [replacement if yr == battery_replacement_year else 0.0
                                     for yr in range(1, n + 1)])
    m.om_series = _add(m.om_series, escalate(-1 * capital * om_fraction, om_escalation, n))
    m.total_ibi_and_cbi += size_kw * rebate_per_kw + size_kwh * rebate_per_kwh
    m.federal_itc += itc_fraction * capital
    m.total_depreciation = _add(m.total_depreciation, depreciation_schedule(
        basis=capital, itc_fraction=itc_fraction, macrs_option_years=macrs_option_years,
        macrs_bonus_fraction=macrs_bonus_fraction, macrs_itc_reduction=macrs_itc_reduction, years=n))
    return replacement


def add_fuel(m: Metrics, *, year1: float, year1_bau: float, escalation: float) -> None:
    """Existing boiler (proforma.jl:146-160) and generator fuel."""
    n = m.years
    m.fuel_cost_series = _add(m.fuel_cost_series, escalate(-year1, escalation, n))
    m.fuel_cost_series_bau = _add(m.fuel_cost_series_bau, escalate(-year1_bau, escalation, n))


def finish(m: Metrics, *, elec_escalation: float, tax_rate: float, discount_rate: float,
           initial_capital: float, lifecycle_capital_bau: float,
           year1_bill: float, year1_bill_bau: float, year1_export: float = 0.0,
           year1_export_bau: float = 0.0, year1_standby: float = 0.0) -> dict:
    """proforma.jl:240-361 -- cash flows, IRR and simple payback (host-owned)."""
    n = m.years
    elec = lambda v: [-1 * v * (1 + elec_escalation) ** yr for yr in range(1, n + 1)]
    bill, export, standby = elec(year1_bill), elec(-year1_export), elec(year1_standby)
    opex = [a + b + c + d + e for a, b, c, d, e in
            zip(bill, export, m.om_series, m.fuel_cost_series, standby)]
    ded = list(opex) if tax_rate > 0 else [0.0] * n
    opex_at = [(o - d) + d * (1 - tax_rate) for o, d in zip(opex, ded)]
    fcf = [dep * tax_rate + p_ * (1 - tax_rate) + ox
           for dep, p_, ox in zip(m.total_depreciation, m.total_pbi, opex_at)]
    fcf[0] += m.federal_itc
    free_cashflow = [(-1 * initial_capital) + m.total_ibi_and_cbi] + fcf

    bill_b, export_b = elec(year1_bill_bau), elec(-year1_export_bau)
    opex_b = [a + b + c + d for a, b, c, d in
              zip(bill_b, export_b, m.om_series_bau, m.fuel_cost_series_bau)]
    ded_b = list(opex_b) if tax_rate > 0 else [0.0] * n
    fcf_b = [(o - d) + d * (1 - tax_rate) + x * (1 - tax_rate)
             for o, d, x in zip(opex_b, ded_b, m.total_pbi_bau)]
    free_cashflow_bau = [-1 * lifecycle_capital_bau] + fcf_b

    net = [a - b for a, b in zip(free_cashflow, free_cashflow_bau)]
    cumulative, run = [], 0.0
    for c in net:
        run += c
        cumulative.append(run)
    out = {"offtaker_annual_free_cashflows": [round(x, 2) for x in free_cashflow],
           "offtaker_annual_free_cashflows_bau": [round(x, 2) for x in free_cashflow_bau],
           "net_free_cashflow": net, "cumulative_cashflow": cumulative,
           "simple_payback_years": 0.0, "internal_rate_of_return": reopt_irr(net),
           "npv": sum(c / (1 + discount_rate) ** i for i, c in enumerate(net))}
    if cumulative[-1] < 0:
        return out
    spp = 0.0
    for i in range(1, n):                          # Julia: for i in 2:years, 1-based
        if cumulative[i] < 0:
            spp += 1
        elif cumulative[i - 1] < 0 and cumulative[i] > 0:
            spp += -(cumulative[i - 1] / net[i])
    out["simple_payback_years"] = round(spp, 2)
    return out


def reopt_irr(cash: list[float]) -> float:
    """proforma.jl irr: 0 if NPV(0) < 0, else the root in [0, 0.99], rounded to 3."""
    if sum(cash) < 0:
        return 0.0
    f = lambda r: sum(c / (1 + r) ** i for i, c in enumerate(cash))
    lo, hi = 0.0, 0.99
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return 0.0
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < 1e-9:
            break
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return round((lo + hi) / 2, 3)
