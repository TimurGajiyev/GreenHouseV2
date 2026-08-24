// Probe: will the REopt web tool accept an off-grid site in Sana'a, Yemen?
async (page) => {
  const log = [];
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(6000);

  // Step 2: off-grid
  const og = page.locator('#run_off_grid');
  if (await og.count()) {
    await og.first().scrollIntoViewIfNeeded();
    await page.evaluate(() => {
      const e = document.querySelector('#run_off_grid');
      if (e) { e.click(); e.dispatchEvent(new Event('change', { bubbles: true })); }
    });
    await page.waitForTimeout(4000);
    log.push('off-grid selected: ' + await page.evaluate(() =>
      (document.querySelector('#run_off_grid') || {}).checked));
  } else { log.push('NO off_grid radio'); }

  // what technologies are offered now?
  log.push('techs: ' + JSON.stringify(await page.evaluate(() =>
    Array.from(document.querySelectorAll('input[id^="run_analyze_"]'))
      .map(e => ({ id: e.id, checked: e.checked, disabled: e.disabled })))));

  // address field -> try Yemen
  const addrSel = ['#run_site_attributes_address', 'input[name*="address"]',
                   '#address', 'input[placeholder*="address" i]'];
  let used = null;
  for (const s of addrSel) {
    const l = page.locator(s).first();
    if (await l.count()) { used = s; break; }
  }
  log.push('address selector: ' + used);
  if (used) {
    const l = page.locator(used).first();
    await l.scrollIntoViewIfNeeded();
    await l.click();
    await l.fill('15.2811, 44.0811');
    await page.waitForTimeout(3000);
    await l.press('Enter');
    await page.waitForTimeout(6000);
    log.push('after coords: ' + JSON.stringify(await page.evaluate(() => {
      const g = id => (document.getElementById(id) || {}).value;
      return {
        addr: g('run_site_attributes_address'),
        lat: g('run_site_attributes_latitude'), lon: g('run_site_attributes_longitude'),
        err: (document.body.innerText.match(/[^\n]*(not.{0,20}(found|support|valid)|outside|United States|U\.S\.)[^\n]*/i) || [''])[0],
      };
    })));
  }
  await page.screenshot({ path: 'D:/GreenHouseV2/reopt_test_screenshots/yemen/probe.png', scale: 'css' });
  return log.join('\n');
}
