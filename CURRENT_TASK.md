# Current task

## Done
- [x] Session 1: platform foundation, frontend, docs, settlements, maker-checker, HttpOnly refresh cookie, AML
- [x] Session 2: Phase 3.5 KYC document upload; Phase 3.6 PDF statements & receipts (browser-verified)

## Next task (start here)
**Phase 3.7 — provider settlement-file upload for reconciliation.**

Acceptance criteria:
- Admin (finance) uploads a CSV settlement/statement file for a provider: `POST /admin/reconciliation/providers/upload`
  (multipart: `provider`, `file`). Columns mapped by a per-provider profile (`provider_reference`, `amount`,
  `status`, optional `date`); a generic profile accepts those exact headers.
- Rows are normalised (amount as Decimal, status mapped to successful/failed/pending) and passed to
  `run_provider_reconciliation(statement=...)`; the run stores file name, row count and discrepancies.
- Also flag internal successful transactions for that provider that are missing from the file
  (`missing_in_provider_file`) within the file's date range.
- Admin UI: upload control on Finance → Reconciliation; discrepancy table with links to transactions.
- Tests: matched, amount mismatch, status mismatch, missing on either side, malformed file (422).

Then continue with Phase 3 items 8–10 in DEVELOPMENT_ROADMAP.md, plus malware scanning for uploads,
maker-checker for fee/limit changes and goAML XML export.
