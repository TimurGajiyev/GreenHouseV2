// Diagnose the two smoke paths that misbehaved:
//   E: "Use custom electricity rate" did not reveal its fields
//   D: off-grid produced no metric tiles
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
      await page.waitForTimeout(900);
      if (!n) break;
    }
  };

  // ---------- E ----------
  await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(8000);
  await openAll();

  const before = await page.evaluate(() => {
    const cbs = Array.from(document.querySelectorAll('input[type=checkbox]')).map(c => ({
      label: (c.getAttribute('aria-label') || '').slice(0, 46), checked: c.checked }));
    return { checkboxes: cbs,
             numInputs: Array.from(document.querySelectorAll('input[type=number]'))
               .map(i => (i.getAttribute('aria-label') || '').slice(0, 40)) };
  });
  log.push('E before: ' + JSON.stringify(before, null, 1).slice(0, 900));

  const cb = page.locator('label').filter({ hasText: 'Use custom electricity rate' }).first();
  log.push('E label found: ' + (await cb.count()));
  if (await cb.count()) { await cb.scrollIntoViewIfNeeded(); await cb.click({ force: true }); await page.waitForTimeout(2500); }
  await openAll();
  const after = await page.evaluate(() => {
    const cb = Array.from(document.querySelectorAll('input[type=checkbox]'))
      .find(c => /custom electricity rate/i.test(c.getAttribute('aria-label') || ''));
    return { checked: cb ? cb.checked : null,
             numInputs: Array.from(document.querySelectorAll('input[type=number]'))
               .map(i => (i.getAttribute('aria-label') || '').slice(0, 40)) };
  });
  log.push('E after: ' + JSON.stringify(after, null, 1).slice(0, 900));

  // ---------- D ----------
  await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(8000);
  const og = page.getByText('Off-grid', { exact: true }).first();
  await og.click(); await page.waitForTimeout(2500);
  const gen = page.getByRole('button', { name: 'Generator', exact: true }).first();
  if (await gen.count()) { await gen.click(); await page.waitForTimeout(1800); }
  await openAll();
  const box = page.locator('[data-testid="stSelectbox"]')
    .filter({ has: page.locator('label:has-text("Type of building")') }).first();
  const inp = box.locator('input').first();
  await inp.click(); await page.waitForTimeout(500);
  await inp.type('Office - Large', { delay: 50 });
  await page.waitForTimeout(700); await inp.press('Enter');
  await page.waitForTimeout(1800);

  await page.getByRole('button', { name: /Get results/i }).first().click();
  let st = null;
  for (let i = 0; i < 36; i++) {
    await page.waitForTimeout(10000);
    st = await page.evaluate(() => {
      const b = document.body.innerText;
      return { done: /Results for your site/i.test(b), failed: /Run failed|Traceback/i.test(b),
               msg: (b.match(/Run failed[^\n]{0,200}/) || [''])[0] };
    });
    if (st.done || st.failed) break;
  }
  log.push('D run: ' + JSON.stringify(st));
  if (st && st.done) {
    const d = await page.evaluate(() => ({
      metrics: Array.from(document.querySelectorAll('[data-testid="stMetric"]')).map(e => e.innerText.replace(/\n/g, '=')),
      savingsCards: document.querySelectorAll('.reopt-savings').length,
      savingsText: (document.querySelector('.reopt-savings') || {}).innerText,
      statCards: document.querySelectorAll('.reopt-card').length,
    }));
    log.push('D result: ' + JSON.stringify(d, null, 1).slice(0, 700));
  }
  return log.join('\n');
}
