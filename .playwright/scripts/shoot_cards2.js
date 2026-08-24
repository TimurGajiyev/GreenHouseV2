async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/theme';
  const log = [];
  const cards = page.locator('.reopt-card');
  const n = await cards.count();
  log.push('stat cards: ' + n);
  for (let i = 0; i < n; i++) {
    await cards.nth(i).scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
    await cards.nth(i).screenshot({ path: SHOTS + `/card-${i + 1}.png` });
    log.push('  shot card-' + (i + 1));
  }
  const sav = page.locator('.reopt-savings').first();
  if (await sav.count()) {
    await sav.scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
    await sav.screenshot({ path: SHOTS + '/card-savings.png' });
    log.push('  shot card-savings');
  }
  // and a viewport shot with both cards + savings visible
  const first = page.locator('.reopt-card').first();
  await first.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -160));
  await page.waitForTimeout(600);
  await page.screenshot({ path: SHOTS + '/06-cards-view.png', scale: 'css' });
  log.push('  shot 06-cards-view');
  return log.join('\n');
}
