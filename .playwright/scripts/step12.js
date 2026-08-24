async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots';
  const log = [];
  const before = (page.__cap || []).length;

  const btn = page.getByRole('button', { name: /Get Results/i }).first();
  await btn.scrollIntoViewIfNeeded();
  await btn.click();
  log.push('submitted at ' + new Date().toISOString());

  let navigated = false;
  try { await page.waitForURL(/results|\/runs?\//i, { timeout: 60000 }); navigated = true; log.push('navigated -> ' + page.url()); }
  catch (e) { log.push('no nav in 60s; url=' + page.url()); }

  await page.waitForTimeout(2500);
  await page.screenshot({ path: SHOTS + '/10-submitted.png', scale: 'css' });

  const st = await page.evaluate(() => {
    const errs = Array.from(document.querySelectorAll('.error,.alert-danger,[class*=error]'))
      .filter(x => x.getClientRects().length && x.innerText.trim())
      .slice(0,4).map(x => x.innerText.trim().replace(/\s+/g,' ').slice(0,200));
    const body = document.body.innerText.replace(/\s+/g,' ');
    return { errs, url: location.href,
             running: /running|optimiz|processing|please wait|in progress/i.test(body),
             hasResults: /Financial|Net Present Value|System Size|Results/i.test(body),
             bodyHead: body.slice(0, 300) };
  });
  log.push('state: ' + JSON.stringify(st, null, 1));

  const nw = (page.__cap || []).slice(before);
  log.push('new net events: ' + nw.length + '  ' +
    JSON.stringify(nw.filter(c => c.dir === 'resp').map(c => c.status + ' ' + c.url.slice(0,90)).slice(-6), null, 1));
  return log.join('\n');
}
