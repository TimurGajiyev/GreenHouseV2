// QA matrix, группа S, длинная часть B — S-03 и S-04 на полном годе.
//
// S-03 счётчик сервисов + лимит 600 с — ожидается, что сойдутся все три и
//      порядок правил станет осмысленным
// S-04 три машины + батарея, без обслуживания, лимит 600 с — проба на
//      трактуемость: достаточно ли лимита, когда флот больше
//
//   browser_run_code_unsafe filename=.playwright/scripts/gh_qa_s_long_b.js
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
    await page.waitForTimeout(600);
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
  const setSelect = async (ariaPrefix, option) => {
    const box = page.locator(`input[type=text][aria-label^="${ariaPrefix}"]`).first();
    await box.scrollIntoViewIfNeeded();
    await box.click();
    await page.waitForTimeout(500);
    await page.locator('li[role="option"], [role="option"]').filter({ hasText: option }).first().click();
    await idle();
  };

  const UNITS = 0;
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
  const openYear = async () => {
    await page.goto(APP, { waitUntil: 'load' });
    await page.waitForTimeout(1200);
    await btn('Custom dispatch study (not REopt)').click();
    await page.locator('text=Hourly load').first().waitFor({ timeout: 60000 });
    await idle();
    await setRadio('Free mode: a real year, no file needed');
    await setCheck("Scale the profile to this site's own demand", true);
  };
  const solveLong = async () => {
    const t0 = Date.now();
    await btn('Solve scenarios').scrollIntoViewIfNeeded();
    await btn('Solve scenarios').click();
    await idle();
    await page.waitForTimeout(2000);
    return (Date.now() - t0) / 1000;
  };

  // ==================================================================== S-03
  // Тот же год и тот же счётчик сервисов, что в S-02, но лимит поднят до 600 с.
  // Предмет проверки -- что при достаточном лимите порядок правил становится
  // тем, которого требует их устройство: B не дешевле A, потому что правило
  // 90 % строже, и C не дороже B, потому что батарею можно не трогать.
  CASE = 'S-03 Счётчик сервисов на годе, лимит 600 с';
  try {
    await openYear();
    await setCell(UNITS, 10, 0, 12);
    await setCell(UNITS, 10, 1, 12);
    await setNum('Time limit per scenario', 600);
    await setNum('Optimality gap', 0.5);
    const secs = await solveLong();
    const t = await body();
    const C = await compare();
    rec('страница дождалась ответа', !!C, `${secs.toFixed(0)} с на три сценария`);
    if (C) {
      const solver = C.rows['Solver'] || [];
      const gaps = solver.map(gapOf);
      const cost = (C.rows['Operating cost'] || []).map(N);
      const load = N((C.rows['Load (kWh)'] || [])[0]);
      const gen = (C.rows['Fuel-fired generation (kWh)'] || []).map(N);
      rec('все три правила в таблице', C.head.length === 4, C.head.join(' | '));
      rec('все три уложились в допуск 0.5 %', gaps.every((g) => g <= 0.5),
        solver.join(' | '));
      rec('ни одна колонка не стоит 0 ₸', cost.every((c) => c > 0),
        cost.map((c) => c.toLocaleString() + ' ₸').join(' / '));
      rec('машины несут большую часть года во всех трёх',
        gen.every((g) => g > 0.5 * load),
        gen.map((g) => (100 * g / load).toFixed(1) + ' %').join(' / ') + ' нагрузки');
      rec('B не дешевле A: правило 90 % строже', cost[1] >= cost[0] - 1,
        `A ${cost[0].toLocaleString()} → B ${cost[1].toLocaleString()} ₸`);
      rec('C не дороже B: батарею можно не трогать', cost[2] <= cost[1] + 1,
        `B ${cost[1].toLocaleString()} → C ${cost[2].toLocaleString()} ₸`);
      rec('и батарея действительно что-то зарабатывает', cost[2] < cost[1] - 1,
        `экономия ${(cost[1] - cost[2]).toLocaleString()} ₸ в год`);
      const chg = (C.rows['Battery charged (kWh)'] || []).map(N);
      rec('работает батарея только там, где она включена',
        chg[0] === 0 && chg[1] === 0 && chg[2] > 0,
        `заряд ${chg.map((c) => c.toLocaleString()).join(' / ')} kWh`);
      // окупаемость считается по настоящим числам, а не по нулю
      const econ = slice(t, 'Economics of one scenario', 'Dispatch by period');
      rec('раздел экономики построен и называет срок окупаемости',
        /years|never|saves the CAPEX/.test(econ),
        econ.match(/PAYBACK[\s\S]{0,120}/)?.[0]?.replace(/\n/g, ' ').slice(0, 120) || '');
    }
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== S-04
  // Три машины и батарея, обслуживания нет: проба на то, хватает ли лимита,
  // когда флот вырастает. Кейс НЕ предписывает исход -- он предписывает, чтобы
  // страница повела себя честно при любом исходе: либо правило в таблице с
  // указанным gap, либо названо как нерешённое, и ни при каких условиях -- ноль.
  CASE = 'S-04 Три машины и батарея на годе, лимит 600 с';
  try {
    await openYear();
    await setSelect('Start from', '3 units');
    await setNum('Time limit per scenario', 600);
    await setNum('Optimality gap', 0.5);
    // Название пресета лежит в ЗНАЧЕНИИ поля, а не в тексте страницы, а имена
    // машин нарисованы на канвасе таблицы -- ни того, ни другого нет в
    // innerText. Первая версия проверки искала их там и краснела, хотя пресет
    // переключался: это подтверждала соседняя проверка разбора по юнитам,
    // вернувшая «Jenbacher, TEDOM, КГУ-3».
    const preset = await page.locator('input[type=text][aria-label^="Start from"]')
      .first().inputValue();
    rec('пресет сменился на три машины', /3 units/.test(preset), preset);
    const secs = await solveLong();
    const t = await body();
    const C = await compare();
    rec('страница дождалась ответа', !!C || /not one rule was solved/.test(t),
      `${secs.toFixed(0)} с`);
    const named = /Left out of the comparison/.test(t) || /not one rule was solved/.test(t);
    const shown = C ? C.head.length - 1 : 0;
    rec('каждое правило либо в таблице, либо названо как нерешённое',
      shown === 3 || named, `в таблице ${shown}, ` + (named ? 'остальные названы' : 'названных нет'));
    if (C) {
      const solver = C.rows['Solver'] || [];
      const cost = (C.rows['Operating cost'] || []).map(N);
      const load = N((C.rows['Load (kWh)'] || [])[0]);
      const gen = (C.rows['Fuel-fired generation (kWh)'] || []).map(N);
      rec('ни одна колонка не стоит 0 ₸', cost.every((c) => c > 0),
        cost.map((c) => c.toLocaleString() + ' ₸').join(' / '));
      rec('НАБЛЮДЕНИЕ: чего добился солвер за 600 с', true, solver.join(' | '));
      rec('НАБЛЮДЕНИЕ: доля флота в годовой нагрузке', true,
        gen.map((g) => (100 * g / load).toFixed(1) + ' %').join(' / '));
      // порядок проверяем только среди тех правил, что действительно сошлись
      const gaps = solver.map(gapOf);
      const ok = (i) => gaps[i] <= 0.5;
      if (ok(0) && ok(1)) {
        rec('B не дешевле A среди сошедшихся', cost[1] >= cost[0] - 1,
          `A ${cost[0].toLocaleString()} → B ${cost[1].toLocaleString()} ₸`);
      }
      if (ok(1) && ok(2)) {
        rec('C не дороже B среди сошедшихся', cost[2] <= cost[1] + 1,
          `B ${cost[1].toLocaleString()} → C ${cost[2].toLocaleString()} ₸`);
      }
      const ut = await page.evaluate(() => {
        const x = [...document.querySelectorAll('table')].find((y) => {
          const h = [...y.querySelectorAll('thead th')].map((th) => th.innerText.trim());
          return h[0] === 'UNIT' && h.includes('RUNNING HOURS');
        });
        if (!x) return null;
        return [...x.querySelectorAll('tbody tr')].map(
          (tr) => [...tr.querySelectorAll('th,td')].map((c) => c.innerText.trim()));
      });
      rec('в разборе по юнитам три машины, а не две',
        !!ut && ut.filter((r) => r[0] !== 'Fleet').length === 3,
        ut ? ut.map((r) => r[0]).join(', ') : 'таблицы нет');
    }
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  const bad = OUT.filter((r) => !r.ok);
  return JSON.stringify({ total: OUT.length, failed: bad.length, report: OUT }, null, 1);
}
