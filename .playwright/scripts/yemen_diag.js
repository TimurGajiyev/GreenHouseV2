// Is "Julia server is down" a global outage or specific to the Yemen inputs?
// P1: identical off-grid scenario at a US address (Golden CO)
// P2: same, but at Sana'a, Yemen
// Everything else identical, so the only variable is the site.
async (page) => {
  const log = [];
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
          await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 3000 }); await page.waitForTimeout(250); } catch (e) {}
      }
    }
  };

  for (const p of [{ id: 'P1', addr: '1617 Cole Blvd, Golden, CO 80401' },
                   { id: 'P2', addr: "Sana'a, Yemen" }]) {
    log.push('=== ' + p.id + '  ' + p.addr + ' ===');
    await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 120000 });
    await page.waitForTimeout(3000);
    await page.evaluate(() => {
      const e = document.querySelector('#run_off_grid');
      if (e) { e.click(); e.dispatchEvent(new Event('change', { bubbles: true })); }
    });
    await page.waitForTimeout(4000);
    for (const id of ['run_analyze_pv', 'run_analyze_battery', 'run_analyze_generator']) {
      try { await page.locator('#' + id).check({ timeout: 6000 }); } catch (e) {}
    }
    await page.waitForTimeout(2000);
    await set('run_site_attributes_description', p.id + ' offgrid probe');

    const addr = page.locator('#run_site_attributes_address');
    await addr.scrollIntoViewIfNeeded(); await addr.click(); await addr.fill('');
    await addr.type(p.addr, { delay: 45 });
    await page.waitForTimeout(3000);
    const pac = page.locator('.pac-container .pac-item');
    if (await pac.count()) await pac.first().click();
    else { await addr.press('ArrowDown'); await addr.press('Enter'); }
    await page.waitForTimeout(5000);
    log.push('  site ' + JSON.stringify(await page.evaluate(() => ({
      lat: (document.getElementById('run_site_attributes_latitude') || {}).value,
      lon: (document.getElementById('run_site_attributes_longitude') || {}).value }))));

    await set('run_site_attributes_land_acres', 50);
    await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'FlatLoad_8_7');
    await page.waitForTimeout(800);
    await set('run_site_attributes_load_profile_attributes_annual_kwh', 2555000);
    await expandAll();
    await set('run_site_attributes_financial_attributes_analysis_years', 10);
    // everything else left at the tool's own defaults

    await page.getByRole('button', { name: /Get Results/i }).first().click({ timeout: 30000 });
    try { await page.waitForURL(/\/tool\//, { timeout: 60000 }); } catch (e) {}

    let st = null;
    for (let i = 0; i < 40; i++) {
      await page.waitForTimeout(10000);
      try {
        st = await page.evaluate(() => {
          const t = document.body.innerText.replace(/\s+/g, ' ');
          return { url: location.href.slice(0, 90),
                   running: /Optimizing your results/i.test(t),
                   oops: /Oops/i.test(t),
                   msg: (t.match(/(Julia server is down|[^.]{0,90}(cannot be null|must be|invalid|not supported)[^.]{0,90})/i) || [''])[0].slice(0, 180),
                   done: /Results Comparison|System Sizes/i.test(t) };
        });
      } catch (e) { continue; }
      if (!st.running) break;
    }
    log.push('  ' + JSON.stringify(st));
  }
  return log.join('\n');
}
