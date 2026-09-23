// GreenHouse UI suite, part 1 of 3 — the input panels of the custom dispatch study.
//
// Shell, the four load sources, the window, the Site fit and the grid-connection
// check. Nothing here solves, so it runs in well under a minute.
//
//   browser_run_code_unsafe filename=.playwright/scripts/gh_ui_1_inputs.js
//
// The app must be serving on 8505. Every case is wrapped, so one failure never
// hides the rest; the return value is a JSON report.
async (page) => {
  const APP = 'http://localhost:8505/';
  const REPORT = [];
  let G = '';
  const rec = (name, ok, d) => REPORT.push({ g: G, name, ok: !!ok, d: d === undefined ? '' : String(d) });
  const has = (t, s, name) => rec(name || `"${s.slice(0, 44)}"`, t.includes(s), t.includes(s) ? '' : 'absent');
  const N = (s) => { const m = String(s).replace(/[   ]/g, '').match(/-?[\d,]+(\.\d+)?/); return m ? parseFloat(m[0].replace(/,/g, '')) : NaN; };

  const idle = async (ms = 120000) => {
    await page.waitForTimeout(350);
    const w = page.locator('[data-testid="stStatusWidget"]');
    try { await w.waitFor({ state: 'attached', timeout: 1200 }); } catch (e) { }
    try { await w.waitFor({ state: 'detached', timeout: ms }); } catch (e) { }
    await page.waitForTimeout(400);
  };
  const body = async () => (await page.evaluate(() => document.body.innerText)).replace(/[  ]/g, ' ');
  const slice = (t, a, b) => { const i = t.indexOf(a); if (i < 0) return ''; const j = b ? t.indexOf(b, i + a.length) : -1; return t.slice(i, j < 0 ? t.length : j); };

  const btn = (name) => page.locator('button').filter({ hasText: name }).first();
  const tab = async (name) => { await btn(name).click(); await idle(); };

  const openApp = async () => {
    await page.goto(APP, { waitUntil: 'load' });
    await page.waitForTimeout(1200);
    await btn('Custom dispatch study (not REopt)').click();
    await page.locator('text=Hourly load').first().waitFor({ timeout: 60000 });
    await idle();
  };
  const setNum = async (prefix, v) => {
    const el = page.locator(`input[type=number][aria-label^="${prefix}"]`).first();
    await el.scrollIntoViewIfNeeded();
    await el.fill(String(v));
    await el.press('Enter');
    await idle();
  };
  const setCheck = async (label, want) => {
    const box = page.locator('[data-testid="stCheckbox"]').filter({ hasText: label }).first();
    await box.scrollIntoViewIfNeeded();
    const on = await box.locator('input[type=checkbox]').isChecked();
    if (on !== want) { await box.locator('label').first().click(); await idle(); }
  };
  const setRadio = async (label) => {
    const r = page.locator('[data-testid="stRadioOption"]').filter({ hasText: label }).first();
    await r.scrollIntoViewIfNeeded();
    await r.click();
    await idle();
  };
  const setSelect = async (ariaPrefix, option) => {
    const box = page.locator(`input[type=text][aria-label^="${ariaPrefix}"]`).first();
    await box.scrollIntoViewIfNeeded();
    await box.click();
    await page.waitForTimeout(400);
    await page.locator('li[role="option"], [role="option"]').filter({ hasText: option }).first().click();
    await idle();
  };

  // ======================================================================
  G = 'A. the page and its panels';
  try {
    await openApp();
    let t = await body();
    for (const s of ['REopt tool', 'Custom dispatch study (not REopt)', 'Not REopt.',
      'Hourly load', 'Site demand', 'Grid price', 'Units', 'Battery',
      'Operating rules to compare', 'Coverage and lifetime', 'Solve scenarios'])
      has(t, s);
    rec('the Solve button is enabled',
      await btn('Solve scenarios').isEnabled());
    const nGrids = await page.locator('[data-testid="stDataFrame"]').count();
    rec('two editable tables: units and scenarios', nGrids === 2, `${nGrids} grid(s)`);
    const scenNames = await page.evaluate(() => {
      const g = [...document.querySelectorAll('[data-testid="stDataFrame"]')][1];
      return [0, 1, 2].map(r => {
        const c = g.querySelector(`[data-testid="glide-cell-1-${r}"]`);
        return c ? (c.innerText || c.getAttribute('aria-label') || '').trim() : '';
      });
    });
    rec('the three shipped rules are the scenarios',
      scenNames[0].startsWith('A') && scenNames[1].startsWith('B') && scenNames[2].startsWith('C'),
      scenNames.join(' | '));
  } catch (e) { rec('EXCEPTION', false, e.message); }

  // ======================================================================
  G = 'B. the REopt tab still stands beside it';
  try {
    await tab('REopt tool');
    const t = await body();
    for (const s of ['Step 1: Select Use Case', 'Step 2: Select Grid-Tied or Off-Grid',
      'Step 3: Select Your Energy Goals'])
      has(t, s);
    rec('the REopt tab does not carry the study\'s panels', !t.includes('Operating rules to compare'));
    await tab('Custom dispatch study (not REopt)');
    rec('and the study comes back', (await body()).includes('Hourly load'));
  } catch (e) { rec('EXCEPTION', false, e.message); }

  // ======================================================================
  G = 'C. the four load sources';
  try {
    await setRadio('Example: bess_profile_v2.jsx day (24 h)');
    let t = await body();
    const day = slice(t, 'Window length (hours)', 'Site');
    rec('the 24 h example gives 24 hours', /\b24 hours ·/.test(day), day.split('\n').filter(Boolean)[1] || day.slice(0, 80));
    const dayKwh = N(day.match(/·\s*([\d,]+) kWh/)?.[1]);

    await setRadio('Example: bess_profile_v2.jsx week (168 h)');
    t = await body();
    const wk = slice(t, 'Window length (hours)', 'Site');
    rec('the 168 h example gives 168 hours', /\b168 hours ·/.test(wk), wk.split('\n').filter(Boolean)[1] || '');
    const wkKwh = N(wk.match(/·\s*([\d,]+) kWh/)?.[1]);
    rec('a week carries about seven days of energy', wkKwh > 5 * dayKwh && wkKwh < 9 * dayKwh,
      `${wkKwh.toLocaleString()} kWh vs 7 × ${dayKwh.toLocaleString()}`);

    await setRadio('Free mode: a real year, no file needed');
    t = await body();
    rec('free mode builds a full year', t.includes('8,760 real hours'));
    rec('and no annual-shape dropdown is left on the page', !t.includes('Annual shape'));
    const lvl = N(t.match(/averages ([\d,]+) kW, the Site panel's own average/)?.[1]);
    rec('its level is the Site panel\'s average, not a reference building\'s', lvl === 3000, `${lvl} kW`);

    // the upload path: the widget is there and takes a file
    await setRadio('Upload hourly CSV');
    t = await body();
    rec('the upload path asks for a file', t.includes('Hourly load, kW'));
    rec('and nothing downstream runs without one', t.includes('Required:') && t.includes('hourly load'));
  } catch (e) { rec('EXCEPTION', false, e.message); }

  // ======================================================================
  G = 'D. the window cuts the year';
  try {
    await setRadio('Free mode: a real year, no file needed');
    await setNum('Window start hour', 200);
    await setNum('Window length', 48);
    let t = await body();
    let w = slice(t, 'Window length (hours)', 'Site');
    rec('a 48 h window is 48 hours', /\b48 hours ·/.test(w), w.split('\n').filter(Boolean)[1] || '');
    const peak48 = N(w.match(/peak ([\d,]+) kW/)?.[1]);
    const yearPeak = N(t.match(/Peak ([\d,]+) kW, quietest/)?.[1]);
    rec('the window\'s peak cannot exceed the year\'s', peak48 <= yearPeak, `${peak48} <= ${yearPeak}`);

    // the field's own ceiling is what is left of the series after the start,
    // so a window can never run off the end of the year
    const maxAttr = await page.locator('input[type=number][aria-label^="Window length"]')
      .first().getAttribute('max');
    rec('the length cannot exceed what is left after the start',
      Number(maxAttr) === 8760 - 200, `max ${maxAttr}, start 200`);
    await setNum('Window length', 99999);
    w = slice(await body(), 'Window length (hours)', 'Site');
    const cut = N(w.match(/([\d,]+) hours ·/)?.[1]);
    rec('and asking for more than that does not lengthen the window', cut <= 8760 - 200, `${cut} h`);
    await setNum('Window start hour', 0);
    await setNum('Window length', 48);
    rec('and the window can be reset', /\b48 hours ·/.test(slice(await body(), 'Window length (hours)', 'Site')));
  } catch (e) { rec('EXCEPTION', false, e.message); }

  // ======================================================================
  G = 'E. the Site fit';
  try {
    let t = await body();
    rec('off by default, and it says so', slice(t, 'Site demand', 'Grid price').includes('Not scaling'));

    await setCheck("Scale the profile to this site's own demand", true);
    t = await body();
    let s = slice(t, 'Site demand', 'Grid price');
    rec('on: the profile lands on all three anchors',
      /min 1,200 · mean 3,000 · max 5,500 kW/.test(s), s.match(/fitted on[^\n]*/)?.[0] || s.slice(0, 90));
    rec('the load factor is average / maximum', /load factor 54\.5 %/.test(s), s.match(/load factor [\d.]+ %/)?.[0]);

    await setNum('Minimum load (kW)', 2000);
    await setNum('Average load (kW)', 4000);
    await setNum('Maximum load (kW)', 6000);
    s = slice(await body(), 'Site demand', 'Grid price');
    rec('the anchors are the ones typed in, not the shape\'s own',
      /min 2,000 · mean 4,000 · max 6,000 kW/.test(s), s.match(/fitted on[^\n]*/)?.[0]);
    rec('and the load factor follows them', /load factor 66\.7 %/.test(s), s.match(/load factor [\d.]+ %/)?.[0]);

    await setNum('Minimum load (kW)', 5000);        // min > avg: no curve exists
    s = slice(await body(), 'Site demand', 'Grid price');
    rec('anchors out of order are refused, with the numbers',
      s.includes('The three anchors have to increase'), s.match(/minimum [\d,]+ < average [\d,]+/)?.[0]);
    rec('and nothing is fitted while they are wrong', !s.includes('fitted on'));
    await setNum('Minimum load (kW)', 2000);
    rec('correcting them fits again', slice(await body(), 'Site demand', 'Grid price').includes('fitted on'));
  } catch (e) { rec('EXCEPTION', false, e.message); }

  // ======================================================================
  G = 'F. the grid connection check';
  try {
    await setCheck('The grid connection is limited', true);
    await setNum('Maximum grid import (kW)', 100);
    let s = slice(await body(), 'Site demand', 'Grid price');
    rec('a wire that cannot cover the peak is called out before solving',
      s.includes('No answer exists'), s.match(/the peak is [\d,]+ kW but the wire passes [\d,]+ kW/)?.[0]);
    rec('and it names the fleet it counted', /the fleet is rated 2,267 kW/.test(s),
      s.match(/the fleet is rated [\d,]+ kW/)?.[0]);

    await setNum('Maximum grid import (kW)', 3800);   // 3,800 + 2,267 = 6,067 vs a 6,000 peak
    s = slice(await body(), 'Site demand', 'Grid price');
    rec('a wire that just covers it is called tight', s.includes('Tight: peak'),
      s.match(/Tight: peak [\d,]+ kW against [\d,]+ kW/)?.[0]);

    await setNum('Maximum grid import (kW)', 20000);
    s = slice(await body(), 'Site demand', 'Grid price');
    rec('an ample wire says nothing', !s.includes('No answer exists') && !s.includes('Tight: peak'));

    await setSelect('Start from', '3 units');
    await setNum('Maximum grid import (kW)', 100);
    s = slice(await body(), 'Site demand', 'Grid price');
    rec('adding a third unit is counted in the fleet', /the fleet is rated 3,367 kW/.test(s),
      s.match(/the fleet is rated [\d,]+ kW/)?.[0]);
    await setSelect('Start from', '2 units');
    await setCheck('The grid connection is limited', false);
    rec('and the cap can be switched off again',
      !slice(await body(), 'Site demand', 'Grid price').includes('Maximum grid import'));
  } catch (e) { rec('EXCEPTION', false, e.message); }

  const bad = REPORT.filter(r => !r.ok);
  return JSON.stringify({ total: REPORT.length, failed: bad.length, report: REPORT }, null, 1);
}
