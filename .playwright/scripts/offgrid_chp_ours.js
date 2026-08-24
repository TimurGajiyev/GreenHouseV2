// Off-grid CHP through our UI: the tech must be offered, the boiler panel must
// NOT appear (scenario.jl:85 forbids heating keys off-grid), the operating
// reserve fields must appear, and the run must complete.
async (page) => {
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
  const pill = async (name) => {
    const b = page.getByRole('button', { name, exact: true }).first();
    if (!(await b.count())) { log.push('    MISSING pill ' + name); return false; }
    await b.scrollIntoViewIfNeeded(); await b.click(); await page.waitForTimeout(2500);
    return true;
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

  await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(8000);

  // Grid mode is an st.segmented_control -- its options are not role=button,
  // so click the label inside the button group directly.
  const ok = await page.evaluate(() => {
    const b = Array.from(document.querySelectorAll('[data-testid="stButtonGroup"] button, [data-testid="stButtonGroup"] label'))
      .find(e => e.innerText.trim() === 'Off-grid');
    if (b) { b.click(); return true; }
    return false;
  });
  log.push('off-grid clicked: ' + ok);
  await page.waitForTimeout(4000);

  log.push('offgrid techs offered: ' + JSON.stringify(await page.evaluate(() =>
    Array.from(document.querySelectorAll('[data-testid="stButtonGroup"] button'))
      .map(b => b.innerText.trim()))));

  await pill('CHP');
  await openAll();
  await setSel('Type of building', 'Office - Large');
  await openAll();

  const state = await page.evaluate(() => {
    const t = document.body.innerText;
    return {
      panels: Array.from(document.querySelectorAll('.reopt-panel-head')).map(e => e.innerText.trim()),
      boilerPanel: /Existing Heating System/.test(t),
      electricOnlyNote: /electric-only/i.test(t),
      loadReserve: /Load operating reserve requirement/.test(t),
      pvReserve: /PV operating reserve requirement/.test(t),
      thermalEff: /Thermal efficiency at 100/.test(t),
    };
  });
  log.push('state: ' + JSON.stringify(state));

  const btn = page.getByRole('button', { name: /Get results/i }).first();
  if (await btn.isDisabled()) { log.push('button disabled'); return log.join('\n'); }
  await btn.click();
  let st = null;
  for (let i = 0; i < 50; i++) {
    await page.waitForTimeout(10000);
    st = await page.evaluate(() => {
      const b = document.body.innerText;
      return { done: /Results for your site/i.test(b), failed: /Run failed|Traceback/i.test(b),
               msg: (b.match(/Run failed[^\n]{0,220}/) || [''])[0] };
    });
    if (st.done || st.failed) break;
  }
  log.push('run: ' + JSON.stringify(st));
  if (st && st.done) {
    log.push('results: ' + JSON.stringify(await page.evaluate(() => ({
      figs: Array.from(document.querySelectorAll('.reopt-fig-num')).map(e => e.innerText),
      cards: Array.from(document.querySelectorAll('.reopt-card-title')).map(e => e.innerText.trim()),
    }))));
    await page.screenshot({ path: 'D:/GreenHouseV2/reopt_test_screenshots/gen/ours-offgrid-CHP.png', scale: 'css' });
  }
  return log.join('\n');
}
