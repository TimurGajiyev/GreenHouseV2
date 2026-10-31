# Zharkent app — his method, rebuilt and compared

Notes on a colleague's Streamlit app at <https://zharkent.tail042aa5.ts.net/>, as of 29 Oct 2026.

**How it was examined**
- Every control was opened in a browser and every "?" note was read, in English and in Russian.
- The source of the app's three HTML pages was read.
- His published run files were downloaded:
  - the per-step decisions: 220,657 five-minute steps;
  - the yearly results: 480 rows.
- His method was then **rebuilt in [recreate.py](recreate.py) and checked against his own numbers**.

The server code (Python, `inputs.py`) is not visible from outside. Everything below comes from what the app publishes.

**What came out**

1. **The rebuild is exact, on both of his published runs and on four new runs made on 29 Oct.**
   - His two runs use different batteries: 3 MWh × 0.33 C and 3 MWh × 0.5 C.
   - The four new runs each changed one input: export allowed, band 80 %, grid 60 KZT/kWh, and no gap filling ([WALKTHROUGH.md](WALKTHROUGH.md), sections 6–7).
   - In every one of them, every 5-minute step agrees in 100 % of steps on all three plants: each engine's output, on/off state, battery charge and grid import.
   - His yearly figures are reproduced to within 0.01 %.
   - Every size that his results mark "in the band" (the ones he reports) is within 0.011 % of his saving.
2. **Most of his saving is not the battery.** On the starch plant (Krakhmal = ЖКПЗ) he reports **90.5 M KZT/yr** for a 3 MWh battery.
   - His own rule **with no battery** already saves **77.1 M** of that, because it lets engines replace grid import at any hour.
   - The battery's own share is **13.5 M**: 14.7 M when the engines can run only in the hours they actually ran.
3. **On his own model, with the battery credited only with its own share, no battery size pays back on Krakhmal before it wears out.** The shortest payback is 17–19 years against an 11–14-year life. That is the same answer GreenHouse gives for ЖКПЗ.
4. **Meshki and Joined look different.** On Meshki (Жаркент 3) 6–8 sizes pay back, and on Joined (both plants on one battery) 13–14 do. Joined assumes a cable between the two plants that he does not cost.

**Files**
- [recreate.py](recreate.py) rebuilds his rule from his published data.
- [WALKTHROUGH.md](WALKTHROUGH.md) is the log of the full click-through and the scenario runs, in Russian.
- [screens/](screens/) holds the screenshots: `app/`, `report/`, `data/`, `today/` and `runs/`, plus `first-pass/` from the first visit.
- His published files and the page sources are kept locally in `.playwright/output/zharkent/` and `.playwright/output/` (git-ignored, because they are his material).

| Command | What it does |
|---|---|
| `python docs/zharkent-app/recreate.py` | his default run, checked step by step (≈ 10 s) |
| `python docs/zharkent-app/recreate.py sizes` | all 24 sizes against his results (≈ 1 min) |
| `python docs/zharkent-app/recreate.py split` | what the default battery's saving is made of |
| `python docs/zharkent-app/recreate.py alone` | the battery's own saving for every size (≈ 2 min) |

---

## 1. The three entities

| In the app | Ours | Engines | Grid connection |
|---|---|---|---|
| **Krakhmal** (K, «Крахмал») | ЖКПЗ | MWM / Tedom Quanto 1200 («Жаркент», 1,200 kW) + Jenbacher JMC 320 («Жаркент 2», 1,066 kW) | ЖКПЗ |
| **Meshki** (M, «Мешки») | Жаркент 3 | Jenbacher JMC 320 («Жаркент 3», 1,066 kW) | Универсал |
| **Joined (one battery)** | ALL3 | all three engines, both loads behind one battery | "the cable between the entities is not costed" |

---

## 2. What he says he is doing (his texts and "?" notes)

- **The question:** which battery size, and how fast it pays back. He answers it by replaying the measured year through a simple controller, not an optimiser:
  > The rule: an engine runs only if it can work at or above the band, or if the other engines plus the battery cannot cover the load. Engines are taken as always available. Every 5 minutes of measured data where the power balance closes is simulated (gaps up to the fill limit bridged); stretches of data start at 50 % charge with the engines as measured. Today's operation is costed on the same 5-minute steps, so the comparison is like for like. Battery life = cycle life ÷ cycles a year, capped at the calendar life; a size counts only if it pays back before it wears out.
- **Who set what.** Every input carries a source and a status.
  - "Richard, 14 Oct 2026" set:
    - the 90 % band, no export, and all engines allowed to stop;
    - the gas and grid prices;
    - the battery and inverter prices.
  - "Richard, 15 Oct 2026" set that Krakhmal's December and February are never filled.
  - The service rate of 6 KZT/kWh is, in the Russian note, «ставка, которую сервисная компания предъявляет клиентам», the rate the service company charges clients. He uses it only to price an engine hour.
