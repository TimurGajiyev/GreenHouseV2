async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots';
  const log = [];

  // Expand every collapsed bootstrap panel by clicking its toggle
  const toggles = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('.panel-collapse.collapse').forEach(p => {
      const open = getComputedStyle(p).display !== 'none';
      const t = document.querySelector('[data-target="#' + p.id + '"], [href="#' + p.id + '"], [aria-controls="' + p.id + '"]');
      out.push({ id: p.id, open, hasToggle: !!t });
    });
    return out;
  });
  log.push('panels: ' + JSON.stringify(toggles));

  for (const p of toggles) {
    if (p.open || !p.hasToggle) continue;
    try {
      const t = page.locator('[data-target="#' + p.id + '"], [href="#' + p.id + '"], [aria-controls="' + p.id + '"]').first();
      await t.scrollIntoViewIfNeeded();
      await t.click({ timeout: 5000 });
      await page.waitForTimeout(600);
      log.push('expanded ' + p.id);
    } catch (e) { log.push('could not expand ' + p.id + ': ' + String(e).split('\n')[0].slice(0,60)); }
  }
  await page.waitForTimeout(1200);

  const after = await page.evaluate(() => {
    const panels = {};
    document.querySelectorAll('.panel-collapse.collapse').forEach(p => panels[p.id] = getComputedStyle(p).display !== 'none');
    let visible = 0;
    document.querySelectorAll('input,select,textarea').forEach(e => { if (e.type !== 'hidden' && e.getClientRects().length) visible++; });
    return { panels, visibleFields: visible };
  });
  log.push('after: ' + JSON.stringify(after, null, 1));
  await page.screenshot({ path: SHOTS + '/07-all-panels-expanded.png', scale: 'css' });
  return log.join('\n');
}
