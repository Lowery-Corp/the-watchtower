# Watchtower Profiles, Sessions, and API Keys Implementation Plan

> **For Hermes:** After owner approval, implement this plan on `vm-work-dev-db:/home/lowery/the-watchtower` using strict RED→GREEN→REFACTOR cycles. Push implementation only to `dev` after exact-diff review.

**Status:** Proposal for owner review; no implementation has started.

**Goal:** Add the identity and tenant-isolation foundation needed for a future Watchtower web portal: externally authenticated user sessions, one Watchtower profile per auth-service user, profile-owned monitored services, and revocable user-managed API keys that associate webhook events with the correct profile.

**Architecture:** The external auth service remains the source of truth for credentials, users, and session-token validity. Watchtower stores only a stable external user ID and Watchtower-specific profile/resources. Browser sessions use an HttpOnly Watchtower cookie containing the auth-service bearer token; protected Watchtower endpoints validate that token with the auth service. Machine API keys are generated and managed by authenticated profile owners and resolve every webhook request to a profile before any event is accepted.

**Tech stack:** FastAPI, async HTTPX, Pydantic, async SQLAlchemy, PostgreSQL 17, Alembic, pytest, Docker Compose, Nginx.

---

## 1. Scope of this milestone

### Included

1. External auth-service client and fail-closed token validation.
2. Watchtower login, current-session, and logout API contracts suitable for a future portal.
3. Lazy creation of one local Watchtower profile per external auth user.
4. Profile-scoped monitored-service ownership and database constraints.
5. Authenticated CRUD for monitored services.
6. User-managed API-key creation, listing, metadata update, revocation, and deletion policy.
7. Webhook authentication through a profile-owned API key.
8. Profile attribution on events and outbox rows with database-enforced cross-tenant integrity.
9. Tenant-isolation tests proving one user cannot read, mutate, or ingest into another user's resources.
10. Documentation, OpenAPI, migration, security, runtime, and independent-review gates.

### Explicitly deferred

- Website target/profile CRUD (`https://example.com`, interval, timeout, expected status).
- Scheduled HTTP polling workers.
- Uptime state projection, incidents, uptime percentages, alerts, dashboards, or frontend code.
- Teams, organizations, shared profiles, invitations, and role-based membership.
- Billing, quotas, or plan enforcement.
- PostgreSQL row-level security; this milestone uses mandatory tenant predicates plus composite relational constraints. RLS can be a later defense-in-depth milestone.

This milestone makes uptime monitoring safely tenant-aware; it does not yet perform uptime checks.

---

## 2. Verified current context

### Auth service

Live documentation: `http://100.97.236.10:8000/docs`

Verified OpenAPI operations include:

- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/token-check`
- `POST /api/v1/auth/logout`
- user administration routes under `/api/v1/users/*`

The auth API uses an OAuth2 bearer token. `AuthorizedUser` includes `id`, `username`, `is_admin`, and `token`. Unauthenticated `/auth/me` and `/auth/token-check` return `401` with `WWW-Authenticate: Bearer`.

### Scrappy pattern

Scrappy:

1. Proxies email/password login to the auth service.
2. Places the returned bearer token in a secure HttpOnly application cookie.
3. Sends the token to auth `/auth/me` for protected requests.
4. Uses the external user UUID as the tenant key in application repositories.

Watchtower should preserve this useful pattern while improving error handling, typed response validation, cookie configurability, structured logging, and testability.

### Watchtower state

- Canonical worktree: `vm-work-dev-db:/home/lowery/the-watchtower`
- Allowed implementation branch: `dev` only
- Current database counts: zero monitored services, zero events, zero outbox rows
- Existing ingestion uses deployment-configured per-service HMAC secrets.
- Existing unstaged change in `compose.yaml` publishes PostgreSQL on host port `5433`; it is not part of this proposal and must not be overwritten, staged, or silently included.

---

## 3. Recommended product decisions

These are proposed defaults and require owner approval before implementation.

### D1 — Profile cardinality

**Recommendation:** One Watchtower profile per external auth user for this milestone.

Use a separate internal `profile.id` plus unique `profile.auth_user_id`. Do not make every domain row depend directly on the external UUID; the internal profile identity leaves a clean path to future teams/workspaces and memberships.

### D2 — Profile provisioning

**Recommendation:** Lazily create the local profile after the first successfully authenticated `GET /api/v1/profile` or another profile-protected request.

No passwords or auth tokens are stored in the profile table. If an auth user is deactivated or deleted, the auth service rejects the session and the local profile becomes inaccessible but remains available for an explicit retention/deletion policy.

### D3 — Machine API-key protocol

**Recommendation:** Use a high-entropy opaque API key sent in `X-Watchtower-API-Key` over TLS.

Proposed token shape:

```text
wtk_<public-prefix>.<random-256-bit-secret>
```

Watchtower stores only a deterministic cryptographic digest and non-secret prefix; it displays the full token exactly once at creation. A random 256-bit token makes offline recovery from a database leak infeasible. Authentication uses constant-time digest comparison.

This is simpler and safer at rest than storing reversible HMAC secrets in PostgreSQL. Production use must require HTTPS at the public ingress because bearer API keys must never cross an untrusted plaintext network.

**Alternative requiring explicit selection:** Preserve the existing exact-body HMAC protocol with user-managed key IDs. That requires encrypted key material and a separately managed encryption key because the server must recover the signing secret to verify HMAC. It adds key-encryption, rotation, and disaster-recovery scope.

### D4 — Existing HMAC compatibility

**Recommendation:** Keep deployment-configured HMAC authentication as a documented legacy path for one migration milestone, but require all newly managed user keys to use the tenant-backed API-key path. Because the current development database is empty, no data backfill is needed.

Before implementation, decide whether to:

- retain legacy HMAC temporarily, or
- make a clean pre-release cutover and remove `WATCHTOWER_WEBHOOK_SECRETS` immediately.

No legacy event may be accepted without deterministic profile ownership.

### D5 — API-key scope

**Recommendation:** Keys are profile-owned and may submit events only for monitored services belonging to that profile. Initial allowed scope is `events:write`; the schema can represent scopes without implementing speculative permissions.

A key may optionally be restricted to one monitored service at creation. Default profile-wide keys are convenient, while service-bound keys minimize blast radius.

### D6 — Cross-tenant not-found behavior

**Recommendation:** Return `404` for attempts to fetch, update, or delete another profile's resources to avoid confirming their existence. Return generic `401` for API-key/source ownership mismatches on webhook ingestion.

---

## 4. Proposed data model

### `watchtower.profile`

- `id UUID PRIMARY KEY`
- `auth_user_id UUID NOT NULL UNIQUE`
- `display_name VARCHAR(255) NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`

The auth service owns username/email/admin/session state. Watchtower stores only domain-specific profile metadata.

### `watchtower.api_key`

- `id UUID PRIMARY KEY`
- `profile_id UUID NOT NULL REFERENCES profile(id) ON DELETE CASCADE`
- `name VARCHAR(100) NOT NULL`
- `public_prefix VARCHAR(32) NOT NULL UNIQUE`
- `secret_digest BYTEA NOT NULL`
- `scopes JSONB NOT NULL` (initially only `events:write`)
- `service_id UUID NULL` (optional service restriction)
- `created_at TIMESTAMPTZ NOT NULL`
- `expires_at TIMESTAMPTZ NULL`
- `last_used_at TIMESTAMPTZ NULL`
- `revoked_at TIMESTAMPTZ NULL`
- unique `(profile_id, name)`
- index `(profile_id, revoked_at)`

Never store the plaintext key. Never return `secret_digest` through ORM serialization, APIs, logs, or OpenAPI examples.

### `watchtower.monitored_service` changes

- add `profile_id UUID NOT NULL`
- replace global slug uniqueness with unique `(profile_id, slug)`
- add unique `(id, profile_id)` to support composite references
- index `(profile_id, active)`

Two profiles may use the same source slug; API-key authentication identifies the profile before source resolution.

### `watchtower.event` changes

- add `profile_id UUID NOT NULL`
- enforce composite FK `(service_id, profile_id)` to `monitored_service(id, profile_id)`
- make idempotency unique `(profile_id, service_id, source_event_id)`
- add index `(profile_id, occurred_at)`
- retain immutable normalized JSONB payload

### `watchtower.outbox_message` changes

- add `profile_id UUID NOT NULL`
- enforce event/service/profile identity using a composite FK backed by a matching event uniqueness constraint
- include profile identity in publisher-ready payload metadata without exposing user credentials
- index unpublished work by profile only if query plans justify it

### Migration strategy

Create a new additive Alembic revision after `0004_outbox_integrity`.

Because the current database is empty, profile ownership may be `NOT NULL` immediately. The migration must fail with an actionable message if tenant-owned rows exist without an approved owner mapping; it must never silently assign them to an arbitrary user. Upgrade/downgrade testing runs against a disposable database, never the live development database.

---

## 5. Proposed API contracts

### Session/auth routes

#### `POST /api/v1/auth/login`

- Accept `{email, password}` over HTTPS.
- Forward credentials to the auth service without logging them.
- On success, set a configurable HttpOnly session cookie.
- Cookie defaults: `Secure`, `SameSite=Lax`, path `/`, bounded lifetime.
- Return sanitized user/session status; do not return the bearer token to browser JavaScript.
- Invalid credentials: `401`.
- Auth-service unavailable/timeout: `503`.

#### `GET /api/v1/auth/me`

- Read Watchtower cookie or explicit bearer token.
- Validate through auth `/api/v1/auth/me`.
- Lazily create/read the local profile.
- Return external identity fields plus Watchtower profile metadata.

#### `POST /api/v1/auth/logout`

- Ask auth service to invalidate the token.
- Always clear the local cookie.
- Do not log the token.

### Profile routes

- `GET /api/v1/profile`
- `PATCH /api/v1/profile`

No arbitrary profile ID is accepted for the current user's own profile endpoints.

### Monitored-service routes

- `POST /api/v1/services`
- `GET /api/v1/services`
- `GET /api/v1/services/{service_id}`
- `PATCH /api/v1/services/{service_id}`
- `DELETE /api/v1/services/{service_id}` or deactivate-only policy

Every repository call requires `profile_id`; IDs alone are insufficient.

### API-key routes

- `POST /api/v1/api-keys` — returns full key once
- `GET /api/v1/api-keys` — metadata/prefix only
- `GET /api/v1/api-keys/{key_id}` — metadata/prefix only
- `PATCH /api/v1/api-keys/{key_id}` — name, expiry, allowed service
- `DELETE /api/v1/api-keys/{key_id}` — revoke immediately; default to soft revocation for auditability

Key creation requires a recent valid user session. Revoked or expired keys fail immediately.

### Webhook route

`POST /api/v1/webhooks/events`

For the managed-key path:

1. Parse and structurally validate the API-key prefix before consuming the body.
2. Resolve the active, unexpired key and profile.
3. Read the body with the existing bounded streaming limit.
4. Validate the event envelope.
5. Resolve source by `(profile_id, source_slug)`.
6. Enforce optional key-to-service restriction.
7. Persist event and outbox with the same `profile_id` in one transaction.
8. Preserve existing duplicate/conflict semantics.
9. Update `last_used_at` without turning ingestion failure into a partial commit.

Authentication failures remain generic and must not reveal whether a profile, key, or source exists.

---

## 6. Implementation tasks (TDD sequence)

### Task 0 — Resolve blockers and freeze baseline

- Confirm decisions D1–D6.
- Decide how to handle the existing unstaged `compose.yaml` PostgreSQL-port change: leave local, commit separately, or include by explicit owner direction.
- Obtain a dedicated non-production auth test account/token or approve mocked success plus live unauthenticated contract checks.
- Confirm current `dev` equals `origin/dev` and preserve all unrelated changes.

### Task 1 — Typed auth-service client

**Likely files:**

- Modify `pyproject.toml` to make HTTPX a runtime dependency.
- Modify `src/watchtower/core/config.py` for auth URL, timeout, cookie, and trusted-network settings.
- Create `src/watchtower/clients/auth_service.py`.
- Create `src/watchtower/schemas/auth.py`.
- Add unit/contract tests under `tests/unit/clients/` and `tests/contract/`.

**RED first:** valid user parsing, invalid token, timeout, malformed upstream response, and token redaction.

**GREEN:** bounded async client, typed models, explicit error taxonomy, no token/body logging, fail closed.

### Task 2 — Profile model and repository

**Likely files:**

- Create `src/watchtower/models/profile.py`.
- Create `src/watchtower/schemas/profile.py`.
- Create `src/watchtower/repositories/profiles.py`.
- Update `src/watchtower/models/__init__.py` and `alembic/env.py` model imports as required.
- Add repository concurrency tests.

**RED first:** two concurrent first requests for one auth user create exactly one profile; different auth users create different profiles.

**GREEN:** PostgreSQL conflict-safe lazy provisioning with service-owned transaction boundaries.

### Task 3 — User-session dependencies and routes

**Likely files:**

- Create `src/watchtower/api/v1/dependencies/user_auth.py`.
- Create `src/watchtower/api/v1/endpoints/auth.py`.
- Create `src/watchtower/api/v1/endpoints/profile.py`.
- Update `src/watchtower/api/v1/api.py` and application lifespan/client wiring.

**RED first:** login cookie attributes, invalid login `401`, auth outage `503`, `/me` profile provisioning, logout clearing cookie, and missing session `401` before protected endpoint work.

### Task 4 — Tenant schema migration

**Likely files:**

- Create `alembic/versions/0005_profiles_and_tenant_ownership.py` (final filename/revision determined at implementation).
- Modify profile/service/event/outbox ORM models.
- Add migration and constraint tests.

**RED first:** cross-profile event/service and outbox/event rows fail at the database boundary.

**GREEN:** add profile/API-key tables, ownership columns, composite keys, indexes, and non-null constraints in safe order.

### Task 5 — Profile-scoped monitored-service management

**Likely files:**

- Extend `schemas/monitored_service.py`.
- Extend `repositories/monitored_services.py`.
- Create `services/monitored_services.py`.
- Create `api/v1/endpoints/services.py`.

**RED first:** profile A cannot list/get/update/delete profile B's service; duplicate slug is rejected within one profile but allowed across profiles.

### Task 6 — API-key generation and storage

**Likely files:**

- Create `src/watchtower/models/api_key.py`.
- Create `src/watchtower/schemas/api_key.py`.
- Create `src/watchtower/core/api_keys.py`.
- Create `src/watchtower/repositories/api_keys.py`.
- Create `src/watchtower/services/api_keys.py`.

**RED first:** adequate entropy, parser rejects malformed keys cheaply, digest comparison is constant-time, plaintext is returned only at creation, revoked/expired keys reject, and no plaintext appears in database-backed models.

### Task 7 — API-key management endpoints

**Likely files:**

- Create `src/watchtower/api/v1/endpoints/api_keys.py`.
- Update aggregate router.
- Add integration/API/OpenAPI tests.

**RED first:** owner-only CRUD, masked list output, one-time secret display, immediate revocation, service-binding ownership, and cross-tenant `404`.

### Task 8 — Tenant-aware webhook ingestion

**Likely files:**

- Extend or split `api/v1/dependencies/webhook_auth.py`.
- Extend `services/event_ingestion.py`.
- Extend event/outbox repositories and schemas.
- Update webhook OpenAPI and contract documentation.

**RED first:** valid profile key accepted; cross-profile source rejected; revoked/expired key rejected; duplicate and conflict semantics remain profile-scoped; no body read for structurally invalid key; no key leakage.

### Task 9 — Documentation and operator configuration

- Update `.env.example`, `README.md`, `AGENTS.md`, and `docs/event-contract.md`.
- Add a profile/API-key contract document.
- Document private auth URL/Tailscale trust assumptions and production HTTPS requirement.
- Document key rotation/revocation and the legacy HMAC decision.
- Ensure generated OpenAPI matches runtime status codes, cookie/bearer security, and required machine-key header metadata.

### Task 10 — Full validation, review, and delivery

- Build every affected runtime, migration, and profile-gated test image.
- Run full pytest, Ruff, strict mypy, `pip check`, Compose validation, Alembic drift check, and Nginx syntax.
- Run disposable migration upgrade → downgrade → upgrade.
- Run live session checks with the dedicated auth test identity.
- Run live API-key webhook accepted → duplicate → conflict smoke.
- Verify one event/outbox row and matching profile/service identity.
- Verify revoked key rejection and zero cross-tenant access.
- Scan logs/diff/images for tokens, API keys, passwords, and payload leakage.
- Freeze the staged diff, record its SHA-256 fingerprint, and obtain independent fail-closed security, database, and architecture/API reviews.
- Commit as the configured Watchtower identity and push explicitly with `git push origin HEAD:dev` only after approval.

---

## 7. Criteria for success

### Identity and sessions

- [ ] Watchtower never stores user passwords.
- [ ] A valid auth-service token resolves to one typed external identity.
- [ ] Exactly one local profile exists per external auth user, including concurrent first access.
- [ ] Invalid/expired tokens return `401`; auth-service outages return `503`, not anonymous access.
- [ ] Login sets an HttpOnly cookie with approved Secure/SameSite/lifetime attributes.
- [ ] Logout clears the local cookie and attempts upstream invalidation.
- [ ] Tokens, passwords, cookie values, and auth response bodies never appear in logs.

### Tenant isolation

- [ ] Every monitored service belongs to exactly one profile.
- [ ] Every event and outbox row has database-enforced ownership consistent with its service/profile.
- [ ] Profile A cannot list, read, update, delete, or ingest into profile B's resources.
- [ ] Cross-tenant object probes return non-enumerating responses.
- [ ] Every tenant-aware repository method requires `profile_id`; tests fail if an ID-only lookup is introduced.
- [ ] Two profiles may use the same service slug without collision.

### API keys

- [ ] A logged-in user can create, list, rename/restrict, and revoke their own API keys.
- [ ] The full API key is returned once and never retrievable afterward.
- [ ] PostgreSQL stores only the key digest and non-secret metadata.
- [ ] Key generation provides at least 256 bits of cryptographic randomness.
- [ ] Revoked and expired keys stop authenticating immediately.
- [ ] A service-restricted key cannot submit for another service.
- [ ] API-key authentication is constant-time after candidate lookup and has generic failures.
- [ ] API keys and key digests never appear in logs, OpenAPI examples, exception text, or Git.

### Ingestion behavior

- [ ] A valid managed key associates the event with the correct profile and monitored service.
- [ ] Duplicate retries remain deterministic and create no extra event/outbox rows.
- [ ] Conflicting reuse of an event ID still returns `409`.
- [ ] Event and outbox writes remain one atomic transaction.
- [ ] Existing body limits, proxy limits, request IDs, strict timestamp/JSON validation, and rate limits remain effective.
- [ ] The approved legacy-HMAC migration policy is implemented and documented.

### Quality and operations

- [ ] Full test suite, Ruff, strict mypy, `pip check`, Compose validation, Alembic drift, and Nginx syntax pass.
- [ ] Migration upgrade/downgrade/upgrade passes on a disposable database.
- [ ] Live auth and managed-key ingestion smoke tests pass without residual test users, keys, services, or events.
- [ ] Auth failure behavior and OpenAPI are verified against the live auth service contract.
- [ ] Runtime services remain healthy and run as non-root where currently required.
- [ ] Exact staged fingerprint receives independent security, database, and architecture approval.
- [ ] Only `dev` is pushed; `main` remains unchanged; canonical worktree is clean except any explicitly preserved owner change.

---

## 8. Risks and mitigations

1. **The auth endpoint currently uses plaintext HTTP.** Restrict it to the private Tailscale network; require HTTPS before traversing an untrusted network. Make the URL configurable and document trust assumptions.
2. **Auth service availability becomes a protected-route dependency.** Use short timeouts, fail closed, map outages to `503`, and avoid unsafe long-lived identity caches in the first milestone.
3. **Bearer machine keys require TLS.** Do not advertise the managed-key endpoint for public plaintext use. If exact-body HMAC is required, approve the encrypted-secret alternative before implementation.
4. **Tenant predicates can be omitted accidentally.** Require profile IDs in repository signatures, add cross-tenant tests, and enforce ownership with composite database constraints.
5. **External users can be deactivated while local data remains.** Auth rejection blocks access; define data retention/deletion separately rather than cascading from an unavailable external event.
6. **`last_used_at` can create write amplification.** Update opportunistically or with bounded cadence if traffic volume warrants it; do not weaken ingestion atomicity.
7. **Existing unstaged Compose work can be accidentally mixed into the feature.** Resolve ownership before editing `compose.yaml`; never stage it implicitly.

---

## 9. Owner feedback requested

Please approve or revise these decisions before implementation:

1. One profile per auth user now, with teams/workspaces deferred?
2. Lazy profile provisioning on first authenticated Watchtower request?
3. Opaque hashed API keys over TLS, or encrypted user-managed HMAC secrets?
4. Remove legacy deployment-configured HMAC now, or retain it for one migration milestone?
5. Profile-wide keys by default with optional service restriction?
6. Soft-revoke API keys rather than hard-delete audit records?
7. Should the existing unstaged PostgreSQL `5433` host-port change be committed separately, preserved locally, or included in this feature?
8. Can a dedicated non-production auth account/token be provided for successful live session validation?
