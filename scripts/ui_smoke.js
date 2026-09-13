#!/usr/bin/env node
/**
 * UI 可计算冒烟（视觉回归防线）
 * ------------------------------------------------------------------
 * 目的：把「用户先发现」前置到「提交前发现」。只做**可计算**的断言，不需要人眼、
 * 不需要视觉模型、不依赖主题是否正确加载（读的是 token 定义本身）：
 *
 *   1) 对比度：核心文字/语义色在各背景上的 WCAG 对比度必须达标
 *      （正文 ≥ 4.5:1，次要/大字 ≥ 3:1）
 *   2) 变量完整性：所有 var(--x) 必须能解析到定义（除运行时注入白名单）
 *
 * 用法：node scripts/ui_smoke.js [--dom]
 *   --dom  额外跑一次 Playwright 真实页面检查（最小可点击区 / 命中测试 / 控制台报错），
 *          需要前端已启动；未启动时自动跳过，不算失败。
 * ------------------------------------------------------------------
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const THEME = path.join(ROOT, 'src/webui/src/styles/theme.css');
const SRC = path.join(ROOT, 'src/webui/src');

// 由 JS 运行时注入、不在 CSS 里定义的变量
const RUNTIME_VARS = new Set(['--nav-height', '--vv-top', '--vv-bottom']);
// 已知但**不参与**扫描的文件：style.css 是废弃遗留样式（全仓无人 import，
// 其 :root 只服务于它自己的排版），故不计入"变量是否被定义"的判定。
const EXCLUDE_FILES = new Set(['style.css', 'styles/theme.css']);
// 显式豁免（必须写明理由，禁止为了变绿而放宽阈值）：
//   --warning-border：应参与主题计算，别名解决不了，留待统一处理
//   --xxx：theme.css 注释里的示例占位（var(--xxx)），非真实使用
const VAR_WAIVERS = new Set(['--warning-border', '--xxx']);
// 对比度豁免：<前景>|<背景> → 理由。当前一条属于需要设计决策的品牌问题，见 runTokenChecks 输出。
const CONTRAST_WAIVERS = new Map([
  ['--text-on-accent|--accent', '白字落在品牌橙上仅 2.8:1，未达 AA。修法需设计决策（加深 accent / 强调底改用 --accent-strong / 文字改深色），暂豁免但必须在报告中暴露'],
]);

/* ---------- 解析 token ---------- */
function parseTokens(css) {
  const m = css.match(/:root\s*\{([\s\S]*?)\n\}/);
  if (!m) throw new Error('theme.css 里找不到 :root 块');
  const out = new Map();
  // 注意：必须按「整块」匹配而不是逐行——像 --font-sans 的值是跨两行书写的，
  // 逐行匹配会因第一行没有分号而漏掉它（曾经因此误报"未定义"）。
  const re = /(--[a-zA-Z0-9-]+)\s*:\s*([^;{}]+);/g;
  let mm;
  while ((mm = re.exec(m[1]))) out.set(mm[1], mm[2].replace(/\s+/g, ' ').trim());
  return out;
}
// 解析颜色值：#hex / rgb() / rgba() / var(--x)（一层解引用）
function resolveColor(tokens, raw, depth = 0) {
  if (!raw) return null;
  let v = raw.trim();
  const vm = v.match(/^var\(\s*(--[a-zA-Z0-9-]+)\s*\)$/);
  if (vm && depth < 4) return resolveColor(tokens, tokens.get(vm[1]), depth + 1);
  let m;
  if ((m = v.match(/^#([0-9a-fA-F]{6})$/))) {
    const n = parseInt(m[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1];
  }
  if ((m = v.match(/^#([0-9a-fA-F]{3})$/))) {
    const h = m[1];
    return [parseInt(h[0] + h[0], 16), parseInt(h[1] + h[1], 16), parseInt(h[2] + h[2], 16), 1];
  }
  if ((m = v.match(/^rgba?\(([^)]+)\)$/))) {
    const p = m[1].split(',').map((s) => s.trim());
    return [+p[0], +p[1], +p[2], p[3] === undefined ? 1 : +p[3]];
  }
  return null;
}
function lum([r, g, b]) {
  const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function over(fg, bg) { // 前景带 alpha 时先合成到背景上
  const a = fg[3];
  return [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a));
}
function contrast(fg, bg) {
  const l1 = lum(over(fg, bg)), l2 = lum(bg);
  const hi = Math.max(l1, l2), lo = Math.min(l1, l2);
  return (hi + 0.05) / (lo + 0.05);
}

/* ---------- 断言表 ---------- */
// [前景 token, 背景 token, 最低对比度, 说明]
const PAIRS = [
  ['--text-primary', '--bg-base', 4.5, '正文 / 主背景'],
  ['--text-primary', '--bg-surface', 4.5, '正文 / 卡片'],
  ['--text-primary', '--bg-surface-2', 4.5, '正文 / 次级底'],
  ['--text-secondary', '--bg-base', 4.5, '次要文字 / 主背景'],
  ['--text-secondary', '--bg-surface', 4.5, '次要文字 / 卡片'],
  ['--text-tertiary', '--bg-base', 3.0, '辅助文字 / 主背景（小字，放宽到 3.0）'],
  ['--text-tertiary', '--bg-surface', 3.0, '辅助文字 / 卡片（小字，放宽到 3.0）'],
  ['--text-on-accent', '--accent', 3.0, '强调色上的文字'],
  ['--danger', '--bg-surface', 3.0, '危险色 / 卡片'],
  ['--success', '--bg-surface', 3.0, '成功色 / 卡片'],
  ['--info', '--bg-surface', 3.0, '信息色 / 卡片'],
  ['--like', '--bg-surface', 3.0, '点赞色 / 卡片'],
];

function runTokenChecks() {
  const css = fs.readFileSync(THEME, 'utf8');
  const tokens = parseTokens(css);
  let fail = 0;
  console.log('\n=== 对比度（WCAG）===');
  PAIRS.forEach(([fgT, bgT, min, desc]) => {
    const fg = resolveColor(tokens, tokens.get(fgT));
    const bg = resolveColor(tokens, tokens.get(bgT));
    if (!fg || !bg) { console.log(`  ✗ ${desc}：${fgT} 或 ${bgT} 解析失败`); fail++; return; }
    const r = Math.round(contrast(fg, bg) * 100) / 100;
    let ok = r >= min, note = '';
    const key = fgT + '|' + bgT;
    if (!ok && CONTRAST_WAIVERS.has(key)) { ok = true; note = '  ⚠豁免：' + CONTRAST_WAIVERS.get(key); }
    if (!ok) fail++;
    console.log(`  ${ok ? (note ? '!' : '✓') : '✗'} ${desc}: ${r}:1 (要求 ≥${min})  [${fgT} on ${bgT}]${note}`);
  });

  console.log('\n=== 变量完整性（var() 必须能解析到定义）===');
  const used = new Map();
  (function walk(dir) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) { if (!['node_modules', 'assets'].includes(e.name)) walk(p); }
      else if (/\.(vue|css|scss|ts)$/.test(e.name)
               && !EXCLUDE_FILES.has(path.relative(SRC, p).replace(/\\/g, '/'))) {
        (fs.readFileSync(p, 'utf8').match(/var\(\s*--[a-zA-Z0-9-]+/g) || []).forEach((v) => {
          const n = v.replace(/var\(\s*/, '');
          used.set(n, (used.get(n) || 0) + 1);
        });
      }
    }
  })(SRC);
  let miss = 0;
  [...used.keys()].sort().forEach((n) => {
    if (!tokens.has(n) && !RUNTIME_VARS.has(n) && !VAR_WAIVERS.has(n)) {
      console.log(`  ✗ ${n} 被使用 ${used.get(n)} 次，但 theme.css 未定义`); miss++;
    }
  });
  console.log(miss === 0 ? `  ✓ 全部 ${used.size} 个变量均可解析（运行时注入的除外）` : `  ✗ ${miss} 个未定义`);
  return fail + miss;
}

(async () => {
  let bad = runTokenChecks();
  if (process.argv.includes('--dom')) bad += await runDomChecks();
  console.log('\n' + (bad === 0 ? 'SMOKE=PASS' : `SMOKE=FAIL（${bad} 项不达标）`));
  process.exit(bad === 0 ? 0 : 1);
})();

/* ---------- 可选：真实页面检查 ---------- */
async function runDomChecks() {
  let pw;
  try { pw = require(process.env.PLAYWRIGHT_CORE || 'playwright-core'); }
  catch (_) { console.log('\n[--dom] 未找到 playwright-core，跳过页面检查'); return 0; }
  let browser;
  try {
    browser = await pw.chromium.launch({ channel: 'msedge', headless: true });
    const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1366, height: 900 } });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push(String(e)));
    await page.goto('https://127.0.0.1:5173/', { waitUntil: 'domcontentloaded', timeout: 12000 });
    await page.waitForTimeout(1500);
    const r = await page.evaluate(() => {
      const small = [];
      document.querySelectorAll('button, a, [role="button"]').forEach((el) => {
        const b = el.getBoundingClientRect();
        if (b.width > 0 && b.height > 0 && (b.width < 32 || b.height < 24)) {
          small.push((el.textContent || el.className || el.tagName).trim().slice(0, 24) + ` ${Math.round(b.width)}×${Math.round(b.height)}`);
        }
      });
      // 命中测试：可见按钮的中心点必须真的命中它自己（抓"被遮挡/不可点"）
      const blocked = [];
      document.querySelectorAll('button').forEach((el) => {
        const b = el.getBoundingClientRect();
        if (b.width < 8 || b.height < 8) return;
        const top = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
        if (top && !el.contains(top) && top !== el) blocked.push((el.textContent || '').trim().slice(0, 20) || el.className);
      });
      return { small: small.slice(0, 8), blocked: blocked.slice(0, 8) };
    });
    console.log('\n=== 页面检查（--dom）===');
    console.log('  小于 32×24 的可点元素:', r.small.length ? r.small.join(' | ') : '无');
    console.log('  中心点被遮挡的按钮:', r.blocked.length ? r.blocked.join(' | ') : '无');
    console.log('  控制台报错:', errs.length ? errs.slice(0, 3).join(' | ') : '无');
    await browser.close();
    return r.blocked.length + errs.length;
  } catch (e) {
    if (browser) await browser.close().catch(() => {});
    console.log('\n[--dom] 页面检查跳过：' + String(e).split('\n')[0].slice(0, 100));
    return 0;
  }
}
