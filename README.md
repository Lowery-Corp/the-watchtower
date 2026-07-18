# The Watchtower

Backend for an event-driven logging and uptime monitoring service. The current milestone provides authenticated, versioned event ingestion; immutable PostgreSQL event storage; a transactional outbox; FastAPI operational endpoints; structured request correlation; async SQLAlchemy; and Alembic-managed schema versioning.

## Runtime architecture

```text
source service --HMAC-signed event--> Nginx edge :8010 --> FastAPI :8000
                                      |                    |
                                      | per-IP rate limit  +--> per-service rate limit
                                      |                         |
                                      |                         +--> async SQLAlchemy transaction
                                      |                                |--> immutable PostgreSQL event
                                      |                                +--> Kafka-ready outbox row
                                      +--> 256 KiB edge body cap       Alembic manages schema versions
```

Kafka publishing is deliberately decoupled from the request transaction and remains the next broker-integration milestone.

Compose runs:

- `db`: PostgreSQL 17 with an internal-only port and persistent named volume.
- `migrate`: one-shot `alembic upgrade head` service.
- `api`: internal-only, non-root FastAPI/uvicorn runtime on Compose port `8000`.
- `proxy`: non-root Nginx edge exposed on host port `8010` by default, with a 256 KiB body cap and per-IP webhook rate limiting.
- `test`: profile-gated image containing the test, lint, and type-check tools.

## Prerequisites

- Docker Engine
- Docker Compose v2
- Git over SSH for repository access

All development is performed on `vm-work-dev-db` in `/home/lowery/the-watchtower` on branch `dev`.

## Configuration

Copy `.env.example` to `.env` and replace the development password before shared or persistent use:

```bash
cp .env.example .env
```

The application reads `WATCHTOWER_`-prefixed settings. Never commit `.env`.

`WATCHTOWER_WEBHOOK_SECRETS` is a JSON object mapping registered service slugs to HMAC secrets. Keep the actual value in deployment secret storage; the checked-in example is intentionally empty. PostgreSQL stores only source identity and key-identifier metadata, never the signing secret.

The default signature freshness window is 300 seconds and the default maximum raw webhook body is 262,144 bytes (256 KiB). The application allows 60 successfully authenticated requests per service per 60-second process-local window. Nginx independently limits the webhook path to 60 requests per minute per client IP with a burst of 20; production ingress must preserve an authoritative client address rather than trusting caller-supplied forwarding headers.

## Build and start

```bash
cd /home/lowery/the-watchtower
docker compose config -q
docker compose --profile test build
docker compose up -d db proxy
docker compose ps
```

The migration service must complete successfully before the API starts.

## Operational endpoints

```text
GET http://127.0.0.1:8010/api/v1/health
GET http://127.0.0.1:8010/api/v1/health/live
GET http://127.0.0.1:8010/api/v1/health/ready
GET http://127.0.0.1:8010/api/v1/openapi.json
```

- `health`: basic API status.
- `live`: process liveness; does not require PostgreSQL.
- `ready`: executes `SELECT 1` through an async SQLAlchemy session and returns 503 if PostgreSQL is unavailable.
- Every HTTP response includes `X-Request-ID`. Safe caller-provided IDs are preserved; invalid values are replaced.

## Event ingestion

```text
POST http://127.0.0.1:8010/api/v1/webhooks/events
```

The endpoint requires `X-Watchtower-Service`, `X-Watchtower-Timestamp`, and `X-Watchtower-Signature` headers. A valid event and its `watchtower.events.raw.v1` outbox message commit in one transaction. Retrying the same service/event ID returns `202` with `status: duplicate` and creates no additional rows.

See [`docs/event-contract.md`](docs/event-contract.md) for the exact envelope, signing algorithm, response contract, and sender example.

## Tests and quality gates

Run everything inside the Compose test image:

```bash
docker compose run --rm test pytest -v
docker compose run --rm test ruff check src tests alembic
docker compose run --rm test mypy src tests
```

The integration suite uses real PostgreSQL rather than SQLite.

## Alembic

```bash
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic history
```

Migration downgrades can remove database objects. Obtain explicit authorization and verify backups/scope before running them outside an empty development database.

## Logs and shutdown

```bash
docker compose logs --tail 100 proxy api
docker compose stop proxy api db
```

Do not run `docker compose down -v` unless permanent deletion of the PostgreSQL volume is explicitly intended.

## Development rules

- Work and push only on `dev`; do not push implementation commits directly to `main`.
- Use tests first for behavior changes.
- Keep endpoint modules thin; service/use-case code owns transactions.
- Repositories never commit implicitly.
- Keep credentials, event payloads containing private data, and generated artifacts out of Git.
- Read `AGENTS.md` and the current plan under `.hermes/plans/` before changing architecture.
