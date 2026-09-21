"""A year built from typical days, and twenty-five years built from that year.

**Not REopt.** This belongs to the Custom dispatch study, like everything else it
imports from. No formula in ``reopt_core`` is touched: the core solves each typical
day exactly as it solves any horizon, and this module only decides which days to
give it and how to add the answers up.

Why typical days at all
-----------------------
A full year of unit commitment is 8,760 hours times one binary per engine per
hour, and it does not solve. The standard answer in the literature is to cluster
the 365 days into a handful of typical ones and optimise those with WEIGHTS --
how many real days each typical day stands for. Kotzur, Markewitz, Robinius and
Stolten, *Time series aggregation for energy system design: Modeling seasonal
storage*, Applied Energy 213 (2018) 123-135, is the reference for the method and
for its one real limitation, quoted in their own words: typical periods
"are modeled independently and cannot exchange energy", so **seasonal** storage
needs a second, inter-period state variable to survive aggregation.

That limitation is stated rather than worked around here, and it is a mild one
for this study: the battery in it is a daily-cycling asset whose state of charge
is already closed over each day (cyclic SoC), so there is no seasonal store to
lose. What IS lost is any commitment decision that crosses midnight -- measured
on one month solved both ways: cost within 0.06 %, but 4 starts became 0.
So the money and the energy of a clustered year can be trusted; the start count
is a lower bound. ``tools/test_year_horizon.py`` is the measurement.

Why one year buys twenty-five
-----------------------------
This is REopt's own convention, in NREL's words: REopt "uses one year of resource
and cost data with present worth factors to account for life-time costs, assuming
that one year repeats with degradation and escalation factors". So the lifecycle
figures here multiply an ANNUAL operating cost by ``reopt_core.finance.annuity``,
which is the geometric sum REopt builds in ``REopt/src/core/utils.jl:11`` and
assumes cost growth in the first period. The same function the REopt panels use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from reopt_core import model as M
from reopt_core.finance import annuity

HOURS_PER_DAY = 24
DAYS_PER_YEAR = 365
HOURS_PER_YEAR = HOURS_PER_DAY * DAYS_PER_YEAR


# --------------------------------------------------------------- typical days
@dataclass
class Typical:
    """The year, compressed. ``weights`` sums to the number of days clustered."""

    load: list[list[float]]          # (k, 24) cluster centroid load
    price: list[list[float]]         # (k, 24) cluster centroid price
    weights: list[int]               # how many real days each cluster stands for
    day_of: list[int]                # for each real day, its cluster index

    @property
    def k(self) -> int:
        return len(self.weights)

    @property
    def days(self) -> int:
        return len(self.day_of)


def _kmeanspp(x: list[list[float]], k: int, seed: int, n_iter: int = 100) -> list[int]:
    """k-means with k-means++ seeding, deterministic for a given seed.

    Pure Python on purpose: this runs on at most 365 points of 48 dimensions, so
    the numpy dependency buys nothing and the arithmetic stays inspectable. The
    algorithm is the one in D:/Greenhouse/src/aggregate.py, line for line:
    squared euclidean distance, centroids as representatives, an empty cluster
    re-seeded to the point furthest from any centroid. k-means on whole periods
    is the clustering the time-series-aggregation literature uses for this job
    (Kotzur et al. 2018 compare it against hierarchical and k-medoids).
    """
    rnd = _Random(seed)
    n = len(x)
    k = min(k, n)
    d = len(x[0])

    def dist2(a: Sequence[float], b: Sequence[float]) -> float:
        return sum((a[i] - b[i]) ** 2 for i in range(d))

    centers = [list(x[rnd.below(n)])]
    d2 = [dist2(p, centers[0]) for p in x]
    while len(centers) < k:
        total = sum(d2)
        if total <= 0:
            centers.append(list(x[rnd.below(n)]))
        else:
            r = rnd.unit() * total
            acc = 0.0
            pick = n - 1
            for i, w in enumerate(d2):
                acc += w
                if acc >= r:
                    pick = i
                    break
            centers.append(list(x[pick]))
        d2 = [min(d2[i], dist2(x[i], centers[-1])) for i in range(n)]

    labels = [0] * n
    for it in range(n_iter):
        new = []
        far_i, far_d = 0, -1.0
        for i, p in enumerate(x):
            best, bestd = 0, float("inf")
            for c, ctr in enumerate(centers):
                dd = dist2(p, ctr)
                if dd < bestd:
                    best, bestd = c, dd
            new.append(best)
            if bestd > far_d:
                far_i, far_d = i, bestd
        if it and new == labels:
            break
        labels = new
        for c in range(k):
            members = [x[i] for i in range(n) if labels[i] == c]
            if members:
                centers[c] = [sum(m[j] for m in members) / len(members) for j in range(d)]
            elif far_d > 0:             # nobody chose it: re-seed to the outlier
                centers[c] = list(x[far_i])
                labels[far_i] = c
            # far_d == 0 means every day already sits exactly on its centre, so
            # there is no outlier to move and no work for another cluster. The
            # empty one is dropped below rather than handed an arbitrary day: a
            # year of identical days must come back as ONE typical day weighted
            # 365, not as 364 + 1.
    return labels


class _Random:
    """A tiny reproducible PRNG, so a run is repeatable without seeding numpy."""

    def __init__(self, seed: int) -> None:
        self.s = (seed * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)

    def _next(self) -> int:
        self.s = (self.s * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        return self.s >> 11

    def unit(self) -> float:
        return self._next() / float(1 << 53)

    def below(self, n: int) -> int:
        return int(self.unit() * n) % n


def cluster(load: Sequence[float], price: Sequence[float], k: int,
            seed: int = 0) -> Typical:
    """Cluster whole days of an hourly series into ``k`` typical days.

    The feature of a day is its 24 load hours next to its 24 price hours, each
    part divided by its own maximum so that kilowatts do not drown out a price
    (the same normalisation as aggregate.py, and for the same reason).

    The representative is the CENTROID -- the mean of the cluster's days -- not a
    medoid. A centroid preserves annual energy exactly: the weighted sum of the
    centroids is the sum of every real day, to the last kWh. A medoid does not.
    The price of that is a smoothed peak, which is why the peak of a clustered
    year is reported as its own number and never as the real year's peak.
    """
    n_days = len(load) // HOURS_PER_DAY
    if n_days < 2:
        raise ValueError("typical days need at least two whole days of load")
    if len(load) % HOURS_PER_DAY:
        raise ValueError(f"{len(load)} hours is not a whole number of days")
    if not 1 <= k <= n_days:
        raise ValueError(f"k must be between 1 and {n_days}, got {k}")

    lo = [list(load[d * 24:(d + 1) * 24]) for d in range(n_days)]
    pr = [list(price[d * 24:(d + 1) * 24]) for d in range(n_days)]
    lmax = max(max(r) for r in lo) or 1.0
    pmax = max((max(r) for r in pr), default=0.0) or 1.0
    feat = [[v / lmax for v in lo[d]] + [v / pmax for v in pr[d]] for d in range(n_days)]

    labels = _kmeanspp(feat, k, seed)
    used = sorted(set(labels))
    remap = {c: i for i, c in enumerate(used)}
    labels = [remap[c] for c in labels]

    cl, cp, w = [], [], []
    for c in range(len(used)):
        members = [d for d in range(n_days) if labels[d] == c]
        w.append(len(members))
        cl.append([sum(lo[d][h] for d in members) / len(members) for h in range(24)])
        cp.append([sum(pr[d][h] for d in members) / len(members) for h in range(24)])
    return Typical(load=cl, price=cp, weights=w, day_of=labels)


# ------------------------------------------------------------------- the year
def _concat(days: list[dict], order: Sequence[int], key: str):
    """Lay the typical days out over the real calendar, in the order they occur."""
    first = days[0]["series"].get(key)
    if isinstance(first, dict):
        out: dict[str, list[float]] = {name: [] for name in first}
        for c in order:
            src = days[c]["series"].get(key) or {}
            for name in out:
                out[name].extend(src.get(name) or [0.0] * HOURS_PER_DAY)
        return out
    if isinstance(first, list):
        if not first:
            return []
        out2: list[float] = []
        for c in order:
            out2.extend(days[c]["series"].get(key) or [0.0] * HOURS_PER_DAY)
        return out2
    return first


def _starts_cyclic(on: Sequence[float]) -> int:
    """Off->on transitions over a cyclic horizon -- the core's own count.

    ``model.py:_was_off`` looks at hour ``(t-1) % H`` when the commitment wraps,
    which is what the study's scenarios do. Applied to the replayed year this is
    the same rule the core would apply had it solved those 8,760 hours itself.
    """
    n = len(on)
    return sum(1 for t in range(n) if on[t] > 0.5 and on[(t - 1) % n] <= 0.5)


def replay(days: list[dict], typ: Typical, price_year: list[float],
           start_cost: dict[str, float] | None = None) -> dict:
    """Assemble one year-long result out of the ``k`` solved typical days.

    Each typical day is laid down on every real day of its cluster, so the year
    is the days replayed -- k solutions, 365 copies. Every linear quantity of the
    replayed year is therefore exactly the weighted sum of the typical days', by
    construction and not by a second calculation: sum over 8,760 hours == sum of
    weight x sum over 24. That is what makes the tables in the study add up
    whichever way a reader recomputes them.

    Starts are the one quantity that is NOT a sum over the typical days, and the
    reason is worth spelling out. A day solved on its own wraps at midnight, so
    its own start count already covers the hour-23-to-hour-0 seam of a day
    followed by ITSELF. Lay two unlike days next to each other and the join
    creates or removes a start that neither day could see. Those joins are real --
    the year does contain them -- so they are counted here, with exactly the rule
    the core uses for a cyclic horizon (``model.py:_was_off``), and the start cost
    they carry is added to the objective. Two consequences, both deliberate:

    * every table in the study reports the SAME start count, the one the replayed
      year actually performs, rather than one number in the cost table and a
      larger one in the period view;
    * ``objective_lifecycle_cost`` is the weighted sum of the day objectives PLUS
      the cost of the starts the joins create. It is reported in ``typical`` so it
      can be read separately -- measured on the JSX factory over a year: 331
      starts inside the typical days, 456 once they are run back to back.

    What is still lost is a minimum up or down time spanning a join: the days were
    solved as if each stood alone, so a unit can appear to run for fewer hours
    than its minimum across a boundary. The clustered year is an estimate of the
    year, not a dispatch plan for it, and that is the line where the estimate ends.
    """
    order = list(typ.day_of)
    series = {key: _concat(days, order, key) for key in days[0]["series"]}
    H = len(series["load_kw"])

    # unit rows: weighted sums of the typical days' own rows, so cost and energy
    # stay tied to the numbers the solver reported for each day
    by_name: dict[str, dict] = {}
    for c in order:
        for row in (days[c]["sizes"].get("fueltech_units") or []):
            acc = by_name.setdefault(row["name"], {
                "index": row["index"], "name": row["name"], "kind": row["kind"],
                "size_kw": row["size_kw"], "energy_kwh": 0.0, "running_hours": 0,
                "spill_kwh": 0.0, "fuel_units": 0.0,
                "fuel_unit_name": row.get("fuel_unit_name"),
                "existing_kw": row.get("existing_kw", 0.0),
                "purchase_kw": row.get("purchase_kw", 0.0),
                "segment": row.get("segment"), "unavailable_hours": 0,
                "production_incentive": 0.0,
                "starts": (0 if row.get("starts") is not None else None),
                "starts_by_day": ([] if row.get("starts_by_day") is not None else None),
                "capacity_factor": 0.0,
            })
            acc["energy_kwh"] += row["energy_kwh"]
            acc["running_hours"] += row["running_hours"]
            acc["spill_kwh"] += row.get("spill_kwh") or 0.0
            acc["fuel_units"] += row.get("fuel_units") or 0.0
            acc["unavailable_hours"] += row.get("unavailable_hours") or 0
            if acc["starts"] is not None:
                acc["starts"] += int(row.get("starts") or 0)
            if acc["starts_by_day"] is not None:
                acc["starts_by_day"].extend(row.get("starts_by_day") or [0])
    rows = list(by_name.values())
    for r in rows:
        r["capacity_factor"] = (r["energy_kwh"] / (r["size_kw"] * H)) if r["size_kw"] > 1e-9 else 0.0

    # The joins between unlike days: recount over the replayed year with the core's
    # own cyclic rule, and charge the difference. See the docstring.
    inside = {r["name"]: r["starts"] for r in rows if r["starts"] is not None}
    joins = 0
    extra_cost = 0.0
    on_all = series.get("fueltech_unit_on") or {}
    for r in rows:
        if r["starts"] is None or r["name"] not in on_all:
            continue
        on = on_all[r["name"]]
        whole = _starts_cyclic(on)
        joins += whole - r["starts"]
        extra_cost += (whole - r["starts"]) * float((start_cost or {}).get(r["name"], 0.0))
        r["starts"] = whole
        r["starts_by_day"] = [sum(1 for t in range(d * 24, (d + 1) * 24)
                                  if on[t] > 0.5 and on[(t - 1) % len(on)] <= 0.5)
                              for d in range(H // 24)]

    st_rows = []
    for row in (days[order[0]]["sizes"].get("storage_units") or []):
        thru = sum(sum(days[c]["series"]["battery_discharge_kw"]) for c in order)
        st_rows.append(dict(row, throughput_kwh=thru,
                            full_cycles=(thru / row["energy_kwh"]) if row["energy_kwh"] > 1e-9 else 0.0))

    sizes = dict(days[order[0]]["sizes"], fueltech_units=rows, storage_units=st_rows,
                 fueltech_kw=sum(r["size_kw"] for r in rows))
    obj_days = sum(days[c]["objective_lifecycle_cost"] for c in order)
    obj = obj_days + extra_cost
    gaps = [(d.get("solver") or {}).get("mip_gap") for d in days]
    gaps = [g for g in gaps if isinstance(g, float) and g == g and abs(g) != float("inf")]
    statuses = {d["status"] for d in days}

    return {
        "status": ("Optimal" if statuses == {"Optimal"} else "; ".join(sorted(statuses))),
        "solver": {"mip_gap": (max(gaps) if gaps else None),
                   "typical_days": typ.k, "weights": list(typ.weights)},
        "objective_lifecycle_cost": obj,
        "sizes": sizes,
        "energy": {
            "annual_load_kwh": sum(series["load_kw"]),
            "pv_kwh": sum(series.get("pv_to_load_kw") or []),
            "pv_curtailed_kwh": sum(series.get("pv_curtailed_kw") or []),
            "fueltech_kwh": sum(series["fueltech_kw"]),
            "grid_kwh": sum(series["grid_kw"]),
            "battery_discharge_kwh": sum(series["battery_discharge_kw"]),
            "unserved_kwh": sum(series.get("unserved_kw") or []),
            "exported_kwh": sum(series.get("export_kw") or []),
        },
        "series": series,
        "price_year": price_year,
        "typical": {"k": typ.k, "weights": list(typ.weights), "day_of": list(typ.day_of),
                    "objective_typical_days": obj_days,
                    "starts_inside_days": sum(inside.values()) if inside else 0,
                    "starts_from_joins": joins, "join_start_cost": extra_cost},
    }


def solve_year(pose: Callable[[list[float], list[float]], "M.ScenarioInputs"],
               load: Sequence[float], price: Sequence[float], k: int, *,
               seed: int = 0, time_limit: int = 120, mip_gap: float = 0.005,
               on_day: Callable[[int, int], None] | None = None,
               typical: Typical | None = None) -> dict:
    """Cluster, solve each typical day with the core, replay them over the year.

    ``pose`` turns one day's load and price into ``ScenarioInputs`` -- the caller
    owns the scenario, so the units, battery and rules are whatever the study's
    own tables say. Nothing here knows about them.
    """
    # One clustering serves every scenario of a study: the days are a property of
    # the load, not of the operating rule, and two scenarios compared on different
    # calendars would not be comparable at all.
    typ = typical or cluster(load, price, k, seed)
    days: list[dict] = []
    start_cost: dict[str, float] = {}
    for c in range(typ.k):
        if on_day:
            on_day(c, typ.k)
        inp = pose(typ.load[c], typ.price[c])
        if not start_cost:
            # What a start costs is the scenario's business, not this module's, so
            # it is read off the inputs the caller posed rather than guessed.
            for u in (list(inp.fuel_techs) if inp.fuel_techs else [inp.fuel_tech]):
                if u.enabled:
                    start_cost[u.name or u.label or u.kind] = float(u.start_cost or 0.0)
        res = M.solve(inp, time_limit=time_limit, mip_gap=mip_gap)
        if res["status"] not in ("Optimal", "Not Solved"):
            raise RuntimeError(f"typical day {c + 1} of {typ.k}: {res['status']}")
        days.append(res)
    price_year: list[float] = []
    for c in typ.day_of:
        price_year.extend(typ.price[c])
    return replay(days, typ, price_year, start_cost)


# ------------------------------------------------------------- twenty-five years
@dataclass
class Lifecycle:
    """What twenty-five years of one annual figure is worth today."""

    years: int
    escalation: float
    discount: float
    pwf: float
    annual_cost: float
    present_value: float
    annual_saving: float = 0.0
    saving_present_value: float = 0.0
    capex: float = 0.0
    simple_payback_years: float | None = None
    discounted_payback_years: float | None = None
    cumulative: list[float] = field(default_factory=list)


def lifecycle(annual_cost: float, *, years: int = 25, escalation: float = 0.0,
              discount: float = 0.0, annual_saving: float = 0.0,
              capex: float = 0.0) -> Lifecycle:
    """Present value of an annual figure repeated ``years`` times, and the payback.

    The present-worth factor is ``reopt_core.finance.annuity`` -- REopt's own
    geometric sum, which charges the first year already escalated once
    (``utils.jl:11``: "this formulation assumes cost growth in first period").
    Using anything else here would put the study's 25-year numbers on a different
    footing from the REopt panels', which is the one thing worth avoiding.

    Simple payback is CAPEX over the year-one saving, undiscounted -- that is
    what makes it simple, and it is the same quantity the study already showed.
    Discounted payback is the first year in which the discounted savings have
    repaid the CAPEX, interpolated inside that year; it is ``None`` when they
    never do, which is a real answer and not a failure.
    """
    pwf = annuity(years, escalation, discount)
    cum, run = [], 0.0
    disc_pay = None
    for y in range(1, years + 1):
        run += annual_saving * (1 + escalation) ** y / (1 + discount) ** y
        cum.append(run)
        if disc_pay is None and run >= capex > 0:
            prev = cum[-2] if len(cum) > 1 else 0.0
            step = run - prev
            disc_pay = (y - 1) + ((capex - prev) / step if step > 0 else 0.0)
    return Lifecycle(
        years=years, escalation=escalation, discount=discount, pwf=pwf,
        annual_cost=annual_cost, present_value=pwf * annual_cost,
        annual_saving=annual_saving, saving_present_value=pwf * annual_saving,
        capex=capex,
        simple_payback_years=(capex / annual_saving if capex > 0 and annual_saving > 0 else None),
        discounted_payback_years=disc_pay, cumulative=cum)


def annualise(window_cost: float, hours: int) -> float:
    """A window scaled to a year, with the error that carries stated where it is
    shown (app_dispatch) rather than hidden here. Exact only at 8,760 hours."""
    if hours <= 0:
        return 0.0
    return window_cost * HOURS_PER_YEAR / hours


def suggest_k(days: int) -> int:
    """A default number of typical days.

    12 is the figure the neighbouring project settled on (D:/Greenhouse/src/
    aggregate.py, ``n_days=12``). Measured on this calculator against years that
    can be solved whole: 4 typical days land within 0.5 %, 8 within 0.02 % and 12
    within 0.01 %, so 12 is comfortable rather than necessary.
    """
    return max(1, min(12, days))
