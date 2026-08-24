// Discover which fields/panels appear for Grid-tied + Generator + CHP + Battery + PV.
async (page) => {
  const log = [];
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1500);

  const tick = async (name, exact) => {
    const cb = page.getByRole('checkbox', { name: name, exact: !!exact });
    try { if (!(await cb.isChecked())) await cb.check({ timeout: 5000 }); log.push('ticked ' + name); }
    catch (e) { try { await cb.click({ force: true }); log.push('force-ticked ' + name); }
                catch (e2) { log.push('FAILED ' + name); } }
  };
  await tick('Backup Generator');
  await tick('CHP');
  await tick('Battery');
  await tick('PV', true);
  await page.waitForTimeout(2500);

  const info = await page.evaluate(() => {
    const panels = Array.from(document.querySelectorAll('.panel-collapse'))
      .map((p) => ({ id: p.id, open: getComputedStyle(p).display !== 'none' }));
    // required markers
    const req = Array.from(document.querySelectorAll('label'))
      .filter((l) => /\*/.test(l.innerText) && l.getClientRects().length)
      .map((l) => l.innerText.trim().replace(/\s+/g, ' ').slice(0, 70));
    const chpFields = [];
    document.querySelectorAll('input,select,textarea').forEach((e) => {
      const id = e.id || e.name || '';
      if (/chp|boiler|heating|thermal|fuel/i.test(id) && e.type !== 'hidden') {
        let label = '';
        if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (l) label = l.innerText.trim().replace(/\s+/g, ' '); }
        chpFields.push({ id: id.slice(0, 70), type: e.type, val: e.value, vis: e.getClientRects().length > 0, label: label.slice(0, 55) });
      }
    });
    return { panels, req, chpCount: chpFields.length, chpFields: chpFields.slice(0, 40) };
  });
  log.push('PANELS: ' + JSON.stringify(info.panels));
  log.push('REQUIRED(*) labels: ' + JSON.stringify(info.req, null, 1));
  log.push('CHP/thermal fields (' + info.chpCount + '):');
  info.chpFields.forEach((f) => log.push('   ' + (f.vis ? 'VIS' : 'hid') + ' ' + f.id.padEnd(64) + ' ' + f.type.padEnd(11) + ' ' + JSON.stringify(f.val).slice(0, 18) + ' ' + f.label));
  return log.join('\n');
}
