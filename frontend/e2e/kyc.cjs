// KYC document flow: customer uploads ID + selfie, reviewer sees previews and approves.
// Usage: node frontend/e2e/kyc.cjs <dir containing id.png and selfie.png>  (API :8000 with demo data, Vite :5173)
const { chromium } = require('playwright');
const SP = process.argv[2];
(async () => {
  const b = await chromium.launch(); const errs = [];
  async function page(vp) { const p = await (await b.newContext({ viewport: vp })).newPage(); await p.route(/fonts\.(googleapis|gstatic)/, r => r.abort()); p.on('pageerror', e => errs.push(e.message)); return p; }
  const step = async (n, f) => { try { await f(); console.log('✓', n); } catch (e) { console.log('✗', n, e.message.split('\n')[0]); throw e; } };
  const c = await page({ width: 390, height: 900 });
  const email = `kofi${Date.now()}@example.com`;
  await step('register', async () => {
    await c.goto('http://localhost:5173/register');
    await c.getByLabel('Full name').fill('Kofi Asare'); await c.getByLabel('Email').fill(email);
    await c.getByLabel('Mobile number').fill('054' + String(Date.now()).slice(-7)); await c.getByLabel('Password').fill('Str0ngPass!word');
    await c.getByRole('button', { name: 'Create account' }).click(); await c.getByText('Hello, Kofi').waitFor({ timeout: 8000 });
  });
  await step('submit is blocked until required documents are uploaded', async () => {
    await c.goto('http://localhost:5173/app/verification');
    await c.getByLabel('Tier').selectOption('2');
    await c.getByLabel('ID number').fill('GHA-' + String(Date.now()).slice(-9) + '-1');
    await c.getByLabel('First name').fill('Kofi'); await c.getByLabel('Last name').fill('Asare');
    await c.getByLabel('Date of birth').fill('1990-05-17');
    if (!(await c.getByRole('button', { name: 'Submit for verification' }).isDisabled())) throw new Error('button should be disabled');
  });
  await step('upload ID + selfie and submit', async () => {
    await c.getByLabel('ID card — front').setInputFiles(SP + '/id.png');
    await c.getByText('✓ id.png').waitFor();
    await c.getByLabel('Selfie holding your ID').setInputFiles(SP + '/selfie.png');
    await c.getByText('✓ selfie.png').waitFor();
    await c.getByRole('button', { name: 'Submit for verification' }).click();
    await c.getByText('Under review').waitFor({ timeout: 5000 });
    await c.screenshot({ path: SP + '/shots/kyc_customer.png', fullPage: true });
  });
  await step('reviewer sees document images load', async () => {
    const a = await page({ width: 1280, height: 900 });
    await a.goto('http://localhost:5173/login'); await a.getByLabel('Email').fill('admin@fincore.demo'); await a.getByLabel('Password').fill('Demo!Pass2026');
    await a.getByRole('button', { name: 'Sign in' }).click(); await a.waitForTimeout(1500);
    await a.goto('http://localhost:5173/admin/kyc'); await a.getByText('Kofi Asare').last().click();
    const img = a.getByAltText('Id Front'); await img.waitFor();
    await a.waitForFunction(() => [...document.images].filter(i => i.complete && i.naturalWidth > 0).length >= 2, null, { timeout: 5000 });
    await a.screenshot({ path: SP + '/shots/kyc_admin.png' });
    await a.getByRole('dialog').getByRole('button', { name: /Approve/ }).click(); await a.getByText('Review recorded').waitFor();
  });
  console.log('page errors', errs); await b.close();
})();
