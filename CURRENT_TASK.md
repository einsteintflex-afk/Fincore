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
**Real MTN sandbox end-to-end test.** Owner first removes the environment network secret for
sandbox.momodeveloper.mtn.com and sets fresh sandbox keys in the server environment
(`FINCORE_MTN_SANDBOX_COLLECTION_*`, `FINCORE_MTN_DISBURSEMENT_PRIMARY_KEY` + `FINCORE_MTN_SANDBOX_DISBURSEMENT_API_USER/KEY`).
Acceptance: token login 200 for both products; a RequestToPay to an MTN sandbox test number reaches SUCCESSFUL and
credits the wallet; a Transfer reaches SUCCESSFUL and books the 15% fee; results recorded in FINCORE_MASTER_PROGRESS.md.

Then: owner setup wizard (business name, settlement account, link templates, go-live checklist); Phase 3 leftovers
(Redis rate limiter, malware scanning, Playwright in CI); iOS/macOS builds on a Mac.
