// Extract the COMPLETE results-page structure from a finished REopt run:
// every section, every table, every row label, in document order.
async (page) => {
  const URL = 'https://reopt.nlr.gov/tool/results/80c68644-7920-4096-b284-6d24e7e11ab8';
  const log = [];
  await page.goto(URL, { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(7000);

  // force every drawer open (nested ones resist clicking)
  for (let p = 0; p < 4; p++) {
    const closed = await page.evaluate(() =>
      Array.from(document.querySelectorAll('.panel-collapse.collapse'))
        .filter((c) => c.id && c.id !== 'topnav-collapse' && getComputedStyle(c).display === 'none')
        .map((c) => c.id));
    if (!closed.length) break;
    for (const id of closed) {
      try {
        const t = page.locator('[data-target="#' + id + '"], [href="#' + id + '"], [aria-controls="' + id + '"]').first();
        await t.scrollIntoViewIfNeeded();
        await t.click({ timeout: 3500 });
        await page.waitForTimeout(300);
      } catch (e) {}
    }
  }
  await page.evaluate(() => {
    document.querySelectorAll('.panel-collapse.collapse').forEach((c) => {
      c.classList.add('in'); c.style.display = 'block'; c.style.height = 'auto';
    });
  });
  await page.waitForTimeout(2500);

  const spec = await page.evaluate(() => {
    const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const out = { sections: [] };

    document.querySelectorAll('.panel-collapse').forEach((panel) => {
      if (!panel.id || panel.id === 'topnav-collapse') return;
      const head = document.querySelector(
        '[data-target="#' + panel.id + '"], [href="#' + panel.id + '"], [aria-controls="' + panel.id + '"]');
      const section = {
        id: panel.id,
        title: head ? clean(head.innerText) : panel.id,
        intro: '',
        tables: [],
        subheads: [],
      };
      // intro paragraph
      const p0 = panel.querySelector('p');
      if (p0) section.intro = clean(p0.innerText).slice(0, 300);
      // sub-headings inside the panel
      panel.querySelectorAll('h3,h4,h5,.panel-title').forEach((h) => {
        const t = clean(h.innerText);
        if (t && !section.subheads.includes(t)) section.subheads.push(t);
      });
      // tables: header cells + row labels + values
      panel.querySelectorAll('table').forEach((tbl) => {
        const header = Array.from(tbl.querySelectorAll('thead th, tr:first-child th'))
          .map((th) => clean(th.innerText));
        const rows = [];
        tbl.querySelectorAll('tr').forEach((tr) => {
          const cells = Array.from(tr.querySelectorAll('th,td')).map((c) => clean(c.innerText));
          if (!cells.length) return;
          if (cells.length === 1) { rows.push({ group: cells[0] }); return; }
          rows.push({ label: cells[0], values: cells.slice(1) });
        });
        if (rows.length) section.tables.push({ header, rows });
      });
      out.sections.push(section);
    });
    return out;
  });

  await page.evaluate((d) => { window.__resspec = d; }, JSON.stringify(spec));
  log.push('sections: ' + spec.sections.length);
  spec.sections.forEach((s) => {
    const nrows = s.tables.reduce((a, t) => a + t.rows.length, 0);
    log.push(`  ${s.id.padEnd(28)} "${s.title.slice(0, 42)}"  tables=${s.tables.length} rows=${nrows}`);
  });
  return log.join('\n');
}
