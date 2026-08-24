// Does the web UI actually remove CHP when Off-grid is selected?
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots';
  const log = [];
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1500);

  const snap = async (label) => {
    const s = await page.evaluate(() => {
      const out = {};
      document.querySelectorAll('input[type=checkbox]').forEach((c) => {
        if (!/^run_analyze_/.test(c.id)) return;
        const lbl = (c.closest('label') ? c.closest('label').innerText : c.id).trim().replace(/\s+/g, ' ');
        out[lbl || c.id] = {
          id: c.id,
          disabled: c.disabled,
          inDOM: true,
          visible: c.getClientRects().length > 0
        };
      });
      return out;
    });
    log.push('--- ' + label + ' (' + Object.keys(s).length + ' tech checkboxes present) ---');
    Object.entries(s).forEach(([k, v]) =>
      log.push('   ' + k.padEnd(36) + ' disabled=' + String(v.disabled).padEnd(6) + ' visible=' + v.visible));
    return s;
  };

  const grid = await snap('GRID-TIED (default)');
  await page.screenshot({ path: SHOTS + '/17-gridtied-techs.png', scale: 'css' });

  await page.locator('#run_off_grid').check();
  await page.waitForTimeout(2500);
  const off = await snap('OFF-GRID');
  await page.screenshot({ path: SHOTS + '/18-offgrid-techs.png', scale: 'css' });

  const gk = Object.keys(grid), ok = Object.keys(off);
  log.push('');
  log.push('REMOVED when off-grid: ' + JSON.stringify(gk.filter((k) => !ok.includes(k))));
  log.push('KEPT when off-grid:    ' + JSON.stringify(ok));

  const chpExists = await page.evaluate(() => !!document.getElementById('run_analyze_chp'));
  log.push('');
  log.push('#run_analyze_chp present in DOM off-grid? ' + chpExists);
  return log.join('\n');
}
