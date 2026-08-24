async (page) => {
  const SHOTS = 'D:/GreenHouseV2/reopt_test_screenshots';
  const log = [];

  if (!page.__dlg) {
    page.__dlg = [];
    page.on('dialog', async d => { page.__dlg.push(d.message()); try { await d.accept(); } catch (e) {} });
    log.push('dialog auto-accept installed');
  }

  const rateState = async () => page.evaluate(() => {
    const d = document.getElementById('dropdown-input');
    const list = document.querySelectorAll('#dropdown-list li, .dropdown-list li, [id*=dropdown] li');
    return { disabled: d ? d.disabled : null, placeholder: d ? d.placeholder : null,
             value: d ? d.value : null, options: list.length };
  });
  log.push('before: ' + JSON.stringify(await rateState()));

  // Re-trigger the utility-rate fetch by re-selecting the address
  const addr = page.locator('#run_site_attributes_address');
  for (let attempt = 1; attempt <= 3; attempt++) {
    const before = (page.__cap || []).length;
    await addr.click();
    await addr.fill('');
    await addr.type('1617 Cole Blvd, Golden, CO 80401', { delay: 40 });
    await page.waitForTimeout(2200);
    const pac = page.locator('.pac-container .pac-item');
    if (await pac.count()) { await pac.first().click(); } else { await addr.press('ArrowDown'); await addr.press('Enter'); }
    await page.waitForTimeout(6000);
    const st = await rateState();
    log.push('attempt ' + attempt + ': ' + JSON.stringify(st) + '  dialogs=' + JSON.stringify(page.__dlg.slice(-1)));
    if (!st.disabled && st.options > 0) { log.push('RATES LOADED on attempt ' + attempt); break; }
  }

  await page.screenshot({ path: SHOTS + '/04-location-and-rates.png', scale: 'css' });

  // what did the utility-rates call return this time?
  const ur = (page.__cap || []).filter(c => /utility-rates/.test(c.url));
  return log.join('\n') + '\n---\nutility-rates events: ' + JSON.stringify(ur.slice(-4), null, 1);
}
