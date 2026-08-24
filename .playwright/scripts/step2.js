async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots';
  const log = [];
  const set = async (id, val) => {
    const el = page.locator('#' + id.replace(/([:.\[\]])/g, '\$1'));
    try { await el.fill(String(val), { timeout: 5000 }); log.push(id + ' = ' + val); }
    catch (e) { log.push('FAIL ' + id + ': ' + String(e).slice(0, 70)); }
  };

  await set('run_site_attributes_description', 'GreenHouseV2 PV+Battery Resilience Test');

  // address autocomplete
  const addr = page.locator('#run_site_attributes_address');
  await addr.click();
  await addr.fill('');
  await addr.type('1617 Cole Blvd, Golden, CO 80401', { delay: 60 });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: SHOTS + '/03-address-autocomplete.png', scale: 'css' });

  // what suggestions appeared?
  const sugg = await page.evaluate(() => {
    const sels = ['.pac-container .pac-item', '.autocomplete-suggestion', 'ul[role=listbox] li', '.ui-menu-item', '[class*=suggestion]'];
    for (const s of sels) {
      const n = document.querySelectorAll(s);
      if (n.length) return { sel: s, items: Array.from(n).slice(0,5).map(e => e.innerText.trim().replace(/\s+/g,' ')) };
    }
    return { sel: null, items: [] };
  });
  log.push('suggestions: ' + JSON.stringify(sugg));

  if (sugg.sel && sugg.items.length) {
    await page.locator(sugg.sel).first().click();
    log.push('clicked first suggestion');
  } else {
    await addr.press('ArrowDown'); await page.waitForTimeout(400); await addr.press('Enter');
    log.push('used keyboard fallback');
  }
  await page.waitForTimeout(4000);
  await page.screenshot({ path: SHOTS + '/04-location-resolved.png', scale: 'css' });

  const after = await page.evaluate(() => {
    const g = id => { const e = document.getElementById(id); return e ? e.value : '(none)'; };
    return {
      address: g('run_site_attributes_address'),
      latlon: [g('run_site_attributes_latitude'), g('run_site_attributes_longitude')],
      rate: g('dropdown-input'),
      rateDisabled: (document.getElementById('dropdown-input')||{}).disabled
    };
  });
  return log.join('\n') + '\n---\n' + JSON.stringify(after, null, 1) + '\n---\nnet events: ' + (page.__cap ? page.__cap.length : 0);
}
