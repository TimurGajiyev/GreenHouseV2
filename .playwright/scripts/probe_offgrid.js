// What does an Off-grid run require? Techs: Generator + Battery + PV (CHP unavailable).
async (page) => {
  const log = [];
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1500);
  await page.locator('#run_off_grid').check();
  await page.waitForTimeout(2500);

  const techIds = await page.evaluate(() => Array.from(document.querySelectorAll('input[id^=run_analyze_]')).map((c) => c.id));
  log.push('available techs off-grid: ' + JSON.stringify(techIds));

  for (const id of ['run_analyze_generator', 'run_analyze_battery', 'run_analyze_pv']) {
    try { await page.locator('#' + id).check({ timeout: 5000 }); log.push('  ticked ' + id); }
    catch (e) { log.push('  FAIL ' + id); }
  }
  await page.waitForTimeout(2500);

  const info = await page.evaluate(() => {
    const req = [];
    document.querySelectorAll('label').forEach((l) => {
      if (!/\*/.test(l.innerText) || !l.getClientRects().length) return;
      const f = l.getAttribute('for');
      const el = f ? document.getElementById(f) : null;
      req.push({ label: l.innerText.trim().replace(/\s+/g, ' ').slice(0, 60), id: f || '(none)', val: el ? el.value : '?' });
    });
    const panels = Array.from(document.querySelectorAll('.panel-collapse')).map((p) => p.id);
    const checked = {};
    document.querySelectorAll('input[id^=run_analyze_]').forEach((c) => { checked[c.id] = c.checked; });
    // off-grid specific fields
    const og = [];
    document.querySelectorAll('input,select').forEach((e) => {
      if (/offgrid|off_grid|operating_reserve|sr_required|min_load_met/i.test(e.id || '') && e.type !== 'hidden') {
        const l = e.id ? document.querySelector('label[for="' + CSS.escape(e.id) + '"]') : null;
        og.push({ id: e.id.slice(0, 66), val: e.value, vis: e.getClientRects().length > 0, label: l ? l.innerText.trim().replace(/\s+/g, ' ').slice(0, 50) : '' });
      }
    });
    return { req, panels, checked, og, hasTariff: !!document.getElementById('dropdown-input') };
  });
  log.push('checked: ' + JSON.stringify(info.checked));
  log.push('panels: ' + JSON.stringify(info.panels));
  log.push('electricity-rate control present? ' + info.hasTariff);
  log.push('REQUIRED(*):');
  info.req.forEach((r) => log.push('   ' + r.label.padEnd(58) + ' id=' + r.id.slice(0, 58) + ' val=' + JSON.stringify(r.val).slice(0, 14)));
  log.push('OFF-GRID specific fields:');
  info.og.forEach((f) => log.push('   ' + (f.vis ? 'VIS' : 'hid') + ' ' + f.id.padEnd(64) + ' ' + JSON.stringify(f.val).slice(0, 12) + ' ' + f.label));
  return log.join('\n');
}
