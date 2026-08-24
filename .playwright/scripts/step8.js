async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots';
  const log = [];
  const set = async (id, val) => {
    try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded();
          await l.fill(String(val), { timeout: 6000 }); log.push('  OK   ' + id + ' = ' + val); }
    catch (e) { log.push('  FAIL ' + id + ' :: ' + String(e).split('\n')[0].slice(0,60)); }
  };
  const pick = async (id, val) => {
    try { const l = page.locator('#' + id); await l.scrollIntoViewIfNeeded();
          await l.selectOption(String(val), { timeout: 6000 }); log.push('  OK   ' + id + ' -> ' + val); }
    catch (e) { log.push('  FAIL ' + id + ' :: ' + String(e).split('\n')[0].slice(0,60)); }
  };

  log.push('RESILIENCE:');
  await pick('run_site_attributes_load_profile_attributes_number_of_outages', '1');
  await page.waitForTimeout(700);
  await set('run_site_attributes_load_profile_attributes_outage_duration', '48');
  await set('run_site_attributes_load_profile_attributes_critical_load_fraction', '50');

  log.push('FINANCIAL:');
  await set('run_site_attributes_financial_attributes_analysis_years', '25');
  await set('run_site_attributes_financial_attributes_offtaker_discount_rate_fraction', '8.3');
  await set('run_site_attributes_financial_attributes_elec_cost_escalation_rate_fraction', '1.7');

  log.push('PV:');
  await set('run_site_attributes_pv_attributes_installed_cost_per_kw', '1600');
  await set('run_site_attributes_pv_attributes_min_kw', '0');
  await set('run_site_attributes_pv_attributes_max_kw', '2000');

  log.push('BATTERY:');
  await set('run_site_attributes_storage_attributes_installed_cost_per_kwh', '300');
  await set('run_site_attributes_storage_attributes_installed_cost_per_kw', '800');
  await set('run_site_attributes_storage_attributes_installed_cost_constant', '0');
  await set('run_site_attributes_storage_attributes_om_cost_fraction_of_installed_cost', '2.5');
  await set('run_site_attributes_storage_attributes_min_kwh', '0');
  await set('run_site_attributes_storage_attributes_max_kwh', '4000');
  await pick('run_site_attributes_storage_attributes_can_grid_charge', 'true');
  await pick('run_site_attributes_storage_attributes_dispatch_strategy', 'cost_optimal');

  await page.waitForTimeout(1000);
  await page.screenshot({ path: SHOTS + '/08-form-filled.png', scale: 'css' });

  const final = await page.evaluate(() => {
    const ids = ['run_site_attributes_description','run_site_attributes_address','run_site_attributes_land_acres',
      'dropdown-input','run_site_attributes_load_profile_attributes_doe_reference_name',
      'run_site_attributes_load_profile_attributes_annual_kwh',
      'run_site_attributes_load_profile_attributes_outage_duration',
      'run_site_attributes_load_profile_attributes_number_of_outages',
      'run_site_attributes_load_profile_attributes_critical_load_fraction',
      'run_site_attributes_financial_attributes_analysis_years',
      'run_site_attributes_pv_attributes_installed_cost_per_kw','run_site_attributes_pv_attributes_max_kw',
      'run_site_attributes_storage_attributes_installed_cost_per_kwh',
      'run_site_attributes_storage_attributes_installed_cost_per_kw',
      'run_site_attributes_storage_attributes_max_kwh'];
    const o = {}; ids.forEach(i => { const e = document.getElementById(i); o[i.replace(/^run_site_attributes_/,'')] = e ? e.value : '(missing)'; });
    return o;
  });
  return log.join('\n') + '\n---FINAL---\n' + JSON.stringify(final, null, 1);
}
