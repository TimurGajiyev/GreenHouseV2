// Screenshot the themed calculator before and after a run, and verify the
// REopt colours actually landed.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/theme';
  const log = [];
  await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(9000);

  const err = await page.evaluate(() => {
    const b = document.body.innerText;
    return /Traceback|StreamlitAPIException/.test(b)
      ? (b.match(/(Traceback|[A-Za-z]*Error|StreamlitAPIException)[^]{0,400}/) || [''])[0] : '';
  });
  if (err) { log.push('!! app error:'); log.push(err); await page.screenshot({ path: SHOTS + '/00-error.png', fullPage: true }); return log.join('\n'); }

  // verify the theme actually applied
  const theme = await page.evaluate(() => {
    const head = document.querySelector('.reopt-panel-head');
    const stepEl = document.querySelector('.reopt-step');
    const btn = Array.from(document.querySelectorAll('button')).find(b => /Get results/i.test(b.innerText));
    const cs = (el) => el ? getComputedStyle(el) : null;
    return {
      panelHeads: document.querySelectorAll('.reopt-panel-head').length,
      panelHeadBg: head ? cs(head).backgroundColor : null,
      panelHeadColor: head ? cs(head).color : null,
      stepColor: stepEl ? cs(stepEl).color : null,
      stepSize: stepEl ? cs(stepEl).fontSize : null,
      bodyFont: cs(document.body).fontFamily,
      appBg: cs(document.querySelector('[data-testid="stAppViewContainer"]') || document.body).backgroundColor,
      buttonBg: btn ? cs(btn).backgroundColor : null,
    };
  });
  log.push('THEME: ' + JSON.stringify(theme, null, 1));

  await page.screenshot({ path: SHOTS + '/01-form-top.png', scale: 'css' });
  await page.screenshot({ path: SHOTS + '/02-form-full.png', scale: 'css', fullPage: true });

  // run with defaults + a building type so the results page renders
  const box = page.locator('[data-testid="stSelectbox"]')
    .filter({ has: page.locator('label:has-text("Type of building")') }).first();
  const inp = box.locator('input').first();
  await inp.scrollIntoViewIfNeeded(); await inp.click();
  await page.waitForTimeout(600);
  await inp.type('Office - Large', { delay: 55 });
  await page.waitForTimeout(800);
  await inp.press('Enter');
  await page.waitForTimeout(2200);
  log.push('building -> ' + await box.locator('input').first().inputValue().catch(() => '?'));

  await page.getByRole('button', { name: /Get results/i }).first().click();
  log.push('submitted');
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
  log.push('final: ' + JSON.stringify(st));

  if (st && st.done) {
    await page.waitForTimeout(2000);
    const cards = await page.evaluate(() => ({
      statCards: document.querySelectorAll('.reopt-card').length,
      savingsCard: document.querySelectorAll('.reopt-savings').length,
      savingsBg: document.querySelector('.reopt-savings')
        ? getComputedStyle(document.querySelector('.reopt-savings')).backgroundColor : null,
      figures: Array.from(document.querySelectorAll('.reopt-fig-num')).map(e => e.innerText),
      savingsValue: (document.querySelector('.reopt-savings-value') || {}).innerText,
    }));
    log.push('CARDS: ' + JSON.stringify(cards));
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(600);
    await page.screenshot({ path: SHOTS + '/03-results-top.png', scale: 'css' });
    await page.screenshot({ path: SHOTS + '/04-results-full.png', scale: 'css', fullPage: true });
  }
  return log.join('\n');
}
