"""Battery payback by a fixed dispatch rule, on the plants' measured steps.

The measured year is replayed step by step through a fixed rule -- an engine runs only
in the efficient band or when the battery and the other engines cannot cover the load;
the battery takes the engines' surplus and covers the shortfall -- and priced against
what the meters show the plant did. A battery's saving is today's cost less the rule's,
its payback is its price over that saving, its life is its cycle life over the cycles a
year. The rule and the formulas reproduce a reference run step for step
(docs/zharkent-app/recreate.py, README section 3); the battery is described by the
dispatch study's own fields, and the defaults are the reference run's.

The steps are the plants' 5-minute run file when it is on disk, else this project's
hourly table, built by the same data rules. Nothing of the dispatch study's optimiser is
in here.
"""
from __future__ import annotations

import calendar
import functools
import math
import os
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HOURLY = os.path.join(ROOT, "real_data", "zharkent", "data", "zharkent_all_hourly.csv")
# the 5-minute run file, kept out of git: when it is on disk the rule runs on it
HIS_DIR = os.path.join(ROOT, ".playwright", "output", "zharkent")
HIS_RUN = "c1621a84d5f54a63"

# ---- the engines (datasheet rows) --------------------------------------------------------
RATED = {"mwm": 1200.0, "zh2": 1066.0, "zh3": 1066.0}
EFF = {"mwm": {0.5: 0.402, 0.75: 0.424, 1.0: 0.436},
       "zh2": {0.5: 0.396, 0.75: 0.419, 1.0: 0.432}}
EFF["zh3"] = EFF["zh2"]
NAME = {"mwm": "TEDOM", "zh2": "J320 Жаркент 2", "zh3": "J320 Жаркент 3"}
LONG = {"mwm": "TEDOM Quanto 1200 (Жаркент)", "zh2": "Jenbacher J320 (Жаркент 2)",
        "zh3": "Jenbacher J320 (Жаркент 3)"}

# ---- the three entities ----------------------------------------------------------------
GROUPS = {
    "K": dict(name="ЖКПЗ", units=["mwm", "zh2"],
              about="TEDOM Quanto 1200 + Jenbacher J320 (Жаркент 2), grid connection ЖКПЗ"),
    "M": dict(name="Жаркент 3", units=["zh3"],
              about="Jenbacher J320 (Жаркент 3), grid connection Универсал"),
    "KM": dict(name="Both plants, one battery", units=["mwm", "zh2", "zh3"],
               about="All three engines and both loads behind one battery; the cable "
                     "between the plants is not costed"),
}


@dataclass(frozen=True)
class Inputs:
    """Every input of the rule-based battery payback study. The defaults are the
    reference run's; the battery is described by the dispatch study's own fields."""
    # generators: each engine's rated output and efficiency at 50 / 75 / 100 % load (the
    # datasheets), and the engines the battery works with; the others run as measured
    gen_kw: tuple = (("mwm", 1200.0), ("zh2", 1066.0), ("zh3", 1066.0))
    gen_eff: tuple = (("mwm", (0.402, 0.424, 0.436)), ("zh2", (0.396, 0.419, 0.432)),
                      ("zh3", (0.396, 0.419, 0.432)))
    with_battery: tuple = ("mwm", "zh2", "zh3")
    # engines and the rule
    band: float = 0.90                      # engines run at least at, fraction of rated
    start_wear_h: float = 4.0               # equivalent engine hours per start
    service_kzt_kwh: float = 6.0            # KZT per kWh of rating -> per engine hour
    allow_export: bool = False
    # data
    bridge_h: float = 3.0                   # gaps up to this long bridged by a straight line
    # prices
    gas_kzt_m3: float = 75.0                # incl. VAT
    grid_kzt_kwh: float = 50.0              # incl. VAT
    vat: float = 0.12
    gas_kwh_m3: float = 9.44
    # battery: the dispatch study's fields
    # the default battery: of the reference run's own sizes (1, 2, 3, 4, 5.5, 7 MWh × 0.25,
    # 0.33, 0.5, 1 C), the one with the most profit over its life that keeps the engines in
    # the band and pays back before it wears out -- on ЖКПЗ and on both plants together
    power_kw: float = 1375.0
    energy_kwh: float = 5500.0
    own_kw: float = 15.0                    # cooling and controls, while there is a battery
    rte: float = 0.88
    soc_lo: float = 0.10                    # minimum state of charge
    wear_kzt_kwh: float = 0.0               # per kWh discharged
    capex_kzt: float = 475_200_000.0        # (5,500 kWh × 150 + 1,375 kW × 120) USD × 480
    soc_start: float = 0.50                 # every unbroken run of data starts here
    om_frac: float = 0.0                    # battery O&M, of CAPEX per year
    replace_year: int = 0                   # 0 = none
    replace_frac: float = 1.0               # of CAPEX
    cycle_life: float = 6000.0
    calendar_life: float = 15.0
    # other sizes for the payback charts: energy, with the battery's own hours of storage,
    # priced in proportion to its CAPEX
    sizes_mwh: tuple = (1.0, 2.0, 3.0, 4.0, 5.5, 7.0)
    # fixed parts of the rule
    soc_hi: float = 0.95                    # the charge window's top
    run_kw: float = 50.0                    # a unit counts as running above this
    kzt_eur: float = 520.0                  # display only
    start_wear_compared: tuple = (0.0, 1.0, 2.0, 4.0, 8.0)
    all_may_stop: bool = True
    min_run_h: float = 0.5
    min_off_h: float = 0.25
    taper_from: float = 0.85                # full charge power to here, linear to zero at 100 %
    floor: float = 0.50                     # datasheet minimum load
    below_band_allowed: float = 0.01        # share of engine hours below the band
    study_from: str = "2025-10-01"
    study_to: str = "2026-10-01"            # exclusive
    never_filled: tuple = (("K", "2025-12-01", "2026-01-01"), ("K", "2026-02-01", "2026-03-01"))
    coverage: float = 0.25                  # a month enters the year above this share

    # ---- derived ----
    @property
    def gas_kzt_kwh(self) -> float:         # KZT per kWh of gas, ex VAT
        return self.gas_kzt_m3 / (1 + self.vat) / self.gas_kwh_m3

    @property
    def grid_ex_vat(self) -> float:
        return self.grid_kzt_kwh / (1 + self.vat)

    @property
    def hours(self) -> float:               # hours of storage: energy ÷ power
        return self.energy_kwh / self.power_kw if self.power_kw else 0.0

    def rated(self, u: str) -> float:       # kW
        return dict(self.gen_kw)[u]

    def eff(self, u: str) -> dict:          # electrical efficiency at 50 / 75 / 100 % load
        return dict(zip((0.5, 0.75, 1.0), dict(self.gen_eff)[u]))

    def works(self, u: str) -> bool:        # the battery works with this engine
        return u in self.with_battery

    def om_h(self, u: str) -> float:        # KZT per engine hour
        return self.service_kzt_kwh * self.rated(u)


