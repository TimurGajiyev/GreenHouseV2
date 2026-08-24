// Drive CHP and Prime Generator through OUR UI (not just the engine) and
// confirm each produces results with the right panels present.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/gen';
  const log = [];

  const openAll = async () => {
    for (let i = 0; i < 4; i++) {
      const n = await page.evaluate(() => {
        let c = 0;
        document.querySelectorAll('[data-testid="stExpander"] details').forEach(d => {
          if (!d.open) { const s = d.querySelector('summary'); if (s) { s.click(); c++; } }
        });
        return c;
      });
      await page.waitForTimeout(1000);
      if (!n) break;
    }
  };
  const setSel = async (labRe, optName) => {
    const box = page.locator('[data-testid="stSelectbox"]')
      .filter({ has: page.locator(`label:has-text("${labRe}")`) }).first();
    if (!(await box.count())) { log.push('    MISSING select ' + labRe); return; }
    const inp = box.locator('input').first();
    await inp.scrollIntoViewIfNeeded(); await inp.click();
    await page.waitForTimeout(500);
    await inp.type(optName, { delay: 50 });
    await page.waitForTimeout(700); await inp.press('Enter');
    await page.waitForTimeout(1600);
  };
  const setNum = async (lab, val) => {
    const loc = page.locator(`input[type="number"][aria-label*="${lab}" i]`).first();
    if (!(await loc.count())) { log.push('    MISSING ' + lab); return false; }
    await loc.scrollIntoViewIfNeeded(); await loc.click();
    await loc.press('Control+a'); await loc.fill(String(val)); await loc.press('Enter');
    await page.waitForTimeout(1200);
    return true;
  };
  const pill = async (name) => {
    const b = page.getByRole('button', { name, exact: true }).first();
    if (!(await b.count())) { log.push('    MISSING pill ' + name); return false; }
    await b.scrollIntoViewIfNeeded(); await b.click(); await page.waitForTimeout(2000);
    return true;
  };

  for (const tech of ['CHP', 'Prime Generator']) {
    log.push('=== ' + tech + ' ===');
    try {
      await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
      await page.waitForTimeout(8000);
      await pill(tech);
      await openAll();
      await setSel('Type of building', 'Office - Large');
      await openAll();

      const panels = await page.evaluate(() =>
        Array.from(document.querySelectorAll('.reopt-panel-head')).map(e => e.innerText.trim()));
      log.push('  panels: ' + JSON.stringify(panels));

      // is the heating-system section present only for CHP?
      const heat = await page.evaluate(() => {
        const t = document.body.innerText;
        const m = t.match(/Heating load for [^\n]{0,120}/);
        return { hasPanel: /Existing Heating System/.test(t), note: m ? m[0] : null };
      });
      log.push('  heating: ' + JSON.stringify(heat));

      await setNum('Maximum new PV size', 2000);
      await setNum('System capital cost', 1600);
      await setNum('Energy capacity cost', 300);
      await setNum('Power capacity cost', 800);
      await setNum('Constant cost', 0);
      await setNum('Maximum energy capacity', 4000);
      await setNum('Host discount rate', 8.3);
      await setNum('Electricity cost escalation', 1.7);

      const btn = page.getByRole('button', { name: /Get results/i }).first();
      if (await btn.isDisabled()) { log.push('  button disabled'); continue; }
      await btn.click();
      let st = null;
      for (let i = 0; i < 40; i++) {
        await page.waitForTimeout(10000);
        st = await page.evaluate(() => {
          const b = document.body.innerText;
          return { done: /Results for your site/i.test(b), failed: /Run failed|Traceback/i.test(b),
                   msg: (b.match(/Run failed[^\n]{0,220}/) || [''])[0] };
        });
        if (st.done || st.failed) break;
      }
      log.push('  ' + JSON.stringify(st));
      if (st && st.done) {
        const d = await page.evaluate(() => ({
          figs: Array.from(document.querySelectorAll('.reopt-fig-num')).map(e => e.innerText),
          cards: Array.from(document.querySelectorAll('.reopt-card-title')).map(e => e.innerText.trim()),
          savings: (document.querySelector('.reopt-savings-value') || {}).innerText,
        }));
        log.push('  ' + JSON.stringify(d));
        await page.screenshot({ path: SHOTS + '/ours-' + tech.replace(/\s+/g, '-') + '.png', scale: 'css' });
      }
    } catch (e) { log.push('  EXCEPTION ' + String(e).slice(0, 130)); }
  }
  return log.join('\n');
}
