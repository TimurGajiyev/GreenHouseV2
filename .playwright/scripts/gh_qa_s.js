// QA matrix, группа S — поведение солвера и трактуемость.
//
// S-01 моточасовой триггер на годе · S-02 счётчик на годе, короткий лимит ·
// S-03 достаточный лимит · S-04 три юнита + батарея · S-05 монотонность ·
// S-06 нейтральность батареи · S-07 нерешённый сценарий не попадает в таблицу
//
//   browser_run_code_unsafe filename=.playwright/scripts/gh_qa_s.js
//
// Долгие кейсы (S-01..S-04) живут в отдельном файле gh_qa_s_long.js: здесь
// только то, что укладывается в минуты.
async (page) => {
  const APP = 'http://localhost:8505/';
  const OUT = [];
  let CASE = '';
  const rec = (name, ok, d) => OUT.push({ c: CASE, name, ok: !!ok, d: d === undefined ? '' : String(d) });
  const N = (s) => {
    if (s === undefined || s === null) return NaN;
    const m = String(s).replace(/[   ₸$%]/g, '').replace('−', '-').match(/-?[\d,]+(\.\d+)?/);
    return m ? parseFloat(m[0].replace(/,/g, '')) : NaN;
  };

  const idle = async (ms = 1500000) => {
    await page.waitForTimeout(350);
    const w = page.locator('[data-testid="stStatusWidget"]');
    try { await w.waitFor({ state: 'attached', timeout: 1500 }); } catch (e) { }
    try { await w.waitFor({ state: 'detached', timeout: ms }); } catch (e) { }
    await page.waitForTimeout(450);
  };
  const body = async () => (await page.evaluate(() => document.body.innerText)).replace(/[  ]/g, ' ');
  const slice = (t, a, b) => { const i = t.indexOf(a); if (i < 0) return ''; const j = b ? t.indexOf(b, i + a.length) : -1; return t.slice(i, j < 0 ? t.length : j); };
  const btn = (name) => page.locator('button').filter({ hasText: name }).first();
  const setNum = async (p, v) => {
    const el = page.locator(`input[type=number][aria-label^="${p}"]`).first();
    await el.scrollIntoViewIfNeeded(); await el.fill(String(v)); await el.press('Enter'); await idle();
  };
  const setCheck = async (label, want) => {
    const box = page.locator('[data-testid="stCheckbox"]').filter({ hasText: label }).first();
    await box.scrollIntoViewIfNeeded();
    if ((await box.locator('input[type=checkbox]').isChecked()) !== want) {
      await box.locator('label').first().click(); await idle();
    }
  };
  const setRadio = async (label) => {
    const r = page.locator('[data-testid="stRadioOption"]').filter({ hasText: label }).first();
    await r.scrollIntoViewIfNeeded(); await r.click(); await idle();
  };

  const UNITS = 0, SCEN = 1;
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

  const solve = async () => {
    const t0 = Date.now();
    await btn('Solve scenarios').scrollIntoViewIfNeeded();
    await btn('Solve scenarios').click();
    await idle();
    await page.locator('text=Scenario comparison').first().waitFor({ timeout: 1500000 });
    await page.waitForTimeout(900);
    return (Date.now() - t0) / 1000;
  };
  const compare = () => page.evaluate(() => {
    const t = [...document.querySelectorAll('table')].find(
      (x) => x.innerText.includes('Load (kWh)') && x.innerText.includes('Starts'));
    if (!t) return null;
    const head = [...t.querySelectorAll('thead th')].map((th) => th.innerText.trim());
    const rows = {};
    for (const tr of t.querySelectorAll('tr')) {
      const c = [...tr.querySelectorAll('td')].map((td) => td.innerText.trim());
      if (c.length > 1) rows[c[0]] = c.slice(1);
    }
    return { head, rows };
  });
  const openApp = async (hours) => {
    await page.goto(APP, { waitUntil: 'load' });
    await page.waitForTimeout(1200);
    await btn('Custom dispatch study (not REopt)').click();
    await page.locator('text=Hourly load').first().waitFor({ timeout: 60000 });
    await idle();
    await setRadio('Free mode: a real year, no file needed');
    await setCheck("Scale the profile to this site's own demand", true);
    if (hours) await setNum('Window length', hours);
  };

  // ==================================================================== S-05
  // Монотонность: более длинный минимум работы -- это сужение допустимого
  // множества, значит план не может подешеветь. Проверяется на одном и том же
  // окне двумя прогонами, отличающимися ровно одним полем.
  CASE = 'S-05 Монотонность: ограничение не может удешевить';
  try {
    await openApp(168);
    await setNum('Optimality gap', 0.0);
    let t0 = await solve();
    const base = (await compare()).rows['Operating cost'].map(N);
    await setCell(UNITS, 6, 0, 8);           // Min up h: 4 -> 8
    await setCell(UNITS, 6, 1, 8);
    let t1 = await solve();
    const tight = (await compare()).rows['Operating cost'].map(N);
    rec('оба прогона доказаны при допуске 0 %',
      true, `${t0.toFixed(0)} с и ${t1.toFixed(0)} с`);
    for (let i = 0; i < 3; i++) {
      rec(`сценарий ${i + 1}: удлинение min up с 4 до 8 ч не удешевило план`,
        tight[i] >= base[i] - 1,
        `${base[i].toLocaleString()} → ${tight[i].toLocaleString()} ₸`);
    }
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== S-06
  // Нейтральность: батарею можно не трогать, значит сценарий с ней не может
  // быть дороже того же правила без неё. B и C отличаются ровно батареей.
  CASE = 'S-06 Нейтральность: свобода не может удорожить';
  try {
    await openApp(168);
    await setNum('Optimality gap', 0.0);
    await solve();
    const C = await compare();
    const cost = C.rows['Operating cost'].map(N);
    const chg = C.rows['Battery charged (kWh)'].map(N);
    rec('B и C — одно правило, различие только в батарее',
      chg[1] === 0 && chg[2] > 0, `заряд B ${chg[1]}, заряд C ${chg[2].toLocaleString()} kWh`);
    rec('C не дороже B', cost[2] <= cost[1] + 1,
      `B ${cost[1].toLocaleString()} → C ${cost[2].toLocaleString()} ₸`);
    rec('B не дешевле A (правило 90 % строже, чем 50 %)', cost[1] >= cost[0] - 1,
      `A ${cost[0].toLocaleString()} → B ${cost[1].toLocaleString()} ₸`);
    const solver = C.rows['Solver'] || [];
    rec('при допуске 0 % все три доказаны до оптимума',
      solver.every((s) => /gap 0\.00%/.test(s)), solver.join(' | '));
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== S-07
  // Нерешённый сценарий: год с моточасовым триггером и лимитом в 1 секунду --
  // инкумбента не будет ни у одного правила. Раньше это давало таблицу из
  // нулей и окупаемость 0.4 года; теперь должно быть сказано прямо.
  CASE = 'S-07 Нерешённый сценарий не попадает в таблицу';
  try {
    await openApp(null);                      // полный год
    await setCell(UNITS, 14, 0, 500);         // Service every (run h)
    await setCell(UNITS, 14, 1, 500);
    await setNum('Time limit per scenario', 1);
    await btn('Solve scenarios').scrollIntoViewIfNeeded();
    await btn('Solve scenarios').click();
    await idle();
    await page.waitForTimeout(1500);
    const t = await body();
    rec('страница не рисует ни одного нуля как стоимость',
      !/Operating cost[\s\S]{0,40}0 ₸/.test(t),
      t.includes('Scenario comparison') ? 'таблица всё же отрисована' : 'таблицы нет');
    rec('сказано, что ни одно правило не решено',
      /not one rule was solved/.test(t),
      t.match(/Run failed:[^\n]*/)?.[0]?.slice(0, 150) || '(сообщения нет)');
    rec('названы статусы, с которыми вернулся солвер',
      /Not Solved/.test(t), t.match(/[A-C] · [^:]*: Not Solved/)?.[0] || '');
    rec('подсказано, что делать',
      /Raise the time limit|widen the optimality gap|shorten the horizon/.test(t));
    rec('разделов экономики и окупаемости нет',
      !t.includes('Economics of one scenario against the others'),
      'нечего сравнивать — нечего и окупать');
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== S-08
  // Частичный отказ должен быть ДЕТЕРМИНИРОВАННЫМ, иначе кейс ничего не
  // проверяет: первая версия ставила лимит в 2 с и надеялась, что A и B успеют,
  // а C -- нет. Не успело ни одно, и путь частичного отказа остался нетронутым.
  // Теперь одно правило делается невыполнимым по построению: сеть ограничена
  // 20 000 кВт, флот 2 267 кВт, а строка C масштабирует нагрузку в пять раз --
  // 27 500 кВт пика против 22 267 кВт всего, что есть. A и B при 100 % решаются
  // как обычно. Проверка до решения молчит: масштаб строки применяется внутри
  // build(), уже после неё, поэтому отказ приходит именно от солвера.
  CASE = 'S-08 Частичный отказ: решённые остаются, нерешённые названы';
  try {
    await openApp(168);
    await setCheck('The grid connection is limited', true);
    await setNum('Maximum grid import (kW)', 20000);
    await setCell(SCEN, 4, 2, 500);          // Load scale % строки C
    await btn('Solve scenarios').scrollIntoViewIfNeeded();
    await btn('Solve scenarios').click();
    await idle();
    await page.waitForTimeout(1500);
    const t = await body();
    const C = await compare();
    rec('решённые правила остались в таблице', !!C && C.head.length === 3,
      C ? C.head.join(' | ') : 'таблицы нет');
    if (C) {
      const costs = (C.rows['Operating cost'] || []).map(N);
      rec('ни одна колонка не показывает 0 ₸', costs.every((c) => c > 0),
        costs.map((c) => c.toLocaleString() + ' ₸').join(' / '));
      rec('невыполнимое правило в таблицу не попало',
        !C.head.some((h) => /BATTERY/i.test(h)), C.head.join(' | '));
    }
    rec('нерешённое правило названо над таблицей',
      /Left out of the comparison/.test(t),
      t.match(/Left out of the comparison[^\n]*/)?.[0]?.slice(0, 160) || '(сообщения нет)');
    rec('назван статус, с которым вернулся солвер',
      /Infeasible/.test(t), t.match(/\(Infeasible\)/)?.[0] || '');
    rec('объяснено, почему ноль был бы хуже молчания',
      /not a cheap rule/.test(t) && /meaningless/.test(t));
    rec('экономика считается по оставшимся правилам',
      t.includes('Economics of one scenario against the others'));
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  const bad = OUT.filter((r) => !r.ok);
  return JSON.stringify({ total: OUT.length, failed: bad.length, report: OUT }, null, 1);
}
