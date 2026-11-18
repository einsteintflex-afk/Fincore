# FinCore — master progress

_Last updated: 2026-11-18 (session 6). The codebase is the source of truth; re-run the checks below to confirm._

## 1. Architecture
- **Backend:** FastAPI modular monolith (`backend/app`), SQLAlchemy 2, PostgreSQL 16, Alembic. One worker process
  (`python -m app.cli worker`): webhook delivery, provider status polling, outbox, scheduled settlements, AML scan,
  automatic backups.
- **Ledger:** double-entry, `Decimal`/NUMERIC(20,4), append-only (DB triggers), row locks, compensating reversals,
  two-phase outflows (hold → provider → complete/release), per-provider clearing accounts,
  separate `WITHDRAWAL_FEE_REVENUE` account.
- **Frontend:** React 18 + TypeScript + Vite + Tailwind (`frontend/`). Same build runs on the web, in Capacitor
  (Android/iOS) and in Tauri (Windows/macOS/Linux). All platforms call the same API; nothing authoritative is
  stored on devices.
- **Identities kept apart:** dashboard users (humans, max 15, `users`) · connected applications (API keys,
  `developer_apps`) · subscribers of those applications (`app_subscribers`, never dashboard users).
- **Payments:** MTN MoMo Collections (RequestToPay) and Disbursements (Transfer), separate products, separate keys,
  separate sandbox/production profiles. Labelled simulator for development only. Card acceptance via an
  acquiring bank's hosted page (simulated acquirer until a bank is signed).

