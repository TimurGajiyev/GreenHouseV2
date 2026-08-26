// Does the fleet UI appear, and is it inert at one unit?
async (page) => {
  const log = [];
  const openAll = async () => {
    for (let i = 0; i < 5; i++) {
      const n = await page.evaluate(() => {
        let c = 0;
        document.querySelectorAll('[data-testid="stExpander"] details').forEach(d => {
          if (!d.open) { const s = d.querySelector('summary'); if (s) { s.click(); c++; } }
        });
        return c;
      });
      await page.waitForTimeout(900);
      if (!n) break;
    }
  };
  const setNum = async (lab, val) => {
    const loc = page.locator(`input[type="number"][aria-label*="${lab}" i]`).first();
    if (!(await loc.count())) { log.push('  MISSING ' + lab); return false; }
    await loc.scrollIntoViewIfNeeded(); await loc.click();
    await loc.press('Control+a'); await loc.fill(String(val)); await loc.press('Enter');
    await page.waitForTimeout(1400);
    return true;
  };
  const pill = async (name) => {
    const b = page.getByRole('button', { name, exact: true }).first();
    if (!(await b.count())) { log.push('  MISSING pill ' + name); return false; }
    await b.scrollIntoViewIfNeeded(); await b.click(); await page.waitForTimeout(2200);
    return true;
  };

  await page.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(9000);
  await pill('Prime Generator');
  await openAll();

  const probe = () => page.evaluate(() => {
    const t = document.body.innerText;
    const labels = Array.from(document.querySelectorAll('input[type="number"]'))
      .map(e => (e.getAttribute('aria-label') || '').trim());
    return {
      genCount: labels.filter(l => /Number of fuel-fired units/i.test(l)).length,
      batCount: labels.filter(l => /Number of battery units/i.test(l)).length,
      partLoad: /Part-load behaviour/i.test(t),
      turndown: labels.some(l => /Minimum turndown/i.test(l)),
      fleetPanel: /Fleet — /.test(t),
      bankPanel: /Battery bank — /.test(t),
      unit2: labels.some(l => /Maximum capacity \(kW\)/i.test(l)),
      warn: /beyond what the REopt web tool computes/i.test(t),
    };
  });

  log.push('at 1 unit:  ' + JSON.stringify(await probe()));

  await setNum('Number of fuel-fired units', 3);
  await openAll();
  await setNum('Number of battery units', 2);
  await openAll();
  log.push('at 3 gen / 2 bat: ' + JSON.stringify(await probe()));

  const names = await page.evaluate(() =>
    Array.from(document.querySelectorAll('input[type="text"]'))
      .map(e => e.value).filter(v => /^(Unit|Battery) \d/.test(v)));
  log.push('unit name fields: ' + JSON.stringify(names));

  await page.screenshot({ path: 'D:/GreenHouseV2/reopt_test_screenshots/fleet/fleet-form.png', scale: 'css' });
  return log.join('\n');
}
