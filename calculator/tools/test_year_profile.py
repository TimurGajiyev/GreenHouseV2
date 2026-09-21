"""Part 3 of the year/25-year methodology check: is the YEAR itself a real year?

No solver. Free mode builds an 8,760-hour year from a DOE reference building
shape scaled to the example week's average kilowatt (app_dispatch.build_year).
This part checks what that year actually contains -- energy conserved, a real
season, a real weekend -- against the thing it replaced, a week said 52 times,
and states plainly how much of the example week's own character survives the
substitution.

It also checks the day/week pickers the Dispatch Period view uses, because those
are what the design shows a reader once a year has been solved.

    python tools/test_year_profile.py
"""

from __future__ import annotations

import os
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app_dispatch as D
import app_periods as A

FAIL: list[str] = []
HOURS, DAYS = 8760, 365


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK' if ok else 'XX'}  {name:<54}{detail}")
    if not ok:
        FAIL.append(name)


def head(t: str) -> None:
    print(f"\n{t}\n{'-' * len(t)}")


def month_means(year: list[float]) -> list[float]:
    """Mean kW of each calendar month of a non-leap hourly year."""
    out, start = [], 0
    for dim in (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31):
        h = dim * 24
        out.append(sum(year[start:start + h]) / h)
        start += h
    return out


def main() -> int:
    print(__doc__.strip().splitlines()[0])
    ex = D._jsx_loads()
    if not ex:
        print("  -- the JSX artifact is not present; nothing to check")
        return 0
    week = ex["week"]
    w_mean = sum(week) / len(week)
    w_peak, w_low = max(week), min(week)

    head("4.1  every shape is a full year carrying the week's own energy")
    built = {}
    for label, spec in D.YEAR_SHAPES.items():
        year, note = D.build_year(spec, week)
        built[label] = year
        # The procedural FlatLoad shapes are zero outside their shift -- that is
        # what they are. Only the CRB buildings are continuously loaded.
        floor = 0.0 if "no climate" in label else 1e-9
        ok = (len(year) == HOURS and min(year) >= floor
              and abs(sum(year) / HOURS / w_mean - 1) < 1e-9)
        off = sum(1 for v in year if v <= 0)
        check(label[:52], ok,
              f"{sum(year) / 1e6:>8.3f} GWh  mean {sum(year) / HOURS:>7,.0f} kW"
              + (f"  {off:,} zero hours" if off else ""))
    totals = {round(sum(y)) for y in built.values()}
    check("all shapes carry the identical annual energy", len(totals) == 1,
          f"{len(totals)} distinct total(s)")

    head("4.2  a real year has a season; a tiled week does not")
    tiled = (week * 53)[:HOURS]
    m = month_means(tiled)
    swing_tiled = max(m) / min(m)
    print(f"      the example week tiled 52.14 times:  busiest month "
          f"{swing_tiled:.3f}x the quietest")
    # Not exactly 1.000: 168 hours do not divide into calendar months, so each
    # month cuts the repeating week at a different phase. That is arithmetic,
    # not weather -- a real year swings 1.19x to 1.38x (below).
    check("tiling a week produces no season", swing_tiled < 1.02,
          f"swing {swing_tiled:.3f} (tiling phase, not weather) -- this is why "
          f"it was replaced")

    print()
    for label, year in built.items():
        m = month_means(year)
        swing = max(m) / min(m)
        flat = "no climate" in label
        if flat:
            # No weather in these, but months do not hold the same number of
            # working days, so the monthly MEAN still moves. What must be
            # constant is the level itself: the profile takes two values, off
            # and on. Test that, not the calendar.
            levels = sorted({round(v, 6) for v in year})
            check(label[:52], len(levels) == 2,
                  f"month swing {swing:>6.3f}x from the calendar alone; "
                  f"{len(levels)} distinct levels (off/on)")
        else:
            check(label[:52], swing > 1.05, f"month swing {swing:>6.3f}x")

    head("4.3  weekday and weekend are distinguishable")
    # CRB years start on a Sunday (REopt's convention for the 2017 calendar the
    # tariff module uses); either way a 5/2 pattern shows up as a gap between the
    # busiest and quietest day-of-week means.
    for label, year in built.items():
        dow = [statistics.mean(
            year[d * 24 + h] for d in range(DAYS) if d % 7 == k for h in range(24))
            for k in range(7)]
        ratio = (max(dow) / min(dow)) if min(dow) > 0 else float("inf")
        print(f"      {label[:52]:<54}weekday/weekend spread "
              + (f"{ratio:.3f}x" if ratio != float("inf") else "total (idle at weekends)"))

    head("4.4  how much of the example week's own character survives")
    print(f"      the example week:      peak/mean {w_peak / w_mean:.2f}"
          f"   min/mean {w_low / w_mean:.2f}")
    print()
    best, best_d = None, 1e9
    for label, year in built.items():
        ym = sum(year) / HOURS
        p, l = max(year) / ym, min(year) / ym
        d = abs(p - w_peak / w_mean) + abs(l - w_low / w_mean)
        if d < best_d:
            best, best_d = label, d
        print(f"      {label[:52]:<54}peak/mean {p:.2f}   min/mean {l:.2f}"
              f"   distance {d:.2f}")
    default = next(iter(D.YEAR_SHAPES))
    check("the default shape is the closest to the example week", best == default,
          f"closest is '{best[:40]}', default is '{default[:40]}'")
    print("      NOTE: the LEVEL is the plant's own; the SHAPE is a US reference")
    print("      building. A site with a different season will get a different answer.")

    head("4.5  the day and week the design shows are slices of that year")
    year = built[default]
    rep, pk = A.representative_day(year), A.peak_day(year)
    daily = [sum(year[d * 24:(d + 1) * 24]) for d in range(DAYS)]
    check("365 day slices sum to the year", abs(sum(daily) - sum(year)) < 1e-6,
          f"{sum(daily):,.0f} vs {sum(year):,.0f}")
    check("the peak day contains the year's peak hour",
          max(year[pk * 24:(pk + 1) * 24]) == max(year), f"day {pk}")
    med = sorted(daily)[len(daily) // 2]
    check("the representative day is the median-energy day",
          abs(daily[rep] - med) <= 1e-6 * med, f"day {rep}")
    check("the representative day is not the peak day", rep != pk,
          f"rep {rep}, peak {pk}")
    # A single day is 1/365 of the year: the view must not imply otherwise.
    share = daily[rep] / sum(year)
    check("a representative day is about 1/365 of the year",
          abs(share * DAYS - 1) < 0.15, f"{share * DAYS:.3f} x (1/365)")

    print(f"\n{'FAILED: ' + '; '.join(FAIL) if FAIL else 'all profile checks passed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
