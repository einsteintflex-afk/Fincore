# Security

## Controls implemented

### Identity & access
| Control | Implementation |
|---|---|
| Password hashing | Argon2id (`argon2-cffi`), policy: ≥10 chars, upper, lower, digit |
| Brute-force protection | 5 failed logins → 15 min lockout; strict per-IP rate limit on login/registration/reset; constant-time response for unknown emails |
| Sessions | Access JWT (HS256, 15 min, in memory) carries a session id checked on every request → instant revocation; refresh tokens are opaque, SHA-256 hashed, rotated on every use, 14-day expiry, delivered to browsers as an HttpOnly SameSite=Strict cookie (CSRF header required) |
| 2FA | TOTP (RFC 6238) with ±1 step window; seed encrypted at rest; challenge token (5 min) between password and code |
| Password reset | Single-use opaque token, hashed, 30-minute expiry; all sessions revoked after reset/change |
| Account restrictions | `no_debit`, `no_credit`, `full_freeze`, `login_block`; account status frozen/closed; enforced in services and auth dependency |
| Staff RBAC | `support`, `compliance`, `finance`, `admin`, `super_admin`; only super_admin changes roles (and role changes revoke sessions) |
| Merchant RBAC | Per-business roles (owner/admin/finance/developer/support/viewer) mapped to permissions |
| API keys | `sk_test_`/`sk_live_` secrets shown once, stored as SHA-256 hash, prefix lookup, revocation and rolling; live keys gated on business approval + platform live switch |

### Data protection
* Secrets at rest (TOTP seeds, webhook signing secrets) encrypted with Fernet (AES-128-CBC + HMAC-SHA256);
  key from `FINCORE_ENCRYPTION_KEY` → use a KMS/HSM-managed value in production.
* Startup refuses insecure `SECRET_KEY`/missing `ENCRYPTION_KEY` in staging/production.
* Logs are structured JSON; keys containing password/secret/token/pin/otp/code are redacted.
* Public checkout pages mask customer emails.
* KYC documents: private storage, unguessable keys, file type detected from content (client filename/type
  ignored), size limit, staff access only via expiring signed links, each view audit-logged.
* Money is never handled as float (backend `Decimal`, frontend strings).

### Financial integrity
* Double-entry ledger with DB-level immutability triggers, balance CHECK constraints, row locking,
  idempotency keys, compensating reversals and an integrity verifier (exposed as reconciliation runs).
* Append-only audit log (DB trigger) for all sensitive user, staff and system actions with IP and request id.

### API & transport
* Security headers on every response (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `no-store`,
  HSTS in production); nginx adds a strict CSP for the SPA.
* CORS allow-list from configuration; in the Docker deployment SPA and API share one origin.
* Inbound provider callbacks: HMAC verification (Paystack, sandbox); MTN callbacks re-verified via status API.
* Outbound webhooks signed `t=<ts>,v1=HMAC_SHA256(secret, "<ts>.<body>")` with 5-minute replay window.
* Webhook URLs must be HTTPS and public in production (basic SSRF guard).

### Fraud & compliance
* Rules-based risk scoring on withdrawals, transfers and payments (large amount, velocity, new account,
  unverified withdrawal); blocking threshold and alert queue for compliance.
* Duplicate national-ID detection across accounts.
* Tiered KYC limits (per transaction, daily, monthly, max balance).

## Threat model (summary)

| Threat | Mitigation | Residual / to do |
|---|---|---|
| Credential stuffing | lockout, rate limits, 2FA | add breached-password check, device fingerprinting, CAPTCHA after failures |
| Session theft (XSS) | CSP, no third-party scripts, in-memory access tokens, HttpOnly SameSite=Strict refresh cookie + CSRF header, revocable sessions | — |
| Double spend / race conditions | row locks, sorted lock order, CHECK constraints, idempotency | — (covered by concurrency test) |
| Insider manipulation of balances | append-only ledger and audit log, adjustments require finance role and reason, maker-checker approval above thresholds | extend four-eyes to fee/limit changes |
| Forged provider callbacks | signature verification / status re-query | IP allow-listing at the edge for MTN |
| Webhook SSRF | HTTPS + public host check in production | resolve DNS and block private ranges at send time |
| API key leakage | hashed storage, rolling, revocation, usage logs | IP allow-lists per key, key scopes |
| Money laundering / mule accounts | KYC tiers, limits, real-time risk alerts, AML scenarios (structuring, rapid movement, fan-in, dormant reactivation), duplicate-ID alerts, CSV case export | sanctions/PEP screening, goAML XML STR filing to FIC, scenario tuning by compliance |

## Production security checklist
- [ ] Secrets from a secrets manager (not env files); rotate `SECRET_KEY`/`ENCRYPTION_KEY` with a key-versioning plan
- [ ] TLS everywhere (edge + DB connections with `sslmode=verify-full`)
- [ ] WAF + edge rate limiting; IP allow-list provider callbacks
- [ ] Database least-privilege roles (app role cannot `DROP`/`ALTER`/`TRUNCATE`; migration role separate)
- [ ] Centralised log retention and SIEM alerts on `user.locked_out`, `user.role_changed`, `wallet.adjusted`, `transaction.reversed`
- [ ] Penetration test and secure code review by an independent firm
- [ ] Data protection: register with Ghana's Data Protection Commission (Act 843); DPIA; retention policy
- [ ] Incident response plan and Bank of Ghana cyber & information security directive alignment
