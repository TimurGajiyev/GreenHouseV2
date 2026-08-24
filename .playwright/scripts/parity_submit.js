// Re-apply every PT1 input on the already-loaded form (the first attempt failed
// validation because the tariff had not been selected), then submit and harvest.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/parity';
  const log = [];
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

  await expandAll();
  await set('run_site_attributes_land_acres', 6);
  await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'Supermarket');
  await page.waitForTimeout(900);
  await set('run_site_attributes_load_profile_attributes_annual_kwh', 3000000);
  await expandAll();
  await set('run_site_attributes_financial_attributes_analysis_years', 20);
  await set('run_site_attributes_financial_attributes_offtaker_discount_rate_fraction', 7.5);
  await set('run_site_attributes_financial_attributes_elec_cost_escalation_rate_fraction', 2.2);
  await set('run_site_attributes_pv_attributes_installed_cost_per_kw', 1850);
  await set('run_site_attributes_pv_attributes_om_cost_per_kw', 20);
  await set('run_site_attributes_pv_attributes_min_kw', 0);
  await set('run_site_attributes_pv_attributes_max_kw', 1500);
  await set('run_site_attributes_storage_attributes_installed_cost_per_kwh', 320);
  await set('run_site_attributes_storage_attributes_installed_cost_per_kw', 850);
  await set('run_site_attributes_storage_attributes_installed_cost_constant', 0);
  await set('run_site_attributes_storage_attributes_max_kwh', 3000);
  await page.waitForTimeout(800);

  log.push('inputs ' + JSON.stringify(await page.evaluate(() => {
    const g = id => (document.getElementById(id) || {}).value;
    return {
      lat: g('run_site_attributes_latitude'), lon: g('run_site_attributes_longitude'),
      rate: (g('dropdown-input') || '').slice(0, 62),
      bldg: g('run_site_attributes_load_profile_attributes_doe_reference_name'),
      kwh: g('run_site_attributes_load_profile_attributes_annual_kwh'),
      yrs: g('run_site_attributes_financial_attributes_analysis_years'),
      pvcost: g('run_site_attributes_pv_attributes_installed_cost_per_kw'),
      pvom: g('run_site_attributes_pv_attributes_om_cost_per_kw'),
      pvmax: g('run_site_attributes_pv_attributes_max_kw'),
      bkwh: g('run_site_attributes_storage_attributes_installed_cost_per_kwh'),
      bkw: g('run_site_attributes_storage_attributes_installed_cost_per_kw'),
    };
  })));
  await page.screenshot({ path: SHOTS + '/PT1-reopt-form.png', scale: 'css' });

  await page.getByRole('button', { name: /Get Results/i }).first().click();
  try { await page.waitForURL(/\/tool\/results\//, { timeout: 60000 }); } catch (e) {}
  log.push('url ' + page.url());

  const errs = await page.evaluate(() => Array.from(document.querySelectorAll('.error,.alert-danger,[class*=error]'))
    .filter(x => x.getClientRects().length && x.innerText.trim())
    .slice(0, 4).map(x => x.innerText.replace(/\s+/g, ' ').trim().slice(0, 200)));
  if (errs.length) log.push('VALIDATION ' + JSON.stringify(errs));

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
    await page.screenshot({ path: SHOTS + '/PT1-reopt-results.png', scale: 'css' });
    await page.evaluate(d => { window.__pt1 = d; }, JSON.stringify({ url: page.url(), rows }));
    const g = k => (rows[k] || [])[1] || '-';
    log.push(`PV=${g('PV Size')} BattP=${g('Battery Power')} BattE=${g('Battery Capacity')}`);
    log.push(`LCC=${g('Total Life Cycle Costs')} NPV=${g('Net Present Value')} ` +
             `Y1=${g('Total Year 1 Utility Cost - Before Tax')}`);
    log.push('rate used: ' + JSON.stringify((rows['Electricity rate'] || rows['Utility rate'] || [])[0] || '?'));
    log.push('rows ' + Object.keys(rows).length);
  }
  return log.join('\n');
}
