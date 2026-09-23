# Scheduled maintenance — browser test series

Driven through the real app in a browser (Playwright against
`streamlit run calculator/streamlit_app.py`), not through the Python API. Each
series configures the Custom dispatch study by hand in the UI, presses
**Solve scenarios**, and reads the rendered tables back.

Common to every series:

| | |
|---|---|
| Load | Free mode, Hospital shape (DOE reference, Chicago), scaled to the example week's mean |
| Window | **500 hours** from hour 0 — 1,028,160 kWh, peak 2,982 kW, minimum 1,262 kW |
| Grid | 60 ₸/kWh, no export, no demand charge |
| Battery | 2,500 kW / 5,500 kWh, 88 % round trip, 30 % min SoC, wear 0.50 ₸/kWh, CAPEX 391,000,000 ₸ |
| Scenarios | the app's own three: A free from 50 %, B 90 % rule, C 90 % + battery |
| Solver | 0.5 % gap, 60 s per scenario |
| Maintenance | PyPSA formulation — count × duration, capacity lost 100 %, services spread evenly; the optimiser picks the hours |

A 500-hour window is ~21 days, so a unit that runs throughout clocks ~492
running hours. Against the 1,000–2,000 running-hour minor-service interval that
INNIO Jenbacher and TEDOM publish, **one** service in 500 h is already tighter
than the regimen — the app says so in its own Service plan caption. The series
below therefore run a deliberately conservative plan, not a slack one.

---

## Series 1 — two engines, identical service plans

Fleet as the preset ships it, plus one service each.

| Unit | Rated kW | Energy ₸/kWh | Start ₸ | Min load % | Services × h |
|---|---:|---:|---:|---:|---|
| Jenbacher | 1,067 | 22 | 15,000 | 50 | 1 × 8 |
| TEDOM | 1,200 | 22 | 15,000 | 50 | 1 × 8 |

**Units table as rendered**

| UNIT | SIZE kW | PRODUCTION kWh | CF | RUNNING HOURS | FUEL MMBtu | STARTS | SERVICES | SERVICE H | AVAILABILITY |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Jenbacher | 1,067 | 474,113 | 88.9 % | **492** | 4,622 | 1 | 1 | 8 | 98.40 % |
| TEDOM | 1,200 | 459,346 | 76.6 % | **492** | 4,478 | 1 | 1 | 8 | 98.40 % |
| Fleet | 2,267 | 933,459 | | 984 | 9,100 | 2 | 2 | 16 | 98.40 % |

This is the answer to the original complaint: RUNNING HOURS reads 492 of 500,
not 500 of 500, and the three new columns say why.

**Scenario comparison (500 h window)**

| Metric | A free 50 % | B 90 % rule | C 90 % + battery |
|---|---:|---:|---:|
| Fuel-fired generation kWh | 933,459 | 946,265 | 1,002,129 |
| Grid purchase kWh | 94,701 | 122,814 | 44,222 |
| Spill kWh | 0 | 40,920 | 8,426 |
| Starts | 2 | 20 | 10 |
| Generation cost ₸ | 20,536,097 | 20,817,835 | 22,046,837 |
| Grid cost ₸ | 5,682,035 | 7,368,843 | 2,653,331 |
| Start cost ₸ | 30,000 | 300,000 | 150,000 |
| Battery wear ₸ | 0 | 0 | 35,808 |
| **Operating cost ₸** | **26,248,132** | 28,486,678 | **24,885,976** |
| Solver | Optimal, gap 0.00 % | Optimal, gap 0.00 % | Optimal, gap 1.59 % |

**Services placed:** Jenbacher on day 7, TEDOM on day 8 — the optimiser
staggered them by a day without being told to. Visible in *Starts by unit and
day*: one bar each, on adjacent days, in different colours.

Screenshot: `screenshots/gh_maint_s1_2units.png`

---

## Series 2 — three engines, the third on completely different data

КГУ-3 is not the preset's clone of the other two. It is a smaller, thirstier,
cheap-to-start machine on a tighter service plan.

