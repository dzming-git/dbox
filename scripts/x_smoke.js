#!/usr/bin/env node
/* X 面板黄金路径冒烟（真服务 + 无头浏览器）
 * 见 docs/development/x-hardening-plan.md 阶段 2.2。
 * 用法：node scripts/x_smoke.js     前置：本机 dev 服务在跑（5173/8080/8093）。
 *
 * 覆盖：
 *   1. 打开关注流：内容出现（无未捕获错误）
 *   2. 锚点恢复精度：滚动 → 面板自行保存锚点 → 刷新 → 该卡片回到原位置（误差 < 3px）
 *   3. 产出键取回机制：清掉本地重键 → pull() 取不回、pullProduced() 取回、其它键无损
 *   4. 全新浏览器上下文打开搜索页：关键词缓存从 0 取回 N（防「新设备搜索页为空」）
 *
 * ⚠️ 已知留白（有意，不假装覆盖）：
 *   · 用户页（feed:user:<uid>）需先确认用户页 hash 路由格式；
 *   · 「全部重搜」真实后台爬取耗时数分钟且有风控，此处只验证其依赖的取回原语。
 * ⚠️ 关于锚点断言的踩坑记录：**不要**断言「新 profile 打开会精确恢复到服务端锚点」——
 *   实测(1) 新 profile 本机无锚点、面板按主控语义停在顶部；(2) 锚点指向的推文常常已从
 *   关注流缓存中消失（内容本就滚动更新），此时无法"精确落位"。有效断言是下面这条：
 *   用产品自己的保存路径产生锚点，再刷新校验。
 */
'use strict';
const L = require('./x_e2e_lib.js');

const results = [];
function record(name, ok, detail) {
  results.push({ name, ok, detail });
  console.log(`${ok ? '  ok  ' : ' FAIL '} ${name}${detail ? '  — ' + detail : ''}`);
}
function skip(name, why) { results.push({ name, ok: true, detail: 'SKIP: ' + why }); console.log(`  skip  ${name}  — ${why}`); }

const anchorOf = (f) => f.evaluate(() => {
  try { return (XFEED && XFEED.keys) ? XSTATE.get(XFEED.keys.anchor) : null; } catch (_) { return null; }
});

async function case1(page) {
  const tr = L.trackRequests(page);
  const t0 = Date.now();
  const f = await L.openPanel(page, '#/home');
  await L.waitStable(page);
  const t = await L.waitCards(f, { min: 1, timeout: 9000 });
  record('1 打开关注流：内容出现', t !== null, t === null ? '9s 内无卡片' : (Date.now() - t0) + 'ms（含 boot）');
  if (t === null) console.log(tr.dump());
  return f;
}

async function case2(page, f) {
  // 1) 用产品自己的路径产生锚点：滚动容器 → 等防抖保存
  const cont = await f.evaluate(() => { const c = document.querySelector('#view-browse'); return c ? { h: c.scrollHeight, kh: c.clientHeight } : null; });
  if (!cont || cont.h <= cont.kh + 400) { skip('2 锚点恢复精度', '内容不足以滚动'); return; }
  const before = await anchorOf(f);
  // 必须用**真实滚轮事件**：面板刻意忽略程序化改动 scrollTop（避免在恢复过程中把自己的
  // 锚点又存一遍），所以 `el.scrollTop = x` 不会触发保存——本用例最初就是这么 skip 的。
  await page.mouse.move(195, 420);
  let moved = 0;
  for (let i = 0; i < 25 && moved < 1200; i++) {
    await page.mouse.wheel(0, 200);
    await L.sleep(70);
    moved = await f.evaluate(() => { const c = document.querySelector('#view-browse'); return c ? c.scrollTop : 0; });
  }
  await L.sleep(1800);                                   // 滚动防抖保存
  const saved = await anchorOf(f);
  if (!saved || !saved.id || (before && before.id === saved.id)) { skip('2 锚点恢复精度', `滚动后锚点未更新（实际滚动 ${moved}px）`); return; }
  const want = Number(saved.offset);

  // 2) 刷新，校验该卡片回到原位置
  await page.reload({ waitUntil: 'domcontentloaded' });
  const f2 = await L.waitPanelFrame(page);
  let okRender = true;
  try { await L.waitFor(() => f2.evaluate((id) => !!document.querySelector(`[data-tid="${id}"]`), saved.id), { timeout: 15000, interval: 60, label: '锚点卡片渲染' }); }
  catch (_) { okRender = false; }
  if (!okRender) { record('2 锚点恢复精度', false, `刷新后锚点卡片 ${saved.id} 15s 内未渲染`); return; }
  const top = await f2.evaluate((id) => document.querySelector(`[data-tid="${id}"]`).getBoundingClientRect().top, saved.id);
  const diff = Math.abs(top - want);
  record('2 锚点恢复精度', diff < 3, `卡片 top=${top.toFixed(1)} vs 保存 offset=${want.toFixed(1)}（差 ${diff.toFixed(2)}px）`);
}

