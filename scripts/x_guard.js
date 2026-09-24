#!/usr/bin/env node
/* X 插件契约守卫（静态检查，无副作用，秒级）
 * 见 docs/development/x-hardening-plan.md 阶段 1.4 / 2.1。
 *
 * 检查项：
 *   A. ui/panel.html 的内联 X_KEYS 与 extensions/x/x_keys.json 完全一致（--fix 可自动同步）
 *   B. panel.html / backend/server.py 里出现的键字面量都已在注册表登记
 *   C. heavyKeys / producedKeys 由注册表派生（禁止重新硬编码），且派生结果与注册表一致
 *   D. fetchVia==='pullProduced' 的键在 panel.html 里确有取回调用点
 *   E. 6 个 localStorage 键字面量都在 panel.html 里存在（防改名漂移）
 *
 * 用法：
 *   node scripts/x_guard.js          只检查（有问题退出码 1）
 *   node scripts/x_guard.js --fix    从 x_keys.json 重新生成 panel.html 的内联块，再检查
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const REG_PATH = path.join(ROOT, 'extensions/x/x_keys.json');
const PANEL_PATH = path.join(ROOT, 'extensions/x/ui/panel.html');
const SERVER_PATH = path.join(ROOT, 'extensions/x/backend/server.py');
const START = '/*X_KEYS_JSON_START*/';
const END = '/*X_KEYS_JSON_END*/';

const fails = [];
const warns = [];
const oks = [];
const fail = (m) => fails.push(m);
const warn = (m) => warns.push(m);
const ok = (m) => oks.push(m);

const reg = JSON.parse(fs.readFileSync(REG_PATH, 'utf8'));
let panel = fs.readFileSync(PANEL_PATH, 'utf8');
const server = fs.readFileSync(SERVER_PATH, 'utf8');

/* ---------- 注册表 → 派生集合 ---------- */
const heavyList = reg.keys.filter((e) => e.heavy).map((e) => e.name + (e.prefix ? '*' : ''));
const producedConcrete = reg.keys
  .filter((e) => e.producer === 'server' && !e.prefix)
  .map((e) => e.name);
const nsFirstSeg = [...new Set(reg.keys.map((e) => e.name.split(':')[0]))];

/* ---------- A. 内联块一致性（含 --fix） ---------- */
function extractInline(src) {
  const i = src.indexOf(START);
  const j = src.indexOf(END);
  if (i < 0 || j < 0) return null;
  return src.slice(i + START.length, j);
}
// ⚠️ 行尾：panel.html 在本仓可能是 CRLF，而注册表生成的是 LF。若逐字节比较，
// 任何编辑器/工具改写行尾都会让这里整天误报（本轮就误报过一次）。比较前统一成 LF，
// 写回时沿用文件原有行尾，避免把文件搞成混行尾。
const EOL = panel.indexOf('\r\n') >= 0 ? '\r\n' : '\n';
const norm = (s) => s.replace(/\r\n/g, '\n');
const wantBodyLF = JSON.stringify(reg, null, 2).split('\n').join('\n  ');
const wantBody = EOL === '\n' ? wantBodyLF : wantBodyLF.split('\n').join('\r\n');
const wantFull = START + wantBody + END;
if (process.argv.includes('--fix')) {
  const cur = extractInline(panel);
  if (cur === null) {
    fail('panel.html 里找不到 ' + START + ' … ' + END + ' 标记，无法自动同步');
  } else if (norm(cur) !== norm(wantBody)) {
    panel = panel.slice(0, panel.indexOf(START)) + wantFull + panel.slice(panel.indexOf(END) + END.length);
    fs.writeFileSync(PANEL_PATH, panel);
    ok('已用 x_keys.json 重写 panel.html 的内联 X_KEYS');
  } else {
    ok('内联 X_KEYS 已是最新，无需改写');
  }
}
{
  const cur = extractInline(panel);
  if (cur === null) {
    fail('panel.html 缺少内联键注册表标记 ' + START);
  } else if (norm(cur) !== norm(wantBody)) {
    fail('panel.html 的内联 X_KEYS 与 x_keys.json 不一致 → 跑 `node scripts/x_guard.js --fix`');
  } else {
    ok(`A 内联 X_KEYS 与 x_keys.json 一致（行尾 ${EOL === '\r\n' ? 'CRLF' : 'LF'}）`);
  }
}

