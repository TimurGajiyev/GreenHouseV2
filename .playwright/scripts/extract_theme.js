// Extract REopt's actual colours, fonts and panel styling.
async (page) => {
  await page.goto('https://reopt.nlr.gov/tool', { waitUntil: 'load', timeout: 90000 });
  await page.waitForTimeout(3000);
  for (const id of ['run_analyze_pv', 'run_analyze_battery']) {
    try { await page.locator('#' + id).check({ timeout: 4000 }); } catch (e) {}
  }
  await page.waitForTimeout(2000);

  const theme = await page.evaluate(() => {
    const cs = (el) => el ? getComputedStyle(el) : null;
    const pick = (el, props) => {
      const s = cs(el); if (!s) return null;
      const o = {}; props.forEach(p => o[p] = s[p]); return o;
    };
    const out = {};
    out.body = pick(document.body, ['backgroundColor', 'color', 'fontFamily', 'fontSize']);

    // panel headings (the orange bars)
    const heads = Array.from(document.querySelectorAll('.panel-heading'));
    out.panelHeading = heads.slice(0, 3).map(h => ({
      text: (h.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 30),
      ...pick(h, ['backgroundColor', 'color', 'fontSize', 'fontWeight', 'padding', 'borderRadius']),
    }));
    // panel body
    const body = document.querySelector('.panel-body');
    out.panelBody = pick(body, ['backgroundColor', 'color', 'padding', 'border']);
    // panel container
    const panel = document.querySelector('.panel');
    out.panel = pick(panel, ['backgroundColor', 'border', 'borderRadius', 'marginBottom', 'boxShadow']);

    // step headings
    const h2 = Array.from(document.querySelectorAll('h2')).find(h => /^Step \d/.test(h.innerText || ''));
    out.stepHeading = pick(h2, ['color', 'fontSize', 'fontWeight', 'fontFamily', 'marginTop']);

    // labels + inputs
    out.label = pick(document.querySelector('label'), ['color', 'fontSize', 'fontWeight']);
    const inp = document.querySelector('input[type=text]');
    out.input = pick(inp, ['backgroundColor', 'color', 'border', 'borderRadius', 'height', 'fontSize']);

    // the Get Results button
    const btn = Array.from(document.querySelectorAll('button,a')).find(b => /Get Results/i.test(b.innerText || ''));
    out.primaryButton = pick(btn, ['backgroundColor', 'color', 'borderRadius', 'fontSize', 'fontWeight', 'padding']);

    // link colour
    out.link = pick(document.querySelector('a[href]'), ['color']);

    // any "default:" hint text
    const hint = Array.from(document.querySelectorAll('span,small,div'))
      .find(e => /^default:/i.test((e.innerText || '').trim()));
    out.defaultHint = hint ? { text: hint.innerText.trim().slice(0, 24), ...pick(hint, ['color', 'fontSize']) } : null;

    return out;
  });
  return JSON.stringify(theme, null, 1);
}
