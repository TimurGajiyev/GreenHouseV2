# Core stress suite — `calculator/tools/stress_core.py`

The other suites in `calculator/tools/` build a scenario and check that a
particular answer came back. This one makes up scenarios nobody wrote by hand
and asks whether the answer can possibly be right. It imports
`reopt_core.model` and nothing else of ours, so a failure is the solver's.

```
python calculator/tools/stress_core.py                 # everything, ~20 s
python calculator/tools/stress_core.py --only=A,C      # some of it
python calculator/tools/stress_core.py --seed=7        # different instances
python calculator/tools/stress_core.py --cases=20      # more of them
```

## What each group asks, and why it is not the same question twice

| | asks | how it can fail |
|---|---|---|
| **A** brute force | is the optimum the optimum? | the MILP returns a number the exhaustive search beats |
| **B** invariants | is the dispatch physical? | energy appears, a unit runs below its floor, a start goes uncounted |
| **C** comparative statics | does the model respond the right way round? | a constraint makes the plant cheaper |
| **D** identities | is it consistent with itself? | rotating a closed horizon moves the answer |
| **E** degenerate | does it fail cleanly? | a nonsense input returns a confident wrong number |
| **F** size | does it still hold at scale? | an invariant that holds at 24 h breaks at 8,760 |

**A is the only check in the project that verifies the optimum rather than a
property of it.** For instances small enough to enumerate — five to seven hours,
one or two machines — it walks every on/off pattern there is, rejects the ones
the minimum up and down times forbid, and costs the rest in closed form: with
the commitment fixed there is no coupling left between hours, so each hour is a
one-constraint continuous problem that cheapest-first solves exactly. Two
implementations that share no code have to land on the same number.

Maintenance is deliberately thin here: `test_maintenance.py` already covers the
PyPSA event formulation and the running-hours trigger in seventeen groups, and
repeating it would make this suite look like that one.

## 2026-09-23 — 318 checks at the default seed, 0 failures

Six further seeds (1, 42, 99, 777, 2026, 31337) run clean over groups A and B,
which is another 72 brute-force instances and 72 random ones.

```
A. the optimum, found twice and independently        20 of 20 instances agreed
                                                     (5 of them infeasible, and
                                                      the solver said so)
B. invariants on instances nobody designed           199 checks, 10 of 10 ran a
                                                     unit, 8 of 10 started one
C. comparative statics                               14 pairs
D. identities                                        8
E. the inputs nobody means to type                   19
F. the sizes the page warns about                    8,760 h LP      3.8 s
                                                     336 h, 3 units + battery  0.8 s
                                                     720 h + a service  2.9 s, gap 0.00%
```

### What held exactly

* **The MILP optimum equals an exhaustive search** on every tiny instance, over
  cyclic and finite horizons, with and without spill, with and without a wire
  limit. Where no pattern serves the load the solver returns `Infeasible`
  rather than a number.
* **Energy balances to 1e-13 kW** in every hour of every instance.
* **A closed cycle returns exactly the round-trip efficiency**: 0.8800 out of
  0.88, 0.9500 out of 0.95. The state of charge follows its own recurrence to
  1e-13 kWh.
* **Reported starts are the off-to-on transitions** of the on/off series, on
  both seam conventions, in every instance.
* **The objective equals the sum of the costs reported** — O&M, starts, running
  hours, cycling, services, the energy bill and capital — to 1e-6 relative.
* **Scaling every price by 3 scales the bill by 3** and leaves the schedule
  identical to the kWh.
* **Rotating a cyclic horizon by 7 or 13 hours changes nothing.** A closed
  horizon is a circle, so where it is cut must not matter, and it does not.
* **A site with no technology**: the MILP, the closed-form `business_as_usual`,
  and the arithmetic anyone would do by hand all give the same number.

### What the suite found

**`can_grid_charge=False` did nothing.** A battery told it may not charge from
the grid cycled 4,264 kWh on a site with no PV and no engine — the only possible
source was the utility. REopt splits the charge by where it came from
(`dvProductionToStorage` per technology, `dvGridToStorage`) and the flag zeroes
the second; this port carries both variables but balances electricity at a
single node, so grid power flowed into the on-site charge variable while the
grid-charge variable sat pinned at zero.

No cost was ever understated — `grid[t]` is billed whatever it goes on to do —
but a site told not to arbitrage the tariff did so anyway. Fixed by constraining
the on-site charge of the refused batteries to what the site actually generated
in that hour. All nine existing suites still pass unchanged, so no scenario
recorded in this repo was relying on it.

### Two of my own premises the suite corrected

Both were wrong tests, not wrong code, and both are worth writing down:

1. **A finite horizon is not a relaxation of the cyclic one.** With the units
   starting cold it forces a start on anything running at hour 0 — measured at
   exactly +8,000, unit A's start cost. It is a relaxation only when the units
   start warm, and then it ties the cyclic answer exactly. The assertion now
   states the provable direction and prices the other one.
2. **A battery cannot arbitrage against a machine that is not the margin.** An
   engine large enough to cover the peak on its own makes itself the marginal
   source in the dear hours, and no battery can arbitrage 8 ₸ against 8 ₸. The
   instance now has headroom when power is cheap and a shortfall when it is
   dear, which is what makes the storage worth anything.

## Notes for the next run

* Group A's cost is exponential in `H × G`: seven hours and two machines is
  16,384 patterns, eight and two is 65,536. Keep instances small.
* Groups A, C, D and E solve with `mip_gap=0` so the comparisons are not
  polluted by a tolerance; group B uses 0.2 % and group F 0.5–1 %.
* The guard `most of the sweep actually committed a machine` exists because the
  first version of group B was vacuous: a tariff of 10–40 against machines
  costing 10–55 left every unit off in every hour, and an instance where nothing
  commits proves nothing about commitment.
