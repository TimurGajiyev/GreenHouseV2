// QA matrix, group P, part C — P-10 обслуживание по счётчику на полном годе.
//
//   browser_run_code_unsafe filename=.playwright/scripts/gh_qa_p_c.js
//
// Год с обслуживанием считается около 145 с на сценарий, поэтому сценарии B и C
// снимаются очисткой имени (пустое имя = строка пропускается при решении) и
// проверяется одно правило A. Предмет кейса — обслуживание, а не сравнение
// правил, так что ничего из проверяемого при этом не теряется.
async (page) => {
  const APP = 'http://localhost:8505/';
  const OUT = [];
  let CASE = 'P-10 Обслуживание по счётчику (8 760 ч)';
  const rec = (name, ok, d) => OUT.push({ c: CASE, name, ok: !!ok, d: d === undefined ? '' : String(d) });
  const N = (s) => {
    if (s === undefined || s === null) return NaN;
    const m = String(s).replace(/[   ₸$%]/g, '').replace('−', '-').match(/-?[\d,]+(\.\d+)?/);
    return m ? parseFloat(m[0].replace(/,/g, '')) : NaN;
  };
  const near = (name, got, want, tol, unit) =>
    rec(name, Math.abs(got - want) <= tol,
      `${got.toLocaleString('en-US', { maximumFractionDigits: 4 })} vs ` +
      `${want.toLocaleString('en-US', { maximumFractionDigits: 4 })}${unit ? ' ' + unit : ''}`);

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

  try {
    await page.goto(APP, { waitUntil: 'load' });
    await page.waitForTimeout(1200);
    await btn('Custom dispatch study (not REopt)').click();
    await page.locator('text=Hourly load').first().waitFor({ timeout: 60000 });
    await idle();
    await setRadio('Free mode: a real year, no file needed');
    await setCheck("Scale the profile to this site's own demand", true);

    // 12 сервисов в год, по 8 часов, полный вывод, ровно по срезам
    await setCell(UNITS, 10, 0, 12);
    await setCell(UNITS, 10, 1, 12);
    const plan = slice(await body(), 'Service plan', 'Battery');
    rec('план обслуживания пересчитан на счётчик',
      /12 × 8 h = 96 h out of 8,760 h/.test(plan),
      plan.match(/Jenbacher: [^\n]*/)?.[0]?.slice(0, 130));
    const av = plan.match(/availability ([\d.]+) %/);
    near('готовность 98.90 %', av ? parseFloat(av[1]) : NaN, 98.90, 0.01, '%');
    rec('интервал пересчитан в моточасы и сопоставлен с нормой OEM',
      /one service every ~\d+ running hours/.test(plan),
      plan.match(/one service every ~[\d,]+ running hours[^\n]*/)?.[0]?.slice(0, 110));
    rec('счётчик честно назван проксѝ',
      plan.includes('A count is a proxy for that interval'));

    // оставляем один сценарий: год с обслуживанием идёт ~145 с на правило
    await setCell(SCEN, 1, 1, '');
    await setCell(SCEN, 1, 2, '');
    await setNum('Time limit per scenario', 600);

    const t0 = Date.now();
    await btn('Solve scenarios').scrollIntoViewIfNeeded();
    await btn('Solve scenarios').click();
    await idle();
    await page.locator('text=Scenario comparison').first().waitFor({ timeout: 1500000 });
    await page.waitForTimeout(1200);
    const secs = (Date.now() - t0) / 1000;

    const C = await page.evaluate(() => {
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
    // Очистка имени сценария через сетку НЕ убирает строку: glide не отдаёт
    // пустую строку обратно в data_editor, и правила B и C остаются. Это
    // ограничение сценария теста, а не продукта; пропуск строки с пустым именем
    // проверяется отдельно в группе N (кейс N-11). Поэтому здесь просто
    // фиксируем, сколько правил реально посчиталось и за сколько.
    rec('сравнение отрисовано', C && C.head.length >= 2,
      C ? C.head.join(' | ') + `, ${secs.toFixed(0)} с на ${C.head.length - 1} сценария` : 'нет таблицы');
    const solver = (C.rows['Solver'] || [])[0] || '';
    rec('доказан с допуском 0.5 %',
      /Optimal/.test(solver) && (N(solver.match(/gap ([\d.]+)/)?.[1] || '0') <= 0.5),
      solver);
    near('нагрузка года на месте', N((C.rows['Load (kWh)'] || [])[0]), 26280000, 1, 'kWh');
    const gen = N((C.rows['Fuel-fired generation (kWh)'] || [])[0]);
    rec('генераторы несут основную часть года', gen > 0.5 * 26280000,
      `${(100 * gen / 26280000).toFixed(1)} % нагрузки`);

    const ut = await page.evaluate(() => {
      const t = [...document.querySelectorAll('table')].find((x) => {
        const h = [...x.querySelectorAll('thead th')].map((th) => th.innerText.trim());
        return h[0] === 'UNIT' && h.includes('RUNNING HOURS');
      });
      if (!t) return null;
      return {
        head: [...t.querySelectorAll('thead th')].map((th) => th.innerText.trim()),
        rows: [...t.querySelectorAll('tbody tr')].map(
          (tr) => [...tr.querySelectorAll('th,td')].map((c) => c.innerText.trim())),
      };
    });
    rec('таблица юнитов отчиталась об обслуживании', !!ut,
      ut ? ut.head.join(' ') : 'таблицы нет');
    if (ut) {
      const sv = ut.head.indexOf('SERVICES');
      const sh = ut.head.indexOf('SERVICE H');
      const avc = ut.head.indexOf('AVAILABILITY');
      const rows = ut.rows.filter((r) => r[0] !== 'Fleet');
      rec('по 12 сервисов у каждого юнита', rows.every((r) => N(r[sv]) === 12),
        rows.map((r) => `${r[0]}: ${r[sv]}`).join('; '));
      rec('по 96 часов простоя у каждого', rows.every((r) => N(r[sh]) === 96),
        rows.map((r) => `${r[0]}: ${r[sh]} ч`).join('; '));
      rec('готовность в таблице совпадает с планом',
        rows.every((r) => Math.abs(N(r[avc]) - 98.90) < 0.01),
        rows.map((r) => `${r[0]}: ${r[avc]}`).join('; '));
      rec('колонки моточасового режима отсутствуют (режим — счётчик)',
        !ut.head.includes('EVERY RUN H'), ut.head.filter((h) => /RUN|BANK/.test(h)).join(' ') || 'нет');
    }
    rec('разбивка пусков по юнитам и дням отрисована',
      (await body()).includes('Starts by unit and day'));
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  const bad = OUT.filter((r) => !r.ok);
  return JSON.stringify({ total: OUT.length, failed: bad.length, report: OUT }, null, 1);
}
