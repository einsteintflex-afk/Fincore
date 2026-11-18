// Browser check of the five-section dashboard, applications, settings tabs and the withdrawal fee review.
// Usage: node frontend/e2e/console.cjs <screenshots-dir>   (API on :8000, Vite on :5173, demo data loaded)
const { chromium } = require("playwright");
const path = require("path");

const BASE = "http://localhost:5173";
const out = process.argv[2] || ".";
const PW = "Demo!Pass2026";

(async () => {
  const browser = await chromium.launch();
  const errors = [];
  const results = [];
  const step = (name, ok, extra = "") => {
    results.push(`${ok ? "PASS" : "FAIL"} ${name}${extra ? " — " + extra : ""}`);
    if (!ok) process.exitCode = 1;
  };

  async function session(viewport) {
    const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1 });
    await ctx.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
    page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(`console: ${m.text()}`));
    return { ctx, page };
  }
  async function login(page, email) {
    await page.goto(`${BASE}/login`);
    await page.fill('input[type="email"]', email);
    await page.fill('input[type="password"]', PW);
    await page.click('button[type="submit"]');
    await page.waitForTimeout(1500);
  }

  // ---- administrator: five sections
  const { ctx, page } = await session({ width: 1366, height: 900 });
  await login(page, "admin@fincore.demo");
  step("admin lands on the dashboard", page.url().endsWith("/console"), page.url());
  const nav = await page.locator("aside nav a").allInnerTexts();
  step("exactly five primary sections", JSON.stringify(nav.map((s) => s.trim())) === JSON.stringify(["Overview", "Applications", "Transactions", "Payments", "Settings"]), nav.join(","));
  await page.waitForSelector("text=Total collections");
  step("overview shows totals and system status", (await page.locator("text=System status").count()) > 0 && (await page.locator("text=Withdrawal fees collected").count()) > 0);
  await page.screenshot({ path: path.join(out, "console-overview.png"), fullPage: true });

  await page.click("aside >> text=Applications");
  await page.click("text=Register application");
  const appName = `Send Me ${Date.now() % 100000}`;
  await page.fill('input[placeholder="Send Me"]', appName);
  await page.click('form >> button:has-text("Register")');
  await page.waitForTimeout(1500);
  step("application registered and opened", /\/console\/applications\/[0-9a-f-]{36}$/.test(page.url()), page.url());
  await page.click("text=New test key");
  await page.waitForTimeout(800);
  step("API key secret shown once", (await page.locator("text=it will not be shown again").count()) > 0);
  await page.screenshot({ path: path.join(out, "console-application.png"), fullPage: true });

  await page.click("aside >> text=Transactions");
  await page.waitForSelector("text=Transaction monitoring");
  step("transactions section with search and filters", (await page.locator('input[placeholder="Reference / provider ref"]').count()) === 1);

  await page.click("aside >> text=Payments");
  await page.waitForSelector("text=MTN MoMo");
  step("payments shows MTN collections and disbursements", (await page.locator("text=Disbursements (Transfer)").count()) === 1);
  await page.screenshot({ path: path.join(out, "console-payments.png"), fullPage: true });

  for (const [tab, marker] of [["users", "seats used"], ["subscribers", "Verified subscribers"], ["fee", "Withdrawal fee:"], ["security", "Two-factor"], ["api", "API & webhooks"], ["audit", "Audit log"], ["backups", "Database backups"], ["system", "Fee"]]) {
    await page.goto(`${BASE}/console/settings/${tab}`);
    await page.waitForTimeout(1200);
    step(`settings → ${tab}`, (await page.locator(`text=${marker}`).count()) > 0);
    if (tab === "users") await page.screenshot({ path: path.join(out, "console-users.png"), fullPage: true });
    if (tab === "fee") await page.screenshot({ path: path.join(out, "console-fee.png"), fullPage: true });
  }
  await ctx.close();

  // ---- wallet user: withdrawal shows the fee before confirming (phone width)
  const m = await session({ width: 390, height: 844 });
  await login(m.page, "ama@fincore.demo");
  await m.page.goto(`${BASE}/app/withdraw`);
  await m.page.waitForTimeout(1200);
  await m.page.fill('input[inputmode="decimal"]', "100");
  await m.page.click('button:has-text("Review")');
  await m.page.waitForTimeout(1000);
  const net = await m.page.locator('[data-testid="Recipient receives"]').innerText().catch(() => "");
  const fee = await m.page.locator('[data-testid="Withdrawal fee (15%)"]').innerText().catch(() => "");
  step("withdrawal review shows 15% fee and net 85", /15\.00/.test(fee) && /85\.00/.test(net), `${fee} / ${net}`);
  await m.page.screenshot({ path: path.join(out, "mobile-withdraw-review.png"), fullPage: true });
  const overflow = await m.page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  step("no horizontal scroll at phone width", !overflow);
  await m.page.click('button:has-text("Confirm withdrawal")');
  await m.page.waitForTimeout(2000);
  step("withdrawal completes", (await m.page.locator("text=/successful|processing/i").count()) > 0);
  await m.ctx.close();

  await browser.close();
  console.log(results.join("\n"));
  console.log(errors.length ? `ERRORS:\n${errors.join("\n")}` : "0 console/page errors");
  if (errors.length) process.exitCode = 1;
})();
