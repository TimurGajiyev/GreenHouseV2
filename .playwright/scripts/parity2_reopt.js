// PT2 -- fresh scenario, controlled tariff.
// The Phoenix attempt (PT1) could not be used: the tool submits the rate by
// display name and resolves it server-side to a record whose implied energy
// price is ~$0.58/kWh, which no URDB rate at that location comes near. So PT2
// keeps the one tariff whose parsing is already proven exact (Intermountain REA
// B-TOU, urdb 5b44ffc75457a36716a907eb) and changes everything else: different
// building, load, costs, horizon, discount rate, escalation and land.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/parity';
  const log = [];

  if (!page.__dlg) {
    page.__dlg = [];
    page.on('dialog', async d => { page.__dlg.push(d.message()); try { await d.accept(); } catch (e) {} });
  }
  const set = async (id, v) => {
    try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded();
          await l.fill(String(v), { timeout: 8000 }); }
    catch (e) { log.push('  FAIL set ' + id); }
  };
  const pick = async (id, v) => {
    try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded();
          await l.selectOption(String(v), { timeout: 8000 }); }
    catch (e) { log.push('  FAIL pick ' + id); }
  };
  const expandAll = async () => {
    for (let p = 0; p < 4; p++) {
      const closed = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
        .filter(c => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none').map(c => c.id));
      if (!closed.length) break;
      for (const id of closed) {
        try { const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
          await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 3500 }); await page.waitForTimeout(300); } catch (e) {}
      }
    }
  };

  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(3000);
  for (const id of ['run_analyze_pv', 'run_analyze_battery']) {
    try { await page.locator('#' + id).check({ timeout: 6000 }); } catch (e) { log.push('  FAIL tech ' + id); }
  }
  await page.waitForTimeout(2500);
  await set('run_site_attributes_description', 'PT2 Golden supermarket parity');

  let ratesOk = false;
  for (let a = 1; a <= 4 && !ratesOk; a++) {
    const addr = page.locator('#run_site_attributes_address');
    await addr.scrollIntoViewIfNeeded(); await addr.click(); await addr.fill('');
    await addr.type('1617 Cole Blvd, Golden, CO 80401', { delay: 45 });
    await page.waitForTimeout(2400);
    const pac = page.locator('.pac-container .pac-item');
    if (await pac.count()) await pac.first().click();
    else { await addr.press('ArrowDown'); await addr.press('Enter'); }
    await page.waitForTimeout(5000);
    ratesOk = !(await page.locator('#dropdown-input').isDisabled());
  }
  const dd = page.locator('#dropdown-input');
  await dd.scrollIntoViewIfNeeded(); await dd.click(); await dd.fill('');
  await dd.type('Commercial Demand Metered Time of Use', { delay: 35 });
  await page.waitForTimeout(2400);
  const items = page.locator('.dropdown-item');
  const n = await items.count();
  if (n) { await items.first().click(); await page.waitForTimeout(2000); }
  log.push('rate (' + n + '): ' + (await dd.inputValue()).slice(0, 80));

  await set('run_site_attributes_land_acres', 6);
  await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'Supermarket');
  await page.waitForTimeout(900);
  await set('run_site_attributes_load_profile_attributes_annual_kwh', 3000000);

  await expandAll();
  await set('run_site_attributes_financial_attributes_analysis_years', 20);
  await set('run_site_attributes_financial_attributes_offtaker_discount_rate_fraction', 7.5);
  await set('run_site_attributes_financial_attributes_elec_cost_escalation_rate_fraction', 2.2);
  await set('run_site_attributes_pv_attributes_installed_cost_per_kw', 1850);
  await set('run_site_attributes_pv_attributes_min_kw', 0);
  await set('run_site_attributes_pv_attributes_max_kw', 1500);
  await set('run_site_attributes_storage_attributes_installed_cost_per_kwh', 320);
  await set('run_site_attributes_storage_attributes_installed_cost_per_kw', 850);
  await set('run_site_attributes_storage_attributes_installed_cost_constant', 0);
  await set('run_site_attributes_storage_attributes_max_kwh', 3000);
  await page.waitForTimeout(900);
  await page.screenshot({ path: SHOTS + '/PT2-reopt-form.png', scale: 'css' });

  await page.getByRole('button', { name: /Get Results/i }).first().click();
  try { await page.waitForURL(/\/tool\/results\//, { timeout: 60000 }); } catch (e) {}
  log.push('url ' + page.url());

  let st = null;
  for (let i = 0; i < 55; i++) {
    await page.waitForTimeout(10000);
    try {
      st = await page.evaluate(() => {
        const b = document.body.innerText.replace(/\s+/g, ' ');
        return { running: /Optimizing your results/i.test(b), oops: /Oops!/i.test(b),
                 done: /Results Comparison|System Sizes/i.test(b) && !/Optimizing your results/i.test(b) };
      });
    } catch (e) { continue; }
    if (!st.running) break;
  }
  log.push(JSON.stringify(st));

  if (st && st.done) {
    await expandAll();
    await page.evaluate(() => document.querySelectorAll('.panel-collapse.collapse')
      .forEach(x => { x.classList.add('in'); x.style.display = 'block'; x.style.height = 'auto'; }));
    await page.waitForTimeout(2500);
    const rows = await page.evaluate(() => {
      const clean = s => (s || '').replace(/\s+/g, ' ').trim();
      const o = {};
      document.querySelectorAll('.panel-collapse').forEach(p => {
        if (!p.id) return;
        p.querySelectorAll('table tr').forEach(tr => {
          const cs = Array.from(tr.querySelectorAll('th,td')).map(x => clean(x.innerText));
          if (cs.length > 1 && cs[0]) o[cs[0]] = cs.slice(1);
        });
      });
      return o;
    });
    await page.screenshot({ path: SHOTS + '/PT2-reopt-results.png', scale: 'css' });
    const keep = {};
    ['PV Size','Battery Power','Battery Capacity','Total Life Cycle Costs','Net Present Value',
     'Total Year 1 Utility Cost - Before Tax','Utility Energy Cost','Utility Demand Cost',
     'Utility Fixed Cost','Total Upfront Capital Cost Before Incentives',
     'Average Annual PV Energy Production','Year 1 O&M Cost, Before Tax',
     'PV Serving Load (kWh)','PV Charging Battery (kWh)','PV Curtailment (kWh)',
     'PV Total Electricity Produced (kWh)','Battery Serving Load (kWh)',
     'Grid Serving Load (kWh)','Grid Charging Battery (kWh)','URDB rate',
     'Site Location','Type of building','Annual electric energy consumption (kWh)',
     'Land available (acres)','Analysis period (years)','Solver optimality tolerance (%)',
     'O&M cost ($/kW-DC per year)','Array tilt (deg)','Compensation type']
      .forEach(k => { if (rows[k]) keep[k] = rows[k]; });
    log.push(JSON.stringify(keep, null, 1));
  }
  return log.join('\n');
}