| Unit | Rated kW | Energy ₸/kWh | Start ₸ | Min load % | Services × h |
|---|---:|---:|---:|---:|---|
| Jenbacher | 1,067 | 22 | 15,000 | 50 | 1 × 8 |
| TEDOM | 1,200 | 22 | 15,000 | 50 | 1 × 8 |
| **КГУ-3** | **750** | **34** | **4,000** | **40** | **2 × 8** |

**Units table as rendered**

| UNIT | SIZE kW | PRODUCTION kWh | CF | RUNNING HOURS | FUEL MMBtu | STARTS | SERVICES | SERVICE H | AVAILABILITY |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Jenbacher | 1,067 | 447,200 | 83.8 % | 492 | 4,360 | 1 | 1 | 8 | 98.40 % |
| TEDOM | 1,200 | 482,943 | 80.5 % | 492 | 4,708 | 1 | 1 | 8 | 98.40 % |
| КГУ-3 | 750 | 95,436 | **25.4 %** | **168** | 930 | **16** | 2 | 16 | 96.80 % |
| Fleet | 3,017 | 1,025,578 | | 1,152 | 9,998 | 18 | 4 | 32 | 97.87 % |

**The different data produces different behaviour, which is the point.** At
34 ₸/kWh against the grid's 60 it is still worth running, but only where it
beats the alternatives — 25.4 % capacity factor and 168 running hours against
the other two at ~84 %. Its 4,000 ₸ start makes cycling affordable, so it takes
**16 starts** where the others take 1. It is being dispatched as a peaker, not
as baseload, purely from its own numbers.

**Operating cost:** A 23,956,831 ₸ · B 26,389,148 ₸ · C 24,053,698 ₸
(fleet starts 18 / 34 / 24).

Adding the third unit cut scenario A from 26,248,132 to 23,956,831 ₸ over the
window — 2,291,301 ₸, or 8.7 % — because even expensive own generation beats
60 ₸/kWh grid.

Input screenshot: `screenshots/gh_maint_s2_inputs.png`

---

## Series 3 — four engines, the fourth different again

A small, nearly-grid-priced peaker on the tightest service plan of the four.

| Unit | Rated kW | Energy ₸/kWh | Start ₸ | Min load % | Services × h | Spill |
|---|---:|---:|---:|---:|---|---|
| Jenbacher | 1,067 | 22 | 15,000 | 50 | 1 × 8 | yes |
| TEDOM | 1,200 | 22 | 15,000 | 50 | 1 × 8 | yes |
| КГУ-3 | 750 | 34 | 4,000 | 40 | 2 × 8 | yes |
| **GT-4 peaker** | **400** | **48** | **1,500** | **25** | **3 × 4** | **no** |

**Units table as rendered**

| UNIT | SIZE kW | PRODUCTION kWh | CF | RUNNING HOURS | FUEL MMBtu | STARTS | SERVICES | SERVICE H | AVAILABILITY |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Jenbacher | 1,067 | 443,721 | 83.2 % | 492 | 4,326 | 1 | 1 | 8 | 98.40 % |
| TEDOM | 1,200 | 488,588 | 81.4 % | 492 | 4,763 | 1 | 1 | 8 | 98.40 % |
| КГУ-3 | 750 | 92,363 | 24.6 % | 160 | 900 | 15 | 2 | 16 | 96.80 % |
| **GT-4 peaker** | 400 | **0** | **0.0 %** | **0** | 0 | **0** | 3 | 12 | 97.60 % |
| Fleet | 3,417 | 1,024,671 | | 1,144 | 9,989 | 17 | 7 | 44 | 97.80 % |

**Scenario comparison**

| Metric | A free 50 % | B 90 % rule | C 90 % + battery |
|---|---:|---:|---:|
| Grid purchase kWh | 3,488 | 28,658 | 3,674 |
| Spill kWh | 0 | 41,370 | 10,045 |
| Starts | 17 | 42 | 23 |
| **Operating cost ₸** | **23,950,411** | 26,373,921 | 23,987,104 |
| Solver | Optimal, gap 0.15 % | Optimal, gap 0.19 % | Optimal, gap 2.20 % |

