# The Watchtower — Agent Operating Reference

## Authority and phase gate

This file is the primary context handoff for AI coding agents working in this repository.

**Current phase: the event-ingestion, profiles, external-auth, managed API-key, tenant-isolation, monitored-service management, active uptime-monitor worker, and React operator-frontend foundation is shipped on `dev`; the profile-authenticated read-only uptime API is the active extension and is pending final repository gates/push. Application changes must be developed, validated, committed, and pushed only from `/home/lowery/the-watchtower` on `vm-work-dev-db`. Never push implementation commits directly to `main`; promote `dev` through an explicitly reviewed pull request.**

When implementation is approved:

1. Read this file and the current plan under `.hermes/plans/` before editing.
2. Confirm unresolved decisions with the owner instead of silently selecting architecture-changing defaults.
3. Use test-driven development: failing test, minimal implementation, passing test, then refactor.
4. Keep commits small and scoped. Never commit credentials, `.env`, payload samples containing private data, or generated cache/build artifacts.
5. Update this file whenever an approved architecture decision changes.

Before staging or committing, inspect `git status`, preserve any existing index fingerprint, and stage explicit intended paths only. Never use `git add .`, `git add -A`, broad reset/restore commands, or sweep unrelated work into a feature commit.

## Project identity

- Human name: **The Watchtower**
- GitHub/repository slug: **`the-watchtower`**
- Intended owner: **`Lowery-Corp`**
- Visibility: **private**
- Development branch: **`dev` only**; do not push implementation commits directly to `main`.
- Required development host: **`vm-work-dev-db` over SSH**
- Required development checkout: **`/home/lowery/the-watchtower`**
- Local Hermes checkout `/home/lowery/projects/the-watchtower` is an administrative/reference mirror, not the implementation worktree.
- Scope now: FastAPI backend plus the `watchtowersHouse` JavaScript React operator frontend
- Primary language/frameworks: Python + FastAPI; JavaScript + React + Vite
- Primary datastore: PostgreSQL
- Architecture direction: tenant-aware control plane with a production Node static server serving the built Vite frontend and forwarding browser `/api/*` traffic to FastAPI, external identity, profile-owned resources, Kafka-compatible topics, and a transactional outbox boundary
- Explicitly out of scope for this milestone: alert delivery, broad analytics, Kubernetes, and multi-region deployment

## Product intent

The Watchtower is a centralized, tenant-aware logging and uptime-observation control plane for the owner's other applications. Its JavaScript React frontend provides browser login, profile-aware Home metrics, monitored-service lifecycle management, and managed API-key operations through the frontend static server's same-origin `/api/*` forwarding. **`MonitoredService` is currently the deployed application/source identity used by events, API keys, and application-scoped role memberships; do not introduce a duplicate `applications` table or migrate ingestion references unless a later approved slice explicitly changes that boundary.** The external DB Management Auth API remains the browser identity authority; Watchtower lazily provisions one local profile per stable external subject UUID and uses that profile as the ownership root. Profile owners manage monitored services and digest-only machine API keys. Services submit event envelopes to a webhook through managed keys or an explicitly mapped legacy HMAC compatibility path. The API authenticates the profile and source, validates and deduplicates the envelope, persists the immutable event in PostgreSQL, and records an outbox message in the same transaction. This transactional outbox prevents acknowledged events from being lost between PostgreSQL and Kafka. The active uptime worker separately probes configured HTTPS endpoints and stores current state plus bounded check history. Alerting, event-stream projection, and broader analytics remain later work.

The active tenant milestone extends the shipped vertical slice through this path:

```text
external auth subject UUID
  -> idempotently provision local profile
  -> profile-scoped monitored service + managed API key
  -> authenticated POST /api/v1/webhooks/events
  -> validate CloudEvents-inspired envelope and tenant ownership
  -> deduplicate by profile + service + source event id
  -> transactionally insert event + outbox row and record successful key use
  -> HTTP 202 response
  -> outbox publisher emits Kafka record
```