## 2. Completed (verified this session unless noted)
| Area | What exists |
|---|---|
| 15-seat dashboard | Hard limit of 15 seat-holding accounts incl. the primary admin, enforced by a PostgreSQL trigger serialised with an advisory lock (concurrent activations tested), plus API checks. Invitation-only (no public registration: `/auth/register` → 403). Invite → accept with own password; activate / deactivate / remove / role change / resend link / revoke sessions / activity view. Primary admin protected in code **and** by a DB trigger (cannot be deactivated, removed, demoted, deleted). Only super admins manage the team; only the primary admin can grant/alter super admin. Deactivation revokes sessions immediately. |
| Verified subscribers | Per-application subscribers: register, SMS-code verification (or admin verification), short-lived subscriber tokens, `X-Subscriber-Token` enforcement when the app requires it, clear 401/403 reasons, deactivation revokes all tokens, tokens are app-bound. Settings → Subscribers for admins. Not counted in seats (tested with 30). |
| Withdrawal fee | Configurable (Settings → Withdrawal fee; finance/admin; audited; 0–50%, 2 dp), default **15%**, deducted from the requested amount (100 → fee 15, recipient 85, debit 100). Rate and net amount stored on each transaction. Quote endpoint + review screen before confirming; `expected_fee_percent` refuses a stale fee (409). Fee booked to `WITHDRAWAL_FEE_REVENUE` only when the payout succeeds; failures return everything. Not applied to collections, transfers, settlements, refunds, reversals, adjustments. |
| MTN Collections | From session 5: RequestToPay, verify-before-credit, callbacks re-verified, pending/successful/failed/rejected/expired/timeout, expiry, idempotent references, reconciliation (31 tests against a stand-in MTN API). |
| MTN Disbursements | Transfer with derived idempotent reference, status checks, success/failed/rejected/timeout(404) handling, submitted ≠ successful, net amount sent, two-phase ledger, separate credentials (`FINCORE_MTN_DISBURSEMENT_PRIMARY_KEY` + API user/key per mode), refuses to run without its own credentials (no silent simulator fallback). |
| Applications | Dashboard "Applications": register app (unique ID), permissions (collections/payouts/refunds/balance/subscribers), activate/deactivate, live/test keys (shown once), rotate, revoke, webhooks (signed, retried, history), per-app transactions. Gateway queries are scoped to the calling app (one app cannot read/refund another's charges or payouts, even in the same business); webhooks go only to the originating app. Payout API with idempotency and duplicate-reference protection. |
| Dashboard | Five sections: Overview (collections, disbursements, balances, counts, withdrawal fees, recent, system status), Applications, Transactions (search/filter/detail, approvals, risk alerts), Payments (MTN status, providers, pending, reconciliation), Settings (Users, Subscribers, Withdrawal fee, Security, API & webhooks, Audit log, Reports, Backups, System). |
| Backups | `app.cli backup / verify-backup / restore`; worker backups every 24 h when `FINCORE_BACKUP_DIR` set; restore only into a new database; verified restore (ledger balanced, guards present). |
| Platforms | Web ✔ · Android APK + AAB built and signed ✔ · Windows NSIS installer built (unsigned, not run on Windows) ✔ · Linux .deb built and run ✔ · iOS Xcode project + icons (not built — needs Mac) · macOS bundle config (not built — needs Mac). |
| Earlier sessions | Wallets, transfers, deposits, statements/PDFs, KYC, AML, maker-checker, settlements, refunds, reversals, payment links, checkout, card flow, reconciliation (file upload), audit log, HttpOnly refresh cookie, 2FA. |

## 3. Incomplete / not verified
- ~~MTN sandbox login~~ **resolved.** Real MTN sandbox verified 2026-11-18 after removing the environment's network secret (it was replacing the Authorization header): fresh sandbox API users for Collections and Disbursements log in (200); through FinCore's own services a GH₵100 RequestToPay deposit and a GH₵40 Transfer withdrawal (fee 6.00, net 34.00) both reached SUCCESSFUL with the ledger balanced. Fix found on the way: MTN's `CREATED` status is now treated as pending. Production approval is still required for real money.
- iOS and macOS builds (need a Mac + Apple Developer account). Windows installer not executed on Windows; unsigned.
- APK not run on a physical device/emulator in this session (no emulator available); it is signed and its
  manifest/contents were inspected.
- Email/SMS delivery providers not configured (invitation links are shown to the admin and queued in the outbox;
  subscriber SMS codes are exposed as `dev_code` only in development/test).
- Old browser scripts `journey.cjs` / `kyc.cjs` now need `INVITE_LINK` (an invitation link) to run.
- Phase 3 leftovers: Redis rate limiter (per-process today), malware scanning of uploads, Playwright in CI.

## 4. Files created / modified this session
Backend new: `services/{team,withdrawal_fee,subscribers,payouts,backups}.py`, `api/v1/{team,subscribers,console}.py`,
migration `f486306236e4`, `tests/test_private_platform.py`. Modified: models (user, developer, transaction,
business, enums, guards), `services/{transactions,payments,webhooks,ledger,seed,auth}.py`, `providers/{__init__,mtn_momo}.py`,
`api/v1/{auth,admin,gateway,wallets,system}.py`, `api/deps.py`, `core/config.py`, `cli.py`, `workers/runner.py`,
`main.py`, tests (conftest, auth, admin, wallets, mtn, private_forms), `scripts/loadtest.py`.
Frontend new: `src/pages/console/ConsolePages.tsx`, `capacitor.config.ts`, `android/`, `ios/`, `src-tauri/`,
`resources/`, `scripts/make-icons.py`, `e2e/console.cjs`, `src/__tests__/console.test.tsx`. Modified: `App.tsx`,
`components/{Layout,ui}.tsx`, `lib/{api,auth,hooks,types}.ts(x)`, auth/customer/public pages, old e2e scripts.
Docs: this file, `docs/MOBILE_DESKTOP.md`, `docs/API.md`, `docs/OPERATIONS.md`, `docs/openapi.json`, status files.

## 5. Database changes (migration `f486306236e4`, non-destructive)
`users.is_primary_admin` (unique partial index), `users.invited_by_id`, `users.deactivated_at`; `user_invitations`;
`app_subscribers`, `subscriber_verifications`; `developer_apps.permissions`, `.require_verified_subscribers`;
`transactions.fee_rate`, `.net_amount`, `.app_id`; `businesses.is_house`; triggers `trg_users_seat_limit`,
`trg_users_primary_admin`; setting `withdrawal_fee = 15`; old withdrawal fee rules deactivated (kept).
Earliest active super admin became primary admin. No rows deleted. A backup was taken before migrating.

## 6–8. Tests and builds (actual results, 2026-11-18)
| Check | Result |
|---|---|
| Backend `pytest` | **206 passed** (32 new in `test_private_platform.py`: all 9 financial scenarios, seats incl. concurrency, privilege escalation, subscribers, isolation, payouts, MTN disbursement outcomes, backups) |
| Backend `ruff` / `alembic check` | clean / no drift |
| Frontend `npm run build` / `npm test` | ok / **21 passed** |
| Browser `e2e/console.cjs` | 18/18 steps pass, 0 console errors (five sections, register app + key, all settings tabs, phone-width withdrawal review 15/85, no horizontal scroll) |
| Load test (2 accounts, 100 transfers, concurrency 10) | 100/100 ok |
| Backup → verified restore | restored_ok, debits = credits, 0 unbalanced journals |
| Android `assembleRelease bundleRelease` | APK 4.1 MB + AAB 3.9 MB, signed (apksigner verified), INTERNET permission only, no secrets in bundle |
| Windows `tauri build --runner cargo-xwin` | `FinCore_1.0.0_x64-setup.exe` 2.8 MB (PE32 NSIS installer), unsigned |
| Linux `tauri build --bundles deb` | built; app launched under Xvfb, signed in, dashboard loaded from the API |
Simulated vs real: every MTN test above uses a stand-in MTN API. No real MTN call has succeeded end to end.

## 9. Current errors
None known. MTN sandbox works end to end (see §3).

## 10. Missing credentials / owner actions
- Regenerate both MTN sandbox keys on momodeveloper.mtn.com (they were pasted in chat) and set them as server environment variables, not in chat.
- MTN Ghana production approval and production Collections + Disbursement keys / API users / callback URL.
- Hosting (domain + HTTPS), email + SMS provider, Apple Developer account + Mac (iOS/macOS), optional Windows
  code-signing certificate.

## 11. Platform build status
See §2 "Platforms" and `docs/MOBILE_DESKTOP.md`.

## 12. Outstanding external requirements
MTN partner onboarding (production), an acquiring bank for cards, hosting, messaging providers, Apple/Google
developer accounts. Owner decision recorded: no Bank of Ghana involvement (TD-027) — see BLOCKERS.md for the note.

## 13. Resume
```bash
service postgresql start
cd backend && ../.venv/bin/alembic upgrade head && ../.venv/bin/python -m pytest -q
cd ../frontend && npm ci && npm run build && npm test
# run: backend ../.venv/bin/uvicorn app.main:app --port 8000 ; frontend npx vite --port 5173
# browser check: node frontend/e2e/console.cjs <shots-dir>
```

## 14. The single next task
Owner setup wizard (business name, settlement account, link templates, go-live checklist) — see CURRENT_TASK.md.
