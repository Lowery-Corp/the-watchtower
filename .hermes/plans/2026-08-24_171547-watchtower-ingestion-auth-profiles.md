# The Watchtower Ingestion, API-Key, and Auth-Profile Implementation Plan

> **For Hermes / implementing agent:** This document is a planning artifact only. Do not implement, edit application code, migrate a database, build containers, commit, or push until the user explicitly authorizes execution. When authorized, work only on `vm-work-dev-db` in `/home/lowery/the-watchtower`, use the `dev` branch for implementation commits/pushes, preserve unrelated work, and execute the checklist in order.

**Goal:** Build The Watchtower as a horizontally scalable, stateless FastAPI service that authenticates human operators through `https://dauth.johnmgrubbs.io`, identifies producer applications through managed API keys, and durably stores application logs, metrics, and generic webhook events in PostgreSQL.

**Architecture:** Keep identity/password/session authority in DAuth. Store Watchtower-specific authorization profiles, applications, API-key metadata, and event data in PostgreSQL. Every API instance remains interchangeable: it keeps no local sessions, no in-memory credential registry, and no replica-local ingestion state. Human browser tokens live only in secure HttpOnly cookies; machine API keys are verified from a public key identifier plus a protected verifier stored in PostgreSQL.

**Tech stack:** FastAPI, Pydantic v2, SQLAlchemy 2 async, asyncpg, Alembic, PostgreSQL 17, httpx, React/Vite, Axios, Docker Compose, pytest/pytest-asyncio/httpx test client.

---

## 0. Planning boundary and current repository state

- [ ] Do not begin implementation until the user explicitly says to proceed.
- [ ] Re-baseline the remote repository immediately before implementation; do not rely on the state recorded in this plan.
- [ ] Canonical worktree: `vm-work-dev-db:/home/lowery/the-watchtower`.
- [ ] Required implementation/push branch: `dev`.
- [ ] Current observed branch during planning: `rework` at `cc9ad9a`.
- [ ] Current observed unrelated modifications that must not be overwritten or accidentally committed:
  - `watchtowers-backend/api/v1/endpoints/auth.py`
  - `watchtowers-frontend/src/App.jsx`
- [ ] Before switching branches or editing, have the user identify whether the current `rework` changes should be preserved, committed separately, moved, or discarded. Never decide silently.
- [ ] Record `HEAD`, `origin/dev`, `origin/main`, branch, worktree status, staged paths, and staged-diff hash before any implementation write.
- [ ] Keep `main` unchanged. Push only an explicitly reviewed `dev` commit.
- [ ] Commit immediately after every completed feature once that feature's focused tests and verification pass. Keep each feature in its own narrowly scoped commit; do not combine unrelated features or defer all commits until the end.
- [ ] Before every feature commit, stage only that feature's allowlisted files, inspect the staged diff, run `git diff --cached --check`, and verify no unrelated dirty files or secrets are included.
- [ ] Do not push intermediate feature commits until the planned final review unless the user explicitly requests otherwise; when pushing, push the reviewed `dev` history only.

## 1. Confirmed requirements

### Functional

- [ ] Receive authenticated webhook events from multiple external applications.
- [ ] Support logs, metrics, and a generic/custom event type without requiring a new table for every producer.
- [ ] Store accepted events durably in PostgreSQL before acknowledging success.
- [ ] Derive the producer application from the API key; never trust a caller-supplied application ID.
- [ ] Allow authenticated human users to register and manage applications.
- [ ] Allow authorized users to create, list, rotate, revoke, and inspect usage metadata for API keys.
- [ ] Add Watchtower auth profiles linked to identities from DAuth.
- [ ] Support profile roles/permissions for administration and per-application access.
- [ ] Provide a frontend for application, API-key, profile/access, and event management.
- [ ] Keep the current logout button intentionally inert: clicking it must not call DAuth, call Watchtower logout, clear local auth state, clear cookies, or navigate. Logout behavior is deferred until the user revisits it.

### Non-functional

- [ ] Keep the API stateless across replicas and restarts.
- [ ] Keep all secrets in untracked `.env` files; commit only `.env.example` files containing placeholders.
- [ ] Never store raw API keys in PostgreSQL, logs, traces, error messages, or frontend storage.
- [ ] Make ingestion idempotent when the sender provides an external event ID or idempotency key.
- [ ] Apply payload-size limits, validation, rate limiting, and consistent error responses.
- [ ] Produce audit records for security-sensitive management actions.
- [ ] Use migrations for every schema change.

