// Extract the COMPLETE UI spec for steps 1-5 with PV + Battery + (CHP | Prime Generator).
// Captures: step headings, helper text, every field (label, type, unit, options,
// default, tooltip/help), panel grouping, and required markers.
async (page) => {
  const log = [];

  const grab = async (label) => {
    return await page.evaluate((cfgName) => {
      const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();

      // --- steps ---
      const steps = Array.from(document.querySelectorAll('h2, h3'))
        .filter((h) => /^Step \d/i.test(clean(h.innerText)) || /Step \d/i.test(clean(h.innerText)))
        .map((h) => clean(h.innerText));

      // --- tech checkboxes with their exact visible labels ---
      const techs = Array.from(document.querySelectorAll('input[id^=run_analyze_]')).map((c) => ({
        id: c.id,
        label: clean(c.closest('label') ? c.closest('label').innerText : ''),
        checked: c.checked, disabled: c.disabled
      }));

      // --- every form control ---
      const fields = [];
      document.querySelectorAll('input, select, textarea').forEach((el) => {
        if (el.type === 'hidden' || el.type === 'submit' || el.type === 'button') return;
        const id = el.id || el.name || '';
        if (!id) return;

        // label
        let label = '';
        if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) label = clean(l.innerText); }
        if (!label) { const g = el.closest('.form-group'); if (g) { const l = g.querySelector('label'); if (l) label = clean(l.innerText); } }
        if (!label) label = clean(el.placeholder || el.getAttribute('aria-label') || '');

        // tooltip / help text: REopt uses a sibling anchor with data-content / title
        let help = '';
        const grp = el.closest('.form-group') || el.parentElement;
        if (grp) {
          const t = grp.querySelector('[data-content], [data-original-title], [title]:not([title=""]), .help-block, .popover-content');
          if (t) help = clean(t.getAttribute('data-content') || t.getAttribute('data-original-title') || t.getAttribute('title') || t.innerText);
        }

        const panel = (el.closest('.panel-collapse') || {}).id || 'top';
        // panel heading text
        let panelTitle = '';
        if (panel !== 'top') {
          const h = document.querySelector('[data-target="#' + panel + '"], [href="#' + panel + '"], [aria-controls="' + panel + '"]');
          if (h) panelTitle = clean(h.innerText);
        }

        fields.push({
          cfg: cfgName,
          panel, panelTitle,
          id, name: el.name || '', tag: el.tagName.toLowerCase(), type: el.type || '',
          label, required: /\*/.test(label),
          value: (el.type === 'checkbox' || el.type === 'radio') ? String(el.checked) : el.value,
          placeholder: el.placeholder || '',
          min: el.getAttribute('min') || '', max: el.getAttribute('max') || '', step: el.getAttribute('step') || '',
          options: el.tagName === 'SELECT' ? Array.from(el.options).map((o) => ({ v: o.value, t: clean(o.text) })) : null,
          visible: el.getClientRects().length > 0,
          help
        });
      });
      return { steps, techs, fields };
    }, label);
  };

  const out = { configs: {} };

  // --- CONFIG A: grid-tied, PV + Battery + CHP ---
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1800);
  for (const id of ['run_analyze_pv', 'run_analyze_battery', 'run_analyze_chp']) {
    try { await page.locator('#' + id).check({ timeout: 5000 }); } catch (e) { log.push('A: fail ' + id); }
  }
  await page.waitForTimeout(2500);
  // expand everything so hidden advanced fields are captured too
  for (let p = 0; p < 3; p++) {
    const closed = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
      .filter((c) => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none').map((c) => c.id));
    if (!closed.length) break;
    for (const id of closed) {
      try { const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
        await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 3500 }); await page.waitForTimeout(300); } catch (e) {}
    }
  }
  // also reveal "advanced" sub-toggles (Change default..., custom cost, etc.)
  await page.evaluate(() => {
    document.querySelectorAll('.panel-collapse.collapse').forEach((c) => { c.classList.add('in'); c.style.display = 'block'; c.style.height = 'auto'; });
    document.querySelectorAll('[style*="display: none"]').forEach((e) => { if (e.querySelector && e.querySelector('input,select')) e.style.display = ''; });
  });
  await page.waitForTimeout(1200);
  out.configs.chp = await grab('chp');
  log.push('CONFIG chp: fields=' + out.configs.chp.fields.length + ' techs=' + out.configs.chp.techs.length);

  // --- CONFIG B: grid-tied, PV + Battery + Prime Generator ---
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1800);
  for (const id of ['run_analyze_pv', 'run_analyze_battery', 'run_analyze_prime_generator']) {
    try { await page.locator('#' + id).check({ timeout: 5000 }); } catch (e) { log.push('B: fail ' + id); }
  }
  await page.waitForTimeout(2500);
  for (let p = 0; p < 3; p++) {
    const closed = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
      .filter((c) => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none').map((c) => c.id));
    if (!closed.length) break;
    for (const id of closed) {
      try { const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
        await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 3500 }); await page.waitForTimeout(300); } catch (e) {}
    }
  }
  await page.evaluate(() => {
    document.querySelectorAll('.panel-collapse.collapse').forEach((c) => { c.classList.add('in'); c.style.display = 'block'; c.style.height = 'auto'; });
  });
  await page.waitForTimeout(1200);
  out.configs.prime = await grab('prime');
  log.push('CONFIG prime: fields=' + out.configs.prime.fields.length);

  // --- CONFIG C: off-grid, PV + Battery + Generator ---
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(1800);
  await page.locator('#run_off_grid').check();
  await page.waitForTimeout(2500);
  for (const id of ['run_analyze_pv', 'run_analyze_battery', 'run_analyze_generator']) {
    try { await page.locator('#' + id).check({ timeout: 5000 }); } catch (e) { log.push('C: fail ' + id); }
  }
  await page.waitForTimeout(2500);
  for (let p = 0; p < 3; p++) {
    const closed = await page.evaluate(() => Array.from(document.querySelectorAll('.panel-collapse.collapse'))
      .filter((c) => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none').map((c) => c.id));
    if (!closed.length) break;
    for (const id of closed) {
      try { const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
        await t.scrollIntoViewIfNeeded(); await t.click({ timeout: 3500 }); await page.waitForTimeout(300); } catch (e) {}
    }
  }
  await page.evaluate(() => {
    document.querySelectorAll('.panel-collapse.collapse').forEach((c) => { c.classList.add('in'); c.style.display = 'block'; c.style.height = 'auto'; });
  });
  await page.waitForTimeout(1200);
  out.configs.offgrid = await grab('offgrid');
  log.push('CONFIG offgrid: fields=' + out.configs.offgrid.fields.length);

  await page.evaluate((d) => { window.__uispec = d; }, JSON.stringify(out));
  log.push('stashed window.__uispec');
  log.push('STEPS(chp cfg): ' + JSON.stringify(out.configs.chp.steps));
  return log.join('\n');
}