If Kafka is deferred for the first deployment, retain the outbox table and publisher interface. Do not couple the HTTP endpoint directly to a Kafka client.

## Scrappy API conventions to preserve

This structure is intentionally based on `scrappysScrapyard` from `Lowery-Corp/scrappy`:

- `main.py` constructs FastAPI and owns lifespan/middleware/router registration.
- A versioned aggregate router lives at `api/v1/api.py`.
- Endpoint modules remain thin and use FastAPI dependencies.
- Pydantic request/response contracts live under `schemas/`.
- SQLAlchemy ORM models live under `models/`.
- Database query code lives under `repositories/`.
- Async SQLAlchemy session construction and dependencies live under `db/`.
- Environment-backed settings use `pydantic-settings` under `core/config.py`.
- Alembic owns schema migrations.
- Every response carries an `X-Request-ID`.
- Health, readiness, and liveness routes are separate.

Intentional improvements over Scrappy:

- Package application code under `src/watchtower/`; avoid path-dependent top-level imports.
- Add a `services/` use-case layer. Services own transaction boundaries; repositories never call `commit()`.
- Use structured JSON logging, never `print()`.
- Accept an incoming request/correlation ID when valid; otherwise generate one.
- Do not use wildcard CORS by default.
- Never track `__pycache__`, `.pyc`, local databases, `.env`, test caches, or build output.
- Pin only direct dependencies in `pyproject.toml`; use a lock strategy selected during implementation.

## Backend milestone state

The committed `dev` branch includes:

- FastAPI application factory under `src/watchtower/main.py`.
- Typed `WATCHTOWER_` settings through `pydantic-settings`.
- Versioned `/api/v1/health`, `/live`, and PostgreSQL-backed `/ready` routes.
- Validated/generated `X-Request-ID` middleware.
- Structured JSON logging through `structlog`.
- Async SQLAlchemy engine, `AsyncSession` factory, and FastAPI dependency with caller-owned transactions.
- Alembic async environment and revisions:
  - `0001_initial_schema`: creates PostgreSQL schema `watchtower`.
  - `0002_monitored_service`: creates source identity/key metadata without storing signing secrets.
  - `0003_event_outbox`: creates immutable JSONB events and Kafka-ready transactional outbox rows.
  - `0004_outbox_integrity`: enforces event/service identity consistency for every outbox row.
- Authenticated `POST /api/v1/webhooks/events` using per-service HMAC-SHA256, signed timestamps, constant-time comparison, source binding, and a 256 KiB default body limit.
- Webhook abuse controls use shared PostgreSQL fixed-window application budgets keyed by authenticated managed-key UUID or mapped legacy profile/source identity. Per-identity transaction advisory locks make rollover timing safe across replicas; indexed inactive rows older than 24 hours are batch-pruned under nonblocking per-identity advisory locks during later consumption.
- Idempotency by monitored service plus source event UUID; duplicate retries return the original canonical event and create no additional outbox row.
- Service-owned event/outbox transactions; repositories never commit.
- The frontend is published on host port `5174`; FastAPI and PostgreSQL are published only on host loopback ports `8001` and `5433`, and remote API clients require a trusted TLS ingress. The frontend proxy enforces the configured global request-body limit.

The committed tenant/auth/frontend milestone adds:

- Typed, fail-closed external-auth client and browser login/logout/current-user routes.
- One local profile per stable external identity UUID, provisioned idempotently.
- PostgreSQL-enforced `active`/`suspended` profile access state and database-timed `last_authenticated_at`; successful DAuth validation never reactivates a suspended profile.
- Profile ownership for monitored services, events, outbox rows, and API keys, enforced in repository predicates and PostgreSQL constraints.
- Authenticated profile-scoped service and API-key management routes; cross-profile probes behave as not found.
- Digest-only, one-time-disclosed managed API keys using versioned high-entropy tokens, a non-secret lookup prefix, domain-separated SHA-256 verification, constant-time comparison, optional immutable service binding, expiry, and irreversible soft revocation.
- Managed-key webhook ingestion plus a retained legacy HMAC path that is disabled unless each service slug has both a secret and explicit profile UUID mapping.
- Transaction-time managed-key revalidation, duplicate-header rejection, and atomic `last_used_at` recording with accepted or duplicate event outcomes.
- Origin checks for cookie-authenticated mutations; explicit bearer credentials take precedence and never fall back to cookies when malformed.
- Forward migrations `0005_profile`, `0006_tenant_ownership`, `0007_api_keys`, `0008_security_hardening`, `0009_webhook_rate_limit`, `0010_rate_limit_retention`, `0011_api_key_owner_restrict`, `0012_profile_auth_metadata`, `0013_watchtower_roles`, `0014_watchtower_permissions`, `0015_api_key_application_rbac`, `0016_uptime_monitoring`, and `0017_profile_uptime_keys`.
- A `watchtowersHouse` React/Vite frontend with Login, protected Home, Monitored Services, Uptime Monitors, and API Keys pages. Service ingestion keys support safe listing, service-bound issuance, one-time secret disclosure, metadata rename, and irreversible revocation; the separate profile uptime panel supports singleton issue/reissue only.
- Active HTTPS monitor polling runs in the private `uptime-worker`, stores latest state plus bounded check history, and exposes no host port.
- The active extension adds exactly one route, `GET /api/v1/uptime`, authenticated by a profile-bound `wtp_v1_` key with `uptime:read`; service ingestion remains restricted to service-bound `wtk_v1_` keys with `events:write`.
- Same-origin frontend-server forwarding where browser `/api/*` requests reach FastAPI over the Compose network; both the production server and Vite development server allow `dwatchtower.johnmgrubbs.io`, and `https://dwatchtower.johnmgrubbs.io` is trusted for cookie-authenticated mutations.

Do not describe the profile uptime API extension as fully shipped until full repository tests, Ruff, strict mypy, dependency checks, Compose validation, runtime smoke tests, secret scans, exact-diff reviews, and the separately authorized push to `dev` are complete.

Legacy HMAC signing secrets are supplied only through deployment configuration (`WATCHTOWER_WEBHOOK_SECRETS`) and require matching profile ownership in `WATCHTOWER_LEGACY_WEBHOOK_PROFILES`; neither secret is stored in PostgreSQL or Git. Managed raw API keys are disclosed once and never persisted. Kafka client selection and outbox publication remain gated on a real broker spike.

Exact development commands, run from `/home/lowery/the-watchtower` on `vm-work-dev-db`:

```bash
docker compose config -q
docker compose --profile test build
docker compose up -d --build db api frontend
docker compose run --rm test pytest -v
docker compose run --rm test ruff check src tests alembic
docker compose run --rm test mypy src tests
docker compose run --rm --no-deps frontend-tools npm test
docker compose run --rm --no-deps frontend-tools npm run lint
docker compose run --rm --no-deps frontend-tools npm run build
docker compose run --rm --no-deps frontend-tools npm audit --audit-level=high
docker compose run --rm migrate alembic current
docker compose logs --tail 100 api
docker compose ps
```

Automated deployment is defined in `.github/workflows/deploy.yml` and follows Scrappy's single `build-and-deploy` job structure. Pushes to `main` run the compact Compose/backend/frontend test block, publish `latest` and commit-SHA `watchtower-frontend` and `watchtower-api` images, connect through Tailscale, then execute the same remote pull, Compose shutdown/rebuild, and image-prune sequence used by Scrappy. Keep Watchtower changes on `dev`; deployment begins only after the intended changes reach `main`.

Alembic downgrades and volume removal are destructive operations and require explicit owner authorization. Never run `docker compose down -v` by default.

## Application structure

Maintain this structure unless the approved plan changes it:

```text
.
├── .github/
│   └── workflows/
│       └── deploy.yml
├── AGENTS.md
├── pyproject.toml
├── Dockerfile
├── compose.yaml
├── .env.example
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── watchtowersHouse/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── auth/
│       ├── components/
│       ├── layouts/
│       ├── pages/
│       └── services/
├── src/
│   └── watchtower/
│       ├── __init__.py
│       ├── main.py
│       ├── api/
│       │   └── v1/
│       │       ├── api.py
│       │       └── endpoints/
│       │           ├── health.py
│       │           ├── auth.py
│       │           ├── api_keys.py
│       │           ├── webhooks.py
│       │           └── services.py
│       ├── clients/
│       │   └── auth_service.py
│       ├── core/
│       │   ├── api_keys.py
│       │   ├── config.py
│       │   ├── logging.py
│       │   └── security.py
│       ├── db/
│       │   ├── base.py
│       │   ├── dependencies.py
│       │   └── session.py
│       ├── middleware/
│       │   └── request_context.py
│       ├── models/
│       │   ├── profile.py
│       │   ├── api_key.py
│       │   ├── monitored_service.py
│       │   ├── event.py
│       │   └── outbox_message.py
│       ├── schemas/
│       │   ├── auth.py
│       │   ├── api_key.py
│       │   ├── event.py
│       │   ├── monitored_service.py
│       │   └── health.py
│       ├── repositories/
│       │   ├── profiles.py
│       │   ├── api_keys.py
│       │   ├── events.py
│       │   ├── monitored_services.py
│       │   └── outbox.py
│       ├── services/
│       │   ├── profiles.py
│       │   ├── api_keys.py
│       │   ├── monitored_services.py
│       │   └── event_ingestion.py
│       ├── messaging/
│       │   ├── envelope.py
│       │   ├── topics.py
│       │   └── publisher.py
│       └── workers/
│           └── outbox_publisher.py
└── tests/
    ├── unit/
    ├── integration/
    └── contract/
```

Do not create placeholder modules that have no approved task. The tree is a destination map, not permission to scaffold everything at once.

## API contract direction

### Webhook write endpoint

```text
POST /api/v1/webhooks/events
```

Expected behavior:

- Always require `X-Watchtower-Service` and accept exactly one authentication mode: a managed `X-Watchtower-API-Key`, or the explicitly mapped legacy timestamp/signature pair.
- Reject duplicate authentication headers and ambiguous mixed authentication modes.
- For managed keys, parse the versioned token strictly, look up by non-secret prefix, compare the stored digest in constant time, and revalidate revocation, expiry, profile, and optional service binding inside the ingestion transaction.
- For legacy HMAC, require both a configured secret and `WATCHTOWER_LEGACY_WEBHOOK_PROFILES` profile UUID; there is no tenantless fallback.
- Reject stale legacy timestamps to reduce replay risk.
- Enforce a bounded payload size before parsing.
- Validate a versioned, CloudEvents-inspired envelope.
- Normalize all timestamps to UTC.
- Enforce idempotency with a unique `(profile_id, service_id, source_event_id)` constraint.
- Insert the event and outbox message atomically; update managed-key `last_used_at` only in the same successful transaction.
- Return `202 Accepted` with the canonical event ID and ingestion status.
- A duplicate retry must be safe and deterministic; do not create duplicate event/outbox rows.

Envelope fields:

```json
{
  "spec_version": "1.0",
  "event_id": "UUID supplied by source",
  "event_type": "service.heartbeat",
  "source": "auth-api",
  "subject": "optional component or instance",
  "occurred_at": "UTC RFC3339 timestamp",
  "severity": "info",
  "environment": "production",
  "correlation_id": "optional trace/workflow id",
  "data": {}
}
```

The envelope contract is versioned and implemented. Preserve unknown event data in PostgreSQL `JSONB`; do not flatten arbitrary payload fields into columns. Breaking contract changes require a new version.

### Operational endpoints

```text
GET /api/v1/health
GET /api/v1/health/live
GET /api/v1/health/ready
```

- `health`: basic service status.
- `live`: process event loop responds.
- `ready`: required dependencies are usable; initially PostgreSQL, and later Kafka according to the approved failure policy.

### Authenticated management endpoints