## 2. Explicit architecture decisions

### 2.1 Statelessness definition

The Watchtower API may hold short-lived request-local objects and shared network connection pools, but it must not depend on process-local state for identity, authorization, API-key validity, ingestion correctness, or user sessions.

- PostgreSQL is the source of truth for profiles, roles, applications, key status, events, and audit records.
- DAuth is the source of truth for human identity, password verification, account activity, token validity, and global DAuth admin status.
- The browser may carry an opaque DAuth access token in a `Secure`, `HttpOnly`, `SameSite=Lax` cookie set by the Watchtower backend. That remains stateless because any Watchtower replica can validate it through DAuth.
- Do not store auth tokens in React state, `localStorage`, or `sessionStorage`.
- Do not use an in-memory map for API keys, roles, rate counters, idempotency, or revocation.
- PostgreSQL-backed limits are acceptable for MVP. A shared Redis service may be introduced later only if throughput requires it; replica-local counters are not acceptable.

### 2.2 Authentication versus authorization

Keep the two concerns separate:

1. **DAuth identity authentication**
   - Validates email/password.
   - Issues and revokes access tokens.
   - Returns stable user ID, username/email, activity, and global `is_admin` metadata.
2. **Watchtower auth profile**
   - Keyed by the stable DAuth user UUID.
   - Stores Watchtower status and Watchtower-specific roles/permissions.
   - Does not store passwords or duplicate DAuth credentials.
3. **Application API key authentication**
   - Used only on machine ingestion endpoints.
   - Resolves directly to one Watchtower application and a set of ingestion scopes.
   - Is not a DAuth user token and must never grant human dashboard access.

### 2.3 DAuth integration contract observed during planning

Source documentation: `https://dauth.johnmgrubbs.io/docs#/` and `/openapi.json`, version `0.1.0`.

Current usable contract:

- `POST /api/v1/auth/login`
  - Body: `{ "email": "...", "password": "...", "internal": true }`.
  - Internal response currently includes `id`, `username`, `is_admin`, and `token`.
- `POST /api/v1/auth/me`
  - Current service implementation reads the opaque token from the nonstandard `token` request header.
  - Response includes `id`, `username`, `is_admin`, and `token`.
- `POST /api/v1/auth/logout`
  - Logout behavior and the current token-transport inconsistency are explicitly out of scope for this implementation cycle.
  - The Watchtower frontend logout button must remain a no-op until the user authorizes logout work.
- `GET /api/v1/auth/me`, `/token-check`, and `/is-admin` use the DAuth cookie flow.

Contract gaps to resolve before final auth implementation:

- [ ] Decide whether DAuth will formally support `Authorization: Bearer <token>` for service-to-service introspection, or whether Watchtower must continue using the current `token` header.
- [ ] Update DAuth's OpenAPI security schemes and endpoint documentation so actual token transport is documented.
- [ ] Confirm cookie name/domain/SameSite behavior for the deployed Watchtower and DAuth hostnames.
- [ ] Pin this integration with contract tests so a DAuth change cannot silently break Watchtower.

Recommended direction for current scope: standardize DAuth introspection calls on `Authorization: Bearer <token>`, while retaining cookie authentication for direct browser requests. Until DAuth supports that contract, isolate the current `token` header behavior in one DAuth client module rather than spreading it through route code. Do not modify or depend on logout behavior during this cycle.

### 2.4 API-key format and storage

Recommended generated form:

`wt_live_<public_key_id>.<random_secret>`

- `public_key_id`: nonsecret, indexed identifier used to locate one key row.
- `random_secret`: at least 32 cryptographically random bytes, URL-safe encoded.
- Store only:
  - public key ID,
  - key prefix/last four for display,
  - HMAC-SHA-256 verifier of the complete secret using `WATCHTOWER_API_KEY_PEPPER`,
  - application ID,
  - scopes,
  - status and timestamps.
- Show the raw key exactly once at creation/rotation time.
- Compare verifiers with a constant-time comparison.
- Keep the pepper only in backend `.env`; support a documented rotation strategy before changing it.
- Never accept an application ID from an ingestion caller as authority; resolve it from the key row.

### 2.5 Ingestion model

Use one normalized event envelope and a PostgreSQL `JSONB` payload for MVP:

```json
{
  "external_event_id": "producer-unique-id-or-null",
  "event_type": "log",
  "occurred_at": "2026-08-24T17:00:00Z",
  "source": "payments-api",
  "topic": "checkout",
  "severity": "error",
  "payload": {
    "message": "charge failed",
    "duration_ms": 287,
    "tags": {"region": "us-east"}
  }
}
```