DEFAULTS = Inputs()

# The inputs still waiting for a contract or a supplier's figure.
PLACEHOLDERS = ["Fuel below 50 % load", "Engine counts as running above", "Start wear",
                "KZT per EUR", "Start wear values compared", "Battery cycle life",
                "Battery calendar life", "Round-trip efficiency", "Minimum SoC",
                "Battery's own use", "Minimum run time", "Minimum off time", "Charge taper",
                "Month coverage needed"]


# where each engine's datasheet figures come from
SHEET = {"mwm": ("Tedom Quanto 1200, MWM TCG 2020 V12 (technical sheet)",
                 "Tedom Quanto 1200 (MWM TCG 2020) technical sheet: 1200/900/600 kW, fuel "
                 "2750/2123/1492 kW"),
         "zh2": ("Jenbacher JMC 320 NG technical description; installed units are JMC 320",
                 "Jenbacher JMC 320 NG technical description"),
         "zh3": ("Jenbacher JMC 320 NG technical description; installed units are JMC 320",
                 "Jenbacher JMC 320 NG technical description")}


def _rated_row(u: str) -> str:
    return f"{LONG[u]}: rated output"


def _eff_row(u: str) -> str:
    return f"{LONG[u]}: efficiency at 50/75/100 %"


WITH_BATTERY_ROW = "Generators with the battery"


def _generator_rows(g: Inputs) -> list[tuple]:
    """Each engine's rating and efficiencies (datasheet, or typed when changed), and the
    engines the battery works with."""
    rows = []
    for u in RATED:
        same_kw = g.rated(u) == DEFAULTS.rated(u)
        rows.append((_rated_row(u), f"{g.rated(u):,.0f} kW",
                     SHEET[u][0] if same_kw else "Typed on this page", "datasheet" if same_kw else "typed"))
        e = g.eff(u)
        same_e = e == DEFAULTS.eff(u)
        rows.append((_eff_row(u), " / ".join(f"{100 * v:.1f}" for v in e.values()) + " %, LHV",
                     SHEET[u][1] if same_e else "Typed on this page", "datasheet" if same_e else "typed"))
    on = [LONG[u] for u in RATED if g.works(u)]
    off = [LONG[u] for u in RATED if not g.works(u)]
    rows.append((WITH_BATTERY_ROW, ", ".join(on) or "none",
                 "Project input; " + ("the others run as the meters show: " + ", ".join(off)
                                      if off else "every engine follows the rule"), "confirmed"))
    return rows


def inputs_table(inp: Inputs) -> list[dict]:
    """Every input of the run: value, where it comes from, and its status."""
    g = inp
    R = [
        *_generator_rows(g),
        ("Fuel below 50 % load", "extend fuel line", "Below 50 % the fuel input is extended along the 50–75 % slope; datasheets stop at 50 %", "placeholder"),
        ("Engine counts as running above", f"{g.run_kw:g} kW", "A unit counts as running above this output", "placeholder"),
        ("Service cost basis", f"{g.service_kzt_kwh:.1f} ₸/kWh of rating, per engine hour", "Service company's rate; sets the cost of an engine hour", "confirmed"),
        ("Start wear", f"{g.start_wear_h:.1f} engine hours per start", "To be set by the service company (warm vs cold start)", "placeholder"),
        ("KZT per EUR", f"{g.kzt_eur:g} ₸/EUR", "Display only", "placeholder"),
        ("Start wear values compared", ", ".join(f"{x:g}" for x in g.start_wear_compared) + " engine hours per start", "No published figure for gas engines; results are shown across this range", "placeholder"),
        ("Battery power", f"{g.power_kw:,.0f} kW", "Project input", "confirmed"),
        ("Battery energy", f"{g.energy_kwh:,.0f} kWh ({g.hours:.2f} h of storage)", "Project input", "confirmed"),
        ("Battery CAPEX", f"{g.capex_kzt:,.0f} ₸", "Project input; by default (5,500 kWh × 150 + 1,375 kW × 120) USD × 480 ₸/USD. The sizes compared are priced in proportion to their energy", "confirmed"),
        ("Battery O&M", f"{100 * g.om_frac:g} % of CAPEX per year", "Project input", "confirmed"),
        ("Replacement", (f"year {g.replace_year}, {100 * g.replace_frac:g} % of CAPEX" if g.replace_year else "none"), "Project input", "confirmed"),
        ("Wear cost", f"{g.wear_kzt_kwh:g} ₸ per kWh discharged", "Project input", "confirmed"),
        ("Start SoC", f"{100 * g.soc_start:g} %", "Every unbroken run of measured data starts at this charge", "confirmed"),
        ("Battery cycle life", f"{g.cycle_life:g} full cycles", "Life in years = this ÷ cycles a year, capped at the calendar life. Typical LFP warranty figure; replace with the supplier's", "placeholder"),
        ("Battery calendar life", f"{g.calendar_life:g} years", "A battery ages even when it cycles little; its life never exceeds this", "placeholder"),
        ("Round-trip efficiency", f"{100 * g.rte:g} %, AC to AC", "Applied as √RTE each way", "placeholder"),
        ("Minimum SoC", f"{100 * g.soc_lo:g} %", "Bottom of the charge window", "placeholder"),
        ("Maximum SoC", f"{100 * g.soc_hi:g} %", "Top of the charge window", "confirmed"),
        ("Battery's own use", f"{g.own_kw:g} kW", "Cooling and controls", "placeholder"),
        ("Battery sizes compared", ", ".join(f"{x:g}" for x in g.sizes_mwh) + f" MWh at {g.hours:.2f} h of storage", "Other sizes for the payback charts", "confirmed"),
        ("Engines run at least at", f"{100 * g.band:g} % of rated", "The efficient band; the datasheet floor is 50 %", "confirmed"),
        ("Export allowed", "yes" if g.allow_export else "no", "Export is not compensated", "confirmed"),
        ("All engines may stop", "yes" if g.all_may_stop else "no", "All engines may stop if the battery and the grid cover the load", "confirmed"),
        ("Minimum run time", f"{g.min_run_h:g} h", "Placeholder", "placeholder"),
        ("Minimum off time", f"{g.min_off_h:g} h", "Placeholder", "placeholder"),
        ("Charge taper", f"from {100 * g.taper_from:g} %", "Full charge power to here, linear to zero at 100 %", "placeholder"),
        ("Datasheet minimum load", f"{100 * g.floor:g} % of rated", "An engine drops below the band to here only when the battery is full and export is forbidden", "datasheet"),
        ("Allowed time below the band", f"{100 * g.below_band_allowed:g} % of engine hours", "A size counts as keeping the engines in the band if at most this share of running hours is below it", "confirmed"),
        ("VAT", f"{100 * g.vat:g} %", "Prices are taken ex VAT (input VAT is recovered)", "confirmed"),
        ("Gas price incl. VAT", f"{g.gas_kzt_m3:g} ₸/m³", "Project input", "confirmed"),
        ("Grid price incl. VAT", f"{g.grid_kzt_kwh:g} ₸/kWh", "Project input; flat, no capacity charge", "confirmed"),
        ("Gas heating value", f"{g.gas_kwh_m3:g} kWh/m³", "Tedom technical sheet basis 34 MJ/m³; confirm from the supply contract", "datasheet"),
        ("Gas ex VAT", f"{g.gas_kzt_kwh:.3f} ₸ per kWh of gas", f"{g.gas_kzt_m3:g} ÷ {1 + g.vat:g} ÷ {g.gas_kwh_m3:g}", "confirmed"),
        ("Grid ex VAT", f"{g.grid_ex_vat:.2f} ₸/kWh", f"{g.grid_kzt_kwh:g} ÷ {1 + g.vat:g}", "confirmed"),
        ("Export price", "0 ₸/kWh", "Export is not compensated", "confirmed"),
        ("Study year", f"{g.study_from} – {g.study_to} (exclusive)", "Twelve full months, Oct 2025 – Sep 2026", "confirmed"),
        ("Bridge data gaps up to", f"{g.bridge_h:g} h", "Gaps in one signal up to this long are bridged by a straight line; longer gaps stay empty", "confirmed"),
        ("Never filled", "ЖКПЗ Dec 2025, Feb 2026", "MWM data missing; kept as measured", "confirmed"),
        ("Month coverage needed", f"{100 * g.coverage:g} % of hours", "A month enters the annual figure only if at least this share of its hours close the power balance", "placeholder"),
    ]
    return [dict(input=a, value=b, source=c, status=d) for a, b, c, d in R]


