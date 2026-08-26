// End-to-end: run the app to RESULTS and confirm the period views render.
// This is the check that was missing when the %-d strftime crash shipped.
// Two passes: the single-unit shape, then a 3-generator / 2-battery fleet.
async (page) => {
  const log = [];
  const openAll = async () => {
    for (let i = 0; i < 5; i++) {
      const n = await page.evaluate(() => {
        let c = 0;
        document.querySelectorAll('[data-testid="stExpander"] details').forEach(d => {
          if (!d.open) { const s = d.querySelector('summary'); if (s) { s.click(); c++; } }
        });
        return c;
      });
      await page.waitForTimeout(900);
      if (!n) break;
    }
  };
  const setNum = async (lab, val) => {
    const loc = page.locator(`input[type="number"][aria-label*="${lab}" i]`).first();
    if (!(await loc.count())) { log.push('    MISSING ' + lab); return false; }
    await loc.scrollIntoViewIfNeeded(); await loc.click();
    await loc.press('Control+a'); await loc.fill(String(val)); await loc.press('Enter');
    await page.waitForTimeout(1100);
    return true;
  };
  const setSel = async (labRe, optName) => {
    const box = page.locator('[data-testid="stSelectbox"]')
      .filter({ has: page.locator(`label:has-text("${labRe}")`) }).first();
    if (!(await box.count())) { log.push('    MISSING select ' + labRe); return; }
    const inp = box.locator('input').first();
    await inp.scrollIntoViewIfNeeded(); await inp.click();
    await page.waitForTimeout(450);
    await inp.type(optName, { delay: 45 });
    await page.waitForTimeout(650); await inp.press('Enter');
    await page.waitForTimeout(1500);
  };
  const pill = async (name) => {
    const b = page.getByRole('button', { name, exact: true }).first();
    if (!(await b.count())) { log.push('    MISSING pill ' + name); return false; }
    await b.scrollIntoViewIfNeeded(); await b.click(); await page.waitForTimeout(2000);
    return true;
  };

  for (const pass of [{ tag: 'single', gens: 1, bats: 1 },
                      { tag: 'fleet', gens: 3, bats: 2 }]) {
    log.push(`=== ${pass.tag}: ${pass.gens} gen / ${pass.bats} battery ===`);
    await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
    await page.waitForTimeout(9000);

    await pill('Prime Generator');
    await openAll();
    await setSel('Type of building', 'Supermarket');
    await openAll();
    await setNum('Annual energy consumption', 3000000);
    await setNum('Land available', 6);
    await setNum('Analysis period', 20);
    await setNum('Maximum new PV size', 1000);

    if (pass.gens > 1) { await setNum('Number of fuel-fired units', pass.gens); await openAll(); }
    if (pass.bats > 1) { await setNum('Number of battery units', pass.bats); await openAll(); }

    const btn = page.getByRole('button', { name: /Get results/i }).first();
    if (await btn.isDisabled()) { log.push('  BUTTON DISABLED'); continue; }
    await page.evaluate(() => {
      document.querySelectorAll('.reopt-fig-num').forEach(e => { e.textContent = 'stale'; });
    });
    await btn.click();

    let st = null;
    for (let i = 0; i < 70; i++) {
      await page.waitForTimeout(10000);
      st = await page.evaluate(() => {
        const b = document.body.innerText;
        return {
          done: /Dispatch by period/i.test(b),
          failed: /Run failed|Traceback|ValueError|KeyError|TypeError/i.test(b),
          msg: (b.match(/(Run failed|ValueError|KeyError|TypeError)[^\n]{0,200}/) || [''])[0],
        };
      });
      if (st.done || st.failed) break;
    }
    log.push('  ' + JSON.stringify(st));
    if (!st || !st.done) {
      await page.screenshot({ path: `D:/GreenHouseV2/reopt_test_screenshots/fleet/${pass.tag}-FAILED.png`, scale: 'css' });
      continue;
    }

    // everything the period section is supposed to put on the page
    const seen = await page.evaluate(() => {
      const t = document.body.innerText;
      const grids = document.querySelectorAll('[data-testid="stDataFrame"]').length;
      return {
        heading: /Dispatch by period/i.test(t),
        repDay: /representative day is the one whose energy/i.test(t),
        hourly: /Hour by hour/i.test(t),
        dayPick: /Representative day/.test(t) && /Peak day/.test(t),
        monthly: /Monthly peak grid purchase/i.test(t),
        ratchetNote: /sum of the twelve monthly peaks/i.test(t),
        charts: document.querySelectorAll('[data-testid="stVegaLiteChart"], .vega-embed').length,
        tables: grids,
        figs: Array.from(document.querySelectorAll('.reopt-fig-num')).map(e => e.innerText),
      };
    });
    log.push('  rendered: ' + JSON.stringify(seen));

    // switch to the peak day -- exercises the other strftime path
    const peak = page.getByText('Peak day', { exact: true }).first();
    if (await peak.count()) {
      await peak.click();
      await page.waitForTimeout(6000);
      const after = await page.evaluate(() => ({
        failed: /Traceback|ValueError|KeyError/i.test(document.body.innerText),
        label: (document.body.innerText.match(/[A-Z][a-z]+day, \d+ [A-Z][a-z]+ — hours 1 to 24/) || [''])[0],
      }));
      log.push('  peak-day switch: ' + JSON.stringify(after));
    }
    await page.screenshot({ path: `D:/GreenHouseV2/reopt_test_screenshots/fleet/${pass.tag}-periods.png`, scale: 'css' });
  }
  return log.join('\n');
}
