// Private mode + payment link with questions + payer flow + receipt verification. Usage: node frontend/e2e/private_links.cjs <shots-dir>  (run `python -m app.cli private-mode on` first)
const { chromium } = require('playwright'); const { execSync } = require('child_process');
(async () => {
  const SP = process.argv[2]; const b = await chromium.launch(); const errs = [];
  async function page(vp) { const p = await (await b.newContext({ viewport: vp })).newPage(); await p.route(/fonts\.(googleapis|gstatic)/, r => r.abort()); p.on('pageerror', e => errs.push(e.message)); return p; }
  const step = async (n, f) => { try { await f(); console.log('✓', n); } catch (e) { console.log('✗', n, e.message.split('\n')[0]); throw e; } };
  const pub = await page({ width: 390, height: 900 });
  await step('private landing + sign-up closed', async () => {
    await pub.goto('http://localhost:5173/'); await pub.getByText('Private payment system').waitFor();
    await pub.screenshot({ path: SP + '/shots/private_landing.png' });
    await pub.goto('http://localhost:5173/register'); await pub.getByText('Sign-up is closed').waitFor();
  });
  const m = await page({ width: 1280, height: 900 });
  let slug;
  await step('owner creates link with questions', async () => {
    await m.goto('http://localhost:5173/login'); await m.getByLabel('Email').fill('kofi@fincore.demo'); await m.getByLabel('Password').fill('Demo!Pass2026');
    await m.getByRole('button', { name: 'Sign in' }).click(); await m.waitForTimeout(1500);
    await m.goto('http://localhost:5173/merchant'); await m.waitForTimeout(1200);
    await m.goto(m.url() + '/links'); await m.waitForTimeout(800);
    await m.getByRole('button', { name: 'New link' }).click();
    const title = 'Nursing admission form ' + Date.now().toString().slice(-4);
    await m.getByLabel('Title (what people are paying for)').fill(title);
    await m.getByLabel(/Price in GHS/).fill('150');
    for (const [i, label, type] of [[1, 'Programme', 'select'], [2, 'Index number', 'text'], [3, 'Phone', 'phone']]) {
      await m.getByRole('button', { name: 'Add question' }).click();
      await m.getByLabel(`Question ${i}`).fill(label);
      await m.getByLabel(`Answer type ${i}`).selectOption(type);
      if (type === 'select') await m.getByPlaceholder(/Choices separated by commas/).fill('Registered Nursing, Midwifery');
    }
    await m.screenshot({ path: SP + '/shots/link_editor.png' });
    await m.getByRole('button', { name: 'Create link' }).click(); await m.getByText('Payment link created').waitFor();
    const row = m.locator('li', { hasText: title });
    slug = (await row.locator('p.font-mono').innerText()).split('/pay/')[1];
    await row.getByRole('button', { name: 'Button code' }).click(); await m.getByText('Pay button for your website').waitFor();
    await m.screenshot({ path: SP + '/shots/button_code.png' });
  });
  let ref;
  await step('payer answers questions and pays', async () => {
    await pub.goto('http://localhost:5173/pay/' + slug);
    await pub.getByRole('button', { name: 'Continue to payment' }).click();
    await pub.waitForTimeout(300);
    await pub.getByLabel('Your name').fill('Abena Mensah');
    await pub.getByLabel('Programme').selectOption('Midwifery');
    await pub.getByLabel('Index number').fill('NMC/2026/0147');
    await pub.getByLabel('Phone').fill('0241234567');
    await pub.screenshot({ path: SP + '/shots/pay_form.png' });
    await pub.getByRole('button', { name: 'Continue to payment' }).click();
    await pub.getByLabel('Mobile money number').fill('0241234567');
    await pub.getByRole('button', { name: /Pay GH₵150.00/ }).click();
    await pub.getByText('Payment successful').waitFor({ timeout: 8000 });
    ref = pub.url().split('/checkout/')[1];
  });
  await step('office verifies the receipt', async () => {
    const code = execSync(`cd /home/user/Fincore/backend && ../.venv/bin/python -c "from app.services.forms import receipt_code; print(receipt_code('${ref}'))"`).toString().trim();
    await pub.goto(`http://localhost:5173/verify?reference=${ref}&code=${code}`);
    await pub.getByRole('button', { name: 'Check receipt' }).click();
    await pub.getByText('Genuine and paid.').waitFor(); await pub.getByText('NMC/2026/0147').waitFor();
    await pub.screenshot({ path: SP + '/shots/verify.png', fullPage: true });
    await pub.getByLabel('Verification code').fill('AAAAA-BBBBB'); await pub.getByRole('button', { name: 'Check receipt' }).click();
    await pub.getByText('No genuine FinCore receipt').waitFor();
  });
  console.log('page errors', errs); await b.close();
})();
