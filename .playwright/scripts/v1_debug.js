// Why did V1 (Chicago, roofspace, net metering, 30 yr) not submit?
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/variability';
  const log = [];
  if (!page.__dlg) { page.__dlg = []; page.on('dialog', async d => { page.__dlg.push(d.message()); try { await d.accept(); } catch (e) {} }); }
  const set = async (id, v) => { try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded(); await l.fill(String(v), { timeout: 8000 }); } catch (e) { log.push('  FAIL set ' + id); } };
  const pick = async (id, v) => { try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded(); await l.selectOption(String(v), { timeout: 8000 }); } catch (e) { log.push('  FAIL pick ' + id); } };

  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(2200);
  await page.locator('#run_analyze_pv').check();
  await page.waitForTimeout(1800);
  await set('run_site_attributes_description', 'V1 debug');

  let ratesOk = false;
  for (let a = 1; a <= 4 && !ratesOk; a++) {
    const addr = page.locator('#run_site_attributes_address');
    await addr.click(); await addr.fill('');
    await addr.type('Chicago, IL', { delay: 40 });
    await page.waitForTimeout(2300);
    const pac = page.locator('.pac-container .pac-item');
    if (await pac.count()) await pac.first().click(); else { await addr.press('ArrowDown'); await addr.press('Enter'); }
    await page.waitForTimeout(4800);
    ratesOk = !(await page.locator('#dropdown-input').isDisabled());
  }
  log.push('rates=' + ratesOk);

  // roofspace only
  await page.locator('#run_site_attributes_pv_wind_space_available_roofspace').check();
  await page.waitForTimeout(1200);
  const roofField = await page.evaluate(() => {
    const e = document.getElementById('run_site_attributes_roof_squarefeet');
    return e ? { exists: true, visible: e.getClientRects().length > 0, value: e.value } : { exists: false };
  });
  log.push('roof field: ' + JSON.stringify(roofField));
  await set('run_site_attributes_roof_squarefeet', 120000);

  const dd = page.locator('#dropdown-input');
  await dd.click(); await dd.fill(''); await dd.type('Commercial', { delay: 40 });
  await page.waitForTimeout(2000);
  if (await page.locator('.dropdown-item').count()) { await page.locator('.dropdown-item').first().click(); await page.waitForTimeout(1500); }

  await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'Hospital');
  await page.waitForTimeout(700);
  await set('run_site_attributes_load_profile_attributes_annual_kwh', 8000000);

  for (let p = 0; p < 2; p++) {
    const closed = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
      .filter(c => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none').map(c => c.id));
    if (!closed.length) break;
    for (const id of closed) {
      try { const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
        await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 3500 }); await page.waitForTimeout(300); } catch (e) {}
    }
  }
  await set('run_site_attributes_financial_attributes_analysis_years', 30);
  await set('run_site_attributes_financial_attributes_offtaker_discount_rate_fraction', 6.0);
  await set('run_site_attributes_financial_attributes_elec_cost_escalation_rate_fraction', 2.5);
  await pick('run_site_attributes_electric_tariff_attributes_compensation_type', 'net_metering');
  await page.waitForTimeout(1200);
  // net metering makes this field required
  await set('run_site_attributes_electric_tariff_attributes_net_metering_limit_kw', 1000);
  await page.waitForTimeout(600);
  await set('run_site_attributes_pv_attributes_installed_cost_per_kw', 1750);
  await set('run_site_attributes_pv_attributes_max_kw', 1500);
  await page.waitForTimeout(900);

  // what does net_metering reveal?
  const nem = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('input,select').forEach(e => {
      const id = e.id || '';
      if (/net_meter|interconnection|wholesale|export/i.test(id) && e.type !== 'hidden') {
        const l = e.id ? document.querySelector('label[for="' + CSS.escape(e.id) + '"]') : null;
        out.push({ id, value: e.value, visible: e.getClientRects().length > 0,
                   label: l ? l.innerText.replace(/\s+/g, ' ').trim().slice(0, 46) : '' });
      }
    });
    return out;
  });
  log.push('NEM fields: ' + JSON.stringify(nem, null, 1));

  await page.getByRole('button', { name: /Get Results/i }).first().click();
  try { await page.waitForURL(/\/tool\/results\//, { timeout: 60000 }); } catch (e) {}
  let st = null;
  for (let i = 0; i < 40; i++) {
    await page.waitForTimeout(10000);
    try { st = await page.evaluate(() => { const b = document.body.innerText.replace(/\s+/g,' ');
      return { running:/Optimizing your results/i.test(b), oops:/Oops!/i.test(b),
               done:/Results Comparison/i.test(b) && !/Optimizing your results/i.test(b) }; }); }
    catch (e) { continue; }
    if (!st.running) break;
  }
  log.push('run state: ' + JSON.stringify(st) + '  url=' + page.url());
  if (st && st.done) {
    for (let p = 0; p < 3; p++) {
      const closed = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
        .filter(c => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none').map(c => c.id));
      if (!closed.length) break;
      for (const id of closed) {
        try { const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
          await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 3500 }); await page.waitForTimeout(280); } catch (e) {}
      }
    }
    await page.evaluate(() => document.querySelectorAll('.panel-collapse.collapse')
      .forEach(c => { c.classList.add('in'); c.style.display='block'; c.style.height='auto'; }));
    await page.waitForTimeout(1800);
    const dump = await page.evaluate(() => { const clean = s => (s||'').replace(/\s+/g,' ').trim();
      const rows = {}; document.querySelectorAll('.panel-collapse').forEach(p => { if (!p.id) return;
        p.querySelectorAll('table tr').forEach(tr => { const cs = Array.from(tr.querySelectorAll('th,td')).map(x => clean(x.innerText));
          if (cs.length > 1 && cs[0]) rows[cs[0]] = cs.slice(1); }); }); return rows; });
    await page.evaluate(d => { window.__v1 = d; }, JSON.stringify({ url: page.url(), rows: dump }));
    log.push('PV=' + ((dump['PV Size']||[])[1]||'-') + '  Y1=' + ((dump['Total Year 1 Utility Cost - Before Tax']||[])[1]||'-')
             + '  LCC=' + ((dump['Total Life Cycle Costs']||[])[1]||'-')
             + '  rate=' + ((dump['URDB rate']||[])[0]||'-'));
  }
  const err = await page.evaluate(() => {
    const es = Array.from(document.querySelectorAll('.error,.alert-danger,[class*=error]'))
      .filter(x => x.getClientRects().length && x.innerText.trim())
      .map(x => x.innerText.replace(/\s+/g, ' ').trim().slice(0, 300));
    return { url: location.href, errors: es.slice(0, 4), dialogs: null };
  });
  log.push('after submit: ' + JSON.stringify(err, null, 1));
  log.push('dialogs: ' + JSON.stringify(page.__dlg.slice(-2)));
  await page.screenshot({ path: SHOTS + '/V1-debug.png', scale: 'css' });
  return log.join('\n');
}
