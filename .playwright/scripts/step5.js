async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots';
  const log = [];
  const d = page.locator('#dropdown-input');
  await d.scrollIntoViewIfNeeded();
  await d.click();
  await d.fill('');
  await d.type('Commercial', { delay: 80 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: SHOTS + '/05-rate-dropdown-open.png', scale: 'css' });

  const info = await page.evaluate(() => {
    const wrap = document.getElementById('search-dropdown-component');
    const all = Array.from(wrap.querySelectorAll('*')).map(e => ({
      tag: e.tagName, cls: (e.className && e.className.baseVal === undefined ? e.className : '').toString().slice(0,50),
      kids: e.children.length, txt: (e.innerText||'').trim().replace(/\s+/g,' ').slice(0,60)
    })).filter(x => x.txt || x.kids > 1);
    // also scan document for a floating options layer mentioning a utility name
    const floating = Array.from(document.querySelectorAll('li,div[role=option],[class*=item]'))
      .filter(e => e.getClientRects().length && /Elec|Utility|Commercial|Rural|Xcel|Public Service/i.test(e.innerText||''))
      .slice(0, 10).map(e => ({ tag: e.tagName, cls: (e.className||'').toString().slice(0,40), txt: e.innerText.trim().replace(/\s+/g,' ').slice(0,70) }));
    return { wrapInner: wrap.innerHTML.length, wrapChildren: wrap.children.length, all: all.slice(0,10), floating };
  });
  log.push(JSON.stringify(info, null, 1));
  return log.join('\n');
}
