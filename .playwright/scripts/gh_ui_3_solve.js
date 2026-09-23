// GreenHouse UI suite, part 3 of 3 — solving, and whether the answers mean
// anything. This is the part that costs real time: three scenarios over a
// 48-hour window, twice.
//
//   browser_run_code_unsafe filename=.playwright/scripts/gh_ui_3_solve.js
//
// The checks are invariants, not remembered numbers, so nothing here goes stale
// when the load, the fleet or the solver version changes:
//   * every scenario is handed the same load
//   * energy in equals energy out, hour for hour, over the horizon
//   * B is A with a TIGHTER rule, so B cannot be cheaper than A
//   * C is B plus an OPTIONAL battery, so C cannot be dearer than B
//   * a round trip loses what the round-trip efficiency says it loses
//   * a cap of zero starts a day means zero starts
async (page) => {
  const APP = 'http://localhost:8505/';
  const REPORT = [];
  let G = '';
  const rec = (name, ok, d) => REPORT.push({ g: G, name, ok: !!ok, d: d === undefined ? '' : String(d) });
  const N = (s) => {
    if (s === undefined || s === null) return NaN;
    const m = String(s).replace(/[   ₸$]/g, '').replace('−', '-').match(/-?[\d,]+(\.\d+)?/);
    return m ? parseFloat(m[0].replace(/,/g, '')) : NaN;
  };
  const near = (name, got, want, tol, unit) => {
    const ok = Math.abs(got - want) <= tol;
    rec(name, ok, `${got.toLocaleString('en-US', { maximumFractionDigits: 2 })} vs ` +
      `${want.toLocaleString('en-US', { maximumFractionDigits: 2 })}${unit ? ' ' + unit : ''}`);
  };

  const idle = async (ms = 600000) => {
    await page.waitForTimeout(350);
    const w = page.locator('[data-testid="stStatusWidget"]');
    try { await w.waitFor({ state: 'attached', timeout: 1500 }); } catch (e) { }
    try { await w.waitFor({ state: 'detached', timeout: ms }); } catch (e) { }
    await page.waitForTimeout(500);
  };
  const body = async () => (await page.evaluate(() => document.body.innerText)).replace(/[  ]/g, ' ');
  const btn = (name) => page.locator('button').filter({ hasText: name }).first();
  const setNum = async (prefix, v) => {
    const el = page.locator(`input[type=number][aria-label^="${prefix}"]`).first();
    await el.scrollIntoViewIfNeeded(); await el.fill(String(v)); await el.press('Enter'); await idle();
  };
  const setCheck = async (label, want) => {
    const box = page.locator('[data-testid="stCheckbox"]').filter({ hasText: label }).first();
    await box.scrollIntoViewIfNeeded();
    if ((await box.locator('input[type=checkbox]').isChecked()) !== want) {
      await box.locator('label').first().click(); await idle();
    }
  };
  const setRadio = async (label) => {
    const r = page.locator('[data-testid="stRadioOption"]').filter({ hasText: label }).first();
    await r.scrollIntoViewIfNeeded(); await r.click(); await idle();
  };

  // the grid helpers, as part 2 establishes them
  const SCEN = 1;
  const canvasOf = (gi) => page.locator('[data-testid="stDataFrame"]').nth(gi).locator('canvas').first();
  const selectedCell = (gi) => page.evaluate((gi) => {
    const g = [...document.querySelectorAll('[data-testid="stDataFrame"]')][gi];
    const c = g && g.querySelector('[data-testid^="glide-cell-"][aria-selected="true"]');
    return c ? c.getAttribute('data-testid').replace('glide-cell-', '') : null;
  }, gi);
  const selectCell = async (gi, col, row) => {
    const cv = canvasOf(gi);
    let at = null;
    for (let tries = 0; tries < 4 && !at; tries++) {
      await cv.evaluate((el) => el.scrollIntoView({ block: 'center' }));
      await page.waitForTimeout(400);
      await page.mouse.move(5, 5);
      await page.waitForTimeout(150);
      const box = await cv.boundingBox();
      await page.mouse.move(box.x + 60, box.y + 52);
      await page.waitForTimeout(120);
      await page.mouse.down();
      await page.waitForTimeout(90);
      await page.mouse.up();
      await page.waitForTimeout(350);
      at = await selectedCell(gi);
    }
    if (!at) throw new Error('the grid did not take the click');
    const step = async (key) => {
      const from = at;
      await cv.press(key);
      for (let i = 0; i < 25; i++) {
        await page.waitForTimeout(100);
        const now = await selectedCell(gi);
        if (now && now !== from) { at = now; return; }
      }
    };
    for (let n = 0; n < 60; n++) {
      const [c, r] = at.split('-').map(Number);
      if (c === col && r === row) return;
      await step(c < col ? 'ArrowRight' : c > col ? 'ArrowLeft'
        : r < row ? 'ArrowDown' : 'ArrowUp');
    }
    throw new Error(`selection stuck at ${at}, wanted ${col}-${row}`);
  };
  const setCell = async (gi, col, row, v) => {
    await selectCell(gi, col, row);
    await canvasOf(gi).press('Enter');
    const ov = page.locator('[data-testid="portal"] input, [data-testid="portal"] textarea').first();
    await ov.waitFor({ timeout: 6000 });
    await ov.fill(String(v));
    await page.keyboard.press('Enter');
    await idle();
  };

  // ---- reading the comparison table -------------------------------------
  const compare = () => page.evaluate(() => {
    const t = [...document.querySelectorAll('table')].find(
      (x) => x.innerText.includes('Load (kWh)') && x.innerText.includes('Starts'));
    if (!t) return null;
    const head = [...t.querySelectorAll('thead th')].map((th) => th.innerText.trim());
    const rows = {};
    for (const tr of t.querySelectorAll('tr')) {
      const cells = [...tr.querySelectorAll('td')].map((td) => td.innerText.trim());
      if (cells.length > 1) rows[cells[0]] = cells.slice(1);
    }
    return { head, rows };
  });

  const solve = async () => {
    const b = btn('Solve scenarios');
    await b.scrollIntoViewIfNeeded();
    await b.click();
    await idle();                                    // the progress bar is a rerun
    await page.locator('text=Scenario comparison').first().waitFor({ timeout: 600000 });
    await page.waitForTimeout(800);
  };

  const setUp = async () => {
    await page.goto(APP, { waitUntil: 'load' });
    await page.waitForTimeout(1200);
    await btn('Custom dispatch study (not REopt)').click();
    await page.locator('text=Hourly load').first().waitFor({ timeout: 60000 });
    await idle();
    await setRadio('Free mode: a real year, no file needed');
    await setNum('Window start hour', 0);
    await setNum('Window length', 48);
    await setCheck("Scale the profile to this site's own demand", true);   // 1,200 / 3,000 / 5,500
    await setNum('Time limit per scenario', 120);
    await setNum('Optimality gap', 0.5);
  };

  let C = null;
  // ======================================================================
  G = 'L. the three rules solve and land somewhere sensible';
  try {
    await setUp();
    await solve();
    C = await compare();
    if (!C) throw new Error('no comparison table rendered');
    rec('all three scenarios are reported side by side',
      C.head.length === 4 && /^A/.test(C.head[1]) && /^B/.test(C.head[2]) && /^C/.test(C.head[3]),
      C.head.join(' | '));

    const row = (k) => (C.rows[k] || []).map(N);
    const load = row('Load (kWh)');
    rec('every rule is handed the same load',
      load.length === 3 && load[0] === load[1] && load[1] === load[2],
      load.map((x) => x.toLocaleString()).join(' / '));
    // the Site panel was told mean 3,000 kW over 48 h
    near('and that load is the site\'s own average over the window', load[0], 48 * 3000, 1, 'kWh');

    const gen = row('Fuel-fired generation (kWh)');
    const grid = row('Grid purchase (kWh)');
    const chg = row('Battery charged (kWh)');
    const dis = row('Battery discharged (kWh)');
    const spill = row('Spill (kWh)');
    for (let i = 0; i < 3; i++) {
      const inn = gen[i] + grid[i] + dis[i];
      const out = load[i] + chg[i] + spill[i];
      rec(`${C.head[i + 1]}: what comes in equals what goes out`,
        Math.abs(inn - out) <= Math.max(2, 0.005 * out),
        `in ${inn.toLocaleString()} vs out ${out.toLocaleString()} kWh`);
    }

    const peak = row('Peak grid purchase (kW)');
    rec('no scenario draws more than the site\'s own maximum',
      peak.every((p) => p <= 5500 + 1), peak.map((x) => x.toLocaleString()).join(' / ') + ' kW');

    const cost = row('Operating cost');
    rec('an operating cost is reported for each', cost.length === 3 && cost.every((c) => c > 0),
      cost.map((x) => x.toLocaleString()).join(' / '));
    rec('B cannot beat A: the same fleet under a tighter minimum-load rule',
      cost[1] >= cost[0] - 1, `A ${cost[0].toLocaleString()} vs B ${cost[1].toLocaleString()}`);
    rec('C cannot lose to B: the same rule with a battery it may ignore',
      cost[2] <= cost[1] + 1, `B ${cost[1].toLocaleString()} vs C ${cost[2].toLocaleString()}`);

    rec('only the scenario with the battery uses one',
      chg[0] === 0 && dis[0] === 0 && chg[1] === 0 && dis[1] === 0 && chg[2] > 0 && dis[2] > 0,
      `charged ${chg.join('/')}, discharged ${dis.join('/')}`);
    const rte = dis[2] / chg[2];
    rec('and a round trip gives back what the 88 % efficiency allows',
      rte > 0.86 && rte < 0.90, `${(100 * rte).toFixed(2)} % out of 88 %`);

    const starts = row('Starts');
    const perDay = row('Starts per day, average (fleet)');
    const worst = row('Starts on the busiest day (fleet)');
    for (let i = 0; i < 3; i++) {
      near(`${C.head[i + 1]}: the average of two days is the count over two`,
        perDay[i], starts[i] / 2, 0.01, 'starts/day');
      rec(`${C.head[i + 1]}: the busiest day is no better than the average`,
        worst[i] >= perDay[i] - 1e-9, `${worst[i]} vs ${perDay[i]}`);
    }
    const yr = row('Starts per year (annualised)');
    near('a year is the window scaled by the hours in one', yr[0], starts[0] * 8760 / 48, 1, 'starts');

    const solver = (C.rows['Solver'] || []);
    rec('the solver proved each of them', solver.every((s) => /Optimal/.test(s)), solver.join(' | '));

    const cur = await body();
    rec('the operating cost is carried to a year', cur.includes('Operating cost per year'));
    rec('and each scenario is put beside the first', cur.includes('vs first scenario'));
  } catch (e) { rec('EXCEPTION', false, e.message); }

  // ======================================================================
  G = 'M. the panels the answer is read in';
  try {
    const t = await body();
    for (const s of ['Scenario comparison', 'Economics of one scenario against the others',
      'Over 25 years', 'Dispatch by period', 'Starts by unit and day'])
      rec(`"${s}"`, t.includes(s), t.includes(s) ? '' : 'absent');
    const charts = await page.locator('[data-testid="stVegaLiteChart"]').count();
    rec('the dispatch is drawn, not only tabulated', charts > 0, `${charts} chart(s)`);

    // The period view belongs to whichever scenario is in the chair, so B is
    // put there first: it is the only rule that starts an engine in this
    // window, and a breakdown of zero starts proves nothing.
    const names = C.head.slice(1);
    const pick = page.locator('[data-testid="stButtonGroup"] button')
      .filter({ hasText: names[1].slice(0, 6) }).first();
    await pick.scrollIntoViewIfNeeded();
    await pick.click();
    await idle();
    rec('the reader can put any scenario in the chair',
      (await body()).includes('Economics of one scenario against the others'));

    // the starts-by-day table is the one whose columns are DAYS: the unit
    // summary table above it also starts with UNIT and ends in a Fleet row
    const findStarts = () => page.evaluate(() => {
      const isDay = (h) => /^(MON|TUE|WED|THU|FRI|SAT|SUN) /.test(h);
      const t = [...document.querySelectorAll('table')].find((x) => {
        const head = [...x.querySelectorAll('thead th')].map((th) => th.innerText.trim());
        return head[0] === 'UNIT' && head.some(isDay);
      });
      if (!t) return null;
      return {
        head: [...t.querySelectorAll('thead th')].map((th) => th.innerText.trim()),
        rows: [...t.querySelectorAll('tbody tr')].map(
          (tr) => [...tr.querySelectorAll('th,td')].map((c) => c.innerText.trim())),
      };
    });
    // the section is re-rendered when the scenario in the chair changes, and
    // the table can be a beat behind the heading
    let st = null;
    for (let i = 0; i < 12 && !st; i++) { st = await findStarts(); if (!st) await page.waitForTimeout(500); }
    rec('starts are broken down by unit and by day', !!st,
      st ? `${st.rows.length} rows x ${st.head.length} columns: ${st.head.join(' ')}` : 'no such table');
    if (st) {
      const fleet = st.rows.find((r) => r[0] === 'Fleet');
      const units = st.rows.filter((r) => r !== fleet && r.length === st.head.length);
      rec('one row per unit, one column per day, plus a total',
        units.length === 2 && st.head.length === 1 + 2 + 1,
        `${units.length} units, ${st.head.length} columns`);
      const tot = (r) => N(r[r.length - 1]);
      const startsB = (C.rows['Starts'] || []).map(N)[1];
      near('the fleet row is the start count the comparison reports for B',
        tot(fleet), startsB, 1e-9, 'starts');
      near('and the units add up to the fleet',
        units.reduce((a, r) => a + (isNaN(tot(r)) ? 0 : tot(r)), 0), tot(fleet), 1e-9, 'starts');
    }
  } catch (e) { rec('EXCEPTION', false, e.message); }

  // ======================================================================
  G = 'N. a rule typed into the table reaches the solver';
  try {
    // no starts allowed on any day: whatever is running at hour 0 is all there
    // will ever be, so the count has to come back zero
    await setCell(SCEN, 5, 0, 0);
    await solve();
    const D = await compare();
    const starts = (D.rows['Starts'] || []).map(N);
    rec('a cap of no starts a day is obeyed exactly', starts[0] === 0,
      `A ${starts[0]} starts, B ${starts[1]}, C ${starts[2]}`);
    const cost0 = (C.rows['Operating cost'] || []).map(N)[0];
    const cost1 = (D.rows['Operating cost'] || []).map(N)[0];
    rec('and taking a freedom away cannot make the answer cheaper',
      cost1 >= cost0 - 1, `${cost0.toLocaleString()} -> ${cost1.toLocaleString()}`);
    rec('the other two rules are untouched by a cap on the first',
      (D.rows['Operating cost'] || []).map(N)[1] === (C.rows['Operating cost'] || []).map(N)[1],
      `B ${(D.rows['Operating cost'] || [])[1]}`);
  } catch (e) { rec('EXCEPTION', false, e.message); }

  const bad = REPORT.filter((r) => !r.ok);
  return JSON.stringify({ total: REPORT.length, failed: bad.length, report: REPORT }, null, 1);
}
