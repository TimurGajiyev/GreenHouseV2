// QA matrix, group P, part A — driven through the browser.
//
// P-01 базовый день · P-02 базовая неделя · P-04..P-06 загрузка CSV ·
// P-07 фит площадки · P-08 сеть с запасом · P-09 почасовой тариф
//
//   browser_run_code_unsafe filename=.playwright/scripts/gh_qa_p_a.js
//
// Каждый кейс начинается с чистой сессии (перезагрузка страницы), чтобы
// состояние предыдущего не протекало в следующий.
async (page) => {
  const APP = 'http://localhost:8505/';
  const OUT = [];
  let CASE = '';
  const rec = (name, ok, d) => OUT.push({ c: CASE, name, ok: !!ok, d: d === undefined ? '' : String(d) });
  const N = (s) => {
    if (s === undefined || s === null) return NaN;
    const m = String(s).replace(/[  \u00a0₸$]/g, '').replace('−', '-').match(/-?[\d,]+(\.\d+)?/);
    return m ? parseFloat(m[0].replace(/,/g, '')) : NaN;
  };
  const near = (name, got, want, tol, unit) =>
    rec(name, Math.abs(got - want) <= tol,
      `${got.toLocaleString('en-US', { maximumFractionDigits: 2 })} vs ` +
      `${want.toLocaleString('en-US', { maximumFractionDigits: 2 })}${unit ? ' ' + unit : ''}`);

  const idle = async (ms = 600000) => {
    await page.waitForTimeout(350);
    const w = page.locator('[data-testid="stStatusWidget"]');
    try { await w.waitFor({ state: 'attached', timeout: 1500 }); } catch (e) { }
    try { await w.waitFor({ state: 'detached', timeout: ms }); } catch (e) { }
    await page.waitForTimeout(450);
  };
  const body = async () => (await page.evaluate(() => document.body.innerText)).replace(/[\u00a0 ]/g, ' ');
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
  const upload = async (what, file) => {
    await page.locator('[data-testid="stFileUploader"]').filter({ hasText: what })
      .locator('input[type=file]').first().setInputFiles(file);
    await idle();
  };
  const solve = async () => {
    const b = btn('Solve scenarios');
    await b.scrollIntoViewIfNeeded();
    await b.click();
    await idle();
    await page.locator('text=Scenario comparison').first().waitFor({ timeout: 600000 });
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
  // подпись окна: "N hours · E kWh · peak P kW · minimum M kW"
  const window0 = async () => {
    const t = await body();
    const s = slice(t, 'Window length (hours)', 'Site');
    const m = s.match(/([\d,]+) hours · ([\d,]+) kWh · peak ([\d,]+) kW · minimum ([\d,]+) kW/);
    return m ? { h: N(m[1]), kwh: N(m[2]), peak: N(m[3]), min: N(m[4]), raw: m[0] } : { raw: s.slice(0, 120) };
  };
  const balanceFromTable = (C) => {
    const row = (k) => (C.rows[k] || []).map(N);
    const load = row('Load (kWh)'), gen = row('Fuel-fired generation (kWh)');
    const grid = row('Grid purchase (kWh)'), chg = row('Battery charged (kWh)');
    const dis = row('Battery discharged (kWh)'), sp = row('Spill (kWh)');
    return load.map((_, i) => Math.abs(gen[i] + grid[i] + dis[i] - load[i] - chg[i] - sp[i]));
  };

  // ==================================================================== P-01
  CASE = 'P-01 Базовый день';
  try {
    await openApp();
    await setRadio('Example: bess_profile_v2.jsx day (24 h)');
    const w = await window0();
    rec('24 часа в подписи окна', w.h === 24, w.raw);
    near('энергия дня', w.kwh, 56009, 1, 'kWh');
    rec('фит площадки выключен по умолчанию',
      (await body()).includes('Not scaling'));
    await solve();
    const C = await compare();
    rec('три сценария в таблице', C && C.head.length === 4, C ? C.head.join(' | ') : 'нет таблицы');
    const solver = C.rows['Solver'] || [];
    rec('все три решены', solver.every((s) => /Optimal/.test(s)), solver.join(' | '));
    rec('gap каждого в пределах 0.5 %',
      solver.every((s) => { const g = s.match(/gap ([\d.]+)%/); return !g || parseFloat(g[1]) <= 0.5 + 1e-9; }),
      solver.join(' | '));
    const bal = balanceFromTable(C);
    rec('баланс энергии сходится в каждом сценарии',
      bal.every((b) => b <= 2), 'невязки ' + bal.map((b) => b.toFixed(0)).join(' / ') + ' kWh');
    near('нагрузка в таблице равна энергии окна', N((C.rows['Load (kWh)'] || [])[0]), 56009, 1, 'kWh');
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== P-02
  CASE = 'P-02 Базовая неделя';
  try {
    await openApp();
    await setRadio('Example: bess_profile_v2.jsx week (168 h)');
    const w = await window0();
    rec('168 часов в подписи окна', w.h === 168, w.raw);
    near('энергия недели', w.kwh, 368663, 1, 'kWh');
    rec('неделя ≈ семь дней', w.kwh > 5 * 56009 && w.kwh < 9 * 56009, `${w.kwh.toLocaleString()} kWh`);
    await solve();
    const C = await compare();
    const solver = C.rows['Solver'] || [];
    rec('все три решены', solver.every((s) => /Optimal/.test(s)), solver.join(' | '));
    rec('баланс энергии сходится', balanceFromTable(C).every((b) => b <= 2));
    const cost = (C.rows['Operating cost'] || []).map(N);
    rec('B не дешевле A (правило 90 % строже)', cost[1] >= cost[0] - 1,
      `A ${cost[0].toLocaleString()} · B ${cost[1].toLocaleString()}`);
    rec('C не дороже B (батарею можно не трогать)', cost[2] <= cost[1] + 1,
      `B ${cost[1].toLocaleString()} · C ${cost[2].toLocaleString()}`);
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== P-04
  CASE = 'P-04 Загрузка CSV 8 760 строк';
  try {
    await openApp();
    await setRadio('Upload hourly CSV');
    await upload('Hourly load, kW', 'D:/GreenHouseV2/reopt_test_data/ui/load_8760_flat.csv');
    const w = await window0();
    rec('8 760 часов принято', w.h === 8760, w.raw);
    near('суммарная энергия', w.kwh, 21900000, 1, 'kWh');
    near('пик равен плоскому значению', w.peak, 2500, 1, 'kW');
    near('минимум равен ему же', w.min, 2500, 1, 'kW');
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== P-05
  CASE = 'P-05 CSV формата Excel';
  try {
    await openApp();
    await setRadio('Upload hourly CSV');
    await upload('Hourly load, kW', 'D:/GreenHouseV2/reopt_test_data/ui/load_excel.csv');
    const w = await window0();
    rec('три строки данных, заголовок пропущен', w.h === 3, w.raw);
    near('десятичная запятая и разделитель разрядов разобраны',
      w.kwh, 1342.5 + 2000.0 + 1900.25, 1, 'kWh');
    near('пик', w.peak, 2000, 1, 'kW');
    near('минимум', w.min, 1342.5, 1, 'kW');
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== P-06
  CASE = 'P-06 CSV со счётчиком часов';
  try {
    await openApp();
    await setRadio('Upload hourly CSV');
    await upload('Hourly load, kW', 'D:/GreenHouseV2/reopt_test_data/ui/load_counter.csv');
    const w = await window0();
    rec('восемь часов', w.h === 8, w.raw);
    near('взят второй столбец, а не счётчик', w.kwh, 1600 + 1700 + 1800 + 1900 + 2000 + 2100 + 2200 + 2300, 1, 'kWh');
    near('минимум = первое значение данных', w.min, 1600, 1, 'kW');
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== P-07
  CASE = 'P-07 Фит площадки';
  try {
    await openApp();
    await setRadio('Free mode: a real year, no file needed');
    await setCheck("Scale the profile to this site's own demand", true);
    const s = slice(await body(), 'Site demand', 'Grid price');
    rec('профиль сел на все три якоря',
      /min 1,200 · mean 3,000 · max 5,500 kW/.test(s), s.match(/fitted on[^\n]*/)?.[0] || s.slice(0, 110));
    rec('load factor = среднее / максимум', /load factor 54\.5 %/.test(s), s.match(/load factor [\d.]+ %/)?.[0]);
    rec('γ отчитан', /γ [\d.]+/.test(s), s.match(/γ [\d.]+/)?.[0]);
    const w = await window0();
    near('энергия года = 3 000 кВт × 8 760 ч', w.kwh, 26280000, 1, 'kWh');
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== P-08
  CASE = 'P-08 Сеть с запасом';
  try {
    await openApp();
    await setRadio('Free mode: a real year, no file needed');
    await setCheck("Scale the profile to this site's own demand", true);
    await setNum('Window length', 168);
    await setCheck('The grid connection is limited', true);
    await setNum('Maximum grid import (kW)', 20000);
    const s = slice(await body(), 'Site demand', 'Grid price');
    rec('до решения ни ошибки, ни предупреждения',
      !s.includes('No answer exists') && !s.includes('Tight: peak'),
      'сеть 20,000 + флот 2,267 против пика окна');
    await solve();
    const C = await compare();
    rec('решается', (C.rows['Solver'] || []).every((x) => /Optimal/.test(x)));
    const peak = (C.rows['Peak grid purchase (kW)'] || []).map(N);
    rec('импорт ни разу не упирается в лимит', peak.every((p) => p < 20000 - 1),
      'пиковый импорт ' + peak.map((p) => p.toLocaleString()).join(' / ') + ' kW');
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  // ==================================================================== P-09
  CASE = 'P-09 Почасовой тариф нужной длины';
  try {
    await openApp();
    await setRadio('Free mode: a real year, no file needed');
    await upload('Or hourly prices', 'D:/GreenHouseV2/reopt_test_data/ui/price_8760.csv');
    const g = slice(await body(), 'Or hourly prices', 'Fuel-fired units');
    rec('цены приняты и диапазон показан', /hourly prices/.test(g),
      g.match(/hourly prices [^\n]*/)?.[0] || g.slice(0, 110));
    const m = g.match(/hourly prices ([\d.,]+)–([\d.,]+)/);
    near('нижняя граница тарифа', m ? N(m[1]) : NaN, 40, 0.01, '₸/kWh');
    near('верхняя граница тарифа', m ? N(m[2]) : NaN, 90, 0.01, '₸/kWh');
    rec('ошибки о несовпадении длины нет', !g.includes('using the flat price'));
  } catch (e) { rec('ИСКЛЮЧЕНИЕ', false, e.message); }

  const bad = OUT.filter((r) => !r.ok);
  return JSON.stringify({ total: OUT.length, failed: bad.length, report: OUT }, null, 1);
}
