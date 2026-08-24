// B side of the A/B test, driven with REAL Playwright input (fill + Enter),
// verifying every field actually took the value before running.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/abtest';
  const log = [];

  await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(8000);

  // open all expanders
  for (let i = 0; i < 4; i++) {
    const n = await page.evaluate(() => {
      let c = 0;
      document.querySelectorAll('[data-testid="stExpander"] details').forEach((d) => {
        if (!d.open) { const s = d.querySelector('summary'); if (s) { s.click(); c++; } }
      });
      return c;
    });
    await page.waitForTimeout(1200);
    if (!n) break;
  }
  await page.waitForTimeout(1500);

  const setField = async (labelPart, value) => {
    const loc = page.locator(`input[type="number"][aria-label*="${labelPart}" i]`).first();
    if (!(await loc.count())) { log.push(`  MISSING  ${labelPart}`); return false; }
    await loc.scrollIntoViewIfNeeded();
    await loc.click();
    await loc.press('Control+a');
    await loc.fill(String(value));
    await loc.press('Enter');
    await page.waitForTimeout(1400);
    const got = await page.locator(`input[type="number"][aria-label*="${labelPart}" i]`).first().inputValue();
    const ok = Math.abs(parseFloat(got) - parseFloat(value)) < 1e-6;
    log.push(`  ${ok ? 'OK  ' : 'BAD '} ${labelPart} -> ${got} (wanted ${value})`);
    return ok;
  };

  // pick the building type: click the combobox, type to filter, Enter
  {
    const box = page.locator('[data-testid="stSelectbox"]')
      .filter({ has: page.locator('label:has-text("Type of building")') }).first();
    const inp = box.locator('input').first();
    await inp.scrollIntoViewIfNeeded();
    await inp.click();
    await page.waitForTimeout(600);
    await inp.type('Office - Large', { delay: 60 });
    await page.waitForTimeout(900);
    await inp.press('Enter');
    await page.waitForTimeout(2000);
    const got = await box.locator('input').first().inputValue().catch(() => '');
    log.push('  building -> ' + JSON.stringify(got));
  }

  log.push('setting inputs:');
  const targets = [
    ['Analysis period', 25],
    ['Host discount rate', 8.3],
    ['Electricity cost escalation', 1.7],
    ['System capital cost', 1600],
    ['Maximum new PV size', 2000],
    ['Energy capacity cost', 300],
    ['Power capacity cost', 800],
    ['Constant cost', 0],
    ['Maximum energy capacity', 4000],
  ];
  let allOk = true;
  for (const [lab, val] of targets) { if (!(await setField(lab, val))) allOk = false; }
  log.push('all inputs verified: ' + allOk);

  await page.screenshot({ path: SHOTS + '/B-ours-form.png', scale: 'css', fullPage: true });

  await page.getByRole('button', { name: /Get results/i }).first().click();
  log.push('clicked Get results');

  let st = null;
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(10000);
    st = await page.evaluate(() => {
      const b = document.body.innerText;
      return { done: /Results for your site/i.test(b), failed: /Run failed|Traceback/i.test(b),
               msg: (b.match(/Run failed[^\n]{0,220}/) || [''])[0] };
    });
    if (st.done || st.failed) break;
  }
  log.push('final: ' + JSON.stringify(st));

  if (st && st.done) {
    for (let i = 0; i < 3; i++) {
      const n = await page.evaluate(() => {
        let c = 0;
        document.querySelectorAll('[data-testid="stExpander"] details').forEach((d) => {
          if (!d.open) { const s = d.querySelector('summary'); if (s) { s.click(); c++; } }
        });
        return c;
      });
      await page.waitForTimeout(1200);
      if (!n) break;
    }
    await page.waitForTimeout(2000);
    const M = await page.evaluate(() =>
      Array.from(document.querySelectorAll('[data-testid="stMetric"]')).map((e) => e.innerText.replace(/\n/g, ' = ')));
    log.push('METRICS:');
    M.forEach((m) => log.push('   ' + m));
    // pull the comparison table too
    const tbl = await page.evaluate(() => {
      const t = Array.from(document.querySelectorAll('[data-testid="stDataFrame"]'))
        .map((d) => d.innerText.replace(/\n/g, ' | '));
      return t;
    });
    log.push('TABLES:');
    tbl.forEach((t) => log.push('   ' + t.slice(0, 400)));
    await page.screenshot({ path: SHOTS + '/B-ours-results.png', scale: 'css', fullPage: true });
  }
  return log.join('\n');
}
