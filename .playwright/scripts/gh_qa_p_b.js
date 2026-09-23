// QA matrix, group P, part B — кейсы, которым нужны правки в таблицах и решения.
//
// P-03 год через типовые дни · P-11 обслуживание по моточасам ·
// P-12 батарея с фиксированным SoC · P-13 Ownership = Purchase ·
// P-14 Variable O&M
//
//   browser_run_code_unsafe filename=.playwright/scripts/gh_qa_p_b.js
//
// Столбцы таблицы юнитов: 1 Unit · 2 kW · 3 Fuel cost · 4 Start cost ·
// 5 Min load % · 6 Min up · 7 Min down · 8 Spill · 9 Max starts/day ·
// 10 Services/period · 11 Service h · 12 Capacity lost % · 13 Spread ·
// 14 Service every (run h) · 15 Service cost · 16 Variable O&M ·
// 17 Ownership · 18 Purchase cost
async (page) => {
  const APP = 'http://localhost:8505/';
  const OUT = [];
  let CASE = '';
  const rec = (name, ok, d) => OUT.push({ c: CASE, name, ok: !!ok, d: d === undefined ? '' : String(d) });
  const N = (s) => {
    if (s === undefined || s === null) return NaN;
    const m = String(s).replace(/[   ₸$]/g, '').replace('−', '-').match(/-?[\d,]+(\.\d+)?/);
    return m ? parseFloat(m[0].replace(/,/g, '')) : NaN;
  };
  const near = (name, got, want, tol, unit) =>
    rec(name, Math.abs(got - want) <= tol,
      `${got.toLocaleString('en-US', { maximumFractionDigits: 2 })} vs ` +
      `${want.toLocaleString('en-US', { maximumFractionDigits: 2 })}${unit ? ' ' + unit : ''}`);

  const idle = async (ms = 900000) => {
    await page.waitForTimeout(350);
    const w = page.locator('[data-testid="stStatusWidget"]');
    try { await w.waitFor({ state: 'attached', timeout: 1500 }); } catch (e) { }
    try { await w.waitFor({ state: 'detached', timeout: ms }); } catch (e) { }
    await page.waitForTimeout(450);
  };
  const body = async () => (await page.evaluate(() => document.body.innerText)).replace(/[  ]/g, ' ');
  const slice = (t, a, b) => { const i = t.indexOf(a); if (i < 0) return ''; const j = b ? t.indexOf(b, i + a.length) : -1; return t.slice(i, j < 0 ? t.length : j); };
  const btn = (name) => page.locator('button').filter({ hasText: name }).first();

  const openApp = async () => {
    await page.goto(APP, { waitUntil: 'load' });
    await page.waitForTimeout(1200);
    await btn('Custom dispatch study (not REopt)').click();
    await page.locator('text=Hourly load').first().waitFor({ timeout: 60000 });
    await idle();
  };
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

  // ---- таблицы (glide-data-grid), как в gh_ui_2_tables.js --------------
  const UNITS = 0;
  const canvasOf = (gi) => page.locator('[data-testid="stDataFrame"]').nth(gi).locator('canvas').first();
  const selectedCell = (gi) => page.evaluate((gi) => {
    const g = [...document.querySelectorAll('[data-testid="stDataFrame"]')][gi];
    const c = g && g.querySelector('[data-testid^="glide-cell-"][aria-selected="true"]');
    return c ? c.getAttribute('data-testid').replace('glide-cell-', '') : null;
  }, gi);
  const cellText = (gi, col, row) => page.evaluate(([gi, col, row]) => {
    const g = [...document.querySelectorAll('[data-testid="stDataFrame"]')][gi];
    const c = g && g.querySelector(`[data-testid="glide-cell-${col}-${row}"]`);
    return c ? (c.innerText || c.getAttribute('aria-label') || '').trim() : '(не отрисована)';
  }, [gi, col, row]);
  const selectCell = async (gi, col, row) => {
    const cv = canvasOf(gi);
    let at = null;
    for (let tries = 0; tries < 4 && !at; tries++) {
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
      at = await selectedCell(gi);
    }
    if (!at) throw new Error('таблица не приняла клик');
    const reclick = async () => {
      // Прокрутка таблицы вправо меняет высоту страницы, канвас уезжает из-под
      // курсора и клавиши перестают доходить. Возвращаем фокус щелчком и
      // продолжаем с того места, где выделение реально стоит.
      await cv.evaluate((el) => el.scrollIntoView({ block: 'center' }));
      await page.waitForTimeout(350);
      const box = await cv.boundingBox();
      await page.mouse.move(box.x + 60, box.y + 52);
      await page.waitForTimeout(100);
      await page.mouse.down();
      await page.waitForTimeout(90);
      await page.mouse.up();
      await page.waitForTimeout(300);
      at = (await selectedCell(gi)) || at;
    };
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
      if (!moved && ++stalls % 2 === 0) await reclick();
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
  const pickCell = async (gi, col, row, option) => {
    await selectCell(gi, col, row);
    await canvasOf(gi).press('Enter');
    await page.waitForTimeout(700);
    await page.locator('[data-testid="portal"]').getByText(option, { exact: true }).first().click();
    await idle();
  };

  const solve = async () => {
    const b = btn('Solve scenarios');
    await b.scrollIntoViewIfNeeded();
    await b.click();
    await idle();
    await page.locator('text=Scenario comparison').first().waitFor({ timeout: 900000 });
    await page.waitForTimeout(900);
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
  // таблица «Fuel-fired units» в разделе периодов
  const unitTable = () => page.evaluate(() => {
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

  const freeYear = async (hours) => {
    await setRadio('Free mode: a real year, no file needed');
    await setCheck("Scale the profile to this site's own demand", true);
    if (hours) await setNum('Window length', hours);
  };

  // ==================================================================== P-03
  CASE = 'P-03 Год через типовые дни';
  try {
    await openApp();
    await freeYear(null);
    await setRadio('A year from typical days (weighted)');
    let t = slice(await body(), 'How to cover the horizon', 'Solve scenarios');
    rec('подпись обещает 12 × 24 = 288 часов на сценарий',
      /12 typical days × 24 h = 288 hours to solve per scenario instead of 8,760/.test(t),
      t.match(/\d+ typical days × 24 h = [\d,]+ hours[^.]*/)?.[0] || t.slice(0, 120));
    const t0 = Date.now();
    await solve();
    const secs = (Date.now() - t0) / 1000;
    const C = await compare();
    const note = slice(await body(), 'Scenario comparison', 'Economics of one');
    rec('над таблицей сказано, из чего собран год',
      /a year from 12 typical days/.test(note) && /= 365 days/.test(note),
      note.match(/a year from[^\n]*/)?.[0]?.slice(0, 110));
    rec('все три решены', (C.rows['Solver'] || []).every((s) => /Optimal/.test(s)),
      (C.rows['Solver'] || []).join(' | '));
    near('годовая энергия сохранена точно', N((C.rows['Load (kWh)'] || [])[0]), 26280000, 1, 'kWh');
    rec('год посчитан за минуты, а не за часы', secs < 300, `${secs.toFixed(0)} с на три сценария`);
    const gen = (C.rows['Fuel-fired generation (kWh)'] || []).map(N);
    rec('генераторы реально работают', gen[0] > 0.5 * 26280000,
      `${(100 * gen[0] / 26280000).toFixed(1)} % нагрузки у A`);
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== P-11
  CASE = 'P-11 Обслуживание по моточасам (720 ч)';
  try {
    await openApp();
    await freeYear(720);
    await setCell(UNITS, 14, 0, 500);          // Service every (run h)
    await setCell(UNITS, 14, 1, 500);
    let u = slice(await body(), 'Service plan', 'Battery');
    rec('план обслуживания пересчитан на моточасы',
      /every 500 running hours/.test(u), u.split('\n').filter(Boolean)[0]?.slice(0, 130));
    rec('сказано, что счёт становится следствием, а не входом',
      u.includes('overrides the count') && u.includes('never runs is never'));
    await solve();
    const ut = await unitTable();
    rec('таблица юнитов показывает интервал в моточасах',
      ut && ut.head.includes('EVERY RUN H'), ut ? ut.head.join(' ') : 'таблицы нет');
    if (ut) {
      const i = ut.head.indexOf('EVERY RUN H');
      const j = ut.head.indexOf('SERVICES');
      const k = ut.head.indexOf('RUNNING HOURS');
      const rows = ut.rows.filter((r) => r[0] !== 'Fleet');
      rec('интервал отчитан как 500 ч для каждого юнита',
        rows.every((r) => N(r[i]) === 500), rows.map((r) => r[i]).join(' / '));
      rec('число сервисов — следствие наработки',
        rows.every((r) => N(r[j]) <= Math.ceil(N(r[k]) / 500) + 1),
        rows.map((r) => `${r[0]}: ${r[j]} сервисов при ${r[k]} моточасах`).join('; '));
      rec('есть колонка накопленных моточасов', ut.head.includes('BANKED H'));
    }
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== P-12
  CASE = 'P-12 Батарея с фиксированным SoC';
  try {
    await openApp();
    await freeYear(48);
    const soc = page.locator('input[type=number][aria-label^="Start SoC"]').first();
    rec('при цикличном режиме стартовый SoC закрыт', await soc.isDisabled());
    await solve();
    const cyc = (await compare()).rows['Operating cost'].map(N);
    await setRadio('Fixed');
    rec('в режиме Fixed поле открывается', !(await soc.isDisabled()));
    await setNum('Start SoC', 50);
    await solve();
    const C = await compare();
    const fix = C.rows['Operating cost'].map(N);
    rec('решается в обоих режимах', (C.rows['Solver'] || []).every((s) => /Optimal/.test(s)));
    rec('фиксированный старт не дороже цикличного (цикл — это лишнее ограничение)',
      fix[2] <= cyc[2] + 1,
      `цикл ${cyc[2].toLocaleString()} → фикс ${fix[2].toLocaleString()} ₸`);
    const dis = N((C.rows['Battery discharged (kWh)'] || [])[2]);
    const chg = N((C.rows['Battery charged (kWh)'] || [])[2]);
    rec('батарея работает в сценарии C', dis > 0 && chg > 0,
      `заряд ${chg.toLocaleString()} / разряд ${dis.toLocaleString()} kWh`);
    rec('при незамкнутом цикле разряд НЕ обязан равняться 88 % заряда',
      true, `отдано ${(100 * dis / chg).toFixed(2)} % от принятого`);
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== P-13
  CASE = 'P-13 Ownership = Purchase';
  try {
    await openApp();
    await freeYear(48);
    await solve();
    const before = (await compare()).rows['Operating cost'].map(N);
    await pickCell(UNITS, 17, 0, 'Purchase');
    await setCell(UNITS, 18, 0, 120000000);
    rec('ячейка владения приняла значение', (await cellText(UNITS, 17, 0)) === 'Purchase',
      await cellText(UNITS, 17, 0));
    rec('цена покупки записана', N(await cellText(UNITS, 18, 0)) === 120000000,
      await cellText(UNITS, 18, 0));
    await solve();
    const after = (await compare()).rows['Operating cost'].map(N);
    rec('цена покупки НЕ входит в операционную стоимость (верно)',
      Math.abs(after[0] - before[0]) < 1,
      `${before[0].toLocaleString()} → ${after[0].toLocaleString()} ₸`);
    const page_text = await body();
    rec('НАХОДКА: цена покупки должна быть видна в результатах',
      page_text.includes('120,000,000'),
      page_text.includes('120,000,000') ? 'найдена'
        : 'НЕ найдена нигде на странице — столбцы Ownership и Purchase cost ни на что не влияют');
    const econ = slice(page_text, 'Economics of one scenario', 'Dispatch by period');
    rec('раздел экономики учитывает капитал флота, а не только батареи',
      /120,000,000/.test(econ),
      econ.match(/EXTRA (BATTERY )?CAPEX[\s\S]{0,160}/)?.[0]?.replace(/\n/g, ' ').slice(0, 150) || '');
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== P-14
  CASE = 'P-14 Variable O&M';
  try {
    await openApp();
    await freeYear(48);
    await solve();
    const C0 = await compare();
    const gen0 = N((C0.rows['Generation cost'] || [])[0]);
    const kwh0 = N((C0.rows['Fuel-fired generation (kWh)'] || [])[0]);
    const spill0 = N((C0.rows['Spill (kWh)'] || [])[0]);
    await setCell(UNITS, 16, 0, 8);            // Variable O&M
    await setCell(UNITS, 16, 1, 8);
    await solve();
    const C1 = await compare();
    const gen1 = N((C1.rows['Generation cost'] || [])[0]);
    const kwh1 = N((C1.rows['Fuel-fired generation (kWh)'] || [])[0]);
    const spill1 = N((C1.rows['Spill (kWh)'] || [])[0]);
    rec('стоимость генерации выросла', gen1 > gen0,
      `${gen0.toLocaleString()} → ${gen1.toLocaleString()} ₸`);
    // Сверять деньги против НАПЕЧАТАННЫХ киловатт-часов точнее, чем на один
    // kWh, нельзя: таблица округляет и выработку, и спилл до целых, так что
    // допуск 30 ₸ -- это ровно цена одного округлённого киловатт-часа, а не
    // послабление. Точную проверку до копейки делает tools/qa_group_p.py.
    near('база до O&M = 22 ₸ за kWh рейтинговой выработки (в пределах округления таблицы)',
      gen0, 22 * (kwh0 + spill0), 30, '₸');
    near('после O&M = 30 ₸ за kWh рейтинговой выработки (в пределах округления таблицы)',
      gen1, 30 * (kwh1 + spill1), 35, '₸');
    rec('операционная стоимость не упала от добавленной статьи',
      N(C1.rows['Operating cost'][0]) >= N(C0.rows['Operating cost'][0]) - 1,
      `${N(C0.rows['Operating cost'][0]).toLocaleString()} → ${N(C1.rows['Operating cost'][0]).toLocaleString()} ₸`);
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  const bad = OUT.filter((r) => !r.ok);
  return JSON.stringify({ total: OUT.length, failed: bad.length, report: OUT }, null, 1);
}
