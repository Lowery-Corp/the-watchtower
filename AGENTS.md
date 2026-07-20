# The Watchtower — Agent Operating Reference

## Authority and phase gate

This file is the primary context handoff for AI coding agents working in this repository.

**Current phase: the event-ingestion foundation is shipped on `dev`; the approved profiles, external-auth, managed API-key, and tenant-isolation milestone is active but remains uncommitted in the canonical worktree. Application changes must be developed, validated, committed, and pushed only from `/home/lowery/the-watchtower` on `vm-work-dev-db`. Never push implementation commits directly to `main`; promote `dev` through an explicitly reviewed pull request.**

When implementation is approved:

1. Read this file and the current plan under `.hermes/plans/` before editing.
2. Confirm unresolved decisions with the owner instead of silently selecting architecture-changing defaults.
3. Use test-driven development: failing test, minimal implementation, passing test, then refactor.
4. Keep commits small and scoped. Never commit credentials, `.env`, payload samples containing private data, or generated cache/build artifacts.
5. Update this file whenever an approved architecture decision changes.

The canonical worktree currently contains the in-progress tenant/auth/API-key milestone and an unrelated pre-existing `compose.yaml` modification. Before staging or committing, inspect `git status`, preserve the existing index fingerprint, and stage explicit intended paths only. Never use `git add .`, `git add -A`, broad reset/restore commands, or include `compose.yaml` without separate owner direction.

## Project identity

- Human name: **The Watchtower**
- GitHub/repository slug: **`the-watchtower`**
- Intended owner: **`Lowery-Corp`**
- Visibility: **private**
- Development branch: **`dev` only**; do not push implementation commits directly to `main`.
- Required development host: **`vm-work-dev-db` over SSH**
- Required development checkout: **`/home/lowery/the-watchtower`**
- Local Hermes checkout `/home/lowery/projects/the-watchtower` is an administrative/reference mirror, not the implementation worktree.
- Scope now: backend only
- Primary language/framework: Python + FastAPI
- Primary datastore: PostgreSQL
- Architecture direction: tenant-aware event ingestion with external identity, profile-owned resources, Kafka-compatible topics, and a transactional outbox boundary
- Explicitly out of scope for the first implementation: frontend/dashboard, alert delivery, broad analytics, Kubernetes, multi-region deployment

## Product intent

The Watchtower is a centralized, tenant-aware logging and uptime-observation backend for the owner's other applications. The external DB Management Auth API remains the browser identity authority; Watchtower lazily provisions one local profile per stable external subject UUID and uses that profile as the ownership root. Profile owners manage monitored services and digest-only machine API keys. Services submit event envelopes to a webhook through managed keys or an explicitly mapped legacy HMAC compatibility path. The API authenticates the profile and source, validates and deduplicates the envelope, persists the immutable event in PostgreSQL, and records an outbox message in the same transaction. This transactional outbox prevents acknowledged events from being lost between PostgreSQL and Kafka. Aggregation, uptime-state projection, alerting, and a UI can consume the event stream later.

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
- Webhook abuse controls at both boundaries: per-service application budgets and per-IP Nginx edge limits.
- Idempotency by monitored service plus source event UUID; duplicate retries return the original canonical event and create no additional outbox row.
- Service-owned event/outbox transactions; repositories never commit.
- Host port `8010` terminates at the non-root Nginx proxy; FastAPI and PostgreSQL are not published to the host.

The approved but uncommitted canonical-worktree milestone adds:

- Typed, fail-closed external-auth client and browser login/logout/current-user routes.
- One local profile per stable external identity UUID, provisioned idempotently.
- Profile ownership for monitored services, events, outbox rows, and API keys, enforced in repository predicates and PostgreSQL constraints.
- Authenticated profile-scoped service and API-key management routes; cross-profile probes behave as not found.
- Digest-only, one-time-disclosed managed API keys using versioned high-entropy tokens, a non-secret lookup prefix, domain-separated SHA-256 verification, constant-time comparison, optional immutable service binding, expiry, and irreversible soft revocation.
- Managed-key webhook ingestion plus a retained legacy HMAC path that is disabled unless each service slug has both a secret and explicit profile UUID mapping.
- Transaction-time managed-key revalidation, duplicate-header rejection, and atomic `last_used_at` recording with accepted or duplicate event outcomes.
- Origin checks for cookie-authenticated mutations; explicit bearer credentials take precedence and never fall back to cookies when malformed.
- Forward migrations `0005_profile`, `0006_tenant_ownership`, `0007_api_keys`, and `0008_security_hardening`.

Do not describe this active milestone as shipped until full tests, Ruff, strict mypy, dependency checks, Compose validation, Alembic parity and disposable migration cycles, runtime smoke tests, secret scans, and exact-diff reviews all pass and the implementation is committed and pushed to `dev`.

Legacy HMAC signing secrets are supplied only through deployment configuration (`WATCHTOWER_WEBHOOK_SECRETS`) and require matching profile ownership in `WATCHTOWER_LEGACY_WEBHOOK_PROFILES`; neither secret is stored in PostgreSQL or Git. Managed raw API keys are disclosed once and never persisted. Kafka client selection and outbox publication remain gated on a real broker spike.

Exact development commands, run from `/home/lowery/the-watchtower` on `vm-work-dev-db`:

