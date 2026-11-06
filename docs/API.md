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
| Dashboards (customers, merchants, staff) | `POST /auth/login` → `access_token` (15 min) + `refresh_token`; send `Authorization: Bearer <access>`; refresh with `POST /auth/refresh` |
| 2FA accounts | login returns `requires_2fa` + `challenge_token` → `POST /auth/login/2fa` |
| Merchant servers | `Authorization: Bearer sk_test_...` or `sk_live_...` on `/gateway/*` |

## Endpoint groups

| Group | Paths |
|---|---|
| Auth | `/auth/register`, `/auth/login`, `/auth/login/2fa`, `/auth/refresh`, `/auth/logout`, `/auth/verify-email`, `/auth/password/{forgot,reset,change}`, `/auth/2fa/{setup,enable,disable}`, `/auth/sessions` |
| My account | `/me`, `/me/limits`, `/me/summary`, `/me/notifications`, `/me/kyc`, `/me/tickets` |
| Wallets | `/wallets`, `/wallets/{id}`, `/wallets/{id}/statement?format=json|csv`, `/wallets/lookup`, `/wallets/lookup-momo`, `/wallets/lookup-bank`, `/banks` |
| Money movement | `/deposits`, `/withdrawals`, `/transfers`, `/transactions`, `/transactions/{ref}`, `/transactions/{ref}/refresh`, `/beneficiaries` |
| Businesses | `/businesses`, `/businesses/{id}` (+ `/members`, `/wallets`, `/transactions`, `/payment-requests`, `/payment-links`, `/refunds`, `/settlements`, `/settlement-destination`, `/analytics`, `/reports/settlement`) |
| Developer | `/developer/apps`, `/developer/apps/{id}/keys`, `/webhooks`, `/deliveries`, `/usage`, `/developer/events` |
| Gateway (API key) | `POST /gateway/charges`, `GET /gateway/charges`, `GET /gateway/charges/{ref}`, `POST /gateway/refunds`, `GET /gateway/balance`, `POST /gateway/sandbox/charges/{ref}/resolve` |
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
