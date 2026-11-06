# Investment platform (future module — NOT ACTIVE)

The investment module is designed but deliberately **disabled** (`FINCORE_INVESTMENTS_ENABLED=false`,
`GET /api/v1/investments/products` returns 503). Offering investment products in Ghana is regulated
(Securities and Exchange Commission Ghana under the Securities Industry Act 2016 (Act 929); pensions by
NPRA; deposit-like products by the Bank of Ghana). Activation requires the business owner to obtain the
appropriate licences or partner with a licensed fund manager/broker.

## Recommended model: partner-distributed products
FinCore acts as a distribution/technology layer; a licensed fund manager (e.g. a money-market or
treasury-bill fund) is the product issuer and custodian. FinCore holds customer subscriptions in an
omnibus account and reconciles units daily with the fund administrator.

## Bounded context
```
investment_products      id, partner, name, type (money_market|tbill|fixed_income|equity_fund),
                         currency, min_investment, risk_rating, status, documents (KID/prospectus)
investment_accounts      id, user_id, product_id, units (NUMERIC(24,8)), cost_basis, status
investment_orders        id, account_id, side (subscribe|redeem), amount, units, nav, status,
                         partner_reference, wallet_transaction_id
nav_prices               product_id, date, nav  (from partner daily feed)
investment_statements    periodic returns reporting per account
suitability_assessments  user_id, answers, risk_profile, completed_at
```

## Ledger integration
New system accounts per currency: `INVEST_OMNIBUS` (liability — funds owed to the fund partner pending
settlement) and `PROVIDER_CLEARING:<FUND_PARTNER>`. Subscription: DR wallet / CR INVEST_OMNIBUS (hold) →
partner confirms units → DR INVEST_OMNIBUS / CR partner clearing. Redemption is the reverse. Units are
tracked in the investment context; cash is always in the main ledger.

## Features to build when authorised
1. Suitability questionnaire and risk disclosure acceptance (mandatory before first order).
2. Product catalogue with documents and historical NAV charts.
3. Subscribe/redeem orders with cut-off times and T+n settlement.
4. Portfolio view: holdings, market value (units × latest NAV), unrealised gain, time-weighted return.
5. Monthly statements and tax reporting.
6. Investment education content (articles, risk explainers) — can launch earlier as non-regulated content.

## Prerequisites (business owner)
- Licensing route decided with counsel (SEC Ghana); partner agreement signed.
- Partner API/data feeds for NAV, order placement and confirmations.
- Complaints-handling and disclosures approved by compliance.