```text
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me
POST/GET /api/v1/services
GET/PATCH/DELETE /api/v1/services/{service_id}
GET /api/v1/services/{service_id}/memberships
PUT/DELETE /api/v1/services/{service_id}/memberships/{profile_id}
POST/GET /api/v1/api-keys
GET/PATCH/DELETE /api/v1/api-keys/{api_key_id}
```

External auth tokens remain browser-session credentials and are never stored in the Watchtower database. Successful login returns an empty `204` plus the HttpOnly cookie; only protected `GET /auth/me` returns current identity and profile metadata. Profile and ownership identity comes only from the stable external UUID, not mutable email, username, or display name. All service and key queries include `profile_id`; cross-profile access returns `404`. Raw managed keys are returned once with `Cache-Control: no-store`, never listed again, and never logged.

### Profile uptime machine endpoint

```text
GET /api/v1/uptime
```

This is the only new route in the profile uptime slice. It requires exactly one `X-Watchtower-Profile-Key` header and never accepts a profile or service selector. Missing, duplicate, malformed, unknown, and superseded keys share the same generic `401`; a valid key for a suspended profile returns `403`; a depleted PostgreSQL-backed budget returns `429` with `Retry-After`. Successful responses use `Cache-Control: no-store`, include every service currently visible through `applications.read`, nest only active monitors, and expose latest state plus a fixed 24-hour rolling uptime percentage. History, custom windows, writes, pagination, public status pages, event payloads, role data, and key metadata are excluded. Callers must use TLS at a trusted ingress.

The UI and existing `POST /api/v1/api-keys` issue or reissue the singleton profile uptime credential. Reissue preserves the row, immediately invalidates the previous token, and discloses the replacement once. Service ingestion keys remain service-bound `wtk_v1_`/`events:write` credentials; profile uptime keys are profile-bound `wtp_v1_`/`uptime:read` credentials and cannot authenticate ingestion.

## Persistence direction

Use PostgreSQL schema `watchtower`.

### `profile`

Purpose: durable local tenant root keyed by the external auth service's stable subject UUID. Profile deletion is explicit and child-first; tenant roots use restrictive foreign keys rather than accidental cascades.

### `role`, `permission`, `role_permission`, and `profile_role`

Purpose: durable normalized human authorization metadata. PostgreSQL is the source of truth. The permission catalog is closed to `profiles.read`, `profiles.manage`, `applications.read`, `applications.manage`, `memberships.manage`, `api_keys.read`, `api_keys.manage`, and `events.read`; deterministic UUID seeds and restrictive foreign keys make role grants stable and explicit. `watchtower_admin` receives every permission, `app_admin` receives application/key management, membership management, and event read access, and `viewer` receives application/event read access. Monitored-service/application list and read operations resolve `applications.read` from these tables, while update and activation operations resolve `applications.manage`; global administrators apply across applications and scoped roles apply only to their assigned application. Membership APIs resolve `memberships.manage` in PostgreSQL and may assign only application-scoped `app_admin` or `viewer`. PUT normalizes a target to exactly one role, preserves an unchanged assignment, and otherwise derives a UUIDv5 with namespace `fe2ed8dc-d070-5687-9b68-51356c0fe51f` from `{application_id}:{profile_id}:{role}`; mutations lock the monitored-service row and retain at least one local `app_admin`, regardless of global admins. Any active profile may create an application, and creation atomically grants that creator `app_admin` in the same PostgreSQL transaction. Human management permissions are intentionally separate from machine API-key ingestion scopes; neither credential class substitutes for the other.

### `api_key`

Purpose: explicitly discriminated machine credential metadata with durable human creator history. Service ingestion credentials are service-bound; the singleton profile uptime credential is profile-bound and supports issue/reissue only. Persist only key kind/version, non-secret lookup prefix, fixed-length digest, binding, scopes, rotation/expiry/revocation/use timestamps, and audit metadata. `profile_id` identifies the human creator and restricts profile deletion; `service_id` is the authoritative machine source and tenant binding. PostgreSQL `api_keys.read` and `api_keys.manage` grants control human metadata access; key mutations and managed ingestion lock the application before authorization or any key-row lock so concurrent membership changes and revocation cannot race authorization or deadlock. Ingestion derives the service owner and slug from the key's database-bound service rather than the creator or request header. Revoked unbound legacy rows remain durable but cannot authenticate or appear in application-scoped lists. Never persist or log the raw token.

