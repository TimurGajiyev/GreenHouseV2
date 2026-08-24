// What does Prime Generator require, alongside CHP + Battery + PV?
async (page) => {
  const log = [];
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1500);
  for (const id of ['run_analyze_prime_generator', 'run_analyze_chp', 'run_analyze_battery', 'run_analyze_pv']) {
    try { await page.locator('#' + id).check({ timeout: 5000 }); } catch (e) { log.push('FAIL ' + id); }
  }
  await page.waitForTimeout(2500);

  const info = await page.evaluate(() => {
    const panels = Array.from(document.querySelectorAll('.panel-collapse')).map((p) => p.id);
    const req = [];
    document.querySelectorAll('label').forEach((l) => {
      if (!/\*/.test(l.innerText) || !l.getClientRects().length) return;
      const f = l.getAttribute('for');
      const el = f ? document.getElementById(f) : null;
      req.push({ label: l.innerText.trim().replace(/\s+/g, ' ').slice(0, 62), id: f || '(none)', value: el ? el.value : '?' });
    });
    const pg = [];
    document.querySelectorAll('input,select').forEach((e) => {
      if (/prime_generator|generator_attributes/i.test(e.id || '') && e.type !== 'hidden') {
        let lb = '';
        const l = e.id ? document.querySelector('label[for="' + CSS.escape(e.id) + '"]') : null;
        if (l) lb = l.innerText.trim().replace(/\s+/g, ' ');
        pg.push({ id: e.id.slice(0, 66), type: e.type, val: e.value, vis: e.getClientRects().length > 0, label: lb.slice(0, 48) });
      }
    });
    return { panels, req, pg: pg.slice(0, 25), pgTotal: pg.length };
  });
  log.push('PANELS: ' + JSON.stringify(info.panels));
  log.push('REQUIRED(*) fields:');
  info.req.forEach((r) => log.push('   ' + r.label.padEnd(64) + ' id=' + r.id.slice(0, 60) + ' val=' + JSON.stringify(r.value).slice(0, 16)));
  log.push('PRIME GENERATOR fields (' + info.pgTotal + '):');
  info.pg.forEach((f) => log.push('   ' + (f.vis ? 'VIS' : 'hid') + ' ' + f.id.padEnd(66) + ' ' + f.type.padEnd(11) + ' ' + JSON.stringify(f.val).slice(0, 14) + ' ' + f.label));
  return log.join('\n');
}
