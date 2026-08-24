// Run the calculator, then scan EVERY results table for leaked internal
// variable names (snake_case) instead of REopt labels.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/theme';
  const log = [];
  await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(9000);

  const bad = await page.evaluate(() => {
    const b = document.body.innerText;
    return /Traceback|StreamlitAPIException|NameError|KeyError/.test(b)
      ? (b.match(/(Traceback|[A-Za-z]*Error)[^]{0,300}/) || [''])[0] : '';
  });
  if (bad) { log.push('!! ' + bad); return log.join('\n'); }

  // choose the building type then run
  const box = page.locator('[data-testid="stSelectbox"]')
    .filter({ has: page.locator('label:has-text("Type of building")') }).first();
  const inp = box.locator('input').first();
  await inp.scrollIntoViewIfNeeded(); await inp.click();
  await page.waitForTimeout(600);
  await inp.type('Office - Large', { delay: 55 });
  await page.waitForTimeout(700);
  await inp.press('Enter');
  await page.waitForTimeout(2200);

  await page.getByRole('button', { name: /Get results/i }).first().click();
  let st = null;
  for (let i = 0; i < 36; i++) {
    await page.waitForTimeout(10000);
    st = await page.evaluate(() => {
      const b = document.body.innerText;
      return { done: /Results for your site/i.test(b), failed: /Run failed|Traceback/i.test(b),
               msg: (b.match(/Run failed[^\n]{0,220}/) || [''])[0] };
    });
    if (st.done || st.failed) break;
  }
  log.push('run: ' + JSON.stringify(st));
  if (!st || !st.done) return log.join('\n');

  // open every drawer so all tables render
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
  await page.waitForTimeout(2500);

  // dataframes render to canvas, so read the underlying grid cells via aria
  const leaked = await page.evaluate(() => {
    const SNAKE = /^[a-z][a-z0-9]*(_[a-z0-9]+){1,}$/;   // installed_cost_per_kw etc.
    const hits = new Set();
    document.querySelectorAll('[role="gridcell"], [role="rowheader"], [data-testid="stDataFrame"] *')
      .forEach((e) => {
        const t = (e.textContent || '').trim();
        if (t && t.length < 60 && SNAKE.test(t)) hits.add(t);
      });
    // also plain text anywhere in the results area
    const body = document.body.innerText.split(/\s+/);
    body.forEach((w) => { if (SNAKE.test(w) && w.length < 46) hits.add(w); });
    return Array.from(hits).sort();
  });
  log.push('LEAKED snake_case tokens: ' + (leaked.length ? JSON.stringify(leaked, null, 1) : 'none'));

  await page.screenshot({ path: SHOTS + '/07-labels.png', scale: 'css', fullPage: true });
  return log.join('\n');
}
