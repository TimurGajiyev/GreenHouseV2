# Battery payback on the measured Zharkent data — grid60_gas22

Grid 60 ₸/kWh · gas 22 ₸/kWh at full load (OEM part-load curves) · start 15,000 ₸ · battery 2,500 kW / 5,500 kWh, RTE 88%, SoC ≥ 30%, wear 0.5 ₸/kWh · CAPEX 391,000,000 ₸ · 25 yr, escalation 3.4%, discount 6.24%.

Solves 3,960, not Optimal 0, worst gap 1.0e-04. Data table SHA-256 `d7452bfe5fabd2ce…`, commit `a03fbd3`.

The battery over 25 years: CAPEX + O&M 2.5 % of it a year, escalated + replacement at 100 % of it in year 10 — the study page's defaults. NPV and payback below count all of it.

Break-even saving: **43.5 M ₸/yr** against CAPEX + O&M + replacement (21.8 M ₸/yr against the CAPEX alone).

## ЖКПЗ (TEDOM Quanto 1200 + J320 Жаркент 2)

186 measured days of 24 hours (70 of them not midnight to midnight), 2025-10-23 – 2026-10-04; no measured day in Feb, Dec, so every M ₸/yr below is a range. Over those days: load 7,300 MWh, bought 1,712 MWh, sent to the city 86 MWh.

Measured operation, priced as a scenario: **235.7 M ₸** over those days, **426.7 … 487.4 M ₸/yr**.

| View | A, M ₸/yr | A − measured | Battery D−A, M ₸/yr | D−A over the days, M ₸ | NPV incl. O&M + replacement, M ₸ | Payback simple / disc., yr | Page default B−A, M ₸/yr |
|---|---:|---:|---:|---:|---:|---:|---:|
| optimiser, engines free | 309.4 … 330.7 | -159.4 … -117.3 | **5.0 … 8.8** | 2.3 | -690 ($-1,499k) … -623 ($-1,353k) | never / never | 0.9 … 4.1 |
| optimiser, availability as measured | 371.2 … 422.0 | -69.7 … -55.5 | **16.1 … 22.1** | 9.2 | -491 ($-1,068k) … -384 ($-835k) | never / never | 13.3 … 19.4 |
| engines as logged + battery by rule | — | — | **9.3 … 12.3** | 5.0 | -613 ($-1,333k) … -559 ($-1,215k) | never / never | — |

## Жаркент 3 (J320)

313 measured days of 24 hours (96 of them not midnight to midnight), 2025-09-15 – 2026-10-04. Over those days: load 4,624 MWh, bought 829 MWh, sent to the city 504 MWh.

Measured operation, priced as a scenario: **149.6 M ₸** over those days, **173.8 M ₸/yr**.

| View | A, M ₸/yr | A − measured | Battery D−A, M ₸/yr | D−A over the days, M ₸ | NPV incl. O&M + replacement, M ₸ | Payback simple / disc., yr | Page default B−A, M ₸/yr |
|---|---:|---:|---:|---:|---:|---:|---:|
| optimiser, engines free | 131.9 | -41.9 | **5.3** | 4.6 | -684 ($-1,487k) | never / never | -3.6 |
| optimiser, availability as measured | 160.5 | -13.3 | **8.1** | 7.0 | -634 ($-1,378k) | never / never | 0.7 |
| engines as logged + battery by rule | — | — | **6.4** | 5.3 | -666 ($-1,447k) | never / never | — |

## Three engines as one pool (ЖКПЗ + Жаркент 3)

161 measured days of 24 hours (70 of them not midnight to midnight), 2025-10-23 – 2026-10-04; no measured day in Feb, Dec, so every M ₸/yr below is a range. Over those days: load 8,748 MWh, bought 1,602 MWh, sent to the city 365 MWh.

Measured operation, priced as a scenario: **271.0 M ₸** over those days, **577.2 … 652.3 M ₸/yr**.

| View | A, M ₸/yr | A − measured | Battery D−A, M ₸/yr | D−A over the days, M ₸ | NPV incl. O&M + replacement, M ₸ | Payback simple / disc., yr | Page default B−A, M ₸/yr |
|---|---:|---:|---:|---:|---:|---:|---:|
| optimiser, engines free | 419.7 … 451.8 | -205.6 … -153.3 | **3.7 … 5.2** | 2.0 | -713 ($-1,550k) … -687 ($-1,493k) | never / never | 1.9 … 4.1 |
| optimiser, availability as measured | 464.9 … 535.0 | -121.8 … -108.3 | **13.0 … 15.7** | 6.8 | -547 ($-1,188k) … -499 ($-1,085k) | never / never | 11.0 … 14.5 |
| engines as logged + battery by rule, no bus netting (credits the battery with a wire's work) | — | — | **33.2 … 38.6** | 16.2 | -184 ($-400k) … -88 ($-191k) | 19.1 / never … 22.1 / never | — |
| engines as logged + battery by rule, common bus (export offsets the other plant first) | — | — | **19.3 … 24.2** | 9.3 | -434 ($-944k) … -345 ($-750k) | never / never | — |

US$ at 460 ₸/$. A day is 24 consecutive hours in which every meter read, midnight to midnight wherever the run of measured hours has room for it, and is solved as one 24-hour cycle; a run shorter than a day is left out. Where a logger missed the engine or the grid reading, the same hour's balance supplies it (engine = plant − grid), kept and flagged: the J320 loggers mostly stop writing an engine that stopped, so dropping those hours would drop the outages. Annual figures are weighted by calendar month. A month with no measured day is not filled: it is taken at the lowest and at the highest measured month, so the figure is a range 'low … high' (NPV likewise; payback with its shorter end first). 'Over the days' is the measured days' own total.

