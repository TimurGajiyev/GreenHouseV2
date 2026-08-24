// Verify the calculator across BOTH grid modes, with screenshots of every stage.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/calculator';
  const log = [];
  const shot = async (n, full) => {
    await page.screenshot({ path: SHOTS + '/' + n + '.png', scale: 'css', fullPage: !!full });
    log.push('  shot ' + n);
  };

  const runOnce = async (tag, offGrid) => {
    log.push('=== ' + tag + ' ===');
    await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
    await page.waitForTimeout(6000);

    if (offGrid) {
      const og = page.getByText('Off-grid', { exact: true }).first();
      await og.click();
      await page.waitForTimeout(3000);
      log.push('  selected Off-grid');
      // off-grid needs a generator to serve load
      const gen = page.getByText('Generator', { exact: true }).first();
      if (await gen.count()) { await gen.click(); await page.waitForTimeout(2000); log.push('  added Generator'); }
    }
    await shot(tag + '-01-form', true);

    const techs = await page.evaluate(() => {
      const t = Array.from(document.querySelectorAll('button')).map((b) => b.innerText.trim());
      return t.filter((x) => ['PV', 'Battery', 'CHP', 'Generator', 'Prime Generator'].includes(x));
    });
    log.push('  tech buttons offered: ' + JSON.stringify(techs));

    const btn = page.getByRole('button', { name: /Get results/i }).first();
    await btn.scrollIntoViewIfNeeded();
    await btn.click();
    log.push('  clicked Get results');

    let st = null;
    for (let i = 0; i < 30; i++) {
      await page.waitForTimeout(10000);
      st = await page.evaluate(() => {
        const b = document.body.innerText;
        return { running: /Solving|PVWatts|Fetching|Building load/i.test(b),
                 failed: /Run failed|Traceback/i.test(b),
                 done: /Results for your site/i.test(b),
                 msg: (b.match(/Run failed[^\n]{0,260}/) || [''])[0] };
      });
      if (st.done || st.failed) break;
    }
    log.push('  final: ' + JSON.stringify(st));

    if (st && st.done) {
      // expand every results drawer
      for (let p = 0; p < 3; p++) {
        const n = await page.evaluate(() => {
          let c = 0;
          document.querySelectorAll('[data-testid="stExpander"] summary, [data-testid="stExpander"] details:not([open]) summary').forEach((s) => {
            const d = s.closest('details');
            if (d && !d.open) { s.click(); c++; }
          });
          return c;
        });
        await page.waitForTimeout(1500);
        if (!n) break;
      }
      await page.waitForTimeout(2500);
      const metrics = await page.evaluate(() =>
        Array.from(document.querySelectorAll('[data-testid="stMetric"]')).map((e) => e.innerText.replace(/\n/g, ' | ')));
      log.push('  METRICS:');
      metrics.forEach((m) => log.push('     ' + m));
      const counts = await page.evaluate(() => ({
        charts: document.querySelectorAll('[data-testid="stVegaLiteChart"]').length,
        tables: document.querySelectorAll('[data-testid="stDataFrame"]').length,
        expanders: document.querySelectorAll('[data-testid="stExpander"]').length,
      }));
      log.push('  ' + JSON.stringify(counts));
      await shot(tag + '-02-results', true);
    } else {
      await shot(tag + '-02-failed', true);
    }
  };

  await runOnce('gridtied', false);
  await runOnce('offgrid', true);
  return log.join('\n');
}