Rules:

- `event_type`: controlled values `log`, `metric`, or `event` for MVP.
- `application_id`: server-derived from API key.
- `received_at`: server-generated UTC timestamp.
- `occurred_at`: producer timestamp; optional, validated, stored separately.
- `external_event_id`: optional; when supplied, unique within the application.
- `payload`: required JSON object with configurable maximum request size.
- Preserve the request ID for traceability, but do not persist secrets or full request headers.
- Return success only after the PostgreSQL transaction commits.
- Suggested endpoint: `POST /api/v1/ingest/events` with `Authorization: Bearer <watchtower-api-key>`.
- MVP success: `201 Created`; duplicate idempotent replay returns the existing event identity without inserting a second row.
- Batch ingestion, durable queues, partitioning, TimescaleDB, and OpenTelemetry-native ingestion are later phases unless concrete volume requirements justify them now.

## 3. Proposed PostgreSQL schema

All tables use UUID primary keys, timezone-aware timestamps, explicit foreign keys, and Alembic migrations under the existing `app` schema.

### `auth_profiles`

- `id UUID PK`
- `dauth_user_id UUID UNIQUE NOT NULL`
- `email CITEXT or normalized VARCHAR NOT NULL`
- `display_name VARCHAR NULL`
- `status ENUM(active, suspended) NOT NULL`
- `last_authenticated_at TIMESTAMPTZ NULL`
- `created_at`, `updated_at`

Do not duplicate passwords, DAuth tokens, or DAuth's credential state.

### `roles`

- `id UUID PK`
- `name VARCHAR UNIQUE NOT NULL`
- Seed MVP roles: `watchtower_admin`, `app_admin`, `viewer`.

### `profile_roles`

- `profile_id FK auth_profiles`
- `role_id FK roles`
- Optional `application_id FK applications` for app-scoped roles; null means global.
- Unique constraint across profile, role, and scope.

Suggested permissions:

- `watchtower_admin`: manage all profiles, applications, keys, and events.
- `app_admin`: manage assigned applications and their keys; read their events.
- `viewer`: read assigned applications and events; cannot reveal/create/revoke keys.

### `applications`

- `id UUID PK`
- `slug VARCHAR UNIQUE NOT NULL`
- `name VARCHAR NOT NULL`
- `description TEXT NULL`
- `status ENUM(active, disabled) NOT NULL`
- `created_by_profile_id FK auth_profiles`
- `created_at`, `updated_at`

Disabling an application rejects all of its keys without deleting historical data.

### `api_keys`

- `id UUID PK`
- `application_id FK applications NOT NULL`
- `public_key_id VARCHAR UNIQUE NOT NULL`
- `secret_verifier BYTEA/VARCHAR NOT NULL`
- `display_prefix VARCHAR NOT NULL`
- `name VARCHAR NOT NULL`
- `scopes TEXT[] or normalized key-scope table`
- `status ENUM(active, revoked) NOT NULL`
- `created_by_profile_id FK auth_profiles`
- `created_at`, `expires_at NULL`, `revoked_at NULL`, `last_used_at NULL`
- Optional `replaced_by_key_id FK api_keys` to connect rotations.

MVP scopes: `ingest:logs`, `ingest:metrics`, `ingest:events`. A request's `event_type` must match the key scope.

### `events`

- `id UUID PK`
- `application_id FK applications NOT NULL`
- `api_key_id FK api_keys NOT NULL`
- `external_event_id VARCHAR NULL`
- `event_type ENUM(log, metric, event) NOT NULL`
- `source VARCHAR NULL`
- `topic VARCHAR NULL`
- `severity VARCHAR NULL`
- `occurred_at TIMESTAMPTZ NULL`
- `received_at TIMESTAMPTZ NOT NULL`
- `request_id UUID/VARCHAR NOT NULL`
- `payload JSONB NOT NULL`
- Unique partial constraint/index on `(application_id, external_event_id)` when external ID is not null.
- Indexes on `(application_id, received_at DESC)`, `(application_id, event_type, received_at DESC)`, and severity only if query requirements justify it.

Do not add a broad GIN index to all payloads until real query patterns justify its write/storage cost.

### `audit_events`

- `id UUID PK`
- `actor_profile_id FK auth_profiles NULL`
- `action VARCHAR NOT NULL`
- `target_type`, `target_id`
- `application_id NULL`
- `request_id`
- `metadata JSONB` containing nonsecret context only
- `created_at`

