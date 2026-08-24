async (page) => {
  const log = [];
  // stash the captured network log into the page so it can be written to disk via browser_evaluate
  const cap = JSON.stringify(page.__cap || []);
  await page.evaluate(d => { window.__cap = d; }, cap);
  log.push('stashed capture into window.__cap (' + cap.length + ' chars, ' + (page.__cap||[]).length + ' events)');

  // full text of the validation error
  const err = await page.evaluate(() => {
    const nodes = Array.from(document.querySelectorAll('*'))
      .filter(e => e.getClientRects().length && /input_errors|Invalid inputs/i.test(e.innerText || ''))
      .sort((a,b) => a.innerText.length - b.innerText.length);
    return nodes.length ? nodes[0].innerText.trim() : '(not found)';
  });
  log.push('--- VALIDATION ERROR ---\n' + err.slice(0, 1200));

  // what outage-start controls exist and what are their values?
  const outage = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('input,select').forEach(e => {
      const id = (e.id || e.name || '');
      if (/outage|start_hour|start_date/i.test(id)) {
        out.push({ id, type: e.type, value: e.value, visible: e.getClientRects().length > 0,
                   opts: e.tagName === 'SELECT' ? e.options.length : undefined });
      }
    });
    return out;
  });
  log.push('--- OUTAGE CONTROLS ---\n' + JSON.stringify(outage, null, 1));
  return log.join('\n');
}
