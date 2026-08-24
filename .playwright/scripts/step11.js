async (page) => {
  const log = [];
  // inspect the hour select + date picker widget
  const info = await page.evaluate(() => {
    const h = document.getElementById('run_site_attributes_load_profile_attributes_outage_start_hour');
    const d = document.getElementById('run_site_attributes_load_profile_attributes_outage_start_date');
    const pickers = Array.from(document.querySelectorAll('input[type=date],.datepicker,[class*=date],[placeholder*=ate]'))
      .filter(e => e.getClientRects().length)
      .slice(0,5).map(e => ({ tag:e.tagName, id:e.id, cls:(e.className||'').toString().slice(0,45), ph:e.placeholder||'', val:e.value }));
    return {
      hourOpts: h ? Array.from(h.options).slice(0,5).map(o => o.value + '=' + o.text) : null,
      hourTotal: h ? h.options.length : 0,
      dateVal: d ? d.value : '(none)',
      pickers
    };
  });
  log.push(JSON.stringify(info, null, 1));

  // set the hidden date + visible hour, firing events so the app picks them up
  const res = await page.evaluate(() => {
    const fire = el => { ['input','change','blur'].forEach(t => el.dispatchEvent(new Event(t, { bubbles: true }))); };
    const d = document.getElementById('run_site_attributes_load_profile_attributes_outage_start_date');
    if (d) { d.value = '2024-07-16'; fire(d); }
    return { date: d ? d.value : null };
  });
  log.push('date set -> ' + JSON.stringify(res));

  try {
    const h = page.locator('#run_site_attributes_load_profile_attributes_outage_start_hour');
    await h.scrollIntoViewIfNeeded();
    const opts = await h.locator('option').allTextContents();
    // pick a late-afternoon start (index 17 if available, else the 2nd option)
    const values = await h.evaluate(el => Array.from(el.options).map(o => o.value));
    const target = values.includes('17') ? '17' : (values.filter(Boolean)[16] || values.filter(Boolean)[0]);
    await h.selectOption(target);
    log.push('hour selected -> ' + target + '  (of ' + values.length + ' options)');
  } catch (e) { log.push('hour FAILED: ' + String(e).split('\n')[0].slice(0,90)); }

  await page.waitForTimeout(800);
  const now = await page.evaluate(() => ({
    date: (document.getElementById('run_site_attributes_load_profile_attributes_outage_start_date')||{}).value,
    hour: (document.getElementById('run_site_attributes_load_profile_attributes_outage_start_hour')||{}).value
  }));
  log.push('now: ' + JSON.stringify(now));
  return log.join('\n');
}