Minimum audited actions: application create/disable, profile suspend/reactivate, role grant/revoke, API-key create/rotate/revoke, and failed privileged authorization attempts where useful.

## 4. API surface and authorization matrix

### Human auth/profile endpoints

- `POST /api/v1/auth/login` — proxy DAuth login, set secure HttpOnly cookie, upsert the local auth profile.
- `GET /api/v1/auth/me` — validate token through DAuth and return DAuth identity plus Watchtower roles/app memberships.
- `POST /api/v1/auth/logout` — deferred/out of scope. Do not rely on this endpoint in the current frontend flow.
- `GET /api/v1/profiles` — global admin only.
- `GET /api/v1/profiles/{id}` — self or global admin.
- `PATCH /api/v1/profiles/{id}` — profile-safe fields for self; status/roles only for authorized admins.
- `PUT/DELETE /api/v1/profiles/{id}/roles/{role}` — global admin, or app admin for roles scoped to an app they administer.

### Application endpoints

- `POST /api/v1/applications` — authenticated user; creator receives app-admin membership.
- `GET /api/v1/applications` — only applications visible to current profile; all for global admin.
- `GET/PATCH /api/v1/applications/{id}` — app viewer/read; app admin/write.
- `POST /api/v1/applications/{id}/disable` — app admin or global admin.

### API-key endpoints

- `POST /api/v1/applications/{id}/api-keys` — app/global admin; raw key returned once.
- `GET /api/v1/applications/{id}/api-keys` — metadata only, never verifier/raw secret.
- `POST /api/v1/applications/{id}/api-keys/{key_id}/rotate` — create replacement and revoke old key either immediately or at an explicit cutoff.
- `POST /api/v1/applications/{id}/api-keys/{key_id}/revoke` — idempotent revocation.

### Ingestion/query endpoints

- `POST /api/v1/ingest/events` — Watchtower API key only; event type must match key scope.
- Optional post-MVP: `POST /api/v1/ingest/events/batch` with bounded count and body size.
- `GET /api/v1/events` — authenticated human profile, application-scoped authorization, bounded pagination and filters.
- `GET /api/v1/events/{id}` — authenticated human profile with access to event's application.

Never allow a human cookie to authenticate machine ingestion by accident, and never allow an application API key to authenticate management endpoints.

## 5. Agent-friendly implementation checklist

### Phase A — Safety baseline and test harness

**Likely files**

- Create: `watchtowers-backend/tests/conftest.py`
- Create: `watchtowers-backend/tests/unit/`
- Create: `watchtowers-backend/tests/integration/`
- Create: `watchtowers-backend/pytest.ini` or add equivalent project test configuration
- Modify: `watchtowers-backend/requirements.txt`

**Checklist**

- [ ] Re-baseline branch/dirty state and resolve the existing `rework` modifications before touching code.
- [ ] Check out/update `dev` without discarding unrelated changes.
- [ ] Add pytest, pytest-asyncio, and test database fixtures.
- [ ] Use a separate PostgreSQL test database/schema; never point tests at development data.
- [ ] Add a FastAPI app/client fixture with dependency overrides for DB and DAuth.
- [ ] Run the empty/smoke suite in Docker Compose and verify it passes.
- [ ] Commit only the allowlisted harness files.

**Validation**

```bash
docker compose -f compose.dev.yaml config
docker compose -f compose.dev.yaml run --rm api pytest -q
```

### Phase B — Configuration and secret hygiene

**Likely files**

- Modify: `.gitignore`
- Modify: `watchtowers-backend/core/config.py`
- Create: `watchtowers-backend/.env.example`
- Create: `watchtowers-frontend/.env.example`
- Modify: `compose.dev.yaml`
- Create: `watchtowers-backend/tests/unit/core/test_config.py`

**Checklist**

- [ ] Add validated settings for `DATABASE_URL`, `AUTH_API_URL`, `COOKIE_KEY`, `WATCHTOWER_API_KEY_PEPPER`, payload limits, token/cookie policy, allowed origins, and environment name.
- [ ] Remove unused secret requirements from settings only after proving no active caller uses them.
- [ ] Keep real values only in ignored `.env` files.
- [ ] Add placeholders and comments to `.env.example`; never add real values.
- [ ] Fail startup clearly when required production secrets are absent or weak.
- [ ] Verify `git status` and scan staged additions for secret formats before every commit.

### Phase C — Correct the model registry and create database migrations

**Likely files**

