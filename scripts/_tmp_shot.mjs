import { chromium } from 'playwright';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));

await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);

// count visible input[type=text] on home
const inputs = await page.$$eval('input[type="text"]', els => els.map(e => ({ ph: e.placeholder, rect: e.getBoundingClientRect() })));
console.log('INPUTS:', JSON.stringify(inputs, null, 2));

await page.screenshot({ path: 'scripts/_tmp_home.png', fullPage: false });

// switch to list view
try {
  const listBtn = await page.$('text=列表');
  if (listBtn) { await listBtn.click(); await page.waitForTimeout(800); }
} catch (e) {}
await page.screenshot({ path: 'scripts/_tmp_home_list.png', fullPage: false });

console.log('ERRORS:', errors.length, errors.slice(0,5));
await browser.close();