```bash
docker compose config -q
docker compose --profile test build
docker compose up -d db proxy
docker compose run --rm test pytest -v
docker compose run --rm test ruff check src tests alembic
docker compose run --rm test mypy src tests
docker compose run --rm migrate alembic current
docker compose logs --tail 100 api
docker compose ps
```

Alembic downgrades and volume removal are destructive operations and require explicit owner authorization. Never run `docker compose down -v` by default.

## Application structure

Maintain this structure unless the approved plan changes it:

```text
.
├── AGENTS.md
├── pyproject.toml
├── Dockerfile
├── compose.yaml
├── .env.example
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
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
POST/GET /api/v1/api-keys
GET/PATCH/DELETE /api/v1/api-keys/{api_key_id}
```

External auth tokens remain browser-session credentials and are never stored in the Watchtower database. Profile and ownership identity comes only from the stable external UUID, not mutable email, username, or display name. All service and key queries include `profile_id`; cross-profile access returns `404`. Raw managed keys are returned once with `Cache-Control: no-store`, never listed again, and never logged.

## Persistence direction

Use PostgreSQL schema `watchtower`.

### `profile`

Purpose: durable local tenant root keyed by the external auth service's stable subject UUID. Profile deletion is explicit and child-first; tenant roots use restrictive foreign keys rather than accidental cascades.

### `api_key`

Purpose: profile-owned machine credential metadata. Persist only key version, non-secret lookup prefix, fixed-length digest, immutable optional service binding, scopes, expiry/revocation/use timestamps, and audit metadata. Never persist or log the raw token.

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

For the first slice, uptime is passive: services emit `service.heartbeat` and lifecycle/error events. Later projection workers can calculate current status and uptime windows from the stream.

Do not add active polling/scheduling until the owner answers whether Watchtower should also call external health URLs. If approved later, model checks as commands/events rather than embedding scheduler logic in webhook routes.

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
- Apply request size and rate limits at both proxy and application boundaries.
- Database role should have only required schema privileges.
- Retention and deletion policies are unresolved and must be approved before production use.

## Testing expectations

- Unit tests: envelope validation, legacy HMAC verification, managed-key generation/parsing/digest verification, external-auth protocol handling, topic mapping, and idempotency decisions.
- API tests: browser session lifecycle, trusted-origin enforcement, profile-scoped service/key lifecycle, one-time key disclosure, valid managed and legacy ingestion, revocation/expiry/binding failures, duplicate headers, malformed envelope, duplicate retry, and oversized body.
- Integration tests against PostgreSQL: concurrent profile provisioning, profile isolation, composite tenant constraints, key/event/outbox atomicity, unique constraints, rollback behavior, and repository predicates.
- Contract tests: exact event-envelope and Kafka-message shapes.
- Worker tests: publish acknowledgement, retry scheduling, duplicate execution.
- Health tests: liveness independent of dependencies; readiness reflects required dependencies.

Use real PostgreSQL for persistence integration tests; SQLite is not an acceptable substitute for PostgreSQL `JSONB`, schemas, constraints, or async behavior.

## Definition of done for the active tenant milestone

- A validated external subject provisions exactly one local profile, including under concurrent first use.
- Every monitored service, event, outbox row, and API key belongs to one profile; database constraints reject cross-profile relationships.
- Profile owners can manage only their own services and API-key metadata; cross-profile probes do not enumerate resources.
- Raw managed keys are disclosed once, never persisted, and can authenticate only while unexpired and unrevoked and within immutable binding/scope restrictions.
- Managed-key state is revalidated in the same transaction as event/outbox persistence, and failed ingestion does not update `last_used_at`.
- Legacy HMAC works only for explicitly profile-mapped service identities.
- Valid events and outbox rows remain atomic and duplicate retries remain deterministic.
- Alembic upgrades a fresh PostgreSQL database through the full migration head; authorized disposable downgrade/upgrade cycles preserve migration integrity.
- Full tests, Ruff check/format, strict mypy, `pip check`, Compose validation, migration parity, runtime smoke, tenant isolation, and secret scans pass.
- The exact intended diff receives independent review, excludes unrelated `compose.yaml`, is committed only on `dev`, and leaves `main` unchanged.
- No frontend, active polling, production exposure, or unapproved analytics surface is introduced.

## Approved defaults and remaining gates

Implementation began with these owner-approved defaults and subsequent decisions:

1. Private `Lowery-Corp/the-watchtower` repository.
2. CloudEvents-inspired versioned envelopes.
3. External DB Management Auth stable UUIDs are the profile identity; mutable user fields are metadata only.
4. Browser session tokens and machine API keys are separate credential classes.
5. Managed API keys are preferred for webhook ingestion; raw values are disclosed once and only digests are persisted.
6. Legacy per-service HMAC remains only through explicit secret and profile mappings, with timestamp/replay protection.
7. PostgreSQL enforces tenant ownership and the transactional outbox boundary before direct Kafka coupling.
8. Passive heartbeat events precede active probes.
9. Thirty-day proposed raw-event retention and a 256 KiB body limit.
10. Development, commits, and pushes occur on `vm-work-dev-db`, branch `dev` only.

Kafka broker/client selection, public/Tailscale exposure, production deployment, retention enforcement, and active uptime probes remain separate approval or spike gates.