/* ---------- 键字面量匹配 ---------- */
function normPattern(p) {
  return p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
function isRegistered(lit) {
  for (const e of reg.keys) {
    if (e.prefix) {
      if (lit === e.name || lit === e.name + '*' || lit.startsWith(e.name)) return true;
    } else if (lit === e.name) return true;
  }
  return false;
}
function scanLiterals(src, file) {
  // 候选：以注册表已知命名空间开头的含冒号字符串字面量
  const re = new RegExp(`['"]([a-z][a-zA-Z0-9_]*(?::[a-zA-Z0-9_*-]+)+)['"]`, 'g');
  const bad = new Map();
  let m;
  while ((m = re.exec(src)) !== null) {
    const lit = m[1];
    if (!nsFirstSeg.includes(lit.split(':')[0])) continue;
    if (isRegistered(lit)) continue;
    const line = src.slice(0, m.index).split('\n').length;
    bad.set(lit, `${file}:${line}  ${lit}`);
  }
  return [...bad.values()];
}
{
  const bad = [...scanLiterals(panel, 'panel.html'), ...scanLiterals(server, 'server.py')];
  if (bad.length) {
    fail('B 以下键字面量未在 x_keys.json 登记：\n      ' + bad.join('\n      '));
  } else {
    ok('B 所有键字面量均已登记');
  }
}

/* ---------- C. 派生而非硬编码 ---------- */
{
  if (/setHeavyKeys\s*\(\s*\[/.test(panel)) {
    fail('C panel.html 里 setHeavyKeys 又出现硬编码数组 → 必须用 xHeavyKeys() 派生');
  } else if (!/setHeavyKeys\s*\(\s*xHeavyKeys\(\)/.test(panel)) {
    fail('C panel.html 未调用 setHeavyKeys(xHeavyKeys())');
  } else {
    ok(`C heavyKeys 由注册表派生（当前 ${heavyList.length} 个：${heavyList.join(', ')}）`);
  }
  if (/setProducedKeys\s*\(\s*\[/.test(panel)) {
    fail('C panel.html 里 setProducedKeys 出现硬编码数组 → 必须用 xProducedKeys() 派生');
  } else if (!/setProducedKeys\s*\(\s*xProducedKeys\(\)/.test(panel)) {
    warn('C 未注册 setProducedKeys(xProducedKeys())：pullProduced() 无参调用将取不到默认集合');
  } else {
    ok(`C producedKeys 由注册表派生（当前 ${producedConcrete.length} 个：${producedConcrete.join(', ')})`);
  }
}

/* ---------- D. 产出型键必须有取回调用点 ---------- */
{
  // 代码里常用 KW_CACHE_PFX 这类常量间接拼键名，直接匹配会误报 → 先做「常量→字面量」展开
  const constMap = {};
  {
    const cr = /const\s+([A-Z][A-Z0-9_]*)\s*=\s*'([^']+)'/g;
    let cm;
    while ((cm = cr.exec(panel)) !== null) constMap[cm[1]] = cm[2];
  }
  const expand = (s) => s.replace(/\b[A-Z][A-Z0-9_]*\b/g, (x) => (constMap[x] !== undefined ? constMap[x] : x));
  const windows = [];
  const re = /(pullProduced|pullKeys)\s*\(/g;
  let m;
  while ((m = re.exec(panel)) !== null) windows.push(expand(panel.slice(m.index, m.index + 320)));
  const need = reg.keys.filter((e) => e.fetchVia === 'pullProduced');
  const missing = [];
  for (const e of need) {
    const hit = windows.some((w) => w.includes(e.name));
    if (!hit) missing.push(`${e.name}${e.prefix ? '*' : ''}`);
  }
  if (missing.length) {
    fail('D 以下「服务端产出、需显式取回」的键在 panel.html 找不到取回调用点：\n      '
      + missing.join('\n      ') + '\n      （这类漏取回的表现：提示任务已完成，页面却毫无变化）');
  } else {
    ok(`D ${need.length} 个产出型键都有取回调用点（${need.map((e) => e.name + (e.prefix ? '*' : '')).join(', ')}）`);
  }
}

/* ---------- E. localStorage 键 ---------- */
{
  const missing = reg.localStorage.filter((e) => !panel.includes(e.name)).map((e) => e.name);
  if (missing.length) warn('E 以下 localStorage 键在 panel.html 中找不到字面量：' + missing.join(', '));
  else ok(`E ${reg.localStorage.length} 个 localStorage 键字面量均在场`);
  const neverRead = reg.localStorage.filter((e) => !new RegExp(`(getItem|setItem)\\(\\s*['"]${e.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}['"]`).test(panel)
    && !new RegExp(`['"]${e.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}['"]`).test(panel));
  if (neverRead.length) warn('E 疑似未使用：' + neverRead.map((e) => e.name).join(', '));
}

/* ---------- 汇总 ---------- */
for (const l of oks) console.log('  ok   ' + l);
for (const l of warns) console.log(' WARN  ' + l);
for (const l of fails) console.log(' FAIL  ' + l);
console.log(`\n${fails.length ? '✗' : '✓'} x_guard: ${fails.length} 失败 / ${warns.length} 警告 / ${oks.length} 通过`);
process.exit(fails.length ? 1 : 0);