- Create: `watchtowers-backend/models/auth_profile.py`
- Create: `watchtowers-backend/models/role.py`
- Create: `watchtowers-backend/models/application.py`
- Create: `watchtowers-backend/models/api_key.py`
- Replace/refactor: `watchtowers-backend/models/webhook.py`
- Refactor or remove: `watchtowers-backend/models/topic.py`
- Modify: `watchtowers-backend/models/__init__.py`
- Modify: `watchtowers-backend/db/base.py`
- Create: `watchtowers-backend/alembic/versions/<revision>_watchtower_core_tables.py`
- Create: `watchtowers-backend/tests/integration/db/test_core_schema.py`

**Checklist**

- [ ] Write schema tests first for constraints, cascades/restrict behavior, indexes, enum/check constraints, and uniqueness.
- [ ] Fix existing naming/model issues (`Events` class duplicated in topic/webhook modules, missing event payload columns, and only `signin_log` imported into metadata).
- [ ] Add the schema in one reviewable migration or a short ordered migration series.
- [ ] Ensure Alembic creates/uses the `app` schema safely on a fresh PostgreSQL database.
- [ ] Run upgrade from empty DB, downgrade where safe, and upgrade again.
- [ ] Confirm autogenerate reports no unexplained drift after migration.

### Phase D — Isolated DAuth client and contract tests

**Likely files**

- Create: `watchtowers-backend/clients/dauth.py`
- Create: `watchtowers-backend/schemas/dauth.py`
- Refactor: `watchtowers-backend/repositories/auth.py`
- Refactor: `watchtowers-backend/repositories/user.py`
- Modify: `watchtowers-backend/httpxC/http_client.py`
- Create: `watchtowers-backend/tests/unit/clients/test_dauth.py`
- Create: `watchtowers-backend/tests/contract/test_dauth_contract.py`

**Checklist**

- [ ] Write tests for successful login/introspection, 401, 403 inactive user, timeout, malformed response, and DAuth 5xx.
- [ ] Put all DAuth paths, headers, timeouts, and response parsing in one client.
- [ ] Never log email/password/token bodies.
- [ ] Use short timeouts and bounded retries only for safe/idempotent DAuth requests; do not blindly retry login side effects.
- [ ] Translate DAuth failures into stable Watchtower error responses without leaking internals.
- [ ] Add an opt-in live contract test against `https://dauth.johnmgrubbs.io`; keep normal unit tests mocked and deterministic.
- [ ] Leave logout implementation unchanged and out of scope; contract tests must not make logout a release requirement for this cycle.

### Phase E — Human sessions and Watchtower auth profiles

**Likely files**

- Refactor: `watchtowers-backend/api/v1/endpoints/auth.py`
- Refactor: `watchtowers-backend/auth/dependencies.py`
- Create: `watchtowers-backend/api/v1/endpoints/profiles.py`
- Create: `watchtowers-backend/repositories/auth_profiles.py`
- Create: `watchtowers-backend/services/authorization.py`
- Create: `watchtowers-backend/schemas/auth_profile.py`
- Modify: `watchtowers-backend/api/v1/api.py`
- Create: `watchtowers-backend/tests/integration/api/test_auth.py`
- Create: `watchtowers-backend/tests/integration/api/test_profiles.py`

**Checklist**

- [ ] Remove the duplicate `GET /auth/me` route currently present in `auth.py`.
- [ ] Make cookie reads/deletes consistently use `settings.cookie_key`.
- [ ] Set `Secure`, `HttpOnly`, explicit path, expiry, and environment-appropriate SameSite/domain settings.
- [ ] On successful DAuth login, upsert `auth_profiles` by stable DAuth user ID.
- [ ] Return a structured current-user object, not a bare username string.
- [ ] Enforce suspended-profile denial even when the DAuth token remains valid.
- [ ] Keep local profile/role queries in PostgreSQL; no process-local permissions cache.
- [ ] Implement global and app-scoped authorization dependencies.
- [ ] Audit role/status changes.
- [ ] Test cookie attributes, token rejection, inactive/suspended profile behavior, and privilege boundaries.

### Phase F — Applications and memberships

**Likely files**

- Create: `watchtowers-backend/api/v1/endpoints/applications.py`
- Create: `watchtowers-backend/repositories/applications.py`
- Create: `watchtowers-backend/services/applications.py`
- Create: `watchtowers-backend/schemas/application.py`
- Modify: `watchtowers-backend/api/v1/api.py`
- Create: `watchtowers-backend/tests/integration/api/test_applications.py`

**Checklist**

