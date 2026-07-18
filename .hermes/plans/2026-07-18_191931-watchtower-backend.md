# The Watchtower Backend Implementation Plan

> **For Hermes:** After owner approval, use the test-driven-development workflow and implement this plan task-by-task. Do not begin implementation while the decision gate is unresolved.

**Goal:** Build a backend-only FastAPI service that securely ingests events from other applications, persists them in PostgreSQL, and exposes a reliable Kafka-ready event-stream boundary for later uptime aggregation and display.

**Architecture:** Follow Scrappy's layered FastAPI conventions—versioned endpoints, Pydantic schemas, async SQLAlchemy, repositories, Alembic, request IDs—while adding a service/use-case layer and transactional outbox. The webhook request commits the canonical event and outbox record atomically; a separate publisher moves outbox records to Kafka with at-least-once delivery and idempotent consumers.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2/pydantic-settings, SQLAlchemy 2 async, asyncpg, PostgreSQL, Alembic, Kafka client selected after a spike, pytest, pytest-asyncio/anyio, HTTPX, Ruff, mypy or Pyright, Docker Compose.

---

## Preparation findings

The deployed `dev` version of Scrappy's backend was inspected as the structural reference. Useful conventions:

- `main.py` constructs the app and lifespan.
- `/api/v1` aggregate router includes focused endpoint routers.
- `core/config.py` centralizes environment-backed settings.
- `db/session.py` and `db/dependencies.py` provide async SQLAlchemy sessions.
- Models, schemas, and repositories are separate.
- Alembic controls migrations.
- Request-ID middleware sets `X-Request-ID`.
- Health, ready, and live endpoints are distinct.

Do not reproduce these observed liabilities:

- tracked `__pycache__`/`.pyc` artifacts;
- repository-level commits that prevent service-owned atomic transactions;
- `print()` debugging in request/database paths;
- wildcard CORS defaults;
- a flat import layout dependent on the working directory;
- an uncurated full transitive `requirements.txt` as the design source.

Detailed agent context and target structure are in `AGENTS.md`.

## Decision gate — owner feedback required before Task 1

Proposed defaults are shown in **bold**:

1. Repository: `Lowery-Corp/the-watchtower`, **private**.
2. Event contract: **CloudEvents-inspired versioned envelope**, not strict CloudEvents dependency initially.
3. Source authentication: **per-service HMAC-SHA256 with timestamp and replay window**.
4. Kafka scope: **implement PostgreSQL outbox plus publisher interface in the first slice; run a real Kafka-compatible broker in integration/deployment once the client spike passes**.
5. Uptime scope: **passive heartbeat events first**; defer active HTTP polling.
6. Retention: proposed **30 days for raw events**, with future aggregated records retained longer.
7. Maximum webhook body: proposed **256 KiB**.
8. Initial environment: confirm deployment host, domain/Tailscale exposure, and whether CI should run on GitHub Actions.

No application files should be scaffolded until these decisions are approved or revised.

---

### Task 1: Establish Python package and quality gates

**Objective:** Create the smallest installable FastAPI package with deterministic lint, type, and test commands.

**Files:**
- Create: `pyproject.toml`
- Create: `src/watchtower/__init__.py`
- Create: `tests/__init__.py`
- Create: `.env.example`
- Modify: `.gitignore`

**Steps:**

1. Write a failing import test in `tests/unit/test_package.py` for `import watchtower`.
2. Run the focused test and verify it fails because the package is absent.
3. Add the minimal `src/watchtower` package and direct dependencies only.
4. Configure Ruff, type checking, and pytest in `pyproject.toml`.
5. Run unit tests, Ruff, and the type checker; require clean output.
6. Commit only these files with `chore: initialize watchtower backend package`.

**Verification:** A clean checkout installs, imports `watchtower`, and runs one exact command for each quality gate.

### Task 2: Add typed settings and application factory

**Objective:** Construct FastAPI through an application factory with explicit lifespan and no import-time external connections.

**Files:**
- Create: `src/watchtower/core/config.py`
- Create: `src/watchtower/main.py`
- Create: `tests/unit/core/test_config.py`
- Create: `tests/unit/test_main.py`

**Steps:**

