// CONTROL 2: PV + Battery, Cost Savings only (NO Resilience).
// Narrows whether the EPIPE backend failure is triggered by the Battery
// technology or by the Resilience (outage) modelling.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots';
  const log = [];
  const t0 = Date.now();
  const stamp = () => ((Date.now() - t0) / 1000).toFixed(1) + 's';

  if (!page.__dlg) {
    page.__dlg = [];
    page.on('dialog', async (d) => { page.__dlg.push(d.message()); try { await d.accept(); } catch (e) {} });
  }
  const set = async (id, v) => {
    try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded(); await l.fill(String(v), { timeout: 8000 }); }
    catch (e) { log.push('  FAIL set ' + id); }
  };
  const pick = async (id, v) => {
    try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded(); await l.selectOption(String(v), { timeout: 8000 }); }
    catch (e) { log.push('  FAIL pick ' + id); }
  };

  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1500);

  for (const [n, ex] of [['PV', true], ['Battery', false]]) {
    const cb = page.getByRole('checkbox', { name: n, exact: ex });
    if (!(await cb.isChecked())) await cb.check();
  }
  await page.waitForTimeout(1200);
  const goals = await page.evaluate(() => ({
    cost: document.getElementById('cost_savings').checked,
    res: document.getElementById('resilience').checked
  }));
  log.push('[' + stamp() + '] techs=PV+Battery  goals=' + JSON.stringify(goals));

  await set('run_site_attributes_description', 'CONTROL2 PV+Battery Cost Savings');
  const addr = page.locator('#run_site_attributes_address');
  let ratesOk = false;
  for (let a = 1; a <= 4 && !ratesOk; a++) {
    await addr.click(); await addr.fill('');
    await addr.type('1617 Cole Blvd, Golden, CO 80401', { delay: 45 });
    await page.waitForTimeout(2300);
    const pac = page.locator('.pac-container .pac-item');
    if (await pac.count()) { await pac.first().click(); } else { await addr.press('ArrowDown'); await addr.press('Enter'); }
    await page.waitForTimeout(5000);
    ratesOk = !(await page.locator('#dropdown-input').isDisabled());
  }
  const dd = page.locator('#dropdown-input');
  await dd.scrollIntoViewIfNeeded(); await dd.click(); await dd.fill('');
  await dd.type('Commercial', { delay: 70 });
  await page.waitForTimeout(2000);
  if (await page.locator('.dropdown-item').count()) { await page.locator('.dropdown-item').first().click(); await page.waitForTimeout(1500); }
  log.push('[' + stamp() + '] rate=' + (await dd.inputValue()).slice(0, 55));

  await set('run_site_attributes_land_acres', '5');
  await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'LargeOffice');
  await page.waitForTimeout(800);
  await set('run_site_attributes_load_profile_attributes_annual_kwh', '5000000');

  // same battery economics as the main scenario
  const panels = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.panel-collapse.collapse'))
      .map((p) => ({ id: p.id, open: getComputedStyle(p).display !== 'none' })));
  for (const p of panels) {
    if (p.open) continue;
    try {
      const t = page.locator('[data-target="#' + p.id + '"], [href="#' + p.id + '"], [aria-controls="' + p.id + '"]').first();
      await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 5000 }); await page.waitForTimeout(400);
    } catch (e) {}
  }
  await set('run_site_attributes_pv_attributes_installed_cost_per_kw', '1600');
  await set('run_site_attributes_pv_attributes_max_kw', '2000');
  await set('run_site_attributes_storage_attributes_installed_cost_per_kwh', '300');
  await set('run_site_attributes_storage_attributes_installed_cost_per_kw', '800');
  await set('run_site_attributes_storage_attributes_installed_cost_constant', '0');
  await set('run_site_attributes_storage_attributes_max_kwh', '4000');
  await page.waitForTimeout(600);
  await page.screenshot({ path: SHOTS + '/15-control2-form.png', scale: 'css' });

  await page.getByRole('button', { name: /Get Results/i }).first().click();
  try { await page.waitForURL(/\/tool\/results\//, { timeout: 60000 }); } catch (e) {}
  await page.waitForTimeout(3000);
  log.push('[' + stamp() + '] submitted url=' + page.url());

  let final = null;
  for (let i = 0; i < 24; i++) {
    await page.waitForTimeout(10000);
    final = await page.evaluate(() => {
      const b = document.body.innerText.replace(/\s+/g, ' ');
      return { running: /Optimizing your results/i.test(b), oops: /Oops!/i.test(b),
               done: /Life Cycle|life cycle savings|System Performance/i.test(b) && !/Optimizing your results/i.test(b),
               url: location.href,
               err: (b.match(/Oops![^]{0,150}/) || [''])[0] };
    });
    log.push('[' + stamp() + '] poll ' + (i + 1) + ' running=' + final.running + ' oops=' + final.oops + ' done=' + final.done);
    if (!final.running) break;
  }
  await page.screenshot({ path: SHOTS + '/16-control2-result.png', scale: 'css' });
  log.push('FINAL: ' + JSON.stringify(final));
  return log.join('\n');
}
