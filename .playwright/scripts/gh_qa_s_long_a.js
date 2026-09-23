// QA matrix, группа S, длинная часть A — S-01 и S-02 на полном годе.
//
// S-01 моточасовой триггер + лимит 120 с — ожидается, что не сойдётся
// S-02 счётчик сервисов + лимит 120 с — ожидается, что A и B сойдутся, а C нет
//
//   browser_run_code_unsafe filename=.playwright/scripts/gh_qa_s_long_a.js
//
// Каждый кейс — три сценария по 8 760 часов, то есть около 7 минут на кейс.
// Ничего не ускоряем: предмет проверки в том, что страница делает с ответом,
// который солвер не успел довести, а это видно только на настоящем годе.
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
  // Общие для обоих кейсов проверки честности вывода.
  const honest = (C, t) => {
    if (C) {
      const costs = (C.rows['Operating cost'] || []).map(N);
      rec('ни одна колонка не стоит 0 ₸', costs.every((c) => c > 0),
        costs.map((c) => c.toLocaleString() + ' ₸').join(' / '));
    }
    const named = /Left out of the comparison/.test(t) || /not one rule was solved/.test(t);
    const all = C ? C.head.length - 1 : 0;
    rec('каждое правило либо в таблице, либо названо как нерешённое',
      all === 3 || named,
      `в таблице ${all}, ` + (named ? 'остальные названы' : 'названных нет'));
  };

  // ==================================================================== S-01
  // Моточасовой триггер на годе: 17 520 бинарей коммитмента плюс столько же
  // бинарей «здесь начинается сервис» плюс счётчик наработки с большим M,
  // который связывает каждый час со всеми предыдущими. За 120 с это не
  // закрывается -- ожидаем большой остаточный gap и план, в котором машины
  // почти не работают, хотя газ вдвое дешевле сети.
  CASE = 'S-01 Моточасовой триггер на годе, лимит 120 с';
  try {
    await openYear();
    await setCell(UNITS, 14, 0, 500);
    await setCell(UNITS, 14, 1, 500);
    await setNum('Time limit per scenario', 120);
    await setNum('Optimality gap', 0.5);
    const secs = await solveLong();
    const t = await body();
    const C = await compare();
    rec('страница дождалась ответа', !!C || /not one rule was solved/.test(t),
      `${secs.toFixed(0)} с`);
    honest(C, t);
    if (C) {
      const solver = C.rows['Solver'] || [];
      const gaps = solver.map(gapOf);
      rec('НАБЛЮДЕНИЕ: за 120 с год с моточасовым триггером не сходится',
        gaps.some((g) => g > 5), solver.join(' | '));
      const load = N((C.rows['Load (kWh)'] || [])[0]);
      const gen = (C.rows['Fuel-fired generation (kWh)'] || []).map(N);
      rec('НАБЛЮДЕНИЕ: в недосчитанном плане машины почти не работают',
        gen.every((g) => g < 0.05 * load),
        gen.map((g) => (100 * g / load).toFixed(2) + ' %').join(' / ') + ' нагрузки');
      const costs = (C.rows['Operating cost'] || []).map(N);
      rec('НАБЛЮДЕНИЕ: стоимость почти равна счёту за всю нагрузку из сети',
        costs.every((c) => c > 0.95 * load * 60),
        `${costs.map((c) => c.toLocaleString()).join(' / ')} против ${(load * 60).toLocaleString()} ₸`);
    }
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== S-02
  // Тот же год, но обслуживание задано СЧЁТОМ с равномерной разбивкой: по
  // одному событию на срез -- на порядок более простая комбинаторика. Ожидаем,
  // что правила без батареи сойдутся за 120 с, а правило с батареей нет.
  CASE = 'S-02 Счётчик сервисов на годе, лимит 120 с';
  try {
    await openYear();
    await setCell(UNITS, 10, 0, 12);
    await setCell(UNITS, 10, 1, 12);
    await setNum('Time limit per scenario', 120);
    await setNum('Optimality gap', 0.5);
    const secs = await solveLong();
    const t = await body();
    const C = await compare();
    rec('страница дождалась ответа', !!C || /not one rule was solved/.test(t),
      `${secs.toFixed(0)} с`);
    honest(C, t);
    if (C) {
      const names = C.head.slice(1);
      const solver = C.rows['Solver'] || [];
      const gaps = solver.map(gapOf);
      const load = N((C.rows['Load (kWh)'] || [])[0]);
      const gen = (C.rows['Fuel-fired generation (kWh)'] || []).map(N);
      const tight = names.filter((_, i) => gaps[i] <= 0.5);
      rec('правила без батареи укладываются в допуск за 120 с',
        tight.length >= 2, names.map((n, i) => `${n.slice(0, 1)} ${solver[i]}`).join(' | '));
      rec('и это настоящий план: машины несут большую часть года',
        gen.some((g) => g > 0.5 * load),
        gen.map((g) => (100 * g / load).toFixed(1) + ' %').join(' / ') + ' нагрузки');
      const hard = names.filter((_, i) => gaps[i] > 0.5);
      rec('НАБЛЮДЕНИЕ: тяжёлым остаётся правило с батареей',
        hard.length === 0 ? /Left out of the comparison/.test(t) : /BATTERY/i.test(hard.join(' ')),
        hard.length ? `не сошлись: ${hard.join(', ')}`
          : (t.match(/Left out of the comparison[^\n]*/)?.[0]?.slice(0, 120) || 'сошлись все три'));
    }
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  const bad = OUT.filter((r) => !r.ok);
  return JSON.stringify({ total: OUT.length, failed: bad.length, report: OUT }, null, 1);
}
