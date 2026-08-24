// Under what conditions does the "Backup Generator" checkbox exist?
async (page) => {
  const log = [];
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1500);

  const probe = async (label) => {
    const s = await page.evaluate(() => {
      const out = {};
      document.querySelectorAll('input[id^=run_analyze_]').forEach((c) => {
        const lbl = (c.closest('label') ? c.closest('label').innerText : '').trim().replace(/\s+/g, ' ');
        out[c.id] = { label: lbl, visible: c.getClientRects().length > 0, disabled: c.disabled, checked: c.checked };
      });
      return out;
    });
    log.push('--- ' + label + ' ---');
    Object.entries(s).forEach(([k, v]) => log.push('   ' + k.padEnd(32) + ' "' + v.label + '" vis=' + v.visible + ' checked=' + v.checked));
    return Object.keys(s);
  };

  const a = await probe('Grid-tied, Cost Savings only (default)');

  // turn Resilience ON
  await page.locator('#resilience').check();
  await page.waitForTimeout(2000);
  const b = await probe('Grid-tied, Cost Savings + Resilience');

  log.push('');
  log.push('APPEARS only with Resilience: ' + JSON.stringify(b.filter((k) => !a.includes(k))));
  return log.join('\n');
}
