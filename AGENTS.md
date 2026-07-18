# The Watchtower — Agent Operating Reference

## Authority and phase gate

This file is the primary context handoff for AI coding agents working in this repository.

**Current phase: preparation only. Do not scaffold or implement the application until the owner explicitly approves the plan.**

When implementation is approved:

1. Read this file and the current plan under `.hermes/plans/` before editing.
2. Confirm unresolved decisions with the owner instead of silently selecting architecture-changing defaults.
3. Use test-driven development: failing test, minimal implementation, passing test, then refactor.
4. Keep commits small and scoped. Never commit credentials, `.env`, payload samples containing private data, or generated cache/build artifacts.
5. Update this file whenever an approved architecture decision changes.

## Project identity

- Human name: **The Watchtower**
- GitHub/repository slug: **`the-watchtower`**
- Intended owner: **`Lowery-Corp`**
- Intended visibility: **private** (assumption pending owner confirmation)
- Required development host: **`vm-work-dev-db` over SSH**
- Required development checkout: **`/home/lowery/the-watchtower`**
- Local Hermes checkout `/home/lowery/projects/the-watchtower` is an administrative/reference mirror, not the implementation worktree.
- Scope now: backend only
- Primary language/framework: Python + FastAPI
- Primary datastore: PostgreSQL
- Architecture direction: event-driven ingestion with Kafka-compatible topics and an outbox boundary
- Explicitly out of scope for the first implementation: frontend/dashboard, alert delivery, broad analytics, Kubernetes, multi-region deployment

## Product intent

The Watchtower is a centralized logging and uptime-observation backend for the owner's other applications. Services send event envelopes to a webhook. The API authenticates the source, validates and deduplicates the envelope, persists the event in PostgreSQL, and records an outbox message in the same transaction. This transactional outbox prevents acknowledged events from being lost between PostgreSQL and Kafka. Aggregation, uptime-state projection, alerting, and a UI can consume the event stream later.

The first vertical slice must prove this path:

```text
source service
  -> authenticated POST /api/v1/webhooks/events
  -> validate CloudEvents-inspired envelope
  -> deduplicate by source + event id
  -> transactionally insert event + outbox row
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

## Target application structure

Agents should implement toward this structure unless the approved plan changes it:

```text
.
├── AGENTS.md
├── pyproject.toml
├── Dockerfile
├── docker-compose.yaml
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
│       │           ├── webhooks.py
│       │           ├── events.py
│       │           └── services.py
│       ├── core/
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
│       │   ├── monitored_service.py
│       │   ├── event.py
│       │   └── outbox_message.py
│       ├── schemas/
│       │   ├── event.py
│       │   ├── monitored_service.py
│       │   └── health.py
│       ├── repositories/
│       │   ├── events.py
│       │   ├── monitored_services.py
│       │   └── outbox.py
│       ├── services/
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

### Initial write endpoint

```text
POST /api/v1/webhooks/events
```

Expected behavior:

- Require source authentication. Proposed default: per-service HMAC-SHA256 signature over the raw request body plus timestamp.
- Reject stale timestamps to reduce replay risk.
- Enforce a bounded payload size before parsing.
- Validate a versioned, CloudEvents-inspired envelope.
- Normalize all timestamps to UTC.
- Enforce idempotency with a unique `(source, event_id)` constraint.
- Insert the event and outbox message atomically.
- Return `202 Accepted` with the canonical event ID and ingestion status.
- A duplicate retry must be safe and deterministic; do not create duplicate event/outbox rows.

Proposed envelope fields:

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

The exact schema is pending owner approval. Preserve unknown event data in PostgreSQL `JSONB`; do not flatten arbitrary payload fields into columns.

### Operational endpoints

```text
GET /api/v1/health
GET /api/v1/health/live
GET /api/v1/health/ready
```

- `health`: basic service status.
- `live`: process event loop responds.
- `ready`: required dependencies are usable; initially PostgreSQL, and later Kafka according to the approved failure policy.

Read APIs (`GET /events`, `GET /services`) are not part of the first ingestion slice unless the owner approves them.

## Persistence direction

Use PostgreSQL schema `watchtower`.

### `monitored_service`

Purpose: stable identity and source authentication metadata.

Likely fields: UUID primary key, unique slug, display name, environment, active flag, secret hash/key identifier, created/updated timestamps. Never store plaintext webhook secrets.

### `event`

Purpose: immutable canonical event record.

Likely fields: UUID primary key, source event ID, service UUID, event type, severity, environment, subject, occurred/received timestamps, correlation ID, request ID, payload `JSONB`, schema version. Index service/time, type/time, severity/time, received time. Unique source/service + source event ID.

### `outbox_message`

Purpose: reliable bridge from PostgreSQL transaction to Kafka.

Likely fields: UUID primary key, aggregate/event UUID, topic, partition key, serialized payload `JSONB`, created/published timestamps, attempt count, next-attempt time, last error. Index unpublished messages and retry schedule.

Repositories issue SQL and map records. `event_ingestion` owns one transaction that inserts both `event` and `outbox_message`.

## Kafka/event-stream direction

Proposed topic names:

```text
watchtower.events.raw.v1
watchtower.events.normalized.v1
watchtower.uptime.state-changed.v1
watchtower.dead-letter.v1
```

Partition key: monitored service UUID or stable service slug, so per-service ordering is preserved.

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
- Store webhook secrets outside Git; persist only hashes or key IDs.
- Use constant-time signature comparison.
- Include timestamp and signature version in authentication headers.
- Apply request size and rate limits at both proxy and application boundaries.
- Database role should have only required schema privileges.
- Retention and deletion policies are unresolved and must be approved before production use.

## Testing expectations

- Unit tests: envelope validation, HMAC verification, topic mapping, idempotency decisions.
- API tests: valid ingest, invalid signature, replay timestamp, malformed envelope, duplicate retry, oversized body.
- Integration tests against PostgreSQL: event + outbox atomicity, unique constraints, rollback behavior, repository filters.
- Contract tests: exact event-envelope and Kafka-message shapes.
- Worker tests: publish acknowledgement, retry scheduling, duplicate execution.
- Health tests: liveness independent of dependencies; readiness reflects required dependencies.

Use real PostgreSQL for persistence integration tests; SQLite is not an acceptable substitute for PostgreSQL `JSONB`, schemas, constraints, or async behavior.

## Definition of done for the first vertical slice

- A source can submit one signed event.
- Invalid/replayed requests are rejected.
- A valid event and outbox row are committed atomically.
- Retrying the same source event is idempotent.
- The outbox publisher interface and one implementation path are tested.
- Health/live/ready semantics are documented and tested.
- Alembic can upgrade a fresh PostgreSQL database and downgrade the new revision.
- Tests, lint, type checking, and container health checks pass.
- No frontend or unapproved analytics surface is introduced.

## Owner decisions still required

See the plan's decision gate. Do not silently finalize:

1. Private repository visibility.
2. Whether Kafka runs in the first deployed slice or only the outbox interface is implemented.
3. Custom envelope vs strict CloudEvents 1.0 compatibility.
4. HMAC as the initial webhook authentication mechanism.
5. Passive heartbeat only vs active HTTP uptime probes.
6. Event retention period and maximum request size.
7. Initial deployment host and CI expectations.