### `monitored_service`

Purpose: profile-owned stable source identity.

Required ownership behavior: uniqueness is profile-scoped, every repository predicate includes `profile_id`, and database constraints prevent cross-profile event or key bindings. Legacy HMAC secrets remain deployment-only configuration rather than database columns.

### `event`

Purpose: immutable canonical event record.

Required fields include profile UUID, source event ID, service UUID, event type, severity, environment, subject, occurred/received timestamps, correlation ID, request ID, payload `JSONB`, and schema version. Index profile/service/time and query dimensions. Idempotency is unique by profile, service, and source event ID.

### `outbox_message`

Purpose: reliable bridge from PostgreSQL transaction to Kafka.

Required fields include profile UUID, aggregate/event UUID, topic, tenant-qualified partition key, serialized payload `JSONB`, created/published timestamps, attempt count, next-attempt time, and last error. Database constraints ensure the outbox profile agrees with its referenced event.

Repositories issue SQL and map records. `event_ingestion` owns one transaction that inserts both `event` and `outbox_message`.

## Kafka/event-stream direction

Proposed topic names:

```text
watchtower.events.raw.v1
watchtower.events.normalized.v1
watchtower.uptime.state-changed.v1
watchtower.dead-letter.v1
```

Partition key: tenant-qualified profile UUID plus stable service slug, so tenant isolation and per-service ordering are preserved.

Rules:

- Topic names and envelope versions are constants with contract tests.
- Consumers must be idempotent; delivery is at least once.
- Never make the HTTP request transaction depend on a successful synchronous Kafka publish.
- The outbox publisher marks rows published only after broker acknowledgement.
- Failed publishes use bounded exponential backoff and eventually dead-letter metadata.
- Schema evolution must be additive within a version; breaking changes create a new version/topic.

## Uptime interpretation

Uptime monitoring is active and server-owned. Operators configure profile-authorized HTTPS monitors; the private `uptime-worker` claims due rows with PostgreSQL locking, performs bounded probes, stores latest state, retains bounded check history, and exposes no network port. The profile uptime API reads that state and calculates only the fixed rolling 24-hour window.

Do not move scheduling into webhook or request routes, expose arbitrary history/custom windows, add public status pages, or couple alert delivery to this slice. Event-stream projection and alert delivery remain separate approved work.

## Security and data handling

- Assume log/event payloads can contain sensitive information.
- Reject or redact configured sensitive keys before structured application logging.
- Never log full webhook bodies by default.
- Store browser session tokens, webhook secrets, and raw managed keys outside Git and PostgreSQL.
- Persist only fixed-length managed-key digests plus non-secret lookup metadata; use versioned high-entropy tokens, domain-separated hashing, and constant-time verification.
- Raw API keys are disclosed once with `Cache-Control: no-store`; never include them in list/read responses, logs, fixtures, or examples.
- Keep browser sessions and machine API keys as separate credential classes. Cookie-authenticated state changes require a trusted exact `Origin`; an explicit malformed bearer header must never fall back to a cookie.
- Fail closed on external-auth timeouts, outages, malformed payloads, and protocol drift. Preserve generic non-enumerating authentication responses.
- Revalidate managed-key revocation, expiry, profile, and service binding while holding the ingestion transaction's row lock.
- Legacy HMAC requires timestamp freshness, constant-time signature comparison, and explicit service-to-profile mapping.
- Enforce request size and shared rate limits in the application; production ingress may add independent network-level controls.
- Database role should have only required schema privileges.
- Retention and deletion policies are unresolved and must be approved before production use.

## Testing expectations

