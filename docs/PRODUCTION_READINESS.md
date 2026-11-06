# Outstanding production requirements

FinCore is **not production-ready for real money**. Nothing here claims regulatory approval, provider
approval or production readiness. This is the gap list, grouped by who must act.

## Requires the business owner (cannot be done by engineering)
| Item | Why |
|---|---|
| Bank of Ghana licence/authorisation (EMI/PSP category per Payment Systems and Services Act 2019, Act 987) | Legally required to hold e-money and provide payment services |
| Provider contracts & production credentials (MTN MoMo, Telecel, AT, sponsor bank/GhIPSS, or Paystack) | Needed to move real money (BLOCKERS.md B-1…B-4) |
| Trust/settlement bank account for customer float | E-money float must be held in designated trust accounts |
| Approval of fee schedule and KYC tier limits | Commercial and regulatory decisions (TD-014) |
| NIA / Ghana Card verification vendor contract | Automated KYC instead of manual review |
| Data Protection Commission registration, privacy policy, terms of service | Act 843 compliance, customer-facing legal terms |
| Paid services: email (SES/Mailgun), SMS gateway, error tracking (Sentry), hosting | Operational dependencies with cost |
| Independent penetration test & security audit | Required before go-live |

## Engineering backlog before go-live
- [ ] Email/SMS delivery providers wired into the outbox worker (OTP via SMS, transaction receipts)
- [x] Maker-checker approvals for adjustments and reversals above thresholds (fee/limit changes still single-approver)
- [ ] Refresh token in HttpOnly SameSite cookie (TD-011)
- [x] AML transaction monitoring scenarios + CSV case export
- [ ] Sanctions/PEP screening on onboarding; goAML XML STR export for FIC
- [ ] KYC document upload to encrypted object storage with virus scanning
- [ ] Redis-backed rate limiter or edge limits for multi-instance deployments
- [x] Automatic settlements on schedule (daily/weekly)
- [ ] Statement PDF generation (CSV/JSON exist)
- [ ] Provider settlement-file ingestion (upload UI) for reconciliation
- [ ] Load testing at target volume on production-like infrastructure
- [ ] Observability stack (Prometheus/Grafana dashboards, alert rules, Sentry)
- [ ] Customer-facing mobile apps (current SPA is mobile-responsive)

## Already in place
Double-entry immutable ledger with integrity checks; concurrency-safe postings; idempotency; tiered
limits; risk alerts; RBAC; audit log; 2FA; encrypted secrets; signed webhooks; reconciliation; sandbox
isolation; CI; Docker deployment; health/metrics endpoints; backup job; scheduled settlements; maker-checker;
AML scenarios; 108 backend + 15 frontend tests; browser smoke and journey scripts.