LABELS = {"band": "Engines run at least at", "start_wear_h": "Start wear",
          "service_kzt_kwh": "Service cost basis", "allow_export": "Export allowed",
          "bridge_h": "Bridge data gaps up to", "gas_kzt_m3": "Gas price incl. VAT",
          "grid_kzt_kwh": "Grid price incl. VAT", "vat": "VAT", "gas_kwh_m3": "Gas heating value",
          "power_kw": "Battery power", "energy_kwh": "Battery energy", "own_kw": "Battery's own use",
          "rte": "Round-trip efficiency", "soc_lo": "Minimum SoC", "wear_kzt_kwh": "Wear cost",
          "capex_kzt": "Battery CAPEX", "soc_start": "Start SoC", "om_frac": "Battery O&M",
          "replace_year": "Replacement", "replace_frac": "Replacement",
          "cycle_life": "Battery cycle life", "calendar_life": "Battery calendar life",
          "sizes_mwh": "Battery sizes compared"}


def changed(inp: Inputs) -> list[str]:
    """The inputs that differ from the defaults, as the inputs table names them."""
    out = []
    for u in RATED:
        if inp.rated(u) != DEFAULTS.rated(u):
            out.append(_rated_row(u))
        if inp.eff(u) != DEFAULTS.eff(u):
            out.append(_eff_row(u))
    if set(inp.with_battery) != set(DEFAULTS.with_battery):
        out.append(WITH_BATTERY_ROW)
    for k, label in LABELS.items():
        if getattr(inp, k) != getattr(DEFAULTS, k) and label not in out:
            out.append(label)
    return out


# ---- the measured steps ------------------------------------------------------------------
def _bridge(s: pd.Series, max_steps: int, frozen: pd.Series | None = None) -> pd.Series:
    """Fill runs of missing values of at most ``max_steps`` with a straight line between
    the readings either side; longer runs, and runs at either end, stay empty."""
    if max_steps <= 0:
        return s
    na = s.isna()
    run_id = (na != na.shift()).cumsum()
    length = na.groupby(run_id).transform("sum")
    inner = na & (length <= max_steps)
    # only runs with a reading on both sides
    first_ok, last_ok = s.first_valid_index(), s.last_valid_index()
    if first_ok is None:
        return s
    inner &= (s.index > first_ok) & (s.index < last_ok)
    if frozen is not None:
        inner &= ~frozen
    filled = s.interpolate(limit_area="inside")
    return s.where(~inner, filled)


def hourly_steps(group: str, inp: Inputs = DEFAULTS, study_only: bool = True) -> pd.DataFrame:
    """The rule's steps, built from this project's hourly table by the run file's data rules.

    * engines and grid each as measured; a reading this project rebuilt from the hour's
      balance is dropped (the run file leaves those hours empty, or takes the myPlant
      window, which this table does not have);
    * Жаркент 3's CR06 clock (UTC+5) moved +1 h onto the others';
    * gaps up to ``bridge_h`` bridged by a straight line, except in the never-filled periods;
    * a step is kept when every engine and the grid are known; load = engines + grid;
    * the study year only, Oct 2025 – Sep 2026.
    Both plants together net their grids (one bus)."""
    t = pd.read_csv(HOURLY, parse_dates=["time"]).set_index("time")
    k = pd.DataFrame({
        "mwm": t["tedom_kw"],
        "zh2": t["j320_2_kw"].where(~t["j320_2_from_balance"].fillna(False).astype(bool)),
        "grid": t["zhkpz_import_kw"].where(~t["import_2_from_balance"].fillna(False).astype(bool)),
    })
    m = pd.DataFrame({
        "zh3": t["j320_3_kw"].where(~t["j320_3_from_balance"].fillna(False).astype(bool)),
        "grid": t["site3_import_kw"].where(~t["import_3_from_balance"].fillna(False).astype(bool)),
    })
    m.index = m.index + pd.Timedelta(hours=1)
    idx = k.index.union(m.index)
    k, m = k.reindex(idx), m.reindex(idx)
    steps = max(0, int(math.floor(inp.bridge_h + 1e-9)))     # one step = one hour here
    never = pd.Series(False, index=idx)
    for g_, a, b in inp.never_filled:
        if g_ == "K":
            never |= (idx >= pd.Timestamp(a)) & (idx < pd.Timestamp(b))
    k = pd.DataFrame({c: _bridge(k[c], steps, never) for c in k})
    m = pd.DataFrame({c: _bridge(m[c], steps) for c in m})
    units = GROUPS[group]["units"]
    if group == "K":
        sig = {"mwm": k["mwm"], "zh2": k["zh2"]}
        grid = k["grid"]
    elif group == "M":
        sig = {"zh3": m["zh3"]}
        grid = m["grid"]
    else:
        sig = {"mwm": k["mwm"], "zh2": k["zh2"], "zh3": m["zh3"]}
        grid = k["grid"] + m["grid"]
    x = pd.DataFrame({f"{u}_measured": sig[u] for u in units})
    x["grid_measured"] = grid
    x["load"] = x[[f"{u}_measured" for u in units]].sum(axis=1, min_count=len(units)) + grid
    lo, hi = pd.Timestamp(inp.study_from), pd.Timestamp(inp.study_to)
    if study_only:
        x = x[(x.index >= lo) & (x.index < hi)]
    x = x.dropna()
    x = x.reset_index().rename(columns={"index": "time"})
    x["new"] = x["time"].diff() != pd.Timedelta(hours=1)
    x.attrs["dt"] = 1.0
    x.attrs["source"] = "hourly measurements"
    return x


