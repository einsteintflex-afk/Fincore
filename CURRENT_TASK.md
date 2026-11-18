# Current task

## Direction
Private payment system for the owner's own sites (TD-020): Nurses Hub (nursing studies), healthcare
registration, admission forms/fees, a mini market. MoMo + card. Direct integrations only (TD-019).

## Done
- [x] Sessions 1–2: platform, frontend, docs, settlements, maker-checker, HttpOnly cookie, AML, KYC docs, PDFs,
      settlement-file reconciliation, performance
- [x] Session 3: private mode, payment links with custom questions, receipt verification, pay-button code
- [x] Session 4: card payments (hosted acquirer page, test acquirer with 3-D Secure, refunds to card)
- [x] Session 5: MTN MoMo Collections as the MoMo channel (TD-022); personal-number collection removed
- [x] Session 6: 15-seat private dashboard, verified subscribers, 15% withdrawal fee, MTN Disbursements, app isolation,
      five-section dashboard, backups, Android/Windows builds (see FINCORE_MASTER_PROGRESS.md)

## Next task (start here)
**Owner setup wizard ("Get started" screen).** First sign-in of the primary admin: business name and contact,
settlement destination (no personal collection numbers — TD-022), ready-made application/link templates
(registration form, admission fee, study package, healthcare registration, mini-market), the API keys to copy, and a
go-live checklist read from /console/payments. Tests (API + browser).

Done since last update: real MTN sandbox verified end to end (Collections + Disbursements) — see
FINCORE_MASTER_PROGRESS.md §3. Later: Phase 3 leftovers (Redis rate limiter, malware scanning, Playwright in CI),
iOS/macOS builds on a Mac.
