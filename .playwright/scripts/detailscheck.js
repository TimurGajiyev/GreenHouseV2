async (page) => {
  const base = 'https://natlabrockies.github.io/REopt.jl/dev/';
  const rels = ['','reopt/examples/','reopt/inputs/','reopt/outputs/','reopt/methods/',
    'mpc/examples/','mpc/inputs/','mpc/outputs/','mpc/methods/','developer/concept/',
    'developer/organization/','developer/inputs/','developer/adding_tech/','developer/documentation/'];
  const out = [];
  for (const r of rels) {
    await page.goto(base + r, { waitUntil: 'load', timeout: 60000 });
    const info = await page.evaluate(() => {
      const m = document.querySelector('#documenter-page');
      const det = Array.from(m.querySelectorAll('details'));
      const before = m.innerText.length;
      const closed = det.filter(d => !d.open).length;
      det.forEach(d => d.open = true);
      const after = m.innerText.length;
      // anything else hidden?
      let hiddenText = 0;
      m.querySelectorAll('*').forEach(e => {
        const cs = getComputedStyle(e);
        if ((cs.display === 'none' || cs.visibility === 'hidden') && e.textContent.trim()) {
          hiddenText += e.textContent.trim().length;
        }
      });
      return { details: det.length, closed, before, after, hiddenText };
    });
    out.push((r || '(home)').padEnd(26) + 'details=' + String(info.details).padStart(3) +
      ' closed=' + String(info.closed).padStart(3) +
      ' innerText ' + String(info.before).padStart(6) + ' -> ' + String(info.after).padStart(6) +
      (info.after !== info.before ? '  <-- GREW +' + (info.after - info.before) : '') +
      '  hiddenTextChars=' + info.hiddenText);
  }
  return out.join('\n');
}
