// Pin down the orange panel-header bar and the results cards.
async (page) => {
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(2500);
  const a = await page.evaluate(() => {
    const out = {};
    // walk up/down from the "Site (required)" text to find the coloured bar
    const head = Array.from(document.querySelectorAll('.panel-heading'))
      .find(h => /Site/.test(h.innerText || ''));
    if (head) {
      const chain = [];
      let n = head;
      for (let i = 0; i < 3 && n; i++, n = n.parentElement) {
        const s = getComputedStyle(n);
        chain.push({ tag: n.tagName, cls: (n.className || '').toString().slice(0, 40),
                     bg: s.backgroundColor, color: s.color, padding: s.padding });
      }
      // children too
      Array.from(head.children).slice(0, 3).forEach(c => {
        const s = getComputedStyle(c);
        chain.push({ tag: 'child:' + c.tagName, cls: (c.className || '').toString().slice(0, 40),
                     bg: s.backgroundColor, color: s.color });
      });
      out.headerChain = chain;
    }
    return out;
  });
  return JSON.stringify(a, null, 1);
}