**GT-4 is never dispatched.** At 48 ₸/kWh it undercuts the 60 ₸ grid, but the
other three already cover the load, so grid import in scenario A falls to
3,488 kWh over the whole window — there is essentially nothing left for it to
displace. Adding it changed scenario A by 6,420 ₸ in 23.95 M, which is inside
the solver's own gap: **the fourth unit earns nothing on this load.**

Screenshots: `screenshots/gh_maint_s3_left.png`, `gh_maint_s3_right.png`
(inputs), `gh_maint_s3_4units.png` (results).

---

## The finding this series produced

**Maintenance is scheduled on a unit that never runs.** GT-4 reports 3 services,
12 hours out and 97.60 % availability while producing 0 kWh in 0 running hours.
That is the E-count formulation doing exactly what it was told — `Σ ms = E`
forces E events whether or not the unit ever operates — and it is wrong as
engineering: a minor service is due on *running* hours, so an engine that never
started is not due one.

It costs nothing here (an idle unit's outage constrains nothing), so no number
above is distorted by it. But it makes the AVAILABILITY column misleading for an
idle unit: 97.60 % "available" next to 0 % utilised.

Two ways to close it, neither done yet:

* gate the event count on the unit running at all — cheap, but a binary
  "did it run" interacts awkwardly with the count constraint;
* trigger services on cumulative running hours instead of a fixed count, which
  is how the OEM interval is actually written and what HOMER Pro implements.
  This is the more correct model and the larger change.

Until then: **set services to 0 for a unit you expect to sit idle**, or read
AVAILABILITY next to RUNNING HOURS rather than on its own.

---

## What the browser run established about the feature

1. The maintenance columns reach the model. The Service plan caption converts
   the count into running hours and flags a plan tighter than the OEM interval.
2. `RUNNING HOURS` now moves off the horizon length, which is what prompted the
   work: 492 of 500 rather than 500 of 500.
3. The optimiser staggers services across units on its own — no overlap rule is
   given to it, and it never took two engines out at once in any series.
4. A unit whose numbers differ is dispatched differently, with its own service
   plan honoured alongside the others': КГУ-3 at 34 ₸/kWh and a 4,000 ₸ start
   ran 160–168 h with 15–16 starts while the 22 ₸ engines ran 492 h with 1.
5. It scales: 2 → 3 → 4 units on the same 500-hour window, each solved inside
   the 60 s per-scenario limit, three scenarios each.

## Cost across the three series (scenario A, 500 h window)

| Fleet | Operating cost ₸ | vs previous |
|---|---:|---:|
| 2 engines | 26,248,132 | — |
| 3 engines (+ КГУ-3) | 23,956,831 | −2,291,301 (−8.7 %) |
| 4 engines (+ GT-4) | 23,950,411 | −6,420 (inside the solver gap) |

The third unit pays for itself against a 60 ₸ grid. The fourth does not: by then
there is no grid import left to displace.

## Note on driving this in a browser

The units table is `st.data_editor`, which renders on a canvas
(glide-data-grid), so cells have no DOM geometry — the accessibility tree gives
column names with zero-size boxes. Editing works by clicking a computed pixel
position, pressing any printable key to open the real `input.gdg-input` overlay,
filling that, and committing with Enter.

Two traps cost a run each:

* **Tab drifts.** Tabbing across columns auto-scrolls the grid horizontally, and
  after a few hops the values land in the wrong columns. Click each target cell
  explicitly instead, and re-measure the grid rect before every click — the page
  reflows as rows are added.
* **A new row does not inherit defaults.** Adding a row leaves `Service h`,
  `Capacity lost %` and `Spread services` empty rather than at their column
  defaults, so a unit added by hand needs all three filled or it is silently not
  maintainable.