def his_steps_available() -> bool:
    return os.path.exists(os.path.join(HIS_DIR, f"runs_{HIS_RUN}_decisions.csv.gz"))


@functools.lru_cache(maxsize=1)
def _his_file() -> pd.DataFrame:
    """The 5-minute run file, read once and only for the measured columns the rule needs
    (it also carries every step's decision text in two languages)."""
    want = {"time", "group", "load", "grid_measured", "mwm_measured", "zh2_measured", "zh3_measured"}
    return pd.read_csv(os.path.join(HIS_DIR, f"runs_{HIS_RUN}_decisions.csv.gz"),
                       usecols=lambda c: c in want, parse_dates=["time"], low_memory=False)


def his_steps(group: str) -> pd.DataFrame:
    """The 5-minute steps of the run file."""
    d = _his_file()
    x = d[d.group == group].sort_values("time").reset_index(drop=True)
    x["new"] = x["time"].diff() != pd.Timedelta(minutes=5)
    keep = ["time", "load", "grid_measured", "new"] + [f"{u}_measured" for u in GROUPS[group]["units"]]
    x = x[[c for c in keep if c in x.columns]].copy()
    x.attrs["dt"] = 5 / 60
    x.attrs["source"] = "5-minute run file"
    return x


# ---- the arithmetic ------------------------------------------------------------------------
def fuel_kw(u: str, p: np.ndarray, run_kw: float = 50.0, inp: Inputs | None = None) -> np.ndarray:
    """kW of gas: straight lines through rated × load ÷ efficiency at 50, 75 and 100 %,
    the 50–75 % slope extended below 50 %; nothing below the running threshold. The rating
    and efficiencies are the inputs' (the datasheets' by default)."""
    rated = inp.rated(u) if inp is not None else RATED[u]
    e = inp.eff(u) if inp is not None else EFF[u]
    xs = [rated * f for f in e]
    ys = [rated * f / v for f, v in e.items()]
    slope = (ys[1] - ys[0]) / (xs[1] - xs[0])
    f = np.where(p < xs[0], ys[0] + slope * (p - xs[0]), np.interp(p, xs, ys))
    return np.where(p > run_kw, np.maximum(f, 0.0), 0.0)


