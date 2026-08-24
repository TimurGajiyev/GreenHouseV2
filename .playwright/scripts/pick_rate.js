// Select the Phoenix TOU rate through the real dropdown and read back the
// urdb_label the form will submit, so both calculators use the same tariff.
async (page) => {
  const dd = page.locator('#dropdown-input');
  await dd.scrollIntoViewIfNeeded();
  await dd.click();
  await dd.fill('');
  await dd.type('Large General Service TOU', { delay: 40 });
  await page.waitForTimeout(2800);
  const items = page.locator('.dropdown-item');
  const n = await items.count();
  const texts = [];
  for (let i = 0; i < n; i++) texts.push((await items.nth(i).innerText()).replace(/\s+/g, ' ').trim());
  let chosen = null;
  for (let i = 0; i < n; i++) {
    if (/Large General Service TOU \(E-32 L\) Secondary/i.test(texts[i])) {
      await items.nth(i).click();
      chosen = texts[i];
      break;
    }
  }
  await page.waitForTimeout(3000);
  return JSON.stringify({ n, texts, chosen, urdbLabel: await dd.inputValue() }, null, 1);
}
