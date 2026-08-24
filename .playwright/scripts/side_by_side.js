// Side-by-side: open REopt and our calculator in two tabs, capture both,
// and diff their Step 1-5 structure field by field.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/compare';
  const log = [];

  const ctx = page.context();

  // ---------- TAB 1: real REopt, configured PV + Battery + CHP ----------
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(2500);
  for (const id of ['run_analyze_pv', 'run_analyze_battery']) {
    try { await page.locator('#' + id).check({ timeout: 5000 }); } catch (e) {}
  }
  await page.waitForTimeout(2500);
  await page.screenshot({ path: SHOTS + '/reopt-steps.png', scale: 'css', fullPage: true });
  log.push('captured REopt (full page)');

  const reopt = await page.evaluate(() => {
    const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const steps = Array.from(document.querySelectorAll('h2'))
      .map((h) => clean(h.innerText)).filter((t) => /^Step \d/.test(t));
    // visible labelled inputs, grouped by panel
    const groups = {};
    document.querySelectorAll('input,select,textarea').forEach((el) => {
      if (el.type === 'hidden' || !el.getClientRects().length) return;
      const panel = (el.closest('.panel-collapse') || {}).id || 'top';
      let lab = '';
      if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) lab = clean(l.innerText); }
      if (!lab) { const g = el.closest('.form-group'); if (g) { const l = g.querySelector('label'); if (l) lab = clean(l.innerText); } }
      if (!lab) lab = clean(el.placeholder || '');
      (groups[panel] = groups[panel] || []).push({ id: el.id || el.name, label: lab, type: el.type });
    });
    // panel headings visible in step 5
    const panels = Array.from(document.querySelectorAll('.panel-heading, .panel-title'))
      .map((p) => clean(p.innerText)).filter(Boolean);
    return { steps, groups, panels };
  });
  log.push('REopt steps: ' + JSON.stringify(reopt.steps));
  log.push('REopt step-5 panels: ' + JSON.stringify([...new Set(reopt.panels)].slice(0, 12)));

  // ---------- TAB 2: our calculator ----------
  const p2 = await ctx.newPage();
  await p2.goto('http://localhost:8501', { waitUntil: 'load', timeout: 90000 });
  await p2.waitForTimeout(7000);
  // open every expander so all inputs are visible
  for (let i = 0; i < 3; i++) {
    const n = await p2.evaluate(() => {
      let c = 0;
      document.querySelectorAll('[data-testid="stExpander"] details').forEach((d) => {
        if (!d.open) { const s = d.querySelector('summary'); if (s) { s.click(); c++; } }
      });
      return c;
    });
    await p2.waitForTimeout(1200);
    if (!n) break;
  }
  await p2.waitForTimeout(1500);
  await p2.screenshot({ path: SHOTS + '/ours-steps.png', scale: 'css', fullPage: true });
  log.push('captured ours (full page)');

  const ours = await p2.evaluate(() => {
    const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const steps = Array.from(document.querySelectorAll('h2,h3'))
      .map((h) => clean(h.innerText)).filter((t) => /^Step \d/.test(t));
    const expanders = Array.from(document.querySelectorAll('[data-testid="stExpander"] summary'))
      .map((s) => clean(s.innerText));
    const labels = Array.from(document.querySelectorAll('label'))
      .map((l) => clean(l.innerText)).filter(Boolean);
    return { steps, expanders, labels };
  });
  log.push('ours steps: ' + JSON.stringify(ours.steps));
  log.push('ours sections: ' + JSON.stringify(ours.expanders));

  // ---------- diff ----------
  const norm = (s) => s.toLowerCase().replace(/[^a-z0-9]/g, '');
  const oursSet = new Set(ours.labels.map(norm));
  const missing = [];
  for (const [panel, fields] of Object.entries(reopt.groups)) {
    if (!['site', 'utility', 'load_profile', 'financial', 'pv', 'battery'].includes(panel)) continue;
    for (const f of fields) {
      if (!f.label) continue;
      const key = norm(f.label.replace(/\*/g, ''));
      if (key && !oursSet.has(key)) missing.push(panel + ' :: ' + f.label + '  [' + f.id + ']');
    }
  }
  log.push('');
  log.push('=== REopt fields NOT present in ours (' + missing.length + ') ===');
  missing.forEach((m) => log.push('   ' + m));

  await ctx.pages()[0].bringToFront();
  return log.join('\n');
}