1. Write failing tests for environment parsing and `create_app()` metadata.
2. Verify failures are due to missing settings/app factory.
3. Implement `Settings` with `pydantic-settings` and an injected/cached settings dependency.
4. Implement `create_app()` and module-level `app` without connecting to PostgreSQL/Kafka at import time.
5. Run focused and full unit tests, lint, and types.
6. Commit with `feat: add typed settings and app factory`.

**Verification:** Tests can instantiate multiple isolated app/settings configurations without reading developer secrets.

### Task 3: Add request context and structured logging

**Objective:** Correlate HTTP requests, event ingestion, database rows, and Kafka messages without logging bodies or secrets.

**Files:**
- Create: `src/watchtower/core/logging.py`
- Create: `src/watchtower/middleware/request_context.py`
- Create: `tests/unit/middleware/test_request_context.py`

**Steps:**

1. Write failing tests for generated and accepted request IDs and response `X-Request-ID`.
2. Define validity limits for incoming IDs to prevent log injection.
3. Implement context-local request/correlation fields and JSON logging configuration.
4. Verify logs include request ID while excluding request bodies and auth headers.
5. Run quality gates.
6. Commit with `feat: add request context logging`.

**Verification:** Concurrent requests retain distinct IDs; malformed supplied IDs are replaced.

### Task 4: Define versioned health routes

**Objective:** Provide stable health, liveness, and readiness semantics under `/api/v1`.

**Files:**
- Create: `src/watchtower/api/v1/api.py`
- Create: `src/watchtower/api/v1/endpoints/health.py`
- Create: `src/watchtower/schemas/health.py`
- Create: `tests/api/test_health.py`
- Modify: `src/watchtower/main.py`

**Steps:**

1. Write failing endpoint tests for `/api/v1/health`, `/live`, and `/ready`.
2. Implement thin routes and typed response models.
3. Keep liveness dependency-free; make readiness dependency checks injectable.
4. Verify response contracts and request IDs.
5. Run full quality gates.
6. Commit with `feat: add operational health endpoints`.

**Verification:** Liveness remains 200 when a simulated dependency is down; readiness returns a documented non-ready result.

### Task 5: Configure async PostgreSQL and migration baseline

**Objective:** Add PostgreSQL schema `watchtower`, async session lifecycle, and repeatable Alembic configuration.

