"""Render the profiling results block headlessly and check the HTML it emits.

The `%-d` crash reached the user because the *data* functions were validated
but the *render* path never ran. This closes that for the new design layer:
Streamlit is stubbed out, `render_periods` is called for every switch position,
and the captured HTML is checked for the faults that a table renderer actually
produces -- a row with the wrong number of cells, an empty header, a stray
NaN/None, an unbalanced tag.

Three shapes are covered, because they take different column paths:

  single   1 generator, 1 battery, PV        the REopt web-form shape
  fleet    3 generators, 2 batteries, PV     per-unit columns, several banks
  commit   2 fixed-nameplate units with turndown, start cost and curtailment
           -- the only shape that produces STARTS and SPILL columns
"""

from __future__ import annotations

import os
import re
import sys
import traceback
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reopt_core import data_sources as ds
from reopt_core import model as M
from reopt_core.tariff import build_tariff

LAT, LON = 39.74437, -105.15199
URDB = "5b44ffc75457a36716a907eb"

FAILURES: list[str] = []
HTML: list[str] = []
CHARTS: list[object] = []


# ------------------------------------------------------------- streamlit stub
class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _stub(switch_pick):
    """A streamlit module double that records every HTML block emitted."""
    st = types.SimpleNamespace()
    st.html = lambda body, **k: HTML.append(str(body))
    st.markdown = lambda body, **k: HTML.append(str(body))
    st.caption = lambda *a, **k: None
    st.write = lambda *a, **k: None
    st.altair_chart = lambda ch, **k: CHARTS.append(ch)
    st.columns = lambda spec, **k: [_Ctx() for _ in range(spec if isinstance(spec, int)
                                                          else len(spec))]
    st.expander = lambda *a, **k: _Ctx()
    st.container = lambda *a, **k: _Ctx()
    st.segmented_control = lambda label, options, **k: switch_pick(label, options)
    st.radio = lambda label, options, **k: switch_pick(label, options)
    st.dataframe = lambda *a, **k: None
    st.divider = lambda *a, **k: None
    return st


# ------------------------------------------------------------------- checks
_TAG = re.compile(r"<(/?)(table|thead|tbody|tr|th|td)\b[^>]*>")
_COLSPAN = re.compile(r'colspan="(\d+)"')


def check_tables(where: str) -> int:
    """Every table: header non-empty, every row as wide as the header."""
    n = 0
    for html in HTML:
        for tbl in re.findall(r"<table.*?</table>", html, re.S):
            n += 1
            head = re.findall(r"<th[^>]*>(.*?)</th>", tbl, re.S)
            if not head:
                FAILURES.append(f"{where}: table with no header")
                continue
            if any(h.strip() == "" for h in head):
                FAILURES.append(f"{where}: empty header cell in {head}")
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S):
                cells = re.findall(r"<td([^>]*)>(.*?)</td>", row, re.S)
                if not cells:
                    continue
                width = sum(int(_COLSPAN.search(a).group(1)) if _COLSPAN.search(a) else 1
                            for a, _ in cells)
                if width != len(head):
                    FAILURES.append(
                        f"{where}: row has {width} cells, header has {len(head)}"
                        f" -- {[v[:18] for _, v in cells]}")
                    break
                for _, v in cells:
                    if v.strip() in ("nan", "None", "NaN", "inf", "-inf"):
                        FAILURES.append(f"{where}: cell renders as {v.strip()!r}")
                        break
    return n


def check_tags(where: str) -> None:
    for html in HTML:
        depth: dict[str, int] = {}
        for closing, tag in _TAG.findall(html):
            depth[tag] = depth.get(tag, 0) + (-1 if closing else 1)
            if depth[tag] < 0:
                FAILURES.append(f"{where}: closing </{tag}> with none open")
                return
        bad = [t for t, d in depth.items() if d != 0]
        if bad:
            FAILURES.append(f"{where}: unbalanced tags {bad}")
            return


def check_charts(where: str) -> None:
    for ch in CHARTS:
        try:
            spec = ch.to_dict()
        except Exception as exc:
            FAILURES.append(f"{where}: chart does not compile: "
                            f"{type(exc).__name__}: {exc}")
            continue
        if not spec.get("layer"):
            FAILURES.append(f"{where}: chart has no layers")


