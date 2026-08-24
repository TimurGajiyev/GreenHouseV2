// Expand EVERY drawer on a REopt results page, screenshot each one,
// and extract all text + tables to markdown (stashed in window.__report).
// SHOTS is rewritten per-scenario before each run.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/offgrid';
  const log = [];

  // --- 1. expand every collapsible, repeatedly (drawers nest) ---
  let totalOpened = 0;
  for (let pass = 1; pass <= 4; pass++) {
    const targets = await page.evaluate(() =>
      Array.from(document.querySelectorAll('.panel-collapse.collapse'))
        .filter((c) => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none')
        .map((c) => c.id));
    if (!targets.length) { log.push('pass ' + pass + ': nothing left collapsed'); break; }
    let opened = 0;
    for (const id of targets) {
      try {
        const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
        await t.scrollIntoViewIfNeeded();
        await t.click({ timeout: 4000 });
        await page.waitForTimeout(350);
        opened++;
      } catch (e) { log.push('   could not open #' + id); }
    }
    totalOpened += opened;
    log.push('pass ' + pass + ': opened ' + opened + '/' + targets.length);
  }
  await page.waitForTimeout(2500);

  // nudge lazy charts into rendering
  await page.evaluate(async () => {
    const h = document.documentElement.scrollHeight;
    for (let y = 0; y < h; y += 600) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 60)); }
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(2500);

  const state = await page.evaluate(() => {
    const c = Array.from(document.querySelectorAll('.panel-collapse.collapse'))
      .filter((x) => x.id && x.id !== 'topnav-collapse');
    return { drawers: c.length, open: c.filter((x) => getComputedStyle(x).display !== 'none').length,
             tables: document.querySelectorAll('table').length,
             charts: document.querySelectorAll('.highcharts-container, svg.highcharts-root, canvas').length };
  });
  log.push('DRAWERS ' + state.open + '/' + state.drawers + ' open  tables=' + state.tables + ' charts=' + state.charts);

  // --- 2. screenshot each drawer individually ---
  const ids = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.panel-collapse'))
      .filter((c) => c.id && c.id !== 'topnav-collapse').map((c) => c.id));
  let n = 0;
  for (const id of ids) {
    n++;
    const name = String(n).padStart(2, '0') + '-' + id;
    try {
      const el = page.locator('#' + id).first();
      await el.scrollIntoViewIfNeeded();
      await page.waitForTimeout(450);
      await el.screenshot({ path: SHOTS + '/drawer-' + name + '.png' });
      log.push('  shot drawer-' + name);
    } catch (e) {
      try { await page.screenshot({ path: SHOTS + '/drawer-' + name + '-viewport.png', scale: 'css' });
            log.push('  shot drawer-' + name + ' (viewport fallback)'); }
      catch (e2) { log.push('  FAILED shot ' + name); }
    }
  }

  // --- 3. whole-page screenshot in viewport-height slices ---
  const slices = await page.evaluate(() => Math.ceil(document.documentElement.scrollHeight / window.innerHeight));
  for (let i = 0; i < Math.min(slices, 30); i++) {
    await page.evaluate((k) => window.scrollTo(0, k * window.innerHeight), i);
    await page.waitForTimeout(400);
    await page.screenshot({ path: SHOTS + '/page-slice-' + String(i + 1).padStart(2, '0') + '.png', scale: 'css' });
  }
  log.push('page slices: ' + Math.min(slices, 30));

  // --- 4. extract every drawer's text + tables as markdown ---
  const md = await page.evaluate(() => {
    const esc = (s) => (s || '').trim().replace(/\s+/g, ' ').replace(/\|/g, '\\|');
    const tableToMd = (t) => {
      const rows = Array.from(t.querySelectorAll('tr'));
      if (!rows.length) return '';
      const out = rows.map((tr) => '| ' + Array.from(tr.querySelectorAll('th,td')).map((c) => esc(c.innerText)).join(' | ') + ' |');
      const cols = (out[0].match(/\|/g) || []).length - 1;
      if (out.length > 1) out.splice(1, 0, '|' + ' --- |'.repeat(cols));
      return out.join('\n');
    };
    let s = '# REopt Results — ' + document.title + '\n\n';
    s += '- URL: ' + location.href + '\n';
    s += '- Captured: ' + new Date().toISOString() + '\n\n';

    const drawers = Array.from(document.querySelectorAll('.panel-collapse')).filter((c) => c.id && c.id !== 'topnav-collapse');
    drawers.forEach((d) => {
      const head = document.querySelector('[data-target="#' + d.id + '"], [href="#' + d.id + '"], [aria-controls="' + d.id + '"]');
      const title = head ? esc(head.innerText) : d.id;
      s += '\n---\n\n## ' + title + '  \n`#' + d.id + '` · open=' + (getComputedStyle(d).display !== 'none') + '\n\n';
      const tabs = Array.from(d.querySelectorAll('table'));
      // text with tables stripped out, so prose is not duplicated
      const clone = d.cloneNode(true);
      clone.querySelectorAll('table').forEach((t) => t.remove());
      const prose = (clone.innerText || '').replace(/\n{3,}/g, '\n\n').trim();
      if (prose) s += prose + '\n\n';
      tabs.forEach((t, i) => { const m = tableToMd(t); if (m) s += '**Table ' + (i + 1) + '**\n\n' + m + '\n\n'; });
    });

    // charts: capture their rendered data labels / series names
    const charts = Array.from(document.querySelectorAll('.highcharts-container'));
    if (charts.length) {
      s += '\n---\n\n## Charts (' + charts.length + ')\n\n';
      charts.forEach((c, i) => {
        const title = c.querySelector('.highcharts-title');
        const series = Array.from(c.querySelectorAll('.highcharts-legend-item text')).map((t) => t.textContent.trim());
        s += '- **Chart ' + (i + 1) + '**: ' + (title ? title.textContent.trim() : '(untitled)') +
             (series.length ? ' — series: ' + series.join(', ') : '') + '\n';
      });
    }
    return s;
  });
  await page.evaluate((d) => { window.__report = d; }, md);
  log.push('markdown extracted: ' + md.length + ' chars (window.__report)');
  return log.join('\n');
}
