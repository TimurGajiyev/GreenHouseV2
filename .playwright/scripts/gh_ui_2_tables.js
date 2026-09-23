// GreenHouse UI suite, part 2 of 3 — prices, the two editable tables, the
// battery and the coverage rules. Still no solving.
//
//   browser_run_code_unsafe filename=.playwright/scripts/gh_ui_2_tables.js
//
// The data editors are glide-data-grid canvases, so cells are reached through
// the accessibility layer Streamlit exposes as data-testid="glide-cell-<col>-<row>".
// Column 0 is the row marker, so the first data column is 1:
//   units      1 unit  2 kW  3 fuel  4 start  5 min%  6 up  7 down  8 spill
//              9 max starts/day  10 services  11 service h  12 service %
//              13 evenly  14 every run h  15 service cost  16 O&M  17 ownership
//              18 purchase cost
//   scenarios  1 name  2 min%  3 battery  4 load scale  5 max starts/day
async (page) => {
  const APP = 'http://localhost:8505/';
  const REPORT = [];
  let G = '';
  const rec = (name, ok, d) => REPORT.push({ g: G, name, ok: !!ok, d: d === undefined ? '' : String(d) });
  const N = (s) => { const m = String(s).replace(/[  \u00a0]/g, '').match(/-?[\d,]+(\.\d+)?/); return m ? parseFloat(m[0].replace(/,/g, '')) : NaN; };

  const idle = async (ms = 120000) => {
    await page.waitForTimeout(350);
    const w = page.locator('[data-testid="stStatusWidget"]');
    try { await w.waitFor({ state: 'attached', timeout: 1200 }); } catch (e) { }
    try { await w.waitFor({ state: 'detached', timeout: ms }); } catch (e) { }
    await page.waitForTimeout(400);
  };
  const body = async () => (await page.evaluate(() => document.body.innerText)).replace(/[\u00a0 ]/g, ' ');
  const slice = (t, a, b) => { const i = t.indexOf(a); if (i < 0) return ''; const j = b ? t.indexOf(b, i + a.length) : -1; return t.slice(i, j < 0 ? t.length : j); };
  const btn = (name) => page.locator('button').filter({ hasText: name }).first();

  const openApp = async () => {
    await page.goto(APP, { waitUntil: 'load' });
    await page.waitForTimeout(1200);
    await btn('Custom dispatch study (not REopt)').click();
    await page.locator('text=Hourly load').first().waitFor({ timeout: 60000 });
    await idle();
  };
  const setNum = async (prefix, v) => {
    const el = page.locator(`input[type=number][aria-label^="${prefix}"]`).first();
    await el.scrollIntoViewIfNeeded(); await el.fill(String(v)); await el.press('Enter'); await idle();
  };
  const setText = async (prefix, v) => {
    const el = page.locator(`input[type=text][aria-label^="${prefix}"]`).first();
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

  // ---- the grids ---------------------------------------------------------
  // The editor is a canvas. Streamlit exposes a screen-reader table beside it
  // -- data-testid="glide-cell-<col>-<row>" -- which is how a cell is READ, but
  // those nodes have no geometry, so a cell is REACHED by clicking the canvas
  // once and then walking with the arrow keys. The walk is verified against
  // aria-selected, so it does not matter which cell the click landed on, and
  // glide scrolls columns 10-18 into view by itself as the selection passes.
  const UNITS = 0, SCEN = 1;                     // units render first
  const canvasOf = (gi) => page.locator('[data-testid="stDataFrame"]').nth(gi).locator('canvas').first();
  const selectedCell = (gi) => page.evaluate((gi) => {
    const g = [...document.querySelectorAll('[data-testid="stDataFrame"]')][gi];
    const c = g && g.querySelector('[data-testid^="glide-cell-"][aria-selected="true"]');
    return c ? c.getAttribute('data-testid').replace('glide-cell-', '') : null;
  }, gi);
  const cellText = (gi, col, row) => page.evaluate(([gi, col, row]) => {
    const g = [...document.querySelectorAll('[data-testid="stDataFrame"]')][gi];
    const c = g && g.querySelector(`[data-testid="glide-cell-${col}-${row}"]`);
    return c ? (c.innerText || c.getAttribute('aria-label') || '').trim() : '(not rendered)';
  }, [gi, col, row]);
  const rowCount = (gi) => page.evaluate((gi) => {
    const g = [...document.querySelectorAll('[data-testid="stDataFrame"]')][gi];
    return [...g.querySelectorAll('[data-testid^="glide-cell-1-"]')].length;
  }, gi);

  const selectCell = async (gi, col, row) => {
    const cv = canvasOf(gi);
    // Three things make a click on this canvas unreliable, and all three are
    // worked around here rather than hoped away:
    //   * Streamlit's header is sticky, so a grid scrolled flush to the top has
    //     its first row under it -- the grid is centred instead.
    //   * the pointer entering a dataframe raises a toolbar button that steals
    //     the focus from a zero-delay click -- the press is held for 90 ms, and
    //     the pointer leaves the grid first so the toolbar is down.
    //   * even then the focus can land on the grid container rather than the
    //     cell, and the next key is spent moving it in, not moving the
    //     selection -- so the walk is PRIMED: arrow right until the selection
    //     actually moves, and only then count from where it really is.
    let at = null;
    for (let tries = 0; tries < 4 && !at; tries++) {
      await cv.evaluate((el) => el.scrollIntoView({ block: 'center' }));
      await page.waitForTimeout(400);
      await page.mouse.move(5, 5);
      await page.waitForTimeout(150);
      const box = await cv.boundingBox();
      await page.mouse.move(box.x + 60, box.y + 52);     // header 35 px, rows 35 px
      await page.waitForTimeout(120);
      await page.mouse.down();
      await page.waitForTimeout(90);
      await page.mouse.up();
      await page.waitForTimeout(350);
      at = await selectedCell(gi);
    }
    if (!at) throw new Error('the grid did not take the click');

    // The walk presses one key and then WAITS for the selection to actually
    // move before choosing the next one. Counting presses fails twice over: a
    // key sent while glide is scrolling a far-right column into view is
    // dropped, and the accessibility attribute the selection is read from lags
    // the keypress, so a walk that re-reads without waiting overshoots and then
    // paces back and forth. A dropped key here just means the same key again.
    const step = async (key) => {
      const from = at;
      await cv.press(key);
      for (let i = 0; i < 25; i++) {
        await page.waitForTimeout(100);
        const now = await selectedCell(gi);
        if (now && now !== from) { at = now; return true; }
      }
      return false;                                  // dropped; press it again
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
    await canvasOf(gi).press('Enter');                       // open the overlay editor
    const ov = page.locator('[data-testid="portal"] input, [data-testid="portal"] textarea').first();
    await ov.waitFor({ timeout: 6000 });
    await ov.fill(String(v));
    await page.keyboard.press('Enter');
    await idle();
  };
  const pickCell = async (gi, col, row, option) => {          // a dropdown column
    await selectCell(gi, col, row);
    await canvasOf(gi).press('Enter');
    await page.waitForTimeout(700);
    await page.locator('[data-testid="portal"]').getByText(option, { exact: true }).first().click();
    await idle();
  };

  const setUp = async () => {                 // a small, fixed starting point
    await openApp();
    await setRadio('Free mode: a real year, no file needed');
    await setNum('Window start hour', 0);
    await setNum('Window length', 48);
    await setCheck("Scale the profile to this site's own demand", true);
  };

  // ======================================================================
  G = 'G. grid price';
  try {
    await setUp();
    let t = await body();
    rec('the price is asked for in the chosen currency',
      await page.locator('input[type=number][aria-label="Grid price (₸/kWh)"]').count() === 1);
    rec('and the study says what it does not price',
      t.includes('No export and no demand charge in this study.'));

    await setText('Currency', '$');
    rec('changing the currency relabels the price field',
      await page.locator('input[type=number][aria-label="Grid price ($/kWh)"]').count() === 1);
    rec('and the battery wear field with it',
      await page.locator('input[type=number][aria-label="Wear cost ($ per kWh discharged)"]').count() === 1);
    rec('and the battery CAPEX field',
      await page.locator('input[type=number][aria-label="Battery CAPEX ($)"]').count() === 1);
    await setText('Currency', '₸');
    rec('and it goes back',
      await page.locator('input[type=number][aria-label="Grid price (₸/kWh)"]').count() === 1);

    // an hourly price series shorter than the load must be refused, not padded
    await page.locator('[data-testid="stFileUploader"]').filter({ hasText: 'Or hourly prices' })
      .locator('input[type=file]').first()
      .setInputFiles('D:/GreenHouseV2/reopt_test_data/ui/price_short.csv');
    await idle();
    t = slice(await body(), 'Or hourly prices', 'Fuel-fired units');
    rec('an hourly price file too short for the load is refused, with both counts',
      /10 prices for 48 hours/.test(t), t.match(/\d+ prices for \d+ hours[^\n]*/)?.[0] || t.slice(0, 80));
    rec('and it says it fell back to the flat price', t.includes('using the flat price'));
  } catch (e) { rec('EXCEPTION', false, e.message); }

  // ======================================================================
  G = 'H. the units table';
  try {
    await setUp();
    rec('the preset ships two units', await rowCount(UNITS) === 2, `${await rowCount(UNITS)} rows`);
    rec('named as the artifact names them',
      (await cellText(UNITS, 1, 0)) === 'Jenbacher' && (await cellText(UNITS, 1, 1)) === 'TEDOM',
      `${await cellText(UNITS, 1, 0)} / ${await cellText(UNITS, 1, 1)}`);
    rec('rated as the artifact rates them',
      N(await cellText(UNITS, 2, 0)) === 1067 && N(await cellText(UNITS, 2, 1)) === 1200,
      `${await cellText(UNITS, 2, 0)} / ${await cellText(UNITS, 2, 1)} kW`);

    // a rating typed into the grid has to reach the rest of the page
    await setCheck('The grid connection is limited', true);
    await setNum('Maximum grid import (kW)', 100);
    let s = slice(await body(), 'Site demand', 'Grid price');
    rec('the fleet the page counts is the sum of the ratings',
      /the fleet is rated 2,267 kW/.test(s), s.match(/the fleet is rated [\d,]+ kW/)?.[0]);
    await setCell(UNITS, 2, 0, 1500);
    rec('an edited rating is read back from the grid', N(await cellText(UNITS, 2, 0)) === 1500,
      await cellText(UNITS, 2, 0));
    // The Site panel renders ABOVE the units table, so it can only learn of an
    // edit on the rerun after it. One more interaction is the rerun.
    await setNum('Maximum grid import (kW)', 120);
    s = slice(await body(), 'Site demand', 'Grid price');
    rec('and the fleet the page counts follows the edit',
      /the fleet is rated 2,700 kW/.test(s), s.match(/the fleet is rated [\d,]+ kW/)?.[0]);
    await setCell(UNITS, 2, 0, 1067);
    await setCheck('The grid connection is limited', false);

    // maintenance: a count per horizon
    await setCell(UNITS, 10, 0, 2);
    let u = slice(await body(), 'Service plan', 'Battery');
    rec('a service count states the hours out and the availability it implies',
      /2 × 8 h = 16 h out of 48 h/.test(u) && /availability 66\.67 %/.test(u),
      u.split('\n').filter(Boolean)[0] || '(no service plan caption)');
    rec('and it is measured against the OEM interval, not a calendar',
      u.includes('1,000–2,000 h minor-service interval'));
    rec('a count is flagged as the proxy it is',
      u.includes('A count is a proxy for that interval'));

    // maintenance: a running-hour interval, which is how the OEM writes it
    await setCell(UNITS, 14, 0, 300);
    u = slice(await body(), 'Service plan', 'Battery');
    rec('a running-hour interval replaces the count',
      /every 300 running hours/.test(u), u.split('\n').filter(Boolean)[0] || '');
    rec('and it says the count is now an outcome',
      u.includes('overrides the count') && u.includes('never runs is never'));
    rec('with no service price it warns the count may exceed the need',
      u.includes('no service cost set'));
    await setCell(UNITS, 15, 0, 2500000);
    u = slice(await body(), 'Service plan', 'Battery');
    rec('pricing a service removes that warning', !u.includes('no service cost set'),
      u.match(/; [\d,]+ each/)?.[0] || '');
    await setCell(UNITS, 14, 0, 0);
    await setCell(UNITS, 10, 0, 0);
    await setCell(UNITS, 15, 0, 0);
    rec('and clearing both ends the service plan', !(await body()).includes('Service plan'));

    // ownership drives the investment column, never the dispatch
    // columns past the ninth are outside the grid's viewport and glide renders
    // nothing for them, so the cell is visited before it is read
    await selectCell(UNITS, 17, 0);
    rec('every unit is owned outright to begin with',
      (await cellText(UNITS, 17, 0)) === 'Paid (owned)', await cellText(UNITS, 17, 0));
    await pickCell(UNITS, 17, 0, 'Purchase');
    rec('ownership can be switched to Purchase',
      (await cellText(UNITS, 17, 0)) === 'Purchase', await cellText(UNITS, 17, 0));
    await setCell(UNITS, 18, 0, 120000000);
    rec('and a purchase cost sits beside it',
      N(await cellText(UNITS, 18, 0)) === 120000000, await cellText(UNITS, 18, 0));
    await pickCell(UNITS, 17, 0, 'Paid (owned)');
    await setCell(UNITS, 18, 0, 0);
  } catch (e) { rec('EXCEPTION', false, e.message); }

  // ======================================================================
  G = 'I. the scenarios table';
  try {
    await setUp();
    rec('three rules ship with the page', await rowCount(SCEN) === 3, `${await rowCount(SCEN)} rows`);
    rec('A is the free rule, B and C the 90 % one',
      N(await cellText(SCEN, 2, 0)) === 50 && N(await cellText(SCEN, 2, 1)) === 90
      && N(await cellText(SCEN, 2, 2)) === 90,
      [0, 1, 2].map(async r => await cellText(SCEN, 2, r)).length ? '50 / 90 / 90' : '');
    rec('and only C carries the battery',
      (await cellText(SCEN, 3, 0)) === 'false' && (await cellText(SCEN, 3, 2)) === 'true',
      `${await cellText(SCEN, 3, 0)} / ${await cellText(SCEN, 3, 1)} / ${await cellText(SCEN, 3, 2)}`);

    // the two levers that scale the same series
    await setCell(SCEN, 4, 0, 120);
    let t = slice(await body(), 'Each row is solved separately', 'Time limit');
    rec('a scale that fights the Site fit is called out',
      t.includes('The Site panel is fitting the profile'), t.match(/a row scales the load to [\d,]+ %/)?.[0] || t.slice(0, 90));
    rec('and it says where the maximum actually lands',
      /takes the maximum to 6,600 kW/.test(t), t.match(/takes the maximum to [\d,]+ kW/)?.[0]);
    await setCell(SCEN, 4, 0, 100);
    t = slice(await body(), 'Each row is solved separately', 'Time limit');
    rec('back at 100 % there is nothing to warn about',
      !t.includes('The Site panel is fitting the profile'));
    await setCheck("Scale the profile to this site's own demand", false);
    await setCell(SCEN, 4, 0, 120);
    t = slice(await body(), 'Each row is solved separately', 'Time limit');
    rec('and with no fit on, a scale is nobody\'s business',
      !t.includes('The Site panel is fitting the profile'));
    await setCell(SCEN, 4, 0, 100);
  } catch (e) { rec('EXCEPTION', false, e.message); }

  // ======================================================================
  G = 'J. the battery panel';
  try {
    await setUp();
    const val = async (p) => Number(await page.locator(`input[type=number][aria-label^="${p}"]`).first().inputValue());
    rec('the artifact\'s battery is the default', await val('Power (kW)') === 2500 && await val('Energy (kWh)') === 5500,
      `${await val('Power (kW)')} kW / ${await val('Energy (kWh)')} kWh`);
    rec('with its round trip and floor', await val('Round-trip') === 88 && await val('Minimum SoC') === 30,
      `${await val('Round-trip')} % / ${await val('Minimum SoC')} %`);
    rec('and the CAPEX the payback is measured against', await val('Battery CAPEX') === 391000000,
      (await val('Battery CAPEX')).toLocaleString());
    const soc = page.locator('input[type=number][aria-label^="Start SoC"]').first();
    rec('a cyclic run has no starting charge to set', await soc.isDisabled());
    await setRadio('Fixed');
    rec('choosing a fixed start opens the field', !(await soc.isDisabled()));
    await setRadio('Cyclic (end = start)');
    rec('and going back closes it again', await soc.isDisabled());
    rec('the panel says the size is fixed and the scenarios switch it',
      (await body()).includes('Size is fixed; each scenario below switches the battery on or off.'));
  } catch (e) { rec('EXCEPTION', false, e.message); }

  // ======================================================================
  G = 'K. how the horizon is covered';
  try {
    await setUp();                                   // 48 h
    const kd = page.locator('input[type=number][aria-label^="Typical days"]').first();
    rec('typical days are closed while the window is solved as posed', await kd.isDisabled());
    await setRadio('A year from typical days (weighted)');
    let t = slice(await body(), 'How to cover the horizon', 'Solve scenarios');
    rec('a 48 h horizon is too short for typical days, and it says so',
      t.includes('Typical days need at least four whole days'),
      t.match(/Typical days need[^\n]*/)?.[0] || '');

    await setNum('Window length', 8760);
    t = slice(await body(), 'How to cover the horizon', 'Solve scenarios');
    rec('a whole year can be covered by typical days',
      /12 typical days × 24 h = 288 hours to solve per scenario/.test(t),
      t.match(/\d+ typical days × 24 h = [\d,]+ hours[^.]*/)?.[0] || t.slice(0, 120));
    await setNum('Typical days', 4);
    t = slice(await body(), 'How to cover the horizon', 'Solve scenarios');
    rec('and the count is the reader\'s to set', /4 typical days × 24 h = 96 hours/.test(t),
      t.match(/\d+ typical days × 24 h = \d+ hours/)?.[0]);

    await setRadio('Solve the window as posed');
    t = slice(await body(), 'How to cover the horizon', 'Solve scenarios');
    rec('solving a year hour by hour is warned about, with the binary count',
      /8,760 hours with on\/off units means 17,520 commitment binaries/.test(t),
      t.match(/[\d,]+ commitment binaries per scenario/)?.[0] || t.slice(0, 120));

    const yrs = await page.locator('input[type=number][aria-label^="Analysis period"]').first().inputValue();
    const disc = await page.locator('input[type=number][aria-label^="Discount rate"]').first().inputValue();
    const esc = await page.locator('input[type=number][aria-label^="Operating cost escalation"]').first().inputValue();
    rec('the lifetime defaults are REopt\'s own', Number(yrs) === 25 && Number(disc) === 6.24 && Number(esc) === 3.4,
      `${yrs} years, ${disc} %/yr discount, ${esc} %/yr escalation`);
  } catch (e) { rec('EXCEPTION', false, e.message); }

  const bad = REPORT.filter(r => !r.ok);
  return JSON.stringify({ total: REPORT.length, failed: bad.length, report: REPORT }, null, 1);
}