- [ ] Write authorization matrix tests first.
- [ ] Create applications with normalized unique slugs.
- [ ] Give creator app-admin access transactionally.
- [ ] List only applications visible to the current profile.
- [ ] Disable rather than hard-delete applications with event history.
- [ ] Verify disabled applications reject all machine ingestion.
- [ ] Audit create/update/disable operations.

### Phase G — API-key lifecycle

**Likely files**

- Create: `watchtowers-backend/security/api_keys.py`
- Create: `watchtowers-backend/api/v1/endpoints/api_keys.py`
- Create: `watchtowers-backend/repositories/api_keys.py`
- Create: `watchtowers-backend/services/api_keys.py`
- Create: `watchtowers-backend/schemas/api_key.py`
- Create: `watchtowers-backend/auth/api_key_dependencies.py`
- Modify: `watchtowers-backend/api/v1/api.py`
- Create: `watchtowers-backend/tests/unit/security/test_api_keys.py`
- Create: `watchtowers-backend/tests/integration/api/test_api_keys.py`

**Checklist**

- [ ] Write deterministic tests around injected randomness/verifier helpers, plus integration tests with real generated keys.
- [ ] Generate keys with `secrets`, return raw value once, and persist only verifier/display metadata.
- [ ] Resolve the application from the key; reject unknown, malformed, expired, revoked, or disabled-app keys identically enough to avoid credential enumeration.
- [ ] Update `last_used_at` without making ingestion correctness depend on that update succeeding; avoid a write hotspot if volume becomes high.
- [ ] Enforce scopes per event type.
- [ ] Make revoke idempotent.
- [ ] Make rotation explicit and auditable; document whether old key revocation is immediate or scheduled.
- [ ] Prove list/get responses never serialize `secret_verifier`.

### Phase H — Durable event ingestion

**Likely files**

- Replace/refactor: `watchtowers-backend/api/v1/endpoints/webhook.py`
- Create: `watchtowers-backend/api/v1/endpoints/ingest.py`
- Refactor: `watchtowers-backend/schemas/webhook.py` into `schemas/event.py`
- Create: `watchtowers-backend/repositories/events.py`
- Create: `watchtowers-backend/services/ingestion.py`
- Modify: `watchtowers-backend/api/v1/api.py`
- Create: `watchtowers-backend/tests/integration/api/test_ingestion.py`

**Checklist**

- [ ] Replace the current authenticated `GET /webhook` endpoint with a body-bearing `POST` ingestion endpoint.
- [ ] Write tests first for every event type, application attribution, invalid key, wrong scope, disabled app, payload limits, malformed timestamps, idempotent replay, concurrent duplicate delivery, DB rollback, and secret-safe logs.
- [ ] Parse API-key auth only on ingestion routes.
- [ ] Validate the envelope and enforce body limits before expensive processing.
- [ ] Resolve the key/application server-side and insert in one transaction.
- [ ] Acknowledge only after commit.
- [ ] Handle duplicate `(application_id, external_event_id)` safely under concurrency using a database uniqueness constraint, not a check-then-insert race.
- [ ] Return stable machine-readable errors with request IDs.
- [ ] Remove event/body `print()` statements.
- [ ] Do not send the event to the existing offload worker in MVP unless the durability/acknowledgement contract is redesigned around a durable queue.

### Phase I — Event query API

**Likely files**

- Create: `watchtowers-backend/api/v1/endpoints/events.py`
- Extend: `watchtowers-backend/repositories/events.py`
- Create/extend: `watchtowers-backend/schemas/event.py`
- Create: `watchtowers-backend/tests/integration/api/test_events.py`

**Checklist**

- [ ] Require human DAuth/profile authorization, not an ingestion key.
- [ ] Filter by accessible applications at query time.
- [ ] Add cursor pagination ordered by `(received_at, id)`.
- [ ] Support bounded filters for application, type, source/topic, severity, and time range.
- [ ] Cap page sizes and date ranges.
- [ ] Verify app users cannot infer the existence of inaccessible events.
- [ ] Use observed query plans to justify additional indexes.

### Phase J — Frontend management experience

**Likely files**