async function case3(f) {
  const r = await f.evaluate(async () => {
    const key = 'feed:tweets:items';
    if (XSTATE._cache[key] === undefined) return { skip: '本地无 ' + key };
    const other = XSTATE._cache['bm:list'] ? JSON.stringify(XSTATE._cache['bm:list'].value).length : -1;
    delete XSTATE._cache[key];
    await XSTATE.pull();
    const afterPull = XSTATE._cache[key] !== undefined;
    await XSTATE.pullProduced([key]);
    const afterProduced = XSTATE._cache[key] !== undefined;
    const other2 = XSTATE._cache['bm:list'] ? JSON.stringify(XSTATE._cache['bm:list'].value).length : -1;
    return { afterPull, afterProduced, intact: other === other2, other, other2 };
  });
  if (r.skip) { skip('3 产出键取回机制', r.skip); return; }
  record('3 产出键取回：pull 取不回、pullProduced 取回、其它键无损',
    r.afterPull === false && r.afterProduced === true && r.intact === true,
    `pull 后=${r.afterPull}（应 false，重键不在对账里）｜pullProduced 后=${r.afterProduced}｜其它键 ${r.other}→${r.other2}`);
}

const kwState = (f) => f.evaluate(() => {
  const list = (typeof srchKwList !== 'undefined' && srchKwList) ? srchKwList : [];
  const keys = list.map((e) => 'search:kw:' + e.key);
  return { n: keys.length, have: keys.filter((k) => XSTATE._cache[k] !== undefined).length };
});

async function case4(tok) {
  const { browser, page } = await L.openBrowser(tok);   // 新 context：除 token 外 localStorage 全空
  try {
    const f = await L.openPanel(page, '#/search');
    await L.waitStable(page);
    try { await L.waitFor(async () => { const s = await kwState(f); return s.n > 0 && s.have >= s.n; }, { timeout: 12000, interval: 300, label: '关键词缓存取回' }); } catch (_) {}
    const s = await kwState(f);
    record('4 新上下文搜索页：关键词缓存从 0 取回', s.n > 0 && s.have >= s.n,
      s.n === 0 ? '关键词清单为空（该账号没设关键词？）' : `${s.have}/${s.n} 个 search:kw:* 已取回`);
  } finally { await browser.close(); }
}

(async () => {
  const tok = await L.login();
  const { browser, page } = await L.openBrowser(tok);
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e).slice(0, 140)));
  try {
    const f = await case1(page);
    await case2(page, f);
    const f2 = await L.waitPanelFrame(page).catch(() => null);
    if (f2) await case3(f2); else record('3 产出键取回机制', false, '面板 frame 未就绪');
    await case4(tok);
    record('页面无未捕获错误', errs.length === 0, errs.slice(0, 2).join(' | '));
  } catch (e) {
    record('套件执行', false, String((e && e.message) || e).slice(0, 200));
  } finally { await browser.close(); }

  const bad = results.filter((r) => !r.ok).length;
  console.log(`\n${bad ? '✗' : '✓'} x_smoke: ${bad} 失败 / ${results.length - bad} 通过`);
  process.exit(bad ? 1 : 0);
})();
