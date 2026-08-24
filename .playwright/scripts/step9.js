async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots';
  const log = [];
  const before = (page.__cap || []).length;

  const btn = page.getByRole('button', { name: /Get Results/i }).first();
  await btn.scrollIntoViewIfNeeded();
  await page.screenshot({ path: SHOTS + '/09-before-submit.png', scale: 'css' });
  log.push('clicking Get Results...');
  await btn.click();

  // wait for navigation or a results/progress indicator
  try { await page.waitForURL(/results|run|simulation/i, { timeout: 45000 }); log.push('navigated to ' + page.url()); }
  catch (e) { log.push('no URL change within 45s; url=' + page.url()); }
  await page.waitForTimeout(3000);
  await page.screenshot({ path: SHOTS + '/10-submitted.png', scale: 'css' });

  // any validation errors on the page?
  const errs = await page.evaluate(() => {
    const e = Array.from(document.querySelectorAll('.error, .alert-danger, .has-error, .invalid-feedback, [class*=error]'))
      .filter(x => x.getClientRects().length && x.innerText.trim())
      .slice(0, 8).map(x => x.innerText.trim().replace(/\s+/g,' ').slice(0,120));
    return e;
  });
  log.push('visible errors: ' + JSON.stringify(errs));
  log.push('title: ' + await page.title());
  log.push('url: ' + page.url());

  const newCap = (page.__cap || []).slice(before);
  log.push('new network events: ' + newCap.length);
  const posts = newCap.filter(c => c.dir === 'req' && c.method === 'POST');
  log.push('POSTs: ' + JSON.stringify(posts.map(p => ({ url: p.url.slice(0,110), bodyLen: p.body ? p.body.length : 0 })), null, 1));
  return log.join('\n');
}
