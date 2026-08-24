// SCENARIO 2 — OFF-GRID: Generator + Battery + PV.
// CHP is not offered off-grid (UI removes it); no ElectricTariff panel exists.
// Size caps left at defaults so the year-long island stays feasible.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/offgrid';
  const log = [];
  const t0 = Date.now();
  const stamp = () => ((Date.now() - t0) / 1000).toFixed(1) + 's';
  const shot = async (n) => { await page.screenshot({ path: SHOTS + '/' + n + '.png', scale: 'css' }); log.push('[' + stamp() + '] shot ' + n); };

  if (!page.__dlg) { page.__dlg = []; page.on('dialog', async (d) => { page.__dlg.push(d.message()); try { await d.accept(); } catch (e) {} }); }
  const set = async (id, v) => { try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded(); await l.fill(String(v), { timeout: 8000 }); }
                                 catch (e) { log.push('  FAIL set ' + id); } };
  const pick = async (id, v) => { try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded(); await l.selectOption(String(v), { timeout: 8000 }); }
                                  catch (e) { log.push('  FAIL pick ' + id); } };

  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1500);
  await shot('01-landing');

  await page.locator('#run_off_grid').check();
  await page.waitForTimeout(2500);
  await shot('02-offgrid-selected');

  for (const id of ['run_analyze_generator', 'run_analyze_battery', 'run_analyze_pv']) {
    try { await page.locator('#' + id).check({ timeout: 5000 }); } catch (e) { log.push('  FAIL tick ' + id); }
  }
  await page.waitForTimeout(2000);
  const techs = await page.evaluate(() => { const o = {}; document.querySelectorAll('input[id^=run_analyze_]').forEach((c) => { o[c.id.replace('run_analyze_', '')] = c.checked; }); return o; });
  log.push('[' + stamp() + '] techs=' + JSON.stringify(techs));
  await shot('03-techs-selected');

  await set('run_site_attributes_description', 'OFFGRID Generator+Battery+PV');
  const addr = page.locator('#run_site_attributes_address');
  await addr.click(); await addr.fill('');
  await addr.type('1617 Cole Blvd, Golden, CO 80401', { delay: 45 });
  await page.waitForTimeout(2500);
  const pac = page.locator('.pac-container .pac-item');
  if (await pac.count()) { await pac.first().click(); } else { await addr.press('ArrowDown'); await addr.press('Enter'); }
  await page.waitForTimeout(4000);
  log.push('[' + stamp() + '] address=' + (await addr.inputValue()).slice(0, 55));

  await set('run_site_attributes_land_acres', '5');
  await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'LargeOffice');
  await page.waitForTimeout(800);
  await set('run_site_attributes_load_profile_attributes_annual_kwh', '5000000');
  await shot('04-site-and-load');

  // expand all panels
  const panels = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
    .map((p) => ({ id: p.id, open: getComputedStyle(p).display !== 'none' })));
  for (const p of panels) {
    if (p.open || p.id === 'topnav-collapse') continue;
    try { const t = page.locator('[data-target="#' + p.id + '"], [href="#' + p.id + '"], [aria-controls="' + p.id + '"]').first();
      await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 5000 }); await page.waitForTimeout(450); } catch (e) {}
  }
  log.push('[' + stamp() + '] panels=' + JSON.stringify(panels.map((p) => p.id)));
  await shot('05-panels-expanded');

  // off-grid specific reliability inputs
  await set('run_site_attributes_load_profile_attributes_min_load_met_annual_fraction', '99.9');
  await set('run_site_attributes_load_profile_attributes_operating_reserve_required_fraction', '10');

  // economics — costs only; leave size caps at defaults for feasibility
  await set('run_site_attributes_financial_attributes_analysis_years', '25');
  await set('run_site_attributes_financial_attributes_offtaker_discount_rate_fraction', '8.3');
  await set('run_site_attributes_pv_attributes_installed_cost_per_kw', '1600');
  await set('run_site_attributes_storage_attributes_installed_cost_per_kwh', '300');
  await set('run_site_attributes_storage_attributes_installed_cost_per_kw', '800');
  await set('run_site_attributes_storage_attributes_installed_cost_constant', '0');
  await page.waitForTimeout(800);
  await shot('06-form-complete');

  await page.getByRole('button', { name: /Get Results/i }).first().click();
  try { await page.waitForURL(/\/tool\/results\//, { timeout: 60000 }); } catch (e) {}
  await page.waitForTimeout(3000);
  log.push('[' + stamp() + '] submitted url=' + page.url());
  await shot('07-submitted');

  const errs = await page.evaluate(() => Array.from(document.querySelectorAll('.error,.alert-danger,[class*=error]'))
    .filter((x) => x.getClientRects().length && x.innerText.trim())
    .slice(0, 3).map((x) => x.innerText.trim().replace(/\s+/g, ' ').slice(0, 240)));
  if (errs.length) log.push('VALIDATION: ' + JSON.stringify(errs));

  let final = null;
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(10000);
    try {
      final = await page.evaluate(() => {
        const b = document.body.innerText.replace(/\s+/g, ' ');
        return { running: /Optimizing your results/i.test(b), oops: /Oops!/i.test(b),
                 done: /Results Comparison|life cycle|System Performance/i.test(b) && !/Optimizing your results/i.test(b),
                 url: location.href, err: (b.match(/Oops![^]{0,170}/) || [''])[0] };
      });
    } catch (e) { log.push('  poll ' + (i + 1) + ' navigating'); continue; }
    log.push('[' + stamp() + '] poll ' + (i + 1) + ' running=' + final.running + ' oops=' + final.oops + ' done=' + final.done);
    if (!final.running) break;
  }
  await shot('08-result');
  log.push('FINAL: ' + JSON.stringify(final));
  return log.join('\n');
}
