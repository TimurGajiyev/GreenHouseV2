async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots';
  const log = [];

  // Persistent network capture on the page object (survives across MCP calls)
  if (!page.__cap) {
    page.__cap = [];
    page.on('request', req => {
      const u = req.url();
      if (/\/api\/|\/job|reopt|results|simulated_load|urdb|pvwatts/i.test(u) && req.method() !== 'OPTIONS') {
        let body = null;
        try { body = req.postData(); } catch (e) {}
        page.__cap.push({ t: Date.now(), dir: 'req', method: req.method(), url: u, body: body ? body.slice(0, 200000) : null });
      }
    });
    page.on('response', async resp => {
      const u = resp.url();
      if (/\/api\/|\/job|reopt|results|simulated_load|urdb|pvwatts/i.test(u)) {
        page.__cap.push({ t: Date.now(), dir: 'resp', status: resp.status(), url: u });
      }
    });
    log.push('network capture attached');
  }

  const shot = async (n) => { await page.screenshot({ path: SHOTS + '/' + n + '.png', scale: 'css' }); log.push('shot ' + n); };

  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 60000 });
  await page.waitForTimeout(1500);
  await shot('01-landing');

  // helper: tick a checkbox robustly (custom-styled inputs need the label click)
  const tick = async (name, exact) => {
    const cb = page.getByRole('checkbox', { name, exact: !!exact });
    try {
      if (await cb.isChecked()) { log.push(name + ': already checked'); return; }
      await cb.check({ timeout: 4000 });
      log.push(name + ': checked via check()');
    } catch (e) {
      try { await cb.click({ force: true, timeout: 4000 }); log.push(name + ': clicked force'); }
      catch (e2) { log.push(name + ': FAILED ' + String(e2).slice(0, 80)); }
    }
  };

  await tick('Resilience');
  await tick('PV', true);
  await tick('Battery');
  await page.waitForTimeout(1500);
  await shot('02-goals-and-techs');

  // report resulting state
  const state = await page.evaluate(() => {
    const out = {};
    document.querySelectorAll('input[type=checkbox]').forEach(c => {
      const lbl = (c.closest('label')?.innerText || c.getAttribute('aria-label') || c.id || '').trim().replace(/\s+/g,' ').slice(0,40);
      if (lbl) out[lbl] = c.checked;
    });
    return { checks: out, textboxes: document.querySelectorAll('input[type=text],input:not([type])').length,
             scrollH: document.documentElement.scrollHeight };
  });
  return log.join('\n') + '\n---\n' + JSON.stringify(state, null, 1);
}