- **Placeholders.** Most rule and battery parameters are placeholders «из передаточной записки», from a **handover note**: start wear, round-trip efficiency, charge window, own use, minimum run/off and charge taper. 15 of 41 inputs are placeholders. The Today page says: "do not quote any [money figure] to the client until they are replaced."
- **Two statements that the numbers contradict:**
  - The English note on the band says "the **optimiser** runs engines only in the efficient band". There is no optimiser: decisions are made by a fixed rule (section 3), and the Russian note does not say "optimiser".
  - The Data page says "Hours without a value are left empty, not filled in". The battery scenario, however, bridges gaps up to 3 h with a straight line.

---

## 3. His method, rebuilt from his numbers

### 3.1 How

His run "Default inputs" (16 Oct 2026 13:51) publishes two files:
- every simulated 5-minute step, with the measured load and engines (the input) and his rule's engines, battery and import (the output), plus the decision text;
- the yearly results for every size.

The rule was read off the eight kinds of decision text in his file:

| Decision text | Steps |
|---|---:|
| hold | 216,224 |
| STOP Zharkent | 1,340 |
| START Zharkent | 1,233 |
| START MWM | 499 |
| STOP MWM | 497 |
| new stretch of data | 405 |
| … no unit free to start: import | 298 |
| engines below the 90 % band | 161 |

The remaining details were then fitted until each step matched: which engine is chosen, the minimum times, the charge taper, the forced stops and how starts are counted.

### 3.2 The rule, exactly

For each 5-minute step in which the measured power balance closes (load = engines + grid):

