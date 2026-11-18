# FinCore API guide

Interactive reference: `GET /docs` (Swagger) or `/redoc`. Machine-readable spec: [`openapi.json`](openapi.json)
(124 paths). Base path: `/api/v1`.

## Conventions
* **Money** is a decimal **string** (`"125.50"`). GHS accepts up to 2 decimal places. Never send floats.
* **Errors**: `{"error": {"code": "insufficient_funds", "message": "Insufficient funds", "details": {...}}}`
  with an appropriate HTTP status (401, 403, 404, 409, 422, 429, 502, 503).
* **Idempotency**: send `Idempotency-Key: <unique string>` on money-moving POSTs (`/deposits`, `/withdrawals`,
  `/transfers`, refunds, settlements, gateway charges/refunds). Same key + same body → original response;
  same key + different body → `409 idempotency_mismatch`.
* **Pagination**: `?page=1&page_size=20` → `{items, total, page, page_size}`.
* **Request IDs**: every response has `X-Request-ID` (send your own to correlate).

## Authentication

| Audience | How |
|---|---|
| Dashboard users (max 15, invitation only) | `POST /auth/login` → `access_token` (15 min) + refresh token (HttpOnly cookie for the web app; JSON body, kept in memory only, for the packaged apps); send `Authorization: Bearer <access>`; refresh with `POST /auth/refresh`. There is no public registration: `POST /auth/register` returns 403. Invited users call `GET /auth/invitation?token=` and `POST /auth/invitation/accept` |
| 2FA accounts | login returns `requires_2fa` + `challenge_token` → `POST /auth/login/2fa` |
| Connected applications | `Authorization: Bearer sk_test_...` or `sk_live_...` on `/gateway/*` — separate from dashboard logins and not counted in the 15 seats |
| Subscribers of an application | the application sends `X-Subscriber-Token` (issued by `POST /gateway/subscribers/{external_id}/token`) when the app requires verified subscribers |

## Endpoint groups

| Group | Paths |
|---|---|
| Auth | `/auth/invitation`, `/auth/invitation/accept`, `/auth/login`, `/auth/login/2fa`, `/auth/refresh`, `/auth/logout`, `/auth/verify-email`, `/auth/password/{forgot,reset,change}`, `/auth/2fa/{setup,enable,disable}`, `/auth/sessions` |
| My account | `/me`, `/me/limits`, `/me/summary`, `/me/notifications`, `/me/kyc`, `/me/tickets` |
| Wallets | `/wallets`, `/wallets/{id}`, `/wallets/{id}/statement?format=json|csv`, `/wallets/lookup`, `/wallets/lookup-momo`, `/wallets/lookup-bank`, `/banks` |
| Money movement | `/deposits`, `/withdrawals/quote`, `/withdrawals`, `/transfers`, `/transactions`, `/transactions/{ref}`, `/transactions/{ref}/refresh`, `/beneficiaries` |
| Businesses | `/businesses`, `/businesses/{id}` (+ `/members`, `/wallets`, `/transactions`, `/payment-requests`, `/payment-links`, `/refunds`, `/settlements`, `/settlement-destination`, `/analytics`, `/reports/settlement`) |
| Developer | `/developer/apps`, `/developer/apps/{id}/keys`, `/webhooks`, `/deliveries`, `/usage`, `/developer/events` |
| Gateway (API key) | `POST /gateway/charges`, `GET /gateway/charges`, `GET /gateway/charges/{ref}`, `POST /gateway/refunds`, `GET /gateway/balance`, `GET /gateway/payouts/quote`, `POST /gateway/payouts`, `GET /gateway/payouts/{ref}`, `POST /gateway/sandbox/charges/{ref}/resolve` — every call is scoped to the calling application and checked against its permissions |
| Subscribers (API key) | `POST /gateway/subscribers`, `GET /gateway/subscribers/{external_id}`, `POST …/verification`, `POST …/verification/confirm`, `POST …/token`, `GET /gateway/subscribers/access/check` |
| Dashboard (five sections) | `/console/overview`, `/console/applications` (+ `/{id}`, `/keys`, `/keys/{id}/rotate`, `/keys/{id}/revoke`, `/webhooks`, `/transactions`), `/console/payments`, `/console/settings/withdrawal-fee`, `/console/settings/backups` |
| Settings: users & subscribers | `/admin/team` (+ `/invitations`, `/{id}/deactivate`, `/activate`, `/remove`, `/role`, `/invitation/resend`, `/sessions/revoke`, `/activity`), `/admin/subscribers` |
| Checkout (public) | `GET /checkout/{ref}`, `POST /checkout/{ref}/mobile-money`, `POST /checkout/{ref}/wallet`, `GET|POST /pay/{slug}` |
| Callbacks | `POST /callbacks/{provider}` (sandbox, mtn_momo, paystack) |
| Admin | `/admin/overview`, `/admin/users`, `/admin/kyc`, `/admin/businesses`, `/admin/transactions`, `/admin/adjustments`, `/admin/fraud-alerts`, `/admin/fees`, `/admin/limits`, `/admin/settings`, `/admin/audit-logs`, `/admin/reports/*`, `/admin/reconciliation/*`, `/admin/tickets`, `/admin/providers`, `/admin/analytics/*` |
| System | `/health`, `/ready`, `/metrics`, `/api/v1/platform` |

