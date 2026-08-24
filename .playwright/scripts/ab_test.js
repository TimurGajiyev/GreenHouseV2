// A/B TEST: run the SAME scenario in the real REopt tool and in our calculator.
//
// Scenario: Golden CO (39.74437,-105.15199), Large Office 5,000,000 kWh,
//           Land only 5 acres, Intermountain REA B-TOU rate,
//           PV $1600/kW max 2000 kW, Battery $300/kWh $800/kW constant $0 max 4000 kWh,
//           25 yr, 8.3% discount, 1.7% electricity escalation. Cost savings only.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/abtest';
  const log = [];
  const ctx = page.context();

  // ============================ A: real REopt ============================
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(2000);
  if (!page.__dlg) { page.__dlg = []; page.on('dialog', async d => { page.__dlg.push(d.message()); try { await d.accept(); } catch (e) {} }); }

  const set = async (id, v) => { try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded(); await l.fill(String(v), { timeout: 8000 }); } catch (e) { log.push('  A FAIL set ' + id); } };
  const pick = async (id, v) => { try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded(); await l.selectOption(String(v), { timeout: 8000 }); } catch (e) { log.push('  A FAIL pick ' + id); } };

  for (const id of ['run_analyze_pv', 'run_analyze_battery']) {
    try { await page.locator('#' + id).check({ timeout: 5000 }); } catch (e) {}
  }
  await page.waitForTimeout(2000);
  await set('run_site_attributes_description', 'AB TEST PV+Battery');

  let ratesOk = false;
  for (let a = 1; a <= 4 && !ratesOk; a++) {
    const addr = page.locator('#run_site_attributes_address');
    await addr.click(); await addr.fill('');
    await addr.type('1617 Cole Blvd, Golden, CO 80401', { delay: 45 });
    await page.waitForTimeout(2300);
    const pac = page.locator('.pac-container .pac-item');
    if (await pac.count()) await pac.first().click(); else { await addr.press('ArrowDown'); await addr.press('Enter'); }
    await page.waitForTimeout(5000);
    ratesOk = !(await page.locator('#dropdown-input').isDisabled());
  }
  const dd = page.locator('#dropdown-input');
  await dd.scrollIntoViewIfNeeded(); await dd.click(); await dd.fill('');
  await dd.type('Commercial Demand Metered Time of Use', { delay: 40 });
  await page.waitForTimeout(2200);
  if (await page.locator('.dropdown-item').count()) { await page.locator('.dropdown-item').first().click(); await page.waitForTimeout(1800); }
  log.push('A rate: ' + (await dd.inputValue()).slice(0, 70));

  await set('run_site_attributes_land_acres', '5');
  await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'LargeOffice');
  await page.waitForTimeout(800);
  await set('run_site_attributes_load_profile_attributes_annual_kwh', '5000000');

  for (let p = 0; p < 2; p++) {
    const closed = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
      .filter(c => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none').map(c => c.id));
    if (!closed.length) break;
    for (const id of closed) {
      try { const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
        await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 4000 }); await page.waitForTimeout(400); } catch (e) {}
    }
  }
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
  await page.screenshot({ path: SHOTS + '/A-reopt-form.png', scale: 'css', fullPage: true });

  await page.getByRole('button', { name: /Get Results/i }).first().click();
  try { await page.waitForURL(/\/tool\/results\//, { timeout: 60000 }); } catch (e) {}
  log.push('A submitted: ' + page.url());

  // ======================= B: our calculator (in parallel) ================
  const p2 = await ctx.newPage();
  await p2.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
  await p2.waitForTimeout(7000);
  for (let i = 0; i < 3; i++) {
    const n = await p2.evaluate(() => { let c = 0;
      document.querySelectorAll('[data-testid="stExpander"] details').forEach(d => {
        if (!d.open) { const s = d.querySelector('summary'); if (s) { s.click(); c++; } } });
      return c; });
    await p2.waitForTimeout(1000);
    if (!n) break;
  }
  // set the numeric inputs by their aria-label
  const setNum = async (label, val) => {
    const ok = await p2.evaluate(([lab, v]) => {
      const inputs = Array.from(document.querySelectorAll('input[type="number"]'));
      const el = inputs.find(i => (i.getAttribute('aria-label') || '').toLowerCase().includes(lab.toLowerCase()));
      if (!el) return false;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, String(v));
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.blur();
      return true;
    }, [label, val]);
    if (!ok) log.push('  B FAIL set ' + label);
    await p2.waitForTimeout(900);
  };
  await setNum('Analysis period', 25);
  await setNum('Host discount rate', 8.3);
  await setNum('Electricity cost escalation', 1.7);
  await setNum('System capital cost', 1600);
  await setNum('Maximum new PV size', 2000);
  await setNum('Energy capacity cost', 300);
  await setNum('Power capacity cost', 800);
  await setNum('Constant cost', 0);
  await setNum('Maximum energy capacity', 4000);
  await p2.waitForTimeout(1500);
  await p2.screenshot({ path: SHOTS + '/B-ours-form.png', scale: 'css', fullPage: true });

  await p2.getByRole('button', { name: /Get results/i }).first().click();
  log.push('B submitted');

  // ---- wait for both ----
  let bDone = null;
  for (let i = 0; i < 30; i++) {
    await p2.waitForTimeout(10000);
    bDone = await p2.evaluate(() => {
      const b = document.body.innerText;
      return { done: /Results for your site/i.test(b), failed: /Run failed|Traceback/i.test(b),
               msg: (b.match(/Run failed[^\n]{0,200}/) || [''])[0] };
    });
    if (bDone.done || bDone.failed) break;
  }
  log.push('B final: ' + JSON.stringify(bDone));

  let aDone = null;
  for (let i = 0; i < 30; i++) {
    try {
      aDone = await page.evaluate(() => {
        const b = document.body.innerText.replace(/\s+/g, ' ');
        return { running: /Optimizing your results/i.test(b), oops: /Oops!/i.test(b),
                 done: /Results Comparison|life cycle savings/i.test(b) && !/Optimizing your results/i.test(b) };
      });
    } catch (e) { await page.waitForTimeout(8000); continue; }
    if (!aDone.running) break;
    await page.waitForTimeout(10000);
  }
  log.push('A final: ' + JSON.stringify(aDone));

  // ---- harvest numbers ----
  if (aDone && aDone.done) {
    for (let p = 0; p < 3; p++) {
      const closed = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
        .filter(c => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none').map(c => c.id));
      if (!closed.length) break;
      for (const id of closed) {
        try { const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
          await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 3500 }); await page.waitForTimeout(300); } catch (e) {}
      }
    }
    await page.waitForTimeout(2000);
    const A = await page.evaluate(() => {
      const t = document.body.innerText.replace(/[ \t]+/g, ' ');
      const grab = (re) => { const m = t.match(re); return m ? m[1] : null; };
      return {
        pv: grab(/PV Size\s*\|?\s*0 kW\s*([\d,]+) kW/) || grab(/([\d,]+) kW\s*\n?\s*PV size/i),
        batkw: grab(/Battery Power[^\n]*?0 kW\s*([\d,]+) kW/),
        batkwh: grab(/Battery Capacity[^\n]*?0 kWh\s*([\d,]+) kWh/),
        y1bau: grab(/Total Year 1 Utility Cost - Before Tax\s*\$([\d,]+)/),
        lcc: grab(/Total Life Cycle Costs\s*\$([\d,]+)/),
        savings: grab(/\$([\d,\-]+)\s*View citation/) };
    });
    log.push('A NUMBERS: ' + JSON.stringify(A));
    await page.screenshot({ path: SHOTS + '/A-reopt-results.png', scale: 'css', fullPage: true });
  } else {
    await page.screenshot({ path: SHOTS + '/A-reopt-failed.png', scale: 'css', fullPage: true });
  }

  if (bDone && bDone.done) {
    const B = await p2.evaluate(() =>
      Array.from(document.querySelectorAll('[data-testid="stMetric"]')).map(e => e.innerText.replace(/\n/g, '=')));
    log.push('B NUMBERS: ' + JSON.stringify(B));
    await p2.screenshot({ path: SHOTS + '/B-ours-results.png', scale: 'css', fullPage: true });
  }
  return log.join('\n');
}