0. **New stretch** (a gap before the step): charge 50 %; each engine on or off as the meters show it (on above 50 kW).
1. **Need** = load + 15 kW (the battery's own use).
2. **Battery limits:**
   - it can give min(P, (charge − 10 %) × E × √0.88 ÷ 5 min);
   - it can take min(P × min(1, (100 % − charge) ÷ 15 %), (95 % − charge) × E ÷ √0.88 ÷ 5 min).
3. **Short:** if the rated output of the running engines plus what the battery can give is below need, **start** the engine that has been off **longest** (it must have been off at least 15 min). If that is still not enough, start the next one in the same step. If none can start, **import** the gap.
4. **Surplus:** if 90 % of the running engines' rated output exceeds need plus what the battery can take, **stop** the engine that has run **longest** (it must have run at least 30 min), but only if the others plus the battery still cover need. If none can stop, the engines go below the band.
5. **Forced stop:** if even 50 % of rated output exceeds need plus what the battery can take, stop the longest-running engine whatever the cover.
6. **Output:**
   - the engines make min(running rated output, need + what the battery can take), never below 50 %, shared in proportion to rating;
   - a surplus over need charges the battery;
   - a shortfall is discharged up to what the battery can give;
   - the rest is imported. Export happens only when allowed, and it is off by default.
7. **Charge** += (charge power × √0.88 − discharge power ÷ √0.88) × 5 min ÷ E.

So **engines run at full output whenever they run** (96 % of running steps are at 100 %), and the battery absorbs the difference.
- The "band" only decides when an engine is stopped.
- The longest-off / longest-running choice spreads hours evenly over the engines.
- The minimum run of 30 min and minimum off of 15 min are short: no run in his year is shorter.

### 3.3 Costing and the year

- **Fuel:** a straight-line fuel curve through rated × load ÷ efficiency at 50, 75 and 100 %:
  - MWM: 600 → 1,492.5, 900 → 2,122.6, 1,200 → 2,752.3 kW of gas;
  - Jenbacher: 533 → 1,346.0, 799.5 → 1,908.1, 1,066 → 2,467.6 kW of gas;
  - below 50 % load, the 50–75 % slope is extended.

  Gas costs 75 KZT/m³ ÷ 1.12 ÷ 9.44 = **7.094 KZT per kWh of gas**.
- **Service** = engine hours × hourly rate + start wear × starts × hourly rate.
  - The hourly rate is 6 KZT/kWh × rated output: MWM 7,200 KZT/h, Jenbacher 6,396 KZT/h.
  - An engine hour is a 5-minute step above 50 kW.
  - A start is an off-to-on change inside a stretch. It also counts when the rule switches on, at a stretch's first step, an engine the meters show off.
- **Grid** = import × 50 ÷ 1.12 = **44.64 KZT/kWh**. Export earns nothing.
- **A year:**
  - each month is multiplied by its hours ÷ its complete hours;
  - months below 25 % complete hours are dropped;
  - the year is the mean of the remaining months × 12.

  On Krakhmal, June is multiplied by 2.85 and January by 1.71, and the total by 12/9 for December, February and July.

### 3.4 How close the rebuild is

Default inputs, the default battery (3 MWh × 0.33 C = 0.99 MW), in M KZT a year:

| | Krakhmal: his / rebuilt | Meshki: his / rebuilt | Joined: his / rebuilt |
|---|---:|---:|---:|
| 5-minute steps, all matching | 65,770 | 94,153 | 60,734 |
| Today | 449.0 / 449.0 | 169.5 / 169.5 | 600.7 / 600.7 |
| With battery and rule | 358.5 / 358.5 | 143.4 / 143.4 | 473.6 / 473.6 |
| Saving | 90.5 / 90.5 | 26.1 / 26.1 | 127.2 / 127.2 |
| Engine starts a year | 899.2 / 899.2 | 741.3 / 741.3 | 887.7 / 887.7 |
| Battery cycles a year | 699 / 699 | 688 / 688 | 643 / 643 |
| Payback, years | 3.02 / 3.02 | 10.46 / 10.46 | 2.15 / 2.15 |

Every figure agrees to within 0.01 %.

**An independent check.** The rule was read off this run (3 MWh × 0.33 C). It was then run unchanged on his other run, 29 Oct, with a different battery: 3 MWh × 0.5 C = 1.5 MW.
- All steps match there too, on all three plants: engines, charge and import in 100 % of steps.
- Saving 91.71 vs his 91.72 M (Krakhmal), 26.48 vs 26.48 (Meshki), 125.01 vs 125.02 (Joined).
- Starts and payback agree as well.

That check exposed the one rule detail first missed: two engines started in the same step. It was fixed in step 3 above.

**All sizes.** Every size his results mark in the band is within 0.011 % of his saving: 54 sizes in the default run and 18 in the other.

9 small, low-power sizes differ more (for example 1 MWh × 0.25 C). His results mark all of them "not in the band", so his charts leave them out. Their step data is not published, so their last details could not be fitted.

### 3.5 His result formulas, checked on every row

All 15 hold on all 480 result rows of both published runs.

- **Battery price** = (kWh × 150 + kW × 120) USD × 480 KZT/USD. There are no other costs.
- **Cost:**
  - cost = fuel + service + grid;
  - fuel = kWh of gas × 7.094;
  - grid = import × 44.64;
  - service = Σ engine hours × rate + start wear × Σ starts × rate.
- **Saving** = today − cost with battery.
  - The *running in the band* part = (today's − the rule's KZT per kWh made) × today's generation.
  - The *replacing import* part = saving − the band part.
  - KZT per kWh made = (fuel + service) ÷ generation.
- **Payback** = price ÷ saving. This is simple payback: no discounting, escalation, battery O&M or replacement.
- **Cycles** = energy discharged ÷ (0.85 × capacity).
- **Life** = min(6,000 ÷ cycles, 15 years).
- **Profit over life** = saving × life − price.
- **In the band** ⇔ hours below the band ≤ 1 % of engine hours.
- **Pays back** ⇔ payback ≤ life.

---

## 4. What his numbers say

### 4.1 His saving, taken apart with his own model

His rule was run with no battery, and every case was run again with each engine allowed only in the steps the meters show it running (above 50 kW). Default battery 3 MWh × 0.33 C, price 273.0 M KZT; M KZT a year:

| | Krakhmal | Meshki | Joined |
|---|---:|---:|---:|
| **His saving** (today − rule with battery) | **90.5** | **26.1** | **127.2** |
| *Engines always available (as he has it):* | | | |
| the rule alone, no battery, saves | 77.1 | −5.3 | 78.6 |
| the battery's own share | **13.5** | 31.4 | 48.6 |
| payback on that share | 20.2 y | 8.7 y | 5.6 y |
| *Engines only when the meters show them running:* | | | |
| the rule alone saves | 33.3 | −15.1 | 50.3 |
| rule with battery saves | 48.0 | 12.7 | 88.0 |
| the battery's own share | **14.7** | 27.8 | 37.6 |
| payback on that share | 18.6 y (life 10.9 y) | 9.8 y | 7.3 y |
| import left with the battery, MWh/yr (his: 38 / 0.3 / 0.3) | 1,858 | 770 | 1,572 |

- **Krakhmal:** 85 % of his saving (77.1 of 90.5 M) needs no battery.
  - It comes from running the engines at full output whenever they are on, and starting one whenever the load needs it, at hours when today the plant imported instead.
  - Limited to the hours the engines really ran, the battery's own share is about the same (14.7 M), and its payback of 18.6 years is longer than its 10.9-year life.
- **Meshki:** his rule *without* a battery costs more than today, so the battery's share against the rule (31.4) overstates it. His own saving against today (26.1, or 12.7 with engines as they actually ran) is the fair figure. He reports 10.5 years, which wears out first.
- **Joined:** the battery's own share is large (38–49 M), but it needs both plants on one bus, and the cable is not costed.

### 4.2 Every size, battery alone

The battery's own saving is (rule alone) − (rule with battery), for all 24 sizes:

| Entity · engines | Battery's own saving, M KZT/yr | In-band sizes paying back before wear-out | Shortest payback |
|---|---|---:|---|
| Krakhmal · always available | −27.1 … 26.7 | **0 of 18** | 4 MWh × 0.25 C: 18.8 y (life 11.1) |
| Krakhmal · as the meters show | −16.4 … 28.1 | **0 of 18** | 4 MWh × 0.25 C: 17.1 y (life 14.0) |
| Meshki · always available | −33.0 … 41.8 | 8 of 18 | 3 MWh × 0.33 C: 8.7 y (life 8.7) |
| Meshki · as the meters show | −18.6 … 37.7 | 6 of 18 | 3 MWh × 0.33 C: 9.8 y (life 10.4) |
| Joined · always available | −72.2 … 59.4 | 13 of 18 | 2 MWh × 0.5 C: 5.0 y (life 6.2) |
| Joined · as the meters show | −53.1 … 52.4 | 14 of 18 | 2 MWh × 0.5 C: 6.7 y (life 7.5) |

*Paying back before wear-out* is his own test (payback ≤ life, engines in the band). It still uses his simple payback with no discounting; with discounting and O&M fewer sizes would pass.

### 4.3 From his answer to GreenHouse's, one assumption at a time

Krakhmal / ЖКПЗ. Steps 1–5 use his own model, rebuilt; step 6 is GreenHouse.

| Step | Battery saving, M/yr | Payback |
|---|---:|---|
| 1. His headline: 3 MWh / 0.99 MW, grid 50, engines always available, saving = today − (rule + battery) | 90.5 | 3.0 y simple (273 M) |
| 2. Count only the battery's own share = (rule alone) − (rule + battery) | **13.5** | 20.3 y > 8.6 y life: **never** |
| 3. Engines only in the hours the meters show them running | 14.7 | 18.6 y > 10.9 y life: never |
| 4. Our battery, 5.5 MWh / 2.5 MW | 25.1 | 21.5 y at his unit prices (540 M), 15.6 y at our 391 M |
| 5. Our grid price, 60 KZT/kWh | 32.3 | 12.1 y simple at 391 M, but below the 43.5 M/yr that O&M, replacement and discounting require: **never** |
| 6. GreenHouse: an optimiser, not his rule, as the dispatch the battery is measured against | 16.1 … 22.1 | never (break-even 43.5 M/yr) |

Step 2 alone removes his payback: 77.1 of his 90.5 M is the rule running the engines at full output, available at any hour, in place of grid import, which needs no battery. The other steps move the battery's own share between 13.5 and 32.3 M/yr; none of it reaches the 30–60 M/yr that our finance needs for a battery of 273–540 M (30.4 M at 273 M, 43.5 M at 391 M, 60.1 M at 540 M).

### 4.4 Other things the numbers show

- **The ceiling.** His Today page puts the most that full-output running could save at 33.4 M (Krakhmal) and 27.1 M (Meshki) KZT/yr. His *running in the band* part stays inside it (29.3 M on Krakhmal). The rest of his saving is import replacement.
- **Import.** With the battery, Krakhmal's import falls from 3,318 MWh to 21–100 MWh a year across the sizes. The engines take over almost all of it, including hours in which the meters show the engines stopped.
- **"Best" means shortest payback,** which favours batteries that wear out fast.
  - Krakhmal's best is 2 MWh × 0.5 C: 2.4 y, life 5.8 y, profit over life 278 M.
  - The most profitable size is 5.5 MWh × 0.25 C: 1,001 M over its life.
  - In the 29 Oct run the best was 1 MWh × 1 C: life 3.0 y, 2,322 starts a year against 635 today.
- **Small sizes are erratic** under the rule. On Joined, 1 MWh gives 45, 2.5 and 49 M at 0.25, 0.33 and 0.5 C.
- **Start wear** (a 4-hour placeholder) moves the payback:
  - Krakhmal 2 MWh × 0.5 C: 2.05 y at 0 h to 3.04 y at 8 h;
  - Meshki 3 MWh × 0.33 C: 6.7 y to 24.0 y.

### 4.5 His values on the GreenHouse page

The Custom dispatch study now has a switch at its top, **Scenario values → Colleague's app (Zharkent)**. It sets every input to his and adds a rule C (the 90 % rule without the battery). Press **Solve scenarios**: about 6 minutes on one plant. Full account: `REPORT.md`, Part 18, "Revised 31.10.2026".

| Per year, M KZT, ours / his | Krakhmal | Meshki | Joined |
|---|---:|---:|---:|
| Today | 453.0 / 449.0 | 175.8 / 169.5 | 605.4 / 600.7 |
| With 3 MWh | 346.7 / 358.5 | 149.8 / 143.4 | 469.6 / 473.6 |
| Saving against today | 106.3 / 90.5 | 26.0 / 26.1 | 135.8 / 127.2 |
| Price ÷ saving, years | 2.6 / 3.0 | 10.5 / 10.5 | 2.0 / 2.1 |
| Same hours: today | −0.8 % | −0.6 % | −0.6 % |
| Same hours: with the battery | −3.0 % | +0.5 % | −2.3 % |

- His framing gives his answer on our engine: his payback is real arithmetic on his assumptions.
- What is left is method. An optimiser beats his rule where it has engines to choose between (Krakhmal, Joined). On Meshki, one engine under its 90 % floor has to cycle, which he does in 5-minute steps with charge carried overnight, and our hours and closed days cannot.
- The same run shows the split he does not: on Krakhmal, 81.2 of the 106.3 is the rule and 25.1 the battery.
- New question for him: his J320 is 1,066 kW at 43.2 / 39.6 %, the passport 1,067 kW at 40.5 / 37.4 %, about 6 % more gas. Where does his figure come from?

Reproduce: `python calculator/tools/test_colleague_values.py --compare=K` (or `M`, `KM`).

---

## 5. How his approach differs from yours (GreenHouse)

| | His (Zharkent app) | Yours (GreenHouse custom dispatch study) | What it does to the answer |
|---|---|---|---|
| **What a saving is** | today as measured − rule with battery | the same dispatch with and without the battery (A vs D), on the same days | His figure includes everything the rule changes besides the battery: 77 of 90.5 M on Krakhmal |
| **Dispatch** | fixed rule, decides one step at a time, no look-ahead | MILP optimiser (HiGHS), unit commitment, a whole day at once | A battery measured against a weak rule looks better than against an optimal plan. Your optimiser without a battery already saves 56–70 M ₸/yr over today; his rule alone, engines as they ran, saves 33 M |
| **Engine availability** | always available | as logged by default, "always available" as an option | On his own model the rule alone saves 77.1 M with engines always available and 33.3 M as logged |
| **Engine operation** | full output when on, 90 % band, all may stop; min run 30 min, min off 15 min | 50 % minimum load, part load priced on the OEM curve; min up 4 h, down 5 h (NOT CONFIRMED) | His engines start and stop far more often: 899 starts a year against 635 today |
| **Start cost** | 4 engine hours × hourly rate = 28,800 KZT (MWM), 25,584 KZT (Jenbacher) | 15,000 ₸ | His start costs about twice yours |
| **Time step** | 5 minutes | 1 hour | His battery sees swings within the hour that yours averages out, a real advantage of his. But before mid-September 2026 his grid is a ~55-minute average, so part of those swings is an artefact (load 2,151 = 943 + 1,048 at 5 min + 160 window average) |
| **Data used** | every 5-minute step where the balance closes: 5,481 h on Krakhmal | days of 24 complete hours: 4,464 h on ЖКПЗ | Similar coverage; his has more scattered short stretches (71 on Krakhmal, each starting at 50 % charge) |
| **Gaps** | bridged by a straight line up to 3 h | never filled; a reading the logger missed is taken from the same hour's balance and flagged | Small, but it is invented data in his case |
| **A year** | each month × hours ÷ complete hours; dropped months filled by the mean (× 12/9) | month-weighted; a month not measured makes the year a range | His single figure hides that Krakhmal's December and February are unknown |
| **Prices** | grid 44.64 KZT/kWh ex VAT; gas 7.094 KZT/kWh of gas + 6 KZT/kWh service ≈ 22.3 KZT/kWh at full load | grid 60 ₸/kWh; gas 22 ₸/kWh at full load | Engine cost is about the same. A higher grid price makes import replacement worth more in yours |
| **Battery** | 3 MWh × 0.33 C, 273 M KZT = (kWh × 150 + kW × 120) USD × 480; no other costs | 5.5 MWh / 2.5 MW at the project CAPEX of 391 M ₸ | |
| **Battery life** | cycles: 6,000 ÷ cycles a year, at most 15 y | 25-year horizon, replacement in year 10 | His captures wear-out by cycling, which yours does not |
| **Finance** | simple payback, profit over life | 25 years, escalation 3.4 %, discount 6.24 %, NPV, O&M 2.5 %/yr | His paybacks are short partly because nothing is discounted and the battery costs nothing to keep |
| **Answer for ЖКПЗ** | 3.0 y (default battery), 2.4 y ("best") | never pays back (16–22 M ₸/yr against 43.5 needed) | On his own model with the battery's own share, 17–20 y against a 10–14 y life: **never**, the same as yours |

**Where his is stronger:**
- the 5-minute resolution;
- a written reason for every step;
- explicit placeholder flags on every input;
- battery life from cycling, and the start-wear sensitivity;
- a sweep of 24 sizes.

**Where yours is stronger:**
- the counterfactual: the battery against the same dispatch without it;
- an optimal dispatch to measure against;
- availability as logged;
- no invented data;
- honest ranges for months not measured;
- discounted 25-year economics.

---

## 6. Bugs found while clicking

| # | What | How to see it | Effect |
|---|---|---|---|
| 1 | **Switching the language drops every compared size with a decimal point.** RU → EN turns capacities 1, 2, 3, 4, 5.5, 7 into 1, 2, 3, 4, 7, and C-rates 0.25, 0.33, 0.5, 1 into 1 C only. | Sidebar → RU → EN, then open *Other sizes*. | His 29 Oct run compared exactly these sizes and carries the Russian default name «Сценарий». It was very likely made after a language switch, without meaning to. |
| 2 | **The day chart can show the previous entity** while the new entity's month file loads, and raises `TypeError: Cannot read properties of undefined (reading 'meas')`. | Switch Krakhmal → Meshki → Joined before the month has loaded. | Reproduces every time: 4 of 4 tab switches in the report, and 4 times during the scenario runs. It settles once the file arrives. |
| 3 | **The step panel prints the load 15 kW low** (*Load 1 949 kW* where the simulation used 1 964 + 15). The line labelled *Load + battery's own use* plots the load alone. | Click a day-chart column and compare it with the decision text. | Display only; the simulation is right. |
| 4 | **Run scenario with inputs identical to an earlier run adds no run.** After about 30 s it opens the earlier run instead, and the new name is dropped without a message. | Rename the scenario and press *Run scenario* with the defaults (WALKTHROUGH S5). | Confirmed twice. It is behaviour, probably matching by an input fingerprint (the hidden *fp* column), not a fault, but the page does not say so. |

---

## 7. Questions for the author

1. Could the saving be reported against **the same rule without a battery**? On his own model that cuts Krakhmal's battery saving from 90.5 to 13.5 M KZT/yr.
2. Could there be an option for **engines only in the hours the meters show them running**? Today's import partly happened while engines were down.
3. The **gap filling** (straight lines up to 3 h) and the **month scaling** (June × 2.85, dropped months filled by the mean) both make data that was not measured. Would a range for the missing months be acceptable?
4. Before mid-September 2026 the 5-minute load mixes 5-minute engines with an hour-long grid average. Could the load be built at the window's resolution there?
5. Could "best" be the most **profit over life**, or a discounted NPV with O&M and installation, rather than the shortest payback?
6. Who supplies the 15 placeholders, the handover note's values in particular (start wear, minimum run/off, RTE, charge window)?

---

## Appendix A. Results as he reports them

### Default inputs (16 Oct 2026 13:51; nothing changed from `inputs.py`)

| | Krakhmal | Meshki | Joined |
|---|---:|---:|---:|
| Today, M KZT/yr | 449.0 | 169.5 | 600.7 |
| Default battery 3 MWh × 0.33 C: saving / payback / life | 90.5 M / 3.0 y / 8.6 y | 26.1 M / 10.5 y / 8.7 y ✕ | 127.2 M / 2.1 y / 9.3 y |
| — running in the band / replacing import | 29.3 / 61.2 | 5.0 / 21.1 | 52.1 / 75.0 |
| "Best" (shortest payback) | 2 MWh × 0.5 C: 2.4 y, life 5.8 y | 4 MWh × 0.25 C: 11.3 y, life 11.5 y | 1 MWh × 1 C: 1.4 y, life 3.2 y |
| Most profit over life | 5.5 MWh × 0.25 C: 1,001 M | 5.5 MWh × 0.25 C: 49 M | 5.5 MWh × 0.25 C: 1,588 M |
| Saving across the 24 sizes, M KZT/yr | −3 to 104 | −79 to 36 | 3 to 138 |

### Latest run (29 Oct 2026 04:30, «Сценарий»)

The sizes were reduced to 1, 2, 3, 4, 7 MWh × 1 C (bug 1). His battery was 3 MWh × 0.5 C:
- Krakhmal 91.7 M/yr, 3.3 y;
- Meshki 26.5 M, 11.4 y ✕;
- Joined 125.0 M, 2.4 y.

### Today (his *Today* page)

| | Krakhmal | Meshki |
|---|---:|---:|
| Months used | 9 (Dec 25, Feb 26, Jul 26 dropped) | 12 |
| Cost, M KZT/yr: fuel + service + grid | 190.9 + 110.0 + 148.1 = **449.0** | 83.2 + 47.3 + 39.1 = **169.5** |
| Import, MWh/yr | 3,318 | 875 |
| Engines | MWM 6,477 h, 329 starts, loading 62 %; Zh2 7,202 h, 305 starts, 85 % | Zh3 6,726 h, 166 starts, 68 % |
| MWM hours by load: < 50 % / 50–75 % / 75–90 % / ≥ 90 % | 2,128 / 1,689 / 2,627 / 33 | — |
| "Full-output running could save at most" | 33.4 M | 27.1 M |

Measured energy by month, Krakhmal (his *Data* page):

| Month | MWM MWh | Zh2 MWh | Import MWh | Export MWh | Complete hours |
|---|---:|---:|---:|---:|---:|
| Sep 2025 | 277 | 131 | 107 | 118 | 651 / 720 |
| Oct 2025 | 506 | 553 | 138 | 44 | 597 / 744 |
| Nov 2025 | 413 | 584 | 302 | 0 | 679 / 720 |
| Dec 2025 | 0 | 194 | 638 | 0 | **0 / 744** |
| Jan 2026 | 154 | 478 | 416 | 0 | 411 / 744 |
| Feb 2026 | 0 | 244 | 523 | 14 | **0 / 672** |
| Mar 2026 | 307 | 687 | 351 | 27 | 614 / 744 |
| Apr 2026 | 517 | 660 | 126 | 0 | 626 / 720 |
| May 2026 | 415 | 563 | 126 | 2 | 576 / 744 |
| Jun 2026 | 159 | 189 | 191 | 51 | 220 / 720 |
| Jul 2026 | 167 | 420 | 270 | 0 | 154 / 744 |
| Aug 2026 | 381 | 469 | 283 | 2 | 589 / 744 |
| Sep 2026 | 275 | 379 | 263 | 35 | 711 / 720 |
| Oct 2026 | 1 | 103 | 44 | 55 | 325 / 326 |

---

## Appendix B. The page, control by control

### Sidebar — every input and its "?" note

| Control | Default | Range / options | His note (EN; RU adds where noted) | Status |
|---|---|---|---|---|
| Language / Язык | EN | EN, RU | — (switching it triggers bug 1) | — |
| View | Battery scenarios | Battery scenarios · Data · Today | "Battery scenarios: run the rule with any inputs. Data: the measured data hour by hour. Today: what the plant costs now, from the meters." | — |
| Scenario name | Scenario | text | "Your label for this run; it shows in the run history." | — |
| Capacity, MWh | 3.00 | 0.5–30, step 0.5 | "This battery gets the cards, the 5-minute decisions and the day charts." | — |
| C-rate | 0.33 C | 0.2, 0.25, 0.33, 0.5, 0.75, 1, 1.5, 2 C | "Power = capacity × C-rate. 0.5 C: a full battery empties in 2 hours at full power; 1 C: in 1 hour." | — |
| Band: engines run at least at, % of rated | 90 | 50–100 | "Richard, 14 Oct 2026: the optimiser runs engines only in the efficient band (datasheet floor is 50 %)." RU: «ГПУ работают только в эффективном диапазоне» (no "optimiser"). | confirmed |
| Start wear, engine hours per start | 4.00 | 0–20 | "Handover placeholder. To be set by the service company (warm vs cold)." RU: «Заглушка из передаточной записки». | placeholder |
| Service, KZT per kWh at rated output | 6.00 | 0–30 | "Service company's presented figure; used only to set the cost per engine hour. Cost per engine hour = this × rated kW." RU: «ставка, которую сервисная компания предъявляет клиентам». | confirmed |
| Allow export (not compensated) | off | tick-box | "Richard, 14 Oct 2026: export forbidden by default; also run with it allowed." | confirmed |
| Bridge data gaps up to, hours | 3.00 | 0–24 | "Gaps in one signal up to this long are bridged by a straight line between the readings either side (tagged 'filled'); longer gaps stay empty. Krakhmal's December 2025 and February 2026 are never filled. 0 = no filling." | confirmed |
| Gas, KZT/m³ incl. VAT | 75.00 | 1–500 | "Richard, 14 Oct 2026." | confirmed |
| Grid, KZT/kWh incl. VAT | 50.00 | 1–200 | "Richard, 14 Oct 2026; flat, no capacity charge assumed." | confirmed |
| VAT, % | 12.00 | 0–30 | "Kazakhstan VAT 12 %; prices below are taken EX VAT (client recovers input VAT)." | confirmed |
| Gas heating value, kWh/m³ | 9.44 | 8–11 | "Tedom technical sheet basis 34 MJ/m³ (Jenbacher uses 9.5); confirm from supply contract." | datasheet |
| Capacities, MWh | 1, 2, 3, 4, 5.5, 7 | multi-select | "Battery capacities compared in every run (each with every C-rate below)." The note under it: "24 combinations, plus your battery … about a second each on the server." | confirmed |
| C-rates | 0.25, 0.33, 0.5, 1 C | multi-select | "C-rates compared in every run; 0.33 C on 3 MWh = 1 MW." | confirmed |
| Battery, USD per kWh | 150 | 0–1000 | "Richard, 14 Oct 2026." | confirmed |
| Inverter, USD per kW | 120 | 0–1000 | "Richard, 14 Oct 2026." | confirmed |
| KZT per USD | 480 | 100–1000 | "Placeholder exchange rate." | placeholder |
| Cycle life, full cycles | 6000 | 1000–20000 | "Battery life in cycles; life in years = this ÷ cycles a year (capped at the calendar life). Typical LFP warranty figure; replace with the supplier's." | placeholder |
| Calendar life, years | 15 | 5–30 | "A battery ages even when it cycles little; its life never exceeds this." | placeholder |
| Round-trip efficiency, % | 88 | slider | "Handover placeholder; applied as √RTE each way." | placeholder |
| Usable charge window, % | 10 – 95 | range slider | "Handover placeholder." | placeholder |
| Battery's own consumption, kW | 15 | 0–200 | "Handover placeholder: cooling and controls." | placeholder |

- **Changed from inputs.py: …** lists the inputs that differ from the defaults file. Ticking export shows "Export allowed", and a grid price of 60 shows "Grid price incl. VAT". The inspected battery's capacity is not an `inputs.py` value, so changing it shows nothing.
- **Run scenario** runs the rule for the inspected battery and every size, and adds a run to the history (bug 4).
- **Inputs his runs use that have no control in the sidebar:**
  - fuel below 50 % (placeholder);
  - running threshold 50 kW (placeholder);
  - KZT per EUR 520 (placeholder, display only);
  - start-wear values compared 0, 1, 2, 4, 8 (placeholder);
  - other battery costs 0 (confirmed);
  - all engines may stop (confirmed);
  - minimum run 0.5 h and minimum off 0.25 h (placeholders);
  - charge taper 85 → 100 % (placeholder);
  - datasheet minimum 50 % (datasheet);
  - allowed time below the band 1 % (confirmed);
  - study year Oct 2025 – Sep 2026 (confirmed);
  - never filled: Krakhmal Dec 2025 and Feb 2026 (Richard, 15 Oct 2026);
  - month coverage 25 % (placeholder).

### View "Battery scenarios"

- **Run history:** one row per run, with columns
  - *show*, which displays that run's report (more than one can be ticked);
  - *delete* (not touched);
  - name, time, battery;
  - the best size per entity;
  - *changed*, the inputs that differ from `inputs.py`.

  A hidden column *fp* would not display. The toolbar has show/hide columns, download as CSV (opens the browser's save dialog), search and full screen. On 29 Oct the history held 9 runs.
- **Files:** each run has `report.html`, `results.csv` (one row per entity × size × start-wear value) and `decisions.csv.gz` (every step, with the reason in English and Russian and each value's source: `c` CSV, `m` myPlant window, `f` filled).
- **The report:**
  - **Header:** the run name, the inspected battery, the start wear, the band, and a red list of the placeholders in use.
  - **Tabs:** Krakhmal · Meshki · Joined.
  - **Three cards:** today, your battery, the shortest payback. Clicking a card shows its arithmetic.
  - **Every chart** has a "?" note, a button per series that hides or shows it, and *show all*.

    | Chart | Click |
    |---|---|
    | Payback by battery size | a point → that size's arithmetic |
    | Profit over the battery's life | a point → arithmetic |
    | Where the saving comes from (band / import, with a C-rate switch) | a bar → arithmetic |
    | Engine starts per year (today dashed) | none |
    | Day chart every 5 minutes, measured above and with the rule below, plus charge %; ◀ ▶ and a date box (days without data are skipped) | a column → the decision and each value's source |
    | Start wear (payback at 0–8 engine hours per start) | none |
    | Wear per year: engine starts vs battery cycles | a point → wear arithmetic |
    | Wear per year by battery size (with a C-rate switch) | a bar → wear arithmetic |
  - **Inputs of this run:** all 41 inputs with value, source and status.
  - **Buttons:** RU/EN and the dark/light theme, both remembered in the browser.

### View "Data"

A static page with no simulation:
- month buttons with the share of complete hours per entity;
- monthly energy bars;
- an hour-by-hour month chart;
- a 5-minute day chart with ◀ ▶ and a date box, and summary cards;
- a monthly table.

Hovering shows each value and its source. Its footer gives the sources:

> Engine power comes from the unit CSV (hourly average of the 5-minute readings). For the two Jenbachers, if the CSV has no reading, it comes from myPlant. Grid exchange comes from myPlant (the window of about 55 minutes that contains each clock hour). From mid-September 2026 it comes from the CSV. The MWM is only in the CSV. Hours without a value are left empty, not filled in. A myPlant record that stays at the same non-zero value for more than about an hour is a frozen logger, not data, and is left out. Load is calculated as engines + grid, and only for hours where every piece is known. Meshki's myPlant clock is shifted by +1 h to match the CSV.

### View "Today"

A static page "built with the default inputs", with nothing simulated. Each number shows its month-by-month arithmetic on hover (Appendix A).

### Main menu (⋮)

*Print* and *Record screen* only.

---

## Appendix C. What was done, and what was not

- **Opened:**
  - every sidebar control and its "?" note, in English and Russian;
  - the three views;
  - the run history and its toolbar;
  - every report card, chart click, series toggle, C-rate switch, day control, language and theme button;
  - every "?" and hover on the Data and Today pages.
- **Changed and put back:** capacity, export, grid price and language were changed to watch the *Changed from* line. These changes stay in the browser session, and a reload restores the defaults.
- **Run scenario:**
  - first visit: pressed once with the defaults, under the name "Test run (Timur via Claude)"; no run was added (bug 4);
  - second visit (29 Oct), at your request: four scenarios, which are now in his history as «Тест (Тимур) — …», plus one repeat of the defaults, which was not saved (bug 4). Results are in WALKTHROUGH section 6.
- **His history between the visits:** 4 of his 9 runs were deleted before the second visit, including the 29 Oct 04:30 run, whose folder is now gone from the server. They were not deleted by these visits: the first screenshot of the second visit already shows 5 runs.
- **Not touched:** the *delete* tick-box, *Record screen* and *Stop*.
- **Downloaded:** his published run files, to rebuild his method. They are kept in `.playwright/output/zharkent/`, git-ignored.
- **Not visible:** his Python code. The rule in section 3 is inferred from his decisions and reproduces them step for step.
