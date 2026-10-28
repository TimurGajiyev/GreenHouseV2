# Battery payback on the measured Zharkent data — grid60_gas22

Grid 60 ₸/kWh · gas 22 ₸/kWh at full load (OEM part-load curves) · start 15,000 ₸ · battery 2,500 kW / 5,500 kWh, RTE 88%, SoC ≥ 30%, wear 0.5 ₸/kWh · CAPEX 391,000,000 ₸ · 25 yr, escalation 3.4%, discount 6.24%.

Solves 3,552, not Optimal 0, worst gap 1.0e-04. Data table SHA-256 `d7452bfe5fabd2ce…`, commit `8abd106`.

The battery over 25 years: CAPEX + O&M 2.5 % of it a year, escalated + replacement at 100 % of it in year 10 — the study page's defaults. NPV and payback below count all of it.

Break-even saving: **43.5 M ₸/yr** against CAPEX + O&M + replacement (21.8 M ₸/yr against the CAPEX alone).

## ЖКПЗ (TEDOM Quanto 1200 + J320 Жаркент 2)

164 fully measured days, 2025-10-23 – 2026-10-04; months with no measured day, filled from their neighbours: [2, 12]. Over those days: load 6,404 MWh, bought 1,530 MWh, sent to the city 75 MWh.

Measured operation, priced as a scenario: **477.1 M ₸/yr** (462.8 scaled by hours).

| View | A, M ₸/yr | A − measured | Battery D−A, M ₸/yr | by hours | NPV incl. O&M + replacement, M ₸ | Payback simple / disc., yr | Page default B−A, M ₸/yr |
|---|---:|---:|---:|---:|---:|---:|---:|
| optimiser, engines free | 326.8 | -150.3 | **5.4** | 4.6 | -682 ($-1,483k) | never / never | 1.3 |
| optimiser, availability as measured | 409.3 | -67.8 | **18.3** | 17.7 | -452 ($-982k) | never / never | 16.0 |
| engines as logged + battery by rule | — | — | **7.9** | 8.7 | -639 ($-1,389k) | never / never | — |

## Жаркент 3 (J320)

293 fully measured days, 2025-09-15 – 2026-10-04. Over those days: load 4,364 MWh, bought 787 MWh, sent to the city 473 MWh.

Measured operation, priced as a scenario: **175.0 M ₸/yr** (176.0 scaled by hours).

| View | A, M ₸/yr | A − measured | Battery D−A, M ₸/yr | by hours | NPV incl. O&M + replacement, M ₸ | Payback simple / disc., yr | Page default B−A, M ₸/yr |
|---|---:|---:|---:|---:|---:|---:|---:|
| optimiser, engines free | 132.6 | -42.4 | **5.0** | 5.1 | -690 ($-1,500k) | never / never | -3.9 |
| optimiser, availability as measured | 161.5 | -13.5 | **8.2** | 8.3 | -632 ($-1,373k) | never / never | 0.9 |
| engines as logged + battery by rule | — | — | **6.4** | 6.2 | -666 ($-1,447k) | never / never | — |

## Three engines as one pool (ЖКПЗ + Жаркент 3)

135 fully measured days, 2025-10-23 – 2026-10-04; months with no measured day, filled from their neighbours: [2, 12]. Over those days: load 7,308 MWh, bought 1,356 MWh, sent to the city 309 MWh.

Measured operation, priced as a scenario: **640.3 M ₸/yr** (614.4 scaled by hours).

| View | A, M ₸/yr | A − measured | Battery D−A, M ₸/yr | by hours | NPV incl. O&M + replacement, M ₸ | Payback simple / disc., yr | Page default B−A, M ₸/yr |
|---|---:|---:|---:|---:|---:|---:|---:|
| optimiser, engines free | 445.3 | -195.0 | **4.0** | 4.5 | -707 ($-1,537k) | never / never | 2.8 |
| optimiser, availability as measured | 521.1 | -119.2 | **14.2** | 14.6 | -524 ($-1,140k) | never / never | 12.9 |
| engines as logged + battery by rule, no bus netting (credits the battery with a wire's work) | — | — | **34.0** | 37.0 | -170 ($-369k) | 21.6 / never | — |
| engines as logged + battery by rule, common bus (export offsets the other plant first) | — | — | **19.7** | 21.3 | -427 ($-929k) | never / never | — |

US$ at 460 ₸/$. Annual figures are weighted by calendar month; 'by hours' is the study page's own scaling of the kept days to a year.

