// QA matrix, группа D — известные дефекты отображения (регрессионные ловушки).
//
// D-01 нерешённый сценарий как победитель — ИСПРАВЛЕНО, здесь сторож
// D-02 большой gap подаётся тихо — измеряем последствия
// D-03 флот для проверки сети отстаёт на один rerun — измеряем задержку
//
//   browser_run_code_unsafe filename=.playwright/scripts/gh_qa_d.js
//
// D-02 требует настоящего года: дешёвой конфигурации, надёжно дающей большой
// остаточный gap, не существует -- на коротком окне солвер закрывает всё.
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
  const gapOf = (s) => { const m = String(s).match(/gap ([\d.]+)%/); return m ? parseFloat(m[1]) : NaN; };

  const idle = async (ms = 2400000) => {
    await page.waitForTimeout(350);
    const w = page.locator('[data-testid="stStatusWidget"]');
    try { await w.waitFor({ state: 'attached', timeout: 1500 }); } catch (e) { }
    try { await w.waitFor({ state: 'detached', timeout: ms }); } catch (e) { }
    await page.waitForTimeout(500);
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
  const openYear = async (hours) => {
    await page.goto(APP, { waitUntil: 'load' });
    await page.waitForTimeout(1200);
    await btn('Custom dispatch study (not REopt)').click();
    await page.locator('text=Hourly load').first().waitFor({ timeout: 60000 });
    await idle();
    await setRadio('Free mode: a real year, no file needed');
    await setCheck("Scale the profile to this site's own demand", true);
    if (hours) await setNum('Window length', hours);
  };
  const solveLong = async () => {
    const t0 = Date.now();
    await btn('Solve scenarios').scrollIntoViewIfNeeded();
    await btn('Solve scenarios').click();
    await idle();
    await page.waitForTimeout(1500);
    return (Date.now() - t0) / 1000;
  };

  // ==================================================================== D-01
  // Сторож на исправленный дефект. Было: правило без ответа попадало в таблицу
  // со стоимостью 0 ₸, становилось базой сравнения и давало окупаемость
  // 0.4 года для батареи за 391 млн ₸. Условие воспроизводится дёшево: сеть
  // ограничена, а строка C масштабирует нагрузку в пять раз -- она невыполнима
  // по построению, две другие считаются как обычно.
  CASE = 'D-01 Нерешённый сценарий как победитель (сторож)';
  try {
    await openYear(168);
    await setCheck('The grid connection is limited', true);
    await setNum('Maximum grid import (kW)', 20000);
    await setCell(SCEN, 4, 2, 500);
    await solveLong();
    const t = await body();
    const C = await compare();
    rec('таблица построена по решённым правилам', !!C && C.head.length === 3,
      C ? C.head.join(' | ') : 'таблицы нет');
    const costs = C ? (C.rows['Operating cost'] || []).map(N) : [];
    rec('ни одна стоимость не равна нулю', costs.length > 0 && costs.every((c) => c > 0),
      costs.map((c) => c.toLocaleString() + ' ₸').join(' / '));
    rec('нерешённое правило названо, а не посчитано',
      /Left out of the comparison/.test(t),
      t.match(/Left out of the comparison[^\n]*/)?.[0]?.slice(0, 120) || '(не названо)');
    // Искать надо ИМЯ правила, а не слово «battery»: в сноске раздела стоит
    // «battery CAPEX 391,000,000 ₸», и первая версия проверки краснела на ней,
    // хотя исключённого правила там нет и быть не может -- раздел строится по
    // списку решённых прогонов.
    const econ = slice(t, 'Economics of one scenario', 'Dispatch by period');
    rec('исключённого правила нет в разделе экономики',
      !econ.toLowerCase().includes('90% + battery'),
      econ.match(/COMPARED WITH[^\n]*/)?.[0]?.slice(0, 90) || '');
    rec('нет окупаемости быстрее года — прежний симптом нуля',
      !/0\.[0-9] years/.test(econ) && !/0\.[0-9] \/ 0\.[0-9] yr/.test(t),
      t.match(/[\d.]+ years/)?.[0] || 'сроков окупаемости не найдено');
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== D-02
  // Год со счётчиком сервисов и лимитом 120 с: два правила доказываются до
  // сотых долей процента, а правило с батареей остаётся на тривиальном
  // инкумбенте с разрывом под 47 %. Вопрос кейса: узнает ли об этом читатель,
  // или число из недосчитанного правила молча встанет рядом с доказанными.
  CASE = 'D-02 Большой gap подаётся тихо';
  try {
    await openYear(null);
    await setCell(UNITS, 10, 0, 12);
    await setCell(UNITS, 10, 1, 12);
    await setNum('Time limit per scenario', 120);
    await setNum('Optimality gap', 0.5);
    const secs = await solveLong();
    const t = await body();
    const C = await compare();
    rec('страница дождалась ответа', !!C, `${secs.toFixed(0)} с`);
    if (C) {
      const names = C.head.slice(1);
      const solver = C.rows['Solver'] || [];
      const gaps = solver.map(gapOf);
      const cost = (C.rows['Operating cost'] || []).map(N);
      const wide = names.filter((_, i) => gaps[i] > 5);
      rec('НАБЛЮДЕНИЕ: разрывы в одной таблице несопоставимы',
        true, names.map((n, i) => `${n.slice(0, 1)} ${gaps[i]}%`).join(' | '));
      rec('есть правило с разрывом больше 5 %', wide.length > 0,
        wide.join(', ') || 'нет');
      if (wide.length) {
        // вот цена молчания: разница, которую покажет экономика
        const worst = names.indexOf(wide[0]);
        const best = gaps.indexOf(Math.min(...gaps));
        rec('НАБЛЮДЕНИЕ: во что это обходится при сравнении',
          true,
          `${names[worst].slice(0, 1)} против ${names[best].slice(0, 1)}: ` +
          `${(cost[worst] - cost[best]).toLocaleString()} ₸ разницы, из них до ` +
          `${(cost[worst] * gaps[worst] / 100).toLocaleString()} ₸ — недосчёт`);
        const above = slice(t, 'Scenario comparison', 'Economics of one');
        rec('страница называет недосчитанные правила над таблицей',
          /Not proved, and so not comparable/.test(above),
          above.match(/Not proved[^\n]*/)?.[0]?.slice(0, 150) || 'над таблицей о разрыве ничего нет');
        rec('назван разрыв каждого недосчитанного правила',
          (above.match(/stopped at a gap of [\d.]+ %/g) || []).length === wide.length,
          (above.match(/stopped at a gap of [\d.]+ %/g) || []).join(', '));
        rec('сказано, что запрошенный допуск не выдержан',
          /against the [\d.]+ % that was asked for/.test(above),
          above.match(/against the [\d.]+ % that was asked for/)?.[0] || '');
        rec('сказано, что экономия и окупаемость по ним ненадёжны',
          /savings, net present values and paybacks/.test(above) && /upper bounds/.test(above));
      }
    }
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== D-03
  // Панель Site рисуется ВЫШЕ таблицы юнитов, поэтому о правке мощности она
  // узнаёт только на следующем перерисовывании. Кейс измеряет задержку: сразу
  // после правки сумма старая, после любого следующего действия -- верная.
  CASE = 'D-03 Флот для проверки сети отстаёт на один rerun';
  try {
    await openYear(168);
    await setCheck('The grid connection is limited', true);
    await setNum('Maximum grid import (kW)', 100);
    const before = slice(await body(), 'Site demand', 'Grid price');
    rec('до правки сумма флота верная', /the fleet is rated 2,267 kW/.test(before),
      before.match(/the fleet is rated [\d,]+ kW/)?.[0] || '');
    await setCell(UNITS, 2, 0, 1500);          // Jenbacher 1067 -> 1500
    const right_after = slice(await body(), 'Site demand', 'Grid price');
    const stale = /the fleet is rated 2,267 kW/.test(right_after);
    rec('НАБЛЮДЕНИЕ: сразу после правки сумма ещё старая', true,
      right_after.match(/the fleet is rated [\d,]+ kW/)?.[0] + (stale ? ' (отстала)' : ' (уже верная)'));
    await setNum('Maximum grid import (kW)', 120);   // любое следующее действие
    const after = slice(await body(), 'Site demand', 'Grid price');
    rec('после следующего действия сумма догоняет правку',
      /the fleet is rated 2,700 kW/.test(after),
      after.match(/the fleet is rated [\d,]+ kW/)?.[0] || '');
    rec('задержка ровно в одно перерисовывание, а не навсегда',
      !/the fleet is rated 2,267 kW/.test(after));
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  const bad = OUT.filter((r) => !r.ok);
  return JSON.stringify({ total: OUT.length, failed: bad.length, report: OUT }, null, 1);
}
