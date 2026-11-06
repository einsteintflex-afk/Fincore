# Current task

## Done (session 1)
- [x] Backend foundation (ledger, wallets, payments, providers, developer, admin)
- [x] Frontend (customer, merchant, developer, admin portals + checkout), browser-verified
- [x] Documentation set, docker-compose, CI, load test
- [x] Phase 3.1 Scheduled daily/weekly settlements
- [x] Phase 3.2 Maker-checker approvals for large adjustments/reversals
- [x] Phase 3.3 Refresh token in HttpOnly cookie + CSRF header (browser-verified)
- [x] Phase 3.4 AML monitoring scenarios + CSV case export

## Next task (start here)
**Phase 3.5 — KYC document upload.**

Acceptance criteria:
- Storage abstraction `app/services/storage.py` with a local-filesystem backend (dev/test) and an
  S3-compatible backend configured by env vars (bucket, region, endpoint, credentials) — no paid account
  needed to develop; document the production settings.
- `POST /me/kyc/documents` (multipart: `kind` = id_front | id_back | selfie | proof_of_address, file) →
  validates type (JPEG/PNG/PDF by magic bytes) and size (≤ 5 MB), stores under a random key, returns a
  document id. `KycIn.documents` references uploaded ids; tier ≥ 2 requires id_front + selfie.
- Staff view documents through a short-lived signed URL (`GET /admin/kyc/{id}/documents/{doc}`), audit-logged.
- Files are never served from a public path; client filenames are not trusted.
- Frontend: upload controls on the Verification page; previews in the admin KYC review modal.
- Tests for validation, ownership and staff access.

Then continue with Phase 3 items 6–10 in DEVELOPMENT_ROADMAP.md, plus maker-checker for fee/limit
changes and goAML XML export.