## Gateway integration example

```bash
curl -X POST $BASE/api/v1/gateway/charges \
  -H "Authorization: Bearer sk_test_..." -H "Idempotency-Key: order-1042" \
  -H "Content-Type: application/json" \
  -d '{"amount":"120.00","phone":"0241234567","email":"c@example.com","reference":"order-1042"}'
```
Response (abridged):
```json
{"reference":"PAY-20261106-7KQ2M9X4TZAB","merchant_reference":"order-1042","status":"successful",
 "amount":"120.00","fee":"1.80","environment":"sandbox","checkout_url":"https://…/checkout/PAY-…"}
```
Without `phone`, status is `pending` and you redirect the customer to `checkout_url`.

### Sandbox magic values
| Phone / account ends in | Result |
|---|---|
| `0000` | failed – insufficient balance |
| `1111` | pending – resolve via `POST /gateway/sandbox/charges/{ref}/resolve` (`{"status":"successful"}`) |
| `2222` | failed – declined/timeout |
| `9999` (name lookup) | account not found |
| amount `666.00` | provider outage |
| anything else | successful |

## Payouts and the withdrawal fee

Payouts are withdrawals from the application's balance. The withdrawal fee (default **15%**, set in
Settings → Withdrawal fee) is **deducted from the requested amount**:

```bash
curl "$BASE/api/v1/gateway/payouts/quote?amount=100" -H "Authorization: Bearer sk_live_..."
# {"requested_amount":"100.00","fee_percent":"15","fee_amount":"15.00","net_amount":"85.00","total_debit":"100.00"}
curl -X POST $BASE/api/v1/gateway/payouts -H "Authorization: Bearer sk_live_..." -H "Idempotency-Key: po-77" \
  -H "Content-Type: application/json" \
  -d '{"amount":"100","phone":"0241234567","reference":"po-77","expected_fee_percent":"15"}'
# {"reference":"WDR-…","status":"processing","amount":"100.00","fee":"15.00","net_amount":"85.00",…}
```
`processing` means submitted to MTN, not paid. The final status comes from MTN (poll `GET /gateway/payouts/{reference}`
or listen for `payout.successful` / `payout.failed`). A failed payout returns the full amount; no fee is kept.
`expected_fee_percent` makes the call fail with `409 fee_changed` if the fee changed after you showed it to the user.
A reused `reference` returns `409 duplicate_reference`. Sandbox keys return a labelled simulation and move no money.
The application needs the `payouts` permission (granted by an administrator in Applications).

## Verified subscribers

```bash
POST /gateway/subscribers                     {"external_id":"nurse-42","display_name":"Akua","phone":"0241234567"}
POST /gateway/subscribers/nurse-42/verification          # SMS code to the subscriber
POST /gateway/subscribers/nurse-42/verification/confirm  {"code":"123456"}   -> status "active"
POST /gateway/subscribers/nurse-42/token                 -> {"subscriber_token": "...", "expires_in": 43200}
```
When the application has "Only serve verified subscribers" on, charges and payouts need `X-Subscriber-Token`;
otherwise they fail with `403 subscriber_token_required` / `subscriber_not_verified` / `subscriber_inactive`.
Deactivating a subscriber revokes every token at once (`401 subscriber_session_revoked`). Tokens of one
application are rejected by every other application.

## Webhooks
Events: `charge.success`, `charge.failed`, `refund.processed`, `refund.failed`, `settlement.paid`,
`settlement.failed`, `payment_link.paid`, `test.ping`.

```json
{"id":"evt_…","type":"charge.success","created_at":"2026-11-06T21:40:00Z","livemode":false,
 "data":{"reference":"PAY-…","amount":"120.00","currency":"GHS","status":"successful", "...": "..."}}
```
Headers: `X-FinCore-Event`, `X-FinCore-Delivery`, `X-FinCore-Signature: t=<unix>,v1=<hex>` where
`v1 = HMAC_SHA256(signing_secret, "<t>." + raw_body)`. Reject if `|now − t| > 300 s`. Respond 2xx within
10 s; failures retry with exponential backoff (1, 2, 4 … min, max 6 h, 8 attempts). Deliveries can be
inspected and retried from the developer dashboard.
