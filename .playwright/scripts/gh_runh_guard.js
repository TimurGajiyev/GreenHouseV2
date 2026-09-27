// Сторож на тихий локаут: интервал сервиса короче минимального времени работы.
//
// Измерено в ядре: Service every (run h) = 1 при Min up h = 4 даёт 0 моточасов,
// Optimal, gap 0.00 % и 100 % нагрузки из сети. Страница об этом молчала.
//
//   browser_run_code_unsafe filename=.playwright/scripts/gh_runh_guard.js
async (page) => {
  const APP = 'http://localhost:8505/';
  const OUT = [];
  const rec = (name, ok, d) => OUT.push({ name, ok: !!ok, d: d === undefined ? '' : String(d) });

  const idle = async (ms = 600000) => {
    await page.waitForTimeout(350);
    const w = page.locator('[data-testid="stStatusWidget"]');
    try { await w.waitFor({ state: 'attached', timeout: 1500 }); } catch (e) { }
    try { await w.waitFor({ state: 'detached', timeout: ms }); } catch (e) { }
    await page.waitForTimeout(500);
  };
  const body = async () => (await page.evaluate(() => document.body.innerText)).replace(/[  ]/g, ' ');
  const btn = (name) => page.locator('button').filter({ hasText: name }).first();

  const canvasOf = (gi) => page.locator('[data-testid="stDataFrame"]').nth(gi).locator('canvas').first();
  const selectedCell = (gi) => page.evaluate((gi) => {
    const g = [...document.querySelectorAll('[data-testid="stDataFrame"]')][gi];
    const c = g && g.querySelector('[data-testid^="glide-cell-"][aria-selected="true"]');
    return c ? c.getAttribute('data-testid').replace('glide-cell-', '') : null;
  }, gi);
  const selectCell = async (gi, col, row) => {
    const cv = canvasOf(gi);
    let at = null;
    const click = async () => {
      await cv.evaluate((el) => el.scrollIntoView({ block: 'center' }));
      await page.waitForTimeout(400);
      await page.mouse.move(5, 5);
      await page.waitForTimeout(150);
      const box = await cv.boundingBox();
      await page.mouse.move(box.x + 60, box.y + 52);
      await page.waitForTimeout(120);
      await page.mouse.down();
      await page.waitForTimeout(90);
      await page.mouse.up();
      await page.waitForTimeout(350);
      return await selectedCell(gi);
    };
    for (let t = 0; t < 4 && !at; t++) at = await click();
    if (!at) throw new Error('таблица не приняла клик');
    const step = async (key) => {
      const from = at;
      await cv.press(key);
      for (let i = 0; i < 25; i++) {
        await page.waitForTimeout(100);
        const now = await selectedCell(gi);
        if (now && now !== from) { at = now; return true; }
      }
      return false;
    };
    let stalls = 0;
    for (let n = 0; n < 80; n++) {
      const [c, r] = at.split('-').map(Number);
      if (c === col && r === row) return;
      const moved = await step(c < col ? 'ArrowRight' : c > col ? 'ArrowLeft'
        : r < row ? 'ArrowDown' : 'ArrowUp');
      if (!moved && ++stalls % 2 === 0) at = (await click()) || at;
    }
    throw new Error(`выделение застряло на ${at}, нужно ${col}-${row}`);
  };
  const setCell = async (gi, col, row, v) => {
    await selectCell(gi, col, row);
    await canvasOf(gi).press('Enter');
    const ov = page.locator('[data-testid="portal"] input, [data-testid="portal"] textarea').first();
    await ov.waitFor({ timeout: 6000 });
    await ov.fill(String(v));
    await page.keyboard.press('Enter');
    await idle();
  };

  const UNITS = 0, C_MINT = 14;

  await page.goto(APP, { waitUntil: 'load' });
  await page.waitForTimeout(1200);
  await btn('Custom dispatch study (not REopt)').click();
  await page.locator('text=Hourly load').first().waitFor({ timeout: 60000 });
  await idle();

  // ---- 1. интервал 1 моточас при минимальной работе 4 ч -------------------
  await setCell(UNITS, C_MINT, 0, 1);
  await setCell(UNITS, C_MINT, 1, 1);
  let t = await body();
  const warn = (t.match(/This fleet cannot start[\s\S]{0,700}/) || [''])[0];
  rec('1 моточас: предупреждение показано', /This fleet cannot start/.test(t),
    warn.slice(0, 220));
  rec('назван Jenbacher', /Jenbacher[\s\S]{0,200}shortest run/.test(warn), '');
  rec('названа минимальная работа 4 h', /\*\*4 h\*\*|shortest run the unit is allowed is 4 h/.test(warn.replace(/\*/g, '')) || /allowed is 4 h/.test(warn), '');
  rec('назван интервал 1', /falls due after 1\b/.test(warn.replace(/\*/g, '')), '');
  rec('сказано, что решение будет Optimal', /report .?Optimal/.test(warn), '');
  rec('названа TEDOM тоже', (warn.match(/shortest run/g) || []).length >= 2,
    (warn.match(/shortest run/g) || []).length + ' строки');

  // ---- 2. то же с живым прогоном: флот действительно тёмный --------------
  await page.locator('input[type=number][aria-label^="Window length"]').first()
    .fill('168');
  await page.keyboard.press('Enter');
  await idle();
  await btn('Solve scenarios').scrollIntoViewIfNeeded();
  await btn('Solve scenarios').click();
  await idle();
  await page.waitForTimeout(1500);
  t = await body();
  const share = (t.match(/Grid share of load \(%\)\s*([\d.]+)/) || [])[1];
  const hrs = (t.match(/Fleet running hours\s*([\d,]+)/) || [])[1];
  rec('прогон: сеть берёт всю нагрузку', share === '100.0', 'доля сети ' + share + ' %');
  rec('прогон: флот не работал', hrs === '0', 'моточасов ' + hrs);
  rec('прогон: солвер доволен', /Optimal, gap 0\.00%/.test(t), '');
  rec('предупреждение осталось после прогона', /This fleet cannot start/.test(t), '');

  // ---- 3. заводской интервал — предупреждения нет ------------------------
  await setCell(UNITS, C_MINT, 0, 1500);
  await setCell(UNITS, C_MINT, 1, 1500);
  t = await body();
  rec('1 500 моточасов: предупреждения нет', !/This fleet cannot start/.test(t), '');
  rec('план обслуживания всё ещё описан', /Service plan/.test(t), '');

  // ---- 4. граница: интервал равен минимальной работе ---------------------
  await setCell(UNITS, C_MINT, 0, 4);
  await setCell(UNITS, C_MINT, 1, 4);
  t = await body();
  rec('интервал 4 = min up 4: предупреждения нет', !/This fleet cannot start/.test(t), '');
  await setCell(UNITS, C_MINT, 0, 3);
  t = await body();
  rec('интервал 3 < min up 4: предупреждение есть', /This fleet cannot start/.test(t),
    (t.match(/This fleet cannot start[\s\S]{0,160}/) || [''])[0].slice(0, 160));
  rec('названа только одна машина', (t.match(/shortest run/g) || []).length === 1,
    (t.match(/shortest run/g) || []).length + ' строка');

  const bad = OUT.filter((o) => !o.ok);
  return JSON.stringify({ total: OUT.length, failed: bad.length, report: OUT }, null, 1);
}