**Files:**
- Create: `src/watchtower/db/base.py`
- Create: `src/watchtower/db/session.py`
- Create: `src/watchtower/db/dependencies.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `tests/integration/db/test_session.py`
- Modify: `src/watchtower/core/config.py`

**Steps:**

1. Write a failing PostgreSQL integration test for session acquisition and transaction rollback.
2. Implement async engine/session factory with no hidden commit.
3. Configure model metadata for schema `watchtower` and Alembic imports.
4. Run upgrade/downgrade against disposable PostgreSQL.
5. Run integration and quality gates.
6. Commit with `feat: add postgres persistence foundation`.

**Verification:** A failed use case rolls back all writes; migration upgrade/downgrade works from a fresh database.

### Task 6: Define monitored-service persistence

**Objective:** Represent event sources and authentication key metadata without storing plaintext secrets.

**Files:**
- Create: `src/watchtower/models/monitored_service.py`
- Create: `src/watchtower/schemas/monitored_service.py`
- Create: `src/watchtower/repositories/monitored_services.py`
- Create: `alembic/versions/<revision>_create_monitored_service.py`
- Create: `tests/integration/repositories/test_monitored_services.py`

**Steps:**

1. Write failing model/repository tests for unique slug, active flag, and secret-hash metadata.
2. Implement the model, schema, repository, and migration.
3. Keep commit/rollback outside the repository.
4. Test unique and lookup behavior against PostgreSQL.
5. Run migration round-trip and quality gates.
6. Commit with `feat: add monitored service registry`.

**Verification:** Duplicate service slugs fail predictably; no plaintext secret appears in database fixtures or logs.

### Task 7: Specify the event envelope as a contract

**Objective:** Freeze the approved version-one inbound contract before implementing the endpoint.

**Files:**
- Create: `src/watchtower/schemas/event.py`
- Create: `src/watchtower/messaging/envelope.py`
- Create: `tests/contract/test_event_envelope.py`

**Steps:**

1. Write failing contract tests for required fields, UTC timestamps, event types, severity, payload, and additive unknown-data policy.
2. Add invalid cases for naive timestamps, malformed IDs, oversized fields, and unsupported spec versions.
3. Implement the minimal Pydantic envelope and normalization helpers.
4. Serialize and compare a canonical Kafka-ready payload fixture.
5. Run contract and quality gates.
6. Commit with `feat: define versioned event envelope`.

**Verification:** Contract tests document exact accepted input and canonical output without relying on prose alone.

### Task 8: Implement webhook signature verification

**Objective:** Authenticate source requests and prevent straightforward replay attacks.

**Files:**
- Create: `src/watchtower/core/security.py`
- Create: `tests/unit/core/test_webhook_signatures.py`

**Steps:**

1. Write failing tests for valid signature, wrong secret, altered body, stale timestamp, malformed header, and constant-time comparison path.
2. Define versioned headers such as `X-Watchtower-Timestamp` and `X-Watchtower-Signature`.
3. Implement HMAC-SHA256 verification over timestamp + raw body.
4. Ensure errors do not reveal which credential component failed.
5. Run security-focused and full tests.
6. Commit with `feat: verify signed webhook requests`.

**Verification:** Replaying an otherwise valid signed body outside the configured window is rejected.

### Task 9: Add event and outbox models atomically

**Objective:** Persist immutable events and Kafka-ready outbox messages in one transaction.

**Files:**
- Create: `src/watchtower/models/event.py`
- Create: `src/watchtower/models/outbox_message.py`
- Create: `src/watchtower/repositories/events.py`
- Create: `src/watchtower/repositories/outbox.py`
- Create: `alembic/versions/<revision>_create_event_and_outbox.py`
- Create: `tests/integration/repositories/test_event_outbox.py`

**Steps:**

1. Write failing PostgreSQL tests for JSONB payload, indexes, unique `(service_id, event_id)`, and unpublished outbox lookup.
2. Implement models and repositories without commits.
3. Add migration with explicit constraints and retry indexes.
4. Test rollback: force outbox insertion failure and prove event insertion does not persist.
5. Test migration upgrade/downgrade and quality gates.
6. Commit with `feat: add event and outbox persistence`.

**Verification:** Event and outbox records are all-or-nothing, and duplicate event IDs cannot create duplicate rows.

### Task 10: Implement the ingestion use case

**Objective:** Orchestrate service lookup, idempotency, event persistence, and outbox creation.

**Files:**
- Create: `src/watchtower/services/event_ingestion.py`
- Create: `src/watchtower/messaging/topics.py`
- Create: `tests/integration/services/test_event_ingestion.py`

**Steps:**

1. Write failing tests for first ingestion, duplicate retry, inactive source, and transaction failure.
2. Define topic constants and partition key rules.
3. Implement one service-owned transaction using repositories.
4. Return a typed outcome (`accepted` or `duplicate`) with canonical event ID.
5. Run focused/integration/full quality gates.
6. Commit with `feat: add transactional event ingestion`.

**Verification:** Duplicate retries return the original canonical result and create no additional event/outbox row.

### Task 11: Expose the webhook endpoint

**Objective:** Provide the authenticated `POST /api/v1/webhooks/events` API without embedding business logic in the route.

**Files:**
- Create: `src/watchtower/api/v1/endpoints/webhooks.py`
- Create: `tests/api/test_event_webhook.py`
- Modify: `src/watchtower/api/v1/api.py`

**Steps:**

1. Write failing API tests for valid 202, duplicate retry, invalid signature, stale signature, malformed envelope, inactive source, and oversized payload.
2. Implement raw-body signature dependency and thin endpoint delegation to `event_ingestion`.
3. Return a typed acknowledgement with event ID, status, and request ID.
4. Verify full payload and authorization headers never appear in captured logs.
5. Run API/integration/full quality gates.
6. Commit with `feat: add event ingestion webhook`.

**Verification:** A signed event reaches PostgreSQL/outbox end-to-end, and all rejection paths are stable and documented.

### Task 12: Spike and select Kafka client

**Objective:** Validate a Python Kafka client against the intended broker before binding production interfaces to it.

**Files:**
- Create: `spikes/kafka-client/RESULTS.md`
- Create: temporary spike code under `spikes/kafka-client/`

**Steps:**

1. Confirm broker target (Apache Kafka, Redpanda, or compatible service) with owner.
2. Compare currently maintained async-capable clients for Python/runtime compatibility, delivery acknowledgements, headers, and graceful shutdown.
3. Run a disposable broker and prove keyed publish/consume plus broker-unavailable behavior.
4. Record measured findings and recommendation in `RESULTS.md`.
5. Delete throwaway code unless it is explicitly promoted through tests.
6. Commit only the decision record with `docs: select kafka client`.

**Verification:** Selection is based on a real broker test, not package familiarity.

### Task 13: Implement outbox publisher

**Objective:** Publish pending outbox records with acknowledgements, retries, and safe concurrent workers.

**Files:**
- Create: `src/watchtower/messaging/publisher.py`
- Create: `src/watchtower/workers/outbox_publisher.py`
- Create: `tests/integration/workers/test_outbox_publisher.py`
- Modify: `src/watchtower/core/config.py`

**Steps:**

1. Write failing tests for successful publish, broker failure, retry schedule, worker restart, and concurrent row claiming.
2. Define a publisher protocol separate from the selected client adapter.
3. Claim rows with PostgreSQL locking suitable for multiple workers.
4. Mark published only after broker acknowledgement; record bounded retry metadata on failure.
5. Verify duplicate worker execution remains safe for at-least-once delivery.
6. Run integration/full quality gates and commit with `feat: publish transactional outbox events`.

**Verification:** Broker downtime does not lose committed events; recovery drains pending rows.

### Task 14: Containerize the backend stack

**Objective:** Run API and PostgreSQL reproducibly, adding the approved Kafka-compatible broker scope.

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yaml`
- Modify: `.env.example`
- Create: `tests/smoke/test_compose_stack.py` or equivalent script

