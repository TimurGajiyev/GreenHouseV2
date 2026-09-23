# Browser suite — the custom dispatch study, end to end

A Playwright series over the live Streamlit app, written to answer one question:
does every control on the page do what it says, and does the answer that comes
back mean anything?

Run against `http://localhost:8505` (`python -m streamlit run calculator/streamlit_app.py
--server.port 8505 --server.headless true --server.fileWatcherType none`). The
file watcher is off, so **the server must be restarted after any edit to
`calculator/`** or the suite tests the code that was loaded, not the code on disk.

```
browser_run_code_unsafe filename=.playwright/scripts/gh_ui_1_inputs.js    # ~2 min
browser_run_code_unsafe filename=.playwright/scripts/gh_ui_2_tables.js    # ~4 min
browser_run_code_unsafe filename=.playwright/scripts/gh_ui_3_solve.js     # ~4 min, solves twice
```

Each part returns `{total, failed, report[]}`. Every group is wrapped, so one
failure never hides the rest of the run.

## 2026-09-23 — 127 checks, 0 failures

| part | group | checks |
|---|---|---|
| 1 | A. the page and its panels | 14 |
| 1 | B. the REopt tab still stands beside it | 5 |
| 1 | C. the four load sources | 8 |
| 1 | D. the window cuts the year | 5 |
| 1 | E. the Site fit | 7 |
| 1 | F. the grid connection check | 6 |
| 2 | G. grid price | 8 |
| 2 | H. the units table | 16 |
| 2 | I. the scenarios table | 7 |
| 2 | J. the battery panel | 7 |
| 2 | K. how the horizon is covered | 6 |
| 3 | L. the three rules solve and land somewhere sensible | 22 |
| 3 | M. the panels the answer is read in | 11 |
| 3 | N. a rule typed into the table reaches the solver | 3 |

### What the solve actually returned

Free mode, hours 0–48 of the generated year, fitted to the site's own
1,200 / 3,000 / 5,500 kW, the two shipped engines, the 2,500 kW / 5,500 kWh
battery, 60 ₸/kWh flat, 120 s and 0.5 % per scenario.

| | A · free from 50% | B · 90% rule | C · 90% + battery |
|---|---|---|---|
| load | 144,000 kWh | 144,000 kWh | 144,000 kWh |
| generation | — | — | — |
| peak grid purchase | 3,233 kW | 3,233 kW | 3,233 kW |
| battery charged / discharged | 0 / 0 | 0 / 0 | 8,208 / 7,223 kWh |
| starts | 0 | 1 | 0 |
| operating cost | 4,949,303 ₸ | 5,079,825 ₸ | 4,718,264 ₸ |
| solver | Optimal, gap 0.00 % | Optimal, gap 0.00 % | Optimal, gap 0.35 % |

The three numbers that matter are consistent with each other:

* **144,000 kWh = 48 h × 3,000 kW.** The Site panel was told the site averages
  3,000 kW and the horizon is 48 hours, and that is exactly the energy every
  scenario was handed.
* **B ≥ A.** B is A with the minimum load raised from 50 % to 90 % — a strictly
  smaller feasible set, so it cannot be cheaper. It is 130,522 ₸ dearer.
* **C ≤ B.** C is B plus a battery it is free to leave idle, so it cannot be
  worse. It is 361,561 ₸ better.
* **7,223 / 8,208 = 88.00 %.** The round trip gives back exactly what the
  round-trip efficiency allows, and the run is cyclic, so nothing is left in the
  battery at the end to flatter the figure.
* **Energy in equals energy out** in all three, to 1 kWh in 153,034.

### The checks are invariants, not remembered numbers

Nothing above is asserted as a literal except the load, which is arithmetic the
reader can do. The suite asserts relationships — B ≥ A, C ≤ B, in = out,
discharge/charge ≈ RTE, per-unit starts sum to the fleet count, a cap of zero
starts a day yields zero starts — so it keeps its meaning when the load, the
fleet, the prices or the solver change.

## What the suite found

**The grid-connection check counted the preset's ratings, not the edited ones.**
`app_dispatch.render()` read the fleet from `ss["gd_units_df"]`, which is only
ever written when the *preset* changes; every edit to the units table lives in
the data editor's own widget state. Lower Jenbacher from 1,067 kW to 1,500 kW
and the "No answer exists / Tight" check went on counting 2,267 kW. Fixed by
writing `ss["gd_fleet_kw"]` at the end of the units panel and reading that.

The edited frame is deliberately *not* written back to `gd_units_df`:
`st.data_editor` holds its edits as a delta against the frame it was handed, and
with `num_rows="dynamic"` a frame written back with its added rows already in it
would take them a second time. A single number carries no such risk.

The Site panel renders above the units table, so it learns of an edit one rerun
late — the same bargain the fit checkbox already makes, and unavoidable while
the panels are in that order.

## Driving a Streamlit data editor from Playwright

The units and scenario tables are glide-data-grid **canvases**. Four things had
to be worked out, and all four are in the scripts:

1. **Reading** a cell: Streamlit exposes a screen-reader table beside the
   canvas, `data-testid="glide-cell-<col>-<row>"`, whose text is the cell's
   text. Column 0 is the row marker, so the first data column is 1.
2. **Reaching** a cell: those nodes have zero geometry, so they cannot be
   clicked. Click the canvas once and walk with the arrow keys instead.
3. **The click must be a press-and-hold.** A zero-delay click leaves the focus
   on the toolbar button that appears when the pointer enters a dataframe, and
   the first arrow key is then spent moving focus rather than the selection.
   90 ms with the pointer moved off the grid first is enough. The grid is also
   scrolled to the *centre*, because Streamlit's sticky header eats a click
   aimed at a grid flush with the top of the viewport.
4. **The walk must wait for each move.** `aria-selected` lags the keypress, and
   a key sent while glide is scrolling a far-right column into view is dropped
   outright. Counting presses overshoots and then paces back and forth; pressing
   one key, waiting for the selection to actually change, and only then choosing
   the next one is exact and self-correcting.

Columns 10–18 of the units table are off-screen and glide renders nothing for
them until the selection passes through, so a cell there is visited before it is
read.
