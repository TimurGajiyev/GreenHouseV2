// End-to-end REopt Web Tool automation: PV + Battery + Resilience scenario.
// Target: https://reopt.nlr.gov/tool
// Run via Playwright MCP `browser_run_code_unsafe` (receives `page`).
//
// Discovered quirks this script works around:
//   1. GET /tool/utility-rates intermittently returns HTTP 500 -> retry the address entry.
//   2. Outage start date + hour are REQUIRED by the backend but NOT enforced client-side;
//      omitting them yields: ElectricUtility.outage_start_time_steps "cannot be null".
//   3. Outage / Financial / PV / Battery inputs live inside collapsed Bootstrap panels
//      and must be expanded before they are fillable.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots';
  const log = [];
  const t0 = Date.now();
  const stamp = () => ((Date.now() - t0) / 1000).toFixed(1) + 's';
  const shot = async (n) => {
    await page.screenshot({ path: SHOTS + '/' + n + '.png', scale: 'css' });
    log.push('[' + stamp() + '] shot ' + n);
  };

  // ---- network capture + dialog auto-accept (idempotent across calls) ----
  if (!page.__cap) {
    page.__cap = [];
    page.on('request', (r) => {
      if (/\/tool\/(results|utility-rates|simulated|fetch)/i.test(r.url())) {
        let body = null;
        try { body = r.postData(); } catch (e) {}
        page.__cap.push({ t: Date.now(), dir: 'req', method: r.method(), url: r.url(), body: body });
      }
    });
    page.on('response', (r) => {
      if (/\/tool\/(results|utility-rates|simulated|fetch)/i.test(r.url())) {
        page.__cap.push({ t: Date.now(), dir: 'resp', status: r.status(), url: r.url() });
      }
    });
  }
  if (!page.__dlg) {
    page.__dlg = [];
    page.on('dialog', async (d) => { page.__dlg.push(d.message()); try { await d.accept(); } catch (e) {} });
  }

  const set = async (id, v) => {
    try {
      const l = page.locator('#' + id);
      await l.scrollIntoViewIfNeeded();
      await l.fill(String(v), { timeout: 8000 });
    } catch (e) { log.push('  FAIL set ' + id); }
  };
  const pick = async (id, v) => {
    try {
      const l = page.locator('#' + id);
      await l.scrollIntoViewIfNeeded();
      await l.selectOption(String(v), { timeout: 8000 });
    } catch (e) { log.push('  FAIL pick ' + id); }
  };
  const tick = async (name, exact) => {
    const cb = page.getByRole('checkbox', { name: name, exact: !!exact });
    try {
      if (!(await cb.isChecked())) await cb.check({ timeout: 5000 });
    } catch (e) {
      try { await cb.click({ force: true }); } catch (e2) { log.push('  FAIL tick ' + name); }
    }
  };

  // ---- 1. load page + scenario selection ----
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1500);
  await shot('01-landing');
  await tick('Resilience');
  await tick('PV', true);
  await tick('Battery');
  await page.waitForTimeout(1500);
  await shot('02-goals-and-techs');
  log.push('[' + stamp() + '] goals=CostSavings+Resilience techs=PV+Battery');

  // ---- 2. site description + address (retry: utility-rates intermittently 500s) ----
  await set('run_site_attributes_description', 'GreenHouseV2 PV+Battery Resilience Test');
  const ADDR = '1617 Cole Blvd, Golden, CO 80401';
  let ratesOk = false;
  for (let a = 1; a <= 4 && !ratesOk; a++) {
    const addr = page.locator('#run_site_attributes_address');
    await addr.click();
    await addr.fill('');
    await addr.type(ADDR, { delay: 45 });
    await page.waitForTimeout(2300);
    if (a === 1) await shot('03-address-autocomplete');
    const pac = page.locator('.pac-container .pac-item');
    if (await pac.count()) { await pac.first().click(); }
    else { await addr.press('ArrowDown'); await addr.press('Enter'); }
    await page.waitForTimeout(5000);
    ratesOk = !(await page.locator('#dropdown-input').isDisabled());
    log.push('[' + stamp() + '] address attempt ' + a + ' -> rates ' + (ratesOk ? 'OK' : 'not ready'));
  }
  await shot('04-location-resolved');

  // ---- 3. electricity rate (custom search dropdown -> urdb_label) ----
  const dd = page.locator('#dropdown-input');
  await dd.scrollIntoViewIfNeeded();
  await dd.click();
  await dd.fill('');
  await dd.type('Commercial', { delay: 70 });
  await page.waitForTimeout(2000);
  await shot('05-rate-dropdown-open');
  if (await page.locator('.dropdown-item').count()) {
    await page.locator('.dropdown-item').first().click();
    await page.waitForTimeout(2000);
  }
  log.push('[' + stamp() + '] rate = ' + (await dd.inputValue()));

  // ---- 4. site + load profile ----
  await set('run_site_attributes_land_acres', '5');
  await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'LargeOffice');
  await page.waitForTimeout(800);
  await set('run_site_attributes_load_profile_attributes_annual_kwh', '5000000');
  await shot('06-site-load-outage');

  // ---- 5. expand every collapsed panel ----
  const panels = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.panel-collapse.collapse'))
      .map((p) => ({ id: p.id, open: getComputedStyle(p).display !== 'none' })));
  for (const p of panels) {
    if (p.open) continue;
    try {
      const t = page.locator('[data-target="#' + p.id + '"], [href="#' + p.id + '"], [aria-controls="' + p.id + '"]').first();
      await t.scrollIntoViewIfNeeded();
      await t.click({ timeout: 5000 });
      await page.waitForTimeout(500);
    } catch (e) { log.push('  could not expand ' + p.id); }
  }
  await shot('07-all-panels-expanded');

  // ---- 6. resilience / outage ----
  await pick('run_site_attributes_load_profile_attributes_number_of_outages', '1');
  await page.waitForTimeout(700);
  await set('run_site_attributes_load_profile_attributes_outage_duration', '48');
  await set('run_site_attributes_load_profile_attributes_critical_load_fraction', '50');
  await page.evaluate(() => {
    const d = document.getElementById('run_site_attributes_load_profile_attributes_outage_start_date');
    if (d) {
      d.value = '2024-07-16';
      ['input', 'change', 'blur'].forEach((t) => d.dispatchEvent(new Event(t, { bubbles: true })));
    }
  });
  await pick('run_site_attributes_load_profile_attributes_outage_start_hour', '17');

  // ---- 7. financial / PV / battery ----
  await set('run_site_attributes_financial_attributes_analysis_years', '25');
  await set('run_site_attributes_financial_attributes_offtaker_discount_rate_fraction', '8.3');
  await set('run_site_attributes_financial_attributes_elec_cost_escalation_rate_fraction', '1.7');
  await set('run_site_attributes_pv_attributes_installed_cost_per_kw', '1600');
  await set('run_site_attributes_pv_attributes_min_kw', '0');
  await set('run_site_attributes_pv_attributes_max_kw', '2000');
  await set('run_site_attributes_storage_attributes_installed_cost_per_kwh', '300');
  await set('run_site_attributes_storage_attributes_installed_cost_per_kw', '800');
  await set('run_site_attributes_storage_attributes_installed_cost_constant', '0');
  await set('run_site_attributes_storage_attributes_om_cost_fraction_of_installed_cost', '2.5');
  await set('run_site_attributes_storage_attributes_min_kwh', '0');
  await set('run_site_attributes_storage_attributes_max_kwh', '4000');
  await pick('run_site_attributes_storage_attributes_can_grid_charge', 'true');
  await pick('run_site_attributes_storage_attributes_dispatch_strategy', 'cost_optimal');
  await page.waitForTimeout(800);
  await shot('08-form-filled');

  // ---- 8. submit ----
  await shot('09-before-submit');
  await page.getByRole('button', { name: /Get Results/i }).first().click();
  try { await page.waitForURL(/\/tool\/results\//, { timeout: 60000 }); } catch (e) {}
  await page.waitForTimeout(2500);
  await shot('10-submitted');
  log.push('[' + stamp() + '] after submit url=' + page.url());

  const st = await page.evaluate(() => {
    const b = document.body.innerText.replace(/\s+/g, ' ');
    return {
      running: /Optimizing your results/i.test(b),
      oops: /Oops!/i.test(b),
      err: (b.match(/Oops![^]{0,240}/) || [''])[0]
    };
  });
  log.push('[' + stamp() + '] ' + JSON.stringify(st));

  // stash capture so it can be written to disk via browser_evaluate(filename)
  await page.evaluate((d) => { window.__cap = d; }, JSON.stringify(page.__cap || []));
  return log.join('\n');
}
