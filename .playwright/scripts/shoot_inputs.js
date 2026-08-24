// Screenshot the Inputs and Defaults drawers so the labels can be eyeballed.
async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots/theme';
  const log = [];
  const shootDrawer = async (name, file) => {
    const summ = page.locator('[data-testid="stExpander"] summary')
      .filter({ hasText: name }).first();
    if (!(await summ.count())) { log.push('no drawer: ' + name); return; }
    const det = summ.locator('xpath=ancestor::details[1]');
    await summ.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    await det.screenshot({ path: SHOTS + '/' + file });
    log.push('shot ' + file);
  };
  await shootDrawer('Inputs', '08-inputs.png');
  await shootDrawer('Defaults', '09-defaults.png');

  // dump the Inputs rows as text so the labels are verifiable, not just visual
  const rows = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('[data-testid="stExpander"] details').forEach((d) => {
      const t = (d.querySelector('summary') || {}).innerText || '';
      if (!/Inputs|Defaults/.test(t)) return;
      d.querySelectorAll('[role="gridcell"], [role="rowheader"]').forEach((c) => {
        const s = (c.textContent || '').trim();
        if (s) out.push(s);
      });
    });
    return out.slice(0, 80);
  });
  log.push('cells: ' + JSON.stringify(rows.slice(0, 40)));
  return log.join('\n');
}
