// Run every variability case from reopt_test_data/variability_cases.json in the
// REAL REopt tool and stash the harvested numbers in window.__vary.
// (The case list is inlined below because the VM sandbox cannot read files.)
async (page) => {
  const CASES = __CASES__;
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/variability';
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

  for (const c of CASES) {
    log.push('=== ' + c.id + ' ' + c.name + ' ===');
    await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
    await page.waitForTimeout(2200);

    if (c.off_grid) { try { await page.locator('#run_off_grid').check(); await page.waitForTimeout(2000); } catch (e) {} }

    const techIds = { PV: 'run_analyze_pv', Battery: 'run_analyze_battery',
                      Generator: 'run_analyze_generator', CHP: 'run_analyze_chp' };
    for (const t of c.techs) {
      try { await page.locator('#' + techIds[t]).check({ timeout: 5000 }); }
      catch (e) { log.push('    FAIL tech ' + t); }
    }
    await page.waitForTimeout(2000);
    await set('run_site_attributes_description', c.id + ' ' + c.name.slice(0, 30));

    // location via lat/lon checkbox is not exposed; use the address autocomplete
    let ratesOk = c.off_grid;
    for (let a = 1; a <= 4 && !ratesOk; a++) {
      const addr = page.locator('#run_site_attributes_address');
      await addr.click(); await addr.fill('');
      await addr.type(c.address, { delay: 40 });
      await page.waitForTimeout(2300);
      const pac = page.locator('.pac-container .pac-item');
      if (await pac.count()) await pac.first().click();
      else { await addr.press('ArrowDown'); await addr.press('Enter'); }
      await page.waitForTimeout(4800);
      ratesOk = !(await page.locator('#dropdown-input').isDisabled());
    }
    log.push('  rates ready=' + ratesOk);

    // space available
    if (c.space === 'roof') { try { await page.locator('#run_site_attributes_pv_wind_space_available_roofspace').check(); await page.waitForTimeout(900); } catch (e) {} }
    if (c.land_acres) await set('run_site_attributes_land_acres', c.land_acres);
    if (c.roof_sqft) await set('run_site_attributes_roof_squarefeet', c.roof_sqft);

    // rate: type part of the label then take the matching entry
    if (!c.off_grid) {
      const dd = page.locator('#dropdown-input');
      await dd.scrollIntoViewIfNeeded(); await dd.click(); await dd.fill('');
      await dd.type('Commercial', { delay: 40 });
      await page.waitForTimeout(2000);
      const n = await page.locator('.dropdown-item').count();
      if (n) { await page.locator('.dropdown-item').first().click(); await page.waitForTimeout(1600); }
      log.push('  rate=' + (await dd.inputValue()).slice(0, 58));
    }

    await pick('run_site_attributes_load_profile_attributes_doe_reference_name', c.building);
    await page.waitForTimeout(700);
    await set('run_site_attributes_load_profile_attributes_annual_kwh', c.annual_kwh);

    await expandAll();
    await set('run_site_attributes_financial_attributes_analysis_years', c.years);
    await set('run_site_attributes_financial_attributes_offtaker_discount_rate_fraction', c.discount);
    await set('run_site_attributes_financial_attributes_elec_cost_escalation_rate_fraction', c.elec_esc);
    if (c.compensation && c.compensation !== 'no_compensation') {
      await pick('run_site_attributes_electric_tariff_attributes_compensation_type', c.compensation);
      await page.waitForTimeout(600);
    }
    if (c.pv) {
      await set('run_site_attributes_pv_attributes_installed_cost_per_kw', c.pv.installed_cost_per_kw);
      await set('run_site_attributes_pv_attributes_min_kw', c.pv.min_kw);
      await set('run_site_attributes_pv_attributes_max_kw', c.pv.max_kw);
    }
    if (c.battery) {
      await set('run_site_attributes_storage_attributes_installed_cost_per_kwh', c.battery.installed_cost_per_kwh);
      await set('run_site_attributes_storage_attributes_installed_cost_per_kw', c.battery.installed_cost_per_kw);
      await set('run_site_attributes_storage_attributes_installed_cost_constant', c.battery.installed_cost_constant);
      await set('run_site_attributes_storage_attributes_max_kwh', c.battery.max_kwh);
    }
    await page.waitForTimeout(900);
    await page.screenshot({ path: SHOTS + '/' + c.id + '-reopt-form.png', scale: 'css' });

    await page.getByRole('button', { name: /Get Results/i }).first().click();
    try { await page.waitForURL(/\/tool\/results\//, { timeout: 60000 }); } catch (e) {}
    const url = page.url();
    log.push('  submitted ' + url.split('/').pop());

    let st = null;
    for (let i = 0; i < 40; i++) {
      await page.waitForTimeout(10000);
      try {
        st = await page.evaluate(() => {
          const b = document.body.innerText.replace(/\s+/g, ' ');
          return { running: /Optimizing your results/i.test(b), oops: /Oops!/i.test(b),
                   done: /(Results Comparison|Results Summary)/i.test(b) && !/Optimizing your results/i.test(b) };
        });
      } catch (e) { continue; }
      if (!st.running) break;
    }
    log.push('  ' + JSON.stringify(st));

    if (st && st.done) {
      await expandAll();
      await page.evaluate(() => document.querySelectorAll('.panel-collapse.collapse')
        .forEach(c => { c.classList.add('in'); c.style.display = 'block'; c.style.height = 'auto'; }));
      await page.waitForTimeout(2000);
      const dump = await page.evaluate(() => {
        const clean = s => (s || '').replace(/\s+/g, ' ').trim();
        const rows = {};
        document.querySelectorAll('.panel-collapse').forEach(p => {
          if (!p.id) return;
          p.querySelectorAll('table tr').forEach(tr => {
            const cs = Array.from(tr.querySelectorAll('th,td')).map(x => clean(x.innerText));
            if (cs.length > 1 && cs[0]) rows[cs[0]] = cs.slice(1);
          });
        });
        return rows;
      });
      out[c.id] = { url, rows: dump };
      await page.screenshot({ path: SHOTS + '/' + c.id + '-reopt-results.png', scale: 'css' });
      const pv = dump['PV Size'] || [];
      const bat = dump['Battery Capacity'] || [];
      log.push('  PV=' + (pv[1] || '-') + '  Batt=' + (bat[1] || '-')
               + '  LCC=' + ((dump['Total Life Cycle Costs'] || [])[1] || '-'));
    } else {
      out[c.id] = { url, rows: null, failed: true };
      await page.screenshot({ path: SHOTS + '/' + c.id + '-reopt-failed.png', scale: 'css' });
    }
  }

  await page.evaluate(d => { window.__vary = d; }, JSON.stringify(out));
  log.push('stashed window.__vary');
  return log.join('\n');
}