def _months(x: pd.DataFrame) -> tuple:
    """Each step's calendar month as an index into the months the steps cover, the hours
    in each of those months and their names -- worked out once per set of steps."""
    key = x.attrs.get("_months")
    if key is None or len(key[1]) != len(x):
        t = x["time"]
        code = (t.dt.year * 12 + t.dt.month - 1).to_numpy()
        uniq, inv = np.unique(code, return_inverse=True)
        hours = np.array([calendar.monthrange(int(c) // 12, int(c) % 12 + 1)[1] * 24.0 for c in uniq])
        names = [f"{int(c) // 12}-{int(c) % 12 + 1:02d}" for c in uniq]
        key = (uniq, inv, hours, names)
        x.attrs["_months"] = key
    return key


def year(x: pd.DataFrame, per_step: pd.DataFrame, inp: Inputs = DEFAULTS) -> pd.Series:
    """Each month × (hours in month ÷ complete hours); months under the coverage dropped;
    the year = the mean of the months kept × 12."""
    dt = x.attrs.get("dt", 1.0)
    uniq, inv, in_month, names = _months(x)
    complete = np.bincount(inv, minlength=len(uniq)) * dt
    keep = complete / in_month >= inp.coverage
    scale = np.where(keep, in_month / np.where(complete > 0, complete, 1.0), 0.0)
    n_kept = max(1, int(keep.sum()))
    out = pd.Series({c: float((np.bincount(inv, weights=np.asarray(per_step[c], dtype=float),
                                           minlength=len(uniq)) * scale).sum()) * 12 / n_kept
                     for c in per_step.columns}, dtype=float)
    out.attrs["months"] = [n for n, k in zip(names, keep) if k]
    out.attrs["left_out"] = [n for n, k in zip(names, keep) if not k]
    out.attrs["complete_h"] = float(complete.sum())
    return out


def cost(x: pd.DataFrame, out: dict[str, np.ndarray], imp: np.ndarray, exp: np.ndarray,
         inp: Inputs = DEFAULTS, start_h: float | None = None, extra: dict | None = None) -> pd.Series:
    """Fuel + service (engine hours + starts × start wear) + grid, per year."""
    dt = x.attrs.get("dt", 1.0)
    start_h = inp.start_wear_h if start_h is None else start_h
    cols = {}
    new = x["new"].values
    for u, p in out.items():
        run = p > inp.run_kw
        # a start inside a stretch, or the rule switching on at a stretch's first step an
        # engine the meters show off there (how the reference run counts its starts)
        meas = x[f"{u}_measured"].fillna(0).values > inp.run_kw
        start = (run & ~np.r_[False, run[:-1]] & ~new) | (new & run & ~meas)
        cols[f"{u}_fuel"] = fuel_kw(u, p, inp.run_kw, inp) * dt
        cols[f"{u}_run_h"] = run * dt
        cols[f"{u}_starts"] = start.astype(float)
        cols[f"{u}_kwh"] = p * dt
    cols["imp_kwh"], cols["exp_kwh"] = imp * dt, exp * dt
    for k, v in (extra or {}).items():
        cols[k] = v
    y = year(x, pd.DataFrame(cols), inp)
    us = list(out)
    y["fuel_kwh"] = sum(y[f"{u}_fuel"] for u in us)
    y["fuel_kzt"] = y["fuel_kwh"] * inp.gas_kzt_kwh
    y["run_h"] = sum(y[f"{u}_run_h"] for u in us)
    y["starts"] = sum(y[f"{u}_starts"] for u in us)
    y["om_kzt"] = sum((y[f"{u}_run_h"] + start_h * y[f"{u}_starts"]) * inp.om_h(u) for u in us)
    y["start_wear_kzt"] = sum(start_h * y[f"{u}_starts"] * inp.om_h(u) for u in us)
    y["grid_kzt"] = y["imp_kwh"] * inp.grid_ex_vat
    y["gen_kwh"] = sum(y[f"{u}_kwh"] for u in us)
    y["cost_kzt"] = y["fuel_kzt"] + y["om_kzt"] + y["grid_kzt"]
    y["kzt_per_kwh_gen"] = (y["fuel_kzt"] + y["om_kzt"]) / y["gen_kwh"] if y["gen_kwh"] else 0.0
    return y


def base(x: pd.DataFrame, units: list[str], inp: Inputs = DEFAULTS,
         start_h: float | None = None) -> pd.Series:
    """Today, from the meters: each engine as measured, the grid as measured."""
    g = x["grid_measured"].values
    return cost(x, {u: x[f"{u}_measured"].fillna(0).values for u in units},
                np.maximum(g, 0), np.maximum(-g, 0), inp, start_h)


def simulate(x: pd.DataFrame, units: list[str], e_kwh: float, p_kw: float,
             inp: Inputs = DEFAULTS) -> dict:
    """The rule, step by step (docs/zharkent-app/recreate.py, its constants as inputs).

    Only the engines the battery works with follow the rule. The others run as the meters
    show: their output is taken off the load the rule serves, and where they make more than
    the load the battery may take the surplus (the rest is exported, as measured)."""
    dt = x.attrs.get("dt", 1.0)
    min_on = max(1, int(round(inp.min_run_h / dt)))
    min_off = max(1, int(round(inp.min_off_h / dt)))
    n, eta = len(x), inp.rte ** 0.5
    fixed = [u for u in units if not inp.works(u)]
    measured = {u: x[f"{u}_measured"].fillna(0).values for u in fixed}
    all_units, units = list(units), [u for u in units if inp.works(u)]
    RATED = {u: inp.rated(u) for u in units}        # noqa: N806 -- the inputs' ratings
    total = x["load"].values
    load = total - sum(measured.values()) if fixed else total
    new = x["new"].values
    meas_on = {u: (x[f"{u}_measured"].fillna(0).values > inp.run_kw) for u in units}
    out = {u: np.zeros(n) for u in units}
    soc_s, ch_s, dis_s, imp_s, exp_s, oob, forced = (np.zeros(n) for _ in range(7))
    on = {u: False for u in units}
    age = {u: 0 for u in units}
    soc = inp.soc_start
    for i in range(n):
        if new[i]:                               # a new stretch: start SoC, engines as measured
            soc = inp.soc_start
            for u in units:
                on[u], age[u] = bool(meas_on[u][i]), 10 ** 6
        need = load[i] + inp.own_kw if e_kwh > 0 else load[i]
        give = min(p_kw, max(0.0, (soc - inp.soc_lo) * e_kwh * eta / dt)) if e_kwh > 0 else 0.0
        taper = min(1.0, (1.0 - soc) / (1.0 - inp.taper_from))
        take = min(p_kw * taper, max(0.0, (inp.soc_hi - soc) * e_kwh / eta / dt)) if e_kwh > 0 else 0.0
        r_on = sum(RATED[u] for u in units if on[u])
        if r_on + give < need:                   # short: start the engine off the longest,
            while r_on + give < need:            # and the next one if that is not enough
                cand = [u for u in units if not on[u] and age[u] >= min_off]
                if not cand:
                    break
                u = max(cand, key=lambda k: age[k])
                on[u], age[u] = True, 0
                r_on += RATED[u]
        elif inp.band * r_on > need + take:      # surplus even at the band: stop the longest-running
            cand = [u for u in units if on[u] and age[u] >= min_on]
            for u in sorted(cand, key=lambda k: -age[k]):
                if r_on - RATED[u] + give >= need:
                    on[u], age[u] = False, 0
                    break
        r_on = sum(RATED[u] for u in units if on[u])
        # even the datasheet floor makes more than the load and the battery can absorb,
        # and export is forbidden: an engine is stopped whatever the cover ("forced")
        while not inp.allow_export and r_on and inp.floor * r_on > need + take:
            u = max((k for k in units if on[k]), key=lambda k: age[k])
            on[u], age[u] = False, 0
            forced[i] = 1.0
            r_on = sum(RATED[k] for k in units if on[k])
        gen = min(r_on, need + take)             # engines full, the battery takes the surplus
        gen = max(gen, inp.floor * r_on)         # never under the datasheet floor
        if r_on and gen < inp.band * r_on - 1e-6:
            oob[i] = 1.0
        for u in units:
            out[u][i] = gen * RATED[u] / r_on if on[u] else 0.0
        if gen >= need:
            ch = min(gen - need, take)
            dis = 0.0
            exp_s[i] = gen - need - ch
        else:
            ch = 0.0
            dis = min(need - gen, give)
            imp_s[i] = need - gen - dis
        soc += (ch * eta - dis / eta) * dt / e_kwh if e_kwh > 0 else 0.0
        soc_s[i], ch_s[i], dis_s[i] = soc, ch, dis
        for u in units:
            age[u] += 1
    out = {u: (out[u] if u in out else measured[u]) for u in all_units}
    return dict(out=out, soc=soc_s, ch=ch_s, dis=dis_s, imp=imp_s, exp=exp_s, oob=oob,
                forced=forced, need=total + (inp.own_kw if e_kwh > 0 else 0.0))


def power_for(e_kwh: float, inp: Inputs = DEFAULTS) -> float:
    """A size's power: the battery's own hours of storage."""
    if abs(e_kwh - inp.energy_kwh) < 1e-6:
        return inp.power_kw
    return e_kwh / inp.hours if inp.hours else 0.0


def price(e_kwh: float, inp: Inputs = DEFAULTS) -> float:
    """A size's CAPEX, ₸: the battery's CAPEX in proportion to energy (at the same hours
    of storage a price per kWh and per kW scales the same way)."""
    return inp.capex_kzt * e_kwh / inp.energy_kwh if inp.energy_kwh else 0.0


def payback(capex: float, net: float, inp: Inputs = DEFAULTS) -> float:
    """Simple payback: CAPEX ÷ the net saving a year, and the replacement too if the
    battery has not paid back by its year. NaN when it never does."""
    if net <= 0:
        return np.nan
    p = capex / net
    rep = inp.replace_frac * capex if inp.replace_year > 0 else 0.0
    if rep and p > inp.replace_year:
        p = (capex + rep) / net
    return p


def evaluate(x: pd.DataFrame, units: list[str], e_kwh: float, p_kw: float, sim: dict,
             today: pd.Series, inp: Inputs = DEFAULTS, start_h: float | None = None) -> pd.Series:
    """One simulated size: cost, saving and its two parts, cycles, life, payback, profit
    over life, in the band, pays back."""
    dt = x.attrs.get("dt", 1.0)
    y = cost(x, sim["out"], sim["imp"], sim["exp"], inp, start_h,
             extra={"throughput_kwh": sim["dis"] * dt, "oob_h": sim["oob"] * dt,
                    "charge_kwh": sim["ch"] * dt})
    y["e_mwh"], y["p_mw"] = e_kwh / 1000.0, p_kw / 1000.0
    y["capex_kzt"] = price(e_kwh, inp)
    y["wear_kzt"] = y["throughput_kwh"] * inp.wear_kzt_kwh
    y["cost_kzt"] = y["cost_kzt"] + y["wear_kzt"]
    y["saving_kzt"] = today["cost_kzt"] - y["cost_kzt"]
    y["band_kzt"] = (today["kzt_per_kwh_gen"] - y["kzt_per_kwh_gen"]) * today["gen_kwh"]
    y["import_kzt"] = y["saving_kzt"] - y["band_kzt"]
    y["bat_om_kzt"] = inp.om_frac * y["capex_kzt"]
    y["net_kzt"] = y["saving_kzt"] - y["bat_om_kzt"]
    y["cycles"] = y["throughput_kwh"] / (e_kwh * (inp.soc_hi - inp.soc_lo)) if e_kwh else 0.0
    y["life_y"] = (min(inp.cycle_life / y["cycles"], inp.calendar_life) if y["cycles"]
                   else inp.calendar_life)
    y["payback_y"] = payback(y["capex_kzt"], y["net_kzt"], inp)
    rep = (inp.replace_frac * y["capex_kzt"]
           if 0 < inp.replace_year < y["life_y"] else 0.0)
    y["replace_kzt"] = rep
    y["profit_kzt"] = y["net_kzt"] * y["life_y"] - y["capex_kzt"] - rep
    # in the band: hours below it against the hours of the engines that follow the rule
    y["rule_run_h"] = sum(y[f"{u}_run_h"] for u in units if inp.works(u))
    y["in_band"] = bool(y["oob_h"] <= inp.below_band_allowed * y["rule_run_h"])
    y["pays_back"] = bool(y["payback_y"] == y["payback_y"] and y["payback_y"] <= y["life_y"])
    y["battery_wear_kzt"] = y["capex_kzt"] / y["life_y"] if y["life_y"] else 0.0
    return y


@dataclass
class Run:
    """One entity's run: today, your battery, every size compared, and the steps."""
    group: str
    x: pd.DataFrame
    today: pd.Series
    yours: pd.Series
    sizes: pd.DataFrame
    sim: dict = field(repr=False, default_factory=dict)
    sims: dict = field(repr=False, default_factory=dict)
    inp: Inputs = DEFAULTS

    @property
    def best(self) -> pd.Series | None:
        """Shortest payback, in the band and before wear-out."""
        ok = self.sizes[self.sizes["in_band"] & self.sizes["pays_back"]]
        if ok.empty:
            return None
        return ok.sort_values("payback_y").iloc[0]


def run_group(group: str, inp: Inputs = DEFAULTS, x: pd.DataFrame | None = None,
              on_size=None) -> Run:
    """Today, your battery and every size compared, for one entity."""
    x = hourly_steps(group, inp) if x is None else x
    units = GROUPS[group]["units"]
    today = base(x, units, inp)
    compared = {round(1000.0 * float(e), 6) for e in inp.sizes_mwh}
    sizes = sorted(compared | {round(float(inp.energy_kwh), 6)})
    sims, rows = {}, []
    for i, e in enumerate(sizes):
        if on_size:
            on_size(i, len(sizes))
        p = power_for(e, inp)
        s = simulate(x, units, e, p, inp)
        sims[e] = s
        r = evaluate(x, units, e, p, s, today, inp)
        r["compared"] = e in compared
        rows.append(r)
    table = pd.DataFrame(rows)
    key = round(float(inp.energy_kwh), 6)
    yours = table.iloc[sizes.index(key)]
    r = Run(group=group, x=x, today=today, yours=yours,
            sizes=table[table["compared"]].reset_index(drop=True), sim=sims[key], sims=sims,
            inp=inp)
    # keep the step series only of the sizes the page draws step by step: yours and the
    # shortest payback
    b = r.best
    keep = {key} | ({round(1000.0 * float(b.e_mwh), 6)} if b is not None else set())
    r.sims = {k: v for k, v in sims.items() if k in keep}
    return r


def start_wear_curve(r: Run, e_kwh: float) -> list[tuple[float, float]]:
    """Payback of one size at every start wear compared."""
    units = GROUPS[r.group]["units"]
    p = power_for(e_kwh, r.inp)
    s = r.sims.get(round(float(e_kwh), 6))
    if s is None:
        s = simulate(r.x, units, e_kwh, p, r.inp)
    out = []
    for w in r.inp.start_wear_compared:
        t = base(r.x, units, r.inp, start_h=w)
        y = evaluate(r.x, units, e_kwh, p, s, t, r.inp, start_h=w)
        out.append((float(w), float(y["payback_y"])))
    return out


def wear_vs_start(r: Run, row: pd.Series) -> list[dict]:
    """Wear per year against the engine hours charged per start: engine start wear with
    the battery and today, and the battery's wear (price ÷ life)."""
    units = GROUPS[r.group]["units"]
    rate_starts_yours = sum(row[f"{u}_starts"] * r.inp.om_h(u) for u in units)
    rate_starts_today = sum(r.today[f"{u}_starts"] * r.inp.om_h(u) for u in units)
    return [dict(h=float(h), with_battery=h * rate_starts_yours, today=h * rate_starts_today,
                 battery=float(row["battery_wear_kzt"])) for h in np.arange(0, 8.5, 0.5)]


def today_breakdown(r: Run) -> dict:
    """Today for one entity: cost per year, engines per year and what full-output running
    could save at most."""
    t, inp = r.today, r.inp
    units = GROUPS[r.group]["units"]
    eng = {}
    excess_h = excess_kzt = penalty_kwh = 0.0
    for u in units:
        gen, run_h = t[f"{u}_kwh"], t[f"{u}_run_h"]
        loading = gen / (run_h * inp.rated(u)) if run_h else 0.0
        eng[u] = dict(kwh=gen, run_h=run_h, starts=t[f"{u}_starts"], loading=loading)
        xh = max(0.0, run_h - gen / inp.rated(u))
        excess_h += xh
        excess_kzt += xh * inp.om_h(u)
        penalty_kwh += max(0.0, t[f"{u}_fuel"] - gen / inp.eff(u)[1.0])
    fuel_per_kwh = t["fuel_kzt"] / t["gen_kwh"] if t["gen_kwh"] else 0.0
    return dict(total=t["cost_kzt"], fuel=t["fuel_kzt"], fuel_kwh=t["fuel_kwh"],
                service=t["om_kzt"], grid=t["grid_kzt"], imp=t["imp_kwh"], exp=t["exp_kwh"],
                gen=t["gen_kwh"], load=t["gen_kwh"] + t["imp_kwh"] - t["exp_kwh"],
                engines=eng, excess_h=excess_h, excess_kzt=excess_kzt,
                penalty_kwh=penalty_kwh, penalty_kzt=penalty_kwh * inp.gas_kzt_kwh,
                export_kzt=t["exp_kwh"] * fuel_per_kwh,
                months=t.attrs.get("months", []), left_out=t.attrs.get("left_out", []))


def months_table(x: pd.DataFrame, units: list[str], inp: Inputs = DEFAULTS) -> pd.DataFrame:
    """Per calendar month: measured energy, import, export, complete hours, cost (scaled to
    the full month as the year does), and whether the month enters the year."""
    dt = x.attrs.get("dt", 1.0)
    m = x["time"].dt.to_period("M")
    g = x.groupby(m.values)
    rows = []
    for p, s in g:
        hours = p.days_in_month * 24
        complete = len(s) * dt
        r = {"month": p, "complete_h": complete, "hours": hours,
             "share": complete / hours, "kept": complete / hours >= inp.coverage}
        fuel = om = 0.0
        for u in units:
            pw = s[f"{u}_measured"].fillna(0).values
            r[f"{u}_mwh"] = pw.sum() * dt / 1e3
            fuel += fuel_kw(u, pw, inp.run_kw, inp).sum() * dt * inp.gas_kzt_kwh
            on = pw > inp.run_kw
            om += on.sum() * dt * inp.om_h(u)
        gm = s["grid_measured"].values
        r["imp_mwh"] = np.maximum(gm, 0).sum() * dt / 1e3
        r["exp_mwh"] = np.maximum(-gm, 0).sum() * dt / 1e3
        scale = hours / complete if complete else 0.0
        r["fuel_kzt"], r["service_kzt"] = fuel * scale, om * scale
        r["grid_kzt"] = r["imp_mwh"] * 1e3 * inp.grid_ex_vat * scale
        rows.append(r)
    return pd.DataFrame(rows)


# the reference run's published figures, for the data check (docs/zharkent-app README,
# appendix A; screens/data/*monthly-table): used by the tests and REPORT.md, not the page
HIS_TODAY = {"K": dict(cost=449.0e6, fuel=190.9e6, service=110.0e6, grid=148.1e6,
                       imp=3318e3, run_h=13679, starts=635, months=9),
             "M": dict(cost=169.5e6, fuel=83.2e6, service=47.3e6, grid=39.1e6,
                       imp=875e3, run_h=6726, starts=166, months=12),
             "KM": dict(cost=600.7e6)}
HIS_RESULT = {"K": dict(saving=90.5e6, payback=3.02, starts=899.2, cycles=699),
              "M": dict(saving=26.1e6, payback=10.46, starts=741.3, cycles=688),
              "KM": dict(saving=127.2e6, payback=2.15, starts=887.7, cycles=643)}
HIS_MONTHS = {
    "K": {"2025-09": (277, 131, 107, 118, 651), "2025-10": (506, 553, 138, 44, 597),
          "2025-11": (413, 584, 302, 0, 679), "2025-12": (0, 194, 638, 0, 0),
          "2026-01": (154, 478, 416, 0, 411), "2026-02": (0, 244, 523, 14, 0),
          "2026-03": (307, 687, 351, 27, 614), "2026-04": (517, 660, 126, 0, 626),
          "2026-05": (415, 563, 126, 2, 576), "2026-06": (159, 189, 191, 51, 220),
          "2026-07": (167, 420, 270, 0, 154), "2026-08": (381, 469, 283, 2, 589),
          "2026-09": (275, 379, 263, 35, 711), "2026-10": (1, 103, 44, 55, 325)},
    "M": {"2025-09": (67, 147, 2, 347), "2025-10": (276, 172, 0, 606), "2025-11": (446, 30, 29, 595),
          "2025-12": (126, 264, 25, 659), "2026-01": (349, 75, 41, 597), "2026-02": (347, 119, 34, 593),
          "2026-03": (508, 20, 50, 632), "2026-04": (510, 14, 52, 622), "2026-05": (410, 50, 43, 629),
          "2026-06": (449, 12, 52, 575), "2026-07": (363, 23, 42, 576), "2026-08": (340, 6, 43, 539),
          "2026-09": (451, 2, 70, 710), "2026-10": (190, 3, 31, 326)},
}


def raw_months(group: str) -> pd.DataFrame:
    """This project's hourly table per month, before any of the step rules: each signal
    summed over the hours it has (rebuilt readings included), the grid split into import
    and export, and the hours where every signal is known."""
    t = pd.read_csv(HOURLY, parse_dates=["time"])
    if group == "M":
        t["time"] = t["time"] + pd.Timedelta(hours=1)
        cols = {"zh3": "j320_3_kw"}
        grid = "site3_import_kw"
    else:
        cols = {"mwm": "tedom_kw", "zh2": "j320_2_kw"}
        grid = "zhkpz_import_kw"
    t["m"] = t["time"].dt.to_period("M")
    rows = []
    for p, s in t.groupby("m"):
        r = {"month": str(p)}
        for u, c in cols.items():
            r[f"{u}_mwh"] = s[c].sum() / 1e3
        r["imp_mwh"] = s[grid].clip(lower=0).sum() / 1e3
        r["exp_mwh"] = (-s[grid]).clip(lower=0).sum() / 1e3
        known = s[grid].notna()
        for c in cols.values():
            known &= s[c].notna()
        r["balance_h"] = int(known.sum())
        rows.append(r)
    return pd.DataFrame(rows)


def data_check(group: str) -> pd.DataFrame:
    """This project's months against the reference run's Data page, where published."""
    ref = HIS_MONTHS.get(group)
    if not ref:
        return pd.DataFrame()
    ours = raw_months(group).set_index("month")
    units = GROUPS[group]["units"]
    rows = []
    for month, vals in ref.items():
        o = ours.loc[month] if month in ours.index else None
        r = {"month": month}
        for u, v in zip(units, vals[:len(units)]):
            r[f"{NAME[u]} reference"] = v
            r[f"{NAME[u]} ours"] = round(float(o[f"{u}_mwh"])) if o is not None else None
        n = len(units)
        r["import reference"], r["import ours"] = vals[n], round(float(o["imp_mwh"])) if o is not None else None
        r["export reference"], r["export ours"] = vals[n + 1], round(float(o["exp_mwh"])) if o is not None else None
        r["complete h reference"] = vals[n + 2]
        r["complete h ours"] = int(o["balance_h"]) if o is not None else None
        rows.append(r)
    return pd.DataFrame(rows)


def with_inputs(**kw) -> Inputs:
    return replace(DEFAULTS, **kw)


# ---- this project's "Dispatch by period", fed by the rule ----------------------------------
def _site(group: str) -> str:
    """The measured site of real_data each entity is: ЖКПЗ, Жаркент 3, or the pool of
    all three engines."""
    import real_data as RD
    return {"K": RD.ZHKPZ, "M": RD.SITE3, "KM": RD.ALL3}[group]
KWH_PER_MMBTU = 293.07107


def _step_costs(x: pd.DataFrame, out: dict, imp: np.ndarray, inp: Inputs,
                dis: np.ndarray | None = None) -> tuple:
    """Each step's cost in the rule's terms: energy (fuel + engine hours + grid) and starts
    (start wear × the hourly rate), with the reference start count; and each unit's starts."""
    dt = x.attrs.get("dt", 1.0)
    new = x["new"].values
    energy = imp * dt * inp.grid_ex_vat
    ops = np.zeros(len(x)) if dis is None else dis * dt * inp.wear_kzt_kwh
    starts = {}
    for u, p in out.items():
        run = p > inp.run_kw
        meas = x[f"{u}_measured"].fillna(0).values > inp.run_kw
        start = (run & ~np.r_[False, run[:-1]] & ~new) | (new & run & ~meas)
        energy = energy + fuel_kw(u, p, inp.run_kw, inp) * dt * inp.gas_kzt_kwh + run * dt * inp.om_h(u)
        ops = ops + start * inp.start_wear_h * inp.om_h(u)
        starts[u] = start.astype(float)
    return energy, ops, starts


def period_state(r: Run) -> dict:
    """Your battery under the rule, as this project's period view reads a result.

    The steps are averaged to clock hours (an hour counts when every one of its steps
    is there) and cut into whole 24-hour days the way the dispatch study cuts measured
    days (real_data.days), so the view's day and week are real days with their own
    dates. Every kW is the rule's; every tenge is the rule's arithmetic: the hour's energy
    cost (fuel on the curve, engine hours, grid) and its start wear, today's and the
    rule's, so the saving in the hover panel and the veil is the study's saving, hour by hour.
    """
    import real_data as RD
    x, s, inp = r.x, r.sim, r.inp
    dt = x.attrs.get("dt", 1.0)
    units = GROUPS[r.group]["units"]
    e_kwh = 1000.0 * float(r.yours.e_mwh)
    p_kw = 1000.0 * float(r.yours.p_mw)
    battery = e_kwh > 0
    # the rule, and today from the meters, step by step
    e_rule, o_rule, st_rule = _step_costs(x, s["out"], s["imp"], inp, s["dis"])
    meas = {u: x[f"{u}_measured"].fillna(0).values for u in units}
    imp0 = np.maximum(x["grid_measured"].values, 0.0)
    e_today, o_today, st_today = _step_costs(x, meas, imp0, inp)
    f = pd.DataFrame({"hour": x["time"].dt.floor("h"), "need": s["need"], "imp": s["imp"],
                      "ch": s["ch"], "dis": s["dis"], "exp": s["exp"], "soc": s["soc"],
                      "e_rule": e_rule, "o_rule": o_rule, "e_today": e_today,
                      "o_today": o_today, "n": 1.0})
    for u in units:
        f[f"p_{u}"] = s["out"][u]
        f[f"on_{u}"] = (s["out"][u] > inp.run_kw).astype(float)
        f[f"st_{u}"] = st_rule[u]
        f[f"st0_{u}"] = st_today[u]
        f[f"fuel_{u}"] = fuel_kw(u, s["out"][u], inp.run_kw, inp) * dt
    g = f.groupby("hour")
    mean_cols = ["need", "imp", "ch", "dis", "exp"] + [f"p_{u}" for u in units]
    sum_cols = (["e_rule", "o_rule", "e_today", "o_today", "n"]
                + [f"st_{u}" for u in units] + [f"st0_{u}" for u in units]
                + [f"fuel_{u}" for u in units])
    h = pd.concat([g[mean_cols].mean(), g[sum_cols].sum(), g["soc"].last(),
                   g[[f"on_{u}" for u in units]].max()], axis=1)
    full = pd.date_range(h.index.min(), h.index.max(), freq="h")
    h = h.reindex(full)
    complete = (h["n"] >= round(1.0 / dt) - 1e-9).fillna(False)
    keep = RD.days(complete)
    h = h[keep.values]
    H = len(h)
    names = {u: LONG[u] for u in units}
    series = {
        "load_kw": list(h["need"]), "pv_to_load_kw": [0.0] * H, "pv_curtailed_kw": [0.0] * H,
        "grid_kw": list(h["imp"]), "battery_charge_kw": list(h["ch"]),
        "battery_discharge_kw": list(h["dis"]), "soc_kwh": list(h["soc"] * e_kwh),
        "fueltech_kw": list(h[[f"p_{u}" for u in units]].sum(axis=1)),
        "fueltech_unit_kw": {names[u]: list(h[f"p_{u}"]) for u in units},
        "fueltech_unit_on": {names[u]: list(h[f"on_{u}"]) for u in units},
        "fueltech_unit_spill_kw": {names[u]: [0.0] * H for u in units},
        "unserved_kw": [0.0] * H, "export_kw": list(h["exp"]),
    }
    n_days = H // 24
    rows = []
    for u in units:
        st_h = list(h[f"st_{u}"])
        energy = float(h[f"p_{u}"].sum())
        rows.append({
            "index": len(rows), "name": names[u], "kind": "CHP", "size_kw": inp.rated(u),
            "energy_kwh": energy, "running_hours": int(h[f"on_{u}"].sum()),
            "capacity_factor": energy / (inp.rated(u) * H) if H else 0.0,
            "fuel_units": float(h[f"fuel_{u}"].sum()) / 1000.0, "fuel_unit_name": "MWh gas",
            "spill_kwh": 0.0, "starts": int(round(sum(st_h))),
            "starts_by_day": [int(round(sum(st_h[d * 24:(d + 1) * 24]))) for d in range(n_days)],
        })
    thru = float(h["dis"].sum())
    storage = ([{"name": "Battery", "power_kw": p_kw, "energy_kwh": e_kwh,
                 "duration_hours": e_kwh / p_kw if p_kw else 0.0, "throughput_kwh": thru,
                 "full_cycles": thru / (e_kwh * (inp.soc_hi - inp.soc_lo))}] if battery else [])
    res = {"series": series, "status": "rule",
           "sizes": {"fueltech_units": rows, "storage_units": storage, "pv_kw": 0.0,
                     "fueltech_kw": sum(inp.rated(u) for u in units)}}
    tariff = type("Tariff", (), {"energy_cost_per_kwh": [inp.grid_ex_vat] * H})()
    eng_full = float(np.mean([inp.gas_kzt_kwh / inp.eff(u)[1.0] + inp.om_h(u) / inp.rated(u)
                              for u in units]))
    spread = inp.grid_ex_vat - eng_full
    starts_cur = [int(round(v)) for v in h[[f"st_{u}" for u in units]].sum(axis=1)]
    starts_base = [int(round(v)) for v in h[[f"st0_{u}" for u in units]].sum(axis=1)]
    sav = {"base": "today, measured",
           "save_e": list(h["e_today"] - h["e_rule"]), "save_s": list(h["o_today"] - h["o_rule"]),
           "starts_cur": starts_cur, "starts_base": starts_base,
           "soc_cur": series["soc_kwh"] if battery else [], "soc_base": [],
           "soc0_cur": inp.soc_start * e_kwh, "soc0_base": 0.0, "eta": inp.rte ** 0.5,
           "price_mean": inp.grid_ex_vat, "spread": spread if spread > 0 else inp.grid_ex_vat}
    return {"res": res, "tariff": tariff, "currency": "₸", "savings": sav,
            "time": list(h.index), "measured_site": _site(r.group),
            "label": f"{_label(r.yours)} · by the rule",
            "days": n_days, "hours_dropped": int(len(x) * dt) - H}


def _label(y: pd.Series) -> str:
    return f"Battery {1000 * y.e_mwh:,.0f} kWh / {1000 * y.p_mw:,.0f} kW"
