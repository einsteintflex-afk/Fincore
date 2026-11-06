// Visits every page of the four portals as the demo users and reports console/page errors and 5xx responses.
// Usage: node frontend/e2e/smoke.cjs <screenshot-dir>   (API on :8000 with demo data, Vite on :5173)
const { chromium } = require('playwright');
const SP = process.argv[2] || "."; require("fs").mkdirSync(SP + "/shots", { recursive: true });
(async () => {
  const browser = await chromium.launch();
  const errors = [];
  async function session(email, paths, prefix) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
    const page = await ctx.newPage(); await page.route(/fonts\.(googleapis|gstatic)/, r => r.abort());
    page.on('pageerror', e => errors.push(`${prefix} pageerror ${page.url()}: ${e.message}`));
    page.on('console', m => { if (m.type() === 'error') errors.push(`${prefix} console ${page.url()}: ${m.text()}`); });
    page.on('response', r => { if (r.status() >= 500) errors.push(`${prefix} HTTP ${r.status()} ${r.url()}`); });
    await page.goto('http://localhost:5173/login');
    await page.fill('input[type=email]', email);
    await page.fill('input[type=password]', 'Demo!Pass2026');
    await page.click('button[type=submit]');
    await page.waitForTimeout(1500);
    for (const p of paths) {
      await page.goto('http://localhost:5173' + p);
      await page.waitForTimeout(900);
      await page.waitForTimeout(400);
      const name = prefix + p.replace(/[\/:]/g, '_');
      await page.screenshot({ path: `${SP}/shots/${name}.png`, fullPage: false });
      const text = await page.locator('main, body').first().innerText();
      if (/Something went wrong|404/.test(text.slice(0, 300))) errors.push(`${prefix} suspicious content at ${p}: ${text.slice(0,120)}`);
    }
    await ctx.close();
  }
  await session('ama@fincore.demo', ['/app', '/app/send', '/app/deposit', '/app/withdraw', '/app/transactions', '/app/beneficiaries', '/app/statements', '/app/verification', '/app/security', '/app/support'], 'cust');
  // merchant: find biz id via redirect
  const ctx = await browser.newContext(); const pg = await ctx.newPage();
  await pg.goto('http://localhost:5173/login'); await pg.fill('input[type=email]', 'kofi@fincore.demo'); await pg.fill('input[type=password]', 'Demo!Pass2026'); await pg.click('button[type=submit]'); await pg.waitForTimeout(1200);
  await pg.goto('http://localhost:5173/merchant'); await pg.waitForTimeout(1500); const biz = pg.url().split('/merchant/')[1]; await ctx.close();
  const mp = ['', '/payments', '/links', '/transactions', '/settlements', '/reports', '/team', '/settings'].map(s => `/merchant/${biz}${s}`);
  await session('kofi@fincore.demo', [...mp, `/developer/${biz}`, `/developer/${biz}/docs`], 'merch');
  await session('admin@fincore.demo', ['/admin', '/admin/users', '/admin/kyc', '/admin/businesses', '/admin/transactions', '/admin/fraud', '/admin/finance', '/admin/config', '/admin/support', '/admin/audit', '/admin/approvals'], 'admin');
  // public
  const c2 = await browser.newContext({ viewport: { width: 390, height: 844 } }); const p2 = await c2.newPage();
  p2.on('pageerror', e => errors.push(`public pageerror: ${e.message}`));
  await p2.goto('http://localhost:5173/'); await p2.waitForTimeout(800); await p2.screenshot({ path: `${SP}/shots/public_landing_mobile.png` });
  console.log(JSON.stringify({ biz, errors }, null, 1));
  await browser.close();
})();
