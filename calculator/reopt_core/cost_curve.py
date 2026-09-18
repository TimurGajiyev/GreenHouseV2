"""Capital-cost curve with incentives -- verbatim port of REopt/src/core/cost_curve.jl.

REopt never multiplies a technology's size by a single $/kW. It builds a
piecewise-linear cost curve from

  1. the (size, cost) pairs, when ``tech_sizes_for_cost_curve`` is given,
  2. the utility, then state, then federal incentives -- each a percentage of
     cost with an optional $ cap, plus a $/kW rebate with an optional $ cap,

then re-prices every segment's slope through ``effective_cost`` so the ITC and
MACRS tax shields are included. The MILP buys a size on exactly one segment.

Every branch, the order of the regions, the ``round(..., digits=0)`` on the
slope and intercept, and the ``big_number`` sentinel are kept as in the Julia
source, so a scalar cost with no incentives collapses to one segment whose slope
is ``effective_cost(round(cost))`` -- exactly what REopt computes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .finance import effective_cost, macrs_schedule_for

BIG_NUMBER = 1.0e10


def _slope(x1, y1, x2, y2):
    return (y2 - y1) / (x2 - x1)


def _intercept(x1, y1, x2, y2):
    return y2 - _slope(x1, y1, x2, y2) * x2


def _insert_u_bp(xp, yp, region, u_xbp, u_ybp, p, u_cap):
    xp[region].append(u_xbp)
    yp[region].append(u_ybp - u_ybp * p + u_cap)


def _insert_p_bp(xp, yp, region, p_xbp, p_ybp, u, p_cap):
    xp[region].append(p_xbp)
    yp[region].append(p_ybp - (p_cap + p_xbp * u))


def _insert_u_after_p_bp(xp, yp, region, u_xbp, u_ybp, p, p_cap, u_cap):
    xp[region].append(u_xbp)
    if p_cap == 0:
        yp[region].append(u_ybp - (p * u_ybp + u_cap))
    else:
        yp[region].append(u_ybp - (p_cap + u_cap))


def _insert_p_after_u_bp(xp, yp, region, p_xbp, p_ybp, u, u_cap, p_cap):
    xp[region].append(p_xbp)
    if u_cap == 0:
        yp[region].append(p_ybp - (p_cap + u * p_xbp))
    else:
        yp[region].append(p_ybp - (p_cap + u_cap))


def _jround(x: float) -> float:
    """Julia ``round(x, digits=0)`` -- RoundNearest, ties to even, like Python's."""
    return float(round(x))


@dataclass
class CostCurveTech:
    """The attributes ``cost_curve`` reads off a REopt tech."""

    installed_cost_per_kw: float | list[float]
    tech_sizes_for_cost_curve: list[float]
    federal_itc_fraction: float = 0.0
    federal_rebate_per_kw: float = 0.0
    state_ibi_fraction: float = 0.0
    state_ibi_max: float = BIG_NUMBER
    state_rebate_per_kw: float = 0.0
    state_rebate_max: float = BIG_NUMBER
    utility_ibi_fraction: float = 0.0
    utility_ibi_max: float = BIG_NUMBER
    utility_rebate_per_kw: float = 0.0
    utility_rebate_max: float = BIG_NUMBER
    macrs_option_years: int = 0
    macrs_bonus_fraction: float = 0.0
    macrs_itc_reduction: float = 0.0
    replacement_year: int | None = None      # Generator only
    replace_cost_per_kw: float = 0.0         # Generator only
    no_incentives: bool = False              # Generator / AbsorptionChiller


