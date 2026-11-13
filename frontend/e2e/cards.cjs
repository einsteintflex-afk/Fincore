// Card checkout in test mode: approve, 3-D Secure, and abandon-then-MoMo. Usage: node frontend/e2e/cards.cjs <shots-dir> <payment-link-slug-with-questions>
const { chromium } = require('playwright');
(async () => {
  const [SP, slug] = process.argv.slice(2); const b = await chromium.launch(); const errs = [];
  const step = async (n, f) => { try { await f(); console.log('✓', n); } catch (e) { console.log('✗', n, e.message.split('\n')[0]); throw e; } };
  async function payer() { const p = await (await b.newContext({ viewport: { width: 390, height: 900 } })).newPage(); await p.route(/fonts\.(googleapis|gstatic)/, r => r.abort()); p.on('pageerror', e => errs.push(e.message)); return p; }
  async function toCheckout(p) {
    await p.goto('http://localhost:5173/pay/' + slug);
    await p.getByLabel('Your name').fill('Esi Card');
    await p.getByLabel('Programme').selectOption({ index: 1 });
    await p.getByLabel('Index number').fill('IDX-' + Date.now());
    await p.getByLabel('Phone').fill('0241234567');
    await p.getByRole('button', { name: 'Continue to payment' }).click();
    await p.getByRole('button', { name: 'Card', exact: true }).click();
  }
  await step('card approved and returned to checkout', async () => {
    const p = await payer(); await toCheckout(p);
    await p.getByRole('button', { name: /Pay GH₵/ }).click();
    await p.getByText('TEST MODE — simulated bank card page').waitFor({ timeout: 8000 });
    await p.screenshot({ path: SP + '/shots/card_page.png' });
    await p.getByText('Test cards').click(); await p.getByRole('button', { name: /4111 1111 1111 1111/ }).click();
    await p.getByRole('button', { name: /Pay GH₵/ }).click();
    await p.getByText('Payment approved').waitFor();
    await p.getByText('Payment successful').waitFor({ timeout: 10000 });
    await p.screenshot({ path: SP + '/shots/card_success.png' });
  });
  await step('3-D Secure approve', async () => {
    const p = await payer(); await toCheckout(p);
    await p.getByRole('button', { name: /Pay GH₵/ }).click();
    await p.getByLabel('Card number').fill('4000000000003220'); await p.getByLabel('Expiry (MM/YY)').fill('1230'); await p.getByLabel('CVC').fill('123');
    await p.getByRole('button', { name: /Pay GH₵/ }).click();
    await p.getByText('Bank verification (test)').waitFor(); await p.screenshot({ path: SP + '/shots/card_3ds.png' });
    await p.getByRole('button', { name: 'Approve' }).click();
    await p.getByText('Payment successful').waitFor({ timeout: 10000 });
  });
  await step('abandoned card page, then pay by MoMo', async () => {
    const p = await payer(); await toCheckout(p);
    await p.getByRole('button', { name: /Pay GH₵/ }).click();
    await p.getByText('TEST MODE — simulated bank card page').waitFor();
    await p.goBack(); await p.waitForTimeout(1500);
    await p.getByText("Your card payment wasn't completed").waitFor({ timeout: 8000 });
    await p.getByRole('button', { name: 'Mobile money' }).click();
    await p.getByLabel('Mobile money number').fill('0241234567');
    await p.getByRole('button', { name: /Pay GH₵/ }).click();
    await p.getByText('Payment successful').waitFor({ timeout: 10000 });
  });
  console.log('page errors', errs); await b.close();
})();
