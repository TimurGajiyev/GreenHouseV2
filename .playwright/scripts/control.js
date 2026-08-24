// CONTROL EXPERIMENT: minimal Cost-Savings + PV-only run at the same site.
// Purpose: isolate whether the EPIPE backend failure is specific to the
// PV+Battery+Resilience scenario or affects the service generally.
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

  // Cost Savings only (default), PV only. No Resilience, no Battery.
  const pv = page.getByRole('checkbox', { name: 'PV', exact: true });
  if (!(await pv.isChecked())) await pv.check();
  await page.waitForTimeout(1200);
  log.push('[' + stamp() + '] techs=PV only, goals=CostSavings only');

  await set('run_site_attributes_description', 'CONTROL PV-only Cost Savings');
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
  log.push('[' + stamp() + '] rates ready=' + ratesOk);

  const dd = page.locator('#dropdown-input');
  await dd.scrollIntoViewIfNeeded(); await dd.click(); await dd.fill('');
  await dd.type('Commercial', { delay: 70 });
  await page.waitForTimeout(2000);
  if (await page.locator('.dropdown-item').count()) { await page.locator('.dropdown-item').first().click(); await page.waitForTimeout(1500); }
  log.push('[' + stamp() + '] rate=' + (await dd.inputValue()).slice(0, 60));

  await set('run_site_attributes_land_acres', '5');
  await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'LargeOffice');
  await page.waitForTimeout(800);
  await set('run_site_attributes_load_profile_attributes_annual_kwh', '5000000');
  await page.waitForTimeout(800);
  await page.screenshot({ path: SHOTS + '/12-control-form.png', scale: 'css' });

  await page.getByRole('button', { name: /Get Results/i }).first().click();
  try { await page.waitForURL(/\/tool\/results\//, { timeout: 60000 }); } catch (e) {}
  await page.waitForTimeout(3000);
  log.push('[' + stamp() + '] submitted url=' + page.url());
  await page.screenshot({ path: SHOTS + '/13-control-submitted.png', scale: 'css' });

  // poll up to ~4 minutes for completion
  let final = null;
  for (let i = 0; i < 24; i++) {
    await page.waitForTimeout(10000);
    final = await page.evaluate(() => {
      const b = document.body.innerText.replace(/\s+/g, ' ');
      return { running: /Optimizing your results/i.test(b), oops: /Oops!/i.test(b),
               done: /Net Present Value|Life Cycle Cost|System Size/i.test(b) && !/Optimizing your results/i.test(b),
               url: location.href, head: b.slice(0, 170) };
    });
    log.push('[' + stamp() + '] poll ' + (i + 1) + ' running=' + final.running + ' oops=' + final.oops + ' done=' + final.done);
    if (!final.running) break;
  }
  await page.screenshot({ path: SHOTS + '/14-control-result.png', scale: 'css' });
  log.push('FINAL: ' + JSON.stringify(final));
  return log.join('\n');
}