- Refactor: `watchtowers-frontend/src/auth/AuthProvider.jsx`
- Refactor: `watchtowers-frontend/src/services/AuthService.jsx`
- Extend: `watchtowers-frontend/src/services/api.jsx`
- Create: `watchtowers-frontend/src/services/applications.js`
- Create: `watchtowers-frontend/src/services/apiKeys.js`
- Create: `watchtowers-frontend/src/services/events.js`
- Create: `watchtowers-frontend/src/pages/Applications.jsx`
- Create: `watchtowers-frontend/src/pages/ApplicationDetail.jsx`
- Create: `watchtowers-frontend/src/pages/ApiKeys.jsx`
- Create: `watchtowers-frontend/src/pages/Events.jsx`
- Create: `watchtowers-frontend/src/pages/Profiles.jsx`
- Modify after reconciling existing dirty work: `watchtowers-frontend/src/App.jsx`
- Add component/service tests using the project's selected React test tooling.

**Checklist**

- [ ] Model `user` as an object containing identity and permissions; current code alternates between a username string and `user.permissions`.
- [ ] Standardize login input on email/password to match DAuth.
- [ ] Remove credential/user console logging.
- [ ] Make the visible logout button intentionally inert: no API request, no cookie manipulation, no auth-state clearing, and no navigation. Add a concise code comment/TODO stating that logout is deliberately deferred by product decision.
- [ ] Provide application create/list/detail flows.
- [ ] Provide API-key create/rotate/revoke UI with a one-time secret reveal and explicit copy/download warning.
- [ ] Never retain the raw key after leaving/closing the one-time reveal state.
- [ ] Provide role-aware navigation and disabled controls; backend authorization remains authoritative.
- [ ] Provide event filters/pagination and safe JSON payload rendering.
- [ ] Provide profile/role management only to authorized admins.
- [ ] Test 401 session expiry, 403 authorization, one-time key behavior, and inaccessible routes.

### Phase K — Operational controls and observability

**Likely files**

- Extend: `watchtowers-backend/middleware/request_id.py`
- Extend: `watchtowers-backend/api/v1/endpoints/health.py`
- Create: `watchtowers-backend/middleware/body_limit.py` if server/proxy controls are insufficient
- Modify: `compose.dev.yaml`
- Modify: `README.md`
- Populate: `APP_STRUCTURE_BLUEPRINT.md`

**Checklist**

- [ ] Emit structured logs with request ID, route, status, latency, application ID, and public key ID only; never raw key/token/payload by default.
- [ ] Distinguish liveness from readiness; readiness verifies required PostgreSQL connectivity and critical configuration.
- [ ] Add configurable body-size and per-key rate limits.
- [ ] Document backup, retention, key-rotation, compromised-key, and DAuth-outage procedures.
- [ ] Define retention before production: indefinite storage is not an operational plan.
- [ ] Add metrics for ingestion count, rejection reason, DB latency, DAuth latency/failures, duplicate deliveries, and payload sizes.
- [ ] Verify two API replicas can serve alternating login/profile/key/ingestion requests with no sticky sessions.

### Phase L — End-to-end acceptance and release

- [ ] Start from a clean test database using Docker Compose.
- [ ] Run Alembic upgrade successfully.
- [ ] Authenticate a human through DAuth.
- [ ] Confirm a local Watchtower profile is created without a password/token column.
- [ ] Create an application and API key.
- [ ] Confirm the raw key is returned once and absent from DB/logs/subsequent API responses.
- [ ] Ingest one log, metric, and generic event.
- [ ] Confirm each event is attributed to the application derived from the key.
- [ ] Replay an event ID and confirm no duplicate row.
- [ ] Revoke the key and confirm the next ingestion is rejected.
- [ ] Rotate a key and verify old/new behavior matches policy.
- [ ] Suspend a profile and confirm its valid DAuth token no longer grants Watchtower access.
- [ ] Confirm cross-application access is denied for viewer/app-admin profiles.
- [ ] Restart/switch API replicas and repeat representative requests to prove statelessness.
- [ ] Run backend tests, frontend tests, linting, migration checks, Compose config/build, health probes, and secret scans.
- [ ] Review exact staged paths and staged diff.
- [ ] Confirm every completed feature already has its own focused commit on `dev`; use a final commit only for genuinely final release/documentation changes.
- [ ] Fetch immediately before push and require `origin/dev` to be the expected ancestor/base of the reviewed local `dev` history.
- [ ] Push explicitly to `origin dev` only.
- [ ] Fetch again and verify remote `dev` equals the new commit and `origin/main` is unchanged.

## 6. Acceptance criteria

The MVP is complete only when all are true:

1. Any healthy Watchtower API replica can process any request without sticky sessions.
2. DAuth authenticates humans; Watchtower stores no human passwords.
3. A DAuth identity maps to one local auth profile and role set.
4. Each machine key maps to exactly one application and explicit ingestion scopes.
5. Raw API keys are shown once and are never recoverable from PostgreSQL.
6. Revocation and application disabling take effect on the next request across all replicas.
7. Every acknowledged event has committed to PostgreSQL.
8. Duplicate external event IDs do not produce duplicate application events, including under concurrency.
9. Human management permissions and machine ingestion permissions cannot be substituted for one another.
10. Secrets exist only in ignored `.env` files/deployment secret storage; committed examples contain placeholders.
11. Audit records exist for key and access-management changes without containing secrets.
12. Automated tests cover auth contract failures, role boundaries, key lifecycle, ingestion durability/idempotency, and cross-application isolation.
13. The complete Docker Compose application builds, migrates, starts healthy, and passes current probes.
14. Implementation commits exist only on `dev`; `main` remains unchanged.
15. Every completed feature has its own narrowly scoped commit created immediately after that feature's tests and verification pass.
16. The logout button is present but intentionally performs no action and makes no network request.

## 7. Risks and tradeoffs

- **DAuth contract drift:** Current OpenAPI omits security schemes and does not fully document token transport. Mitigate with a single client adapter and live opt-in contract tests.
- **Logout deliberately deferred:** The current DAuth/Watchtower logout inconsistency is accepted for now. The frontend button remains inert, and logout/revocation is not an MVP acceptance requirement until the user reopens that scope.
- **DAuth availability:** Per-request remote introspection makes DAuth a runtime dependency. This is simplest and honors revocation immediately, but DAuth latency/outage affects the dashboard. Do not add a local token cache until TTL/revocation behavior is explicitly designed.
- **High-volume metrics:** PostgreSQL JSONB is suitable for an MVP but not automatically ideal for very high-cardinality time-series workloads. Establish volume/query targets before adding partitions, TimescaleDB, or a durable ingestion queue.
- **Key-verifier pepper rotation:** A single pepper is operationally simple but requires a rotation design. A future verifier-version column can support overlap.
- **`last_used_at` hotspot:** Updating it on every event can amplify writes. For MVP this may be acceptable; otherwise update at a bounded interval using shared durable state.
- **Unbounded retention:** Logs and metrics can grow quickly. Production launch needs retention, archive, and deletion policy.
- **Current dirty branch:** Existing uncommitted work on `rework` creates a high risk of accidental overwrite or mixed commits. Resolve it before implementation.

## 8. Open product decisions for the user

These decisions materially affect implementation and should be answered before or during Phase A:

- [ ] Can every authenticated DAuth user create applications, or only Watchtower admins?
- [ ] Should a new DAuth user automatically receive an active Watchtower profile, or require admin approval?
- [ ] Can an application have multiple human members with different app-scoped roles?
- [ ] Should global DAuth `is_admin=true` automatically imply Watchtower admin, or should Watchtower roles remain separately assigned? Recommended: explicit local Watchtower role, with a narrowly documented bootstrap rule.
- [ ] Should key rotation revoke the old key immediately or permit a configurable overlap window?
- [ ] Should API keys expire by default? If yes, choose default/max lifetime.
- [ ] What are expected event rate, peak burst, maximum payload size, and retention duration?
- [ ] Is querying raw payload fields required in MVP, or only envelope fields and full payload display?
- [ ] Is a batch ingestion endpoint required for MVP?
- [ ] When DAuth is unavailable, should dashboard requests fail closed immediately, or is a short validated-token cache acceptable? Recommended MVP: fail closed and expose dependency health.
- [ ] Should app deletion ever be supported, or only disabling/archiving? Recommended: disable/archive only once events exist.

## 9. Recommended MVP cut line

Include in MVP:

- DAuth login/me through an isolated client; logout is deliberately deferred and the frontend button remains a no-op.
- Local auth profiles and three roles.
- Applications and app-scoped membership.
- Create/list/revoke API keys; immediate rotation semantics.
- Single-event ingestion for log/metric/event.
- PostgreSQL durability and external-event idempotency.
- Basic event list/detail filters.
- Management UI for profiles, apps, keys, and events.
- Audit events, body limits, per-key rate limits, health checks, tests, and documentation.

Defer until usage requires it:

- Batch ingestion.
- Kafka/Celery ingestion path.
- TimescaleDB/partitioning.
- Arbitrary JSONPath search and blanket GIN indexing.
- Custom user-defined roles/permission editor.
- API-key overlap scheduling.
- Alerting/rules engine, dashboards, aggregation, and notification channels.
- OpenTelemetry/Prometheus/Loki protocol-native receivers.
