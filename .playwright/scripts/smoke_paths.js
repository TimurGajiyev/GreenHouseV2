// Smoke-test the UI end to end on several option paths, checking that each one
// actually produces results (this is where the stale-module TypeError showed up).
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/smoke';
  const log = [];

  const openAll = async () => {
    for (let i = 0; i < 4; i++) {
      const n = await page.evaluate(() => {
        let c = 0;
        document.querySelectorAll('[data-testid="stExpander"] details').forEach((d) => {
          if (!d.open) { const s = d.querySelector('summary'); if (s) { s.click(); c++; } }
        });
        return c;
      });
      await page.waitForTimeout(1000);
      if (!n) break;
    }
  };
  const setNum = async (lab, val) => {
    const loc = page.locator(`input[type="number"][aria-label*="${lab}" i]`).first();
    if (!(await loc.count())) { log.push('    MISSING ' + lab); return false; }
    await loc.scrollIntoViewIfNeeded(); await loc.click();
    await loc.press('Control+a'); await loc.fill(String(val)); await loc.press('Enter');
    await page.waitForTimeout(1200);
    return true;
  };
  const setSel = async (labRe, optName) => {
    const box = page.locator('[data-testid="stSelectbox"]')
      .filter({ has: page.locator(`label:has-text("${labRe}")`) }).first();
    if (!(await box.count())) { log.push('    MISSING select ' + labRe); return false; }
    const inp = box.locator('input').first();
    await inp.scrollIntoViewIfNeeded(); await inp.click();
    await page.waitForTimeout(500);
    await inp.type(optName, { delay: 50 });
    await page.waitForTimeout(700);
    await inp.press('Enter');
    await page.waitForTimeout(1500);
    const got = await box.locator('input').first().inputValue().catch(() => '');
    if (got !== optName) log.push(`    ${labRe} -> ${JSON.stringify(got)} (wanted ${optName})`);
    return got === optName;
  };
  const pill = async (name) => {
    const b = page.getByRole('button', { name, exact: true }).first();
    if (await b.count()) { await b.scrollIntoViewIfNeeded(); await b.click(); await page.waitForTimeout(1500); return true; }
    log.push('    MISSING pill ' + name); return false;
  };

  const run = async (tag, setup) => {
    log.push('=== ' + tag + ' ===');
    try {
    await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
    await page.waitForTimeout(8000);
    await openAll();
    await setup();
    await openAll();
    await page.waitForTimeout(800);

    const btn = page.getByRole('button', { name: /Get results/i }).first();
    if (await btn.isDisabled()) { log.push('  button disabled — required field missing'); return; }
    await btn.click();
    let st = null;
    for (let i = 0; i < 40; i++) {
      await page.waitForTimeout(10000);
      st = await page.evaluate(() => {
        const b = document.body.innerText;
        return { done: /Results for your site/i.test(b),
                 failed: /Run failed|Traceback/i.test(b),
                 warn: /Ignoring .*older than this page/i.test(b),
                 msg: (b.match(/Run failed[^\n]{0,220}/) || [''])[0] };
      });
      if (st.done || st.failed) break;
    }
    log.push('  ' + JSON.stringify(st));
    if (st && st.done) {
      const m = await page.evaluate(() =>
        Array.from(document.querySelectorAll('[data-testid="stMetric"]'))
          .slice(0, 4).map(e => e.innerText.replace(/\n/g, '=')));
      log.push('  ' + JSON.stringify(m));
      await page.screenshot({ path: SHOTS + '/' + tag + '.png', scale: 'css' });
    } else {
      await page.screenshot({ path: SHOTS + '/' + tag + '-FAIL.png', scale: 'css' });
    }
    } catch (e) { log.push('  EXCEPTION ' + String(e).slice(0, 120)); }
  };

  // A: plain grid-tied PV+Battery, defaults
  await run('A-default', async () => {
    await setSel('Type of building', 'Office - Large');
  });

  // B: net metering (this is the path that crashed)
  await run('B-net-metering', async () => {
    await setSel('Type of building', 'Office - Large');
    await setSel('Compensation type', 'Net metering (full retail rate)');
    await page.waitForTimeout(1200);
    await openAll();
    await setNum('Net metering system size limit', 800);
  });

  // C: roofspace only
  await run('C-roofspace', async () => {
    await setSel('Type of building', 'Office - Large');
    // Streamlit radios: click the visible label, the input itself is intercepted
    const roof = page.locator('[data-testid="stRadioGroup"] label')
      .filter({ hasText: 'Roofspace only' }).first();
    if (await roof.count()) { await roof.scrollIntoViewIfNeeded(); await roof.click({ force: true }); await page.waitForTimeout(1800); }
    else { log.push('    MISSING radio Roofspace only'); }
    await openAll();
    await setNum('Roofspace available', 5000);   // 5,000 ft2 x 0.01 = 50 kW cap
  });

  // D: off-grid with generator
  await run('D-offgrid', async () => {
    const og = page.getByText('Off-grid', { exact: true }).first();
    await og.click(); await page.waitForTimeout(2500);
    await pill('Generator');
    await openAll();
    await setSel('Type of building', 'Office - Large');
  });

  // E: custom flat rate
  await run('E-custom-rate', async () => {
    await setSel('Type of building', 'Office - Large');
    const cb = page.locator('label').filter({ hasText: 'Use custom electricity rate' }).first();
    if (await cb.count()) { await cb.scrollIntoViewIfNeeded(); await cb.click({ force: true }); await page.waitForTimeout(2000); }
    else { log.push('    MISSING custom-rate checkbox'); }
    await openAll();
    await setNum('Energy rate', 0.14);
    await setNum('Monthly demand rate', 12);
  });

  return log.join('\n');
}
