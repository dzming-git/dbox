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
  const cAll = await count();
  console.log('A: all items =', cAll);
  // type tabs: find 功能建议
  const typeTab = async (label) => page.evaluate((lbl) => {
    const t = Array.from(document.querySelectorAll('.fb-type-tab')).find(e => e.textContent.includes(lbl));
    if (t) { t.click(); return true; } return false;
  }, label);
  // status tabs: find 待验证 / 已关闭
  const statusTab = async (label) => page.evaluate((lbl) => {
    const t = Array.from(document.querySelectorAll('.fb-tab')).find(e => e.textContent.includes(lbl));
    if (t) { t.click(); return true; } return false;
  }, label);
  // TEST 1: type filter 功能建议 then 全部
  let ok = await typeTab('功能建议');
  console.log('click 功能建议:', ok);
  await sleep(1000);
  console.log('B: after type=功能建议 items =', await count());
  await page.screenshot({ path: '_tmp_fb_type.png' });
  ok = await typeTab('全部');
  console.log('click 全部(type):', ok);
  await sleep(1000);
  console.log('C: after back-to-all(type) items =', await count());
  // TEST 2: status filter 待验证 (empty) then 全部
  ok = await statusTab('待验证');
  console.log('click 待验证:', ok);
  await sleep(1000);
  console.log('D: after status=待验证 items =', await count());
  ok = await statusTab('全部');
  console.log('click 全部(status):', ok);
  await sleep(1000);
  console.log('E: after back-to-all(status) items =', await count());
  await page.screenshot({ path: '_tmp_fb_final.png' });
  await browser.close();
})();
