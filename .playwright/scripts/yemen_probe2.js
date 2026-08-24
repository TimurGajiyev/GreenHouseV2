// Can the tool geocode a Yemeni address, and does it accept the site once set?
async (page) => {
  const log = [];
  const state = () => page.evaluate(() => {
    const g = id => (document.getElementById(id) || {}).value;
    const t = document.body.innerText;
    return {
      addr: g('run_site_attributes_address'),
      lat: g('run_site_attributes_latitude'),
      lon: g('run_site_attributes_longitude'),
      msg: (t.match(/[^\n]*(only.{0,40}United States|not.{0,25}(found|supported|valid)|outside|must be (in|within))[^\n]*/i) || [''])[0],
    };
  });

  for (const q of ["Sana'a, Yemen", 'Bani Mattar, Sanaa, Yemen', '15.2811,44.0811']) {
    const l = page.locator('#run_site_attributes_address').first();
    await l.scrollIntoViewIfNeeded();
    await l.click();
    await l.press('Control+a');
    await l.fill(q);
    await page.waitForTimeout(3500);
    // take the first autocomplete suggestion if one appeared
    const sug = page.locator('.pac-item, [class*="autocomplete"] li, [role="option"]').first();
    const n = await sug.count();
    if (n) { await sug.click(); } else { await l.press('Enter'); }
    await page.waitForTimeout(5000);
    log.push(`"${q}" suggestions=${n} -> ` + JSON.stringify(await state()));
  }

  // last resort: write lat/lon straight into the hidden inputs and see if it sticks
  log.push('forced -> ' + JSON.stringify(await page.evaluate(() => {
    const set = (id, v) => {
      const e = document.getElementById(id);
      if (!e) return 'no-' + id;
      e.value = v;
      e.dispatchEvent(new Event('input', { bubbles: true }));
      e.dispatchEvent(new Event('change', { bubbles: true }));
      return e.value;
    };
    return {
      lat: set('run_site_attributes_latitude', '15.2811'),
      lon: set('run_site_attributes_longitude', '44.0811'),
      addr: set('run_site_attributes_address', "Bani Mattar, Sana'a, Yemen"),
    };
  })));
  await page.waitForTimeout(4000);
  log.push('after force -> ' + JSON.stringify(await state()));
  await page.screenshot({ path: 'D:/GreenHouseV2/reopt_test_screenshots/yemen/probe2.png', scale: 'css' });
  return log.join('\n');
}
