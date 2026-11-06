// End-to-end customer journey. Usage: node e2e/journey.cjs <screenshot-dir> <recipient-account-no> <payment-link-slug>
// Requires the API (port 8000, demo data loaded) and Vite dev server (port 5173) to be running.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const page = await (await b.newContext({ viewport: { width: 390, height: 844 } })).newPage();
  await page.route(/fonts\.(googleapis|gstatic)/, r => r.abort());
  const errs = []; page.on('pageerror', e => errs.push(e.message));
  const step = async (name, fn) => { try { await fn(); console.log('✓', name); } catch (e) { console.log('✗', name, e.message.split('\n')[0]); await page.screenshot({ path: process.argv[2] + '/fail.png' }); throw e; } };
  const email = `yaw${Date.now()}@example.com`;
  await step('register', async () => {
    await page.goto('http://localhost:5173/register');
    await page.getByLabel('Full name').fill('Yaw Darko');
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Mobile number').fill('0244556677');
    await page.getByLabel('Password').fill('Str0ngPass!word');
    await page.getByRole('button', { name: 'Create account' }).click();
    await page.getByText('Hello, Yaw').waitFor({ timeout: 8000 });
  });
  await step('deposit 150 via momo', async () => {
    await page.goto('http://localhost:5173/app/deposit');
    await page.getByLabel('Amount (GHS)').fill('150');
    await page.getByRole('button', { name: 'Request payment' }).click();
    await page.getByText('Successful').first().waitFor({ timeout: 8000 });
  });
  await step('send 40 to Ama', async () => {
    await page.goto('http://localhost:5173/app/send');
    await page.getByLabel('Recipient FinCore account number').fill(process.argv[3]);
    await page.getByText('Ama Owusu').waitFor({ timeout: 5000 });
    await page.getByLabel('Amount (GHS)').fill('40');
    await page.getByRole('button', { name: 'Review transfer' }).click();
    await page.getByRole('button', { name: /Send GH₵40.00/ }).click();
    await page.getByText('Successful').first().waitFor({ timeout: 8000 });
  });
  await step('balance is 110.00', async () => {
    await page.goto('http://localhost:5173/app');
    await page.getByText('GH₵110.00').first().waitFor({ timeout: 5000 });
  });
  await step('tier-0 limit is enforced in UI', async () => {
    await page.goto('http://localhost:5173/app/deposit');
    await page.getByLabel('Amount (GHS)').fill('300');
    await page.getByRole('button', { name: 'Request payment' }).click();
    await page.getByText(/per-transaction limit/).waitFor({ timeout: 5000 });
  });
  await step('anonymous payment-link checkout', async () => {
    const c = await b.newContext(); const p = await c.newPage();
    await p.route(/fonts\.(googleapis|gstatic)/, r => r.abort());
    await p.goto('http://localhost:5173/pay/' + process.argv[4]);
    await p.getByLabel('Amount (GHS)').fill('25.50');
    await p.getByRole('button', { name: 'Continue to payment' }).click();
    await p.getByLabel('Mobile money number').fill('0201234567');
    await p.getByRole('button', { name: /Pay GH₵25.50/ }).click();
    await p.getByText('Payment successful').waitFor({ timeout: 8000 });
    await p.screenshot({ path: process.argv[2] + '/shots/checkout_success.png' });
  });
  console.log('page errors:', errs);
  await b.close();
})();
