# GreenHouse — REopt replication, validation and field use

One document covering the whole project: what was built, how it was verified against
the live REopt web tool and the REopt.jl source, what was found in both, and where
the limits are.

**Target system:** <https://reopt.nlr.gov/tool> · **Local engine:** `REopt/` — REopt.jl
**v0.61.1** (`REopt/Project.toml`) · **Our calculator:** `calculator/` (Python + Streamlit
+ PuLP/HiGHS) · **Offline docs:** `docs/reopt-jl/` (14 pages, 197 KB)

---

## Contents

- [Part 1 — The calculator](#part-1--the-calculator)
- [Part 2 — Validation scoreboard](#part-2--validation-scoreboard)
- [Part 3 — Test cases in detail](#part-3--test-cases-in-detail)
- [Part 4 — Findings about the REopt web tool](#part-4--findings-about-the-reopt-web-tool)
- [Part 5 — Grid-tied vs off-grid](#part-5--grid-tied-vs-off-grid)
- [Part 6 — CHP and Prime Generator](#part-6--chp-and-prime-generator)
- [Part 7 — Off-grid CHP](#part-7--off-grid-chp)
- [Part 8 — Field use: the Sana'a vendor proposal](#part-8--field-use-the-sanaa-vendor-proposal)
- [Part 9 — Bugs found and fixed](#part-9--bugs-found-and-fixed)
- [Part 10 — Known gaps](#part-10--known-gaps)
- [Part 11 — The profiling view](#part-11--the-profiling-view)
- [Part 12 — CHP and Battery, field for field with the web tool](#part-12--chp-and-battery-field-for-field-with-the-web-tool)
- [Part 13 — Custom dispatch study (not REopt)](#part-13--custom-dispatch-study-not-reopt)
- [Part 14 — An outside case: Sigalo et al. 2023](#part-14--an-outside-case-sigalo-et-al-2023)
- [Part 15 — IEEE PES pglib-uc: the commitment maths, cross-validated](#part-15--ieee-pes-pglib-uc-the-commitment-maths-cross-validated)
- [Part 16 — A year, and twenty-five of them: the methodology re-checked](#part-16--a-year-and-twenty-five-of-them-the-methodology-re-checked)
- [Part 17 — Repository layout and how to reproduce](#part-17--repository-layout-and-how-to-reproduce)

---

# Part 1 — The calculator

A working subset of the REopt web tool: **steps 1–5**, four technologies
(Prime Generator / Generator, CHP, PV, Battery).

```bash
pip install streamlit pulp highspy pandas altair
streamlit run calculator/streamlit_app.py
```

Needs a free API key from <https://developer.nlr.gov> for PVWatts and URDB:
set `NLR_DEVELOPER_API_KEY`, or put the key in `.nrel_api_key`.

## Nothing in it is invented

| Piece | Source |
|---|---|
| Step titles, field labels, option values **and order**, defaults, help text | Scraped live from the tool into `reopt_test_data/ui-spec.json`, then **code-generated** into `reopt_core/ui_fields.py` (270 fields) |
| `annuity`, `annuity_two_escalation_rates` | `utils.jl:11,21` |
| `levelization_factor` · `npv` | `utils.jl:54` · `utils.jl:295` |
| `effective_cost` (ITC + MACRS → `cap_cost_slope`) | `utils.jl:83` |
| MACRS 5/7-year schedules | `financial.jl:19-20` |
| Objective — lifecycle cost, per-term tax treatment | `reopt.jl:511-590` |
| Storage sizing / SOC dynamics / cost-constant binary | `storage_constraints.jl:2-73,151` |
| Electric load balance | `load_balance.jl:3` |
| PV land-use constraint | `tech_constraints.jl:26-31` |
| Operating reserve (off-grid) | `operating_reserve_constraints.jl` |
| Thermal balance + existing boiler | `chp.jl`, `existing_boiler.jl`, `financial.jl:7` |
| Nearest CRB city | `doe_commercial_reference_building_loads.jl:79-93` |
| Procedural FlatLoad shapes | `doe_commercial_reference_building_loads.jl:278` |
| Hourly load shapes | `REopt/data/load_profiles/electric/crb8760_norm_<City>_<Type>.dat` |
| Heating load | `REopt/data/load_profiles/{space_heating,domestic_hot_water}_annual_mmbtu.json` |
| PV production | PVWatts v8 — same URL and `ac/1000` scaling as `utils.jl:475-513` |
| Tech defaults | `pv.jl`, `electric_storage.jl:225-265`, `generator.jl:9-47`, `chp_defaults.json` |
| Emissions | Cambium `scenarioviewer.nlr.gov`, AVERT `/tool/emissions-profile`, EASIUR `/tool/emissions-health-defaults` |
| Solver | **HiGHS** — the same solver the web tool submits (`solver_name: "HiGHS"`) |

UI rules reproduced from observed behaviour:

- Prime Generator and CHP are **mutually exclusive** (verified in both directions).
- **Backup Generator only appears when Resilience is selected.**
- Off-grid removes the entire electricity-rate panel and has **no business-as-usual
  case** (`reopt.jl:117`).
- Required fields with a blank default stay blank — "Type of building" is not silently
  defaulted to the first option.

---

# Part 2 — Validation scoreboard

Every figure below comes from a real submission to the public REopt service, compared
row-by-row against the same scenario in our calculator.

| Suite | Scope | Result | Script |
|---|---|---|---|
| **TC1** | Golden CO · Large Office 5 GWh · PV + Battery · 25 yr | **23/23** (incl. payback, IRR) | `tools/validate2.py` |
| **TC2** | Phoenix AZ · Supermarket 3 GWh · emissions, health & climate costs · 20 yr | **15/15** | `tools/validate_tc2.py` |
| **G1/G2** | CHP and Prime Generator + PV + Battery | **24/24** (incl. payback, IRR) | `tools/validate_gen.py` |
| **V1–V4** | Variability — four sites, buildings, tariffs, horizons | **27/29** | `tools/vary_ours.py` |
| **OG1** | Off-grid, generator pinned as the tool submits it | **LCC −0.08%** | `tools/validate_offgrid.py` |
| **PT2** | Live head-to-head on a scenario neither had seen | **22/24** | `tools/validate_parity.py` |

The single most demanding check is the **business-as-usual bill**: it exercises the URDB
parse, the 8,760-hour CRB load, the TOU demand ratchets and the present-worth factor with
no optimizer freedom to absorb an error. It reproduces REopt **to the dollar** in TC1, TC2,
V1–V4 and PT2.

---

# Part 3 — Test cases in detail

> Figures in this part were refreshed on 2026-09-18 after the battery's initial state of charge was ported (Part 12): with SoC starting at 50% instead of closing in a loop, TC1 and G1/G2 now match REopt's life cycle cost to the dollar.

## TC1 — Golden CO (23/23)

> Large Office 5,000,000 kWh · 5 acres · Intermountain REA B-TOU ·
> PV $1,600/kW max 2,000 · Battery $300/kWh $800/kW const $0 max 4,000 ·
> 25 yr · discount 8.3% · escalation 1.7%

| | REopt | Ours |
|---|---:|---:|
| PV | 165 kW | **165 kW** |
| Battery | 78 kW / 171 kWh | **78 kW / 171 kWh** |
| Life cycle cost, BAU / optimized | $4,624,883 / $4,601,676 | $4,624,883 / **$4,601,676** |
| Net present value | $23,207 | **$23,207** |
| CO₂e over the period | 18,664 t | 18,664 t |
| Cost of climate / health emissions | $600,023 / $427,092 | $600,195 / $427,108 |

## TC2 — Phoenix AZ (15/15)

Deliberately a different site, building, tariff, AVERT region and horizon.
REopt run `18d2e5c0-536f-4a07-8d8b-d2a24673b830`.

Both calculators decline to build anything (PV 0 / Battery 0). Year-1 energy $117,000,
demand $16,526, fixed $300, total $133,826 and life cycle cost $1,214,920 all match
exactly. Cambium location (*West Connect South*), AVERT region (*Southwest*), CO₂e
(423 t/yr) and NOx/SO₂/PM2.5 (0.46 / 0.21 / 0.07 t) all match.

## V1–V4 — Variability (27/29)

Four scenarios, each varying a different axis. AVERT region and Cambium location resolved
automatically from coordinates in all four and matched: Mid-Atlantic, Northwest, Florida,
Southwest.

| # | Scenario | What it probes | Result |
|---|---|---|---|
| **V1** | Chicago · Hospital · 8 GWh · **roof** 120,000 ft² · **net metering** · 30 yr | roof limit, NEM, long horizon | **6/6** |
| **V2** | Seattle · Warehouse · 1.5 GWh · **battery only** · 15 yr · 9% | no-PV path, short horizon, high discount | **7/7** |
| **V3** | Miami · Restaurant · 0.8 GWh · PV+battery · 1 acre · 20 yr | tiny site, cheap tariff, build-nothing | **8/8** |
| **V4** | Albuquerque · Midrise Apartment · 2.5 GWh · PV+battery · 4 acres · 25 yr | default costs, both techs built | **6/8** |

V1's PV hit the roof limit exactly in both: 120,000 ft² × 0.01 kW/ft² = 1,200 kW.
V3 is the one where Cambium returns *"NA – Cambium data not used"* (Florida Keys is
outside the Cambium grid) and both tools handled it correctly.

**V4 is the only disagreement**, and it is understood: PV 290 kW vs our 358 kW (+23%),
because the piecewise PV size-class cost curve is not ported. Battery capacity matched
to −0.07% and life cycle cost to **−0.16%** — the solutions sit on a nearly flat part of
the objective, so a different PV size costs almost the same.

## PT2 — Live head-to-head on an unseen scenario (22/24)

Run on 2026-08-24. REopt run
[`c5e511b2-56d6-4673-8a7a-f46338687576`](https://reopt.nlr.gov/tool/results/c5e511b2-56d6-4673-8a7a-f46338687576).

> Golden CO · **Supermarket** 3,000,000 kWh · 6 acres · B-TOU · **20 yr** · 7.5% discount ·
> 2.2% escalation · PV $1,850/kW max 1,500 · Battery $320/kWh $850/kW max 3,000 ·
> no export compensation. REopt solved at a **0.1%** optimality tolerance.

Nothing overlaps TC1/TC2/G1/G2: different building, load, costs, horizon, discount and land.

**Business as usual — all five rows to the dollar:**
energy $190,890 · demand $91,771 · fixed $480 · year-1 total $283,141 ·
life cycle cost $2,570,463.

**Optimized:**

| Row | REopt | Ours | Δ |
|---|---:|---:|---:|
| PV Size | 25 kW | 25 kW | +0.47% |
| Battery Power | 26 kW | 26 kW | −1.23% |
| Battery Capacity | 36 kWh | 35 kWh | −3.88% |
| Average Annual PV Energy Production | 36,747 kWh | 36,747 kWh | **0.00%** |
| Year 1 Utility Cost — Before Tax | $276,050 | $276,109 | +0.02% |
| Upfront Capital Before Incentives | $80,081 | $79,366 | −0.89% |
| **Total Life Cycle Costs** | **$2,559,868** | **$2,559,867** | **−0.000%** |
| Net Present Value | $10,595 | $10,590 | −0.05% |

Life cycle cost lands **$5 apart on $2.56 million**.

**The two mismatched rows are one difference, not two.** Battery charging totals 3,067 kWh
for REopt (443 from PV + 2,624 from grid) against 2,959 kWh for us (2,959 from PV + 0 from
grid) — 3.5% apart. Both charge the same 36 kWh battery by the same amount; they attribute
the source differently. In an hour where PV is generating and the battery is charging that
label is arbitrary, which is why every cost row still agrees.

**Through the UI, not just the engine** — same inputs typed into the running app:

| | REopt | Our engine | Our Streamlit UI |
|---|---:|---:|---:|
| PV size | 25 kW | 25 kW | **25 kW** |
| Battery power | 26 kW | 26 kW | **26 kW** |
| Battery capacity | 36 kWh | 35 kWh | **35 kWh** |
| Net savings | $10,595 | $10,590 | **$10,590** |

![PT2 ours](reopt_test_screenshots/parity/PT2-ours-results.png)

### A discarded first attempt

PT1 was Phoenix/Mesa on an Arizona Public Service TOU tariff
([`87129ce1`](https://reopt.nlr.gov/tool/results/87129ce1-bbcc-4265-8853-0e58aeb97a3e)).
It is not reported as a result because the tariff could not be reproduced: the web tool
submits the rate by **display name** and resolves it server-side, and the record it
resolved implies **$0.58/kWh** for energy ($1,739,600 on 3,000,000 kWh). All 55 APS
large-general-service records at those coordinates bill $0.11–0.13/kWh. The gap is in
tariff identification, not in either optimizer.

---

# Part 4 — Findings about the REopt web tool

## 4.1 Defects

### `GET /tool/utility-rates` returns HTTP 500 intermittently — *medium*

First address entry produced a blocking alert (*"An unexpected error occurred while
fetching the utility rates"*). The identical URL returned HTTP 200 on three consecutive
`curl` calls, and other coordinates returned 200. A genuine intermittent server fault,
not a bad request. A user's first attempt at a site can fail with an opaque alert and no
retry guidance.

### Outage start date/hour required by the backend, not enforced client-side — *high (UX)*

Submitting with the outage start blank passes client validation and fails server-side with
a raw Julia dictionary:

```
{"ElectricUtility" => {"outage_start_time_steps" => ["Item 1 in the array did not validate: This field cannot be null."]}}
```

Step 0 guidance lists outage start as required data, but the fields carry no `*` and the
form submits anyway.

### Resilience runs fail with a Julia EPIPE error — *critical, reproducible*

| Goals | Techs | Result |
|---|---|---|
| Cost Savings | PV | ✅ ~12 s |
| Cost Savings | PV + Battery | ✅ ~12 s |
| Cost Savings + **Resilience** | PV + Battery | ❌ `IOError: write: broken pipe (EPIPE)` (×2) |

Job UUIDs `dbbcf56e-155c-439b-8618-daebf366e777` and
`179a8965-16fb-42c1-911b-44ccbfe71c74`. The failure is not caused by the Battery
technology and not by a general outage — B and C differ from A only in the Resilience goal.

Why resilience is the expensive path: enabling outages appends a microgrid sub-model
(`reopt.jl:546-548`) with a **constraint per (scenario × outage-start-time-step)** each
summing over the outage duration (`outage_constraints.jl:51-58`), plus a three-dimensional
binary block `binMGGenIsOnInTS[S, tZeros, outage_time_steps]` (`reopt.jl:769-770`) whose
big-M bounds the source itself flags as weak. Converting a pure LP into a MILP with weak
big-M bounds is consistent with a solve outliving a proxy timeout.

### PV size class inconsistent with the optimized size — *medium (accuracy)*

Run B returned 25 kW while costing it at size class 3 (*Large Commercial, 101–2,000 kW*)
at $1,920/kW. 25 kW belongs in class 2 (11–100 kW) at $2,232/kW — a **16% cost
understatement** for the recommended system. The tool detects the inconsistency and warns,
but leaves resolution to the user rather than re-solving.

### The tool cannot run a site outside the United States

Controlled experiment, everything identical except the site:

| Run | Site | Result |
|---|---|---|
| P1 | Golden, CO | **completed** — PV 767 kW, genset 1,750 kW |
| P2 | non-US coordinates | **"Julia server is down"** |

Three separate Yemen submissions failed the same way. The geocoder accepts a foreign
address and the form validates, but the backend fails every time. The likely cause is that
its lat/lon-keyed datasets (AVERT, Cambium, EASIUR, the ASHRAE-zone city lookup) have no
coverage outside the US — *that part is inference; the failure is reproducible.*

## 4.2 Hidden defaults the UI never shows

Every PV and Battery cost box is **empty by default**. Whatever the user does not type
comes from `electric_storage.jl:225-265`:

| Julia default | Value | Consequence if left blank |
|---|---|---|
| `installed_cost_constant` | **$222,115** | A fixed six-figure charge for *any* battery. It appears nowhere in the UI. |
| `installed_cost_per_kw` / `_per_kwh` | $968 / $253 | |
| `total_itc_fraction` | **0.30** | 30% ITC applied silently |
| `macrs_option_years` / `macrs_bonus_fraction` | 5 yr / **1.0** | 100% bonus depreciation assumed |
| `soc_min_fraction` | 0.2, but **0.8** if `dispatch_strategy=="backup"` | usable capacity changes 60 pp on a dropdown change |
| `charge`/`discharge_efficiency` | ≈0.9479 each | round-trip ≈ **89.8%** |

Financial defaults (`financial.jl:5-18`) include two that are load-bearing for resilience
and have **no UI control at all**: `value_of_lost_load_per_kwh = 1.00` — the entire price
of unserved energy in `ExpectedOutageCost`, which at $1.00/kWh biases resilience runs
toward under-sizing — and `microgrid_upgrade_cost_fraction = 0.0`, which makes islanding
look free.

## 4.3 `dispatch_strategy` does not match between UI and REopt.jl

The UI sends `cost_optimal`. REopt.jl accepts only
`["optimized", "peak_shaving_look_ahead", "peak_shaving_look_behind", "self_consumption",
"backup", "custom_soc"]` (`electric_storage.jl:261`, hard throw at `:359-360`), and
`grep -rn "cost_optimal" src/` returns nothing. Yet a run submitting `cost_optimal`
completed — so an intermediate API layer, not present in this workspace, rewrites
`cost_optimal` → `optimized`. **Anyone calling REopt.jl directly with a value copied from
the web UI will hit a hard error.**

## 4.4 Off-grid conventions worth knowing

- The web tool pins the off-grid generator to **200% of peak load** ("Peak Load
  Multiplier"), giving 1,750 kW for an 875 kW peak. **No such rule exists in REopt.jl** —
  it is a tool-side convention.
- The solver optimality tolerance varies by run and is echoed in the Inputs drawer: 5% on
  one off-grid run, 0.1% on the PT2 grid-tied run. At 5%, two quite different designs can
  be indistinguishable to the tool.

## 4.5 Scope and honest limits of the source citations

1. **The deployed backend version is unverified.** The local tree is v0.61.1; the tool
   exposes no version endpoint. Line citations describe *the local copy*.
2. **The API translation layer is absent from this workspace.** Where a mapping is
   claimed it is inferred from matching field names and confirmed defaults — except
   §4.3, which is *provably* performed by that missing layer.

---

# Part 5 — Grid-tied vs off-grid

Same site (Golden CO, Large Office 5 GWh, 5 acres, 25 yr @ 8.3%), run both ways.

## Three UI restrictions, all verified experimentally

1. **Prime Generator and CHP are mutually exclusive** grid-tied — ticking either sets
   `disabled=true` on the other, verified in both orders.
2. **Backup Generator only exists when Resilience is enabled** — with Cost Savings alone
   the checkbox is absent from the DOM. So "generator + CHP" grid-tied requires Resilience,
   which reproducibly fails (Part 4.1).
3. **CHP is not offered off-grid** — `run_analyze_chp` is removed from the DOM entirely.

The closest achievable pair is therefore CHP + Battery + PV (grid-tied) and
Generator + Battery + PV (off-grid).

## Results

| Metric | Grid-tied (BAU → optimized) | Off-grid |
|---|---|---|
| PV | 0 → **165 kW** | **833 kW** |
| Battery | 0 → **78 kW / 171 kWh** | **346 kW / 1,939 kWh** |
| Fuel tech | CHP **0 kW** | Generator **2,705 kW** |
| Year-1 utility cost | $511,882 → $480,890 | n/a — no tariff collected |
| Life cycle cost | $5,079,767 → **$5,056,559** | **$11,131,414** |
| Levelized cost of energy | ≈$0.102/kWh delivered (BAU) | **$0.214/kWh** |
| Diesel | — | **296,250 gal/yr** |
| Renewable electricity | 5% | 23% |
| Solve time | ~70 s | **~260 s** |

**CHP sized to 0 kW** — a legitimate optimizer result, not a failure: at $8.00/MMBtu gas
against this tariff it cannot beat grid purchase. Grid-tied savings split almost evenly
between energy ($15,263) and demand ($15,729) charges, the demand half being the battery
earning its keep on a B-TOU rate.

Islanding this site costs roughly **2.1× the grid-tied delivered cost**. Diesel dominates:
**$6.18 M of the $11.13 M life-cycle cost is generator fuel** (56%) against $4.31 M for all
capital, which is why renewable penetration lands at only 23% despite 833 kW of PV.

## Structural differences off-grid

- **No business-as-usual column** — the drawer is *"Results Summary"*, not *"Results
  Comparison"* (`reopt.jl:117`).
- **No utility panel at all** — `ElectricTariff` "cannot be supplied when
  `Settings.off_grid_flag` is true" (`electric_tariff.jl:45`).
- **Operating-reserve inputs appear** — `min_load_met_annual_fraction` and
  `operating_reserve_required_fraction` for load and PV. The results confirm the
  constraint binds: 772,383 kWh provided against 768,828 kWh required.
- **~3.7× slower**, consistent with off-grid being a year-long outage — every time step
  is a `time_steps_without_grid` step.

Raw captures: [`reopt_test_data/gridtied/results.md`](reopt_test_data/gridtied/results.md)
(36 KB) · [`reopt_test_data/offgrid/results.md`](reopt_test_data/offgrid/results.md) (18 KB).
The **Defaults** drawer is the useful one for auditing — 21,454 characters of backend
assumptions the form never shows.

---

# Part 6 — CHP and Prime Generator

Two mirrored runs, one per fuel-fired technology. Golden CO, Large Office 5 GWh,
Intermountain REA B-TOU, PV $1,600/kW max 2,000, Battery $300/kWh $850… $800/kW max 4,000,
25 yr @ 8.3%, escalation 1.7%, fuel $8.00/MMBtu.

REopt runs: **G1 CHP** `7afae73e-2c85-40d3-aa77-2036a4cbaa78` ·
**G2 Prime Generator** `8100e6cc-52ff-4e74-829a-b9b70c36de82`.

| Row | G1 REopt | G1 ours | G2 REopt | G2 ours |
|---|---:|---:|---:|---:|
| PV Size | 165 kW | 165 kW | 165 kW | 165 kW |
| Battery Power / Capacity | 78 kW / 171 kWh | 78 / 171 | 78 kW / 171 kWh | 78 / 171 |
| CHP / Prime Generator Size | **0 kW** | **0 kW** | **0 kW** | **0 kW** |
| Heating System Fuel Used | 5,266 MMBtu | 5,266 | — | — |
| Heating System Fuel Cost (lifecycle) | $454,883 | $454,883 | — | — |
| Total Life Cycle Costs | $5,056,559 | $5,056,559 | $4,601,676 | $4,601,676 |
| Net Present Value | $23,207 | $23,207 | $23,207 | $23,207 |

**20/20 rows match** (G1 11/11, G2 9/9). Largest deviation is NPV at −0.13%, the difference
of two ~$5 M numbers that each agree to better than 0.001%.

Both technologies size to **0 kW**. At $8.00/MMBtu with 35.55% electric efficiency the recip
engine burns ~$0.077/kWh of gas before any capital or O&M, against a blended utility energy
rate below that. The two scenarios' life cycle costs differ by exactly **$454,883** — the
existing boiler's lifecycle fuel bill, which REopt only models when CHP is on the scenario.

## What had to be built to make this match

1. **The existing boiler.** Selecting CHP makes REopt model the site's heating system, and
   its fuel cost enters both BAU and optimized LCC. The load is reproducible exactly from
   the tables REopt ships: space heating 5,027.88 + domestic hot water 238.57 =
   **5,266.45 MMBtu** of fuel, × 0.80 boiler efficiency = 4,213.2 MMBtu thermal. Both match
   the tool to the digit.
2. **A separate boiler escalation rate** — `existing_boiler_fuel_cost_escalation_rate_fraction
   = 0.0348` (`financial.jl:7`), not the electricity rate. That single constant reproduces
   $454,883.
3. **A thermal balance in the MILP** — `boiler_thermal + chp_thermal == thermal_load`, with
   recovered CHP heat capped by the engine's thermal/electric efficiency ratio.
4. **Prime Generator separated from the off-grid Generator** — REopt's Prime Generator is
   the gas recip engine priced in $/MMBtu (the same `chp_defaults.json` size-class-0 engine
   as CHP, minus heat recovery); the off-grid Generator is diesel priced in $/gallon.

---

# Part 7 — Off-grid CHP

## Why the web tool hides it

A **front-end restriction only**. REopt.jl allows it explicitly:

```julia
# REopt/src/core/scenario.jl:85
offgrid_allowed_keys = ["PV", "Wind", "ElectricStorage", "Generator", "CHP",
                        "Settings", "Site", "Financial", "ElectricLoad",
                        "ElectricTariff", "ElectricUtility"]
```

and there is off-grid-specific CHP machinery that would otherwise be dead code —
`techs.jl:232-237` sorts CHP into `requiring_oper_res`/`providing_oper_res` only when
`off_grid_flag`; `operating_reserve_constraints.jl` §5c is written for `p.techs.chp`;
`chp.jl:315-323` accepts `operating_reserve_required_fraction` *only* off-grid;
`chp_constraints.jl:156` switches the min-turndown window on `off_grid_flag`.

The block is in the UI: the captured `offgrid` config offers Generator, Battery, PV, Wind
and CST, and contains **0** fields with `chp` in the id against 53 in the grid-tied CHP
config. There is not even a hidden input to submit.

**Their reason is sound.** Off-grid forbids every heating key, so REopt builds CHP
electric-only there — `scenario.jl:531` says so in a comment. An off-grid "CHP" has no heat
to recover, which makes the name misleading and leaves fuel type as the only thing
separating it from the off-grid Generator.

## What was implemented

Additive and gated on `off_grid_flag`, so no grid-tied behaviour could change:

| Change | Where |
|---|---|
| CHP and Prime Generator offered off-grid, labelled as unavailable in the web tool | `streamlit_app.py` Step 4 |
| One fuel-fired tech at a time (the model has a single `fuel_tech` slot) | `streamlit_app.py` |
| Off-grid forces electric-only: no boiler panel, no thermal efficiency, no heat credit | `streamlit_app.py`, `model.py` |
| `chp_defaults()` — the real recip-engine defaults | `reopt_core/defaults.py` |
| Operating-reserve constraints, off-grid only | `reopt_core/model.py` |
| Load and PV operating-reserve inputs | `streamlit_app.py` |
| `custom_normalized_flatload()` — the five procedural FlatLoad shapes | `reopt_core/data_sources.py` |

Grid-tied regression after the change: **TC1 21/21, TC2 15/15, G1/G2 20/20 — unchanged**.
Off-grid CHP runs end to end in the UI and sizes to **862 kW** (PV 833 kW, battery
453 kW / 1,955 kWh) — economic off-grid, unlike grid-tied where it was 0.

## Off-grid validation

REopt run `431b38d4-8d87-448c-a483-a4c6f9826116` — off-grid, Golden CO, `FlatLoad_8_7`
@ 2,555,000 kWh, 10 years, tool defaults.

| | REopt | ours, PV free | ours, PV pinned to 767 kW |
|---|---:|---:|---:|
| PV Size | 767 kW | 1,096 kW | 767 kW |
| Generator Size | 1,750 kW | 1,750 kW (pinned) | 1,750 kW (pinned) |
| Total Life Cycle Costs | $4,224,458 | $4,208,338 | **$4,221,096 (−0.08%)** |

**At a matched design point our engine reproduces REopt's off-grid life cycle cost to
−0.08%.** The sizing difference is worth $12,757 — 0.30% of life cycle cost — and that run
was solved at a **5% optimality tolerance**, so the two designs are indistinguishable to
the tool. The cost surface is simply flat in PV size for this scenario.

Operating reserve is now implemented (10% of served load, 25% of PV output). For that run
it is not binding — the pinned 1,750 kW genset has ample headroom — which is why it did not
move the numbers. It binds when the fuel tech is small.

---

# Part 8 — Field use: the Sana'a vendor proposal

A 29-page turnkey proposal by **Sunwoda** (via Guangzhou Jiancheng International Energy,
cert. SUN-SES-001) for a clean-workshop factory in Bani Mattar District, Sana'a, Yemen
(15.2811 N, 44.0811 E). Full text: [`vendor_analysis/vendor_deck.txt`](vendor_analysis/vendor_deck.txt).

| | |
|---|---|
| PV | ≥ 1,500 kWp N-type TOPCon, 580 Wp, fixed tilt ~15°, ~8,500 m² — $597,000 |
| Battery | ≥ 3,132 kWh — twelve 261 kWh LFP cabinets, 12 × 125 kW grid-forming PCS — $613,300 |
| Diesel | 1,000 kW containerized prime-power set — $306,500 |
| DVR | 800 kW / 375 kWh voltage restorer, ≤ 5 ms transfer, 20 min ride-through — $259,500 |
| Load | 650–700 kW over 10 working hours, ≥ 7,000 kWh/day |
| Total | equipment $2,161,900 + ~10% margin = **$2,361,900** |

The engineering content is serious — five weather-condition dispatch strategies, five fault
modes, black start, morning-inrush sequencing, a full BOM, and a risk register that
correctly names heat, sandstorms, diesel supply and local O&M capability. The weakness is
four paragraphs of economics on page 27.

**Verdict: the project is worth doing; the vendor's case for it is overstated, and their
design is not the cheapest way to get there.**

## Claims checked

| Claim | Deck | Computed | |
|---|---:|---:|---|
| Solar yield | 1,825 kWh/kWp/yr | 1,847 | **verified** — conservative by 1.2% |
| Diesel avoided | 3,000,000 L/yr | 697,889 | **4.3× overstated** |
| CO₂ avoided | 8,000 t/yr | 1,882 | **4.3× overstated** |
| Annual saving | $711,750 | $582,491 | 22% overstated |
| Simple payback | 3.3 yr | 4.05 yr | broadly right |

The diesel figure is the serious one. The site consumes 2,555,000 kWh a year; a genset at
32.2% HHV efficiency burns about 0.29 L/kWh, so running the *entire* site on diesel takes
**737,988 L** — the physical ceiling on what any solar project here can displace.
3,000,000 L would require 10.5 GWh, four times the factory's total consumption. The CO₂
figure derives from the same litres and inherits the same error.

The saving is overstated because it assumes every PV kWh displaces diesel. It cannot:
2,737,500 kWh of generation against 2,555,000 kWh of load, concentrated in daylight hours,
means surplus — our dispatch curtails **9.6%** in the vendor's own design. The deck concedes
this under Condition 1 ("MPPT curtailment reduces PV output") but never carries it into the
economics.

There is no discount rate, no fuel escalation, no O&M, no replacement and no life-cycle cost
anywhere in the document. The battery is also specified inconsistently: p. 6 says "two PCS
cabinets of 750 kW total", p. 10 and the BOM say twelve × 125 kW = 1,500 kW.

## Re-optimized at their own prices

| | Vendor design | Least-cost | Diesel only |
|---|---:|---:|---:|
| PV | 1,500 kW | **1,606 kW** | 0 |
| Battery | 1,500 kW / 3,132 kWh | **696 kW / 1,453 kWh** | 0 |
| Diesel genset | 1,000 kW | **523 kW** | 962 kW |
| Upfront capital | $1,516,800 | **$1,084,160** | $295,003 |
| 10-yr life cycle cost | $2,213,003 | **$1,725,402** | $5,562,176 |
| LCOE | $0.087/kWh | **$0.068/kWh** | $0.218/kWh |

**$487,601 cheaper over ten years (−22.0%) and $432,640 cheaper upfront.** More PV, less
than half the battery: at $195.82/kWh the 3,132 kWh cabinet bank is an expensive way to
cover evenings when a small genset must exist for reliability regardless.

**Caveat in the vendor's favour:** REopt sizes a genset on energy, not motor inrush. The
deck computes a worst-case start peak of 1,200 kW (300 + 300 + 600) and sizes 1,000 kW
against it — a real constraint the optimizer cannot see. REopt's own tool pins off-grid
gensets to 200% of peak load, which here would be 1,750 kW, *larger* than the vendor's.
**Do not read 523 kW as a recommendation to buy a 523 kW genset.**

## Diesel-price sensitivity

The whole case rests on diesel at $0.26/kWh (~$0.90/L). Yemen's supply is unstable — the
deck's own risk register says so, and then tests it nowhere.

| Diesel | $/kWh | PV | Battery | Genset | 10-yr saving vs diesel-only |
|---:|---:|---:|---:|---:|---:|
| $0.45/L | 0.130 | 1,398 kW | 1,070 kWh | 608 kW | $1,448,512 |
| $0.70/L | 0.202 | 1,497 kW | 1,241 kWh | 570 kW | $2,761,844 |
| **$0.90/L** | **0.260** | **1,606 kW** | **1,453 kWh** | **523 kW** | **$3,836,009** |
| $1.20/L | 0.347 | 1,710 kW | 1,758 kWh | 467 kW | $5,483,276 |
| $1.60/L | 0.462 | 1,792 kW | 1,990 kWh | 425 kW | $7,709,254 |

Strongly positive across the whole range — but the **optimal battery size varies by 1.9×**,
which is exactly the decision the vendor fixed by assertion.

## What each side offers

**This analysis adds:** least-cost sizing instead of assertion; life-cycle economics;
8,760-hour dispatch instead of five hand-written weather conditions; falsifiable arithmetic;
sensitivity on the one input the case depends on; load-shape bracketing (10 h/day sits
between the 8 h and 16 h standard shapes — the 16 h case moves the optimum to
1,726 kW / 3,519 kWh, closer to theirs, so the load shape should be measured, not assumed);
and the ability to model a Yemeni site at all.

**The vendor has, and we do not:** power quality — the DVR (±5%, ≤ 5 ms, 20 min
ride-through) and SVG address the actual reason this factory needs a microgrid, and REopt
has no concept of voltage quality; grid-forming PCS and black start; motor-start inrush; a
real bill of materials, fire suppression, C4 corrosion protection, liquid cooling above
45 °C ambient, Modbus TCP / IEC 61850 / OPC UA integration, and a 20–30 week schedule.

**These are complementary, not competing.** Keep their electrical architecture; challenge
their sizing and their economics.

## Method

Load modelled as `FlatLoad_8_7` at 2,555,000 kWh/yr (7,000 kWh/day × 365); the 16 h shape
is the other bound. The battery is priced entirely per-kWh with a 2.088 h minimum duration
because the vendor sells an indivisible 125 kW / 261 kWh cabinet — without the duration
floor the optimizer buys power the cabinet price does not charge for. Diesel at $3.41/gal
is *derived* from the deck's own $0.26/kWh at 32.2% HHV and 40.7 kWh/gal. No ITC, no MACRS,
no tax shield — none of the US tax code applies in Yemen.

Reproduce with `python calculator/tools/yemen_case.py`; raw output in
[`vendor_analysis/yemen_runs.json`](vendor_analysis/yemen_runs.json).

---

# Part 9 — Bugs found and fixed

Every one of these was found by a numeric mismatch against a real REopt run.

| Bug | Symptom | Fix |
|---|---|---|
| **TOU demand billed annually** | $17,657 vs REopt's $193,252 | URDB TOU demand is billed **every month** against that month's peak in each period — 24 ratchets = 12 months × 2, not one per year. Exact match after. |
| **Battery O&M basis** | Life-cycle savings negative (−$68,470); PV oversized 220 vs 165 kW | `ElectricStorageCapCost` is the **full initial cost basis** including the constant (`reopt.jl:422-433`), not the kW term alone |
| **Storage cost constant unconditional** | Same | Must sit behind the `binIncludeStorageCostConstant` binary (`storage_constraints.jl:151`) |
| **PV O&M 18 vs 20** | Contributed to the same sizing gap | Size-class 3 default is $20/kW-yr |
| **`net_metering_limit_kw` as a hard PV cap** | V1 gave 3/6 | It caps capacity that may **participate** in net metering, not system size — REopt returned 1,200 kW under a 1,000 kW limit. Removed → 6/6 |
| **Missing required NEM field** | Form rejected | Selecting net metering opens a **required** "Net metering system size limit (kW)" |
| **Health cost escalation averaged separately** | Health cost 8.7% low | Health factors fall while their $/tonne rises — both rates go into one `annuity_two_escalation_rates` (`utils.jl:21`), not two steps |
| **Hardcoded EASIUR values** | Phoenix health cost −30% | Fetch per-coordinate from `/tool/emissions-health-defaults` |
| **IRR on a zero system** | 450.5% | Return 0 when initial capital ≈ 0 |
| **Building type silently defaulted** | Ran as Hospital | REopt ships a blank default for that required field; `index=None` + placeholder + disabled run button |
| **Prime Generator priced as full CHP** | Invisible (tech sized to 0) | `chp.jl:419-421` scales `installed_cost_per_kw` and `om_cost_per_kwh` by **0.75** for an electric-only unit — $3,382.50/kW, not $4,510 |
| **CHP missing its MACRS** | Invisible (tech sized to 0) | The captured spec ships CHP with 5-yr MACRS / 100% bonus and Prime Generator with none; we applied none to both |
| **No operating reserve off-grid** | PV +42.9%, diesel −26.3%, capital +22.5% vs REopt | Ported `operating_reserve_constraints.jl`, gated to off-grid |
| **Stale module after edit** | `ScenarioInputs.__init__() got an unexpected keyword argument` | Streamlit reloads the script but not imported modules — added a filtering guard with a clear "restart Streamlit" message |

Two harness bugs are worth recording because they produced convincing-looking wrong
answers:

- A Playwright selector `"O&M cost"` matched the Financial panel's **O&M escalation rate**
  and set it to 20%/year, which correctly made the optimizer refuse to build PV. The app
  was right; the test was wrong.
- The REopt address autocomplete once resolved "Sana'a, Yemen" to **Morocco** (34.02 N,
  −4.97 E). All site scripts now verify the resolved coordinates before submitting.

---

# Part 10 — Known gaps

Stated plainly, without softening:

- **PV size-class piecewise cost curve** is not ported — a single `$/kW` is an
  approximation. This is the cause of V4's +23% PV.
- **Payback / IRR / PV LCOE** run 1–4% off in TC1 (9.28 vs 9.15 yr, 9.3% vs 9.5%,
  $0.070 vs $0.067) because of ITC timing inside the proforma.
- **On-site fuel-burn emissions** are not modelled (always 0). Irrelevant for PV+battery,
  relevant for generator and CHP scenarios.
- **Generator/CHP minimum turndown** binaries are not modelled (`recip_engine` is 0.25,
  applied across all 8,760 hours off-grid). Implementing it needs 8,760 binaries and a much
  slower solve. Off-grid CHP results are slightly optimistic on that account.
- **Breakeven Cost of CO₂e** is not computed (Percent Reduction is).
- **Not ported at all:** net-metering export bins, tiered energy rates, the
  `ElectricUtility` export structure, EV load, renewable-energy targets
  (`renewable_energy_constraints.jl`), Wind, CST, GHP, ASHP, absorption chillers,
  steam turbines.
- `include_climate_in_objective` / `include_health_in_objective` remain **false** (the
  tool's own default), so emissions are **displayed but not optimized**.
- **Result-card icons** are absent. Material Symbols `@import` did not load, inline `<svg>`
  is stripped by `st.html`, and a CSS `data:` URI kills the whole `<style>` block. Accepted.
- The **CHP dispatch physics was never exercised** in G1/G2 — both sized to 0 kW, so
  turndown, unavailability periods and part-load efficiency were not tested there.

---

# Part 11 — The profiling view

The results page ends in a dispatch profiling block: a stacked supply chart, a statistics
strip, and a set of tables at three time scales. It is the same visual language as the
reference profiling artifact (`bess_profile_v2.jsx`), rebuilt in Streamlit so the two read
as one product.

## The design, as measured

Every value below was taken from the reference and verified in the browser with
`getComputedStyle` after the page rendered, not merely written into a stylesheet:

| Element | Specification | Measured |
| --- | --- | --- |
| palette | paper `#EEF1F4`, panel `#FFFFFF`, ink `#17242F`, muted `#5C6B79`, rule `#CBD5DC` | same |
| charge / discharge | `#1F7A8C` / `#C2571A` | same |
| ceiling / saving | `#8A97A3` / `#3F8F5C` | same |
| unit colours | `#46617F`, `#7C6E9B`, `#A8845C`, then three harmonised hues before wrapping | same |
| table header | mono 10.5px, muted, uppercase, letter-spacing .06em, padding 7px 9px, right-aligned except the first column, 1px rule under | 10.5px, `rgb(92,107,121)`, uppercase, 0.63px, `7px 9px` |
| table body | mono 12px, ink, padding 5px 9px, tabular figures, first column muted | 12px, `5px 9px`, `tabular-nums` |
| row wash | every second row `rgba(23,36,47,0.022)` | `rgba(23,36,47,0.024)` (browser rounding) |
| total row | 1px solid ink above, weight 600 | `1px` `rgb(23,36,47)`, `600` |
| section row | ink, weight 600, uppercase, letter-spacing .06em | same |
| panel title | Inter 19px, weight 650, letter-spacing -0.015em | same |
| stat cell | label mono 10.5px uppercase .07em muted; value mono 15px ink | same |
| switch | mono 12px, letter-spacing .04em, padding 9px 18px, square, active = ink fill | `12px`, `9px 18px`, `0px` radius |

The switch styling is scoped with a marker span and an adjacent-sibling rule, so steps 1–5
keep the REopt-orange Streamlit styling and only the profiling switches change: measured on
the live page, the four form controls still read Roboto 14px with 6px/9999px radii while the
two profiling switches read mono 12px with square corners.

## The hover panel

The reference is Recharts, where one `<Tooltip>` serves a whole category: point anywhere in
an hour's column and a single panel names every series at once — the load, the fleet, each
engine with its share, the battery, the grid, the units running, the state of charge, the
starts, the money. That panel is most of what the chart is for, so it was rebuilt exactly.

Three things had to be solved, none of them obvious.

**One panel for the column, not one per mark.** Vega-Lite gives the tooltip to the topmost
mark under the pointer, so a stacked bar answered with its own three fields and the full
panel appeared only if the pointer found the 1.6px load line. The fix is the shape Recharts
draws anyway: a transparent rect per hour, spanning the plot from `bot` to `top`, laid over
every other layer. It takes the pointer wherever in the column it is and carries the hour as
one tooltip object. A point selection on it (`on="pointerover"`, `clear="pointerout"`) then
drives two more things for free — the column washes `rgba(23,36,47,0.05)` under the pointer,
which is Recharts' `cursor`, and the hovered hour's marker fills in and swells, which is its
`activeDot`.

**The panel is plain text.** vega-tooltip escapes what it is given and builds a fixed
`<h2>` plus `<tr><td class="key">…<td class="value">` table, so a mark cannot colour its own
row and no class can be attached to one. What is fixed is the order: rows come out in the
order of the tooltip channel, identically for every hour. So the rows are addressed by
position — one `tr:nth-child(k) td.value { color: … }` rule per row, written next to the
chart from the same `(label, text, colour)` list that fills it. This is why a row that does
not apply carries an em dash instead of disappearing, as it does in the reference: a table
that reflowed under the pointer would break both the colours and the reading. The one field
named `title` becomes the heading — that is vega-tooltip's own rule, not a trick.

**Streamlit styles it first.** Streamlit ships vega-tooltip's stylesheet and its own theme
on top, both from the document head, and both address the cells as `#vg-tooltip-element
table tr td.value`. The old sheet said `#vg-tooltip-element table td.value` — one element
short, so it lost, and their `display: block; text-align: left; -webkit-line-clamp: 5` won:
the figures sat under their labels instead of forming a column. Repeating their exact
selector is enough, because this sheet is in the body and wins on document order.

Measured on the live page with `getComputedStyle`, hovering hour 08:00 of the JSX case:

| Element | Specification | Measured |
| --- | --- | --- |
| panel | white, 1px rule `#CBD5DC`, square, padding 10px 12px, mono 12px | `rgb(255,255,255)`, `1px solid rgb(203,213,220)`, `0px`, `10px 12px`, `ui-monospace`, `12px` |
| heading | mono 12px, weight 600, letter-spacing .04em, 1px rule under | `12px`, `600`, `0.48px`, `1px solid rgb(203,213,220)` |
| label cell | muted, left, `white-space: pre` so the per-unit rows keep their indent | `rgb(92,107,121)`, `left`, `pre` |
| figure cell | table-cell, right, tabular figures, no wrap | `table-cell`, `right`, `tabular-nums`, `nowrap` |
| row | line-height 1.7 | `20.4px` on 12px |
| table | 230px floor | `230px`, drawn at 262px for a 12-row panel |

The figures wear their series' colour: ink for the load, muted for the fleet total and the
counts, each engine its own bar colour, teal for charge, peach for discharge and starts,
grey for the grid. The two money rows are the one departure from the reference. It colours
them green because it colours each figure as it writes it, so a negative hour comes out
peach; here the colour is fixed per row and cannot follow the sign, and a loss printed in
green would be a lie. They stay in ink, carry their own `+`/`−`, and the veil under the load
line is green or peach for that same hour.

**A trap worth naming.** `st.html` sanitises the string it is given, and one HTML tag
anywhere in it — even inside a CSS comment — costs the whole `<style>` block silently. A
comment that mentioned `<h2>` while explaining the heading rule deleted the entire profiling
stylesheet; the page still rendered, just undesigned. There are no tags in that file now and
a note in it says why.

## The axes

Matched to the reference in the same pass: no tick marks on either axis, a rule under the
hours and none beside the kW, a grid of horizontal dashes 2 on 4 off in the rule colour, and
hours labelled from the first (1, 3, 5 …) rather than the second. The chart is 380px for a
day and 420px for a week, as the reference sizes it. The saving veil now draws beneath the
bars with straight edges: its area times the price spread is the money, so the smoothing
curve it had been given was quietly misstating it.

## Dynamic asset variability

Nothing in the block is written for a fixed number of machines. `_shape()` reads the solved
result once and everything else loops over what it found:

```python
units  = [u for u in sizes["fueltech_units"]  if u["size_kw"]    > 1e-6]
banks  = [b for b in sizes["storage_units"]   if b["energy_kwh"] > 1e-6]
series = [series["fueltech_unit_kw"][u["name"]] for u in units]
```

- **Columns** — the hourly header is `HOUR · LOAD · ⟨one column per unit⟩ · PV · CHARGE + ·
  DISCHARGE − · GRID · SOC %`, plus `SPILL`, `EXPORT` and `UNSERVED` only when the run has
  them. Three engines give three columns; six give six.
- **Chart series** — one stacked bar series per unit, colour by index through the palette,
  then PV and grid; the battery is a signed bar offset beside the stack, as the reference
  groups them.
- **Headline** — `3 × CHP` with `Engine 1 300 + Engine 2 300 + Engine 3 300 = 900 kW`, built
  from the fleet, and the dashed ceiling line is the sum of the nameplates.
- **Per-unit tables** — one row per generator and one per battery, each with a fleet/bank
  total row.
- **Stat strip** — battery cells appear only with a battery, the fuel cell only with a
  fuel-fired unit; the strip stays six wide.

## Field-by-field against the reference

The reference's per-hour row is `[load, chp, ch, dis, soc%, grid, starts, uon, spill]`.
Each field was checked against what this block renders, and the gaps closed:

| Reference field | Here | Note |
| --- | --- | --- |
| `load` | `LOAD` | same |
| `chp` | one column per unit, plus `Fleet output` in the hover panel | finer than the reference, which prints the fleet total |
| `ch` / `dis` | `CHARGE +` / `DISCHARGE −` | prints a figure, and `−` on discharge, as the reference does |
| `soc` | `SOC %` | stored as kWh, shown as a share of installed capacity |
| `grid` | `GRID` | same |
| `starts` | `STARTS` on the weekly table, `Starts this hour` in the hover panel | same |
| `uon` | `ON` | added; was missing |
| `spill` | `SPILL`, per unit in the result | same |
| — | `PV`, `EXPORT`, `UNSERVED` | this model has them, the reference has no PV and no unserved load |

Tables:

| Reference | Here |
| --- | --- |
| `dayTable` — `Час, Нагрузка, …names, Заряд +, Разряд −, Сеть, SoC %` | same order, plus `PV`, `ON` and the optional columns |
| `weekTable` — same, then `Пик, Пусков` | same, plus end-of-day `SOC %` |
| `hourWeekTable` — `День, Час, …` | same; `DAY` and `HOUR` are separate columns, as there |
| `summaryTable` | transposed, see below |
| `Profiles` — eight load archetypes | not carried; it is a property of that study, not of one REopt run |

The summary is the one table that could not be copied. The reference puts the three
*scenarios* (A/B/C) in the columns and the three time scales in section rows; this
calculator solves one scenario, so the time scales take the columns and the metrics are
sectioned instead. Its metric list was then brought up to the reference's:

| Reference metric | Here |
| --- | --- |
| Нагрузка завода / Выработка КГУ / Заряд / Разряд / Закуп | already present |
| Пик закупа | already present |
| Пусков | `Starts` — added |
| Сброс | `Spill (kWh)` — added |
| Моточасы парка | `Fleet running hours` — added |
| Доля сети, % | `Grid share of load (%)` — added |
| Полных циклов BESS | `Battery full cycles` — added |
| Поправка на SoC | `Battery SOC carried (kWh)` — added, see below |
| Топливо и O&M / Пуски / Износ ячеек, ₸ | not carried: those are the reference's flat tenge tariff model. The cost row here is the tariff energy charge this calculator actually computes |
| Экономия и окупаемость к A / к B | not carried: they are differences between that study's three scenarios |

### The SoC correction is structurally zero over a year

The reference carries a `поправка на SoC` because a window that ends fuller than it started
has been subsidised by stored energy — in its own annual figures that correction is
183,939 ₸, so its battery does not close the loop.

Here the storage balance wraps:

```python
# reopt_core/model.py:472
prev = bsoc[b][T[-1]] if t == 0 else bsoc[b][t - 1]
m += bsoc[b][t] == prev + charge_efficiency * bchg[b][t] - ...
```

so over the full horizon the battery must return to where it began. Measured on the
rendered summary:

```
  day   SOC carried    +264.1 kWh
  week  SOC carried    −258.1 kWh
  year  SOC carried       0.0 kWh
```

The row is worth showing anyway: inside a day or a week the drift is real, and it says how
much that window is flattered or penalised by stored energy crossing its edges.

### Counters agree with the solver

`test_profile_render.py` asserts that the summary's year column is not an independent
opinion: fleet running hours and starts re-derived from the hourly series must equal what
the model reported in `sizes["fueltech_units"]`, and battery cycles must equal
throughput ÷ installed capacity. All three shapes pass.

## Isolation from the core

`reopt_core/model.py` was not opened for this work. The block reads `res["series"]` and
`res["sizes"]` and sums them; it computes no cost and no energy of its own. The two files
added or changed are `profile_ui.py` (palette, stylesheet, table renderer, chart) and
`app_periods.py` (aggregation and layout); `streamlit_app.py` gained one import and one
`P.inject()` call.

Proof rather than assertion — after the change, unchanged to the dollar:

```
TC1              21/21 checks within tolerance
PT2              22/24 rows; life cycle cost $2,559,867 vs REopt $2,559,868  (−0.000%)
test_periods     all period-view checks passed, single and fleet
```

## Running the reference's own example

`bess_profile_v2.jsx` ships its results inline — a 24-hour day and a 168-hour week for two
fleets under three operating rules — produced by a causal rule-based controller.
`tools/jsx_case.py` reads those rows, poses the identical problem to this MILP at the
artifact's own prices (22 ₸/kWh own generation, 60 ₸/kWh import, 15,000 ₸ per start,
0.5 ₸/kWh cell wear), and puts the two answers side by side.

First, the artifact reconciles with itself. Over all 1,152 published hours the per-unit
columns sum to the fleet column, `generation − spill + discharge + grid = load + charge`
holds to 1 kW, and no hour charges and discharges at once.

| Case | Artifact, ₸ | This MILP, ₸ | Δ |
| --- | ---: | ---: | ---: |
| day, 2 engines, free 50% | 1,492,498 | **1,492,498** | **+0.00%** |
| day, 2 engines, 90% rule | 1,580,284 | 1,563,237 | −1.08% |
| day, 2 engines, 90% + BESS | 1,377,366 | 1,367,502 | −0.72% |
| day, 3 engines, free 50% | 1,348,610 | 1,275,280 | −5.44% |
| day, 3 engines, 90% rule | 1,459,074 | 1,418,074 | −2.81% |
| day, 3 engines, 90% + BESS | 1,315,706 | 1,259,645 | −4.26% |
| week, 2 engines, free 50% | 9,400,780 | 9,346,281 | −0.58% |
| week, 2 engines, 90% rule | 9,952,586 | 9,831,623 | −1.22% |
| week, 2 engines, 90% + BESS | 8,754,845 | 8,655,505 | −1.13% |
| week, 3 engines, free 50% | 8,625,984 | 8,246,715 | −4.40% |
| week, 3 engines, 90% rule | 9,367,890 | 9,157,859 | −2.24% |
| week, 3 engines, 90% + BESS | 8,761,464 | 8,278,228 | −5.52% (MIP gap 0.35%) |

Same constraints and perfect foresight, so each of our costs is a lower bound on theirs; the
difference is what the controller leaves on the table, not a disagreement about physics.

### The one exact match is the useful one

Two engines under free modulation with no battery and no starts: **1,492,498 ₸ on both
sides, and every line item identical to the kilowatt-hour** — generation 49,159, import
6,850, peak 1,839, zero starts, zero spill. When the constraint set leaves no slack, their
controller is already optimal and this engine reproduces it exactly. That is a check on the
whole encoding — fuel cost, turndown, power balance — not just on the total.

### Where the gaps come from

**The 90% rule (two engines, day).** We burn 4,202 kWh *more* and spill 2,627 kWh *more*,
yet pay 17,047 ₸ less:

```
  +4,202 kWh own generation @ 22 ₸   =  +92,453 ₸
  −1,575 kWh import        @ 60 ₸   =  −94,500 ₸
  −1 start                 @ 15,000  =  −15,000 ₸
                                        −17,047 ₸   (matches the reported delta)
```

At a 38 ₸/kWh spread, holding an engine on its 90% shelf and dumping the surplus is cheaper
than topping up from the grid. The causal controller cannot see that trade.

**Three engines.** The peak load is 4,106 kW against 3,367 kW of nameplate, so at least
739 kW must be imported in that hour. We import exactly 739 kW; the artifact imports
1,806 kW — **2.44× the physical minimum** — in both mode A and mode B, because its rule did
not commit the third engine in time. That single hour is most of the 5.4% day gap.

### The same case drawn in our own view

`tools/jsx_render_check.py` solves the artifact's case and renders it through this
calculator's profiling block, then compares the two tables. Structure and values are kept
apart, because our dispatch is deliberately not theirs.

The block had to learn horizons other than a year first: it hard-coded 8,760 hours in the
index, the day scan, the window slice and the summary. `horizon(series)` now drives all of
them, the third summary column becomes `HORIZON, n H` when the run is shorter, the
monthly-peak section is skipped when there are not twelve months to bill, and the battery
table's `/YR` suffix follows the actual horizon. Both year-path validators still pass.

**Structure — every reference column present, in order, in all four checked cases:**

| Reference column set | Ours |
| --- | --- |
| `Час, Нагрузка, Jenbacher, TEDOM, Заряд +, Разряд −, Сеть, SoC %` | `HOUR, LOAD, JENBACHER, TEDOM, CHARGE +, DISCHARGE −, GRID, SOC %, ON` |
| same with `КГУ-3` inserted | same, `КГУ-3` in the same position |
| 24 rows plus a total row | 24 rows plus a total row |

Two deliberate differences. We add `ON`, the reference's `uon` field, which its tables carry
only in the tooltip. And in a scenario with no battery — modes A and B — we do not draw the
three battery columns at all, where the reference prints them as zeros; the artifact always
has a BESS configured even in the runs that do not use it.

**Values — the exact-match case, hour by hour.** Two engines, free modulation, no battery:

```
  load                0.0 kW max difference, 0 of 24 hours differ
  fleet generation    0.0 kW                 0 of 24
  grid purchase       0.0 kW                 0 of 24
  charge / discharge  0.0 kW                 0 of 24
  per-unit split    243.0 kW                 degenerate: the two units are priced alike,
                                             so only their sum is pinned
```

The total row agrees too: load 56,009 kWh and import 6,850 kWh on both sides, and the
per-unit columns differ only in how the identical sum 49,159 kWh is split between two
equally-priced machines.

**Where the schedules differ, the difference is legible.** Three engines, free modulation:
generation and import differ in exactly 3 of 24 hours, by exactly 1,067 kW each time — one
Jenbacher, not committed. That is the whole 5.4% cost gap, visible as three cells.

### The artifact's negative verdict on the battery, re-examined

For three engines the artifact reports that the battery never pays back (`payA: null`). Its
evidence is that mode C costs more than mode A — but that comparison changes two things at
once, the battery *and* the 90% rule. Isolating the battery with mode D (free 50% **with**
the battery):

| Week, 3 engines | ₸ | vs free 50% |
| --- | ---: | ---: |
| A free 50%, no battery | 8,246,715 | — |
| C 90% rule + battery (artifact's comparison) | 8,278,228 | +31,513 |
| D free 50% + battery | **8,137,084** | **−109,631** |

The battery does save money; the 90% rule is what destroys its value. But the saving is
small — extrapolating this week gives about 5.7 M ₸/year against a 391 M ₸ capex, roughly
70 years — because three engines already cover the load with almost no import left to
displace (739 kWh in the whole week). **So the artifact's conclusion for three engines is
right, and its reasoning is not.** For two engines the same isolation gives 727,600 ₸/week,
about 38 M ₸/year and a ten-year payback, consistent with the 9.5 years the twelve-month
decomposition in the CHP+BESS work produced.

```bash
python calculator/tools/jsx_case.py check   # the artifact's own arithmetic
python calculator/tools/jsx_case.py day     # 24-hour case, both fleets
python calculator/tools/jsx_case.py week    # 168-hour case
```

## What is deliberately not carried over

The reference's savings veil and its A/B/C mode comparison need an hour-by-hour baseline to
subtract. This calculator has a business-as-usual case but not an hourly BAU dispatch, so the
veil would have to be invented. It is left out rather than faked. The eight-archetype profile
sweep is likewise a property of that study, not of a single REopt run.

## Render tests

`tools/test_profile_render.py` stubs Streamlit, calls `render_periods` for every switch
position on three solved shapes — one generator, three generators with two batteries, and two
fixed-nameplate engines with turndown, start costs and curtailment — and checks the emitted
HTML: every row as wide as its header, no empty header cell, no cell rendering as `nan` or
`None`, balanced tags, and a chart specification that compiles.

This exists because the `%-d` crash in Part 9 reached the page: the data functions had been
validated and the render path never had been.

---

# Part 12 — CHP and Battery, field for field with the web tool

The earlier CHP and Battery panels were ours, not REopt's. They carried inputs the tool does
not have — a "Part-load behaviour" expander, an "Existing Heating System" panel, editors for
several generators and batteries — and they lacked or mis-modelled a long list of inputs it
does have. Both panels were rebuilt from a live capture, and every input was ported from
REopt.jl so it acts in the model the way it acts in REopt.

## The capture

`reopt_test_data/chp-bess-panels.json` is a Playwright walk of reopt.nlr.gov/tool on
2026-09-18 (grid-tied, CHP + Battery, Golden CO, Hospital electric and heating load,
$8/MMBtu): every visible heading and control of each panel in DOM order, once collapsed
and once with "Advanced inputs" open, plus every field a checkbox reveals.

| Panel | Visible | Under "Advanced inputs" | Revealed by a checkbox |
| --- | ---: | ---: | --- |
| Battery | 8 | 19 | hourly SoC upload (Custom hourly state of charge) |
| CHP | 13 | 31 | existing size + net/gross load; single $/kW; custom schedule / generation profile |
| Utilities | Fuel Costs: 6 | CHP standby charge | 12 monthly prices, twice |
| Load Profiles | heating load: 10 | — | space heating / hot water split; process heat |
| Financial | 2 escalation rates | — | — |

REopt does not keep these inputs together, and neither does the calculator any more: fuel
prices sit under **Utilities**, the heating load under **Load Profiles**, fuel escalation
under **Financial**, and only the equipment under **Battery** and **Combined Heat & Power** —
in that order, as on the site. Every input starts blank with the tool's default as its
placeholder; blank means "use the default", exactly as on the site.

## What was wrong, and what REopt actually does

| Input | Before | REopt (and now here) |
| --- | --- | --- |
| CHP size class, costs, efficiencies, min size, turndown, max size | size class 0 always: $4,510/kW, 35.55% | chosen from the average boiler fuel load (chp.jl:479). Hospital, Golden: 170 kW heuristic → reciprocating engine, class 2, 100 kW → $3,920/kW and 250 kW → $3,660/kW, 31.2% / 48.5%, 50 kW minimum, 25% turndown, 341 kW maximum — the tool's own placeholders, reproduced |
| Size-cost pairs and incentives | one $/kW slope, federal ITC only | cost_curve.jl, ported verbatim: piecewise curve with REopt's whole-dollar slope rounding, utility → state → federal incentives with caps, one segment chosen by binaries (cost_curve_constraints.jl 7f–7h) |
| Minimum new non-zero size | missing | zero or at least that size — folded into the segments, as REopt does |
| Existing CHP | missing | existing kW sits under the new capacity with no capital cost; a net load is grossed up by its output (reopt_inputs.jl:1258) |
| Heat recovery | **annual** credit: July CHP heat paid down January boiler fuel | **hourly** balance: CHP heat serves that hour's load or is wasted, the boiler makes up the rest, capped at 1.25 × peak |
| Heating load | annual MMBtu only | hourly space heating + hot water from the CRB profiles, addressable share, monthly entry, separate SH/DHW, process heat |
| Thermal efficiency at 50% | missing | affine thermal curve with its own intercept binary (chp_constraints.jl 2a–2c) |
| Maintenance schedule | missing | the prime mover's default periods → 432 unavailable hours in 2017 (utils.jl:349), or an uploaded schedule |
| Custom maximum generation profile | missing | availability = profile × (1 − maintenance) |
| Electrical / heating load-following | missing | ported with their binaries and big-M from chp_constraints.jl |
| Production-based incentive | missing | production_incentive_constraints.jl |
| CHP standby charge | missing | pwf × 12 × rate × size, after tax (reopt.jl:295) |
| CHP fuel escalation | the generic 3.4% | its own 3.48% |
| Fuel prices by month | missing | each hour priced at its month |
| Battery initial state of charge | **ignored** — SoC closed in a loop | SoC before hour 1 = 50% of energy, final SoC free (storage_constraints.jl:48); the loop remains available as REopt's `optimize_soc_init_fraction` |
| Battery rebates, constant replacement | missing | $/kW rebate in the kW cost; constant replaced in its year |
| Battery dispatch strategy | missing | Backup mode → 80% minimum SoC; custom hourly SoC ± 2% |

## Verification

**Fields.** A Playwright walk of the rebuilt panels returns the tool's labels, order,
sections and placeholders: all 27 Battery inputs and all 44 CHP inputs, including both
incentive grids and the maintenance-schedule controls. `tools/test_chp_bess_fields.py`
asserts it against the capture, and asserts every derived default against the site.

**Numbers — REopt run ee53addc (Hospital, Golden, $8/MMBtu, CHP + Battery).** Both sides
build nothing, and the accounting agrees to the dollar:

| | REopt | This calculator |
| --- | ---: | ---: |
| Total life cycle cost | $9,525,566 | $9,525,566 |
| Utility electricity, lifecycle | $8,465,392 | $8,465,392 |
| Heating fuel, lifecycle | $1,060,174 | $1,060,174 |
| Heating fuel, year 1 | $79,254 | $79,254 |
| Heating system fuel / thermal | 9,907 / 7,925 MMBtu | 9,907 / 7,925 MMBtu |
| Existing boiler capacity | 4.7 MMBtu/h | 4.7 MMBtu/h |

**No regression, two improvements.** The initial-SoC fix moved the existing live
comparisons *closer* to REopt:

| Validator | Before | After |
| --- | --- | --- |
| TC1 | 21/21, LCC +$31 | 21/21, **LCC exact**, $4,601,676 |
| TC2 | 15/15 | 15/15 |
| G1 / G2 | 20/20 | 20/20, G2 LCC exact |
| PT2 | 22/24, +$5 | 22/24, −$1 |
| OG1, V1–V4 | −0.08% matched, 27/29 | unchanged |

**A case where CHP is built** (CHP gas $3/MMBtu, battery $150/kWh, $400/kW, no constant):
this calculator sizes CHP at 197.7 kW on the 100–250 kW segment, running 7,974 h around
432 maintenance hours and serving 6,447 of 7,925 MMBtu of heat, with a 726 kW / 2,404 kWh
battery; life cycle cost $8,770,975 against $9,525,566 BAU (MIP gap 0.6% at 900 s). The same
case on the site ran past the tool's default 600-second optimisation timeout and failed, and
after that the site's firewall rejected further automated submissions (see Part 10).

The local REopt.jl (below) solved it: optimal at its 1 % gap after 2,081 s, CHP 208.4 kW,
battery 753 kW / 2,592 kWh, LCC $8,726,006 — ours was 0.52 % above that, inside the 0.62 %
gap our 900-second run still had. To separate the model from the solver, REopt's sizes were
fixed in this calculator and the dispatch solved to a proven optimum:

| Case 2, REopt's sizes | REopt.jl | This calculator |
| --- | ---: | ---: |
| Initial capital (cost curve) | $1,460,253 | $1,460,254 |
| LCC, BAU | $9,525,566 | $9,525,566 |
| LCC, optimal | $8,726,006 | $8,718,424 (−0.087 %) |
| Simple payback / IRR | 7.16 y / 13.1 % | 7.13 y / 13.2 % |

On the same equipment this model finds a dispatch $7,582 cheaper, well inside the 1 %
REopt's run was allowed to stop short by; capital, BAU and the pro-forma agree. The
REopt.jl result is cached, so `tools/chp_bess_reopt_case.py --case=2 --jl` reprints it
without re-solving.

## REopt.jl's own test suite

The site can be checked only one submission at a time, and it rate-limits automated use.
REopt.jl ships its own tests: scenario files in `REopt/test/scenarios` and assertions in
`REopt/test/runtests.jl`, each with the tolerance REopt allows itself.
`tools/test_reopt_jl_suite.py` poses every CHP and Battery test that stays inside this
calculator's technologies (no absorption chiller, cooling or outages) and checks our
result against REopt's expected value at REopt's tolerance. All nine groups pass:

| Group (runtests.jl) | Checked | REopt | This calculator |
| --- | --- | ---: | ---: |
| CHP Sizing Heuristic (217) | heuristic / max kW, two cases | 100 / 200, 65 / 130 | same |
| Heating inputs + CHP defaults (2315) | thermal MMBtu, class-based min size and O&M | 50 kW, $0.027; 125 kW, $0.023; CT 2,000 kW, $0.015 | same |
| Solar and Storage (394) | PV kW, battery kW / kWh, LCC to 1e-5 | 216.67, 49.0 / 83.3, $12,391,786 | 216.67, 49.05 / 83.32, $12,391,786 |
| Storage Duration (4124) | kW × 8 = kWh | 0 | 0 |
| Battery O&M Cost Fraction (4523) | O&M / capital | 0.025 | 0.025 |
| CHP Sizing (1146) | size, LCC | 263 ± 50 kW, $11.1M ± 5% | 264 kW, $11,112,924 |
| CHP Cost Curve and Min Allowable Size (1172) | capex, capex after incentives, size | $3,295,875, $2,636,976, 555.5 | $3,295,912, $2,637,087, 555.5 |
| **CHP Proforma Metrics (1501)** | simple payback | **8.31 ± 0.02 y** | **8.31 y** (IRR 10.5%) |
| CHP Supplementary firing and standby, part 1 (1293) | electric kWh, thermal MMBtu (1e-5), demand cost, heating load | 7,008,000; 29,567.45; 0; 99,864 | same |

Three model corrections came out of it:

* **Land.** A PV size limit from land area was applied on its own; REopt only has a
  `LandConstraint` with concentrating solar. The limit now comes through the PV maximum size
  (roof + land for "both"), and Solar and Storage went from PV 166.67 kW to REopt's 216.67.
* **Climate zone.** The CRB load city is now looked up in `REopt/data/climate_cities.shp`
  first, as REopt does, with the nearest-city rule only as its fallback (outside the US, and
  for Los Angeles, as in REopt). The shapefile is read in pure Python — no GIS package.
* **Payback and IRR.** REopt's pro-forma (`results/proforma.jl`, host-owned) is now ported
  line for line and drives the results page. The previous one priced only the electricity
  bill and O&M; REopt's also carries every fuel stream with its own escalation (CHP fuel,
  existing boiler in both cases), the CHP standby charge, utility → state → federal cash
  incentives, production incentives and battery replacement in its year, and escalates
  year-one values from year 1 onward. The CHP payback test only passes with all of these.
  Against the live tool it now matches too: TC1 and G1/G2 print **9.15 yrs** and **9.5 %**
  on reopt.nlr.gov and here; `validate2.py` and `validate_gen.py` check both rows
  (±0.02 y, REopt's own payback tolerance; ±0.05 % on IRR, which the tool prints to 0.1 %).

## A local REopt.jl as the reference engine

The site rate-limits automated runs and times out at 600 s, so REopt.jl itself now runs
on this machine: Julia 1.10 LTS, the repository's own `REopt/` source (v0.61.1, the code
every port here cites) and HiGHS, in `reopt_jl/`. `tools/reopt_jl.py` takes REopt's own
JSON and returns REopt's results dict, cached per scenario; setup and gotchas are in
CLAUDE.md.

**The install is REopt as its authors test it.** `tools/check_reopt_jl.py` runs REopt's
test scenarios through it and asserts what runtests.jl asserts — all pass — then poses the
same scenarios to this calculator:

| | runtests.jl | REopt.jl (local) | This calculator |
| --- | ---: | ---: | ---: |
| Solar and Storage — PV kW | 216.6667 | 216.6667 | 216.6667 |
| Solar and Storage — battery kW / kWh | 49.0 / 83.3 | 49.05 / 83.32 | 49.05 / 83.32 |
| Solar and Storage — LCC | $12,391,786 | $12,391,786.16 | $12,391,786.16 |
| CHP Proforma — simple payback | 8.31 ± 0.02 | 8.31 | 8.31 |
| CHP Proforma — IRR | — | 10.5 % | 10.5 % |
| Supplementary firing, part 1 — CHP thermal MMBtu | 29,567.45 | 29,567.45 | 29,567.45 |

**The case posed as the site poses it.** `tools/chp_bess_reopt_case.py --jl` writes the
Golden Hospital case as REopt JSON using only what the site's form sends (REopt.jl's
defaults are the web tool's: CHP ITC 0 %, MACRS 5 yr / 100 % bonus, escalations
1.66 % / 3.48 %). Case 1 agrees three ways — site, local REopt.jl and this calculator all
give LCC **$9,525,566** with 9,906.75 MMBtu of boiler fuel — which confirms the JSON
matches the site's inputs.

Fixed along the way:

* **Pro-forma rounding.** REopt rounds the year-one values its pro-forma reads (energy and
  demand to cents, fixed charge and export to dollars, boiler and CHP fuel to 3 decimals,
  generator fuel to cents — results/electric_tariff.jl, existing_boiler.jl, chp.jl). Without
  that, a run that builds nothing carried solver round-off into the cash flows and printed a
  15.3-year payback where REopt prints 0. Now 0 / 0 %, as REopt.
* **Annual electric kWh.** The field was pre-filled with 5,000,000; on the site it is blank,
  and blank means the CRB default for the building in the site's climate zone
  (electric_load.jl:260) — 8,281,865 kWh for a Golden hospital. Now blank with that
  placeholder, as on the site.
* **Size class box.** The disabled prime mover / size class boxes kept the value of their
  first render (class 0) instead of following the heating load; they now show the derived
  class, as the site does.
* **Results Comparison.** The table lumped boiler fuel into "Total Utility Electricity
  Cost". It now carries the site's rows for a heating case — existing boiler capacity, CHP
  production and fuel, heating system production and fuel, year-one and lifecycle fuel
  costs, standby charges, non-outage fuel costs — and case 1 reads exactly as on the site:
  electricity **$8,465,392**, heating fuel **$1,060,174** lifecycle / **$79,254** year one,
  boiler **4.7 MMBtu/hr**. "-$0" and "-0 kWh" no longer print.

## Still open

* PV-only result elements (the PV levelized cost tile, the "PV Serving Load" legend entry)
  still show when PV is not evaluated; the site's behaviour there has not been captured.
* The tool prints the default maximum CHP size as 341 kW in the form and 342 kW in the
  results echo; REopt.jl's arithmetic gives 341.14. It only matters when the optimum sits
  on the maximum.
* Under load-following, REopt charges per-kWh O&M on *rated* production even in maintenance
  hours; here a unit in maintenance is simply off.
* The Emissions panel's CHP fuel factors and on-site fuel-burn costs are not yet on the
  page (they do not enter the objective at the tool's defaults).
* Prime Generator and Generator panels were outside this change and keep their previous
  fields; the multi-unit fleet editors now appear only there. The engine still supports a
  fleet of CHP units and a bank of batteries.

---

# Part 13 — Custom dispatch study (not REopt)

The REopt panels copy reopt.nlr.gov field for field and carry nothing else. Studies like
`bess_profile_v2.jsx` need inputs the web tool does not have, so they have their own
section: the switch at the top of the app reads **REopt tool | Custom dispatch study (not
REopt)**, and the second opens `calculator/app_dispatch.py` behind a banner that says it
is not REopt and cannot be checked against the site.

| Input | What it carries |
| --- | --- |
| Hourly load | CSV / text upload of any length from 24 to 8,760 h (Excel `;` exports with decimal commas, a leading hour column, timestamps are all read), or the JSX's own day and week; a window (start hour, length) |
| Grid price | flat, or an hourly series; any currency label (₸ by default) |
| Fuel-fired units | one row per unit: rated kW, energy cost per kWh (on rated output, spill included), start cost, minimum load %, minimum up / down hours, spill allowed; presets for the JSX's 2- and 3-unit fleets |
| Battery | power, energy, round-trip efficiency, minimum SoC, wear cost per kWh discharged, grid charging, cyclic or fixed starting SoC |
| Scenarios | any number of rows, each solved separately: minimum-load override, battery on / off, **load scale %** — the variability axis; the JSX's A / B / C are filled in |
| Coverage and lifetime | solve the window as posed, or **a year from k typical days** (weighted, k = 12 by default); analysis period, operating-cost escalation and discount rate for the 25-year table |

The engine is the same MILP with the finance switched off (one period, no discounting,
tax or capital cost), so the objective is the plain operating cost of the horizon — the
figure the JSX reports. Results come as a side-by-side comparison (energy, cost by line,
difference against the first scenario, solver status) and then the same **Dispatch by
period** view as the REopt results, for whichever scenario is picked, priced in the
study's currency.

**Verified.** `tools/test_dispatch_study.py` poses the JSX's day through the section's own
builder and through the runner `jsx_case.py` was validated with; the operating cost agrees
exactly in all six cases, and the section's line-by-line accounting reproduces the solver's
objective:

| Fleet · rule | Operating cost, ₸ | Grid purchase, kWh |
| --- | ---: | ---: |
| 2 units · A free from 50 % | 1,492,498 | 6,850 |
| 2 units · B 90 % rule | 1,563,237 | 6,850 |
| 2 units · C 90 % + battery | 1,367,502 | 3,227 |
| 3 units · A free from 50 % | 1,275,280 | 739 |
| 3 units · B 90 % rule | 1,418,074 | 2,180 |
| 3 units · C 90 % + battery | 1,259,645 | 0 |

**Economics and the savings veil.** Under the comparison, one scenario is picked and set
against every other in a single table — saving over the window, saving per year, the extra
battery CAPEX (an input, 391,000,000 ₸ by default) and the payback in years — which is the
JSX's "Экономия к B / Окупаемость к B / к A" strip rearranged so every pair reads on one
row. The chart then carries the JSX's green veil: each hour's energy saving against the
chosen base, divided by the spread (mean grid price − mean unit cost, 38 ₸/kWh here) and
hung from the load line, so its area × spread is the money; hours that cost more show in
peach. The stat strip ends with "Saving vs …" and a line splits it as the JSX does —
energy, starts and wear, SoC correction. A battery scenario defaults to the base with the
same rule and load scale and no battery (C against B, as in the JSX).

On the JSX's day: C saves 195,734 ₸ against B and 124,996 ₸ against A; the hourly savings
add up to those differences exactly (`tools/test_dispatch_study.py`). Per year is the
window annualised (× 8,760 / 24), so the day gives payback 5.5 years against B and 8.6
against A; the JSX's 6.3 / 11.5 come from full-year runs, which this section also accepts
as an 8,760-hour upload.

**Starts per day.** The two workbooks disagree most on how often engines start:
`CHP_BESS_dispatch_sim.xlsx` (1-minute threshold rules) starts 4 per day with the battery,
while `CHP_BESS_model_v2.xlsx` / the JSX (hourly) comes to 41–307 starts a year, 0.1–0.8 a
day; this hourly optimiser, like the JSX, cannot see the minute-scale excursions behind the
workbook's starts. Starts are now a first-class quantity:

* **a cap** — `FuelTechInputs.max_starts_per_day`: at most N starts per unit in any
  calendar day of the horizon (hours 0–23, 24–47, …). The start indicator is already bounded
  below by every real start, so the cap needs no new binaries. Blank means no limit and adds
  no variables or constraints, so every existing case and validator is unchanged. In the
  section it is a column of the units table, with a per-scenario override so caps can be
  compared side by side;
* **a report** — starts per day (average and busiest day), starts per year, and the
  workbook's own maintenance measure, effective hours = running hours + starts × the
  equivalent hours of one start (15 by default, the workbook's placeholder).

On the JSX week with three units and the 90 % rule the optimiser starts engines 14 times,
up to 3 a day. A cap of one start per unit per day holds on every unit-day and costs
9,417 ₸ more over the week; a cap of zero forbids starts and costs 745,849 ₸ more; a blank
cap reproduces the uncapped week to the tenge (`tools/test_dispatch_study.py`).

**A year, and twenty-five of them.** A sixth panel, *Coverage and lifetime*, decides how the
horizon is covered and what a lifetime of it is worth. Two choices:

* **Solve the window as posed** — the original behaviour, unchanged, down to the tenge
  (`tools/test_year_cases.py` case 5).
* **A year from typical days (weighted)** — the load's days are clustered into *k* typical
  ones (k-means++ on each day's 24 load hours beside its 24 price hours, each part
  normalised by its own maximum), each typical day is solved **by the core, as an ordinary
  24-hour horizon**, and the answers are laid back down on every real day of their cluster.
  `calculator/year_study.py` holds all of it; no formula in `reopt_core` is touched. The
  method and its one real limitation are Kotzur, Markewitz, Robinius and Stolten, *Time
  series aggregation for energy system design: Modeling seasonal storage*, Applied Energy
  **213** (2018) 123–135, whose own words for the limitation are that typical periods "are
  modeled independently and cannot exchange energy".

Why it is worth a panel: 8,760 hours with on/off units is 17,520 commitment binaries and the
run stops at its time limit with a gap, while 12 typical days is 288 hours and solves in
about a second per scenario. Measured against years that *can* be solved whole, 12 typical
days land within 0.02 % (Part 16).

Three properties are exact rather than approximate, and the tests check each one:

* **annual energy** — the representative is the cluster's centroid, so the weighted sum of
  the typical days is the sum of every real day to the last kWh;
* **the accounting** — every linear quantity of the replayed year is the weighted sum of the
  typical days' by construction (each day is laid down exactly as many times as its weight),
  so `account()` reproduces the objective exactly;
* **the price** — the year is priced with the replayed price series, the one actually solved,
  and the period view's energy charge is the study's own grid cost to the tenge.

Two are not, and are said so on the page:

* **the peak** is smoothed by clustering — a centroid day has no single hour's extreme in it;
* **the joins.** A day solved alone wraps at midnight, so its start count covers a day
  followed by *itself*; put two unlike days next to each other and the join creates or
  removes a start neither day could see. Those joins are counted with the core's own cyclic
  rule (`model.py:_was_off`) and the start cost they carry is added, so the cost table and
  the period view report one start count and not two. Measured on the factory year: 352
  starts inside the typical days, 54 more from the joins, 810,000 ₸. What is still not
  enforced is a minimum up or down time spanning a join — the clustered year is an estimate
  of the year, not a dispatch plan for it.

**Over N years.** A second new table takes the annual operating cost each scenario reported
and carries it to the end of the analysis period: present value, the extra CAPEX, net
present value, simple payback and **discounted payback**. The present-worth factor is
`reopt_core.finance.annuity` — REopt's own geometric sum from `utils.jl:11`, which charges
year 1 already escalated once — so the study's 25-year figures rest on the same arithmetic as
the REopt panels'. This is also REopt's own lifetime convention, in NREL's words: it "uses
one year of resource and cost data with present worth factors to account for life-time costs,
assuming that one year repeats with degradation and escalation factors". Analysis period
(25 yr), escalation (3.4 %/yr, REopt's fuel default) and discount rate (6.24 %/yr, REopt's
offtaker default) are inputs, because this section is not REopt and says so. Simple payback
is undiscounted CAPEX ÷ year-one saving; discounted payback is the year in which the
discounted savings have repaid the CAPEX, interpolated inside that year, and "never" when
they do not. Read from the other side of a comparison the table mirrors itself and says "(the
other way)", as the savings strip above it already does.

In the browser the default A / B / C day solves in under a minute; beyond a week, on/off
units add one binary per unit per hour and a run may stop at its time limit with a small
remaining gap, which the comparison table shows.

---

# Part 14 — An outside case: Sigalo et al. 2023

*Real-Time Economic Dispatch of CHP Systems with Battery Energy Storage for Behind-the-Meter
Applications*, Energies **16**(1274), 2023 — a 2 × 250 kW<sub>e</sub> CHP plant with a
1,000 kWh battery at an animal-feed factory, solved by MILP with an LSTM forecast and a
receding horizon. It is the first case posed to this calculator that comes from neither
REopt nor a vendor, so it tests the engine rather than the port.

## A reverse-engineered CSV, audited

A day-long CSV circulated as "digitised from the paper". `tools/audit_paper_csv.py` checks
it three ways (provenance, physics, economics) and keeps them apart:

* **Provenance fails.** Its time step is 1 h (the paper runs 48 half-hour steps), its tariff
  is a smooth 0.040–0.185 USD curve over 23 values (the paper's Table 5 has two bands,
  £0.106 / £0.140), and its heat load swings 170–460 kW<sub>th</sub> in anti-phase with the
  electric load (the paper's Figure 7 is flat at ≈483). Only the equipment is the paper's.
* **Physics, mostly.** Balance, the 500 kW fleet cap, the 50 % minimum load and the 250 kW
  battery limit all hold. Two do not: the SoC trace implies a **lossless battery** (Table 4
  says 90 % each way), and the baseline column **over-generates up to 90 kW in 6 hours**
  with no import and no export permitted. Its SoC column fits the 30–100 % window only if
  read as energy *above* the floor.
* **Economics: not an optimum.** Priced with the paper's own Table 3 curve, its "optimised"
  column costs 524.63/day against this calculator's 514.46 on the same inputs — 1.94 %
  cheaper here. Ignoring heat the gap is 5.17 %, because at a 0.040 night tariff buying is
  cheaper than running the engines; the night-time CHP output is justified by heat alone.

## The paper's own case, rebuilt

`tools/paper_case.py` builds the day from the tables (Table 2 efficiencies, Table 3 fuel
curve, Table 4 battery, Table 5 tariff, flat 483 kW<sub>th</sub>, 48 half-hour steps, no
export) and marks its four assumptions in the source: the electric load is unpublished
(two profiles are run — a reconstruction of Figure 6 and the CSV's day — and only agreeing
conclusions are reported), a 90 % boiler stands in for the tank whose capacity the paper
never gives, the start-up cost of Eq (19) has no published value, and the day closes on SoC.

**Half-hour steps on an hourly engine.** `reopt_core.model` integrates one hour per step.
The transformation — keep every kW rate, multiply every per-kWh price by Δt, divide the
battery's kWh by Δt — is exact, and `--check-dt` proves it on one physical day held constant
inside each hour: 24 × 1 h and 48 × 30 min give 528.1455 vs 528.1509 and identical CHP, grid,
discharge and boiler energies.

| Scenario (CSV load / Figure-6 load) | Total | CHP kWh | Grid kWh | Starts |
| --- | ---: | ---: | ---: | ---: |
| grid only | 1,470 / 1,706 | 0 | 9,005 / 10,934 | 0 |
| CHP, no battery | 574 / 706 | 8,635 / 10,038 | 370 / 896 | 9 / 2 |
| **CHP + battery** | **529 / 617** | 9,152 / 11,106 | 0 | 7 / 0 |
| battery with no losses (the CSV's assumption) | 523 / 609 | 9,005 / 10,934 | 0 | 0 |
| start cost 100, or max 1 start/day | 528 / 617 | 9,153 / 11,106 | 0 | 0 |
| heat ignored | 502 / 617 | 9,092 / 11,106 | 0 | 5 / 4 |

Holding on both profiles: savings against grid-only **64 %** (the paper's ideal Scenario 1
gives 54.4 %, and ours carries neither forecast error nor start cost); the battery removes
grid import entirely and is worth **46–89 per day** over CHP alone; **heat is what keeps the
engines on** — with the thermal load the optimum starts nothing, without it 4–5 times, which
is the paper's qualitative claim in numbers; and the caps on starts never bind because the
optimum has none.

**Table 6 is not reproducible, as Part 12's reading predicted.** At the paper's own tariff
and a load of Figure 6's magnitude, grid-only must cost 1,470–1,706/day; Table 6 prints
731.98. The factor of ≈2 matches Eq (19)'s missing Δt. Percentages compare; absolute figures
do not.

**Limits this exposed.** The engine optimises an *affine* fuel curve built from the 100 %
and 50 % efficiencies and is re-priced on Table 3's quadratic; the gap is 1.2–1.6 % (it was
2.1–2.5 % before Part 15's fuel-intercept fix), so
scenario differences smaller than that are approximation, not dispatch (the constraint
monotonicity check is therefore run on the engine objective, where it holds exactly).
REopt's piecewise fuel curve of Eq (5)–(8) is not implemented, there is no thermal store,
and there is no receding horizon — this calculator is always the paper's "ideal" scenario.

**One engine defect, found and fixed.** A *disabled* technology kept its `min_kw` as a size
floor while its upper bound went to zero, so any scenario that switched PV or a fuel tech
off with a non-zero minimum came back Infeasible (model.py:475). Both bounds are now zero
when the tech is off; the enabled path is untouched, and TC1 23/23, TC2 15/15, G1/G2 24/24,
PT2 22/24, all nine REopt.jl groups, the dispatch study and the field checks are unchanged.

---

# Part 15 — IEEE PES pglib-uc: the commitment maths, cross-validated

[pglib-uc](https://github.com/power-grid-lib/pglib-uc) is the unit-commitment benchmark
library curated by the IEEE PES Task Force on Benchmarks for Validation of Emerging Power
System Algorithms: real instances (CAISO, FERC, RTS-GMLC) under CC-BY **and the task
force's own reference model**, `uc_model.jl`. That model is the ground truth here.
`benchmarks/uc_reference_highs.jl` is their file with one edit — Cbc and JuMP 0.19 syntax
swapped for HiGHS and JuMP 1.x, plus a JSON dump of the solution. No constraint or
objective term is touched.

pglib-uc models more than this calculator does, so `tools/pglib_uc_case.py` states a
*derived* instance and lists every change in its header: reserves to zero, ramp limits
made non-binding, one startup category, the piecewise cost collapsed to its two end points,
renewables removed, every unit starting off, a tail of zero-demand periods, and demand
scaled to the chosen subset. What remains is exactly what this engine claims: commitment
with minimum up and down times, start costs, minimum stable load, an affine cost curve and
an equality demand balance with no grid.

| Instance | Units | Periods | IEEE PES reference | This calculator | Difference |
| --- | ---: | ---: | ---: | ---: | ---: |
| RTS-GMLC 2020-01-27 | 73 | 54 | 7,647,266.30 | 7,647,266.30 | 0.0000 % |
| CAISO 2014-09-01 | 60 | 54 | 9,297.69 | 9,297.69 | 0.0000 % |
| FERC 2015-07-01 (lw) | 80 | 28 | 9,005,380.75 | 9,005,380.75 | 0.0000 % |

Exact on all three, and faster (13 s against 83 s on RTS-GMLC). Start counts match on two;
on FERC 77 against 75 at the same cost, where units with a zero start cost leave equal
optima.

**Three engine defects had to be fixed to get there, and no earlier test could have caught
them** — REopt has no minimum up or down time, and every case posed here before had a
horizon far longer than those times.

1. **The fuel curve's y-intercept did not scale with unit size.**
   `fuel_slope_and_intercept` (utils.jl:645) returns it per kW of *rated* capacity. REopt
   multiplies it by `dvSize` for CHP (chp_constraints.jl:34) and does not for the generator
   (generator_constraints.jl:11); this port multiplied by 1 in both cases, so a CHP with a
   part-load efficiency curve burned too little fuel — 24.6 kW/h per engine, about 3.5 %,
   on Part 14's case. The product size × on is now linearised exactly, so it is right
   whether the unit is fixed or being sized.
2. **A negative y-intercept was silently dropped** (`ic > 0`), where REopt's own condition
   is `abs(ic) > 1e-7`. Four of RTS-GMLC's 73 units and 23 of FERC's 80 have a cost curve
   whose first point sits below the linear extension; their cost was overstated.
3. **Minimum up and down times wrapped around the horizon.** Hour 0 followed hour H−1, so a
   unit stopped near the end could not run near the start. That is right for a repeating
   day and remains the default; it is wrong for a finite horizon with a stated initial
   state. RTS-GMLC's minimum down times reach 48 h and FERC's 84 h against a 28-period
   horizon, which made RTS-GMLC 13.3 % too expensive and left FERC unable to serve its
   demand at all. `ScenarioInputs.cyclic_commitment = False` with
   `FuelTechInputs.initial_on` now states the finite-horizon convention.

After the fixes: TC1 23/23, TC2 15/15, G1/G2 24/24, PT2 22/24, off-grid and V1–V4 unchanged,
all nine REopt.jl groups, the profiling, field, dispatch-study and JSX checks all pass. The
only figures that moved are Part 14's, and in the direction the first fix predicts: the gap
between the affine fuel curve and Table 3's quadratic fell from 2.1–2.5 % to 1.2–1.6 %, and
the CHP + battery day on the CSV load went from 528.15 to 528.64 with 7 starts instead of 0,
because an engine's hourly intercept is now actually charged.

---

# Part 16 — A year, and twenty-five of them: the methodology re-checked

The calculator is asked for two things a single solved window cannot give on its own: a
**year**, and **twenty-five** of them. This part re-derives both from the definitions and
measures every shortcut the app takes on the way. Three test files, none of which import
the design layer:

| File | What it settles | Solver |
| --- | --- | --- |
| `tools/test_year_finance.py` | every 25-year formula, rebuilt year by year from its definition and against REopt.jl's own convention | none |
| `tools/test_year_horizon.py` | what the length of the horizon does to the answer, and how well a window stands in for a year | HiGHS |
| `tools/test_year_profile.py` | whether the year free mode builds is a year at all | none |

## The 25-year chain is exact

The lifecycle cost the solver minimises and the 25 cash flows the pro-forma discounts are
separate code reaching the same money. On a full year with a fixed battery and a
demand-charge tariff:

| | |
| --- | --- |
| capital, after ITC and MACRS | 617,695 |
| year-1 utility bill × pwf_e 14.8203 × (1 − 0.26) | 1,426,356 |
| year-1 storage O&M × pwf_om 16.2186 | 30,303 |
| **rebuilt lifecycle cost** | **16,624,220** |
| **solver objective** | **16,624,220** |
| NPV as `lcc_bau − lcc` | −614,604 |
| NPV from the 25 cash flows | −614,604 |

Present-worth factors, the PV levelization factor, `effective_cost` (ITC at end of year 1,
MACRS with and without bonus, replacement discounted to its year) and the BAU identity
`lifecycle = pwf_e × year1 × (1 − tax)` all reproduce their year-by-year sums. Nothing in
the 25-year machinery is approximated.

Two deviations from REopt.jl are printed rather than failed, both in the finance port:

- **`proforma.pv_lcoe`** escalates O&M as `(1+e)^(y-1)`; `financial.jl:268` uses `(1+e)^y`.
  Worth −0.47 % on the whole LCOE. Part 10 already records PV LCOE running 1–4 % *above*
  the live tool, so matching the Julia source here would widen that gap, not close it. The
  decision belongs against reopt.nlr.gov, not against the source, so it is left alone and
  recorded.
- **`proforma.build`** carries the same off-by-one. It is dead code: the app's payback and
  IRR come from the `Metrics` / `add_tech` port, which is faithful.

## A horizon shorter than a year is not a year divided

Capital, per-kW O&M and the fixed monthly charge are quantities **per year**. Energy, fuel
and per-kWh O&M are quantities **per hour solved**. The core multiplies both by the same
present-worth factors and scales neither by the horizon, so a short window puts a full year
of standing costs against a week of energy. Measured on a 1,000 kW flat load, $0.12/kWh and
a $100/month fixed charge, with no technologies at all:

| horizon | lifecycle cost | × 8,760/H | vs the year |
| --- | --- | --- | --- |
| 8,760 h | 11,541,663 | 11,541,663 | — |
| 4,380 h | 5,777,412 | 11,554,823 | +0.1 % |
| 730 h | 973,869 | 11,686,427 | +1.3 % |
| 168 h | 234,255 | 12,214,723 | **+5.8 %** |
| 24 h | 44,745 | 16,332,045 | **+41.5 %** |

`fixed_cost = fixed_monthly_charge * 12` regardless of how many hours are solved, so a day
annualised bills 365 years of standing charge. The same distortion decides what gets built:
a 1,000 kW load on a $0.34/kWh grid with a generator at $800/kW burning $0.172/kWh of fuel
builds the full 1,000 kW from a quarter, a month or a year — and **nothing at all from a
week**, because one week of fuel saving cannot repay a whole year's capital.

This is not reached by the app today: the Custom dispatch study switches finance off
(`analysis_years=1`, every rate zero, no capital, no fixed charge), so its objective is a
pure window operating cost and the mixing cannot occur. It is a property of the **core**,
and it is what makes "solve a week, then annualise" unsafe the moment any per-year cost
enters. The neighbouring project guards exactly this with an explicit
`year_fraction = n·Δt / 8760` on every capital term (`D:/Greenhouse/src/optimize.py:235`,
after Calliope's `annualisation_weight`) and warns in the same place that monthly charges
on short horizons are "непропорционально тяжёлыми".

## A window, annualised, is a poor estimate of a year

The study reports "per year = window × 8,760 / H". Against a real solved year — the DOE
hospital shape free mode builds, scaled to the example week's 2,194 kW average, the JSX
fleet with the commitment rules off so the full year is an honest LP (473,489,871 in 6.4 s):

| estimator | error against the solved year |
| --- | --- |
| one calendar week × 8,760/168, best of the 52 | −0.19 % |
| one calendar week, worst of the 52 | **+22.66 %** |
| one calendar week, median | −2.56 % |
| spread across the 52 weeks | **37.4 percentage points** |
| one calendar month × 8,760/H, worst of the 12 | **+18.08 %** |
| the example week tiled into a year | −5.08 % |
| 4 weighted representative days | −0.50 % |
| 8 weighted representative days | −0.02 % |
| **12 weighted representative days** | **−0.01 %, in 0.2 s** |
| 24 weighted representative days | −0.03 % |

A single week is a lottery: which week you cut decides a 37-point range. Twelve clustered
days — k-means on the day vectors, centroids as representatives, weights summing to 365,
the method in `D:/Greenhouse/src/aggregate.py` — reproduce the year to a hundredth of a
percent for a thirtieth of the work.

An earlier note in `app_dispatch.py` said a 30-day window annualised came within 0.3–0.5 %.
That was measured against the **tiled** year, which has no season in it; against a real
year a month is out by up to 18 %.

### With the integer rules on

The comparison above is an LP, because only an LP lets a whole year be solved as the truth.
Repeated on one month of the DOE warehouse shape — which falls to 0.15 × its mean at night,
below one engine's minimum load — with the real 3-unit fleet, 50 % floor, 15,000 per start
and 4/5 h minimum up/down (744 h solved whole to optimality in 10.6 s, 45,369,136, 4 starts):

| estimator | cost | starts |
| --- | --- | --- |
| the month solved whole | 45,369,136 | 4 |
| 4 weighted representative days | −0.07 % | 0 |
| 8 weighted representative days | −0.06 % | 0 |
| 31 days, each solved separately | −0.06 % | 0 |
| the first week × 744/168 | **+5.00 %** | — |

The cost survives clustering; **the starts do not**. Cutting a month into days and wrapping
each one cyclically loses every start that happens at a day boundary — 4 became 0 here. For
a study whose whole subject is start cost, that is the limitation to state out loud: a
representative-day year can be trusted for money and energy, not for the "Starts per year"
row. The same table shows k=31 is no better than k=8, which locates the whole error in the
day boundary rather than in the clustering.

## The year free mode builds

Every one of the six shapes is 8,760 real hours carrying the example week's own energy
(19.223 GWh, mean 2,194 kW, identical to the kWh across all six). A week said 52 times has a
monthly swing of 1.014× — arithmetic from the tiling phase, not weather. The real shapes
swing 1.19× to 1.38×, and their weekday/weekend split runs from 1.24× to "total" for the
two procedural FlatLoad shapes, which are idle at weekends (4,600 and 2,520 zero hours in
the year — disclosed in the caption as "quietest hour 0 kW").

The default shape is the closest to the example week on peak/mean and min/mean of the six,
which is what its comment claims:

| shape | peak/mean | min/mean |
| --- | --- | --- |
| the example week itself | 1.87 | 0.51 |
| Continuous, mild seasonal swing (default) | 1.71 | 0.57 |
| Continuous with a daily peak | 2.02 | 0.35 |
| Two shifts, five days | 2.11 | 0.00 |
| Office hours, strong seasonal swing | 2.67 | 0.31 |
| Deep nights and weekends | 3.08 | 0.15 |

The level is the plant's own; the shape is a US reference building. A site with a different
season gets a different answer, and the caption says so.

The day and week the Dispatch Period view shows are slices of that year and nothing else:
365 day-slices sum to the year exactly, the peak day contains the year's peak hour, the
representative day is the median-energy day, and it carries 1.026 × (1/365) of the year.

## Five cases, from an hourly load to a payback

`tools/test_year_cases.py` carries five unlike cases through the **app's own path** —
`app_dispatch.build`, `year_study.solve_year`, `app_dispatch.account` and the real
`app_periods` view rendered headlessly — and checks each against the core by recomputing
the same quantity a second way. 60 checks, all passing.

| Case | Load | Plant | What it proves | Simple / discounted payback |
| --- | --- | --- | --- | ---: |
| 1 Factory on an expensive grid | DOE hospital year, 2,194 kW mean, 19.223 GWh | 3 engines (1,067 + 1,200 + 1,100 kW), 90 % floor, 15,000 ₸/start, BESS 2,500 kW / 5,500 kWh | the app's weighted year equals the core solved day by day, to the tenge | **9.57 / 11.26 yr** |
| 2 Cold store, deep nights | DOE warehouse year, peak 6,763 kW, quietest hour 330 kW | 2 × 900 kW, BESS 1,500 kW / 6,000 kWh with grid charging | a two-zone price survives clustering exactly, and the period view's energy charge is the study's own grid cost | **3.76 / 4.02 yr** |
| 3 Data centre, flat | 4,200 kW every hour, 36.8 GWh; price 0.14 before 07:00, 0.38 after | 1 × 3,000 kW, BESS 1,200 kW / 4,800 kWh | a year of identical days clusters to **one** typical day and reproduces the whole solved year to the cent, 20× faster | **6.41 / 7.15 yr**, identical both ways |
| 4 Island, no usable grid | DOE large-office year, peak 5,863 kW | 3 × 2,000 kW diesel, no commitment rules, BESS 2,000 kW / 8,000 kWh | the clustering error, measured against a year that can be solved whole | **260 yr / never** — the battery does not pay here |
| 5 The JSX week, window mode | the artifact's own 168 hours | 2 engines + BESS | the old path is untouched, and what annualising one week does | **6.38 / 7.11 yr** against **6.14 / 6.82** from the year |

Case 4 is the measurement that matters, because both routes are available on it:

| | operating cost | error | seconds | speed-up |
| --- | ---: | ---: | ---: | ---: |
| the year solved whole (LP) | 669,721,953 | — | 6.4 | — |
| 4 typical days | 669,401,733 | −0.048 % | 0.2 | 27× |
| 8 typical days | 669,480,021 | −0.036 % | 0.6 | 12× |
| 12 typical days | 669,585,947 | −0.020 % | 0.7 | 9× |
| 24 typical days | 669,663,406 | −0.009 % | 1.6 | 4× |

With the battery — 8,760 coupled state-of-charge equations and a cyclic closing condition —
the whole year comes to 668,757,031 and 12 typical days to 668,625,580, again −0.020 %.

Case 5 puts a number on the old shortcut on a case where the plant is the same and only the
basis differs: one week annualised gives an operating cost 5.60 % below the year's, a saving
3.62 % low and a payback 3.76 % long (6.38 against 6.14 years). That is the same defect Part
16 measured in the abstract, arriving in the one figure a reader acts on.

One trap found while building these cases and worth leaving written down: asking for a
0.001 % optimality gap on a battery scenario ran for over 13 minutes without returning,
because enabling storage creates one binary (the cost constant, `model.py:517`) and HiGHS
then chases a gap the relaxation cannot close. At the app's own default of 0.5 % the same
model solves in 8 seconds.

## What this means for a 25-year answer over a custom dispatch

The REopt path already does 25 years correctly, but it needs a full 8,760-hour year and a
tariff. The Custom dispatch study now has both halves of the answer: a year it can actually
solve (k weighted typical days, `calculator/year_study.py`) and a 25-year table built on
`finance.annuity` — the same present-worth factor the REopt panels use — with simple and
discounted payback. Part 13 describes the panel; the five cases above are the evidence that
the numbers reaching the design are the numbers the core produced. The window path is still
there and still honest about what it is: an annualisation of one window, now with the size
of that error printed next to it.

---

# Part 17 — Repository layout and how to reproduce

```
GreenHouseV2/
  REPORT.md                    this document
  CLAUDE.md                    project instructions
  REopt/                       REopt.jl v0.61.1 source + data
  reopt_jl/                    local Julia env running that source (setup.jl, run.jl)
  benchmarks/                  pglib-uc clone (gitignored) + uc_reference_highs.jl
  docs/reopt-jl/               offline docs capture (14 pages, INDEX.md is the map)
  calculator/
    streamlit_app.py           steps 1-5 UI
    app_results.py             results drawers + charts
    app_periods.py             day / week / year profiling block
    ui_theme.py                REopt-matched styling
    profile_ui.py              profiling palette, tables and dispatch chart
    app_chp_bess.py            REopt's CHP, Battery, fuel and heating inputs, field for field
    app_dispatch.py            custom dispatch study (not REopt): any load, units, rules
    year_study.py              typical days -> a year, and a year -> 25 of them (not REopt)
    reopt_core/
      finance.py               verbatim ports of the REopt.jl financial formulas
      defaults.py              defaults from REopt.jl structs
      ui_fields.py             GENERATED from the live UI spec - do not hand-edit
      data_sources.py          CRB + FlatLoad profiles, PVWatts, URDB
      tariff.py                URDB -> hourly prices + demand ratchets
      emissions.py             Cambium, AVERT, EASIUR
      model.py                 the MILP (HiGHS via PuLP)
      cost_curve.py            cost_curve.jl: size-cost pairs and incentives
      chp_defaults.py          chp.jl: CHP defaults from the heating load, maintenance
      proforma.py              proforma.jl: cash flows, simple payback, IRR
    tools/                     generators, patches and validators
  reopt_test_data/             captured REopt specs, payloads and reference runs
  reopt_test_screenshots/      evidence, one folder per test series
  vendor_analysis/             Sana'a deck text, runs and analysis
  .playwright/scripts/         browser automation for both calculators
```

## Validators

```bash
python calculator/tools/validate2.py         # TC1   23/23
python calculator/tools/validate_tc2.py      # TC2   15/15
python calculator/tools/validate_gen.py      # G1/G2 24/24
python calculator/tools/vary_ours.py         # V1-V4 27/29
python calculator/tools/validate_offgrid.py  # OG1   LCC -0.08%
python calculator/tools/validate_parity.py   # PT2   22/24
python calculator/tools/yemen_case.py        # Sana'a vendor case
python calculator/tools/test_periods.py         # period-view data functions
python calculator/tools/test_profile_render.py  # profiling render path + HTML
python calculator/tools/test_dispatch_chart.py  # chart layers, hover panel, colour sheet
python calculator/tools/test_chp_bess_fields.py # CHP + Battery vs the live tool
python calculator/tools/chp_bess_reopt_case.py  # CHP + Battery cases posed as on the site
python calculator/tools/test_reopt_jl_suite.py  # REopt.jl's own tests, 9 groups
python calculator/tools/check_reopt_jl.py      # local REopt.jl vs runtests vs this calculator
python calculator/tools/test_dispatch_study.py # custom dispatch study vs the validated JSX runner
python calculator/tools/audit_paper_csv.py     # audit a reverse-engineered day against the paper
python calculator/tools/paper_case.py          # the paper's own case (--check-dt for the dt proof)
python calculator/tools/pglib_uc_case.py       # IEEE PES pglib-uc vs its own reference model
python calculator/tools/test_year_finance.py    # 25-year formulas, rebuilt year by year
python calculator/tools/test_year_horizon.py    # horizon vs year; window annualisation error
python calculator/tools/test_year_profile.py    # the year free mode builds, and the day/week slices
python calculator/tools/test_year_cases.py      # five cases end to end, each to a payback
python calculator/tools/reopt_jl.py <scenario.json>  # any REopt JSON through the local REopt.jl
```

## Regenerating the UI spec after the real tool changes

```bash
node .playwright/scripts/extract_ui.js   # via Playwright MCP
python calculator/tools/gen_ui_fields.py
```

## Offline docs

`docs/reopt-jl/` is a full text capture of the REopt.jl documentation; `INDEX.md` is the
map. Regenerate text with `node .playwright/scripts/extract.mjs`; verify nesting fidelity
with `node .playwright/scripts/nestverify.mjs`, which compares every page's HTML list-depth
profile against the markdown indent profile — all 14 must read OK.

---

*All REopt job UUIDs cited in this document are real submissions to the public service and
are recorded for traceability.*
