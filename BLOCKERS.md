# Blockers (need the business owner)

None of these block continued engineering; they block **real-money operation**.

| ID | Blocker | What's needed | Engineering status |
|---|---|---|---|
| B-1 | MTN MoMo production access | MoMo partner agreement; Collections + Disbursements subscription keys, API user/key, target environment, callback IP allow-listing | Adapter implemented & unit-tested with mocked HTTP |
| B-2 | Telecel Cash API | Partner agreement + API specification + credentials | Adapter skeleton; config surface ready |
| B-3 | AT Money API | Partner agreement + API specification + credentials | Adapter skeleton; config surface ready |
| B-4 | Bank transfers (GhIPSS) | GhIPSS membership via a sponsor bank (or direct as a licensed PSP): institution code, API spec, credentials | Adapter skeleton; config ready |
| B-5 | ~~Third-party gateway~~ | Not used — owner chose direct integrations (TD-019) | Paystack adapter dormant |
| B-6 | Regulatory | Bank of Ghana licence/authorisation, trust account for float, approval of limits and fees | Kill switch keeps platform in sandbox |
| B-7 | Identity verification | NIA/Ghana Card verification vendor contract | `IdentityVerifier` plug-in point; manual review works |
| B-8 | Messaging | Email (e.g. SES/Mailgun) and SMS (e.g. Hubtel/mNotify/Arkesel) accounts | Outbox implemented; delivery stub logs messages |
| B-9 | Hosting & tooling | Cloud account, domain, secrets manager, Sentry/monitoring (paid) | Docker/compose/CI ready |
| B-10 | Investments | Licensing route with SEC Ghana or a licensed partner | Designed, disabled by flag |

## Environment notes (not blockers)
- The cloud development sandbox has no Docker daemon, so images were not built here; the stack runs with
  local PostgreSQL 16, uvicorn and Vite. CI builds and tests on GitHub Actions.
