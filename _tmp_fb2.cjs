const { chromium } = require('C:\\Users\\<用户>\\AppData\\Local\\npm-cache\\_npx\\db89d7302a373f10\\node_modules\\playwright');
const BASE = 'http://127.0.0.1:5173';
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(BASE + '/login', { waitUntil: 'networkidle' });
  await sleep(600);
  await page.fill('input[type="text"]', 'root');
  await page.fill('input[type="password"]', '<初始密码>');
  await page.click('button[type="submit"]').catch(async()=>{ await page.keyboard.press('Enter'); });
  await sleep(1500);
  await page.goto(BASE + '/feedback', { waitUntil: 'networkidle' });
  await sleep(1500);
  const count = async () => page.$$eval('.fb-item', els => els.length);
  // 1. click a type filter (功能建议)
  const clickedType = await page.evaluate(() => {
    const t = Array.from(document.querySelectorAll('.fb-type-tab')).find(e => e.textContent.includes('功能建议'));
    if (t) { t.click(); return t.textContent.trim(); } return null;
  });
  console.log('1. clicked type:', clickedType);
  await sleep(800);
  console.log('   items after type filter =', await count());
  // 2. type keyword into search box (find input with placeholder containing 搜索/关键词)
  const kwInput = await page.$('input[placeholder*="搜索"], input[placeholder*="关键词"]');
  if (kwInput) {
    await kwInput.fill('2026');
    console.log('2. typed keyword 2026');
    await sleep(1500); // wait debounce
    console.log('   items after keyword =', await count());
    await page.screenshot({ path: '_tmp_fb_kw.png' });
  } else {
    console.log('2. no keyword input found');
  }
  // 3. "exit": click first item to open detail, then back
  const first = await page.$('.fb-item');
  if (first) { await first.click(); await sleep(800); console.log('3. opened detail'); }
  const back = await page.$('.fb-back');
  if (back) { await back.click(); await sleep(800); console.log('   back to list'); }
  // 4. click 全部 (status)
  await page.evaluate(() => {
    const t = Array.from(document.querySelectorAll('.fb-tab')).find(e => e.textContent.includes('全部'));
    if (t) t.click();
  });
  await sleep(1200);
  const cFinal = await count();
  console.log('4. items after back-to-all =', cFinal, '(expected 3)');
  await page.screenshot({ path: '_tmp_fb_final2.png' });
  await browser.close();
})();
