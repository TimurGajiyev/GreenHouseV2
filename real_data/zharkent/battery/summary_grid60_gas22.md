# Battery payback on the measured Zharkent data — grid60_gas22

Grid 60 ₸/kWh · gas 22 ₸/kWh at full load (OEM part-load curves) · start 15,000 ₸ · battery 2,500 kW / 5,500 kWh, RTE 88%, SoC ≥ 30%, wear 0.5 ₸/kWh · CAPEX 391,000,000 ₸ · 25 yr, escalation 3.4%, discount 6.24%.

Solves 3,552, not Optimal 0, worst gap 1.0e-04. Data table SHA-256 `d7452bfe5fabd2ce…`, commit `8abd106`.

The battery over 25 years: CAPEX + O&M 2.5 % of it a year, escalated + replacement at 100 % of it in year 10 — the study page's defaults. NPV and payback below count all of it.

Break-even saving: **43.5 M ₸/yr** against CAPEX + O&M + replacement (21.8 M ₸/yr against the CAPEX alone).

## ЖКПЗ (TEDOM Quanto 1200 + J320 Жаркент 2)

164 fully measured days, 2025-10-23 – 2026-10-04; no measured day in Feb, Dec, so every M ₸/yr below is a range. Over those days: load 6,404 MWh, bought 1,530 MWh, sent to the city 75 MWh.

Measured operation, priced as a scenario: **207.9 M ₸** over those days, **412.9 … 491.7 M ₸/yr**.

| View | A, M ₸/yr | A − measured | Battery D−A, M ₸/yr | D−A over the days, M ₸ | NPV incl. O&M + replacement, M ₸ | Payback simple / disc., yr | Page default B−A, M ₸/yr |
|---|---:|---:|---:|---:|---:|---:|---:|
| optimiser, engines free | 299.7 … 328.1 | -165.3 … -113.2 | **5.3 … 10.3** | 2.1 | -684 ($-1,487k) … -594 ($-1,292k) | never / never | 1.2 … 5.6 |
| optimiser, availability as measured | 356.2 … 423.9 | -71.4 … -56.6 | **16.0 … 21.3** | 7.9 | -494 ($-1,073k) … -398 ($-865k) | never / never | 13.3 … 18.9 |
| engines as logged + battery by rule | — | — | **7.2 … 10.6** | 3.9 | -650 ($-1,413k) … -591 ($-1,284k) | never / never | — |

## Жаркент 3 (J320)

293 fully measured days, 2025-09-15 – 2026-10-04. Over those days: load 4,364 MWh, bought 787 MWh, sent to the city 473 MWh.

Measured operation, priced as a scenario: **141.3 M ₸** over those days, **175.0 M ₸/yr**.

| View | A, M ₸/yr | A − measured | Battery D−A, M ₸/yr | D−A over the days, M ₸ | NPV incl. O&M + replacement, M ₸ | Payback simple / disc., yr | Page default B−A, M ₸/yr |
|---|---:|---:|---:|---:|---:|---:|---:|
| optimiser, engines free | 132.6 | -42.4 | **5.0** | 4.1 | -690 ($-1,500k) | never / never | -3.9 |
| optimiser, availability as measured | 161.5 | -13.5 | **8.2** | 6.6 | -632 ($-1,373k) | never / never | 0.9 |
| engines as logged + battery by rule | — | — | **6.4** | 4.9 | -666 ($-1,447k) | never / never | — |

## Three engines as one pool (ЖКПЗ + Жаркент 3)

135 fully measured days, 2025-10-23 – 2026-10-04; no measured day in Feb, Dec, so every M ₸/yr below is a range. Over those days: load 7,308 MWh, bought 1,356 MWh, sent to the city 309 MWh.

Measured operation, priced as a scenario: **227.2 M ₸** over those days, **561.4 … 662.9 M ₸/yr**.

| View | A, M ₸/yr | A − measured | Battery D−A, M ₸/yr | D−A over the days, M ₸ | NPV incl. O&M + replacement, M ₸ | Payback simple / disc., yr | Page default B−A, M ₸/yr |
|---|---:|---:|---:|---:|---:|---:|---:|
| optimiser, engines free | 402.8 … 448.1 | -218.9 … -156.9 | **3.6 … 5.1** | 1.7 | -715 ($-1,554k) … -689 ($-1,497k) | never / never | 1.4 … 3.8 |
| optimiser, availability as measured | 447.3 … 543.6 | -124.7 … -110.3 | **11.5 … 14.9** | 5.4 | -573 ($-1,247k) … -513 ($-1,116k) | never / never | 9.1 … 13.5 |
| engines as logged + battery by rule, no bus netting (credits the battery with a wire's work) | — | — | **32.9 … 39.4** | 13.7 | -189 ($-412k) … -74 ($-162k) | 18.7 / never … 22.3 / never | — |
| engines as logged + battery by rule, common bus (export offsets the other plant first) | — | — | **18.8 … 24.7** | 7.9 | -442 ($-961k) … -337 ($-732k) | never / never | — |

US$ at 460 ₸/$. A day counts only when every meter read all 24 of its hours. Where a logger missed the engine or the grid reading, the same hour's balance supplies it (engine = plant − grid), kept and flagged: the J320 loggers mostly stop writing an engine that stopped, so dropping those hours would drop the outages. Annual figures are weighted by calendar month. A month with no measured day is not filled: it is taken at the lowest and at the highest measured month, so the figure is a range 'low … high' (NPV likewise; payback with its shorter end first). 'Over the days' is the measured days' own total.

