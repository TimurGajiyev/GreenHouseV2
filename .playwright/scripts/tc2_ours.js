// TEST CASE 2 in our calculator — same scenario as the REopt run 18d2e5c0.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/testcase2';
  const log = [];
  await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(8000);

  const openAll = async () => {
    for (let i = 0; i < 4; i++) {
      const n = await page.evaluate(() => {
        let c = 0;
        document.querySelectorAll('[data-testid="stExpander"] details').forEach((d) => {
          if (!d.open) { const s = d.querySelector('summary'); if (s) { s.click(); c++; } }
        });
        return c;
      });
      await page.waitForTimeout(1100);
      if (!n) break;
    }
  };
  await openAll();
  await page.waitForTimeout(1200);

  const setNum = async (lab, val) => {
    const loc = page.locator(`input[type="number"][aria-label*="${lab}" i]`).first();
    if (!(await loc.count())) { log.push('  MISSING ' + lab); return false; }
    await loc.scrollIntoViewIfNeeded();
    await loc.click(); await loc.press('Control+a');
    await loc.fill(String(val)); await loc.press('Enter');
    await page.waitForTimeout(1300);
    const got = await page.locator(`input[type="number"][aria-label*="${lab}" i]`).first().inputValue();
    const ok = Math.abs(parseFloat(got) - parseFloat(val)) < 1e-6;
    log.push(`  ${ok ? 'OK  ' : 'BAD '} ${lab} -> ${got}`);
    return ok;
  };
  const setSel = async (labRe, optName) => {
    const box = page.locator('[data-testid="stSelectbox"]')
      .filter({ has: page.locator(`label:has-text("${labRe}")`) }).first();
    const inp = box.locator('input').first();
    await inp.scrollIntoViewIfNeeded(); await inp.click();
    await page.waitForTimeout(500);
    await inp.type(optName, { delay: 55 });
    await page.waitForTimeout(800);
    await inp.press('Enter');
    await page.waitForTimeout(1600);
    const got = await box.locator('input').first().inputValue().catch(() => '');
    log.push(`  ${got === optName ? 'OK  ' : 'BAD '} ${labRe} -> ${JSON.stringify(got)}`);
  };

  // coordinates
  await setNum('Latitude', 33.4869);
  await setNum('Longitude', -112.0738);
  // rate label
  const rate = page.locator('input[type="text"][aria-label*="URDB" i]').first();
  if (await rate.count()) {
    await rate.scrollIntoViewIfNeeded(); await rate.click();
    await rate.press('Control+a'); await rate.fill('539fc194ec4f024c27d8a859');
    await rate.press('Enter'); await page.waitForTimeout(1500);
    log.push('  rate label set');
  } else { log.push('  MISSING rate input'); }

  await setSel('Type of building', 'Supermarket');
  await openAll();
  await setNum('Annual energy consumption', 3000000);
  await setNum('Land available', 2);
  await setNum('Analysis period', 20);
  await setNum('Host discount rate', 7.5);
  await setNum('Electricity cost escalation', 2.2);
  await setNum('System capital cost', 2000);
  await setNum('Maximum new PV size', 1000);
  await setNum('Energy capacity cost', 350);
  await setNum('Power capacity cost', 900);
  await setNum('Constant cost', 0);
  await setNum('Maximum energy capacity', 2000);
  await page.waitForTimeout(1200);
  await page.screenshot({ path: SHOTS + '/B-ours-form.png', scale: 'css', fullPage: true });

  await page.getByRole('button', { name: /Get results/i }).first().click();
  log.push('submitted');

  let st = null;
  for (let i = 0; i < 40; i++) {
    await page.waitForTimeout(10000);
    st = await page.evaluate(() => {
      const b = document.body.innerText;
      return { done: /Results for your site/i.test(b), failed: /Run failed|Traceback/i.test(b),
               msg: (b.match(/Run failed[^\n]{0,240}/) || [''])[0] };
    });
    if (st.done || st.failed) break;
  }
  log.push('final: ' + JSON.stringify(st));

  if (st && st.done) {
    await openAll();
    await page.waitForTimeout(2500);
    const M = await page.evaluate(() =>
      Array.from(document.querySelectorAll('[data-testid="stMetric"]')).map((e) => e.innerText.replace(/\n/g, ' = ')));
    log.push('METRICS:'); M.forEach((m) => log.push('   ' + m));
    const caps = await page.evaluate(() =>
      Array.from(document.querySelectorAll('[data-testid="stCaptionContainer"]'))
        .map((e) => e.innerText.trim()).filter((t) => /Cambium|AVERT|reference building/i.test(t)));
    log.push('CONTEXT:'); caps.forEach((c) => log.push('   ' + c.slice(0, 160)));
    const secs = await page.evaluate(() =>
      Array.from(document.querySelectorAll('[data-testid="stExpander"] summary')).map((s) => s.innerText.trim()));
    log.push('SECTIONS: ' + JSON.stringify(secs));
    await page.screenshot({ path: SHOTS + '/B-ours-results.png', scale: 'css', fullPage: true });
  } else {
    await page.screenshot({ path: SHOTS + '/B-ours-failed.png', scale: 'css', fullPage: true });
  }
  return log.join('\n');
}
