async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots';
  const log = [];
  const set = async (id, val) => {
    try { await page.locator('#' + id).fill(String(val), { timeout: 6000 }); log.push('  ' + id + ' = ' + val); }
    catch (e) { log.push('  FAIL ' + id + ': ' + String(e).split('\n')[0].slice(0,70)); }
  };
  const pick = async (id, val) => {
    try { await page.locator('#' + id).selectOption(String(val), { timeout: 6000 }); log.push('  ' + id + ' -> ' + val); }
    catch (e) { log.push('  FAIL ' + id + ': ' + String(e).split('\n')[0].slice(0,70)); }
  };

  // 1. choose the electricity rate
  const item = page.locator('.dropdown-item').first();
  const rateName = (await item.innerText()).trim();
  await item.click();
  await page.waitForTimeout(2500);
  const chosen = await page.locator('#dropdown-input').inputValue();
  log.push('RATE chosen: ' + chosen + '   (clicked: ' + rateName.slice(0,70) + ')');

  // 2. site
  log.push('SITE:');
  await set('run_site_attributes_land_acres', '5');

  // 3. load profile
  log.push('LOAD PROFILE:');
  await pick('run_site_attributes_load_profile_attributes_doe_reference_name', 'LargeOffice');
  await page.waitForTimeout(800);
  await set('run_site_attributes_load_profile_attributes_annual_kwh', '5000000');

  // 4. resilience / outage
  log.push('OUTAGE:');
  await set('run_site_attributes_load_profile_attributes_outage_duration', '48');
  await pick('run_site_attributes_load_profile_attributes_number_of_outages', '1');

  await page.waitForTimeout(1200);
  await page.screenshot({ path: SHOTS + '/06-site-load-outage.png', scale: 'css' });

  const state = await page.evaluate(() => {
    const g = id => { const e = document.getElementById(id); return e ? (e.value === '' ? '(empty)' : e.value) : '(missing)'; };
    return {
      rate: g('dropdown-input'),
      acres: g('run_site_attributes_land_acres'),
      building: g('run_site_attributes_load_profile_attributes_doe_reference_name'),
      annual_kwh: g('run_site_attributes_load_profile_attributes_annual_kwh'),
      outage_hours: g('run_site_attributes_load_profile_attributes_outage_duration'),
      n_outages: g('run_site_attributes_load_profile_attributes_number_of_outages')
    };
  });
  return log.join('\n') + '\n---\n' + JSON.stringify(state, null, 1);
}
