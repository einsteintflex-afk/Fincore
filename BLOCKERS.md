# Blockers (need the business owner)

None of these block continued engineering; they block **real-money operation**.

| ID | Blocker | What's needed | Engineering status |
|---|---|---|---|
| B-1 | MTN MoMo production access + working sandbox login | MoMo partner application approved by MTN Ghana; production Collections **and** Disbursement subscription keys, API users/keys, target environment, callback URL registration and IP allow-listing. For the sandbox: remove the network secret "MTN MoMo Collections key (sandbox)" from the `fincore` cloud environment, regenerate both sandbox keys (they were pasted in chat) and set them in the server environment | Collections + Disbursements implemented and tested against a stand-in MTN API. Real sandbox: both keys accepted and API users created, but token login returns `500 login_failed` even with no credentials sent — likely the environment's network secret overriding the Authorization header |
| B-2 | Telecel Cash API | Partner agreement + API specification + credentials | Adapter skeleton; config surface ready |
| B-3 | AT Money API | Partner agreement + API specification + credentials | Adapter skeleton; config surface ready |
| B-4 | Bank transfers (GhIPSS) | GhIPSS membership via a sponsor bank (or direct as a licensed PSP): institution code, API spec, credentials | Adapter skeleton; config ready |
| B-5 | ~~Third-party gateway~~ | Not used — owner chose direct integrations (TD-019) | Paystack adapter dormant |
| B-11 | Card payments | Card-acquiring (merchant) agreement with a Ghanaian bank (e.g. Ecobank, GCB, CalBank, Stanbic): merchant ID, API credentials, hosted payment page spec | Card flow built and tested with a simulated acquirer; `bank_card` adapter awaits the bank's API spec |
| B-6 | ~~Regulatory~~ | Owner decision (2026-11-18): no Bank of Ghana involvement (TD-027). Note for the owner: Ghana's Payment Systems and Services Act, 2019 (Act 987) generally requires a licence to provide payment services to the public, and MTN's partner onboarding may ask about it — worth confirming with a lawyer before collecting money for others | Kill switch (`FINCORE_LIVE_PAYMENTS_ENABLED`) still gates real money |
| B-7 | Identity verification | NIA/Ghana Card verification vendor contract | `IdentityVerifier` plug-in point; manual review works |
| B-8 | Messaging | Email (e.g. SES/Mailgun) and SMS (e.g. Hubtel/mNotify/Arkesel) accounts | Outbox implemented; delivery stub logs messages |
| B-9 | Hosting & tooling | Cloud account, domain, secrets manager, Sentry/monitoring (paid) | Docker/compose/CI ready |
| B-12 | Apple / Google / Windows distribution | Apple Developer Program + a Mac with Xcode (iOS, macOS builds, signing, notarization); Google Play developer account for the AAB; optional Windows code-signing certificate | Android APK/AAB and Windows installer built; iOS/macOS projects configured (docs/MOBILE_DESKTOP.md) |
| B-10 | Investments | Licensing route with SEC Ghana or a licensed partner | Designed, disabled by flag |

## Environment notes (not blockers)
- The cloud development sandbox has no Docker daemon, so images were not built here; the stack runs with
  local PostgreSQL 16, uvicorn and Vite. CI builds and tests on GitHub Actions.
