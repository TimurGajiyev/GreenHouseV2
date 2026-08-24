// G1: CHP + PV + Battery   |   G2: Prime Generator + PV + Battery
// Same site as test case 1 (Golden CO, Large Office 5,000,000 kWh) so the
// electric side is directly comparable with runs already validated.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/gen';
  const log = [];
  const out = {};

  if (!page.__dlg) {
    page.__dlg = [];
    page.on('dialog', async d => { page.__dlg.push(d.message()); try { await d.accept(); } catch (e) {} });
  }
  const set = async (id, v) => {
    if (v === null || v === undefined) return;
    try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded();
          await l.fill(String(v), { timeout: 8000 }); }
    catch (e) { log.push('    FAIL set ' + id); }
  };
  const pick = async (id, v) => {
    try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded();
          await l.selectOption(String(v), { timeout: 8000 }); }
    catch (e) { log.push('    FAIL pick ' + id); }
  };
  const expandAll = async () => {
    for (let p = 0; p < 3; p++) {
      const closed = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
        .filter(c => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none').map(c => c.id));
      if (!closed.length) break;
      for (const id of closed) {
        try { const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
          await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 3500 }); await page.waitForTimeout(280); } catch (e) {}
      }
    }
  };

  const CASES = [
    { id: 'G1', tech: 'run_analyze_chp', label: 'CHP' },
    { id: 'G2', tech: 'run_analyze_prime_generator', label: 'Prime Generator' },
  ];

  for (const c of CASES) {
    log.push('=== ' + c.id + '  ' + c.label + ' + PV + Battery ===');
    await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
    await page.waitForTimeout(2200);

    for (const id of [c.tech, 'run_analyze_pv', 'run_analyze_battery']) {
      try { await page.locator('#' + id).check({ timeout: 6000 }); }
      catch (e) { log.push('    FAIL tech ' + id); }
    }
    await page.waitForTimeout(2500);
    await set('run_site_attributes_description', c.id + ' ' + c.label);

    let ratesOk = false;
    for (let a = 1; a <= 4 && !ratesOk; a++) {
      const addr = page.locator('#run_site_attributes_address');
      await addr.click(); await addr.fill('');
      await addr.type('1617 Cole Blvd, Golden, CO 80401', { delay: 45 });
      await page.waitForTimeout(2300);
      const pac = page.locator('.pac-container .pac-item');
      if (await pac.count()) await pac.first().click();
      else { await addr.press('ArrowDown'); await addr.press('Enter'); }
      await page.waitForTimeout(5000);
      ratesOk = !(await page.locator('#dropdown-input').isDisabled());
    }
    const dd = page.locator('#dropdown-input');
    await dd.scrollIntoViewIfNeeded(); await dd.click(); await dd.fill('');
    await dd.type('Commercial Demand Metered Time of Use', { delay: 40 });
    await page.waitForTimeout(2200);
    if (await page.locator('.dropdown-item').count()) {
      await page.locator('.dropdown-item').first().click(); await page.waitForTimeout(1800);
    }
    log.push('  rate=' + (await dd.inputValue()).slice(0, 60));

    await set('run_site_attributes_land_acres', 5);
    await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'LargeOffice');
    await page.waitForTimeout(800);
    await set('run_site_attributes_load_profile_attributes_annual_kwh', 5000000);

    // fuel-tech specific required inputs
    if (c.id === 'G1') {
      await pick('run_site_attributes_load_profile_boiler_attributes_doe_reference_name', 'LargeOffice');
      await page.waitForTimeout(700);
      await set('run_site_attributes_load_profile_boiler_attributes_annual_mmbtu', 15000);
      await set('run_site_attributes_boiler_attributes_fuel_blended_annual_rates_per_mmbtu', 8.0);
      await set('run_site_attributes_chp_attributes_fuel_blended_annual_rates_per_mmbtu', 8.0);
    } else {
      await set('run_site_attributes_prime_generator_attributes_fuel_blended_annual_rates_per_mmbtu', 8.0);
    }

    await expandAll();
    await set('run_site_attributes_financial_attributes_analysis_years', 25);
    await set('run_site_attributes_financial_attributes_offtaker_discount_rate_fraction', 8.3);
    await set('run_site_attributes_financial_attributes_elec_cost_escalation_rate_fraction', 1.7);
    await set('run_site_attributes_pv_attributes_installed_cost_per_kw', 1600);
    await set('run_site_attributes_pv_attributes_min_kw', 0);
    await set('run_site_attributes_pv_attributes_max_kw', 2000);
    await set('run_site_attributes_storage_attributes_installed_cost_per_kwh', 300);
    await set('run_site_attributes_storage_attributes_installed_cost_per_kw', 800);
    await set('run_site_attributes_storage_attributes_installed_cost_constant', 0);
    await set('run_site_attributes_storage_attributes_max_kwh', 4000);
    await page.waitForTimeout(900);
    await page.screenshot({ path: SHOTS + '/' + c.id + '-form.png', scale: 'css' });

    await page.getByRole('button', { name: /Get Results/i }).first().click();
    try { await page.waitForURL(/\/tool\/results\//, { timeout: 60000 }); } catch (e) {}
    const url = page.url();
    log.push('  submitted ' + url.split('/').pop());

    const errs = await page.evaluate(() => Array.from(document.querySelectorAll('.error,.alert-danger,[class*=error]'))
      .filter(x => x.getClientRects().length && x.innerText.trim())
      .slice(0, 3).map(x => x.innerText.replace(/\s+/g, ' ').trim().slice(0, 200)));
    if (errs.length) log.push('  VALIDATION: ' + JSON.stringify(errs));

    let st = null;
    for (let i = 0; i < 45; i++) {
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
    log.push('  ' + JSON.stringify(st));

    if (st && st.done) {
      await expandAll();
      await page.evaluate(() => document.querySelectorAll('.panel-collapse.collapse')
        .forEach(x => { x.classList.add('in'); x.style.display = 'block'; x.style.height = 'auto'; }));
      await page.waitForTimeout(2200);
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
      out[c.id] = { url, rows };
      await page.screenshot({ path: SHOTS + '/' + c.id + '-results.png', scale: 'css' });
      const g = k => (rows[k] || [])[1] || '-';
      log.push(`  PV=${g('PV Size')}  Batt=${g('Battery Capacity')}  ` +
               `${c.label}=${g('CHP Size') !== '-' ? g('CHP Size') : g('Prime Generator Size')}  ` +
               `LCC=${g('Total Life Cycle Costs')}  NPV=${g('Net Present Value')}`);
    } else {
      out[c.id] = { url, rows: null, failed: true };
      await page.screenshot({ path: SHOTS + '/' + c.id + '-failed.png', scale: 'css' });
    }
  }

  await page.evaluate(d => { window.__gen = d; }, JSON.stringify(out));
  log.push('stashed window.__gen');
  return log.join('\n');
}
