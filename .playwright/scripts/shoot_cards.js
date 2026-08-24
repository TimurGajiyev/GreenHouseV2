// Tight screenshot of the results header + cards, to compare against REopt.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/theme';
  const log = [];
  const box = await page.evaluate(() => {
    const h = Array.from(document.querySelectorAll('h2,h3'))
      .find(e => /Results for your site/i.test(e.innerText || ''));
    if (!h) return null;
    const last = document.querySelectorAll('.reopt-savings');
    const end = last.length ? last[last.length - 1] : h;
    const a = h.getBoundingClientRect(), b = end.getBoundingClientRect();
    return { top: a.top + window.scrollY - 20, bottom: b.bottom + window.scrollY + 120 };
  });
  if (!box) { log.push('results header not found'); return log.join('\n'); }
  await page.evaluate((t) => window.scrollTo(0, t), box.top);
  await page.waitForTimeout(900);
  await page.screenshot({ path: SHOTS + '/05-cards.png', scale: 'css' });
  log.push('shot 05-cards.png');

  const detail = await page.evaluate(() => {
    const g = (sel) => Array.from(document.querySelectorAll(sel)).map(e => e.innerText.replace(/\n/g, ' | '));
    return {
      titles: g('.reopt-card-title'),
      figs: g('.reopt-fig-num'),
      labs: g('.reopt-fig-lab'),
      savings: g('.reopt-savings-title').concat(g('.reopt-savings-value')),
    };
  });
  log.push(JSON.stringify(detail, null, 1));
  return log.join('\n');
}
