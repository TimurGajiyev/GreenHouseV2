// Inspect the accordion/drawer structure of a completed results page.
async (page) => {
  const log = [];
  await page.goto('https://reopt.nlr.gov/tool/results/2a557c51-d812-415c-9596-63440a3af76e',
                  { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(6000);

  const info = await page.evaluate(() => {
    const collapses = Array.from(document.querySelectorAll('.panel-collapse, .collapse'))
      .map((c) => ({ id: c.id, cls: (c.className || '').toString().slice(0, 40),
                     open: getComputedStyle(c).display !== 'none',
                     textLen: (c.innerText || '').length }))
      .filter((c) => c.id);
    const toggles = Array.from(document.querySelectorAll('[data-toggle=collapse],[data-bs-toggle=collapse],a[href^="#"],button[aria-controls]'))
      .filter((t) => t.getClientRects().length)
      .map((t) => ({ tag: t.tagName, txt: (t.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 45),
                     target: t.getAttribute('data-target') || t.getAttribute('data-bs-target') || t.getAttribute('href') || t.getAttribute('aria-controls'),
                     expanded: t.getAttribute('aria-expanded') }))
      .filter((t) => t.target && t.target !== '#');
    return { nCollapse: collapses.length, collapses: collapses.slice(0, 40),
             nToggle: toggles.length, toggles: toggles.slice(0, 40),
             tables: document.querySelectorAll('table').length,
             charts: document.querySelectorAll('.highcharts-container, svg.highcharts-root, canvas').length,
             bodyLen: document.body.innerText.length };
  });
  log.push('collapses=' + info.nCollapse + ' toggles=' + info.nToggle +
           ' tables=' + info.tables + ' charts=' + info.charts + ' bodyLen=' + info.bodyLen);
  log.push('--- COLLAPSE TARGETS ---');
  info.collapses.forEach((c) => log.push('   ' + String(c.id).padEnd(38) + ' open=' + String(c.open).padEnd(6) + ' len=' + c.textLen + '  ' + c.cls));
  log.push('--- TOGGLES ---');
  info.toggles.forEach((t) => log.push('   ' + t.tag.padEnd(7) + ' -> ' + String(t.target).padEnd(36) + ' exp=' + String(t.expanded).padEnd(6) + ' "' + t.txt + '"'));
  return log.join('\n');
}
