# Current task

## Direction
Private payment system for the owner's own sites (TD-020): Nurses Hub (nursing studies), healthcare
registration, admission forms/fees, a mini market. MoMo + card. Direct integrations only (TD-019).

## Done
- [x] Sessions 1–2: platform, frontend, docs, settlements, maker-checker, HttpOnly cookie, AML, KYC docs, PDFs,
      settlement-file reconciliation, performance
- [x] Session 3: private mode, payment links with custom questions, receipt verification, pay-button code
- [x] Session 4: card payments (hosted acquirer page, test acquirer with 3-D Secure, refunds to card)

## Next task (start here)
**Owner setup wizard ("Get started" screen) for the private deployment.**

Acceptance criteria:
- First sign-in of a super admin with no businesses shows a guided screen: business name (e.g. Nurses Hub),
  contact email/phone, settlement MoMo number or bank account; creates and auto-approves the business
  (owner is the platform admin) and sets the settlement destination.
- Step 2 offers ready-made link templates the owner can tick and price: Registration form, Admission fee,
  Study package/exam prep, Healthcare registration, Mini-market checkout (amount entered by payer), each with
  sensible default questions (full name, phone, programme, index number) that remain editable.
- Step 3 shows the links and pay-button code to copy, and a checklist of what's still needed to go live
  (MTN keys, acquiring bank, BoG licence) with status read from /admin/providers.
- Tests (API + browser).

Afterwards: Phase 3 leftovers (Redis rate limiter, Playwright in CI, malware scanning, maker-checker for
fees/limits, goAML).
