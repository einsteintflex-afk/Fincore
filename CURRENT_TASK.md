# Current task

## Direction
Private payment system for the owner's own sites (TD-020): Nurses Hub (nursing studies), healthcare
registration, admission forms/fees, a mini market. MoMo + card. Direct integrations only (TD-019).

## Done
- [x] Sessions 1–2: platform, frontend, docs, settlements, maker-checker, HttpOnly cookie, AML, KYC docs, PDFs,
      settlement-file reconciliation, performance
- [x] Session 3: private mode, payment links with custom questions, receipt verification, pay-button code

## Next task (start here)
**Card payments — bank-acquirer adapter + sandbox card flow.**

Acceptance criteria:
- `CardAcquirerProvider` interface: create hosted-payment session (amount, reference, return URL) → redirect
  URL; verify result on return/callback; refund. FinCore never sees card numbers (bank's hosted page).
- Sandbox implementation: a FinCore-hosted *simulated* card page clearly marked TEST with test card numbers
  (e.g. 4000 0000 0000 0002 success, …0119 declined, …3220 requires 3-D Secure approve/decline).
- Checkout shows "Card" next to "Mobile money"; card payments post the same ledger journal as MoMo via a
  `PROVIDER_CLEARING:<ACQUIRER>` account; refunds go back through the acquirer.
- Config placeholders for the chosen bank (`FINCORE_CARD_ACQUIRER=sandbox|<bank>`, merchant ID, keys).
- Tests + browser test.

Afterwards: owner-friendly onboarding (create "Nurses Hub" business + its fee links from a guided screen), then
Phase 3 leftovers (Redis rate limiter, Playwright in CI, malware scanning, maker-checker for fees/limits, goAML).
