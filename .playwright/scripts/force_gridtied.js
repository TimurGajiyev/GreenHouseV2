// Force every collapsed drawer open via Bootstrap's `in` class, then
// re-screenshot the stragglers and re-extract the full markdown.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/gridtied';
  const log = [];

  const forced = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('.panel-collapse.collapse').forEach((c) => {
      if (!c.id || c.id === 'topnav-collapse') return;
      if (getComputedStyle(c).display === 'none') {
        c.classList.add('in');
        c.style.height = 'auto';
        c.style.display = 'block';
        out.push(c.id);
      }
    });
    return out;
  });
  log.push('force-opened: ' + JSON.stringify(forced));
  await page.waitForTimeout(1500);

  await page.evaluate(async () => {
    const h = document.documentElement.scrollHeight;
    for (let y = 0; y < h; y += 600) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 50)); }
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(1500);

  const st = await page.evaluate(() => {
    const c = Array.from(document.querySelectorAll('.panel-collapse.collapse')).filter((x) => x.id && x.id !== 'topnav-collapse');
    return { total: c.length, open: c.filter((x) => getComputedStyle(x).display !== 'none').length,
             tables: document.querySelectorAll('table').length,
             stillClosed: c.filter((x) => getComputedStyle(x).display === 'none').map((x) => x.id) };
  });
  log.push('DRAWERS ' + st.open + '/' + st.total + ' open  tables=' + st.tables +
           (st.stillClosed.length ? '  STILL CLOSED: ' + JSON.stringify(st.stillClosed) : '  (all open)'));

  // re-screenshot the ones we just forced
  for (const id of forced) {
    try {
      const el = page.locator('#' + id).first();
      await el.scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
      await el.screenshot({ path: SHOTS + '/drawer-forced-' + id + '.png' });
      log.push('  shot drawer-forced-' + id);
    } catch (e) { log.push('  FAILED shot ' + id); }
  }

  // full re-extract now that everything is open
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
    s += '- URL: ' + location.href + '\n- Captured: ' + new Date().toISOString() + '\n';
    const all = Array.from(document.querySelectorAll('.panel-collapse')).filter((c) => c.id && c.id !== 'topnav-collapse');
    s += '- Drawers: ' + all.length + ' (all expanded)\n- Tables: ' + document.querySelectorAll('table').length + '\n\n';
    all.forEach((d) => {
      const head = document.querySelector('[data-target="#' + d.id + '"], [href="#' + d.id + '"], [aria-controls="' + d.id + '"]');
      s += '\n---\n\n## ' + (head ? esc(head.innerText) : d.id) + '\n`#' + d.id + '`\n\n';
      const tabs = Array.from(d.querySelectorAll('table'));
      const clone = d.cloneNode(true);
      clone.querySelectorAll('table').forEach((t) => t.remove());
      const prose = (clone.innerText || '').replace(/\n{3,}/g, '\n\n').trim();
      if (prose) s += prose + '\n\n';
      tabs.forEach((t, i) => { const m = tableToMd(t); if (m) s += '**Table ' + (i + 1) + '**\n\n' + m + '\n\n'; });
    });
    const charts = Array.from(document.querySelectorAll('.highcharts-container'));
    if (charts.length) {
      s += '\n---\n\n## Charts (' + charts.length + ')\n\n';
      charts.forEach((c, i) => {
        const t = c.querySelector('.highcharts-title');
        const series = Array.from(c.querySelectorAll('.highcharts-legend-item text')).map((x) => x.textContent.trim());
        s += '- **Chart ' + (i + 1) + '**: ' + (t ? t.textContent.trim() : '(untitled)') +
             (series.length ? ' — series: ' + series.join(', ') : '') + '\n';
      });
    }
    return s;
  });
  await page.evaluate((d) => { window.__report = d; }, md);
  log.push('markdown re-extracted: ' + md.length + ' chars');
  return log.join('\n');
}
