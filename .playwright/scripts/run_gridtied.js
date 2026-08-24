// SCENARIO 1 — GRID-TIED: Generator + CHP + Battery + PV, Cost Savings.
// CHP forces a thermal subsystem: existing-boiler fuel cost, CHP fuel cost,
// and a separate boiler building type are all required (*).
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/gridtied';
  const log = [];
  const t0 = Date.now();
  const stamp = () => ((Date.now() - t0) / 1000).toFixed(1) + 's';
  const shot = async (n) => { await page.screenshot({ path: SHOTS + '/' + n + '.png', scale: 'css' }); log.push('[' + stamp() + '] shot ' + n); };

  if (!page.__dlg) { page.__dlg = []; page.on('dialog', async (d) => { page.__dlg.push(d.message()); try { await d.accept(); } catch (e) {} }); }
  if (!page.__cap2) {
    page.__cap2 = [];
    page.on('request', (r) => { if (/\/tool\/results/.test(r.url()) && r.method() === 'POST') {
      let b = null; try { b = r.postData(); } catch (e) {} page.__cap2.push({ url: r.url(), body: b }); } });
  }

  const set = async (id, v) => { try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded(); await l.fill(String(v), { timeout: 8000 }); }
                                 catch (e) { log.push('  FAIL set ' + id); } };
  const pick = async (id, v) => { try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded(); await l.selectOption(String(v), { timeout: 8000 }); }
                                  catch (e) { log.push('  FAIL pick ' + id); } };
  const tickId = async (id) => { try { const l = page.locator('#' + id);
      if (!(await l.isChecked())) { await l.check({ timeout: 5000 }); } log.push('  ticked #' + id); }
      catch (e) { try { await page.locator('#' + id).click({ force: true }); log.push('  force #' + id); } catch (e2) { log.push('  FAIL tick #' + id); } } };

  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1500);
  await shot('01-landing');

  // Grid-tied (default) + Cost Savings (default). Techs by ID.
  await tickId('run_grid');
  for (const id of ['run_analyze_generator', 'run_analyze_chp', 'run_analyze_battery', 'run_analyze_pv']) await tickId(id);
  await page.waitForTimeout(2500);
  const techs = await page.evaluate(() => {
    const o = {}; document.querySelectorAll('input[id^=run_analyze_]').forEach((c) => { o[c.id.replace('run_analyze_', '')] = c.checked; }); return o;
  });
  log.push('[' + stamp() + '] techs=' + JSON.stringify(techs));
  await shot('02-techs-selected');

  // site + address
  await set('run_site_attributes_description', 'GRIDTIED Gen+CHP+Battery+PV');
  let ratesOk = false;
  for (let a = 1; a <= 4 && !ratesOk; a++) {
    const addr = page.locator('#run_site_attributes_address');
    await addr.click(); await addr.fill('');
    await addr.type('1617 Cole Blvd, Golden, CO 80401', { delay: 45 });
    await page.waitForTimeout(2300);
    const pac = page.locator('.pac-container .pac-item');
    if (await pac.count()) { await pac.first().click(); } else { await addr.press('ArrowDown'); await addr.press('Enter'); }
    await page.waitForTimeout(5000);
    ratesOk = !(await page.locator('#dropdown-input').isDisabled());
  }
  log.push('[' + stamp() + '] rates ready=' + ratesOk);

  const dd = page.locator('#dropdown-input');
  await dd.scrollIntoViewIfNeeded(); await dd.click(); await dd.fill('');
  await dd.type('Commercial', { delay: 70 });
  await page.waitForTimeout(2000);
  if (await page.locator('.dropdown-item').count()) { await page.locator('.dropdown-item').first().click(); await page.waitForTimeout(1800); }
  log.push('[' + stamp() + '] rate=' + (await dd.inputValue()).slice(0, 60));
  await shot('03-site-and-rate');

  await set('run_site_attributes_land_acres', '5');
  await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'LargeOffice');
  await page.waitForTimeout(800);
  await set('run_site_attributes_load_profile_attributes_annual_kwh', '5000000');

  // --- CHP thermal subsystem (all required) ---
  await pick('run_site_attributes_load_profile_boiler_attributes_doe_reference_name', 'LargeOffice');
  await page.waitForTimeout(600);
  await set('run_site_attributes_load_profile_boiler_attributes_annual_mmbtu', '15000');
  await set('run_site_attributes_boiler_attributes_fuel_blended_annual_rates_per_mmbtu', '8.00');
  await set('run_site_attributes_chp_attributes_fuel_blended_annual_rates_per_mmbtu', '8.00');
  await shot('04-thermal-inputs');

  // expand all panels then fill economics
  const panels = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
    .map((p) => ({ id: p.id, open: getComputedStyle(p).display !== 'none' })));
  for (const p of panels) {
    if (p.open) continue;
    try { const t = page.locator('[data-target="#' + p.id + '"], [href="#' + p.id + '"], [aria-controls="' + p.id + '"]').first();
      await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 5000 }); await page.waitForTimeout(450); } catch (e) {}
  }
  log.push('[' + stamp() + '] panels=' + JSON.stringify(panels.map((p) => p.id)));
  await shot('05-panels-expanded');

  await set('run_site_attributes_financial_attributes_analysis_years', '25');
  await set('run_site_attributes_financial_attributes_offtaker_discount_rate_fraction', '8.3');
  await set('run_site_attributes_financial_attributes_elec_cost_escalation_rate_fraction', '1.7');
  await set('run_site_attributes_pv_attributes_installed_cost_per_kw', '1600');
  await set('run_site_attributes_pv_attributes_min_kw', '0');
  await set('run_site_attributes_pv_attributes_max_kw', '2000');
  await set('run_site_attributes_storage_attributes_installed_cost_per_kwh', '300');
  await set('run_site_attributes_storage_attributes_installed_cost_per_kw', '800');
  await set('run_site_attributes_storage_attributes_installed_cost_constant', '0');
  await set('run_site_attributes_storage_attributes_max_kwh', '4000');
  await page.waitForTimeout(800);
  await shot('06-form-complete');

  // submit
  await page.getByRole('button', { name: /Get Results/i }).first().click();
  try { await page.waitForURL(/\/tool\/results\//, { timeout: 60000 }); } catch (e) {}
  await page.waitForTimeout(3000);
  log.push('[' + stamp() + '] submitted url=' + page.url());
  await shot('07-submitted');

  // any validation error?
  const errs = await page.evaluate(() => Array.from(document.querySelectorAll('.error,.alert-danger,[class*=error]'))
    .filter((x) => x.getClientRects().length && x.innerText.trim())
    .slice(0, 3).map((x) => x.innerText.trim().replace(/\s+/g, ' ').slice(0, 220)));
  if (errs.length) log.push('VALIDATION: ' + JSON.stringify(errs));

  // poll to completion
  let final = null;
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(10000);
    try {
      final = await page.evaluate(() => {
        const b = document.body.innerText.replace(/\s+/g, ' ');
        return { running: /Optimizing your results/i.test(b), oops: /Oops!/i.test(b),
                 done: /Results Comparison|life cycle savings/i.test(b) && !/Optimizing your results/i.test(b),
                 url: location.href, err: (b.match(/Oops![^]{0,160}/) || [''])[0] };
      });
    } catch (e) { log.push('  poll ' + (i + 1) + ' nav in progress'); continue; }
    log.push('[' + stamp() + '] poll ' + (i + 1) + ' running=' + final.running + ' oops=' + final.oops + ' done=' + final.done);
    if (!final.running) break;
  }
  await shot('08-result');
  log.push('FINAL: ' + JSON.stringify(final));
  await page.evaluate((d) => { window.__cap2 = d; }, JSON.stringify(page.__cap2 || []));
  return log.join('\n');
}
