async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots';
  const log = [];
  const d = page.locator('#dropdown-input');
  await d.scrollIntoViewIfNeeded();
  await d.click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: SHOTS + '/05-rate-dropdown-open.png', scale: 'css' });

  const opts = await page.evaluate(() => {
    // find any visible list near the rate input
    const cands = Array.from(document.querySelectorAll('ul,ol,div'))
      .filter(e => e.querySelectorAll('li').length > 2 && e.getClientRects().length);
    const best = cands.sort((a,b) => b.querySelectorAll('li').length - a.querySelectorAll('li').length)[0];
    if (!best) return { found: false };
    return { found: true, id: best.id, cls: best.className,
             count: best.querySelectorAll('li').length,
             sample: Array.from(best.querySelectorAll('li')).slice(0,8).map(li => li.innerText.trim().replace(/\s+/g,' ').slice(0,80)) };
  });
  log.push('dropdown options: ' + JSON.stringify(opts, null, 1));
  return log.join('\n');
}
