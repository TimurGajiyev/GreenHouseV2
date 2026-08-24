// TEST CASE 2 on the real REopt tool.
// Phoenix AZ · Supermarket · 3,000,000 kWh · 2 acres · PV + Battery
// PV $2000/kW max 1000 kW · Battery $350/kWh $900/kW const $0 max 2000 kWh
// 20 years · discount 7.5% · elec escalation 2.2%
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/testcase2';
  const log = [];
  if (!page.__dlg) { page.__dlg = []; page.on('dialog', async d => { page.__dlg.push(d.message()); try { await d.accept(); } catch (e) {} }); }

  const set = async (id, v) => { try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded(); await l.fill(String(v), { timeout: 8000 }); } catch (e) { log.push('  FAIL set ' + id); } };
  const pick = async (id, v) => { try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded(); await l.selectOption(String(v), { timeout: 8000 }); } catch (e) { log.push('  FAIL pick ' + id); } };

  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(2000);
  for (const id of ['run_analyze_pv', 'run_analyze_battery']) {
    try { await page.locator('#' + id).check({ timeout: 5000 }); } catch (e) {}
  }
  await page.waitForTimeout(2000);
  await set('run_site_attributes_description', 'TC2 Phoenix Supermarket');

  let ratesOk = false;
  for (let a = 1; a <= 4 && !ratesOk; a++) {
    const addr = page.locator('#run_site_attributes_address');
    await addr.click(); await addr.fill('');
    await addr.type('3401 N Central Ave, Phoenix, AZ 85012', { delay: 45 });
    await page.waitForTimeout(2400);
    const pac = page.locator('.pac-container .pac-item');
    if (await pac.count()) await pac.first().click(); else { await addr.press('ArrowDown'); await addr.press('Enter'); }
    await page.waitForTimeout(5000);
    ratesOk = !(await page.locator('#dropdown-input').isDisabled());
  }
  log.push('rates ready=' + ratesOk);

  const dd = page.locator('#dropdown-input');
  await dd.scrollIntoViewIfNeeded(); await dd.click(); await dd.fill('');
  await dd.type('Commercial', { delay: 50 });
  await page.waitForTimeout(2200);
  const items = page.locator('.dropdown-item');
  const n = await items.count();
  log.push('rate options: ' + n);
  if (n) {
    await items.first().click();
    await page.waitForTimeout(1800);
  }
  const chosenRate = await dd.inputValue();
  log.push('RATE: ' + chosenRate);

  await set('run_site_attributes_land_acres', '2');
  await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'Supermarket');
  await page.waitForTimeout(800);
  await set('run_site_attributes_load_profile_attributes_annual_kwh', '3000000');

  for (let p = 0; p < 2; p++) {
    const closed = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
      .filter(c => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none').map(c => c.id));
    if (!closed.length) break;
    for (const id of closed) {
      try { const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
        await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 4000 }); await page.waitForTimeout(400); } catch (e) {}
    }
  }
  await set('run_site_attributes_financial_attributes_analysis_years', '20');
  await set('run_site_attributes_financial_attributes_offtaker_discount_rate_fraction', '7.5');
  await set('run_site_attributes_financial_attributes_elec_cost_escalation_rate_fraction', '2.2');
  await set('run_site_attributes_pv_attributes_installed_cost_per_kw', '2000');
  await set('run_site_attributes_pv_attributes_min_kw', '0');
  await set('run_site_attributes_pv_attributes_max_kw', '1000');
  await set('run_site_attributes_storage_attributes_installed_cost_per_kwh', '350');
  await set('run_site_attributes_storage_attributes_installed_cost_per_kw', '900');
  await set('run_site_attributes_storage_attributes_installed_cost_constant', '0');
  await set('run_site_attributes_storage_attributes_max_kwh', '2000');
  await page.waitForTimeout(900);
  await page.screenshot({ path: SHOTS + '/A-reopt-form.png', scale: 'css', fullPage: true });

  await page.getByRole('button', { name: /Get Results/i }).first().click();
  try { await page.waitForURL(/\/tool\/results\//, { timeout: 60000 }); } catch (e) {}
  log.push('submitted: ' + page.url());

  let st = null;
  for (let i = 0; i < 40; i++) {
    await page.waitForTimeout(10000);
    try {
      st = await page.evaluate(() => {
        const b = document.body.innerText.replace(/\s+/g, ' ');
        return { running: /Optimizing your results/i.test(b), oops: /Oops!/i.test(b),
                 done: /Results Comparison/i.test(b) && !/Optimizing your results/i.test(b) };
      });
    } catch (e) { continue; }
    if (!st.running) break;
  }
  log.push('final: ' + JSON.stringify(st));

  if (st && st.done) {
    for (let p = 0; p < 3; p++) {
      const closed = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
        .filter(c => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none').map(c => c.id));
      if (!closed.length) break;
      for (const id of closed) {
        try { const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
          await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 3500 }); await page.waitForTimeout(300); } catch (e) {}
      }
    }
    await page.evaluate(() => document.querySelectorAll('.panel-collapse.collapse')
      .forEach(c => { c.classList.add('in'); c.style.display = 'block'; c.style.height = 'auto'; }));
    await page.waitForTimeout(2500);

    const dump = await page.evaluate(() => {
      const clean = s => (s || '').replace(/\s+/g, ' ').trim();
      const out = {};
      document.querySelectorAll('.panel-collapse').forEach(panel => {
        if (!panel.id || panel.id === 'topnav-collapse') return;
        const rows = [];
        panel.querySelectorAll('table tr').forEach(tr => {
          const c = Array.from(tr.querySelectorAll('th,td')).map(x => clean(x.innerText));
          if (c.length > 1) rows.push(c);
        });
        if (rows.length) out[panel.id] = rows;
      });
      return out;
    });
    await page.evaluate(d => { window.__tc2 = d; }, JSON.stringify(dump));
    log.push('captured sections: ' + Object.keys(dump).join(', '));
    await page.screenshot({ path: SHOTS + '/A-reopt-results.png', scale: 'css', fullPage: true });
  } else {
    await page.screenshot({ path: SHOTS + '/A-reopt-failed.png', scale: 'css', fullPage: true });
  }
  return log.join('\n');
}
