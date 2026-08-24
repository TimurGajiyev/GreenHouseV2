// PT2 through our Streamlit UI end to end, so the comparison covers the whole
// stack (form -> engine -> results), not just the solver.
// REopt reference: run c5e511b2 -- PV 25 kW, Battery 26 kW / 36 kWh,
// life cycle cost $2,559,868, NPV $10,595.
async (page) => {
  const log = [];
  const openAll = async () => {
    for (let i = 0; i < 5; i++) {
      const n = await page.evaluate(() => {
        let c = 0;
        document.querySelectorAll('[data-testid="stExpander"] details').forEach(d => {
          if (!d.open) { const s = d.querySelector('summary'); if (s) { s.click(); c++; } }
        });
        return c;
      });
      await page.waitForTimeout(1000);
      if (!n) break;
    }
  };
  const setNum = async (lab, val) => {
    const loc = page.locator(`input[type="number"][aria-label*="${lab}" i]`).first();
    if (!(await loc.count())) { log.push('  MISSING ' + lab); return false; }
    await loc.scrollIntoViewIfNeeded(); await loc.click();
    await loc.press('Control+a'); await loc.fill(String(val)); await loc.press('Enter');
    await page.waitForTimeout(900);
    return true;
  };
  const setSel = async (labRe, optName) => {
    const box = page.locator('[data-testid="stSelectbox"]')
      .filter({ has: page.locator(`label:has-text("${labRe}")`) }).first();
    if (!(await box.count())) { log.push('  MISSING select ' + labRe); return; }
    const inp = box.locator('input').first();
    await inp.scrollIntoViewIfNeeded(); await inp.click();
    await page.waitForTimeout(500);
    await inp.type(optName, { delay: 45 });
    await page.waitForTimeout(700); await inp.press('Enter');
    await page.waitForTimeout(1500);
  };

  await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(8000);
  await openAll();

  // Site: enter the exact coordinates REopt used
  const latlon = page.locator('input[type="checkbox"]').first();
  const lbl = page.getByText('Use latitude & longitude', { exact: false }).first();
  if (await lbl.count()) { await lbl.click(); await page.waitForTimeout(2000); }
  await openAll();
  await setNum('Latitude', 39.74437);
  await setNum('Longitude', -105.15199);
  await setNum('Land available', 6);

  await openAll();
  await setSel('Type of building', 'Supermarket');
  await openAll();
  await setNum('Annual energy consumption', 3000000);

  await setNum('Analysis period', 20);
  await setNum('Host discount rate', 7.5);
  await setNum('Electricity cost escalation', 2.2);

  await setNum('System capital cost', 1850);
  await setNum('Maximum new PV size', 1500);
  // "O&M cost" alone also matches the Financial panel's escalation-rate field,
  // which sits earlier in the DOM -- match the PV field's full label instead.
  await setNum('O&M cost ($/kW-DC per year)', 20);
  await setNum('O&M cost escalation rate', 2.5);

  await setNum('Energy capacity cost', 320);
  await setNum('Power capacity cost', 850);
  await setNum('Constant cost', 0);
  await setNum('Maximum energy capacity', 3000);

  await page.waitForTimeout(1200);
  log.push('inputs: ' + JSON.stringify(await page.evaluate(() => {
    const o = {};
    document.querySelectorAll('input[type="number"]').forEach(e => {
      const a = e.getAttribute('aria-label') || '';
      if (/Latitude|Longitude|Land available|Annual energy|Analysis period|Host discount|escalation|System capital cost|Maximum new PV|O&M cost|Energy capacity cost|Power capacity cost|Maximum energy capacity|Federal ITC|tax rate/i.test(a)) o[a] = e.value;
    });
    const t = document.body.innerText;
    o['_urdb'] = (t.match(/5b44ffc75457a36716a907eb/) || ['(not shown)'])[0];
    o['_bldg'] = (t.match(/Supermarket/) || ['(not set)'])[0];
    return o;
  }), null, 1));

  await page.screenshot({ path: 'D:/GreenHouseV2/reopt_test_screenshots/parity/PT2-ours-form.png', scale: 'css' });

  // A previous run's results may still be on screen, so clear the marker first.
  await page.evaluate(() => {
    document.querySelectorAll('.reopt-fig-num').forEach(e => { e.textContent = 'stale'; });
  });
  const btn = page.getByRole('button', { name: /Get results/i }).first();
  if (await btn.isDisabled()) { log.push('BUTTON DISABLED'); return log.join('\n'); }
  await btn.click();
  let st = null;
  for (let i = 0; i < 60; i++) {
    await page.waitForTimeout(10000);
    st = await page.evaluate(() => {
      const b = document.body.innerText;
      return { done: /Results for your site/i.test(b), failed: /Run failed|Traceback/i.test(b),
               msg: (b.match(/Run failed[^\n]{0,240}/) || [''])[0] };
    });
    if (st.done || st.failed) break;
  }
  log.push('run: ' + JSON.stringify(st));

  if (st && st.done) {
    log.push('results: ' + JSON.stringify(await page.evaluate(() => ({
      figs: Array.from(document.querySelectorAll('.reopt-fig-num')).map(e => e.innerText),
      labs: Array.from(document.querySelectorAll('.reopt-fig-lab')).map(e => e.innerText.trim()),
      cards: Array.from(document.querySelectorAll('.reopt-card-title')).map(e => e.innerText.trim()),
      savings: (document.querySelector('.reopt-savings-value') || {}).innerText,
    })), null, 1));
    // pull whatever the result tables expose as text
    const tbl = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll('[data-testid="stDataFrame"]').forEach(d => {
        const t = (d.innerText || '').replace(/\s+/g, ' ').trim();
        if (t) out.push(t.slice(0, 260));
      });
      return out.slice(0, 6);
    });
    log.push('tables: ' + JSON.stringify(tbl, null, 1));
    await page.screenshot({ path: 'D:/GreenHouseV2/reopt_test_screenshots/parity/PT2-ours-results.png', scale: 'css' });
  }
  return log.join('\n');
}