def cost_curve(tech: CostCurveTech, *, analysis_years: int, owner_discount_rate: float,
               owner_tax_rate: float) -> tuple[list[float], list[float], list[float], int]:
    """cost_curve.jl:61 -- returns (cap_cost_slope, cost_curve_bp_x, cap_cost_yint, n_segments)."""
    big_number = BIG_NUMBER
    regions = ["utility", "state", "federal", "combined"]
    cap_cost_slope: list[float] = []
    cost_curve_bp_x = [0.0]
    cost_curve_bp_y = [0.0]
    cap_cost_yint: list[float] = []

    inc = {"federal": {}, "state": {}, "utility": {}}
    if tech.no_incentives:
        for r in inc:
            inc[r].update({"%": 0.0, "%_max": 0.0, "rebate": 0.0, "rebate_max": 0.0})
    else:
        # NOTE REopt incentive calculation works best if "unlimited" incentives are entered as 0
        inc["federal"]["%"] = tech.federal_itc_fraction
        inc["federal"]["%_max"] = 0
        inc["state"]["%"] = tech.state_ibi_fraction
        inc["state"]["%_max"] = 0 if tech.state_ibi_max == big_number else tech.state_ibi_max
        inc["utility"]["%"] = tech.utility_ibi_fraction
        inc["utility"]["%_max"] = 0 if tech.utility_ibi_max == big_number else tech.utility_ibi_max
        inc["federal"]["rebate"] = tech.federal_rebate_per_kw
        inc["federal"]["rebate_max"] = 0
        inc["state"]["rebate"] = tech.state_rebate_per_kw
        inc["state"]["rebate_max"] = 0 if tech.state_rebate_max == big_number else tech.state_rebate_max
        inc["utility"]["rebate"] = tech.utility_rebate_per_kw
        inc["utility"]["rebate_max"] = 0 if tech.utility_rebate_max == big_number else tech.utility_rebate_max

    cost = tech.installed_cost_per_kw
    cost_list = list(cost) if isinstance(cost, (list, tuple)) else [cost]
    sizes = list(tech.tech_sizes_for_cost_curve or [])

    xp = {"utility": [0.0, big_number]}
    yp = {"utility": [0.0, big_number * cost_list[0]]}
    if sizes:
        if len(sizes) == 1:
            yp["utility"] = [0.0, big_number * cost_list[0]]
        else:
            xp["utility"] = []
            if sizes[0] != 0:
                xp["utility"].append(0)
            xp["utility"].extend(sizes)
            if sizes[-1] <= (big_number - 1.0):
                xp["utility"].append(big_number)
            if sizes[0] == 0:
                yp["utility"] = [cost_list[0]] + [s * c for s, c in zip(sizes[1:], cost_list[1:])]
            else:
                yp["utility"] = [0] + [s * c for s, c in zip(sizes, cost_list)]
            yp["utility"].append(big_number * cost_list[-1])
            cost_curve_bp_y = [yp["utility"][0]]

    for r in range(len(regions) - 1):
        region, next_region = regions[r], regions[r + 1]
        xp[next_region] = [0.0]
        yp[next_region] = [0.0]
        p = inc[region]["%"]
        p_cap = inc[region]["%_max"]
        u = inc[region]["rebate"]
        u_cap = inc[region]["rebate_max"]
        switch_percentage = (p == 0 or p_cap == 0)
        switch_rebate = (u == 0 or u_cap == 0)

        for point in range(1, len(xp[region])):
            xp_prev, yp_prev = xp[region][point - 1], yp[region][point - 1]
            x, y = xp[region][point], yp[region][point]
            xa, ya = x, y
            u_xbp = u_ybp = p_xbp = p_ybp = 0.0
            if not switch_rebate:
                u_xbp = u_cap / u
                u_ybp = _slope(xp_prev, yp_prev, x, y) * u_xbp + _intercept(xp_prev, yp_prev, x, y)
            if not switch_percentage:
                p_xbp = (p_cap / p - _intercept(xp_prev, yp_prev, x, y)) / _slope(xp_prev, yp_prev, x, y)
                p_ybp = p_cap / p

            if ((p * y) < p_cap or p_cap == 0) and ((u * x) < u_cap or u_cap == 0):
                ya = y - (p * y + u * x)
            elif (p * y) < p_cap and (u * x) >= u_cap:
                if not switch_rebate:
                    if u * x != u_cap:
                        _insert_u_bp(xp, yp, next_region, u_xbp, u_ybp, p, u_cap)
                    switch_rebate = True
                ya = y - (p * y + u_cap)
            elif (p * y) >= p_cap and (u * x) < u_cap:
                if not switch_percentage:
                    if p * y != p_cap:
                        _insert_p_bp(xp, yp, next_region, p_xbp, p_ybp, u, p_cap)
                    switch_percentage = True
                ya = y - (p_cap + x * u)
            elif p * y >= p_cap and u * x >= u_cap:
                if not switch_rebate and not switch_percentage:
                    if p_xbp == u_xbp:
                        _insert_u_bp(xp, yp, next_region, u_xbp, u_ybp, p, u_cap)
                        switch_percentage = True
                        switch_rebate = True
                    elif p_xbp < u_xbp:
                        if p * y != p_cap:
                            _insert_p_bp(xp, yp, next_region, p_xbp, p_ybp, u, p_cap)
                        switch_percentage = True
                        if u * x != u_cap:
                            _insert_u_after_p_bp(xp, yp, next_region, u_xbp, u_ybp, p, p_cap, u_cap)
                        switch_rebate = True
                    else:
                        if u * x != u_cap:
                            _insert_u_bp(xp, yp, next_region, u_xbp, u_ybp, p, u_cap)
                        switch_rebate = True
                        if p * y != p_cap:
                            _insert_p_after_u_bp(xp, yp, next_region, p_xbp, p_ybp, u, u_cap, p_cap)
                        switch_percentage = True
                elif switch_rebate and not switch_percentage:
                    if p * y != p_cap:
                        _insert_p_after_u_bp(xp, yp, next_region, p_xbp, p_ybp, u, u_cap, p_cap)
                    switch_percentage = True
                elif not switch_rebate and switch_percentage:
                    if u * x != u_cap:
                        _insert_u_after_p_bp(xp, yp, next_region, u_xbp, u_ybp, p, p_cap, u_cap)
                    switch_rebate = True
                if p_cap == 0:
                    ya = y - (p * y + u_cap)
                elif u_cap == 0:
                    ya = y - (p_cap + u * x)
                else:
                    ya = y - (p_cap + u_cap)

            xp[next_region].append(xa)
            yp[next_region].append(ya)
            # "funky logic in REopt ignores everything except xa, ya"
            if region == "federal":
                cost_curve_bp_x.append(xa)
                cost_curve_bp_y.append(ya)

    for seg in range(1, len(cost_curve_bp_x)):
        tmp_slope = _jround((cost_curve_bp_y[seg] - cost_curve_bp_y[seg - 1])
                            / (cost_curve_bp_x[seg] - cost_curve_bp_x[seg - 1]))
        tmp_y_int = _jround(cost_curve_bp_y[seg] - tmp_slope * cost_curve_bp_x[seg])
        cap_cost_slope.append(tmp_slope)
        cap_cost_yint.append(tmp_y_int)
    n_segments = len(cap_cost_slope)

    # Re-price each segment's slope through the ITC and MACRS tax benefits
    updated_slope: list[float] = []
    for s in range(n_segments):
        if cost_curve_bp_x[s + 1] <= 0:
            raise ValueError(f"Invalid cost curve: breakpoint {s + 1} is {cost_curve_bp_x[s + 1]}")
        itc = tech.federal_itc_fraction
        rebate_federal = tech.federal_rebate_per_kw
        itc_unit_basis = 0 if itc == 1 else (cap_cost_slope[s] + rebate_federal) / (1 - itc)
        if tech.macrs_option_years != 0:
            bonus, itc_red = tech.macrs_bonus_fraction, tech.macrs_itc_reduction
        else:
            bonus, itc_red = 0.0, 0.0
        schedule = macrs_schedule_for(tech.macrs_option_years)
        replacement_cost, replacement_year = 0.0, analysis_years
        if tech.replacement_year is not None:          # Generator is the only one
            replacement_cost = (0.0 if tech.replacement_year >= analysis_years
                                else tech.replace_cost_per_kw)
            replacement_year = tech.replacement_year
        updated_slope.append(effective_cost(
            itc_basis=itc_unit_basis, replacement_cost=replacement_cost,
            replacement_year=replacement_year, discount_rate=owner_discount_rate,
            tax_rate=owner_tax_rate, itc=itc, macrs_schedule=schedule,
            macrs_bonus_fraction=bonus, macrs_itc_reduction=itc_red,
            rebate_per_kw=rebate_federal))

    updated_yint: list[float] = []
    for p_ in range(1, n_segments + 1):
        cost_curve_bp_y[p_] = (cost_curve_bp_y[p_ - 1]
                               + updated_slope[p_ - 1] * (cost_curve_bp_x[p_] - cost_curve_bp_x[p_ - 1]))
        updated_yint.append(cost_curve_bp_y[p_] - updated_slope[p_ - 1] * cost_curve_bp_x[p_])
    return updated_slope, cost_curve_bp_x, updated_yint, n_segments


def segments(slope: list[float], bp_x: list[float], yint: list[float], n: int, *,
             min_allowable_kw: float = 0.0, is_chp: bool = True) -> list[dict]:
    """reopt_inputs.jl:572-593 update_cost_curve! -- one dict per segment.

    For CHP the first breakpoint of every segment is raised to
    ``min_allowable_kw``, which is how REopt lets the model pick zero or at
    least that size.
    """
    return [{
        "slope": slope[s],
        "yint": yint[s],
        "min": max(bp_x[s], min_allowable_kw) if is_chp else bp_x[s],
        "max": bp_x[s + 1],
    } for s in range(n)]


def needs_segments(n_segments: int, *, is_chp: bool, min_allowable_kw: float) -> bool:
    """reopt_inputs.jl:579 -- the MILP gets segment binaries only in these cases."""
    return n_segments > 1 or (is_chp and min_allowable_kw > 0.0)
