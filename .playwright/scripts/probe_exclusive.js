// Are Prime Generator and CHP mutually exclusive? Test both orders.
async (page) => {
  const log = [];
  const state = () => page.evaluate(() => {
    const g = (id) => { const e = document.getElementById(id); return e ? { inDOM: true, checked: e.checked, disabled: e.disabled, vis: e.getClientRects().length > 0 } : { inDOM: false }; };
    return { prime: g('run_analyze_prime_generator'), chp: g('run_analyze_chp'),
             panels: Array.from(document.querySelectorAll('.panel-collapse')).map((p) => p.id) };
  });

  // ORDER 1: prime first, then CHP
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1500);
  await page.locator('#run_analyze_prime_generator').check();
  await page.waitForTimeout(1800);
  log.push('after PRIME:   ' + JSON.stringify(await state()));
  let r = 'n/a';
  try { await page.locator('#run_analyze_chp').check({ timeout: 4000 }); r = 'CHP check() OK'; }
  catch (e) { r = 'CHP check() BLOCKED (' + String(e).split('\n')[0].slice(0, 45) + ')'; }
  await page.waitForTimeout(1500);
  log.push('  -> ' + r);
  log.push('after +CHP:    ' + JSON.stringify(await state()));

  // ORDER 2: CHP first, then prime
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1500);
  await page.locator('#run_analyze_chp').check();
  await page.waitForTimeout(1800);
  log.push('');
  log.push('after CHP:     ' + JSON.stringify(await state()));
  try { await page.locator('#run_analyze_prime_generator').check({ timeout: 4000 }); r = 'PRIME check() OK'; }
  catch (e) { r = 'PRIME check() BLOCKED (' + String(e).split('\n')[0].slice(0, 45) + ')'; }
  await page.waitForTimeout(1500);
  log.push('  -> ' + r);
  log.push('after +PRIME:  ' + JSON.stringify(await state()));
  return log.join('\n');
}