# ------------------------------------------------------------------ scenarios
def scenario(n_gen, n_bat, pf, tar, *, commit=False):
    load = ds.build_electric_load("Supermarket", 3_000_000.0, LAT, LON)
    if commit:
        gens = [M.FuelTechInputs(
            enabled=True, kind="CHP", label="CHP", name=f"Engine {i + 1}",
            installed_cost_per_kw=0.0, om_cost_per_kw=0.0, om_cost_per_kwh=0.02,
            fuel_cost_per_mmbtu=8.0, electric_efficiency_full_load=0.35,
            thermal_efficiency_full_load=0.0,
            min_kw=300.0, max_kw=300.0, min_turn_down_fraction=0.5,
            start_cost=120.0, min_up_hours=2, min_down_hours=2, can_curtail=True,
            macrs_option_years=0, macrs_bonus_fraction=0.0, federal_itc_fraction=0.0)
            for i in range(n_gen)]
    else:
        gens = [M.FuelTechInputs(
            enabled=True, kind="Generator", name=f"Gen {i + 1}",
            installed_cost_per_kw=800.0, om_cost_per_kw=10.0,
            fuel_cost_per_gallon=2.25, min_kw=0.0, max_kw=400.0)
            for i in range(n_gen)]
    bats = [M.StorageInputs(
        enabled=True, name=f"Battery {i + 1}",
        installed_cost_per_kwh=320.0, installed_cost_per_kw=850.0,
        installed_cost_constant=0.0, max_kwh=1500.0)
        for i in range(n_bat)]
    return M.ScenarioInputs(
        loads_kw=load["loads_kw"], tariff=tar,
        financial=M.FinancialInputs(analysis_years=20,
                                    offtaker_discount_rate_fraction=0.075),
        pv=M.PVInputs(enabled=True, installed_cost_per_kw=1850.0,
                      max_kw=1000.0, acres_per_kw=0.006, production_factor=pf),
        storage=bats[0], storages=(bats if n_bat > 1 else None),
        fuel_tech=gens[0], fuel_techs=(gens if n_gen > 1 else None),
        land_acres=6.0, pv_location="ground", compensation_type="no_compensation",
    )


def exercise(tag: str, res, tar) -> None:
    print(f"\n--- {tag} ---")
    import app_periods
    import profile_ui
    import ui_theme

    state = {"res": res, "tariff": tar}
    for period in ("Day", "Week"):
        for which in ("Representative day", "Peak day"):
            HTML.clear()
            CHARTS.clear()

            def pick(label, options, _p=period, _w=which):
                return _p if "Period" in label else _w

            stub = _stub(pick)
            for mod in (app_periods, profile_ui, ui_theme):
                mod.st = stub
            where = f"{tag} / {period} / {which}"
            try:
                app_periods.render_periods(state)
            except Exception as exc:
                FAILURES.append(f"{where}: {type(exc).__name__}: {exc}")
                print(f"  XX  {where}")
                traceback.print_exc(limit=4)
                continue
            n = check_tables(where)
            check_tags(where)
            check_charts(where)
            print(f"  OK  {where:<44} {n} tables, {len(CHARTS)} chart, "
                  f"{sum(len(h) for h in HTML):,} bytes of HTML")


def main():
    pf, _ = ds.call_pvwatts_api(LAT, LON, tilt=20, azimuth=180, array_type=0,
                                module_type=0, losses=14)
    tar = build_tariff(ds.fetch_urdb_rate(URDB))

    for tag, ng, nb, commit, kw in (
        ("single  1 gen / 1 battery", 1, 1, False, dict(time_limit=900)),
        ("fleet   3 gen / 2 batteries", 3, 2, False, dict(time_limit=900)),
        ("commit  2 engines, turndown + starts", 2, 1, True,
         dict(time_limit=240, mip_gap=0.02)),
    ):
        res = M.solve(scenario(ng, nb, pf, tar, commit=commit), **kw)
        exercise(tag, res, tar)

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print("  - " + f)
        sys.exit(1)
    print("all profiling render checks passed")


if __name__ == "__main__":
    main()
