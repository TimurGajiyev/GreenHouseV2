// Drive the Streamlit calculator and verify steps 1-5 render and a run completes.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/calculator';
  const log = [];
  const shot = async (n) => { await page.screenshot({ path: SHOTS + '/' + n + '.png', scale: 'css', fullPage: true }); log.push('shot ' + n); };

  await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(6000);

  const body = await page.evaluate(() => document.body.innerText);
  if (/Traceback|Error|Exception/i.test(body)) {
    log.push('!! app shows an error on load:');
    log.push(body.slice(0, 1200));
    await shot('00-error');
    return log.join('\n');
  }

  // which step headings rendered?
  const heads = await page.evaluate(() =>
    Array.from(document.querySelectorAll('h1,h2,h3'))
      .map((h) => h.innerText.trim()).filter(Boolean));
  log.push('HEADINGS:');
  heads.forEach((h) => log.push('   ' + h));

  await shot('01-initial');

  // count controls
  const ctl = await page.evaluate(() => ({
    buttons: document.querySelectorAll('button').length,
    inputs: document.querySelectorAll('input').length,
    expanders: document.querySelectorAll('[data-testid="stExpander"]').length,
  }));
  log.push('controls: ' + JSON.stringify(ctl));

  // click "Get results"
  const btn = page.getByRole('button', { name: /Get results/i }).first();
  if (!(await btn.count())) { log.push('!! Get results button not found'); return log.join('\n'); }
  await btn.scrollIntoViewIfNeeded();
  await btn.click();
  log.push('clicked Get results');

  // wait for either results or an error, up to 4 min
  let state = null;
  for (let i = 0; i < 24; i++) {
    await page.waitForTimeout(10000);
    state = await page.evaluate(() => {
      const b = document.body.innerText;
      return {
        running: /Solving|PVWatts|Fetching|Building load/i.test(b),
        failed: /Run failed|Traceback/i.test(b),
        done: /Results for your site/i.test(b),
        msg: (b.match(/Run failed[^\n]{0,300}/) || [''])[0],
      };
    });
    log.push('poll ' + (i + 1) + ' ' + JSON.stringify(state));
    if (state.done || state.failed) break;
  }
  await shot('02-after-run');

  if (state && state.done) {
    const nums = await page.evaluate(() => {
      const m = Array.from(document.querySelectorAll('[data-testid="stMetric"]'))
        .map((e) => e.innerText.replace(/\n/g, ' = '));
      return m;
    });
    log.push('METRICS:');
    nums.forEach((n) => log.push('   ' + n));
    const charts = await page.evaluate(() =>
      document.querySelectorAll('canvas, svg.marks, [data-testid="stVegaLiteChart"]').length);
    log.push('charts rendered: ' + charts);
  }
  return log.join('\n');
}
