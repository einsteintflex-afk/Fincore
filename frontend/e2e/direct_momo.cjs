// 'Pay to my MoMo number': owner enables it, payer submits a transaction ID, owner confirms.
// Usage: node frontend/e2e/direct_momo.cjs <shots-dir> <payment-link-slug-with-questions> <owner-momo-number e.g. 0551234567>
const { chromium } = require('playwright');
(async () => {
  const [SP, slug, number] = process.argv.slice(2); const b = await chromium.launch(); const errs = [];
  const step = async (n, f) => { try { await f(); console.log('✓', n); } catch (e) { console.log('✗', n, e.message.split('\n')[0]); throw e; } };
  async function page(vp) { const p = await (await b.newContext({ viewport: vp })).newPage(); await p.route(/fonts\.(googleapis|gstatic)/, r => r.abort()); p.on('pageerror', e => errs.push(e.message)); return p; }
  const m = await page({ width: 1280, height: 900 });
  let base;
  await step('owner turns on "Pay to my MoMo number"', async () => {
    await m.goto('http://localhost:5173/login'); await m.getByLabel('Email').fill('kofi@fincore.demo'); await m.getByLabel('Password').fill('Demo!Pass2026');
    await m.getByRole('button', { name: 'Sign in' }).click(); await m.waitForTimeout(1500);
    await m.goto('http://localhost:5173/merchant'); await m.waitForTimeout(1200); base = m.url();
    await m.goto(base + '/settings'); await m.waitForTimeout(800);
    await m.getByLabel('Accept MoMo transfers to my number').check();
    await m.getByLabel('Your MoMo number').fill(number);
    await m.getByLabel('Name on the MoMo account (shown to payers)').fill('Nurses Hub');
    await m.locator('form', { hasText: 'Accept MoMo transfers' }).getByRole('button', { name: 'Save' }).click();
    await m.getByText('Payers can now send MoMo to your number').waitFor();
  });
  const p = await page({ width: 390, height: 900 });
  const txid = 'MP' + Date.now();
  await step('payer sends MoMo and submits the transaction ID', async () => {
    await p.goto('http://localhost:5173/pay/' + slug);
    await p.getByLabel('Your name').fill('Akua Boateng');
    await p.getByLabel('Programme').selectOption({ index: 1 });
    await p.getByLabel('Index number').fill('IDX-' + Date.now());
    await p.getByLabel('Phone').fill('0201234567');
    await p.getByRole('button', { name: 'Continue to payment' }).click();

    await p.getByText('Send GH₵150.00 by MoMo to:').waitFor({ timeout: 5000 });
    await p.getByText(number.replace(/(\d{3})(\d{3})(\d{4})/, '$1 $2 $3')).waitFor();
    await p.screenshot({ path: SP + '/shots/direct_payer.png', fullPage: true });
    await p.getByLabel('MoMo transaction ID (from your SMS)').fill(txid);
    await p.getByLabel('Number you sent from').fill('0201234567');
    await p.getByRole('button', { name: 'I have sent the money' }).click();
    await p.getByText('Payment sent — waiting for confirmation').waitFor();
  });
  await step('owner sees it and confirms', async () => {
    await m.goto(base + '/payments'); await m.waitForTimeout(1000);
    await m.getByText(/MoMo payments? to confirm/).waitFor();
    await m.screenshot({ path: SP + '/shots/direct_owner.png' });
    await m.getByText(txid).click();
    await m.getByRole('button', { name: 'Confirm received' }).click();
    await m.getByText('Payment confirmed — receipt is ready').waitFor();
  });
  await step("payer's page turns to Payment successful", async () => {
    await p.getByText('Payment successful').waitFor({ timeout: 10000 });
  });
  console.log('page errors', errs); await b.close();
})();
