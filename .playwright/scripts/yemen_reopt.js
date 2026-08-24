// Sana'a factory (Yemen) run through the REopt web tool, off-grid.
//   Y1  vendor design forced to the deck's sizes, operating reserve 0
//   Y2  optimizer free to size,                   operating reserve 0
//   Y3  optimizer free to size,                   REopt's own reserve defaults
// Y1/Y2 use reserve 0 so they are directly comparable with our model, which
// does not implement operating reserve; Y3 measures what that omission costs.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/yemen';
  const log = [];
  const out = {};

  if (!page.__dlg) {
    page.__dlg = [];
    page.on('dialog', async d => { page.__dlg.push(d.message()); try { await d.accept(); } catch (e) {} });
  }
  const set = async (id, v) => {
    if (v === null || v === undefined) return;
    try {
      const l = page.locator('#' + id);
      await l.scrollIntoViewIfNeeded();
      await l.fill(String(v), { timeout: 8000 });
    } catch (e) { log.push('    FAIL set ' + id); }
  };
  const pick = async (id, v) => {
    try {
      const l = page.locator('#' + id);
      await l.scrollIntoViewIfNeeded();
      await l.selectOption(String(v), { timeout: 8000 });
    } catch (e) { log.push('    FAIL pick ' + id); }
  };
  const expandAll = async () => {
    for (let p = 0; p < 3; p++) {
      const closed = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
        .filter(c => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none').map(c => c.id));
      if (!closed.length) break;
      for (const id of closed) {
        try {
          const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
          await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 3500 }); await page.waitForTimeout(280);
        } catch (e) {}
      }
    }
  };

  // vendor's own prices, deck p.25-27
  const PV_COST = 398.0, BESS_KWH_COST = 195.82, DG_COST = 306.5;
  const DIESEL_GAL = 3.41;          // implied by the deck's $0.26/kWh at 32.2% HHV
  const CASES = [
    { id: 'Y1', desc: 'vendor design forced', res: 0,
      pv: [1500, 1500], bkwh: [3132, 3132], bkw: [1500, 1500], gen: [1000, 1000] },
    { id: 'Y2', desc: 'optimizer sizing', res: 0,
      pv: [0, 5000], bkwh: [0, 20000], bkw: [0, 10000], gen: [0, 2000] },
    { id: 'Y3', desc: 'optimizer sizing, REopt reserve defaults', res: null,
      pv: [0, 5000], bkwh: [0, 20000], bkw: [0, 10000], gen: [0, 2000] },
  ];

  for (const c of CASES) {
    log.push('=== ' + c.id + '  ' + c.desc + ' ===');
    await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 120000 });
    await page.waitForTimeout(3000);

    // Step 2: off-grid
    await page.evaluate(() => {
      const e = document.querySelector('#run_off_grid');
      if (e) { e.click(); e.dispatchEvent(new Event('change', { bubbles: true })); }
    });
    await page.waitForTimeout(4000);

    for (const id of ['run_analyze_pv', 'run_analyze_battery', 'run_analyze_generator']) {
      try { await page.locator('#' + id).check({ timeout: 6000 }); }
      catch (e) { log.push('    FAIL tech ' + id); }
    }
    await page.waitForTimeout(2500);
    await set('run_site_attributes_description', c.id + " Sana'a factory " + c.desc);

    // Site -- the tool geocodes "Sana'a, Yemen" to 15.3667 / 44.21122 (~17 km
    // from the deck's 15.2811 / 44.0811; immaterial for irradiance).
    // The autocomplete is unreliable -- picking its first suggestion once
    // resolved "Sana'a" to Morocco (34.02 N, -4.97 E). Verify the coordinates
    // actually land in Yemen and retry until they do.
    let site = null;
    for (let a = 0; a < 5; a++) {
      const addr = page.locator('#run_site_attributes_address');
      await addr.scrollIntoViewIfNeeded();
      await addr.click(); await addr.fill('');
      await addr.type("Sana'a, Yemen", { delay: 55 });
      await page.waitForTimeout(3500);
      if (a % 2 === 0) { await addr.press('Enter'); }
      else {
        const pac = page.locator('.pac-container .pac-item');
        if (await pac.count()) await pac.first().click(); else await addr.press('Enter');
      }
      await page.waitForTimeout(5000);
      site = await page.evaluate(() => ({
        lat: parseFloat((document.getElementById('run_site_attributes_latitude') || {}).value),
        lon: parseFloat((document.getElementById('run_site_attributes_longitude') || {}).value),
      }));
      if (site.lat > 12 && site.lat < 19 && site.lon > 42 && site.lon < 47) break;
      log.push('  geocode attempt ' + a + ' landed at ' + JSON.stringify(site) + ' -- retrying');
    }
    log.push('  site ' + JSON.stringify(site));
    if (!(site && site.lat > 12 && site.lat < 19)) {
      log.push('  ABORT: could not geocode to Yemen'); continue;
    }

    await set('run_site_attributes_land_acres', 50);   // deliberately non-binding
    await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'FlatLoad_8_7');
    await page.waitForTimeout(900);
    await set('run_site_attributes_load_profile_attributes_annual_kwh', 2555000);

    await expandAll();
    await set('run_site_attributes_load_profile_attributes_min_load_met_annual_fraction', 99.999);
    if (c.res !== null) {
      await set('run_site_attributes_load_profile_attributes_operating_reserve_required_fraction', c.res);
      await set('run_site_attributes_pv_attributes_operating_reserve_required_fraction', c.res);
    }

    // Financial -- Yemen: no US tax code, so no ITC, no MACRS, no tax shield
    await set('run_site_attributes_financial_attributes_analysis_years', 10);
    await set('run_site_attributes_financial_attributes_offtaker_discount_rate_fraction', 8.3);
    await set('run_site_attributes_financial_attributes_offtaker_tax_rate_fraction', 0);
    await set('run_site_attributes_financial_attributes_generator_fuel_cost_escalation_rate_fraction', 3.4);

    // PV
    await set('run_site_attributes_pv_attributes_installed_cost_per_kw', PV_COST);
    await set('run_site_attributes_pv_attributes_om_cost_per_kw', 20);
    await set('run_site_attributes_pv_attributes_min_kw', c.pv[0]);
    await set('run_site_attributes_pv_attributes_max_kw', c.pv[1]);
    await set('run_site_attributes_pv_attributes_tilt', 15);
    await set('run_site_attributes_pv_attributes_azimuth', 180);
    await set('run_site_attributes_pv_attributes_federal_itc_fraction', 0);
    await pick('run_site_attributes_pv_attributes_macrs_option_years', '0');
    await pick('run_site_attributes_pv_attributes_macrs_bonus_fraction', '0');

    // Battery -- the vendor's 125 kW / 261 kWh cabinet is an indivisible
    // 2.088 h block, so all of its price is per-kWh and the duration is locked.
    await set('run_site_attributes_storage_attributes_installed_cost_per_kwh', BESS_KWH_COST);
    await set('run_site_attributes_storage_attributes_installed_cost_per_kw', 0);
    await set('run_site_attributes_storage_attributes_installed_cost_constant', 0);
    await set('run_site_attributes_storage_attributes_min_kwh', c.bkwh[0]);
    await set('run_site_attributes_storage_attributes_max_kwh', c.bkwh[1]);
    await set('run_site_attributes_storage_attributes_min_kw', c.bkw[0]);
    await set('run_site_attributes_storage_attributes_max_kw', c.bkw[1]);
    // min only: energy >= 2.088 x power stops the optimizer buying power that
    // the vendor's cabinet price does not charge for. Pairing it with an equality
    // AND pinned min=max sizes over-constrained Y1 into an infeasible model,
    // which the tool surfaces as "Julia server is down".
    if (c.id !== 'Y1') {
      await set('run_site_attributes_storage_attributes_min_duration_hours', 2.088);
    }
    await set('run_site_attributes_storage_attributes_total_itc_fraction', 0);
    await pick('run_site_attributes_storage_attributes_macrs_option_years', '0');
    await pick('run_site_attributes_storage_attributes_macrs_bonus_fraction', '0');

    // Diesel generator
    await set('run_site_attributes_generator_attributes_installed_cost_per_kw', DG_COST);
    await set('run_site_attributes_generator_attributes_fuel_cost_per_gallon', DIESEL_GAL);
    await set('run_site_attributes_generator_attributes_fuel_available_gal', 10000000);
    await set('run_site_attributes_generator_attributes_om_cost_per_kw', 10);
    await set('run_site_attributes_generator_attributes_om_cost_per_kwh', 0);
    await set('run_site_attributes_generator_attributes_min_kw', c.gen[0]);
    await set('run_site_attributes_generator_attributes_max_kw', c.gen[1]);
    await set('run_site_attributes_generator_attributes_elec_effic_full_load', 32.2);

    await page.waitForTimeout(1200);
    await page.screenshot({ path: SHOTS + '/' + c.id + '-form.png', scale: 'css' });

    await page.getByRole('button', { name: /Get Results/i }).first().click();
    try { await page.waitForURL(/\/tool\/results\//, { timeout: 60000 }); } catch (e) {}
    const url = page.url();
    log.push('  submitted ' + url.split('/').pop());

    const errs = await page.evaluate(() => Array.from(document.querySelectorAll('.error,.alert-danger,[class*=error]'))
      .filter(x => x.getClientRects().length && x.innerText.trim())
      .slice(0, 4).map(x => x.innerText.replace(/\s+/g, ' ').trim().slice(0, 220)));
    if (errs.length) log.push('  VALIDATION: ' + JSON.stringify(errs));

    let st = null;
    for (let i = 0; i < 60; i++) {
      await page.waitForTimeout(10000);
      try {
        st = await page.evaluate(() => {
          const b = document.body.innerText.replace(/\s+/g, ' ');
          return { running: /Optimizing your results/i.test(b), oops: /Oops!/i.test(b),
                   done: /Results Comparison|Results for/i.test(b) && !/Optimizing your results/i.test(b) };
        });
      } catch (e) { continue; }
      if (!st.running) break;
    }
    log.push('  ' + JSON.stringify(st));

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
      out[c.id] = { url, rows };
      await page.screenshot({ path: SHOTS + '/' + c.id + '-results.png', scale: 'css' });
      const g = (k, i) => (rows[k] || [])[i === undefined ? 1 : i] || '-';
      log.push(`  PV=${g('PV Size')} Batt=${g('Battery Capacity')}/${g('Battery Power')} ` +
               `DG=${g('Generator Size')} LCC=${g('Total Life Cycle Costs')} ` +
               `fuel=${g('Generator Fuel Used')}`);
    } else {
      out[c.id] = { url, rows: null, failed: true };
      await page.screenshot({ path: SHOTS + '/' + c.id + '-failed.png', scale: 'css' });
    }
  }

  await page.evaluate(d => { window.__yemen = d; }, JSON.stringify(out));
  log.push('stashed window.__yemen');
  return log.join('\n');
}