**Steps:**

1. Write a failing smoke check for API readiness and webhook ingestion.
2. Build a non-root, health-checked API image.
3. Add PostgreSQL with durable volume and health check.
4. Add broker/outbox worker only according to the approved Kafka decision.
5. Run migrations explicitly during deployment; do not race migrations from every worker.
6. Verify restart persistence, health transitions, and graceful shutdown; commit with `chore: add development container stack`.

**Verification:** A fresh `docker compose up --build` reaches ready state and accepts a signed sample event without manual container edits.

### Task 15: Add CI and operational documentation

**Objective:** Make repository quality and deployment expectations repeatable for agents and maintainers.

**Files:**
- Create: `.github/workflows/ci.yml` if GitHub Actions is approved
- Update: `AGENTS.md`
- Create: `docs/event-contract.md`
- Create: `docs/operations.md`

**Steps:**

1. Configure CI services for PostgreSQL and approved broker scope.
2. Run lint, types, unit, contract, integration, migration round-trip, and image build.
3. Document signature generation, topic contracts, readiness behavior, retention, backup, and outbox recovery.
4. Verify docs commands against the actual stack.
5. Update `AGENTS.md` from proposed to actual structure and decisions.
6. Commit with `ci: validate watchtower backend`.

**Verification:** CI passes from a clean clone and documentation examples produce real verified results.

---

## Acceptance criteria for the approved MVP

- FastAPI backend only; no frontend code.
- Versioned signed webhook endpoint accepts a documented event envelope.
- PostgreSQL stores immutable event payloads and transactional outbox messages.
- Duplicate source retries are idempotent.
- Health/live/ready endpoints have tested semantics.
- Kafka boundary uses versioned topics, stable keys, and at-least-once assumptions.
- Broker outage cannot lose an event already acknowledged by the API.
- Alembic upgrade/downgrade works against PostgreSQL.
- No plaintext secrets or full sensitive payloads are logged.
- Quality gates and container smoke tests pass.

## Risks and tradeoffs

- **Dual-write reliability:** direct DB + Kafka writes lose consistency; transactional outbox is intentional extra complexity.
- **Event contract drift:** accepting arbitrary JSON without a stable envelope harms consumers; version the envelope and contract-test it.
- **Webhook replay/abuse:** signatures without timestamps, size limits, and rate limits are insufficient.
- **At-least-once delivery:** duplicates are normal; event IDs, unique constraints, and idempotent consumers are mandatory.
- **Readiness policy:** making Kafka mandatory for readiness can remove ingestion capacity during broker outages even though the outbox can buffer; decide deliberately.
- **Unbounded storage:** raw logs grow quickly; retention/partitioning must be selected before production scale.
- **Premature uptime logic:** passive heartbeats and active probes are different products; start with approved scope only.

## Feedback requested

Please approve or revise the eight decision-gate items before implementation. After approval, implementation should begin at Task 1 and proceed in small tested commits.