- Unit tests: envelope validation, legacy HMAC verification, managed-key generation/parsing/digest verification, external-auth protocol handling, topic mapping, and idempotency decisions.
- API tests: browser session lifecycle, trusted-origin enforcement, profile-scoped service/key lifecycle, one-time key disclosure, valid managed and legacy ingestion, revocation/expiry/binding failures, duplicate headers, malformed envelope, duplicate retry, and oversized body.
- Integration tests against PostgreSQL: concurrent profile provisioning, profile isolation, composite tenant constraints, key/event/outbox atomicity, unique constraints, rollback behavior, and repository predicates.
- Contract tests: exact event-envelope and Kafka-message shapes.
- Worker tests: publish acknowledgement, retry scheduling, duplicate execution.
- Health tests: liveness independent of dependencies; readiness reflects required dependencies.
- Frontend tests: login success/failure, protected navigation, profile-aware Home data, API-key loading/empty/error states, one-time disclosure, safe metadata updates, and revocation. Run Vitest, ESLint, Vite build, and `npm audit` in the profile-gated `frontend-tools` container; the runtime image serves only the built Vite bundle through the non-root Node static server on internal port `5173`.

Use real PostgreSQL for persistence integration tests; SQLite is not an acceptable substitute for PostgreSQL `JSONB`, schemas, constraints, or async behavior.

## Definition of done for the active tenant milestone

- A validated external subject provisions exactly one local profile, including under concurrent first use.
- Every monitored service, event, outbox row, and API key belongs to one profile; database constraints reject cross-profile relationships.
- Profile owners can manage only their own services and API-key metadata; cross-profile probes do not enumerate resources.
- Raw managed keys are disclosed once, never persisted, and can authenticate only while unexpired and unrevoked and within immutable binding/scope restrictions.
- Managed-key state is revalidated in the same transaction as event/outbox persistence, and failed ingestion does not update `last_used_at`.
- Legacy HMAC works only for explicitly profile-mapped service identities.
- Operators can sign in through the React frontend, view profile-aware Home metrics, and list, issue, rename, copy once, and revoke profile-owned API keys without exposing session or key material to persistent browser storage.
- The production frontend server serves built routes and forwards `/api/*` through one configured trusted origin; anonymous protected routes return to Login.
- Valid events and outbox rows remain atomic and duplicate retries remain deterministic.
- Alembic upgrades a fresh PostgreSQL database through the full migration head; authorized disposable downgrade/upgrade cycles preserve migration integrity.
- Full backend and frontend tests, Ruff check/format, strict mypy, ESLint, Vite build, `pip check`, `npm audit`, Compose validation, migration parity, runtime smoke, tenant isolation, and secret scans pass.
- The exact intended diff receives independent review, isolates intended frontend integration hunks from pre-existing unrelated work, is committed only on `dev`, and leaves `main` unchanged.
- Active polling remains isolated to the private uptime worker; no production exposure, public status surface, custom analytics window, or alert delivery is introduced by the profile read API.

## Approved defaults and remaining gates

Implementation began with these owner-approved defaults and subsequent decisions:

1. Private `Lowery-Corp/the-watchtower` repository.
2. CloudEvents-inspired versioned envelopes.
3. External DB Management Auth stable UUIDs are the profile identity; mutable user fields are metadata only.
4. Browser session tokens and machine API keys are separate credential classes.
5. Managed API keys are preferred for webhook ingestion; raw values are disclosed once and only digests are persisted.
6. Legacy per-service HMAC remains only through explicit secret and profile mappings, with timestamp/replay protection.
7. PostgreSQL enforces tenant ownership and the transactional outbox boundary before direct Kafka coupling.
8. Passive heartbeat events preceded the now-shipped private active HTTPS probe worker; request routes never run probes.
9. Thirty-day proposed raw-event retention and a 256 KiB body limit.
10. Development, commits, and pushes occur on `vm-work-dev-db`, branch `dev` only.

Kafka broker/client selection, public/Tailscale exposure, production deployment, raw-event retention enforcement, alert delivery, public status pages, and broader uptime analytics remain separate approval or spike gates.
