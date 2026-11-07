// Admin uploads a provider CSV with a wrong amount and sees the discrepancy. Usage: node frontend/e2e/recon.cjs <dir with settlement.csv>
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const errs = []; const SP = process.argv[2];
  const p = await (await b.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  await p.route(/fonts\.(googleapis|gstatic)/, r => r.abort()); p.on('pageerror', e => errs.push(e.message));
  await p.goto('http://localhost:5173/login'); await p.getByLabel('Email').fill('admin@fincore.demo'); await p.getByLabel('Password').fill('Demo!Pass2026');
  await p.getByRole('button', { name: 'Sign in' }).click(); await p.waitForTimeout(1500);
  await p.goto('http://localhost:5173/admin/finance'); await p.waitForTimeout(800);
  await p.getByLabel('Provider').selectOption('sandbox');
  await p.getByLabel('CSV file').setInputFiles(SP + '/settlement.csv');
  await p.getByRole('button', { name: 'Upload & reconcile' }).click();
  await p.getByText('Amount differs').waitFor({ timeout: 5000 }); console.log('✓ discrepancy shown');
  await p.getByText('provider GH₵1,499.00 vs FinCore GH₵1,500.00').waitFor(); console.log('✓ amounts explained');
  await p.screenshot({ path: SP + '/shots/recon.png' });
  await p.getByRole('dialog').getByRole('link').first().click(); await p.waitForTimeout(1200);
  const rows = await p.locator('tbody tr').count(); console.log(rows === 1 ? '✓' : '✗', 'link opens transaction search, rows:', rows);
  console.log('page errors', errs); await b.close();
})();
